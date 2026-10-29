"""The Plot tab of the side panel: one plot of the tab at a time - picked in the list at its top, by
clicking the plot, in the data panel or from the plot's right-click menu - and what can be done to it:
- Plot: its name (where it's listed - F2), title and axis labels, scales, limits (and Fit), its own
  grid and legend, x and y swapped;
- Series: what's in it - shown or hidden, added from any plot of any open tab (a linked copy: it
  shows that series' data, whatever it becomes), put back after being removed, removed, moved to
  another plot, drawn as a line, markers, steps, a scatter or bars (a series of the script's drawn
  as another type is a linked copy of it in its place), on the left or the right y axis. Nothing is
  picked until it's picked: the series picked glows on the plot while the tab is open;
- Appearance of the picked series (_style_editor): the same in every plot it's in, or - a copy - its
  own. Folded away and greyed out while it's locked;
- Trendline and Error bars of the picked series (_fits);
- Show up to x: the plot's data only up to an x (_upto), a slider to move it, Play to draw it from
  the first point to the last - offered only for plots of lines, scatters, bars and areas.
Picked is what's picked in a tab - a plot, and maybe one of its series - shared by the panels and
the plot (it's outlined as it's picked, and for as long as this tab is open). plot_menu() and figure_menu() are the plot's right-click
menus, series_tag() says where a series comes from."""
import math

from PySide6 import QtCore, QtGui, QtWidgets

from . import _fits, _layout, _series, _sliders, _style_editor, _upto, _view
from ._history import history
from ._settings import store
from ._widgets import InlineDelegate, NumberField, Section

Qt = QtCore.Qt
SLIDER_STEPS = 1000
TYPES = {'line': 'Line', 'markers': 'Markers only', 'both': 'Line and markers', 'steps': 'Steps',
         'scatter': 'Scatter', 'bars': 'Bars', 'area': 'Filled area'}


class Picked(QtCore.QObject):
    """What's picked in a tab: a plot, and maybe one of its series."""

    changed = QtCore.Signal(object)   # who picked it - a panel needn't follow itself - or None

    def __init__(self):
        super().__init__()
        self.ax = self.series = None

    def set(self, ax=None, series=None, by=None):
        if series is not None:
            ax = series.ax
        ax = _view.main_of(ax) if ax is not None else None
        same = ax is self.ax and (series is self.series or (series is not None and self.series is not None
                                                           and series.artist is self.series.artist))
        self.ax, self.series = ax, series
        if not same:
            self.changed.emit(by)


def series_tag(s):
    """(tag, explanation): where the series comes from."""
    entry = _view.entry_of(s)
    run = getattr(s.artist, '_csn_run', None)
    if entry is not None and entry.get('in_place_of'):
        return 'script', f"Drawn by the script, shown here as {TYPES.get(entry['kind'], entry['kind']).lower()}"
    if entry is not None and entry.get('link'):
        if entry.get('shadow'):
            return 'reference copy', "A faint linked copy of a series in another plot, for comparison"
        return 'copy', ("A linked copy of a series in another plot: it shows that series' data. Hiding, "
                        "locking or deleting it acts on every copy")
    if run not in (None, _sliders.LIVE):
        return 'saved run', 'A run of the parameter sliders kept as data. Picking it puts its parameters on the sliders'
    if entry is not None:
        return 'added', 'Added in this window'
    if run == _sliders.LIVE:
        return 'original run', "Drawn by the sliders' function from the original run's parameters"
    return 'script', 'Drawn by the script'


def members_of(main):
    """The plot and its twins (a right-hand y axis)."""
    return [a for a in main.figure.axes if _view.main_of(a) is main] if main.figure is not None else []


def series_in(main):
    return [s for a in members_of(main) for s in _series.series(a)]


def _say(canvas, text):
    if text and hasattr(canvas, 'say'):
        canvas.say(text)


# ---- adding, removing and moving series

def fill_add_menu(menu, ax, canvas):
    """Every series of every plot in the open tabs (a copy goes into this plot), and the script's
    series taken out of this plot (to put back)."""
    menu.clear()
    main = _view.main_of(ax)
    here = {_series.link_of(s) for s in series_in(main)}
    removed = [s for a in members_of(main) for s in _series.series(a, everything=True)
               if _series.key_of(s) in store.plots().get('removed', [])]
    if removed:
        back = menu.addMenu('Put back in this plot')
        for s in removed:
            back.addAction(_style_editor.preview(s), s.label,
                           lambda _=False, k=_series.key_of(s): _view.set_removed(k, False))
        menu.addSeparator()
    figures = _series.open_figures()
    for figure in figures:
        holder = menu.addMenu(_series.tab_name(figure)) if len(figures) > 1 else menu
        for other in _layout.plots(figure):
            items = [s for s in series_in(other) if not s.label.endswith(_view.REFERENCE)]
            if not items:
                continue
            plot = holder.addMenu(_series.plot_name(other) + ('  (this plot)' if other is main else ''))
            for s in items:
                action = plot.addAction(_style_editor.preview(s), s.label,
                                        lambda _=False, s=s: _say(canvas, _view.copy_to(s, main)))
                action.setEnabled(_series.link_of(s) not in here)
            if plot.isEmpty():
                holder.removeAction(plot.menuAction())
        if holder is not menu and holder.isEmpty():
            menu.removeAction(holder.menuAction())
    if menu.isEmpty():
        menu.addAction('There are no series in the open tabs').setEnabled(False)


def fill_move_menu(menu, s, canvas, copy=False):
    """Every other plot of the open tabs - the series moved there (or copied, copy)."""
    menu.clear()
    main = _view.main_of(s.ax)
    figures = _series.open_figures()
    for figure in figures:
        holder = menu.addMenu(_series.tab_name(figure)) if len(figures) > 1 else menu
        for other in _layout.plots(figure):
            if other is main or not other.get_visible():
                continue
            act = _view.copy_to if copy else _view.move_to_plot
            holder.addAction(_series.plot_name(other), lambda _=False, o=other: _say(canvas, act(s, o)))
        if holder is not menu and holder.isEmpty():
            menu.removeAction(holder.menuAction())
    menu.addSeparator()
    menu.addAction('A new plot in this tab', lambda: _to_new_plot(s, canvas, False, copy))
    menu.addAction('A new plot in a new tab', lambda: _to_new_plot(s, canvas, True, copy))


def _to_new_plot(s, canvas, new_tab, copy):
    ax = _layout.new_plot(canvas.figure, new_tab=new_tab, title=s.label)
    if ax is not None:
        _say(canvas, (_view.copy_to if copy else _view.move_to_plot)(s, ax))


def remove(s, canvas):
    if _view.locked(s):
        _say(canvas, f"“{s.label}” is locked. Unlock it to remove it")
        return
    _view.remove_from_plot(s)


