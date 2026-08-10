# Design rationale

*[中文版 / Chinese version](DESIGN.zh-TW.md)*

Why this exists, why it is shaped the way it is, and what had to be changed
along the way. If you only read one section, read
[The principle](#the-principle-succeeding-is-not-the-same-as-being-correct).

---

## Why build it at all

LinkedIn publishes five puzzles a day. They are timed, and the time is what you
share. Solving them by hand is the point of the game — but working out *how a
computer could see the board at all* turned out to be a much more interesting
problem than the puzzles themselves.

So the goal was never "get a fast time". The goal was: **can a program look at
the same pixels a human looks at, and understand them?** Everything else follows
from that. Which is also why there is no AI and no API anywhere in this project.
Sending the screenshot to a vision model would answer the question by not
answering it.

The project grew in three stages, and the shape of the code still shows it:

1. **Read a phone screenshot, print the answer.** One puzzle (Tango), one script.
2. **All five puzzles, in one double-clickable .exe.** This forced the split
   between generic board-finding and per-puzzle reading.
3. **Play it directly in the browser.** This added everything under
   `automation/`, and with it a whole class of new problems — the answer now had
   to be not just right, but *actionable*, and safely so.

---

## The principle: succeeding is not the same as being correct

This is the single most important idea in the codebase, and it was learned the
hard way.

Early on, a Tango board was solved and the answer looked completely plausible:
every row balanced, no three in a row, every constraint satisfied. It was wrong.
Recognition had found only one of the four `=` / `×` marks, and the solver had
faithfully solved *a different puzzle* — one that happened to be legal.

That is the dangerous failure mode. A crash is fine; you see it and fix it. An
answer that is wrong but internally consistent is not fine, especially once the
program is moving your mouse based on it.

Three defences came out of that, and they are used everywhere:

### 1. Uniqueness as a completeness check

Published puzzles have exactly one solution. That is a fact about the *puzzle*,
which means it can be used as a test of the *recognition*:

> If the solver can find two solutions, recognition must have missed a constraint.

So Tango, Sudoku and Patches do not just solve — they ask the solver to find a
*second* solution, and reject the answer if one exists. This catches missing
`=` marks, missing givens, and mis-read digits without needing to know anything
about what was missed.

```python
# tango.py, in essence
solution = solve(model)
model.AddForbidden(solution)      # "now find a different one"
if solve(model) is not None:
    raise MultipleSolutions       # recognition is incomplete
```

Queens and Zip are exempt: their answers are inherently unique given a correctly
read board, so they use structural guards instead (below).

### 2. Structural sanity guards

Uniqueness does not help when the *structure* is misread. Two guards were added
after specific incidents:

- **Queens region validity.** A pastel Queens board was misclassified as
  Patches, and "solved" as one giant rectangle covering the board — reported as
  success, then dragged the mouse from corner to corner. Now Queens verifies
  that it found exactly *n* colour regions and that each one is contiguous.
- **Patches label count.** The same incident from the other side: Patches now
  refuses to proceed on fewer than three labels, because a board that looks like
  it has one or two labels is almost certainly not a Patches board.

### 3. Normalise, then retry at other scales

Every threshold in this project was calibrated on boards around 794 px wide. At
390 px the same board fails — anti-aliasing eats thin marks, and a `=` sign
becomes a grey smudge.

The naive fix is a threshold per size. The actual fix is to stop having a size:

```python
TARGET_BOARD_PIXELS = 794     # everything is scaled to this before reading
MIN_BOARD_PIXELS = 500        # below this, upscale rather than trust it
```

The pipeline finds the board, rescales it to the calibrated size, and only then
reads it. When that fails — or succeeds but not uniquely — it retries with
progressively tighter centre crops and higher prescale factors:

```python
_PRESCALE_STEPS  = (1.0, 1.75, 2.5)
_CROP_FRACTIONS  = (1.0, 0.85, 0.72, 0.6, 0.5)
```

Crucially, **a success does not end the retry loop if the solution is not
unique.** That is the rule that turns "it worked" into "it is right".

---

## Layering: why `core` / `puzzles` / `automation` / `ui`

The layers exist because of what each one is allowed to know:

| Layer | Knows about | Does not know about |
|---|---|---|
| `core/` | pixels, grids, digits | which puzzle this is |
| `puzzles/` | puzzle rules, what the colours mean | the screen, the mouse, the GUI |
| `automation/` | screen coordinates, mouse, verification | how to solve anything |
| `ui/` | windows, buttons, language | image processing, solving |

The payoff is testability. `test_solvers.py` runs the whole solver layer with no
images at all. `test_automation.py` runs the whole click-planning layer with a
fake 10-pixel-per-cell grid and a dry-run driver, so it can assert exact click
counts without a mouse existing. Neither needs a screen.

It also means **exactly one file moves the mouse** (`input_driver.py`). Anything
that wants to click goes through it, so the abort check, the dry-run switch and
the speed multiplier all live in one place and cannot be bypassed.

### Why per-puzzle modules rather than a class hierarchy

Each puzzle module exposes the same few functions — `read_*`, `solve_*`, and a
description of how to fill it in — but the five puzzles have almost nothing in
common internally. Tango reads two icon types and edge marks. Queens does colour
clustering. Patches reads digits *and* shape hints. A base class would have been
five special cases wearing a trench coat. A flat registry of modules is honest
about that:

```python
PUZZLES = {"tango": tango, "queens": queens, ...}
```

---

## Recognition: the parts that were harder than expected

### Finding the grid

The obvious approach — count the grid lines — is wrong. Boards have faint outer
borders that are sometimes detected and sometimes not, so the line *count*
fluctuates between n-1 and n+1 for the same board. Patches boards were
consistently sized one short this way.

The fix is to use the **spacing** rather than the count. Line positions are
stable even when the outermost one is missed, so:

```
n = round(board_width / median(gaps between detected lines))
```

This is immune to missing the first or last line entirely, which is exactly the
failure that kept happening.

### The `=` and `×` marks are brown, not grey

Tango's edge marks were being erased by a saturation filter built on the
assumption that "marks are grey, cells are coloured". They are not grey — they
are a low-saturation brown, which the filter removed along with the background.
Switching the whole detection to the HSV **Value** channel fixed it. Saturation
was the wrong axis for this problem entirely.

### Moon crescents and black borders

Moons were detected by looking for a dark blob — which also caught the board's
own black border when sampling ran close to a cell edge. The fix was to sample
well inside the cell and take a *median* excluding saturated pixels, so a few
stray border pixels cannot move the answer.

### Queens crowns: the threshold that did not exist

The crown detector originally used a dark-pixel ratio over the whole cell, with
a threshold around 0.17. Measured on real boards, crowns gave 0.10–0.20 and
empty cells gave 0.10–0.20 as well — the grid lines were contributing most of
the signal, and there was no threshold that could separate them.

Insetting the sample region by 28 % of the cell removes the grid lines entirely,
and the two populations separate cleanly:

```python
ICON_INSET_RATIO = 0.28       # crowns 0.268-0.374, empty cells 0.000
```

The lesson generalised: when a threshold seems impossible to pick, the
measurement is usually including something it should not.

### Colour regions: why not k-means

Queens regions were first grouped with k-means. It worked, and then it did not —
the same board could split one region into two on different runs, because
k-means initialisation is random and two of the pastel colours were genuinely
close together.

Replaced with frequency-based grouping: collect every cell's median colour, sort
by how often each appears, and merge anything within a small fixed distance of
an already-established colour.

```python
SAME_COLOR_EPSILON = 10
```

Deterministic, and it never invents a region that is not on the board.

### Patches: the white gaps that looked like digits

Patches labels are stacked translucent shapes. The white gaps *between* those
shapes were being read as digit strokes — a real "4" came back as four separate
fragments, and a blank label as three. Both were reported as unreadable, which
aborted the whole solve.

Two changes fixed it: read digits only from the centre 62 % of the badge, and
discard components shorter than 42 % of the badge height.

```python
DIGIT_REGION_RATIO      = 0.62
DIGIT_MIN_HEIGHT_RATIO  = 0.42
```

There is a second lesson buried here. The first test fixture built for this bug
was made by filling in the whole badge — which quietly turned a *dashed* badge
into a *solid* one, and the test passed against a board that could not occur.
The fixture now only erases the centre digit. **A test written against an
impossible input proves nothing.**

### Digit reading without an OCR engine

The digits are from one app, at a handful of sizes, drawn in one font. That is
not an OCR problem, it is a lookup. Glyphs are normalised to 28×28 and matched
against templates captured from the app itself. No Tesseract dependency, no
model download, and it does not misread a `4` as a `A` — because `A` is not in
the table.

---

## Automation: the answer has to be actionable

Getting the right answer turned out to be about half the work. Delivering it
through a real mouse into a real web page introduced its own failures, every one
of which came from a real session.

### It kept clicking after the puzzle was finished

The worst one. After the board is filled, the site replaces it with a completion
screen. The verify-and-retry loop then re-read that screen, found no crowns
where crowns should be, concluded the fill had failed, and kept clicking.

The fix is that `verify()` reports **two different things**:

- *the board is wrong* → retry those cells
- *the board is no longer there* → stop, release the mouse, do not retry

Distinguishing "wrong" from "gone" is what makes the program let go. This is
covered by `test_stops_when_board_changes`, which paints over the board and
asserts that the retry plan comes back as `None`.

### It fought the user's own mouse

Originally a confirmation dialog appeared before the automation started. The
user clicked OK, and the automation — configured with zero delay — started
clicking while the mouse button was still down. The two inputs interleaved and
the board ended up scrambled.

Two changes: the confirmation dialog was removed entirely (the whole point is to
save seconds), and a short deliberate delay plus `wait_for_mouse_release()` was
added, so nothing happens until the physical mouse button is actually up.

### The page could not keep up

Zip is filled with one continuous drag. The page decides the path from which
cells the pointer crossed — so jumping cell centre to cell centre skips the
cells in between, and the game replies "you must follow the number order".

The driver now interpolates every drag so no step exceeds 12 pixels:

```python
DRAG_MAX_STEP_PX = 12
```

and the default speed multiplier was raised to 2.0 after watching a screen
recording of it outrunning the page.

There is a related constant for clicking the same cell twice:

```python
SAME_SPOT_CLICK_GAP = 0.15    # pause between same-cell clicks; see the constant's comment
```

### Patches: when "can the board still be located" stops being answerable

*(`speed-optimization` branch, not yet merged to `main`.)*

The mid-plan guard's structural check (above) has one puzzle it cannot serve
well: Patches. Its own drawn answer covers the board in solid colour, and
that colour erases the interior grid lines `detect_grid_size` depends on -
not intermittently, but for good, because filling only ever adds coverage.
A real 8x8 fill (2026-08-09) demonstrated exactly how bad this gets:
`detect_grid_size` failed 7 checks in a row on a board that had not moved at
all, confirmed against the screen recording - well past the tolerance a
2026-08-06 incident had already raised to absorb a smaller version of the
same problem.

The insight that broke the deadlock: the guard does not actually need to
*re-derive* the grid to know the board is still there. It already knows,
from the plan itself, exactly which cells it painted and which it did not.
So instead of asking "can I still find a grid", it asks a narrower question
it can actually answer: **does the board's outer border still exist, and
does the part we have not painted yet still look like it did when we
started?**

The border half is nearly free. `find_board_bbox` looks for the board's
*outer* contour, which our own fills never touch — they are drawn strictly
inside cells. Measured directly on the failing 8x8 frame and on every
heavily-filled fixture already in the test suite, the border locates
reliably in every case where the interior grid-line check does not.

The content half is where the first attempt went wrong, and it is worth
telling honestly. The first version scored how much of the reference
frame's un-painted structure (grid remnants, label digits — anything darker
than the background, outside our own saturated fills) still read dark in
the current frame, and used that score to make two decisions: a high score
meant "still ours, keep going"; a low score meant "not ours, abort now" —
faster than the existing tolerance counter. An independent adversarial
review, briefed only on the diff and asked to refute it, found two ways
this was actually worse than doing nothing:

