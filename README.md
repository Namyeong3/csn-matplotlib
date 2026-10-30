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

def report(speed, steps):                      # a button: gets the values it names
    print(speed, steps)                        # prints and errors show in the terminal

def faster(speed):
    return {'speed': speed * 2}                # a dict back = new slider values, redrawn (past the top: the range grows)

def ask():
    return {'speed': float(input('Speed: '))}  # input() asks in the terminal

csn_matplotlib.sliders(draw, figure=fig,
                       speed=(0.1, 10),          # (low, high) -> slider
                       steps=(10, 10_000, 'log'),# whole numbers stay whole; 'log' scale
                       damped=True,              # True / False / bool -> tick box
                       buttons={'Report': report, 'Faster': faster, 'Ask': ask})
                       # or buttons=[report, faster]: each named after its function
```

In a long run, call `csn_matplotlib.progress(i, n)` (or take a `progress` parameter) for a progress bar.
`csn_matplotlib.Stopped` is raised when a run is stopped, so let it through.

## Terminal

Ctrl+J or Alt+T. Shows what the script prints and its errors, and has a Python prompt in the script's
namespace (its variables and imports). A command that changes a figure redraws it; one that makes a
figure opens it in a tab. `input()` asks here once the window is open.

| Key | Does |
|---|---|
| Tab | complete |
| Up / Down | earlier commands |
| Ctrl+L | clear |
| Ctrl+C | drop the typed line / interrupt a waiting `input()` |
| Esc | empty the line |

## Keys

| Key | Does |
|---|---|
| Ctrl+B / Alt+S | side panel |
| Ctrl+J / Alt+T | terminal |
| F2 | rename the tab, series or plot under the pointer |
| F11 | plots only (again: back) |
| Ctrl+Z / Ctrl+Y | undo / redo |
| Ctrl+T / Ctrl+W / Ctrl+Shift+T | new / close / reopen tab |
| Space | fit the plot |
| Esc | stop a run |
