"""The data panel, beside the plot: every series of every plot of the tab, under its plot's name - a
tick shows or hides it (in every plot it's in), a double-click (or F2) renames it, the padlock locks
it (and the rest of its run): looked at and copied, never changed. A plot's name: F2 renames it, a
double-click or the arrow at its right folds its series away. Its tag says where it comes from
(the script, the original run of the sliders, a saved run, a copy of a series in another plot).
Its right-click menu also shows it in other plots, moves it, sends a faint reference copy, removes
it from its plot (Delete) or deletes it everywhere. Picking a series - here, in the Plot tab, or by clicking
it on the plot - puts the parameters of its run on the sliders. Picking a plot's name outlines it on
the plot and opens it in the Plot tab; hovering over a plot's name outlines it too, over a series
lights the series up.
For the series picked, in sections that fold away: its statistics - how many points, where it
starts and ends (the initial condition, for a time series), its x step and whether that's even, its
lowest, highest and mean, the parameters of its run - and a table of all its values. A row picked is
pinned on the plot, a double-click pans there, Ctrl+C copies the rows picked and the table's
right-click menu copies whole columns or the lot. The statistics of a series of more than
THREADED points are worked out in a thread.
It follows the figure: a redraw with new or changed data refreshes it (REFRESH_MS after), and so
does anything undone or redone."""
import threading

import numpy as np
from PySide6 import QtCore, QtGui, QtWidgets

from . import _plot_panel, _series, _sliders, _style, _style_editor, _view
from ._history import history
from ._widgets import InlineDelegate, Section, Splitter

Qt = QtCore.Qt
THREADED = 200_000   # a series of more points: its statistics are worked out in a thread


class _Mailbox(QtCore.QObject):
    done = QtCore.Signal(object, str)   # (the series, the statistics) - from the thread


