"""A series' appearance, changed from the Plot tab: its colour (the palette's eight, or any), its
marker, its line, their sizes, its opacity and (a stem plot) its baseline - put on the plot and
its legend at once, and on the parts drawn with it (an errorbar's caps and bars, a stem plot's stems). A series in
several plots has one look in all of them, unless a copy has a look of its own. Each change goes into
the settings file under the series' axes and first name (reapply), so a series drawn again - the
parameter sliders, the next run of the script - keeps it; and each can be undone (_history).
preview() draws a series' look small, for the panels' lists: its line and its marker, as plotted."""
import numpy as np
from PySide6 import QtCore, QtGui, QtWidgets
from matplotlib.colors import to_hex
from matplotlib.lines import Line2D
from matplotlib.markers import MarkerStyle
from matplotlib.path import Path

from . import _series, _style
from ._history import history
from ._settings import store

Qt = QtCore.Qt

MARKERS = ['', '.', 'o', 's', '^', 'v', 'D', 'x', '+', '*']
LINES = ['None', '-', '--', ':', '-.']
_DASHES = {'-': Qt.PenStyle.SolidLine, '--': Qt.PenStyle.DashLine, ':': Qt.PenStyle.DotLine,
           '-.': Qt.PenStyle.DashDotLine}


# ---- drawing a look

def marker_path(marker):
    """matplotlib's own outline of the marker, as a Qt path about (0, 0), about 1 across, y down."""
    style = MarkerStyle(marker)
    path = style.get_path().transformed(style.get_transform())
    shape = QtGui.QPainterPath()
    for vertices, code in path.iter_segments(simplify=False, curves=True):
        points = [QtCore.QPointF(vertices[i], -vertices[i + 1]) for i in range(0, len(vertices), 2)]
        if code == Path.MOVETO:
            shape.moveTo(points[0])
        elif code == Path.LINETO:
            shape.lineTo(points[0])
        elif code == Path.CURVE3:
            shape.quadTo(points[0], points[1])
        elif code == Path.CURVE4:
            shape.cubicTo(points[0], points[1], points[2])
        elif code == Path.CLOSEPOLY:
            shape.closeSubpath()
    return shape, style.is_filled()


def draw_marker(painter, marker, centre, size, colour):
    if marker in ('', 'None', 'none', None, ' '):
        return
    try:
        shape, filled = marker_path(marker)
    except (ValueError, TypeError):
        shape, filled = marker_path('o')
    painter.save()
    painter.translate(centre)
    painter.scale(size, size)
    pen = QtGui.QPen(QtGui.QColor(colour), 1.5)
    pen.setCosmetic(True)   # its width in pixels, not scaled with the marker
    painter.setPen(Qt.PenStyle.NoPen if filled else pen)
    painter.setBrush(QtGui.QColor(colour) if filled else Qt.BrushStyle.NoBrush)
    painter.drawPath(shape)
    painter.restore()


def draw_line(painter, line, start, end, width, colour):
    if line not in _DASHES:
        return
    pen = QtGui.QPen(QtGui.QColor(colour), width)
    pen.setStyle(_DASHES[line])
    pen.setCapStyle(Qt.PenCapStyle.FlatCap)
    painter.setPen(pen)
    painter.drawLine(start, end)


def _canvas(width, height, ratio=3.0):
    """A pixmap drawn at 3x - icons are scaled down from it smoothly, whatever the screen."""
    pixmap = QtGui.QPixmap(int(width * ratio), int(height * ratio))
    pixmap.setDevicePixelRatio(ratio)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QtGui.QPainter(pixmap)
    painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
    return pixmap, painter


def look(s):
    """{'colour', 'marker', 'line', 'size', 'width', 'alpha'} as the series is now - a line's
    'drawstyle' too, and a stem plot's 'baseline' (shown or not)."""
    artist = s.artist
    if s.kind == 'line':
        found = {'colour': to_hex(artist.get_color()), 'marker': _marker_name(artist.get_marker()),
                 'line': artist.get_linestyle(), 'size': artist.get_markersize(), 'width': artist.get_linewidth(),
                 'alpha': _alpha(artist), 'drawstyle': artist.get_drawstyle()}
        if s.stem and len(s.parts) > 1:
            found['baseline'] = bool(s.parts[-1].get_visible())
        return found
    first = artist.patches[0] if s.kind == 'bars' and artist.patches else artist
    sizes = artist.get_sizes() if s.kind == 'scatter' else []
    return {'colour': s.colour(), 'marker': getattr(artist, '_csn_marker', 'o') if s.kind == 'scatter' else '',
            'line': 'None', 'size': float(sizes[0]) ** 0.5 if len(sizes) else 6.0, 'width': 0.0,
            'alpha': _alpha(first)}


