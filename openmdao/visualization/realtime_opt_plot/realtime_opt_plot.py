""" A real-plot of the optimization process"""

from collections import defaultdict
import sqlite3

from bokeh.models import (
    ColumnDataSource,
    Legend,
    LegendItem,
    LinearAxis,
    Range1d,
    Toggle,
    Column,
    Row,
    CustomJS,
    Div,
)
from bokeh.models.tools import (
    BoxZoomTool,
    ResetTool,
    HoverTool,
    PanTool,
    WheelZoomTool,
    SaveTool,
    ZoomInTool,
    ZoomOutTool,
)
from bokeh.plotting import curdoc, figure
from bokeh.server.server import Server
from tornado.ioloop import IOLoop
from bokeh.palettes import Category20, Category20b, Category20c
from bokeh.layouts import row, column, Spacer
from bokeh.application.application import Application
from bokeh.application.handlers import FunctionHandler

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
    import cProfile, pstats

    with cProfile.Profile() as profile:
        realtime_opt_plot(
            options.case_recorder_filename,
            2000 # ms between callback calls
        )
    results = pstats.Stats(profile)
    results.dump_stats("realtime_opt_plot.prof")

def _make_legend_item(varname, color):
    toggle = Toggle(
        label=varname,
        active=False,
        # width=120,
        height=20,
        margin=(0, 0, 2, 0),
    )

    # TODO what should we do with colors?
    color = 'black'
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


def _update_y_min_max(name, y, y_min, y_max):
    y_min[name] = min(y_min[name], y)
    y_max[name] = max(y_max[name], y)
    if y_min[name] == y_max[name]:
        y_min[name] = y_min[name] - 1
        y_max[name] = y_max[name] + 1

def _get_value_for_plotting(value_from_recorder, var_type):
    if value_from_recorder is None or value_from_recorder.size == 0:
        return (0.0)
    if var_type == 'cons':
        # plot the worst case value
        return np.linalg.norm(value_from_recorder, ord=np.inf)
    else:
        return np.linalg.norm(value_from_recorder)


