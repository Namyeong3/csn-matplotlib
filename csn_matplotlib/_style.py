"""The look: matplotlib's rcParams (the plots) and Qt's palette (the window around them), both dark.
The colours are the dark steps of a palette checked for colour blindness - series in a fixed order,
text in text colours, never a series colour."""
import ctypes
import os

import matplotlib as mpl
from cycler import cycler
from PySide6 import QtCore, QtGui, QtWidgets

SURFACE = '#1a1a19'    # the figure, the axes and the window - one surface, nothing framed
BASE = '#151514'       # lists and tables, a step down
FIELD = '#30302d'      # text boxes, drop-downs and buttons, a clear step up from the surface
FIELD_EDGE = '#4b4a45' # and their edge
RAISED = '#242422'     # legends, tooltips, the inspector's label
HOVER = '#2c2c2a'
PRESSED = '#383835'
BORDER = '#333330'
GRID = '#3d3c38'       # grid lines: plain to see, still under the data
GRID_MINOR = '#31302d'
TEXT = '#f0efec'
TEXT_2 = '#c3c2b7'
TEXT_3 = '#8a897f'
ACCENT = '#3987e5'
SELECT = '#22406a'

SERIES = ['#3987e5', '#d95926', '#199e70', '#c98500', '#d55181', '#008300', '#9085e9', '#e66767']

RC = {
    'figure.facecolor': SURFACE, 'figure.edgecolor': SURFACE,
    'figure.constrained_layout.use': True,   # labels and titles never over a neighbouring plot
    'figure.constrained_layout.w_pad': 0.07, 'figure.constrained_layout.h_pad': 0.07,   # off the edges
    'axes.facecolor': SURFACE, 'axes.edgecolor': BORDER, 'axes.linewidth': 0.8,
    'axes.labelcolor': TEXT_2, 'axes.titlecolor': TEXT, 'axes.titleweight': 'semibold',
    'axes.titlesize': 12, 'axes.titlepad': 10, 'axes.labelsize': 10, 'axes.labelpad': 6,
    'axes.prop_cycle': cycler(color=SERIES),
    'axes.grid': True, 'axes.axisbelow': True,
    'axes.spines.top': False, 'axes.spines.right': False,
    'grid.color': GRID, 'grid.linewidth': 0.6,
    'xtick.color': BORDER, 'ytick.color': BORDER, 'xtick.labelcolor': TEXT_2, 'ytick.labelcolor': TEXT_2,
    'xtick.labelsize': 9, 'ytick.labelsize': 9,
    'text.color': TEXT,
    'font.family': ['Segoe UI', 'DejaVu Sans'], 'font.size': 10,
    'legend.facecolor': RAISED, 'legend.edgecolor': BORDER, 'legend.framealpha': 0.92,
    'legend.labelcolor': TEXT_2, 'legend.fontsize': 9,
    'lines.linewidth': 2.0, 'lines.markersize': 4, 'lines.solid_capstyle': 'round',
    'patch.edgecolor': SURFACE,   # a surface-coloured gap between bars
    'scatter.edgecolors': 'face',
    'hatch.color': TEXT_3,
    'errorbar.capsize': 3,
    'agg.path.chunksize': 20000,   # a line of millions of points drawn in pieces - not an overflow
    'savefig.dpi': 300, 'savefig.facecolor': 'auto', 'savefig.format': 'svg',   # PNGs at 300 dpi, SVG first
    'toolbar': 'toolbar2',
    # matplotlib's own keys that the window does otherwise: the arrows pan, Ctrl+W closes a tab, each
    # plot has its grid in the Plot tab, the scales are there too
    'keymap.back': ['c', 'backspace', 'MouseButton.BACK'], 'keymap.forward': ['v', 'MouseButton.FORWARD'],
    'keymap.grid': [], 'keymap.grid_minor': [], 'keymap.xscale': [], 'keymap.yscale': [],
    'keymap.quit': [], 'keymap.quit_all': [],
}