def _alpha(artist):
    alpha = artist.get_alpha()
    if alpha is None and hasattr(artist, 'get_facecolor'):
        try:
            colours = np.atleast_2d(artist.get_facecolor())
            alpha = float(colours[0][3]) if colours.shape[1] == 4 else 1.0
        except (TypeError, IndexError, ValueError):
            alpha = 1.0
    return round(float(alpha if alpha is not None else 1.0), 3)


def _marker_name(marker):
    return '' if marker in ('None', 'none', None, ' ', '') else marker


def preview(s):
    """The series' look as a small icon: its line across, its marker on it (a bar: a block)."""
    width, height = 30, 14
    pixmap, painter = _canvas(width, height)
    now = look(s)
    centre = QtCore.QPointF(width / 2, height / 2)
    painter.setOpacity(max(now.get('alpha', 1.0), 0.25))
    if s.kind in ('bars', 'area'):
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QtGui.QColor(now['colour']))
        if s.kind == 'bars':
            painter.drawRoundedRect(QtCore.QRectF(8, 2, 14, 10), 2, 2)
        else:   # an area: a hill
            hill = QtGui.QPainterPath(QtCore.QPointF(2, 12))
            hill.cubicTo(9, 1, 15, 3, 28, 6)
            hill.lineTo(28, 12)
            hill.closeSubpath()
            painter.drawPath(hill)
    elif s.stem:
        draw_line(painter, '-', QtCore.QPointF(centre.x(), 13), QtCore.QPointF(centre.x(), centre.y()), 1.4,
                  now['colour'])
        draw_marker(painter, now['marker'] or 'o', centre, 7, now['colour'])
    else:
        draw_line(painter, now['line'], QtCore.QPointF(2, centre.y()), QtCore.QPointF(width - 2, centre.y()),
                  min(max(now['width'], 1.0), 3.0), now['colour'])
        draw_marker(painter, now['marker'], centre, min(max(now['size'] * 1.4, 6.0), 11.0), now['colour'])
    painter.end()
    return QtGui.QIcon(pixmap)


# ---- changing a look

def own_look(s):
    """Whether a copy has a look of its own, not its source's."""
    identity = _series.added(s)
    entry = next((e for e in store.plots().get('added', []) if e['id'] == identity), None) if identity else None
    return bool(entry is not None and entry.get('link') and entry.get('own_look'))


def chosen_colour(s):
    """Whether the series' colour was chosen - in the window, or by the script (one that's not of the
    colour cycle) - not just the next one the plot had."""
    source = _series.find(_series.link_of(s)) or s
    if 'colour' in store.plots().get('looks', {}).get(_series.key_of(source), {}):
        return True
    from matplotlib import rcParams
    cycle = {c.lower() for c in rcParams['axes.prop_cycle'].by_key().get('color', [])} | {c.lower() for c in _style.SERIES}
    return source.colour().lower() not in cycle


def sharing(s):
    """The series that change look with this one: itself and every copy sharing its look - or itself
    alone, a copy with a look of its own."""
    if own_look(s):
        return [s]
    found = [m for m in _series.members(s) if not own_look(m)]
    return found if any(m.artist is s.artist for m in found) else [s, *found]


def apply(s, remember=True, everywhere=True, **changes):
    """Puts the changes (any of look()'s keys) on the series and its legend entries - and, everywhere,
    on the copies sharing its look."""
    for target in (sharing(s) if everywhere else [s]):
        _apply_one(target, remember, changes)


