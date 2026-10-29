"""Where the plots sit: the Layout tab of the side panel, and arranging them on the plot itself.
Pick an arrangement - side by side, stacked, a big plot with two small beside it, a grid... - and the
tab's plots fill it in order. The map under it (and the plot, while 'Arrange on the plot' is on) is
the tab's grid: drag a plot onto another to swap them, or onto an empty cell to move it there; drag
the lines between them to resize; click one to hide it, move it to another tab or a new one, or
change its scales. Hidden plots aren't deleted - they're listed under the map, to show again. 'Add a
plot' makes an empty one, for series of other plots (the Plot tab's Add series), and a plot's menu
copies it (copy_plot: its labels and scales, linked copies of its series); a plot added so can be
deleted again, the script's own only hidden. Plots left to arrange themselves (one more, one fewer)
are never put in a row: two stacked, three as a big one with two beside it, five as two over three,
more in a grid. An empty cell's menu (here, or right-clicking the
empty space on the plot) moves any plot of any open tab into it, or makes a new one there.
A tab once arranged is a GridSpec of its own under matplotlib's constrained layout (so labels don't
overlap; the tight one where a colorbar needs it); a tab never arranged keeps the script's own
layout. Moving a plot to another tab moves the Axes itself - its twins (twinx) and colorbars with
it - into the other figure, which matplotlib has no way to do: see _move(). Every change goes
through one snapshot of the whole layout (_put): undo and redo put the one before or after, and the
settings file keeps the last."""
import copy
import math
import sys
import traceback
import weakref

from matplotlib.gridspec import GridSpec, GridSpecFromSubplotSpec
from matplotlib.layout_engine import ConstrainedLayoutEngine, TightLayoutEngine
from PySide6 import QtCore, QtGui, QtWidgets

from . import _series, _style, _view
from ._history import history
from ._settings import figure_key, store
from ._widgets import Section

Qt = QtCore.Qt
SCALES = ('linear', 'log', 'symlog')


def _grid(name, rows, cols):
    return name, rows, cols, [(r, r + 1, c, c + 1) for r in range(rows) for c in range(cols)], None, None


# (name, rows, columns, cells (first row, row after, first column, column after), widths, heights)
TEMPLATES = [
    _grid('One plot', 1, 1),
    _grid('Side by side', 1, 2),
    _grid('Stacked', 2, 1),
    _grid('Three side by side', 1, 3),
    _grid('Three stacked', 3, 1),
    ('A big one, two beside it', 2, 2, [(0, 2, 0, 1), (0, 1, 1, 2), (1, 2, 1, 2)], (3, 2), None),
    ('A big one, two under it', 2, 2, [(0, 1, 0, 2), (1, 2, 0, 1), (1, 2, 1, 2)], None, (3, 2)),
    ('Two beside a big one', 2, 2, [(0, 2, 1, 2), (0, 1, 0, 1), (1, 2, 0, 1)], (2, 3), None),
    ('Two over a wide one', 2, 2, [(1, 2, 0, 2), (0, 1, 0, 1), (0, 1, 1, 2)], None, (2, 3)),
    ('A big one, three beside it', 3, 2, [(0, 3, 0, 1), (0, 1, 1, 2), (1, 2, 1, 2), (2, 3, 1, 2)], (3, 2), None),
    ('A big one, three under it', 2, 3, [(0, 1, 0, 3), (1, 2, 0, 1), (1, 2, 1, 2), (1, 2, 2, 3)], None, (3, 2)),
    _grid('Two by two', 2, 2),
    ('A big one, four beside it', 2, 3, [(0, 2, 0, 1), (0, 1, 1, 2), (0, 1, 2, 3), (1, 2, 1, 2), (1, 2, 2, 3)],
     (2, 1, 1), None),
    ('A big one, four under it', 2, 4, [(0, 1, 0, 4), (1, 2, 0, 1), (1, 2, 1, 2), (1, 2, 2, 3), (1, 2, 3, 4)],
     None, (3, 2)),
    ('Two over three', 2, 6, [(0, 1, 0, 3), (0, 1, 3, 6), (1, 2, 0, 2), (1, 2, 2, 4), (1, 2, 4, 6)], None, None),
    ('Three over two', 2, 6, [(0, 1, 0, 2), (0, 1, 2, 4), (0, 1, 4, 6), (1, 2, 0, 3), (1, 2, 3, 6)], None, None),
    ('Two by two, one wide under them', 3, 2, [(0, 1, 0, 1), (0, 1, 1, 2), (1, 2, 0, 1), (1, 2, 1, 2), (2, 3, 0, 2)],
     None, None),
    _grid('Two rows of three', 2, 3),
    _grid('Three rows of two', 3, 2),
    _grid('Three by three', 3, 3),
]

_known = weakref.WeakValueDictionary()   # ax_id -> every plot there's been (its main axes, not its twins)
_current = None    # the layout as it is - None: every tab as its script made it
_opening = False   # last time's being put back: tabs made now open behind the first one


def _empty():
    return {'tabs': {}, 'new_tabs': [], 'added': []}


def snapshot():
    return copy.deepcopy(_current) if _current is not None else _empty()


# ---- a tab's plots

def plots(figure):
    """The figure's plots in its order - a plot and its twins (twinx, twiny) are one, a colorbar is
    its plot's."""
    found = []
    for ax in figure.axes:
        if hasattr(ax, '_colorbar'):
            continue
        main = _main(ax)
        if main not in found:
            found.append(main)
    return found


def _main(ax):
    main = getattr(ax, '_csn_main', None)
    if main is not None:
        return main
    siblings = ax._twinned_axes.get_siblings(ax)
    return next((a for a in ax.figure.axes if a in siblings), ax)


def _members(main):
    """The plot, its twins and its colorbars: what moves together."""
    if hasattr(main, '_csn_twins'):
        return [main, *main._csn_twins, *main._csn_bars]
    siblings = main._twinned_axes.get_siblings(main)
    return [main, *(a for a in main.figure.axes if a in siblings and a is not main)]


def _remember(figure):
    """How the script left the figure and its plots - what they go back to - noted before anything
    changes them; and every plot known by its ax_id()."""
    if not hasattr(figure, '_csn_engine0'):
        figure._csn_engine0 = figure.get_layout_engine()
        figure._csn_margins0 = {name: getattr(figure.subplotpars, name)
                                for name in ('left', 'right', 'bottom', 'top', 'wspace', 'hspace')}
    for main in plots(figure):
        if hasattr(main, '_csn_twins'):
            continue
        twins = _members(main)[1:]
        main._csn_twins = twins
        main._csn_bars = [a for a in figure.axes if hasattr(a, '_colorbar') and any(
            parent is main or parent in twins for parent in (getattr(a, '_colorbar_info', None) or {}).get('parents', []))]
        for ax in _members(main):
            ax._csn_main = main
            spec = ax.get_subplotspec()
            grid = spec.get_gridspec() if spec is not None else None
            ax._csn_place0 = {'figure': figure, 'spec': spec, 'position': ax.get_position(original=True).frozen(),
                              'visible': ax.get_visible(), 'in_layout': ax.get_in_layout(),
                              'outer': (grid, grid._subplot_spec) if isinstance(grid, GridSpecFromSubplotSpec) else None}
            ax._csn_shares = {name: [other for other in ax._shared_axes[name].get_siblings(ax) if other is not ax]
                              for name in ax._axis_names}
        _known[_series.ax_id(main)] = main


def _axes(identity):
    if not identity:
        return None
    ax = _known.get(identity)
    if ax is not None and ax in ax.figure.axes:
        return ax
    return _series.axes_of(identity)


def _figure(key):
    return next((f for f in _series.figures() if figure_key(f) == key), None) if key is not None else None


