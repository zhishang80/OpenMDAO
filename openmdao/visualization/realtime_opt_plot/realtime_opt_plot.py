""" A real-plot of the optimization process"""

from bokeh.models import ColumnDataSource, Legend, LegendItem, LinearAxis, Range1d, Toggle, Column, Row, CustomJS, Div
from bokeh.plotting import curdoc, figure
from bokeh.server.server import Server
from tornado.ioloop import IOLoop
from bokeh.palettes import Category10, Category20, d3, Viridis256, Category20b, Category20c
from bokeh.layouts import row, column, Spacer

import numpy as np


from openmdao.recorders.sqlite_reader import SqliteCaseReader

try:
    from openmdao.utils.gui_testing_utils import get_free_port
except:
    # If get_free_port is unavailable, the default port will be used
    def get_free_port():
        return 5000

def _realtime_opt_plot_setup_parser(parser):
    """
    Set up the realtime plot subparser for the 'openmdao realtime_opt_plot' command.

    Parameters
    ----------
    parser : argparse subparser
        The parser we're adding options to.
    """
    parser.add_argument(
        "case_recorder_filename",
        type=str,
        help="Name of openmdao case recorder filename. It should contain driver cases",
    )

def _realtime_opt_plot_cmd(options, user_args):
    """
    Run the realtime_opt_plot command.

    Parameters
    ----------
    options : argparse Namespace
        Command line options.
    user_args : list of str
        Args to be passed to the user script.
    """

    realtime_opt_plot(
        options.case_recorder_filename,
    )


def _make_legend_item(varname, color):
    toggle = Toggle(
    label=varname,
    active=False,
    # width=120,
    height=20,
    margin=(0, 0, 2, 0)
    )
    
    # Add custom CSS styles for both active and inactive states
    toggle.stylesheets = [
        f"""
            .bk-btn {{
                color: {color};
                border-color: {color};
                background-color: white;
                font-size: 12pt;
                display: flex;
                align-items: center; /* Vertical centering */
                justify-content: center; /* Horizontal centering */
                height: 12px; /* Example height, adjust as needed */
                border-width: 0px; /* Adjust to desired thickness */
                border-style: solid; /* Ensures a solid border */
            }}

            .bk-btn.bk-active {{
                color: white;
                border-color: {color};
                background-color: {color};
                font-size: 12pt;
                display: flex;
                align-items: center; /* Vertical centering */
                justify-content: center; /* Horizontal centering */
                height: 12px; /* Example height, adjust as needed */
                border-width: 0px; /* Adjust to desired thickness */
                border-style: solid; /* Ensures a solid border */
            }}

            .bk-btn:focus {{
                outline: none; /* Removes the default focus ring */
            }}
        """
    ]
    


    return toggle
    


