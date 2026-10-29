"""Drawn from a series: a trendline - a least-squares fit (linear, polynomial, exponential, logarithmic,
power) or a moving average - and error bars - a constant, a percentage of each value, or another
series' values; on y, x or both; as bars with caps or as a band. Each is kept in the settings file
under the series' key, can be undone, and is drawn again whenever its series is (refresh(), before
every draw): a run of the sliders, the window opening. Drawn in the series' colour unless given one,
hidden with it; the trendline is in the legend, with its equation and R² if asked. Fits use the
points with finite values that the model allows (y > 0 for exponential and power, x > 0 for
logarithmic and power); x is matplotlib's float - for dates, days since 1970."""
import math

import numpy as np
from matplotlib.lines import Line2D

from . import _series, _view
from ._history import history
from ._settings import store

TRENDS = [('linear', 'Linear'), ('poly', 'Polynomial'), ('exp', 'Exponential'), ('log', 'Logarithmic'),
          ('power', 'Power'), ('mean', 'Moving average')]
ERRORS = [('constant', 'Constant'), ('percent', 'Percent of each value'), ('series', 'Values of another series')]
BARS_MOST = 20000   # error bars for more points than this are drawn as a band: bars would fill the plot solid
SAMPLES = 400       # a fitted curve is drawn through this many points
BAND_ALPHA = 0.22
_SUPERSCRIPT = str.maketrans('0123456789-', '⁰¹²³⁴⁵⁶⁷⁸⁹⁻')
_drawn = []   # (the series' artist, what was drawn for it)


def spec(s):
    """{'trend': {...}, 'errors': {...}} kept for the series (either may be missing)."""
    return dict(store.plots().get('fits', {}).get(_series.key_of(s), {}))


def info(s, which):
    """What the panel shows of what's drawn: {'equation', 'r2', 'points'} or {'error'} - or None."""
    drawn = getattr(s.artist, '_csn_fits', {}).get(which)
    return drawn[2] if drawn is not None else None


def set_trend(s, trend, record=True):
    _set(s, 'trend', trend, record, 'Trendline')


def set_errors(s, errors, record=True):
    _set(s, 'errors', errors, record, 'Error bars')


def _set(s, which, value, record, name):
    key, figure = _series.key_of(s), s.ax.figure
    old = store.plots().get('fits', {}).get(key, {}).get(which)
    if old == value:
        return
    _put(key, which, value, figure)
    if record:
        history.push(f"{'Change' if value and old else 'Add' if value else 'Remove'} {name.lower()}",
                     lambda: _put(key, which, old, figure), lambda: _put(key, which, value, figure))


def _put(key, which, value, figure):
    _series.quiet()
    fits = store.plots().setdefault('fits', {})
    if value:
        fits.setdefault(key, {})[which] = dict(value)
    else:
        fits.get(key, {}).pop(which, None)
        if not fits.get(key):
            fits.pop(key, None)
    store.changed()
    s = _series.find(key)
    target = s.ax.figure if s is not None else figure
    if target is not None and target.canvas is not None:
        target.canvas.draw_idle()


# ---- drawing them, before each draw

def refresh(figure):
    """What's kept for the figure's series drawn as their data is now - and what was drawn for a
    series no longer there, gone."""
    for item in list(_drawn):
        parent, artists = item
        if _gone(parent):
            _remove(artists)
            _drawn.remove(item)
    fits = store.plots().get('fits', {})
    for ax in figure.axes:
        legend = False
        for s in _series.series(ax):
            have = getattr(s.artist, '_csn_fits', None)
            wanted = fits.get(_series.key_of(s)) if fits else None
            if have is None and not wanted:
                continue
            have = have or {}
            if s.parts and not s.stem:   # the script's own error bars: shown only while no others are picked
                own = not (wanted or {}).get('errors') and s.visible()
                for part in s.parts:
                    if part.get_visible() != own:
                        part.set_visible(own)
            for which in ('trend', 'errors'):
                value = (wanted or {}).get(which)
                signature = _signature(s, which, value)
                old = have.get(which)
                if old is not None and old[0] == signature:
                    continue
                if old is not None:
                    _remove(old[1])
                    _forget(old[1])
                    have.pop(which)
                if value is None or (which == 'errors' and value.get('kind') == 'none'):   # none at all
                    continue
                try:
                    artists, found = (_trend if which == 'trend' else _errors)(s, value)
                except (ValueError, TypeError, np.linalg.LinAlgError, FloatingPointError) as error:
                    artists, found = [], {'error': f"{type(error).__name__}: {error}"}
                have[which] = (signature, artists, found)
                _drawn.append((s.artist, artists))
                legend = legend or which == 'trend'
            s.artist._csn_fits = have
        if legend or (ax.get_legend() is not None and _stale_legend(ax)):
            _view.legend_again(ax)


