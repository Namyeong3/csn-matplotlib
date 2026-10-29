"""What an axes plots, as series the panels list and the inspector hovers: lines, scatters, bar groups
and filled areas (fill_between), each with its data as given (dates and all) and where its points are
on screen. An errorbar's caps and bars and a stem plot's stems and baseline are parts of their series:
shown, hidden and coloured with it. Lines that aren't in data coordinates (axhline, axvline) aren't
series. A series added to other plots is one series in all of them - its copies are linked to it
(link_of, members) - and a series removed from its plot is still there, invisible (_view)."""
import numpy as np
from matplotlib.container import BarContainer, ErrorbarContainer, StemContainer
from matplotlib.collections import LineCollection, PathCollection, PolyCollection
from matplotlib.lines import Line2D
from matplotlib.colors import to_hex

from ._settings import figure_key, store

OURS = 'csn'      # the gid of what this library draws itself
LARGE = 1e250     # limits past this are an overflow, not data: ticks can't be counted or named there


class Series:
    """artist: the Line2D, PathCollection, BarContainer or PolyCollection; kind: 'line', 'scatter',
    'bars' or 'area'; parts: what's drawn with it (an errorbar's caps and bars, a stem plot's stems
    and baseline); stem: the line is a stem plot's markers."""

    def __init__(self, ax, artist, kind, label, parts=(), stem=False):
        self.ax, self.artist, self.kind, self.label = ax, artist, kind, label
        self.parts, self.stem = list(parts), stem

    def data(self):
        """(x, y) as plotted - the given values, not matplotlib's floats; bars: centres and heights; an
        area: the points of its outline."""
        if self.kind == 'line':
            return _array(self.artist, 'x'), _array(self.artist, 'y')
        if self.kind == 'scatter':
            offsets = np.asarray(self.artist.get_offsets())
            return offsets[:, 0], offsets[:, 1]
        if self.kind == 'area':
            outline = _outline(self.artist)
            return outline[:, 0], outline[:, 1]
        horizontal = getattr(self.artist, 'orientation', 'vertical') == 'horizontal'
        rects = self.artist.patches
        if horizontal:
            return (np.array([r.get_width() for r in rects]),
                    np.array([r.get_y() + r.get_height() / 2 for r in rects]))
        return (np.array([r.get_x() + r.get_width() / 2 for r in rects]),
                np.array([r.get_height() for r in rects]))

    def floats(self):
        """(x, y) as matplotlib's floats (dates as day numbers) - what statistics and distances use."""
        if self.kind == 'line':
            xy = np.asarray(self.artist.get_xydata(), dtype=float)
            return xy[:, 0], xy[:, 1]
        x, y = self.data()
        return np.asarray(x, dtype=float), np.asarray(y, dtype=float)

    def screen(self):
        """Each point's display position (Nx2, pixels from the bottom left)."""
        if self.kind == 'line':
            return self.artist.get_transform().transform(np.asarray(self.artist.get_xydata(), dtype=float))
        if self.kind == 'scatter':
            return self.artist.get_offset_transform().transform(np.asarray(self.artist.get_offsets(), dtype=float))
        if self.kind == 'area':
            return self.artist.get_transform().transform(_outline(self.artist))
        return self.ax.transData.transform(np.column_stack(self.floats()))

    def point(self, index):
        """One point's display position - without working out every other's."""
        if self.kind == 'line':
            xy = np.asarray(self.artist.get_xydata()[index], dtype=float)[None]
            return self.artist.get_transform().transform(xy)[0]
        if self.kind == 'scatter':
            xy = np.asarray(self.artist.get_offsets()[index], dtype=float)[None]
            return self.artist.get_offset_transform().transform(xy)[0]
        return self.screen()[index]

    def visible(self):
        if self.kind == 'bars':
            return any(r.get_visible() for r in self.artist.patches)
        return self.artist.get_visible()

    def set_visible(self, on):
        for artist in (self.artist.patches if self.kind == 'bars' else [self.artist]) + self.parts:
            if artist is not None:
                artist.set_visible(on)

    def colour(self):
        try:
            if self.kind == 'line':
                return to_hex(self.artist.get_color())
            if self.kind in ('scatter', 'area'):
                colours = self.artist.get_facecolor()
                return to_hex(colours[0], keep_alpha=False) if len(colours) else '#888888'
            return to_hex(self.artist.patches[0].get_facecolor(), keep_alpha=False) if self.artist.patches else '#888888'
        except (ValueError, IndexError):
            return '#888888'

    def __len__(self):
        if self.kind == 'line':
            return len(self.artist.get_xdata(orig=False))
        if self.kind == 'scatter':
            return len(self.artist.get_offsets())
        if self.kind == 'area':
            return len(_outline(self.artist))
        return len(self.artist.patches)