def _edges(start, length, ratios):
    total, edges, run = float(sum(ratios)) or 1.0, [start], 0.0
    for ratio in ratios:
        run += ratio
        edges.append(start + length * run / total)
    return edges


# ---- arrangements

_GUESSES = {1: 'One plot', 2: 'Stacked', 3: 'A big one, two beside it', 5: 'Two over three'}


def _default(count):
    """The arrangement guessed for so many plots: one, two stacked, a big one with two beside it, then
    a grid as square as it goes - never a row of tall thin plots."""
    count = max(count, 1)
    if count in _GUESSES:
        return next(t for t in TEMPLATES if t[0] == _GUESSES[count])
    cols = math.ceil(math.sqrt(count))
    rows = math.ceil(count / cols)
    return next((t for t in TEMPLATES if t[1:3] == (rows, cols) and len(t[3]) == rows * cols),
                None) or _grid(f"{rows} by {cols}", rows, cols)


def _fill(template, ids, hidden=()):
    """The template's cells, with these plots in order - those there's no room for, hidden."""
    name, rows, cols, cells, widths, heights = template
    ids = list(ids)
    return {'template': name, 'rows': rows, 'cols': cols, 'cells': [list(cell) for cell in cells],
            'plots': (ids + [None] * len(cells))[:len(cells)],
            'widths': [float(w) for w in widths or [1] * cols], 'heights': [float(h) for h in heights or [1] * rows],
            'hidden': [i for i in hidden if i not in ids] + ids[len(cells):]}


def _named(rows, cols, cells):
    shape = sorted(tuple(cell) for cell in cells)
    return next((t[0] for t in TEMPLATES if t[1:3] == (rows, cols) and sorted(t[3]) == shape), None)


def _plain(count, like=None):
    """The arrangement for so many plots - a column of them staying a column (up to three), else the
    guess (_default)."""
    count = max(count, 1)
    if like is None or like['cols'] != 1 or like['rows'] == 1 or count > 3:
        return _default(count)
    rows, cols = count, 1
    return next((t for t in TEMPLATES if t[1:3] == (rows, cols) and len(t[3]) == rows * cols),
                None) or _grid(f"{rows} by {cols}", rows, cols)


def _uniform(state):
    """A plain grid - every cell one place - which closes up when a plot leaves it."""
    return len(state['cells']) == state['rows'] * state['cols'] and all(
        r1 - r0 == 1 and c1 - c0 == 1 for r0, r1, c0, c1 in state['cells'])


def _adopt(figure):
    """The arrangement the script made, as an arrangement here: its own grid, where all its plots are
    in one - else the plain grid for that many."""
    mains = plots(figure)
    shown = [m for m in mains if m.get_visible()]
    hidden = [_series.ax_id(m) for m in mains if not m.get_visible()]
    ids = [_series.ax_id(m) for m in shown]
    specs = [m.get_subplotspec() for m in shown]
    specs = [s.get_topmost_subplotspec() if s is not None else None for s in specs]   # a plot with its colorbar: its cell
    if shown and None not in specs and len({id(s.get_gridspec()) for s in specs}) == 1 \
            and type(specs[0].get_gridspec()) is GridSpec:
        gs = specs[0].get_gridspec()
        rows, cols = gs.get_geometry()
        cells = [[s.rowspan.start, s.rowspan.stop, s.colspan.start, s.colspan.stop] for s in specs]
        covered, overlap = set(), False
        for r0, r1, c0, c1 in cells:
            spots = {(r, c) for r in range(r0, r1) for c in range(c0, c1)}
            overlap = overlap or bool(spots & covered)
            covered |= spots
        if not overlap:
            filled = list(ids)
            for r in range(rows):
                for c in range(cols):
                    if (r, c) not in covered:   # the grid's empty places: cells to put a plot in
                        cells.append([r, r + 1, c, c + 1])
                        filled.append(None)
            order = sorted(range(len(cells)), key=lambda i: (cells[i][0], cells[i][2]))
            cells = [cells[i] for i in order]
            return {'template': _named(rows, cols, cells), 'rows': rows, 'cols': cols, 'cells': cells,
                    'plots': [filled[i] for i in order], 'widths': [float(w) for w in gs.get_width_ratios()],
                    'heights': [float(h) for h in gs.get_height_ratios()], 'hidden': hidden}
    return _fill(_default(len(ids)), ids, hidden)


def _state_in(layout, figure):
    _remember(figure)
    state = layout['tabs'].get(figure_key(figure))
    return copy.deepcopy(state) if state is not None else _adopt(figure)


def state_of(figure):
    """The tab's arrangement now - fitted to the plots it has (none left out, none that's gone)."""
    state = _state_in(_current if _current is not None else _empty(), figure)
    return _complete(figure, state) if _valid(state) else state


def _valid(state):
    try:
        rows, cols, cells = int(state['rows']), int(state['cols']), state['cells']
        return (rows >= 1 and cols >= 1 and len(state['plots']) == len(cells) and len(state['widths']) == cols
                and len(state['heights']) == rows and isinstance(state.get('hidden', []), list)
                and all(0 <= r0 < r1 <= rows and 0 <= c0 < c1 <= cols for r0, r1, c0, c1 in cells)
                and all(float(w) > 0 for w in [*state['widths'], *state['heights']]))
    except (KeyError, TypeError, ValueError):
        return False


def _complete(figure, state):
    """The arrangement fitted to the plots the tab has now: those gone left out, a new one put in."""
    mine = [_series.ax_id(m) for m in plots(figure)]
    seen = set()
    for number, identity in enumerate(state['plots']):
        if identity not in mine or identity in seen:
            state['plots'][number] = None
        seen.add(identity)
    state['hidden'] = [i for i in dict.fromkeys(state.get('hidden', [])) if i in mine and i not in state['plots']]
    for identity in mine:
        if identity not in state['plots'] and identity not in state['hidden']:
            state = _put_in(state, identity)
    return state


def _put_in(state, identity, cell=None):
    """The plot into the arrangement: into that cell or the first empty one - none, the plain grid for
    one more."""
    if identity in state['hidden']:
        state['hidden'].remove(identity)
    if cell is not None and state['plots'][cell] is None:
        state['plots'][cell] = identity
    elif None in state['plots']:
        state['plots'][state['plots'].index(None)] = identity
    else:
        shown = [i for i in state['plots'] if i] + [identity]
        state = _fill(_plain(len(shown), state if _uniform(state) else None), shown, state['hidden'])
    return state


def _take_out(state, identity, hide=False):
    """The plot out of the arrangement (into the hidden ones, if hide) - on a plain grid, the rest
    closing up."""
    if identity in state['plots']:
        state['plots'][state['plots'].index(identity)] = None
    if identity in state['hidden'] and not hide:
        state['hidden'].remove(identity)
    if hide and identity not in state['hidden']:
        state['hidden'].append(identity)
    if _uniform(state) and None in state['plots']:
        shown = [i for i in state['plots'] if i]
        state = _fill(_plain(len(shown), state), shown, state['hidden'])
    return state


def _tidy(layout):
    """Tabs made here with nothing left in them: gone."""
    for name in list(layout['new_tabs']):
        state = layout['tabs'].get(name)
        if state is None or not (any(state['plots']) or state['hidden']):
            layout['new_tabs'].remove(name)
            layout['tabs'].pop(name, None)
    return layout


# ---- putting a layout on the figures

