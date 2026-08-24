# Project evolution

A thematic tour of what this project has become, from the first single-app
release (1.0.0) through the `speed-optimization` branch merge. Unlike
[CHANGELOG.md](../CHANGELOG.md), which is chronological and version-numbered,
this groups every real change by *what kind of problem it solved* - useful
for getting a sense of the project's shape without reading a year of dated
entries. Technical detail, exact numbers, and the story behind each fix live
in CHANGELOG.md; this page is the map, not the territory.

---

## Recognition accuracy and template calibration

Getting a digit, a colour, or a board size right the first time, on a real
screen, not a synthetic test case.

- **Digit templates 0 and 7 stopped depending on the machine's fonts.**
  They used to be rendered from `C:/Windows/Fonts` at import time - absent
  entirely on a machine without those fonts, with matching then picking the
  nearest *wrong* digit at high confidence. Baked into the source as bytes
  instead, so coverage never depends on what is installed.
- **Digit classification gained a margin check.** Score alone cannot
  separate right from wrong - a misread scored higher than many correct
  matches. A glyph is now only accepted when the runner-up is a measured
  distance behind; otherwise it is reported unreadable rather than guessed.
- **Patches' margin threshold was physically impossible to pass for its
  hardest digit pair**, then replaced with a relative rule measured over
  13,000 real font samples that blocks zero readings the old absolute gate
  used to catch by accident.
- **Zip's dot detection and digit-hole handling were both fixed** after real
  discs were measured losing wide-glyph numbers ("10" vs "1") and a filled-in
  "0" scoring one point away from misreading as "9".
- **Sudoku's digit candidates are narrowed to what the board can actually
  hold** (a 6x6 only has 1-6), which measurably widens every glyph's margin
  for free - a technique later re-evaluated for Zip and Patches too.
- **Two board-type misdetections were root-caused and fixed from real
  session logs, not guessed at**: a Sudoku board whose colour ratio sat just
  under the Tango-branch cutoff, and a Zip board whose path colour did the
  same - each one costing 5-9 seconds per occurrence while the wrong ladder
  of solver attempts ran to exhaustion before falling back to the right one.
- **A growing, real-world archive of digit material now builds itself.**
  Sudoku's post-fill verify already re-reads every cell it typed, so an
  unreadable one (ground truth known - it is exactly the digit our own
  solver chose) is saved as a calibration candidate. Later extended so every
  successful Sudoku/Zip/Patches solve saves a *pristine, pre-fill* capture
  plus its computed-answer overlay as a matched pair - material for a future
  per-puzzle split of the currently-shared recognition thresholds, reviewed
  by a human before anything is fed back into the templates.

## Automation safety mechanisms

The parts that watch the board while the mouse is moving, and refuse to act
on one that changed underneath them.

- **Every puzzle got a uniqueness or sanity guard on its solver output** -
  Tango, Sudoku and Patches reject a second valid solution; Queens rejects a
  colour-region read that does not form exactly *n* connected regions;
  Patches rejects fewer than 3 labels. A wrong recognition now fails loudly
  instead of confidently clicking a plausible-looking wrong answer.
- **A mid-plan board guard watches the screen between actions.** Once a fill
  plan starts, nothing used to look at the screen again until it finished -
  measured blind windows up to 21 seconds - so a completion screen swapped
  in partway through absorbed every remaining click. The guard asks one
  structural question between actions instead, throttled to stay cheap.
- **The guard survived two rounds of hardening against its own false
  positives.** Patches' own drawn fill colour defeats the guard's structural
  grid-line check as soon as enough of the board is covered; a masking
  fallback and, later, a content-comparison check (verified only *affirms*
  or *declines*, never aborts on its own) closed that gap without
  reintroducing the false stops the guard exists to prevent. The final
  design was reshaped by an independent adversarial review that found real
  counter-examples (a uniform grey frame, a same-size different board) in
  the first version before it shipped.
- **The guard and post-fill verify both learned that a MOVED board is not
  an unchanged one** - both used to compare cells by grid index only, which
  is blind to translation, so a board shifted 80px down still verified as
  fine.
- **The CLI's fully-automated path shares the exact same guard as the GUI**,
  closing a gap where `--go` could run a whole plan with no protection at
  all.
- **A guard-triggered abort could silently end an entire continuous
  session** instead of moving on to the next puzzle, because of a stop-flag
  latch shared between the aborted round and the very next wait step. Fixed
  and confirmed with a test that was run against the unfixed code first, to
  prove it reproduces the real incident before proving the fix resolves it.

## Solve-speed optimization

Turning "eventually correct" into "correct in under a second," measured
before and after every change, never by skipping a safety check.

- **Working images are capped on their long side** - upscaling cannot add
  information a recognizer can use, so paying to process pixels beyond
  that only slows every downstream step down.
