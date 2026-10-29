"""The terminal under the plots: what's printed - stdout and stderr, by the script, a run's thread,
a warning - shown there as well as where it goes anyway (install(), at import: what's printed before
the window opens is there too). Under it a Python prompt, in the script's own namespace (its variables,
plt, np...), as python's own: '...' while a block goes on, Up and Down for what was typed before, Tab
completes (or indents), Ctrl+L clears, Ctrl+C (nothing selected) drops what's typed, Esc empties the
line; the figures a command changes are drawn again after it, and one it makes opens in a tab. input()
and sys.stdin read from it too, once the window's open (before, the console): from the window's thread
it goes on meanwhile, from a run's thread the run waits (Stop still stops it); Ctrl+C interrupts. One for
the window: it moves into the tab in front, under its plots and beside its side panel
(CSNFigureManager), and the toolbar folds it open and shut (Alt+T, Ctrl+J) - open or shut in every tab
alike."""
import sys
import threading

from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtCore import Qt

from . import _style

KEPT = 5000          # lines kept - the oldest dropped
WAITING = 2_000_000  # characters printed and not shown yet, at most - the oldest dropped
FLUSH_MS = 60        # what's printed shown this often
HEIGHT = 220         # its height, opened - until it's dragged to another
state = {'shown': False, 'height': HEIGHT}


class _Sink:
    """What's been printed and not shown yet, from any thread."""

    def __init__(self):
        self._lock = threading.Lock()
        self._chunks, self._size = [], 0

    def add(self, text, error):
        if not text:
            return
        with self._lock:
            self._chunks.append((text, error))
            self._size += len(text)
            while self._size > WAITING and len(self._chunks) > 1:
                self._size -= len(self._chunks.pop(0)[0])

    def take(self):
        with self._lock:
            chunks, self._chunks, self._size = self._chunks, [], 0
        return chunks


_sink = _Sink()


class _Tee:
    """A stream (stdout, stderr) writing where it did, and to the terminal."""

    def __init__(self, stream, error):
        self._stream, self._error = stream, error

    def write(self, text):
        try:
            _sink.add(str(text), self._error)
        except Exception:   # the terminal is never why a print fails
            pass
        return self._stream.write(text) if self._stream is not None else len(text)

    def flush(self):
        if self._stream is not None:
            self._stream.flush()

    def __getattr__(self, name):   # everything else, the stream's own (encoding, buffer...)
        return getattr(self._stream, name)

    # ---- stdin (error None): read in the terminal once the window's open

    def _panel(self):
        """The terminal, where a line's read from - once the window's open, or in a run's thread - else
        None: the console, as before."""
        terminal = Terminal._one
        if self._error is not None or terminal is None:
            return None
        if threading.current_thread() is not threading.main_thread():
            return terminal
        return terminal if terminal.window().isVisible() else None

    def readline(self, size=-1):
        panel = self._panel()
        if panel is not None:
            return panel.read_line()
        return self._stream.readline(size) if self._stream is not None else ''

    def read(self, size=-1):   # in the terminal: a line, as there's no end to type
        panel = self._panel()
        if panel is not None:
            return panel.read_line()
        return self._stream.read(size) if self._stream is not None else ''

    def fileno(self):   # input() reads the console itself while stdin is one: not while the terminal's to
        if self._panel() is not None:
            import io   # here: only to say it isn't one
            raise io.UnsupportedOperation('fileno')
        return self._stream.fileno()

    def isatty(self):
        if self._panel() is not None:
            return False
        return self._stream.isatty() if self._stream is not None else False

    def __iter__(self):
        return self

    def __next__(self):
        line = self.readline()
        if not line:
            raise StopIteration
        return line


def install():
    if not isinstance(sys.stdout, _Tee):
        sys.stdout = _Tee(sys.stdout, False)
    if not isinstance(sys.stderr, _Tee):
        sys.stderr = _Tee(sys.stderr, True)
    if not isinstance(sys.stdin, _Tee):
        sys.stdin = _Tee(sys.stdin, None)


