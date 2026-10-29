"""A test of most of csn_matplotlib at once - five tabs:
- Oscillator: a damped, driven spring on sliders (progress reported), in a big plot with two small
  ones beside it (subplot_mosaic). Push stiffness up and the explicit Euler blows up to inf/nan; push
  steps to millions and it takes a while (Stop, Esc).
- Signals: three years of daily dates, two plots sharing x, one with a twin y axis (twinx), a band
  (fill_between) and bars.
- Statistics: a histogram, a scatter with a colorbar, error bars on a log x axis, a stem and a step.
- Big data: a random walk of many points as markers; past 20 million it asks before drawing.
- Controls: tick boxes among the sliders, and buttons running the script's own functions - one
  changes a slider, one prints into the terminal, one asks there with input(), one fails on purpose.
The terminal (Alt+T or Ctrl+J): what the script prints, its errors, and a Python prompt in the script's
own names - try last['signal'].std(), or temperature.set_title('Typed in the terminal'). Tab completes,
Up and Down go back through what was typed."""
import csn_matplotlib
import matplotlib.pyplot as plt
import numpy as np

rng = np.random.default_rng(7)


# ---- Oscillator: sliders, progress, things that blow up

oscillator = plt.figure('Oscillator', figsize=(13, 7))
axes = oscillator.subplot_mosaic([['time', 'phase'], ['time', 'energy']], width_ratios=[2, 1])
oscillator.suptitle('Damped, driven spring - explicit Euler')
axes['time'].set_xlabel('time (s)')
axes['time'].set_ylabel('position')
axes['phase'].set_xlabel('position')
axes['phase'].set_ylabel('velocity')
axes['energy'].set_xlabel('time (s)')
axes['energy'].set_ylabel('energy')
axes['energy'].set_yscale('log')


def spring(stiffness=4.0, damping=0.15, drive=0.5, drive_frequency=1.3, duration=40.0, steps=20_000, progress=None):
    dt = duration / steps
    t = np.linspace(0.0, duration, steps + 1)
    x, v = np.empty(steps + 1), np.empty(steps + 1)
    x[0], v[0] = 1.0, 0.0
    for i in range(steps):
        a = -stiffness * x[i] - damping * v[i] + drive * np.cos(drive_frequency * t[i])
        x[i + 1] = x[i] + dt * v[i]
        v[i + 1] = v[i] + dt * a
        if progress and i % 5000 == 0:
            progress(i, steps)
    energy = 0.5 * v ** 2 + 0.5 * stiffness * x ** 2
    axes['time'].plot(t, x, 'o', ms=2.5, label='position')
    axes['time'].plot(t, v, lw=1, label='velocity')
    axes['time'].axhline(0, color='0.5', lw=0.8)
    axes['time'].legend(loc='upper right')
    axes['time'].set_title(f"{steps:,} steps of {dt:.2g} s")
    axes['phase'].plot(x, v, lw=1)
    axes['energy'].plot(t, energy, lw=1, label='energy')


csn_matplotlib.sliders(spring, figure=oscillator, stiffness=(0.1, 1e6, 'log'), damping=(0.0, 2.0), drive=(0.0, 3.0),
                       drive_frequency=(0.1, 5.0), duration=(1.0, 200.0), steps=(100, 20_000_000, 'log'))


# ---- Signals: dates, sharex, twinx, a band, bars

signals, (temperature, rain) = plt.subplots(2, 1, sharex=True, figsize=(13, 7), num='Signals')
days = np.arange(np.datetime64('2023-01-01'), np.datetime64('2026-01-01'))
season = 12 - 9 * np.cos(2 * np.pi * np.arange(len(days)) / 365.25)
daily = season + rng.normal(0, 2.5, len(days))
temperature.plot(days, daily, lw=0.8, label='daily mean')
temperature.plot(days, season, lw=2, label='season')
temperature.fill_between(days, season - 4, season + 4, alpha=0.2, label='usual range')
temperature.set_ylabel('temperature (°C)')
temperature.set_title('Weather, three years')
temperature.legend(loc='upper left')
months = np.arange(np.datetime64('2023-01'), np.datetime64('2026-01')).astype('datetime64[D]') + np.timedelta64(14, 'D')
monthly = rng.gamma(4, 15, len(months))
rain.bar(months, monthly, width=np.timedelta64(24, 'D'), label='rain')
rain.set_ylabel('rain (mm)')
rain.set_xlabel('date')
total = rain.twinx()
total.plot(months, np.cumsum(monthly), color='#d95926', marker='o', ms=3, label='so far')
total.set_ylabel('rain so far (mm)')
rain.legend(loc='upper left')
total.legend(loc='upper right')


# ---- Statistics: hist, scatter + colorbar, errorbar on log x, stem, step

