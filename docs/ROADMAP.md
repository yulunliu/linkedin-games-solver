# Roadmap

*[中文版 / Chinese version](ROADMAP.zh-TW.md)*

What is known to be limited, and what is planned about it. Written as honestly
as possible — these are the places where the current code works because of an
assumption that happens to hold, not because the problem is solved.

**None of these stop the program working today.** Everything here is a gap in
coverage, robustness or polish, not a broken feature. They are written down so
that nobody — including future me — has to rediscover them.
**以下沒有一項會讓程式現在無法使用。** 這裡全部都是涵蓋範圍、強健度或完成度上的
缺口，不是壞掉的功能。寫下來是為了讓任何人（包括未來的我）不必重新發現一次。

| # | Gap | Impact today | Effort |
|---|---|---|---|
| [1](#1-screen-mode-assumes-one-particular-display) | Screen mode assumes the primary monitor | You may have to set the capture region by hand | medium |
| [2](#2-image-mode-is-calibrated-for-iphone-13-pro-screenshots) | Image thresholds calibrated on one device | Other devices may fail to read — but fail loudly, not wrongly | medium |
| [3](#3-verify-and-retry-does-not-cover-zip-or-patches) | No verification for Zip and Patches | A drag the page missed is not detected or retried | medium |
| [4](#4-error-messages-ignore-the-language-setting) | Errors are not translated | English users see Chinese in error text | low, but touches many files |
| [5](#5-the-0-and-7-templates-have-never-seen-a-real-board) | 0 and 7 templates are font-derived | Untested; would fail rather than misread | needs a screenshot |

---

## 1. Screen mode assumes one particular display

### Where it stands

Screen capture already avoids the worst hard-coding. `capture.py` finds the
primary monitor by looking for the display containing screen origin `(0, 0)`,
because `mss.monitors[1]` is *not* reliably the primary one on a multi-monitor
setup. The default capture rectangle is then computed relative to that monitor
rather than in absolute coordinates:

```python
def default_region():
    monitor = primary_monitor()
    left = monitor["left"] + (monitor["width"] - DEFAULT_REGION_WIDTH) // 2
    top  = monitor["top"] + DEFAULT_REGION_TOP
    return left, top, DEFAULT_REGION_WIDTH, DEFAULT_REGION_HEIGHT
```

So it survives a different primary resolution, and the region is editable in the
UI for anything else.

### What is still wrong

- **The default size and vertical offset are guesses** from one setup:
  640 × 700 at y = 200. On a 4K display, or a browser at a different zoom, the
  board simply is not there and the user has to fix it by hand.
- **A board on the second monitor is never found.** Capture is confined to the
  primary display; there is no search across displays.
- **Windows display scaling is unhandled.** At 125 % or 150 % DPI scaling, `mss`
  and `pyautogui` can disagree about what a "pixel" is, so the capture is right
  and the clicks land slightly off.

### Planned

1. **Find the board instead of being told where it is.** The board detector in
   `core/board.py` already locates a board inside an arbitrary image. Capture
   the whole virtual desktop, run detection on a downscaled copy, then re-capture
   just the region that was found at full resolution. This removes the region
   controls from the normal path entirely — they stay as a manual override.
2. **Search every monitor.** `mss.monitors[0]` is the union of all displays;
   detecting on that and mapping the result back gives multi-monitor support
   almost for free once step 1 exists.
3. **Make DPI scaling explicit.** Declare the process per-monitor DPI aware via
   `SetProcessDpiAwareness`, then assert once at startup that a known screen
   coordinate round-trips through capture and back — and warn loudly if it does
   not, rather than clicking 30 px off in silence.
4. **Remember where the board was found.** Cache the last successful region in
   settings and try it first, so the common case stays fast.

Step 1 is the one that matters; 2 and 4 fall out of it.

---

## 2. Image mode is calibrated for iPhone 13 Pro screenshots

### Where it stands

The pipeline is *less* resolution-dependent than it looks. Every board is
rescaled to a fixed size before any threshold is applied:

```python
TARGET_BOARD_PIXELS = 794     # everything is calibrated at this size
MIN_BOARD_PIXELS = 500        # below this, upscale rather than trust it
```

and when a first attempt fails or produces a non-unique solution, it retries at
other prescale factors and centre crops. That is what lets the same code read
both a 1170 × 2532 phone screenshot and a desktop browser capture.

### What is still wrong

Three things are genuinely tied to the phone the fixtures came from:

- **The digit templates.** `core/digit_templates.py` holds glyphs captured from
  one app rendering at a handful of sizes. They are normalised to 28 × 28 before
  matching, so moderate size differences are fine — but a different font weight,
  heavier anti-aliasing, or a device that renders digits with a different stroke
  ratio will start producing mismatches. Those now *fail* rather than guess (the
  margin check in `digits.py` rejects anything whose runner-up is close), but
  failing is still failing: `tools/calibrate_digits.py` is the answer, and it
  needs screenshots from that device.
- **0 and 7 have never been seen on a real board.** No fixture contains either,
  so those two templates are font-derived. They are baked into the source so
  coverage does not depend on the machine, but they are untested against the
  app's actual rendering.
- **The crop fractions.** `_CROP_FRACTIONS = (1.0, 0.85, 0.72, 0.6, 0.5)` were
  chosen by measuring how much of an iPhone 13 Pro screenshot is board versus
  status bar, notch area, and the app's own chrome. A tablet screenshot, or a
  phone with very different proportions, may need a crop that is not in the
  list.
- **Colour thresholds assume the phone app's palette.** `detect_type.py` and
  `queens.py` were calibrated against the app's colours. LinkedIn has already
  shipped one pastel Queens variant that broke type detection once; the fix
  (corner fill coverage) is more robust than the saturation test it replaced,
  but it is still a fixed number.

### Planned

1. **Derive thresholds from the image, not from a constant.** Most of these are
   really asking "is this cell noticeably darker/more saturated than the board
   background?" Measuring the board's own background first, and expressing
   thresholds relative to it, removes the dependence on any particular
   rendering. This is the single highest-value change in this section.
2. **Detect the board without the crop list.** The crop fractions exist to help
   board detection when a screenshot has a lot of non-board content. A stronger
   detector — largest quadrilateral contour with a near-square aspect ratio and
   internal grid structure — would find the board directly and make the crop
   ladder a fallback rather than a requirement.
3. **Say *which* glyph was unreadable.** Recognition now refuses to guess an
   ambiguous digit, but the resulting message is generic. "Unreadable digit at
   label (3,4)" would tell the user exactly where to look and exactly what to
   send in a bug report. The information exists at the point of failure; it is
   simply not carried out.
4. **Collect fixtures from other devices.** Everything above is guesswork
   without test images from an Android phone, an iPad, and a non-Retina desktop.
   `tests/test_recognition.py` is structured to make adding a fixture cheap, and
   `tools/calibrate_digits.py` turns a new device's screenshots into templates
   in one command.

Done since the first draft of this document 這份文件初稿之後已完成:
`tools/calibrate_digits.py` is now shipped, and digits 0 and 7 are baked into
the source instead of being rendered from a Windows font at import time — see
[CHANGELOG.md](../CHANGELOG.md).

---

## 3. Verify-and-retry does not cover Zip or Patches

### Where it stands

After filling in, `verify()` re-reads the board and either fixes the wrong cells
or stops because the board is gone. But the dispatch table has three entries:

```python
_VERIFIERS = {queens.KEY: _verify_queens, tango.KEY: _verify_tango, sudoku.KEY: _verify_sudoku}
```

Zip and Patches fall through to `supported=False`, which means: no check, no
retry, and no board-changed detection either.

### Why it matters

Those two are the *drag*-based puzzles — the ones most likely to go wrong. A
drag the page failed to follow is exactly the failure mode that
`DRAG_MAX_STEP_PX` and the speed multiplier exist to mitigate, and it is the one
case where nothing verifies the outcome. The program reports success and stops.

This is not a small gap dressed up as a minor one: for two of five puzzles, the
safety net that the rest of the design leans on is simply absent.

### Planned

1. **Read back the Zip path.** The drawn path is a thick coloured line; sampling
   the boundary between each pair of adjacent cells says whether the segment was
   drawn. Comparing that to the intended path gives both a correctness check and
   the point at which the drag broke down.
2. **Read back the Patches tiling.** Completed rectangles are drawn with a
   visible border; the existing label detector already locates each badge, so
   checking that each one sits inside a rectangle of the right size is close to
   what `find_labels` already does.
3. **At minimum, detect board-changed for all five.** Even without per-cell
   verification, noticing that the board is gone is cheap and would let Zip and
   Patches stop cleanly rather than just running out of actions.

Item 3 is small and should be done first.

---

## 4. Error messages ignore the language setting

### The problem

`i18n.py` translates the interface, but recognition and solver errors are
hard-coded bilingual strings built at the point of failure:

```python
return failure(KEY, "no solution / 找不到符合規則的解", grid=grid, info=info)
```

The same applies to `result.info` — board size, region counts, label counts.
Those strings go straight into the log area without passing through the
translator.

### Why it matters

Switching the interface to English does not switch the error text. So an
English-speaking user sees Chinese in the one place where a clear message
matters most: the moment something went wrong and they need to know what to do
about it. Requirement "the interface can switch language" is therefore only
half met.

It is a completeness problem, not a correctness one — the message is still
readable, just not in the chosen language.

### Planned

1. **Return a key and arguments, not a formatted string.** `failure()` and
   `info.append()` take something like `("err_no_solution", {})` or
   `("info_board_size", {"n": 6})`, and the UI formats at display time using
   the translator it already holds.
2. **Add the keys to `i18n.py`** — around 25 new entries, following the
   existing flat `{key: {lang: text}}` shape.
3. **Keep a plain-text fallback for the CLI**, which has no translator when
   `--image` is used before any settings are loaded.

Mechanical work that touches every puzzle module and both UIs. That breadth is
why it has not been done yet — not difficulty.

---

## 5. The 0 and 7 templates have never seen a real board

### The problem

No screenshot in `tests/fixtures/` contains a `0` or a `7`. Those two digit
templates are therefore rendered from system fonts, not captured from the app.

They are now baked into the source as bytes rather than rendered at import
time — so coverage no longer depends on which fonts a machine has, which was a
real bug (see [CHANGELOG.md](../CHANGELOG.md)). But baked-in is not the same as
verified.

### Why it matters

Less than it sounds, because of how the failure would surface. `classify_glyph`
rejects any glyph whose runner-up digit is within `MIN_MARGIN`, so an app-drawn
`7` that does not match the Arial-derived template would be reported as
**unreadable**, not misread as something else. Patches then falls back to
treating that label as "any size" and accepts the answer only if the tiling is
still unique; Zip fails the consecutive-numbering check.

So the realistic worst case is a refusal to solve, not a wrong answer. That is
the intended behaviour — but it is untested, and a refusal is still a failure.

### Planned

1. **Capture a board containing them.** A Zip puzzle with 7 or more numbered
   dots, or a Patches label of 7, is all it takes. These do occur; none has been
   screenshotted yet.
2. **Run `python tools/calibrate_digits.py`** with that screenshot wired into
   the truth table. The script refuses to write a set missing any digit 0-9, so
   it cannot regress.
3. **Add the fixture to `tests/test_recognition.py`** with the usual docstring
   saying what it guards.

Blocked on having the right screenshot, not on any code.

---

## 6. Smaller things worth doing

| Item | Why |
|---|---|
| **Get a fixture containing a 0 and a 7** | Those templates are font-derived and have never been checked against a real board. A Zip puzzle with 7+ dots, or a Patches label of 7, would do it |
| **Record a demo GIF** | The READMEs have a placeholder for one; the project is much easier to understand when you see it play |
| **Try DOM-free page-zoom detection** | Recognition degrades below 500 px. The app already warns; it could instead detect the zoom level and suggest a specific `Ctrl` `+` count |
| **A sixth puzzle** | [ARCHITECTURE.md](ARCHITECTURE.md#adding-a-sixth-puzzle) documents the six steps. Nothing in `core/` or `automation/`'s plumbing needs to change |
| **Broaden CI** | `.github/workflows/tests.yml` already runs the suites on Windows and Ubuntu across three Python versions. Worth adding a build job that produces the .exe |

---

## Not planned

- **DOM automation.** Reading LinkedIn's HTML would be easier and more robust
  than reading pixels. It would also delete the interesting half of the project
  and tie it to markup that can change without notice. See
  [DESIGN.md](DESIGN.md#what-was-deliberately-not-done).
- **A vision model for recognition.** Same reason — it answers the question by
  not answering it, and adds a network dependency and an API key to a tool that
  currently needs neither.
- **Cross-platform screen control.** Image mode already works anywhere. Screen
  mode uses Win32 window focusing, and porting it to macOS or Linux is a fair
  amount of work for a feature that duplicates something the user can already do
  with a screenshot.
- **Exposing the recognition thresholds as settings.** Every one was measured on
  real boards and is documented next to its measured values. A settings screen
  would invite tuning by guesswork — the right fix is item 2.1 above, making
  them adaptive so there is nothing to tune.

---

## Related documents

- [DESIGN.md](DESIGN.md) — why it is built this way
- [ARCHITECTURE.md](ARCHITECTURE.md) — module by module
- [USAGE.md](USAGE.md) — step by step
