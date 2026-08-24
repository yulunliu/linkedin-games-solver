# Contributing

*中文版在下半部 / Chinese version in the second half*

Thanks for looking. The most useful contribution to this project is almost
always **a screenshot**, not code — see below.

## The one rule

> **Succeeding is not the same as being correct.**

If recognition misreads one constraint, the solver still returns a
perfectly legal-looking board — just the wrong one, silently, and then the
program moves your mouse based on it. Any change that makes a wrong answer
more likely to be *reported as success* will be rejected, even if it fixes a
real failure. Failing loudly is always the better outcome.

In practice this means every recognition change needs one of:

- a uniqueness check (if a second solution exists, recognition missed something)
- a structural sanity guard (region count, label count, dot numbering)
- or an explicit "unreadable" path that aborts instead of guessing

## Before you open a PR

```bash
python tests/run_all.py
```

All eleven suites must pass. They are offline and none of them moves the mouse,
so they are safe to run anywhere.

```bash
python -m pyflakes linkedin_games_solver tools tests
```

Should print nothing.

## Reporting a recognition bug

This is the highest-value contribution. Please include:

1. **The screenshot itself** — in screen mode, press **Save**; the image it
   writes is exactly what the recogniser saw.
2. What the puzzle actually was (board size, and the answer if you solved it).
3. The log text from the app window.

A screenshot that fails is directly usable as a test fixture, which is how
every bug in this project has been fixed and kept fixed.

## Adding a test fixture

1. Put the image in `tests/fixtures/`.
2. Add a case to `tests/test_recognition.py`, with a docstring saying **which
   bug it guards against**. Every fixture in there corresponds to a real
   failure; a fixture without a story is just a slower test.
3. Verify the expected values **by eye from the screenshot**, not by running
   the recogniser and recording its output. A test that asserts what the code
   currently does proves nothing.

There is a real example of getting this wrong in
[docs/DESIGN.md](docs/DESIGN.md#patches-the-white-gaps-that-looked-like-digits):
a fixture built by filling in a whole badge quietly turned a *dashed* badge
into a *solid* one, so the test passed against a board that cannot occur.

## Digits look wrong on your device

The digit templates are captured from one app rendering. If your phone or
browser draws them differently:

```bash
python tools/calibrate_digits.py
```

Point `SUDOKU_IMAGE` / `PATCHES_IMAGE` at your own screenshots and update the
truth tables (`SUDOKU_GIVENS`, `PATCHES_LABELS`) with what you can see in
them. The script refuses to write a template set that is missing any digit
0-9, because a digit with no template gets silently read as a different one.

## Adding a sixth puzzle

Six steps, listed in
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md#adding-a-sixth-puzzle). Nothing in
`core/`, `ui/`, `capture.py`, `mapper.py` or `input_driver.py` needs to change.

## Code style

- Comments in **English and 中文 together**, at paragraph level, with the
  tricky lines called out individually. Match the surrounding files.
- Every tuning constant gets a comment saying **what was measured** to arrive
  at it. `ICON_INSET_RATIO = 0.28  # crown 0.268~0.374, empty 0.000` is the
  standard; a bare number is not.
- `input_driver.py` is the only file that may move the mouse. Keep it that way.
- No new runtime dependency without a reason in the PR description.

---

# 貢獻指南

謝謝你來看。對這個專案最有用的貢獻幾乎都是**一張截圖**，而不是程式碼 —— 見下。

## 唯一的規則

> **「跑得出答案」不等於「答案是對的」。**

如果辨識讀錯一個條件，求解器一樣會回傳一個看起來完全合法的盤面 ——
只是錯的，而且沒有任何警訊，然後程式會照著它去動你的滑鼠。
任何會讓「錯誤答案更容易被回報成成功」的修改都會被退回，就算它真的修好了某個失敗。
明確地失敗永遠是比較好的結果。

實務上這代表每個辨識相關的修改都需要下列之一：

- 唯一性檢查（如果存在第二組解，就代表辨識漏掉了什麼）
- 結構合理性守門（色塊數量、標籤數量、圓點編號）
- 或一條明確的「讀不出來」路徑，用中止取代猜測

## 開 PR 之前

```bash
python tests/run_all.py
```

十一組測試都必須通過。它們全部離線、也不會動滑鼠，在任何地方跑都安全。

```bash
python -m pyflakes linkedin_games_solver tools tests
```

應該什麼都不印。

## 回報辨識問題

這是價值最高的貢獻。請附上：

1. **截圖本身** —— 在螢幕模式按**存圖**，它寫出來的圖就是辨識器實際看到的畫面。
2. 這題實際上是什麼（棋盤大小；如果你解出來了，也附上答案）。
3. 程式視窗裡的記錄文字。

一張會失敗的截圖可以直接拿來當測試素材 ——
這個專案裡每一個 bug 都是這樣被修好、並且維持修好的。

## 新增測試素材

1. 把圖片放進 `tests/fixtures/`。
2. 在 `tests/test_recognition.py` 加一個案例，並在 docstring 說明
   **它守住的是哪個 bug**。那裡每一張圖都對應一個真實的失敗；
   沒有故事的素材只是讓測試變慢而已。
3. 預期數值要**人工看著截圖核對**，不要跑辨識器再把它的輸出記下來。
   一個「驗證程式目前行為」的測試什麼也證明不了。

[docs/DESIGN.zh-TW.md](docs/DESIGN.zh-TW.md#patches那些看起來很像數字的白色縫隙)
裡有一個真的做錯的例子：把整個標籤塗滿做出來的素材，
不小心把**虛線**標籤變成了**實心**標籤，於是測試是對著一個現實中
不可能出現的盤面通過的。

## 你的裝置上數字讀不對

數字範本是從單一 App 的繪製結果擷取出來的。如果你的手機或瀏覽器畫得不一樣：

```bash
python tools/calibrate_digits.py
```

把 `SUDOKU_IMAGE` / `PATCHES_IMAGE` 指向你自己的截圖，
並依照你在圖上看到的內容更新答案表（`SUDOKU_GIVENS`、`PATCHES_LABELS`）。
這支腳本會拒絕寫出「缺少 0-9 任何一個數字」的範本集合，
因為沒有範本的數字會被默默讀成另一個數字。

## 新增第六款謎題

六個步驟，列在
[docs/ARCHITECTURE.zh-TW.md](docs/ARCHITECTURE.zh-TW.md#要新增第六款謎題)。
`core/`、`ui/`、`capture.py`、`mapper.py`、`input_driver.py` 都不需要改。

## 程式風格

- 註解**中英文並列**，以段落為單位，關鍵的那幾行另外單獨說明。
  請對齊周圍檔案的寫法。
- 每個調校用的常數都要有註解說明**是量到什麼才訂出這個值的**。
  `ICON_INSET_RATIO = 0.28  # 皇冠 0.268~0.374、空白 0.000` 是標準；
  只有一個裸數字不行。
- `input_driver.py` 是唯一可以動滑鼠的檔案。請維持這件事。
- 新增執行期相依套件時，請在 PR 說明裡寫理由。