def delete_everywhere(s, canvas):
    if _view.locked(s):
        _say(canvas, f"“{s.label}” is locked. Unlock it to delete it")
        return
    count = len(_series.members(s) or [s])
    if count > 1:
        answer = QtWidgets.QMessageBox.question(
            canvas, 'Delete series', f"Delete “{s.label}” from all {count} plots it is in? (Ctrl+Z undoes it)")
        if answer != QtWidgets.QMessageBox.StandardButton.Yes:
            return
    _view.delete_everywhere(s)


# ---- what a series is drawn as

def kind_of(s):
    if s.kind != 'line':
        return s.kind
    look = _style_editor.look(s)
    if str(look.get('drawstyle', 'default')).startswith('steps'):
        return 'steps'
    has_line = look['line'] not in ('None', 'none', '', ' ')
    has_marker = bool(look['marker'])
    return 'both' if has_line and has_marker else 'markers' if has_marker else 'line'


def kinds_for(s):
    """The kinds the series can be drawn as - a stem plot, an errorbar's line (its bars go with it),
    horizontal bars and a filled area only as they are."""
    if s.stem:
        return ['line']
    few = s.kind == 'bars' or len(s) <= _view.BARS_MAX   # bars of many points: too slow to make, unreadable
    if s.kind == 'line':
        return ['line', 'markers', 'both', 'steps'] + ([] if s.parts else ['scatter'] + (['bars'] if few else []))
    if s.kind == 'bars' and getattr(s.artist, 'orientation', 'vertical') == 'horizontal':
        return ['bars']
    if s.kind in ('scatter', 'bars'):
        return [s.kind] + [k for k in ('line', 'scatter', 'bars') if k != s.kind and (k != 'bars' or few)]
    return [s.kind]


def set_kind(s, kind):
    """Drawn as that kind: a line's own style (markers, steps), or drawn anew - a copy as another type,
    a series of the script's as a linked copy of it in its place."""
    entry = _view.entry_of(s)
    if kind in ('scatter', 'bars') or (s.kind in ('scatter', 'bars') and kind == 'line'):
        from ._sliders import Stopped   # here: stopped by the watchdog, it says so
        canvas = s.ax.figure.canvas
        if kind == 'bars' and s.kind != 'bars' and len(s) > _view.BARS_MAX:
            _say(canvas, f"“{s.label}” has {len(s):,} points: too many to draw as bars (at most {_view.BARS_MAX:,})")
            return
        try:
            if entry is not None:
                _view.set_kind(entry['id'], kind)
            elif _view.locked(s):
                _say(canvas, f"“{s.label}” is locked. Unlock it to change it")
            else:
                _view.redraw_as(s, kind)
        except Stopped:
            _say(canvas, f"Stopped: “{s.label}” is drawn as it was")
            canvas.draw_idle()
        return
    now = _style_editor.look(s)
    changes = {'drawstyle': 'steps-mid' if kind == 'steps' else 'default'}
    if kind in ('line', 'steps', 'both') and now['line'] in ('None', 'none', '', ' '):
        changes['line'] = '-'
    if kind == 'markers':
        changes['line'] = 'None'
    if kind in ('markers', 'both') and not now['marker']:
        changes['marker'] = 'o'
    if kind in ('line', 'steps'):
        changes['marker'] = ''
    changes = {k: v for k, v in changes.items() if now.get(k) != v}
    if changes:
        _style_editor.apply(s, **changes)
        _style_editor.record(s, {k: now.get(k) for k in changes}, changes)
        for figure in {m.ax.figure for m in _style_editor.sharing(s)}:
            figure.canvas.draw_idle()


def set_own_look(entry_id, on, record=True):
    """A copy with a look of its own - or its source's again."""
    entry = next((e for e in _view.entries() if e['id'] == entry_id), None)
    s = _view.series_of_entry(entry_id)
    if entry is None or not entry.get('link') or bool(entry.get('own_look')) == on:
        return
    _series.quiet()
    entry['own_look'] = on
    if on and s is not None:
        entry['look'] = _style_editor.look(s)
    store.changed()
    _view.sync_copies()
    if record:
        history.push('Give the copy an appearance of its own' if on else "Give the copy its source's appearance",
                     lambda: set_own_look(entry_id, not on, False), lambda: set_own_look(entry_id, on, False))
    if s is not None:
        s.ax.figure.canvas.draw_idle()


# ---- the panel

