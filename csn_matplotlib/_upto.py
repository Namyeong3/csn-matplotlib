"""Showing a plot only up to an x: its series - and their trendlines and error bars - drawn with only
their points up to that x, the axes and their limits as they are. A line ends exactly at the x (it's
drawn to there, without a marker where it ends), a scatter shows whole points, bars whole bars, steps
whole steps; a
filled area and horizontal bars are cut off at the x. Played, the x goes from the first point to the
last over some seconds - always from the first, wherever the slider is - drawn frame by frame over
an image of the plot without its data, so only the data is drawn again. Its right-hand axis and the
plots sharing its x axis are cut with it. Only for plots of lines, scatters, bars and areas
(supported); like the zoom, it isn't kept for next time."""
import contextlib
import math
import time

import numpy as np
from matplotlib.collections import LineCollection, PathCollection, PolyCollection, PolyQuadMesh
from matplotlib.container import BarContainer
from matplotlib.transforms import BboxBase
from PySide6 import QtCore

from . import _detail, _series


def _main(ax):
    return getattr(ax, '_csn_main', None) or ax


def group(ax):
    """The plot, its twins, and the plots in its tab sharing its x axis."""
    main = _main(ax)
    figure = main.figure
    found = [a for a in figure.axes if a is main or _main(a) is main
             or main._shared_axes['x'].joined(main, a) or main._twinned_axes.joined(main, a)]
    return list(dict.fromkeys(found))


def get(ax):
    """The x the plot is shown up to - None: all of it."""
    return getattr(_main(ax), '_csn_upto', None)


def set_upto(ax, x):
    _series.quiet()
    for member in group(ax):
        member._csn_upto = None if x is None else float(x)
    ax.figure.canvas.draw_idle()


def span(ax):
    """(first, last): the x the plot's series start and end at, as floats - None if it has none."""
    lows, highs = [], []
    for member in group(ax):
        for s in _series.series(member):
            if not s.visible():
                continue
            try:
                x = s.floats()[0]
            except (TypeError, ValueError):
                continue
            x = x[np.isfinite(x)]
            if len(x):
                lows.append(float(x.min()))
                highs.append(float(x.max()))
    return (min(lows), max(highs)) if lows and min(lows) < max(highs) else None


def supported(ax):
    """Whether the plot can be shown up to an x: what's in it lines, scatters, bars and areas - not an
    image, a mesh or a contour."""
    for member in group(ax):
        if member.images:
            return False
        for collection in member.collections:
            if isinstance(collection, PolyQuadMesh) or not isinstance(
                    collection, (PathCollection, LineCollection, PolyCollection)):
                return False
    return span(ax) is not None


class _UpTo(BboxBase):
    """The axes' box up to the x - worked out as it's drawn, so it follows a zoom."""

    def __init__(self, ax):
        super().__init__()
        self.ax = ax

    def get_points(self):
        ax = self.ax
        box = ax.bbox
        x = getattr(ax, '_csn_upto', None)
        edge = box.x1
        if x is not None:
            try:
                edge = float(ax.transData.transform((x, ax.get_ylim()[0]))[0])
            except (ValueError, OverflowError):
                pass
            if not math.isfinite(edge):
                edge = box.x1
        edge = min(max(edge, box.x0), box.x1)
        if ax.xaxis_inverted():
            return np.array([[edge, box.y0], [box.x1, box.y1]])
        return np.array([[box.x0, box.y0], [edge, box.y1]])


def _drawn_in(ax):
    return [*ax.lines, *ax.collections, *(p for p in ax.patches if p is not ax.patch), *ax.images]


def _clipped(ax, artist):
    """What's cut off at the x rather than shown up to it: an area, horizontal bars."""
    if isinstance(artist, PolyCollection) and not isinstance(artist, LineCollection):
        return True
    return any(artist in c.patches for c in ax.containers
               if isinstance(c, BarContainer) and getattr(c, 'orientation', 'vertical') == 'horizontal')


def prepare(figure):
    """Before a draw: what's cut off at the x (an area, horizontal bars) clipped there - or, no longer,
    as it was."""
    for ax in figure.axes:
        cut = getattr(ax, '_csn_upto', None)
        for artist in _drawn_in(ax):
            clipped = isinstance(artist.get_clip_box(), _UpTo)
            if cut is None or not _clipped(ax, artist):
                if clipped:
                    artist.set_clip_box(getattr(artist, '_csn_clip0', None))
            elif not clipped:
                artist._csn_clip0 = artist.get_clip_box()
                artist.set_clip_box(_UpTo(ax))


def _increasing(line, x):
    key = (id(line._xorig), len(x))
    if getattr(line, '_csn_increasing', (None,))[0] != key:
        line._csn_increasing = (key, bool(len(x) < 2 or np.all(np.diff(x) >= 0)))
    return line._csn_increasing[1]


