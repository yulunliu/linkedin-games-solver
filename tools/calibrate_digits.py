"""
Regenerate core/digit_templates.py from real screenshots.
從真實截圖重新產生 core/digit_templates.py。

    python tools/calibrate_digits.py

WHY this exists 為什麼需要這支腳本:
  The app draws its digits in the iOS system font, and some of them differ
  enough from Windows fonts to be misread - its "5" has an unusually round
  bowl that most fonts classify as a "6". Glyphs taken from the app itself
  match exactly, so recognition becomes a lookup rather than a guess.
  這個 App 的數字是用 iOS 系統字型畫的，其中有幾個跟 Windows 字型差夠多而會誤判 ——
  它的「5」下半部特別圓，多數字型會判成「6」。直接取自 App 本身的字形完全吻合，
  辨識就從「猜」變成「查表」。

WHEN to run it 什麼時候要重跑:
  - the app changes its font 這個 App 換字型
  - you are on a device whose digits look different (another phone, a tablet)
    你的裝置數字長得不一樣（別支手機、平板）
  - you have a screenshot containing a digit that is still thin on real
    samples (0 and 7 each have exactly one, as of 2026-08-27 - see
    BROWSER_PATCHES_GIVENS_2 below) or a puzzle type with NO dedicated real
    source at all (Zip has none - every Zip digit template is borrowed from
    Sudoku/Patches/fonts, never checked against Zip's own widget rendering)
    你有一張截圖含有目前樣本還很單薄的數字（0 與 7 目前各只有一個真實樣本，
    截至 2026-08-27——見下面的 BROWSER_PATCHES_GIVENS_2），或是某個題型
    完全沒有專屬真實來源（Zip 就是——它的每個數字範本都是跟 Sudoku／
    Patches／字型借來的，從來沒有用 Zip 自己元件畫出來的數字驗證過）

HOW to add your own samples 怎麼加入自己的樣本:
  1. put the screenshot in tests/fixtures/ 把截圖放進 tests/fixtures/
  2. point SUDOKU_IMAGE / PATCHES_IMAGE at it, and update the matching truth
     table (SUDOKU_GIVENS / PATCHES_LABELS) with what each position really is
     把 SUDOKU_IMAGE / PATCHES_IMAGE 指向它，並更新對應的答案表
     （SUDOKU_GIVENS / PATCHES_LABELS），寫出每個位置實際上是什麼數字
  3. or add a new collector function and list it in main()
     或者新增一個收集器函式，並在 main() 裡列上它
  4. run this script and re-run the tests 執行這支腳本，然後重跑測試

The truth tables are read by eye from the screenshots. That is the point - the
templates must come from ground truth, not from what the current recogniser
happens to output, or errors would be baked in and reinforced.
底下的對照表是人工看著截圖讀出來的。這正是重點 —— 範本必須來自事實，
而不是來自目前辨識器剛好輸出的結果，否則錯誤會被烘焙進去並自我強化。
"""

from __future__ import annotations

import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from linkedin_games_solver.core import build_grid, read_image  # noqa: E402
from linkedin_games_solver.core.digits import (  # noqa: E402
    _render_font_glyph,
    normalize_glyph,
    split_digit_glyphs,
)
from linkedin_games_solver.puzzles import patches, zip_path  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures"
OUTPUT = ROOT / "linkedin_games_solver" / "core" / "digit_templates.py"

#: Digits that no screenshot contains yet, filled in from system fonts.
#: 目前沒有任何截圖含有的數字，改用系統字型補齊。
FALLBACK_DIGITS = (0, 7)
FALLBACK_FONTS = [
    "C:/Windows/Fonts/arialbd.ttf",
    "C:/Windows/Fonts/arial.ttf",
    "C:/Windows/Fonts/segoeuib.ttf",
    "C:/Windows/Fonts/segoeui.ttf",
    "C:/Windows/Fonts/calibrib.ttf",
    "C:/Windows/Fonts/verdana.ttf",
]

# --------------------------------------------------------------------------
# Ground truth, read by eye. 人工判讀的正確答案。
# --------------------------------------------------------------------------
#: Mini Sudoku givens: (row, col) -> digit. 數獨題目給的數字。
SUDOKU_GIVENS = {
    (0, 0): 1, (0, 1): 2,
    (1, 0): 3, (1, 1): 4,
    (2, 0): 2, (2, 5): 1,
    (3, 0): 4, (3, 5): 3,
    (4, 4): 1, (4, 5): 2,
    (5, 4): 3, (5, 5): 5,
}