- A uniform gray frame in a narrow brightness band scored a **perfect
  1.0** and disabled the guard permanently — the metric never required the
  *current* frame to have any contrast of its own, only that it was darker
  than the reference's background, which any flat enough gray satisfies at
  every pixel simultaneously.
- Replayed against the real 2026-08-06 incident's own fixture — the one
  `PATCHES_FAILURE_TOLERANCE=6` exists to cover — the immediate-abort
  verdict killed that *correct* fill on the very first check. That pair has
  a genuine ~1% scale drift between the two captures, small enough that a
  human would call it the same board, but enough to drag the raw score
  under the threshold.

Both findings point at the same design mistake: giving the new check the
power to make the guard *stricter* introduces exactly the kind of
confident-but-wrong judgement the whole project exists to avoid. The fix
was not a better number, it was a smaller contract. The check now can only
ever **affirm** ("the content still matches — reset the failure counter")
or **decline** ("could not confirm — fall through to the tolerance counting
that already existed, untouched"). It never aborts anything itself:

```python
if use_content_check and reference_content_matches(reference, image):
    consecutive_failures = 0     # affirmed - extend the plan's life
    return True
# declined, or the check is not enabled here: everything below is
# byte-for-byte the same code that ran before this feature existed.
consecutive_failures += 1
if consecutive_failures <= failure_tolerance:
    return True
...
```

Under that contract, every scenario is provably no worse than the
pre-change guard: the worst the new code can do is decline, which *is* the
old path. Affirmation itself still has to clear two independent, measured
gates — a structural-match floor (0.90, against a *naturally rendered*
worst-case impostor of 0.76) and a contrast-retention floor (0.85, because a
white scrim of opacity `a` compresses the masked content's contrast by
exactly `1 - a`, a relationship confirmed on real screen captures rather
than assumed) — so a uniform gray frame, a scrim, or a different Patches
board sharing the same grid pitch all decline rather than affirm. Re-review
after the rewrite found the contract held, with one honestly-documented
residual: a partial *dark*, desaturated occluder is, in principle,
indistinguishable from one of our own dark fills, because both are read the
same way. Bounded by the plan's own length, and disclosed in the code
rather than swept past.

The broader lesson generalises past this one guard: **a safety check earns
the right to say "stop" separately from the right to say "continue".**
Letting the same signal do both, on the reasoning that it was measured
carefully, is still trading a known, bounded blind spot for an unmeasured
one — and the only way that trade got caught here was by handing the design
to reviewers whose only job was to break it, before it ever touched the
puzzle a real user was still trying to finish.

### Waiting for a board that could never have been found

*(`speed-optimization` branch, not yet merged to `main`.)*

A 2026-08-10 session logged 68 seconds of continuous polling - 353 checks,
roughly one every 190ms, exactly on schedule - that never once detected a
board. A screen recording of the same region, played back afterwards,
showed the real Patches puzzle sitting there, untouched, for well over ten
of those seconds. Not a timing coincidence, not a slow poll: the polling
loop was working exactly as designed, checking exactly as often as
designed, against content that its own detector could never have accepted,
no matter how many more times it checked.

The habit that found this was choosing to trust neither the log's silence
nor the recording's picture on their own, and instead going one level lower
than either: saving the *exact bytes* the waiting loop's own capture path
produced (the panel's "Test region" button already existed for this, it
had just never been reached for while the loop was silently failing) and
feeding those, not a screen recording of the same area, into the same
detector by hand. The two were not interchangeable. The recording located
the board at native resolution without trouble; the app's own capture,
of what should have been the identical screen at the identical moment,
did not. `find_board_bbox`'s largest contour on the real capture was
7,980px² - the individual number badges, nothing more - against the
15%-of-frame area a board-sized contour needs. The board's own outer
border was too faint, in absolute pixels at native capture size, for a
fixed-radius Canny-and-dilate pass to ever close it into one shape.

The part worth sitting with is that this exact failure mode already had a
name, written down, in a completely different function. `_locate_board` -
the locator `solve_image()` itself uses once it has committed to actually
solving - carries a docstring that opens with "pre-scaling if its faint
border is missed at 1x," backed by a three-step prescale ladder built for
precisely this. The *cheap* pre-check that decides when to even start
solving was written separately, later, for a different reason (reaction
time, not correctness - see "The page could not keep up" for why it exists
at all), and it re-derived the same "is a board here" question from
scratch rather than reusing the answer the slower path had already worked
out. It re-derived it *incompletely*: one scale, not three. Nothing in
that gap was ever exercised by a fixture, because every fixture collected
up to that point happened to have a border that survives at 1x - Patches
included, most of the time. The one that did not simply never got tested,
because nobody had gone looking for one until a real session produced it
and a real capture, not a proxy for one, was saved and inspected.

The fix adds back exactly one of `_locate_board`'s three steps - a retry
at 1.75x when the native-scale check finds nothing - measured at 150.9ms
worst case against 30.0ms before, still comfortably inside the poll
budget, and paid only while genuinely nothing is on screen yet. The
broader lesson is less about scale factors and more about where trust
should sit: a screen recording of "the same" region is a recording of what
a human would see there, not of what the program's own capture path
actually receives, and the two can quietly diverge. When a detector's
behaviour cannot be explained by its own code, the next step is not a
recording of the screen - it is whatever the detector itself was actually
given.

### Resuming a half-filled board

If the user has already placed some crowns, or the automation was interrupted,
the plan must account for what is already on screen. Queens cells cycle
empty → X → crown, so a cell showing an X needs one more click, not two, and a
crown in the wrong place has to be cleared first. `players.py` reads the current
state and computes the click count per cell rather than assuming a blank board.

---

## Internationalisation

Every user-visible string goes through a flat dictionary keyed by a short name,
with `en` and `zh` entries, and a `Translator` object that the UI holds:

```python
t = Translator("zh")
t("btn_solve")        # "自動解答"
```

Flat rather than nested, because nesting buys structure nobody needed and makes
missing keys harder to spot. Language is persisted in settings, so it survives a
restart.

Comments in the source are bilingual for the same reason the UI is: this is
published for other people to read, and the English half is what makes the
project searchable and reusable while the Chinese half is what makes it
maintainable by its author.

---

## What was deliberately not done

- **No AI or vision model.** Answering "can a program understand this image" by
  asking a model would be answering the wrong question.
- **No DOM automation.** Reading the page's HTML would be far easier and far
  more robust than reading pixels. It would also make the interesting part
  disappear, and would depend on LinkedIn's markup rather than on what is
  actually on screen.
- **No region-selection UI.** An early version let the user drag a rectangle
  around the board. It created a second Tk root window and took the whole app
  down with it. It was replaced with automatic board detection, which is better
  anyway — the user should not have to tell the program where a board is when
  the program can see it.
- **No configuration file for thresholds.** Every threshold in this project was
  derived from measurements on real boards and is documented next to its
  measured values. Exposing them as settings would invite tuning by guesswork.

---

## Related documents

- [ARCHITECTURE.md](ARCHITECTURE.md) — module by module
- [USAGE.md](USAGE.md) — step by step
- [ROADMAP.md](ROADMAP.md) — what is next
