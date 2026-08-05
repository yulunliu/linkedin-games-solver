# Changelog

Notable changes. Format loosely follows [Keep a Changelog](https://keepachangelog.com/).
重要變更紀錄。格式大致依照 Keep a Changelog。

## [1.2.0] — 2026-08-04

**Upgrade from 1.1.0.** A user's own screen recordings, played back frame by
frame through the actual detection code, showed the mid-plan board guard
added in 1.1.0 stopping Patches fills that were still correct - the guard
built to catch a real bug was itself producing a different kind of false
stop. Every claim below was checked by feeding real captures (from those
recordings, and from the guard's own new diagnostic dump) straight into the
functions that make the decision, not by reasoning about what should happen.
**建議從 1.1.0 升級。** 使用者自己錄的螢幕畫面，逐格切開直接餵給真正的偵測
程式碼後，顯示 1.1.0 新增的填答中途盤面保護，會讓其實還沒出錯的拼塊填答
中止——這個為了抓真的 bug 而做的保護，自己也會產生另一種誤判。以下每一項
都是把真實擷取（來自那些錄影，以及保護自己新增的診斷存檔）直接丟進做判斷
的函式驗證過的，不是用推論的。

### Fixed — the mid-plan board guard 填答中途的盤面保護

- **Patches fills stopped early because the guard's own structural check
  cannot survive the puzzle's own drawn answer.** `detect_grid_size` reads
  grid lines as thin dark columns/rows against a light background; a drawn
  patch's pastel fill reads as "mostly dark" over a wide span instead,
  breaking that assumption from the moment the first patch is drawn.
  Reproduced directly: `build_grid` raised `grid size not detected` on a real
  mid-drag capture extracted from a user's recording. Added a masking
  fallback in `board_watch.locate_board` - pixels above HSV saturation 50 (our
  own fills measure 76-94 over a wide area; the pristine background is under
  3 for 90% of pixels) are replaced with white before a second locate attempt.
  Recovers detection from roughly 1/6 through 2/3 of a typical fill, verified
  against two real fixtures pulled from that recording.
  **拼塊填答會提早停手，因為保護自己的結構性檢查撐不過謎題自己畫出來的答案。**
  `detect_grid_size`是把格線讀成淺色背景上細細的深色欄/列；貼塊畫上去的
  粉彩填色，卻會在一大片範圍內被讀成「大部分是暗的」，從畫上第一塊貼塊
  開始就打破這個假設。已直接重現：對一張從使用者錄影切出來的真實拖曳中
  截圖，`build_grid` 拋出「無法自動偵測棋盤格數」。在 `board_watch.locate_board`
  加了一道遮色備援——HSV 飽和度超過 50 的像素（我們自己的填色量到
  76~94，涵蓋很大一片；乾淨背景 90% 的像素都在 3 以下）先換成白色再試一次。
  能救回大約從填答 1/6 到 2/3 這段範圍的誤判，用那段錄影切出的兩張真實
  測試圖驗證過。

- **The masking fix does not reach the very end of a Patches fill, and that
  gap is now a deliberate, bounded trade instead of an unexplained failure.**
  Past roughly 2/3 filled, a drawn patch's own internal grid line can share
  masking's saturation threshold with its surrounding fill, so the fix cannot
  tell them apart. Rather than guess at a cleverer detector - one earlier
  attempt this same day (verify only the outer border, skip re-deriving grid
  size) was tried, measured, and reverted, because it also made random noise
  and a different puzzle at the same size read as "still our board", which is
  worse than the bug it fixed - `PatchesPlayer` now runs its LAST TWO
  rectangles with the mid-plan check turned off. Confirmed on a real capture:
  once two drawn patches touched the board's own edges, even the cheaper
  outer-border check (`find_board_bbox`) picked a patch's own border instead
  of the board's.
  **這個遮色修正救不到拼塊填答的最後一段，這個缺口現在是刻意、範圍有限的
  取捨，不再是沒解釋的失敗。** 填到大約三分之二之後，貼塊自己畫出來的內部
  格線，飽和度可能跟周圍填色太接近，遮色沒辦法把兩者分開。與其硬猜一個
  更聰明的偵測法——同一天真的試過一種（只驗外框、不重新推算格數），
  量測後發現它會讓純雜訊、換成同尺寸的另一款謎題都被判定成「還是我們的
  棋盤」，比它想修的 bug 更糟，已經復原——現在改成讓 `PatchesPlayer` 對
  **最後兩塊矩形**關閉中途盤面檢查。已用真實擷取確認：兩塊貼塊同時碰到
  棋盤自己的邊緣時，連比較便宜的外框檢查（`find_board_bbox`）都會挑到
  某一塊貼塊自己的邊框，不是棋盤的。

### Added 新增

- **The guard now saves the exact frame that triggered a stop**, to
  `img/boardwatch_stop_<timestamp>.png`, logged with its path. Before this,
  a real board replacement and a false structural failure produced the
  identical log line - there was no way to tell them apart after the fact.
  This is what made the fixes above possible to verify against a real
  production capture rather than a reconstructed one.
  **保護現在會存下觸發中止的那一張畫面**，存到
  `img/boardwatch_stop_<時間戳>.png`，記錄欄印出路徑。在這之前，真正的
  盤面被換掉，跟結構性檢查誤判，記錄裡印出的是完全一樣的一行字——事後
  沒有辦法分辨。上面這兩項修正能對著真正在跑的 exe 產生的擷取驗證，
  而不是重建出來的畫面，靠的就是這個。

### Known limitation, unchanged from before 已知限制，沿用之前的說明

Filling the last two Patches rectangles while the board has genuinely been
replaced (window covered, tab switched) would go unnoticed for those two
drags only - a small, bounded reopening of the exact risk 1.1.0's guard was
built to close, accepted as a deliberate trade rather than left undocumented.
拼塊填最後兩塊矩形時，如果棋盤真的被換掉（視窗被蓋住、切走分頁），
只有這兩筆拖曳不會被發現——這是 1.1.0 那個保護原本要防的風險，
被重新打開了一小段、範圍有限，是刻意接受的取捨，不是沒說明的缺口。

## [1.1.0] — 2026-08-03

**Upgrade from 1.0.0.** Two of the five puzzles could not be solved on a
browser-sized board, and the automation could put the mouse and the answer in
places neither was meant to go. Every number below was produced by running code
against real captures, not estimated.
**建議從 1.0.0 升級。** 五款謎題中有兩款在瀏覽器尺寸的棋盤上解不出來，
而自動化可能把滑鼠與答案送到不該去的地方。下面每一個數字都是實際跑程式量出來的，
不是估計值。

### Fixed — recognition 辨識修正

- **Patches could not read its own labels.** `MIN_MARGIN = 0.04` demanded a gap
  between the best and second-best digit that is **physically impossible** for 6
  and 8: the closest cross-digit template pair is 6 vs 8 at similarity 0.9705,
  so a glyph matching an 8 perfectly beats 6 by at most 0.0295 - the gate asked
  for 136% of the entire available budget. A label scoring 0.9931 was thrown
  away. Replaced with a relative rule measured over 325 fonts x 4 sizes =
  13,000 samples: `0.90 / max(0.020, 0.80 * (1 - score))` admits **zero** wrong
  readings that the old gate blocked.
  **Patches 讀不出自己的標籤。** `MIN_MARGIN = 0.04` 要求的第一名與第二名差距，
  對 6 和 8 而言**物理上不可能**：最接近的跨數字範本組合是 6 對 8，
  相似度 0.9705，所以完全吻合 8 的字形最多只能贏 6 0.0295 ——
  那個門檻要求的是全部可用預算的 136%。一個 0.9931 分的標籤就這樣被丟掉。
  改用相對規則，用 325 種字型 × 4 種尺寸 = 13,000 個樣本量測，
  新規則**不會**放行任何舊門檻擋得住的錯誤。

- **Zip lost dots whose number had a wide glyph.** `_looks_like_dot` measured
  the disc's raw dark area, which varies with how much white ink the printed
  number uses - measured 0.5972 for "10" against 0.7407 for "1". The 0.60 floor
  sat inside that spread and silently discarded the "10" disc. Now measured as
  solidity with the number filled back in, which a circle satisfies at pi/4 =
  0.785 regardless of what is written on it: 0.7785-0.8002 across 12 discs.
  **Zip 會漏掉數字比較寬的圓點。** `_looks_like_dot` 量的是圓盤的原始深色面積，
  而那個值隨數字佔掉多少白色而變 —— 實測「10」是 0.5972、「1」是 0.7407。
  0.60 的下限正好落在中間，默默丟掉「10」那顆。改成把數字填回去後量實心度，
  圓形不管上面寫什麼都是 pi/4 = 0.785：12 個圓盤實測 0.7785~0.8002。

- **Zip read digits with their own holes filled in.** A counter (0 4 6 8 9) is a
  separate dark component the flood fill cannot reach, so `_enclosed_holes`
  handed back solid blobs. The "0" of "10" had a **wrong** top-1 - it read as 9
  with a margin of 0.0001, so only the margin gate stood between it and a silent
  misread. After the fix all 12 discs have the correct top-1 digit.
  **Zip 讀到的數字內孔被填實了。** 內孔（0 4 6 8 9）是另一個深色元件，
  灌水碰不到，所以 `_enclosed_holes` 交回的是實心團塊。「10」的那個「0」
  第一名是**錯的** —— 讀成 9、差距 0.0001，只剩差距檢查擋在它與一次無聲誤讀之間。

- **Type misdetection killed the whole run.** `detect_type` reasons about colour
  over the board region and falls back to the WHOLE image when it cannot locate
  the board, so a small board in a large capture has its colour diluted:
  measured 0.00186 against a 0.006 threshold on a 1920x1080 capture with a 390px
  Tango board, filed as Sudoku, and every attempt afterwards failed with "board
  not found". The pipeline now retries the other types after the detected one
  has failed the full ladder.
  **類型判斷錯了就整條路死掉。** 定位不到棋盤時 `detect_type` 會退回用整張圖算顏色，
  小棋盤在大擷取範圍裡顏色被稀釋：1920x1080、390px 的 Tango 實測 0.00186
  對上門檻 0.006，被歸成 Sudoku，之後每次嘗試都失敗在「找不到棋盤」。

### Added — recognition 辨識新增

- **Zip deduces numbers it cannot read.** Its dots are numbered 1..k with no
  gaps, so the puzzle itself often determines an unreadable disc: the digit
  count narrows the candidates, and any numbering that yields no valid path is
  discarded. Accepted **only** when exactly one distinct path survives - two is
  a guess, and a guess would put a wrong route under the real mouse.
  **Zip 會推論讀不出來的號碼。** 圓點編號 1..k 連續無缺口，所以謎題自己往往就能
  決定答案：位數縮小候選，走不出路徑的編號被淘汰。
  **只有**剩下恰好一條相異路徑時才採用 —— 剩兩條就是猜測。

- **Sudoku only considers digits the board can contain.** A 6x6 holds 1..6, so
  excluding 0 and 7-9 raises 6's template ceiling from 0.0295 to 0.0591 and 3's
  from 0.0785 to 0.1163; per-glyph margin improves +0.0148 on average, up to
  +0.0599. Zip and Patches use all ten digits and gain nothing, which the code
  says rather than implying otherwise.
  **Sudoku 只考慮盤面可能出現的數字。** 6x6 只有 1..6，排除 0 與 7-9 之後，
  6 的範本天花板從 0.0295 升到 0.0591、3 從 0.0785 升到 0.1163。
  Zip 與 Patches 用到全部十個數字，什麼都買不到，程式裡就這樣寫。

### Fixed — the mouse 滑鼠相關修正

- **The fill plan never looked at the screen again once it started.** Measured
  blind windows: Queens 8.96s, Tango 21.15s, Patches 12.07s, plus 2.97s on the
  retry path against an already-stale snapshot. When the site swapped in its
  completion screen partway through, every remaining click landed on it. The new
  `automation/board_watch.py` asks one structural question between actions - can
  this board still be located, at our size - and is hooked into the one function
  every action already calls. 0 false aborts across 17 real board states; 6 of 8
  replacement scenarios detected.
  **填答計畫一旦開始就不再看畫面。** 實測盲點：Queens 8.96 秒、Tango 21.15 秒、
  Patches 12.07 秒，補點路徑再對過期快照盲點 2.97 秒。網站中途換上完成畫面時，
  剩下的每一次點擊都落在它上面。

- **Queens had no uniqueness guard - the only puzzle without one.** A misread
  colour region that still yields n contiguous regions passed every check;
  `verify.py` accepts 85% region agreement so a 1-in-81 misread is 1.2% and
  passes, and the verifier then only asks whether the crowns it chose are
  present. The wrong layout was clicked and reported "9/9 correct".
  **Queens 完全沒有唯一性守門 —— 唯一沒有的謎題。** 一個仍然產生 n 塊連通色塊的
  誤讀會通過每一道檢查，錯誤佈局被點下去還回報「9/9 正確」。

- **Patches called `solve_tiling`, not `solve_tiling_unique`.** The unique
  version existed but was only reached on the unreadable-label rescue branch, so
  the success path returned whichever tiling CP-SAT found first. Measured on
  `live_patches.png`: blanking any one of the 7 numbered labels produced a
  different tiling returned `ok=True`, 7 times out of 7. Not conditional on
  blank labels - six "6" labels down a 6x6 diagonal has zero blanks, sums to
  exactly n*n, passes both guards, and has four legal tilings.
  **Patches 呼叫的是 `solve_tiling` 而不是 `solve_tiling_unique`。**
  唯一性版本存在，卻只有「讀不出來」的救援分支會走到。

- **The guard was cutting drags short.** It was asked inside the drag
  interpolation loop, contradicting that function's own comment. A drag is
  committed by mouseUp wherever the pointer is, so aborting partway does not
  cancel it - it sends a SHORTER drag. Measured: a Patches rectangle intended as
  1x4 was released after 12 steps and the page received 1x2. The safety
  mechanism was placing wrong pieces on the board.
  **保護會把拖曳切短。** 它被放在拖曳插值迴圈裡詢問，違反那個函式自己的註解。
  拖曳是靠 mouseUp 在指標當下位置送出的，中途中止不是取消而是「送出較短的拖曳」。

- **The working-size cap desynced the coordinates.** `_scaled` clamped the scale
  factor privately while the grid was mapped back with the unclamped one. A
  500px board on an 870x1882 canvas reported `(162,601,436,437)` against a true
  `(185,691,500,500)` - **1.6 cells out, with `ok=True`** - and those are the
  coordinates the mouse uses. Now 1px / 0.02 cells across four geometries.
  **工作尺寸上限讓座標換算失準。** 回報位置差 1.6 格而且 `ok=True`，
  而那正是滑鼠會用的座標。現在四種幾何下誤差 1 像素 / 0.02 格。

- **Zip silently produced a wrong route.** The consecutive-number test passes on
  any PREFIX, so twelve discs of which only 1..8 were readable looked exactly
  like an eight-dot puzzle; the solver returned a full path visiting the unread
  dots in the wrong order, dragged with the real mouse and reported as success.
  Reproduced 3 of 3 runs at 0.70x.
  **Zip 會安靜地產生錯誤路線。** 連續性檢查對任何「前綴」都通過，
  12 個圓盤只讀出 1..8 就跟一題 8 點的謎題一模一樣。

### Changed 調整

- Dry run now takes the same abort checks as a live run. It returned before both
  the per-click and the drag loops, so any test of where a plan stopped was
  measuring a code path the user never runs (2-click cell: 1 check versus 3).
  預演現在與實際執行走過同樣多的中止檢查。
- The board guard reuses its last answer within 0.25s. Unthrottled it made
  821 evaluations for one sitting of five puzzles at 110-160ms each - 73-104s of
  pure checking, and it held the physical left button down for 39.2s on Zip
  against 8.1s unguarded.
  盤面保護在 0.25 秒內沿用上一次的答案。不節流的話一輪五款要評估 821 次。
- Working images are capped at 2600px on the long side. Upscaling cannot add
  information, so a 1920x1080 capture taken to the 2.5x prescale became
  4800x2700: the fixture sweep dropped from 138.9s to 54.8s total, and the sizes
  actually captured solve in 0.21-0.40s each.
  工作影像長邊上限 2600px。放大不會增加資訊。
- The save dialog opens in the project's `img/` folder instead of inheriting
  whatever folder Windows last used - which was a previous project's samples
  directory.
  存圖對話框改為開在專案的 `img/`，不再沿用 Windows「上次用過的資料夾」。
- Python 3.9 support is now verified rather than merely declared. `input_driver`
  used `str | None` without `from __future__ import annotations`, which raises
  on import under 3.9 - it shipped in 1.0.0 and only CI caught it.
  Python 3.9 支援現在是「被驗證」而不只是「被宣告」。

### Tests 測試

Four new suites - `test_compat.py`, `test_board_guard.py`, `test_zip_dots.py`,
plus additions to the existing three. Every one was confirmed to FAIL against
the code before its fix; a test that passes either way proves nothing.
四個新測試檔，加上對既有三個的補充。每一個都確認過「在修正前會失敗」——
一個修不修都會過的測試什麼也證明不了。

### Known limitations 已知限制

Found by a systematic audit of extreme inputs, abnormal operation, hostile
environments and concurrency. **Not yet fixed** - listed so nobody has to
rediscover them. Detail in [docs/ROADMAP.md](docs/ROADMAP.md).
這些是對極端輸入、異常操作、惡劣環境與並行狀況做系統性稽核找到的。
**尚未修正**，列在這裡讓人不必重新發現一次。

- `self.result` is not cleared when the image behind it is replaced, so Save can
  write the previous puzzle's answer onto a new screenshot.
- A board that MOVES (page scroll, window resize) passes both the guard and
  `verify()`, and every remaining click lands one cell off.
- `ui/cli.py --go` has no board guard at all - the GUI path has it, the CLI does
  not.
- Closing the window mid-fill kills the worker before `mouseUp`.
- The GUI cannot start without `mss` even in image mode, and a wrong-typed
  `region` in the settings file stops it starting at all.
- There is no wall-clock budget, and Stop cannot interrupt a solve in progress.

## [1.0.0] — 2026-08-02

First release as a single project. Previously two separate codebases: an
image-mode solver and a browser-automation player.
第一次以單一專案發布。先前是兩套獨立的程式：圖片模式求解器，與瀏覽器自動填答。

### Added 新增

- **Both modes in one app.** A radio button switches between playing on screen
  and solving an image file. Image mode reuses the whole pipeline unchanged and
  never touches the mouse.
  **兩種模式合在同一個程式。** 用選項在「螢幕自動填答」與「解圖片檔」之間切換。
  圖片模式原封不動重用整條流程，而且完全不碰滑鼠。
- **English / 中文 interface**, remembered between sessions.
  **中英文介面切換**，設定會被保存。
- **`tools/calibrate_digits.py`** — regenerate the digit templates from your own
  screenshots. Refuses to write a set missing any digit 0-9.
  從你自己的截圖重新產生數字範本。缺任何一個 0-9 就拒絕寫出。
- **Bilingual documentation** — README plus architecture, design rationale,
  usage and roadmap, in English and 中文.
  **雙語文件** —— README，加上架構、設計理念、操作說明、未來計畫，中英各一份。
- **Four test suites** covering solver logic, digit recognition, recognition
  against real screenshots, and click planning. All offline; none moves the mouse.
  **四組測試**，涵蓋求解邏輯、數字辨識、真實截圖辨識、點擊計畫。
  全部離線，沒有任何一個會動滑鼠。

### Fixed 修正

- **Digits 0 and 7 had no template.** They were rendered from `C:/Windows/Fonts`
  at import time, so on a machine without those fonts they were simply absent —
  and matching then picked the nearest wrong digit with high confidence: a "0"
  scored 0.89 as a "6", a "7" scored 0.76 as a "2". Both are now baked into the
  source as bytes, so coverage never depends on the machine.
  **數字 0 與 7 沒有範本。** 它們是在 import 時從 `C:/Windows/Fonts` 算繪的，
  所以在沒有那些字型的機器上就直接不存在 —— 比對於是以高信心挑最接近的錯誤數字：
  「0」以 0.89 被判成「6」、「7」以 0.76 被判成「2」。
  現在兩者都以位元組烘焙在原始碼裡，涵蓋範圍不再因機器而異。
- **Digit matching had no margin check.** Score alone does not separate right
  from wrong — a "6" misread as a "5" scored 0.944, higher than many correct
  matches. Classification now requires the runner-up to be at least `MIN_MARGIN`
  behind, and reports the glyph as unreadable otherwise. Measured across ten
  fonts, this removed every silent misread.
  **數字比對沒有差距檢查。** 光看分數分不出對錯 —— 一個把「6」判成「5」的錯誤
  拿到 0.944 分，比很多正確比對還高。現在分類要求第二名至少落後 `MIN_MARGIN`，
  否則就回報成讀不出來。用十種字型實測，這消掉了所有默默讀錯的情形。
- **`PatchLabel.glyphs` was never populated** — a dead field left over from an
  earlier design. It now holds the normalised bitmaps, which is what the
  calibration tool harvests.
  **`PatchLabel.glyphs` 從來沒有被填值** —— 是舊設計留下的死欄位。
  現在它會存放正規化後的點陣圖，也就是校準工具要取用的東西。

### Carried over from the two original projects 從原本兩個專案帶過來的修正

These were already fixed before this release; they are listed because the
rationale is now documented in [docs/DESIGN.md](docs/DESIGN.md).
這些在本次發布前就已經修好；列在這裡是因為理由現在記錄在設計文件裡。

- Uniqueness checks on Tango, Sudoku and Patches — a second solution means
  recognition missed a constraint.
  Tango、Sudoku、Patches 的唯一性檢查 —— 找得到第二組解就代表辨識漏掉了條件。
- Queens region validity (exactly *n* contiguous colour regions) and Patches
  label count (≥3), after a pastel Queens board was misfiled as Patches and
  "solved" as one giant rectangle.
  Queens 的色塊合理性（剛好 *n* 塊且連通）與 Patches 的標籤數量（≥3），
  是在一個淡色系 Queens 盤面被誤判成 Patches、並被「解」成一塊大矩形之後加的。
- Board size from line **spacing** rather than line count, because a faint outer
  border is detected inconsistently.
  棋盤格數改用格線**間距**推算而不是數量，因為很淡的外框時有時無。
- Frequency-based colour grouping instead of k-means, which split regions
  differently between runs.
  用出現頻率分群顏色取代 k-means —— 後者在不同次執行會把色塊切得不一樣。
- Drag interpolation (`DRAG_MAX_STEP_PX = 12`) so the page sees every cell the
  pointer crosses; without it Zip replied "you must follow the number order".
  拖曳插值（`DRAG_MAX_STEP_PX = 12`），讓網頁看到指標經過的每一格；
  少了它 Zip 會回「您必須按照數字的順序」。
- Stop on board change: after the site shows its completion screen the program
  releases the mouse instead of clicking at a board that is no longer there.
  盤面改變就停止：網站顯示完成畫面之後，程式會釋放滑鼠，
  而不是繼續對著已經不存在的棋盤點下去。

### Known limitations 已知限制

Not defects to be fixed before release, but things you should know. Details in
[docs/ROADMAP.md](docs/ROADMAP.md).
這些不是「發布前必須修掉的缺陷」，但你應該知道。詳情見未來計畫文件。

- **Verify-and-retry covers Tango, Queens and Sudoku only.** Zip and Patches are
  filled by dragging and their result is not read back, so a drag the page did
  not follow is not detected or retried.
  **檢查補點只涵蓋 Tango、Queens、Sudoku。** Zip 與 Patches 是用拖曳填的，
  結果不會被讀回來，所以網頁沒跟上的拖曳不會被偵測到、也不會補。
- **Solver and recognition error messages are fixed bilingual strings**, not
  translated through `i18n.py`, so they ignore the language setting.
  **求解與辨識的錯誤訊息是固定的中英文串接字串**，沒有走 `i18n.py`，
  因此不受語言設定影響。
- **No test fixture contains a 0 or a 7.** Those two templates are font-derived
  and unverified against a real board.
  **沒有任何測試素材含有 0 或 7。** 這兩個範本來自字型，尚未用真實盤面驗證過。
- Screen mode is Windows-only and assumes the board is on the primary monitor.
  螢幕模式僅限 Windows，而且假設棋盤在主螢幕上。
- Image mode thresholds are calibrated on iPhone 13 Pro screenshots.
  圖片模式的門檻值是照 iPhone 13 Pro 的截圖校準的。
