"""Many points, drawn fast - and every one of them, unless drawing them would take too long.
A line with more markers than MANY has only the markers drawn that show: one for each pixel the points
fall on in the view as it is - so zoomed in, every point there is drawn again. Its data isn't touched
(the panels, the inspector and the limits see it all); only which markers are drawn. While the view
moves it draws every nth marker instead, and the proper ones once it stops.
What a draw costs is estimated before it starts (estimate(): the points of each shown series, a marker
counting as MARKER_COST points of a line, times the seconds a point took in this window's last
draws). One that would take longer than ASK_S isn't started: a panel over the figure lists its large
series - plot, series, how many points - and asks whether to draw all of them or a reduced set, every
nth point, drawn in about REDUCED_S. That's asked when the window opens too, and again whenever a run
makes the figure much larger than what was agreed. The reduced set is only what's drawn: the series
keep all their points, which statistics, values, the inspector and saved files use; and each plot
drawn reduced says so in one red label on its tab (badges(); its More info: ReducedInfo).
Agg keeps Python's lock (the GIL) through each call that draws, and a figure drawn in a thread of its
own still stops the window for as long as one call takes - a million markers, a second. chunked()
makes the renderer draw large paths, markers and collections a part at a time, so the window answers
between parts - and the draw can be followed (progress) and stopped (Cancelled)."""
import contextlib
import math

import numpy as np
from matplotlib.path import Path
from PySide6 import QtCore, QtWidgets

from . import _series, _style

Qt = QtCore.Qt
MANY = 5000                 # a line with more markers than this: only those that show are drawn
MOVING_MARKERS = 20000      # while the view moves, about this many of them
MARKER_COST = 10            # a marker takes as long to draw as this many points of a line
BAR_COST = 400              # ... and a bar (a patch of its own)
RATE = 1.1e-7               # seconds a point of a line takes - until the window has timed its own draws
ASK_S = 2.5                 # a figure that would take longer than this to draw: asked first
REDUCED_S = 0.6             # a reduced set: drawn in about this long
MARKER_CHUNK = 10_000       # drawn a part at a time: markers, a collection's items... (small: the
LINE_CHUNK = 100_000        # window's turn comes between two parts) ... and a line's points
PREPARE_CHUNK = 500_000     # so many points at a time looked at for the markers that show


def _size(values):
    """How many values - without making an array of a list (len() of a list is free)."""
    try:
        return len(values)
    except TypeError:
        return int(np.size(values))


def prepare(figure, moving=False, rate=RATE, cancelled=None):
    """Before a draw: each line with many markers marks only the points that show. Gives whether any
    was drawn the quick way (moving), to be drawn properly once the view stops. Drawn reduced: nothing
    to mark (reduced() lets matplotlib mark them). cancelled() True: stops (Cancelled) between parts."""
    if _plan(figure, rate):
        return False
    rough = False
    for ax in figure.axes:
        if ax.get_visible():
            for line in ax.lines:
                rough = _markers(line, ax, moving, cancelled) or rough
    return rough


def _shows_markers(line):
    return line.get_marker() not in (None, '', ' ', 'None', 'none') and line.get_markersize() > 0