def _put(layout):
    """The layout as it's given: tabs made, plots added, each plot in its tab, each tab arranged."""
    global _current
    if _busy():   # a run's thread is drawing into the plots: once it's done
        QtCore.QTimer.singleShot(250, lambda: _put(layout))
        return
    _series.quiet()
    layout = copy.deepcopy(layout)
    for figure in _series.figures():
        _remember(figure)
    for name in layout['new_tabs']:
        if _figure(name) is None:
            _make_tab(name)
    homes = {i: key for key, state in layout['tabs'].items() for i in [*state['plots'], *state['hidden']] if i}
    wanted = {plot['id']: plot for plot in layout['added']}
    for identity, ax in list(_known.items()):
        if getattr(ax, '_csn_added_plot', False) and identity not in wanted:
            _drop(identity, ax)
    for identity, plot in wanted.items():
        if _axes(identity) is None:
            figure = _figure(homes.get(identity, plot.get('tab'))) or next(iter(_series.figures()), None)
            if figure is not None:
                _make_plot(figure, identity, plot)
    for figure in _series.figures():   # a plot made twice over (never meant to be): only the one known stays
        for ax in list(figure.axes):
            if getattr(ax, '_csn_added_plot', False) and _known.get(_series.ax_id(ax)) is not ax:
                _drop(None, ax)
    alive = _series.figures()
    for identity, ax in list(_known.items()):
        target = _figure(homes.get(identity))
        if target is None:   # in no tab's arrangement: where the script made it
            target = ax._csn_place0['figure']
        if target in alive and ax.figure is not target:
            _move(ax, target)
    for figure in _series.figures():
        key = figure_key(figure)
        state = layout['tabs'].get(key)
        if state is not None:
            state = layout['tabs'][key] = _complete(figure, state)
        _arrange(figure, state)
    for figure in _series.figures():
        if getattr(figure, '_csn_made', False) and figure_key(figure) not in layout['new_tabs'] and not plots(figure):
            _close(figure)
    _rejoin()
    _current = layout
    store.data['layout'] = copy.deepcopy(layout)
    store.changed()
    for figure in _series.figures():
        toolbar = figure.canvas.toolbar
        if toolbar is not None:
            toolbar.update()   # matplotlib's back and forward would put the plots where they were
        if hasattr(figure.canvas, 'quick_once'):   # every plot moves: shown at once, drawn properly after
            figure.canvas.quick_once()
        figure.canvas.draw_idle()


def _arrange(figure, state):
    """The tab's plots into their cells - or, no arrangement, back where the script put them."""
    if state is None:
        if not getattr(figure, '_csn_arranged', False):
            return
        figure._csn_arranged = False
        figure._csn_gs = figure._csn_grid_box = None
        figure._layout_engine = figure._csn_engine0
        figure.subplotpars.update(**figure._csn_margins0)   # a tight layout moves the figure's margins
        for ax in figure.axes:
            place = getattr(ax, '_csn_place0', None)
            if place is None or place['figure'] is not figure:
                continue
            if place['outer'] is not None:
                place['outer'][0]._subplot_spec = place['outer'][1]
            if place['spec'] is not None:
                ax.set_subplotspec(place['spec'])
            ax._set_position(place['position'])
            ax.set_visible(place['visible'])
            ax.set_in_layout(place['in_layout'])
        return
    figure._csn_arranged = True
    _engine(figure)
    gs = GridSpec(state['rows'], state['cols'], figure=figure, width_ratios=state['widths'],
                  height_ratios=state['heights'])
    gs._csn_shares = (list(state['widths']), list(state['heights']))   # each cell's share, its labels and all
    figure._csn_gs = gs
    for (r0, r1, c0, c1), identity in zip(state['cells'], state['plots']):
        main = _axes(identity)
        if main is None or main.figure is not figure:
            continue
        members = _members(main)
        for ax in members:
            if ax is main or ax.get_subplotspec() is not None:   # a twin without one follows its plot anyway
                _seat(ax, gs[r0:r1, c0:c1], members)
            ax.set_visible(True)
            ax.set_in_layout(True)
    for identity in state['hidden']:
        main = _axes(identity)
        if main is None or main.figure is not figure:
            continue
        members = _members(main)
        for ax in members:
            if ax is main or ax.get_subplotspec() is not None:
                _seat(ax, gs[0, 0], members)   # in this grid still, so the layout knows of one grid
            ax.set_visible(False)
            ax.set_in_layout(False)


def _engine(figure):
    """Constrained layout, so labels don't overlap - but a colorbar made in a small grid beside its
    plot (as plt.colorbar does without one) only goes with the tight layout, and one made for the
    layout the figure has, with that one."""
    bars = [a for a in figure.axes if hasattr(a, '_colorbar')]
    if any(a.get_subplotspec() is not None for a in bars):
        kind = TightLayoutEngine
    elif bars:
        kind = None   # the one it has
    else:
        kind = ConstrainedLayoutEngine
    if kind is not None and not isinstance(figure.get_layout_engine(), kind):
        figure._layout_engine = kind()   # not set_layout_engine(): it refuses once there's a colorbar
        figure.stale = True
    engine = figure.get_layout_engine()
    if isinstance(engine, ConstrainedLayoutEngine) and 'execute' not in vars(engine):
        execute = engine.execute
        engine.execute = lambda fig: _laid_out(execute, fig)
        from matplotlib import _constrained_layout
        match = _constrained_layout.match_submerged_margins
        if not getattr(match, '_csn', False):   # in an arranged tab, not done: _laid_out()
            def matched(layoutgrids, fig):
                if getattr(fig, '_csn_gs', None) is None:
                    match(layoutgrids, fig)
            matched._csn = True
            _constrained_layout.match_submerged_margins = matched


def _laid_out(execute, figure):
    """The constrained layout, each plot - its labels and colorbar with it - in its cell as the arrangement
    has it: matplotlib's ratios are of the plots alone, their labels added on (a plot with a colorbar would
    take more than its share, the line between the cells not where it's drawn), so they're set from the
    labels' room the layout found, and it's laid out again. Where it can't be (cells too small for their
    labels, or it failed), each plot plainly in its cell and its colorbar beside it: matplotlib would leave
    them where they were. matplotlib also widens the margins inside every plot spanning cells to the
    widest such margin of the grid (a colorbar's, say): a plot whose edge is on such a line kept that
    much empty room in its cell - in an arranged tab it isn't done (_engine())."""
    from matplotlib import _constrained_layout
    from matplotlib.transforms import Bbox
    gs = getattr(figure, '_csn_gs', None)
    try:
        grids = execute(figure)
        laid = grids is not None and _constrained_layout.check_no_collapsed_axes(grids, figure)
        if laid and gs is not None and gs in grids:
            grid = grids[gs]
            box = grid.get_outer_bbox(rows=[0, gs.nrows - 1], cols=[0, gs.ncols - 1])
            figure._csn_grid_box = tuple(box.extents)   # where the cells are: the arranger draws them there
            again = False
            for size, wanted, sides, now, put in (
                    (box.width, gs._csn_shares[0], ('left', 'right', 'leftcb', 'rightcb'), gs.get_width_ratios(),
                     gs.set_width_ratios),
                    (box.height, gs._csn_shares[1], ('top', 'bottom', 'topcb', 'bottomcb'), gs.get_height_ratios(),
                     gs.set_height_ratios)):
                total = sum(wanted)
                ratios = [max(size * share / total - sum(grid.margins[side][k].value() for side in sides), size * 0.02)
                          for k, share in enumerate(wanted)]   # the cell less its labels' room (as solved): the plot
                if max(abs(a / sum(ratios) - b / sum(now)) for a, b in zip(ratios, now)) > 0.002:
                    put(ratios)
                    again = True
            if again:
                grids = execute(figure)
                laid = grids is not None and _constrained_layout.check_no_collapsed_axes(grids, figure)
        if laid or grids is None:
            return grids
    except Exception:
        pass
    figure._csn_grid_box = None
    for ax in figure.axes:
        spec = ax.get_subplotspec()
        if spec is not None and not hasattr(ax, '_colorbar_info'):
            ax._set_position(spec.get_position(figure))
    for cax in figure.axes:
        info = getattr(cax, '_colorbar_info', None)
        parents = [p for p in (info or {}).get('parents', ()) if p.figure is figure]
        if not parents or cax.get_subplotspec() is not None:
            continue
        box = Bbox.union([p.get_position(original=True) for p in parents])
        fraction, location = info.get('fraction', 0.15), info.get('location', 'right')
        pad = 0.05 if location in ('left', 'right') else 0.15
        if location == 'right':
            rest, _, bar = box.splitx(1 - fraction - pad, 1 - fraction)
        elif location == 'left':
            bar, _, rest = box.splitx(fraction, fraction + pad)
        elif location == 'top':
            rest, _, bar = box.splity(1 - fraction - pad, 1 - fraction)
        else:
            bar, _, rest = box.splity(fraction, fraction + pad)
        cax._set_position(bar)
        if len(parents) == 1:
            parents[0]._set_position(rest)


