"""
Work out which of the five puzzles a screenshot shows.
判斷截圖是五款謎題中的哪一種。

Why not read the page title 為什麼不讀網頁標題:
  that would need text OCR and would break whenever the user switches the site
  language. Colour/structure statistics of the board itself are language-neutral.
  讀標題要做文字 OCR，而且使用者一換網站語言就失效。改用棋盤本身的
  顏色與結構統計，跟語言完全無關。

Discriminators, in the order they are applied:
判斷順序與依據：

  Queens  every cell is a filled colour block  -> corner-of-cell non-white ~1.0
  Zip     white board + thick black walls/dots -> high dark-pixel ratio
  Sudoku  white board + thin black digits      -> almost no colour, low dark
  Tango   white board + orange suns/blue moons -> coloured pixels are all orange/blue
  Patches white board + multi-colour labels    -> coloured pixels are varied

  Queens  每格都被實色色塊填滿  -> 取格子角落，非白比例接近 1.0
  Zip     白底 + 粗黑牆與圓點   -> 深色像素比例高
  Sudoku  白底 + 黑色細數字     -> 幾乎沒有彩色，深色比例也低
  Tango   白底 + 橘色太陽藍色月亮 -> 彩色像素幾乎全是橘或藍
  Patches 白底 + 多色標籤       -> 彩色像素顏色很雜

KEY POINT - sample cell *corners*, not centres:
  a fully-filled Tango board has an icon in the middle of every cell, so a
  centre sample would look exactly like Queens. Corners stay white.
  Measured: Queens 1.00 on all boards; everything else <= 0.23.
關鍵 —— 取格子「角落」而不是「中央」：
  Tango 全部填滿時每格中央都有圖示，用中央取樣會跟 Queens 一模一樣；角落仍是白底。
  實測：Queens 全部 1.00，其他各種謎題都 <= 0.23。
"""

from __future__ import annotations

import cv2
import numpy as np

from . import board as board_mod

#: Corner-of-cell non-white ratio above this means every cell is filled -> Queens.
#: 格子角落非白比例超過此值，代表整盤都是實色色塊 -> Queens。
QUEENS_FILLED_CELL_RATIO = 0.8
#: Dark-pixel ratio above this means thick black walls / dots -> Zip.
#: 深色像素比例超過此值，代表有粗黑牆與黑色圓點 -> Zip。
ZIP_DARK_RATIO = 0.05
#: Below this coloured ratio the board has no colour content at all -> Sudoku.
#: 彩色像素比例低於此值代表盤面沒有彩色內容 -> Sudoku。
#:
#: MEASURED 量測依據: the only live Mini Sudoku fixture on file
#: (live_mini_sudoku_browser.png) measures 0.00366 - and if its ratio ever
#: crossed the OLD 0.006 threshold, it would have fallen straight into the
#: Tango branch, because its own colour content (the sub-box shading) is
#: 88.7% orange/blue - comfortably over TANGO_HUE_RATIO. That is not a
#: hypothetical: two real 2026-08-10 production runs (run_20260810_181407 and
#: run_20260810_185005) show detect_type guessing "tango" for a board that
#: only resolved as sudoku several seconds later via the fallback sweep,
#: costing ~6-9s per occurrence while the real board sat on screen the whole
#: time. 0.006 gave the fixture only a 1.6x margin - thin enough that
#: ordinary capture variance (zoom, DPI scaling, anti-aliasing) could tip it
#: over. Raised to 0.01: ~2.7x margin above the measured sudoku value, and
#: still a ~2.6x margin below the smallest CORRECTLY-located non-sudoku
#: fixture (S__104316931.jpg, tango, 0.02559) - see
#: test_puzzle_type_detection and test_mini_sudoku_survives_extra_colour_noise.
#: This only changes which type is TRIED FIRST; every module still requires
#: its own unique-solution / sanity guard, so a wrong guess still fails
#: cleanly rather than inventing an answer - raising this is a speed fix,
#: not a loosened correctness gate.
#: 實測依據：目前唯一的真實瀏覽器 Mini Sudoku 測試圖
#: （live_mini_sudoku_browser.png）量到 0.00366——而它自己的彩色內容
#: （子九宮格底色）有 88.7% 落在橘／藍色相，一旦超過舊門檻 0.006 就會直接
#: 掉進 Tango 分支。這不是空想：兩筆 2026-08-10 的真實執行記錄
#: （run_20260810_181407 與 run_20260810_185005）都顯示 detect_type 把
#: Sudoku 猜成 tango，要等備援全掃過一輪、好幾秒後才靠備援機制解成
#: sudoku——每次白燒 6~9 秒，而真正的棋盤其實整段時間都在畫面上。
#: 0.006 只給這張測試圖 1.6 倍安全邊界——薄到一般擷取誤差（縮放、DPI、
#: 反鋸齒）就可能跨過去。提高到 0.01 後：量到的 sudoku 數值上方有約 2.7 倍
#: 邊界，下方離「正確定位到棋盤」的非 sudoku 測試圖裡最小值
#: （S__104316931.jpg，tango，0.02559）還有約 2.6 倍邊界——見
#: test_puzzle_type_detection 與 test_mini_sudoku_survives_extra_colour_noise。
#: 這裡只影響「先試哪個類型」，每個模組仍然各自要求解唯一／合理性守門，
#: 猜錯一樣會乾淨地失敗而不是編答案——這是速度修正，不是放寬正確性門檻。
NO_COLOR_RATIO = 0.01
#: Fraction of coloured pixels that must be orange-or-blue to be Tango.
#: 彩色像素中「橘或藍」要佔多少才算 Tango。
TANGO_HUE_RATIO = 0.75