def _form():
    form = QtWidgets.QFormLayout()
    form.setContentsMargins(0, 2, 0, 2)
    form.setHorizontalSpacing(10)
    form.setVerticalSpacing(6)
    form.setFieldGrowthPolicy(QtWidgets.QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
    return form


def _hint(text=''):
    label = QtWidgets.QLabel(text)
    label.setObjectName('csnHint')
    label.setWordWrap(True)
    return label


def _row(*widgets, stretch=True):
    row = QtWidgets.QHBoxLayout()
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(6)
    for widget in widgets:
        if isinstance(widget, QtWidgets.QLayout):
            row.addLayout(widget)
        else:
            row.addWidget(widget)
    if stretch:
        row.addStretch(1)
    return row


def _holder(layout):
    widget = QtWidgets.QWidget()
    widget.setLayout(layout)
    return widget


def _combo(items):
    combo = QtWidgets.QComboBox()
    for value, text in items:
        combo.addItem(text, value)
    return combo


def _narrow(combo, letters):
    """A drop-down of names (any length) that's never wider than so many letters."""
    combo.setSizeAdjustPolicy(QtWidgets.QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
    combo.setMinimumContentsLength(letters)


def _select(combo, value):
    index = combo.findData(value)
    if index >= 0:
        combo.setCurrentIndex(index)


def _number(value):
    try:
        return f"{float(value):.6g}"
    except (TypeError, ValueError):
        return ''


class PlotPanel(QtWidgets.QWidget):
    REFRESH_MS = 300
    LIST_MAX = 170   # the series list's height at most - past it, it scrolls

    def __init__(self, canvas):
        super().__init__()
        self.setObjectName('csnPanel')
        self.setMinimumWidth(1)
        self.canvas = canvas
        self.picked = canvas.picked
        self._inside = False   # the pointer over the side panel: only then is what's edited lit on the plot
        self._loading = self._was_locked = False
        self._plots, self._series = [], []
        self._signature = None
        self.player = _upto.Player()
        self.player.moved.connect(self._played)
        self.player.finished.connect(self._play_ended)
        self._refresher = QtCore.QTimer(self)
        self._refresher.setSingleShot(True)
        self._refresher.timeout.connect(self.refresh)
        canvas.mpl_connect('draw_event', lambda event: self._refresher.start(self.REFRESH_MS))
        history.listeners.append(lambda: self._refresher.start(0))
        self.picked.changed.connect(self._picked_elsewhere)

        self.chooser = QtWidgets.QComboBox()
        _narrow(self.chooser, 12)   # a long plot name doesn't widen the panel
        self.chooser.setToolTip('The plot this tab edits - or click a plot')
        self.chooser.activated.connect(self._chose_plot)

        self.sections = {}
        body = QtWidgets.QWidget()
        body.setObjectName('csnPanel')
        column = QtWidgets.QVBoxLayout(body)
        column.setContentsMargins(0, 0, 4, 0)
        column.setSpacing(10)
        for name, widget, opened in (('Plot', self._plot_section(), True),
                                     ('Series in this plot', self._series_section(), True),
                                     ('Appearance', self._look_section(), True),
                                     ('Trendline', self._trend_section(), False),
                                     ('Error bars', self._errors_section(), False),
                                     ('Show up to x', self._upto_section(), False)):
            section = Section(name, widget, opened)
            section.place(column)
            self.sections[name] = section
        self._in_look = False   # the pointer over Appearance: the series as it looks, not lit
        self.sections['Appearance'].installEventFilter(self)
        column.addStretch(1)
        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        scroll.setWidget(body)
        self.empty = _hint('There are no plots in this tab. Right-click the empty space for a new one.')
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)
        layout.addWidget(self.chooser)
        layout.addWidget(self.empty)
        layout.addWidget(scroll, 1)
        self._scroll = scroll
        rename = QtGui.QShortcut(QtGui.QKeySequence(Qt.Key.Key_F2), self)
        rename.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        rename.activated.connect(self._rename)

    # ---- the sections

    def _plot_section(self):
        self.name = QtWidgets.QLineEdit()
        self.name.setToolTip('What the plot is called where it is listed (F2). Empty: its own name')
        self.name.editingFinished.connect(self._named)
        self.title = QtWidgets.QLineEdit()
        self.xlabel = QtWidgets.QLineEdit()
        self.ylabel = QtWidgets.QLineEdit()
        for field, which in ((self.title, 'title'), (self.xlabel, 'xlabel'), (self.ylabel, 'ylabel')):
            field.setPlaceholderText('none')
            field.editingFinished.connect(lambda f=field, w=which: self._text(w, f.text()))
        self.scales = {}
        for axis in ('x', 'y'):
            combo = _combo([(s, s) for s in _layout.SCALES])
            combo.activated.connect(lambda _=0, a=axis: self._scale(a))
            self.scales[axis] = combo
        self.limits = {}
        for axis in ('x', 'y'):
            low, high = QtWidgets.QLineEdit(), QtWidgets.QLineEdit()
            for field in (low, high):
                field.setValidator(QtGui.QDoubleValidator())
                field.setMinimumWidth(40)
                field.editingFinished.connect(lambda a=axis: self._limits(a))
            self.limits[axis] = (low, high)
        fit = QtWidgets.QPushButton('Fit')
        fit.setToolTip('Fit the limits to the data shown (Space on the plot)')
        fit.clicked.connect(self._fit)
        self.grid_on = QtWidgets.QCheckBox('Shown')
        self.grid_on.toggled.connect(lambda on: self._grid(on=on))
        self.grid_axis = _combo([('both', 'x and y'), ('x', 'x only'), ('y', 'y only')])
        self.grid_axis.activated.connect(lambda _=0: self._grid(on=True, axis=self.grid_axis.currentData()))
        self.grid_style = _combo([('-', 'solid'), ('--', 'dashed'), (':', 'dotted')])
        self.grid_style.activated.connect(lambda _=0: self._grid(on=True, style=self.grid_style.currentData()))
        self.grid_minor = QtWidgets.QCheckBox('Minor')
        self.grid_minor.setToolTip('Minor grid lines too')
        self.grid_minor.toggled.connect(lambda on: self._grid(on=True, minor=on) if on or self.grid_on.isChecked()
                                        else None)
        self.legend = QtWidgets.QCheckBox('Legend')
        self.legend.toggled.connect(self._legend)
        self.swap = QtWidgets.QPushButton('Swap x and y')
        self.swap.setToolTip('Exchange the axes: each series plotted with its x on the vertical axis')
        self.swap.clicked.connect(self._swap)
        self.hide_plot = QtWidgets.QPushButton('Hide')
        self.hide_plot.setToolTip('Out of the way, not deleted: listed in the Layout tab, to show again')
        self.hide_plot.clicked.connect(lambda: self._ax() is not None and _layout.hide(self._ax()))
        self.copy_plot = QtWidgets.QPushButton('Duplicate')
        self.copy_plot.setToolTip('A new plot in this tab, showing the same series (linked copies) with the same '
                                  'labels and scales')
        self.copy_plot.clicked.connect(lambda: self._ax() is not None and _layout.copy_plot(self._ax()))
        self.delete_plot = QtWidgets.QPushButton('Delete…')
        self.delete_plot.clicked.connect(lambda: self._ax() is not None and _layout.delete_plot(self._ax(), self))
        form = _form()
        form.addRow('Name', self.name)
        form.addRow('Title', self.title)
        form.addRow('x label', self.xlabel)
        form.addRow('y label', self.ylabel)
        for axis in ('x', 'y'):   # its limits, then its scale
            low, high = self.limits[axis]
            form.addRow(f"{axis} axis", _holder(_row(low, QtWidgets.QLabel('to'), high, *([fit] if axis == 'y' else []),
                                                     stretch=False)))
            form.addRow(f"{axis} scale", _holder(_row(self.scales[axis])))
        form.addRow('', _holder(_row(self.swap)))
        form.addRow('Grid', _holder(_row(self.grid_on, self.grid_minor)))
        self.grid_axis.setToolTip('Which axes get grid lines')
        self.grid_style.setToolTip('How the grid lines are drawn')
        form.addRow('', _holder(_row(self.grid_axis)))
        form.addRow('', _holder(_row(self.grid_style)))
        form.addRow('', _holder(_row(self.legend)))
        form.addRow(_holder(_row(self.copy_plot, self.hide_plot, self.delete_plot)))
        return _holder(form)

    def _series_section(self):
        self.list = QtWidgets.QListWidget()
        self.list.setIconSize(QtCore.QSize(30, 14))
        self.list.setFixedHeight(self.LIST_MAX)
        self.list.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.EditKeyPressed)
        self.list.setItemDelegate(InlineDelegate(self.list))
        self.list.currentRowChanged.connect(self._chose_series)
        self.list.itemChanged.connect(self._series_ticked)
        self.list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self._series_menu)
        add = QtWidgets.QToolButton()
        add.setText('Add series')
        add.setToolTip("A series of any plot in the open tabs, into this one: it shows that series' data")
        add.setPopupMode(QtWidgets.QToolButton.ToolButtonPopupMode.InstantPopup)
        add_menu = QtWidgets.QMenu(add)
        add_menu.aboutToShow.connect(lambda: self._ax() is not None and fill_add_menu(add_menu, self._ax(), self.canvas))
        add.setMenu(add_menu)
        add.setObjectName('csnButton')
        self.move = QtWidgets.QToolButton()
        self.move.setText('Move to')
        self.move.setObjectName('csnButton')
        self.move.setPopupMode(QtWidgets.QToolButton.ToolButtonPopupMode.InstantPopup)
        move_menu = QtWidgets.QMenu(self.move)
        move_menu.aboutToShow.connect(lambda: self._s() is not None and fill_move_menu(move_menu, self._s(), self.canvas))
        self.move.setMenu(move_menu)
        self.remove = QtWidgets.QPushButton('Remove')
        self.remove.setToolTip('Out of this plot. A series of the script can be put back from Add series')
        self.remove.clicked.connect(lambda: self._s() is not None and remove(self._s(), self.canvas))
        self.kind = QtWidgets.QComboBox()
        self.kind.activated.connect(lambda _=0: self._s() is not None and set_kind(self._s(), self.kind.currentData()))
        self.axis = _combo([('left', 'Left y axis'), ('right', 'Right y axis')])
        self.axis.activated.connect(lambda _=0: self._to_axis(self.axis.currentData()))
        self.tag = _hint()
        self.run = _hint()
        form = _form()
        form.addRow(self.list)
        form.addRow(_holder(_row(add, self.move, self.remove)))
        form.addRow('Drawn as', self.kind)
        form.addRow('On the', self.axis)
        form.addRow(self.tag)
        form.addRow(self.run)
        return _holder(form)

    def _look_section(self):
        self.same_look = QtWidgets.QCheckBox("Same appearance as its source")
        self.same_look.setToolTip("Off: this copy keeps an appearance of its own. On: it follows the series it shows")
        self.same_look.toggled.connect(self._same_look)
        self.look_note = _hint()
        self.editor = _style_editor.StyleEditor()
        self.editor.changed.connect(lambda s: self._refresher.start(0))
        column = QtWidgets.QVBoxLayout()
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(6)
        column.addWidget(self.look_note)
        column.addWidget(self.same_look)
        column.addWidget(self.editor)
        return _holder(column)

    def _trend_section(self):
        self.trend = _combo([(None, 'None'), *_fits.TRENDS])
        self.trend.activated.connect(lambda _=0: self._trend_changed())
        self.degree = _field(2, 2, 9, whole=True)
        self.degree.valueChanged.connect(lambda _=0: self._trend_changed())
        self.window = _field(5, 2, 100000, whole=True)
        self.window.valueChanged.connect(lambda _=0: self._trend_changed())
        self.equation = QtWidgets.QCheckBox('Equation and R² in the legend')
        self.equation.toggled.connect(lambda _=False: self._trend_changed())
        self.trend_info = _hint()
        self.trend_info.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        form = _form()
        form.addRow('Fit', self.trend)
        form.addRow('Degree', self.degree)
        form.addRow('Points averaged', self.window)
        form.addRow(self.equation)
        form.addRow(self.trend_info)
        self._trend_form = form
        return _holder(form)

    def _errors_section(self):
        self.errors = _combo([(None, 'None'), ('own', "The script's own"), *_fits.ERRORS])
        self.errors.activated.connect(lambda _=0: self._errors_changed())
        self.error_value = _field(0, 0, 1e15)
        self.error_value.stepper = _tenth_step
        self.error_value.valueChanged.connect(lambda _=0: self._errors_changed())
        self.error_source = QtWidgets.QComboBox()
        _narrow(self.error_source, 12)
        self.error_source.activated.connect(lambda _=0: self._errors_changed())
        self.error_axis = _combo([('y', 'y'), ('x', 'x'), ('both', 'x and y')])
        self.error_axis.activated.connect(lambda _=0: self._errors_changed())
        self.error_style = _combo([('bars', 'Bars with caps'), ('band', 'Shaded band')])
        self.error_style.activated.connect(lambda _=0: self._errors_changed())
        self.errors_info = _hint()
        form = _form()
        form.addRow('Errors', self.errors)
        form.addRow('Size', self.error_value)
        form.addRow('From series', self.error_source)
        form.addRow('Direction', self.error_axis)
        form.addRow('Drawn as', self.error_style)
        form.addRow(self.errors_info)
        self._errors_form = form
        return _holder(form)

    def _upto_section(self):
        self.upto_on = QtWidgets.QCheckBox('Show only up to x =')
        self.upto_on.toggled.connect(self._upto_toggled)
        self.upto_value = QtWidgets.QLineEdit()
        self.upto_value.setValidator(QtGui.QDoubleValidator())
        self.upto_value.setFixedWidth(110)
        self.upto_value.editingFinished.connect(self._upto_typed)
        self.upto_slider = QtWidgets.QSlider(Qt.Orientation.Horizontal)
        self.upto_slider.setRange(0, SLIDER_STEPS)
        self.upto_slider.valueChanged.connect(self._upto_slid)
        self.play = QtWidgets.QPushButton('Play')
        self.play.setToolTip('Draw the plot gradually, from its first point to its last')
        self.play.clicked.connect(self._play)
        self.seconds = _field(5, 0.5, 600, suffix=' s')
        self.seconds.setToolTip('How long Play takes, from the first point to the last')
        column = QtWidgets.QVBoxLayout()
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(6)
        column.addLayout(_row(self.upto_on, self.upto_value))
        column.addWidget(self.upto_slider)
        column.addLayout(_row(self.play, QtWidgets.QLabel('over'), self.seconds))
        column.addWidget(_hint('Its right-hand y axis and the plots sharing its x axis are cut with it. '
                               'Not kept for next time, like the zoom.'))
        return _holder(column)

    # ---- what's picked

    def least_width(self):
        """How wide the tab must be for nothing in it to scroll sideways."""
        bar = self._scroll.verticalScrollBar().sizeHint().width()
        margins = self.layout().contentsMargins()
        return self._scroll.widget().minimumSizeHint().width() + bar + margins.left() + margins.right()

    def _ax(self):
        ax = self.picked.ax
        return ax if ax is not None and ax.figure is self.canvas.figure else None

    def _s(self):
        s = self.picked.series
        return s if s is not None and self._ax() is not None and _view.main_of(s.ax) is self._ax() else None

    def show_plot(self, ax, series=None):
        """This plot (and series) in the panel."""
        self.picked.set(ax, series, by=None)
        self.refresh()

    def _picked_elsewhere(self, by):
        if by is not self:
            self._refresher.start(0)

    def scroll_to(self, name):
        """The section at the top of the tab, once it's laid out."""
        def scroll():
            section = self.sections.get(name)
            if section is not None and section.isVisible():
                body = self._scroll.widget()
                self._scroll.verticalScrollBar().setValue(section.mapTo(body, QtCore.QPoint(0, 0)).y() - 4)
        QtCore.QTimer.singleShot(0, scroll)

    def _chose_plot(self, index):
        ax = self.chooser.itemData(index)
        if ax is not None:
            self.picked.set(ax, None, by=self)
            self.refresh()

    def _chose_series(self, row):
        if self._loading or not (0 <= row < len(self._series)):
            return
        s = self._series[row]
        self.picked.set(s.ax, s, by=self)
        _sliders.select(s)
        self._load_series()

    def _rename(self):
        """F2: the picked series' name to edit in the list - else the plot's."""
        row = self.list.currentRow()
        if self._s() is not None and 0 <= row < self.list.count() and not _view.locked(self._s()):
            self.list.setFocus()
            self.list.editItem(self.list.item(row))
        elif self._ax() is not None:
            self.sections['Plot'].toggle.setChecked(True)
            self.name.setFocus()
            self.name.selectAll()

    def _named(self):
        ax = self._ax()
        if ax is not None and not self._loading:
            _view.set_plot_name(ax, self.name.text())

    # ---- following the figure

    def showEvent(self, event):
        super().showEvent(event)
        self.refresh()
        QtCore.QTimer.singleShot(0, self._fit_list)   # its rows measured as shown, not while hidden

    def hideEvent(self, event):
        super().hideEvent(event)
        self._marks(False)

    def eventFilter(self, watched, event):
        """The side panel (watched): the pointer coming over it, or leaving it - or over Appearance, where
        the series isn't lit: it's seen as it looks."""
        kind = event.type()
        if watched is self.sections.get('Appearance'):
            if kind in (QtCore.QEvent.Type.Enter, QtCore.QEvent.Type.Leave, QtCore.QEvent.Type.Hide):
                self._in_look = kind == QtCore.QEvent.Type.Enter
                self._marks()
            return False
        if kind == QtCore.QEvent.Type.Enter:
            self._inside = True
            self._marks()
        elif kind in (QtCore.QEvent.Type.Leave, QtCore.QEvent.Type.Hide):
            QtCore.QTimer.singleShot(0, lambda w=watched: self._left(w))
        return False

    def _left(self, side):
        """Gone from the side panel - not just into a drop-down or a menu opened from it."""
        try:   # what's under the pointer, not where: a tooltip over the panel isn't the panel
            under = QtWidgets.QApplication.widgetAt(QtGui.QCursor.pos())
            over = side.isVisible() and (QtWidgets.QApplication.activePopupWidget() is not None or
                                         under is side or (under is not None and side.isAncestorOf(under)))
        except RuntimeError:   # deleted meanwhile
            over = False
        if not over and self._inside:
            self._inside = False
            self._marks()

    def _marks(self, shown=True):
        """While the pointer's over the side panel and this tab's open: the plot it edits outlined, the
        series picked glowing - nothing lit once it's gone."""
        canvas = self.canvas
        ax, s = (self._ax(), self._s()) if shown and self._inside and self.isVisible() else (None, None)
        if hasattr(canvas, 'outline'):
            canvas.outline([ax] if ax is not None else [], hold=True, key='plot')
        inspector = getattr(canvas, 'inspector', None)
        if inspector is not None:
            inspector.glow('picked', [s] if s is not None and not self._in_look else [])

    def refresh(self):
        if not self.isVisible():
            return
        if self.canvas.computing:   # a run's thread is changing the figure: once it's done
            self._refresher.start(self.REFRESH_MS)
            return
        self._loading = True
        try:
            plots = _layout.plots(self.canvas.figure)
            if self.picked.ax not in plots:
                first = next((ax for ax in plots if ax.get_visible()), plots[0] if plots else None)
                self.picked.ax, self.picked.series = first, None
            self.chooser.clear()
            for ax in plots:
                self.chooser.addItem(_series.plot_name(ax) + ('' if ax.get_visible() else '  (hidden)'), ax)
            if self.picked.ax is not None:
                self.chooser.setCurrentIndex(plots.index(self.picked.ax))
            self.empty.setVisible(not plots)
            self._scroll.setVisible(bool(plots))
            self.chooser.setVisible(bool(plots))
            if self.picked.ax is not None:
                self._load_plot()
                self._load_list()
        finally:
            self._loading = False
        if self.picked.ax is not None:
            self._load_series()

    def _load_plot(self):
        ax = self.picked.ax
        self.name.setPlaceholderText(_series.plot_name(ax, given=False))
        if not self.name.hasFocus():
            self.name.setText(_series.given_name(ax))
        for field, text in ((self.title, ax.get_title()), (self.xlabel, ax.get_xlabel()), (self.ylabel, ax.get_ylabel())):
            if not field.hasFocus():
                field.setText(text)
        for axis in ('x', 'y'):
            _select(self.scales[axis], ax.get_xscale() if axis == 'x' else ax.get_yscale())
            low, high = ax.get_xlim() if axis == 'x' else ax.get_ylim()
            for field, value in zip(self.limits[axis], (low, high)):
                if not field.hasFocus():
                    field.setText(_number(value))
        grid = _view.grid(ax)
        self.grid_on.setChecked(bool(grid['on']))
        _select(self.grid_axis, grid.get('axis', 'both'))
        _select(self.grid_style, grid.get('style', '-'))
        self.grid_minor.setChecked(bool(grid.get('minor')))
        self.legend.setChecked(_view.legend_shown(ax))
        why = _view.can_swap(ax)
        self.swap.setEnabled(why is None)
        self.swap.setToolTip('Exchange the axes: each series plotted with its x on the vertical axis' if why is None
                             else f"Not possible: {why[0].lower()}{why[1:]}")
        added = getattr(ax, '_csn_added_plot', False)
        self.delete_plot.setVisible(added)
        can = _upto.supported(ax)
        self.sections['Show up to x'].setVisible(can)   # an image, a mesh: not offered at all
        if not can and _upto.get(ax) is not None:
            _upto.set_upto(ax, None)
        upto = _upto.get(ax)
        self.upto_on.setChecked(upto is not None)
        self._show_upto(upto)

    def _load_list(self):
        main = self.picked.ax
        series = series_in(main)
        signature = tuple((id(s.artist), s.label, s.visible(), _view.locked(s)) for s in series)
        picked = self.picked.series
        again = None
        if picked is not None:   # still picked when it's drawn anew - on the other axis, as another kind
            row = next((i for i, s in enumerate(self._series) if s.artist is picked.artist), None)
            again = (next((s for s in series if s.artist is picked.artist), None)
                     or next((s for s in series if _series.key_of(s) == _series.key_of(picked)), None)
                     or next((s for s in series if s.label == picked.label), None)
                     or (series[row] if row is not None and len(series) == len(self._series) else None))
        self.picked.series = again
        if signature != self._signature or len(self._series) != len(series):
            self._signature = signature
            self.list.clear()
            for s in series:
                item = QtWidgets.QListWidgetItem(_style_editor.preview(s), s.label)
                item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsUserCheckable
                              | (Qt.ItemFlag.NoItemFlags if _view.locked(s) else Qt.ItemFlag.ItemIsEditable))
                item.setCheckState(Qt.CheckState.Checked if s.visible() else Qt.CheckState.Unchecked)
                tag, tip = series_tag(s)
                right = ', right y axis' if s.ax is not main else ''
                item.setToolTip(f"{s.label} ({tag}{right}{', locked' if _view.locked(s) else ''}). {tip}")
                self.list.addItem(item)
            self._fit_list()
        else:
            for row, s in enumerate(series):
                self.list.item(row).setIcon(_style_editor.preview(s))
        self._series = series
        if again is None:   # nothing picked, or what was is gone: nothing picked - not a guess
            self.list.clearSelection()
        self.list.setCurrentRow(series.index(again) if again is not None else -1)

    def _fit_list(self):
        """The list as tall as its rows, up to LIST_MAX - past that, it scrolls."""
        rows = self.list.count()
        least = max(self.list.fontMetrics().height() + 10, self.list.iconSize().height() + 10, 26)
        row = max(self.list.sizeHintForRow(0) if rows else 0, least)   # never under a row's usual height
        content = max(rows, 1) * row
        if rows:   # as laid out, if it is: its rows' own heights, padding and all
            self.list.doItemsLayout()
            first, last = (self.list.visualItemRect(self.list.item(i)) for i in (0, rows - 1))
            if first.isValid() and last.isValid() and last.height() >= 16:
                content = max(content, last.bottom() - first.top() + 1 + self.list.spacing() * 2)
        self.list.setFixedHeight(min(content + 2 * self.list.frameWidth() + 4, self.LIST_MAX))
        self.list.updateGeometry()

    def _load_series(self):
        s = self._s()
        self._loading = True
        try:
            for name in ('Appearance', 'Trendline', 'Error bars'):
                self.sections[name].setVisible(s is not None)
            for widget in (self.move, self.remove, self.kind, self.axis):
                widget.setEnabled(s is not None)
            self._marks()
            if s is None:
                self.tag.setText('Pick a series to edit it: in the list, or click it on the plot.' if self._series
                                 else 'This plot has no series. Add one from any plot of the open tabs.')
                self.run.setText('')
                self.kind.clear()
                self.editor.show_series(None)
                return
            locked = _view.locked(s)
            tag, tip = series_tag(s)
            self.tag.setText(f"{tag.capitalize()}: {tip}." + (' Locked.' if locked else ''))
            found = _sliders.run_of(s)
            self.run.setText(f"Parameters: {found[0].describe(self._params(found))}" if found else '')
            self.run.setVisible(bool(found))
            self.kind.clear()
            for kind in kinds_for(s):
                self.kind.addItem(TYPES[kind], kind)
            _select(self.kind, kind_of(s))
            self.kind.setEnabled(self.kind.count() > 1 and not locked)
            self.axis.setCurrentIndex(0 if s.ax is self.picked.ax else 1)
            self.axis.setEnabled(not locked)
            self.remove.setEnabled(not locked)
            self.move.setEnabled(not locked)
            entry = _view.entry_of(s)
            copy = bool(entry is not None and entry.get('link'))
            self.same_look.setVisible(copy)
            if copy:
                self.same_look.setChecked(not entry.get('own_look'))
            copies = len(_series.members(s) or [s]) - 1
            look = self.sections['Appearance']
            if locked:
                self.look_note.setText(f"“{s.label}” is locked. Unlock it (data panel) to change its appearance.")
            elif copy and entry.get('own_look'):
                self.look_note.setText('This copy has an appearance of its own: changes apply to it alone.')
            elif copies:
                self.look_note.setText(f"Changes apply in every plot showing “{s.label}” "
                                       f"({copies + 1} plots), except copies with an appearance of their own.")
            else:
                self.look_note.setText('')
            self.look_note.setVisible(bool(self.look_note.text()))
            if locked:   # nothing to change there: folded away
                look.toggle.setChecked(False)
            elif self._was_locked:
                look.toggle.setChecked(True)
            self._was_locked = locked
            self.editor.setEnabled(not locked)
            self.same_look.setEnabled(not locked)
            self.editor.show_series(s)
            self._load_trend(s, locked)
            self._load_errors(s, locked)
        finally:
            self._loading = False

    def _params(self, found):
        parameters, run = found
        if run == _sliders.LIVE:
            return parameters.values
        return next((e.get('params') for e in _view.entries(run) if e.get('params')), {}) or {}

    def _load_trend(self, s, locked):
        spec = _fits.spec(s).get('trend') or {}
        _select(self.trend, spec.get('kind'))
        self.degree.setValue(int(spec.get('degree', 2)))
        self.window.setValue(int(spec.get('window', 5)))
        self.equation.setChecked(bool(spec.get('equation')))
        kind = spec.get('kind')
        self._trend_form.setRowVisible(self.degree, kind == 'poly')
        self._trend_form.setRowVisible(self.window, kind == 'mean')
        self._trend_form.setRowVisible(self.equation, kind not in (None, 'mean'))
        for widget in (self.trend, self.degree, self.window, self.equation):
            widget.setEnabled(not locked)
        info = _fits.info(s, 'trend')
        if not kind:
            text = 'A least-squares fit to the series, or its moving average, drawn as a dashed line.'
        elif info is None:
            text = ''
        elif 'error' in info:
            text = info['error']
        else:
            text = info['equation'] + (f"\nR² = {info['r2']:.6f}" if info.get('r2') is not None else '') \
                + f"\nfitted to {info['points']:,} points"
        self.trend_info.setText(text)

    def _load_errors(self, s, locked):
        spec = _fits.spec(s).get('errors') or {}
        kind = spec.get('kind')
        own = bool(s.parts) and not s.stem   # error bars the script drew with it (errorbar())
        self.errors.view().setRowHidden(self.errors.findData('own'), not own)   # offered only if there are some
        _select(self.errors, kind if kind not in (None, 'none') else 'own' if own and kind is None else None)
        self.error_value.setSuffix(' %' if kind == 'percent' else '')
        self.error_value.setDigits(6)
        self.error_value.setValue(float(spec.get('value', 0) or 0))
        self.error_source.clear()
        for other in (o for f in _series.open_figures() for a in f.axes for o in _series.series(a)):
            if other.artist is not s.artist and len(other) == len(s):
                self.error_source.addItem(f"{other.label} ({_series.plot_name(_view.main_of(other.ax))})",
                                          _series.key_of(other))
        _select(self.error_source, spec.get('source'))
        _select(self.error_axis, spec.get('axis', 'y'))
        _select(self.error_style, spec.get('style', 'bars'))
        self._errors_form.setRowVisible(self.error_value, kind in ('constant', 'percent'))
        self._errors_form.setRowVisible(self.error_source, kind == 'series')
        for widget in (self.error_axis, self.error_style):
            self._errors_form.setRowVisible(widget, kind not in (None, 'none'))
        for widget in (self.errors, self.error_value, self.error_source, self.error_axis, self.error_style):
            widget.setEnabled(not locked)
        info = _fits.info(s, 'errors')
        if not kind and own:
            from matplotlib.lines import Line2D   # here: only this needs it
            caps = sum(1 for part in s.parts if isinstance(part, Line2D))
            text = (f"It has error bars of its own, drawn by the script{' with caps' if caps else ''}: they're shown "
                    f"as they are. Pick another kind to draw error bars from a constant, a percentage or another "
                    f"series instead (the script's are hidden meanwhile), or None for none at all.")
        elif kind == 'none':
            text = "No error bars: the script's own are hidden." if own else 'No error bars.'
        elif not kind:
            text = 'Error bars from a constant, a percentage of each value, or the values of another series.'
        elif kind == 'series' and not self.error_source.count():
            text = f"No other series has {len(s):,} values, one for each point of this one."
        elif info is not None and 'error' in info:
            text = info['error']
        else:
            text = (info or {}).get('note', '')
        self.errors_info.setText(text)

    # ---- changes: the plot

    def _text(self, which, text):
        ax = self._ax()
        if ax is None or self._loading:
            return
        now = {'title': ax.get_title(), 'xlabel': ax.get_xlabel(), 'ylabel': ax.get_ylabel()}[which]
        if text != now:
            _view.set_text(ax.figure, f"{_series.ax_id(ax)}|{which}", text)

    def _scale(self, axis):
        ax = self._ax()
        if ax is not None and not self._loading:
            _view.set_scale(ax, axis, self.scales[axis].currentData())

    def _limits(self, axis):
        ax = self._ax()
        if ax is None or self._loading:
            return
        low, high = (field.text() for field in self.limits[axis])
        try:
            low, high = float(low), float(high)
        except ValueError:
            self._load_plot()
            return
        old = ax.get_xlim() if axis == 'x' else ax.get_ylim()
        log = (ax.get_xscale() if axis == 'x' else ax.get_yscale()) == 'log'
        if not (math.isfinite(low) and math.isfinite(high)) or low == high or (log and min(low, high) <= 0):
            self._load_plot()
            _say(self.canvas, 'Limits must be two different finite numbers (above 0 on a log scale)')
            return
        if (low, high) == tuple(old):
            return
        _series.quiet()
        (ax.set_xlim if axis == 'x' else ax.set_ylim)(low, high)
        if self.canvas.toolbar is not None:
            self.canvas.toolbar.push_current()
        self.canvas.draw_idle()

    def _fit(self):
        ax = self._ax()
        if ax is not None:
            self.canvas.navigation.reset([ax])

    def _grid(self, **changes):
        ax = self._ax()
        if ax is not None and not self._loading:
            _view.set_grid(ax, **changes)

    def _legend(self, on):
        ax = self._ax()
        if ax is not None and not self._loading:
            _view.set_legend(ax, on)

    def _swap(self):
        ax = self._ax()
        if ax is not None:
            _say(self.canvas, _view.swap_xy(ax))

    # ---- changes: the series

    def _series_ticked(self, item):
        if self._loading:
            return
        row = self.list.row(item)
        if 0 <= row < len(self._series):
            s = self._series[row]
            name = item.text().strip()
            if name != s.label:   # renamed (F2)
                if name and not _view.locked(s):
                    _view.rename(_series.key_of(s), name)
                else:
                    self._signature = None
                    self._refresher.start(0)
                return
            shown = item.checkState() == Qt.CheckState.Checked
            if shown != s.visible():
                _view.set_visible(_series.key_of(s), shown)

    def _series_menu(self, position):
        row = self.list.row(self.list.itemAt(position)) if self.list.itemAt(position) is not None else -1
        if not (0 <= row < len(self._series)):
            return
        menu = QtWidgets.QMenu(self)
        series_actions(menu, self._series[row], self.canvas)
        menu.exec(self.list.viewport().mapToGlobal(position))

    def _to_axis(self, side):
        s, main = self._s(), self._ax()
        if s is None or main is None or self._loading:
            return
        target = _view.right_axis(main) if side == 'right' else main
        if target is not s.ax:
            _say(self.canvas, _view.move_to_plot(s, target))

    def _same_look(self, on):
        s = self._s()
        entry = _view.entry_of(s) if s is not None else None
        if entry is not None and not self._loading:
            set_own_look(entry['id'], not on)

    def _trend_changed(self):
        s = self._s()
        if s is None or self._loading:
            return
        kind = self.trend.currentData()
        old = _fits.spec(s).get('trend') or {}
        value = None if kind is None else {**old, 'kind': kind, 'degree': self.degree.value(),
                                           'window': self.window.value(), 'equation': self.equation.isChecked()}
        _fits.set_trend(s, value)
        self._load_series()

    def _errors_changed(self):
        s = self._s()
        if s is None or self._loading:
            return
        kind = self.errors.currentData()
        old = _fits.spec(s).get('errors') or {}
        own = bool(s.parts) and not s.stem
        value = None
        if kind is None and own:   # none at all: the script's own hidden too
            value = {'kind': 'none'}
        elif kind not in (None, 'own'):
            value = {**old, 'kind': kind, 'value': self.error_value.value(), 'axis': self.error_axis.currentData(),
                     'style': self.error_style.currentData()}
            if kind == 'series':
                value['source'] = self.error_source.currentData()
            if kind != old.get('kind') and kind in ('constant', 'percent') and not value['value']:
                value['value'] = 10.0 if kind == 'percent' else _default_error(s)
        _fits.set_errors(s, value)
        self._load_series()

    # ---- show up to x

    def _show_upto(self, x):
        ax = self._ax()
        span = _upto.span(ax) if ax is not None else None
        self.upto_slider.setEnabled(span is not None)
        self.play.setEnabled(span is not None)
        self.upto_slider.blockSignals(True)
        if span is not None:
            low, high = span
            at = high if x is None else x
            self.upto_slider.setValue(int(round(_upto.Player.share(ax, low, high, at) * SLIDER_STEPS)))
            if not self.upto_value.hasFocus():
                self.upto_value.setText(_number(at))
        self.upto_slider.blockSignals(False)
        self.play.setText('Stop' if self.player.playing else 'Play')

    def _upto_toggled(self, on):
        ax = self._ax()
        if ax is None or self._loading:
            return
        if not on:
            self.player.stop()
            _upto.set_upto(ax, None)
        else:
            self._upto_slid(self.upto_slider.value())

    def _upto_slid(self, position):
        ax = self._ax()
        span = _upto.span(ax) if ax is not None else None
        if span is None or self._loading:
            return
        low, high = span
        x = _upto.Player.at(ax, low, high, position / SLIDER_STEPS)   # evenly along the axis: by decades on a log one
        self.upto_value.setText(_number(x))
        self._loading = True
        self.upto_on.setChecked(True)
        self._loading = False
        _upto.set_upto(ax, x)

    def _upto_typed(self):
        ax = self._ax()
        try:
            x = float(self.upto_value.text())
        except ValueError:
            return
        if ax is not None and math.isfinite(x):
            self._loading = True
            self.upto_on.setChecked(True)
            self._loading = False
            _upto.set_upto(ax, x)
            self._show_upto(x)

    def _play(self):
        ax = self._ax()
        if self.player.playing:
            self.player.stop()
            return
        if ax is not None and self.player.play(ax, self.seconds.value()):   # from the first point, wherever the slider is
            self.play.setText('Stop')

    def _played(self, x):
        self._loading = True
        self.upto_on.setChecked(True)
        self._loading = False
        self._show_upto(x)

    def _play_ended(self):
        self.play.setText('Play')
        ax = self._ax()
        self._loading = True
        self.upto_on.setChecked(ax is not None and _upto.get(ax) is not None)
        self._loading = False