def _seat(ax, cell, members):
    """The axes into the cell - a plot sharing a small grid of its own with its colorbar (and nothing
    else): that grid into the cell, so the colorbar stays beside it."""
    spec = ax.get_subplotspec()
    grid = spec.get_gridspec() if spec is not None else None
    if isinstance(grid, GridSpecFromSubplotSpec) \
            and not isinstance(grid._subplot_spec.get_gridspec(), GridSpecFromSubplotSpec) \
            and all(a in members for a in ax.figure.axes
                    if a.get_subplotspec() is not None and a.get_subplotspec().get_gridspec() is grid):
        grid._subplot_spec = cell
        ax.set_subplotspec(spec)   # its place in the small grid again, now in the cell
    else:
        ax.set_subplotspec(cell)


def _move(main, target):
    """A plot (its twins with it) out of its figure and into another - which matplotlib has no way to
    do: out of the one (delaxes), every part of it told its figure is the other, its box placed in
    the other's, into it (add_axes). Twins and shared axes come apart on the way: _rejoin()."""
    source = main.figure
    members = [ax for ax in _members(main) if ax in source.axes]
    inspector = getattr(source.canvas, 'inspector', None)
    if inspector is not None:
        inspector.clear_hover()
    for ax in members:
        source.delaxes(ax)
    for ax in members:
        for artist in ax.findobj():   # its lines, texts, ticks, legend, insets...
            if getattr(artist, '_parent_figure', None) is source:
                artist._parent_figure = target
        ax.bbox._transform = target.transSubfigure
        ax.bbox.set_children(target.transSubfigure)
        ax.bbox.invalidate()
        offset = getattr(ax, 'titleOffsetTrans', None)   # the title's gap, in points: the other's dpi
        if offset is not None and getattr(offset, '_scale_trans', None) is source.dpi_scale_trans:
            offset._scale_trans = target.dpi_scale_trans
            offset.set_children(target.dpi_scale_trans)
            offset.invalidate()
        target.add_axes(ax)
    source._csn_arranged = target._csn_arranged = True
    source.stale = target.stale = True


def _rejoin():
    """After plots have moved: twins twinned again, plots shared with others (sharex) in the same tab
    sharing again - and an axis shared with one in another tab given tickers of its own, so it
    doesn't count its ticks by the other's limits."""
    joined = []
    for main in list(_known.values()):
        figure = main.figure
        for twin in getattr(main, '_csn_twins', []):
            if twin.figure is figure and not main._twinned_axes.joined(main, twin):
                main._twinned_axes.join(main, twin)
        for ax in _members(main):
            for name, others in getattr(ax, '_csn_shares', {}).items():
                grouper = ax._shared_axes[name]
                for other in others:
                    if other.figure is figure and other in figure.axes and not grouper.joined(ax, other):
                        grouper.join(ax, other)
                        joined.append((ax, other, name))
    everywhere = [(figure, ax) for figure in _series.figures() for ax in figure.axes]
    for figure in _series.figures():
        done = set()
        for ax in figure.axes:
            for name in ax._axis_names:
                if (id(ax), name) in done:
                    continue
                group = [a for a in ax._shared_axes[name].get_siblings(ax) if a in figure.axes]
                done.update((id(a), name) for a in group)
                axis = ax._axis_map[name]
                for which in ('major', 'minor'):
                    ticker = getattr(axis, which)
                    if any(getattr(o._axis_map.get(name), which, None) is ticker
                           for f, o in everywhere if f is not figure):
                        ticker = _own_ticker(ticker, axis)
                        setattr(axis, which, ticker)
                    for other in group:
                        setattr(other._axis_map[name], which, ticker)
    for ax, other, name in joined:   # sharing again: the same limits again
        getter, setter = getattr(other, f"get_{name}lim", None), getattr(ax, f"set_{name}lim", None)
        if getter is not None and setter is not None:
            setter(getter(), emit=False)


def _own_ticker(ticker, axis):
    mine = copy.copy(ticker)
    if ticker.locator is not None:
        mine.locator = copy.copy(ticker.locator)
        mine.locator.set_axis(axis)
    if ticker.formatter is not None:
        mine.formatter = copy.copy(ticker.formatter)
        mine.formatter.set_axis(axis)
        if mine.locator is not None:
            mine.formatter._set_locator(mine.locator)
    return mine


def _make_tab(name):
    import matplotlib.pyplot as plt
    figure = plt.figure(name)
    figure._csn_made = True
    manager = figure.canvas.manager
    if _opening:
        manager.behind = True
        QtCore.QTimer.singleShot(0, manager.show)   # after the script's own tabs
    else:
        manager.show()
    _remember(figure)
    return figure


def _close(figure):
    import matplotlib.pyplot as plt
    plt.close(figure)


def _make_plot(figure, identity, plot):
    ax = figure.add_subplot(1, 1, 1)   # its cell's given it by the arrangement
    ax._csn_id, ax._csn_added_plot = identity, True
    if plot.get('title'):
        ax.set_title(plot['title'])
    _view._put_grid(ax, _view.grid(ax))   # its own grid, as kept - or the default
    _remember(figure)
    return ax


def _drop(identity, ax):
    """A plot added here, gone - its right-hand axis with it."""
    if identity is not None:
        _known.pop(identity, None)
    figure = ax.figure
    for member in [ax, *getattr(ax, '_csn_twins', []), *ax._twinned_axes.get_siblings(ax)]:
        if member in figure.axes:
            figure.delaxes(member)


def restore():
    """The layout kept last time - once, as the window first opens."""
    global _opening
    for figure in _series.figures():
        _remember(figure)
    saved = store.data.get('layout')
    try:
        if not (isinstance(saved, dict) and isinstance(saved.get('tabs'), dict)
                and isinstance(saved.get('new_tabs', []), list) and isinstance(saved.get('added', []), list)):
            return
        layout = {'tabs': {key: dict(state, hidden=list(state.get('hidden', [])))
                           for key, state in saved['tabs'].items() if _valid(state)},
                  'new_tabs': [name for name in saved.get('new_tabs', []) if isinstance(name, str)],
                  'added': [plot for plot in saved.get('added', []) if isinstance(plot, dict) and plot.get('id')]}
        _opening = True
        _put(_tidy(layout))
    except Exception:   # a layout that can't be put back is no reason not to open
        print("csn_matplotlib: couldn't put the plots back where they were:", file=sys.stderr)
        traceback.print_exc()
    finally:
        _opening = False


def _reset():
    global _current
    _put(_empty())
    _current = None


_view.on_reset.append(_reset)


# ---- what can be done to the plots

def _busy():
    return any(getattr(figure.canvas, 'computing', False) for figure in _series.figures())


def _say(figure, text):
    say = getattr(figure.canvas, 'say', None) if figure is not None else None
    if say is not None:
        say(text)


