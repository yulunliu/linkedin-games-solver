# Usage guide

*[中文版 / Chinese version](USAGE.zh-TW.md)*

---

## Installing

### Option 1 — the .exe (Windows, nothing to install)

Download `PuzzleSolver.exe` from [Releases](../../releases) and double-click it.
That is the whole installation.

Windows SmartScreen may warn about an unsigned executable. Click *More info* →
*Run anyway*, or build it yourself from source (see below).

### Option 2 — from source

```bash
pip install -r requirements.txt
```

```bash
python run.py
```

Python 3.9 or newer. Tkinter ships with Python, so there is nothing else to
install.

---

## The window

The app opens with two modes; pick one at the top.

### Mode: Screen (auto-play)

Reads the puzzle off your screen, solves it, and fills it in with the mouse.
Windows only.

| Control | What it does |
|---|---|
| **Board** | The screen rectangle to capture (X / Y / W / H). **Reset** restores the default; **Test** shows what would be captured |
| **Puzzle** | Leave on *Auto-detect* unless it guesses wrong |
| **Speed** | Fastest / Faster / Fast / Normal / Slow / Slowest. Start at Normal; if the page cannot keep up, go slower. Measured five-game fill totals: Normal 37s, Fast 21s, Faster 20s, Fastest 18s - Fastest and Faster are pulled close to Fast on purpose (an earlier, far more aggressive Fastest caused real dropped input and was pulled back) but remain less tested; dropped clicks are self-repaired by the verify pass, a Zip drag that outruns the page is not |
| **Preview** | Tick this and it prints the plan without touching the mouse |
| **Hide** | Minimise the app window while it plays. Left unticked, the window stays visible but is automatically kept clear of the capture region - it can no longer sit on top of the board and block part of it from ever being captured (2026-08-08: this is exactly what broke Mini Sudoku recognition for a whole session) |
| **Verify** | After filling, re-read the board and fix any cells that did not take |
| **Solve & Fill** | Do it |
| **Solve only** | Work out the answer and show it, but do not touch the mouse |
| **Stop** | Abort immediately |
| **Save** | Save the captured image — useful when reporting a recognition problem |

**If you switch monitors, change resolution, or change Windows display
scaling**, the saved **Board** rectangle can go stale — it is a fixed
position on screen, calibrated once. The app now remembers the screen size
from when the region was last actually calibrated and warns (without
blocking) when it no longer matches. If you see this warning and solving
starts failing, press **Reset** or **Test** to recalibrate.

### Mode: Image file

Solves a screenshot and draws the answer on it. Never touches the mouse. Works
on any platform.

| Control | What it does |
|---|---|
| **Choose image…** | Pick a screenshot — phone or desktop, both work |
| **Puzzle** | Usually leave on *Auto-detect* |
| **Solve & Fill** | Solves and shows the answer drawn on the image |
| **Save answer image…** | Save the answer overlay to a file |

### Language

The **Language** selector switches the whole interface between English and 中文.
Your choice is saved and applies next time you open the app.

---

## Playing a sitting on the web (continuous mode)

The order is the opposite of what you might expect: **press the button first,
open the puzzle second**. And **one press covers the whole sitting**: after
**Solve & Fill**, the program keeps watching the capture region - every
puzzle that appears gets solved and filled, one after another, until you
press **Stop**.

1. Start the app and select **Screen (auto-play)**.
2. Optional but recommended the first time: tick **Preview**, press
   **Solve & Fill**, and switch to the puzzle page. It prints exactly what it
   would click without touching anything (a preview runs one round and
   stops). Check the puzzle type and board size look right, then untick.
3. Press **Solve & Fill**. The status line shows it is watching the screen.
4. Switch to Chrome and open the first puzzle. Do not scroll the board out
   of view.
5. **Take your hands off the mouse.** The moment the board appears, it plays.
6. When a round finishes the status line asks for the next puzzle. Open it
   and the program takes over again; press **Stop** after the last one.