def _cut_line(line, cut, undo):
    xy = line.get_xydata()
    if not len(xy):
        return
    x = xy[:, 0]
    undo.append(lambda a=line, s=(line._xorig, line._yorig, line._markevery, line._subslice): _put_line(a, *s))
    if _increasing(line, x):
        k = int(np.searchsorted(x, cut, side='right'))
        if k >= len(x):
            undo.pop()
            return
        shown = xy[:k]
        marks = line._markevery
        stepped = str(line.get_drawstyle()).startswith('steps')   # a step comes in whole, as a bar does
        if 0 < k and x[k] > cut and not stepped and (marks is None or isinstance(marks, np.ndarray)):   # on to the x itself
            a, b = xy[k - 1], xy[k]
            share = (cut - a[0]) / (b[0] - a[0]) if b[0] != a[0] else 0.0
            shown = np.vstack([shown, a + share * (b - a)])
            line._markevery = np.arange(k) if marks is None else marks[marks < k]   # no marker where it ends
        elif isinstance(marks, np.ndarray):
            line._markevery = marks[marks < k]
        line._xorig, line._yorig = shown[:, 0], shown[:, 1]
    else:   # x back and forth (a phase plot): the points past it left out, the line broken there
        y = xy[:, 1].copy()
        y[x > cut] = np.nan
        line._xorig, line._yorig = x, y
    line._subslice = False
    line._invalidx = line._invalidy = True


def _put_line(line, x, y, marks, subslice):
    line._xorig, line._yorig, line._markevery, line._subslice = x, y, marks, subslice
    line._invalidx = line._invalidy = True


def _cut_points(collection, cut, undo):
    offsets = np.asarray(collection.get_offsets())
    if not len(offsets):
        return
    keep = offsets[:, 0] <= cut
    if keep.all():
        return
    count = len(offsets)
    saved = {name: getattr(collection, name, None) for name in ('_offsets', '_sizes', '_facecolors', '_edgecolors',
                                                                '_linewidths', '_A')}
    undo.append(lambda c=collection, s=saved: [setattr(c, k, v) for k, v in s.items()])
    collection._offsets = offsets[keep]
    for name in ('_sizes', '_facecolors', '_edgecolors', '_linewidths', '_A'):
        value = saved[name]
        if value is not None and np.ndim(value) and len(value) == count:
            setattr(collection, name, value[keep])


def _cut_segments(collection, cut, undo):
    paths = collection.get_paths()
    kept = [p for p in paths if len(p.vertices) and np.nanmin(p.vertices[:, 0]) <= cut]
    if len(kept) == len(paths):
        return
    undo.append(lambda c=collection, p=collection._paths: setattr(c, '_paths', p))
    collection._paths = kept


def _cut_bars(container, cut, undo):
    for bar in container.patches:
        if bar.get_visible() and bar.get_x() + bar.get_width() / 2 > cut:
            bar._visible = False
            undo.append(lambda b=bar: setattr(b, '_visible', True))


@contextlib.contextmanager
def cut(figure):
    """While the figure's drawn: each plot shown up to an x drawn with its data up to there - its own
    put back after."""
    undo = []
    try:
        for ax in figure.axes:
            at = getattr(ax, '_csn_upto', None)
            if at is None:
                continue
            for line in ax.lines:
                if line.get_visible() and line.get_transform() is ax.transData:
                    _cut_line(line, at, undo)
            for collection in ax.collections:
                if not collection.get_visible():
                    continue
                if isinstance(collection, LineCollection):
                    _cut_segments(collection, at, undo)
                elif isinstance(collection, PathCollection):
                    _cut_points(collection, at, undo)
            for container in ax.containers:
                if isinstance(container, BarContainer) and getattr(container, 'orientation', 'vertical') != 'horizontal':
                    _cut_bars(container, at, undo)
        yield
    finally:
        for step in reversed(undo):
            step()


def edge(ax):
    """The display x past which nothing's shown - None: no cut."""
    at = get(ax)
    if at is None:
        return None
    try:
        return float(ax.transData.transform((at, ax.get_ylim()[0]))[0])
    except (ValueError, OverflowError):
        return None


