"""View settings: what the window changes about the figures' look, not what they show - titles and axis
labels, series names, each plot's grid and legend, scales, x and y swapped, locks, a right-hand y
axis, and series added to plots (a run saved as data, a series added to another plot). Series looks
are _style_editor's, where each plot sits is _layout's. Each change goes into the settings file
(_settings) and can be undone (_history); zoom and limits never go in - the data will change. What's
kept of a plot or a series is keyed by its plot's ax_id(), so it follows the plot into another tab.

A series added to another plot is a linked copy: it has no data of its own, only its source's (and
follows it - a run of the sliders, a saved run run again), and by default its look. Hiding, locking,
renaming or deleting one does it to every copy at once. A series of the script's can't be deleted:
removed from its plot it's still there, invisible, and can be added back. restore() puts it all back
when the window opens; reset() takes it off."""
import uuid

import numpy as np
from matplotlib import rcParams
from matplotlib.collections import LineCollection, PathCollection, PolyCollection
from matplotlib.colors import to_rgb
from matplotlib.container import BarContainer
from matplotlib.lines import Line2D
from matplotlib.patches import Rectangle

from . import _animate, _series, _style, _style_editor
from ._history import history
from ._settings import store

TEXTS = {'title': 'title', 'xlabel': 'x label', 'ylabel': 'y label'}
SHADOW_ALPHA = 0.35
BARS_MAX = 3000   # a series of more points than this isn't drawn as bars (each a patch of its own: slow, unreadable)
REFERENCE = ' (reference)'   # a reference copy's name: the series' with this after it
on_reset = []   # what reset() calls besides: the sliders back to their defaults, the plots where the script put them
on_shown = []   # ... and set_visible(): a run's reference shown or hidden with the series it's the shadow of


def _originals(thing):
    """What the script made, before the window changed it - kept on the axes or figure, for reset()."""
    if not hasattr(thing, '_csn_originals'):
        thing._csn_originals = {'texts': {}, 'scales': {}}
    return thing._csn_originals


def _done(*figures):
    store.changed()
    for figure in figures:
        if figure is not None and figure.canvas is not None:
            figure.canvas.draw_idle()


def main_of(ax):
    """The plot an axes is part of: itself, or the plot it's the twin of."""
    return getattr(ax, '_csn_main', None) or ax


def _refit(ax):
    """A series came or went: the plot (its twins too) fitted again to what it holds - recentred,
    however it was zoomed."""
    main = main_of(ax)
    for a in [a for a in main.figure.axes if main_of(a) is main]:
        a.set_autoscale_on(True)
        _series.fit(a)


# ---- titles and axis labels

def text_artist(figure, where):
    """'<ax_id>|title' ('|xlabel', '|ylabel') or the figure's 'suptitle' -> its Text, or None."""
    if where == 'suptitle':
        return getattr(figure, '_suptitle', None)
    identity, _, which = where.rpartition('|')
    ax = _series.axes_of(identity)
    if ax is None or which not in TEXTS:
        return None
    return {'title': ax.title, 'xlabel': ax.xaxis.label, 'ylabel': ax.yaxis.label}[which]


def texts_at(figure):
    """[(where, Text)] for every title and axis label of the figure's plots, and its suptitle."""
    found = []
    for ax in figure.axes:
        identity = _series.ax_id(ax)
        found += [(f"{identity}|title", ax.title), (f"{identity}|xlabel", ax.xaxis.label),
                  (f"{identity}|ylabel", ax.yaxis.label)]
    if getattr(figure, '_suptitle', None) is not None:
        found.append(('suptitle', figure._suptitle))
    return found


def set_text(figure, where, text, record=True):
    _series.quiet()
    artist = text_artist(figure, where)
    if artist is None:
        if where != 'suptitle':
            return
        figure.suptitle(text)
        artist = figure._suptitle
        old = ''
    else:
        old = artist.get_text()
        artist.set_text(text)
    owner = figure if where == 'suptitle' else _series.axes_of(where.rpartition('|')[0])
    original = _originals(owner)['texts'].setdefault(where, old)
    saved = (store.section(figure) if where == 'suptitle' else store.plots()).setdefault('texts', {})
    if text == original:
        saved.pop(where, None)
    else:
        saved[where] = text
    if record:
        name = 'title' if where == 'suptitle' else TEXTS[where.rpartition('|')[2]]
        history.push(f'Edit {name}', lambda: set_text(figure, where, old, False),
                     lambda: set_text(figure, where, text, False))
    _done(owner.figure if owner is not figure else figure)