def apply_rc():
    mpl.rcParams.update(RC)


_ICONS = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'icons').replace(os.sep, '/')

STYLESHEET = f"""
QMainWindow, QDialog, QWidget#csnPanel, QWidget#csnParameters, QWidget#csnLayout {{ background: {SURFACE}; }}
QLineEdit#csnRange {{ background: transparent; border: none; color: {TEXT_3}; padding: 0; }}
QLineEdit#csnRange:focus {{ background: {FIELD}; color: {TEXT}; }}
QLineEdit#csnLabelEdit {{ background: {FIELD}; color: {TEXT}; border: 1px solid {ACCENT}; border-radius: 4px; padding: 2px 6px; }}
QToolBar {{ background: {SURFACE}; border: none; border-bottom: 1px solid {BORDER}; padding: 3px 8px; spacing: 2px; }}
QToolBar::handle:horizontal {{ width: 8px; margin-right: 6px; }}
QToolBar::handle:vertical {{ height: 8px; margin-bottom: 6px; }}
QToolButton {{ background: transparent; border: none; border-radius: 6px; padding: 5px; color: {TEXT_2}; }}
QToolButton:hover {{ background: {HOVER}; }}
QToolButton:checked, QToolButton:pressed {{ background: {PRESSED}; }}
QToolButton[popupMode="1"] {{ padding-right: 17px; }}
QToolButton::menu-button {{ border: none; width: 14px; border-top-right-radius: 6px; border-bottom-right-radius: 6px; }}
QToolButton::menu-button:hover {{ background: {PRESSED}; }}
QToolButton[popupMode="2"]::menu-indicator {{ image: none; width: 0; }}
QToolButton#csnChoice {{ border: 1px solid transparent; padding: 3px; }}
QToolButton#csnChoice:checked {{ border-color: {ACCENT}; background: {PRESSED}; }}
QToolButton#csnSection {{ color: {TEXT_2}; font-weight: 600; padding: 4px 2px; }}
QLabel {{ color: {TEXT_2}; }}
QLabel#csnHeading {{ color: {TEXT}; font-weight: 600; font-size: 11pt; }}
QLabel#csnStats {{ color: {TEXT_2}; background: {BASE}; border-radius: 6px; padding: 8px 10px; }}
QLabel#csnError {{ color: #e66767; }}
QLabel#csnHint {{ color: {TEXT_3}; }}
QLabel#csnToast {{ background: {RAISED}; color: {TEXT}; border: 1px solid {BORDER}; border-radius: 8px; padding: 7px 12px; }}
QLabel#csnBadge {{ background: #3b1717; color: #ff9b8f; border: 1px solid #a33a32; border-radius: 6px; padding: 4px 8px; }}
QToolButton#csnButton {{ background: {FIELD}; color: {TEXT}; border: 1px solid {FIELD_EDGE}; border-radius: 6px; padding: 5px 12px; }}
QToolButton#csnButton:hover {{ background: #393935; }}
QToolButton#csnButton:disabled {{ color: {TEXT_3}; border-color: {BORDER}; background: {RAISED}; }}
QToolButton#csnButton::menu-indicator {{ image: none; width: 0; }}
QListWidget {{ background: {BASE}; color: {TEXT}; border: none; border-radius: 6px; outline: 0; }}
QListWidget::item {{ padding: 3px 2px; }}
QListWidget::item:selected {{ background: {SELECT}; color: {TEXT}; }}
QListWidget::item:hover:!selected {{ background: {HOVER}; }}
QCheckBox {{ color: {TEXT_2}; }}
QSplitter::handle {{ background: {BORDER}; }}
QSplitter::handle:hover {{ background: {ACCENT}; }}
QScrollArea {{ background: transparent; border: none; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 0; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 0; }}
QScrollBar::handle {{ background: {PRESSED}; border-radius: 3px; margin: 2px; }}
QScrollBar::handle:vertical {{ min-height: 24px; }}
QScrollBar::handle:horizontal {{ min-width: 24px; }}
QScrollBar::handle:hover {{ background: #4a4a46; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: none; }}
QTreeWidget, QTableView {{ background: {BASE}; color: {TEXT}; border: none; border-radius: 6px; outline: 0; }}
QTableView {{ alternate-background-color: #1c1c1b; gridline-color: transparent;
             selection-background-color: {SELECT}; selection-color: {TEXT}; }}
QTreeWidget::item {{ padding: 3px 2px; }}
QTreeWidget::item:selected {{ background: {SELECT}; color: {TEXT}; }}
QTreeWidget::item:hover:!selected {{ background: {HOVER}; }}
QHeaderView::section {{ background: {BASE}; color: {TEXT_3}; border: none; border-bottom: 1px solid {BORDER};
                        padding: 4px 8px; }}
QTableCornerButton::section {{ background: {BASE}; border: none; }}
QTabWidget::pane {{ border: none; top: 0px; }}
QTabWidget::tab-bar {{ left: 6px; }}
QTabBar {{ background: transparent; }}
QTabBar::tab {{ background: transparent; color: {TEXT_3}; border: none; border-bottom: 2px solid transparent;
                border-top-left-radius: 6px; border-top-right-radius: 6px; padding: 5px 14px; margin: 0 2px 0 0; }}
QTabBar::tab:selected {{ color: {TEXT}; background: {RAISED}; border-bottom-color: {ACCENT}; margin: 0 2px 0 0; }}
QTabBar::tab:!selected {{ margin: 0 2px 0 0; }}
QTabBar::tab:hover:!selected {{ color: {TEXT_2}; background: {HOVER}; }}
QSlider::groove:horizontal {{ height: 4px; background: {PRESSED}; border-radius: 2px; }}
QSlider::sub-page:horizontal {{ background: {ACCENT}; border-radius: 2px; }}
QSlider::handle:horizontal {{ background: {TEXT}; width: 14px; height: 14px; margin: -5px 0; border-radius: 7px; }}
QSlider::handle:horizontal:hover {{ background: #ffffff; }}
QMenu {{ background: {RAISED}; color: {TEXT}; border: 1px solid {FIELD_EDGE}; padding: 4px; }}
QMenu::separator {{ height: 1px; background: {FIELD_EDGE}; margin: 5px 10px; }}
QMenu::item {{ padding: 5px 18px; border-radius: 4px; }}
QMenu::item:selected {{ background: {SELECT}; }}
QLineEdit, QAbstractSpinBox, QComboBox {{ background: {FIELD}; color: {TEXT}; border: 1px solid {FIELD_EDGE};
                                         border-radius: 5px; padding: 3px 6px; selection-background-color: {SELECT}; }}
QLineEdit:focus, QAbstractSpinBox:focus, QComboBox:focus, QComboBox:on {{ border-color: {ACCENT}; }}
QLineEdit:disabled, QAbstractSpinBox:disabled, QComboBox:disabled {{ color: {TEXT_3}; border-color: {BORDER}; background: {RAISED}; }}
QComboBox {{ padding-right: 22px; }}
QComboBox::drop-down {{ subcontrol-origin: padding; subcontrol-position: center right; width: 20px; border: none;
                       background: transparent; }}
QComboBox::down-arrow {{ image: url("{_ICONS}/down.svg"); width: 12px; height: 12px; }}
QComboBox::down-arrow:disabled {{ image: url("{_ICONS}/down_disabled.svg"); }}
QAbstractSpinBox::up-button, QAbstractSpinBox::down-button {{ subcontrol-origin: border; width: 18px; border: none;
                                                            background: transparent; }}
QAbstractSpinBox::up-arrow {{ image: url("{_ICONS}/up.svg"); width: 10px; height: 10px; }}
QAbstractSpinBox::down-arrow {{ image: url("{_ICONS}/down.svg"); width: 10px; height: 10px; }}
QFrame#csnNumber {{ background: {FIELD}; border: 1px solid {FIELD_EDGE}; border-radius: 5px; }}
QFrame#csnNumber[focused="true"] {{ border-color: {ACCENT}; }}
QFrame#csnNumber:disabled {{ background: {RAISED}; border-color: {BORDER}; }}
QLineEdit#csnNumberText {{ background: transparent; border: none; padding: 0; margin: 0; color: {TEXT}; }}
QLineEdit#csnNumberText:disabled {{ color: {TEXT_3}; background: transparent; }}
QAbstractItemView QLineEdit {{ background: {BASE}; border: 1px solid {ACCENT}; border-radius: 3px; padding: 0 3px;
                              margin: 0; }}
QLineEdit#csnInline {{ background: {BASE}; color: {TEXT}; border: none; border-bottom: 1px solid {ACCENT};
                     border-radius: 0; padding: 0; margin: 0; }}
QComboBox QAbstractItemView {{ background: {FIELD}; color: {TEXT}; border: 1px solid {FIELD_EDGE}; outline: 0;
                              selection-background-color: {SELECT}; selection-color: {TEXT}; padding: 2px; }}
QPushButton {{ background: {FIELD}; color: {TEXT}; border: 1px solid {FIELD_EDGE}; border-radius: 6px; padding: 5px 12px; }}
QPushButton:hover {{ background: #393935; }}
QPushButton:pressed, QPushButton:checked {{ background: {SELECT}; border-color: {ACCENT}; }}
QPushButton:disabled {{ color: {TEXT_3}; border-color: {BORDER}; background: {RAISED}; }}
QPushButton[csnHighlight="true"] {{ background: {ACCENT}; border-color: {ACCENT}; color: #ffffff; font-weight: 600; }}
QSlider::handle:horizontal:disabled {{ background: {TEXT_3}; }}
QSlider::sub-page:horizontal:disabled {{ background: #4a4945; }}
QProgressBar {{ background: {BASE}; border: none; border-radius: 3px; max-height: 6px; min-height: 6px; }}
QProgressBar::chunk {{ background: {ACCENT}; border-radius: 3px; }}
QToolTip {{ background: {RAISED}; color: {TEXT}; border: 1px solid {BORDER}; padding: 4px 6px; }}
"""


