To install use:

pip install https://github.com/Namyeong3/csn-matplotlib/archive/refs/heads/main.zip


## This app was made with Claude Code, it is not human code, so take it with a grain of salt.


## How to use

```python
import csn_matplotlib          # first - then matplotlib as always
import matplotlib.pyplot as plt

fig, ax = plt.subplots(num='My tab')   # each figure is a tab; num names it
ax.plot(x, y, label='data')
plt.show()
```

Without the import, matplotlib is untouched.

## Parameters (sliders, tick boxes, buttons)

```python
def draw(speed=1.0, steps=500, damped=True):   # draws into axes made outside it
    ax.plot(*simulate(speed, steps, damped), label='run')

def report(speed, steps):                      # gets the values it names
    print(speed, steps)                        # shows in the terminal too

def faster(speed):
    return {'speed': speed * 2}                # a dict back = new slider values, redrawn

csn_matplotlib.sliders(draw, figure=fig,
                       speed=(0.1, 10),          # (low, high) -> slider
                       steps=(10, 10_000, 'log'),# whole numbers stay whole; 'log' scale
                       damped=True,              # True / False / bool -> tick box
                       buttons={'Report': report, 'Faster': faster})
```

In a long run, call `csn_matplotlib.progress(i, n)` (or take a `progress` parameter) for a progress bar.
`csn_matplotlib.Stopped` is raised when a run is stopped, so let it through.

## Keys

| Key | Does |
|---|---|
| Ctrl+B | side panel |
| Ctrl+J | terminal |
| F11 | plots only (again: back) |
| Ctrl+Z / Ctrl+Y | undo / redo |
| Ctrl+T / Ctrl+W / Ctrl+Shift+T | new / close / reopen tab |
| Space | fit the plot |
| Esc | stop a run |