#: A second, independent Sudoku source - the IN-BROWSER Mini Sudoku widget,
#: not the phone-app screenshot SUDOKU_GIVENS above comes from.
#: 第二個獨立的數獨來源——瀏覽器內建的 Mini Sudoku 元件，不是上面
#: SUDOKU_GIVENS 那張手機截圖的來源。
#:
#: WHY THIS SECOND SOURCE EXISTS 為什麼需要第二個來源:
#: real play (2026-08-08 session log + screen recording) showed digit "3"
#: scoring only 0.876-0.898 against APP_TEMPLATES on this board - short of
#: MIN_SCORE (0.90) - while every other digit on the SAME board scored
#: 0.94-0.99. classify_glyph correctly refused to guess (best_score <
#: MIN_SCORE), so the puzzle read as under-constrained and every solve
#: attempt correctly failed with "solution not unique". Not a logic bug -
#: the browser widget's own rendering of "3" simply was not close enough to
#: the phone-app "3" template above. Confirmed by direct reproduction:
#: python -c calls into core.digits.classify_glyph on this exact fixture's
#: (0,5) and (5,0) cells reproduced the exact scores from the session log.
#: 為什麼需要第二個來源：真實遊玩（2026-08-08 執行記錄 + 螢幕錄影）顯示，
#: 這個棋盤上的數字「3」對 APP_TEMPLATES 只拿到 0.876~0.898 分——不到
#: MIN_SCORE（0.90）——而同一個棋盤上其他每個數字都拿到 0.94~0.99 分。
#: classify_glyph 正確地拒絕用猜的（best_score < MIN_SCORE），於是題目被讀成
#: 條件不足，每一次求解嘗試都正確地失敗在「解不唯一」。這不是邏輯錯誤——
#: 純粹是瀏覽器元件自己畫的「3」，跟上面手機 App 的「3」範本不夠像。
#: 已直接重現確認：對這張測試圖的 (0,5) 與 (5,0) 格呼叫
#: core.digits.classify_glyph，重現出跟執行記錄裡一模一樣的分數。
BROWSER_SUDOKU_GIVENS = {
    (0, 0): 1, (0, 2): 2, (0, 5): 3,
    (2, 0): 2, (2, 2): 4,
    (3, 3): 4, (3, 5): 5,
    (5, 0): 3, (5, 3): 5, (5, 5): 1,
}
BROWSER_SUDOKU_IMAGE = "live_mini_sudoku_browser.png"

#: Patches labels: (row, col) -> number on the badge. Patches 標籤上的數字。
PATCHES_LABELS = {
    (0, 1): 4, (0, 5): 6, (1, 2): 6, (1, 6): 9,
    (3, 4): 3, (4, 3): 8, (6, 1): 12, (6, 5): 2,
    (7, 2): 6, (7, 6): 8,
}

#: A second, independent Patches source - the IN-BROWSER Patches widget, not
#: the phone-app screenshot PATCHES_LABELS above comes from. Same rationale
#: as BROWSER_SUDOKU_GIVENS below (see its own comment).
#:
#: WHY THIS SECOND SOURCE EXISTS 為什麼需要第二個來源:
#: real play (2026-08-25 session log + a saved solve_failed_patches_*.png
#: capture) showed the (4,4) badge's "8" scoring 0.9735 against
#: APP_TEMPLATES with "6" as runner-up at 0.9552 - a margin of 0.0183,
#: under MIN_MARGIN (0.020). classify_glyph correctly refused to guess (the
#: margin gate exists specifically so a confident-looking but ambiguous
#: score cannot reach the solver - see classify_glyph's own docstring), so
#: every crop/scale in solve_image's ladder reported the same "8" as
#: unreadable and the puzzle could not be solved. Not a logic bug in the
#: gate - the browser widget's own rendering of "8" simply was not close
#: enough to the phone-app "8" template above, exactly like BROWSER_SUDOKU_
#: GIVENS's "3". Confirmed by direct reproduction: solve_image() on the
#: saved capture reproduces the exact scores from the session log.
#: 為什麼需要第二個來源：真實遊玩（2026-08-25 執行記錄 + 一張存下的
#: solve_failed_patches_*.png）顯示 (4,4) 這個標籤的「8」對 APP_TEMPLATES
#: 只拿到 0.9735 分，第二名「6」拿到 0.9552 分——差距 0.0183，不到
#: MIN_MARGIN（0.020）。classify_glyph 正確地拒絕用猜的（這個安全邊界
#: 存在的目的，就是不讓「看起來有信心但其實模稜兩可」的分數混進求解器——
#: 見 classify_glyph 自己的文件字串），於是 solve_image 階梯裡每一次
#: 裁切／縮放都把同一個「8」讀成讀不出來，整題無法解出。不是安全邊界的
#: 邏輯錯誤——純粹是瀏覽器元件自己畫的「8」，跟上面手機 App 的「8」範本
#: 不夠像，跟 BROWSER_SUDOKU_GIVENS 的「3」是同一種狀況。已直接重現確認：
#: 對這張存下的截圖呼叫 solve_image()，重現出跟執行記錄裡一模一樣的分數。
BROWSER_PATCHES_GIVENS = {
    (1, 1): 6, (2, 3): 4, (3, 2): 9, (4, 4): 8,
}
BROWSER_PATCHES_IMAGE = "live_patches_browser.png"

