"""Moving around a plot - the mouse, the precision touchpad and a touch screen - on rectilinear axes
(log ones too; polar and 3D keep matplotlib's own):
- a drag (left or middle button - on the touchpad, click and drag; one finger on a touch screen):
  pans, the point under the pointer staying under it;
- the mouse wheel: zooms at the pointer, NOTCH_ZOOM a notch, eased out over GLIDE_S; tilted
  sideways, it pans;
- the touchpad: two fingers up and down zoom at the pointer, coasting on after a flick as Windows
  sends it; two fingers sideways swipe back or forward through the view history, a round arrow
  coming in from that side (Bubble) and going once they lift, if the swipe got far enough; a pinch
  (Windows sends it as Ctrl + wheel) zooms;
- a touch screen: two fingers pinch and pan at once, as a map does;
- over an axis (its tick labels, beside the plot) any of them works on that axis alone;
- Space: the plot last moved, clicked or touched fitted to what it shows (hidden series left out) -
  that one alone; a double tap does it for the plot tapped;
- the arrow keys pan by NUDGE of the plot, + and - zoom by KEY_ZOOM (eased out like a wheel notch):
  the plot last moved or clicked, else the one under the pointer, else every plot.
Nothing moves while the figure is drawn in the background: a move waits for the draw, then goes on
from where the pointer is.
Every view it settles on goes onto matplotlib's view history, so the toolbar's back and forward
go through them. A touchpad's wheel messages are told from a mouse's by touchpad_reader: fingers on
the pad, or a coast still running from them."""
import math
import time

import numpy as np

from . import _series, touchpad_reader
from ._widgets import Bubble