def _field(value, low, high, whole=False, suffix=''):
    """A number field kept in its range, at that value."""
    field = NumberField(whole=whole, suffix=suffix)
    field.setRange(low, high)
    field.clamp = True
    field.setValue(value)
    field.setFixedWidth(110)
    return field


def _tenth_step(value, way):
    """One nudge of an error's size: a tenth of its order of magnitude."""
    if not value:
        return max(0.0, 0.1 * way)
    unit = 10 ** math.floor(math.log10(abs(value))) / 10
    return round((value + way * unit) / unit) * unit


def _default_error(s):
    """A first constant error: a tenth of the series' spread."""
    try:
        y = s.floats()[1]
        spread = float(y[y == y].max() - y[y == y].min())
        return float(f"{spread / 10:.2g}") if spread > 0 and math.isfinite(spread) else 1.0
    except (ValueError, TypeError):
        return 1.0


# ---- the right-click menus

def series_actions(menu, s, canvas):
    """A series' entries in a menu: hide, appearance, remove, move, copy, lock, delete."""
    locked = _view.locked(s)
    key = _series.key_of(s)
    menu.addAction('Hide' if s.visible() else 'Show', lambda: _view.set_visible(key, not s.visible()))
    menu.addAction('Edit appearance…', lambda: canvas.open_look(s)).setEnabled(not locked)
    move = menu.addMenu('Move to')
    move.aboutToShow.connect(lambda: fill_move_menu(move, s, canvas))
    move.setEnabled(not locked)
    copy = menu.addMenu('Also show in')
    copy.aboutToShow.connect(lambda: fill_move_menu(copy, s, canvas, copy=True))
    menu.addAction('Remove from this plot', lambda: remove(s, canvas)).setEnabled(not locked)
    menu.addSeparator()
    menu.addAction('Unlock' if locked else 'Lock', lambda: _view.set_locked(_sliders.run_series(s), not locked))
    menu.addAction('Delete everywhere…', lambda: delete_everywhere(s, canvas)).setEnabled(not locked)


