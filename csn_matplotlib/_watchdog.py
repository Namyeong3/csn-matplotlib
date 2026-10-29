"""Someone watching the window from outside. A small process of its own (this file, run as a script)
gets a beat from the window every BEAT_MS; if none comes for SILENT_S - the window's thread stuck in
one long draw or call, Windows about to call it not responding - it asks, in a window of its own:
keep waiting, stop what it's doing, or close the program. Stop is sent back to the program, where a
thread of its own stops any run, cancels any draw going on in the background and raises Stopped in
the window's thread at its next Python step (a single long numpy or drawing call finishes first).
Close ends the program from outside, which works however stuck it is; the view settings were only
ever saved once the window had come through, so nothing unsafe is kept. The watcher ends with the
program. Not started off-screen (tests): nobody's there to ask."""
import os
import subprocess
import sys
import threading
import time

BEAT_MS = 500
SILENT_S = 5.0
AGAIN_S = 10.0   # "Keep waiting": asked again after this much more silence

_child = None
_timer = None


# ---- in the program

def start():
    """The watcher started, once, with the window."""
    global _child, _timer
    if _child is not None or os.environ.get('QT_QPA_PLATFORM') == 'offscreen' or not sys.executable:
        return
    from PySide6 import QtCore
    try:
        _child = subprocess.Popen([sys.executable, os.path.abspath(__file__), str(os.getpid())],
                                  stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                  creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    except OSError:
        _child = None
        return
    _timer = QtCore.QTimer()
    _timer.setInterval(BEAT_MS)
    _timer.timeout.connect(_beat)
    _timer.start()
    threading.Thread(target=_listen, name='csn_matplotlib watchdog', daemon=True).start()


def _beat():
    try:
        _child.stdin.write(b'.')
        _child.stdin.flush()
    except (OSError, ValueError, AttributeError):   # the watcher's gone: nothing more to tell it
        if _timer is not None:
            _timer.stop()


def _listen():
    """In a thread of its own: what the watcher was told to do."""
    try:
        for line in _child.stdout:
            if line.strip() == b'stop':
                stop_everything()
    except (OSError, ValueError):
        pass


def stop_everything():
    """Every run stopped, every background draw cancelled, and the window's thread interrupted."""
    from . import _series, _sliders
    for parameters in list(_sliders._all):
        job = parameters._job
        if job is not None:
            parameters._interrupt(job)
    for figure in _series.figures():
        render = getattr(figure.canvas, '_render', None)
        if render is not None:
            render['cancel'] = True
    _sliders._raise_in(threading.main_thread(), _sliders.Stopped)
    print('csn_matplotlib: the window stopped answering - what it was doing has been stopped', file=sys.stderr)


# ---- the watcher (this file run as a script)

def _watch(pid):
    last = [time.monotonic()]
    alive = [True]

    def read():
        stream = sys.stdin.buffer
        while True:
            try:
                data = stream.read1(64)
            except (OSError, ValueError):
                data = b''
            if not data:   # the program's gone
                alive[0] = False
                return
            last[0] = time.monotonic()

    threading.Thread(target=read, daemon=True).start()
    asker = None
    quiet_until = 0.0
    while alive[0]:
        silent = time.monotonic() - last[0]
        if asker is None and silent > SILENT_S and time.monotonic() > quiet_until:
            asker = _Asker(pid)
        if asker is not None:
            if silent < 1.0:   # answering again: no need to ask
                asker.close()
                asker = None
            else:
                answer = asker.tick(silent)
                if answer == 'wait':
                    asker.close()
                    asker, quiet_until = None, time.monotonic() + AGAIN_S
                elif answer == 'stop':
                    try:
                        sys.stdout.write('stop\n')
                        sys.stdout.flush()
                    except (OSError, ValueError):
                        pass
                elif answer == 'close':
                    try:
                        import signal
                        os.kill(pid, signal.SIGTERM)   # Windows: TerminateProcess - stuck or not
                    except OSError:
                        pass
                    break
        time.sleep(0.03 if asker is not None else 0.25)
    try:   # ended at once: no Qt left to tidy up on the way out (that can fail, and say so in a box)
        import ctypes
        ctypes.windll.kernel32.TerminateProcess(ctypes.c_void_p(-1), 0)   # -1: this process
    except (AttributeError, OSError):
        pass
    os._exit(0)


class _Asker:
    """The question, in a dark window of its own - made only once there's something to ask."""

    def __init__(self, pid):
        from PySide6 import QtCore, QtGui, QtWidgets
        self.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        self.app.setStyle('Fusion')
        palette = QtGui.QPalette()
        for role, colour in (('Window', '#1a1a19'), ('WindowText', '#f0efec'), ('Base', '#30302d'),
                             ('Text', '#f0efec'), ('Button', '#30302d'), ('ButtonText', '#f0efec'),
                             ('Highlight', '#3987e5'), ('HighlightedText', '#ffffff')):
            palette.setColor(getattr(QtGui.QPalette.ColorRole, role), QtGui.QColor(colour))
        self.app.setPalette(palette)
        self.answer = None
        self.stopping = False
        window = self.window = QtWidgets.QWidget()
        window.setWindowTitle('Plot window not responding')
        window.setWindowFlag(QtCore.Qt.WindowType.WindowStaysOnTopHint)
        self.text = QtWidgets.QLabel()
        self.text.setWordWrap(True)
        self.text.setMinimumWidth(380)
        note = QtWidgets.QLabel('Stop interrupts what the window is doing (a single long calculation finishes '
                                'first). Close ends the program at once; view changes since the last save are lost.')
        note.setWordWrap(True)
        note.setStyleSheet('color: #8a897f')
        buttons = QtWidgets.QHBoxLayout()
        for label, answer in (('Keep waiting', 'wait'), ('Stop what it is doing', 'stop'), ('Close the program', 'close')):
            button = QtWidgets.QPushButton(label)
            button.clicked.connect(lambda _=False, a=answer: setattr(self, 'answer', a))
            buttons.addWidget(button)
            if answer == 'wait':
                button.setDefault(True)
                buttons.addStretch(1)
        layout = QtWidgets.QVBoxLayout(window)
        layout.setContentsMargins(20, 18, 20, 16)
        layout.setSpacing(12)
        layout.addWidget(self.text)
        layout.addWidget(note)
        layout.addLayout(buttons)
        self.tick(SILENT_S)
        window.show()
        _dark_title(window)
        window.raise_()
        window.activateWindow()

    def tick(self, silent):
        """The window kept up to date - and what was answered, once."""
        if self.answer == 'stop':
            self.stopping = True
        doing = 'Asked it to stop - waiting for it to answer.' if self.stopping else \
            'It may be drawing or computing something very large.'
        self.text.setText(f"The plot window hasn't answered for {silent:.0f} s. {doing}")
        self.app.processEvents()
        answer, self.answer = self.answer, None
        return answer

    def close(self):
        self.window.close()
        self.app.processEvents()


def _dark_title(window):
    try:
        import ctypes
        on = ctypes.c_int(1)
        ctypes.WinDLL('dwmapi').DwmSetWindowAttribute(ctypes.c_void_p(int(window.winId())), 20, ctypes.byref(on),
                                                      ctypes.sizeof(on))
    except (OSError, AttributeError):
        pass


if __name__ == '__main__':
    _watch(int(sys.argv[1]))
