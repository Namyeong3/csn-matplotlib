"""Sweeping a parameter: the small graph button beside each one in the Parameters tab. Clicked, the
run on the sliders is computed for STEPS values of that parameter, from the low end of its slider to
the high one - all of them first, in the run's own thread, with the turning circle and Stop - and
then played on the plots, one value after another, the slider following; then the plots go back to
the values on the sliders. The reference stays as it is all along. Right-clicked - or straight away
when it would be a lot to compute or to keep (ASK_POINTS, ASK_S) - it asks first: how many steps,
between which values, and whether to save each step as a PNG or SVG in a folder (named with the tab,
the step and the value). The other parameters stay as the sliders have them. Plots that fit their
data are fitted again at each step, and titles and labels the function sets follow each step. The
button again, a slider or a value touched, or a click or a key on the plot while it plays: it ends
there. Lines and scatters are played; copies of them in other plots keep their data."""
import math
import os
import re
import threading
import time

import numpy as np
from matplotlib.collections import PathCollection
from matplotlib.lines import Line2D
from PySide6 import QtCore, QtGui, QtWidgets

from . import _series, _sliders, _style, _view
from ._widgets import NumberField

Qt = QtCore.Qt
STEPS = 100
PLAY_MS = 4000             # all the steps played in about this long - each shown, however long it takes to draw
HOLD_MS = 800              # the last step, held before the plots go back
ASK_POINTS = 3_000_000     # steps of more points than this, all told: asked first
ASK_S = 15.0               # ... or taking longer than this to compute
MEMORY = 1_500_000_000     # bytes of steps kept at most, where the memory free can't be told: the sweep stops past it
_current = None            # the sweep going on (kept: Qt doesn't own it)


def button(pane, name):
    """The graph button for one parameter of the pane."""
    tool = QtWidgets.QToolButton()
    tool.setObjectName('csnSweep')
    tool.setIcon(_icon())
    tool.setIconSize(QtCore.QSize(18, 18))
    tool.setToolTip(f"Sweep {name}: compute every step from the low end of its slider to the high one, then "
                    f"play them on the plots. Right-click to choose the steps, the limits, or to save each step")
    tool.setCursor(Qt.CursorShape.PointingHandCursor)
    tool.clicked.connect(lambda: start(pane.parameters, name))
    tool.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
    tool.customContextMenuRequested.connect(lambda _: start(pane.parameters, name, ask=True))
    return tool


