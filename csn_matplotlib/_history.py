"""Undo and redo, for what's changed through the window - looks, names, labels, the grid, the layout,
slider values and ranges, series added or deleted. Not the view (zoom, pan): matplotlib's own back
and forward have that. One history for the app, whichever tab a change was in."""


class History:
    LIMIT = 300

    def __init__(self):
        self._undo, self._redo = [], []
        self.listeners = []   # called after every change to the history - widgets showing what's undoable

    def push(self, name, undo, redo):
        """A change already made: undo() takes it back, redo() makes it again."""
        self._undo.append((name, undo, redo))
        del self._undo[:-self.LIMIT]
        self._redo.clear()
        self._tell()

    def undo(self):
        return self._step(self._undo, self._redo, 1)

    def redo(self):
        return self._step(self._redo, self._undo, 2)

    def _step(self, source, target, which):
        if not source:
            return None
        entry = source.pop()
        entry[which]()
        target.append(entry)
        self._tell()
        return entry[0]

    def next_undo(self):
        return self._undo[-1][0] if self._undo else None

    def next_redo(self):
        return self._redo[-1][0] if self._redo else None

    def _tell(self):
        for listener in list(self.listeners):
            try:
                listener()
            except RuntimeError:   # its widget is gone (a closed figure): it hears no more
                self.listeners.remove(listener)


history = History()
