# Changelog

Notable changes. Format loosely follows [Keep a Changelog](https://keepachangelog.com/).
重要變更紀錄。格式大致依照 Keep a Changelog。

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
