"""Parameter sliders: a function that draws the plot from some parameters, and a slider for each in the
Parameters tab of the side panel. Moving one draws the plot again - while it's dragged, or when it's
let go - with the run it started from left as a faint shadow to compare against (the reference; Set
reference makes the current run it).

    def draw(b_0=1.0, r_0=0.1, steps=500):
        t, b, r = simulate(b_0, r_0, steps)
        ax_time.plot(t, b, label='prey')
        ...

    csn_matplotlib.sliders(draw, b_0=(0, 3), r_0=(0, 1), steps=(10, 2000))

The function draws into axes made outside it: it's called again and again, and a figure made inside
would be a new window each time. Each range is (low, high), or (low, high, 'log'); a parameter with
whole numbers for its default and range gets whole numbers. Under each slider its low and high can
be typed over, and a value typed past them takes them with it (the one moved flashes red).

Each run goes in a thread of its own, so the window doesn't stop while it computes: the plot shows a
turning circle, and Stop (or Esc) ends the run. A function that takes a `progress` parameter is given
one to call - progress(0.4) or progress(i, n) - and gets a progress bar; csn_matplotlib.progress() does
the same from anywhere inside the run. A run that fails or is stopped - an error, a MemoryError, too
long - says why, and the plot keeps the previous completed run; values only go into the settings
file once they've run and been drawn without trouble, so a value that brings Python down isn't there
next time. What a run drew is taken away when the next shows, every run starts from the same
colours, and axes that fit their data (not zoomed or panned) fit each new run's.

The original run is the one the script's own call draws. Save run keeps the run as series of their
own, named with what's typed, in colours of their own. Picking one of them - in the data panel, the
Plot tab, or by clicking it on the plot - puts its parameters on the sliders: moving them runs it
again (the original run stays as it was) - unless it's locked, when they're greyed out and Save run
makes an unlocked copy. A copy of a series in another plot counts as the series itself.
The sliders follow the plots that depend on them - those the function draws in, those holding its
saved runs or copies of its series: a tab's Parameters tab has every set of sliders its plots need,
each headed by the plots using it (hovered, they're outlined on the plot). Values, ranges and the
two ticks go into the settings file; every change can be undone."""
import ctypes
import inspect
import math
import os
import threading
import time
import uuid

import numpy as np
from PySide6 import QtCore, QtGui, QtWidgets
from matplotlib.collections import PathCollection
from matplotlib.lines import Line2D

from . import _series, _style, _view
from ._history import history
from ._settings import figure_key, store
from ._widgets import NumberField, Spinner, flash, unflash

Qt = QtCore.Qt
LIVE = 'live'       # the original run: what the script's own call draws - the others are saved runs
_owners = {}        # owner key -> its Parameters: whose a saved run's series are
_all = []           # every Parameters, in the order they were made
_here = threading.local()   # the run going on in this thread, for progress()


class Stopped(BaseException):
    """Raised inside a run that's been stopped. A BaseException, so an `except Exception` in the
    function lets it through."""


def progress(done, total=None):
    """How far the run the sliders started has got - progress(0.4), or progress(i, n) - shown as a bar
    under the sliders and on the plot. Raises Stopped in a run that's been stopped (let it through).
    Outside a run it does nothing."""
    job = getattr(_here, 'job', None)
    if job is not None:
        job.report(done, total)


def sliders(draw, figure=None, buttons=None, **ranges):
    """Sliders for draw's parameters (name=(low, high) each; name=True, False or bool: a tick box, on or
    off - bool: as the function's default says) in the figure's window - the current figure's, if
    none is given - and buttons, {'Label': function} or [function, ...]: each called with the values it
    names (a dict it gives back goes onto the sliders, and is drawn). Draws it once the window opens.
    Gives the Parameters: .values, .run()."""
    import matplotlib.pyplot as plt
    figure = figure if figure is not None else plt.gcf()
    manager = figure.canvas.manager
    if not hasattr(manager, 'add_parameters'):
        raise RuntimeError("sliders() needs csn_matplotlib's window: import csn_matplotlib before making the figure")
    parameters = Parameters(draw, figure, ranges, buttons)
    manager.add_parameters(parameters)
    manager.when_shown(parameters.run)
    return parameters


def needed_by(figure):
    """The sets of sliders the figure's plots depend on."""
    return [p for p in _all if any(ax.figure is figure for ax in p.plots())]


def run_of(s):
    """(Parameters, run) a series was drawn by - the original run, or a saved one - or None. A copy
    is of the run its source is."""
    run = getattr(s.artist, '_csn_run', None)
    if run is None:
        source = _view.source_of(s)
        return run_of(source) if source is not None and source.artist is not s.artist else None
    if run == LIVE:
        owner = getattr(s.artist, '_csn_owner', None)
        return (owner, LIVE) if owner is not None else None
    entry = next(iter(_view.entries(run)), None)
    owner = _owners.get(entry.get('owner')) if entry is not None else None
    return (owner, run) if owner is not None else None


def select(s):
    """A series picked - in a panel, or clicked on the plot: the sliders show the run it's from. Gives
    the Parameters, or None."""
    found = run_of(s) if s is not None else None
    if found is not None:
        found[0].activate(found[1])
        return found[0]
    return None


def run_series(s):
    """Every series of the run this one's from - itself alone, if it's from none."""
    found = run_of(s)
    return found[0].series_of_run(found[1]) if found is not None else [s]


class _Job:
    """One run: its values, how far it's got, and how it ended."""

    def __init__(self, target, values):
        self.target, self.values = target, dict(values)
        self.fraction = None   # None: the function hasn't said how far it's got
        self.stopping = self.inside = self.handled = self.interrupted = False
        self.error = None
        self.started = time.perf_counter()
        self.took = 0.0
        self.before, self.snapshot, self.thread = set(), None, None

    def report(self, done, total=None):
        try:
            fraction = float(done) / float(total) if total else float(done)
        except (TypeError, ValueError, ZeroDivisionError):
            fraction = None
        if fraction is not None and math.isfinite(fraction):
            self.fraction = min(max(fraction, 0.0), 1.0)
        if self.stopping:
            raise Stopped()


class _Mailbox(QtCore.QObject):
    finished = QtCore.Signal(object)   # from the run's thread, to the window's


def _raise_in(thread, kind):
    """kind raised in the thread at its next Python step (a long numpy call finishes first)."""
    ident = getattr(thread, 'ident', None)
    if ident is None:
        return
    count = ctypes.pythonapi.PyThreadState_SetAsyncExc(ctypes.c_ulong(ident), ctypes.py_object(kind))
    if count > 1:
        ctypes.pythonapi.PyThreadState_SetAsyncExc(ctypes.c_ulong(ident), None)


