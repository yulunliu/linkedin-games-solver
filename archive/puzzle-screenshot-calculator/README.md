# LinkedIn 謎題自動求解器

輸入一張手機截圖，自動辨識盤面並算出答案。支援五種謎題：

| 謎題 | 規則摘要 |
|---|---|
| **Tango** (太陽/月亮) | 每列/行太陽與月亮數量相同、不可三連、`=` 同類 `×` 異類 |
| **Queens** (皇后) | 每行/每列/每個色塊區域恰好一個皇后，皇后不可相鄰(含對角線) |
| **Mini Sudoku** (迷你數獨) | 每列/行/宮 1..N 各出現一次 |
| **Zip** (連線) | 一條路徑填滿所有格子、依序經過編號圓點、不可穿牆 |
| **Patches** (拼塊) | 把盤面完全切成矩形，每塊恰含一個數字標籤，面積=數字且形狀符合標籤型別 |

## 直接使用 (雙擊執行檔)

`dist/PuzzleSolver.exe` 是打包好的單一執行檔，雙擊就能開啟視窗：

1. 「選擇圖片...」挑選手機截圖（整張截圖直接用，不需要裁切）
2. 「謎題類型」預設**自動判斷**，判斷錯了可以手動指定
3. 按「分析並求解」
4. 畫面顯示答案疊圖 + 文字報告
5. 「另存答案圖片...」可把結果存成 PNG

> Zip 這類路徑題需要搜尋漢米頓路徑，可能要跑數秒到數十秒，求解期間視窗不會凍結。

## 開發模式 (跑原始碼)

```bash
pip install -r requirements.txt
python gui.py                                   # 視窗版
python main.py samples/S__104316934_0.jpg        # 命令列版 (自動判斷類型)
python main.py xxx.jpg --type zip --debug        # 指定類型並輸出除錯圖
```

`main.py` 參數：

- `--type {tango,queens,sudoku,zip,patches}`：指定謎題類型（預設自動判斷）
- `--grid-size N`：手動指定棋盤格數（預設自動偵測）
- `--debug`：輸出 `xxx_debug.png`，標出每格辨識結果，用來校準
- `--out path.png`：指定答案疊圖輸出路徑

## 重新打包 exe

```bash
python -m PyInstaller --noconfirm --onefile --windowed --name PuzzleSolver --collect-all ortools gui.py
```

`--collect-all ortools` 是必要的，否則 OR-Tools 的原生 DLL（位於 `ortools/.libs/`）
不會被收進 exe，執行時會出現 `ImportError: DLL load failed while importing cp_model_helper`。

## 檔案結構

共用模組：

- `board.py`：棋盤外框偵測、格數推算（用**格線間距**而非線條數量推算，見下方說明）、切格
- `img_io.py`：Unicode 路徑安全的圖片讀寫（見下方說明）
- `digit_ocr.py`：輕量數字辨識（字形正規化 + 範本比對，支援多位數）
- `digit_templates.py`：**自動產生**的字形範本，由 `calibrate_digits.py` 從實際截圖校準
- `calibrate_digits.py`：重新產生字形範本的校準腳本
- `registry.py`：謎題類型註冊表 + 依畫面顏色特徵自動判斷謎題類型
- `puzzle_base.py`：所有謎題模組共用的 `PuzzleResult` 介面

各謎題模組（都提供 `NAME` 與 `analyze(image, n_hint, debug)`）：

- `puzzle_tango.py` → 包裝既有的 `pipeline.py` / `solver.py` / `grid_detector.py` / `cell_classifier.py` / `edge_classifier.py`
- `puzzle_queens.py`、`puzzle_sudoku.py`、`puzzle_zip.py`、`puzzle_patches.py`

入口與測試：

- `gui.py`：Tkinter 桌面 GUI（打包 exe 用這個）
- `main.py`：CLI
- `tests/test_solver.py`：Tango 求解器單元測試
- `tests/test_puzzles.py`：其餘四種求解器單元測試（含無解案例）
- `tests/make_synthetic_puzzle.py`：產生合成 Tango 測試圖

## 已知重要細節（踩過的坑）

- **中文路徑問題**：`cv2.imread` / `cv2.imwrite` 在 Windows 上遇到非 ASCII 路徑會
  **靜默失敗**（回傳 `None`/`False`，不丟例外）。本專案路徑本身含中文，所有讀寫
  一律走 `img_io.py` 的 `imread_unicode` / `imwrite_unicode`，**不要**直接呼叫 cv2 的版本。

- **格數要用格線間距推算，不能數線條數量**：Patches 的最外圈格線比內部格線更淡，
  在中等門檻下只會抓到內部格線、漏掉最外兩條，用數量推算會少算格數。改用
  `N = 棋盤寬度 / 格線間距` 就不受影響。

- **Tango 的棋盤沒有外框**：手機截圖裡那個粗框其實是整張 App 卡片（標題列一路包到
  說明文字），棋盤格線很淡也沒有獨立外框，所以 Tango 走的是 `grid_detector.py` 的
  「內容定位法」（用格內圖示位置反推棋盤），且**需要先知道格數**（固定用 6）。
  其他四種謎題的棋盤都有明顯外框，走 `board.py`。

- **Tango 的 `=`/`×` 符號是棕色不是灰黑色**：跟太陽圖示同色系、飽和度也不低。
  原本用「濾掉彩色像素」避免圖示干擾，結果把符號本身也濾掉了。改用 HSV 的
  **明度 V** 判斷（符號 V≈148，背景 V≈248~255、圖示 V≈233~234）。

- **Tango 的 given 格底色只比白色暗一點**（V≈248 vs 255），門檻要放到 253。

- **Zip 圓點內的數字要用「填洞」取出**：圓點是實心黑圓、數字是白色，數字剛好是
  這個黑色連通元件內部的洞。用形態學運算去逼近會變形；改用從邊界灌水、灌不到的
  背景就是洞，可精確取出。（注意 floodFill 的外圈 padding 值必須跟要清除的背景
  同值，否則灌水什麼都清不掉。）

- **Patches 的虛線標籤代表「任一形狀」**：虛線標籤其實是三個半透明形狀疊在一起，
  中間有空隙，所以**填滿率**（色塊面積/外接框面積）明顯較低（實測虛線 0.76~0.79、
  實心 0.95~0.98），用這個來區分；實心標籤再用外接框長寬比判斷正方形/橫向/縱向。

- **這個 App 的字型「5」下半部很圓**，用一般 Windows 字型比對容易被判成「6」。
  所以 `digit_templates.py` 直接從截圖校準真正的字形當範本；範本沒涵蓋到的數字
  （目前是 0 與 7）才退回用 Arial Bold 算繪。要擴充範本就在
  `calibrate_digits.py` 補樣本與答案後重跑。

## 待驗證

每種謎題目前都只用**一張**真實截圖驗證過（辨識結果與答案都經人工核對）。
不同解析度的手機、深色模式、或不同盤面大小可能還需要微調門檻，
遇到辨識錯誤時先用 `--debug` 看除錯圖定位問題。