def _array(line, axis):
    """A line's own x or y as an array - made once from a list it was given (a list of millions of
    floats takes a while to turn into one, every time)."""
    given = line.get_xdata(orig=True) if axis == 'x' else line.get_ydata(orig=True)
    if isinstance(given, np.ndarray):
        return given
    made = getattr(line, '_csn_arrays', None)
    if made is None:
        made = line._csn_arrays = {}
    kept = made.get(axis)
    if kept is not None and kept[0] is given:
        return kept[1]
    array = np.asarray(given)
    made[axis] = (given, array)
    return array


def _outline(collection):
    paths = collection.get_paths()
    return np.asarray(paths[0].vertices, dtype=float) if paths else np.empty((0, 2))


def series(ax, everything=False):
    """The axes' series, in the order they were plotted (containers first claim their parts) - those
    removed from it too, if everything."""
    found, taken = [], set()

    def order(artist):
        return ax._children.index(artist) if artist in ax._children else 0
    for container in ax.containers:
        if isinstance(container, ErrorbarContainer):
            data_line, caps, bars = container.lines
            parts = [*caps, *bars]
            taken.update(id(a) for a in parts)
            if data_line is not None and data_line.get_gid() != OURS:
                found.append((order(data_line), Series(ax, data_line, 'line', _label(container, data_line), parts)))
                taken.add(id(data_line))
        elif isinstance(container, StemContainer):
            parts = [part for part in (container.stemlines, container.baseline) if part is not None]
            taken.update(id(a) for a in parts)
            marker = container.markerline
            if marker is not None and marker.get_gid() != OURS:
                found.append((order(marker), Series(ax, marker, 'line', _label(container, marker), parts, stem=True)))
                taken.add(id(marker))
        elif isinstance(container, BarContainer) and container.patches:
            taken.update(id(r) for r in container.patches)
            first = container.patches[0]
            if first.get_gid() != OURS:
                found.append((order(first), Series(ax, container, 'bars', _label(container))))
    for number, artist in enumerate(ax._children):
        if id(artist) in taken or artist.get_gid() == OURS:
            continue
        if isinstance(artist, Line2D) and artist.get_transform() is ax.transData:
            found.append((number, Series(ax, artist, 'line', _label(artist))))
        elif isinstance(artist, PathCollection) and len(artist.get_offsets()):
            found.append((number, Series(ax, artist, 'scatter', _label(artist))))
        elif isinstance(artist, PolyCollection) and not isinstance(artist, LineCollection) and artist.get_paths():
            found.append((number, Series(ax, artist, 'area', _label(artist))))
    found.sort(key=lambda pair: pair[0])
    result = [s for _, s in found]
    unnamed = [s for s in result if s.label is None]
    for number, s in enumerate(unnamed, 1):   # "predator vs prey" from the axis labels, else "line 2"
        names = ax.get_ylabel(), ax.get_xlabel()
        s.label = (f"{names[0]} vs {names[1]}" if all(names) and len(unnamed) == 1
                   else f"{s.kind} {number}")
    removed = store.plots().get('removed', [])
    if removed and not everything:
        result = [s for s in result if key_of(s) not in removed]
    return result


def name_of(s):
    """The name the series first had - what its look and new name are kept under, renamed or drawn
    again (a run of the sliders gives the same names)."""
    if getattr(s.artist, '_csn_name', None) is None:
        s.artist._csn_name = s.label
    return s.artist._csn_name


def figures():
    """Every figure with a window (a tab, or a tab closed that can be opened again), in the order they
    were made."""
    from matplotlib._pylab_helpers import Gcf
    return [manager.canvas.figure for manager in sorted(Gcf.get_all_fig_managers(), key=lambda m: m.num)]


def open_figures():
    """The figures whose tabs are open - where a plot or a series can be sent."""
    return [f for f in figures() if not getattr(f.canvas.manager, 'closed', False)]


def tab_name(figure):
    """What the figure's tab is called - renamed or not (figure_key stays its name in the settings)."""
    manager = getattr(figure.canvas, 'manager', None)
    title = manager.get_window_title() if manager is not None else None
    return title or figure_key(figure)


def ax_id(ax):
    """The plot's name in the settings file, for good: the figure the script made it in and its place
    there ('Figure 1/0') - the same once it's been moved to another tab."""
    found = getattr(ax, '_csn_id', None)
    if found is None:
        figure = ax.figure
        found = ax._csn_id = f"{figure_key(figure)}/{figure.axes.index(ax)}"
    return found


def axes_of(identity):
    """The axes with this ax_id(), in whichever figure it is now."""
    for figure in figures():
        for ax in figure.axes:
            if ax_id(ax) == identity:
                return ax
    return None