class Parameters:
    REFERENCE_ALPHA = 0.3
    REFERENCE_LINE_AT = 2000   # a series of more points: its reference is a line, not markers - seen however dense
    SLOW_S = 1.0               # a run still going this long when the sliders move on is stopped for the newer one
    LIVE_S = 0.5               # a first run this long to compute and draw: not updated live, unless that's chosen
    INTERRUPT_MS = 300         # a stopped run that hasn't called progress() since is interrupted after this
    STUCK_MS = 4000            # still going this long after Stop: it can only be quit
    _CYCLES = ('_get_lines', '_get_patches_for_fill')   # where an axes keeps its place in the colour cycle

    def __init__(self, draw, figure, ranges, buttons=None):
        self.draw, self.figure = draw, figure
        self.name = getattr(draw, '__name__', 'sliders')
        base = self.key = figure_key(figure)   # the first set of a figure's: its key, as it always was
        number = 2
        while self.key in _owners:
            self.key = f"{base}|{self.name}" + (f" {number - 1}" if number > 2 else '')
            number += 1
        self.slot = 'sliders' + self.key[len(base):]   # its part of the figure's settings
        _owners[self.key] = self
        _all.append(self)
        signature = inspect.signature(draw)
        unknown = [name for name in ranges if name not in signature.parameters]
        if unknown:
            raise TypeError(f"{draw.__name__}() has no parameter {', '.join(unknown)}")
        self._wants_progress = 'progress' in signature.parameters and 'progress' not in ranges
        self.ranges, self.defaults, self.whole, self.log = {}, {}, {}, {}
        self.toggles = {}          # the tick boxes: name -> on or off, by default
        self.order = list(ranges)  # sliders and tick boxes, in the order given
        if isinstance(buttons, dict):
            self.actions = list(buttons.items())
        else:   # functions alone: named after themselves
            self.actions = [(getattr(f, '__name__', 'Run').replace('_', ' ').strip().capitalize() or 'Run', f)
                            for f in (buttons or [])]
        for name, spec in ranges.items():
            if spec is bool or isinstance(spec, bool):   # on or off
                given = signature.parameters[name].default
                on = spec if isinstance(spec, bool) else given if isinstance(given, bool) else False
                self.toggles[name] = self.defaults[name] = bool(on)
                continue
            low, high, *rest = spec
            default = signature.parameters[name].default
            if default is inspect.Parameter.empty:
                default = low
            self.whole[name] = all(isinstance(v, int) and not isinstance(v, bool) for v in (default, low, high))
            self.log[name] = 'log' in rest
            if self.log[name] and min(low, high) <= 0:
                raise ValueError(f"{name}: a log range needs low and high above 0")
            self.ranges[name] = (min(low, high), max(low, high))
            self.defaults[name] = default
        self.default_ranges = dict(self.ranges)
        saved = store.section(figure).get(self.slot, {})
        self._live_auto = self._live_pending = 'live' not in saved   # Update live: by how heavy the first run is
        for name, bounds in saved.get('ranges', {}).items():
            if name in self.ranges and len(bounds) == 2:
                self.ranges[name] = tuple(self._cast(name, v) for v in bounds)
        self.values = {name: self._cast(name, saved.get('values', {}).get(name, self.defaults[name]))
                       for name in self.order}   # the original run's
        self.shown = self.values   # what the sliders show and change: the original run's, or a saved run's
        self.active = LIVE
        self._good = dict(self.values)    # the original run's last values that worked
        self._safe = dict(self.values)    # ... and were drawn: what the settings file gets
        self._unsaved = None
        self.axes = list(figure.axes)     # the plots it may draw in, whichever tab they're moved to
        self._drawn, self._reference = [], []
        self._copied = []   # the reference in the linked copies of the run's series (a duplicated plot's)
        self._ran = False
        self._cycles = {ax: tuple(getattr(getattr(ax, name, None), '_idx', None) for name in self._CYCLES)
                        for ax in self.axes}
        self._job, self._pending, self._reference_wanted = None, False, True
        self._mailbox = _Mailbox()
        self._mailbox.finished.connect(self._finished)
        self._computed, self._timing_wanted = 0.0, False
        self._said = None   # the last failed run's error, printed: the same one isn't again
        self._listening = set()   # the canvases told of their draws
        _view.on_reset.append(self._reset_hook)
        _view.on_shown.append(self._sync_reference)
        history.listeners.append(self._sync_reference)   # a plot duplicated, a copy taken away
        self.kept = len(self.saved_runs())
        self.pane = ParametersPane(self, saved)
        self.group = _Group(self)
        self._canvases()

    def _cast(self, name, value):
        if name in self.toggles:
            return bool(value)
        return int(round(value)) if self.whole[name] else float(value)

    def press(self, function):
        """A button of the script's: its function, given the values on the sliders it names (all of them,
        if it takes **values) - a dict it gives back put on the sliders, and drawn. An error it raises is
        printed, and said under the sliders; the window goes on."""
        try:
            wanted = inspect.signature(function).parameters
            every = any(w.kind == w.VAR_KEYWORD for w in wanted.values())
            given = function(**{name: value for name, value in self.shown.items() if every or name in wanted})
        except Exception as error:
            import traceback   # here: only this prints one
            traceback.print_exc()
            self.pane.show_error(error, f"{getattr(function, '__name__', 'The button')}() failed")
            return
        self.pane.show_error(None)
        changes = {}
        if isinstance(given, dict):
            changes = {name: self._cast(name, value) for name, value in given.items() if name in self.shown}
        if not changes or self.locked():
            return
        before = self.state()
        for name, value in changes.items():
            if name in self.ranges:   # past the range: the range goes with it
                low, high = self.ranges[name]
                self.ranges[name] = (min(low, value), max(high, value))
            self.shown[name] = value
        self.pane.show_values()
        self.record('Change parameters', before)
        self.run()

    def _canvases(self):
        """The canvases of the tabs its plots are in now (each told to say when it's drawn)."""
        figures = {ax.figure for ax in [*self.axes, *self.plots()] if ax.figure is not None} | {self.figure}
        found = [figure.canvas for figure in figures if figure.canvas is not None]
        for canvas in found:
            if id(canvas) not in self._listening:
                self._listening.add(id(canvas))
                canvas.mpl_connect('draw_event', self._drawn_now)
        return found

    def plots(self):
        """The plots that depend on these parameters: those its original run drew in, those holding a
        saved run of it, and those showing copies of either - before its first run, those of its figure."""
        found = [_view.main_of(t.axes) for t in self._drawn if getattr(t, 'axes', None) is not None]
        if not self._ran and not found:
            found = [_view.main_of(ax) for ax in self.axes if ax.figure is not None]
        runs = [LIVE, *self.saved_runs()]
        for run in runs:
            for s in self.series_of_run(run):
                found.extend(_view.main_of(m.ax) for m in (_series.members(s) or [s]))
        return [ax for ax in dict.fromkeys(found) if ax.figure is not None and ax in ax.figure.axes]

    def saved_runs(self):
        return list(dict.fromkeys(e['run'] for e in _view.entries() if e.get('owner') == self.key and e.get('run')))

    # ---- running, in a thread

    def run(self):
        """Draws the run on the sliders again, with the values on them."""
        job = self._job
        if job is not None:   # one at a time: the newest values once this one's done
            self._pending = True
            if time.perf_counter() - job.started > self.SLOW_S:
                self._stop(job)
            return
        self._start()

    def _start(self):
        self._pending = False
        _series.quiet()   # no figure drawn in the background while the run's thread changes it
        if self.active != LIVE and not _view.entries(self.active):   # its series deleted meanwhile
            self.activate(LIVE)
        job = _Job(self.active, self.shown)
        job.before = {id(thing) for thing in self._everything()}
        job.snapshot = self._snapshot(job.target)
        for ax, places in self._cycles.items():   # the same colours, run after run
            for name, place in zip(self._CYCLES, places):
                cycle = getattr(ax, name, None)
                if cycle is not None and place is not None:
                    cycle._idx = place
        self._job = job
        self._busy(job)
        job.thread = threading.Thread(target=self._work, args=(job,), name='csn_matplotlib run', daemon=True)
        job.thread.start()

    def _work(self, job):
        """In the run's own thread: the function, and whatever it raises kept - never let out."""
        _here.job = job
        try:
            try:
                arguments = dict(job.values)
                if self._wants_progress:
                    arguments['progress'] = job.report
                job.inside = True
                self.draw(**arguments)
            finally:
                job.inside = False
        except BaseException as caught:   # Stopped, MemoryError, anything: that run failed, the window goes on
            job.error = caught
        try:
            job.took = time.perf_counter() - job.started
            _here.job = None
        except Stopped:
            job.error = job.error or Stopped()
        try:
            self._mailbox.finished.emit(job)
        except Stopped:   # a stop sent as it finished: the job's taken once, however many times it's sent
            self._mailbox.finished.emit(job)

    def _finished(self, job):
        if job.handled:
            return
        job.handled = True
        self._job = None
        new = [thing for thing in self._everything() if id(thing) not in job.before
               and getattr(thing, '_csn_added', None) is None
               and not (hasattr(thing, 'get_gid') and thing.get_gid() == _series.OURS)]
        if job.error is None:
            if job.target == LIVE:
                self._take_live(job, new)
            else:
                self._take_saved(job, new)
        else:
            self._remove(new)
            self._restore(job.snapshot)
        self._ran = True
        self._busy(None)
        _view.reapply()
        self._sync_reference()
        for ax in self.axes:
            if ax.figure is not None:
                _series.fit(ax)
        if job.error is not None and not isinstance(job.error, Stopped):   # all of it in the terminal - the same
            said = (type(job.error), str(job.error))                         # one again (a slider dragged) once
            if said != self._said:
                import traceback   # here: only a failed run prints one
                traceback.print_exception(job.error)
            self._said = said
        elif job.error is None:
            self._said = None
        self.pane.show_error(job.error)
        self.pane.show_timing(job.took, None)
        self._computed, self._timing_wanted = job.took, True
        for canvas in self._canvases():
            canvas.draw_idle()
            changed = getattr(canvas.manager, 'parameters_changed', None)
            if changed is not None:   # its plots may be elsewhere now: the tab in front, with them or not
                changed()
        self.group.refresh()
        if self._pending:
            QtCore.QTimer.singleShot(0, self._start_pending)   # after the drawing that's just been asked for

    def _start_pending(self):
        if self._pending and self._job is None:
            self._start()

    def _take_live(self, job, new):
        self._remove(self._drawn)
        self._drawn = new
        for thing in new:
            try:
                thing._csn_run, thing._csn_owner = LIVE, self
            except AttributeError:
                pass
        self._good = dict(job.values)
        self._unsaved = dict(job.values)   # into the file once it's been drawn
        if self._reference_wanted:
            self._reference_wanted = False
            self.set_reference()

    def _take_saved(self, job, new):
        """A saved run run again: its series get the new data; what the function drew goes again. Each
        is matched to what the function drew in the plot it first drew it in (wherever it is now): by
        its name, where both have the same - else by its place among the run's series there, as an
        unnamed line has no name to go by (its made-up one changes with the axis labels)."""
        new_ids = {id(thing) for thing in new}
        made = {}
        for ax in dict.fromkeys(getattr(thing, 'axes', None) for thing in new):
            if ax is not None:
                drawn = [s for s in _series.series(ax) if id(s.artist) in new_ids and s.kind in ('line', 'scatter')]
                if drawn:
                    made[_series.ax_id(ax)] = drawn
        taken, places = set(), {}
        for entry in _view.entries(job.target):
            origin = entry.get('origin', entry['axes'])
            there = [s for s in made.get(origin, []) if id(s.artist) not in taken]
            place = places[origin] = places.get(origin, -1) + 1
            fresh = next((s for s in there if s.label == entry.get('source')), None)
            if fresh is None:
                ordered = made.get(origin, [])
                fresh = ordered[place] if place < len(ordered) and id(ordered[place].artist) not in taken else \
                    (there[0] if there else None)
            if fresh is None:
                continue
            taken.add(id(fresh.artist))
            x, y = fresh.floats()
            entry['x'], entry['y'] = np.array(x, dtype=float), np.array(y, dtype=float)
            entry['params'] = dict(job.values)
            s = _view.series_of_entry(entry['id'])
            if s is not None:
                if s.kind == 'line':
                    s.artist.set_data(x, y)
                else:
                    s.artist.set_offsets(np.column_stack([x, y]))
        self._remove(new)
        self._restore(job.snapshot)
        store.changed()

    def _snapshot(self, target):
        """What a run may change besides its series - put back if it fails, or when it's a saved run's."""
        snapshot = {'legends': {}, 'texts': [], 'views': {}, 'labels': []}
        for ax in self.axes:
            if ax.figure is None:
                continue
            snapshot['legends'][ax] = ax.get_legend()
            snapshot['texts'] += [(text, text.get_text()) for text in
                                  (ax.title, ax._left_title, ax._right_title, ax.xaxis.label, ax.yaxis.label)]
            snapshot['views'][ax] = ax._get_view()
        if target == LIVE:   # what this run replaces stays out of the legend it makes
            for thing in self._drawn:
                label = thing.get_label() if hasattr(thing, 'get_label') else None
                if label and not str(label).startswith('_'):
                    snapshot['labels'].append((thing, label))
                    thing.set_label('_csn_replaced')
        return snapshot

    @staticmethod
    def _restore(snapshot):
        for ax, legend in snapshot['legends'].items():
            ax.legend_ = legend
        for text, value in snapshot['texts']:
            text.set_text(value)
        for ax, view in snapshot['views'].items():
            ax._set_view(view)
        for thing, label in snapshot['labels']:
            thing.set_label(label)

    def _everything(self):
        """What the plots hold that a run could add: containers first - taking one away takes its parts."""
        axes = [ax for ax in self.axes if ax.figure is not None]
        figures = {ax.figure for ax in axes} | {self.figure}
        return [*(c for ax in axes for c in ax.containers), *(a for ax in axes for a in ax._children),
                *(t for f in figures for t in f.texts), *(g for f in figures for g in f.legends),
                *(line for f in figures for line in f.lines)]

    @staticmethod
    def _remove(things):
        for thing in things:
            try:
                thing.remove()
            except (ValueError, NotImplementedError, AttributeError):   # gone already, with its container
                pass

    def _busy(self, job):
        for canvas in self._canvases():
            if hasattr(canvas, 'set_computing'):
                canvas.set_computing(job, self)
        self.pane.set_busy(job)

    def stop(self):
        """Stop (or Esc): the run going on ends - the plot stays at the last values that worked."""
        self._pending = False
        if self._job is not None:
            self._stop(self._job, asked=True)

    def _stop(self, job, asked=False):
        if job.stopping:
            return
        job.stopping = True   # a function calling progress() stops at its next call
        QtCore.QTimer.singleShot(self.INTERRUPT_MS, lambda: self._interrupt(job))
        if asked:
            QtCore.QTimer.singleShot(self.STUCK_MS, lambda: self._stuck(job))

    def _interrupt(self, job):
        if not job.handled and job.inside and not job.interrupted:
            job.interrupted = True
            _raise_in(job.thread, Stopped)

    def _stuck(self, job):
        if not job.handled:
            self.pane.show_stuck()

    def _drawn_now(self, event):
        canvas = event.canvas
        if canvas.is_saving():
            return
        took = getattr(canvas, 'last_draw_s', None)   # the drawing itself - not a wait before it
        if self._live_pending and self._timing_wanted and took is not None:   # once a file's opened, not each run
            self._live_pending = False
            if self._computed + took > self.LIVE_S and self.pane.live.isChecked():
                self.pane.live.blockSignals(True)
                self.pane.live.setChecked(False)
                self.pane.live.blockSignals(False)
        if self._unsaved is not None:   # ran and drawn: safe to keep
            self._safe, self._unsaved = self._unsaved, None
            self.save()
        if self._timing_wanted and took is not None:
            self.pane.show_timing(self._computed, took)
            self._timing_wanted = False

    # ---- runs: the original one, and saved ones

    def series_of_run(self, run):
        """The series of the run: the original run's in the plots it draws in, a saved run's wherever
        they've been put."""
        if run != LIVE:
            return [s for s in (_view.series_of_entry(e['id']) for e in _view.entries(run)) if s is not None]
        axes = list(dict.fromkeys(t.axes for t in self._drawn if getattr(t, 'axes', None) is not None)) or self.axes
        return [s for ax in axes if ax.figure is not None for s in _series.series(ax)
                if getattr(s.artist, '_csn_run', None) == LIVE and getattr(s.artist, '_csn_owner', None) is self]

    def locked(self):
        """Whether the run on the sliders is locked: its parameters to be seen, not changed."""
        return any(_view.locked(s) for s in self.series_of_run(self.active))

    def activate(self, run):
        """The sliders show this run's parameters, and change it."""
        if run != LIVE:
            params = next((e.get('params') for e in _view.entries(run) if e.get('params')), None)
            if params is None:   # saved without its parameters: nothing to show
                return
            shown = {name: self._cast(name, params.get(name, self.defaults[name])) for name in self.order}
        else:
            shown = self.values
        if run == self.active and shown == self.shown:
            self.pane.show_run()
            return
        self.active, self.shown = run, shown
        self.pane.show_values()
        self.pane.show_run()

    def run_name(self, run):
        if run == LIVE:
            return 'original run'
        entry = next(iter(_view.entries(run)), None)
        if entry is None:
            return 'saved run'
        suffix = entry.get('suffix')
        return f"saved run “{suffix}”" if suffix else f"saved run ({entry.get('label', '')})"

    def describe(self, values=None):
        """'b_0 = 1, r_0 = 0.1' - the values given, or those on the sliders."""
        values = self.shown if values is None else values
        return ', '.join(f"{name} = {('on' if values[name] else 'off') if name in self.toggles else _short(values[name])}"
                         for name in self.order if name in values)

    # ---- saving, and the history

    def state(self):
        return self.active, dict(self.shown), dict(self.ranges)

    def load(self, state):
        """A run's values and the ranges as they were (an undo), onto the sliders, and drawn."""
        run, values, ranges = state
        self.ranges = dict(ranges)
        if run != LIVE and not _view.entries(run):
            run = LIVE
        if run == LIVE:
            self.values.update(values)
            self.shown = self.values
        else:
            self.shown = dict(values)
        self.active = run
        self.pane.show_values()
        self.pane.show_run()
        self.save()
        self.run()

    def record(self, name, before):
        after = self.state()
        if after != before:
            history.push(name, lambda: self.load(before), lambda: self.load(after))
        self.save()

    def save(self):
        kept = {'values': dict(self._safe), 'ranges': {name: list(bounds) for name, bounds in self.ranges.items()},
                'reference': self.pane.reference.isChecked()}
        if not self._live_auto:   # Update live as chosen - not as the first run's weight decided it
            kept['live'] = self.pane.live.isChecked()
        store.section(self.figure)[self.slot] = kept
        store.changed()

    def live_chosen(self):
        self._live_auto = self._live_pending = False
        self.save()

    def _reset_hook(self):
        self.ranges = dict(self.default_ranges)
        self.values.clear()
        self.values.update(self.defaults)
        self._safe = dict(self.defaults)
        self.active, self.shown = LIVE, self.values
        self.pane.show_values()
        self.pane.show_run()
        QtCore.QTimer.singleShot(0, self.run)   # once the reset's done with the plots: the run's thread draws in them

    # ---- the reference, and keeping a run

    def set_reference(self):
        """The current run, kept as a faint shadow under the next ones."""
        self._remove(self._reference)
        self._reference = []
        for artist in self._drawn:
            ax = getattr(artist, 'axes', None)
            if ax is None:
                continue
            order = [a for a in self._drawn if getattr(a, 'axes', None) is ax].index(artist)
            shadow = self._shadow(artist)
            if shadow is not None:
                shadow._csn_shadows = (ax, artist.get_label(), order)   # the series it's the shadow of
                self._reference.append(shadow)
        self._sync_reference()
        for canvas in self._canvases():
            canvas.draw_idle()

    def _shadow(self, artist, like=None):
        """A faint copy of a line or of dots, under it in its plot - of like's data if given (a shadow:
        the reference, in a copy of its series), else its own. None for anything else."""
        ax = artist.axes
        source = like if like is not None else artist
        if isinstance(artist, Line2D) and isinstance(source, Line2D) and artist.get_transform() is ax.transData:
            shadow = Line2D(source.get_xdata(orig=True), source.get_ydata(orig=True))
            shadow.update_from(artist)
            if len(shadow.get_xdata(orig=True)) > self.REFERENCE_LINE_AT:   # dense markers: a line shows better
                shadow.set_marker('')
                shadow.set_linestyle('-')
                shadow.set_linewidth(max(artist.get_linewidth(), 1.6))
            ax.add_line(shadow)
        elif isinstance(artist, PathCollection) and isinstance(source, PathCollection) and len(source.get_offsets()):
            offsets = np.asarray(source.get_offsets())
            colours = artist.get_facecolors()
            if len(colours) not in (1, len(offsets)):   # the copy's dots, of another run: their first colour
                colours = colours[:1]
            shadow = ax.scatter(offsets[:, 0], offsets[:, 1], s=artist.get_sizes(), c=colours,
                                marker=getattr(artist, '_csn_marker', 'o'))
        else:
            return None
        shadow.set_label('_reference')
        shadow.set_alpha(self.REFERENCE_ALPHA)
        shadow.set_zorder(artist.get_zorder() - 0.5)
        shadow.set_gid(_series.OURS)
        return shadow

    def show_reference(self, shown):
        self._sync_reference()
        self.save()
        for canvas in self._canvases():
            canvas.draw_idle()

    def _sync_reference(self):
        """Each shadow shown while the reference is on and the series it's the shadow of is shown -
        that series found by its name in its plot, else by its place there."""
        on = self.pane.reference.isChecked()
        for shadow in self._reference:
            ax, label, order = getattr(shadow, '_csn_shadows', (None, None, None))
            mine = [a for a in self._drawn if getattr(a, 'axes', None) is ax]
            match = next((a for a in mine if a.get_label() == label), None)
            if match is None and order is not None and order < len(mine):
                match = mine[order]
            shadow._csn_like = match   # it comes and goes as that series does (_animate)
            shadow.set_visible(on and (match is None or match.get_visible()))
        changed = self._shadow_copies()
        for shadow in self._copied:
            shown = on and shadow._csn_like.get_visible()
            if shadow.get_visible() != shown:
                shadow.set_visible(shown)
                changed.add(shadow.figure)
        for figure in changed:
            if figure is not None and figure.canvas is not None:
                figure.canvas.draw_idle()

    def _shadow_copies(self):
        """The reference in every linked copy of a series it shadows, too - a duplicated plot's, a
        series shown in another plot: made as copies come, dropped as they go. The figures changed."""
        changed, kept = set(), []
        for shadow in self._copied:
            copy = shadow._csn_like
            if shadow._csn_from in self._reference and copy.axes is not None and shadow.axes is copy.axes \
                    and copy in copy.axes.get_children():
                kept.append(shadow)
            else:
                changed.add(shadow.figure)
                self._remove([shadow])
        self._copied = kept
        have = {(id(s._csn_from), id(s._csn_like)) for s in kept}
        for shadow in self._reference:
            like = getattr(shadow, '_csn_like', None)
            if like is None or like.axes is None:
                continue
            source = next((s for s in _series.series(like.axes, everything=True) if s.artist is like), None)
            if source is None:
                continue
            for other in _series.members(source):
                artist = other.artist
                if artist is like or not getattr(artist, '_csn_link', None) or artist.axes is None \
                        or other.label.endswith(_view.REFERENCE) or (id(shadow), id(artist)) in have:
                    continue   # the series itself, a reference copy (a shadow of its own), one done
                made = self._shadow(artist, like=shadow)
                if made is not None:
                    made._csn_from, made._csn_like = shadow, artist   # it comes and goes as the copy does
                    self._copied.append(made)
                    changed.add(made.figure)
        return changed

    def keep(self, suffix):
        """The run on the sliders, kept as series of its own - named with suffix added, each in a colour
        not used yet in its plot. A copy of a saved or a locked run becomes the one the sliders change
        (the copy's unlocked)."""
        source, was_locked = self.active, self.locked()
        run = uuid.uuid4().hex[:10]
        entries, used = [], {}
        for s in self.series_of_run(source):
            if s.kind not in ('line', 'scatter'):
                continue
            taken = used.setdefault(s.ax, {other.colour().lower() for other in _series.series(s.ax)})
            colour = next((c for c in _style.SERIES if c.lower() not in taken), None)
            if colour is not None:
                taken.add(colour.lower())
            if source == LIVE:
                name, origin = _series.name_of(s), _series.ax_id(s.ax)
            else:
                mine = next((e for e in _view.entries(source) if e['id'] == _series.added(s)), {})
                name, origin = mine.get('source', s.label), mine.get('origin', mine.get('axes', _series.ax_id(s.ax)))
            entry = _view.entry_from(s, f"{name} {suffix}".strip(), run=run, owner=self.key, source=name,
                                     origin=origin, params=dict(self.shown), suffix=suffix)
            if colour is not None:
                entry['look'] = {**entry['look'], 'colour': colour}
            entries.append(entry)
        if not entries:
            return
        for entry in entries:
            _view.add_series(entry, record=False)
        history.push('Save run', lambda: [_view.remove_series(e['id'], False) for e in entries],
                     lambda: [_view.add_series(e, False) for e in entries])
        self.kept += 1
        if source != LIVE or was_locked:   # the copy's what the sliders change now
            self.activate(run)
        self.group.refresh()

    def fit_view(self):
        """Every plot fitted to what's shown in it again, zoomed or not."""
        for ax in self.axes:
            if ax.figure is not None:
                ax.set_autoscale_on(True)
                _series.fit(ax)
        for canvas in self._canvases():
            canvas.draw_idle()
            if canvas.toolbar is not None:
                canvas.toolbar.push_current()