def set_plot_name(ax, name, record=True):
    """The plot's name where it's listed (its title stays as it is) - '' or its own name: none given."""
    ax = main_of(ax)
    names = store.plots().setdefault('names', {})
    identity = _series.ax_id(ax)
    old, name = names.get(identity, ''), (name or '').strip()
    if name == _series.plot_name(ax, given=False):
        name = ''
    if name == old:
        return
    if name:
        names[identity] = name
    else:
        names.pop(identity, None)
    if record:
        history.push('Rename plot', lambda: set_plot_name(ax, old, False), lambda: set_plot_name(ax, name, False))
    _done(ax.figure)


# ---- series names, showing and locking - every copy at once

def rename(key, name, record=True):
    s = _series.find(key)
    if s is None or not name:
        return
    _series.quiet()
    old = s.label
    for member in _series.members(s) or [s]:
        reference = member.label.endswith(REFERENCE) and not old.endswith(REFERENCE)
        _rename_one(member, name + REFERENCE if reference else name)
    if record:
        history.push('Rename series', lambda: rename(key, old, False), lambda: rename(key, name, False))
    _done(*{m.ax.figure for m in _series.members(s) or [s]})


def _rename_one(s, name):
    old = s.label
    s.artist.set_label(name)
    s.label = name
    for legend in [s.ax.get_legend(), *s.ax.figure.legends]:
        if legend is not None:
            for text in legend.get_texts():
                if text.get_text() == old:
                    text.set_text(name)
    key = _series.key_of(s)
    names = store.plots().setdefault('names', {})
    if name == _series.name_of(s):
        names.pop(key, None)
    else:
        names[key] = name
    for entry in store.plots().get('added', []):   # an added series keeps its name in its entry
        if entry['id'] == _series.added(s):
            entry['label'] = name


def set_visible(key, shown, record=True):
    s = _series.find(key)
    if s is None:
        return
    _series.quiet()
    hidden = store.plots().setdefault('hidden', [])
    every = _series.members(s) or [s]
    for member in every:   # it comes or goes there, the way of its kind, once drawn
        animate = getattr(member.ax.figure.canvas, 'animate_change', None)
        if animate is not None and member.visible() != shown:
            animate([member.ax], shown, _animate.mode_of(member), _animate.artists_of(member))
    for member in every:
        member.set_visible(shown)
        member_key = _series.key_of(member)
        if shown and member_key in hidden:
            hidden.remove(member_key)
        elif not shown and member_key not in hidden:
            hidden.append(member_key)
    for hook in on_shown:
        hook()
    if record:
        history.push('Show series' if shown else 'Hide series', lambda: set_visible(key, not shown, False),
                     lambda: set_visible(key, shown, False))
    _done(*{m.ax.figure for m in every})


def locked(s):
    """A locked series can't be renamed, restyled, deleted or run again - only looked at (and added to
    other plots). Its copies are locked with it."""
    if s is None:
        return False
    saved = store.plots().get('locked', [])
    return _series.link_of(s) in saved or _series.key_of(s) in saved


def set_locked(series, on, record=True):
    links = list(dict.fromkeys(_series.link_of(s) for s in series))
    saved = store.plots().setdefault('locked', [])
    before = [link in saved for link in links]
    _put_locks(links, [on] * len(links))
    if record:
        history.push('Lock' if on else 'Unlock', lambda: _put_locks(links, before),
                     lambda: _put_locks(links, [on] * len(links)))
    store.changed()


def _put_locks(links, states):
    saved = store.plots().setdefault('locked', [])
    for link, on in zip(links, states):
        if on and link not in saved:
            saved.append(link)
        elif not on and link in saved:
            saved.remove(link)
    store.changed()


# ---- each plot's grid and legend

DEFAULT_GRID = {'on': True, 'minor': False, 'axis': 'both', 'style': '-', 'alpha': 1.0}


def grid(ax):
    main = main_of(ax)
    saved = store.plots().get('grids', {}).get(_series.ax_id(main))
    return dict(getattr(main, '_csn_grid', None) or saved or {**DEFAULT_GRID, 'on': bool(rcParams['axes.grid'])})


def set_grid(ax, record=True, **changes):
    main = main_of(ax)
    old = grid(main)
    new = {**old, **changes}
    _series.quiet()
    _put_grid(main, new)
    store.plots().setdefault('grids', {})[_series.ax_id(main)] = new
    if record:
        history.push('Change grid', lambda: set_grid(main, False, **old), lambda: set_grid(main, False, **new))
    _done(main.figure)