Pressing the button with the puzzle already on screen also works - it detects
the board within a second and starts right away. If recognition fails on a
round (say the page's entrance animation had not settled), it automatically
retries on a fresh capture up to three times.

**If it still fails after all three attempts, it does not fail silently.**
The window comes back into view, a system alert sound plays, the status line
turns red, and continuous mode stops there instead of waiting unattended for
a puzzle that will never be filled. If every retry hit the exact same error,
the message says so explicitly - that means retrying again by hand is
unlikely to help either, and it is worth checking the capture region (press
**Test**) before starting again. Play the puzzle by hand, then press
**Solve & Fill** again for the next one.

### While it is running

- Move the mouse to any corner of the screen to abort (PyAutoGUI's failsafe).
- Or press **Stop**.
- The log shows each stage and the elapsed time per stage.

### Why it waits a second before starting

So that your click on *Solve & Fill* has finished before the automation begins.
With no delay, your mouse button was still physically down when it started
clicking, and the two inputs interleaved and scrambled the board.

### How it knows to stop

After filling in, it re-reads the board:

- **A few cells are wrong** → it re-clicks just those cells (if **Verify** is on).
- **The board is gone** — replaced by the site's completion screen → it stops
  and releases the mouse.

This is why it does not keep clicking at a finished puzzle.

---

## Solving from a screenshot

1. Take a screenshot of the puzzle. On a phone, the standard screenshot is fine —
   no need to crop, the board is found automatically.
2. Transfer it to the computer.
3. Start the app, choose **Image file**, then **Choose image…**.
4. Press **Solve & Fill**. The answer is drawn on the image.
5. **Save answer image…** if you want to keep it.

The answer overlay shows suns and moons as suns and moons, crowns as crowns,
the Zip path as a line, and the Patches tiling as outlined rectangles — so you
can copy it across by eye.

---

## Command line

Same engine, no window. **It defaults to a dry run** — nothing moves unless you
say `--go`.

Solve an image file and save the answer:

```bash
python -m linkedin_games_solver.ui.cli --image screenshot.png --out answer.png
```

Preview what it would do on screen, without touching the mouse:

```bash
python -m linkedin_games_solver.ui.cli --screen
```

Actually play, a bit slower than default:

```bash
python -m linkedin_games_solver.ui.cli --go --slowdown 2.5
```

Capture just one rectangle of the screen:

```bash
python -m linkedin_games_solver.ui.cli --region 700,200,900,900 --go
```

Force the puzzle type and board size when auto-detection is wrong:

```bash
python -m linkedin_games_solver.ui.cli --image shot.png --type queens --grid-size 9
```

Puzzle keys: `tango`, `queens`, `sudoku`, `zip`, `patches`.

---

## When something goes wrong

### "Recognition failed"

This is the *good* failure — it knows it could not read the board, so it stops
rather than filling in a guess.

1. Press **Test** to check the capture region contains the whole board.
2. If the board is small, zoom the page in with `Ctrl` `+`. Recognition is
   calibrated for boards around 794 px wide and warns below 500 px.
3. Press **Save** and look at the saved image — if the board is cut off,
   adjust X / Y / W / H.
4. If the board looks fine in the saved image, set **Puzzle** explicitly instead
   of *Auto-detect*.

### It picked the wrong puzzle type

Set **Puzzle** manually. Auto-detection is right on every board tested, but a
new colour scheme could still fool it.

### The page cannot keep up / Zip says "you must follow the number order"

Set **Speed** to *Slow* or *Slowest*. Zip is filled with one continuous drag,
and the page has to see every cell the pointer crosses.

### It clicked in the wrong place

The capture region and the browser window must not move between capture and
fill. Do not scroll or resize the window while it is running.

### It filled some cells but not others

Turn on **Verify**. It re-reads the board and re-clicks the cells that did not
take. It gives up after a round with no improvement, so it cannot thrash a
partly-correct board back into a wrong one.

### The .exe will not start

If you built it yourself and it dies with `DLL load failed while importing
cp_model_helper`, PyInstaller missed OR-Tools' native DLLs. Rebuild with:

```bash
pyinstaller --onefile --windowed --collect-all ortools --name PuzzleSolver run.py
```

---

## Running the tests

```bash
python tests/run_all.py
```

All three suites are offline and none of them moves the mouse.

---

## Related documents

- [DESIGN.md](DESIGN.md) — why it is built this way
- [ARCHITECTURE.md](ARCHITECTURE.md) — module by module
- [ROADMAP.md](ROADMAP.md) — what is next
- [EVOLUTION.md](EVOLUTION.md) — what has been built so far, by theme
