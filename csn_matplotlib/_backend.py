"""The window: one for every figure, a tab each (plt.figure('Phase') makes a tab named so), dark,
opened maximised - not full screen; un-maximised it's the first figure's own size, in the middle of
the screen. A tab's name is changed by double-clicking it, or F2 with the pointer over it (elsewhere F2
renames the series picked or the plot under the pointer - with neither, the tab in front); right-clicking it closes it (as does Ctrl+W),
Ctrl+Shift+T opens the last one closed again, Ctrl+T makes a new tab with an empty plot, Ctrl+Tab and Ctrl+Shift+Tab
go through the tabs, Ctrl+Q closes the window. Each tab is matplotlib's own Qt window (QtAgg) put
inside it, so its toolbar can still be dragged by its grip to any side of the plot (standing up at
the left or right, the coordinates make way for the side panel's and the copy buttons at its foot)
or out to float on its own, as small as its buttons. Beside the plot, the side panel (Ctrl+B or the
toolbar's button): the Parameters tab (the sliders the tab's plots depend on, _sliders), the data
(_data_panel), the Plot tab (one plot and its series, _plot_panel) and the layout (_layout); it folds
open and shut and is as wide as its edge is dragged. While it folds or is dragged the figure isn't
re-rendered at every step: a still of it stands in (freeze), and it's drawn at its new size once it
stops (thaw). The toolbar's own: undo and redo, arranging the plots, the view settings file, the
plots animated as a tab comes into view (_animate), copying the figure; Home fits every plot to what
it shows. On the canvas: the navigation (_navigation, the arrow keys and + and - too), the point
inspector (_inspector), editing labels (_labels), the layout tool (_layout), and right-click menus:
a plot's (its series, its title, moving it), an empty space's (a plot to put there, from any tab),
the figure's. A plot picked in a panel is outlined for a moment; hovered in a panel, while hovered.
A figure slow to draw (its last draw, or the estimate of this one, over BACKGROUND_S) is drawn in a
thread of its own, a part at a time so the window goes on meanwhile (_detail.chunked) - the last
image of it shown, after VEIL_MS a veil saying how many points are being drawn and how far it's got,
with Stop (or Esc: a reduced set is drawn instead) - and nothing changes the figure while it is
(_series.quiet waits for it). A figure that would take too long to draw asks first whether to draw a
reduced set - as it opens too; a plot drawn reduced says so in a red label on it (_detail). The view
settings aren't written while anything computes or draws: only once the window's come through it. Limits that can't be drawn (an overflow to inf) are put back to the data and it's
drawn again. While a run of the sliders computes in its thread, nothing's drawn - the figure may be
halfway changed - and after VEIL_MS a veil over the plot turns a circle, with Stop (or Esc).
matplotlib finds it by name - matplotlib.use('module://csn_matplotlib._backend') - as FigureCanvas."""
from PySide6 import QtCore, QtGui, QtWidgets   # first, so matplotlib's Qt takes this binding

import io
import math
import os
import threading
import time
import traceback

import matplotlib as mpl
from matplotlib._pylab_helpers import Gcf
from matplotlib.backend_bases import DrawEvent
from matplotlib.backends.backend_agg import RendererAgg
from matplotlib.backends.backend_qt import FigureManagerQT, NavigationToolbar2QT
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg

from . import _animate, _detail, _fits, _layout, _plot_panel, _series, _sliders, _style, _upto, _view
from ._data_panel import DataPanel
from ._history import history
from ._inspector import Inspector
from ._labels import LabelEditor, _Field
from ._layout import LayoutPane, LayoutTool
from ._navigation import Navigation
from ._settings import figure_key, store
from ._widgets import BusyVeil, Splitter, Toast

Qt = QtCore.Qt
_opened = False   # the settings put back: once, as the first window opens


def _first_open():
    """Every plot named by where the script put it (before any's moved), then the layout kept last
    time - plots moved, added, tabs made - then the rest of the view settings, and the tabs' names."""
    global _opened
    if _opened:
        return
    _opened = True
    for figure in _series.figures():
        for ax in figure.axes:
            _series.ax_id(ax)
    _layout.restore()
    _view.restore()
    names = store.data.get('tab_names', {})
    for figure in _series.figures():
        name = names.get(figure_key(figure)) if isinstance(names, dict) else None
        if isinstance(name, str) and name:
            figure.canvas.manager.set_window_title(name)


def _reset_tab_names():
    for figure in _series.figures():
        manager = figure.canvas.manager
        if manager is not None and manager.get_window_title() != figure_key(figure):
            manager.set_window_title(figure_key(figure))


_view.on_reset.append(_reset_tab_names)
store.waits.append(lambda: any(getattr(f.canvas, 'busy', False) for f in _series.figures()))


class Host(QtWidgets.QMainWindow):
    """The one window - a tab for each figure; the tab bar shows once there are two."""

    RESTORED_SHARE = 0.8   # un-maximised, the window is at most this much of the screen, each way
    FADE_IN_DELAY_MS = 90  # opened: shown after this - painted by then - fading in over FADE_IN_MS
    FADE_IN_MS = 140
    _one = None

    @classmethod
    def get(cls):
        if cls._one is None:
            cls._one = cls()
        return cls._one

    def __init__(self):
        super().__init__()
        self.tabs = QtWidgets.QTabWidget()
        self.tabs.setDocumentMode(True)
        self.tabs.setTabBarAutoHide(True)
        self.tabs.setMovable(True)
        bar = self.tabs.tabBar()
        bar.setDrawBase(False)
        self.tabs.currentChanged.connect(self._switched)
        self._front = None          # the page in front: a tab only moved along the bar isn't a new one
        self._held_reveal = None    # a tab picked by pressing its header: it comes in once let go, unmoved
        bar.tabMoved.connect(self._tab_moved)
        bar.installEventFilter(self)
        bar.tabBarDoubleClicked.connect(self._rename)
        for owner in (bar, self.tabs):   # a tab, or the empty room beside them
            owner.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            owner.customContextMenuRequested.connect(lambda at, o=owner: self._tab_menu(o, at))
        self.setCentralWidget(self.tabs)
        self._placed = self._closing = False
        self.closed = []   # the managers of the tabs closed, the last one last
        self._shortcut(['Ctrl+Q'], self.close)
        self._shortcut(['Ctrl+W'], lambda: self.close_tab(self.tabs.currentWidget()))
        self._shortcut(['Ctrl+T'], self.new_tab)
        self._shortcut(['Ctrl+Shift+T'], self.reopen)
        self._shortcut(['Ctrl+Tab', 'Ctrl+PgDown'], lambda: self._step(1))
        self._shortcut(['Ctrl+Shift+Tab', 'Ctrl+Shift+Backtab', 'Ctrl+PgUp'], lambda: self._step(-1))
        self._shortcut(['F11'], self.plot_only)
        self._plot_only, self._was_maximised = False, True
        _style.dark_title_bar(self)   # before it's shown: no light title bar first
        from . import _watchdog
        _watchdog.start()   # asks, from outside, if the window ever stops answering

    def plot_only(self):
        """F11: nothing but the plots, on the whole screen - no tab bar, toolbar, side panel or terminal.
        Again: all as it was."""
        self._plot_only = on = not self._plot_only
        bar = self.tabs.tabBar()
        if on:
            self._was_maximised = self.isMaximized() or self.isFullScreen()
            self._was_full = self.isFullScreen()
            bar.setAutoHide(False)
            bar.hide()
            if not self._was_full:
                self.showFullScreen()
        else:
            bar.show()
            bar.setAutoHide(True)   # one tab: hidden again
            if not getattr(self, '_was_full', False):   # out of full screen first, then maximised: Windows
                self.showNormal()                       # otherwise leaves it at its restored size
                if self._was_maximised:
                    QtCore.QTimer.singleShot(0, self.showMaximized)
        for manager in Gcf.get_all_fig_managers():
            if hasattr(manager, 'plot_only'):
                manager.plot_only(on)

    def _shortcut(self, keys, slot):
        shortcut = QtGui.QShortcut(self)
        shortcut.setKeys([QtGui.QKeySequence(key) for key in keys])
        shortcut.setContext(Qt.ShortcutContext.WindowShortcut)   # wherever the focus is: a plot, a panel
        shortcut.activated.connect(slot)

    def _manager_of(self, page):
        return next((m for m in Gcf.get_all_fig_managers() if m.window is page), None) if page is not None else None

    def add(self, manager):
        page = manager.window
        index = self.tabs.indexOf(page)
        behind, manager.behind = getattr(manager, 'behind', False), False
        if manager in self.closed:
            self.closed.remove(manager)
        manager.closed = False
        if index < 0:
            page.setWindowFlags(Qt.WindowType.Widget)   # matplotlib's window, as a tab's page
            index = self.tabs.addTab(page, manager.get_window_title())
            if self.tabs.count() == 1:
                self.setWindowIcon(page.windowIcon())
            elif not self.isVisible() or behind:
                return   # plt.show() showing them all, a tab kept from last time: the one in front stays
        self.tabs.setCurrentIndex(index)

    def remove(self, manager):
        index = self.tabs.indexOf(manager.window)
        if index >= 0:
            self.tabs.removeTab(index)
            manager.window.setParent(None)   # out of the window, as matplotlib's own closed one would be
        if manager in self.closed:
            self.closed.remove(manager)
        if not self.tabs.count() and not self._closing and self.isVisible():
            self.close()

    def open(self, manager):
        if not self._placed:   # the size it goes back to, un-maximised
            self._placed = True
            screen = (self.screen() or QtGui.QGuiApplication.primaryScreen()).availableGeometry()
            size = manager.restored_size
            self.resize(min(size.width(), int(screen.width() * self.RESTORED_SHARE)),
                        min(size.height(), int(screen.height() * self.RESTORED_SHARE)))
            frame = self.frameGeometry()
            frame.moveCenter(screen.center())
            self.move(frame.topLeft())
        if not self.isVisible():
            self.setWindowOpacity(0.0)   # shown once it's drawn dark - no white frame first
            self.showMaximized()
            QtCore.QTimer.singleShot(self.FADE_IN_DELAY_MS, self._fade_in)
        if mpl.rcParams['figure.raise_window']:
            self.activateWindow()
            self.raise_()

    def retitle(self, manager, title):
        index = self.tabs.indexOf(manager.window)
        if index >= 0:
            self.tabs.setTabText(index, title)
            if index == self.tabs.currentIndex():
                self.setWindowTitle(title)

    # ---- tabs: closed, opened again, made, gone through, renamed

    def close_tab(self, page):
        """The tab out of the window, not gone: Ctrl+Shift+T opens it again. The last one closes the window."""
        manager = self._manager_of(page)
        if manager is None:
            return
        if self.tabs.count() <= 1:
            self.close()
            return
        _series.quiet()
        self.tabs.removeTab(self.tabs.indexOf(page))
        manager.closed = True
        self.closed.append(manager)
        current = self._manager_of(self.tabs.currentWidget())
        if current is not None:
            current.canvas.say(f"Tab “{manager.get_window_title()}” closed. Ctrl+Shift+T reopens it")

    def reopen(self):
        alive = Gcf.get_all_fig_managers()
        while self.closed:
            manager = self.closed.pop()
            if manager in alive:
                self.add(manager)
                return

    def new_tab(self):
        manager = self._manager_of(self.tabs.currentWidget())
        if manager is not None:
            _layout.new_plot(manager.canvas.figure, new_tab=True)

    def _fade_in(self):
        fade = QtCore.QPropertyAnimation(self, b'windowOpacity', self)
        fade.setDuration(self.FADE_IN_MS)
        fade.setStartValue(0.0)
        fade.setEndValue(1.0)
        fade.start(QtCore.QAbstractAnimation.DeletionPolicy.DeleteWhenStopped)

    def _tab_menu(self, owner, at):
        """Right-clicking a tab: rename, close, a new one; the room beside them: a new tab."""
        bar = self.tabs.tabBar()
        spot = bar.mapFrom(owner, at) if owner is not bar else at
        if owner is not bar and spot.y() > bar.height():   # under the tabs: the plot's own menu, not this
            return
        index = bar.tabAt(spot)
        menu = QtWidgets.QMenu(self)
        if index >= 0:
            page = self.tabs.widget(index)
            menu.addAction('Rename…', lambda: self._rename(index))
            menu.addAction('Close tab', lambda: self.close_tab(page)).setShortcut(QtGui.QKeySequence('Ctrl+W'))
            menu.addSeparator()
        menu.addAction('New tab', self.new_tab).setShortcut(QtGui.QKeySequence('Ctrl+T'))
        reopen = menu.addAction('Reopen last closed tab', self.reopen)
        reopen.setShortcut(QtGui.QKeySequence('Ctrl+Shift+T'))
        reopen.setEnabled(bool(self.closed))
        menu.exec(owner.mapToGlobal(at))

    def _step(self, way):
        count = self.tabs.count()
        if count > 1:
            self.tabs.setCurrentIndex((self.tabs.currentIndex() + way) % count)

    def _rename(self, index):
        manager = self._manager_of(self.tabs.widget(index))
        if manager is None:
            return
        bar = self.tabs.tabBar()
        if not bar.isVisible():   # one tab: no bar to type on
            name, ok = QtWidgets.QInputDialog.getText(self, 'Rename tab', 'Name:', text=manager.get_window_title())
            if ok and name.strip():
                manager.rename(name.strip())
            return
        rect = bar.tabRect(index)
        field = _Field(bar, manager.get_window_title(), manager.rename, lambda: field.deleteLater())
        field.setGeometry(rect.adjusted(2, 2, -2, -2).united(QtCore.QRect(rect.left(), rect.top(), 160, rect.height())))
        field.show()
        field.setFocus()
        field.selectAll()

    def _switched(self, index):
        page = self.tabs.widget(index)
        if page is self._front:   # the same tab, dragged to another place on the bar
            return
        self._front = page
        manager = self._manager_of(page)
        if manager is not None:
            self.setWindowTitle(manager.get_window_title())
            pressed = bool(QtWidgets.QApplication.mouseButtons() & Qt.MouseButton.LeftButton) \
                and self.tabs.tabBar().underMouse()
            if self._plot_only and hasattr(manager, 'plot_only'):   # F11's on: this one plots only too
                manager.plot_only(True)
            manager.came_in_front(hold=pressed)
            self._held_reveal = manager if pressed else None   # maybe only picked up to move it

    def _tab_moved(self, *_):
        manager, self._held_reveal = self._held_reveal, None   # dragged along the bar: shown as it is
        if manager is not None:
            manager.canvas.drop_reveal()

    def rename_tab(self):
        """F2: the tab under the pointer renamed - else the one in front."""
        bar = self.tabs.tabBar()
        at = bar.mapFromGlobal(QtGui.QCursor.pos())
        index = bar.tabAt(at) if bar.isVisible() and bar.rect().contains(at) else -1
        self._rename(index if index >= 0 else self.tabs.currentIndex())

    def over_tabs(self):
        bar = self.tabs.tabBar()
        return bar.isVisible() and bar.rect().contains(bar.mapFromGlobal(QtGui.QCursor.pos()))

    def eventFilter(self, watched, event):
        """The tab bar: a tab pressed (and so picked) comes in once it's let go - not if it was dragged.
        F2 there renames it."""
        if event.type() == QtCore.QEvent.Type.KeyPress and event.key() == Qt.Key.Key_F2:
            self.rename_tab()
            return True
        if event.type() == QtCore.QEvent.Type.MouseButtonRelease and self._held_reveal is not None:
            manager, self._held_reveal = self._held_reveal, None
            manager.canvas.let_reveal()
        return False

    def closeEvent(self, event):
        self._closing = True
        try:
            _series.quiet()
            store.flush()   # what's waiting to be written - unless something's still to be come through
            for manager in list(Gcf.get_all_fig_managers()):
                if self.tabs.indexOf(manager.window) >= 0 or getattr(manager, 'closed', False):
                    Gcf.destroy(manager)
        finally:
            self._closing = False
        super().closeEvent(event)