def _board_roi(image: np.ndarray) -> np.ndarray:
    """The board region, or the whole image if it cannot be located.
    棋盤區域；定位不到就用整張圖。"""
    bbox = board_mod.find_board_bbox(image)
    if bbox is None:
        found = board_mod.find_board_by_grid_lines(image)
        bbox = found[0] if found else None
    if bbox is None:
        return image
    x, y, w, h = bbox
    height, width = image.shape[:2]
    return image[max(0, y) : min(height, y + h), max(0, x) : min(width, x + w)]


def _filled_cell_ratio(roi: np.ndarray) -> float:
    """Fraction of cells whose *corner* is not white.
    格子「角落」不是白色的比例。"""
    n = board_mod.detect_grid_size(roi)
    if not n:
        return 0.0
    height, width = roi.shape[:2]
    cell_w, cell_h = width / n, height / n
    filled = total = 0
    for r in range(n):
        for c in range(n):
            x0, y0 = int(c * cell_w + cell_w * 0.10), int(r * cell_h + cell_h * 0.10)
            x1, y1 = int(c * cell_w + cell_w * 0.26), int(r * cell_h + cell_h * 0.26)
            patch = roi[max(0, y0) : y1, max(0, x0) : x1]
            if patch.size == 0:
                continue
            total += 1
            if np.median(patch.reshape(-1, 3), axis=0).min() < 240:
                filled += 1
    return filled / total if total else 0.0


def detect_type(image: np.ndarray) -> str:
    """Return one of: queens / zip / sudoku / tango / patches.
    回傳 queens / zip / sudoku / tango / patches 其中之一。"""
    roi = _board_roi(image)
    hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
    gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)

    # Queens must be checked first: it also has plenty of dark pixels (thick
    # black grid lines), so a dark-ratio test would misfile it as Zip.
    # Queens 要先判斷：它同時也有不少深色像素（粗黑格線），
    # 先檢查深色比例會被誤判成 Zip。
    if _filled_cell_ratio(roi) >= QUEENS_FILLED_CELL_RATIO:
        return "queens"

    if float((gray < 90).mean()) > ZIP_DARK_RATIO:
        # Zip's walls and dots. Checked before tango/patches because a Zip board
        # with the path already drawn also has a high coloured ratio.
        # Zip 的牆與圓點。要在 tango/patches 之前判斷，因為已經畫了路徑的
        # Zip 盤面彩色比例也會很高。
        return "zip"

    colored = (hsv[:, :, 1] > 70) & (hsv[:, :, 2] > 60)
    if float(colored.mean()) < NO_COLOR_RATIO:
        return "sudoku"

    hue = hsv[:, :, 0][colored]
    if hue.size:
        orange = ((hue >= 8) & (hue <= 30)).mean()
        blue = ((hue >= 95) & (hue <= 125)).mean()
        if orange + blue >= TANGO_HUE_RATIO:
            return "tango"
    return "patches"