def _apply_one(s, remember, changes):
    artist = s.artist
    if not hasattr(artist, '_csn_look0'):   # as the script made it - for a reset
        artist._csn_look0 = look(s)
    colour, marker, line = changes.get('colour'), changes.get('marker'), changes.get('line')
    size, width, alpha = changes.get('size'), changes.get('width'), changes.get('alpha')
    if s.kind == 'line':
        if colour is not None:
            artist.set_color(colour)
            for name in ('markerfacecolor', 'markeredgecolor'):   # set apart from the line, but not hollow
                if getattr(artist, '_' + name, 'auto') not in ('auto', 'none', 'None'):
                    getattr(artist, 'set_' + name)(colour)
            for part in (s.parts[:-1] if s.stem else s.parts):   # a stem plot's baseline keeps its own
                part.set_color(colour)
        if marker is not None:
            artist.set_marker(marker or 'None')
        if line is not None:
            artist.set_linestyle(line)
        if size is not None:
            artist.set_markersize(size)
        if width is not None:   # never 0: a bar's edge width carried over to a line drawn from it
            from matplotlib import rcParams   # here: only this needs it
            artist.set_linewidth(width if width > 0 else rcParams['lines.linewidth'])
        if changes.get('drawstyle') is not None:
            artist.set_drawstyle(changes['drawstyle'])
        if changes.get('baseline') is not None and s.stem and len(s.parts) > 1:
            s.parts[-1].set_visible(bool(changes['baseline']) and artist.get_visible())
        if alpha is not None:
            for thing in (artist, *s.parts):
                thing.set_alpha(alpha)
    elif s.kind == 'scatter':
        if colour is not None:
            artist._csn_colours_before = _colours_now(artist)   # for the undo (record): its own, if it had them
            artist.set_array(None)   # a colour picked wins over a colour map
            artist.set_facecolor(colour)
            artist.set_edgecolor(colour)
        own = changes.get('colours')
        if own is not None:   # undone: the colours it had - each point its own, a colour map
            artist.set_cmap(own['cmap'])
            artist.set_norm(own['norm'])
            artist.set_array(own['array'])
            artist.set_facecolor(own['face'])
            artist.set_edgecolor(own['edge'])
        if marker:
            style = MarkerStyle(marker)
            artist.set_paths([style.get_path().transformed(style.get_transform())])
            artist._csn_marker = marker
        if size is not None:
            artist.set_sizes([size ** 2])
        if alpha is not None:
            artist.set_alpha(alpha)
    elif s.kind == 'area':
        if colour is not None:
            artist.set_facecolor(colour)
        if alpha is not None:
            artist.set_alpha(alpha)
    else:
        for rect in s.artist.patches:
            if colour is not None:
                rect.set_facecolor(colour)
            if alpha is not None:
                rect.set_alpha(alpha)
    _legends(s)
    if remember:
        looks = store.plots().setdefault('looks', {})
        kept = looks.setdefault(_series.key_of(s), {})
        kept.update({k: v for k, v in changes.items() if v is not None and k != 'colours'})
        if changes.get('colours') is not None:   # its own colours again: no colour of its own kept
            kept.pop('colour', None)
        store.changed()


def _colours_now(artist):
    """A scatter's colours as they are - None: one colour, nothing a single colour can't give back."""
    face = getattr(artist, '_original_facecolor', None)
    face = artist.get_facecolor() if face is None else face
    many = np.atleast_2d(np.asarray(artist.get_facecolor()))
    if artist.get_array() is None and len(np.unique(many, axis=0)) <= 1:
        return None
    edge = getattr(artist, '_original_edgecolor', None)
    return {'array': artist.get_array(), 'cmap': artist.get_cmap(), 'norm': artist.norm,
            'face': np.array(face, copy=True) if not isinstance(face, str) else face,
            'edge': edge if isinstance(edge, str) or edge is None else np.array(edge, copy=True)}


def reapply():
    """The saved looks, onto the series (drawn again, or the window just opened)."""
    looks = store.plots().get('looks', {})
    if looks:
        for figure in _series.figures():
            for ax in figure.axes:
                for s in _series.series(ax):
                    if _series.key_of(s) in looks:
                        apply(s, remember=False, everywhere=False, **looks[_series.key_of(s)])


def record(s, before, after):
    """A look change, onto the history - found again by its key when undone (it may be drawn anew)."""
    key = _series.key_of(s)
    own = getattr(s.artist, '_csn_colours_before', None) if 'colour' in before and s.kind == 'scatter' else None
    if own is not None:   # it had colours of its own (a colour map): undone, it has them again
        before = {**before, 'colours': own}

    def put(values):
        again = _series.find(key)
        if again is not None:
            apply(again, **values)
            again.ax.figure.canvas.draw_idle()
    history.push('Change series style', lambda: put(before), lambda: put(after))