def _commit(name, layout, figure, before=None):
    if _busy():
        _say(figure, 'A run is in progress. Arrange the plots once it has finished, or stop it')
        return False
    before = before if before is not None else snapshot()
    _put(_tidy(layout))
    after = snapshot()
    if after != before:
        history.push(name, lambda: _put(before), lambda: _put(after))
    return True


def _with(layout, figure, state):
    layout['tabs'][figure_key(figure)] = state
    return layout


def _tab_name(base):
    taken = {figure_key(f) for f in _series.figures()} | set(snapshot()['new_tabs'])
    base = (base or 'Plot').strip()[:40] or 'Plot'
    name, number = base, 2
    while name in taken:
        name, number = f"{base} {number}", number + 1
    return name


def _new_id(layout, key):
    """A new plot's ax_id(): one no plot has had - nothing kept for a plot deleted comes back with it."""
    number = 1
    while any(p['id'] == f"{key}/+{number}" for p in layout['added']) or _axes(f"{key}/+{number}") is not None \
            or _mentioned(f"{key}/+{number}", store.plots()):
        number += 1
    return f"{key}/+{number}"


def _mentioned(identity, thing):
    """Whether the settings keep anything under this plot's ax_id()."""
    if isinstance(thing, str):
        return thing == identity or thing.startswith(identity + '|') or thing.startswith(identity + '/')
    if isinstance(thing, dict):
        return any(_mentioned(identity, k) or _mentioned(identity, v) for k, v in thing.items())
    if isinstance(thing, (list, tuple)):
        return any(_mentioned(identity, v) for v in thing)
    return False


def choose(figure, template):
    """The tab's plots into this arrangement, in the order they're in now."""
    state = state_of(figure)
    shown = [i for i in state['plots'] if i]
    left = len(shown) - len(template[3])
    changed = template[0] != state.get('template')
    if _commit('Arrange plots', _with(snapshot(), figure, _fill(template, shown, state['hidden'])), figure) \
            and left > 0:
        _say(figure, f"{left} plot{'s' if left > 1 else ''} hidden - no room for {'them' if left > 1 else 'it'}")
    if changed and hasattr(figure.canvas, 'reveal'):   # another arrangement altogether: the plots rise in again
        figure.canvas.reveal()


def swap(figure, first, second):
    state = state_of(figure)
    cells = state['plots']
    if first == second or not (cells[first] or cells[second]):
        return
    both = cells[first] and cells[second]
    cells[first], cells[second] = cells[second], cells[first]
    _commit('Swap plots' if both else 'Move plot', _with(snapshot(), figure, state), figure)


def hide(ax):
    """Out of the way, not deleted: listed in the Layout tab, to show again."""
    main = _main(ax)
    figure = main.figure
    state = _take_out(state_of(figure), _series.ax_id(main), hide=True)
    _commit('Hide plot', _with(snapshot(), figure, state), figure)


def show(figure, identity, cell=None):
    state = _put_in(state_of(figure), identity, cell)
    if _commit('Show plot', _with(snapshot(), figure, state), figure):
        _come_in(figure, identity)


def _come_in(figure, identity):
    """A plot added to the tab: its series come in, each its way - the other plots as they are."""
    ax = _axes(identity)
    if ax is not None and hasattr(figure.canvas, 'reveal'):
        figure.canvas.reveal(axes=[ax])


def move_to(ax, target, cell=None):
    """The plot into another tab - into that cell of it, if given (and empty). In its own tab, into
    that cell."""
    main = _main(ax)
    source, identity = main.figure, _series.ax_id(main)
    if target is source:
        if cell is not None:
            state = state_of(source)
            if identity in state['plots']:
                swap(source, state['plots'].index(identity), cell)
            else:
                show(source, identity, cell)
        return
    layout = snapshot()
    _with(layout, source, _take_out(_state_in(layout, source), identity))
    _with(layout, target, _put_in(_state_in(layout, target), identity, cell))
    _commit(f"Move plot to {_series.tab_name(target)}", layout, target)


def move_to_new_tab(ax):
    main = _main(ax)
    source, identity = main.figure, _series.ax_id(main)
    name = _tab_name(_series.plot_name(main))
    layout = snapshot()
    _with(layout, source, _take_out(_state_in(layout, source), identity))
    layout['new_tabs'].append(name)
    layout['tabs'][name] = _fill(TEMPLATES[0], [identity])
    _commit('Move plot to a new tab', layout, source)


def new_plot(figure, new_tab=False, title=None, cell=None):
    """An empty plot, for series copied from others - in this tab (in that cell), or a new tab.
    Gives its axes."""
    layout = snapshot()
    if new_tab:
        key = _tab_name(title or 'New plot')
        identity = _new_id(layout, key)
        layout['new_tabs'].append(key)
        layout['tabs'][key] = _fill(TEMPLATES[0], [identity])
    else:
        key = figure_key(figure)
        identity = _new_id(layout, key)
        _with(layout, figure, _put_in(_state_in(layout, figure), identity, cell))
    layout['added'].append({'id': identity, 'tab': key, 'title': title or ''})
    if not _commit('Add plot', layout, figure):
        return None
    if not new_tab:
        _come_in(figure, identity)
    return _axes(identity)


def copy_plot(ax, figure=None, cell=None):
    """A copy of the plot - its title, labels and scales, and a linked copy of each of its series (on
    its right-hand axis, those on the plot's) - as one change: in its tab, or in another (figure), in
    the next free cell or in that one. Gives its axes."""
    main = _main(ax)
    figure = figure or main.figure
    if _busy():
        _say(figure, 'A run is in progress. Copy the plot once it has finished, or stop it')
        return None
    before = snapshot()
    layout = snapshot()
    key = figure_key(figure)
    identity = _new_id(layout, key)
    _with(layout, figure, _put_in(_state_in(layout, figure), identity, cell))
    layout['added'].append({'id': identity, 'tab': key, 'title': main.get_title()})
    texts = {'xlabel': main.get_xlabel(), 'ylabel': main.get_ylabel()}
    scales = {'x': main.get_xscale(), 'y': main.get_yscale()}
    sources = [s for a in _members(main) if not hasattr(a, '_colorbar') for s in _series.series(a)
               if not s.label.endswith(_view.REFERENCE)]
    made = []

    def forward():
        _put(_tidy(copy.deepcopy(layout)))
        new = _axes(identity)
        if new is None:
            return
        for which, text in texts.items():
            if text:
                _view.set_text(figure, f"{identity}|{which}", text, record=False)
        for axis, scale in scales.items():
            _view.set_scale(new, axis, scale, record=False)
        if not made:
            for s in sources:
                target = new if s.ax is main else _view.right_axis(new, record=False)
                plan = _view._copy_plan(s, target)
                if plan[0] == 'copy':
                    made.append(plan[1])
        elif any(entry['axes'] != identity for entry in made):   # redone: its right-hand axis again
            _view.right_axis(new, record=False)
        for entry in made:
            _view.add_series(entry, record=False)

    def back():
        for entry in made:
            _view.remove_series(entry['id'], record=False)
        _put(before)
    forward()
    history.push('Duplicate plot', back, forward)
    _come_in(figure, identity)
    return _axes(identity)