#: A THIRD Patches source - a real browser capture (video frame, 2026-08-12
#: real session) chosen specifically to close a gap the project's own
#: architecture review found: digits "0" and "7" had ZERO real APP_TEMPLATES
#: samples before this - every match against them was decided entirely by
#: the system-font FALLBACK_TEMPLATES (see digit_templates.py's own
#: docstring on why that is a known risk class - a missing-font machine
#: reading "7" as "2" happened once already). "0" never appears alone in
#: this project's puzzles (a 1-cell Patches area is not a meaningful given,
#: and no other puzzle type prints a bare "0"), so the only way to harvest
#: a real "0" glyph at all is as the leading digit of a two-digit value like
#: "10" - which is exactly what (3,3) below is.
#: WHY THIS FRAME SPECIFICALLY 為什麼是這一幀: a systematic sweep of every
#: screen recording and screenshot in training-data/ (2026-08-26/27) for
#: real digit coverage found this frame (video position ~00:33,
#: LinkedIn_20260812_加速版.mp4) has a clean, not-yet-filled "7" (salmon)
#: and "10" (purple) badge pair with no overlapping UI (no tooltip, no
#: drag-hatch preview, no diagnostic watermark from this program's own
#: BoardWatch) - several OTHER candidate frames from the same sweep were
#: rejected for exactly those contamination reasons (a tooltip covering a
#: badge, this program's own small circled debug annotations getting
#: mistaken for glyphs, a multi-cell region's fill colour merging with its
#: own badge into one connected component). (0,3) in this frame's raw
#: capture is one such contaminated label - a stray debug annotation this
#: program's own overlay left behind reads as an unreadable glyph - and is
#: deliberately NOT included below; only real, unambiguous LinkedIn-rendered
#: digits are used as ground truth.
#: 為什麼是這一幀：系統性地掃過 training-data/ 裡的每一支螢幕錄影與截圖
#: （2026-08-26/27）找真實數字樣本，找到這一幀（影片位置約 00:33，
#: LinkedIn_20260812_加速版.mp4）有一組乾淨、還沒被填過的「7」（鮭紅）與
#: 「10」（紫）標籤，沒有任何畫面遮擋（沒有提示框、沒有拖曳中的預覽網底、
#: 沒有這支程式自己 BoardWatch 留下的診斷浮水印）——同一次搜尋裡有好幾個
#: 其他候選幀，正是因為這幾種汙染理由被排除（提示框蓋住標籤、這支程式
#: 自己畫的小圓圈除錯標記被誤認成字形、多格區塊的填色跟自己的標籤合併成
#: 一個連通元件）。這一幀原始擷取裡的 (0,3) 就是一個這樣被汙染的標籤——
#: 這支程式自己疊圖留下的除錯標記被讀成一個讀不出來的字形——刻意不放進
#: 下面的正確答案表；只用真的、不含糊的 LinkedIn 畫面數字當正確答案。
BROWSER_PATCHES_GIVENS_2 = {
    (3, 1): 7, (3, 3): 10, (3, 5): 5,
    (6, 0): 3, (6, 2): 5, (6, 4): 3, (6, 6): 3,
}
BROWSER_PATCHES_IMAGE_2 = "live_patches_browser_2.png"

