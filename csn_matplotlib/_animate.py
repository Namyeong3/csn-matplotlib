"""Plots drawn as they come into view - a tab opened or switched to, a different arrangement picked, a
plot added, the animation turned on - over REVEAL_MS, each series its own way, whatever else is in its
plot, and the same way wherever it comes in (mode_of): a line along x (markers on it or not) drawn
from x = 0 to the right, horizontal bars out of x = 0, a scatter (points with no line, and images)
fading in, and everything else rising out of y = 0 (kept inside the plot - its bottom on a log scale).
A series shown comes its way, one hidden goes the same way back; a reference shadow goes its series'
way. Only the data moves: axes, grids, ticks, labels and legends stay as they are.
It's made of images, and nothing's drawn again while it runs: the figure is drawn in the order
matplotlib draws it, cut into the images between what moves and what doesn't - each plot's moving
series alone, and what's under and over them - and each frame lays them on each other in that order,
the moving ones squeezed toward their own plot's baseline. So nothing is ever over what it's under in
the end (a grid stays over an area drawn under it), and nothing of a neighbour's moves with a plot.
'Animate plots' in the toolbar's options turns it on and off (kept in Qt's settings, for every
script); any input ends it, and a tab only dragged along the bar doesn't bring it on."""
import numpy as np
from matplotlib.axes import Axes
from matplotlib.backends.backend_agg import RendererAgg
from matplotlib.collections import QuadMesh
from matplotlib.container import BarContainer
from matplotlib.image import AxesImage
from PySide6 import QtCore, QtGui

from . import _series

REVEAL_MS = 550
SLOW_S = 1.0     # a figure taking longer than this to draw: shown as it is, no animation
_qt = None


def _settings():
    global _qt
    if _qt is None:
        _qt = QtCore.QSettings('CSN', 'csn_matplotlib')
    return _qt


def enabled():
    return _settings().value('animate', True, type=bool)


def set_enabled(on):
    _settings().setValue('animate', bool(on))


def _image(renderer, ratio):
    return _qimage(np.asarray(renderer.buffer_rgba()), ratio)


def _qimage(pixels, ratio):
    height, width = pixels.shape[:2]
    image = QtGui.QImage(np.ascontiguousarray(pixels).tobytes(), width, height, width * 4,
                         QtGui.QImage.Format.Format_RGBA8888).copy()
    image.setDevicePixelRatio(ratio)
    return image


def pixels(renderer):
    """The renderer's image, as an array of its own."""
    return np.array(renderer.buffer_rgba(), copy=True)


def _data_artists(ax):
    return [*ax.lines, *ax.collections, *ax.patches, *ax.images]


def _main(ax):
    return getattr(ax, '_csn_main', None) or ax


def mode_of(s):
    """How a series comes and goes: 'wipe' (a line along x - never turning back - with markers on it
    or not, drawn from x = 0 to the right), 'right' (horizontal bars, out of x = 0), 'fade' (a scatter,
    and only that) or 'up' (everything else - markers alone too - out of y = 0). An area goes as its
    plot's other series do: 'wipe' if they all do, else 'up'."""
    if s.kind == 'scatter':
        return 'fade'
    if s.kind == 'area':   # as its plot's other series go: all along x, along x - else out of y = 0
        others = {mode_of(o) for o in _series.series(s.ax) if o.kind != 'area'}
        return 'wipe' if others == {'wipe'} else 'up'
    if s.kind == 'bars':
        bars = s.artist if isinstance(s.artist, BarContainer) else None
        return 'right' if bars is not None and getattr(bars, 'orientation', 'vertical') == 'horizontal' else 'up'
    if s.kind == 'line':
        line = s.artist
        if line.get_linestyle() not in ('None', '', ' ', 'none'):   # joined
            try:
                x = np.asarray(line.get_xdata(), dtype=float)
            except (TypeError, ValueError):
                return 'up'
            x = x[np.isfinite(x)]
            if len(x) > 1 and np.all(np.diff(x) >= 0):   # along x, never turning back
                return 'wipe'
    return 'up'