class Player(QtCore.QObject):
    """The x going from the first point to the last over so many seconds - each frame only the data
    drawn again, over an image of the plot without it; the whole plot again after."""

    moved = QtCore.Signal(float)   # the x it's at
    finished = QtCore.Signal()
    FRAME_MS = 15

    def __init__(self):
        super().__init__()
        self._timer = QtCore.QTimer(self)
        self._timer.setInterval(self.FRAME_MS)
        self._timer.timeout.connect(self._frame)
        self.ax = None
        self._background = self._listening = None

    @property
    def playing(self):
        return self._timer.isActive()

    @staticmethod
    def _ends(ax, low, high):
        """The axis's own scale, and low and high on it - None if it can't go by it."""
        if ax.get_xscale() == 'log' and low <= 0:   # nothing below 0 shows on a log axis: from its left edge
            low = min(ax.get_xlim())
        scale = ax.xaxis.get_transform()
        try:
            ends = scale.transform(np.array([low, high], dtype=float))
        except (TypeError, ValueError):
            return None
        return (scale, ends) if np.all(np.isfinite(ends)) and ends[0] != ends[1] else None

    @classmethod
    def at(cls, ax, low, high, share):
        """The x a share (0 to 1) of the way from low to high - evenly along the axis as it's drawn: on a
        log one, as long from 1 to 10 as from 10 to 100."""
        found = cls._ends(ax, low, high)
        if found is None:
            return low + share * (high - low)
        scale, ends = found
        return float(scale.inverted().transform(np.array([ends[0] + share * (ends[1] - ends[0])]))[0])

    @classmethod
    def share(cls, ax, low, high, x):
        """How far x is from low to high (0 to 1), the same way."""
        found = cls._ends(ax, low, high)
        there = found[0].transform(np.array([x], dtype=float))[0] if found is not None else np.nan
        if not np.isfinite(there):
            return min(max((x - low) / (high - low), 0.0), 1.0)
        ends = found[1]
        return min(max(float((there - ends[0]) / (ends[1] - ends[0])), 0.0), 1.0)

    def play(self, ax, seconds):
        """From the first point - wherever the slider is - to the last."""
        bounds = span(ax)
        if bounds is None or not supported(ax):
            return False
        self.stop()
        self.ax, self.seconds = ax, max(float(seconds), 0.5)
        self.low, self.high = bounds
        self.started = time.perf_counter()
        self._background = None
        canvas = ax.figure.canvas
        self._listening = (canvas, canvas.mpl_connect('draw_event', self._drawn))
        inspector = getattr(canvas, 'inspector', None)
        if inspector is not None:
            inspector.clear_hover()
        self._timer.start()
        self._frame()
        return True

    def stop(self):
        if self._listening is not None:
            canvas, cid = self._listening
            canvas.mpl_disconnect(cid)
            self._listening = None
        self._background = None
        if self._timer.isActive():
            self._timer.stop()
            self.finished.emit()

    def _drawn(self, event):
        self._background = None   # drawn anew (zoomed, resized): the image without data made again

    def _frame(self):
        ax = self.ax
        if ax is None or ax.figure is None:
            self.stop()
            return
        canvas = ax.figure.canvas
        if getattr(canvas, 'drawing', False) or getattr(canvas, 'computing', False):   # this frame waits
            return
        share = min((time.perf_counter() - self.started) / self.seconds, 1.0)
        if share >= 1.0:
            self.stop()
            set_upto(ax, None)
            self.moved.emit(self.high)
            return
        x = self.at(ax, self.low, self.high, share)
        for member in group(ax):
            member._csn_upto = x
        if not self._blit():
            set_upto(ax, x)
        self.moved.emit(x)

    def _blit(self):
        """This frame: the plot's data up to its x over the image without it. False if it can't be."""
        figure = self.ax.figure
        canvas = figure.canvas
        renderer = getattr(canvas, 'renderer', None)
        w, h = figure.bbox.size
        if renderer is None or abs(renderer.width - w) > 1 or abs(renderer.height - h) > 1:
            return False
        members = [a for a in figure.axes if a in group(self.ax)]
        try:
            if self._background is None:
                self._background = self._without_data(figure, renderer, members)
            inspector = getattr(canvas, 'inspector', None)
            if inspector is not None:
                inspector._background = None   # its marks would put back the image from before
            canvas.restore_region(self._background)
            prepare(figure)
            with _detail.reduced(figure, getattr(canvas, 'draw_rate', _detail.RATE)), cut(figure):
                for a in members:
                    if not a.get_visible():
                        continue
                    for artist in sorted(_drawn_in(a), key=lambda t: t.get_zorder()):
                        if artist.get_visible():
                            artist.draw(renderer)
                    legend = a.get_legend()
                    if legend is not None and legend.get_visible():
                        legend.draw(renderer)
        except Exception:   # a frame that can't be drawn this way: drawn the whole way
            self._background = None
            return False
        canvas.update()
        return True

    def _without_data(self, figure, renderer, members):
        hidden = [a for ax in members for a in _drawn_in(ax) if a.get_visible()]
        engine = figure._layout_engine   # laid out as it is: nothing moves while it plays
        canvas = figure.canvas
        for artist in hidden:
            artist._visible = False
        figure._layout_engine = None
        canvas._quiet = True
        try:
            renderer.clear()
            figure.draw(renderer)
            return canvas.copy_from_bbox(figure.bbox)
        finally:
            canvas._quiet = False
            figure._layout_engine = engine
            for artist in hidden:
                artist._visible = True