#: A real Patches session that got and STAYED stuck (2026-08-27 deep review
#: of training-data/ found the same board recurring across
#: img/Patches_20260810.png, _2.png and four solve_failed_patches_*.png
#: captures spanning 20:28-20:30 on 2026-08-14 - the "卡關了嗎?" hint prompt
#: was still showing minutes later). No misread was involved here (every
#: label above already classified correctly), but the user asked to harvest
#: EVERY available real board as training reference regardless of whether it
#: solved - this one just adds independent real samples for a puzzle stuck
#: for reasons unrelated to digit recognition (an unsolvable / hint-seeking
#: layout), not a template gap.
#: 一次真的卡住、而且「一直卡住」的 Patches 真實對局（2026-08-27 深度檢視
#: training-data/ 時，發現同一個盤面重複出現在 img/Patches_20260810.png、
#: _2.png，以及跨越 2026-08-14 20:28-20:30 的四張
#: solve_failed_patches_*.png——「卡關了嗎？」提示過了好幾分鐘還在顯示）。
#: 這裡沒有牽涉到任何誤判（上面每個標籤本來就分類正確），只是使用者要求
#: 不管有沒有解成功，把每一個真實盤面都收集起來當訓練參考資料——這張純粹
#: 是多一組獨立的真實樣本，卡住的原因跟數字辨識無關（是排列本身卡關／
#: 需要提示），不是範本缺口。
BROWSER_PATCHES_GIVENS_3 = {
    (0, 0): 2, (0, 1): 6, (1, 4): 5, (2, 3): 3,
    (3, 2): 4, (4, 1): 8, (5, 4): 2, (5, 5): 6,
}
BROWSER_PATCHES_IMAGE_3 = "live_patches_browser_4.png"

#: A large 8x8 Patches board with unusually rich colour variety in one
#: capture (2026-08-27 deep review; original file was misleadingly named
#: img/Mini_Sudoku_20260809_1.png - it is Patches, not Sudoku, confirmed by
#: eye and by solve_image() succeeding under puzzle_key="patches").
#: 一張顏色特別豐富、8x8 的 Patches 大棋盤（2026-08-27 深度檢視時發現；
#: 原始檔名誤植成 img/Mini_Sudoku_20260809_1.png——實際上是 Patches，不是
#: Sudoku，已用肉眼與 solve_image() 在 puzzle_key="patches" 下成功求解
#: 兩者確認過）。
BROWSER_PATCHES_GIVENS_4 = {
    (0, 0): 4, (0, 4): 8, (1, 3): 3, (2, 2): 3,
    (3, 1): 2, (3, 3): 2, (3, 7): 4, (4, 0): 8,
    (4, 4): 6, (4, 6): 6, (5, 5): 3, (6, 4): 3,
    (7, 3): 4, (7, 7): 4,
}
BROWSER_PATCHES_IMAGE_4 = "live_patches_browser_5.png"

#: A single real board where digit "7" happens to appear in FOUR different
#: badge colours at once (2026-08-27 deep video review, LinkedIn_20260807_
#: 加速版.mp4 t=36s - this same puzzle got stuck for ~100s at this exact
#: layout before recovering, per the same review). Deliberately harvested to
#: reinforce "7" specifically: it is one of only two digits (with "0") that
#: had ZERO real samples before 2026-08-27 and still has the thinnest real
#: coverage of any digit even after that fix - see BROWSER_PATCHES_GIVENS_2's
#: own comment for the full history of that gap.
#: 一個「7」剛好同時以四種不同標籤顏色出現的真實盤面（2026-08-27 深度影片
#: 檢視，LinkedIn_20260807_加速版.mp4 t=36s——同一輪檢視也發現這一題曾在
#: 這個排列卡關約 100 秒後才恢復）。特意拿來加強「7」——它是唯一跟「0」一樣
#: 在 2026-08-27 之前完全沒有真實樣本的數字，就算補了 BROWSER_PATCHES_
#: GIVENS_2 之後，真實樣本數量仍然是所有數字裡最少的——完整脈絡見
#: BROWSER_PATCHES_GIVENS_2 自己的註解。
BROWSER_PATCHES_GIVENS_5 = {
    (0, 1): 7, (1, 4): 7, (2, 0): 7, (6, 5): 7,
}
BROWSER_PATCHES_IMAGE_5 = "live_patches_browser_6.png"

SUDOKU_IMAGE = "S__104316935_0.jpg"
PATCHES_IMAGE = "S__104316936_0.jpg"

#: Every Patches image this tool harvests digits from, paired with its own
#: ground truth - same reasoning as SUDOKU_SOURCES above (one source
#: rendering a digit acceptably does not mean every source does).
#: 這支工具會取樣數字的每一張 Patches 圖片，各自配對自己的正確答案表——
#: 理由跟上面的 SUDOKU_SOURCES 一樣（某個來源把某個數字畫得夠像，
#: 不代表每個來源都夠像）。
PATCHES_SOURCES = [
    (PATCHES_IMAGE, PATCHES_LABELS),
    (BROWSER_PATCHES_IMAGE, BROWSER_PATCHES_GIVENS),
    (BROWSER_PATCHES_IMAGE_2, BROWSER_PATCHES_GIVENS_2),
    (BROWSER_PATCHES_IMAGE_3, BROWSER_PATCHES_GIVENS_3),
    (BROWSER_PATCHES_IMAGE_4, BROWSER_PATCHES_GIVENS_4),
    (BROWSER_PATCHES_IMAGE_5, BROWSER_PATCHES_GIVENS_5),
]