def delete_plot(ax, parent=None):
    """A plot added here, gone - with the series in it (undoable). The script's own can only hide."""
    main = _main(ax)
    if not getattr(main, '_csn_added_plot', False):
        return
    identity, figure = _series.ax_id(main), main.figure
    entries = [entry for entry in _view.entries() if entry.get('axes') == identity]
    if entries:
        answer = QtWidgets.QMessageBox.question(
            parent, 'Delete plot', f"Delete this plot and the {len(entries)} series in it? (Ctrl+Z brings them back)")
        if answer != QtWidgets.QMessageBox.StandardButton.Yes:
            return
    if _busy():
        _say(figure, 'A run is in progress. Delete the plot once it has finished, or stop it')
        return
    before = snapshot()
    layout = snapshot()
    layout['added'] = [plot for plot in layout['added'] if plot['id'] != identity]
    _tidy(_with(layout, figure, _take_out(_state_in(layout, figure), identity)))

    def forward():
        for entry in entries:
            _view.remove_series(entry['id'], record=False)
        _put(layout)

    def back():
        _put(before)
        for entry in entries:
            _view.add_series(entry, record=False)

    forward()
    history.push('Delete plot', back, forward)


def cell_menu(figure, index, at, parent):
    """A cell's menu: for a plot, swapping, moving, hiding, its scales; for an empty one, what to put
    there."""
    state = state_of(figure)
    if index >= len(state['plots']):
        return
    ax = _axes(state['plots'][index])
    others = [(j, _axes(i)) for j, i in enumerate(state['plots']) if i and j != index and _axes(i) is not None]
    menu = QtWidgets.QMenu(parent)
    menu.setToolTipsVisible(True)
    if ax is not None:
        menu.addAction(_series.plot_name(ax)).setEnabled(False)
        if others:
            swaps = menu.addMenu('Swap with')
            for j, other in others:
                swaps.addAction(_series.plot_name(other), lambda _=False, j=j: swap(figure, index, j))
        tabs = menu.addMenu('Move to tab')
        for other in _series.open_figures():
            if other is not figure:
                tabs.addAction(_series.tab_name(other), lambda _=False, o=other: move_to(ax, o))
        if not tabs.isEmpty():
            tabs.addSeparator()
        tabs.addAction('A new tab', lambda _=False: move_to_new_tab(ax))
        menu.addAction('Rename…', lambda _=False: _rename(figure, ax, parent))
        menu.addAction('Duplicate plot', lambda _=False: copy_plot(ax)).setToolTip(
            'A new plot in this tab, showing the same series (linked copies) with the same labels and scales')
        menu.addAction('Hide', lambda _=False: hide(ax)).setToolTip(
            "Out of the way, not deleted - it's listed in the Layout tab, to show again")
        menu.addSeparator()
        for axis in ('x', 'y'):
            scales = menu.addMenu(f"{axis} scale")
            now = ax.get_xscale() if axis == 'x' else ax.get_yscale()
            for scale in SCALES:
                item = scales.addAction(scale, lambda _=False, a=axis, s=scale: _view.set_scale(ax, a, s))
                item.setCheckable(True)
                item.setChecked(scale == now)
        if getattr(ax, '_csn_added_plot', False):
            menu.addSeparator()
            menu.addAction('Delete this plot…', lambda _=False: delete_plot(ax, parent))
    else:
        menu.addAction('Empty space').setEnabled(False)
        menu.addAction('A new plot here', lambda _=False: new_plot(figure, cell=index))
        hidden = [(i, _axes(i)) for i in state['hidden'] if _axes(i) is not None]
        if hidden:
            shows = menu.addMenu('Show a hidden plot here')
            for i, other in hidden:
                shows.addAction(_series.plot_name(other), lambda _=False, i=i: show(figure, i, index))
        moves = menu.addMenu('Move a plot here')
        if others:
            here = moves.addMenu(f"From this tab ({_series.tab_name(figure)})")
            for j, other in others:
                here.addAction(_series.plot_name(other), lambda _=False, j=j: swap(figure, index, j))
        for tab in _series.open_figures():
            if tab is figure:
                continue
            mains = [m for m in plots(tab) if m.get_visible()]
            if mains:
                there = moves.addMenu(f"From {_series.tab_name(tab)}")
                for other in mains:
                    there.addAction(_series.plot_name(other), lambda _=False, o=other: move_to(o, figure, index))
        moves.setEnabled(not moves.isEmpty())
        copies = menu.addMenu('Duplicate a plot here')
        copies.setToolTipsVisible(True)
        copies.setToolTip('A new plot here showing the same series (linked copies), labels and scales')
        for tab in _series.open_figures():
            mains = [m for m in plots(tab) if m.get_visible()]
            if mains:
                there = copies.addMenu(f"From {'this tab' if tab is figure else _series.tab_name(tab)}"
                                       + (f" ({_series.tab_name(tab)})" if tab is figure else ''))
                for other in mains:
                    there.addAction(_series.plot_name(other),
                                    lambda _=False, o=other: copy_plot(o, figure, index))
        copies.setEnabled(not copies.isEmpty())
    menu.exec(at)


def _rename(figure, ax, parent):
    from ._plot_panel import ask_name   # here: the Plot tab's module uses this one
    ask_name(figure.canvas, ax)


# ---- dragging the cells about: on the map, and on the plot