def _put_grid(ax, options):
    """The plot's grid, as the options say. Its right-hand y axis draws none of its own: drawn after
    the plot, its lines would cross the plot's series (and not meet its ticks)."""
    ax._csn_grid = options
    ax.grid(False, which='both')
    for twin in [*getattr(ax, '_csn_twins', []), *ax._twinned_axes.get_siblings(ax)]:
        if twin is not ax:
            twin.grid(False, which='both')
    if options['minor'] and options['on']:
        ax.minorticks_on()
    elif getattr(ax, '_csn_minor', False):   # only the minor ticks this turned on
        ax.minorticks_off()
    ax._csn_minor = options['minor'] and options['on']
    if options['on']:
        ax.grid(True, which='major', axis=options['axis'], linestyle=options['style'], alpha=options['alpha'])
        if options['minor']:
            ax.grid(True, which='minor', axis=options['axis'], linestyle='-', linewidth=0.5,
                    color=_style.GRID_MINOR, alpha=options['alpha'])


def legend_shown(ax):
    legend = main_of(ax).get_legend()
    return legend is not None and legend.get_visible()


def set_legend(ax, on, record=True):
    """The plot's legend shown or not - made, if it had none and there's something to list."""
    main = main_of(ax)
    _series.quiet()
    before = legend_shown(main)
    _put_legend(main, on)
    store.plots().setdefault('legends', {})[_series.ax_id(main)] = bool(on)
    if record and before != on:
        history.push('Show legend' if on else 'Hide legend', lambda: set_legend(main, before, False),
                     lambda: set_legend(main, on, False))
    _done(main.figure)


def _put_legend(ax, on):
    legend = ax.get_legend()
    if on and legend is None:
        handles, _ = ax.get_legend_handles_labels()
        for twin in getattr(ax, '_csn_twins', []):
            handles += twin.get_legend_handles_labels()[0]
        if handles:
            ax.legend(handles=handles)
    elif legend is not None:
        legend.set_visible(on)


# ---- scales

def set_scale(ax, axis, scale, record=True):
    """An axis linear, log or symlog."""
    old = ax.get_xscale() if axis == 'x' else ax.get_yscale()
    if scale == old:
        return
    _series.quiet()
    original = _originals(ax)['scales'].setdefault(axis, old)
    (ax.set_xscale if axis == 'x' else ax.set_yscale)(scale)
    _series.safe_limits(ax)   # a log axis over data at 0 and below
    saved = store.plots().setdefault('scales', {})
    where = f"{_series.ax_id(ax)}|{axis}"
    if scale == original:
        saved.pop(where, None)
    else:
        saved[where] = scale
    if record:
        history.push(f'{axis} scale {scale}', lambda: set_scale(ax, axis, old, False),
                     lambda: set_scale(ax, axis, scale, False))
    _done(ax.figure)


# ---- series added through the window: saved runs, and copies in other plots

def entry_from(s, label, shadow=False, **extra):
    """What the settings file keeps of a series with its data, to draw it again (a saved run)."""
    x, y = s.floats()
    return {'id': uuid.uuid4().hex[:12], 'axes': _series.ax_id(s.ax), 'kind': 'scatter' if s.kind == 'scatter' else 'line',
            'label': label, 'x': np.array(x, dtype=float), 'y': np.array(y, dtype=float),
            'look': _style_editor.look(s), 'shadow': shadow, **extra}


def copy_entry(s, ax, shadow=False):
    """A linked copy of the series for that plot: its source's data, whatever it is then."""
    kind = s.kind if s.kind in ('scatter', 'bars') else 'line'
    return {'id': uuid.uuid4().hex[:12], 'axes': _series.ax_id(ax), 'kind': kind,
            'label': s.label + (REFERENCE if shadow else ''), 'link': _series.link_of(s),
            'look': _style_editor.look(s), 'own_look': bool(shadow), 'shadow': bool(shadow)}


def entries(run=None):
    """The added series' entries - those of one saved run, if it's given."""
    return [e for e in store.plots().get('added', []) if run is None or e.get('run') == run]


def entry_of(s):
    identity = _series.added(s)
    return next((e for e in entries() if e['id'] == identity), None) if identity else None


def series_of_entry(entry_id):
    for figure in _series.figures():
        for ax in figure.axes:
            for s in _series.series(ax, everything=True):
                if _series.added(s) == entry_id:
                    return s
    return None


def source_of(s):
    """The series a copy shows - None for one that isn't a copy, or whose source isn't drawn."""
    link = getattr(s.artist, '_csn_link', None)
    return _series.find(link) if link else None