#: Zip's numbered dots, real captures, three independent boards.
#:
#: WHY THIS DID NOT EXIST UNTIL 2026-08-27 為什麼直到 2026-08-27 才有這個:
#:   Sudoku and Patches each got their own source reactively, the moment a
#:   real board actually misread a digit (BROWSER_SUDOKU_GIVENS for "3" on
#:   2026-08-08, BROWSER_PATCHES_GIVENS for "8" on 2026-08-25). Zip never had
#:   a failure that loud - its one recorded incident (2026-08-16 log) was a
#:   slow RETRY that still finished correctly, not a wrong answer - so nobody
#:   was forced to go add one, and the earlier digit-sample survey that led to
#:   BROWSER_PATCHES_GIVENS_2 was framed around "find colour variety in
#:   videos" and never specifically checked whether Zip had a source at all.
#:   Meanwhile every Zip number was being classified with templates borrowed
#:   entirely from Sudoku (1-6), Patches (0-9) and system fonts (0, 7) -
#:   never checked against a real Zip dot's OWN rendering.
#: 為什麼直到 2026-08-27 才有這個：Sudoku 跟 Patches 都是「真的有一次棋盤讀錯
#:   數字」才反應式地各自補上一個來源（BROWSER_SUDOKU_GIVENS 補 2026-08-08
#:   的「3」、BROWSER_PATCHES_GIVENS 補 2026-08-25 的「8」）。Zip 從來沒有
#:   吵到那個程度——它唯一一次留下記錄的事故（2026-08-16 的 log）只是重試
#:   多花了時間、最後答案還是對的，不是讀錯——所以沒有人被逼著去補一個；
#:   而更早那次促成 BROWSER_PATCHES_GIVENS_2 的數字樣本調查，出發點是
#:   「找影片裡的顏色變化」，從來沒有專門檢查過 Zip 到底有沒有自己的來源。
#:   於是 Zip 的每一個數字，範本全部是跟 Sudoku（1-6）、Patches（0-9）、
#:   系統字型（0、7）借來的——從來沒有用 Zip 自己圓點畫出來的數字驗證過。
#:
#: PROOF THIS WAS A REAL GAP, NOT JUST A THEORETICAL ONE 這不只是理論上的缺口:
#:   Measured directly on live_zip_browser_2.png before this fix: the "8" at
#:   (1,3) scored 0.9845 against borrowed templates, but runner-up "6" scored
#:   0.9659 - margin 0.0186, under MIN_MARGIN (0.020). classify_glyph
#:   correctly refused to guess (find_dots() reported it as an unread,
#:   single-glyph disc) - the exact same failure shape as
#:   BROWSER_PATCHES_GIVENS's "8 vs 6" case, just on Zip's own widget instead
#:   of Patches'. This was sitting undetected in training-data/ the whole
#:   time because nobody had run find_dots() against these captures before.
#: 這不只是理論上的缺口——2026-08-27 修這個之前，直接在
#:   live_zip_browser_2.png 上量過：(1,3) 的「8」對借來的範本只拿到 0.9845
#:   分，第二名「6」拿到 0.9659 分，差距 0.0186，不到 MIN_MARGIN（0.020）。
#:   classify_glyph 正確地拒絕用猜的（find_dots() 把它回報成讀不出來、
#:   只有一個字形的圓盤）——跟 BROWSER_PATCHES_GIVENS 那次「8 對 6」完全
#:   同一種失敗形狀，只是這次是 Zip 自己的元件，不是 Patches 的。這個缺口
#:   一直沒被發現，純粹是因為在這之前沒有人拿這些截圖真的跑過 find_dots()。
#:
#: Ground truth read by eye from tests/fixtures/live_zip_browser*.png
#: (originally training-data/img/calibration_candidates/zip_raw_*.png,
#: auto-harvested by _harvest_raw_board_capture() on a successful solve -
#: cross-checked against find_dots()'s own auto-detected positions, which
#: matched by eye for every disc except the (1,3) "8" above).
#: 正確答案人工從 tests/fixtures/live_zip_browser*.png 讀出（原始檔案是
#: training-data/img/calibration_candidates/zip_raw_*.png，由
#: _harvest_raw_board_capture() 在成功解出時自動存下）——跟 find_dots()
#: 自己偵測到的位置互相核對過，除了上面 (1,3) 的「8」以外，每一顆都跟人工
#: 讀出的一致。
ZIP_SOURCES = [
    ("live_zip_browser.png", {
        (1, 2): 10, (1, 3): 5, (2, 2): 11, (2, 3): 4,
        (3, 0): 8, (3, 1): 9, (3, 4): 6, (3, 5): 7,
        (4, 0): 1, (4, 1): 12, (4, 4): 3, (4, 5): 2,
    }),
    ("live_zip_browser_2.png", {
        (1, 1): 4, (1, 2): 3, (1, 3): 8, (1, 6): 9,
        (2, 1): 5, (2, 2): 6, (2, 5): 7,
        (3, 1): 1, (4, 6): 2,
        (5, 2): 12, (5, 5): 13, (5, 6): 10,
        (6, 1): 16, (6, 4): 15, (6, 5): 14, (6, 6): 11,
    }),
    ("live_zip_browser_3.png", {
        (0, 3): 13, (0, 4): 1, (0, 5): 3,
        (2, 1): 14, (2, 3): 9, (2, 5): 2,
        (3, 1): 15, (3, 3): 8, (3, 5): 6,
        (4, 1): 12, (4, 3): 7, (4, 5): 5,
        (6, 1): 11, (6, 2): 10, (6, 3): 4,
    }),
]


