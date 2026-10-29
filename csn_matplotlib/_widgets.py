"""Small widgets the window is made of: a folding section, a splitter whose edge is easy to catch,
the arrow bubble a sideways swipe brings in, a label's red flash that fades, the turning circle
(and the veil over a plot) while a run computes or a large figure is drawn, the short note (Toast)
an action leaves on the plot, a number field with arrows to nudge it (NumberField), WheelGuard (the
mouse wheel over a drop-down, a slider or a number scrolls the panel, never changes the value) and
InlineDelegate: a row renamed in place without its name cropped."""
import math
import os

import numpy as np
from PySide6 import QtCore, QtGui, QtWidgets

from . import _style

Qt = QtCore.Qt


class Section(QtWidgets.QWidget):
    """A titled part of a panel that folds away - its title with an arrow, over what's in it."""

    def __init__(self, title, body, opened=True):
        super().__init__()
        self.body = body
        self.toggle = QtWidgets.QToolButton()
        self.toggle.setObjectName('csnSection')
        self.toggle.setText(title)
        self.toggle.setCheckable(True)
        self.toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.toggle.toggled.connect(self._folded)
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        layout.addWidget(self.toggle)
        layout.addWidget(body, 1)
        self._layout, self._stretch = None, 0
        self.toggle.setChecked(opened)
        self._folded(opened)

    def place(self, layout, stretch=0):
        """Into the panel's layout; a stretching section gives its room back while folded."""
        self._layout, self._stretch = layout, stretch
        layout.addWidget(self, stretch if self.toggle.isChecked() else 0)

    def _folded(self, opened):
        self.toggle.setArrowType(Qt.ArrowType.DownArrow if opened else Qt.ArrowType.RightArrow)
        self.body.setVisible(opened)
        if self._layout is not None:
            self._layout.setStretchFactor(self, self._stretch if opened else 0)


class Splitter(QtWidgets.QSplitter):
    """A splitter whose edge is HANDLE px wide to catch, drawn as a 1px line (the accent, hovered)."""

    HANDLE = 8

    def __init__(self, orientation):
        super().__init__(orientation)
        self.setHandleWidth(self.HANDLE)

    def createHandle(self):
        return _Handle(self.orientation(), self)


