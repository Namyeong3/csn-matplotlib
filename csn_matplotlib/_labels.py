"""Double-click a title, an axis label or a legend entry to rename it, there on the plot: a text box
over it - Enter or clicking away keeps the new text, Escape keeps the old. Through _view: saved,
undoable. Double-click a legend entry's marker or line to edit that series' appearance in the Plot tab."""
from PySide6 import QtCore, QtWidgets

from . import _series, _view

Qt = QtCore.Qt


class LabelEditor:
    REACH_PX = 4       # this much round a label still counts as on it
    LEAST_WIDTH = 160  # the text box, at least

    def __init__(self, canvas):
        self.canvas = canvas
        self._field = None

    def double_click(self, xy):
        """Editing the label at the display point, or the look of the series whose legend marker is
        there, if there's one: True."""
        s = self._handle_at(xy)
        if s is not None:
            self.canvas.open_look(s)
            return True
        found = self._label_at(xy)
        if found is None:
            return False
        artist, commit = found
        self._open(artist, commit)
        return True

    def _label_at(self, xy):
        figure = self.canvas.figure
        try:
            renderer = self.canvas.get_renderer()
        except AttributeError:
            return None
        for where, artist in _view.texts_at(figure):
            if self._under(artist, xy, renderer):
                return artist, lambda text, w=where: _view.set_text(figure, w, text)
        legends = [(ax.get_legend(), [ax]) for ax in figure.axes] + [(legend, figure.axes) for legend in figure.legends]
        for legend, axes in legends:
            if legend is None or not legend.get_visible():
                continue
            for artist in legend.get_texts():
                if not self._under(artist, xy, renderer):
                    continue
                s = next((s for ax in axes for s in _series.series(ax) if s.label == artist.get_text()), None)
                if s is not None and _view.locked(s):
                    self.canvas.say(f"“{s.label}” is locked. Unlock it in the data panel to rename it")
                    return None
                if s is not None:
                    key = _series.key_of(s)
                    return artist, lambda text, k=key: _view.rename(k, text)
        return None

    def _handle_at(self, xy, texts=False):
        """The series whose legend marker (or line, or patch) is at the point - or its name too, if
        texts - None if none."""
        figure = self.canvas.figure
        try:
            renderer = self.canvas.get_renderer()
        except AttributeError:
            return None
        reach = self.REACH_PX * (self.canvas.device_pixel_ratio or 1.0)
        legends = [(ax.get_legend(), [a for a in figure.axes if _view.main_of(a) is _view.main_of(ax)])
                   for ax in figure.axes] + [(legend, figure.axes) for legend in figure.legends]
        for legend, axes in legends:
            if legend is None or not legend.get_visible():
                continue
            for handle, text in zip(getattr(legend, 'legend_handles', []), legend.get_texts()):
                try:
                    box = handle.get_window_extent(renderer)
                except (AttributeError, TypeError, ValueError):
                    continue
                if texts:
                    try:
                        box = box.union([box, text.get_window_extent(renderer)])
                    except (AttributeError, TypeError, ValueError):
                        pass
                if box.x0 - reach <= xy[0] <= box.x1 + reach and box.y0 - reach <= xy[1] <= box.y1 + reach:
                    return next((s for ax in axes for s in _series.series(ax) if s.label == text.get_text()), None)
        return None

    def _under(self, artist, xy, renderer):
        if artist is None or not artist.get_visible() or not artist.get_text():
            return False
        box = artist.get_window_extent(renderer).expanded(1, 1)
        reach = self.REACH_PX * (self.canvas.device_pixel_ratio or 1.0)
        return box.x0 - reach <= xy[0] <= box.x1 + reach and box.y0 - reach <= xy[1] <= box.y1 + reach

    def _open(self, artist, commit):
        self.close()
        ratio = self.canvas.device_pixel_ratio or 1.0
        box = artist.get_window_extent(self.canvas.get_renderer())
        field = _Field(self.canvas, artist.get_text(), commit, self.close)
        width = max(int(box.width / ratio) + 40, self.LEAST_WIDTH)
        height = field.sizeHint().height()
        centre_x = (box.x0 + box.x1) / 2 / ratio
        centre_y = (self.canvas.figure.bbox.height - (box.y0 + box.y1) / 2) / ratio
        x = min(max(int(centre_x - width / 2), 0), max(self.canvas.width() - width, 0))
        y = min(max(int(centre_y - height / 2), 0), max(self.canvas.height() - height, 0))
        field.setGeometry(x, y, width, height)
        field.show()
        field.setFocus()
        field.selectAll()
        self._field = field

    def close(self):
        field, self._field = self._field, None
        if field is not None:
            field.done = True
            field.hide()
            field.deleteLater()
            self.canvas.setFocus()


class _Field(QtWidgets.QLineEdit):
    def __init__(self, parent, text, commit, close):
        super().__init__(text, parent)
        self.setObjectName('csnLabelEdit')
        self.original, self.commit, self.close_editor, self.done = text, commit, close, False
        self.editingFinished.connect(self._finished)   # Enter, or clicking away

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.done = True
            self.close_editor()
            return
        super().keyPressEvent(event)

    def focusOutEvent(self, event):
        super().focusOutEvent(event)
        if event.reason() != Qt.FocusReason.PopupFocusReason:   # Qt 6 says nothing here when it's unchanged
            self._finished()

    def _finished(self):
        if self.done:
            return
        self.done = True
        text = self.text()
        self.close_editor()
        if text != self.original:
            self.commit(text)