class CSNToolbar(NavigationToolbar2QT):
    toolitems = [(name, 'Fit every plot to its data (Space: only the plot in focus)', image, call)
                 if name == 'Home' else (name, tip, image, call)
                 for name, tip, image, call in NavigationToolbar2QT.toolitems
                 if name not in ('Subplots', 'Customize')]   # the spacing: the layout's; the options: the Plot tab

    area = Qt.ToolBarArea.TopToolBarArea   # where every tab's toolbar is: one moved, all follow

    def __init__(self, canvas, parent=None, coordinates=True):
        super().__init__(canvas, parent, coordinates)
        self.setAllowedAreas(Qt.ToolBarArea.AllToolBarAreas)   # matplotlib's: only the top and the bottom
        label = getattr(self, 'locLabel', None)
        self._anchor = None if label is None else next(
            (action for action in self.actions() if self.widgetForAction(action) is label), None)
        if label is not None:   # taking the room left - and giving it up before the buttons do
            label.setMinimumWidth(1)
        spacer = QtWidgets.QWidget(self)   # standing up: the room between the buttons and the last two
        spacer.setSizePolicy(QtWidgets.QSizePolicy.Policy.Preferred, QtWidgets.QSizePolicy.Policy.Expanding)
        self._spacer = self.addWidget(spacer)
        self._spacer.setVisible(False)
        self.topLevelChanged.connect(lambda _: self._arrange())
        self.orientationChanged.connect(lambda _: self._arrange())

    def moveEvent(self, event):
        super().moveEvent(event)
        QtCore.QTimer.singleShot(0, self._docked)

    def _docked(self):
        """Put at another edge of its tab: every tab's toolbar there too, and the tabs opened later."""
        window = self.parentWidget()
        if self.isFloating() or not isinstance(window, QtWidgets.QMainWindow):
            return
        area = window.toolBarArea(self)
        if area == CSNToolbar.area or area == Qt.ToolBarArea.NoToolBarArea:
            return
        CSNToolbar.area = area
        for manager in Gcf.get_all_fig_managers():
            toolbar = getattr(manager, 'toolbar', None)
            if isinstance(toolbar, CSNToolbar) and toolbar is not self and not toolbar.isFloating():
                manager.window.addToolBar(area, toolbar)

    def insert_action(self, action):
        """Ours after matplotlib's buttons - before the coordinates."""
        self.insertAction(self._anchor, action)

    def insert_widget(self, widget):
        self.insertWidget(self._anchor, widget)

    def insert_separator(self):
        self.insertSeparator(self._anchor)

    def _arrange(self):
        """Lying: the coordinates take the room, the last buttons at the right. Standing up: those at the
        foot. Floating: as small as the buttons."""
        floating = self.isFloating()
        lying = self.orientation() == Qt.Orientation.Horizontal
        if self._anchor is not None:
            self._anchor.setVisible(lying and not floating)
        self._spacer.setVisible(not lying and not floating)
        if floating:
            QtCore.QTimer.singleShot(0, self.adjustSize)

    def say(self, text):
        self.canvas.say(text)

    def home(self, *args):
        """Every plot fitted to what it shows now - hidden series left out."""
        self.canvas.navigation.reset([ax for ax in self.canvas.figure.axes if ax.get_visible()])
        self.say('Every plot fitted to its data')