def _stale_legend(ax):
    legend = ax.get_legend()
    texts = {t.get_text() for t in legend.get_texts()}
    return any(isinstance(a, Line2D) and a.get_gid() == _series.OURS and a.get_label() not in texts
               and not str(a.get_label()).startswith('_') for a in ax.lines)


def _signature(s, which, value):
    if value is None:
        return None
    artist = s.artist
    if s.kind == 'line':
        data = (id(artist._xorig), id(artist._yorig))
    elif s.kind == 'scatter':
        data = (id(artist._offsets),)
    else:
        data = (id(artist),)
    source = None
    if which == 'errors' and value.get('kind') == 'series':
        other = _series.find(value.get('source', ''))
        source = None if other is None else (id(other.artist), *(_signature(other, 'trend', {}) or ()))
    return (repr(sorted(value.items())), data, len(s), s.colour(), s.visible(), s.ax.get_xscale(), source)


def _gone(parent):
    ax = getattr(parent, 'axes', None)
    if ax is None and getattr(parent, 'patches', None):
        ax = parent.patches[0].axes
    return ax is None or (parent not in ax._children and parent not in ax.containers)


def _remove(artists):
    for artist in artists:
        try:
            artist.remove()
        except (ValueError, NotImplementedError, AttributeError):
            pass


def _forget(artists):
    for item in list(_drawn):
        if item[1] is artists:
            _drawn.remove(item)


def _ours(artist, s, below):
    for part in ([artist] if not hasattr(artist, 'get_children') or isinstance(artist, Line2D)
                 else [artist, *artist.get_children()]):
        if hasattr(part, 'set_gid'):
            part.set_gid(_series.OURS)
            part.set_visible(s.visible())
            part.set_zorder(_zorder(s) + (-0.2 if below else 0.1))


def _zorder(s):
    first = s.artist.patches[0] if s.kind == 'bars' and s.artist.patches else s.artist
    return first.get_zorder() if hasattr(first, 'get_zorder') else 2


# ---- trendlines