# --------------------------------------------------------------------------
# Collectors 收集器
# --------------------------------------------------------------------------
#: Every Sudoku image this tool harvests digits from, paired with its own
#: ground truth. A list, not a single image, precisely because one source
#: rendering a digit acceptably does not mean every source does - see
#: BROWSER_SUDOKU_GIVENS's own comment for the real case that proved it.
#: 這支工具會取樣數字的每一張數獨圖片，各自配對自己的正確答案表。用清單
#: 而不是單一張圖，正是因為「某一個來源把某個數字畫得夠像」不代表
#: 每個來源都會——真實發生過的案例見 BROWSER_SUDOKU_GIVENS 自己的註解。
SUDOKU_SOURCES = [
    (SUDOKU_IMAGE, SUDOKU_GIVENS),
    (BROWSER_SUDOKU_IMAGE, BROWSER_SUDOKU_GIVENS),
]


def from_sudoku_cells() -> dict[int, list[np.ndarray]]:
    """Digits printed inside the Sudoku grid, across every known source.
    數獨格子裡印的數字，涵蓋每一個已知的來源。"""
    out: dict[int, list[np.ndarray]] = {}
    for image_name, givens in SUDOKU_SOURCES:
        image = read_image(FIXTURES / image_name)
        if image is None:
            continue
        grid = build_grid(image)
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        for (r, c), digit in givens.items():
            x, y, w, h = grid.cell_boxes[r][c]
            # Inset well inside the cell so grid lines are not read as strokes.
            # 往格子內縮很多，避免把格線讀成筆畫。
            sub = gray[y + int(h * 0.15) : y + int(h * 0.85), x + int(w * 0.15) : x + int(w * 0.85)]
            glyph = normalize_glyph(sub < 128)
            if glyph is not None:
                out.setdefault(digit, []).append(glyph)
    return out


def from_sudoku_keypad() -> dict[int, list[np.ndarray]]:
    """The on-screen number pad below the board. 棋盤下方的數字鍵盤。

    Worth harvesting because it shows all of 1-6 even when the board itself
    never displays some of them.
    值得取樣，因為就算棋盤上沒出現過某些數字，鍵盤上 1-6 一定都有。
    """
    out: dict[int, list[np.ndarray]] = {}
    image = read_image(FIXTURES / SUDOKU_IMAGE)
    if image is None:
        return out
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    h_img, w_img = gray.shape

    # Keypad location as a fraction of the screenshot, measured on the sample.
    # 鍵盤位置，以截圖比例表示；數值是量這張樣本得到的。
    region = gray[int(h_img * 0.685) : int(h_img * 0.845), int(w_img * 0.03) : int(w_img * 0.72)]
    mask = (region < 150).astype(np.uint8)
    num, labels, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)

    boxes = []
    for label in range(1, num):
        x, y, w, h, area = stats[label]
        if area < 300 or h < 25:
            continue
        if not (0.25 <= w / h <= 1.3):  # digit-shaped 數字的長寬比
            continue
        boxes.append((x, y, w, h, label))
    if len(boxes) < 6:
        return out

    # Two rows of three: 1 2 3 / 4 5 6. 兩排各三個：1 2 3 / 4 5 6。
    boxes.sort(key=lambda b: b[1])
    row_height = float(np.median([b[3] for b in boxes]))
    rows: list[list] = []
    for box in boxes:
        if rows and abs(box[1] - rows[-1][0][1]) <= row_height:
            rows[-1].append(box)
        else:
            rows.append([box])

    digit = 1
    for row in rows[:2]:
        row.sort(key=lambda b: b[0])
        for x, y, w, h, label in row[:3]:
            glyph = normalize_glyph(labels[y : y + h, x : x + w] == label)
            if glyph is not None and digit <= 6:
                out.setdefault(digit, []).append(glyph)
            digit += 1
    return out