def add_series(entry, record=True, refit=None):
    """The entry drawn in its plot (a copy: once its source is drawn) and kept in the settings - the
    plot recentred on what it holds then, when it's added by hand or undone or redone (refit)."""
    ax = _series.axes_of(entry['axes'])
    saved = store.plots().setdefault('added', [])
    if ax is None:
        return None
    _series.quiet()
    new = not any(e['id'] == entry['id'] for e in saved)
    if new:
        saved.append(entry)

    def recorded():
        if record:
            history.push('Add series', lambda: remove_series(entry['id'], False, refit=True),
                         lambda: add_series(entry, False, refit=True))
    data = _entry_data(entry)
    if data is None or series_of_entry(entry['id']) is not None:
        recorded()
        store.changed()
        return None
    try:
        artist = _draw_entry(ax, entry, *data)
    except BaseException:   # not drawn after all (stopped): not kept either
        if new and entry in saved:
            saved.remove(entry)
        raise
    recorded()
    s = next((s for s in _series.series(ax, everything=True) if s.artist is artist), None)
    source = source_of(s) if s is not None else None
    look = _style_editor.look(source) if source is not None and not entry.get('own_look') else entry.get('look')
    if s is not None and look:
        _style_editor.apply(s, remember=False, everywhere=False, **look)
    if entry.get('shadow'):
        _set_alpha(s, SHADOW_ALPHA)
    if s is not None and _series.key_of(s) in store.plots().get('hidden', []):
        s.set_visible(False)
    if record if refit is None else refit:
        _refit(ax)
    else:
        _series.fit(ax)
    legend_again(ax)
    _done(ax.figure)
    return artist


def _entry_data(entry):
    if 'x' in entry:
        return np.asarray(entry['x']), np.asarray(entry['y'])
    source = _series.find(entry.get('link', ''))
    if source is None:
        return None
    entry['_token'] = _token(source)
    return source.data()


def _draw_entry(ax, entry, x, y):
    label, kind = entry['label'], entry['kind']
    if kind == 'scatter':
        artist = ax.scatter(x, y, label=label)
    elif kind == 'bars':
        source = _series.find(entry.get('link', ''))
        widths = [r.get_width() for r in source.artist.patches] if source is not None and source.kind == 'bars' \
            else _bar_width(x)
        before = len(ax.patches)
        try:
            artist = ax.bar(x, y, width=widths, label=label)
        except BaseException:   # stopped part way (the watchdog): none of its bars left behind
            for patch in list(ax.patches)[before:]:
                patch.remove()
            raise
    else:
        artist, = ax.plot(x, y, label=label)
        if artist.get_linewidth() <= 0:
            artist.set_linewidth(rcParams['lines.linewidth'])
    artist._csn_added, artist._csn_run = entry['id'], entry.get('run')
    artist._csn_name, artist._csn_link = entry.get('name', entry['label']), entry.get('link')
    artist._csn_token = entry.pop('_token', None)
    return artist


def _bar_width(x):
    """Bars for points this far apart: 0.8 of the usual gap between them (in days, for dates)."""
    try:
        values = np.asarray(x)
        if np.issubdtype(values.dtype, np.datetime64):
            from matplotlib.dates import date2num
            values = date2num(values)
        values = values.astype(float)
        values = np.unique(values[np.isfinite(values)])
    except (TypeError, ValueError):
        return 0.8
    return 0.8 * float(np.median(np.diff(values))) if len(values) > 1 else 0.8


def _set_alpha(s, alpha):
    if s is None:
        return
    for artist in (s.artist.patches if s.kind == 'bars' else [s.artist]):
        artist.set_alpha(alpha)


def _token(s):
    """What a series' data is now - changed when it's drawn anew or given new data."""
    artist = s.artist
    if s.kind == 'line':
        return id(artist), id(artist._xorig), id(artist._yorig)
    if s.kind == 'scatter':
        return id(artist), id(artist._offsets)
    return (id(artist),)


def remove_series(entry_id, record=True, refit=None):
    saved = store.plots().setdefault('added', [])
    entry = next((e for e in saved if e['id'] == entry_id), None)
    _series.quiet()
    figure = None
    found = series_of_entry(entry_id)
    if found is not None:
        if entry is not None:   # its look and name as they are now, for the undo
            entry['look'], entry['label'] = _style_editor.look(found), found.label
        figure = found.ax.figure
        found.artist.remove()
        if record if refit is None else refit:
            _refit(found.ax)
        legend_again(found.ax)
    if entry is not None:
        saved[:] = [e for e in saved if e is not entry]   # not remove(): == on its arrays means nothing
        if record:
            history.push('Delete series', lambda: add_series(entry, False, refit=True),
                         lambda: remove_series(entry_id, False, refit=True))
    _done(figure)