- **The board guard throttles itself**, reusing its last answer within a
  short window instead of re-evaluating on every single action - unthrottled,
  one five-puzzle sitting cost over a minute of pure checking overhead.
- **Continuous mode replaced pressing "solve" five times a day with pressing
  it once.** The loop now waits for a puzzle, solves, fills, waits for the
  board to leave, and repeats - closing a real gap where forgetting to press
  the button again before the next puzzle cost more time than the feature
  saves.
- **A "wait for the button before the puzzle exists" start flow**, several
  new speed tiers, and a pass that cut every measured dead-wait node found
  in real session logs (including a Patches guard tolerance raised only
  after a real false-abort measurement) each shaved real, logged seconds off
  a daily five-puzzle sitting - and one tier that turned out too aggressive
  for real play was deliberately pulled back rather than kept for the sake
  of the number.
- **Zip and Patches deliberately skip post-fill verification**, since
  neither can be read back cell-by-cell (their answer is a drawn path or a
  set of coloured rectangles) - verifying anyway would only pay a redraw-wait
  and re-capture cost for a check that cannot say anything useful.

## User experience and workflow

The parts a person watching the screen actually notices.

- **The mouse parks off the board before every capture**, not just before
  clicking. LinkedIn's own `:hover` styling darkens whatever cell sits under
  the cursor, which a colour-based Queens read cannot tell apart from a real
  region boundary - root-caused from a real session where the cursor
  inherited its position from the previous puzzle's last click.
- **The GUI window gets out of its own capture region's way automatically**,
  and is restored the instant it needs the user's attention (a repeated
  failure, a resolution mismatch) rather than staying hidden through
  continuous mode's normal minimised state.
- **Bilingual interface and documentation from the first release** -
  English and 中文, remembered between sessions, with every source comment
  written in both languages as a project-wide rule, not an afterthought.
- **A saved capture region now warns, without blocking, when the screen it
  was calibrated for has changed** - switching monitors, resolution, or
  Windows display scaling used to fail with nothing more specific than "board
  not found."

## Diagnostics and debugging tools

Because the real target puzzles reset once every 24 hours, there is no "run
it again with more logging" - a session has to leave enough evidence to
answer questions about it after the fact, on the first try.

- **A timestamped, append-only action log** records every click, every
  guard check (including near-misses that used to be invisible), and every
  recognition attempt - shown on screen from the moment a session starts, so
  a screen recording captures its path from the first frame.
- **A solve that exhausts every retry saves the exact capture it failed
  on**, and the guard saves the exact frame that triggered any stop - the
  same idea applied to two different failure shapes, both closing the same
  gap: a failure that cannot be reproduced afterwards because nothing kept
  the real bytes the recognizer actually saw.
- **Two capture folders serve two different audiences on purpose.** `img/`
  is what a person chose to keep and would browse when reporting a bug;
  `calibration_candidates/` is written automatically, without being asked,
  specifically so a human reviews it later before anything reaches the
  calibration tool - mixing the two would make an automatic write look like
  something the user saved on purpose.
- **An optional environment-variable override lets several local
  checkouts of this project share one training-data folder** instead of
  each accumulating its own separate logs and captures - unset (the default
  for every published-exe user), behaviour is completely unchanged.

## Reliability fixes

Real incidents, each root-caused from a real capture, log, or recording
rather than reasoned about in the abstract.

- **A stale result could save the wrong answer onto a new screenshot** -
  picking a new image without solving first left the previous puzzle's
  result in place, so Save silently wrote the old answer under the new
  file's name.
- **Closing the window mid-fill could leave the mouse button physically
  held down**, because the worker thread was killed before its own
  `mouseUp` cleanup could run.
- **The GUI could not start without an optional screen-capture package**,
  even in image mode, which never touches the screen at all.
- **A malformed saved setting used to crash the GUI at startup** with no
  way back in except hand-editing the settings file.
- **A solve had no time budget, and Stop could not interrupt one in
  progress** - a large screen grab could run half a minute with no
  check-in point anywhere in that time.
- **A board too faint at native resolution to detect was fixed by retrying
  at a second scale**, root-caused from a session that polled for over a
  minute against a board confirmed genuinely on screen the whole time by a
  separately-saved raw capture (a screen recording of the same region was
  not the same bytes, and looked fine - the exact reason this project treats
  a recording and a live capture as different evidence).

---

## Related documents

- [CHANGELOG.md](../CHANGELOG.md) — the same history, chronological and
  version-numbered, with full technical detail
- [DESIGN.md](DESIGN.md) — why the project is shaped the way it is
- [ARCHITECTURE.md](ARCHITECTURE.md) — module by module
- [ROADMAP.md](ROADMAP.md) — what is still open
