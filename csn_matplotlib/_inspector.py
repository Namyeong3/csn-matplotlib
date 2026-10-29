"""What's under the pointer, marked over the plot by blitting, so it follows the pointer without
redrawing the figure; after a full redraw (a zoom, a resize) it's drawn on top again. Each kind of
series is marked as it's drawn:
  - a point (markers, a scatter, a stem): a ring round it, and a label (series, index, x, y);
  - a line without markers: the whole line glows - no made-up point on it - with the x and y of its
    place nearest the pointer;
  - a step or a bar: the step or the bar itself, lit from its base up.
What's picked is marked in MARK, unlike any series' colour; a glow is a lighter tint of the series' own.
A line is found anywhere along it (within LINE_REACH_PX), not only at its points; a click on a
legend entry finds its series too. A click on something pins it, picks its series
(canvas.pick_series: the panels show it, the sliders the parameters of its run) and the data panel
goes to its row; a row picked in the panel is pinned the same way. A click on nothing lets go.
glow() lights whole series - the one edited in the Plot tab, the one hovered in the data panel. In a
plot shown up to an x (_upto), the points past it aren't there to find; a series of more than
SAMPLED points is searched through every nth of them. Nothing's found or drawn while the figure is
drawn in the background."""
import math

import numpy as np
from matplotlib.collections import PolyCollection
from matplotlib.lines import Line2D
from matplotlib.text import Text
from matplotlib.transforms import IdentityTransform

from . import _series, _style, _upto

NONE = ('', ' ', 'None', 'none', None)


def _markers(s):
    """Whether the series is drawn as points one can point at."""
    if s.kind in ('scatter', 'area') or s.stem:
        return True
    return s.kind == 'line' and s.artist.get_marker() not in NONE


def _line(s):
    return (s.kind == 'line' and not s.stem and s.artist.get_linestyle() not in NONE
            and s.artist.get_linewidth() > 0)


def _steps(s):
    return _line(s) and str(s.artist.get_drawstyle()).startswith('steps')