def set_removed(key, on, record=True, refit=None):
    """A series of the script's taken out of its plot (it's still there, invisible) - or put back."""
    _series.quiet()
    removed = store.plots().setdefault('removed', [])
    if on == (key in removed):
        return
    s = _series.find(key)
    if on:
        removed.append(key)
    else:
        removed.remove(key)
    if s is not None:
        s.set_visible(not on and key not in store.plots().get('hidden', []))
        if record if refit is None else refit:
            _refit(s.ax)
        legend_again(s.ax)
    if record:
        history.push('Remove series from plot' if on else 'Add series back',
                     lambda: set_removed(key, not on, False, refit=True), lambda: set_removed(key, on, False, refit=True))
    _done(s.ax.figure if s is not None else None)


def _copy_plan(s, ax, shadow=False):
    """How the series gets into that plot: ('home', key) - back where the script drew it; ('copy',
    entry, note) - a linked copy, in its look unless that colour is already used there; ('there',
    note) - it's there already."""
    home = _series.find(_series.link_of(s))
    if home is not None and home.ax is ax and not shadow:
        return 'home', _series.key_of(home)
    if not shadow and any(_series.link_of(other) == _series.link_of(s) and not other.label.endswith(REFERENCE)
                          for other in _series.series(ax)):
        return 'there', f"“{s.label}” is in that plot already"
    entry = copy_entry(s, ax, shadow)
    note = None
    there = [other for a in ax.figure.axes if main_of(a) is main_of(ax) for other in _series.series(a)]
    if not shadow and not _style_editor.chosen_colour(s) and any(_near(s.colour(), other.colour()) for other in there):
        colour = next((c for c in _style.SERIES if not any(_near(c, other.colour()) for other in there)), None)
        if colour is not None:
            entry['own_look'] = True
            entry['look'] = {**entry['look'], 'colour': colour}
            note = f"“{s.label}” has a colour of its own in that plot: its colour is used there already"
    return 'copy', entry, note


def _near(first, second):
    """Two colours hard to tell apart on a plot."""
    try:
        a, b = np.array(to_rgb(first)), np.array(to_rgb(second))
    except ValueError:
        return False
    return float(np.abs(a - b).sum()) < 0.25


def copy_to(s, ax, shadow=False, record=True):
    """The series in another plot as well. Gives what to say about it, or None."""
    _series.quiet()
    plan = _copy_plan(s, ax, shadow)
    if plan[0] == 'home':
        set_removed(plan[1], False, record)
        return None
    if plan[0] == 'there':
        return plan[1]
    add_series(plan[1], record)
    return plan[2]


def remove_from_plot(s, record=True):
    """Out of this plot: a copy is deleted, a series of the script's is taken out (still there)."""
    if _series.added(s) is not None:
        remove_series(_series.added(s), record)
    else:
        set_removed(_series.key_of(s), True, record)


def delete_everywhere(s):
    """The series out of every plot it's in - as one change."""
    every = _series.members(s) or [s]
    copies = [e for e in (entry_of(m) for m in every if _series.added(m) is not None) if e is not None]
    keys = [_series.key_of(m) for m in every if _series.added(m) is None]

    def forward():
        for entry in copies:
            remove_series(entry['id'], False)
        for key in keys:
            set_removed(key, True, False)

    def back():
        for key in keys:
            set_removed(key, False, False)
        for entry in copies:
            add_series(entry, False)
    forward()
    history.push('Delete series', back, forward)


def move_to_plot(s, ax):
    """Into another plot (another tab, the right-hand y axis), out of this one - as one change. Gives
    what to say about it, or None."""
    if s.ax is ax:
        return None
    _series.quiet()
    plan = _copy_plan(s, ax)
    if plan[0] == 'there':
        return plan[1]
    entry, key = entry_of(s), _series.key_of(s)

    def forward():
        if plan[0] == 'home':
            set_removed(plan[1], False, False)
        else:
            add_series(plan[1], False)
        if entry is not None:
            remove_series(entry['id'], False)
        else:
            set_removed(key, True, False)

    def back():
        if entry is not None:
            add_series(entry, False)
        else:
            set_removed(key, False, False)
        if plan[0] == 'home':
            set_removed(plan[1], True, False)
        else:
            remove_series(plan[1]['id'], False)
    forward()
    history.push('Move series', back, forward)
    return plan[2] if plan[0] == 'copy' else None