class Navigation:
    NOTCH_ZOOM = 1.2          # a mouse wheel notch, each way
    GLIDE_S = 0.14            # a notch's zoom, eased out over this long
    PAD_ZOOM = 1.2            # two fingers on the touchpad, per 120 of wheel delta
    PINCH_ZOOM = 1.25         # a touchpad pinch, per 120 of wheel delta
    TILT_PX = 1.0             # a sideways wheel's pan: screen pixels per unit of wheel delta (120 a notch)
    COAST_GAP_S = 0.12        # wheel messages this close after the touchpad's are still its coasting
    DRAG_START_PX = 4         # a press moving less than this is a click, not a pan
    AXIS_REACH_PX = 6         # around an axis' tick labels, still that axis
    SETTLE_S = 0.35           # quiet this long after the wheel / touchpad: the view goes on the history
    DOUBLE_TAP_S = 0.35
    LOCK_UNITS = 12           # a touchpad gesture's first wheel delta, to tell which way it goes
    SWIPE_UNITS = 300         # sideways wheel delta for a swipe to go back or forward
    SWIPE_POLL_MS = 30
    NUDGE = 0.025             # an arrow key pans by this share of the plot
    KEY_ZOOM = 1.1            # + and - zoom by this

    def __init__(self, canvas, Qt, QTimer):
        self.canvas, self.Qt = canvas, Qt
        self.reader = touchpad_reader.shared()
        self._last_pad = -1.0
        self._drag = self._touch = self._glide = None
        self._wheel_targets = None   # kept through one wheel / touchpad gesture
        self._last_tap = -1.0
        self._axis_boxes = None      # [(ax, 'x' | 'y', bbox)] - worked out once a draw
        canvas.mpl_connect('draw_event', lambda event: setattr(self, '_axis_boxes', None))
        self._timer = QTimer()
        self._timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._timer.setInterval(8)
        self._timer.timeout.connect(self._glide_frame)
        self._settler = QTimer()
        self._settler.setSingleShot(True)
        self._settler.timeout.connect(self._settle)
        self._gesture = self._swipe = self._swipe_bubble = None
        self._swipe_watch = QTimer()
        self._swipe_watch.setInterval(self.SWIPE_POLL_MS)
        self._swipe_watch.timeout.connect(self._swipe_check)
        self.focus = []   # the plot last moved, clicked or touched: what Space resets

    @property
    def busy(self):
        return bool(self._drag and self._drag['moved'] or self._touch or self._glide)

    # ---- the mouse

    def press(self, event):
        Qt = self.Qt
        if event.button() not in (Qt.MouseButton.LeftButton, Qt.MouseButton.MiddleButton) or self._toolbar_mode():
            return
        xy = self._xy(event)
        targets = self._targets(xy)
        if targets:
            self.focus = [ax for ax, _ in targets]
        if targets and not self._over_draggable(xy):
            self._stop_glide()
            self._drag = {'targets': targets, 'start': xy, 'last': xy, 'moved': False}

    def move(self, event):
        """True while it's panning - the event is then its own."""
        drag = self._drag
        if drag is None:
            return False
        xy = self._xy(event)
        if not drag['moved']:
            if math.dist(xy, drag['start']) < self.DRAG_START_PX * self._ratio():
                return False
            drag['moved'] = True
            self._begin()
            self.canvas.setCursor(self.Qt.CursorShape.ClosedHandCursor)
        if self._pan(drag['targets'], drag['last'][0] - xy[0], drag['last'][1] - xy[1]):
            drag['last'] = xy
        return True

    def release(self, event):
        """True if this ends a pan; False for a click (or nothing of its own)."""
        drag, self._drag = self._drag, None
        if drag is None or not drag['moved']:
            return False
        self.canvas.unsetCursor()
        self._settle()
        return True

    def wheel(self, event):
        delta = event.angleDelta()
        if not delta.x() and not delta.y():
            return
        now = time.perf_counter()
        pad = self._from_touchpad(delta, now)
        xy = self._xy(event)
        fresh = now - self._last_pad > self.COAST_GAP_S if pad else self._glide is None
        if pad:
            self._last_pad = now
        if fresh or self._wheel_targets is None:
            self._wheel_targets = self._targets(xy)
            self._gesture = {'way': None, 'dx': 0, 'dy': 0}
        pinch = bool(event.modifiers() & self.Qt.KeyboardModifier.ControlModifier)
        dy = delta.y()
        if pad and not pinch:
            gesture = self._gesture
            if gesture['way'] is None:   # which way it goes decides what it does: up and down zoom, sideways swipes
                gesture['dx'] += delta.x()
                gesture['dy'] += delta.y()
                if abs(gesture['dx']) + abs(gesture['dy']) < self.LOCK_UNITS:
                    return
                sideways = abs(gesture['dx']) > 1.5 * abs(gesture['dy']) and self.canvas.toolbar is not None
                gesture['way'] = 'swipe' if sideways else 'zoom'
                if sideways:
                    self._swipe_by(gesture['dx'])
                    return
                dy = gesture['dy']
            elif gesture['way'] == 'swipe':
                self._swipe_by(delta.x())
                return
        targets = self._wheel_targets
        if not targets:
            return
        self.focus = [ax for ax, _ in targets]
        self._begin()
        if pad:
            self._stop_glide()
            if dy:   # Windows' coasting after the fingers lift keeps it going, as a flick should
                self._zoom(targets, xy, (self.PINCH_ZOOM if pinch else self.PAD_ZOOM) ** (-dy / 120))
        elif not dy:   # a mouse wheel's sideways tilt
            self._stop_glide()
            self._pan(targets, -delta.x() * self.TILT_PX * self._ratio(), 0)
        else:
            self._start_glide(targets, xy, -dy / 120 * math.log(self.NOTCH_ZOOM))
            return
        self._settler.start(int(self.SETTLE_S * 1000))

    # ---- the sideways swipe: back and forward through the view history

    def _swipe_by(self, units):
        swipe = self._swipe
        if swipe is None:
            if self._gesture.get('swiped'):   # its coast, after it was decided
                return
            swipe = self._swipe = {'total': 0.0}
            self._swipe_watch.start()
        swipe['total'] += units
        back = swipe['total'] > 0   # scrolling left: back, from the left
        progress = min(abs(swipe['total']) / self.SWIPE_UNITS, 1.0)
        self._bubble().show_at('left' if back else 'right', progress, self._can_go(back))

    def _swipe_check(self):
        """Every SWIPE_POLL_MS while a swipe's on: the fingers lifted - it goes, if it got far enough."""
        swipe = self._swipe
        if swipe is None:
            self._swipe_watch.stop()
            return
        if self.reader is not None:
            lifted = not self.reader.touching
        else:
            lifted = time.perf_counter() - self._last_pad > 0.15
        if not lifted:
            return
        self._swipe_watch.stop()
        self._swipe = None
        if self._gesture is not None:
            self._gesture['swiped'] = True
        back = swipe['total'] > 0
        toolbar = self.canvas.toolbar
        if abs(swipe['total']) >= self.SWIPE_UNITS and self._can_go(back) and toolbar is not None:
            if back:
                toolbar.back()
            else:
                toolbar.forward()
        self._bubble().leave()

    def _can_go(self, back):
        stack = getattr(self.canvas.toolbar, '_nav_stack', None)
        elements = getattr(stack, '_elements', None)
        if not elements:
            return False
        return stack._pos > 0 if back else stack._pos < len(elements) - 1

    def _bubble(self):
        if self._swipe_bubble is None:
            self._swipe_bubble = Bubble(self.canvas)
        return self._swipe_bubble

    def _from_touchpad(self, delta, now):
        if self.reader is None:   # no reader: a touchpad's deltas are seldom whole notches
            return delta.x() % 120 != 0 or delta.y() % 120 != 0
        return self.reader.touching or now - self._last_pad < self.COAST_GAP_S

    # ---- a touch screen (Qt's touch events) and gestures

    def touch(self, event):
        kind = event.type()
        now = time.perf_counter()
        if kind == event.Type.TouchBegin:
            self._stop_glide()
            self._touch = None
            self._touch_began = now
            first = event.points()[0] if event.points() else None
            self._tap_xy = self._xy(first) if first is not None else None
        if kind in (event.Type.TouchEnd, event.Type.TouchCancel):
            touch, self._touch = self._touch, None
            if touch and touch['moved']:
                self._settle()
            elif kind == event.Type.TouchEnd and now - getattr(self, '_touch_began', now) < 0.25:
                if now - self._last_tap < self.DOUBLE_TAP_S and touch and touch['targets']:
                    self.reset([ax for ax, _ in touch['targets']])
                    self._last_tap = -1.0
                else:
                    self._last_tap = now
                    if getattr(self, '_tap_xy', None) is not None:   # a tap: as a click - a point, a line, a series
                        self.canvas.inspector.click(self._tap_xy)
            return
        points = [self._xy(p) for p in event.points() if p.state() != p.State.Released]
        if not points:
            return
        centre = tuple(np.mean(points, axis=0))
        spread = float(np.mean([math.dist(p, centre) for p in points])) if len(points) > 1 else 0.0
        touch = self._touch
        if touch is None or touch['count'] != len(points):   # fingers came or went: start from here
            targets = touch['targets'] if touch else self._targets(centre)
            if targets:
                self.focus = [ax for ax, _ in targets]
            self._touch = {'targets': targets, 'centre': centre, 'spread': spread, 'count': len(points),
                           'start': centre, 'moved': bool(touch and touch['moved'])}
            return
        if not touch['targets']:
            return
        if not touch['moved']:
            if math.dist(centre, touch['start']) < self.DRAG_START_PX * self._ratio() and len(points) == 1:
                return
            touch['moved'] = True
            self._begin()
        if self._drawing():   # this move waits: the next goes from here
            return
        self._pan(touch['targets'], touch['centre'][0] - centre[0], touch['centre'][1] - centre[1])
        if spread > 1 and touch['spread'] > 1:
            self._zoom(touch['targets'], centre, touch['spread'] / spread)
        touch['centre'], touch['spread'] = centre, spread

    def native_gesture(self, event):
        """Qt's own pinch, where the platform sends one."""
        kinds = self.Qt.NativeGestureType
        kind = event.gestureType()
        if kind == kinds.ZoomNativeGesture:
            xy = self._xy(event)
            targets = self._targets(xy)
            if targets:
                self._begin()
                self._zoom(targets, xy, 1 / max(1e-3, 1 + event.value()))
        elif kind == kinds.EndNativeGesture:
            self._settle()

    # ---- the view

    def nudge(self, right, up):
        """An arrow key: the view moved by NUDGE of the plot, right (-1, 0, 1) and up."""
        targets = self._key_targets()
        if not targets:
            return
        self._begin()
        step = self.NUDGE
        self._apply([(ax, which, self._limits(ax, which, lambda b: (b.x0 + right * step * b.width,
                                                                     b.y0 + up * step * b.height,
                                                                     b.x1 + right * step * b.width,
                                                                     b.y1 + up * step * b.height)))
                     for ax, which in targets])
        self._settler.start(int(self.SETTLE_S * 1000))

    def key_zoom(self, way):
        """+ (way 1: in) and - (way -1: out), about the middle of each plot."""
        targets = self._key_targets()
        if not targets:
            return
        self._begin()
        box = targets[0][0].bbox
        self._start_glide(targets, ((box.x0 + box.x1) / 2, (box.y0 + box.y1) / 2), -way * math.log(self.KEY_ZOOM))

    def _key_targets(self):
        """What the keys move: the plot last moved or clicked (with its twins), else the one under the
        pointer, else every plot."""
        axes = [ax for ax in self.focus if ax in self.canvas.figure.axes and self._navigable(ax)]
        if not axes and self.canvas.underMouse():
            axes = [ax for ax, _ in self._targets(tuple(self.canvas.mouseEventCoords()))]
        if not axes:
            return [(ax, 'xy') for ax in self.canvas.figure.axes if self._navigable(ax)]
        return [(ax, 'xy') for ax in axes]

    def reset_focused(self):
        """Space: the plot last moved, clicked or touched (its twins with it) fitted to what it shows -
        only that one; none yet, the one under the pointer."""
        axes = [ax for ax in self.focus if ax in self.canvas.figure.axes]
        if not axes and self.canvas.underMouse():
            axes = [ax for ax, _ in self._targets(tuple(self.canvas.mouseEventCoords()))]
        if axes:
            self.reset(axes)

    def reset(self, axes):
        """These axes (and only these) fitted to what they show now - hidden series left out."""
        self._stop_glide()
        self._begin()
        for ax in axes:
            ax.set_autoscale_on(True)
            _series.fit(ax)
        self.canvas.draw_idle()
        toolbar = self.canvas.toolbar
        if toolbar is not None:
            toolbar.push_current()

    def _begin(self):
        """Before the first move of a gesture: the view it starts from is Home, if nothing is yet."""
        toolbar = self.canvas.toolbar
        if toolbar is not None and toolbar._nav_stack() is None:
            toolbar.push_current()
        inspector = getattr(self.canvas, 'inspector', None)
        if inspector is not None:
            inspector.clear_hover()

    def _settle(self):
        self._settler.stop()
        self._wheel_targets = None
        toolbar = self.canvas.toolbar
        if toolbar is not None:
            toolbar.push_current()
        inspector = getattr(self.canvas, 'inspector', None)
        if inspector is not None:
            inspector.hover_at_cursor()

    def _pan(self, targets, dx, dy):
        """Moves the view by (dx, dy) display pixels - the content the other way. Gives whether it did."""
        if not dx and not dy:
            return True
        return self._apply([(ax, which, self._limits(ax, which, lambda b: (b.x0 + dx, b.y0 + dy, b.x1 + dx, b.y1 + dy)))
                     for ax, which in targets])

    def _zoom(self, targets, xy, scale):
        """Scales the view by scale (under 1: in) about the display point xy."""
        if not math.isfinite(scale) or scale <= 0 or abs(scale - 1) < 1e-9:
            return True
        px, py = xy
        return self._apply([(ax, which, self._limits(ax, which, lambda b: (px + (b.x0 - px) * scale, py + (b.y0 - py) * scale,
                                                                     px + (b.x1 - px) * scale, py + (b.y1 - py) * scale)))
                     for ax, which in targets])

    @staticmethod
    def _limits(ax, which, corners):
        """The data limits that put the axes' box at the display corners - all worked out before any is
        set, as twinned axes would move again with their twin's new limits."""
        x0, y0, x1, y1 = corners(ax.bbox)
        (left, bottom), (right, top) = ax.transData.inverted().transform([(x0, y0), (x1, y1)])
        return (left, right) if 'x' in which else None, (bottom, top) if 'y' in which else None

    def _drawing(self):
        return bool(getattr(self.canvas, 'drawing', False))

    def _apply(self, changes):
        """The new limits set - not while the figure's drawn in the background (False)."""
        if self._drawing():
            return False
        for ax, which, (xlim, ylim) in changes:
            if xlim is not None and self._sane(xlim):
                ax.set_xlim(xlim)
            if ylim is not None and self._sane(ylim):
                ax.set_ylim(ylim)
        self.canvas.draw_idle()
        return True

    @staticmethod
    def _sane(limits):
        low, high = limits
        if not (math.isfinite(low) and math.isfinite(high)) or low == high:
            return False
        return abs(high - low) > 1e-12 * max(abs(low), abs(high), 1e-300) and max(abs(low), abs(high)) < 1e300

    # ---- the wheel's glide

    def _start_glide(self, targets, xy, log_scale):
        glide = self._glide
        remaining = glide['total'] - glide['done'] if glide and glide['targets'] == targets else 0.0
        self._glide = {'targets': targets, 'xy': xy, 'total': remaining + log_scale, 'done': 0.0,
                       'start': time.perf_counter()}
        self._settler.stop()
        if not self._timer.isActive():
            self._timer.start()

    def _glide_frame(self):
        glide = self._glide
        if glide is None:
            self._timer.stop()
            return
        t = min(1.0, (time.perf_counter() - glide['start']) / self.GLIDE_S)
        reached = glide['total'] * (1 - (1 - t) ** 3)   # cubic ease-out
        if not self._zoom(glide['targets'], glide['xy'], math.exp(reached - glide['done'])):
            return   # drawing still: the next frame catches up
        glide['done'] = reached
        if t >= 1.0:
            self._stop_glide()
            self._settler.start(int(self.SETTLE_S * 1000))

    def _stop_glide(self):
        self._glide = None
        self._timer.stop()

    # ---- where

    def _xy(self, event_or_point):
        return tuple(self.canvas.mouseEventCoords(event_or_point))

    def _ratio(self):
        return self.canvas.device_pixel_ratio or 1.0

    def _toolbar_mode(self):
        toolbar = self.canvas.toolbar
        return bool(toolbar is not None and toolbar.mode)

    @staticmethod
    def _navigable(ax):
        return ax.name == 'rectilinear' and ax.get_navigate() and ax.get_visible()

    def _targets(self, xy):
        """[(axes, 'xy' | 'x' | 'y')]: every axes under the point (twins together), else the axis whose
        tick labels it's on."""
        x, y = xy
        figure = self.canvas.figure
        inside = [(ax, 'xy') for ax in figure.axes if self._navigable(ax) and ax.bbox.contains(x, y)]
        if inside:
            return inside
        for ax, which, box in self._axis_regions():
            if box.contains(x, y):
                return [(ax, which)]
        return []

    def _axis_regions(self):
        if self._axis_boxes is None:
            boxes = []
            try:
                renderer = self.canvas.get_renderer()
                reach = self.AXIS_REACH_PX * self._ratio()
                for ax in self.canvas.figure.axes:
                    if not self._navigable(ax):
                        continue
                    for which, axis in (('x', ax.xaxis), ('y', ax.yaxis)):
                        box = axis.get_tightbbox(renderer)
                        if box is not None and box.width > 0 and box.height > 0:
                            boxes.append((ax, which, box.padded(reach)))
            except Exception:   # no renderer yet, or an axis that can't say
                pass
            self._axis_boxes = boxes
        return self._axis_boxes

    def _over_draggable(self, xy):
        figure = self.canvas.figure
        legends = [ax.get_legend() for ax in figure.axes] + list(figure.legends)
        return any(legend is not None and getattr(legend, '_draggable', None) is not None
                   and legend.get_window_extent().contains(*xy) for legend in legends)