class CaseTracker:
    def __init__(self, case_recorder_filename):
        self._case_ids_read = []
        self._case_recorder_filename = case_recorder_filename
        # self._cr = SqliteCaseReader(case_recorder_filename)
        self.source = None
        
        self._initial_cr_with_one_case = None

    def get_new_cases(self):
        # need to read this each time since the constructor does all of the actual reading
        # TODO - add code SqliteCaseReader for reading real-time data
        # cr = SqliteCaseReader("create_cr_files_out/driver_history.db")
        self._cr = SqliteCaseReader(self._case_recorder_filename)
        case_ids = self._cr.list_cases("driver", out_stream=None)
        new_case_ids = [
            case_id for case_id in case_ids if case_id not in set(self._case_ids_read)
        ]
        if new_case_ids:
            # just get the first one
            case_id = new_case_ids[0]
            driver_case = self._cr.get_case(case_id)
            objs = driver_case.get_objectives(scaled=False)
            design_vars = driver_case.get_design_vars(scaled=False)
            constraints = driver_case.get_constraints(scaled=False)
            
            new_data = {
                "counter": int(driver_case.counter),
            }

            # get objectives
            objectives = {}
            for name, value in objs.items():
                objectives[name] = value
                
            new_data["objs"] = objectives

            # get des vars
            desvars = {}
            for name, value in design_vars.items():
                desvars[name] = value
            new_data["desvars"] = desvars

            # get cons
            cons = {}
            for name, value in constraints.items():
                cons[name] = value
                    
            new_data["cons"] = cons

            self._case_ids_read.append(case_id)  # remember that this one has been plotted

            return new_data
        return None

    def get_obj_names(self):
        if self._initial_cr_with_one_case is None:
            cr = SqliteCaseReader(self._case_recorder_filename)
            case_ids = cr.list_cases("driver", out_stream=None)
            if len(case_ids) > 0:
                self._initial_cr_with_one_case = cr
            else:
                return None
        case_ids = self._initial_cr_with_one_case.list_cases("driver", out_stream=None)
        driver_case = self._initial_cr_with_one_case.get_case(case_ids[0])
        obj_vars = driver_case.get_objectives()
        return obj_vars.keys()

    def get_desvar_names(self):
        if self._initial_cr_with_one_case is None:
            cr = SqliteCaseReader(self._case_recorder_filename)
            case_ids = cr.list_cases("driver", out_stream=None)
            if len(case_ids) > 0:
                self._initial_cr_with_one_case = cr
            else:
                return None
        case_ids = self._initial_cr_with_one_case.list_cases("driver", out_stream=None)
        driver_case = self._initial_cr_with_one_case.get_case(case_ids[0])
        design_vars = driver_case.get_design_vars()
        return design_vars.keys()

    def get_cons_names(self):
        if self._initial_cr_with_one_case is None:
            cr = SqliteCaseReader(self._case_recorder_filename)
            case_ids = cr.list_cases("driver", out_stream=None)
            if len(case_ids) > 0:
                self._initial_cr_with_one_case = cr
            else:
                return None
        case_ids = self._initial_cr_with_one_case.list_cases("driver", out_stream=None)
        driver_case = self._initial_cr_with_one_case.get_case(case_ids[0])
        cons = driver_case.get_constraints()
        return cons.keys()

    def get_obj_names(self):
        if self._initial_cr_with_one_case is None:
            cr = SqliteCaseReader(self._case_recorder_filename)
            case_ids = cr.list_cases("driver", out_stream=None)
            if len(case_ids) > 0:
                self._initial_cr_with_one_case = cr
            else:
                return None
        case_ids = self._initial_cr_with_one_case.list_cases("driver", out_stream=None)
        driver_case = self._initial_cr_with_one_case.get_case(case_ids[0])
        obj_vars = driver_case.get_objectives()
        return obj_vars.keys()
    
    def get_units(self, name):
        if self._initial_cr_with_one_case is None:
            cr = SqliteCaseReader(self._case_recorder_filename)
            case_ids = cr.list_cases("driver", out_stream=None)
            if len(case_ids) > 0:
                self._initial_cr_with_one_case = cr
            else:
                return None
        case_ids = self._initial_cr_with_one_case.list_cases("driver", out_stream=None)
        driver_case = self._initial_cr_with_one_case.get_case(case_ids[0])
        try:
            units = driver_case._get_units(name)
        except RuntimeError as err:
            if str(err).startswith("Can't get units for the promoted name"):
                return "Ambiguous"
            raise
        except KeyError as err:
            return "Unavailable"
            
        return units