def sync_copies():
    """Every copy showing its source as it is now: drawn once its source is, its data and (unless it
    has a look of its own) its look following."""
    for entry in list(entries()):
        if 'x' in entry or not entry.get('link'):
            continue
        source = _series.find(entry['link'])
        if source is None:
            continue
        s = series_of_entry(entry['id'])
        if s is None:
            add_series(entry, record=False)
            continue
        if getattr(s.artist, '_csn_token', None) != _token(source):
            _give_data(s, entry, source)
        if not entry.get('own_look'):
            wanted = _style_editor.look(source)
            now = _style_editor.look(s)
            changes = {k: v for k, v in wanted.items() if now.get(k) != v}
            if changes:
                _style_editor.apply(s, remember=False, everywhere=False, **changes)
            if entry.get('shadow'):
                _set_alpha(s, SHADOW_ALPHA)


def _give_data(s, entry, source):
    x, y = source.data()
    if s.kind == 'line':
        s.artist.set_data(x, y)
    elif s.kind == 'scatter':
        s.artist.set_offsets(np.column_stack([np.asarray(x, dtype=float), np.asarray(y, dtype=float)]))
    else:   # bars: drawn again
        look = _style_editor.look(s)
        s.artist.remove()
        artist = _draw_entry(s.ax, entry, x, y)
        again = next((o for o in _series.series(s.ax, everything=True) if o.artist is artist), None)
        if again is not None:
            _style_editor.apply(again, remember=False, everywhere=False, **look)
        s = again or s
    s.artist._csn_token = _token(source)
    _series.fit(s.ax)


def redraw_as(s, kind, record=True):
    """A series of the script's drawn as another kind ('line', 'scatter' or 'bars'): out of its plot,
    and a linked copy of it in its place, drawn that way - as one change."""
    key = _series.key_of(s)
    entry = copy_entry(s, s.ax)
    entry.update(kind=kind, in_place_of=key, name=f"{_series.name_of(s)} ({kind})")

    def forward():
        add_series(entry, False)
        set_removed(key, True, False)

    def back():
        remove_series(entry['id'], False)
        set_removed(key, False, False)
    forward()
    if record:
        history.push('Change series type', back, forward)


def set_kind(entry_id, kind, record=True):
    """A copy drawn as a line, a scatter or bars - one in place of the script's series, as that again:
    the script's series itself."""
    entry = next((e for e in entries() if e['id'] == entry_id), None)
    if entry is None or entry['kind'] == kind:
        return
    home = _series.find(entry['in_place_of']) if entry.get('in_place_of') else None
    if home is not None and (home.kind == kind or home.kind == 'line' == kind[:4]):
        def forward():
            remove_series(entry_id, False)
            set_removed(entry['in_place_of'], False, False)

        def back():
            add_series(entry, False)
            set_removed(entry['in_place_of'], True, False)
        forward()
        if record:
            history.push('Change series type', back, forward)
        return
    old = entry['kind']
    remove_series(entry_id, record=False)
    entry['kind'] = kind
    if entry.get('name'):
        entry['name'] = _kind_named(entry['name'], old, kind)
    try:
        add_series(entry, record=False)
    except BaseException:   # stopped: as it was
        entry['kind'] = old
        if entry.get('name'):
            entry['name'] = _kind_named(entry['name'], kind, old)
        add_series(entry, record=False)
        raise
    if record:
        history.push('Change series type', lambda: set_kind(entry_id, old, False), lambda: set_kind(entry_id, kind, False))


def _kind_named(name, old, kind):
    """A copy's name saying the kind it's drawn as: "x (bars)" drawn as a scatter is "x (scatter)"."""
    if name and name.endswith(f' ({old})'):
        return name[:-len(f' ({old})')] + f' ({kind})'
    return name


def legend_again(ax):
    """A legend made before a series came or went, made again to list what's there now."""
    legend = ax.get_legend()
    if legend is None:
        return
    shown = getattr(legend, '_csn_shown', legend.get_visible())
    if not ax.get_legend_handles_labels()[0]:   # nothing named left to list: hidden, not made empty
        legend._csn_shown = shown
        legend.set_visible(False)
        return
    try:
        ax.legend(loc=legend._loc, ncols=getattr(legend, '_ncols', 1))
    except (TypeError, ValueError, AttributeError):
        ax.legend()
    if ax.get_legend() is not None:
        ax.get_legend().set_visible(shown)


# ---- a right-hand y axis