def _legends(s):
    """Legends hold copies of what they show: these are changed to match."""
    figure = s.ax.figure
    artist = s.artist
    for legend in [s.ax.get_legend(), *figure.legends]:
        if legend is None:
            continue
        handles = getattr(legend, 'legend_handles', None) or getattr(legend, 'legendHandles', [])
        for handle, text in zip(handles, legend.get_texts()):
            if handle is None or text.get_text() != s.label:
                continue
            if s.kind == 'line' and isinstance(handle, Line2D):
                for name in ('color', 'marker', 'linestyle', 'linewidth', 'markerfacecolor', 'markeredgecolor'):
                    getattr(handle, 'set_' + name)(getattr(artist, 'get_' + name)())
                handle.set_markersize(artist.get_markersize() * legend.markerscale)
                handle.set_alpha(artist.get_alpha())
            elif s.kind == 'scatter' and hasattr(handle, 'set_paths'):
                handle.set_facecolor(artist.get_facecolor())
                handle.set_edgecolor(artist.get_edgecolor())
                handle.set_paths(artist.get_paths())
                handle.set_alpha(artist.get_alpha())
            elif s.kind == 'area' and hasattr(handle, 'set_facecolor'):
                if len(artist.get_facecolor()):
                    handle.set_facecolor(artist.get_facecolor()[0])
                handle.set_alpha(artist.get_alpha())
            elif s.kind == 'bars' and hasattr(handle, 'set_facecolor'):
                handle.set_facecolor(s.artist.patches[0].get_facecolor())


# ---- the editor

