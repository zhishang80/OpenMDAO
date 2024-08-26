
import unittest

from openmdao.api import Problem, Group, IndepVarComp, ExecComp, \
    LinearBlockGS, NonlinearBlockGS, DirectSolver
from openmdao.utils.logger_utils import TestLogger
from openmdao.test_suite.components.sellar import StateConnection


class StateConnWithSolveNonlinear(StateConnection):
    def solve_nonlinear(self, inputs, outputs):
        pass


class StateConnWithSolveLinear(StateConnection):
    def solve_linear(self, inputs, outputs):
        pass


class StateConnWithSolves(StateConnection):
    def solve_linear(self, inputs, outputs):
        pass

    def solve_nonlinear(self, inputs, outputs):
        pass


class TestCheckSolvers(unittest.TestCase):

    def test_implicit(self):
        prob = Problem()
        model = prob.model

        model.add_subsystem('indep', IndepVarComp('y', 1.0))
        model.add_subsystem('statecomp', StateConnection())

        model.connect('indep.y', 'statecomp.y2_actual')

        # perform setup with checks but don't run model
        testlogger = TestLogger()
        prob.setup(check=True, logger=testlogger)
        prob.final_setup()

        # should trigger warnings due to having states without solves

        self.assertTrue(testlogger.contains('error',
                        "StateConnection 'statecomp' contains implicit variables but does not implement solve_nonlinear "
                        "or solve_linear or have an iterative nonlinear or linear solver."))

    def test_implicit_without_solve_linear(self):
        prob = Problem()
        model = prob.model

        model.add_subsystem('indep', IndepVarComp('y', 1.0))
        model.add_subsystem('statecomp', StateConnWithSolveNonlinear())

        model.connect('indep.y', 'statecomp.y2_actual')

        # perform setup with checks but don't run model
        testlogger = TestLogger()
        prob.setup(check=True, logger=testlogger)
        prob.final_setup()

        # should trigger solver warning because there is no linear solve
        self.assertTrue(testlogger.contains('error',
                        "StateConnWithSolveNonlinear 'statecomp' contains implicit variables but does not implement solve_linear or have an iterative linear solver."))

    def test_implicit_without_solve_nonlinear(self):
        prob = Problem()
        model = prob.model

        model.add_subsystem('indep', IndepVarComp('y', 1.0))
        model.add_subsystem('statecomp', StateConnWithSolveLinear())

        model.connect('indep.y', 'statecomp.y2_actual')

        # perform setup with checks but don't run model
        testlogger = TestLogger()
        prob.setup(check=True, logger=testlogger)
        prob.final_setup()

        # should trigger solver warning because there is no nonlinear solve
        self.assertTrue(testlogger.contains('error',
                        "StateConnWithSolveLinear 'statecomp' contains implicit variables but does not implement solve_nonlinear or have an iterative nonlinear solver."))

    def test_implicit_with_solves(self):
        prob = Problem()
        model = prob.model

        model.add_subsystem('indep', IndepVarComp('y', 1.0))
        model.add_subsystem('statecomp', StateConnWithSolves())

        model.connect('indep.y', 'statecomp.y2_actual')

        # perform setup with checks but don't run model
        testlogger = TestLogger()
        prob.setup(check=True, logger=testlogger)
        prob.final_setup()

        # should not trigger any solver warnings because solve methods are implemented
        # but there is a warning about the lack of recorder
        warnings = testlogger.get('warning')
        self.assertEqual(len(warnings), 1)

    def test_implicit_iter(self):
        prob = Problem()
        model = prob.model

        model.add_subsystem('indep', IndepVarComp('y', 1.0))
        model.add_subsystem('statecomp', StateConnection())

        model.connect('indep.y', 'statecomp.y2_actual')

        # provide iterative solvers for implicit group
        model.linear_solver = LinearBlockGS()
        model.nonlinear_solver = NonlinearBlockGS()

        # perform setup with checks but don't run model
        testlogger = TestLogger()
        prob.setup(check=True, logger=testlogger)
        prob.final_setup()

        # should not trigger any solver warnings
        # other than lack of recorder warning
        warnings = testlogger.get('warning')
        self.assertEqual(len(warnings), 1)

    def test_implicit_iter_subgroup(self):
        prob = Problem()
        model = prob.model

        model.add_subsystem('indep', IndepVarComp('y', 1.0))

        model.add_subsystem("G1", Group())
        model.G1.add_subsystem('statecomp', StateConnection(),
                               promotes_inputs=['y2_actual'])

        model.connect('indep.y', 'G1.y2_actual')

        # provide iterative solvers for implicit group
        model.linear_solver = LinearBlockGS()
        model.nonlinear_solver = NonlinearBlockGS()

        # perform setup with checks but don't run model
        testlogger = TestLogger()
        prob.setup(check=True, logger=testlogger)
        prob.final_setup()

        # should not trigger solver warning because iterates in parent group
        # but will have recorder warning
        warnings = testlogger.get('warning')
        self.assertEqual(len(warnings), 1)

    def test_implicit_iter_subgroups(self):
        prob = Problem()
        model = prob.model

        model.add_subsystem('indep', IndepVarComp('y', 1.0))

        model.add_subsystem("G1", Group())
        model.G1.add_subsystem('statecomp1', StateConnection(),
                               promotes_inputs=['y2_actual'])

        model.add_subsystem("G2", Group())
        model.G2.add_subsystem('statecomp2', StateConnection(),
                               promotes_inputs=['y2_actual'])

        model.connect('indep.y', ['G1.y2_actual', 'G2.y2_actual'])

        # do not provide iterative linear solver for G2
        model.nonlinear_solver = NonlinearBlockGS()
        model.G1.linear_solver = LinearBlockGS()

        # perform setup with checks but don't run model
        testlogger = TestLogger()
        prob.setup(check=True, logger=testlogger)
        prob.final_setup()

        # should trigger a linear solver warning only for group 2
        self.assertTrue(testlogger.contains('error',
                        "StateConnection 'G2.statecomp2' contains implicit variables but does not implement solve_linear or have an iterative linear solver."))

    def test_cycle(self):
        prob = Problem()
        model = prob.model

        model.add_subsystem("C1", ExecComp('y=2.0*x'))
        model.add_subsystem("C2", ExecComp('y=2.0*x'))
        model.add_subsystem("C3", ExecComp('y=2.0*x'))

        model.connect('C1.y','C2.x')
        model.connect('C2.y','C3.x')
        model.connect('C3.y','C1.x')

        # perform setup with checks but don't run model
        testlogger = TestLogger()
        prob.setup(check=True, logger=testlogger)
        prob.final_setup()

        # should trigger warnings because cycle requires iterative solvers
        self.assertTrue(testlogger.contains('error',
                        "Group '' contains cycles [('C1', 'C2', 'C3')], but does not have an iterative nonlinear or linear solver."))

    def test_cycle_iter(self):
        prob = Problem()
        model = prob.model

        model.add_subsystem("C1", ExecComp('y=2.0*x'))
        model.add_subsystem("C2", ExecComp('y=2.0*x'))
        model.add_subsystem("C3", ExecComp('y=2.0*x'))

        model.connect('C1.y','C2.x')
        model.connect('C2.y','C3.x')
        model.connect('C3.y','C1.x')

        # provide iterative solvers to handle cycle
        model.linear_solver = LinearBlockGS()
        model.nonlinear_solver = NonlinearBlockGS()

        # perform setup with checks but don't run model
        testlogger = TestLogger()
        prob.setup(check=True, logger=testlogger)
        prob.final_setup()

        # should not trigger any solver warnings
        warnings = testlogger.get('warning')
        # but one warning exists due to problem not having a recorder
        self.assertEqual(len(warnings), 1)

    def test_cycle_direct(self):
        prob = Problem()
        model = prob.model

        model.add_subsystem("C1", ExecComp('y=2.0*x'))
        model.add_subsystem("C2", ExecComp('y=2.0*x'))
        model.add_subsystem("C3", ExecComp('y=2.0*x'))

        model.connect('C1.y','C2.x')
        model.connect('C2.y','C3.x')
        model.connect('C3.y','C1.x')

        # provide direct linear solver and iterative nonlinear solver
        model.linear_solver = DirectSolver()
        model.nonlinear_solver = NonlinearBlockGS()

        # perform setup with checks but don't run model
        testlogger = TestLogger()
        prob.setup(check=True, logger=testlogger)
        prob.final_setup()

        # should not trigger any solver warnings
        warnings = testlogger.get('warning')
        # but one warning exists due to problem not having a recorder
        self.assertEqual(len(warnings), 1)

    def test_cycle_iter_subgroup(self):
        prob = Problem()
        model = prob.model

        G1 = model.add_subsystem("G1", Group())
        G1.add_subsystem("C1", ExecComp('y=2.0*x'))
        G1.add_subsystem("C2", ExecComp('y=2.0*x'))
        G1.add_subsystem("C3", ExecComp('y=2.0*x'))

        G1.connect('C1.y','C2.x')
        G1.connect('C2.y','C3.x')
        G1.connect('C3.y','C1.x')

        # provide iterative solvers to handle cycle
        model.linear_solver = LinearBlockGS()
        model.nonlinear_solver = NonlinearBlockGS()

        # perform setup with checks but don't run model
        testlogger = TestLogger()
        prob.setup(check=True, logger=testlogger)
        prob.final_setup()

        # should not trigger solver warning because iterates in parent group
        # but one warning exists due to problem not having a recorder
        warnings = testlogger.get('warning')
        self.assertEqual(len(warnings), 1)

    def test_subcycle_warning(self):
        p = Problem()
        model = p.model
        model.add_subsystem('C1', ExecComp('y=2.0*x'))
        model.add_subsystem('C2', ExecComp('y=2.0*x'))
        model.add_subsystem('C3', ExecComp('y=2.0*x'))
        model.add_subsystem('C4', ExecComp('y=2.0*x'))
        model.add_subsystem('C5', ExecComp('y=2.0*x'))

        model.connect('C1.y', 'C2.x')
        model.connect('C2.y', 'C3.x')
        model.connect('C3.y', 'C1.x')

        model.connect('C3.y', 'C4.x')
        model.connect('C4.y', 'C5.x')

        testlogger = TestLogger()
        p.setup(check=['solvers'], logger=testlogger)
        p.final_setup()

        self.assertTrue(testlogger.contains('warning',
                                            "The following groups contain sub-cycles. Performance and/or convergence may improve"
                                            "\nif these sub-cycles are solved separately in their own group.\n\n"
                                            "'' (Group)  NL: NonlinearRunOnce (maxiter=1), LN: LinearRunOnce (maxiter=1):\n"
                                            "   Cycle 0: ['C1', 'C2', 'C3']\n   Number of non-cycle subsystems: 2\n"))




if __name__ == "__main__":
    unittest.main()