def right_axis(ax, create=True, record=True):
    """The plot's right-hand y axis (a twinx) - made, if it has none and create."""
    main = main_of(ax)
    for twin in [*getattr(main, '_csn_twins', []), *main._twinned_axes.get_siblings(main)]:
        if twin is not main and twin in main.figure.axes and twin.yaxis.get_label_position() == 'right' \
                and main._shared_axes['x'].joined(main, twin):
            return twin
    if not create:
        return None
    _series.quiet()
    twin = main.twinx()
    twin.grid(False, which='both')   # the plot's grid serves both (_put_grid)
    twin._csn_id = f"{_series.ax_id(main)}/right"
    twin._csn_made_twin, twin._csn_main = True, main
    twin._csn_shares = {'x': [main], 'y': []}
    if hasattr(main, '_csn_twins'):
        main._csn_twins.append(twin)
    twins = store.plots().setdefault('twins', [])
    if _series.ax_id(main) not in twins:
        twins.append(_series.ax_id(main))
    store.changed()
    return twin


def _drop_made_twins():
    for figure in _series.figures():
        for ax in list(figure.axes):
            if getattr(ax, '_csn_made_twin', False):
                main = ax._csn_main
                if ax in getattr(main, '_csn_twins', []):
                    main._csn_twins.remove(ax)
                figure.delaxes(ax)


# ---- x and y swapped

def swapped(ax):
    return _series.ax_id(main_of(ax)) in store.plots().get('swapped', [])


def can_swap(ax):
    """None if the plot's x and y can swap, else why not."""
    main = main_of(ax)
    if any(a is not main for a in main._twinned_axes.get_siblings(main)) or getattr(main, '_csn_twins', None):
        return 'It has a second y axis'
    for name in ('x', 'y'):
        if any(a is not main for a in main._shared_axes[name].get_siblings(main)):
            return f"It shares its {name} axis with other plots"
    return None


def swap_xy(ax, record=True):
    main = main_of(ax)
    if can_swap(main) is not None:
        return can_swap(main)
    _series.quiet()
    on = not swapped(main)
    _swap(main, on, everything=True)
    saved = store.plots().setdefault('swapped', [])
    identity = _series.ax_id(main)
    if on:
        saved.append(identity)
    else:
        saved.remove(identity)
    if record:
        history.push('Swap x and y', lambda: swap_xy(main, False), lambda: swap_xy(main, False))
    _done(main.figure)
    return None


def _swap(ax, flag, everything):
    """The plot turned (flag) or back: every artist of it with x and y swapped - all, or, not
    everything, those not turned yet (a run's) - and with everything, its labels, scales, units and
    limits."""
    for artist in ax._children:   # a bar's rectangles are there too
        if not everything and getattr(artist, '_csn_swapped', False) == flag:
            continue
        if _swap_artist(ax, artist):
            artist._csn_swapped = flag
    for container in ax.containers:
        if isinstance(container, BarContainer) and getattr(container, 'orientation', None) in ('vertical', 'horizontal'):
            if not everything and getattr(container, '_csn_swapped', False) == flag:
                continue
            container.orientation = 'horizontal' if container.orientation == 'vertical' else 'vertical'
            container._csn_swapped = flag
    if everything or getattr(ax, '_csn_swap_labels', None) != (ax.get_xlabel(), ax.get_ylabel()):
        xlabel, ylabel = ax.get_xlabel(), ax.get_ylabel()
        ax.set_xlabel(ylabel)
        ax.set_ylabel(xlabel)
        ax._csn_swap_labels = (ax.get_xlabel(), ax.get_ylabel())
    if not everything:
        return
    xscale, yscale = ax.get_xscale(), ax.get_yscale()
    xlim, ylim = ax.get_xlim(), ax.get_ylim()
    for axis in (ax.xaxis, ax.yaxis):   # units (dates) belong to the data, which has moved
        axis._converter, axis.units, axis._converter_is_explicit = None, None, False
    ax.set_xscale(yscale)
    ax.set_yscale(xscale)
    for s in _series.series(ax, everything=True):
        x, y = s.data()
        for axis, values in ((ax.xaxis, x), (ax.yaxis, y)):
            if np.asarray(values).dtype.kind in 'MOU':
                axis.update_units(values)
        break
    ax.set_xlim(ylim)
    ax.set_ylim(xlim)


def _swap_artist(ax, artist):
    if isinstance(artist, Line2D):
        if artist.get_transform() is not ax.transData:
            return False
        artist.set_data(artist.get_ydata(orig=True), artist.get_xdata(orig=True))
    elif isinstance(artist, PathCollection):
        offsets = np.asarray(artist.get_offsets())
        if not len(offsets):
            return False
        artist.set_offsets(offsets[:, ::-1])
    elif isinstance(artist, LineCollection):
        artist.set_segments([np.asarray(segment)[:, ::-1] for segment in artist.get_segments()])
    elif isinstance(artist, PolyCollection):
        artist.set_verts([path.vertices[:, ::-1] for path in artist.get_paths()])
    elif isinstance(artist, Rectangle) and artist is not ax.patch:
        x, y, w, h = artist.get_x(), artist.get_y(), artist.get_width(), artist.get_height()
        artist.set_bounds(y, x, h, w)
    else:
        return False
    return True