class _Arranger:
    """Picking, swapping and resizing a tab's cells within a rectangle - the map in the panel and the
    plot itself both."""

    BORDER_PX = 5   # this near a line between cells counts as on it
    DRAG_PX = 6     # a press moving less than this is a click
    LEAST = 0.1     # a cell's least share of the two it's resized between

    def __init__(self, canvas, widget, area, small):
        self.canvas, self.widget, self.area, self.small = canvas, widget, area, small
        self._press = self._hover = self._target = self._pointer = None

    def geometry(self):
        """(state, cell rects, column edges, row edges) - while a line's dragged, as they'll be once let go."""
        press = self._press
        state = press['preview'] if press is not None and press.get('preview') else state_of(self.canvas.figure)
        rect = self.area()
        xs = _edges(rect.left(), rect.width(), state['widths'])
        ys = _edges(rect.top(), rect.height(), state['heights'])
        cells = [QtCore.QRectF(QtCore.QPointF(xs[c0], ys[r0]), QtCore.QPointF(xs[c1], ys[r1]))
                 for r0, r1, c0, c1 in state['cells']]
        return state, cells, xs, ys

    def hit(self, position):
        """('cross', x index, y index) - where two lines between cells meet, to move both - ('border',
        'x' | 'y', its index) or ('cell', index) at the position, or None."""
        if not self.area().contains(position):
            return None
        state, cells, xs, ys = self.geometry()
        reach = self.BORDER_PX + 2
        for kx in range(1, len(xs) - 1):
            if abs(position.x() - xs[kx]) > reach:
                continue
            for ky in range(1, len(ys) - 1):
                if abs(position.y() - ys[ky]) <= reach and any(
                        start - 1 <= ys[ky] <= end + 1 for start, end in self._spans(state, 'x', kx, xs, ys)) and any(
                        start - 1 <= xs[kx] <= end + 1 for start, end in self._spans(state, 'y', ky, xs, ys)):
                    return 'cross', kx, ky
        for axis, edges, at, along in (('x', xs, position.x(), position.y()), ('y', ys, position.y(), position.x())):
            for k in range(1, len(edges) - 1):
                if abs(at - edges[k]) <= self.BORDER_PX and any(
                        start <= along <= end for start, end in self._spans(state, axis, k, xs, ys)):
                    return 'border', axis, k
        return next((('cell', i) for i, cell in enumerate(cells) if cell.contains(position)), None)

    @staticmethod
    def _spans(state, axis, k, xs, ys):
        """Where the line at that border runs between cells (a big cell across it hasn't one)."""
        if axis == 'x':
            return [(ys[r0], ys[r1]) for r0, r1, c0, c1 in state['cells'] if c1 == k]
        return [(xs[c0], xs[c1]) for r0, r1, c0, c1 in state['cells'] if r1 == k]

    def press(self, position, button):
        self._press = None
        hit = self.hit(position)
        if button == Qt.MouseButton.RightButton:
            if hit is not None and hit[0] == 'cell':
                cell_menu(self.canvas.figure, hit[1], self.widget.mapToGlobal(position.toPoint()), self.widget)
            return
        if button == Qt.MouseButton.LeftButton and hit is not None:
            self._press = {'at': position, 'hit': hit, 'before': snapshot(), 'moved': False,
                           'state': state_of(self.canvas.figure)}

    def move(self, position):
        self._pointer = position
        press = self._press
        if press is None:
            hit = self.hit(position)
            if hit != self._hover:
                self._hover = hit
                self.widget.update()
            self.widget.setCursor(_cursor(hit, False))
            return
        if not press['moved'] and (position - press['at']).manhattanLength() < self.DRAG_PX:
            return
        press['moved'] = True
        if press['hit'][0] in ('border', 'cross'):
            self._resize(press, position)
        else:
            hit = self.hit(position)
            self._target = hit[1] if hit is not None and hit[0] == 'cell' and hit[1] != press['hit'][1] else None
            self.widget.setCursor(_cursor(press['hit'], True))
            self.widget.update()

    def _resize(self, press, position):
        hit = press['hit']
        state = copy.deepcopy(press['state'])
        rect = self.area()
        for axis, k in ([('x', hit[1]), ('y', hit[2])] if hit[0] == 'cross' else [(hit[1], hit[2])]):
            ratios = state['widths'] if axis == 'x' else state['heights']
            edges = _edges(*((rect.left(), rect.width()) if axis == 'x' else (rect.top(), rect.height())), ratios)
            at = position.x() if axis == 'x' else position.y()
            share = (at - edges[k - 1]) / max(edges[k + 1] - edges[k - 1], 1e-9)
            share = min(max(share, self.LEAST), 1 - self.LEAST)
            pair = ratios[k - 1] + ratios[k]
            ratios[k - 1], ratios[k] = pair * share, pair * (1 - share)
        press['preview'] = state   # outlined while dragged: the plots go there once it's let go
        self.widget.update()

    def release(self, position, button):
        press, self._press = self._press, None
        target, self._target = self._target, None
        if press is None or button != Qt.MouseButton.LeftButton:
            return
        figure = self.canvas.figure
        if press['hit'][0] in ('border', 'cross'):
            if press['moved'] and press.get('preview'):
                _commit('Resize plots', _with(snapshot(), figure, press['preview']), figure, before=press['before'])
        elif not press['moved']:
            cell_menu(figure, press['hit'][1], self.widget.mapToGlobal(position.toPoint()), self.widget)
        elif target is not None:
            swap(figure, press['hit'][1], target)
        self.widget.setCursor(_cursor(self.hit(position), False))
        self.widget.update()

    def cancel(self):
        self._press = self._target = None

    def leave(self):
        if self._press is None:
            self._hover = None
            self.widget.unsetCursor()
            self.widget.update()

    def paint(self, painter):
        state, cells, xs, ys = self.geometry()
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        press = self._press
        dragged = press['hit'][1] if press is not None and press['moved'] and press['hit'][0] == 'cell' else None
        accent = QtGui.QColor(_style.ACCENT)
        for index, cell in enumerate(cells):
            ax = _axes(state['plots'][index])
            box = cell.adjusted(3, 3, -3, -3)
            target = index == self._target
            hovered = press is None and self._hover == ('cell', index)
            if self.small:
                fill = QtGui.QColor(_style.SELECT if target else _style.HOVER if hovered else _style.RAISED)
                if ax is None and not (target or hovered):
                    fill.setAlpha(0)
                pen = QtGui.QPen(accent if target else QtGui.QColor(_style.FIELD_EDGE), 2 if target else 1)
            else:
                fill = QtGui.QColor(accent)
                fill.setAlpha(70 if target else 22 if hovered else 0)
                pen = QtGui.QPen(accent, 2 if target else 1.2)
            if ax is None or not self.small:
                pen.setStyle(Qt.PenStyle.DashLine)
            painter.setOpacity(0.35 if index == dragged else 1.0)
            painter.setPen(pen)
            painter.setBrush(fill)
            painter.drawRoundedRect(box, 6, 6)
            self._label(painter, box, _series.plot_name(ax) if ax is not None else 'Empty', ax is None)
            painter.setOpacity(1.0)
        hot = press['hit'] if press is not None and press['hit'][0] in ('border', 'cross') else self._hover
        if hot is not None and hot[0] in ('border', 'cross'):
            pen = QtGui.QPen(accent, 3)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(pen)
            lines = [('x', hot[1]), ('y', hot[2])] if hot[0] == 'cross' else [(hot[1], hot[2])]
            for axis, k in lines:
                for start, end in self._spans(state, axis, k, xs, ys):
                    if axis == 'x':
                        painter.drawLine(QtCore.QLineF(xs[k], start + 4, xs[k], end - 4))
                    else:
                        painter.drawLine(QtCore.QLineF(start + 4, ys[k], end - 4, ys[k]))
            if hot[0] == 'cross':   # the point that moves both
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(accent)
                painter.drawEllipse(QtCore.QPointF(xs[hot[1]], ys[hot[2]]), 5, 5)
        if dragged is not None and self._pointer is not None:   # the plot, following the pointer
            ghost = QtGui.QColor(accent)
            ghost.setAlpha(45)
            painter.setPen(QtGui.QPen(accent, 1.5))
            painter.setBrush(ghost)
            painter.drawRoundedRect(cells[dragged].translated(self._pointer - press['at']).adjusted(3, 3, -3, -3), 6, 6)

    def _label(self, painter, box, text, empty):
        metrics = QtGui.QFontMetrics(painter.font())
        text = metrics.elidedText(text, Qt.TextElideMode.ElideRight, int(max(box.width() - 16, 10)))
        if self.small:
            painter.setPen(QtGui.QColor(_style.TEXT_3 if empty else _style.TEXT_2))
            painter.drawText(box, int(Qt.AlignmentFlag.AlignCenter), text)
            return
        width, height = metrics.horizontalAdvance(text) + 20, metrics.height() + 10
        pill = QtCore.QRectF(box.center().x() - width / 2, box.center().y() - height / 2, width, height)
        backing = QtGui.QColor(_style.RAISED)
        backing.setAlpha(235)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(backing)
        painter.drawRoundedRect(pill, height / 2, height / 2)
        painter.setPen(QtGui.QColor(_style.TEXT_3 if empty else _style.TEXT))
        painter.drawText(pill, int(Qt.AlignmentFlag.AlignCenter), text)


def _cursor(hit, dragging):
    shapes = Qt.CursorShape
    if hit is None:
        return shapes.ArrowCursor
    if hit[0] == 'cross':
        return shapes.SizeAllCursor
    if hit[0] == 'border':
        return shapes.SplitHCursor if hit[1] == 'x' else shapes.SplitVCursor
    return shapes.ClosedHandCursor if dragging else shapes.OpenHandCursor


class LayoutTool:
    """While 'Arrange on the plot' is on: the tab's cells over the plot, to drag about as on the map."""

    def __init__(self, canvas):
        self.canvas, self.active = canvas, False
        self.arranger = _Arranger(canvas, canvas, self._area, small=False)

    def _area(self):
        """The canvas - the part of it the grid's laid out in, once it's been (under a suptitle, say)."""
        rect = QtCore.QRectF(self.canvas.rect())
        box = getattr(self.canvas.figure, '_csn_grid_box', None)
        if box is None or not getattr(self.canvas.figure, '_csn_arranged', False):
            return rect
        x0, y0, x1, y1 = box
        return QtCore.QRectF(rect.left() + x0 * rect.width(), rect.top() + (1 - y1) * rect.height(),
                             (x1 - x0) * rect.width(), (y1 - y0) * rect.height())

    def set_active(self, on):
        self.active = on
        self.arranger.cancel()
        self.canvas.unsetCursor()
        self.canvas.update()

    def cancel(self):
        self.arranger.cancel()

    def press(self, event):
        if self.active:
            self.arranger.press(event.position(), event.button())
        return self.active

    def move(self, event):
        if self.active:
            self.arranger.move(event.position())
        return self.active

    def release(self, event):
        if self.active:
            self.arranger.release(event.position(), event.button())
        return self.active

    def paint(self, painter):
        if self.active:
            self.arranger.paint(painter)