class _Style(QtWidgets.QProxyStyle):
    """Fusion, with its tick boxes drawn crisp and in the theme's colours."""

    def drawPrimitive(self, element, option, painter, widget=None):
        kinds = QtWidgets.QStyle.PrimitiveElement
        if element in (kinds.PE_IndicatorCheckBox, kinds.PE_IndicatorItemViewItemCheck):
            self._tick_box(option, painter)
        elif element == kinds.PE_IndicatorToolBarHandle:
            self._grip(option, painter)
        else:
            super().drawPrimitive(element, option, painter, widget)

    @staticmethod
    def _grip(option, painter):
        """The toolbar's handle, to drag it to another side: six dots."""
        rect = QtCore.QRectF(option.rect)
        across = bool(option.state & QtWidgets.QStyle.StateFlag.State_Horizontal)
        columns, rows = (2, 3) if across else (3, 2)
        gap = 4.0
        left = rect.center().x() - gap * (columns - 1) / 2
        top = rect.center().y() - gap * (rows - 1) / 2
        painter.save()
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        painter.setPen(QtCore.Qt.PenStyle.NoPen)
        painter.setBrush(QtGui.QColor(TEXT_3))
        for column in range(columns):
            for row in range(rows):
                painter.drawEllipse(QtCore.QPointF(left + column * gap, top + row * gap), 1.1, 1.1)
        painter.restore()

    @staticmethod
    def _tick_box(option, painter):
        rect = QtCore.QRectF(option.rect)
        side = min(rect.width(), rect.height(), 16.0) - 2
        box = QtCore.QRectF(0, 0, side, side)
        box.moveCenter(rect.center())
        on = bool(option.state & QtWidgets.QStyle.StateFlag.State_On)
        painter.save()
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        if on:
            painter.setPen(QtCore.Qt.PenStyle.NoPen)
            painter.setBrush(QtGui.QColor(ACCENT))
            painter.drawRoundedRect(box, 3.5, 3.5)
            pen = QtGui.QPen(QtGui.QColor('#ffffff'), 1.8)
            pen.setCapStyle(QtCore.Qt.PenCapStyle.RoundCap)
            pen.setJoinStyle(QtCore.Qt.PenJoinStyle.RoundJoin)
            painter.setPen(pen)
            x, y, s = box.x(), box.y(), side
            painter.drawPolyline(QtGui.QPolygonF([QtCore.QPointF(x + 0.26 * s, y + 0.53 * s),
                                                  QtCore.QPointF(x + 0.44 * s, y + 0.71 * s),
                                                  QtCore.QPointF(x + 0.76 * s, y + 0.31 * s)]))
        else:
            painter.setPen(QtGui.QPen(QtGui.QColor('#5c5b56'), 1.2))
            painter.setBrush(QtGui.QColor(BASE))
            painter.drawRoundedRect(box.adjusted(0.5, 0.5, -0.5, -0.5), 3.5, 3.5)
        painter.restore()