class StyleEditor(QtWidgets.QWidget):
    """Colour, marker, line, marker size, line width, opacity and (a stem plot) the baseline of one
    series; changed(series) after each change."""

    changed = QtCore.Signal(object)

    def __init__(self):
        super().__init__()
        self.series = None
        self._loading = False
        self._dragging = None   # the look a slider drag started from
        grid = QtWidgets.QGridLayout(self)
        grid.setContentsMargins(0, 2, 0, 2)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(6)
        self.colours = self._choices([(c, self._dot_icon(c)) for c in _style.SERIES], 'colour',
                                     extra=('Any colour…', self._any_colour))
        self.markers = self._choices([(m, self._marker_icon(m)) for m in MARKERS], 'marker')
        self.lines = self._choices([(line, self._line_icon(line)) for line in LINES], 'line')
        self.size, size_row = self._slider(1, 20, 'size')
        self.width_, width_row = self._slider(0.5, 6, 'width')
        self.alpha, alpha_row = self._slider(0.05, 1, 'alpha', per_unit=20)
        self.baseline = QtWidgets.QCheckBox('Shown')
        self.baseline.toggled.connect(lambda on: self._change(baseline=on))
        baseline_row = QtWidgets.QHBoxLayout()
        baseline_row.setContentsMargins(0, 0, 0, 0)
        baseline_row.addWidget(self.baseline)
        baseline_row.addStretch(1)
        self.rows = {}
        for row, (name, layout) in enumerate((('Colour', self.colours[0]), ('Marker', self.markers[0]),
                                               ('Line', self.lines[0]), ('Size', size_row), ('Width', width_row),
                                               ('Opacity', alpha_row), ('Baseline', baseline_row))):
            label = QtWidgets.QLabel(name)
            label.setObjectName('csnHint')
            if isinstance(layout, QtWidgets.QWidget):
                holder = layout
            else:
                holder = QtWidgets.QWidget()
                holder.setLayout(layout)
            grid.addWidget(label, row, 0)
            grid.addWidget(holder, row, 1)
            self.rows[name] = (label, holder)
        grid.setColumnStretch(1, 1)

    def _choices(self, options, key, extra=None):
        """(the row, its button group, {value: button}) - a _Row, its last button '…' for those there's
        no room for, and extra (its text, what it does) after them."""
        group = QtWidgets.QButtonGroup(self)
        group.setExclusive(True)
        buttons, icons = {}, {}
        for value, icon in options:
            button = QtWidgets.QToolButton()
            button.setObjectName('csnChoice')
            button.setCheckable(True)
            button.setIcon(icon)
            button.setIconSize(QtCore.QSize(18, 18))
            button.setToolTip(value if value not in ('', 'None') else 'none')
            button.clicked.connect(lambda _=False, v=value: self._change(**{key: v}))
            group.addButton(button)
            buttons[value], icons[value] = button, icon

        def pick(value):
            buttons[value].setChecked(True)
            self._change(**{key: value})
        row = _Row(buttons, icons, pick, extra)
        for button in buttons.values():
            button.clicked.connect(row.refresh)
        return row, group, buttons

    def _slider(self, low, high, key, per_unit=2):
        row = QtWidgets.QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        slider = QtWidgets.QSlider(Qt.Orientation.Horizontal)
        slider.setRange(int(round(low * per_unit)), int(round(high * per_unit)))   # halves, or twentieths
        slider.per_unit = per_unit
        value = QtWidgets.QLabel()
        value.setMinimumWidth(30)
        value.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        def moved(steps):
            value.setText(f"{steps / per_unit:g}")
            self._change(**{key: steps / per_unit})
        slider.valueChanged.connect(moved)
        slider.sliderPressed.connect(self._drag_started)
        slider.sliderReleased.connect(self._drag_ended)
        slider.value_label = value
        row.addWidget(slider, 1)
        row.addWidget(value)
        return slider, row

    def show_series(self, s):
        self.series = s
        if s is None:
            return
        now = look(s)
        self._loading = True
        for _, group, buttons in (self.colours, self.markers, self.lines):
            checked = group.checkedButton()
            if checked is not None:   # an exclusive group won't let go of its last one otherwise
                group.setExclusive(False)
                checked.setChecked(False)
                group.setExclusive(True)
        for (_, _, buttons), value in ((self.colours, now['colour'].lower()), (self.markers, now['marker']),
                                       (self.lines, now['line'])):
            try:
                if value in buttons:
                    buttons[value].setChecked(True)
            except TypeError:   # a marker given as an array: none of these
                pass
        for slider, value in ((self.size, now['size']), (self.width_, now['width']), (self.alpha, now['alpha'])):
            slider.setValue(int(round(value * slider.per_unit)))
            slider.value_label.setText(f"{value:g}")
        self.baseline.setChecked(bool(now.get('baseline', True)))
        for name, shown in (('Marker', s.kind in ('line', 'scatter')), ('Line', s.kind == 'line'),
                            ('Size', s.kind in ('line', 'scatter')), ('Width', s.kind == 'line'),
                            ('Baseline', 'baseline' in now)):
            for widget in self.rows[name]:
                widget.setVisible(shown)
        self.markers[0].leave_out([] if s.kind == 'line' else [''])   # a scatter without markers would be nothing
        for row in (self.colours[0], self.markers[0], self.lines[0]):
            row.refresh()
        self._loading = False

    def _change(self, **changes):
        if self._loading or self.series is None:
            return
        before = look(self.series)
        apply(self.series, **changes)
        if self._dragging is None:   # a slider dragged makes one history entry, when it's let go
            record(self.series, {k: before[k] for k in changes}, changes)
        self.series.ax.figure.canvas.draw_idle()
        self.changed.emit(self.series)

    def _drag_started(self):
        if self.series is not None:
            self._dragging = look(self.series)

    def _drag_ended(self):
        before, self._dragging = self._dragging, None
        if before is not None and self.series is not None:
            after = look(self.series)
            changed = [k for k in ('size', 'width', 'alpha') if before[k] != after[k]]
            if changed:
                record(self.series, {k: before[k] for k in changed}, {k: after[k] for k in changed})

    def _any_colour(self):
        if self.series is None:
            return
        dialog = QtWidgets.QColorDialog(QtGui.QColor(look(self.series)['colour']), self)
        dialog.setWindowTitle('Series colour')
        _style.dark_title_bar(dialog)
        if dialog.exec():
            group = self.colours[1]
            group.setExclusive(False)
            for button in self.colours[2].values():
                button.setChecked(False)
            group.setExclusive(True)
            self._change(colour=dialog.selectedColor().name())
            self.colours[0].refresh()

    @staticmethod
    def _dot_icon(colour):
        pixmap, painter = _canvas(18, 18)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QtGui.QColor(colour))
        painter.drawEllipse(QtCore.QRectF(3, 3, 12, 12))
        painter.end()
        return QtGui.QIcon(pixmap)

    @staticmethod
    def _marker_icon(marker):
        pixmap, painter = _canvas(18, 18)
        if marker:
            draw_marker(painter, marker, QtCore.QPointF(9, 9), 10, _style.TEXT_2)
        else:
            _none(painter)
        painter.end()
        return QtGui.QIcon(pixmap)

    @staticmethod
    def _line_icon(line):
        pixmap, painter = _canvas(18, 18)
        if line in _DASHES:
            draw_line(painter, line, QtCore.QPointF(1, 9), QtCore.QPointF(17, 9), 1.8, _style.TEXT_2)
        else:
            _none(painter)
        painter.end()
        return QtGui.QIcon(pixmap)