class CaseTracker:
    def __init__(self, case_recorder_filename):
        self._case_ids_read = []
        self._case_recorder_filename = case_recorder_filename
        self._cr = None
        self.source = None

        self._num_iterations_read = 0

        self._initial_cr_with_one_case = None

    def _get_case_by_counter(self, counter):
        with sqlite3.connect(self._case_recorder_filename) as con:
            con.row_factory = sqlite3.Row
            cur = con.cursor()
            cur.execute("SELECT * FROM driver_iterations WHERE "
                        "counter=:counter",
                        {"counter": counter})
            row = cur.fetchone()
        con.close()

        if row:
            from openmdao.recorders.case import Case
            if self._cr is None:
                self._cr = SqliteCaseReader(self._case_recorder_filename)
                var_info = self._cr.problem_metadata['variables']
            case = Case('driver', row, self._cr._driver_cases._prom2abs, self._cr._driver_cases._abs2prom, self._cr._driver_cases._abs2meta,
                        self._cr._driver_cases._conns, self._cr._driver_cases._auto_ivc_map, self._cr._driver_cases._var_info, 
                        self._cr._driver_cases._format_version)
            return case
        else:
            return None

    def _get_num_driver_iterations(self):
        row_count = None
        with sqlite3.connect(self._case_recorder_filename) as con:
            con.row_factory = sqlite3.Row
            cur = con.cursor()
            # Query to count the number of rows in the table
            query = f"SELECT COUNT(*) FROM driver_iterations"
            cur.execute(query)
            row_count = cur.fetchone()[0]
        con.close()
        return row_count

    def get_new_case(self):
        num_driver_iterations_recorded = self._get_num_driver_iterations()
        print(f"{num_driver_iterations_recorded=} {self._num_iterations_read=}")
        if num_driver_iterations_recorded > self._num_iterations_read:
            case_counter = self._num_iterations_read + 1  # counter starts at 1 
            driver_case = self._get_case_by_counter(case_counter)

            if driver_case is None:
                return None

            self._num_iterations_read += 1

            objs = driver_case.get_objectives(scaled=False)
            design_vars = driver_case.get_design_vars(scaled=False)
            constraints = driver_case.get_constraints(scaled=False)

            print(f"{driver_case.counter=}")
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

            # self._case_ids_read.append(
            #     case_id
            # )  # remember that this one has been plotted

            return new_data
        return None

    def get_new_cases(self):
        # need to read this each time since the constructor does all of the actual reading
        # TODO - add code SqliteCaseReader for reading real-time data
        self._cr = SqliteCaseReader(self._case_recorder_filename)
        case_ids = self._cr.list_cases("driver", out_stream=None)
        new_case_ids = [
            case_id for case_id in case_ids if case_id not in set(self._case_ids_read)
        ]
        if new_case_ids:
            # just get the first one
            case_id = new_case_ids[0]


            print(f"getting case with id {case_id}")


            driver_case = self._cr.get_case(case_id)
            objs = driver_case.get_objectives(scaled=False)
            design_vars = driver_case.get_design_vars(scaled=False)
            constraints = driver_case.get_constraints(scaled=False)


            print(f"{driver_case.counter=}")
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

            self._case_ids_read.append(
                case_id
            )  # remember that this one has been plotted

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

        # meta = driver_case.get_io_metadata(includes=name)
        # shape = meta[name]['shape']

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
    def __init__(self, case_recorder_filename, callback_period, doc):
        self._source = None
        self._callback_period = callback_period
        case_tracker = CaseTracker(case_recorder_filename)

        # Make the figure and all the settings for it
        p = figure(
            tools=[
                PanTool(dimensions="width"),
                WheelZoomTool(),
                ZoomInTool(),
                ZoomOutTool(),
                BoxZoomTool(),
                ResetTool(),
                SaveTool(),
            ],
            width_policy="max",
            height_policy="max",
            sizing_mode="stretch_both",
            title=f"Real-time Optimization Progress Plot for: {case_recorder_filename}",
            active_drag=None,
            active_scroll="auto",
            active_tap=None,
            output_backend="webgl",
        )

        # uncomment these for debugging Bokeh
        # from bokeh.models.tools import
        # p.add_tools( ExamineTool())

        p.x_range.follow = "start"
        p.title.text_font_size = "25px"
        p.title.text_color = "black"
        p.title.text_font = "arial"
        p.title.align = "center"
        p.title.standoff = 40  # Adds 40 pixels of space below the title

        p.title.background_fill_color = "#eeeeee"
        p.xaxis.axis_label = "Driver iterations"
        p.xaxis.minor_tick_line_color = None
        p.axis.axis_label_text_font_style = "bold"
        p.axis.axis_label_text_font_size = "20pt"
        p.xgrid.band_hatch_pattern = "/"
        p.xgrid.band_hatch_alpha = 0.6
        p.xgrid.band_hatch_color = "lightgrey"
        p.xgrid.band_hatch_weight = 0.5
        p.xgrid.band_hatch_scale = 10

        self.y_min = defaultdict(
            lambda: float("inf")
        )  # update this as new data comes in
        self.y_max = defaultdict(
            lambda: float("-inf")
        )  # update this as new data comes in

        def update():

            print("--- update called ----")
            # See if source is defined yet. If not, see if we have any data
            #   in the case file yet. If there is data, create the
            #   source object and add the lines to the figure

            new_data = None

            if self._source is None:
                # new_data = case_tracker.get_new_cases()
                new_data = case_tracker.get_new_case()
                if new_data:

                    print("start of if self._source is None")


                    ####  make the source dict
                    source_dict = {"iteration": []}

                    # Obj
                    obj_names = case_tracker.get_obj_names()
                    for obj_name in obj_names:
                        source_dict[obj_name] = []

                    # Desvars
                    desvar_names = case_tracker.get_desvar_names()
                    for desvar_name in desvar_names:
                        # source_dict[desvar_name] = []
                        source_dict[f"{desvar_name}_min"] = []
                        source_dict[f"{desvar_name}_max"] = []

                    # Cons
                    con_names = case_tracker.get_cons_names()
                    for con_name in con_names:
                        source_dict[con_name] = []

                    self._source = ColumnDataSource(source_dict)

                    #### make the lines and legends
                    palette = (
                        Category20[20] + Category20b[20] + Category20c[20]
                    )  # gives us 60 colors
                    i_color = (
                        0  # index of line across all variables: obj, desvars, cons
                    )
                    toggles = []
                    column_items = []
                    lines = []
                    axes = []

                    # Objective
                    obj_names = case_tracker.get_obj_names()
                    obj_label = Div(
                        text="<b>OBJECTIVE</b>",
                        width=200,
                        styles={"font-size": "12"},  # Set font size using CSS
                    )  # Fixed-width text label
                    column_items.append(obj_label)

                    if len(obj_names) != 1:
                        raise ValueError(
                            f"Plot assumes there is on objective but {len(obj_names)} found"
                        )
                    for i, obj_name in enumerate(obj_names):
                        units = case_tracker.get_units(obj_name)

                        color = "black"
                        toggle = _make_legend_item(f"{obj_name} ({units})", color)
                        toggle.active = True
                        toggles.append(toggle)

                        column_items.append(toggle)

                        obj_line = p.line(
                            x="iteration",
                            y=obj_name,
                            line_width=3,
                            source=self._source,
                            color="black",
                        )  # make the objective black
                        p.yaxis.axis_label = f"Objective: {obj_name} ({units})"

                        lines.append(obj_line)

                        hover = HoverTool(
                            renderers=[obj_line],
                            tooltips=[
                                ("Iteration", "@iteration"),
                                (obj_name, "@{%s}" % obj_name + "{0.00}"),
                            ],
                            mode="vline",
                            visible=False,
                        )

                        # Add the hover tools to the plot
                        p.add_tools(hover)

                    # desvars
                    desvars_label = Div(
                        text="<b>DESIGN VARS</b>",
                        width=200,
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

                        # desvar_line = p.line(
                        #     x="iteration",
                        #     y=desvar_name,
                        #     line_width=3,
                        #     y_range_name=f"extra_y_{desvar_name}",
                        #     source=self._source,
                        #     # color=color,
                        #     color="black",
                        #     visible=False,
                        # )
                        # desvar_line.visible = False



                        value = new_data["desvars"][desvar_name]

                        size = value.size

                        if size == 1:
                            desvar_line = p.line(
                                x="iteration",
                                y=f"{desvar_name}_min",
                                line_width=3,
                                y_range_name=f"extra_y_{desvar_name}",
                                source=self._source,
                                # color=color,
                                color="black",
                                visible=False,
                            )
                        else:
                            desvar_line = p.varea(
                                x="iteration",
                                y1=f"{desvar_name}_min",
                                y2=f"{desvar_name}_max",
                                # line_width=3,
                                y_range_name=f"extra_y_{desvar_name}",
                                source=self._source,
                                # color=color,
                                color="black",
                                # visible=False,
                                visible=True,
                                alpha=0.3,
                            )
                        desvar_line.visible = False





                        lines.append(desvar_line)

                        hover = HoverTool(
                            renderers=[desvar_line],
                            tooltips=[
                                ("Iteration", "@iteration"),
                                (desvar_name, "@{%s}" % desvar_name + "{0.00}"),
                            ],
                            mode="vline",
                            visible=False,
                        )

                        # Add the hover tools to the plot
                        p.add_tools(hover)

                        extra_y_axis = LinearAxis(
                            y_range_name=f"extra_y_{desvar_name}",
                            axis_label=f"{desvar_name} ({units})",
                            # axis_label_text_color=color,
                            axis_label_text_color="black",
                            axis_label_text_font_size="20px",
                        )

                        axes.append(extra_y_axis)

                        p.add_layout(extra_y_axis, "right")
                        p.right[i_color].visible = False

                        # set the range
                        y_min = -20
                        y_max = -20
                        # if the range is zero, the axis will not be displayed. Plus need some range to make it
                        #    look good. Some other code seems to do +- 1 for the range in this case.
                        if y_min == y_max:
                            y_min = y_min - 1
                            y_max = y_max + 1
                        p.extra_y_ranges[f"extra_y_{desvar_name}"] = Range1d(
                            y_min, y_max
                        )

                        # p.add_layout(extra_y_axis, 'right')
                        i_color += 1

                    # cons
                    cons_label = Div(
                        text="<b>CONSTRAINTS</b>",
                        width=200,
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

                        cons_line = p.line(
                            x="iteration",
                            y=cons_name,
                            line_width=3,
                            line_dash="dashed",
                            y_range_name=f"extra_y_{cons_name}",
                            source=self._source,
                            # color=color,
                            color="black",
                            visible=False,
                        )

                        lines.append(cons_line)

                        hover = HoverTool(
                            renderers=[cons_line],
                            tooltips=[
                                ("Iteration", "@iteration"),
                                (cons_name, "@{%s}" % cons_name + "{0.00}"),
                            ],
                            mode="vline",
                            visible=False,
                        )

                        # Add the hover tools to the plot
                        p.add_tools(hover)

                        extra_y_axis = LinearAxis(
                            y_range_name=f"extra_y_{cons_name}",
                            axis_label=f"{cons_name} ({units})",
                            # axis_label_text_color=color,
                            axis_label_text_color="black",
                            axis_label_text_font_size="20px",
                        )

                        axes.append(extra_y_axis)
                        p.add_layout(extra_y_axis, "right")
                        p.right[i_color].visible = False

                        # set the range
                        y_min = -100
                        y_max = 100
                        # if the range is zero, the axis will not be displayed. Plus need some range to make it
                        #    look good. Some other code seems to do +- 1 for the range in this case.
                        if y_min == y_max:
                            y_min = y_min - 1
                            y_max = y_max + 1
                        p.extra_y_ranges[f"extra_y_{cons_name}"] = Range1d(y_min, y_max)

                        i_color += 1

                    # Create CustomJS callback for toggle buttons
                    callback = CustomJS(
                        args=dict(lines=lines, axes=axes, toggles=toggles),
                        code="""

                            if (typeof window.ColorManager === 'undefined') {
                                window.ColorManager = class {
                                    constructor(palette = 'Category10') {
                                    if (ColorManager.instance) {
                                        return ColorManager.instance;
                                    }
                                    // Define our own palettes
                                    this.palettes = {
                                        'Category10': [
                                        '#1f77b4', '#ff7f0e', '#2ca02c', '#d62728', '#9467bd',
                                        '#8c564b', '#e377c2', '#7f7f7f', '#bcbd22', '#17becf'
                                        ],
                                        'Category20': [
                                        '#1f77b4', '#aec7e8', '#ff7f0e', '#ffbb78', '#2ca02c',
                                        '#98df8a', '#d62728', '#ff9896', '#9467bd', '#c5b0d5',
                                        '#8c564b', '#c49c94', '#e377c2', '#f7b6d2', '#7f7f7f',
                                        '#c7c7c7', '#bcbd22', '#dbdb8d', '#17becf', '#9edae5'
                                        ],
                                        'Colorblind': [
                                        '#0072B2', '#E69F00', '#009E73', '#CC79A7', '#56B4E9',
                                        '#D55E00', '#F0E442', '#000000'
                                        ],
                                        'Set3': [
                                        '#8DD3C7', '#FFFFB3', '#BEBADA', '#FB8072', '#80B1D3',
                                        '#FDB462', '#B3DE69', '#FCCDE5', '#D9D9D9', '#BC80BD',
                                        '#CCEBC5', '#FFED6F'
                                        ]
                                    };
                                    
                                    this.palette = this.palettes[palette] || this.palettes.Category10;
                                    this.usedColors = new Set();
                                    this.variableColorMap = new Map();
                                    
                                    ColorManager.instance = this;
                                    } //  end of constructor
                                
                                    getColor(variableName) {
                                    if (this.variableColorMap.has(variableName)) {
                                        console.log("already have that color");
                                        return this.variableColorMap.get(variableName);
                                    }
                                
                                    const availableColor = this.palette.find(color => !this.usedColors.has(color));
                                    const newColor = availableColor || this.palette[this.usedColors.size % this.palette.length];
                                    
                                    this.usedColors.add(newColor);
                                    this.variableColorMap.set(variableName, newColor);
                                    return newColor;
                                    } // end of getColor
                                
                                    releaseColor(variableName) {
                                    const color = this.variableColorMap.get(variableName);
                                    if (color) {
                                        this.usedColors.delete(color);
                                        this.variableColorMap.delete(variableName);
                                    }
                                    } // end of releaseColor
                                
                                    // Get all available palettes
                                    getPaletteNames() {
                                    return Object.keys(this.palettes);
                                    }
                                
                                    // Change active palette
                                    setPalette(paletteName) {
                                    if (this.palettes[paletteName]) {
                                        this.palette = this.palettes[paletteName];
                                        // Optionally reset all color assignments
                                        this.usedColors.clear();
                                        this.variableColorMap.clear();
                                    }
                                    } // end of setPalette

                                }; // end of class definition

                                window.colorManager = new window.ColorManager("Category20");
                            }  // end of if

                            // Get the toggle that triggered the callback
                            const toggle = cb_obj;
                            const index = toggles.indexOf(toggle);

                            // Set line visibility
                            lines[index].visible = toggle.active;

                            // Set axis visibility if it exists (all except first line)
                            if (index > 0 && index-1 < axes.length) {
                                axes[index-1].visible = toggle.active;
                            }




                                // Let's inspect the origin object
                                //console.log('Button properties:', cb_obj.origin);
                                // Try to access label through origin
                                console.log('Label attempt 1:', cb_obj.label);
                                // Also check model properties
                                //console.log('Model properties:', cb_obj.origin.properties);






                            let variable_name = cb_obj.label;
                            // if turning on, get a color and set the line and toggle button to that color
                            if (toggle.active) {
                                let color = window.colorManager.getColor(variable_name);
                                console.log("color " + color);
                                console.log("before toggle.active axes[index-1].axis_line_color", axes[index-1].axis_line_color);
                                console.log("before toggle.active lines[index].glyph.line_color)", lines[index].glyph.line_color);
                                axes[index-1].axis_label_text_color = color
                                lines[index].glyph.line_color = color;
                                lines[index].glyph.fill_color = color;
                                console.log("after toggle.active axes[index-1].axis_line_color", axes[index-1].axis_line_color);
                                console.log("after toggle.active lines[index].glyph.line_color)", lines[index].glyph.line_color);
                                toggle.stylesheets = [`
                                    .bk-btn {
                                        color: ${color}
                                        border-color: ${color}
                                        background-color: white
                                        font-size: 12pt;
                                        display: flex;
                                        align-items: center; /* Vertical centering */
                                        justify-content: center; /* Horizontal centering */
                                        height: 12px; /* Example height, adjust as needed */
                                        border-width: 0px; /* Adjust to desired thickness */
                                        border-style: solid; /* Ensures a solid border */
                                    }
                                    .bk-btn.bk-active {
                                        color: white;
                                        border-color: ${color};
                                        background-color: ${color};
                                        font-size: 12pt;
                                        display: flex;
                                        align-items: center; /* Vertical centering */
                                        justify-content: center; /* Horizontal centering */
                                        height: 12px; /* Example height, adjust as needed */
                                        border-width: 0px; /* Adjust to desired thickness */
                                        border-style: solid; /* Ensures a solid border */
                                    }
                                `];
                            // if turning off, return the color to the pool and set the color of the button to black
                            } else {
                                window.colorManager.releaseColor(variable_name);
                                console.log("releasing ", variable_name);
                                console.log("before toggle.inactive axes[index-1].axis_line_color", axes[index-1].axis_line_color);
                                console.log("before toggle.inactive lines[index].glyph.line_color)", lines[index].glyph.line_color);
                                axes[index-1].axis_label_text_color = 'black'
                                lines[index].glyph.line_color = 'black';
                                console.log("after toggle.inactive axes[index-1].axis_line_color", axes[index-1].axis_line_color);
                                console.log("after toggle.inactive lines[index].glyph.line_color)", lines[index].glyph.line_color);
                                toggle.stylesheets = [`
                                    .bk-btn {
                                        color: black
                                        border-color: black
                                        background-color: white
                                        font-size: 12pt;
                                        display: flex;
                                        align-items: center; /* Vertical centering */
                                        justify-content: center; /* Horizontal centering */
                                        height: 12px; /* Example height, adjust as needed */
                                        border-width: 0px; /* Adjust to desired thickness */
                                        border-style: solid; /* Ensures a solid border */
                                    }
                                    .bk-btn.bk-active {
                                        color: white;
                                        border-color: black;
                                        background-color: black;
                                        font-size: 12pt;
                                        display: flex;
                                        align-items: center; /* Vertical centering */
                                        justify-content: center; /* Horizontal centering */
                                        height: 12px; /* Example height, adjust as needed */
                                        border-width: 0px; /* Adjust to desired thickness */
                                        border-style: solid; /* Ensures a solid border */
                                    }
                                `];
                            }
                    """,
                    )

                    # Add callback to all toggles
                    for toggle in toggles:
                        toggle.js_on_change("active", callback)

                    # Create a column of toggles with scrolling
                    toggle_column = Column(
                        children=column_items,
                        # width=150,
                        # height=400,
                        # sizing_mode="stretch_width",
                        sizing_mode="fixed",
                        styles={
                            "overflow-y": "auto",
                            "border": "1px solid #ddd",
                            "padding": "8px",
                            "background-color": "#f8f9fa",
                        },
                    )

                    label = Div(
                        text="<b>Variables</b>",
                        width=200,
                        styles={"font-size": "20px"},  # Set font size using CSS
                    )  # Fixed-width text label
                    label_and_toggle_column = Column(
                        label,
                        toggle_column,
                        # width_policy="max",
                        height_policy="max",
                        sizing_mode="stretch_height",
                    )

                    graph = Row(p, label_and_toggle_column, sizing_mode="stretch_both")
                    doc.add_root(graph)

            if new_data is None:
                print("before case_tracker.get_new_case ")
                # new_data = case_tracker.get_new_cases()
                new_data = case_tracker.get_new_case()
                print("after case_tracker.get_new_case ")
            if new_data:
                print("start of if new_data")
                num_driver_iterations = case_tracker._get_num_driver_iterations()
                print(f"number of driver iterations = {num_driver_iterations}")

                counter = new_data["counter"]
                source_stream_dict = {"iteration": [counter]}

                for obj_name, obj_value in new_data["objs"].items():
                    # print(f"{obj_name=} {obj_value.size} objs")
                    float_obj_value = _get_value_for_plotting(obj_value, "objs")

                    source_stream_dict[obj_name] = [float_obj_value]
                    _update_y_min_max(obj_name, float_obj_value, self.y_min, self.y_max)
                    p.y_range.start = self.y_min[obj_name]
                    p.y_range.end = self.y_max[obj_name]

                for desvar_name, desvar_value in new_data["desvars"].items():
                    # print(f"{desvar_name=} {desvar_value.size} desvars")
                    float_desvar_value = _get_value_for_plotting(desvar_value, "desvars")

                    if desvar_name == 'traj.rotation.states:distance':
                        print(f"traj.rotation.states:distance values are {np.min(desvar_value)} {np.max(desvar_value)}")

                    # source_stream_dict[desvar_name] = [float_desvar_value]

                    source_stream_dict[f"{desvar_name}_min"] = [np.min(desvar_value)]
                    source_stream_dict[f"{desvar_name}_max"] = [np.max(desvar_value)]

                    # _update_y_min_max(desvar_name, float_desvar_value, self.y_min, self.y_max)
                    _update_y_min_max(desvar_name, np.min(desvar_value), self.y_min, self.y_max)
                    _update_y_min_max(desvar_name, np.max(desvar_value), self.y_min, self.y_max)
                    p.extra_y_ranges[f"extra_y_{desvar_name}"] = Range1d(
                        self.y_min[desvar_name], self.y_max[desvar_name]
                    )

                for cons_name, cons_value in new_data["cons"].items():
                    # print(f"{cons_name=} {cons_value.size} cons")
                    float_cons_value = _get_value_for_plotting(cons_value, "cons")
                    source_stream_dict[cons_name] = [float_cons_value]

                    _update_y_min_max(cons_name, float_cons_value, self.y_min, self.y_max)
                    p.extra_y_ranges[f"extra_y_{cons_name}"] = Range1d(
                        self.y_min[cons_name], self.y_max[cons_name]
                    )
                self._source.stream(source_stream_dict)
                print("done if new_data at the end")

        doc.add_periodic_callback(update, self._callback_period)
        doc.title = "OpenMDAO Optimization"


def realtime_opt_plot(case_recorder_filename, callback_period):
    """
    Visualize a ??.

    Parameters
    ----------
    case_recorder_filename : MetaModelStructuredComp or MetaModelUnStructuredComp
        The metamodel component.
    """

    def _make_realtime_opt_plot_doc(doc):
        RealTimeOptPlot(case_recorder_filename, callback_period, doc=doc)

    port_number = get_free_port()

    try:
        server = Server(
            {"/": Application(FunctionHandler(_make_realtime_opt_plot_doc))},
            port=port_number,
            unused_session_lifetime_milliseconds=1000 * 60 * 10,
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
        if "server" in globals():
            server.stop()