def _markers(line, ax, moving, cancelled=None):
    if not hasattr(line, '_csn_own_markevery'):
        line._csn_own_markevery = line.get_markevery()
    if line._csn_own_markevery is not None:   # the script chose which: as it said
        return False
    shows = line.get_visible() and _shows_markers(line)
    count = _size(line.get_xdata(orig=True)) if shows else 0
    if count <= MANY:
        if getattr(line, '_csn_marking', False):   # ours no longer needed: matplotlib's own way again
            line._markevery, line._csn_marking, line._csn_marked = None, False, None
            line._invalidx = True
        return False
    if not getattr(line, '_csn_marking', False):
        line._csn_marking = True
        line._subslice = False   # the indices are into all the points: no drawing a slice of them
        line._transformed_path = None
    if moving:
        line._markevery = max(1, count // MOVING_MARKERS)
        line._csn_marked = None
        return True
    box = ax.bbox
    signature = (id(line._xy), count, tuple(ax.viewLim.bounds), tuple(box.bounds), ax.get_xscale(), ax.get_yscale(),
                 line.get_markersize())
    if getattr(line, '_csn_marked', None) == signature:
        return False
    points, transform = line.get_xydata(), line.get_transform()
    reach = line.get_markersize() * ax.figure.dpi / 72
    tall = int(box.height + 2 * reach) + 2
    keys, indices = [], []
    for start in range(0, count, PREPARE_CHUNK):   # a part at a time: Stop heard, the window answers
        if cancelled is not None and cancelled():
            raise Cancelled()
        pixels = transform.transform(points[start:start + PREPARE_CHUNK])
        x, y = pixels[:, 0], pixels[:, 1]
        inside = np.flatnonzero(np.isfinite(x) & np.isfinite(y) & (x >= box.x0 - reach) & (x <= box.x1 + reach)
                                & (y >= box.y0 - reach) & (y <= box.y1 + reach))
        if len(inside):
            column = np.floor(x[inside] - box.x0 + reach).astype(np.int64)
            row = np.floor(y[inside] - box.y0 + reach).astype(np.int64)
            key, first = np.unique(column * tall + row, return_index=True)   # a pixel's first point, in this part
            keys.append(key)
            indices.append(inside[first] + start)
    if keys:   # in order of the parts: a pixel's first point of all
        _, first = np.unique(np.concatenate(keys), return_index=True)
        inside = np.sort(np.concatenate(indices)[first])
    else:
        inside = np.zeros(0, dtype=np.int64)
    line._markevery = inside
    line._csn_marked = signature
    return False


# ---- what a draw costs

def _shown(ax, artist):
    return ax.get_visible() and artist.get_visible()


def _costs(figure):
    """[(axes, artist, points, cost in points of a line)] of every shown series."""
    found = []
    for ax in figure.axes:
        if not ax.get_visible():
            continue
        area = max(ax.bbox.width * ax.bbox.height, 1.0)
        for line in ax.lines:
            if not line.get_visible():
                continue
            n = _size(line.get_xdata(orig=True))
            cost = n if line.get_linestyle() not in ('', ' ', 'None', 'none') else 0
            if _shows_markers(line):
                drawn = min(n, area / 4) if n > MANY and line.get_markevery() is None or \
                    getattr(line, '_csn_marking', False) else n
                cost += drawn * MARKER_COST + (3 * n if n > MANY else 0)   # finding which show: about 3 a point
            found.append((ax, line, n, cost))
        for collection in ax.collections:
            if not collection.get_visible():
                continue
            try:
                offsets = collection.get_offsets()
                n = len(offsets) if offsets is not None and len(offsets) > 1 else \
                    sum(len(p.vertices) for p in collection.get_paths())
            except (TypeError, AttributeError):
                continue
            found.append((ax, collection, n, n * MARKER_COST))
        from matplotlib.container import BarContainer   # here: a bar chart counted as a series of its own
        contained = set()
        for container in ax.containers:
            if isinstance(container, BarContainer):
                contained.update(id(patch) for patch in container.patches)
                bars = sum(1 for patch in container.patches if patch.get_visible())
                if bars:
                    found.append((ax, container, bars, bars * BAR_COST))
        bars = sum(1 for patch in ax.patches if patch.get_visible() and id(patch) not in contained)
        if bars:   # patches of no bar chart
            found.append((ax, None, bars, bars * BAR_COST))
    return found


def count(figure):
    """How many points the figure's shown series have (a bar is one)."""
    return sum(n for _, _, n, _ in _costs(figure))


def units(figure):
    return sum(cost for *_, cost in _costs(figure))


def estimate(figure, rate=RATE):
    """Seconds drawing the figure would take - its series as they are, all their points."""
    return units(figure) * rate


def big_series(figure):
    """[(plot name, series name, points)] of the figure's shown series of more than MANY points,
    largest first."""
    found, names = [], {}
    for ax, artist, n, _ in _costs(figure):
        if artist is None or n <= MANY:
            continue
        if ax not in names:
            names[ax] = {id(s.artist): s.label for s in _series.series(ax, everything=True)}
        found.append((_series.plot_name(_main(ax)), names[ax].get(id(artist), artist.get_label()), n))
    return sorted(found, key=lambda item: -item[2])


def _main(ax):
    return getattr(ax, '_csn_main', None) or ax


def every_nth(figure, rate=RATE):
    """The n of 'every nth point' a reduced set keeps: drawn in about REDUCED_S."""
    return max(2, math.ceil(units(figure) * rate / REDUCED_S))


def allowed(canvas):
    """Whether the figure can be drawn now. One that would take too long asks first - unless what's
    been answered still holds: a reduced set, always; all points, until it's much larger than it was."""
    figure = canvas.figure
    rate = getattr(canvas, 'draw_rate', RATE)
    cost = units(figure)
    if cost * rate <= ASK_S:
        return True
    answer = getattr(figure, '_csn_big', None)
    if answer is not None and (answer[0] == 'reduced' or cost <= answer[1] * 1.5):
        return True
    canvas.big_veil.ask()
    return False


def drawn_points(figure, rate=RATE):
    """How many points the next draw draws - fewer than count() if it's drawn reduced."""
    plan = _plan(figure, rate)
    return sum(min(n, math.ceil(n / plan)) if plan and n > MANY and not hasattr(artist, 'patches') else n
               for _, artist, n, _ in _costs(figure))   # bars are drawn all, reduced or not


def _plan(figure, rate):
    """Every how many points a reduced draw keeps - None: all of them."""
    answer = getattr(figure, '_csn_big', None)
    if answer is None or answer[0] != 'reduced' or units(figure) * rate <= ASK_S:
        return None
    return every_nth(figure, rate)


@contextlib.contextmanager
def reduced(figure, rate=RATE):
    """While the figure's drawn: if it's drawn reduced, its large series have every nth point - their
    own put back after. Their arrays are swapped in place, not copied (nothing sees them change)."""
    swapped, shown = [], {}
    every = _plan(figure, rate)
    if every:
        for ax in figure.axes:
            for line in ax.lines:
                x, y = line._xorig, line._yorig
                if _size(x) > MANY:
                    swapped.append((line, x, y, getattr(line, '_csn_marking', False), line._markevery))
                    line._xorig, line._yorig = np.asarray(x)[::every], np.asarray(y)[::every]
                    line._invalidx = line._invalidy = True
                    if getattr(line, '_csn_marking', False):   # its marked points were of all of them
                        line._markevery, line._csn_marking, line._csn_marked = None, False, None
                    shown.setdefault(ax, []).append((_size(x), _size(line._xorig)))
            for collection in ax.collections:
                offsets = getattr(collection, '_offsets', None)
                if offsets is not None and len(offsets) > MANY:
                    swapped.append((collection, offsets, None, None, None))
                    collection._offsets = offsets[::every]
                    shown.setdefault(ax, []).append((len(offsets), len(collection._offsets)))
    figure._csn_reduced = (every, shown) if shown else None
    try:
        yield
    finally:
        for thing, first, second, marking, markevery in swapped:
            if second is None:
                thing._offsets = first
            else:
                thing._xorig, thing._yorig = first, second
                thing._invalidx = thing._invalidy = True
                thing._markevery, thing._csn_marking, thing._csn_marked = markevery, marking, None


def badges(figure):
    """[(axes, points drawn, points it has, every how many drawn)] for each plot drawn reduced."""
    reduced_now = getattr(figure, '_csn_reduced', None)
    if not reduced_now:
        return []
    every, shown = reduced_now
    found = {}
    for ax, counts in shown.items():
        main = _main(ax)
        drawn, total = found.get(main, (0, 0))
        found[main] = (drawn + sum(c[1] for c in counts), total + sum(c[0] for c in counts))
    return [(ax, drawn, total, every) for ax, (drawn, total) in found.items()]


class ReducedInfo(QtWidgets.QDialog):
    """What the red label's More info opens: which plots are drawn reduced and by how much - and,
    out of the way and asked again first, drawing every point."""

    def __init__(self, canvas):
        super().__init__(canvas.window())
        self.canvas = canvas
        self.setWindowTitle('Not all points shown')
        figure = canvas.figure
        rows = badges(figure)
        from ._series import plot_name
        listed = ''.join(f"<tr><td style='color:{_style.TEXT_2}; padding-right:14px'>{plot_name(ax)}</td>"
                         f"<td align='right' style='color:{_style.TEXT}'>{drawn:,} of {total:,} points drawn</td></tr>"
                         for ax, drawn, total, _ in rows)
        every = rows[0][3] if rows else 1
        text = QtWidgets.QLabel(
            f"<p>To keep the window quick, these plots draw every {_nth(every)} of their points:</p>"
            f"<table>{listed}</table>"
            f"<p style='color:{_style.TEXT_2}'>Only the drawing is reduced. Statistics, the values in the Data "
            f"tab, the point inspector and saved files all use every point.</p>")
        text.setTextFormat(Qt.TextFormat.RichText)
        text.setWordWrap(True)
        text.setMinimumWidth(380)
        close = QtWidgets.QPushButton('Close')
        close.setDefault(True)
        close.clicked.connect(self.accept)
        everything = QtWidgets.QPushButton('Draw every point…')
        everything.setToolTip('Asks first: with this many points the window can freeze, or run out of memory')
        everything.clicked.connect(self._everything)
        buttons = QtWidgets.QHBoxLayout()
        buttons.addWidget(everything)
        buttons.addStretch(1)
        buttons.addWidget(close)
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 16)
        layout.setSpacing(14)
        layout.addWidget(text)
        layout.addLayout(buttons)

    def _everything(self):
        figure = self.canvas.figure
        rate = getattr(self.canvas, 'draw_rate', RATE)
        box = QtWidgets.QMessageBox(QtWidgets.QMessageBox.Icon.Warning, 'Draw every point?',
                                    f"Drawing all {count(figure):,} points would take about "
                                    f"{_seconds(estimate(figure, rate))}, and the window may freeze meanwhile - "
                                    f"with very many points the program can even run out of memory and close.",
                                    parent=self)
        keep = box.addButton('Keep it reduced', QtWidgets.QMessageBox.ButtonRole.RejectRole)
        draw = box.addButton('Draw every point', QtWidgets.QMessageBox.ButtonRole.DestructiveRole)
        box.setDefaultButton(keep)
        box.setEscapeButton(keep)
        box.exec()
        if box.clickedButton() is draw:
            figure._csn_big = ('all', units(figure))
            self.accept()
            self.canvas.say('Drawing every point')
            self.canvas.draw_idle()