# ---- the window opening, a run drawn, and resetting

def restore():
    """Everything saved, put back - once, as the window first opens (every figure the script made is
    there by then)."""
    plots = store.plots()
    for identity in list(plots.get('twins', [])):
        ax = _series.axes_of(identity)
        if ax is not None:
            right_axis(ax, record=False)
    for entry in list(plots.get('added', [])):
        add_series(entry, record=False)
    grids = plots.get('grids', {})
    for figure in _series.figures():
        section = store.section(figure)
        for ax in figure.axes:
            identity = _series.ax_id(ax)
            if identity in grids:
                _put_grid(ax, {**grid(ax), **grids[identity]})
            elif 'grid' in section and main_of(ax) is ax:   # kept for the whole tab, as it used to be
                _put_grid(ax, {**grid(ax), **section['grid']})
            elif main_of(ax) is not ax:   # a twin the script made: no grid over the plot's series
                ax.grid(False, which='both')
        for where, text in dict(section.get('texts', {})).items():
            set_text(figure, where, text, record=False)
    for where, scale in dict(plots.get('scales', {})).items():
        identity, _, axis = where.rpartition('|')
        ax = _series.axes_of(identity)
        if ax is not None:
            set_scale(ax, axis, scale, record=False)
    for identity in list(plots.get('swapped', [])):
        ax = _series.axes_of(identity)
        if ax is not None and can_swap(ax) is None:
            _swap(ax, True, everything=True)
        elif identity in plots['swapped']:
            plots['swapped'].remove(identity)
    reapply()


def reapply():
    """Names, looks, hidden and removed series, legends, swapped plots, copies and edited labels - onto
    the series and plots as they are now (the sliders draw them anew)."""
    plots = store.plots()
    for identity in plots.get('swapped', []):   # what a run drew, the way the plot is turned
        ax = _series.axes_of(identity)
        if ax is not None:
            _swap(ax, True, everything=False)
    for key, name in dict(plots.get('names', {})).items():
        s = _series.find(key)
        if s is not None and s.label != name:
            _rename_one(s, name)
    _style_editor.reapply()
    for key in list(plots.get('hidden', [])):
        s = _series.find(key)
        if s is not None:
            s.set_visible(False)
    for key in plots.get('removed', []):
        s = _series.find(key)
        if s is not None:
            s.set_visible(False)
    sync_copies()
    for identity, on in plots.get('legends', {}).items():
        ax = _series.axes_of(identity)
        if ax is not None:
            _put_legend(ax, on)
    for where, text in dict(plots.get('texts', {})).items():
        ax = _series.axes_of(where.rpartition('|')[0])
        if ax is not None:
            set_text(ax.figure, where, text, record=False)


def reset():
    """Every view setting off every plot, as the script made them - and out of the file."""
    _series.quiet()
    for entry in list(store.plots().get('added', [])):
        remove_series(entry['id'], record=False)
    for identity in list(store.plots().get('swapped', [])):
        ax = _series.axes_of(identity)
        if ax is not None:
            _swap(ax, False, everything=True)
    store.plots()['removed'] = []
    _drop_made_twins()
    for hook in list(on_reset):   # the plots back in their own tabs first, then their looks
        hook()
    for figure in _series.figures():
        for where, text in _originals(figure)['texts'].items():
            set_text(figure, where, text, record=False)
        for ax in figure.axes:
            originals = _originals(ax)
            for where, text in originals['texts'].items():
                set_text(figure, where, text, record=False)
            for axis, scale in originals['scales'].items():
                set_scale(ax, axis, scale, record=False)
            for s in _series.series(ax, everything=True):
                s.set_visible(True)
                if s.label != _series.name_of(s):
                    _rename_one(s, _series.name_of(s))
                first = getattr(s.artist, '_csn_look0', None)
                if first:
                    _style_editor.apply(s, remember=False, everywhere=False, **first)
            ax._csn_grid = None
            _put_grid(ax, {**DEFAULT_GRID, 'on': bool(rcParams['axes.grid'])})
            ax._csn_grid = None
            if ax.get_legend() is not None:
                ax.get_legend().set_visible(True)
    store.clear()
    for figure in _series.figures():
        figure.canvas.draw_idle()