def _trend(s, value):
    x, y = s.floats()
    kind = value.get('kind', 'linear')
    usable = np.isfinite(x) & np.isfinite(y)
    if kind in ('exp', 'power'):
        usable &= y > 0
    if kind in ('log', 'power'):
        usable &= x > 0
    x, y = x[usable], y[usable]
    degree = int(min(max(value.get('degree', 2), 1), 9))
    least = degree + 1 if kind == 'poly' else 2
    if kind == 'mean':
        window = int(max(value.get('window', 5), 2))
        if len(y) < window:
            return [], {'error': f"The series has fewer than {window} usable points"}
        averaged = np.convolve(y, np.ones(window) / window, mode='valid')
        xs, ys = x[window // 2: window // 2 + len(averaged)], averaged
        found = {'equation': f"mean of each {window} points in a row", 'r2': None, 'points': len(y)}
        name = f"moving average ({window})"
    else:
        if len(x) < least or np.ptp(x) == 0:
            return [], {'error': f"Not enough usable points for this fit ({len(x)})"}
        model, equation = _fit(kind, x, y, degree)
        predicted = model(x)
        total = float(np.sum((y - np.mean(y)) ** 2))
        r2 = 1 - float(np.sum((y - predicted) ** 2)) / total if total > 0 else None
        low, high = float(x.min()), float(x.max())
        xs = np.geomspace(low, high, SAMPLES) if s.ax.get_xscale() == 'log' and low > 0 \
            else np.linspace(low, high, SAMPLES)
        ys = model(xs)
        found = {'equation': equation, 'r2': r2, 'points': len(x)}
        name = dict(TRENDS)[kind].lower() + ' fit'
    label = f"{s.label}, {name}"
    if value.get('equation') and kind != 'mean':
        label += f": {found['equation']}" + (f", R² = {found['r2']:.4f}" if found['r2'] is not None else '')
    line = Line2D(xs, ys, color=value.get('colour') or s.colour(), linestyle=value.get('style', '--'),
                  linewidth=float(value.get('width', 1.6)), label=label)
    s.ax.add_line(line)
    _ours(line, s, below=False)
    return [line], found


def _fit(kind, x, y, degree):
    if kind in ('linear', 'poly'):
        polynomial = np.polynomial.Polynomial.fit(x, y, 1 if kind == 'linear' else degree)
        coefficients = polynomial.convert().coef   # in x itself, for the equation (the fit is scaled)
        return polynomial, 'y = ' + _polynomial(coefficients)
    if kind == 'exp':
        b, log_a = np.polyfit(x, np.log(y), 1)
        a = math.exp(log_a)
        return (lambda v: a * np.exp(b * v)), f"y = {_n(a)}·e^({_n(b)}·x)"
    if kind == 'log':
        b, a = np.polyfit(np.log(x), y, 1)
        return (lambda v: a + b * np.log(v)), f"y = {_n(a)} {_signed(b)}·ln x"
    b, log_a = np.polyfit(np.log(x), np.log(y), 1)
    a = math.exp(log_a)
    return (lambda v: a * np.power(v, b)), f"y = {_n(a)}·x^{_n(b)}"


def _n(value):
    return f"{value:.4g}"


def _signed(value):
    return f"− {_n(-value)}" if value < 0 else f"+ {_n(value)}"


def _polynomial(coefficients):
    terms = []
    for power in range(len(coefficients) - 1, -1, -1):
        c = float(coefficients[power])
        if c == 0 and len(coefficients) > 1:
            continue
        variable = '' if power == 0 else 'x' if power == 1 else 'x' + str(power).translate(_SUPERSCRIPT)
        number = _n(abs(c)) if not (variable and math.isclose(abs(c), 1.0)) else ''
        sign = ('−' if c < 0 else '') if not terms else ('− ' if c < 0 else '+ ')
        terms.append(f"{sign}{number}{'·' if number and variable else ''}{variable}")
    return ' '.join(terms) or '0'


# ---- error bars

def _errors(s, value):
    x, y = s.floats()
    kind = value.get('kind', 'constant')
    amount = float(value.get('value', 0) or 0)
    if kind == 'constant':
        size = np.full(len(y), abs(amount))
    elif kind == 'percent':
        size = np.abs(y) * abs(amount) / 100
    else:
        other = _series.find(value.get('source', ''))
        if other is None:
            return [], {'error': 'The series with the errors is not there'}
        size = np.abs(other.floats()[1])
        if len(size) != len(y):
            return [], {'error': f"“{other.label}” has {len(size):,} values, this series {len(y):,}"}
    axis = value.get('axis', 'y')
    style = value.get('style', 'bars')
    found = {'points': len(y)}
    if style == 'bars' and len(y) > BARS_MOST:
        style = 'band'
        found['note'] = f"Drawn as a band: bars for {len(y):,} points would fill the plot"
    colour = value.get('colour') or s.colour()
    ax = s.ax
    artists = []
    if style == 'band':
        order = np.argsort(x, kind='stable') if axis != 'x' else np.argsort(y, kind='stable')
        xs, ys, es = x[order], y[order], size[order]
        if axis in ('y', 'both'):
            artists.append(ax.fill_between(xs, ys - es, ys + es, color=colour, alpha=BAND_ALPHA, linewidth=0,
                                           label='_nolegend_'))
        if axis in ('x', 'both'):
            artists.append(ax.fill_betweenx(ys, xs - es, xs + es, color=colour, alpha=BAND_ALPHA, linewidth=0,
                                            label='_nolegend_'))
    else:
        container = ax.errorbar(x, y, yerr=size if axis in ('y', 'both') else None,
                                xerr=size if axis in ('x', 'both') else None, fmt='none', ecolor=colour,
                                elinewidth=1.0, capsize=float(value.get('caps', 3)), label='_nolegend_')
        artists.append(container)
    for artist in artists:
        _ours(artist, s, below=True)
    return artists, found


def _reset():
    for _, artists in _drawn:
        _remove(artists)
    _drawn.clear()
    for figure in _series.figures():
        for ax in figure.axes:
            for s in _series.series(ax, everything=True):
                if hasattr(s.artist, '_csn_fits'):
                    s.artist._csn_fits = {}


_view.on_reset.append(_reset)
