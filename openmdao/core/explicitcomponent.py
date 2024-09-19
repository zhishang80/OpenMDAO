"""Define the ExplicitComponent class."""
import inspect

import numpy as np
from types import MethodType


from openmdao.jacobians.dictionary_jacobian import DictionaryJacobian
from openmdao.core.component import Component
from openmdao.vectors.vector import _full_slice
from openmdao.utils.class_util import overrides_method
from openmdao.recorders.recording_iteration_stack import Recording
from openmdao.core.constants import INT_DTYPE, _UNDEFINED
from openmdao.utils.jax_utils import jax, jit, ExplicitCompJaxify, \
    compute_partials as _jax_compute_partials, \
    compute_jacvec_product as _jax_compute_jacvec_product, ReturnChecker
from openmdao.utils.array_utils import submat_sparsity_iter
from openmdao.utils.om_warnings import issue_warning


_tuplist = (tuple, list)


class ExplicitComponent(Component):
    """
    Class to inherit from when all output variables are explicit.

    Parameters
    ----------
    **kwargs : dict of keyword arguments
        Keyword arguments that will be mapped into the Component options.

    Attributes
    ----------
    _has_compute_partials : bool
        If True, the instance overrides compute_partials.
    _vjp_hash : int or None
        Hash value for the last set of inputs to the compute_primal function.
    _vjp_fun : function or None
        The vector-Jacobian product function.
    """

    def __init__(self, **kwargs):
        """
        Store some bound methods so we can detect runtime overrides.
        """
        super().__init__(**kwargs)

        self._has_compute_partials = overrides_method('compute_partials', self, ExplicitComponent)
        self.options.undeclare('assembled_jac_type')
        self._vjp_hash = None
        self._vjp_fun = None

    @property
    def nonlinear_solver(self):
        """
        Get the nonlinear solver for this system.
        """
        return self._nonlinear_solver

    @nonlinear_solver.setter
    def nonlinear_solver(self, solver):
        """
        Raise an exception.
        """
        raise RuntimeError(f"{self.msginfo}: Explicit components don't support nonlinear solvers.")

    @property
    def linear_solver(self):
        """
        Get the linear solver for this system.
        """
        return self._linear_solver

    @linear_solver.setter
    def linear_solver(self, solver):
        """
        Raise an exception.
        """
        raise RuntimeError(f"{self.msginfo}: Explicit components don't support linear solvers.")

    def _configure(self):
        """
        Configure this system to assign children settings and detect if matrix_free.
        """
        if self.matrix_free is _UNDEFINED:
            self.matrix_free = overrides_method('compute_jacvec_product', self, ExplicitComponent)

    def _jac_wrt_iter(self, wrt_matches=None):
        """
        Iterate over (name, start, end, vec, slice, dist_sizes) for each column var in the jacobian.

        Parameters
        ----------
        wrt_matches : set or None
            Only include row vars that are contained in this set.  This will determine what
            the actual offsets are, i.e. the offsets will be into a reduced jacobian
            containing only the matching columns.

        Yields
        ------
        str
            Absolute name of 'wrt' variable.
        int
            Starting index.
        int
            Ending index.
        Vector
            The _inputs vector.
        slice
            A full slice.
        ndarray or None
            Distributed sizes if var is distributed else None
        """
        start = end = 0
        local_ins = self._var_abs2meta['input']
        toidx = self._var_allprocs_abs2idx
        sizes = self._var_sizes['input']
        for wrt, meta in self._var_abs2meta['input'].items():
            if wrt_matches is None or wrt in wrt_matches:
                end += meta['size']
                vec = self._inputs if wrt in local_ins else None
                dist_sizes = sizes[:, toidx[wrt]] if meta['distributed'] else None
                yield wrt, start, end, vec, _full_slice, dist_sizes
                start = end

    def _setup_residuals(self):
        """
        Prevent the user from implementing setup_residuals for explicit components.
        """
        if overrides_method('setup_residuals', self, ExplicitComponent):
            raise RuntimeError(f'{self.msginfo}: Class overrides setup_residuals but '
                               'is an ExplicitComponent. setup_residuals may only be '
                               'overridden by ImplicitComponents.')

    def _setup_partials(self):
        """
        Call setup_partials in components.
        """
        if self.options['derivs_method'] in ('cs', 'fd'):
            self._has_approx = True
            method = self.options['derivs_method']
            if not self._declared_partials_patterns:
                # declare all partials as 'cs' or 'fd'
                self.declare_partials('*', '*', method=method)
                super()._setup_partials()
            else:
                super()._setup_partials()
                # declare only those partials that have been declared
                for of, wrt in self._declared_partials_patterns:
                    self._approx_partials(of, wrt, method=method)
        else:
            super()._setup_partials()

        if self.matrix_free:
            return

        # Note: These declare calls are outside of setup_partials so that users do not have to
        # call the super version of setup_partials. This is still in the final setup.
        for out_abs, meta in self._var_abs2meta['output'].items():

            size = meta['size']
            if size > 0:

                # ExplicitComponent jacobians have -1 on the diagonal.
                arange = np.arange(size, dtype=INT_DTYPE)

                self._subjacs_info[out_abs, out_abs] = {
                    'rows': arange,
                    'cols': arange,
                    'shape': (size, size),
                    'val': np.full(size, -1.),
                    'dependent': True,
                }

    def _setup_jacobians(self, recurse=True):
        """
        Set and populate jacobian.

        Parameters
        ----------
        recurse : bool
            If True, setup jacobians in all descendants. (ignored)
        """
        if self._has_approx and self._use_derivatives:
            self._set_approx_partials_meta()

    def add_output(self, name, val=1.0, shape=None, units=None, res_units=None, desc='',
                   lower=None, upper=None, ref=1.0, ref0=0.0, res_ref=None, tags=None,
                   shape_by_conn=False, copy_shape=None, compute_shape=None, distributed=None):
        """
        Add an output variable to the component.

        For ExplicitComponent, res_ref defaults to the value in res unless otherwise specified.

        Parameters
        ----------
        name : str
            Name of the variable in this component's namespace.
        val : float or list or tuple or ndarray
            The initial value of the variable being added in user-defined units. Default is 1.0.
        shape : int or tuple or list or None
            Shape of this variable, only required if val is not an array.
            Default is None.
        units : str or None
            Units in which the output variables will be provided to the component during execution.
            Default is None, which means it has no units.
        res_units : str or None
            Units in which the residuals of this output will be given to the user when requested.
            Default is None, which means it has no units.
        desc : str
            Description of the variable.
        lower : float or list or tuple or ndarray or None
            Lower bound(s) in user-defined units. It can be (1) a float, (2) an array_like
            consistent with the shape arg (if given), or (3) an array_like matching the shape of
            val, if val is array_like. A value of None means this output has no lower bound.
            Default is None.
        upper : float or list or tuple or ndarray or None
            Upper bound(s) in user-defined units. It can be (1) a float, (2) an array_like
            consistent with the shape arg (if given), or (3) an array_like matching the shape of
            val, if val is array_like. A value of None means this output has no upper bound.
            Default is None.
        ref : float
            Scaling parameter. The value in the user-defined units of this output variable when
            the scaled value is 1. Default is 1.
        ref0 : float
            Scaling parameter. The value in the user-defined units of this output variable when
            the scaled value is 0. Default is 0.
        res_ref : float
            Scaling parameter. The value in the user-defined res_units of this output's residual
            when the scaled value is 1. Default is None, which means residual scaling matches
            output scaling.
        tags : str or list of strs
            User defined tags that can be used to filter what gets listed when calling
            list_inputs and list_outputs and also when listing results from case recorders.
        shape_by_conn : bool
            If True, shape this output to match its connected input(s).
        copy_shape : str or None
            If a str, that str is the name of a variable. Shape this output to match that of
            the named variable.
        compute_shape : function or None
            If a function, that function is called to determine the shape of this output.
        distributed : bool
            If True, this variable is a distributed variable, so it can have different sizes/values
            across MPI processes.

        Returns
        -------
        dict
            Metadata for added variable.
        """
        if res_ref is None:
            res_ref = ref

        return super().add_output(name, val=val, shape=shape, units=units,
                                  res_units=res_units, desc=desc,
                                  lower=lower, upper=upper,
                                  ref=ref, ref0=ref0, res_ref=res_ref,
                                  tags=tags, shape_by_conn=shape_by_conn,
                                  copy_shape=copy_shape, compute_shape=compute_shape,
                                  distributed=distributed)

    def _approx_subjac_keys_iter(self):
        is_output = self._outputs._contains_abs
        for abs_key, meta in self._subjacs_info.items():
            if 'method' in meta and not is_output(abs_key[1]):
                method = meta['method']
                if (method is not None and method in self._approx_schemes):
                    yield abs_key

    def _compute_wrapper(self):
        """
        Call compute based on the value of the "run_root_only" option.
        """
        with self._call_user_function('compute'):
            if self._run_root_only():
                if self.comm.rank == 0:
                    if self._discrete_inputs or self._discrete_outputs:
                        self.compute(self._inputs, self._outputs,
                                     self._discrete_inputs, self._discrete_outputs)
                    else:
                        self.compute(self._inputs, self._outputs)
                    self.comm.bcast([self._outputs.asarray(), self._discrete_outputs], root=0)
                else:
                    new_outs, new_disc_outs = self.comm.bcast(None, root=0)
                    self._outputs.set_val(new_outs)
                    if new_disc_outs:
                        for name, val in new_disc_outs.items():
                            self._discrete_outputs[name] = val
            else:
                if self._discrete_inputs or self._discrete_outputs:
                    self.compute(self._inputs, self._outputs,
                                 self._discrete_inputs, self._discrete_outputs)
                else:
                    self.compute(self._inputs, self._outputs)

    def _apply_nonlinear(self):
        """
        Compute residuals. The model is assumed to be in a scaled state.
        """
        outputs = self._outputs
        residuals = self._residuals
        with self._unscaled_context(outputs=[outputs], residuals=[residuals]):
            residuals.set_vec(outputs)

            # Sign of the residual is minus the sign of the output vector.
            residuals *= -1.0
            self._compute_wrapper()
            residuals += outputs
            outputs -= residuals

        self.iter_count_apply += 1

    def _solve_nonlinear(self):
        """
        Compute outputs. The model is assumed to be in a scaled state.
        """
        with Recording(self.pathname + '._solve_nonlinear', self.iter_count, self):
            with self._unscaled_context(outputs=[self._outputs], residuals=[self._residuals]):
                self._residuals.set_val(0.0)
                self._compute_wrapper()

            # Iteration counter is incremented in the Recording context manager at exit.

    def _compute_jacvec_product_wrapper(self, inputs, d_inputs, d_resids, mode,
                                        discrete_inputs=None):
        """
        Call compute_jacvec_product based on the value of the "run_root_only" option.

        Parameters
        ----------
        inputs : Vector
            Nonlinear input vector.
        d_inputs : Vector
            Linear input vector.
        d_resids : Vector
            Linear residual vector.
        mode : str
            Indicates direction of derivative computation, either 'fwd' or 'rev'.
        discrete_inputs : dict or None
            Mapping of variable name to discrete value.
        """
        if self._run_root_only():
            if self.comm.rank == 0:
                if discrete_inputs:
                    self.compute_jacvec_product(inputs, d_inputs, d_resids, mode, discrete_inputs)
                else:
                    self.compute_jacvec_product(inputs, d_inputs, d_resids, mode)
                if mode == 'fwd':
                    self.comm.bcast(d_resids.asarray(), root=0)
                else:  # rev
                    self.comm.bcast(d_inputs.asarray(), root=0)
            else:
                new_vals = self.comm.bcast(None, root=0)
                if mode == 'fwd':
                    d_resids.set_val(new_vals)
                else:  # rev
                    d_inputs.set_val(new_vals)
        else:
            dochk = mode == 'rev' and self._problem_meta['checking'] and self.comm.size > 1

            if dochk:
                nzdresids = self._get_dist_nz_dresids()

            if discrete_inputs:
                self.compute_jacvec_product(inputs, d_inputs, d_resids, mode, discrete_inputs)
            else:
                self.compute_jacvec_product(inputs, d_inputs, d_resids, mode)

            if dochk:
                self._check_consistent_serial_dinputs(nzdresids)

    def _apply_linear(self, jac, mode, scope_out=None, scope_in=None):
        """
        Compute jac-vec product. The model is assumed to be in a scaled state.

        Parameters
        ----------
        jac : Jacobian or None
            If None, use local jacobian, else use jac.
        mode : str
            'fwd' or 'rev'.
        scope_out : set or None
            Set of absolute output names in the scope of this mat-vec product.
            If None, all are in the scope.
        scope_in : set or None
            Set of absolute input names in the scope of this mat-vec product.
            If None, all are in the scope.
        """
        J = self._jacobian if jac is None else jac

        with self._matvec_context(scope_out, scope_in, mode) as vecs:
            d_inputs, d_outputs, d_residuals = vecs

            if not self.matrix_free:
                # if we're not matrix free, we can skip the rest because
                # compute_jacvec_product does nothing.

                # Jacobian and vectors are all scaled, unitless
                J._apply(self, d_inputs, d_outputs, d_residuals, mode)
                return

            # Jacobian and vectors are all unscaled, dimensional
            with self._unscaled_context(outputs=[self._outputs], residuals=[d_residuals]):

                # set appropriate vectors to read_only to help prevent user error
                if mode == 'fwd':
                    d_inputs.read_only = True
                else:  # rev
                    d_residuals.read_only = True

                try:
                    # handle identity subjacs (output_or_resid wrt itself)
                    if J is None or isinstance(J, DictionaryJacobian):
                        if d_outputs._names:
                            rflat = d_residuals._abs_get_val
                            oflat = d_outputs._abs_get_val
                            subjacs_empty = len(self._subjacs_info) == 0

                            # 'val' in the code below is a reference to the part of the
                            # output or residual array corresponding to the variable 'v'
                            if mode == 'fwd':
                                for v in d_outputs._names:
                                    if subjacs_empty or (v, v) not in self._subjacs_info:
                                        val = rflat(v)
                                        val -= oflat(v)
                            else:  # rev
                                for v in d_outputs._names:
                                    if subjacs_empty or (v, v) not in self._subjacs_info:
                                        val = oflat(v)
                                        val -= rflat(v)

                    # We used to negate the residual here, and then re-negate after the hook
                    with self._call_user_function('compute_jacvec_product'):
                        self._compute_jacvec_product_wrapper(self._inputs, d_inputs, d_residuals,
                                                             mode, self._discrete_inputs)
                finally:
                    d_inputs.read_only = d_residuals.read_only = False

    def _solve_linear(self, mode, scope_out=_UNDEFINED, scope_in=_UNDEFINED):
        """
        Apply inverse jac product. The model is assumed to be in a scaled state.

        Parameters
        ----------
        mode : str
            'fwd' or 'rev'.
        scope_out : set, None, or _UNDEFINED
            Outputs relevant to possible lower level calls to _apply_linear on Components.
        scope_in : set, None, or _UNDEFINED
            Inputs relevant to possible lower level calls to _apply_linear on Components.
        """
        d_outputs = self._doutputs
        d_residuals = self._dresiduals

        if mode == 'fwd':
            if self._has_resid_scaling:
                with self._unscaled_context(outputs=[d_outputs], residuals=[d_residuals]):
                    d_outputs.set_vec(d_residuals)
            else:
                d_outputs.set_vec(d_residuals)

            # ExplicitComponent jacobian defined with -1 on diagonal.
            d_outputs *= -1.0

        else:  # rev
            if self._has_resid_scaling:
                with self._unscaled_context(outputs=[d_outputs], residuals=[d_residuals]):
                    d_residuals.set_vec(d_outputs)
            else:
                d_residuals.set_vec(d_outputs)

            # ExplicitComponent jacobian defined with -1 on diagonal.
            d_residuals *= -1.0

    def _compute_partials_wrapper(self):
        """
        Call compute_partials based on the value of the "run_root_only" option.
        """
        with self._call_user_function('compute_partials'):
            if self._run_root_only():
                if self.comm.rank == 0:
                    if self._discrete_inputs:
                        self.compute_partials(self._inputs, self._jacobian, self._discrete_inputs)
                    else:
                        self.compute_partials(self._inputs, self._jacobian)
                    self.comm.bcast(list(self._jacobian.items()), root=0)
                else:
                    for key, val in self.comm.bcast(None, root=0):
                        self._jacobian[key] = val
            else:
                if self._discrete_inputs:
                    self.compute_partials(self._inputs, self._jacobian, self._discrete_inputs)
                else:
                    self.compute_partials(self._inputs, self._jacobian)

    def _linearize(self, jac=None, sub_do_ln=False):
        """
        Compute jacobian / factorization. The model is assumed to be in a scaled state.

        Parameters
        ----------
        jac : Jacobian or None
            Ignored.
        sub_do_ln : bool
            Flag indicating if the children should call linearize on their linear solvers.
        """
        if self.matrix_free or not (self._has_compute_partials or self._approx_schemes):
            return

        self._check_first_linearize()

        with self._unscaled_context(outputs=[self._outputs], residuals=[self._residuals]):
            # Computing the approximation before the call to compute_partials allows users to
            # override FD'd values.
            for approximation in self._approx_schemes.values():
                approximation.compute_approximations(self, jac=self._jacobian)

            if self._has_compute_partials:
                # We used to negate the jacobian here, and then re-negate after the hook.
                self._compute_partials_wrapper()

    def compute(self, inputs, outputs, discrete_inputs=None, discrete_outputs=None):
        """
        Compute outputs given inputs. The model is assumed to be in an unscaled state.

        An inherited component may choose to either override this function or to define a
        compute_primal function.

        Parameters
        ----------
        inputs : Vector
            Unscaled, dimensional input variables read via inputs[key].
        outputs : Vector
            Unscaled, dimensional output variables read via outputs[key].
        discrete_inputs : dict like or None
            If not None, dict like object containing discrete input values.
        discrete_outputs : dict like or None
            If not None, dict like object containing discrete output values.
        """
        global _tuplist

        if self.compute_primal is None:
            return

        returns = \
            self.compute_primal(*self._get_compute_primal_invals(inputs, discrete_inputs))

        if not isinstance(returns, _tuplist):
            returns = (returns,)

        if not discrete_outputs:
            outputs.set_vals(returns)
        else:
            outputs.set_vals(returns[:outputs.nvars()])
            self._discrete_outputs.set_vals(returns[outputs.nvars():])

    def compute_partials(self, inputs, partials, discrete_inputs=None):
        """
        Compute sub-jacobian parts. The model is assumed to be in an unscaled state.

        Parameters
        ----------
        inputs : Vector
            Unscaled, dimensional input variables read via inputs[key].
        partials : Jacobian
            Sub-jac components written to partials[output_name, input_name]..
        discrete_inputs : dict or None
            If not None, dict containing discrete input values.
        """
        pass

    def compute_jacvec_product(self, inputs, d_inputs, d_outputs, mode, discrete_inputs=None):
        r"""
        Compute jac-vector product. The model is assumed to be in an unscaled state.

        If mode is:
            'fwd': d_inputs \|-> d_outputs

            'rev': d_outputs \|-> d_inputs

        Parameters
        ----------
        inputs : Vector
            Unscaled, dimensional input variables read via inputs[key].
        d_inputs : Vector
            See inputs; product must be computed only if var_name in d_inputs.
        d_outputs : Vector
            See outputs; product must be computed only if var_name in d_outputs.
        mode : str
            Either 'fwd' or 'rev'.
        discrete_inputs : dict or None
            If not None, dict containing discrete input values.
        """
        pass

    def is_explicit(self):
        """
        Return True if this is an explicit component.

        Returns
        -------
        bool
            True if this is an explicit component.
        """
        return True

    def _get_compute_primal_invals(self, inputs, discrete_inputs):
        yield from inputs.values()
        if discrete_inputs:
            yield from discrete_inputs.values()

    def _get_compute_primal_argnames(self):
        argnames = []
        argnames.extend(self._var_rel_names['input'])
        if self._discrete_inputs:
            argnames.extend(self._discrete_inputs)
        return argnames

    def _setup_jax(self, from_group=False):
        if self.matrix_free is True:
            self.compute_jacvec_product = MethodType(_jax_compute_jacvec_product, self)
        else:
            self.compute_partials = MethodType(_jax_compute_partials, self)
            self._has_compute_partials = True

        if self.compute_primal is None:
            # convert the compute method to a compute_primal method
            jaxifier = ExplicitCompJaxify(self, verbose=True)

            if jaxifier.get_self_statics:
                self.get_self_statics = MethodType(jaxifier.get_self_statics, self)
            # replace existing compute method with base class method, so that compute_primal
            # will be called.
            self.compute = MethodType(ExplicitComponent.compute, self)

            self.compute_primal = MethodType(jaxifier.compute_primal, self)
            self._compute_primal_returns_tuple = True
        else:
            # check that compute_primal args are in the correct order
            args = list(inspect.signature(self.compute_primal).parameters)
            if args and args[0] == 'self':
                args = args[1:]
            compargs = self._get_compute_primal_argnames()
            if args != compargs:
                raise RuntimeError(f"{self.msginfo}: compute_primal method args {args} don't match "
                                   f"the expected args {compargs}.")

            # determine if the compute_primal method returns a tuple
            self._compute_primal_returns_tuple = ReturnChecker(self.compute_primal).returns_tuple()

        if not from_group and self.options['use_jit']:
            static_argnums = []
            idx = len(self._var_rel_names['input']) + 1
            static_argnums.extend(range(idx, idx + len(self._discrete_inputs)))
            self.compute_primal = MethodType(jit(self.compute_primal.__func__,
                                                 static_argnums=static_argnums), self)

    def _get_jac_func(self):
        # TODO: modify this to use relevance and possibly compile multiple jac functions depending
        # on DV/response so that we don't compute any derivatives that are always zero.
        if self._jac_func_ is None:
            fjax = jax.jacfwd if self.best_partial_deriv_direction() == 'fwd' else jax.jacrev
            nstatic = len(self._discrete_inputs)
            wrt_idxs = list(range(1, len(self._var_abs2meta['input']) + 1))
            self._jac_func_ = MethodType(fjax(self.compute_primal.__func__, argnums=wrt_idxs), self)

            if self.options['use_jit']:
                static_argnums = tuple(range(1 + len(wrt_idxs), 1 + len(wrt_idxs) + nstatic))
                self._jac_func_ = MethodType(jit(self._jac_func_.__func__,
                                                 static_argnums=static_argnums),
                                             self)

        return self._jac_func_

    def get_compute_sparsity(self):
        """
        Return sparsity pattern of the compute function.

        The compute function is executed once for each entry in the inputs array.  It's possible
        that the returned sparsity pattern could be more conservative than the actual
        jacobian sparsity pattern.

        Returns
        -------
        tuple
            Tuple of (rows, cols) where rows and cols are index arrays indicating nonzero locations
            in the jacobian.
        """
        inarr = self._inputs.asarray()
        outarr = self._outputs.asarray()
        outsave = outarr.copy()

        rows = []
        cols = []

        for i in range(len(inarr)):
            old = inarr[i]
            inarr[i] = np.nan
            if self._discrete_inputs or self._discrete_outputs:
                self.compute(self._inputs, self._outputs, self._discrete_inputs,
                             self._discrete_outputs)
            else:
                self.compute(self._inputs, self._outputs)
            irows = np.where(np.isnan(outarr))[0]
            rows.append(irows)
            cols.append(np.full(irows.size, i))
            inarr[i] = old

        if rows:
            rows = np.concatenate(rows)
            cols = np.concatenate(cols)
        else:
            rows = np.zeros(0, dtype=INT_DTYPE)
            cols = np.zeros(0, dtype=INT_DTYPE)

        # restore old output values
        self._outputs.set_val(outsave)

        return rows, cols

    def _check_subjac_sparsity(self):
        """
        Check the declared sparsity of the sub-jacobians vs. the computed sparsity.
        """
        full_nzrows, full_nzcols = self.get_compute_sparsity()

        def row_size_iter():
            for of, start, end, _, _ in self._jac_of_iter():
                yield of, end - start

        def col_size_iter():
            for wrt, start, end, _, _, _ in self._jac_wrt_iter():
                yield wrt, end - start

        prefix_len = len(self.pathname) + 1
        for of, wrt, sjrows, sjcols, _ in submat_sparsity_iter(row_size_iter(), col_size_iter(),
                                                               full_nzrows, full_nzcols,
                                                               (len(self._outputs),
                                                                len(self._inputs))):
            if (of, wrt) in self._subjacs_info:
                meta = self._subjacs_info[of, wrt]
                if meta['rows'] is None and sjrows is not None:
                    issue_warning(f"Sparsity pattern for {of} wrt {wrt} was declared with "
                                  "rows=None, but a sparsity pattern has been computed.\n"
                                  f"rows = {sjrows}\ncols = {sjcols}\n")
                elif not np.all(np.asarray(meta['rows']) == sjrows):
                    issue_warning(f"Sparsity pattern for {of} wrt {wrt} was declared with "
                                  f"rows={meta['rows']} and col={meta['cols']}, but a different "
                                  "sparsity pattern has been computed:\n"
                                  f"rows = {sjrows}\ncols = {sjcols}\n"
                                  f"Note: The sparsity pattern is computed based on the compute "
                                  "function, and may be more conservative than the true pattern.\n")
            else:
                issue_warning(f"{self.msginfo}: Partial for {of[prefix_len:]} wrt "
                              f"{wrt[prefix_len:]} was not declared but is nonzero.\n"
                              f"rows = {sjrows}\ncols = {sjcols}\n")