class ParametersPane(QtWidgets.QWidget):
    """A slider, a number box and an editable low and high for each parameter, which run they're
    showing, how the run's going, and what to do with the runs."""

    STEPS = 1000         # a slider's steps - but whole numbers on a straight scale go one by one
    BUSY_SHOWN_MS = 150  # a run quicker than this shows no progress at all
    POLL_MS = 80

    def __init__(self, parameters, saved):
        from ._sweep import button as sweep_button   # here: that module builds on this one
        super().__init__()
        self.setObjectName('csnParameters')
        self.setMinimumWidth(1)
        self.parameters = p = parameters
        self._runner = QtCore.QTimer(self)   # at most one run an event loop turn, however fast a slider moves
        self._runner.setSingleShot(True)
        self._runner.timeout.connect(p.run)
        self.controls = {}
        self._before = None   # the state a slider drag started from
        self._job = None
        history.listeners.append(self.show_run)   # a lock changed, a run deleted

        self.heading = QtWidgets.QLabel()
        self.heading.setObjectName('csnHint')
        self.heading.setWordWrap(True)
        self.back = QtWidgets.QPushButton('Original run')
        self.back.setToolTip('Show and edit the parameters of the original run again')
        self.back.clicked.connect(lambda: p.activate(LIVE))
        heading = QtWidgets.QHBoxLayout()
        heading.addWidget(self.heading, 1)
        heading.addWidget(self.back)

        body = QtWidgets.QWidget()
        rows = QtWidgets.QVBoxLayout(body)
        rows.setContentsMargins(0, 0, 4, 0)
        rows.setSpacing(2)
        self.switches = {}
        for name in p.order:
            if name in p.toggles:   # on or off: a tick box
                switch = QtWidgets.QCheckBox(name)
                switch.setToolTip(f"{name}: on or off - drawn again as it's ticked")
                switch.toggled.connect(lambda on, n=name: self._switched(n, on))
                rows.addWidget(switch)
                rows.addSpacing(10)
                self.switches[name] = switch
                continue
            box = NumberField(whole=p.whole[name])   # typed: counts on Enter or clicking away
            box.setFixedWidth(112)
            box.stepper = lambda value, way, n=name: self._nudged(n, value, way)
            slider = QtWidgets.QSlider(Qt.Orientation.Horizontal)
            slider.valueChanged.connect(lambda position, n=name: self._slid(n, position))
            slider.sliderPressed.connect(self._drag_started)
            slider.sliderReleased.connect(self._drag_ended)
            box.valueChanged.connect(lambda value, n=name: self._typed(n, value))
            low, high = (self._bound_field(name, side) for side in (0, 1))
            top = QtWidgets.QHBoxLayout()
            top.addWidget(QtWidgets.QLabel(name), 1)
            top.addWidget(sweep_button(self, name))   # every step from low to high, played on the plots
            top.addWidget(box)
            bottom = QtWidgets.QHBoxLayout()
            bottom.addWidget(low)
            bottom.addStretch(1)
            bottom.addWidget(high)
            rows.addLayout(top)
            rows.addWidget(slider)
            rows.addLayout(bottom)
            rows.addSpacing(10)
            self.controls[name] = (slider, box, low, high)

        self.live = QtWidgets.QCheckBox('Update live')
        self.live.setChecked(saved.get('live', True))
        self.live.setToolTip('Compute and draw again as a slider moves. Off: once it is released')
        self.live.toggled.connect(lambda _: p.live_chosen())
        self.reference = QtWidgets.QCheckBox('Show reference')
        self.reference.setChecked(saved.get('reference', True))
        self.reference.setToolTip('The reference run, drawn faintly under the current one')
        self.reference.toggled.connect(p.show_reference)
        ticks = QtWidgets.QHBoxLayout()
        ticks.addWidget(self.live)
        ticks.addWidget(self.reference)
        ticks.addStretch(1)
        buttons = QtWidgets.QGridLayout()
        self.buttons = {}
        for index, (text, tip, action) in enumerate((
                ('Reset', 'Every parameter back to its default value', self.reset),
                ('Set reference', 'Draw this run faintly under the next ones, for comparison', p.set_reference),
                ('Fit view', 'Fit every plot to the data it shows', p.fit_view),
                ('Save run…', "Keep this run's series as data series of their own", self._keep))):
            button = QtWidgets.QPushButton(text)
            button.setToolTip(tip)
            button.clicked.connect(action)
            buttons.addWidget(button, index // 2, index % 2)
            self.buttons[text] = button

        own = QtWidgets.QGridLayout()   # the script's buttons
        for index, (text, function) in enumerate(p.actions):
            button = QtWidgets.QPushButton(str(text))
            button.setToolTip(f"Runs {getattr(function, '__name__', 'its function')}() of the script, "
                              f"with the values on the sliders")
            button.clicked.connect(lambda _=False, f=function: p.press(f))
            own.addWidget(button, index // 2, index % 2)

        self.spinner = Spinner(18)
        self.bar = QtWidgets.QProgressBar()
        self.bar.setRange(0, 1000)
        self.bar.setTextVisible(False)
        self.state_label = QtWidgets.QLabel('Computing…')
        self.state_label.setObjectName('csnHint')
        self.stop_button = QtWidgets.QPushButton('Stop')
        self.stop_button.setToolTip('Stop this run (Esc on the plot). The plot keeps the previous completed run')
        self.stop_button.clicked.connect(p.stop)
        self.quit_button = QtWidgets.QPushButton('Force quit…')
        self.quit_button.setToolTip('The run does not respond to Stop: it is probably inside a single long '
                                    'call. Quitting the program is the only way to end it')
        self.quit_button.clicked.connect(self._quit)
        self.quit_button.hide()
        busy = QtWidgets.QHBoxLayout()
        busy.setContentsMargins(0, 0, 0, 0)
        busy.addWidget(self.spinner)
        busy.addWidget(self.state_label)
        busy.addWidget(self.bar, 1)
        busy.addWidget(self.stop_button)
        busy.addWidget(self.quit_button)
        self.busy_row = QtWidgets.QWidget()
        self.busy_row.setLayout(busy)
        self.busy_row.hide()
        self._busy_shower = QtCore.QTimer(self)
        self._busy_shower.setSingleShot(True)
        self._busy_shower.timeout.connect(self._show_busy)
        self._poller = QtCore.QTimer(self)
        self._poller.setInterval(self.POLL_MS)
        self._poller.timeout.connect(self._poll)

        self.error = QtWidgets.QLabel()
        self.error.setObjectName('csnError')
        self.error.setWordWrap(True)
        self.error.hide()
        self.timing = QtWidgets.QLabel()
        self.timing.setObjectName('csnHint')

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)
        layout.addLayout(heading)
        layout.addWidget(body)
        if p.actions:
            layout.addLayout(own)
        layout.addWidget(self.busy_row)
        layout.addWidget(self.error)
        layout.addWidget(self.timing)
        layout.addLayout(ticks)
        layout.addLayout(buttons)
        self.show_values()
        self.show_run()

    def _bound_field(self, name, side):
        field = QtWidgets.QLineEdit()
        field.setObjectName('csnRange')
        field.setFixedWidth(72)
        field.setAlignment(Qt.AlignmentFlag.AlignLeft if side == 0 else Qt.AlignmentFlag.AlignRight)
        field.setToolTip(('The lowest', 'The highest')[side] + ' the slider goes - type over it')
        field.setValidator(QtGui.QDoubleValidator())
        field.editingFinished.connect(lambda: self._bound_typed(name, side, field))
        return field

    # ---- showing the values, and the run they're from

    def show_values(self):
        """Every slider, box and range field as the parameters are now."""
        p = self.parameters
        for name, (slider, box, low, high) in self.controls.items():
            bottom, top = p.ranges[name]
            widgets = (slider, box)
            for widget in widgets:
                widget.blockSignals(True)
            if p.whole[name] and not p.log[name]:
                slider.setRange(int(bottom), int(top))
            else:
                slider.setRange(0, self.STEPS)
            if not p.whole[name]:
                box.setDigits(max(self._decimals(bottom, top, p.log[name]), 4))
            box.setValue(p.shown[name])
            slider.setValue(self._position(name, p.shown[name]))
            for widget in widgets:
                widget.blockSignals(False)
            low.setText(_short(bottom))
            high.setText(_short(top))
        for name, switch in self.switches.items():
            switch.blockSignals(True)
            switch.setChecked(bool(p.shown[name]))
            switch.blockSignals(False)

    def show_run(self):
        """Which run the sliders are on, and - locked - its parameters greyed out, Save run lit."""
        p = self.parameters
        if p.active != LIVE and not _view.entries(p.active):   # the saved run's gone (deleted, undone)
            p.active, p.shown = LIVE, p.values
            self.show_values()
        locked = p.locked()
        self.heading.setText(('Viewing (locked): ' if locked else 'Editing: ') + p.run_name(p.active))
        self.back.setVisible(p.active != LIVE)
        for slider, box, low, high in self.controls.values():
            for widget in (slider, box, low, high):
                widget.setEnabled(not locked)
        for switch in self.switches.values():
            switch.setEnabled(not locked)
        self.buttons['Reset'].setEnabled(not locked)
        keep = self.buttons['Save run…']
        keep.setProperty('csnHighlight', locked)
        keep.setToolTip('Locked: save a copy of this run to edit its parameters (the copy is unlocked)' if locked
                        else "Keep this run's series as data series of their own")
        keep.style().unpolish(keep)
        keep.style().polish(keep)

    def _nudged(self, name, value, way):
        """A value one nudge away: a hundredth of the range (on a log scale, of its decades) - a whole
        number by at least one."""
        p = self.parameters
        low, high = p.ranges[name]
        if p.log[name] and value > 0:
            moved = value * (high / low) ** (way / 100)
        else:
            moved = value + way * (high - low) / 100
        if p.whole[name]:
            moved = int(round(moved))
            if moved == value:
                moved = value + way
        return moved

    def _position(self, name, value):
        p = self.parameters
        low, high = p.ranges[name]
        if p.whole[name] and not p.log[name]:
            return int(min(max(value, low), high))
        if p.log[name]:
            share = (math.log(value) - math.log(low)) / (math.log(high) - math.log(low)) if value > 0 else 0.0
        else:
            share = (value - low) / (high - low) if high != low else 0.0
        return int(round(min(max(share, 0.0), 1.0) * self.STEPS))

    def _value(self, name, position):
        p = self.parameters
        low, high = p.ranges[name]
        if p.whole[name] and not p.log[name]:
            return int(position)
        share = position / self.STEPS
        if p.log[name]:
            value = math.exp(math.log(low) + share * (math.log(high) - math.log(low)))
            return int(round(value)) if p.whole[name] else value
        return low + share * (high - low)

    @staticmethod
    def _decimals(low, high, log):
        span = abs(math.log10(min(low, high))) + 3 if log else -math.log10(max(abs(high - low), 1e-12) / 1000) + 1
        return int(min(max(math.ceil(span), 2), 8))

    # ---- a run going on

    def set_busy(self, job):
        self._job = job
        self.quit_button.hide()
        if job is None:
            self._busy_shower.stop()
            self._poller.stop()
            self.busy_row.hide()
        else:
            self._busy_shower.start(self.BUSY_SHOWN_MS)

    def _show_busy(self):
        if self._job is None:
            return
        self.busy_row.show()
        self._poll()
        self._poller.start()

    def _poll(self):
        job = self._job
        if job is None:
            return
        self.bar.setVisible(job.fraction is not None)
        if job.fraction is not None:
            self.bar.setValue(int(job.fraction * 1000))
        if not self.quit_button.isVisible():
            seconds = time.perf_counter() - job.started
            self.state_label.setText(('Stopping…' if job.stopping else 'Computing…') + f"  {seconds:.1f} s")
        for canvas in self.parameters._canvases():
            veil = getattr(canvas, 'busy_veil', None)
            if veil is not None and veil.isVisible():
                veil.fraction = job.fraction
                veil.update()

    def show_stuck(self):
        self.quit_button.show()
        self.state_label.setText('Not responding to Stop: probably inside a single long call')

    def _quit(self):
        answer = QtWidgets.QMessageBox.question(
            self, 'Force quit',
            'The run does not respond to Stop: it is probably inside a single long call (numpy, for '
            'instance). Quit the program?\nThe view settings are saved, without the values of this run.')
        if answer == QtWidgets.QMessageBox.StandardButton.Yes:
            store.save()
            os._exit(1)

    # ---- changes

    def _unflash_all(self):
        for _, _, low, high in self.controls.values():
            unflash(low)
            unflash(high)

    def _drag_started(self):
        self._before = self.parameters.state()
        self._unflash_all()

    def _drag_ended(self):
        before, self._before = self._before, None
        if not self.live.isChecked():
            self._runner.start(0)
        if before is not None:
            self.parameters.record('Move slider', before)

    def _slid(self, name, position):
        slider, box, _, _ = self.controls[name]
        p = self.parameters
        before = p.state()
        value = self._value(name, position)
        box.blockSignals(True)
        box.setValue(value)
        box.blockSignals(False)
        p.shown[name] = value
        if self.live.isChecked() or not slider.isSliderDown():   # keys move it without a release
            self._runner.start(0)
        if not slider.isSliderDown():
            self._unflash_all()
            p.record('Change ' + name, before)

    def _switched(self, name, on):
        p = self.parameters
        before = p.state()
        p.shown[name] = bool(on)
        p.record('Change ' + name, before)
        self._runner.start(0)

    def _typed(self, name, value):
        p = self.parameters
        before = p.state()
        self._unflash_all()
        low, high = p.ranges[name]
        _, _, low_field, high_field = self.controls[name]
        if value < low:   # past the range: the range goes with it
            p.ranges[name] = (value, high)
            flash(low_field)
        elif value > high:
            p.ranges[name] = (low, value)
            flash(high_field)
        p.shown[name] = value
        self.show_values()
        p.record('Change ' + name, before)
        self._runner.start(0)

    def _bound_typed(self, name, side, field):
        p = self.parameters
        try:
            bound = p._cast(name, float(field.text()))
        except ValueError:
            self.show_values()
            return
        low, high = p.ranges[name]
        new = (bound, high) if side == 0 else (low, bound)
        if new == (low, high):
            return
        if new[0] >= new[1] or (p.log[name] and new[0] <= 0):
            self.show_values()   # not a range: as it was
            return
        before = p.state()
        self._unflash_all()
        p.ranges[name] = new
        p.shown[name] = p._cast(name, min(max(p.shown[name], new[0]), new[1]))   # the value stays inside
        self.show_values()
        p.record('Change range of ' + name, before)
        self._runner.start(0)

    def reset(self):
        p = self.parameters
        before = p.state()
        p.shown.update(p.defaults)
        self.show_values()
        p.record('Reset parameters', before)
        self._runner.start(0)

    def _keep(self):
        suggestion = f"run {self.parameters.kept + 1}"
        suffix, ok = QtWidgets.QInputDialog.getText(self, 'Save run',
                                                    "Name added to each series of this run:", text=suggestion)
        if ok:
            self.parameters.keep(suffix.strip())

    def show_error(self, error, failed=None):
        """Why the run failed (failed: what else did - a button's function) - None: nothing to say."""
        p = self.parameters
        if error is None:
            self.error.hide()
            return
        if failed is not None:
            message = str(error).strip().splitlines()[0][:120] if str(error).strip() else ''
            self.error.setText(f"{failed} ({type(error).__name__}{': ' + message if message else ''}). "
                               f"The terminal has the whole error.")
            self.error.setToolTip('')
            self.error.show()
            return
        if isinstance(error, Stopped):
            self.error.setText('Run stopped. The plot shows the previous run.')
        else:
            message = str(error).strip().splitlines()[0][:120] if str(error).strip() else ''
            self.error.setText(f"The run failed ({type(error).__name__}{': ' + message if message else ''}). "
                               f"The plot shows the previous run.")
        self.error.setToolTip(f"The previous run's parameters: {p.describe(p._good)}")
        self.error.show()

    def show_timing(self, computed, drawn):
        text = f"Computed in {_duration(computed)}"
        if drawn is not None:
            text += f"  ·  drawn in {_duration(drawn)}"
        self.timing.setText(text)


class _Header(QtWidgets.QWidget):
    """Which plots use a set of sliders, with the arrow that folds them away - hovered, those in the
    tab are outlined on the plot; clicked, folded or opened."""

    def __init__(self, group):
        super().__init__()
        self.group = group
        self.arrow = QtWidgets.QToolButton()
        self.arrow.setObjectName('csnSection')
        self.arrow.setArrowType(Qt.ArrowType.DownArrow)
        self.arrow.setAutoRaise(True)
        self.arrow.clicked.connect(group.toggle)
        self.text = QtWidgets.QLabel()
        self.text.setObjectName('csnHint')
        self.text.setWordWrap(True)
        self.text.setTextFormat(Qt.TextFormat.RichText)
        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(6, 8, 12, 0)
        layout.setSpacing(4)
        layout.addWidget(self.arrow, 0, Qt.AlignmentFlag.AlignTop)
        layout.addWidget(self.text, 1)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip('Click to fold these sliders away, or open them')

    def setText(self, text):
        self.text.setText(text)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.group.toggle()
        super().mousePressEvent(event)

    def enterEvent(self, event):
        super().enterEvent(event)
        self.group.outline(True)

    def leaveEvent(self, event):
        super().leaveEvent(event)
        self.group.outline(False)


class _Group(QtWidgets.QWidget):
    """One set of sliders in a tab's Parameters tab: the plots that use them, over the sliders - which
    fold away."""

    def __init__(self, parameters):
        super().__init__()
        self.parameters = parameters
        self.figure = parameters.figure   # the tab it's shown in
        self.opened = True
        self.header = _Header(self)
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.header)
        layout.addWidget(parameters.pane)

    def toggle(self):
        self.opened = not self.opened
        self.parameters.pane.setVisible(self.opened)
        self.header.arrow.setArrowType(Qt.ArrowType.DownArrow if self.opened else Qt.ArrowType.RightArrow)

    def refresh(self, figure=None):
        if figure is not None:
            self.figure = figure
        plots = self.parameters.plots()
        names = [_series.plot_name(ax) for ax in plots if ax.figure is self.figure]
        names += [f"{_series.plot_name(ax)} (tab {_series.tab_name(ax.figure)})" for ax in plots
                  if ax.figure is not self.figure]
        self.header.setText(f"<span style='color:{_style.TEXT_2}'>{self.parameters.name}()</span>"
                            f" &nbsp;used by: <span style='color:{_style.TEXT}'>{', '.join(names) or 'no plot'}</span>")

    def outline(self, on):
        canvas = getattr(self.figure, 'canvas', None)
        if hasattr(canvas, 'outline'):
            canvas.outline([ax for ax in self.parameters.plots() if ax.figure is self.figure] if on else [], hold=True)