class _Handle(QtWidgets.QSplitterHandle):
    def __init__(self, orientation, parent):
        super().__init__(orientation, parent)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover)

    def event(self, event):
        if event.type() in (QtCore.QEvent.Type.HoverEnter, QtCore.QEvent.Type.HoverLeave):
            self.update()
        return super().event(event)

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        painter.fillRect(self.rect(), QtGui.QColor(_style.SURFACE))   # all of it: nothing of what was there before
        colour = QtGui.QColor(_style.ACCENT if self.underMouse() else _style.BORDER)
        if self.orientation() == Qt.Orientation.Horizontal:
            painter.fillRect(self.width() // 2, 0, 1, self.height(), colour)
        else:
            painter.fillRect(0, self.height() // 2, self.width(), 1, colour)
        painter.end()


class Bubble(QtWidgets.QWidget):
    """The round arrow that comes in from the side as two fingers swipe sideways - back from the
    left, forward from the right - filled in once the swipe is far enough to go."""

    SIZE = 52
    TRAVEL = 84   # how far in it comes, a full swipe

    def __init__(self, parent):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.resize(self.SIZE, self.SIZE)
        self.hide()
        self.side, self.progress, self.possible = 'left', 0.0, True
        self._leaving = QtCore.QVariantAnimation(self)
        self._leaving.setDuration(180)
        self._leaving.setEasingCurve(QtCore.QEasingCurve.Type.InCubic)
        self._leaving.valueChanged.connect(self._left_by)
        self._leaving.finished.connect(self.hide)

    def show_at(self, side, progress, possible):
        self._leaving.stop()
        self.side, self.progress, self.possible = side, progress, possible
        self._place()
        self.show()
        self.raise_()
        self.update()

    def leave(self):
        if self.isVisible():
            self._leaving.setStartValue(float(self.progress))
            self._leaving.setEndValue(0.0)
            self._leaving.start()

    def _left_by(self, progress):
        self.progress = progress
        self._place()

    def _place(self):
        parent = self.parentWidget()
        reach = self.progress * self.TRAVEL
        x = -self.SIZE + reach if self.side == 'left' else parent.width() - reach
        self.move(int(x), (parent.height() - self.SIZE) // 2)

    def paintEvent(self, event):
        armed = self.progress >= 1.0 and self.possible
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        painter.setPen(QtGui.QPen(QtGui.QColor(_style.BORDER), 1))
        painter.setBrush(QtGui.QColor(_style.ACCENT if armed else _style.RAISED))
        painter.drawEllipse(QtCore.QRectF(1, 1, self.SIZE - 2, self.SIZE - 2))
        ink = '#ffffff' if armed else (_style.TEXT_2 if self.possible else _style.TEXT_3)
        pen = QtGui.QPen(QtGui.QColor(ink), 2.6)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        c, s = self.SIZE / 2, 9.0
        way = -1 if self.side == 'left' else 1
        painter.drawLine(QtCore.QPointF(c - way * s, c), QtCore.QPointF(c + way * s, c))
        painter.drawPolyline(QtGui.QPolygonF([QtCore.QPointF(c + way * (s - 6), c - 6), QtCore.QPointF(c + way * s, c),
                                              QtCore.QPointF(c + way * (s - 6), c + 6)]))
        painter.end()


def flash(widget, ms=2600):
    """The widget's text red, fading back to its own colour over ms - or at once, with unflash()."""
    unflash(widget)
    fade = QtCore.QVariantAnimation(widget)
    fade.setStartValue(QtGui.QColor('#e66767'))
    fade.setEndValue(QtGui.QColor(_style.TEXT_3))
    fade.setDuration(ms)
    fade.setEasingCurve(QtCore.QEasingCurve.Type.InQuad)   # red for a while, then fading
    fade.valueChanged.connect(lambda colour: widget.setStyleSheet(f"color: {colour.name()}"))
    fade.finished.connect(lambda: widget.setStyleSheet(''))
    widget._csn_flash = fade
    fade.start()


def unflash(widget):
    fade = getattr(widget, '_csn_flash', None)
    if fade is not None:
        fade.stop()
        widget._csn_flash = None
        widget.setStyleSheet('')


# ---- while a run computes

_FRAMES = []


def spinner_frames():
    """The turning circle's frames (64 px - drawn smaller, smoothly)."""
    if not _FRAMES:
        folder = os.path.join(os.path.dirname(__file__), 'spinner')
        for number in range(24):
            pixmap = QtGui.QPixmap(os.path.join(folder, f"{number}.png"))
            if not pixmap.isNull():
                _FRAMES.append(pixmap)
    return _FRAMES


def _draw_frame(painter, frame, rect):
    """The circle as far round as the clock says (frame unused): turning at its pace however seldom
    it's painted - never waiting on how far the work has got."""
    frames = spinner_frames()
    if frames:
        painter.setRenderHint(QtGui.QPainter.RenderHint.SmoothPixmapTransform)
        pixmap = frames[(QtCore.QDateTime.currentMSecsSinceEpoch() // 40) % len(frames)]
        painter.drawPixmap(rect, pixmap, QtCore.QRectF(pixmap.rect()))


class Spinner(QtWidgets.QWidget):
    FRAME_MS = 40

    def __init__(self, size=20, parent=None):
        super().__init__(parent)
        self.setFixedSize(size, size)
        self._frame = 0
        self._timer = QtCore.QTimer(self)
        self._timer.setInterval(self.FRAME_MS)
        self._timer.timeout.connect(self._turn)

    def showEvent(self, event):
        super().showEvent(event)
        self._timer.start()

    def hideEvent(self, event):
        super().hideEvent(event)
        self._timer.stop()

    def _turn(self):
        self._frame += 1
        self.update()

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        _draw_frame(painter, self._frame, QtCore.QRectF(self.rect()))
        painter.end()


class BusyVeil(QtWidgets.QWidget):
    """Over a plot while a run computes or a large figure is drawn: the plot dimmed, the circle turning,
    what it's doing and how far it's got (when the function says), and Stop (a run only). Takes the
    mouse: the plot waits until it's drawn again."""

    SIZE = 48
    FRAME_MS = 40

    def __init__(self, parent):
        super().__init__(parent)
        self.fraction = None
        self.text = 'Computing'
        self._frame = 0
        self._timer = QtCore.QTimer(self)
        self._timer.setInterval(self.FRAME_MS)
        self._timer.timeout.connect(self._turn)
        self.stop_button = QtWidgets.QPushButton('Stop', self)
        self.stop_button.setToolTip('Stop this run (Esc). The plot keeps the previous completed run.')
        self.stop_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.hide()

    def show_over(self, text='Computing', stoppable=True):
        self.text, self.fraction = text, None
        self.stop_button.setVisible(stoppable)
        self.setGeometry(self.parentWidget().rect())
        self.show()
        self.raise_()
        self._timer.start()
        self.update()

    def leave(self):
        self._timer.stop()
        self.hide()

    def _turn(self):
        self._frame += 1
        self.update()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        hint = self.stop_button.sizeHint()
        self.stop_button.setGeometry((self.width() - hint.width()) // 2, self.height() // 2 + self.SIZE // 2 + 36,
                                     hint.width(), hint.height())

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        veil = QtGui.QColor(_style.SURFACE)
        veil.setAlpha(150)
        painter.fillRect(self.rect(), veil)
        centre = QtCore.QPointF(self.width() / 2, self.height() / 2)
        _draw_frame(painter, self._frame, QtCore.QRectF(centre.x() - self.SIZE / 2, centre.y() - self.SIZE / 2,
                                                         self.SIZE, self.SIZE))
        text = self.text if self.fraction is None else f"{self.text}  {self.fraction * 100:.0f}%"
        painter.setPen(QtGui.QColor(_style.TEXT_2))
        painter.drawText(QtCore.QRectF(0, centre.y() + self.SIZE / 2 + 8, self.width(), 22),
                         int(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop), text)
        painter.end()

    def mousePressEvent(self, event):
        event.accept()

    def mouseReleaseEvent(self, event):
        event.accept()

    def mouseDoubleClickEvent(self, event):
        event.accept()

    def wheelEvent(self, event):
        event.accept()


class Toast(QtWidgets.QLabel):
    """A short note at the bottom left of the plot - what an action did, or why it didn't - fading
    away after a few seconds. Doesn't take the mouse."""

    SHOWN_MS = 3500
    FADE_MS = 400

    def __init__(self, parent):
        super().__init__(parent)
        self.setObjectName('csnToast')
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setWordWrap(True)
        self._opacity = QtWidgets.QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self._opacity)
        self._wait = QtCore.QTimer(self)
        self._wait.setSingleShot(True)
        self._wait.timeout.connect(self._fade_out)
        self._fade = QtCore.QPropertyAnimation(self._opacity, b'opacity', self)
        self._fade.setDuration(self.FADE_MS)
        self._fade.finished.connect(self._faded)
        self.hide()

    def say(self, text, ms=None):
        self._fade.stop()
        self.setText(text)
        parent = self.parentWidget()
        self.setMaximumWidth(max(min(parent.width() - 32, 640), 160))
        self.adjustSize()
        self.move(16, parent.height() - self.height() - 16)
        self._opacity.setOpacity(1.0)
        self.show()
        self.raise_()
        self._wait.start(ms or self.SHOWN_MS)

    def _fade_out(self):
        self._fade.setStartValue(1.0)
        self._fade.setEndValue(0.0)
        self._fade.start()

    def _faded(self):
        if self._opacity.opacity() <= 0.01:
            self.hide()


def chevron(painter, rect, way, colour, width=1.5):
    """A small arrow head in the rectangle: way 1 up, -1 down, 0 right."""
    painter.save()
    painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
    pen = QtGui.QPen(QtGui.QColor(colour), width)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    c = QtCore.QRectF(rect).center()
    r = min(rect.width(), rect.height()) * 0.28
    point = QtCore.QPointF
    if way == 0:
        shape = [point(c.x() - r * 0.5, c.y() - r), point(c.x() + r * 0.5, c.y()), point(c.x() - r * 0.5, c.y() + r)]
    else:
        h = r * 0.55 * (-1 if way > 0 else 1)
        shape = [point(c.x() - r, c.y() - h), point(c.x(), c.y() + h), point(c.x() + r, c.y() - h)]
    painter.drawPolyline(QtGui.QPolygonF(shape))
    painter.restore()


class _Nudge(QtWidgets.QAbstractButton):
    """One of a number field's arrows - held, it goes on."""

    def __init__(self, way, parent):
        super().__init__(parent)
        self.way = way
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setAutoRepeat(True)
        self.setAutoRepeatDelay(350)
        self.setAutoRepeatInterval(60)
        self.setFixedSize(18, 11)
        self.setCursor(Qt.CursorShape.ArrowCursor)
        self.setToolTip('Up (or the Up key)' if way > 0 else 'Down (or the Down key)')

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        if self.isEnabled() and (self.underMouse() or self.isDown()):
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QtGui.QColor(_style.PRESSED if self.isDown() else _style.HOVER))
            painter.drawRoundedRect(QtCore.QRectF(self.rect()).adjusted(1, 0.5, -1, -0.5), 3, 3)
        colour = _style.TEXT if self.isEnabled() and self.underMouse() else \
            _style.TEXT_2 if self.isEnabled() else _style.TEXT_3
        chevron(painter, QtCore.QRectF(self.rect()), self.way, colour, 1.4)
        painter.end()

    def enterEvent(self, event):
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.update()
        super().leaveEvent(event)


def number_text(value, whole=False, digits=6):
    """A number as a field shows it: whole, or to digits significant figures - never 1e+06 for a
    million, an exponent only for the very large or small."""
    if value is None:
        return ''
    if not np.isfinite(value):
        return str(value)
    if whole:
        return f"{int(round(value)):d}"
    if value == 0:
        return '0'
    if 1e-4 <= abs(value) < 1e12:
        return np.format_float_positional(float(value), precision=digits, unique=False, fractional=False, trim='-')
    mantissa, exponent = f"{value:.{max(digits - 1, 1)}e}".split('e')
    if '.' in mantissa:
        mantissa = mantissa.rstrip('0').rstrip('.')
    return f"{mantissa}e{int(exponent)}"


class NumberField(QtWidgets.QFrame):
    """A number to type, with arrows at its right that nudge it up and down (as do the Up and Down
    keys). valueChanged(value) once a value's typed (Enter, or clicking away) or nudged - not at each
    key. The wheel goes on to what it's in. stepper(value, way) gives the value one nudge away (way
    1 up, -1 down) - else it's step; clamp keeps it in its range."""

    valueChanged = QtCore.Signal(object)

    def __init__(self, whole=False, suffix='', parent=None):
        super().__init__(parent)
        self.setObjectName('csnNumber')
        self.whole, self.suffix = whole, suffix
        self.digits, self.step, self.stepper, self.clamp = 6, 1, None, False
        self._value, self._low, self._high = 0, -math.inf, math.inf
        self.text = QtWidgets.QLineEdit(self)
        self.text.setObjectName('csnNumberText')
        self.text.setFrame(False)
        self.text.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.text.editingFinished.connect(self._typed)
        self.text.installEventFilter(self)
        self.up, self.down = _Nudge(1, self), _Nudge(-1, self)
        self.up.clicked.connect(lambda: self.nudge(1))
        self.down.clicked.connect(lambda: self.nudge(-1))
        arrows = QtWidgets.QVBoxLayout()
        arrows.setContentsMargins(0, 0, 0, 0)
        arrows.setSpacing(0)
        arrows.addWidget(self.up)
        arrows.addWidget(self.down)
        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(6, 1, 2, 1)
        layout.setSpacing(2)
        layout.addWidget(self.text, 1)
        layout.addLayout(arrows)
        self.setFixedHeight(26)
        self.setFocusProxy(self.text)
        self._show()

    def value(self):
        return self._value

    def setValue(self, value):
        """Shown - without valueChanged."""
        self._value = int(round(value)) if self.whole else float(value)
        self._show()

    def setRange(self, low, high):
        self._low, self._high = low, high

    def setDigits(self, digits):
        self.digits = digits
        self._show()

    def setSuffix(self, suffix):
        self.suffix = suffix
        self._show()

    def _show(self):
        self.text.setText(number_text(self._value, self.whole, self.digits) + self.suffix)
        self.text.setCursorPosition(0)

    def _fit(self, value):
        if self.whole:
            value = int(round(value))
        if self.clamp:
            value = min(max(value, self._low), self._high)
        return value

    def _typed(self):
        text = self.text.text().strip()
        if self.suffix.strip() and text.endswith(self.suffix.strip()):
            text = text[:-len(self.suffix.strip())].strip()
        try:
            value = float(text.replace(',', '.'))
        except ValueError:
            self._show()   # not a number: the one before, again
            return
        if not np.isfinite(value):
            self._show()
            return
        value = self._fit(value)
        changed = value != self._value
        self._value = value
        self._show()
        if changed:
            self.valueChanged.emit(value)

    def nudge(self, way):
        if not self.isEnabled():
            return
        self._typed()   # a value half typed counts first
        value = self.stepper(self._value, way) if self.stepper is not None else self._value + way * self.step
        value = self._fit(value)
        if value != self._value:
            self._value = value
            self._show()
            self.valueChanged.emit(value)

    def eventFilter(self, watched, event):
        kind = event.type()
        if kind == QtCore.QEvent.Type.KeyPress and event.key() in (Qt.Key.Key_Up, Qt.Key.Key_Down):
            self.nudge(1 if event.key() == Qt.Key.Key_Up else -1)
            return True
        if kind in (QtCore.QEvent.Type.FocusIn, QtCore.QEvent.Type.FocusOut):
            self.setProperty('focused', kind == QtCore.QEvent.Type.FocusIn)
            self.style().unpolish(self)
            self.style().polish(self)
        return False


class WheelGuard(QtCore.QObject):
    """The wheel over a drop-down, a slider or a number field never changes it: it scrolls what
    they're in, as over anything else in a panel."""

    def eventFilter(self, watched, event):
        if event.type() != QtCore.QEvent.Type.Wheel or not isinstance(watched, QtWidgets.QWidget):
            return False
        guarded = isinstance(watched, (QtWidgets.QComboBox, QtWidgets.QAbstractSpinBox)) or (
            isinstance(watched, QtWidgets.QAbstractSlider) and not isinstance(watched, QtWidgets.QScrollBar))
        if not guarded:
            return False
        parent = watched.parentWidget()
        while parent is not None and not isinstance(parent, QtWidgets.QAbstractScrollArea):
            parent = parent.parentWidget()
        if parent is not None:
            QtWidgets.QApplication.sendEvent(parent.verticalScrollBar(), event)
        return True


class InlineDelegate(QtWidgets.QStyledItemDelegate):
    """A list's or tree's rows renamed in place by an entry that fits the row: no frame or padding to
    crop the name, the row's own height, an accent line under it. folder(index): whether the row
    folds (a plot's name in the data panel) - it gets an arrow at its right end, to fold it with."""

    ARROW_PX = 22

    def __init__(self, parent, folder=None):
        super().__init__(parent)
        self.folder = folder

    def createEditor(self, parent, option, index):
        editor = QtWidgets.QLineEdit(parent)
        editor.setObjectName('csnInline')
        editor.setFrame(False)
        editor.setTextMargins(0, 0, 0, 0)
        return editor

    def updateEditorGeometry(self, editor, option, index):
        super().updateEditorGeometry(editor, option, index)
        rect = editor.geometry()
        rect.setTop(option.rect.top() + 1)
        rect.setBottom(option.rect.bottom() - 1)
        if self.folder is not None and self.folder(index):
            rect.setRight(min(rect.right(), option.rect.right() - self.ARROW_PX))
        editor.setGeometry(rect)

    def paint(self, painter, option, index):
        super().paint(painter, option, index)
        if self.folder is not None and self.folder(index):
            view = self.parent()
            opened = view.isExpanded(index) if hasattr(view, 'isExpanded') else True
            row = QtCore.QRect(option.rect)
            row.setLeft(0)
            row.setRight(view.viewport().width() - 1 if hasattr(view, 'viewport') else row.right())
            rect = self.arrow_rect(row)
            hovered = bool(option.state & QtWidgets.QStyle.StateFlag.State_MouseOver)
            colour = _style.TEXT if hovered else _style.TEXT_3
            chevron(painter, QtCore.QRectF(rect), -1 if opened else 0, colour, 1.5)

    def arrow_rect(self, row):
        return QtCore.QRect(row.right() - self.ARROW_PX + 2, row.top(), self.ARROW_PX - 4, row.height())