def plot_menu(canvas, ax, at):
    """A plot's right-click menu: its series, a title, moving and hiding it."""
    main = _view.main_of(ax)
    figure = main.figure
    menu = QtWidgets.QMenu(canvas)
    menu.setToolTipsVisible(True)
    menu.addAction(_series.plot_name(main)).setEnabled(False)
    menu.addAction('Edit in the side panel', lambda: canvas.manager.show_plot_panel(main))
    menu.addAction('Rename…', lambda: ask_name(canvas, main)).setToolTip(
        'What the plot is called where it is listed - its title stays as it is')
    menu.addAction('Title…', lambda: _ask_title(canvas, main))
    menu.addSeparator()
    add = menu.addMenu('Add series')
    add.aboutToShow.connect(lambda: fill_add_menu(add, main, canvas))
    for s in series_in(main):
        sub = menu.addMenu(_style_editor.preview(s), s.label)
        series_actions(sub, s, canvas)
    menu.addSeparator()
    grid = menu.addAction('Grid', lambda: _view.set_grid(main, on=not _view.grid(main)['on']))
    grid.setCheckable(True)
    grid.setChecked(bool(_view.grid(main)['on']))
    legend = menu.addAction('Legend', lambda: _view.set_legend(main, not _view.legend_shown(main)))
    legend.setCheckable(True)
    legend.setChecked(_view.legend_shown(main))
    swap = menu.addAction('Swap x and y', lambda: _say(canvas, _view.swap_xy(main)))
    why = _view.can_swap(main)
    swap.setEnabled(why is None)
    if why is not None:
        swap.setToolTip(why)
    menu.addAction('Fit to data', lambda: canvas.navigation.reset([main]))
    menu.addSeparator()
    tabs = menu.addMenu('Move plot to')
    for other in _series.open_figures():
        if other is not figure:
            tabs.addAction(_series.tab_name(other), lambda _=False, o=other: _layout.move_to(main, o))
    if not tabs.isEmpty():
        tabs.addSeparator()
    tabs.addAction('A new tab', lambda: _layout.move_to_new_tab(main))
    menu.addAction('Duplicate plot', lambda: _layout.copy_plot(main)).setToolTip(
        'A new plot in this tab, showing the same series (linked copies) with the same labels and scales')
    menu.addAction('Hide plot', lambda: _layout.hide(main)).setToolTip(
        'Out of the way, not deleted: listed in the Layout tab, to show again')
    if getattr(main, '_csn_added_plot', False):
        menu.addAction('Delete plot…', lambda: _layout.delete_plot(main, canvas))
    menu.exec(at)


