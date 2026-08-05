"""
謎題類型註冊表 + 自動判斷截圖屬於哪一種謎題。

自動判斷是用整個棋盤區域的顏色統計，而不是去讀標題文字 (讀文字要 OCR 中英文，
又容易受語言設定影響)。各謎題的畫面特徵差異很明顯：

  Queens   整個盤面都是彩色色塊     -> 彩色像素比例極高 (~0.74)
  Zip      白底 + 粗黑牆與黑色圓點  -> 深色像素比例高 (~0.11)、幾乎沒有彩色
  Sudoku   白底 + 黑色細數字        -> 幾乎沒有彩色、深色比例也低 (~0.01)
  Tango    白底 + 橘色太陽/藍色月亮 -> 少量彩色，而且只有 2 種顏色
  Patches  白底 + 多色標籤          -> 少量彩色，但有很多種不同顏色
"""

import cv2
import numpy as np

import puzzle_patches
import puzzle_queens
import puzzle_sudoku
import puzzle_tango
import puzzle_zip
from board import find_board_bbox

PUZZLES = {
    "tango": puzzle_tango,
    "queens": puzzle_queens,
    "sudoku": puzzle_sudoku,
    "zip": puzzle_zip,
    "patches": puzzle_patches,
}

DISPLAY_ORDER = ["tango", "queens", "sudoku", "zip", "patches"]


def _board_roi(image: np.ndarray) -> np.ndarray:
    bbox = find_board_bbox(image)
    if bbox is None:
        # Tango 的棋盤沒有外框，退而取畫面中央偏上的區域做統計就夠判斷了
        import grid_detector

        bbox = grid_detector.detect_board_bbox_by_content(image, 6)
    if bbox is None:
        return image
    x, y, w, h = bbox
    h_img, w_img = image.shape[:2]
    x, y = max(0, x), max(0, y)
    return image[y : min(h_img, y + h), x : min(w_img, x + w)]


def _count_distinct_colors(roi: np.ndarray, colored_mask: np.ndarray, tolerance: int = 34) -> int:
    num, labels, stats, _ = cv2.connectedComponentsWithStats(colored_mask.astype(np.uint8), connectivity=8)
    min_area = max(60, int(colored_mask.size * 0.0004))
    palette: list[np.ndarray] = []
    for i in range(1, num):
        if stats[i][4] < min_area:
            continue
        pixels = roi[labels == i]
        if len(pixels) == 0:
            continue
        color = np.median(pixels, axis=0)
        if all(np.abs(color - known).max() > tolerance for known in palette):
            palette.append(color)
    return len(palette)


def detect_type(image: np.ndarray) -> str:
    roi = _board_roi(image)
    hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
    gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
    sat, val = hsv[:, :, 1], hsv[:, :, 2]

    colored = (sat > 70) & (val > 60)
    colored_fraction = float(colored.mean())
    dark_fraction = float((gray < 90).mean())

    if colored_fraction > 0.4:
        return "queens"
    if colored_fraction < 0.006:
        return "zip" if dark_fraction > 0.05 else "sudoku"
    return "tango" if _count_distinct_colors(roi, colored) <= 3 else "patches"