class Holder(QtWidgets.QWidget):
    """A tab's Parameters tab: every set of sliders its plots depend on, one under another, each
    folding away, all in one column that scrolls. A set needed by plots in several tabs is in the
    one in front."""

    def __init__(self, figure):
        super().__init__()
        self.figure = figure
        self.setMinimumWidth(1)
        inner = QtWidgets.QWidget()
        inner.setObjectName('csnParameters')
        self.column = QtWidgets.QVBoxLayout(inner)
        self.column.setContentsMargins(0, 0, 0, 0)
        self.column.setSpacing(6)
        self.scroll = QtWidgets.QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setWidget(inner)
        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(self.scroll)

    def place(self):
        """The sets the tab's plots need now, taken from wherever they were. Gives how many."""
        needed = needed_by(self.figure)
        shown = [self.column.itemAt(i).widget() for i in range(self.column.count())
                 if self.column.itemAt(i).widget() is not None]
        if shown == [p.group for p in needed] and all(g.parentWidget() is not None and
                                                      g.parentWidget() is self.column.parentWidget() for g in shown):
            for parameters in needed:   # the same sets: left where they are (a slider may be held)
                parameters.group.refresh(self.figure)
            return len(needed)
        while self.column.count():
            self.column.takeAt(0)
        inner = self.column.parentWidget()
        for group in [p.group for p in _all]:
            if group.parentWidget() is inner and group.parameters not in needed:
                group.hide()
                group.setParent(None)
        for parameters in needed:
            parameters.group.refresh(self.figure)
            self.column.addWidget(parameters.group)
            parameters.group.show()
        self.column.addStretch(1)
        return len(needed)


def _short(value):
    return f"{value:.6g}"


def _duration(seconds):
    return f"{seconds * 1000:.1f} ms" if seconds < 1 else f"{seconds:.2f} s"