class CSNFigureManager(FigureManagerQT):
    _toolbar2_class = CSNToolbar
    PANEL_MS = 180          # the panel's folding open or shut
    THAW_MS = 150           # the panel's edge let go of this long: the figure's drawn at its new size
    SIDE_TOP = 6            # the panel's tabs, this far under the toolbar: a picked one doesn't touch its edge
    COPY_DPI = 200
    BUILD_WAIT_MS = 100     # the side panels of the tabs not seen yet: made one at a time, this far apart
    _unbuilt = []           # the managers whose side panels are still to be made, in the order they opened

    def __init__(self, canvas, num):
        interactive = mpl.is_interactive()
        with _style._Windows.aside():
            self._made(canvas, num)
        if interactive:
            self.show()
            canvas.draw_idle()

    def _made(self, canvas, num):
        interactive = mpl.is_interactive()
        mpl.interactive(False)   # matplotlib's own would show the figure in a window of its own
        try:
            super().__init__(canvas, num)
        finally:
            mpl.interactive(interactive)
        window = self.window
        if self.toolbar is not None and CSNToolbar.area != Qt.ToolBarArea.TopToolBarArea:
            window.addToolBar(CSNToolbar.area, self.toolbar)   # where the other tabs have it
        self.restored_size = window.size()   # the figure's own size, and the toolbar
        self.behind = False                   # shown behind the tab in front (a tab kept from last time)
        self.closed = False                   # its tab closed - to be opened again
        self._shown, self._when_shown = False, []
        self._side = None                     # its Data, Plot and Layout tabs, once made (_side_tabs)
        self.holder = _sliders.Holder(canvas.figure)
        self.side_tabs = QtWidgets.QTabWidget()
        self.side_tabs.setDocumentMode(True)
        self.side_tabs.setTabBarAutoHide(True)
        self.side_tabs.tabBar().setDrawBase(False)
        self.side_tabs.setMinimumWidth(1)
        self.side = QtWidgets.QWidget()
        self.side.setMinimumWidth(1)        # so it can fold smoothly (not snap at its contents' least width)
        side = QtWidgets.QVBoxLayout(self.side)
        side.setContentsMargins(0, self.SIDE_TOP, 0, 0)
        side.addWidget(self.side_tabs)
        window.takeCentralWidget()   # the canvas, out of the window but not deleted
        self.left = Splitter(Qt.Orientation.Vertical)   # the canvas over the terminal, the tab in front's
        self.left.addWidget(canvas)
        self.left.setCollapsible(0, False)
        self.left.setStretchFactor(0, 1)
        self.left.splitterMoved.connect(self._terminal_dragged)
        self._terminal_folding = QtCore.QVariantAnimation(window)
        self._terminal_folding.setDuration(self.PANEL_MS)
        self._terminal_folding.setEasingCurve(QtCore.QEasingCurve.Type.OutCubic)
        self._terminal_folding.valueChanged.connect(self._terminal_frame)
        self._terminal_folding.finished.connect(self._terminal_done)
        self._plot_only = None   # F11: what was shown, to show again
        self.splitter = Splitter(Qt.Orientation.Horizontal)
        self.splitter.addWidget(self.left)
        self.splitter.addWidget(self.side)
        self.splitter.setCollapsible(0, False)
        self.splitter.setStretchFactor(0, 1)
        self.splitter.setStretchFactor(1, 0)
        self.splitter.splitterMoved.connect(self._panel_dragged)
        window.setCentralWidget(self.splitter)
        self.side.hide()
        self._panel_width = None   # as wide as its tabs need, until it's dragged to a width
        self._open_on_show = False
        self._folding = QtCore.QVariantAnimation(window)
        self._folding.setDuration(self.PANEL_MS)
        self._folding.setEasingCurve(QtCore.QEasingCurve.Type.OutCubic)
        self._folding.valueChanged.connect(self._fold_frame)
        self._folding.finished.connect(self._fold_done)
        self._thawer = QtCore.QTimer(window)
        self._thawer.setSingleShot(True)
        self._thawer.timeout.connect(canvas.thaw)
        self._add_actions()
        history.listeners.append(self._history_changed)
        canvas.setFocus()

    def show(self):
        self.window._destroying = False
        host = Host.get()
        with _style._Windows.aside():
            host.add(self)
        self._side_later()
        first = not self._shown
        if first:
            self._shown = True
            _first_open()   # the view settings saved last time, before it's first seen
            for callback in self._when_shown:
                QtCore.QTimer.singleShot(0, callback)
            self._when_shown = []
        visible = host.isVisible()
        if not visible and self.in_front():   # the window opening: its plots rise in once they're drawn
            self.canvas.reveal()
        host.open(self)
        if self._open_on_show and hasattr(self, 'panel_action'):
            self._open_on_show = False
            QtCore.QTimer.singleShot(150, lambda: self.panel_action.setChecked(True))   # once it's maximised

    def when_shown(self, callback):
        """callback() once the window's open and the settings are back - straight away, if it is."""
        if self._shown:
            QtCore.QTimer.singleShot(0, callback)
        else:
            self._when_shown.append(callback)

    def in_front(self):
        return Host._one is not None and Host._one.tabs.currentWidget() is self.window

    # ---- the side panel's own tabs, made once they're needed, or in the time between: a tab comes in
    # without waiting for them

    @property
    def panel(self):
        return self._side_tabs()[0]

    @property
    def plot_panel(self):
        return self._side_tabs()[1]

    @property
    def layout_pane(self):
        return self._side_tabs()[2]

    def _side_tabs(self):
        """The Data, Plot and Layout tabs - made now if they aren't yet."""
        if self._side is None:
            canvas = self.canvas
            with _style._Windows.aside():
                data = DataPanel(canvas)
                data.heading.hide()   # the tab bar names it
                canvas.inspector.panel = data
                self._side = (data, _plot_panel.PlotPanel(canvas), LayoutPane(canvas))
                for tab, name in zip(self._side, ('Data', 'Plot', 'Layout')):
                    self.side_tabs.addTab(tab, name)   # after the Parameters, if they're there
                self.side.installEventFilter(self._side[1])   # what it edits lit only while the pointer's over it
                if hasattr(self, 'layout_action'):
                    self._side[2].dragging.toggled.connect(self.layout_action.setChecked)
            if canvas._image_drawn:   # made after the figure's drawn: filled now, not at its next draw
                for tab in self._side:
                    tab._refresher.start(0)
            if self in self._unbuilt:
                self._unbuilt.remove(self)
        return self._side

    def _side_later(self):
        if self._side is None and self not in self._unbuilt:
            self._unbuilt.append(self)
            if len(self._unbuilt) == 1:
                QtCore.QTimer.singleShot(self.BUILD_WAIT_MS, CSNFigureManager._make_next_side)

    @classmethod
    def _make_next_side(cls):
        """One tab's side panels, the one in front's first - once its plots are drawn."""
        waiting = [m for m in cls._unbuilt if m.canvas.figure is not None and not m.window._destroying]
        cls._unbuilt[:] = waiting
        if not waiting:
            return
        manager = next((m for m in waiting if m.in_front()), waiting[0])
        if manager.in_front() and not manager.canvas._image_drawn:
            QtCore.QTimer.singleShot(cls.BUILD_WAIT_MS, cls._make_next_side)
            return
        manager._side_tabs()
        if cls._unbuilt:
            QtCore.QTimer.singleShot(cls.BUILD_WAIT_MS, cls._make_next_side)

    def came_in_front(self, reveal=True, hold=False):
        """Its tab picked: it's the current figure, has the sliders its plots need, and comes in (reveal -
        hold: once let go)."""
        Gcf.set_active(self)   # plt.gcf() is the figure in front
        self.place_parameters()
        self.take_terminal()
        if hasattr(self, 'panel_action') and self._folding.state() != QtCore.QAbstractAnimation.State.Running:
            self.panel_action.blockSignals(True)   # its button as its panel is: open or shut
            self.panel_action.setChecked(not self.side.isHidden())
            self.panel_action.blockSignals(False)
        self.update_arrange_action()
        self.animate_action.blockSignals(True)
        self.animate_action.setChecked(_animate.enabled())
        self.animate_action.blockSignals(False)
        canvas = self.canvas
        canvas.setFocus()
        if canvas.figure.stale:   # changed while it was behind (a copy of a series, a moved plot)
            canvas.draw_idle()
        if reveal and Host._one is not None and Host._one.isVisible():
            canvas.reveal(hold)

    def destroy(self, *args):
        if QtWidgets.QApplication.instance() is None or self.window._destroying:
            return
        for listener in (self._sync, self._history_changed):
            if listener in history.listeners:
                history.listeners.remove(listener)
        self.canvas.finish_drawing()
        super().destroy(*args)
        if Host._one is not None:
            Host._one.remove(self)

    def set_window_title(self, title):
        super().set_window_title(title)
        if Host._one is not None:
            Host._one.retitle(self, title)

    def rename(self, name, record=True):
        """The tab's name (its figure keeps its own: the settings file knows it by that)."""
        name, old = name.strip(), self.get_window_title()
        if not name or name == old:
            return
        self.set_window_title(name)
        names = store.data.setdefault('tab_names', {})
        key = figure_key(self.canvas.figure)
        if name == key:
            names.pop(key, None)
        else:
            names[key] = name
        store.changed()
        if record:
            history.push('Rename tab', lambda: self.rename(old, False), lambda: self.rename(name, False))

    def full_screen_toggle(self):
        host = Host.get()
        if host.isFullScreen():
            host.showMaximized()
        else:
            host.showFullScreen()

    def resize(self, width, height):
        """The figure's in a tab, as big as the window: this is only the size it opens at, un-maximised."""
        ratio = self.canvas.device_pixel_ratio or 1.0
        bar = self.toolbar.sizeHint().height() if self.toolbar is not None else 0
        self.restored_size = QtCore.QSize(int(width / ratio), int(height / ratio) + bar)

    # ---- the side panel's tabs

    def add_parameters(self, parameters):
        """A set of sliders made for this figure: its Parameters tab, in front, opened with the window."""
        self.place_parameters()
        if self.side_tabs.indexOf(self.holder) >= 0:
            self.side_tabs.setCurrentWidget(self.holder)
        if self.window.isVisible() and hasattr(self, 'panel_action'):
            self.panel_action.setChecked(True)
        else:
            self._open_on_show = True

    def place_parameters(self):
        """The Parameters tab: the sliders this tab's plots depend on - there only if there are some."""
        count = self.holder.place()
        index = self.side_tabs.indexOf(self.holder)
        if count and index < 0:
            self.side_tabs.insertTab(0, self.holder, 'Parameters')
        elif not count and index >= 0:
            self.side_tabs.removeTab(index)

    def parameters_changed(self):
        if self.in_front():
            self.place_parameters()

    def _history_changed(self):
        if self.in_front():   # a plot moved here or away, a run saved or deleted
            QtCore.QTimer.singleShot(0, self.place_parameters)
        QtCore.QTimer.singleShot(0, self.update_arrange_action)

    def update_arrange_action(self):
        """The toolbar's Arrange plots, only while there's more than one plot to arrange."""
        action = getattr(self, 'layout_action', None)
        if action is None or self.canvas.figure is None:
            return
        several = sum(1 for ax in _layout.plots(self.canvas.figure) if ax.get_visible()) > 1
        if not several and action.isChecked():
            action.setChecked(False)
        action.setVisible(several)

    def show_side(self, name):
        """The side panel open at that tab ('Data', 'Plot', 'Layout', 'Parameters')."""
        self._side_tabs()
        for index in range(self.side_tabs.count()):
            if self.side_tabs.tabText(index) == name:
                self.side_tabs.setCurrentIndex(index)
        if hasattr(self, 'panel_action') and not self.panel_action.isChecked():
            self.panel_action.setChecked(True)

    def show_plot_panel(self, ax, series=None):
        self.show_side('Plot')
        self.plot_panel.show_plot(ax, series)

    def open_look(self, s):
        """The Plot tab, at the series' appearance."""
        self.show_plot_panel(_view.main_of(s.ax), s)
        section = self.plot_panel.sections['Appearance']
        if not _view.locked(s):
            section.toggle.setChecked(True)
            self.plot_panel.scroll_to('Series in this plot')   # its list and its appearance in view
        else:
            self.canvas.say(f"“{s.label}” is locked. Unlock it in the data panel to change its appearance")

    # ---- the toolbar's own

    def _add_actions(self):
        toolbar = self.toolbar
        if toolbar is None:
            return
        toolbar.insert_separator()
        self.undo_action = QtGui.QAction(_glyph('undo', toolbar), 'Undo', toolbar)
        self.undo_action.setShortcut(QtGui.QKeySequence('Ctrl+Z'))
        self.undo_action.triggered.connect(lambda: self._step(history.undo, 'Undone'))
        self.redo_action = QtGui.QAction(_glyph('redo', toolbar), 'Redo', toolbar)
        self.redo_action.setShortcuts([QtGui.QKeySequence('Ctrl+Y'), QtGui.QKeySequence('Ctrl+Shift+Z')])
        self.redo_action.triggered.connect(lambda: self._step(history.redo, 'Redone'))
        toolbar.insert_action(self.undo_action)
        toolbar.insert_action(self.redo_action)
        toolbar.insert_separator()
        self.layout_action = QtGui.QAction(_glyph('layout', toolbar), 'Arrange plots', toolbar)
        self.layout_action.setCheckable(True)
        self.layout_action.setToolTip('Arrange the plots: drag one onto another to swap them, drag the borders '
                                      'between them, click one for more (Esc stops)')
        self.layout_action.toggled.connect(self._layout_mode)   # and back from the Layout tab, once it's made
        toolbar.insert_action(self.layout_action)
        self.update_arrange_action()
        self.canvas.mpl_connect('draw_event', lambda event: self.update_arrange_action())
        toolbar.insert_widget(self._settings_button(toolbar))
        history.listeners.append(self._sync)
        self._sync()

        toolbar.addSeparator()   # after the coordinates: at the right, or standing up, at the foot
        copy = QtGui.QAction(_glyph('copy', toolbar), 'Copy image', toolbar)
        copy.setToolTip('Copy the figure as an image (Ctrl+Shift+C)')
        copy.setShortcut(QtGui.QKeySequence('Ctrl+Shift+C'))
        copy.triggered.connect(self.copy_image)
        toolbar.addAction(copy)
        self.panel_action = QtGui.QAction(_glyph('panel', toolbar), 'Side panel', toolbar)
        self.panel_action.setToolTip('Side panel (Alt+S, Ctrl+B)')
        self.panel_action.setCheckable(True)
        self.panel_action.setShortcuts([QtGui.QKeySequence('Alt+S'), QtGui.QKeySequence('Ctrl+B')])
        self.panel_action.toggled.connect(self._fold)
        self.terminal_action = QtGui.QAction(_glyph('terminal', toolbar), 'Terminal', toolbar)
        self.terminal_action.setToolTip('Terminal: what the script prints, and a Python prompt (Alt+T, Ctrl+J)')
        self.terminal_action.setCheckable(True)
        self.terminal_action.setShortcuts([QtGui.QKeySequence('Alt+T'), QtGui.QKeySequence('Ctrl+J')])
        self.terminal_action.toggled.connect(self._fold_terminal)
        toolbar.addAction(self.terminal_action)
        toolbar.addAction(self.panel_action)

    def _settings_button(self, toolbar):
        menu = QtWidgets.QMenu(toolbar)
        menu.setToolTipsVisible(True)
        self.remember_action = menu.addAction('Remember view settings')
        self.remember_action.setCheckable(True)
        self.remember_action.setToolTip('Looks, names, labels, grids, the layout, locks, fits and the sliders, '
                                        'kept for next time - never the zoom')
        self.remember_action.triggered.connect(store.set_enabled)
        self.file_action = menu.addAction('')
        self.file_action.setEnabled(False)
        self.choose_action = menu.addAction('Choose settings file…')
        self.choose_action.triggered.connect(self._choose_file)
        menu.addSeparator()
        menu.addAction('Reset view settings…').triggered.connect(self._reset_view)
        menu.addSeparator()
        self.animate_action = menu.addAction('Animate plots')
        self.animate_action.setCheckable(True)
        self.animate_action.setChecked(_animate.enabled())
        self.animate_action.setToolTip('The plots come into view as a tab is opened or switched to, or a '
                                       'different arrangement picked, and series as they are shown or hidden')
        self.animate_action.toggled.connect(self._animate)
        menu.aboutToShow.connect(self._sync_settings)
        button = _menu_button(toolbar, menu, icon=_glyph('settings', toolbar))
        button.setToolTip('Options')
        return button

    def _sync(self):
        """The toolbar showing what can be undone and redone."""
        undo, redo = history.next_undo(), history.next_redo()
        self.undo_action.setEnabled(undo is not None)
        self.undo_action.setToolTip(f"Undo {undo.lower()} (Ctrl+Z)" if undo else 'Nothing to undo')
        self.redo_action.setEnabled(redo is not None)
        self.redo_action.setToolTip(f"Redo {redo.lower()} (Ctrl+Y)" if redo else 'Nothing to redo')

    def _sync_settings(self):
        has_script = store.script is not None
        self.remember_action.setChecked(store.enabled)
        self.remember_action.setEnabled(has_script)
        self.choose_action.setEnabled(has_script)
        if has_script:
            self.file_action.setText(f"In {os.path.basename(store.path)}")
            self.file_action.setToolTip(store.path)
        else:
            self.file_action.setText('Not kept: there is no script file to keep them beside')

    def _step(self, step, done):
        name = step()
        if name:
            self.canvas.say(f"{done}: {name}")

    def _animate(self, on):
        _animate.set_enabled(on)
        self.canvas.say('Plots animated as they come into view' if on else 'Plots shown without animation')
        if on:
            self.canvas.reveal()
        else:
            self.canvas.reveal_effect.stop()

    def _choose_file(self):
        path, _ = QtWidgets.QFileDialog.getSaveFileName(self.window, 'Keep the view settings in', store.path or '',
                                                        'Plot settings (*.json)')
        if path:
            store.move_to(path)
            if not store.enabled:
                store.set_enabled(True)

    def _reset_view(self):
        answer = QtWidgets.QMessageBox.question(
            self.window, 'Reset view settings',
            'Put every figure back as the script made it - looks, names, labels, grids, the layout, locks, '
            'trendlines and error bars, the sliders, and the series and plots added here - and remove it all '
            'from the settings file?')
        if answer == QtWidgets.QMessageBox.StandardButton.Yes:
            _view.reset()
            self._sync()
            self.canvas.say('Every figure as the script made it')

    def _layout_mode(self, on):
        self.layout_pane.dragging.setChecked(on)
        toolbar = self.toolbar
        if on and toolbar is not None and toolbar.mode:   # matplotlib's pan or zoom, off: one drag at a time
            if toolbar.mode == 'pan/zoom':
                toolbar.pan()
            else:
                toolbar.zoom()

    def copy_image(self):
        buffer = io.BytesIO()
        self.canvas.figure.savefig(buffer, format='png', dpi=self.COPY_DPI)
        QtWidgets.QApplication.clipboard().setImage(QtGui.QImage.fromData(buffer.getvalue(), 'PNG'))
        self.canvas.say('Figure copied to the clipboard')

    # ---- the panel, folding

    def _fold(self, opening):
        self._folding.stop()
        self._total = self.splitter.width() - self.splitter.handleWidth()
        if opening or not self.side.isHidden():
            self.canvas.freeze()
        if opening:
            start = self.side.width() if not self.side.isHidden() else 0   # it may be still folding shut
            if self.side.isHidden():
                self.side.show()
                self.splitter.setSizes([self._total, 0])   # after show(): shown, a splitter gives it its own width
            end = min(self._panel_width or self._least_width(), int(self._total * 0.6))
        elif not self.side.isHidden():
            start, end = self.side.width(), 0
        else:
            return
        self._folding.setStartValue(start)
        self._folding.setEndValue(end)
        self._folding.start()

    def _least_width(self):
        """The panel's width for its tabs to fit without scrolling sideways (the Plot tab's the widest)."""
        try:
            room = self.plot_panel.least_width() + 2 * self.side_tabs.style().pixelMetric(
                QtWidgets.QStyle.PixelMetric.PM_DefaultFrameWidth) + 4
        except Exception:
            room = DataPanel.WIDTH
        return max(DataPanel.WIDTH, room)

    def _fold_frame(self, width):
        self.splitter.setSizes([self._total - int(width), int(width)])

    def _fold_done(self):
        if self._folding.endValue() == 0:
            self.side.hide()
        self.canvas.thaw()
        self.canvas.setFocus()

    # ---- the terminal, folding - one for the window, in the tab in front

    def take_terminal(self):
        """The window's terminal into this tab, under its plots - open or shut as in every tab."""
        from . import _terminal   # here: the terminal module is this one's alone
        terminal = _terminal.Terminal.get()
        shown = _terminal.state['shown'] and self._plot_only is None
        if terminal.parent() is not self.left:
            self.left.addWidget(terminal)
            self.left.setCollapsible(1, True)
            self.left.setStretchFactor(1, 0)
        terminal.setVisible(shown)
        if shown:
            total = self.left.height() - self.left.handleWidth()
            height = min(_terminal.state['height'], int(total * 0.6))
            self.left.setSizes([total - height, height])
        if hasattr(self, 'terminal_action'):
            self.terminal_action.blockSignals(True)
            self.terminal_action.setChecked(_terminal.state['shown'])
            self.terminal_action.blockSignals(False)

    def _fold_terminal(self, opening):
        from . import _terminal   # here: the terminal module is this one's alone
        _terminal.state['shown'] = bool(opening)
        terminal = _terminal.Terminal.get()
        if terminal.parent() is not self.left:
            self.take_terminal()
            terminal.setVisible(False)
        self._terminal_folding.stop()
        self._terminal_total = self.left.height() - self.left.handleWidth()
        if opening or not terminal.isHidden():
            self.canvas.freeze()
        if opening:
            start = terminal.height() if not terminal.isHidden() else 0   # it may be still folding shut
            if terminal.isHidden():
                terminal.show()
                self.left.setSizes([self._terminal_total, 0])
            end = min(_terminal.state['height'], int(self._terminal_total * 0.6))
        elif not terminal.isHidden():
            start, end = terminal.height(), 0
        else:
            return
        self._terminal_folding.setStartValue(start)
        self._terminal_folding.setEndValue(end)
        self._terminal_folding.start()
        if opening:   # opened to type in, most likely
            terminal.focus_prompt()

    def _terminal_frame(self, height):
        self.left.setSizes([self._terminal_total - int(height), int(height)])

    def _terminal_done(self):
        from . import _terminal   # here: the terminal module is this one's alone
        if self._terminal_folding.endValue() == 0:
            _terminal.Terminal.get().hide()
        self.canvas.thaw()

    def _terminal_dragged(self, position, index):
        from . import _terminal   # here: the terminal module is this one's alone
        if self._terminal_folding.state() == QtCore.QAbstractAnimation.State.Running:
            return
        self.canvas.freeze()
        self._thawer.start(self.THAW_MS)
        terminal = _terminal.Terminal.get()
        if terminal.height() > 40:
            _terminal.state['height'] = terminal.height()
        elif not terminal.isHidden() and terminal.height() == 0:   # dragged shut
            terminal.hide()
            _terminal.state['shown'] = False
            self.terminal_action.blockSignals(True)
            self.terminal_action.setChecked(False)
            self.terminal_action.blockSignals(False)

    def plot_only(self, on):
        """F11 (Host): nothing but the plots - no toolbar, side panel or terminal - or all as it was."""
        from . import _terminal   # here: the terminal module is this one's alone
        if on and self._plot_only is None:
            terminal = _terminal.Terminal.get()
            self._plot_only = (not self.side.isHidden(), terminal.parent() is self.left and not terminal.isHidden())
            if self.toolbar is not None:
                self.toolbar.hide()
            self._folding.stop()
            self._terminal_folding.stop()
            self.side.hide()
            if self._plot_only[1]:
                terminal.hide()
        elif not on and self._plot_only is not None:
            side, _ = self._plot_only
            self._plot_only = None
            if self.toolbar is not None:
                self.toolbar.show()
            if side:
                self.side.show()
            if self.in_front():
                self.take_terminal()
        self.canvas.setFocus()

    def _panel_dragged(self, position, index):
        if self._folding.state() == QtCore.QAbstractAnimation.State.Running:
            return
        self.canvas.freeze()
        self._thawer.start(self.THAW_MS)
        width = self.side.width()
        if width > 40:
            self._panel_width = width
        elif not self.side.isHidden() and width == 0:   # dragged shut
            self.side.hide()
            self.panel_action.blockSignals(True)
            self.panel_action.setChecked(False)
            self.panel_action.blockSignals(False)