def _icon():
    """A small graph: two axes and a family of curves, each a step further."""
    pixmap = QtGui.QPixmap(36, 36)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QtGui.QPainter(pixmap)
    painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
    painter.setPen(QtGui.QPen(QtGui.QColor(_style.TEXT_3), 2.4))
    painter.drawLine(QtCore.QPointF(5, 4), QtCore.QPointF(5, 31))
    painter.drawLine(QtCore.QPointF(5, 31), QtCore.QPointF(32, 31))
    for k, alpha in ((0, 90), (1, 160), (2, 255)):
        colour = QtGui.QColor(_style.ACCENT)
        colour.setAlpha(alpha)
        painter.setPen(QtGui.QPen(colour, 2.4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        path = QtGui.QPainterPath(QtCore.QPointF(8, 27))
        path.cubicTo(QtCore.QPointF(15, 27 - 4 * k), QtCore.QPointF(20, 12 - 3 * k), QtCore.QPointF(31, 22 - 7 * k))
        painter.drawPath(path)
    painter.end()
    pixmap.setDevicePixelRatio(2.0)
    return QtGui.QIcon(pixmap)


def start(p, name, ask=False):
    """The sweep of that parameter: asked about first if asked for, or if it's a lot."""
    canvas = p.figure.canvas
    if _current is not None:   # a sweep's button again: it stops
        _current.cancel()
        return
    if p._job is not None:
        if canvas is not None:
            canvas.say('Wait for what is going on to finish, or stop it')
        return
    targets = _targets(p)
    if not targets:
        if canvas is not None:
            canvas.say('Nothing to sweep: this run has no lines or scatters')
        return
    low, high = p.ranges[name]
    plan = {'steps': STEPS, 'low': low, 'high': high, 'folder': '', 'format': None}
    points = sum(_length(artist) for artist, *_ in targets)
    heavy = points * STEPS > ASK_POINTS or p._computed * STEPS > ASK_S
    if ask or heavy:
        dialog = _Ask(p, name, plan, points, heavy)
        if dialog.exec() != QtWidgets.QDialog.DialogCode.Accepted:
            return
        plan = dialog.plan()
    values = _values(p, name, plan)
    if len(values) < 2:
        if canvas is not None:
            canvas.say('A sweep needs at least two different values')
        return
    _Sweep(p, name, values, plan, targets).compute()


def _values(p, name, plan):
    steps, low, high = max(int(plan['steps']), 2), plan['low'], plan['high']
    if p.log[name] and low > 0 and high > 0:
        values = np.geomspace(low, high, steps)
    else:
        values = np.linspace(low, high, steps)
    if p.whole[name]:
        values = list(dict.fromkeys(int(round(v)) for v in values))
    return [p._cast(name, v) for v in values]


def _kind(artist):
    ax = getattr(artist, 'axes', None)
    if ax is None:
        return None
    if isinstance(artist, Line2D) and artist.get_transform() is ax.transData:
        return 'line'
    if isinstance(artist, PathCollection) and len(artist.get_offsets()):
        return 'scatter'
    return None


def _length(artist):
    return len(artist.get_xdata(orig=True)) if isinstance(artist, Line2D) else len(artist.get_offsets())


def _data(artist):
    if isinstance(artist, Line2D):
        return np.array(artist.get_xdata(orig=True), copy=True), np.array(artist.get_ydata(orig=True), copy=True)
    return np.array(artist.get_offsets(), copy=True)


def _put(artist, data):
    if isinstance(artist, Line2D):
        artist.set_data(*data)
    else:
        artist.set_offsets(data)


def _targets(p):
    """What's played: [(artist, the axes the function draws it in, its name there, its kind)] - the
    original run's own lines and scatters, or a saved run's series."""
    found = []
    if p.active == _sliders.LIVE:
        for artist in p._drawn:
            kind = _kind(artist)
            if kind is not None:
                found.append((artist, artist.axes, artist.get_label(), kind))
    else:
        for entry in _view.entries(p.active):
            s = _view.series_of_entry(entry['id'])
            home = _series.axes_of(entry.get('origin', entry['axes']))
            kind = _kind(s.artist) if s is not None else None
            if kind is not None and home is not None:
                found.append((s.artist, home, entry.get('source', s.label), kind))
    return found


def _bytes(frame):
    return sum(sum(a.nbytes for a in (data if isinstance(data, tuple) else (data,)))
               for items in frame.values() for _, _, data in items)


def _file_name(tab, number, name, value, extension):
    text = f"{tab} {number:03d} {name}={_sliders._short(value)}.{extension}"
    return re.sub(r'[<>:"/\\|?*]', '_', text)


class _StepJob(_sliders._Job):
    """The sweep, as a run: how far it's got over all its steps."""

    def __init__(self, target, values, steps):
        super().__init__(target, values)
        self.steps, self.step = steps, 0

    def report(self, done, total=None):
        try:
            inner = float(done) / float(total) if total else float(done)
        except (TypeError, ValueError, ZeroDivisionError):
            inner = 0.0
        if not math.isfinite(inner):
            inner = 0.0
        self.fraction = min(max((self.step + min(max(inner, 0.0), 1.0)) / self.steps, 0.0), 1.0)
        if self.stopping:
            raise _sliders.Stopped()


class _Sweep(QtCore.QObject):
    computed = QtCore.Signal()   # from the run's thread, to the window's
    MEMORY_SHARE = 0.6           # of the memory free as it starts: the most a sweep's steps keep

    @staticmethod
    def memory():
        """(bytes free, bytes in all) of the computer's memory - None if it can't be told."""
        try:
            import psutil   # here: only if it's installed
            found = psutil.virtual_memory()
        except Exception:
            return None
        return found.available, found.total

    @staticmethod
    def amount(size):
        return f"{size / 1e9:,.1f} GB" if size >= 1e9 else f"{size / 1e6:,.0f} MB"

    def _projected(self, sizes):
        """Bytes all the steps would keep: each in between the first and the last as its value is."""
        first, last = float(self.values[0]), float(self.values[-1])
        a, b = sizes[0], sizes[len(self.values) - 1]
        return sum(a + (b - a) * ((float(v) - first) / (last - first) if last != first else 0.0) for v in self.values)

    def _too_much(self, size, memory, limit, what):
        share = f" ({self.MEMORY_SHARE:.0%} of the {self.amount(memory[0])} free)" if memory else ''
        fits = int(len(self.values) * limit / size) if size else len(self.values)
        then = f"About {fits} steps would fit, or a narrower range" if fits >= 2 else 'Not even two steps would fit'
        error = MemoryError(f"{what} take about {self.amount(size)} to keep, more than the {self.amount(limit)} a "
                            f"sweep may{share}. {then}")
        error.plain = True   # said as it is: no traceback, it's nothing in the function
        return error

    def __init__(self, p, name, values, plan, targets):
        super().__init__()
        self.p, self.name, self.values, self.plan, self.targets = p, name, values, plan, targets
        self.frames = []   # [(value, {axes: [(name, kind, data)]}, [(text, its text)])]
        self.computed.connect(self._computed)
        self._playing = self._done = self._stopped = False
        self._index = 0
        self._connections = []
        self._watched = []
        self.originals, self.texts, self.views = [], [], {}

    # ---- every step computed, first

    def compute(self):
        global _current
        _current = self
        p = self.p
        job = self.job = _StepJob(p.active, p.shown, len(self.values))
        _series.quiet()
        p._job = job
        p._busy(job)
        if p.figure.canvas is not None:
            p.figure.canvas.say(f"Computing {len(self.values)} steps of {self.name}…")
        self._watch()
        job.thread = threading.Thread(target=self._work, name='csn_matplotlib sweep', daemon=True)
        job.thread.start()

    def _watch(self):
        """The sliders and values of the pane: one touched, the sweep stops."""
        for controls in self.p.pane.controls.values():
            for widget in controls:
                for each in [widget, *widget.findChildren(QtWidgets.QWidget)]:
                    each.installEventFilter(self)
                    self._watched.append(each)

    def _unwatch(self):
        for widget in self._watched:
            try:
                widget.removeEventFilter(self)
            except RuntimeError:   # gone meanwhile
                pass
        self._watched = []

    def cancel(self):
        """Stopped from outside: while computing, as Stop does; while saving or playing, it ends there."""
        if self._done:
            return
        if self._playing:
            self.end()
        elif self.p._job is self.job:
            self.p.stop()
        else:
            self._stopped = True   # saving: at the next step

    def _work(self):
        p, job = self.p, self.job
        _sliders._here.job = job
        count = len(self.values)
        kept, sizes, frames = 0, {}, {}
        order = [0, count - 1, *range(1, count - 1)] if count > 2 else list(range(count))   # the ends first: from
        memory = self.memory()                                                           # them, what all would take
        limit = self.MEMORY_SHARE * memory[0] if memory else MEMORY
        try:
            for done, step in enumerate(order):
                value = self.values[step]
                if job.stopping:
                    raise _sliders.Stopped()
                job.step, job.fraction = done, done / count
                arguments = dict(job.values)
                arguments[self.name] = value
                if p._wants_progress:
                    arguments['progress'] = job.report
                before = {id(thing) for thing in p._everything()}
                snapshot = p._snapshot(job.target)
                for ax, places in p._cycles.items():   # the same colours each step
                    for cycle_name, place in zip(p._CYCLES, places):
                        cycle = getattr(ax, cycle_name, None)
                        if cycle is not None and place is not None:
                            cycle._idx = place
                new = []
                try:
                    job.inside = True
                    try:
                        p.draw(**arguments)
                    finally:
                        job.inside = False
                    new = [thing for thing in p._everything() if id(thing) not in before
                           and getattr(thing, '_csn_added', None) is None
                           and not (hasattr(thing, 'get_gid') and thing.get_gid() == _series.OURS)]
                    frame = {}
                    for thing in new:
                        if _kind(thing) is not None:
                            frame.setdefault(thing.axes, []).append((thing.get_label(), _kind(thing), _data(thing)))
                    texts = [(text, text.get_text()) for text, _ in snapshot['texts']]
                finally:
                    p._remove(new)
                    p._restore(snapshot)
                sizes[step] = _bytes(frame)
                kept += sizes[step]
                frames[step] = (value, frame, texts)
                if done == 1 and count > 2:   # the first and the last: before the rest's computed, whether they'd fit
                    projected = self._projected(sizes)
                    if projected > limit:
                        raise self._too_much(projected, memory, limit, f"its {count} steps would")
                if kept > limit:
                    raise self._too_much(kept, memory, limit, f"the {done + 1} steps so far")
            self.frames = [frames[step] for step in range(count)]
            job.fraction = 1.0
        except BaseException as caught:   # stopped, failed: the plots stay as they were
            job.error = caught
        finally:
            _sliders._here.job = None
            self.computed.emit()

    def _computed(self):
        global _current
        p, job = self.p, self.job
        job.thread.join()
        p._job = None
        p._busy(None)
        canvas = p.figure.canvas
        for each in p._canvases():
            each.draw_idle()
        if job.error is not None or not self.frames:
            _current = None
            self._done = True
            self._unwatch()
            if canvas is not None:
                stopped = isinstance(job.error, _sliders.Stopped)
                if job.error is not None and not stopped and not getattr(job.error, 'plain', False):
                    import traceback   # here: only a failed sweep prints one
                    traceback.print_exception(job.error)   # the function's own error: all of it, in the terminal
                canvas.say('Sweep stopped' if stopped else f"The sweep failed: {job.error}", error=not stopped)
            if p._pending:
                QtCore.QTimer.singleShot(0, p._start_pending)
            return
        self._match()
        self._keep()
        if self.plan.get('format') and self.plan.get('folder'):
            self._export(0)
        else:
            self._play()

    def _match(self):
        """Each played artist, to its place in the steps: by its name in its plot, else by its order."""
        first = self.frames[0][1]
        self.places = []
        taken = set()
        order = {}
        for artist, home, label, kind in self.targets:
            items = first.get(home, [])
            place = order[home] = order.get(home, -1) + 1
            index = next((i for i, (n, k, _) in enumerate(items) if n == label and k == kind
                          and (home, i) not in taken), None)
            if index is None and place < len(items) and items[place][1] == kind and (home, place) not in taken:
                index = place
            if index is not None:
                taken.add((home, index))
                self.places.append((artist, home, index))

    def _keep(self):
        """What's to be put back after: the data, the texts, each plot's view."""
        self.originals = [(artist, _data(artist)) for artist, _, _ in self.places]
        self.texts = [(text, text.get_text()) for text, _ in self.frames[0][2]]
        axes = list(dict.fromkeys(artist.axes for artist, _, _ in self.places if artist.axes is not None))
        self.views = {ax: (ax._get_view(), ax.get_autoscalex_on(), ax.get_autoscaley_on()) for ax in axes}

    def _show(self, index):
        value, frame, texts = self.frames[index]
        for artist, home, place in self.places:
            items = frame.get(home, [])
            if place < len(items):
                _put(artist, items[place][2])
        for text, words in texts:
            text.set_text(words)
        for ax in self.views:   # fitted to this step (and the reference), where it fits its data
            try:
                _series.fit(ax)
            except (ValueError, OverflowError):
                _series.safe_limits(ax)
        pane = self.p.pane
        slider, box, _, _ = pane.controls[self.name]
        for widget, setter in ((slider, lambda: slider.setValue(pane._position(self.name, value))),
                               (box, lambda: box.setValue(value))):
            widget.blockSignals(True)
            setter()
            widget.blockSignals(False)

    # ---- saved, each step

    def _export(self, index):
        canvases = self.p._canvases()
        figures = list(dict.fromkeys(artist.figure for artist, _, _ in self.places if artist.figure is not None))
        if self._stopped:
            for canvas in canvases:
                canvas.busy_veil.leave()
            self.end()
            return
        if index >= len(self.frames):
            for canvas in canvases:
                canvas.busy_veil.leave()
            canvases[0].say(f"{len(self.frames)} steps saved in {self.plan['folder']}") if canvases else None
            self._play()
            return
        for canvas in canvases:
            canvas.busy_veil.show_over(f"Saving step {index + 1} of {len(self.frames)}", stoppable=False)
        self._show(index)
        extension = self.plan['format']
        try:
            os.makedirs(self.plan['folder'], exist_ok=True)
            for figure in figures:
                tab = _series.tab_name(figure)
                figure.savefig(os.path.join(self.plan['folder'], _file_name(tab, index + 1, self.name,
                                                                            self.frames[index][0], extension)),
                               format=extension)
        except (OSError, ValueError) as error:
            for number, canvas in enumerate(canvases):
                canvas.busy_veil.leave()
                canvas.say(f"Couldn't save the steps: {error}", error=number == 0)   # printed once
            self._play()
            return
        QtCore.QTimer.singleShot(0, lambda: self._export(index + 1))   # the window's turn between two

    # ---- played

    def _play(self):
        self._playing = True
        self._index = 0
        for canvas in self.p._canvases():
            self._connections.append((canvas, canvas.mpl_connect('draw_event', self._drawn)))
            canvas.installEventFilter(self)
        self._step()

    def _step(self):
        if not self._playing:
            return
        self._show(self._index)
        self._waiting = True
        self._shown_at = time.perf_counter()
        for canvas in self.p._canvases():
            canvas.draw_idle()

    def _drawn(self, event):
        if self._playing and self._waiting:
            self._waiting = False
            took = (time.perf_counter() - self._shown_at) * 1000
            QtCore.QTimer.singleShot(int(max(PLAY_MS / len(self.frames) - took, 0)), self._next)

    def _next(self):
        if not self._playing:
            return
        self._index += 1
        if self._index < len(self.frames):
            self._step()
        else:
            QtCore.QTimer.singleShot(HOLD_MS, self.end)

    def eventFilter(self, watched, event):
        kind = event.type()
        touched = kind in (QtCore.QEvent.Type.MouseButtonPress, QtCore.QEvent.Type.KeyPress)
        if touched or (kind == QtCore.QEvent.Type.Wheel and watched in self._watched):
            if self._playing or watched in self._watched:   # the plot while it plays; the sliders all along
                self.cancel()
        return False

    def end(self):
        """The plots back as the sliders have them."""
        global _current
        if self._done:
            return
        self._done = True
        self._playing = False
        self._unwatch()
        for canvas, connection in self._connections:
            canvas.mpl_disconnect(connection)
            canvas.removeEventFilter(self)
        self._connections = []
        for artist, data in self.originals:
            _put(artist, data)
        for text, words in self.texts:
            text.set_text(words)
        for ax, (view, fit_x, fit_y) in self.views.items():
            ax._set_view(view)
            ax.set_autoscalex_on(fit_x)
            ax.set_autoscaley_on(fit_y)
        self.p.pane.show_values()
        for canvas in self.p._canvases():
            canvas.draw_idle()
        _current = None
        if self.p._pending:
            QtCore.QTimer.singleShot(0, self.p._start_pending)


class _Ask(QtWidgets.QDialog):
    """How many steps, between which values, and whether to save each one."""

    def __init__(self, p, name, plan, points, heavy):
        super().__init__(p.figure.canvas.window() if p.figure.canvas is not None else None)
        self.setWindowTitle(f"Sweep {name}")
        self.p, self.name, self.points, self.heavy = p, name, points, heavy
        self.steps = NumberField(whole=True)
        self.steps.setValue(plan['steps'])
        self.low = NumberField(whole=p.whole[name])
        self.low.setValue(plan['low'])
        self.high = NumberField(whole=p.whole[name])
        self.high.setValue(plan['high'])
        for field in (self.steps, self.low, self.high):
            field.setFixedWidth(130)
        for field in (self.steps, self.low, self.high):
            field.valueChanged.connect(lambda _: self._estimate())
            field.text.textEdited.connect(lambda _: self._estimate())   # as it's typed, not only once it's in
        self.estimate = QtWidgets.QLabel()
        self.estimate.setObjectName('csnError' if heavy else 'csnHint')
        self.estimate.setWordWrap(True)
        self.save = QtWidgets.QCheckBox('Also save each step as a picture')
        self.format = QtWidgets.QComboBox()
        self.format.addItem('PNG', 'png')
        self.format.addItem('SVG', 'svg')
        script = getattr(_sliders.store, 'script', None)
        self.folder = QtWidgets.QLineEdit(os.path.join(os.path.dirname(script) if script else os.getcwd(),
                                                       f"{name} sweep"))
        browse = QtWidgets.QPushButton('Choose…')
        browse.clicked.connect(self._browse)
        where = QtWidgets.QHBoxLayout()
        where.addWidget(self.folder, 1)
        where.addWidget(browse)
        self.saving = QtWidgets.QWidget()
        saving = QtWidgets.QFormLayout(self.saving)
        saving.setContentsMargins(0, 0, 0, 0)
        saving.addRow('In', where)
        saving.addRow('As', self.format)
        self.saving.setEnabled(False)
        self.save.toggled.connect(self.saving.setEnabled)
        form = QtWidgets.QFormLayout()
        form.setHorizontalSpacing(12)
        form.addRow('Steps', self.steps)
        form.addRow('From', self.low)
        form.addRow('To', self.high)
        cancel = QtWidgets.QPushButton('Cancel')
        cancel.clicked.connect(self.reject)
        go = QtWidgets.QPushButton('Compute')
        go.setDefault(True)
        go.clicked.connect(self.accept)
        buttons = QtWidgets.QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(cancel)
        buttons.addWidget(go)
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 16)
        layout.setSpacing(12)
        layout.addLayout(form)
        layout.addWidget(self.estimate)
        layout.addWidget(self.save)
        layout.addWidget(self.saving)
        layout.addLayout(buttons)
        self.setMinimumWidth(440)
        self._estimate()

    def _estimate(self):
        """No guess at what the steps take - the parameter may change how many points each has: the memory
        free, and the first and last steps computed first, to measure it, before the rest."""
        memory = _Sweep.memory()
        if memory:
            free = f"{_Sweep.amount(memory[0])} of memory free, of {_Sweep.amount(memory[1])}"
            limit = _Sweep.amount(memory[0] * _Sweep.MEMORY_SHARE)
        else:
            free, limit = "How much memory is free can't be told here", _Sweep.amount(MEMORY)
        lead = 'This may take long to compute, or a lot of memory to keep. ' if self.heavy else ''
        try:
            steps = max(int(float(self.steps.text.text().replace(',', '').replace(' ', ''))), 2)
        except ValueError:
            steps = max(int(self.steps.value() or 2), 2)
        self.estimate.setText(f"{lead}{free}. All {steps:,} steps are computed first and "
                              f"kept, then played: the first and the last are computed before the rest, and if all of "
                              f"them would take more than {limit}, it stops there.")

    def _browse(self):
        folder = QtWidgets.QFileDialog.getExistingDirectory(self, 'Save the steps in', self.folder.text())
        if folder:
            self.folder.setText(folder)

    def plan(self):
        low, high = self.low.value(), self.high.value()
        return {'steps': max(int(self.steps.value() or STEPS), 2), 'low': low, 'high': high,
                'folder': self.folder.text().strip() if self.save.isChecked() else '',
                'format': self.format.currentData() if self.save.isChecked() else None}