class DataPanel(QtWidgets.QWidget):
    REFRESH_MS = 400
    WIDTH = 340   # its first width, opened
    ADD_ROLE = Qt.ItemDataRole.UserRole + 3   # an empty plot's Add series row: that plot's ax_id()

    def __init__(self, canvas):
        super().__init__()
        self.setObjectName('csnPanel')
        self.setMinimumWidth(1)   # so it can open and close smoothly (not snap at its contents' least width)
        self.canvas = canvas
        self._entries, self._signature, self._picked = [], None, None
        self._folded = set()   # the ax_id()s of the plots folded away
        self._mainbox = _Mailbox()
        self._mainbox.done.connect(self._stats_done)
        self._refresher = QtCore.QTimer(self)
        self._refresher.setSingleShot(True)
        self._refresher.timeout.connect(self.refresh)
        canvas.mpl_connect('draw_event', lambda event: self._refresher.start(self.REFRESH_MS))
        history.listeners.append(lambda: self._refresher.start(0))
        canvas.picked.changed.connect(self._picked_elsewhere)

        self.heading = QtWidgets.QLabel('Data')
        self.heading.setObjectName('csnHeading')
        self.tree = QtWidgets.QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setColumnCount(4)
        self.tree.setRootIsDecorated(False)
        self.tree.setIndentation(10)
        self.tree.setIconSize(QtCore.QSize(30, 14))
        self.tree.setMouseTracking(True)
        header = self.tree.header()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeMode.Stretch)
        for column in (1, 2, 3):
            header.setSectionResizeMode(column, QtWidgets.QHeaderView.ResizeMode.ResizeToContents)
        self.tree.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.EditKeyPressed)   # a double-click: _double
        self._delegate = InlineDelegate(self.tree, folder=self._folds)
        self.tree.setItemDelegate(self._delegate)
        self.tree.itemDoubleClicked.connect(self._double)
        self.tree.itemCollapsed.connect(lambda item: self._fold(item, True))
        self.tree.itemExpanded.connect(lambda item: self._fold(item, False))
        self.tree.itemChanged.connect(self._item_changed)
        self.tree.currentItemChanged.connect(lambda item, _: self._pick(item, chosen=True))
        self.tree.itemClicked.connect(self._clicked)
        self._unlit = None   # a series shown or hidden from its row: not lit till the pointer leaves it
        self._under = None   # (the row under the pointer, on its tick box): lit as it changes
        self.tree.viewport().installEventFilter(self)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._tree_menu)
        delete = QtGui.QShortcut(QtGui.QKeySequence(QtGui.QKeySequence.StandardKey.Delete), self.tree)
        delete.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        delete.activated.connect(self._delete)

        self.stats = QtWidgets.QLabel()
        self.stats.setObjectName('csnStats')
        self.stats.setTextFormat(Qt.TextFormat.RichText)
        self.stats.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.stats.setWordWrap(True)
        self.model = _Values()
        self.table = QtWidgets.QTableView()
        self.table.setModel(self.model)
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        self.table.verticalHeader().hide()
        self.table.verticalHeader().setDefaultSectionSize(22)
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QtWidgets.QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeMode.Fixed)   # as wide as the last row's number
        self.table.selectionModel().currentRowChanged.connect(lambda current, _: self._row(current.row()))
        self.table.doubleClicked.connect(lambda index: self._go_to(index.row()))
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._menu)
        copy = QtGui.QShortcut(QtGui.QKeySequence(QtGui.QKeySequence.StandardKey.Copy), self.table)
        copy.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        copy.activated.connect(self._copy_rows)

        self.sections = [Section('Statistics', self.stats), Section('Values', self.table)]
        details = QtWidgets.QWidget()
        details_layout = QtWidgets.QVBoxLayout(details)
        details_layout.setContentsMargins(0, 0, 0, 0)
        details_layout.setSpacing(8)
        for section, stretch in zip(self.sections, (0, 1000)):
            section.place(details_layout, stretch)
        details_layout.addStretch(1)   # the room, while the values are folded away: the sections stay at the top
        inner = Splitter(Qt.Orientation.Vertical)
        inner.addWidget(self.tree)
        inner.addWidget(details)
        inner.setStretchFactor(1, 1)
        inner.setSizes([180, 460])
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 12)
        layout.setSpacing(8)
        layout.addWidget(self.heading)
        layout.addWidget(inner, 1)

    # ---- following the figure

    def showEvent(self, event):
        super().showEvent(event)
        self.refresh()

    def hideEvent(self, event):
        super().hideEvent(event)
        self._light(None, None)

    def eventFilter(self, watched, event):
        if watched is self.tree.viewport():
            kind = event.type()
            if kind == QtCore.QEvent.Type.Leave:
                self._unlit = self._under = None
                self._light(None, None)
            elif kind == QtCore.QEvent.Type.MouseMove:   # over a series' tick box: nothing lit (it shows or hides it)
                at = event.position().toPoint()
                item = self.tree.itemAt(at)
                on_box = item is not None and self._series_of(item) is not None and self._on_box(at)
                if (id(item), on_box) != self._under:
                    self._under = (id(item), on_box)
                    if on_box:
                        self._light(None, None)
                    elif item is not None:
                        self._hovered(item, 0)
            elif kind == QtCore.QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
                at = event.position().toPoint()
                item = self.tree.itemAt(at)
                if item is not None and self._plot_of(item) is not None and item.childCount() \
                        and self._delegate.arrow_rect(self._row_rect(item)).contains(at):
                    item.setExpanded(not item.isExpanded())   # its arrow: folded or opened
                    return True
        return super().eventFilter(watched, event)

    def _on_box(self, at):
        """Whether the point is on the row's tick box (a little round it)."""
        index = self.tree.indexAt(at)
        option = QtWidgets.QStyleOptionViewItem()
        option.rect = self.tree.visualRect(index)
        try:
            self._delegate.initStyleOption(option, index)
            box = self.tree.style().subElementRect(QtWidgets.QStyle.SubElement.SE_ItemViewItemCheckIndicator,
                                                   option, self.tree)
        except (AttributeError, TypeError):
            box = QtCore.QRect()
        if not box.isValid():
            box = QtCore.QRect(option.rect.left(), option.rect.top(), 22, option.rect.height())
        return box.adjusted(-4, -4, 4, 4).contains(at)

    def _row_rect(self, item):
        rect = self.tree.visualItemRect(item)
        return QtCore.QRect(0, rect.top(), self.tree.viewport().width(), rect.height())

    def _folds(self, index):
        """Whether the row at that index is a plot's name, with series to fold away."""
        item = self.tree.itemFromIndex(index) if index.column() == 0 else None
        return item is not None and item.parent() is None and item.childCount() > 0

    def _fold(self, item, folded):
        identity = item.data(0, Qt.ItemDataRole.UserRole + 1)
        if identity:
            (self._folded.add if folded else self._folded.discard)(identity)

    def _double(self, item, column):
        """A double-click: a series renamed (a plot's name folds - the tree's own)."""
        s = self._series_of(item)
        if s is not None and column == 0 and not _view.locked(s) and self._on_name(item):
            self.tree.editItem(item, 0)

    def _on_name(self, item):
        """Whether the pointer's on the row's name - not its tick box or its marker."""
        at = self.tree.viewport().mapFromGlobal(QtGui.QCursor.pos())
        index = self.tree.indexAt(at)
        option = QtWidgets.QStyleOptionViewItem()
        option.rect = self.tree.visualRect(index)
        try:
            self._delegate.initStyleOption(option, index)
            text = self.tree.style().subElementRect(QtWidgets.QStyle.SubElement.SE_ItemViewItemText, option, self.tree)
        except (AttributeError, TypeError):
            return not self._on_box(at)
        return text.contains(at) if text.isValid() else not self._on_box(at)

    def _light(self, ax, s):
        """Under the pointer: the plot outlined, or the series lit up on the plot."""
        self.canvas.outline([ax] if ax is not None else [], hold=True)
        inspector = getattr(self.canvas, 'inspector', None)
        if inspector is not None:
            inspector.glow('panel', [s] if s is not None else [])

    def refresh(self):
        if not self.isVisible():
            return
        if getattr(self.canvas, 'computing', False):   # a run's thread is changing the figure: once it's done
            self._refresher.start(self.REFRESH_MS)
            return
        mains = [ax for ax in self.canvas.figure.axes if _view.main_of(ax) is ax]
        entries = [s for main in mains for s in _plot_panel.series_in(main)]
        signature = tuple((id(s.ax), id(s.artist), s.label, len(s)) for s in entries)
        picked = self._picked
        self._entries = entries
        if signature != self._signature:
            self._signature = signature
            self._rebuild(picked)
            return
        self._picked = self._match(picked)
        if self._picked is not None and not self.model.same(*self._picked.data()):
            self._show(self._picked)
        self._update_items()   # a look changed, a lock, or something undone

    def _match(self, old):
        """The series that was picked, as it is now - the same artist, or drawn again under its name."""
        if old is None:
            return None
        return (next((s for s in self._entries if s.artist is old.artist), None)
                or next((s for s in self._entries if s.ax is old.ax and _series.name_of(s) == _series.name_of(old)), None))

    def _rebuild(self, picked):
        tree = self.tree
        tree.blockSignals(True)
        tree.clear()
        mains = list(dict.fromkeys(_view.main_of(s.ax) for s in self._entries))
        empty = [ax for ax in self.canvas.figure.axes if _view.main_of(ax) is ax and ax not in mains
                 and not hasattr(ax, '_colorbar')]
        again = self._match(picked)
        current = None
        for main in mains + empty:
            hidden = '' if main.get_visible() else '  (hidden)'
            parent = QtWidgets.QTreeWidgetItem([_series.plot_name(main) + hidden, '', '', ''])
            parent.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEditable)
            parent.setData(0, Qt.ItemDataRole.UserRole + 1, _series.ax_id(main))
            font = parent.font(0)
            font.setBold(True)
            parent.setFont(0, font)
            parent.setForeground(0, QtGui.QColor(_style.TEXT_2))
            parent.setToolTip(0, 'Click to outline this plot and edit it in the Plot tab. F2 renames it, '
                                 'a double-click or the arrow folds it')
            tree.addTopLevelItem(parent)
            parent.setFirstColumnSpanned(True)
            if main in empty:   # a row that adds one: a click gives every series there is to copy in
                note = QtWidgets.QTreeWidgetItem(['+  Add series…', '', '', ''])
                note.setFlags(Qt.ItemFlag.ItemIsEnabled)
                note.setForeground(0, QtGui.QColor(_style.ACCENT))
                note.setData(0, self.ADD_ROLE, _series.ax_id(main))
                note.setToolTip(0, 'Copy a series of any plot into this one')
                parent.addChild(note)
                note.setFirstColumnSpanned(True)
            for s in (s for s in self._entries if _view.main_of(s.ax) is main):
                item = QtWidgets.QTreeWidgetItem(['', f"{len(s):,}", '', ''])
                item.setData(0, Qt.ItemDataRole.UserRole, self._entries.index(s))
                item.setForeground(1, QtGui.QColor(_style.TEXT_3))
                item.setToolTip(1, 'Number of points')
                self._fill(item, s)
                parent.addChild(item)
                if again is not None and s is again:
                    current = item
        if current is None and self._entries:
            current = next((item for item in self._items() if self._series_of(item) is self._entries[0]), None)
        tree.expandAll()
        for item in self._items():
            if item.data(0, Qt.ItemDataRole.UserRole + 1) in self._folded:
                item.setExpanded(False)
        if current is not None:
            tree.setCurrentItem(current)
        tree.blockSignals(False)
        if current is not None:
            self._pick(current)
        else:
            self._picked = None
            self._show(None)

    def _fill(self, item, s):
        """An item's name, preview, tick, tag and padlock, as the series is now."""
        locked = _view.locked(s)
        flags = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsUserCheckable
        item.setFlags(flags if locked else flags | Qt.ItemFlag.ItemIsEditable)
        right = s.ax is not _view.main_of(s.ax)
        item.setText(0, s.label + ('  (right axis)' if right else ''))
        item.setIcon(0, _style_editor.preview(s))
        item.setCheckState(0, Qt.CheckState.Checked if s.visible() else Qt.CheckState.Unchecked)
        copies = len(_series.members(s) or [s])
        item.setToolTip(0, f"{s.label}: {s.kind}" + (f", in {copies} plots" if copies > 1 else '')
                        + ('. Locked' if locked else '. Double-click to rename'))
        tag, tip = _plot_panel.series_tag(s)
        item.setText(2, tag)
        item.setForeground(2, QtGui.QColor(_style.ACCENT if _series.added(s) is not None else _style.TEXT_3))
        item.setToolTip(2, tip)
        item.setIcon(3, _padlock(locked))
        item.setToolTip(3, 'Locked: it can be looked at and copied, not changed. Click to unlock' if locked
                        else 'Click to lock it: it can then be looked at and copied, not changed')

    def _update_items(self):
        self.tree.blockSignals(True)
        for item in self._items():
            s = self._series_of(item)
            if s is not None:
                self._fill(item, s)
        self.tree.blockSignals(False)

    # ---- picking and changing

    def _series_of(self, item):
        index = item.data(0, Qt.ItemDataRole.UserRole) if item is not None else None
        return self._entries[index] if index is not None and index < len(self._entries) else None

    def _plot_of(self, item):
        identity = item.data(0, Qt.ItemDataRole.UserRole + 1) if item is not None else None
        return _series.axes_of(identity) if identity else None

    def _pick(self, item, chosen=False):
        ax = self._plot_of(item)
        if ax is not None:   # a plot's name: outlined, and in the Plot tab
            if chosen:
                self.canvas.picked.set(ax, None, by=self)
                self.canvas.outline([ax])
            return
        s = self._series_of(item)
        if s is None:
            return
        self._picked = s
        self._show(s)
        if chosen:   # picked by hand (not the panel following a redraw): the sliders show its run
            self.canvas.picked.set(s.ax, s, by=self)
            _sliders.select(s)

    def _clicked(self, item, column):
        empty = item.data(0, self.ADD_ROLE)
        if empty:   # an empty plot's Add series row
            ax = _series.axes_of(empty)
            if ax is not None:
                menu = QtWidgets.QMenu(self)
                _plot_panel.fill_add_menu(menu, ax, self.canvas)
                menu.exec(QtGui.QCursor.pos())
            return
        s = self._series_of(item)
        if s is not None and column == 3:
            self._toggle_lock(s)
        elif s is not None:   # picked already, clicked again: its run on the sliders all the same
            self.canvas.picked.set(s.ax, s, by=self)
            _sliders.select(s)
        elif self._plot_of(item) is not None:
            self.canvas.picked.set(self._plot_of(item), None, by=self)
            self.canvas.outline([self._plot_of(item)])

    def _hovered(self, item, column):
        s = self._series_of(item)
        if s is not None and self._unlit is not None and _series.key_of(s) == self._unlit:
            return   # just shown or hidden from its row: lit again once the pointer's come back to it
        self._unlit = None
        self._light(self._plot_of(item), s)

    def _picked_elsewhere(self, by):
        """A series picked in the Plot tab or on the plot: picked here too."""
        s = self.canvas.picked.series
        if by is self or s is None or not self.isVisible():
            return
        for item in self._items():
            mine = self._series_of(item)
            if mine is not None and mine.artist is s.artist:
                if self.tree.currentItem() is not item:
                    self.tree.blockSignals(True)
                    self.tree.setCurrentItem(item)
                    self.tree.blockSignals(False)
                    self._pick(item)
                break

    def _toggle_lock(self, s):
        """The series locked or unlocked - with the rest of its run, if it's from one."""
        _view.set_locked(_sliders.run_series(s), not _view.locked(s))

    def _say(self, text):
        self.canvas.say(text)

    def _item_changed(self, item, column):
        ax = self._plot_of(item)
        if ax is not None and column == 0:   # a plot renamed
            name = item.text(0).replace('  (hidden)', '').strip()
            if name != _series.plot_name(ax):
                _view.set_plot_name(ax, name)
            return
        s = self._series_of(item)
        if s is None or column != 0:
            return
        key = _series.key_of(s)
        name = item.text(0).replace('  (right axis)', '').strip()
        if name != s.label:
            if name and not _view.locked(s):
                _view.rename(key, name)
            else:   # emptied, or locked: as it was
                self._update_items()
                if name:
                    self._say(f"“{s.label}” is locked. Unlock it to rename it")
            return
        shown = item.checkState(0) == Qt.CheckState.Checked
        if shown != s.visible():
            self._unlit = key   # not lit up now, with the pointer still on its row
            self._light(None, None)
            _view.set_visible(key, shown)

    def _delete(self):
        """Delete: the series picked out of its plot - only that one (its menu deletes it everywhere)."""
        if self._picked is not None:
            _plot_panel.remove(self._picked, self.canvas)

    def _tree_menu(self, position):
        item = self.tree.itemAt(position)
        ax = self._plot_of(item)
        if ax is not None:
            self.canvas.plot_menu(ax, self.tree.viewport().mapToGlobal(position))
            return
        s = self._series_of(item)
        if s is None:
            return
        locked = _view.locked(s)
        menu = QtWidgets.QMenu(self)
        menu.addAction('Rename', lambda: self.tree.editItem(item, 0)).setEnabled(not locked)
        menu.addSeparator()
        _plot_panel.series_actions(menu, s, self.canvas)
        reference = QtWidgets.QMenu('Reference copy in', menu)
        for other, name in _plots():
            if other is not _view.main_of(s.ax):
                reference.addAction(name, lambda _=False, a=other: self._say(_view.copy_to(s, a, shadow=True)))
        reference.setEnabled(not reference.isEmpty())
        reference.setToolTip('A faint linked copy, for comparison')
        remove = next((a for a in menu.actions() if a.text() == 'Remove from this plot'), None)
        menu.insertMenu(remove, reference)
        menu.exec(self.tree.viewport().mapToGlobal(position))

    def _row(self, row):
        inspector = getattr(self.canvas, 'inspector', None)
        if inspector is not None and self._picked is not None and row >= 0:
            inspector.pin(self._picked, row)

    def _go_to(self, row):
        inspector = getattr(self.canvas, 'inspector', None)
        if inspector is not None and self._picked is not None:
            inspector.centre_on(self._picked, row)

    def show_point(self, series, index):
        """From a click on the plot: that series picked, that row picked and in view."""
        if not self.isVisible():
            return
        for item in self._items():
            s = self._series_of(item)
            if s is not None and s.artist is series.artist:
                if self._picked is None or self._picked.artist is not s.artist:
                    self.tree.blockSignals(True)
                    self.tree.setCurrentItem(item)
                    self.tree.blockSignals(False)
                    self._pick(item)
                break
        if self._picked is not None and self._picked.artist is series.artist and index < self.model.rowCount():
            model_index = self.model.index(index, 0)
            self.table.selectionModel().blockSignals(True)
            self.table.setCurrentIndex(model_index)
            self.table.selectionModel().blockSignals(False)
            self.table.selectRow(index)
            self.table.scrollTo(model_index, QtWidgets.QAbstractItemView.ScrollHint.PositionAtCenter)

    def _items(self):
        found = []
        stack = [self.tree.invisibleRootItem()]
        while stack:
            item = stack.pop()
            found.append(item)
            stack.extend(item.child(i) for i in range(item.childCount()))
        return found

    # ---- what it shows

    def _show(self, s):
        self.model.show(s)
        last = str(max(self.model.rowCount() - 1, 0))
        self.table.horizontalHeader().resizeSection(0, max(self.table.fontMetrics().horizontalAdvance(last) + 20, 30))
        for section in self.sections:
            section.setVisible(s is not None)
        if s is None:
            self.stats.setText('')
        elif len(s) > THREADED:
            self.stats.setText(f"<b style='color:{_style.TEXT}'>{s.label}</b><br>Computing statistics of "
                               f"{len(s):,} points…")
            extra = _run_rows(s)   # here: it looks through the figures, which only this thread may
            threading.Thread(target=lambda: self._mainbox.done.emit(s, _stats(s, extra)), daemon=True,
                             name='csn_matplotlib statistics').start()
        else:
            self.stats.setText(_stats(s, _run_rows(s)))

    def _stats_done(self, s, text):
        if self._picked is not None and self._picked.artist is s.artist:
            self.stats.setText(text)

    def _menu(self, position):
        if self._picked is None:
            return
        x_name, y_name = self.model.names
        menu = QtWidgets.QMenu(self)
        menu.addAction('Copy rows', self._copy_rows)
        menu.addAction(f'Copy {x_name} as a list', lambda: self._copy_column(0))
        menu.addAction(f'Copy {y_name} as a list', lambda: self._copy_column(1))
        menu.addAction('Copy all as CSV', self._copy_all)
        menu.exec(self.table.viewport().mapToGlobal(position))

    def _copy_rows(self):
        rows = sorted({index.row() for index in self.table.selectionModel().selectedRows()})
        if rows:
            x, y = self.model.x, self.model.y
            _clip('\n'.join(f"{_series.text(x[r])}\t{_series.text(y[r])}" for r in rows))

    def _copy_column(self, which):
        values = (self.model.x, self.model.y)[which]
        if values is not None:
            _clip(repr(np.asarray(values).tolist()))

    def _copy_all(self):
        x, y = self.model.x, self.model.y
        if x is not None:
            x_name, y_name = self.model.names
            _clip('\n'.join([f"{x_name},{y_name}"] + [f"{_series.text(a)},{_series.text(b)}" for a, b in zip(x, y)]))