class _Mailbox(QtCore.QObject):
    rendered = QtCore.Signal(object)   # a draw in the background done - from its thread


class CSNCanvas(FigureCanvasQTAgg):
    manager_class = CSNFigureManager
    VEIL_MS = 300                 # a run or a draw going on longer than this: the veil over the plot
    SETTLE_MS = 250               # drawn the quick way while the view moved: properly once it's been still this long
    BACKGROUND_S = 0.2            # a figure whose draw takes (or would take) longer than this: drawn in a thread
    REVEAL_WAIT_S = 2.0           # the plots kept out of sight for their animation this long at most
    OUTLINE_MS = 1400             # a plot picked: outlined, fading over this long

    def __init__(self, figure=None):
        super().__init__(figure)   # makes the QApplication, where there's none yet
        _style.apply_qt(QtWidgets.QApplication.instance())
        self.setAttribute(Qt.WidgetAttribute.WA_AcceptTouchEvents)
        self._quiet = False          # a draw_event held back: the image drawn isn't the one shown yet
        self._render = None          # the draw going on in the background
        self._draw_again = self._resize_waiting = self._drawing_idle = self._rough = False
        self._reveal_wanted = None   # (the image before, its plots - None: all, grow[, how]) for once it's drawn
        self._reveal_held, self._reveal_since = False, 0.0   # held till the tab's let go; asked for when
        self._shown_image = None     # what's shown while it's drawn
        self.last_draw_s = 0.0
        self.draw_rate = _detail.RATE   # seconds a point of a line takes here: timed from the large draws
        self._guard_draw_event()
        self._mathtext_one_at_a_time()
        self._mailbox = _Mailbox()
        self._mailbox.rendered.connect(self._rendered)
        self.picked = _plot_panel.Picked()
        self._picked_ax = None
        self.picked.changed.connect(self._picked_changed)
        self.navigation = Navigation(self, Qt, QtCore.QTimer)
        self.inspector = Inspector(self)
        self.layout_tool = LayoutTool(self)
        self.labels = LabelEditor(self)
        self.reveal_effect = _animate.Reveal(self)
        self._run = None             # (job, its Parameters) while a run of the sliders computes
        self._draw_waiting = False   # asked to draw meanwhile: drawn once it's done
        self.busy_veil = BusyVeil(self)
        self.busy_veil.stop_button.clicked.connect(self.stop_run)
        self.big_veil = _detail.BigVeil(self)
        self.toast = Toast(self)
        self._badge = None           # the red label while plots here are drawn reduced - one for the tab
        self._badge_press, self._badge_drag = None, False   # (where it was pressed, where it was), being dragged
        self._image_drawn = False    # a renderer made only to measure (not drawn yet: the big veil asking) is blank
        # matplotlib's canvas says it paints every pixel itself; at a scale like 125 % its edge can fall
        # inside a pixel that's then left as it was (a white line beside the panel, or at the bottom):
        # the window's own background under it instead
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, False)
        self._outlined, self._held, self._outline_rects = [], {}, {}
        self._outline_level, self._held_fill = 0.0, 0.0
        self._fill_fade = QtCore.QVariantAnimation(self)   # a plot held by the Plot tab: its fill goes, its line stays
        self._fill_fade.setStartValue(1.0)
        self._fill_fade.setEndValue(0.0)
        self._fill_fade.setDuration(self.OUTLINE_MS)
        self._fill_fade.setEasingCurve(QtCore.QEasingCurve.Type.InQuad)
        self._fill_fade.valueChanged.connect(self._fill_frame)
        self._outline_fade = QtCore.QVariantAnimation(self)
        self._outline_fade.setStartValue(1.0)
        self._outline_fade.setEndValue(0.0)
        self._outline_fade.setDuration(self.OUTLINE_MS)
        self._outline_fade.setEasingCurve(QtCore.QEasingCurve.Type.InQuad)
        self._outline_fade.valueChanged.connect(self._outline_frame)
        self._veil_timer = QtCore.QTimer(self)
        self._veil_timer.setSingleShot(True)
        self._veil_timer.timeout.connect(self._show_veil)
        self._settler = QtCore.QTimer(self)
        self._settler.setSingleShot(True)
        self._settler.timeout.connect(self._settle)
        self._progress_timer = QtCore.QTimer(self)
        self._progress_timer.setInterval(100)
        self._progress_timer.timeout.connect(self._show_progress)
        self.mpl_connect('draw_event', lambda event: self._outline_rects.clear())

    def _guard_draw_event(self):
        """The figure's draw_event let out only from this thread, and not while held back: a draw in
        the background, or one not shown, says it's drawn once its image is the one shown."""
        callbacks = self.figure._canvas_callbacks
        process = callbacks.process

        def guarded(name, *args, **kwargs):
            if name == 'draw_event' and (self._quiet or threading.current_thread() is not threading.main_thread()):
                return None
            return process(name, *args, **kwargs)
        callbacks.process = guarded

    # ---- drawing: never while a run computes; a slow figure in a thread of its own

    @property
    def drawing(self):
        """Whether the figure's being drawn in the background now."""
        return getattr(self, '_render', None) is not None

    def _draw_idle(self):
        self._drawing_idle = True   # asked for through draw_idle(): it may go to the background
        try:
            super()._draw_idle()
        finally:
            self._drawing_idle = False

    def draw(self):
        if not hasattr(self, 'navigation'):   # still being made
            super().draw()
            return
        if self._render is not None:   # drawn in the background already: again once that's done
            self._draw_again = True
            return
        if self._run is not None:   # the run's thread may be halfway through changing the figure
            self._draw_waiting = True
            return
        if not _detail.allowed(self):   # it would take too long: the veil asks what to draw first
            return
        self._prepare()
        if self._drawing_idle and self._heavy():
            self._draw_in_background()
        else:
            self._rough = _detail.prepare(self.figure, self._moving(), self.draw_rate)
            self._draw_here()

    def draw_now(self):
        """The figure drawn here and now, not in the background - True if it was."""
        if self._render is not None or self._run is not None or not _detail.allowed(self):
            return False
        self._prepare()
        self._rough = _detail.prepare(self.figure, self._moving(), self.draw_rate)
        self._draw_here()
        return True

    def draw_idle(self):
        if threading.current_thread() is not threading.main_thread():   # asked from inside a run
            self._draw_waiting = True
            return
        super().draw_idle()

    def _prepare(self):
        """Before a draw: trendlines and error bars as their series are now, plots cut at their x."""
        figure = self.figure
        try:
            _fits.refresh(figure)
        except Exception:   # a fit that can't be drawn is no reason for the figure not to be
            traceback.print_exc()
        _upto.prepare(figure)

    def quick_once(self):
        """The next draw the quick way (a plot's many markers thinned), properly once it's still: the
        plots just moved about (a new arrangement) show at once."""
        self._quick = True

    def _moving(self):
        quick, self._quick = getattr(self, '_quick', False), False
        return self.navigation.busy or quick

    def _heavy(self):
        return self.last_draw_s > self.BACKGROUND_S or _detail.estimate(self.figure, self.draw_rate) > self.BACKGROUND_S

    def _render_figure(self, renderer, draw=None):
        """The figure onto the renderer - its large series reduced, if so answered, and plots shown up to
        an x cut there (draw: what draws it, if not the figure - the animation's images)."""
        with _detail.reduced(self.figure, self.draw_rate), _upto.cut(self.figure):   # shown up to an x: its data cut
            (draw or self.figure.draw)(renderer)

    def _timed(self, took, cost):
        """How long a point took, from a draw of so much (a large one: a small one's mostly else)."""
        if cost > 300_000 and took > 0.05:
            measured = took / cost
            self.draw_rate = min(max(0.5 * self.draw_rate + 0.5 * measured, _detail.RATE / 4), _detail.RATE * 4)

    def _draw_here(self):
        started = time.perf_counter()
        self._is_drawing, self._quiet = True, True
        try:
            renderer = self.get_renderer()
            renderer.clear()
            try:
                self._render_figure(renderer)
            except Exception:
                if not self._repair():
                    raise
                renderer.clear()
                self._render_figure(renderer)
        finally:
            self._is_drawing, self._quiet = False, False
        self.last_draw_s = time.perf_counter() - started
        if not getattr(self.figure, '_csn_reduced', None):
            self._timed(self.last_draw_s, _detail.units(self.figure))
        self.update()
        self._drawn(renderer)

    def _repair(self):
        """Limits that can't be drawn put back to the data - True if there were any."""
        repaired = False
        for ax in self.figure.axes:
            try:
                repaired = _series.safe_limits(ax) or repaired
            except Exception:
                traceback.print_exc()
        return repaired

    @staticmethod
    def _mathtext_one_at_a_time():
        """matplotlib's mathtext parser (a log axis' 10³ labels, any $...$) is one for every figure, and
        it isn't safe in two threads at once: a figure drawn in a thread while the window measured
        another's labels made it fail now and then - that layout given up, the plots spilling over their
        cells till the next. Its parses taken one at a time."""
        from matplotlib import mathtext
        parse = mathtext.MathTextParser.parse
        if getattr(parse, '_csn_locked', False):
            return
        lock = threading.RLock()

        def locked(parser, *args, **kwargs):
            with lock:
                return parse(parser, *args, **kwargs)
        locked._csn_locked = True
        locked.__doc__, locked.__name__ = parse.__doc__, parse.__name__
        mathtext.MathTextParser.parse = locked

    def _draw_in_background(self):
        """In a thread of its own, a part at a time (_detail.chunked): the window answers meanwhile."""
        figure = self.figure
        w, h = figure.bbox.size
        job = {'key': (w, h, figure.dpi), 'error': None, 'started': time.perf_counter(), 'done': 0,
               'units': max(_detail.units(figure), 1), 'points': _detail.drawn_points(figure, self.draw_rate),
               'cancel': False, 'rough': False}
        job['renderer'] = _detail.chunked(RendererAgg(w, h, figure.dpi),
                                          lambda cost: job.__setitem__('done', job['done'] + cost),
                                          lambda: job['cancel'])
        if hasattr(self, 'renderer'):
            self._shown_image = _animate._image(self.renderer, self.device_pixel_ratio or 1.0)
        moving = self._moving()

        def work():
            try:
                job['rough'] = _detail.prepare(figure, moving, self.draw_rate,   # which markers show: in here too
                                               lambda: job['cancel'])
                self._render_figure(job['renderer'])
            except _detail.Cancelled as caught:
                job['error'] = caught
            except Exception as caught:   # put right, or said, back in the window's thread
                job['error'] = caught
                job['trace'] = traceback.format_exc()
            job['took'] = time.perf_counter() - job['started']
            self._mailbox.rendered.emit(job)
        job['thread'] = threading.Thread(target=work, name='csn_matplotlib drawing', daemon=True)
        self._render = job
        self.inspector.clear_hover()
        if not self._veil_timer.isActive() and not self.busy_veil.isVisible():
            self._veil_timer.start(self.VEIL_MS)
        self._progress_timer.start()
        job['thread'].start()

    def _rendered(self, job):
        if self._render is not job:   # taken already (finish_drawing)
            return
        job['thread'].join()
        self._render = None
        self._progress_timer.stop()
        if self._run is None:
            self._veil_timer.stop()
            self.busy_veil.leave()
        figure = self.figure
        if job['error'] is None:
            self.renderer, self._lastKey = job['renderer'], job['key']
            self.last_draw_s = job['took']
            self._rough = job['rough']
            if not getattr(figure, '_csn_reduced', None):   # in the estimate's own units, as _draw_here
                self._timed(job['took'], job['units'])
            self._shown_image = None
            self.update()
            self._drawn(job['renderer'])
        elif isinstance(job['error'], _detail.Cancelled):   # stopped: a reduced set instead, quick
            self._shown_image = None
            figure._csn_big = ('reduced', _detail.units(figure))
            self.say('Drawing stopped. A reduced set of the points is drawn instead')
            self._draw_again = True
        else:
            self._shown_image = None
            self.update()
            if self._repair():
                self._draw_again = True
            else:
                print(job.get('trace', ''), end='')
        if self._resize_waiting:
            self._resize_waiting = False
            super().resizeEvent(QtGui.QResizeEvent(self.size(), self.size()))   # the figure, to the size it is now
        if self._draw_again:
            self._draw_again = False
            self.draw_idle()

    def _show_progress(self):
        job = self._render
        if job is not None and self.busy_veil.isVisible() and self._run is None:
            self.busy_veil.fraction = min(job['done'] / job['units'], 0.99)
            self.busy_veil.update()

    def finish_drawing(self):
        """A draw going on in the background, finished and shown - before the figure changes."""
        job = getattr(self, '_render', None)
        if job is not None:
            job['thread'].join()
            self._rendered(job)

    def print_figure(self, *args, **kwargs):
        """Saved (or copied) - the image shown kept: matplotlib draws a PNG on the window's own image, at
        the file's size and dpi, and the plots were shown that way, zoomed, till the next draw."""
        self.finish_drawing()   # saving draws the figure too: not both at once
        shown = getattr(self, 'renderer', None), getattr(self, '_lastKey', None)
        try:
            return super().print_figure(*args, **kwargs)
        finally:
            if shown[0] is not None:
                self.renderer, self._lastKey = shown
            self.update()

    def _drawn(self, renderer):
        """The figure's image shown: it says so (draw_event), and what's drawn over it follows - the
        plots rising in, if they're to."""
        self._image_drawn = True
        DrawEvent('draw_event', self, renderer)._process()
        if self._rough:
            self._settler.start(self.SETTLE_MS)
        self._place_badges()
        if self._reveal_wanted is not None:
            self._reveal_now()

    def _settle(self):
        if self.navigation.busy:
            self._settler.start(self.SETTLE_MS)
        else:
            self.draw_idle()

    @property
    def computing(self):
        return getattr(self, '_run', None) is not None

    @property
    def busy(self):
        """Computing, drawing, or asking what to draw: not the time to keep the settings."""
        return self.computing or self.drawing or (hasattr(self, 'big_veil') and self.big_veil.isVisible())

    def set_computing(self, job, owner):
        """A run going on (job, the Parameters it's of) or done (None, None)."""
        self._run = (job, owner) if job is not None else None
        if job is not None:
            self.inspector.clear_hover()
            self.layout_tool.cancel()
            if self.reveal_effect.active and self.reveal_effect.whole:   # the window opening: once it's computed
                self._reveal_wanted = (None, None, True)
            self.reveal_effect.stop()
            if not self.busy_veil.isVisible():
                self._veil_timer.start(self.VEIL_MS)
        else:
            self._veil_timer.stop()
            self.busy_veil.leave()
            if self._draw_waiting:
                self._draw_waiting = False
                self.draw_idle()

    def _show_veil(self):
        if self._run is not None:
            self.busy_veil.show_over('Computing', stoppable=True)
            self.busy_veil.fraction = self._run[0].fraction
        elif self._render is not None:
            self.busy_veil.show_over(f"Drawing {self._render['points']:,} points", stoppable=True)
            self._show_progress()

    def stop_run(self):
        """Stop (or Esc): the run computing - or the draw, which then draws a reduced set."""
        if self._run is not None:
            self._run[1].stop()
        elif self._render is not None:
            self._render['cancel'] = True

    def reveal(self, hold=False, axes=None):
        """The plots coming into view (_animate): now, if what's shown is the figure as it is - else once
        it's drawn (hold: once let_reveal() says). Till then nothing of them shows (REVEAL_WAIT_S at most).
        axes: only these plots' data comes in (a plot added) - the rest's shown meanwhile."""
        self._reveal_wanted = (None, list(axes) if axes is not None else None, True)
        self._reveal_held = hold
        self._reveal_since = time.perf_counter()
        QtCore.QTimer.singleShot(int(self.REVEAL_WAIT_S * 1000) + 50, self.update)
        self._reveal_now()

    def let_reveal(self):
        self._reveal_held = False
        self._reveal_now()

    def drop_reveal(self):
        """Not to come in after all: shown as it is."""
        if self._reveal_wanted is not None and self._reveal_wanted[0] is None:
            self._reveal_wanted = None
        self._reveal_held = False
        self.update()

    def _reveal_pending(self):
        """A whole reveal waiting to start: the canvas shows nothing of the plots meanwhile."""
        wanted = self._reveal_wanted
        return (wanted is not None and wanted[0] is None and wanted[1] is None and _animate.enabled()
                and not self.computing and time.perf_counter() - self._reveal_since < self.REVEAL_WAIT_S)

    def animate_change(self, axes, grow, mode, artists):
        """A series about to be shown (grow) or hidden in these plots - these artists of it: it comes or
        goes, the way of its kind (mode), once it's drawn - its reference shadow with it."""
        if not _animate.enabled() or not hasattr(self, 'renderer') or self.drawing or self.computing \
                or not self.isVisible() or self.reveal_effect.active:
            return
        wanted = self._reveal_wanted
        if wanted is not None and wanted[0] is None:
            return   # the plots' data is to come in anyway
        artists, axes = list(artists), list(axes)
        if not grow:   # shown still: those going with it
            artists += _animate.shadows_of(artists, self.figure)
        if wanted is not None and wanted[2] == grow and wanted[3] == mode:   # with another going the same way
            artists, axes = wanted[0] + artists, wanted[1] + axes
        self._reveal_wanted = (artists, axes, grow, mode)

    def _reveal_now(self):
        wanted = self._reveal_wanted
        if wanted is None or self._reveal_held or not self.isVisible() or self.figure.stale or self.drawing \
                or self.computing or not hasattr(self, 'renderer') or self._rough:
            return
        w, h = self.figure.bbox.size
        if abs(self.renderer.width - w) > 1 or abs(self.renderer.height - h) > 1:   # drawn at another size
            return
        self._reveal_wanted = None
        if not self.reveal_effect.start(*wanted):
            if wanted[0] is None and wanted[1] is None and not any(a.get_visible() for ax in self.figure.axes
                                             for a in _animate._data_artists(ax)):
                self._reveal_wanted = wanted   # no data yet (a run's to draw it): it comes in once there is
            self.update()   # no animation now: the plots as they are

    def showEvent(self, event):
        super().showEvent(event)
        if self._reveal_wanted is not None:
            QtCore.QTimer.singleShot(0, self._reveal_now)

    # ---- what's drawn over the figure: notes, outlines, labels on plots drawn reduced

    def say(self, text, error=False):
        """A note at the bottom left - an error printed as well (the terminal shows it, in red); nothing else is."""
        if text:
            self.toast.say(text)
            if error:
                import sys   # here: only an error's printed
                print(f"csn_matplotlib: {text}", file=sys.stderr)

    def outline(self, axes, hold=False, key='hover'):
        """Plots outlined on the canvas - for a moment, or held under a key until outline([], hold=True,
        key=key): 'hover' (a panel's row under the pointer) filled while it's held, 'plot' (the Plot tab's
        plot) its fill fading, its line staying."""
        axes = [_view.main_of(ax) for ax in axes if ax is not None and ax.figure is self.figure]
        if hold:
            if axes != self._held.get(key, []):
                self._held[key] = axes
                if key == 'plot' and axes:
                    self._fill_fade.stop()
                    self._fill_fade.start()
                self.update()
            return
        self._outlined = axes
        self._outline_fade.stop()
        if axes:
            self._outline_fade.start()
        self.update()

    def _outline_frame(self, level):
        self._outline_level = float(level)
        self.update()

    def _fill_frame(self, level):
        self._held_fill = float(level)
        self.update()

    def _outline_rect(self, ax):
        """The plot's place: the cell the layout gives it - not its box, which goes with what's drawn in
        it - in the widget's pixels; a plot in no cell, its box with its labels. Kept until the next draw."""
        if id(ax) not in self._outline_rects:
            cell = self._cell_rect(ax)
            if cell is not None:
                self._outline_rects[id(ax)] = cell
                return cell
            ratio = self.device_pixel_ratio or 1.0
            height = self.figure.bbox.height
            members = [a for a in self.figure.axes if _view.main_of(a) is ax and a.get_visible()]
            boxes = []
            for a in members:
                try:
                    boxes.append(a.get_tightbbox(self.get_renderer()))
                except Exception:
                    boxes.append(a.bbox)
            boxes = [b for b in boxes if b is not None and math.isfinite(b.x0) and math.isfinite(b.y1)]
            if not boxes:
                return None
            x0, y0 = min(b.x0 for b in boxes), min(b.y0 for b in boxes)
            x1, y1 = max(b.x1 for b in boxes), max(b.y1 for b in boxes)
            self._outline_rects[id(ax)] = QtCore.QRectF(x0 / ratio, (height - y1) / ratio, (x1 - x0) / ratio,
                                                        (y1 - y0) / ratio).adjusted(-6, -6, 6, 6)
        return self._outline_rects[id(ax)]

    def _cell_rect(self, ax):
        """The plot's cell in the tab's arrangement, in the widget's pixels - None if it's not in one (or
        it isn't where its cell is: the script's own placing)."""
        try:
            state, cells, xs, ys = self.layout_tool.arranger.geometry()
        except Exception:
            return None
        identity = _series.ax_id(ax)
        if identity not in state['plots']:
            return None
        index = state['plots'].index(identity)
        ratio = self.device_pixel_ratio or 1.0
        box = ax.bbox
        centre = QtCore.QPointF((box.x0 + box.x1) / 2 / ratio, (self.figure.bbox.height - (box.y0 + box.y1) / 2) / ratio)
        if not cells[index].contains(centre):
            return None
        xs, ys = self._split_at_gaps(state, xs, ys)
        r0, r1, c0, c1 = state['cells'][index]
        return QtCore.QRectF(QtCore.QPointF(xs[c0], ys[r0]), QtCore.QPointF(xs[c1], ys[r1])).adjusted(5, 5, -5, -5)

    def _split_at_gaps(self, state, xs, ys):
        """The lines between the cells, each moved to halfway between the plots on either side of it,
        their labels included - so no plot's outline takes in a neighbour's tick labels, and outlines
        in a row or a column still line up. Kept until the next draw."""
        if 'gaps' in self._outline_rects:
            return self._outline_rects['gaps']
        ratio = self.device_pixel_ratio or 1.0
        height = self.figure.bbox.height
        renderer = self.get_renderer()
        boxes = {}   # cell index -> (left, top, right, bottom) of its plot and labels, in the widget's pixels
        for a in self.figure.axes:
            main = _view.main_of(a)
            if not a.get_visible() or _series.ax_id(main) not in state['plots']:
                continue
            try:
                tight = a.get_tightbbox(renderer)
            except Exception:
                tight = a.bbox
            if tight is None or not all(math.isfinite(v) for v in tight.extents):
                continue
            index = state['plots'].index(_series.ax_id(main))
            edges = (tight.x0 / ratio, (height - tight.y1) / ratio, tight.x1 / ratio, (height - tight.y0) / ratio)
            old = boxes.get(index, edges)
            boxes[index] = (min(old[0], edges[0]), min(old[1], edges[1]), max(old[2], edges[2]), max(old[3], edges[3]))
        xs, ys = list(xs), list(ys)
        for edges, ends, starts, last, first in ((xs, 3, 2, 2, 0), (ys, 1, 0, 3, 1)):
            for k in range(1, len(edges) - 1):
                before = [box[last] for i, box in boxes.items() if state['cells'][i][ends] == k]
                after = [box[first] for i, box in boxes.items() if state['cells'][i][starts] == k]
                if before and after:
                    edges[k] = (max(before) + min(after)) / 2
        self._outline_rects['gaps'] = xs, ys
        return xs, ys

    def _paint_outlines(self, painter):
        shown = {}   # ax -> (its line's level, its fill's)
        for key, axes in self._held.items():
            for ax in axes:
                line, fill = shown.get(ax, (0.0, 0.0))
                shown[ax] = (1.0, max(fill, self._held_fill if key == 'plot' else 1.0))
        if self._outline_fade.state() == QtCore.QAbstractAnimation.State.Running:
            for ax in self._outlined:
                line, fill = shown.get(ax, (0.0, 0.0))
                shown[ax] = (max(line, self._outline_level), max(fill, self._outline_level))
        if not shown or self.drawing:
            return
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        for ax, (level, fill_level) in shown.items():
            if ax.figure is not self.figure or not ax.get_visible():
                continue
            rect = self._outline_rect(ax)
            if rect is None:
                continue
            colour = QtGui.QColor(_style.ACCENT)
            colour.setAlphaF(level)
            fill = QtGui.QColor(_style.ACCENT)
            fill.setAlphaF(0.07 * fill_level)
            painter.setPen(QtGui.QPen(colour, 2))
            painter.setBrush(fill)
            painter.drawRoundedRect(rect, 8, 8)

    def _picked_changed(self, by):
        ax = self.picked.ax
        if self.picked.series is not None:   # however it was picked - the plot, a panel, a legend: its run's sliders
            _sliders.select(self.picked.series)
        if by is not self and ax is not None and ax is not self._picked_ax:
            self.outline([ax])
        self._picked_ax = ax

    def _place_badges(self):
        """One red label while any of the tab's plots is drawn reduced - it goes for all of them, and
        can't be closed; More info says which, and how to draw every point. It can be dragged anywhere
        (kept with the tab's settings); till it is, it's put where it covers the least of the titles,
        labels and plots."""
        reduced = _detail.badges(self.figure)
        badge = self._badge
        if not reduced:
            if badge is not None:
                badge.hide()
            return
        if badge is None:
            badge = self._badge = QtWidgets.QLabel(self)
            badge.setObjectName('csnBadge')
            badge.setTextFormat(Qt.TextFormat.RichText)
            badge.setText("Not all points shown for performance. "
                          "<a href='info' style='color:#ffffff'>More info</a>")
            badge.setToolTip('Drag to move it')
            badge.setCursor(Qt.CursorShape.OpenHandCursor)
            badge.linkActivated.connect(lambda _: None if self._badge_drag else _detail.ReducedInfo(self).exec())
            badge.installEventFilter(self)
        badge.adjustSize()
        badge.move(self._badge_spot(badge.size()))
        badge.show()
        badge.raise_()

    def _badge_spot(self, size):
        room = QtCore.QRect(0, 0, self.width(), self.height()).adjusted(8, 8, -8, -8)
        saved = store.section(self.figure).get('badge')
        if isinstance(saved, list) and len(saved) == 2:   # dragged there: kept, as a share of the tab
            at = QtCore.QPoint(int(saved[0] * self.width()), int(saved[1] * self.height()))
            return self._badge_inside(at, size)
        ratio = self.device_pixel_ratio or 1.0
        height = self.figure.bbox.height
        renderer = getattr(self, 'renderer', None)

        def box(bbox):   # display pixels -> the widget's
            return QtCore.QRectF(bbox.x0 / ratio, (height - bbox.y1) / ratio, bbox.width / ratio, bbox.height / ratio)
        texts, plots = [], []
        for ax in self.figure.axes:
            if not ax.get_visible():
                continue
            plots.append(box(ax.bbox))
            for text in (ax.title, getattr(ax, '_left_title', None), getattr(ax, '_right_title', None),
                         ax.xaxis.label, ax.yaxis.label, ax.get_legend()):
                if text is not None and text.get_visible() and renderer is not None \
                        and (not hasattr(text, 'get_text') or text.get_text()):
                    try:
                        texts.append(box(text.get_window_extent(renderer)))
                    except Exception:
                        pass
        suptitle = getattr(self.figure, '_suptitle', None)
        if suptitle is not None and suptitle.get_text() and renderer is not None:
            texts.append(box(suptitle.get_window_extent(renderer)))
        w, h = size.width(), size.height()
        spots = [QtCore.QPoint(room.left(), room.top()), QtCore.QPoint(room.right() - w, room.top()),
                 QtCore.QPoint(room.left(), room.bottom() - h), QtCore.QPoint(room.right() - w, room.bottom() - h),
                 QtCore.QPoint(room.center().x() - w // 2, room.bottom() - h),
                 QtCore.QPoint(room.center().x() - w // 2, room.top())]

        def covered(spot):
            rect = QtCore.QRectF(spot.x(), spot.y(), w, h)
            area = lambda boxes: sum(max(r.width(), 0) * max(r.height(), 0) for r in (rect.intersected(b) for b in boxes))
            return 20 * area(texts) + area(plots)
        return min(spots, key=covered)   # the first of the least covered: the top left, if it's clear

    def _badge_inside(self, at, size):
        return QtCore.QPoint(min(max(at.x(), 0), max(self.width() - size.width(), 0)),
                             min(max(at.y(), 0), max(self.height() - size.height(), 0)))

    def eventFilter(self, watched, event):
        """The red label dragged about: kept where it's let go."""
        badge = self._badge
        if watched is not badge or badge is None:
            return super().eventFilter(watched, event)
        kind = event.type()
        if kind == QtCore.QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
            self._badge_press = (event.globalPosition().toPoint(), badge.pos())
            self._badge_drag = False
        elif kind == QtCore.QEvent.Type.MouseMove and self._badge_press is not None:
            start, origin = self._badge_press
            moved = event.globalPosition().toPoint() - start
            if self._badge_drag or moved.manhattanLength() > QtWidgets.QApplication.startDragDistance():
                self._badge_drag = True
                badge.setCursor(Qt.CursorShape.ClosedHandCursor)
                badge.move(self._badge_inside(origin + moved, badge.size()))
                return True
        elif kind == QtCore.QEvent.Type.MouseButtonRelease and self._badge_press is not None:
            self._badge_press = None
            if self._badge_drag:
                badge.setCursor(Qt.CursorShape.OpenHandCursor)
                store.section(self.figure)['badge'] = [badge.x() / max(self.width(), 1),
                                                       badge.y() / max(self.height(), 1)]
                store.changed()
                QtCore.QTimer.singleShot(0, lambda: setattr(self, '_badge_drag', False))   # no More info for it
                return True
        return super().eventFilter(watched, event)

    # ---- picked, and the menus

    def pick_series(self, s, index=None):
        """A series clicked on the plot: picked in the panels, the sliders on the parameters of its run."""
        self.picked.set(s.ax, s, by=self)
        _sliders.select(s)
        panel = getattr(self.manager, 'panel', None)
        if panel is not None and index is not None:
            panel.show_point(s, index)

    def open_look(self, s):
        manager = self.manager
        if hasattr(manager, 'open_look'):
            manager.open_look(s)

    def plot_menu(self, ax, at):
        _plot_panel.plot_menu(self, ax, at)

    def contextMenuEvent(self, event):
        if self.computing or self.drawing or self.layout_tool.active or self.navigation._toolbar_mode():
            return
        self.reveal_effect.stop()
        xy = tuple(self.mouseEventCoords(event.pos()))
        at = event.globalPos()
        ax = next((a for a in reversed(self.figure.axes) if a.get_visible() and not hasattr(a, '_colorbar')
                   and a.bbox.contains(*xy)), None)
        if ax is not None:
            _plot_panel.plot_menu(self, _view.main_of(ax), at)
            return
        hit = self.layout_tool.arranger.hit(QtCore.QPointF(event.pos()))
        if hit is not None and hit[0] == 'cell':
            state = _layout.state_of(self.figure)
            if hit[1] < len(state['plots']) and state['plots'][hit[1]] is None:
                _layout.cell_menu(self.figure, hit[1], at, self)
                return
        _plot_panel.figure_menu(self, at)

    # ---- standing still while resized

    def freeze(self):
        """Until thaw(): a still of the figure as it is now stands in for it, and being resized doesn't
        re-render the figure."""
        if getattr(self, '_still', None) is None:
            self._still = self.grab()

    def thaw(self):
        if getattr(self, '_still', None) is not None:
            self._still = None
            if self.drawing:
                self._resize_waiting = True
            else:
                super().resizeEvent(QtGui.QResizeEvent(self.size(), self.size()))   # the figure, to this size
            self.update()

    def resizeEvent(self, event):
        if hasattr(self, 'reveal_effect'):
            effect = self.reveal_effect
            if effect.active and effect.whole:   # the window settling at its size (the panel opening): again
                self._reveal_wanted = (None, None, True)
                self._reveal_since = time.perf_counter()
            effect.stop()
        if getattr(self, '_still', None) is not None:
            QtWidgets.QWidget.resizeEvent(self, event)
        elif getattr(self, '_render', None) is not None:   # not while it's drawn: once it is
            QtWidgets.QWidget.resizeEvent(self, event)
            self._resize_waiting = True
        else:
            super().resizeEvent(event)
        if hasattr(self, 'busy_veil'):
            if self.busy_veil.isVisible():
                self.busy_veil.setGeometry(self.rect())
            veil = self.big_veil
            if veil.isVisible():
                veil.move(max((self.width() - veil.width()) // 2, 0), max((self.height() - veil.height()) // 3, 0))

    def paintEvent(self, event):
        if hasattr(self, 'reveal_effect') and not self.reveal_effect.active and self._reveal_pending():
            self._draw_idle()   # drawn meanwhile (the animation starts once it is): nothing of it shown before
            if not self.reveal_effect.active:
                painter = QtGui.QPainter(self)
                painter.fillRect(event.rect(), QtGui.QColor(_style.SURFACE))
                painter.end()
                return
        still = getattr(self, '_still', None)
        if still is not None:
            painter = QtGui.QPainter(self)
            painter.fillRect(event.rect(), QtGui.QColor(_style.SURFACE))
            painter.drawPixmap(0, 0, still)
            painter.end()
            return
        if not hasattr(self, 'reveal_effect'):   # still being made
            super().paintEvent(event)
            return
        if self.reveal_effect.active:
            painter = QtGui.QPainter(self)
            painter.fillRect(event.rect(), QtGui.QColor(_style.SURFACE))
            self.reveal_effect.paint(painter)
            painter.end()
            return
        self._draw_idle()   # a draw asked for: now - it may go to the background
        if self.reveal_effect.active:   # started by that draw: its first frame, not the plots before it
            painter = QtGui.QPainter(self)
            painter.fillRect(event.rect(), QtGui.QColor(_style.SURFACE))
            self.reveal_effect.paint(painter)
            painter.end()
            return
        if self._render is not None:   # the image shown before, until the new one's drawn
            painter = QtGui.QPainter(self)
            painter.fillRect(event.rect(), QtGui.QColor(_style.SURFACE))
            if self._shown_image is not None:
                painter.drawImage(QtCore.QPointF(0, 0), self._shown_image)
            painter.end()
            return
        painter = QtGui.QPainter(self)
        painter.fillRect(event.rect(), QtGui.QColor(_style.SURFACE))   # where the figure's image falls short
        painter.end()
        renderer = getattr(self, 'renderer', None)
        if not self._image_drawn or renderer is None:   # nothing drawn yet: no white of a blank renderer
            return
        # The whole image at the corner, as the animation draws it - not matplotlib's paintEvent, whose
        # copy of the part to repaint is rounded at a scale like 125 % and erased to white first: the
        # white line beside the panel and at the bottom. Qt clips it to the part to repaint.
        buffer = memoryview(renderer.buffer_rgba())
        image = QtGui.QImage(buffer, buffer.shape[1], buffer.shape[0], QtGui.QImage.Format.Format_RGBA8888)
        image.setDevicePixelRatio(self.device_pixel_ratio or 1.0)
        painter = QtGui.QPainter(self)
        painter.drawImage(QtCore.QPointF(0, 0), image)
        self._draw_rect_callback(painter)   # matplotlib's zoom rectangle, while one's dragged
        painter.end()
        if self.layout_tool.active or any(self._held.values()) or self._outlined:
            painter = QtGui.QPainter(self)
            self.layout_tool.paint(painter)
            self._paint_outlines(painter)
            painter.end()

    # ---- input - none reaches the figure while a run computes or it's drawn in the background

    def _busy(self):
        return self.computing or self.drawing

    def keyPressEvent(self, event):
        key = event.key()
        keys = Qt.Key
        self.reveal_effect.stop()
        if key == keys.Key_Escape and (self.computing or self.drawing):
            self.stop_run()
            return
        if self._busy():
            return
        plain = not (event.modifiers() & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier
                                          | Qt.KeyboardModifier.MetaModifier))
        arrows = {keys.Key_Left: (-1, 0), keys.Key_Right: (1, 0), keys.Key_Up: (0, 1), keys.Key_Down: (0, -1)}
        if plain and key in arrows:
            self.navigation.nudge(*arrows[key])
            return
        if plain and key in (keys.Key_Plus, keys.Key_Equal):
            self.navigation.key_zoom(1)
            return
        if plain and key in (keys.Key_Minus, keys.Key_Underscore):
            self.navigation.key_zoom(-1)
            return
        if key == keys.Key_F2 and plain:
            self._rename()
            return
        if key == keys.Key_Space and not event.modifiers() and not event.isAutoRepeat():
            self.navigation.reset_focused()
        elif key == keys.Key_Escape and self.layout_tool.active and hasattr(self.manager, 'layout_action'):
            self.manager.layout_action.setChecked(False)
        super().keyPressEvent(event)

    def _rename(self):
        """F2: the tab under the pointer renamed - else the series picked, else the plot under the pointer,
        else the one picked, else the tab."""
        host = Host._one
        if host is not None and host.over_tabs():
            host.rename_tab()
            return
        s = self.picked.series
        if s is not None and s.ax.figure is self.figure:
            if _view.locked(s):
                self.say(f"“{s.label}” is locked. Unlock it to rename it")
                return
            name, ok = QtWidgets.QInputDialog.getText(self, 'Rename series', 'Name:', text=s.label)
            if ok and name.strip() and name.strip() != s.label:
                _view.rename(_series.key_of(s), name.strip())
            return
        at = self.mapFromGlobal(QtGui.QCursor.pos())
        ratio = self.device_pixel_ratio or 1.0
        x, y = at.x() * ratio, self.figure.bbox.height - at.y() * ratio
        ax = next((a for a in self.figure.axes if a.get_visible() and a.bbox.contains(x, y)), None) or self.picked.ax
        if ax is not None and ax.figure is self.figure:
            _plot_panel.ask_name(self, ax)
        elif host is not None:
            host.rename_tab()

    def wheelEvent(self, event):
        self.reveal_effect.stop()
        if self._busy():
            event.accept()
            return
        self.navigation.wheel(event)
        super().wheelEvent(event)   # matplotlib's scroll_event still goes out

    def mousePressEvent(self, event):
        self.reveal_effect.stop()
        if self._busy() or self.layout_tool.press(event):
            return
        if not _from_touch(event):
            self.navigation.press(event)
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event):
        if self._busy() or self.layout_tool.active:
            return
        xy = tuple(self.mouseEventCoords(event))
        left = event.button() == Qt.MouseButton.LeftButton and not self.navigation._toolbar_mode()   # pan, zoom: only that
        if left and self.labels.double_click(xy):
            return
        manager = self.manager
        if (left and hasattr(manager, 'side_tabs')
                and manager.side.isVisible() and manager.side_tabs.currentWidget() is manager.plot_panel):
            found = self.inspector._find(xy)   # the Plot tab open: a series picked there - else its plot
            ax = found[0].ax if found else next((a for a in reversed(self.figure.axes) if a.get_visible()
                                                 and not hasattr(a, '_colorbar') and a.bbox.contains(*xy)), None)
            if ax is not None:
                self.manager.show_plot_panel(_view.main_of(ax), found[0] if found else None)
        if not _from_touch(event):
            self.navigation.press(event)   # a double click's second press, for a drag after it
        super().mouseDoubleClickEvent(event)

    def mouseMoveEvent(self, event):
        if self.computing or self.layout_tool.move(event):
            return
        touch = _from_touch(event)
        if not touch and self.navigation.move(event):
            return
        if self.drawing:
            return
        super().mouseMoveEvent(event)
        if not touch and not event.buttons() and not self.navigation.busy:
            if self.navigation._toolbar_mode():   # matplotlib's pan or zoom on: the plot's an image to move, no more
                self.inspector.clear_hover()
            else:
                self.inspector.hover_at(tuple(self.mouseEventCoords(event)))

    def mouseReleaseEvent(self, event):
        if self.layout_tool.release(event):
            return
        if _from_touch(event):
            super().mouseReleaseEvent(event)
            return
        panned = self.navigation.release(event)   # a drag ends, run or not
        super().mouseReleaseEvent(event)
        if (not panned and not self._busy() and event.button() == Qt.MouseButton.LeftButton
                and not self.navigation._toolbar_mode()):
            self.inspector.click(tuple(self.mouseEventCoords(event)))

    def leaveEvent(self, event):
        self.inspector.clear_hover()
        super().leaveEvent(event)

    def event(self, event):
        kinds = QtCore.QEvent.Type
        kind = event.type()
        if kind in (kinds.TouchBegin, kinds.TouchUpdate, kinds.TouchEnd, kinds.TouchCancel):
            if hasattr(self, 'reveal_effect'):
                self.reveal_effect.stop()
            if not self.layout_tool.active and not self.computing:   # moving plots, a finger drags the plot
                self.navigation.touch(event)
            event.accept()
            return True
        if kind == kinds.NativeGesture:
            if not self.computing:
                self.navigation.native_gesture(event)
            event.accept()
            return True
        return super().event(event)


def _from_touch(event):
    """A mouse event Windows made up from a touch, alongside the touch events themselves - the
    navigation has those already (both: a finger moved the plot twice as far)."""
    try:
        if event.device().type() == QtGui.QInputDevice.DeviceType.TouchScreen:
            return True
    except AttributeError:
        pass
    try:
        return event.source() == Qt.MouseEventSource.MouseEventSynthesizedBySystem
    except AttributeError:
        return False


def _menu_button(toolbar, menu, action=None, icon=None):
    """A toolbar button with a menu: an action, its menu behind the arrow beside it - or only the menu."""
    button = QtWidgets.QToolButton(toolbar)
    if action is not None:
        button.setDefaultAction(action)
        button.setPopupMode(QtWidgets.QToolButton.ToolButtonPopupMode.MenuButtonPopup)
    else:
        button.setIcon(icon)
        button.setPopupMode(QtWidgets.QToolButton.ToolButtonPopupMode.InstantPopup)
    button.setMenu(menu)
    button.setAutoRaise(True)
    button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    button.setIconSize(toolbar.iconSize())
    toolbar.iconSizeChanged.connect(button.setIconSize)
    return button


def _glyph(kind, widget):
    """The toolbar's own icons, drawn - in the colour matplotlib's are recoloured to."""
    ratio = 3.0   # drawn large, scaled down smoothly whatever the screen
    pixmap = QtGui.QPixmap(int(24 * ratio), int(24 * ratio))
    pixmap.setDevicePixelRatio(ratio)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QtGui.QPainter(pixmap)
    painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
    colour = widget.palette().color(QtGui.QPalette.ColorRole.WindowText)
    pen = QtGui.QPen(colour, 1.6)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    point = QtCore.QPointF
    if kind == 'panel':
        painter.drawRoundedRect(QtCore.QRectF(3.5, 5.5, 17, 13), 2.5, 2.5)
        painter.drawLine(point(14.5, 5.5), point(14.5, 18.5))
        for y in (9, 12, 15):
            painter.drawLine(point(16.5, y), point(18.5, y))
    elif kind in ('undo', 'redo'):
        if kind == 'redo':   # the undo arrow, the other way round
            painter.translate(24, 0)
            painter.scale(-1, 1)
        path = QtGui.QPainterPath(point(5.5, 9.5))
        path.lineTo(14, 9.5)
        path.cubicTo(17.6, 9.5, 19.5, 11.8, 19.5, 14.5)
        path.cubicTo(19.5, 17.2, 17.6, 19.5, 14, 19.5)
        path.lineTo(9.5, 19.5)
        painter.drawPath(path)
        painter.drawPolyline(QtGui.QPolygonF([point(9.5, 5.5), point(5.5, 9.5), point(9.5, 13.5)]))
    elif kind == 'layout':   # a big plot and two small beside it
        painter.drawRoundedRect(QtCore.QRectF(3.5, 4.5, 9, 15), 1.5, 1.5)
        painter.drawRoundedRect(QtCore.QRectF(14.5, 4.5, 6, 6.5), 1.5, 1.5)
        painter.drawRoundedRect(QtCore.QRectF(14.5, 13, 6, 6.5), 1.5, 1.5)
    elif kind == 'settings':
        painter.drawEllipse(point(12, 12), 5.5, 5.5)
        painter.drawEllipse(point(12, 12), 2.2, 2.2)
        painter.setPen(QtGui.QPen(colour, 2.4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.FlatCap))
        for tooth in range(8):
            angle = tooth * math.pi / 4
            painter.drawLine(point(12 + 5.5 * math.cos(angle), 12 + 5.5 * math.sin(angle)),
                             point(12 + 8.5 * math.cos(angle), 12 + 8.5 * math.sin(angle)))
    elif kind == 'animate':   # a curve being drawn, its pen at its end
        path = QtGui.QPainterPath(point(3.5, 18.5))
        path.cubicTo(7, 18.5, 8, 9, 12, 9)
        painter.drawPath(path)
        faint = QtGui.QColor(colour)
        faint.setAlphaF(0.35)
        painter.setPen(QtGui.QPen(faint, 1.6, Qt.PenStyle.DotLine, Qt.PenCapStyle.RoundCap))
        rest = QtGui.QPainterPath(point(12, 9))
        rest.cubicTo(15.5, 9, 16.5, 15, 20.5, 15)
        painter.drawPath(rest)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(colour)
        painter.drawEllipse(point(12, 9), 2.2, 2.2)
        painter.setPen(QtGui.QPen(colour, 1.4))
        painter.drawLine(point(3.5, 21), point(20.5, 21))
    elif kind == 'terminal':   # a prompt in a box
        painter.drawRoundedRect(QtCore.QRectF(3.5, 5.5, 17, 13), 2.5, 2.5)
        painter.drawPolyline(QtGui.QPolygonF([point(7, 9.5), point(9.5, 12), point(7, 14.5)]))
        painter.drawLine(point(11.5, 14.5), point(16, 14.5))
    else:
        painter.drawRoundedRect(QtCore.QRectF(8.5, 3.5, 12, 13), 2, 2)
        painter.drawPolyline(QtGui.QPolygonF([point(5.5, 7.5), point(3.5, 7.5), point(3.5, 20.5),
                                              point(15.5, 20.5), point(15.5, 18.5)]))
    painter.end()
    return QtGui.QIcon(pixmap)


FigureCanvas = CSNCanvas
FigureManager = CSNFigureManager