class Terminal(QtWidgets.QWidget):
    """The window's one terminal: what's printed, as it's printed - errors in red."""

    _one = None
    _asked = QtCore.Signal(object)   # a line wanted in a run's thread: to the window's

    @classmethod
    def get(cls):
        if cls._one is None:
            cls._one = cls()
        return cls._one

    def __init__(self):
        super().__init__()
        self.setObjectName('csnTerminal')
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        self.setStyleSheet(f"QWidget#csnTerminal {{ background: {_style.BASE}; border-top: 1px solid {_style.BORDER}; }}")
        title = QtWidgets.QLabel('Terminal')
        title.setObjectName('csnHint')
        import __main__, os   # here: the script running, whose names the prompt has
        script = getattr(__main__, '__file__', None)
        where = f"{os.path.basename(script)}'s namespace" if script else '__main__'
        python = QtWidgets.QLabel(f"Python {sys.version_info.major}.{sys.version_info.minor}  ·  {where}")
        python.setStyleSheet(f"color: {_style.TEXT_3}; background: transparent;")
        clear = QtWidgets.QToolButton()
        clear.setText('Clear')
        clear.setAutoRaise(True)
        clear.setToolTip('Clear what is shown here (what was printed to the console stays there)')
        clear.clicked.connect(lambda: self.text.clear())
        top = QtWidgets.QHBoxLayout()
        top.setContentsMargins(12, 4, 8, 0)
        top.setSpacing(10)
        top.addWidget(title)
        top.addWidget(python)
        top.addStretch(1)
        top.addWidget(clear)
        self.text = QtWidgets.QPlainTextEdit()
        self.text.setReadOnly(True)
        self.text.setMaximumBlockCount(KEPT)
        self.text.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        self.text.setUndoRedoEnabled(False)
        font = QtGui.QFontDatabase.systemFont(QtGui.QFontDatabase.SystemFont.FixedFont)
        font.setPointSizeF(9.5)
        self.text.setFont(font)
        self.text.setStyleSheet(f"QPlainTextEdit {{ background: {_style.BASE}; color: {_style.TEXT_2};"
                                f" padding: 2px 8px; }}")
        self._plain, self._error = QtGui.QTextCharFormat(), QtGui.QTextCharFormat()
        self._plain.setForeground(QtGui.QColor(_style.TEXT_2))
        self._error.setForeground(QtGui.QColor('#e66767'))
        self._typed, self._quiet = QtGui.QTextCharFormat(), QtGui.QTextCharFormat()
        self._typed.setForeground(QtGui.QColor(_style.TEXT))
        self._quiet.setForeground(QtGui.QColor(_style.TEXT_3))
        self.prompt = QtWidgets.QLabel('>>>')
        self.prompt.setFont(font)
        self.prompt.setStyleSheet(f"color: {_style.ACCENT}; background: transparent;")
        self.input = QtWidgets.QLineEdit()
        self.input.setFont(font)
        self.input.setFrame(False)
        self.input.setStyleSheet(f"QLineEdit {{ background: {_style.BASE}; color: {_style.TEXT}; border: none;"
                                 f" padding: 2px 4px; }}")
        self.input.installEventFilter(self)
        self.input.returnPressed.connect(self._enter)
        self._history, self._back, self._draft = [], 0, ''   # what was typed; how far back Up's gone
        self._console, self._more = None, False
        self._waiters = []   # input()s waiting for a line, first first
        self._asked.connect(self._ask)
        line = QtWidgets.QHBoxLayout()
        line.setContentsMargins(10, 0, 8, 4)
        line.setSpacing(4)
        line.addWidget(self.prompt)
        line.addWidget(self.input, 1)
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addLayout(top)
        layout.addWidget(self.text, 1)
        layout.addLayout(line)
        self.setMinimumHeight(1)   # so it can fold smoothly
        self._timer = QtCore.QTimer(self)
        self._timer.setInterval(FLUSH_MS)
        self._timer.timeout.connect(self._flush)
        self._timer.start()
        self._flush()

    def _flush(self):
        chunks = _sink.take()
        if not chunks:
            return
        merged = []   # one insert for each run of the same stream
        for text, error in chunks:
            if merged and merged[-1][1] == error:
                merged[-1][0].append(text)
            else:
                merged.append(([text], error))
        bar = self.text.verticalScrollBar()
        following = bar.value() >= bar.maximum() - 2   # at the end: it stays at the end
        cursor = QtGui.QTextCursor(self.text.document())
        cursor.movePosition(QtGui.QTextCursor.MoveOperation.End)
        for parts, error in merged:
            look = self._error if error else self._plain
            pieces = ''.join(parts).replace('\r\n', '\n').split('\r')
            cursor.insertText(pieces[0], look)
            for piece in pieces[1:]:   # a carriage return: that line written over (a progress count)
                cursor.movePosition(QtGui.QTextCursor.MoveOperation.StartOfBlock,
                                    QtGui.QTextCursor.MoveMode.KeepAnchor)
                cursor.removeSelectedText()
                cursor.insertText(piece, look)
        if following:
            bar.setValue(bar.maximum())

    # ---- the prompt

    def _shell(self):
        if self._console is None:
            import __main__   # here: the script's namespace, only once something's typed
            import code
            self._console = code.InteractiveConsole(__main__.__dict__, filename='<terminal>')
        return self._console

    def _echo(self, text, look):
        """Shown here alone, after what's been printed so far - at the end, wherever it was scrolled."""
        self._flush()
        cursor = QtGui.QTextCursor(self.text.document())
        cursor.movePosition(QtGui.QTextCursor.MoveOperation.End)
        cursor.insertText(text, look)
        bar = self.text.verticalScrollBar()
        bar.setValue(bar.maximum())

    def _enter(self):
        line = self.input.text()
        self.input.clear()
        waiting = [w for w in self._waiters if not w['gone']]
        if waiting:   # the script's input(): the line's its
            self._echo(line + '\n', self._typed)
            self._answer(waiting[0], line)
            return
        if line.strip() and (not self._history or self._history[-1] != line):
            self._history.append(line)
        self._back, self._draft = 0, ''
        self._echo(f"{self.prompt.text()} {line}\n", self._typed)
        from . import _series   # here: the series module is the window's, made after this one
        _series.quiet()   # a figure being drawn in the background: finished before the command changes it
        try:
            more = self._shell().push(line)
        except SystemExit:   # exit() or quit(): the window stays - closing it ends the script
            self._shell().resetbuffer()
            more = False
            self._echo('The window stays open: close it to end the script.\n', self._quiet)
        self._more = more
        self._show_prompt()
        self._flush()
        self.text.verticalScrollBar().setValue(self.text.verticalScrollBar().maximum())
        if not more:
            self._redraw()

    @staticmethod
    def _redraw():
        """After a command: the figures it changed drawn again, one it made opened in a tab."""
        from matplotlib._pylab_helpers import Gcf
        for manager in Gcf.get_all_fig_managers():
            if not getattr(manager, '_shown', True):
                manager.show()
            elif manager.canvas.figure.stale:
                manager.canvas.draw_idle()

    def _recall(self, step):
        """Up (1) and Down (-1): what was typed before - back down to what's being typed now."""
        if not self._history:
            return
        if self._back == 0:
            self._draft = self.input.text()
        self._back = min(max(self._back + step, 0), len(self._history))
        self.input.setText(self._history[-self._back] if self._back else self._draft)

    def _complete(self):
        """Tab: the name before the cursor completed as far as it's the only way it goes - the ways it
        could go listed above. Where there's no name, an indent."""
        import os
        import re
        import rlcompleter
        text, at = self.input.text(), self.input.cursorPosition()
        word = re.search(r'[\w.]*$', text[:at]).group()
        if not word:
            self.input.insert('    ')
            return
        completer = rlcompleter.Completer(self._shell().locals)
        found = []
        for state in range(1000):
            try:
                match = completer.complete(word, state)
            except Exception:   # a name that can't be looked into
                break
            if match is None:
                break
            if match not in found:
                found.append(match)
        if not found:
            return
        common = os.path.commonprefix(found)
        if len(common) > len(word):
            self.input.insert(common[len(word):])
        if len(found) > 1:
            names = sorted({match[len(word) - len(word.rpartition('.')[2]):] for match in found})
            shown = '  '.join(names[:80]) + (f"  ... and {len(names) - 80} more" if len(names) > 80 else '')
            self._echo(shown + '\n', self._quiet)

    def eventFilter(self, watched, event):
        """The prompt's keys: its own, before the window's shortcuts or a move to the next field."""
        kinds = QtCore.QEvent.Type
        if watched is not self.input or event.type() not in (kinds.KeyPress, kinds.ShortcutOverride):
            return False
        key = event.key()
        ctrl = bool(event.modifiers() & Qt.KeyboardModifier.ControlModifier)
        if event.type() == kinds.ShortcutOverride:
            if key in (Qt.Key.Key_Tab, Qt.Key.Key_Up, Qt.Key.Key_Down, Qt.Key.Key_Escape) or \
                    (ctrl and key in (Qt.Key.Key_L, Qt.Key.Key_C)):
                event.accept()
            return False
        if key == Qt.Key.Key_Tab and not ctrl:
            self._complete()
        elif key in (Qt.Key.Key_Up, Qt.Key.Key_Down):
            self._recall(1 if key == Qt.Key.Key_Up else -1)
        elif key == Qt.Key.Key_Escape:
            self.input.clear()
            self._back = 0
        elif ctrl and key == Qt.Key.Key_L:
            self.text.clear()
        elif ctrl and key == Qt.Key.Key_C and not self.input.hasSelectedText() and \
                any(not w['gone'] for w in self._waiters):   # input() waiting: interrupted, as in a console
            self._echo(f"{self.input.text()}^C\n", self._typed)
            self.input.clear()
            self._answer(next(w for w in self._waiters if not w['gone']), KeyboardInterrupt)
        elif ctrl and key == Qt.Key.Key_C and not self.input.hasSelectedText():   # as python's: dropped
            self._echo(f"{self.prompt.text()} {self.input.text()}\n", self._typed)
            self._echo('KeyboardInterrupt\n', self._error)
            self._shell().resetbuffer()
            self._more = False
            self._show_prompt()
            self.input.clear()
            self._back = 0
        else:
            return False
        return True

    def focus_prompt(self):
        self.input.setFocus()

    def _show_prompt(self):
        waiting = any(not w['gone'] for w in self._waiters)
        self.prompt.setText('→' if waiting else '...' if self._more else '>>>')

    # ---- input() and sys.stdin, once the window's open

    def read_line(self):
        """A line typed here, for input() or sys.stdin: in the window's thread, its events go on meanwhile;
        in a run's, the run waits - Stop still stops it. '' once the window's gone."""
        waiter = {'event': threading.Event(), 'line': None, 'gone': False, 'loop': None}
        if threading.current_thread() is threading.main_thread():
            waiter['loop'] = QtCore.QEventLoop()
            self._ask(waiter)
            if not waiter['event'].is_set():
                waiter['loop'].exec()   # till it's answered - or the window closes
            waiter['gone'] = True
            self._show_prompt()
        else:
            from . import _sliders   # here: the run in this thread, to be stopped
            job = getattr(_sliders._here, 'job', None)
            self._asked.emit(waiter)
            while not waiter['event'].wait(0.1):
                if job is not None and job.stopping:
                    waiter['gone'] = True
                    self._asked.emit(None)   # the prompt as it was
                    raise _sliders.Stopped()
        line = waiter['line']
        if line is KeyboardInterrupt:
            raise KeyboardInterrupt
        return '' if line is None else line + '\n'

    def _ask(self, waiter):
        """In the window's thread: a line wanted - the terminal opened, the cursor in it."""
        if waiter is not None:
            self._waiters.append(waiter)
        self._waiters = [w for w in self._waiters if not w['gone']]
        self._show_prompt()
        if self._waiters:
            from matplotlib._pylab_helpers import Gcf   # here: the tab in front has the terminal
            action = getattr(Gcf.get_active(), 'terminal_action', None)
            if action is not None and not action.isChecked():
                action.setChecked(True)
            self.input.setFocus()

    def _answer(self, waiter, line):
        waiter['line'], waiter['gone'] = line, True
        waiter['event'].set()
        if waiter['loop'] is not None:
            waiter['loop'].quit()
        self._ask(None)