def from_patches_labels() -> dict[int, list[np.ndarray]]:
    """White digits on the coloured Patches badges, including "12", across
    every known source.
    Patches 彩色標籤上的白色數字，包含兩位數的「12」，涵蓋每一個已知的來源。"""
    out: dict[int, list[np.ndarray]] = {}
    for image_name, givens in PATCHES_SOURCES:
        image = read_image(FIXTURES / image_name)
        if image is None:
            continue
        try:
            grid = build_grid(image)
            labels = patches.find_labels(image, grid)
            # find_labels only locates the badges; read_label_value is what
            # extracts the digit bitmaps onto label.glyphs.
            # find_labels 只負責找到標籤位置；是 read_label_value 才把數字
            # 點陣圖抽出來放進 label.glyphs。
            for label in labels:
                patches.read_label_value(image, label)
        except Exception:
            continue

        for label in labels:
            digit = givens.get((label.row, label.col))
            if digit is None:
                continue
            text = str(digit)
            # Only trust a label whose glyph count matches the expected digit
            # count, otherwise the split was wrong and the pairing would be
            # garbage.
            # 只信任「切出的字形數量」與「預期位數」相符的標籤，
            # 否則就是切錯了，配對起來會是垃圾。
            if len(label.glyphs) != len(text):
                continue
            for glyph, char in zip(label.glyphs, text):
                out.setdefault(int(char), []).append(glyph)
    return out


def from_zip_dots() -> dict[int, list[np.ndarray]]:
    """White digits inside Zip's numbered dots, including two-digit values,
    across every known source.
    Zip 編號圓點裡的白色數字，包含兩位數，涵蓋每一個已知的來源。

    Uses find_dots()'s own debug_masks side-channel (see its docstring) so
    this reuses the SAME extraction the real solver runs, instead of a
    reimplementation that could silently drift out of sync.
    用 find_dots() 自己的 debug_masks 側通道（見它的文件字串），這樣用的是
    求解器實際在跑的「同一套」抽取邏輯，而不是可能悄悄跟正式邏輯不同步的
    另一份重寫。
    """
    out: dict[int, list[np.ndarray]] = {}
    for image_name, givens in ZIP_SOURCES:
        image = read_image(FIXTURES / image_name)
        if image is None:
            continue
        try:
            grid = build_grid(image)
            masks: dict[tuple[int, int], np.ndarray] = {}
            zip_path.find_dots(image, grid, debug_masks=masks)
        except Exception:
            continue

        for pos, digit in givens.items():
            mask = masks.get(pos)
            if mask is None:
                continue
            text = str(digit)
            glyphs = split_digit_glyphs(mask)
            # Same guard as from_patches_labels: only trust a disc whose
            # glyph count matches the expected digit count.
            # 跟 from_patches_labels 一樣的把關：只信任「切出的字形數量」
            # 與「預期位數」相符的圓盤。
            if len(glyphs) != len(text):
                continue
            for glyph, char in zip(glyphs, text):
                out.setdefault(int(char), []).append(glyph)
    return out


def from_fonts() -> dict[int, list[np.ndarray]]:
    """System-font stand-ins for digits no screenshot covers.
    截圖沒涵蓋到的數字，用系統字型補。"""
    out: dict[int, list[np.ndarray]] = {}
    for digit in FALLBACK_DIGITS:
        for font in FALLBACK_FONTS:
            if not Path(font).exists():
                continue
            try:
                glyph = _render_font_glyph(str(digit), font)
            except Exception:
                continue
            if glyph is not None:
                out.setdefault(digit, []).append(glyph)
    return out


# --------------------------------------------------------------------------
# Output 輸出
# --------------------------------------------------------------------------
def pack(glyph: np.ndarray) -> bytes:
    return np.packbits(glyph.astype(np.uint8).reshape(-1)).tobytes()


def dedupe(glyphs: list[np.ndarray]) -> list[np.ndarray]:
    """Drop near-identical glyphs; more copies of the same shape add nothing.
    丟掉幾乎相同的字形；同一個形狀存很多份沒有幫助。"""
    kept: list[np.ndarray] = []
    for glyph in glyphs:
        if all(np.logical_xor(glyph, k).sum() > 8 for k in kept):
            kept.append(glyph)
    return kept