def given_name(ax):
    """The name the plot's been given in the window ('' - none)."""
    return store.plots().get('names', {}).get(ax_id(ax), '')


def plot_name(ax, given=True):
    """What a plot's called where it's listed: the name it's been given, else its title, else what it
    plots, else its place."""
    if given and given_name(ax):
        return given_name(ax)
    title = ax.get_title() or ax.get_title('left') or ax.get_title('right')
    if title:
        return title
    x, y = ax.get_xlabel(), ax.get_ylabel()
    if x and y:
        return f"{y} vs {x}"
    figure = ax.figure
    return f"Plot {figure.axes.index(ax) + 1}" if figure is not None and ax in figure.axes else 'Plot'


def key_of(s):
    return f"{ax_id(s.ax)}|{name_of(s)}"


def find(key):
    """The series with this key_of(), wherever it is now - removed from its plot or not."""
    for figure in figures():
        for ax in figure.axes:
            for s in series(ax, everything=True):
                if key_of(s) == key:
                    return s
    return None


def added(s):
    """The id of a series added through the window (a run saved, a copy) - None for the script's."""
    return getattr(s.artist, '_csn_added', None)


def link_of(s):
    """What a series is one with: a copy's source, else its own key."""
    return getattr(s.artist, '_csn_link', None) or key_of(s)


def members(s):
    """The series and every copy of it, in whichever plots they are."""
    link = link_of(s)
    return [other for figure in figures() for ax in figure.axes for other in series(ax) if link_of(other) == link]


def fit(ax):
    """The axes' limits fitted to what it holds now, each way it autoscales - scatters and areas too,
    which matplotlib's relim() leaves out - and never to limits past what can be drawn."""
    x, y = ax.get_autoscalex_on(), ax.get_autoscaley_on()
    if not (x or y):
        return
    ax.relim(visible_only=True)   # what's hidden doesn't count
    for collection in ax.collections:
        if collection.get_visible() and collection.get_gid() != OURS:
            try:
                corners = collection.get_datalim(ax.transData).get_points()
            except (ValueError, TypeError):
                continue
            if np.all(np.isfinite(corners)) and np.all(np.abs(corners) < LARGE):
                ax.update_datalim(corners)
    try:
        ax.autoscale_view(scalex=x, scaley=y)
    except (ValueError, OverflowError):   # data gone to inf: repaired below
        pass
    safe_limits(ax)


def safe_limits(ax):
    """Limits that can't be drawn - inf, nan, past LARGE, or not above 0 on a log axis - put back to
    the finite data there is (or a plain 0 to 1). True if any was."""
    repaired = False
    for axis in ('x', 'y'):
        low, high = ax.get_xlim() if axis == 'x' else ax.get_ylim()
        log = (ax.get_xscale() if axis == 'x' else ax.get_yscale()) == 'log'
        if np.isfinite(low) and np.isfinite(high) and max(abs(low), abs(high)) < LARGE and low != high \
                and not (log and min(low, high) <= 0):
            continue
        values = []
        for s in series(ax):
            if s.visible():
                try:
                    v = s.floats()[0 if axis == 'x' else 1]
                except (TypeError, ValueError):
                    continue
                v = v[np.isfinite(v) & (np.abs(v) < LARGE)]
                values.append(v[v > 0] if log else v)
        values = np.concatenate(values) if values else np.empty(0)
        if len(values) and values.min() < values.max():
            low, high = float(values.min()), float(values.max())
            if log:
                low, high = low / 1.5, high * 1.5
            else:
                pad = (high - low) * 0.05
                low, high = low - pad, high + pad
        elif len(values):
            centre = float(values[0])
            low, high = (centre / 2, centre * 2) if log else (centre - 1, centre + 1)
        else:
            low, high = (1.0, 10.0) if log else (0.0, 1.0)
        (ax.set_xlim if axis == 'x' else ax.set_ylim)(low, high, auto=None)
        repaired = True
    return repaired


def quiet():
    """Before the window changes a figure: any figure being drawn in the background finished first -
    a thread drawing it while it changes could draw half of each."""
    for figure in figures():
        finish = getattr(figure.canvas, 'finish_drawing', None)
        if finish is not None:
            finish()


def _label(*artists):
    for artist in artists:
        label = artist.get_label() if hasattr(artist, 'get_label') else None
        if label and not str(label).startswith('_'):
            return str(label)
    return None


def text(value):
    """A value the way the panel and the inspector show it."""
    if isinstance(value, (float, np.floating)):
        return 'nan' if np.isnan(value) else f"{value:.6g}"
    if isinstance(value, np.datetime64):
        return str(value).replace('T', ' ')
    return str(value)