class RealTimeOptPlot(object):
    def __init__(self, case_recorder_filename, doc):
        
        print("RealTimeOptPlot.__init__")
        
        self._source = None

        case_tracker = CaseTracker(case_recorder_filename)
       
       
        from bokeh.models.tools import BoxZoomTool, ResetTool, HoverTool, PanTool, WheelZoomTool, SaveTool, ZoomInTool, ZoomOutTool

        # Make the figure and all the settings for it
        p = figure(
            tools=[ PanTool(dimensions="width"), WheelZoomTool(), ZoomInTool(), 
                   ZoomOutTool(), BoxZoomTool(), ResetTool(), SaveTool() ],
                   width_policy="max" , height_policy="max",
                   sizing_mode="stretch_both",
                   title=f"Real-time Optimization Progress Plot for: {case_recorder_filename}",
                   active_drag=None,
                   active_scroll="auto",
                   active_tap=None,
                #    active_inspect=None,
                   output_backend="webgl",
        )
       
        # uncomment these for debugging Bokeh
        # from bokeh.models.tools import
        # p.add_tools( ExamineTool())
        
        # Add an invisible line renderer. To avoid this warning message
        #     (MISSING_RENDERERS): Plot has no renderers
        p.line([], [], line_alpha=0)

        p.x_range.follow = "start"
        p.title.text_font_size = '25px'
        p.title.text_color = "black"
        p.title.text_font = "arial"
        p.title.align = "center"
        p.title.standoff = 40  # Adds 40 pixels of space below the title

        p.title.background_fill_color = "#eeeeee"
        p.xaxis.axis_label = "Driver iterations"
        p.xaxis.minor_tick_line_color = None
        p.axis.axis_label_text_font_style = 'bold'
        p.axis.axis_label_text_font_size = '20pt'
        p.xgrid.band_hatch_pattern = "/"
        p.xgrid.band_hatch_alpha = 0.6
        p.xgrid.band_hatch_color = "lightgrey"
        p.xgrid.band_hatch_weight = 0.5
        p.xgrid.band_hatch_scale = 10
        
        from collections import defaultdict
        self.y_min = defaultdict(lambda: float("inf"))  # update this as new data comes in
        self.y_max = defaultdict(lambda: float("-inf"))  # update this as new data comes in
        
        

        def update():
            # See if source is defined yet. If not, see if we have any data
            #   in the case file yet. If there is data, create the
            #   source object and add the lines to the figure

            new_data = None
            
            if self._source is None:
                new_data = case_tracker.get_new_cases()
                if new_data:
                    
                    ####  make the source dict
                    source_dict = { 'iteration': []}
                    
                    # Obj
                    obj_names = case_tracker.get_obj_names()
                    for obj_name in obj_names:
                        source_dict[obj_name] = []
                        
                    # Desvars
                    desvar_names = case_tracker.get_desvar_names()
                    for desvar_name in desvar_names:
                        source_dict[desvar_name] = []
                        
                    # Cons
                    con_names = case_tracker.get_cons_names()
                    for con_name in con_names:
                        source_dict[con_name] = []
                        
                    self._source = ColumnDataSource(source_dict)

                    #### make the lines and legends
                    palette = Category20[20] + Category20b[20] + Category20c[20]
                    i_color = 0  # index of line across all variables: obj, desvars, cons
                    legend_items = []

                    toggles = []
                    column_items = []
                    lines = []
                    axes = []

                    # Objective
                    legend_items.append(LegendItem(label="OBJECTIVE"))  # the only way to make a header in Legends
                    obj_names = case_tracker.get_obj_names()

                    obj_label = Div(text="<b>OBJECTIVE</b>", width=200,
                        styles={"font-size": "12"},  # Set font size using CSS

                    )  # Fixed-width text label

                    column_items.append(obj_label)

                    if len(obj_names) != 1:
                        raise ValueError(f"Plot assumes there is on objective but {len(obj_names)} found")
                    for i, obj_name in enumerate(obj_names):
                        units = case_tracker.get_units(obj_name)

                        color = "black"
                        toggle = _make_legend_item(f"{obj_name} ({units})", color)
                        toggle.active = True
                        toggles.append(toggle)

                        column_items.append(toggle)
                        
                        obj_line = p.line(x="iteration", y=obj_name, line_width=3, source=self._source,
                                          color="black")  # make the objective black
                        p.yaxis.axis_label = f"Objective: {obj_name} ({units})"

                        lines.append(obj_line)
                        
                        
                        legend_items.append(LegendItem(label=f"{obj_name} ({units})", renderers=[obj_line]))
                        
                        hover = HoverTool(renderers=[obj_line], 
                            tooltips=[('Iteration', '@iteration'), 
                             (obj_name, '@{%s}' % obj_name + '{0.00}')],
                            mode='vline', visible=False)

                        # Add the hover tools to the plot
                        p.add_tools(hover)

                    # desvars
                    legend_items.append(LegendItem(label="DESIGN VARS"))  # the only way to make a header in Legends
                    
                    desvars_label = Div(text="<b>DESIGN VARS</b>", width=200,
                        styles={"font-size": "12"},  # Set font size using CSS

                    )  # Fixed-width text label

                    column_items.append(desvars_label)

                    desvar_names = case_tracker.get_desvar_names()
                    for i, desvar_name in enumerate(desvar_names):
                        color = palette[i_color % 60]
                        units = case_tracker.get_units(desvar_name)
                        
                        toggle = _make_legend_item(f"{desvar_name} ({units})", color)
                        toggles.append(toggle)
                        column_items.append(toggle)

                        desvar_line = p.line(x="iteration", y=desvar_name, line_width=3, 
                                y_range_name=f"extra_y_{desvar_name}",
                                source=self._source,color=color, visible=False)
                        desvar_line.visible = False

                        lines.append(desvar_line)

                        hover = HoverTool(renderers=[desvar_line], 
                            tooltips=[('Iteration', '@iteration'), 
                             (desvar_name, '@{%s}' % desvar_name + '{0.00}')],
                            mode='vline', visible=False)

                        # Add the hover tools to the plot
                        p.add_tools(hover)

                        legend_items.append(LegendItem(label=f"{desvar_name} ({units})", renderers=[desvar_line]))
                        extra_y_axis = LinearAxis(y_range_name=f"extra_y_{desvar_name}",
                                                axis_label=f"{desvar_name} ({units})",
                                                axis_label_text_color=color,
                                                axis_label_text_font_size = '20px'
                        )

                        axes.append(extra_y_axis)

                        p.add_layout(extra_y_axis, 'right')
                        p.right[i_color-1].visible = False

                        
                        # set the range
                        y_min = -20
                        y_max = -20
                        # if the range is zero, the axis will not be displayed. Plus need some range to make it
                        #    look good. Some other code seems to do +- 1 for the range in this case.
                        if y_min == y_max:
                            y_min = y_min - 1
                            y_max = y_max + 1
                        p.extra_y_ranges[f"extra_y_{desvar_name}"] = Range1d(
                            y_min, y_max)

                        # p.add_layout(extra_y_axis, 'right')
                        i_color += 1

                    # cons
                    legend_items.append(LegendItem(label="CONSTRAINTS"))  # the only way to make a header in Legends
                    cons_label = Div(text="<b>CONSTRAINTS</b>", width=200,
                        styles={"font-size": "12"},  # Set font size using CSS

                    )  # Fixed-width text label

                    column_items.append(cons_label)
                    
                    cons_names = case_tracker.get_cons_names()
                    for i, cons_name in enumerate(cons_names):
                        color = palette[i_color % 60]

                        units = case_tracker.get_units(cons_name)

                        toggle = _make_legend_item(f"{cons_name} ({units})", color)
                        toggles.append(toggle)
                        column_items.append(toggle)

                        cons_line = p.line(x="iteration", y=cons_name, line_width=3, line_dash="dashed",
                            y_range_name=f"extra_y_{cons_name}",
                            source=self._source,color=color, visible=False)

                        lines.append(cons_line)

                        hover = HoverTool(renderers=[cons_line], 
                            tooltips=[('Iteration', '@iteration'), 
                             (cons_name, '@{%s}' % cons_name + '{0.00}') ],
                            mode='vline', visible=False)

                        # Add the hover tools to the plot
                        p.add_tools(hover)

                        extra_y_axis = LinearAxis(y_range_name=f"extra_y_{cons_name}",
                                                axis_label=f"{cons_name} ({units})",
                                                axis_label_text_color=color,
                                                axis_label_text_font_size = '20px'
)

                        axes.append(extra_y_axis)
                        p.add_layout(extra_y_axis, 'right')
                        p.right[i_color-1].visible = False
                        
                        # set the range
                        y_min = -100
                        y_max = 100
                        # if the range is zero, the axis will not be displayed. Plus need some range to make it
                        #    look good. Some other code seems to do +- 1 for the range in this case.
                        if y_min == y_max:
                            y_min = y_min - 1
                            y_max = y_max + 1
                        p.extra_y_ranges[f"extra_y_{cons_name}"] = Range1d(
                            y_min, y_max)

                        i_color += 1


                    legend = Legend(items=legend_items, title="Variables")
                    
                    # Create CustomJS callback for toggle buttons
                    callback = CustomJS(args=dict(lines=lines, axes=axes, toggles=toggles), code="""
                        // Get the toggle that triggered the callback
                        const toggle = cb_obj;
                        const index = toggles.indexOf(toggle);
                        
                        // Set line visibility
                        lines[index].visible = toggle.active;
                        
                        // Set axis visibility if it exists (all except first line)
                        if (index > 0 && index-1 < axes.length) {
                            axes[index-1].visible = toggle.active;
                        }
                    """)

                    # Add callback to all toggles
                    for toggle in toggles:
                        toggle.js_on_change('active', callback)

                    # Create a column of toggles with scrolling
                    toggle_column = Column(
                        children=column_items,
                        # width=150,
                        height=400,
                        # sizing_mode="stretch_width",
                        sizing_mode="fixed",
                        styles={
                            'overflow-y': 'auto', 
                            'border': '1px solid #ddd',
                            'padding': '8px',
                            'background-color': '#f8f9fa'
                        }
                    )
                    
                    label = Div(text="<b>Variables</b>", width=200,
                                    styles={"font-size": "20px"},  # Set font size using CSS

                                )  # Fixed-width text label
                    label_and_toggle_column = Column(label, toggle_column)

                    graph = Row(p, label_and_toggle_column, sizing_mode='stretch_both')
                                       
                    doc.add_root(graph)

                    # p.legend.click_policy="hide"

                    print("end of source is none and new data")
                    
            if new_data is None:
                new_data = case_tracker.get_new_cases()
            if new_data:
                counter = new_data["counter"]
                source_stream_dict = {"iteration": [counter]}
                
                for obj_name, obj_value in new_data["objs"].items():

                    float_obj_value = 0. if obj_value is None or obj_value.size == 0 else np.linalg.norm(obj_value)

                    source_stream_dict[obj_name] = [float_obj_value]
                    self.y_min[obj_name] = min(self.y_min[obj_name], float_obj_value)
                    self.y_max[obj_name] = max(self.y_max[obj_name], float_obj_value)
                    if self.y_min[obj_name] == self.y_max[obj_name]:
                        self.y_min[obj_name]  = self.y_min[obj_name] - 1
                        self.y_max[obj_name]  = self.y_max[obj_name]  + 1
                    p.y_range.start = self.y_min[obj_name]
                    p.y_range.end = self.y_max[obj_name]
                    
                for desvar_name, desvar_value in new_data["desvars"].items():

                    float_desvar_value = 0. if desvar_value is None or desvar_value.size == 0 else np.linalg.norm(desvar_value)

                    source_stream_dict[desvar_name] = [float_desvar_value]
                    
                    self.y_min[desvar_name] = min(self.y_min[desvar_name], float_desvar_value)
                    self.y_max[desvar_name] = max(self.y_max[desvar_name], float_desvar_value)
                    if self.y_min[desvar_name] == self.y_max[desvar_name]:
                        self.y_min[desvar_name]  = self.y_min[desvar_name] - 1
                        self.y_max[desvar_name]  = self.y_max[desvar_name]  + 1
                    p.extra_y_ranges[f"extra_y_{desvar_name}"] = Range1d(
                            self.y_min[desvar_name], self.y_max[desvar_name])

                for cons_name, cons_value in new_data["cons"].items():

                    float_cons_value = 0. if cons_value is None or cons_value.size == 0 else np.linalg.norm(cons_value)

                    source_stream_dict[cons_name] = [float_cons_value]

                    self.y_min[cons_name] = min(self.y_min[cons_name], float_cons_value)
                    self.y_max[cons_name] = max(self.y_max[cons_name], float_cons_value)
                    if self.y_min[cons_name] == self.y_max[cons_name]:
                        self.y_min[cons_name]  = self.y_min[cons_name] - 1
                        self.y_max[cons_name]  = self.y_max[cons_name]  + 1
                    p.extra_y_ranges[f"extra_y_{cons_name}"] = Range1d(
                            self.y_min[cons_name], self.y_max[cons_name])
                self._source.stream(source_stream_dict)
                print("done new_data at the end")

        
        # Add custom CSS to make the legend scrollable
        custom_css = """
        <style>
        .bk-legend {
            max-height: 200px;
            overflow-y: auto;
            border: 1px solid black;
        }
        </style>
        """

        from bokeh.resources import INLINE
        # Inject the custom CSS into the Bokeh document
        curdoc().template = f"""
        <!DOCTYPE html>
        <html lang="en">
        <head>
            <meta charset="utf-8">
            <title>Scrollable Legend</title>
            {custom_css}
            {{ bokeh_css }}
            {{ bokeh_js }}
        </head>
        <body>
            {{ plot_div | safe }}
            {{ plot_script | safe }}
        </body>
        </html>
        """
        doc.add_periodic_callback(update, 50)
        doc.title = "OpenMDAO Optimization"

    
def realtime_opt_plot(case_recorder_filename):
    """
    Visualize a ??.

    Parameters
    ----------
    case_recorder_filename : MetaModelStructuredComp or MetaModelUnStructuredComp
        The metamodel component.
    """
    from bokeh.application.application import Application
    from bokeh.application.handlers import FunctionHandler

    def _make_realtime_opt_plot_doc(doc):
        RealTimeOptPlot(case_recorder_filename, doc=doc)

    port_number = get_free_port()

    try:
        server = Server({'/': Application(FunctionHandler(_make_realtime_opt_plot_doc))}, port=port_number, 
                        unused_session_lifetime_milliseconds=1000*60*10,
                        )
        server.start()
        server.io_loop.add_callback(server.show, "/")
        
        print(f"Bokeh server running on http://localhost:{port_number}")
        server.io_loop.start()
    except KeyboardInterrupt as e:
        print(f"Server stopped due to keyboard interrupt")
    except Exception as e:
        print(f"Error starting Bokeh server: {e}")
    finally:
        print("Stopping server")
        if 'server' in globals():
            server.stop()