HEADER = '''"""
Auto-generated digit glyph templates, calibrated from real app screenshots.
自動產生的數字字形範本，從實際 App 截圖校準而來。

Do not edit by hand - regenerate with tools/calibrate_digits.py.
不要手動編輯；要更新請重跑 tools/calibrate_digits.py。

Why calibrated templates instead of a system font:
  this app's "5" has an unusually round bowl, and most Windows fonts classify
  it as a "6". Glyphs taken from the app itself match exactly.
為什麼要用校準範本而不是系統字型：
  這個 App 的「5」下半部特別圓，多數 Windows 字型會把它判成「6」。
  直接取自 App 本身的字形才會完全吻合。

Two tables 兩張表:
  APP_TEMPLATES      - captured from the app. Authoritative.
                       取自 App 本身，可信度最高。
  FALLBACK_TEMPLATES - font-rendered stand-ins for digits no capture contains
                       yet (0 and 7). Baked in as bytes rather than rendered at
                       runtime, so the program does not depend on a font file
                       existing on the machine - see the note below.
                       目前還沒有截到的數字（0 與 7）用系統字型算繪的替代品。
                       直接烘焙成位元組而不是執行時算繪，
                       這樣程式就不依賴機器上存在某個字型檔 —— 理由見下。

Why 0 and 7 are baked in rather than rendered on demand 為什麼 0 與 7 要烘焙進來:
  These two were previously rendered from C:/Windows/Fonts at import time. On a
  machine without those fonts the templates were simply absent, and matching
  then picked the closest WRONG digit with high confidence: a "0" scored 0.89 as
  a "6" and a "7" scored 0.76 as a "2" - both far above the acceptance floor.
  A missing font must never turn into a confidently wrong number.
  這兩個數字原本是在 import 時從 C:/Windows/Fonts 算繪出來的。在沒有那些字型的
  機器上，範本就直接不存在，比對於是以高信心挑了最接近的「錯誤」數字：
  「0」以 0.89 被判成「6」、「7」以 0.76 被判成「2」—— 兩者都遠高於接受門檻。
  缺一個字型檔，絕不能變成一個很有信心的錯誤數字。
"""
'''


def emit(name: str, table: dict[int, list[np.ndarray]], comment: list[str]) -> list[str]:
    lines = list(comment)
    lines.append(f"{name}: dict[int, list[bytes]] = {{")
    for digit in sorted(table):
        lines.append(f"    {digit}: [")
        for glyph in dedupe(table[digit]):
            lines.append(f"        {pack(glyph)!r},")
        lines.append("    ],")
    lines.append("}")
    return lines


def main() -> int:
    app: dict[int, list[np.ndarray]] = {}
    for collector in (from_sudoku_cells, from_sudoku_keypad, from_patches_labels, from_zip_dots):
        try:
            part = collector()
        except Exception as exc:
            print(f"  {collector.__name__} failed / 失敗: {exc}")
            continue
        summary = ", ".join(f"{d}x{len(v)}" for d, v in sorted(part.items())) or "(nothing)"
        print(f"  {collector.__name__}: {summary}")
        for digit, glyphs in part.items():
            app.setdefault(digit, []).extend(glyphs)

    fallback = from_fonts()
    print("  from_fonts: " + ", ".join(f"{d}x{len(v)}" for d, v in sorted(fallback.items())))

    covered = set(app) | set(fallback)
    missing = sorted(set(range(10)) - covered)
    if missing:
        # A digit with no template at all is the failure mode this whole file
        # exists to prevent - refuse to write a set that has one.
        # 「某個數字完全沒有範本」正是這整個檔案要避免的失敗模式 ——
        # 缺任何一個就拒絕寫出。
        print(f"\nREFUSING TO WRITE / 拒絕寫出: no template for {missing}.")
        print("A digit with no template is silently misread as another digit.")
        print("缺範本的數字會被默默讀成別的數字。")
        return 1

    lines = [HEADER]
    lines.extend(emit("APP_TEMPLATES", app, []))
    lines.extend(emit("FALLBACK_TEMPLATES", fallback, [
        "",
        "",
        "#: Font-rendered stand-ins for digits not yet captured from the app.",
        "#: Regenerate together with APP_TEMPLATES via tools/calibrate_digits.py.",
        "#: 尚未從 App 截到的數字，用系統字型算繪的替代品。",
        "#: 要更新請跟 APP_TEMPLATES 一起用 tools/calibrate_digits.py 重新產生。",
    ]))

    OUTPUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\nwrote / 已寫出 {OUTPUT}")
    print(f"  from app screenshots / 來自截圖: {sorted(app)}")
    print(f"  from system fonts / 來自系統字型: {sorted(fallback)}")
    print("\nNow re-run the tests / 請重跑測試: python tests/run_all.py")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
