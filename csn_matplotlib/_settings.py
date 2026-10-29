"""The view settings file: what the window changed about each figure (_view, _style_editor,
_sliders), kept beside the script as <script>.plot.json so it's all there again next time.
Whether it's kept and where the file is are remembered per script in Qt's own settings (the
registry), so turning it off or moving the file outlasts the run. A script run without a file
(typed in, a notebook) keeps nothing. Nothing's written while anything computes or draws (waits):
only what the window has come through is kept - a run that would bring it down isn't there next time.
Large arrays (a saved run's data) aren't written into the file as numbers but beside it, in the
<script>.plot.data folder, one binary .npy file each (LARGE)."""
import hashlib
import json
import os
import sys

import numpy as np
from PySide6 import QtCore

LARGE = 20_000   # an array of more values than this: a file of its own beside the settings


def figure_key(figure):
    """A figure's name in the file: its label (plt.figure('Phase')), else 'Figure 1'."""
    label = figure.get_label()
    return label if label else f"Figure {getattr(figure, 'number', 1)}"


class Store:
    SAVE_MS = 400   # changes this close together are written once

    def __init__(self):
        self.waits = []   # callables: any True, and saving waits (a run computing, a figure drawing)
        script = getattr(sys.modules.get('__main__'), '__file__', None)
        self.script = os.path.abspath(script) if script else None
        self._qt = QtCore.QSettings('CSN', 'csn_matplotlib')
        if self.script:
            self._key = 'scripts/' + hashlib.sha1(self.script.lower().encode('utf-8')).hexdigest()[:16]
            self.default_path = os.path.splitext(self.script)[0] + '.plot.json'
            self.enabled = self._qt.value(self._key + '/enabled', False, type=bool)
            self.path = self._qt.value(self._key + '/path', self.default_path) or self.default_path
        else:
            self._key = self.default_path = self.path = None
            self.enabled = False
        self.data = self._read()
        self._timer = None

    def _read(self):
        try:
            with open(self.path, encoding='utf-8') as file:
                data = json.load(file, object_hook=self._load_array)
            return data if isinstance(data, dict) else {}
        except (OSError, TypeError, ValueError):
            return {}

    def section(self, figure):
        """The figure's part of the settings - kept in memory even while saving is off."""
        return self.data.setdefault('figures', {}).setdefault(figure_key(figure), {})

    def changed(self):
        if not self.enabled:
            return
        if self._timer is None:
            self._timer = QtCore.QTimer()
            self._timer.setSingleShot(True)
            self._timer.timeout.connect(self.save)
        self._timer.start(self.SAVE_MS)

    def save(self):
        if not (self.enabled and self.path):
            return
        if any(wait() for wait in self.waits):   # not now: once the window's come through it
            self.changed()
            return
        if self._timer is not None:
            self._timer.stop()
        try:
            self._written = set()
            text = json.dumps(self.data, indent=1, default=self._save_array)
            temporary = self.path + '.tmp'
            with open(temporary, 'w', encoding='utf-8') as file:
                file.write(text)
            os.replace(temporary, self.path)   # never half a file
            self._tidy_arrays()
        except (OSError, TypeError, ValueError) as error:
            print(f"csn_matplotlib: couldn't save the view settings to {self.path}: {error}", file=sys.stderr)

    def flush(self):
        """What's waiting to be written, written now (the window closing)."""
        if self._timer is not None and self._timer.isActive():
            self._timer.stop()
            self.save()

    def _folder(self):
        return os.path.splitext(self.path)[0] + '.data'

    def _save_array(self, value):
        """json's fallback: an array as a list - a large one as a file of its own, named by its contents
        (an unchanged one isn't written again)."""
        if isinstance(value, np.generic):
            return value.item()
        if not isinstance(value, np.ndarray):
            raise TypeError(f"{type(value).__name__} can't be kept in the settings")
        if value.size <= LARGE or value.dtype == object:
            return value.tolist()
        value = np.ascontiguousarray(value)
        name = hashlib.sha1(value.tobytes() + str(value.dtype).encode()).hexdigest()[:20] + '.npy'
        folder = self._folder()
        path = os.path.join(folder, name)
        if not os.path.exists(path):
            os.makedirs(folder, exist_ok=True)
            np.save(path, value, allow_pickle=False)
        self._written.add(name)
        return {'__array__': name}

    def _load_array(self, value):
        if set(value) == {'__array__'}:
            try:
                return np.load(os.path.join(self._folder(), value['__array__']), allow_pickle=False)
            except (OSError, ValueError):
                return np.empty(0)
        return value

    def _tidy_arrays(self):
        """The folder's files no longer in the settings, gone (only ours: .npy files named by contents)."""
        folder = self._folder()
        if not os.path.isdir(folder):
            return
        for name in os.listdir(folder):
            if name.endswith('.npy') and len(name) == 24 and name not in self._written:
                try:
                    os.remove(os.path.join(folder, name))
                except OSError:
                    pass
        if not os.listdir(folder):
            os.rmdir(folder)

    def set_enabled(self, on):
        self.enabled = bool(on) and self.script is not None
        if self._key:
            self._qt.setValue(self._key + '/enabled', self.enabled)
        if self.enabled:
            self.save()

    def move_to(self, path):
        """The settings kept in this file from now on (written there straight away)."""
        self.path = path
        if self._key:
            self._qt.setValue(self._key + '/path', path)
        self.save()

    def plots(self):
        """What's kept of each plot and series, whichever tab it's in now: names, looks, labels, scales,
        locks, series added - keyed by the plot's ax_id(), so it follows a plot moved to another tab."""
        return self.data.setdefault('plots', {})

    def layout(self):
        """Which tab each plot is in, and how each tab's plots are arranged (_layout)."""
        return self.data.setdefault('layout', {})

    def clear(self):
        self.data = {}
        self.changed()


store = Store()