statistics, grid = plt.subplots(2, 2, figsize=(13, 8), num='Statistics')
samples = np.concatenate([rng.normal(0, 1, 4000), rng.normal(3.5, 0.6, 1500)])
grid[0, 0].hist(samples, bins=60, label='samples')
grid[0, 0].set_title('Two bumps')
grid[0, 0].set_xlabel('value')
grid[0, 0].set_ylabel('count')
x, y = rng.normal(0, 1, 800), rng.normal(0, 1, 800)
dots = grid[0, 1].scatter(x, y, c=np.hypot(x, y), s=14, cmap='viridis', label='points')
statistics.colorbar(dots, ax=grid[0, 1], label='distance from 0')
grid[0, 1].set_title('Scatter, coloured')
sizes = np.logspace(1, 5, 12)
times = 3e-4 * sizes * np.log(sizes) * rng.uniform(0.9, 1.1, len(sizes))
grid[1, 0].errorbar(sizes, times, yerr=times * 0.15, fmt='o-', capsize=3, label='measured')
grid[1, 0].set_xscale('log')
grid[1, 0].set_title('Error bars, log x')
grid[1, 0].set_xlabel('n')
grid[1, 0].set_ylabel('seconds')
k = np.arange(0, 30)
grid[1, 1].stem(k, np.exp(-k / 8) * np.cos(k / 2), label='impulse')
grid[1, 1].step(k, np.exp(-k / 8), where='mid', label='envelope')
grid[1, 1].set_title('Stem and step')
grid[1, 1].legend()


# ---- Big data: many markers; past 20 million points it asks first

big = plt.figure('Big data', figsize=(13, 7))
walk = big.add_subplot()
walk.set_xlabel('step')
walk.set_ylabel('position')


def random_walk(points=400_000, spread=1.0):
    csn_matplotlib.progress(0.1)
    steps = np.random.default_rng(1).normal(0, spread, points)
    csn_matplotlib.progress(0.6)
    walk.plot(np.arange(points), np.cumsum(steps), '.', ms=2, label='walk')
    walk.set_title(f"A random walk of {points:,} points")


csn_matplotlib.sliders(random_walk, figure=big, points=(1000, 25_000_000, 'log'), spread=(0.1, 5.0))


# ---- Controls: tick boxes and buttons next to the sliders, prints in the terminal

controls, (wave, spectrum) = plt.subplots(1, 2, figsize=(13, 6), num='Controls', width_ratios=[2, 1])
wave.set_xlabel('time (s)')
wave.set_ylabel('signal')
spectrum.set_xlabel('frequency (Hz)')
spectrum.set_ylabel('amplitude')
spectrum.set_title('Spectrum')
last = {}   # the last run's signal, for the buttons


def waves(frequency=2.0, amplitude=1.0, seed=0, noisy=True, smoothed=False, envelope=True):
    t = np.linspace(0, 10, 2000)
    decay = amplitude * np.exp(-t / 8)
    signal = decay * np.sin(2 * np.pi * frequency * t / 5)
    if noisy:
        signal = signal + np.random.default_rng(seed).normal(0, 0.25, t.size)
    if smoothed:
        signal = np.convolve(signal, np.ones(25) / 25, mode='same')
    wave.plot(t, signal, lw=1, label='signal')
    if envelope:
        wave.plot(t, decay, '--', lw=1, label='envelope')
        wave.plot(t, -decay, '--', lw=1, color=wave.lines[-1].get_color(), label='_nolegend_')
    wave.legend(loc='upper right')
    wave.set_title(f"{'Noisy' if noisy else 'Clean'}{', smoothed' if smoothed else ''} wave")
    frequencies = np.fft.rfftfreq(t.size, t[1] - t[0])
    spectrum.plot(frequencies[:120], np.abs(np.fft.rfft(signal))[:120] / t.size, lw=1, label='spectrum')
    last['signal'] = signal


def new_noise(seed):   # a dict given back goes onto the sliders, and is drawn
    return {'seed': seed + 1}


def summary(frequency, amplitude, noisy, smoothed):   # only prints: the terminal (Ctrl+J) shows it
    signal = last.get('signal')
    if signal is not None:
        print(f"frequency {frequency:.2f}, amplitude {amplitude:.2f}, noisy {noisy}, smoothed {smoothed}: "
              f"mean {signal.mean():+.3f}, std {signal.std():.3f}, peak {np.abs(signal).max():.3f}")


def louder(amplitude):   # past the slider's top: its range goes with it
    return {'amplitude': amplitude * 1.5}


def typed_frequency(frequency):   # input() asks in the terminal, which opens for it
    answer = input(f"Frequency in Hz (now {frequency:.2f}; Enter keeps it): ").strip()
    return {'frequency': float(answer)} if answer else None


def fails():
    raise ValueError('this button fails on purpose - its error is in the terminal')


csn_matplotlib.sliders(waves, figure=controls, frequency=(0.5, 10.0), amplitude=(0.1, 3.0), seed=(0, 1000),
                       noisy=True, smoothed=False, envelope=bool,
                       buttons={'New noise': new_noise, 'Print summary': summary, 'Louder': louder,
                                'Type a frequency': typed_frequency, 'A button that fails': fails})

print(f"csn_matplotlib showcase: {len(plt.get_fignums())} figures loaded.")
plt.show()