def _plots():
    """[(axes, name)] for every plot shown in every open tab."""
    figures = _series.open_figures()
    found = []
    for figure in figures:
        for ax in figure.axes:
            if ax.get_visible() and _view.main_of(ax) is ax and not hasattr(ax, '_colorbar'):
                name = _series.plot_name(ax)
                found.append((ax, f"{_series.tab_name(figure)}: {name}" if len(figures) > 1 else name))
    return found


def _padlock(locked):
    """The lock column's icon: shut and plain to see, or open and faint."""
    ratio = 3.0
    pixmap = QtGui.QPixmap(int(30 * ratio), int(14 * ratio))
    pixmap.setDevicePixelRatio(ratio)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QtGui.QPainter(pixmap)
    painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
    colour = QtGui.QColor(_style.TEXT if locked else _style.TEXT_3)
    if not locked:
        colour.setAlpha(150)
    painter.setPen(QtGui.QPen(colour, 1.3))
    painter.setBrush(colour if locked else QtGui.QBrush(Qt.BrushStyle.NoBrush))
    painter.drawRoundedRect(QtCore.QRectF(10.5, 6.5, 9, 6.5), 1.2, 1.2)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    lift = 0 if locked else 1.5   # open: the shackle up, one leg out
    shackle = QtGui.QPainterPath(QtCore.QPointF(12.5, 6.5))
    shackle.lineTo(12.5, 4.5 - lift)
    shackle.arcTo(QtCore.QRectF(12.5, 1.5 - lift, 5, 6), 180, -180)
    shackle.lineTo(17.5, 6.5 if locked else 4.5 - lift)
    painter.drawPath(shackle)
    painter.end()
    return QtGui.QIcon(pixmap)