def apply_qt(app):
    """The theme, once for the app. Before any toolbar exists: matplotlib's toolbar draws its icons
    light only when the palette it's made under is dark."""
    if app.property('csn_themed'):
        return
    app.setProperty('csn_themed', True)
    app._csn_style = _Style('Fusion')   # kept: Qt doesn't own a style set from Python
    app.setStyle(app._csn_style)
    hints = app.styleHints()
    if hasattr(hints, 'setColorScheme'):   # Qt 6.8+
        hints.setColorScheme(QtCore.Qt.ColorScheme.Dark)
    role, group = QtGui.QPalette.ColorRole, QtGui.QPalette.ColorGroup
    palette = QtGui.QPalette()
    for name, colour in (('Window', SURFACE), ('WindowText', TEXT), ('Base', FIELD), ('AlternateBase', '#1c1c1b'),
                         ('Text', TEXT), ('Button', FIELD), ('ButtonText', TEXT), ('BrightText', '#ffffff'),
                         ('Highlight', ACCENT), ('HighlightedText', '#ffffff'), ('ToolTipBase', RAISED),
                         ('ToolTipText', TEXT), ('PlaceholderText', TEXT_3), ('Link', ACCENT),
                         ('Light', PRESSED), ('Midlight', HOVER), ('Mid', BORDER), ('Dark', BASE), ('Shadow', '#000000')):
        palette.setColor(getattr(role, name), QtGui.QColor(colour))
    for name in ('WindowText', 'Text', 'ButtonText'):
        palette.setColor(group.Disabled, getattr(role, name), QtGui.QColor(TEXT_3))
    app.setPalette(palette)
    app.setStyleSheet(STYLESHEET)
    from ._widgets import WheelGuard   # here: _widgets draws in this module's colours
    app._csn_wheel = WheelGuard()   # the wheel over a value scrolls the panel, never changes it
    app._csn_windows = _Windows()   # the one filter on the whole app: every event of every widget goes by it
    app.installEventFilter(app._csn_windows)


