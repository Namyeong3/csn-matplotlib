"""matplotlib, nicer - import it, then use matplotlib as always:

    import csn_matplotlib
    import matplotlib.pyplot as plt

Every figure is then a tab of one dark window opened maximised (plt.figure('Name') makes a tab named
so; double-click a tab to rename it). Ctrl+T makes a new tab, Ctrl+W closes one and Ctrl+Shift+T
reopens it, Ctrl+Tab and Ctrl+Shift+Tab go through them, Ctrl+Q closes the window. The mouse
wheel and two fingers on the touchpad zoom at the pointer (coasting after a flick), two fingers
sideways go back and forward through the views, a drag pans, a touch screen pans and pinches, over an
axis any of these works on that axis alone, the arrow keys pan and + and - zoom a little, and Space
fits the plot last moved, clicked or touched to what it shows (_navigation). Hovering a point names
it; a click pins it and picks its series (_inspector). Double-clicking a title, an axis label or a
legend entry renames it; double-clicking a legend marker opens that series' look (_labels).
Right-clicking a plot, an empty space or the figure gives what can be done there. F11 shows the plots
alone; again, all as it was. The terminal under the plots (Ctrl+J) shows what's printed, as the
console does (_terminal). The side panel
(Ctrl+B): the Parameters tab (the sliders this tab's plots depend on), the Data tab (what's plotted,
values and statistics, padlocks; _data_panel), the Plot tab (one plot: its series - added from any
plot of any tab, moved, removed, shown as another plot type - their look, shared by every plot they're
in or the plot's own, trendlines, error bars, grid, scales, axes swapped, and the plot shown up to an
x or revealed slowly; _plot_panel, _fits, _upto) and the Layout tab (templates, drag to swap and
resize, hide, move to other tabs, add plots; _layout). Plots are animated as a tab comes into view, a
toolbar toggle turns that off (_animate). A figure slow to draw is drawn in a thread of its own; one
of too many points asks first whether to draw a reduced set, and a plot drawn reduced says so on it
(_detail). What's changed is undoable (Ctrl+Z, Ctrl+Y), and can be kept beside the script for next
time - never the zoom; off unless turned on in the toolbar's settings (_view, _settings). csn_matplotlib.sliders() redraws the plot from parameters on
sliders and tick boxes, with buttons for the script's own functions, each run in a thread of its own that can be stopped, and runs can be saved to compare;
csn_matplotlib.progress() reports how far a run has got (_sliders). Figures are saved as SVG unless
another format's chosen, PNGs at 300 dpi.
Windows only; needs PySide6."""
import matplotlib

from . import _style, _terminal

_terminal.install()   # what's printed, in the window's terminal as well
_style.apply_rc()
matplotlib.use('module://csn_matplotlib._backend')

from ._sliders import Stopped, progress, sliders  # noqa: E402 - after the backend's chosen

__all__ = ['sliders', 'progress', 'Stopped']