class _Values(QtCore.QAbstractTableModel):
    """The picked series' values - read only as they're shown, so a million points cost nothing."""

    def __init__(self):
        super().__init__()
        self.x = self.y = None
        self.names = ('x', 'y')

    def show(self, s):
        self.beginResetModel()
        self.x = self.y = None
        if s is not None:
            self.x, self.y = s.data()
            horizontal = s.kind == 'bars' and getattr(s.artist, 'orientation', '') == 'horizontal'
            self.names = ('value', 'at') if horizontal else ('x', 'height') if s.kind == 'bars' else ('x', 'y')
        self.endResetModel()

    def rowCount(self, parent=QtCore.QModelIndex()):
        return 0 if parent.isValid() or self.x is None else len(self.x)

    def columnCount(self, parent=QtCore.QModelIndex()):
        return 0 if parent.isValid() else 3

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        row, column = index.row(), index.column()
        if role == Qt.ItemDataRole.DisplayRole:
            return str(row) if column == 0 else _series.text((self.x, self.y)[column - 1][row])
        if role == Qt.ItemDataRole.TextAlignmentRole:
            return Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        if role == Qt.ItemDataRole.ForegroundRole and column == 0:
            return QtGui.QColor(_style.TEXT_3)
        return None

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Horizontal:
            return (('#',) + tuple(self.names))[section]
        return None

    def same(self, x, y):
        """Whether these are the values it already shows."""
        if self.x is None or len(self.x) != len(x) or len(self.y) != len(y):
            return False
        return all(a is b or _equal(a, b) for a, b in ((self.x, x), (self.y, y)))


