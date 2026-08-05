# Archive — predecessor prototypes / 前身原型

Two earlier, standalone projects that came before `linkedin-games-solver`.
Kept here as a historical record, not as maintained software.
兩個 `linkedin-games-solver` 出現之前、各自獨立的早期專案。
放在這裡是歷史紀錄，不是持續維護的軟體。

**Frozen. Do not modify.** Nothing under this folder should ever be edited to
fix a bug, add a feature, or "clean up" - if a change is needed, it belongs
in `linkedin-games-solver` itself, which is the actively maintained project.
**已凍結，不要修改。** 這個資料夾底下的任何東西都不該被修 bug、加功能，
或「順手整理」——真的需要改動，該改的地方是 `linkedin-games-solver` 本身，
那才是目前持續維護的專案。

| Folder | What it was | Relationship to `linkedin-games-solver` |
|---|---|---|
| [`puzzle-screenshot-calculator/`](puzzle-screenshot-calculator/) | The very first version: paste in a phone screenshot, it recognises the board and computes the answer. No automation - you read the answer and enter it yourself. | `linkedin-games-solver`'s `core/` and `puzzles/` layers grew out of this project's recognition and solving code. |
| [`browser_autoplay/`](browser_autoplay/) | The second version: adds screen capture and mouse automation on top of the first project's solving logic, so the answer gets clicked in automatically instead of typed by hand. | `linkedin-games-solver`'s `automation/` layer grew out of this project's capture/mapper/input-driver code. |

Both are referenced from time to time because, on some captures, one of these
older, narrower pipelines still produces a correct answer when the current
one does not - useful for cross-checking a suspicious result, not for
everyday use.
這兩個偶爾還是會被拿來對照——因為在某些擷取畫面上，這兩個功能範圍較窄的
舊流程，有時候還是能算出正確答案，而現在的版本反而不行——用來交叉核對
一個看起來可疑的結果，不是拿來日常使用。

Their own `dist/` (packaged .exe) and `build/` folders were left out of this
copy - they were PyInstaller output well over GitHub's 100MB per-file limit
and add nothing a reader of the source needs.
它們自己的 `dist/`（打包好的 .exe）與 `build/` 資料夾沒有一起複製過來——
那些是 PyInstaller 的輸出，遠超過 GitHub 單檔 100MB 的上限，
對讀原始碼的人也沒有幫助。