class _Row(QtWidgets.QWidget):
    """A row of choices that fits the panel: as many buttons as there's room for - ROOM at the least -
    the rest in the menu of its last button, '…' (showing the one chosen, when it's one of those), with
    extra (any colour) at the end. Room for them all: all of them."""

    ROOM = 8
    SPACING = 2

    def __init__(self, buttons, icons, pick, extra=None):
        super().__init__()
        self.buttons, self.icons, self.pick, self.extra = buttons, icons, pick, extra
        self._hidden, self._left_out = [], set()
        first = next(iter(buttons.values()))
        self.more = QtWidgets.QToolButton()
        self.more.setObjectName('csnChoice')
        self.more.setText('…')
        self.more.setCheckable(True)
        self.more.setFixedSize(first.sizeHint())
        self.more.clicked.connect(self._more)
        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(self.SPACING)
        layout.setSizeConstraint(QtWidgets.QLayout.SizeConstraint.SetNoConstraint)   # its least width: ROOM buttons'
        for button in buttons.values():
            layout.addWidget(button)
        layout.addWidget(self.more)
        layout.addStretch(1)
        self.setSizePolicy(QtWidgets.QSizePolicy.Policy.Expanding, QtWidgets.QSizePolicy.Policy.Fixed)

    def _values(self):
        return [v for v in self.buttons if v not in self._left_out]

    def _unit(self):
        return self.more.width() + self.SPACING

    def minimumSizeHint(self):
        room = min(self.ROOM, len(self._values()) + (1 if self.extra else 0))
        return QtCore.QSize(room * self._unit() - self.SPACING, self.more.height())

    def sizeHint(self):
        count = len(self._values()) + (1 if self.extra else 0)
        return QtCore.QSize(count * self._unit() - self.SPACING, self.more.height())

    def leave_out(self, values):
        """These not offered at all (a scatter: no marker)."""
        if set(values) != self._left_out:
            self._left_out = set(values)
            for value, button in self.buttons.items():
                button.setVisible(value not in self._left_out)
            self.updateGeometry()
            self._fit()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._fit()

    def _fit(self):
        values = self._values()
        room = max((self.width() + self.SPACING) // self._unit(), 2)
        shown = values if room >= len(values) + (1 if self.extra else 0) else values[:room - 1]
        self._hidden = [v for v in values if v not in shown]
        for value, button in self.buttons.items():
            button.setVisible(value in shown)
        self.more.setVisible(bool(self._hidden) or self.extra is not None)
        self.refresh()

    def refresh(self):
        """'…' showing the choice that's chosen, if it's one of those in its menu."""
        chosen = next((v for v in self._hidden if self.buttons[v].isChecked()), None)
        if chosen is not None:
            self.more.setIcon(self.icons[chosen])
            self.more.setIconSize(QtCore.QSize(18, 18))
            self.more.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        else:
            self.more.setIcon(QtGui.QIcon())
            self.more.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        self.more.setChecked(chosen is not None)
        self.more.setToolTip('More' if self._hidden else self.extra[0].rstrip('…') if self.extra else '')

    def _more(self):
        self.refresh()   # a click doesn't check it: it's checked while one of its menu's is chosen
        if not self._hidden:
            if self.extra is not None:
                self.extra[1]()
            return
        menu = QtWidgets.QMenu(self)
        holder = QtWidgets.QWidget()   # the choices left out, as buttons like the row's: no names needed
        row = QtWidgets.QHBoxLayout(holder)
        row.setContentsMargins(4, 4, 4, 4)
        row.setSpacing(self.SPACING)
        for value in self._hidden:
            original = self.buttons[value]
            button = QtWidgets.QToolButton()
            button.setObjectName('csnChoice')
            button.setIcon(self.icons[value])
            button.setIconSize(original.iconSize())
            button.setToolTip(original.toolTip())
            button.setCheckable(True)
            button.setChecked(original.isChecked())
            button.clicked.connect(lambda _=False, v=value: (menu.close(), self.pick(v)))
            row.addWidget(button)
        choices = QtWidgets.QWidgetAction(menu)
        choices.setDefaultWidget(holder)
        menu.addAction(choices)
        if self.extra is not None:
            menu.addSeparator()
            menu.addAction(self.extra[0], self.extra[1])
        menu.exec(self.more.mapToGlobal(QtCore.QPoint(0, self.more.height())))
        self.refresh()


def _none(painter):
    """'none': a small crossed-out circle."""
    pen = QtGui.QPen(QtGui.QColor(_style.TEXT_3), 1.3)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawEllipse(QtCore.QRectF(4.5, 4.5, 9, 9))
    painter.drawLine(QtCore.QPointF(6, 12), QtCore.QPointF(12, 6))