def artists_of(s):
    """What's drawn of a series: its artist (a bar chart's bars), and its parts (error bars)."""
    return (list(s.artist.patches) if s.kind == 'bars' else [s.artist]) + list(getattr(s, 'parts', []) or [])


def shadows_of(artists, figure):
    """The reference shadows shown of these artists' series (_sliders: _csn_like, the artist shadowed)."""
    ids = {id(a) for a in artists}
    return [a for ax in figure.axes for a in _data_artists(ax)
            if a.get_visible() and id(getattr(a, '_csn_like', None)) in ids]


def _ways(figure, mains):
    """{id: (artist, way)} - every data artist shown in these plots: each series its own way (mode_of),
    a reference shadow its series' way, images fading, anything else rising."""
    ways = {}
    for main in mains:
        for a in [a for a in figure.axes if _main(a) is main]:
            owned = {id(artist): mode_of(s) for s in _series.series(a) if s.visible() for artist in artists_of(s)}
            for artist in _data_artists(a):
                if artist.get_visible():
                    way = (owned.get(id(artist)) or owned.get(id(getattr(artist, '_csn_like', None)))
                           or ('fade' if artist in a.images or isinstance(artist, QuadMesh) else 'up'))
                    ways[id(artist)] = (artist, way)
    return ways


def _drawing_order(ax):
    """What an Axes draws, in the order it draws it (Axes.draw): its patch, then its children by
    zorder - an inset's own, in its place."""
    if not ax.get_visible():
        return []
    children = [c for c in ax.get_children() if c is not ax.patch]
    if not (ax.axison and ax._frameon):
        children = [c for c in children if c not in ax.spines.values()]
    if not ax.axison:
        children = [c for c in children if c not in ax._axis_map.values()]
    children = sorted((c for c in children if not c.get_animated() or isinstance(c, AxesImage)),
                      key=lambda c: c.get_zorder())
    order = [ax.patch] if ax.axison and ax._frameon else []
    for child in children:
        order += _drawing_order(child) if isinstance(child, Axes) else [child]
    return order


def _steps(figure, moving):
    """The figure as the images it's to be drawn in, bottom to top: [(None, [artists]) - still, or
    [(way, axes, [artists]), ...] - moving]. Plots lying over each other (one and its twins, its insets)
    are one group, in their own drawing order; groups don't overlap, so their nth images are drawn
    together - still ones as one image, moving ones each in its own plot."""
    groups, rest = {}, []
    for artist in sorted((a for a in figure.get_children() if a is not figure.patch and not a.get_animated()),
                         key=lambda a: a.get_zorder()):
        if isinstance(artist, Axes):
            box = tuple(np.round(artist.bbox.extents, 1))
            groups.setdefault(box, []).extend((artist, a) for a in _drawing_order(artist))
        else:
            rest.append(artist)
    columns = []
    for order in groups.values():
        runs = [(None, None, [])]
        for ax, artist in order:
            entry = moving.get(id(artist))
            if entry is None:
                if not artist.get_visible():
                    continue
                if runs[-1][0] is not None:
                    runs.append((None, None, []))
            else:
                way, owner = entry[1], getattr(artist, 'axes', None) or ax
                if runs[-1][0] is None or runs[-1][0] != way or runs[-1][1] is not owner:
                    if runs[-1][0] is not None:   # two moving ones in a row: nothing still between them
                        runs.append((None, None, []))
                    runs.append((way, owner, []))
            runs[-1][2].append(artist)
        if runs[-1][0] is not None:
            runs.append((None, None, []))
        columns.append(runs)
    steps = [(None, [figure.patch])]
    for n in range(max((len(c) for c in columns), default=0)):
        here = [c[n] for c in columns if n < len(c)]
        if n % 2 == 0:   # still
            still = [a for run in here for a in run[2]]
            if isinstance(steps[-1], tuple):
                steps[-1][1].extend(still)
            else:
                steps.append((None, still))
        else:
            steps.append([run for run in here if run[2]])
    if isinstance(steps[-1], tuple):
        steps[-1][1].extend(rest)
    else:
        steps.append((None, rest))
    return [step for step in steps if (step[1] if isinstance(step, tuple) else step)]


