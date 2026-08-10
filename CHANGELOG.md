# Changelog

Notable changes. Format loosely follows [Keep a Changelog](https://keepachangelog.com/).
重要變更紀錄。格式大致依照 Keep a Changelog。

## [Unreleased] — `speed-optimization` branch, not yet merged to `main`
## [尚未發布] —— `speed-optimization` 分支，尚未合併回 `main`

**Not a numbered release.** This branch exists to work on solve speed and
reliability without touching the stable, daily-verified `main` branch. Every
item below is real-world-tested on this branch but has not yet gone through
`main`'s merge process. Two multi-day rounds of real play surfaced the fixes
below; three items were caught and reworked by an independent adversarial
review before shipping (see the Patches guard entry).
**不是編號版本。** 這個分支專門用來做解題速度與穩定性的改動，不動到穩定、
每天都用真實遊玩驗證過的 `main` 分支。以下每一項都在這個分支上做過真實
遊玩測試，但還沒走過 `main` 的合併流程。兩輪跨日的真實遊玩找出了下面
這些修正；其中三項在上線前被獨立的對抗性審查抓到問題並重做過
（見 Patches 保護那一條）。

### Fixed — Patches never detected while waiting, however long the wait 拼塊等待再久都偵測不到

- **`wait_for_board()`'s cheap presence check only ever tried 1x scale, and
  some Patches boards' own outer border is too faint for that to ever find at
  native resolution - no amount of waiting fixes it.** Diagnosed from a real
  2026-08-10 session: the log showed 68s of continuous polling (353 polls)
  with zero detections while a screen recording of the same region confirmed
  the real Patches board was genuinely on screen, unattended, the whole time.
  Root-caused by saving the EXACT bytes `BoardWatch`'s own capture path
  produces (the "測範圍"/Test-region button) rather than trusting a screen
  recording of the same region - the two are not the same capture, and only
  the real one showed the bug: `find_board_bbox` at 1x found nothing
  board-sized at all (largest contour 7,980px² against the 15%-of-frame
  67,200px² threshold - the fixed-size Canny+dilate kernels were only
  catching the individual number badges, not the board's own faint outer
  line), while the identical bytes at 1.75x locate cleanly. This is the exact
  same class of failure `puzzles/__init__.py`'s `_locate_board` already
  named in its own docstring ("pre-scaling if its faint border is missed at
  1x") - it had simply never been ported into this module's separate cheap
  check. Fixed by retrying at `BORDER_RETRY_SCALE = 1.75` (same value as
  `_PRESCALE_STEPS[1]`) whenever the 1x check finds nothing. Cost, measured
  on the real failing capture: 1x alone averages 30.0ms when nothing is
  present; the added retry brings the worst case to 150.9ms - still under
  `POLL_INTERVAL`'s own budget, and never paid once a board (at either
  scale) is actually present. New regression test
  (`test_a_faint_bordered_board_is_found_via_the_retry_scale`) pins the real
  failing capture (`tests/fixtures/patches_faint_border_20260810.png`) end
  to end through `wait_for_board()`.
  **`wait_for_board()` 的便宜存在檢查一直只試 1 倍縮放，而某些拼塊棋盤自己
  的外框在原始擷取解析度下太淡，不管等多久都找不到——這不是時間問題。**
  從一次真實 2026-08-10 的執行診斷出來：log 顯示連續輪詢 68 秒（353 次）
  完全沒偵測到，而同一範圍的螢幕錄影確認 Patches 棋盤整段時間確實都在
  畫面上、沒人動過它。真正找到根因的方法，是存下 `BoardWatch` 自己擷取
  路徑真正產生的位元組（面板上的「測範圍」按鈕），而不是信任同一範圍的
  螢幕錄影——兩者不是同一次擷取，只有真正的那次才顯示出問題：
  `find_board_bbox` 在 1 倍下完全找不到任何棋盤大小的東西（最大輪廓只有
  7,980 平方像素，門檻是畫面 15%＝67,200——固定尺寸的 Canny+dilate 核只抓
  到一顆顆數字標籤，抓不到棋盤本身那圈很淡的外框線），而同一份位元組在
  1.75 倍下乾淨定位成功。這跟 `puzzles/__init__.py` 的 `_locate_board`
  自己文件字串早就取過名字的問題是同一類（「淡色邊框在原尺寸抓不到時
  先放大再找」）——只是一直沒有搬進這個模組獨立的便宜檢查裡。修法：
  1 倍檢查找不到時，用 `BORDER_RETRY_SCALE = 1.75`（跟 `_PRESCALE_STEPS[1]`
  同一個值）重試一次。成本，對著真實的失敗擷取實測：只用 1 倍在畫面上
  什麼都沒有時平均 30.0 毫秒；加上這次重試後最壞情況變成 150.9 毫秒——
  仍在 `POLL_INTERVAL` 自己的預算內，而且只要任一倍率真的找到棋盤就不會
  付這筆成本。新增回歸測試
  （`test_a_faint_bordered_board_is_found_via_the_retry_scale`）把這張真實
  失敗擷取（`tests/fixtures/patches_faint_border_20260810.png`）整個穿過
  `wait_for_board()` 釘住。

### Fixed — Mini Sudoku misdetected as Tango, costing 6-9s per occurrence 迷你數獨被誤判成 Tango，每次白燒 6~9 秒

- **`detect_type`'s `NO_COLOR_RATIO` (0.006) gave a genuine Mini Sudoku board
  only a 1.6x safety margin before falling into the Tango branch.** Measured
  on the only live Sudoku fixture on file (`live_mini_sudoku_browser.png`):
  coloured-pixel ratio 0.00366 (sub-box shading), and that colour is itself
  88.7% orange/blue - over `TANGO_HUE_RATIO`'s 0.75 cutoff - so crossing the
  ratio threshold sent it straight into "tango" with no further check.
  Confirmed against two real 2026-08-10 production runs
  (`run_20260810_181407_416.log`, `run_20260810_185005_381.log`): the same
  Sudoku board detected as tango, burned the full tango ladder (~16
  crop/scale attempts, all "multiple solutions" or "board not found") plus a
  queens attempt, and only resolved correctly ~6-9s later via the
  fallback-type sweep - while the real board sat on screen the whole time.
  Raised to 0.01: ~2.7x margin above the measured sudoku value, ~2.6x margin
  below the smallest correctly-located non-sudoku fixture (0.02559). This
  only changes which type is tried FIRST - every puzzle module still
  requires its own unique-solution/sanity guard, so a wrong guess still
  fails cleanly rather than inventing an answer; this is a speed fix, not a
  loosened correctness gate. New regression test
  (`test_mini_sudoku_survives_extra_colour_noise`) synthetically reproduces
  the capture-variance class of failure and confirms it survives under the
  new threshold.
  **`detect_type` 的 `NO_COLOR_RATIO`（0.006）只給真的 Mini Sudoku 盤面
  1.6 倍安全邊界，一跨過就會掉進 Tango 分支。** 對目前唯一的真實瀏覽器
  Sudoku 測試圖（`live_mini_sudoku_browser.png`）實測：彩色像素比例
  0.00366（子九宮格底色），而這個顏色本身有 88.7% 落在橘／藍色相——
  超過 `TANGO_HUE_RATIO` 的 0.75 門檻——所以比例一旦跨過門檻就會直接被當成
  「tango」，不會再做任何檢查。對照兩筆真實 2026-08-10 執行記錄
  （`run_20260810_181407_416.log`、`run_20260810_185005_381.log`）確認：
  同一個 Sudoku 盤面被判成 tango，燒完整條 tango 階梯（約 16 種裁切／縮放
  組合，全部「找到多組解」或「偵測不到棋盤」）加一次 queens 嘗試，要等
  備援類型全掃過、約 6~9 秒後才靠備援機制解對——而真正的棋盤其實整段
  時間都在畫面上。提高到 0.01：量到的 sudoku 數值上方有約 2.7 倍邊界，
  下方離「正確定位到棋盤」的最小非 sudoku 測試圖值（0.02559）還有約
  2.6 倍邊界。這裡只改變「先試哪個類型」——每個謎題模組仍然各自要求
  解唯一／合理性守門，猜錯一樣會乾淨地失敗而不是編答案；這是速度修正，
  不是放寬正確性門檻。新增的回歸測試
  （`test_mini_sudoku_survives_extra_colour_noise`）合成重現了這種
  「擷取誤差」等級的失敗，並確認在新門檻下能撐過去。

### Added — save the capture a solve fully failed on, for later diagnosis 求解完全失敗時存下當時的擷取畫面供事後排查

- **A 2026-08-10 Patches failure ("28 label(s) unreadable ... tiling is
  ambiguous", every crop/scale in the ladder) could not be root-caused
  afterwards, because nothing had kept the actual bytes the recogniser saw** -
  a hand screenshot taken around the same time solved cleanly through the
  full pipeline, proving it was not the same capture. A solve that exhausts
  every `MAX_SOLVE_ATTEMPTS` retry now saves the LAST attempted capture (the
  exact image the failing `result` came from) to `captures_dir()` as
  `solve_failed_<puzzle>_<epoch_ms>.png` and logs where it went - the same
  idea as the existing guard `boardwatch_stop_*.png` save, applied to a full
  recognition failure instead of a mid-fill abort. A diagnostic save can
  never break the failure-handling path itself, so it is wrapped the same
  way the guard's save is (best-effort, swallows its own exceptions). New
  test: `test_solve_failed_frame_is_saved_for_diagnosis`.
  **2026-08-10 有一次 Patches 失敗（「28 個標籤讀不出來…切法不唯一」，
  階梯裡每個裁切／縮放都試過）事後完全查不出根因，因為沒有任何東西留住
  辨識器當時實際看到的位元組**——差不多同時間手動截的圖卻能透過完整流程
  乾淨解出來，證明根本不是同一張擷取畫面。現在只要求解把
  `MAX_SOLVE_ATTEMPTS` 次重試都用盡，就會把「最後一次嘗試」用的擷取畫面
  （也就是那次失敗 `result` 實際來自的那張圖）存進 `captures_dir()`，
  檔名是 `solve_failed_<puzzle>_<epoch_ms>.png`，並在記錄裡寫出存去哪裡——
  跟既有守衛的 `boardwatch_stop_*.png` 存檔同一個想法，套用在「整個辨識
  都失敗」而不是「填答中途中止」。診斷用的存檔絕不能弄壞失敗處理流程
  本身，所以包法跟守衛的存檔一樣（盡力而為、自己吞掉例外）。
  新增測試：`test_solve_failed_frame_is_saved_for_diagnosis`。

### Fixed — Patches false-aborting mid-fill, again 拼塊填答中途又誤判中止

- **A real 8x8 Patches fill was wrongly aborted after only 4 of 16 rectangles,
  reproduced identically twice on the same board.** `detect_grid_size`
  (the guard's structural re-check) failed 7 consecutive times once enough of
  the top rows were covered by the puzzle's own fill colour, exceeding
  `PATCHES_FAILURE_TOLERANCE=6` - a stricter, more easily triggered version of
  the exact false abort 1.2.0's masking fallback and 6-check tolerance were
  built to bound. Confirmed against the screen recording that the board never
  moved; the guard's own structural check had simply run out of information to
  work with, because our own fills permanently erase the interior grid lines
  it depends on.
  **一次真實的 8x8 拼塊填答，只畫完 16 塊裡的 4 塊就被誤判中止，在同一個
  棋盤上完全相同地重現了兩次。** `detect_grid_size`（保護自己的結構性重新
  檢查）在頂端幾列被自己的填色蓋住足夠面積之後，連續失敗 7 次，超過
  `PATCHES_FAILURE_TOLERANCE=6`——這是 1.2.0 的遮色備援與 6 次容忍原本要
  界定住的那個誤判，一個更嚴重、更容易觸發的版本。對照螢幕錄影確認棋盤
  完全沒有移動過；保護自己的結構性檢查只是沒有資訊可用了，因為我們自己的
  填色會永久抹掉它依賴的內部格線。

- **Fixed with a reference-content check, not a bigger tolerance number.**
  When the structural locator fails, `board_watch.py` (Patches only) now
  compares the parts of the board NOT covered by our own fills against the
  frame the plan was armed on - affirming the board is still ours without
  needing to re-derive its grid at all. Real measurement first: `find_board_bbox`
  (the board's outer contour) survives on every heavily-filled real fixture
  tested, including today's exact failure frame, even though the interior
  grid-line check does not - because our fills are drawn inside cells, never
  over the board's own outer edge.
  **修法是參考內容比對，不是把容忍次數調更大。** 結構性定位器失敗時，
  `board_watch.py`（僅拼塊）現在會把「沒被我們自己填色蓋住」的部分，
  拿去跟計畫武裝當下的畫面比對——不需要重新推算格線，就能確認棋盤還是
  我們的。先做了真實量測：`find_board_bbox`（棋盤的外框輪廓）在每一張
  測過的、填得很滿的真實測試圖上都還找得到，包含今天這次失敗當下的畫面，
  即使內部格線檢查完全失敗——因為我們的填色永遠畫在格子「裡面」，
  不會蓋到棋盤自己的外框。

- **The first design was wrong, and an independent adversarial review caught
  it before it shipped.** That version scored a 0-1 confidence and let the
  content check ABORT immediately on a mismatch (faster than the 6-check
  tolerance for a genuine replacement). Four independent reviewers, briefed
  only on the diff and told to refute it, found: (a) a uniform gray frame in
  a narrow brightness band scored a perfect 1.0 and disabled the guard
  permanently; (b) worse, replayed against the REAL 2026-08-06 incident
  fixture (the one `PATCHES_FAILURE_TOLERANCE=6` exists for), the immediate-
  abort verdict killed that correct fill on the very first check, because
  that pair has a real ~1% scale drift between captures that a small
  translation search cannot compensate. Rebuilt around a different contract:
  the check can only ever AFFIRM ("content matches, keep going") or DECLINE
  ("could not confirm, fall through to the untouched original tolerance
  path") - it never aborts anything itself. Under that contract every
  scenario is provably no worse than the pre-change guard, because the worst
  the new code can do is decline, which is the old path unchanged. Re-review
  after the rewrite found no further safety issue; two of its hardening
  suggestions (treat an unexpected exception inside the check as a decline,
  not a crash; document the measured boundary of the affirmation gate) were
  folded in.
  **第一版設計是錯的，在上線前被一次獨立的對抗性審查抓到。** 那一版會給
  0~1 的信心分數，並且讓內容比對在不吻合時「立刻中止」（比真的替換情境
  原本 6 次的容忍還快）。四位只看得到程式差異、被要求去推翻它的獨立
  審查者發現：(a) 落在特定亮度區間的整片灰階畫面拿滿分 1.0，把保護永久
  關掉；(b) 更糟的是，重播 2026-08-06 那次真實事件的測試圖（正是
  `PATCHES_FAILURE_TOLERANCE=6` 存在的理由）時，立即中止判決在「第一次」
  檢查就把那次正確的填答錯殺了，因為那組畫面兩次擷取之間有約 1% 的真實
  縮放漂移，小範圍的平移搜尋補償不了。改成另一種契約重做：這個檢查
  只可能「認證」（內容吻合，繼續）或「拒絕認證」（無法確認，落回原封
  不動的舊容忍路徑）——它自己絕不中止任何事。在這個契約下，每一種情境
  都可證明不比修改前的保護差，因為新程式碼最壞的結果就是拒絕認證，
  而那正是舊路徑本身。重做後的複審沒有再找到安全問題；審查提出的兩個
  強化建議（比對內部出現預期外的例外時視同拒絕認證、不當機；把認證關卡
  實測到的邊界記進文件）都已採納。

- **Real-world confirmed the same day.** Re-run against the exact puzzle that
  failed that morning: the guard's structural check failed the same way, but
  the content check affirmed the board 11 times in a row where it used to
  need (and eventually exceed) the tolerance counter, and the fill completed
  - visually confirmed against the LinkedIn puzzle list showing Patches as
  solved, and one of the 16 checks along the way genuinely could not be
  affirmed and correctly fell through to (and was covered by) the original
  tolerance mechanism, evidence the two layers work together as designed.
  **當天就用真實情境確認過。** 拿當天早上失敗的那道題目重跑一次：保護的
  結構性檢查一樣照舊失敗，但內容比對連續 11 次認證棋盤沒問題（這些以前
  都要靠、而且最終會超過容忍計數），填答順利完成——對照 LinkedIn 的
  謎題清單顯示 Patches 已完成，過程中確實有一次真的無法被認證，正確地
  落回（並且被撐住）原本的容忍機制，證明兩層機制真的照設計搭配運作。

### Added — repeated-failure alert 新增：連續失敗提醒

- **Continuous mode used to fail silently.** If recognition exhausted its
  retries, the status text changed but - with the window minimised, which
  continuous mode does by default - nothing on screen showed it, and the loop
  would proceed to wait for a board that structurally never disappears (since
  nothing made the user navigate away from the failed puzzle), silently
  wasting the rest of the sitting. Continuous mode now restores the window,
  plays a system alert sound, turns the status line red, and stops the
  session on the very first fully-retried failure (three fresh-capture
  attempts already exhausted, not a single-frame fluke) rather than spinning
  unattended.
  **連續模式以前失敗時完全無聲無息。** 如果辨識用盡重試次數，狀態文字會
  換，但視窗預設是縮到最小的，畫面上什麼都看不到，迴圈接著會去等一個
  結構上不會消失的棋盤（沒有任何動作讓使用者切離那個失敗的題目），整輪
  剩下的時間就這樣安靜地浪費掉。連續模式現在會在第一次「完整重試過仍然
  失敗」（已經耗盡三次新擷取嘗試，不是單張影格的偶發問題）時，還原視窗、
  播放系統提示音、把狀態列變成紅色，並且停止整個連續模式，而不是繼續
  無人看管地空轉。
- **The failure message now says whether retrying would have helped.** If all
  retry attempts (each on a fresh screen capture) produced the exact same
  error, that is evidence of a persistent problem rather than a rendering-
  timing fluke, and the log/alert now says so explicitly instead of leaving
  the user to assume "try again" is the fix when it was already tried three
  times, silently.
  **失敗訊息現在會說明「再試一次」有沒有意義。** 如果每一次重試（各自用
  新擷取的畫面）都得到完全一樣的錯誤，這就是持續性問題而不是渲染時機
  偶發問題的證據，現在記錄檔／提醒訊息會明講出來，而不是讓使用者以為
  「再試一次」有機會解決，但其實背後已經默默試過三次了。

### Added — screen-resolution-change warning 新增：螢幕解析度改變警告

- **A saved capture region silently went stale if the screen changed.** The
  region is a fixed rectangle of absolute screen pixels, calibrated once and
  reused forever; switching monitors, changing resolution, or changing
  Windows display scaling all invalidate it with no signal beyond a generic
  "board not found". The app now remembers the primary monitor's size at the
  moment the region was last actually recalibrated (not on every save - that
  would silently re-baseline the warning against a region that was never
  re-verified for the new screen) and warns, without blocking, when the
  current size disagrees.
  **螢幕換了之後，存起來的擷取範圍會悄悄失效。** 擷取範圍是一個固定的
  絕對螢幕像素矩形，只在校準當下決定一次、之後一直沿用；換螢幕、換
  解析度、改 Windows 顯示縮放比例都會讓它失效，而且除了一句籠統的
  「找不到棋盤」之外沒有任何提示。程式現在會記住擷取範圍「上次真的被
  重新校準」那一刻的主螢幕尺寸（不是每次存檔都記——那樣會讓警告悄悄
  用一個「其實從來沒有針對新螢幕重新驗證過」的範圍當基準），目前尺寸
  對不上時會提醒（不會擋住執行）。

### Added — Sudoku digit-calibration candidate harvesting 新增：數獨數字校準候選收集

- **A cell we filled ourselves, but could not read back confidently, is now
  saved as a future calibration candidate.** After a fill, Sudoku's verify
  pass already re-reads every cell; when a target cell reads as unreadable
  (not misread - genuinely unreadable) the digit it should hold is exactly
  what our own solver chose and the driver clicked/typed, which is the same
  standard of ground truth `tools/calibrate_digits.py`'s hand-verified tables
  already use. Saved to a separate `calibration_candidates/` folder, never
  the user's own `img/` captures folder, and never fed into the digit
  templates automatically - only a human deliberately running the
  calibration tool after looking at what was saved can do that, per this
  project's core rule against changing a threshold or template without
  looking at real evidence first. Explicitly does NOT harvest the puzzle's
  own printed givens (read by OCR, so a misread given's "ground truth" would
  be circular) or a cell read as a confidently WRONG digit (that ground
  truth is itself suspect - it could be a genuine misread or a dropped
  click).
  **一個我們自己填的、但讀不回來的格子，現在會被存成未來校準的候選資料。**
  填答之後，數獨的檢查補點步驟本來就會重讀每一格；當某個目標格讀不出來
  時（不是讀錯——是真的讀不出來），它應該要是的數字，就是我們自己的
  求解器選中、driver 親自點擊/打字打上去的那個，跟 `tools/calibrate_digits.py`
  人工核對過的真值表是同一個等級的可信度。存進獨立的
  `calibration_candidates/` 資料夾，不是使用者自己的 `img/` 存圖資料夾，
  也絕不會自動餵進數字範本——只有人工看過存下的東西、刻意手動執行校準
  工具才會生效，遵守這個專案「沒看過真實證據不能改動門檻或範本」的核心
  規則。刻意不收集題目原本印的提示數字（那是 OCR 讀出來的，一個讀錯的
  提示，其「真值」會是循環論證）、也不收集讀成「確信但錯誤」數字的格子
  （那個真值本身可疑——可能是真的誤讀，也可能是點擊沒生效）。

### Testing 測試

Test suites: 10 → 11 (`test_board_wait.py` added earlier this branch).
`test_board_guard.py` grew from 21 to 26 cases, five of them pinning the
adversarial review's counter-examples down as permanent regression tests
(a uniform-gray frame at any brightness, a different same-size Patches board
- the strongest attack found, a scrim/dim over the failing frame, and the
real 2026-08-06 incident replayed under the shipped production configuration).
All suites pass, `pyflakes` clean, both executables rebuilt and smoke-tested
after every round.
測試檔：10 → 11（`test_board_wait.py` 是這個分支較早新增的）。
`test_board_guard.py` 從 21 個案例增加到 26 個，其中 5 個把對抗性審查的
反例釘成永久回歸測試（任何亮度的整片灰畫面、另一塊同尺寸拼塊棋盤——
量到最強的攻擊、蓋在失敗畫面上的遮罩/調暗、以及在正式上線設定下重播的
2026-08-06 真實事件）。全部測試組都通過，`pyflakes` 乾淨，每一輪都重新
打包過兩個執行檔並煙霧測試過。

## [1.3.0] — 2026-08-05

**Upgrade from 1.2.0.** Two rounds of work. First, a rigorous audit-and-fix
pass covering every open defect from 1.2.0's known-limitations list: a stale
result that could save the wrong answer onto a new screenshot, a board guard
that missed the board simply moving, the CLI's automated path having no board
guard at all, the GUI unable to start without `mss` even in image mode, a
malformed saved region crashing startup, and a solve with no time budget that
"Stop" could not interrupt. Second, a session action log, so a day's single
real playthrough - the target puzzles reset once every 24 hours, so there is
no "try again with more logging" - leaves a complete, timestamped record of
what the program actually did. Confirmed by a full real playthrough of all
five puzzles in one sitting, no manual intervention needed.
**建議從 1.2.0 升級。** 這次分兩輪。第一輪是嚴謹的稽核與修正，涵蓋 1.2.0
已知限制清單裡的每一項開著的缺陷：換圖後沒清空的舊結果可能把答案存到新
截圖上、盤面守衛偵測不到棋盤只是「移動」了、CLI 的全自動路徑完全沒有
盤面守衛、圖片模式在沒有 `mss` 時也開不了 GUI、設定檔裡型別錯誤的擷取
範圍會讓程式啟動時當掉、求解沒有時間預算導致「停止」中斷不了它。
第二輪是新增一份執行動作記錄——因為目標謎題一天只會重置一次，
沒有「這次記錄不夠、明天再錄一次」的餘地，這份記錄要在單一次真實遊玩裡
就留下完整、帶時間戳記的軌跡。已用一次完整、不需人工介入的五題實際遊玩
確認過。

### Fixed — silent wrong answers and mouse safety 安靜的錯誤答案與滑鼠安全

- **A stale result could save the wrong answer onto a new screenshot.**
  Picking a new image or region without solving first left the previous
  puzzle's result in place; Save then wrote the old answer under the new
  file's name. Fixed by clearing the result atomically with the image.
  **換了新截圖但還沒求解，存圖可能把舊答案存到新截圖上。** 選新圖片或新
  範圍卻還沒求解時，舊結果原封不動留著；存圖就會把舊答案存成新檔名。
  已改為跟影像一起原子性地清空結果。
- **The board guard and post-fill verify both passed a board that had simply
  moved**, because both compare cells by grid index, which is
  translation-invariant. A 9x9 board shifted 80px down still verified as
  unchanged. Both now reject when the located board's position drifts beyond
  0.3 cell from where the plan expects it.
  **守衛跟填完後的驗證，對「只是移動了」的棋盤都會誤判通過**，因為兩者都是
  用格子索引比對，對平移不敏感。一個 9x9 棋盤往下移 80px 仍被判定沒有改變。
  現在兩者都會在定位到的棋盤位置偏移超過 0.3 格時判定為已改變。
- **`ui/cli.py --go` had no mid-plan board guard at all** - the GUI's
  protection was never wired into the CLI's fully-automated path. Measured
  on a scripted board replacement: the GUI stopped after 3 of 28 actions,
  `--go` ran all 28. Fixed by sharing one `board_watch.attach()` function
  between both callers.
  **CLI 的 `--go` 完全沒有填答中途的盤面守衛**——GUI 的保護從來沒有接進 CLI
  的全自動路徑。對一個腳本化的盤面替換實測：GUI 在 28 個動作裡走 3 個就停，
  `--go` 28 個全部走完。已改為 GUI 與 CLI 共用同一個 `board_watch.attach()`。
- **Closing the window mid-fill could leave the mouse button physically held
  down** - the worker thread is a daemon and closing used to just destroy the
  window, killing the thread before `drag_path`'s own `finally: mouseUp()`
  could run. Fixed with a proper close handler that stops the driver and
  joins the thread with a timeout first.
  **填答途中關閉視窗，可能讓滑鼠鍵維持在按下的狀態**——工作執行緒是
  daemon，以前關閉視窗只會直接銷毀視窗，讓執行緒在 `drag_path` 自己的
  `finally: mouseUp()` 有機會執行之前就被砍掉。已改成正式的關閉處理常式，
  先停止驅動、帶逾時 join 執行緒。

### Fixed — crashes and confusing behaviour 當掉與令人困惑的行為

- **The GUI could not start without `mss`, even in image mode**, which never
  captures a screen at all - `default_region()` reached `mss` unconditionally
  on every first run. Now falls back to a fixed rectangle if `mss` cannot be
  imported.
  **圖片模式（根本不會擷取畫面）在沒有 `mss` 時也開不了 GUI**——
  `default_region()` 以前每次第一次啟動都會無條件用到 `mss`。
  現在 `mss` 匯入失敗就退回固定矩形。
- **A malformed saved `region` crashed the GUI at startup**, and `fullscreen`
  has no UI, so hand-editing the settings file was the only way to reach a
  bad value. Now sanitised on load.
  **設定檔裡型別錯誤的 `region` 會讓 GUI 一啟動就當掉**，而 `fullscreen`
  沒有介面，手改設定檔是唯一能碰到壞值的方式。現在讀取時會先清洗過。
- **No wall-clock budget on a solve, and Stop could not interrupt one** - a 4K
  screen grab took 29-49s with no check-in point anywhere in that time. Added
  a `should_continue` callback polled between recognition-ladder rungs, wired
  to the GUI's Stop button end to end.
  **求解沒有時間預算，「停止」中斷不了它**——一次 4K 螢幕擷取要 29~49 秒，
  這整段時間完全沒有任何檢查點。新增 `should_continue` 回呼，在辨識階梯的
  每一階之間輪詢，並整條路線接到 GUI 的「停止」按鈕上。
- Ten smaller defects fixed alongside these: a save that failed silently, a
  region field typo permanently overwriting a calibrated value, a Stop
  pressed during capture being discarded, Sudoku's box-shape fallback
  returning a size that does not tile the board, `read_image` raising instead
  of returning `None` for a directory or locked file, a "zoom in" hint
  appended to unrelated failures, `--region` with a non-positive dimension
  escaping as a raw exception, pyautogui's emergency-stop fail-safe looking
  like a crash, and `--help` crashing on a non-UTF-8 console.
  另外十項較小的缺陷一併修好：存檔失敗會靜默、range 欄位打錯字會永久覆蓋
  校準值、擷取期間按下的停止會被忽略、數獨的盒子形狀備援回傳不能鋪滿棋盤
  的尺寸、`read_image` 對目錄或鎖定檔案拋例外而不是回傳 `None`、「請放大」
  提示被誤貼到無關的失敗上、`--region` 的非正數維度逸出成原始例外、
  pyautogui 的緊急停止看起來像當機、`--help` 在非 UTF-8 主控台當掉。

### Added — session action log 新增：執行動作記錄

- **`core/action_log.py`**: a timestamped, append-only record of every mouse
  action, every board-guard check (including tolerated near-misses that were
  previously invisible), every recognition-ladder attempt, and every
  recovered-from fallback firing. Written next to the executable so a day's
  log sits with the session it describes; a write failure is swallowed rather
  than able to break the feature it is logging. The GUI shows the log file's
  path on screen from the moment it starts, so a screen recording captures it
  from the first frame.
  **`core/action_log.py`**：帶時間戳記、只增不改的記錄——每一次滑鼠動作、
  每一次盤面守衛檢查（包含以前完全看不到、被容忍住的驚險時刻）、每一次
  辨識階梯的嘗試、每一次有救回來的備援被觸發。記錄檔存在執行檔旁邊；
  寫入失敗會被吞掉，不會反過來弄壞它正在記錄的功能。GUI 從啟動的那一刻
  就會把記錄檔路徑顯示在畫面上，讓螢幕錄影從第一格就拍得到。
- **`tools/log_summary.py`**: prints a log file's time span, a per-category
  line count, and every WARN/ERROR line verbatim, as a starting point before
  reading the full file.
  **`tools/log_summary.py`**：印出一份記錄檔的時間範圍、依類別的行數統計，
  以及每一行 WARN/ERROR 的原文，作為讀完整份記錄檔之前的起點。

### Testing 測試

Test suites: 7 → 10 (`test_settings.py`, `test_image_io.py`, `test_cli.py`
added). All ten pass, `pyflakes` clean, and a batch pass over all 24 project
fixture/sample images through the full recognise-and-solve pipeline confirmed
no exceptions and no silent wrong answers.
測試檔：7 → 10（新增 `test_settings.py`、`test_image_io.py`、
`test_cli.py`）。十組全過，`pyflakes` 乾淨，對專案裡全部 24 張範例／測試圖
批次跑完整的辨識求解流程，確認沒有例外、也沒有靜默的錯誤答案。

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