def _nth(n):
    suffix = 'th' if 10 <= n % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')
    return f"{n:,}{suffix}"


def _seconds(s):
    return f"{s:.1f} s" if s < 10 else f"{s:.0f} s" if s < 120 else f"{s / 60:.0f} min"


# ---- drawing a part at a time

class Cancelled(Exception):
    """A draw stopped between two of its parts."""


def chunked(renderer, progress=None, cancelled=None):
    """The renderer drawing large paths, markers and collections a part at a time - between parts the
    window has Python's lock and answers. progress(cost) after each part; cancelled() True: the draw
    stops (Cancelled) at the next one."""
    inner = renderer._renderer
    markers, collection, path = inner.draw_markers, inner.draw_path_collection, renderer.draw_path

    def done(cost):
        if progress is not None:
            progress(cost)
        if cancelled is not None and cancelled():
            raise Cancelled()

    def draw_markers(gc, marker_path, marker_trans, data, trans, *rest):
        vertices, codes = data.vertices, data.codes
        n = len(vertices)
        for start in range(0, max(n, 1), MARKER_CHUNK):
            stop = min(start + MARKER_CHUNK, n)
            part = data if n <= MARKER_CHUNK else \
                Path(vertices[start:stop], None if codes is None else codes[start:stop])
            markers(gc, marker_path, marker_trans, part, trans, *rest)
            done((stop - start) * MARKER_COST)

    def draw_path(gc, data, transform, rgbFace=None):
        vertices, codes = data.vertices, data.codes
        n = len(vertices)
        plain = codes is None or bool(np.all((codes == Path.MOVETO) | (codes == Path.LINETO)))
        if n <= LINE_CHUNK or rgbFace is not None or gc.get_hatch() is not None or not plain:
            path(gc, data, transform, rgbFace)
            done(n)
            return
        for start in range(0, n - 1, LINE_CHUNK):
            stop = min(start + LINE_CHUNK + 1, n)   # each part from where the last ended: no gap
            part_codes = None
            if codes is not None:
                part_codes = codes[start:stop].copy()
                part_codes[0] = Path.MOVETO
            part = Path(vertices[start:stop], part_codes)
            part.should_simplify = data.should_simplify
            part.simplify_threshold = data.simplify_threshold
            path(gc, part, transform, rgbFace)
            done(stop - start)

    def draw_path_collection(gc, master, paths, transforms, offsets, offset_trans, faces, edges, widths, styles,
                             antialiased, urls, position):
        offsets = np.asarray(offsets)
        n = len(offsets)
        if n <= MARKER_CHUNK:
            collection(gc, master, paths, transforms, offsets, offset_trans, faces, edges, widths, styles,
                       antialiased, urls, position)
            done(max(n, 1) * MARKER_COST)
            return

        def part(values, start, stop):   # each item's own values, or values going round
            try:
                m = len(values)
            except TypeError:
                return values
            if m == n:
                return values[start:stop]
            if m <= 1:
                return values
            picked = np.arange(start, stop) % m
            return values[picked] if isinstance(values, np.ndarray) else [values[i] for i in picked]
        for start in range(0, n, MARKER_CHUNK):
            stop = min(start + MARKER_CHUNK, n)
            collection(gc, master, part(paths, start, stop), part(transforms, start, stop), offsets[start:stop],
                       offset_trans, part(faces, start, stop), part(edges, start, stop), part(widths, start, stop),
                       part(styles, start, stop), part(antialiased, start, stop), part(urls, start, stop), position)
            done((stop - start) * MARKER_COST)

    renderer.draw_markers = draw_markers
    renderer.draw_path = draw_path
    renderer.draw_path_collection = draw_path_collection
    return renderer