def _baseline(main, mode):
    """Where the data rises from, in display pixels: 0 on the axis, kept inside the plot - the
    plot's bottom (left) edge where 0 can't be (a log scale)."""
    box = main.bbox
    low, high = (box.y0, box.y1) if mode == 'up' else (box.x0, box.x1)
    log = (main.get_yscale() if mode == 'up' else main.get_xscale()) == 'log'
    at = low
    if not log:
        try:
            at = float(main.transData.transform((main.get_xlim()[0], 0.0))[1] if mode == 'up'
                       else main.transData.transform((0.0, main.get_ylim()[0]))[0])
        except (ValueError, OverflowError):
            at = low
        if not np.isfinite(at):
            at = low
    if mode == 'up' and main.yaxis_inverted() and log:
        at = high
    return min(max(at, low), high)


def _fast(image):
    """The image as Qt draws fastest (premultiplied) - drawn every frame."""
    return image.convertToFormat(QtGui.QImage.Format.Format_ARGB32_Premultiplied)


class Reveal(QtCore.QObject):
    """The frames over the canvas while its data comes in (or a series goes)."""

    def __init__(self, canvas):
        super().__init__(canvas)
        self.canvas = canvas
        self.active = False
        self.progress = 0.0
        # bottom to top: ('still', image, where) or ('move', way, image, its plot's box, {mode: baseline})
        self.steps = []
        self.height, self.ratio = 0, 1.0   # the figure's image's, in pixels
        self.grow = self.whole = True
        self._animation = QtCore.QVariantAnimation(self)
        self._animation.setStartValue(0.0)
        self._animation.setEndValue(1.0)
        self._animation.setDuration(REVEAL_MS)
        self._animation.setEasingCurve(QtCore.QEasingCurve.Type.OutCubic)
        self._animation.valueChanged.connect(self._frame)
        self._animation.finished.connect(self.stop)

    def _ready(self):
        canvas = self.canvas
        return (enabled() and canvas.isVisible() and canvas.width() > 2 and canvas.height() > 2
                and not canvas.computing and not canvas.drawing and hasattr(canvas, 'renderer'))

    def start(self, artists=None, axes=None, grow=True, mode=None):
        """From the figure just drawn: all its data coming in (artists None), each series its own way -
        only these plots' (axes), if given - or these artists coming in (grow) or going, the way mode
        says; going, they're hidden already, and drawn here as they were. Gives whether it started."""
        self.stop()
        if not self._ready():
            return False
        canvas, figure = self.canvas, self.canvas.figure
        mains = [ax for ax in figure.axes if _main(ax) is ax and ax.get_visible() and not hasattr(ax, '_colorbar')]
        if axes is not None:
            wanted = {_main(ax) for ax in axes}
            mains = [ax for ax in mains if ax in wanted]
        if not mains or getattr(canvas, 'last_draw_s', 0.0) > SLOW_S:
            return False
        try:
            if artists is None:
                moving = _ways(figure, mains)
            else:
                artists = list(artists) + (shadows_of(artists, figure) if grow else [])
                moving = {id(a): (a, mode or 'up') for a in artists}
            if not moving:
                return False
            steps = self._drawn(figure, moving, revive=artists if artists is not None and not grow else ())
        except Exception:   # an animation is never a reason for the plot not to show
            return False
        if not any(step[0] == 'move' for step in steps):
            return False
        self.steps = steps
        self.grow, self.whole = grow, artists is None and axes is None
        self.active = True
        self.progress = 0.0
        self._animation.start()
        canvas.update()
        return True

    def _drawn(self, figure, moving, revive):
        """The figure's images (_steps), each drawn alone - reduced and cut as the figure's own image is."""
        canvas = self.canvas
        ratio = canvas.device_pixel_ratio or 1.0
        w, h = figure.bbox.size
        revived = {id(a) for a in revive}
        made = []

        def draw(artists):
            renderer = RendererAgg(w, h, figure.dpi)
            for artist in artists:
                if id(artist) in revived:   # gone from the figure already: drawn as it was
                    artist._visible = True
                    try:
                        artist.draw(renderer)
                    finally:
                        artist._visible = False
                else:
                    artist.draw(renderer)
            return pixels(renderer)

        def all_of(_renderer):
            for step in _steps(figure, moving):
                if isinstance(step, tuple):
                    image = draw(step[1])
                    alpha = image[..., 3]
                    rows = np.flatnonzero(alpha.any(axis=1))
                    if not len(rows):
                        continue
                    columns = np.flatnonzero(alpha.any(axis=0))
                    top, left = int(rows.min()), int(columns.min())
                    cut = image[top:int(rows.max()) + 1, left:int(columns.max()) + 1]
                    made.append(('still', _fast(_qimage(cut, ratio)), QtCore.QPointF(left / ratio, top / ratio)))
                    continue
                for way, ax, artists in step:
                    image = draw(artists)
                    box = ax.bbox
                    top, bottom = max(int(np.floor(h - box.y1)), 0), min(int(np.ceil(h - box.y0)), image.shape[0])
                    left, right = max(int(np.floor(box.x0)), 0), min(int(np.ceil(box.x1)), image.shape[1])
                    cut = image[top:bottom, left:right]
                    if cut.size and cut[..., 3].any():
                        made.append(('move', way, _fast(_qimage(cut, ratio)), (left, top, right, bottom),
                                     {way: _baseline(ax, way) for way in ('up', 'right')}))

        render = getattr(canvas, '_render_figure', None)
        render(None, all_of) if render is not None else all_of(None)
        self.height, self.ratio = h, ratio
        return made

    def stop(self):
        if self._animation.state() == QtCore.QAbstractAnimation.State.Running:
            self._animation.stop()
        if self.active:
            self.active = False
            self.steps = []
            self.canvas.update()

    def _frame(self, value):
        self.progress = float(value)
        self.canvas.update()

    def paint(self, painter):
        """This frame, over the whole canvas - True if there's one (the canvas paints nothing else)."""
        if not self.active or not self.steps:
            return False
        ratio, height = self.ratio, self.height
        t = self.progress if self.grow else 1.0 - self.progress
        painter.setRenderHint(QtGui.QPainter.RenderHint.SmoothPixmapTransform)
        for step in self.steps:
            if step[0] == 'still':
                painter.drawImage(step[2], step[1])
                continue
            _, mode, image, (left, top, right, bottom), bases = step
            source = QtCore.QRectF(0, 0, right - left, bottom - top)   # in the image's pixels
            target = QtCore.QRectF(left / ratio, top / ratio, (right - left) / ratio, (bottom - top) / ratio)
            painter.save()
            if mode == 'fade':
                painter.setOpacity(t)
            elif mode == 'wipe':   # drawn from x = 0 to the right, as far as it's got (taken back the same way)
                source.setWidth(source.width() * t)
                target.setWidth(target.width() * t)
            else:
                painter.setOpacity(min(1.0, 0.25 + 1.5 * t))
                squeeze = max(t, 1e-3)
                if mode == 'up':
                    at = (height - bases['up']) / ratio
                    top_at, bottom_at = at + (target.top() - at) * squeeze, at + (target.bottom() - at) * squeeze
                    target = QtCore.QRectF(target.left(), top_at, target.width(), bottom_at - top_at)
                else:
                    at = bases['right'] / ratio
                    left_at, right_at = at + (target.left() - at) * squeeze, at + (target.right() - at) * squeeze
                    target = QtCore.QRectF(left_at, target.top(), right_at - left_at, target.height())
            if source.width() > 0 and target.width() > 0:
                painter.drawImage(target, image, source)
            painter.restore()
        return True