class _Windows(QtCore.QObject):
    """Every window and dialog the app opens - matplotlib's too - with a dark title bar and a title
    (one without was titled "python"); the wheel kept off values (_widgets.WheelGuard); a click on a
    slider's track puts it there. `with _Windows.aside():` - off meanwhile."""

    TITLES = {}
    SHOW, WHEEL, PRESS = QtCore.QEvent.Type.Show, QtCore.QEvent.Type.Wheel, QtCore.QEvent.Type.MouseButtonPress
    _aside = 0

    def eventFilter(self, watched, event):
        kind = event.type()
        if kind == self.WHEEL:
            return QtWidgets.QApplication.instance()._csn_wheel.eventFilter(watched, event)
        if kind == self.PRESS and isinstance(watched, QtWidgets.QSlider):
            self._slider_press(watched, event)
        elif kind == self.SHOW and isinstance(watched, QtWidgets.QWidget) and watched.isWindow() \
                and not watched.property('csn_titled'):
            if watched.windowType() in (QtCore.Qt.WindowType.Window, QtCore.Qt.WindowType.Dialog):
                watched.setProperty('csn_titled', True)
                if not watched.windowTitle():
                    watched.setWindowTitle(self.TITLES.get(watched.objectName(), 'Plot'))
                dark_title_bar(watched)
        return False

    @staticmethod
    def _slider_press(slider, event):
        """Put where it's clicked, its handle under the pointer - the slider's own press then drags it from
        there. (Qt's way, a style hint, was asked of the style tens of thousands of times as a tab was made.)"""
        if event.button() != QtCore.Qt.MouseButton.LeftButton or not slider.isEnabled():
            return
        style, option = slider.style(), QtWidgets.QStyleOptionSlider()
        slider.initStyleOption(option)
        control, part = QtWidgets.QStyle.ComplexControl.CC_Slider, QtWidgets.QStyle.SubControl
        groove = style.subControlRect(control, option, part.SC_SliderGroove, slider)
        handle = style.subControlRect(control, option, part.SC_SliderHandle, slider)
        point = event.position().toPoint()
        if handle.contains(point):
            return
        if slider.orientation() == QtCore.Qt.Orientation.Horizontal:
            length, start, end, at = handle.width(), groove.x(), groove.right(), point.x()
        else:
            length, start, end, at = handle.height(), groove.y(), groove.bottom(), point.y()
        slider.setSliderPosition(QtWidgets.QStyle.sliderValueFromPosition(
            slider.minimum(), slider.maximum(), at - length // 2 - start, end - length + 1 - start,
            option.upsideDown))

    @classmethod
    def aside(cls):
        """The filter off while a tab's made: thousands of Qt's own events go by then, none of them its."""
        from contextlib import nullcontext   # here: the module's imports are its theme's
        return getattr(QtWidgets.QApplication.instance(), '_csn_windows', None) or nullcontext()

    def __enter__(self):
        self._aside += 1
        if self._aside == 1:
            QtWidgets.QApplication.instance().removeEventFilter(self)
        return self

    def __exit__(self, *exc):
        self._aside -= 1
        if self._aside == 0:
            QtWidgets.QApplication.instance().installEventFilter(self)