# ---- asking first

class BigVeil(QtWidgets.QFrame):
    """Over a figure that would take too long to draw, before it's drawn: which series are large, and
    what to draw."""

    LISTED = 8   # the largest series named; the rest counted

    def __init__(self, canvas):
        super().__init__(canvas)
        self.canvas = canvas
        self.setObjectName('csnBig')
        self.setStyleSheet(f"QFrame#csnBig {{ background: {_style.RAISED}; border: 1px solid {_style.BORDER};"
                           f" border-radius: 10px; }}")
        self.title = QtWidgets.QLabel()
        self.title.setObjectName('csnHeading')
        self.message = QtWidgets.QLabel()
        self.message.setWordWrap(True)
        self.message.setTextFormat(Qt.TextFormat.RichText)
        self.reduce = QtWidgets.QPushButton()
        self.reduce.setProperty('csnHighlight', True)
        self.reduce.clicked.connect(lambda: self._answer('reduced'))
        self.everything = QtWidgets.QPushButton()
        self.everything.clicked.connect(lambda: self._answer('all'))
        note = QtWidgets.QLabel('A reduced set changes only what is drawn: statistics, values, the point '
                                'inspector and saved files use all points. A red label on the tab says so.')
        note.setObjectName('csnHint')
        note.setWordWrap(True)
        skip = QtWidgets.QToolButton()
        skip.setText('×')
        skip.setAutoRaise(True)
        skip.setCursor(Qt.CursorShape.PointingHandCursor)
        skip.setToolTip("Don't draw these series: they're hidden (show them again in the Data tab)")
        skip.setStyleSheet(f"QToolButton {{ color: {_style.TEXT_3}; font-size: 18px; border: none; padding: 0 4px; }}"
                           f"QToolButton:hover {{ color: {_style.TEXT}; }}")
        skip.clicked.connect(self._skip)
        top = QtWidgets.QHBoxLayout()
        top.addWidget(self.title, 1)
        top.addWidget(skip, 0, Qt.AlignmentFlag.AlignTop)
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(22, 18, 14, 18)
        layout.setSpacing(10)
        layout.addLayout(top)
        layout.addWidget(self.message)
        layout.addWidget(self.reduce)
        layout.addWidget(self.everything)
        layout.addWidget(note)
        self.hide()

    def ask(self, stopped=False):
        if self.isVisible():
            return
        figure = self.canvas.figure
        rate = getattr(self.canvas, 'draw_rate', RATE)
        total, every = count(figure), every_nth(figure, rate)
        rows = big_series(figure)
        listed = ''.join(f"<tr><td style='color:{_style.TEXT_3}; padding-right:12px'>{plot}</td>"
                         f"<td style='color:{_style.TEXT}; padding-right:12px'>{name}</td>"
                         f"<td align='right' style='color:{_style.TEXT}'>{n:,}</td></tr>"
                         for plot, name, n in rows[:self.LISTED])
        more = f"<p style='color:{_style.TEXT_3}'>and {len(rows) - self.LISTED} more series</p>" \
            if len(rows) > self.LISTED else ''
        seconds = estimate(figure, rate)
        self.title.setText('Drawing stopped' if stopped else f"{total:,} points in this figure")
        self.message.setText(f"<p style='color:{_style.TEXT_2}'>Drawing all of them would take about "
                             f"{_seconds(seconds)}, and the window would be slow meanwhile. The large series:</p>"
                             f"<table>{listed}</table>{more}")
        self.reduce.setText(f"Draw a reduced set: every {_nth(every)} point ({max(total // every, 1):,} points)")
        self.everything.setText(f"Draw all {total:,} points (about {_seconds(seconds)})")
        self.setFixedWidth(min(560, max(self.canvas.width() - 40, 300)))
        self.adjustSize()
        self.move((self.canvas.width() - self.width()) // 2, (self.canvas.height() - self.height()) // 3)
        self.show()
        self.raise_()

    def _answer(self, answer):
        self.canvas.figure._csn_big = (answer, units(self.canvas.figure))
        self.hide()
        self.canvas.draw_idle()

    def _skip(self):
        """The × : the largest series not drawn at all, as many as it takes for the figure to be drawn
        without asking - hidden (an undo, or the Data tab, shows them again)."""
        from . import _view   # here: the view module draws on this one's
        figure = self.canvas.figure
        rate = getattr(self.canvas, 'draw_rate', RATE)
        left = units(figure)
        for ax, artist, n, cost in sorted(_costs(figure), key=lambda item: -item[3]):
            if left * rate <= ASK_S:
                break
            s = None if artist is None else next(
                (s for s in _series.series(ax, everything=True) if s.artist is artist), None)
            if s is not None:
                _view.set_visible(_series.key_of(s), False)
            elif artist is None or hasattr(artist, 'patches'):   # bars of no series: their patches
                for patch in (artist.patches if artist is not None else
                              [p for p in ax.patches if not any(p in c for c in ax.containers)]):
                    patch.set_visible(False)
            else:
                artist.set_visible(False)
            left -= cost
        self.hide()
        self.canvas.say('The large series are hidden. Show them again in the Data tab')
        self.canvas.draw_idle()
        self.canvas.update()