class Inspector:
    REACH_PX = 14         # how near the pointer a point has to be
    LINE_REACH_PX = 7     # ... and a line, between its points
    MARK = '#ffffff'      # what's picked: unlike every series colour (_style.SERIES)
    OFFSET_PX = 14        # the label, off the point
    SAMPLED = 2_000_000   # a series of more points: every nth searched
    GLOW_POINTS = 30_000   # a glowing series of more points: every nth lit (a wide faint line needs no more)

    def __init__(self, canvas):
        self.canvas = canvas
        self.panel = None            # the window's data panel, once there is one
        self.hover = self.pinned = None   # (Series, index)
        self._how = {'hover': ('point', None), 'pinned': ('point', None)}   # how it's marked, and where
        self._glows = {}             # 'picked' / 'panel' -> the series lit whole
        self._background = None
        self._lit = None   # (what glows, the image with it glowing) - drawn once, not at each move
        self._series = {}            # axes -> its series, this draw's
        self._screens = {}           # id(artist) -> (its points on screen, their indices or None), this draw's
        self._marks = {}             # 'hover' / 'pinned' -> (ring, label)
        canvas.mpl_connect('draw_event', self._on_draw)

    # ---- asked from outside

    def hover_at(self, xy):
        if getattr(self.canvas, 'drawing', False):
            return
        found = self._find(xy)
        hit, how = (found[:2], found[2:]) if found else (None, ('point', None))
        old = self._how['hover']
        if not self._same(hit, self.hover) or how[0] != old[0] or \
                (how[1] is None) != (old[1] is None) or (how[1] is not None and not np.allclose(how[1], old[1])):
            self.hover, self._how['hover'] = hit, how
            self._draw_marks()

    def hover_at_cursor(self):
        if self.canvas.underMouse():
            self.hover_at(tuple(self.canvas.mouseEventCoords()))

    def clear_hover(self):
        if self.hover is not None:
            self.hover = None
            self._draw_marks()

    def click(self, xy):
        if getattr(self.canvas, 'drawing', False):
            return
        labels = getattr(self.canvas, 'labels', None)
        named = labels._handle_at(xy, texts=True) if labels is not None else None
        if named is not None:   # a legend entry: its series
            self.pinned = None
            self._draw_marks()
            self.canvas.pick_series(named)
            return
        found = self._find(xy)
        self.pinned = found[:2] if found else None
        self._how['pinned'] = found[2:] if found else ('point', None)
        self._draw_marks()
        if found is not None:
            s, index, how, _ = found
            self.canvas.pick_series(s, None if how == 'line' else index)

    def pin(self, series, index):
        """A point picked elsewhere (a row of the data panel): marked as a point, or its step or bar."""
        self.pinned = (series, index) if series is not None else None
        self._how['pinned'] = ('band' if series is not None and (series.kind == 'bars' or _steps(series))
                               else 'point', None)
        self._draw_marks()

    def glow(self, key, series):
        """Whole series lit ('picked': the one edited; 'panel': the one hovered in a panel) - [] for none."""
        series = [s for s in series if s is not None and s.ax.figure is self.canvas.figure]
        old = self._glows.get(key, [])
        if [s.artist for s in old] != [s.artist for s in series]:
            self._glows[key] = series
            self._draw_marks()

    def centre_on(self, series, index):
        """Pans the series' axes so the point is in the middle of it."""
        position = series.point(index)
        box = series.ax.bbox
        navigation = getattr(self.canvas, 'navigation', None)
        if navigation is not None and np.all(np.isfinite(position)):
            navigation._begin()
            navigation._pan([(series.ax, 'xy')], position[0] - (box.x0 + box.x1) / 2, position[1] - (box.y0 + box.y1) / 2)
            navigation._settle()

    # ---- finding

    def series_of(self, ax):
        if ax not in self._series:
            self._series[ax] = _series.series(ax)
        return self._series[ax]

    def _screen(self, s):
        """(points on screen, which of the series' points they are - None: all of them)."""
        key = id(s.artist)
        if key not in self._screens:
            count = len(s)
            if count > self.SAMPLED:
                every = math.ceil(count / self.SAMPLED)
                indices = np.arange(0, count, every)
                self._screens[key] = s.screen()[indices], indices
            else:
                self._screens[key] = s.screen(), None
        return self._screens[key]

    def _position(self, s, index):
        screen, indices = self._screen(s)
        if indices is None:
            return screen[index]
        return s.point(index)

    def _find(self, xy):
        """(series, index, how, where) of what's at the display point - how: 'point', 'line' (where:
        the nearest place on it) or 'band' (a step or a bar) - or None."""
        ratio = self.canvas.device_pixel_ratio or 1.0
        point = np.asarray(xy, dtype=float)
        best, best_distance = None, (self.REACH_PX * ratio) ** 2
        band = line = None
        line_distance = (self.LINE_REACH_PX * ratio) ** 2
        for ax in self.canvas.figure.axes:
            if not ax.get_visible() or not ax.bbox.contains(*xy):
                continue
            cut = _upto.edge(ax)
            if cut is not None and (xy[0] < cut if ax.xaxis_inverted() else xy[0] > cut):
                continue   # past where it's shown up to: nothing there
            for s in self.series_of(ax):
                if not s.visible():
                    continue
                if s.kind == 'bars':
                    for index, rect in enumerate(s.artist.patches):
                        if band is None and rect.get_visible() and rect.get_window_extent().contains(*xy):
                            band = (s, index, 'band', None)
                    continue
                screen, indices = self._screen(s)
                if not len(screen):
                    continue
                if _markers(s):
                    offsets = screen - point
                    distances = np.einsum('ij,ij->i', offsets, offsets)
                    if not np.isnan(distances).all():
                        index = int(np.nanargmin(distances))
                        if distances[index] < best_distance:
                            best_distance = distances[index]
                            best = (s, int(indices[index]) if indices is not None else index, 'point', None)
                if _steps(s) and band is None:
                    found = self._step_at(s, screen, indices, point)
                    if found is not None:
                        band = (s, found, 'band', None)
                elif _line(s) and len(screen) > 1:
                    found = self._segment_at(screen, point)
                    if found is not None and found[0] < line_distance:
                        line_distance = found[0]
                        index = found[1]
                        line = (s, int(indices[index]) if indices is not None else index, 'line', found[2])
        return best or band or line

    @staticmethod
    def _segment_at(screen, point):
        """(squared distance, index of the nearer end, the nearest place) of the polyline's nearest
        segment to the point - None if it has none drawn."""
        a, b = screen[:-1], screen[1:]
        d = b - a
        lengths = np.einsum('ij,ij->i', d, d)
        with np.errstate(invalid='ignore', divide='ignore'):
            t = np.clip(np.einsum('ij,ij->i', point - a, d) / lengths, 0.0, 1.0)
        t = np.where(lengths > 0, t, 0.0)
        nearest = a + d * t[:, None]
        gaps = nearest - point
        distances = np.einsum('ij,ij->i', gaps, gaps)
        if np.isnan(distances).all():
            return None
        k = int(np.nanargmin(distances))
        return float(distances[k]), k + (1 if t[k] > 0.5 else 0), nearest[k]

    def _step_extent(self, s, screen, k):
        """A step's left and right edge on screen, as its drawstyle draws it."""
        xs = screen[:, 0]
        n = len(xs)
        style = str(s.artist.get_drawstyle())
        if style == 'steps-mid':
            left = (xs[k - 1] + xs[k]) / 2 if k > 0 else xs[k] - (xs[1] - xs[0]) / 2
            right = (xs[k] + xs[k + 1]) / 2 if k < n - 1 else xs[k] + (xs[k] - xs[k - 1]) / 2
        elif style == 'steps-post':
            left, right = xs[k], xs[k + 1] if k < n - 1 else xs[k] + (xs[k] - xs[k - 1])
        else:   # steps, steps-pre: the step ends at its point
            left, right = (xs[k - 1] if k > 0 else xs[k] - (xs[1] - xs[0])), xs[k]
        return min(left, right), max(left, right)

    def _step_at(self, s, screen, indices, point):
        if len(screen) < 2:
            return None
        xs = screen[:, 0]
        order = np.argsort(xs, kind='stable')
        near = int(np.clip(np.searchsorted(xs[order], point[0]), 0, len(xs) - 1))
        base = self._base(s)
        for k in {int(order[max(near - 1, 0)]), int(order[near]), int(order[min(near + 1, len(xs) - 1)])}:
            left, right = self._step_extent(s, screen, k)
            top = screen[k, 1]
            low, high = min(base, top), max(base, top)
            if left <= point[0] <= right and low - 4 <= point[1] <= high + 4:
                return int(indices[k]) if indices is not None else k
        return None

    def _base(self, s):
        """Where a step's or a bar's base is on screen: y = 0, or the plot's bottom if 0 isn't in it."""
        box = s.ax.bbox
        try:
            zero = s.ax.transData.transform((0, 0))[1] if s.ax.get_yscale() == 'linear' else None
        except (ValueError, OverflowError):
            zero = None
        if zero is None or not np.isfinite(zero):
            return box.y0
        return float(np.clip(zero, box.y0, box.y1))

    @staticmethod
    def _same(a, b):
        return (a is None and b is None) or (a is not None and b is not None
                                             and a[0].artist is b[0].artist and a[1] == b[1])

    # ---- drawing

    def _on_draw(self, event):
        if self.canvas.is_saving():   # a savefig / the copied image: no marks on it
            return
        self._series.clear()
        self._screens.clear()
        for key in ('hover', 'pinned'):   # their series may be new objects now: find them again
            hit = getattr(self, key)
            if hit is not None:
                again = self._again(hit[0])
                setattr(self, key, (again, hit[1]) if again is not None and hit[1] < len(again) else None)
        for key, series in list(self._glows.items()):
            self._glows[key] = [a for a in (self._again(s) for s in series) if a is not None]
        self._background = self.canvas.copy_from_bbox(self.canvas.figure.bbox)
        self._lit = None
        self._draw_marks(blit=False)

    def _again(self, s):
        """The series as it is after a draw - the same artist, or, drawn again, the same label."""
        if s.ax.figure is not self.canvas.figure:
            return None
        candidates = self.series_of(s.ax)
        return next((c for c in candidates if c.artist is s.artist), None) or \
            next((c for c in candidates if c.label == s.label), None)

    def _draw_marks(self, blit=True):
        canvas = self.canvas
        if blit and (self._background is None or getattr(canvas, 'drawing', False)):
            return
        lit = []
        for key in ('picked', 'panel'):
            lit += [s for s in self._glows.get(key, []) if s.artist not in [x.artist for x in lit]]
        for key in ('pinned', 'hover'):   # a line found between its points: it glows whole
            hit = getattr(self, key)
            if hit is not None and self._how[key][0] == 'line' and hit[0].artist not in [x.artist for x in lit]:
                lit.append(hit[0])
        lit = [s for s in lit if s.ax.get_visible() and s.visible()]
        which = tuple(id(s.artist) for s in lit)
        if blit and self._lit is not None and self._lit[0] == which:
            canvas.restore_region(self._lit[1])   # glowing already: only the marks over it drawn again
        else:
            if blit:
                canvas.restore_region(self._background)
            for s in lit:
                for artist in self._glow_of(s):
                    canvas.figure.draw_artist(artist)
            self._lit = (which, canvas.copy_from_bbox(canvas.figure.bbox) if lit else self._background)
        for key, accent in (('pinned', self.MARK), ('hover', _style.TEXT_2)):
            hit = getattr(self, key)
            if hit is None or (key == 'hover' and self._same(hit, self.pinned) and self._how['pinned'][0] != 'line'):
                continue
            how, where = self._how[key]
            if key == 'pinned' and how == 'line':
                continue   # the line glows
            try:
                self._mark(key, accent, hit, how, where)
            except (IndexError, ValueError):
                continue
        if blit:
            canvas.blit(canvas.figure.bbox)

    def _mark(self, key, accent, hit, how, where):
        canvas = self.canvas
        s, index = hit
        ring, label = self._marks_for(key, accent)
        if how == 'line' and where is not None:   # the line glows: only its x and y here, no point
            position = np.asarray(where, dtype=float)
            x, y = s.artist.get_transform().inverted().transform(position)
            self._place(label, s, position, f"{s.label}\nx  {_series.text(x)}\ny  {_series.text(y)}")
            canvas.figure.draw_artist(label)
            return
        position = self._position(s, index) if s.kind != 'bars' else None
        if how == 'band':
            rect = self._band(s, index)
            if rect is None:
                return
            box = PolyCollection([rect], transform=IdentityTransform(), facecolor=accent, edgecolor=accent,
                                 linewidth=1.6, alpha=0.18 if key == 'pinned' else 0.12)
            box.set_figure(canvas.figure)
            box.set_clip_box(s.ax.bbox)
            canvas.figure.draw_artist(box)
            edge = PolyCollection([rect], transform=IdentityTransform(), facecolor='none', edgecolor=accent,
                                  linewidth=2.0 if key == 'pinned' else 1.4)
            edge.set_figure(canvas.figure)
            edge.set_clip_box(s.ax.bbox)
            canvas.figure.draw_artist(edge)
            top = max(rect, key=lambda p: p[1])
            position = np.array([(rect[0][0] + rect[2][0]) / 2, top[1]])
        elif not (np.all(np.isfinite(position)) and s.ax.bbox.contains(*position)):
            return
        else:
            ring.set_markersize(12)
            ring.set_markerfacecolor('none')
            ring.set_data([position[0]], [position[1]])
            canvas.figure.draw_artist(ring)
        x, y = s.data()
        names = ('value', 'at') if s.kind == 'bars' and getattr(s.artist, 'orientation', '') == 'horizontal' else \
                ('x', 'height') if s.kind == 'bars' else ('x', 'y')
        self._place(label, s, position,
                    f"{s.label}   #{index}\n{names[0]}  {_series.text(x[index])}\n{names[1]}  {_series.text(y[index])}")
        canvas.figure.draw_artist(label)

    def _band(self, s, index):
        """The step or bar, as a rectangle on screen ([4 corners])."""
        if s.kind == 'bars':
            box = s.artist.patches[index].get_window_extent()
            return [(box.x0, box.y0), (box.x0, box.y1), (box.x1, box.y1), (box.x1, box.y0)]
        screen, indices = self._screen(s)
        if indices is not None:
            k = int(np.searchsorted(indices, index))
            if k >= len(indices):
                return None
        else:
            k = index
        left, right = self._step_extent(s, screen, k)
        base, top = self._base(s), screen[k, 1]
        if not np.isfinite([left, right, top]).all():
            return None
        return [(left, base), (left, top), (right, top), (right, base)]

    def _glow_of(self, s):
        """What lights the whole series: a copy of it a little wider, in its own colour made lighter
        (_tint) - bars and areas outlined in it too, so they show over themselves."""
        figure = self.canvas.figure
        made = []
        halo = self._tint(s.colour())
        if s.kind == 'line':
            artist = s.artist
            x, y = artist.get_xdata(orig=False), artist.get_ydata(orig=False)
            if len(x) > self.GLOW_POINTS:
                every = math.ceil(len(x) / self.GLOW_POINTS)
                x, y = x[::every], y[::every]
            glow = Line2D(x, y, transform=artist.get_transform(), color=halo, alpha=0.55,
                          linewidth=artist.get_linewidth() + 3 if _line(s) else 0,
                          linestyle='-' if _line(s) else 'None', drawstyle=artist.get_drawstyle(),
                          solid_capstyle='butt', solid_joinstyle='round',   # no round blob where it ends or breaks
                          marker=artist.get_marker() if _markers(s) else 'None',
                          markersize=artist.get_markersize() + 4, markerfacecolor=halo, markeredgecolor=halo)
            glow.set_clip_path(s.ax.patch)
            made.append(glow)
        elif s.kind == 'scatter':
            offsets = np.asarray(s.artist.get_offsets(), dtype=float)
            if len(offsets) > self.GLOW_POINTS:
                offsets = offsets[::math.ceil(len(offsets) / self.GLOW_POINTS)]
            sizes = s.artist.get_sizes()
            size = math.sqrt(float(np.mean(sizes))) if len(sizes) else 6.0
            glow = Line2D(offsets[:, 0], offsets[:, 1], transform=s.artist.get_offset_transform(), linestyle='None',
                          marker='o', markersize=size + 5, markerfacecolor='none', markeredgecolor=halo,
                          markeredgewidth=2, alpha=0.8)
            glow.set_clip_path(s.ax.patch)
            made.append(glow)
        elif s.kind == 'bars':   # over its own colour a lighter fill alone hardly shows: outlined
            boxes = [r.get_window_extent() for r in s.artist.patches if r.get_visible()]
            rects = [[(b.x0, b.y0), (b.x0, b.y1), (b.x1, b.y1), (b.x1, b.y0)] for b in boxes]
            if rects:
                edge = self._tint(s.colour(), 0.65)
                made.append(PolyCollection(rects, transform=IdentityTransform(), facecolor=(*halo, 0.3),
                                           edgecolor=(*edge, 0.95), linewidth=1.6))
        elif s.kind == 'area':
            transform = s.artist.get_transform()
            shapes = [transform.transform(p.vertices) for p in s.artist.get_paths() if len(p.vertices)]
            if shapes:
                made.append(PolyCollection(shapes, transform=IdentityTransform(), facecolor='none',
                                           edgecolor=halo, linewidth=2, alpha=0.85))
        for artist in made:
            artist.set_figure(figure)
            artist.set_animated(True)
            if isinstance(artist, PolyCollection):
                artist.set_clip_box(s.ax.bbox)
        return made

    @staticmethod
    def _tint(colour, by=0.45):
        """The colour, lighter: a glow in the series' own colour that still shows over it."""
        from matplotlib.colors import to_rgb
        return tuple(c + (1 - c) * by for c in to_rgb(colour))

    def _marks_for(self, key, accent):
        if key not in self._marks:
            ring = Line2D([0], [0], transform=IdentityTransform(), linestyle='none', marker='o', markersize=12,
                          markerfacecolor='none', markeredgecolor=accent, markeredgewidth=1.8, animated=True)
            label = Text(0, 0, '', transform=IdentityTransform(), color=_style.TEXT, fontsize=9, linespacing=1.4,
                         animated=True, bbox=dict(boxstyle='round,pad=0.5', facecolor=_style.RAISED,
                                                  edgecolor=_style.BORDER, linewidth=0.8))
            for artist in ring, label:
                artist.set_gid(_series.OURS)
                artist.set_figure(self.canvas.figure)
            self._marks[key] = ring, label
        return self._marks[key]

    def _place(self, label, s, position, text):
        label.set_text(text)
        box = s.ax.bbox
        offset = self.OFFSET_PX * (self.canvas.device_pixel_ratio or 1.0)
        right = position[0] > box.x0 + 0.68 * box.width   # near the right or the top: the label goes the other way
        top = position[1] > box.y0 + 0.7 * box.height
        label.set_position((position[0] + (-offset if right else offset), position[1] + (-offset if top else offset)))
        label.set_horizontalalignment('right' if right else 'left')
        label.set_verticalalignment('top' if top else 'bottom')