def dark_title_bar(window):
    """Windows' title bar dark (Windows 10 20H1+), and on Windows 11 the surface's own colour."""
    try:
        dwm = ctypes.WinDLL('dwmapi')
        hwnd = ctypes.c_void_p(int(window.winId()))
        on = ctypes.c_int(1)
        dwm.DwmSetWindowAttribute(hwnd, 20, ctypes.byref(on), ctypes.sizeof(on))   # DWMWA_USE_IMMERSIVE_DARK_MODE
        r, g, b = (int(SURFACE[i:i + 2], 16) for i in (1, 3, 5))
        caption = ctypes.c_uint32(r | g << 8 | b << 16)   # COLORREF: 0x00BBGGRR
        dwm.DwmSetWindowAttribute(hwnd, 35, ctypes.byref(caption), ctypes.sizeof(caption))   # DWMWA_CAPTION_COLOR
        r, g, b = (int(BORDER[i:i + 2], 16) for i in (1, 3, 5))
        edge = ctypes.c_uint32(r | g << 8 | b << 16)   # the window's 1px edge: not a light line on the dark
        dwm.DwmSetWindowAttribute(hwnd, 34, ctypes.byref(edge), ctypes.sizeof(edge))   # DWMWA_BORDER_COLOR
    except (OSError, AttributeError):
        pass