def _equal(a, b):
    try:
        return np.array_equal(a, b, equal_nan=True)
    except TypeError:   # dates, text: no nan to speak of
        return np.array_equal(a, b)


def _run_rows(s):
    found = _sliders.run_of(s)
    if found is None:
        return []
    parameters, run = found
    values = parameters.values if run == _sliders.LIVE else next(
        (e.get('params') for e in _view.entries(run) if e.get('params')), None)
    return [('parameters', parameters.describe(values))] if values else []


def _stats(s, extra=()):
    x, y = s.data()
    xf, yf = s.floats()
    rows = [('points', f"{len(xf):,}")]
    nans = int(np.isnan(yf).sum())
    if nans:
        rows.append(('missing (nan)', f"{nans:,}"))
    finite = np.flatnonzero(np.isfinite(xf) & np.isfinite(yf))
    if len(finite):
        first, last = finite[0], finite[-1]
        rows += [('start', f"({_series.text(x[first])}, {_series.text(y[first])})"),
                 ('end', f"({_series.text(x[last])}, {_series.text(y[last])})")]
        if s.kind != 'bars':
            rows.append(('x step', _step(xf[finite], _is_date(x))))
        low, high = finite[np.argmin(yf[finite])], finite[np.argmax(yf[finite])]
        name = 'height' if s.kind == 'bars' else 'y'
        rows += [(f"{name} minimum", f"{_series.text(y[low])}  at {_series.text(x[low])}"),
                 (f"{name} maximum", f"{_series.text(y[high])}  at {_series.text(x[high])}"),
                 (f"{name} mean", _series.text(float(np.mean(yf[finite]))))]
        if s.kind == 'bars':
            rows.append(('sum', _series.text(float(np.sum(yf[finite])))))
    rows += list(extra)
    cells = ''.join(f"<tr><td style='color:{_style.TEXT_3}; padding-right:14px'>{name}</td>"
                    f"<td style='color:{_style.TEXT}'>{value}</td></tr>" for name, value in rows)
    return f"<b style='color:{_style.TEXT}'>{s.label}</b><table style='margin-top:6px'>{cells}</table>"


def _step(xf, dates):
    if len(xf) < 2:
        return '-'
    steps = np.diff(xf)
    if not (np.all(steps > 0) or np.all(steps < 0)):
        return 'not monotonic'
    unit = ' days' if dates else ''
    scale = max(abs(steps).max(), 1e-300)
    if np.allclose(steps, steps[0], rtol=1e-6, atol=1e-9 * scale):
        return f"{_series.text(float(np.mean(steps)))}{unit}, uniform"
    return f"{_series.text(float(steps.min()))} to {_series.text(float(steps.max()))}{unit}, non-uniform"


def _is_date(x):
    return x.dtype.kind == 'M' or (x.dtype == object and len(x) and hasattr(x[0], 'year'))


def _clip(text):
    QtWidgets.QApplication.clipboard().setText(text)
