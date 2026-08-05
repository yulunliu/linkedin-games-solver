"""
判斷截圖是哪一種謎題。

既有專案的 registry.detect_type 是用「彩色像素比例」來認 Queens：
整盤都是彩色 -> Queens。但實測遇到**淡色系的 Queens 盤面**(大量淺灰、
米色色塊)，彩度低到判定失敗，被誤認成 Patches，然後用 Patches 的邏輯
「解」出一個毫無意義的答案卻回報成功 —— 這比直接失敗更糟。

這裡改用更本質的特徵：

  Queens  每一格都被實色色塊填滿    -> 取每格「角落」的顏色，非白比例接近 1
  Zip     白底 + 粗黑牆與黑色圓點   -> 深色像素比例高
  Sudoku  白底 + 黑色細數字         -> 幾乎沒有彩色，深色比例也低
  Tango   白底 + 橘色太陽/藍色月亮  -> 彩色像素幾乎全是橘或藍
  Patches 白底 + 多色標籤           -> 彩色像素顏色很雜

取「角落」而不是「中央」很重要：Tango 全部填滿時每格中央都有圖示，
用中央取樣會誤判成 Queens；角落則仍然是白底。
實測角落非白比例：Queens 1.00、其他各種謎題都 <= 0.23。
"""

import cv2
import numpy as np

import solver_bridge  # noqa: F401  匯入時會把 tango_solver 加進 sys.path

import board  # noqa: E402
import grid_detector  # noqa: E402

#: 每格角落非白比例超過此值 -> 整盤都是實色色塊 -> Queens
QUEENS_FILLED_CELL_RATIO = 0.8
#: 深色像素比例超過此值 -> 有粗黑牆/黑色圓點 -> Zip
ZIP_DARK_RATIO = 0.05
#: 彩色像素比例低於此值 -> 盤面沒有彩色內容 -> Sudoku
NO_COLOR_RATIO = 0.006
#: 彩色像素中「橘或藍」佔的比例超過此值 -> 只有太陽與月亮 -> Tango
TANGO_HUE_RATIO = 0.75


def _board_roi(image: np.ndarray):
    bbox = board.find_board_bbox(image)
    if bbox is None:
        try:
            bbox = grid_detector.detect_board_bbox_by_content(image, 6)
        except Exception:
            bbox = None
    if bbox is None:
        return image, None
    x, y, w, h = bbox
    h_img, w_img = image.shape[:2]
    return image[max(0, y) : min(h_img, y + h), max(0, x) : min(w_img, x + w)], bbox


def _filled_cell_ratio(roi: np.ndarray) -> float:
    """每格「角落」不是白色的比例。整盤實色色塊 (Queens) 會接近 1。"""
    n = board.detect_grid_size(roi)
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
    roi, _bbox = _board_roi(image)
    hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
    gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)

    # Queens 要先判斷：它同時也有不少深色像素 (粗黑格線)，
    # 先檢查深色會被誤判成 Zip。
    if _filled_cell_ratio(roi) >= QUEENS_FILLED_CELL_RATIO:
        return "queens"

    dark_ratio = float((gray < 90).mean())
    if dark_ratio > ZIP_DARK_RATIO:
        # Zip 的粗黑牆與黑色圓點；已經畫了藍色路徑時彩色比例也會變高，
        # 所以要在 tango/patches 之前判斷。
        return "zip"

    colored = (hsv[:, :, 1] > 70) & (hsv[:, :, 2] > 60)
    colored_ratio = float(colored.mean())
    if colored_ratio < NO_COLOR_RATIO:
        return "sudoku"

    hue = hsv[:, :, 0][colored]
    if hue.size:
        orange = ((hue >= 8) & (hue <= 30)).mean()
        blue = ((hue >= 95) & (hue <= 125)).mean()
        if orange + blue >= TANGO_HUE_RATIO:
            return "tango"
    return "patches"