def ask_name(canvas, ax):
    """The plot's name, asked for (F2 on the plot, its menu's Rename)."""
    ax = _view.main_of(ax)
    text, ok = QtWidgets.QInputDialog.getText(canvas, 'Rename plot', 'Name (empty: its own name):',
                                              text=_series.plot_name(ax))
    if ok:
        _view.set_plot_name(ax, text)


def _ask_title(canvas, ax):
    text, ok = QtWidgets.QInputDialog.getText(canvas, 'Plot title', 'Title:', text=ax.get_title())
    if ok and text != ax.get_title():
        _view.set_text(ax.figure, f"{_series.ax_id(ax)}|title", text)


def figure_menu(canvas, at):
    """The menu of the space around the plots."""
    figure = canvas.figure
    menu = QtWidgets.QMenu(canvas)
    menu.addAction('New plot in this tab', lambda: _layout.new_plot(figure))
    menu.addAction('New tab', lambda: _layout.new_plot(figure, new_tab=True))
    menu.addSeparator()
    menu.addAction('Arrange plots…', lambda: canvas.manager.show_side('Layout'))
    menu.addAction('Copy image', canvas.manager.copy_image)
    if canvas.toolbar is not None:
        menu.addAction('Save figure…', canvas.toolbar.save_figure)
    menu.exec(at)