class _Map(QtWidgets.QWidget):
    """The tab's cells, small, named by their plots - to drag about."""

    LEAST, MOST = 110, 300

    def __init__(self, canvas):
        super().__init__()
        self.canvas = canvas
        self.setMouseTracking(True)
        policy = QtWidgets.QSizePolicy(QtWidgets.QSizePolicy.Policy.Preferred, QtWidgets.QSizePolicy.Policy.Preferred)
        policy.setHeightForWidth(True)
        self.setSizePolicy(policy)
        self.arranger = _Arranger(canvas, self, lambda: QtCore.QRectF(self.rect()).adjusted(4, 4, -4, -4), small=True)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        box = self.canvas.figure.bbox
        aspect = box.height / box.width if box.width else 0.6
        return int(min(max(width * aspect, self.LEAST), self.MOST))

    def sizeHint(self):
        return QtCore.QSize(260, self.heightForWidth(260))

    def mousePressEvent(self, event):
        self.arranger.press(event.position(), event.button())

    def mouseMoveEvent(self, event):
        self.arranger.move(event.position())

    def mouseReleaseEvent(self, event):
        self.arranger.release(event.position(), event.button())

    def leaveEvent(self, event):
        self.arranger.leave()
        super().leaveEvent(event)

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QtGui.QColor(_style.BASE))
        painter.drawRoundedRect(QtCore.QRectF(self.rect()), 8, 8)
        self.arranger.paint(painter)
        painter.end()


class LayoutPane(QtWidgets.QWidget):
    """The Layout tab: the arrangements to pick from, the map of the tab's plots, the hidden ones."""

    ICON = QtCore.QSize(34, 24)
    PER_ROW = 5

    def __init__(self, canvas):
        super().__init__()
        self.setObjectName('csnLayout')
        self.setMinimumWidth(1)
        self.canvas = canvas
        self._refresher = QtCore.QTimer(self)
        self._refresher.setSingleShot(True)
        self._refresher.timeout.connect(self.refresh)
        canvas.mpl_connect('draw_event', lambda event: self._refresher.start(300))
        history.listeners.append(lambda: self._refresher.start(0))

        choices = QtWidgets.QWidget()
        grid = QtWidgets.QGridLayout(choices)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(4)
        self.templates = []
        for number, template in enumerate(TEMPLATES):
            button = QtWidgets.QToolButton()
            button.setObjectName('csnChoice')
            button.setIcon(_template_icon(template, self.ICON))
            button.setIconSize(self.ICON)
            button.setCheckable(True)
            button.setToolTip(template[0])
            button.clicked.connect(lambda _=False, t=template: self._choose(t))
            grid.addWidget(button, number // self.PER_ROW, number % self.PER_ROW)
            self.templates.append((template[0], button))
        grid.setColumnStretch(self.PER_ROW, 1)

        self.map = _Map(canvas)
        hint = QtWidgets.QLabel('Drag a plot onto another to swap them, or onto an empty cell to move it there. '
                                'Drag the lines between them to resize. Click one for more.')
        hint.setObjectName('csnHint')
        hint.setWordWrap(True)
        add = QtWidgets.QPushButton('Add a plot')
        add.setToolTip("An empty plot in this tab, for series copied from other plots (the data panel's "
                       "right-click menu)")
        add.clicked.connect(lambda: new_plot(canvas.figure))
        self.dragging = QtWidgets.QPushButton('Arrange on the plot')
        self.dragging.setCheckable(True)
        self.dragging.setToolTip('The cells over the plot itself, to drag about as on the map (Esc stops)')
        self.dragging.toggled.connect(lambda on: canvas.layout_tool.set_active(on))
        row = QtWidgets.QHBoxLayout()
        row.addWidget(add)
        row.addWidget(self.dragging)
        arranged = QtWidgets.QWidget()
        column = QtWidgets.QVBoxLayout(arranged)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(8)
        column.addWidget(self.map)
        column.addWidget(hint)
        column.addLayout(row)

        self.hidden = QtWidgets.QListWidget()
        self.hidden.setMaximumHeight(140)
        self.hidden.itemDoubleClicked.connect(self._show_hidden)
        self.show_button = QtWidgets.QPushButton('Show')
        self.show_button.clicked.connect(lambda: self._show_hidden(self.hidden.currentItem()))
        self.none_hidden = QtWidgets.QLabel('None. A plot hidden from its menu waits here, to be shown again.')
        self.none_hidden.setObjectName('csnHint')
        self.none_hidden.setWordWrap(True)
        waiting = QtWidgets.QWidget()
        column = QtWidgets.QVBoxLayout(waiting)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(6)
        column.addWidget(self.none_hidden)
        column.addWidget(self.hidden)
        column.addWidget(self.show_button, 0, Qt.AlignmentFlag.AlignLeft)

        body = QtWidgets.QWidget()
        body.setObjectName('csnLayout')
        sections = QtWidgets.QVBoxLayout(body)
        sections.setContentsMargins(0, 0, 4, 0)
        sections.setSpacing(10)
        Section('Arrangement', choices).place(sections)
        Section('Plots in this tab', arranged).place(sections)
        Section('Hidden plots', waiting).place(sections)
        sections.addStretch(1)
        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        scroll.setWidget(body)
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.addWidget(scroll)

    def showEvent(self, event):
        super().showEvent(event)
        self.refresh()

    def refresh(self):
        if not self.isVisible():
            return
        state = state_of(self.canvas.figure)
        for name, button in self.templates:
            button.setChecked(name == state['template'])
        self.map.updateGeometry()
        self.map.update()
        self.hidden.clear()
        for identity in state['hidden']:
            ax = _axes(identity)
            if ax is not None:
                item = QtWidgets.QListWidgetItem(_series.plot_name(ax))
                item.setData(Qt.ItemDataRole.UserRole, identity)
                self.hidden.addItem(item)
        some = self.hidden.count() > 0
        self.hidden.setVisible(some)
        self.show_button.setVisible(some)
        self.none_hidden.setVisible(not some)

    def _choose(self, template):
        choose(self.canvas.figure, template)
        self.refresh()   # the button pressed shows the arrangement there is, chosen or not

    def _show_hidden(self, item):
        if item is not None:
            show(self.canvas.figure, item.data(Qt.ItemDataRole.UserRole))


def _template_icon(template, size):
    ratio = 3.0
    pixmap = QtGui.QPixmap(int(size.width() * ratio), int(size.height() * ratio))
    pixmap.setDevicePixelRatio(ratio)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QtGui.QPainter(pixmap)
    painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
    _, rows, cols, cells, widths, heights = template
    xs = _edges(1.0, size.width() - 2.0, widths or [1] * cols)
    ys = _edges(1.0, size.height() - 2.0, heights or [1] * rows)
    fill = QtGui.QColor(_style.TEXT_2)
    fill.setAlpha(45)
    painter.setPen(QtGui.QPen(QtGui.QColor(_style.TEXT_2), 1.1))
    painter.setBrush(fill)
    for r0, r1, c0, c1 in cells:
        painter.drawRoundedRect(QtCore.QRectF(QtCore.QPointF(xs[c0], ys[r0]),
                                              QtCore.QPointF(xs[c1], ys[r1])).adjusted(1, 1, -1, -1), 1.8, 1.8)
    painter.end()
    return QtGui.QIcon(pixmap)
