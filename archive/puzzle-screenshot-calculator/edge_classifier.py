"""
偵測相鄰兩格之間有沒有 "=" 或 "×" 關係符號小徽章。

符號通常畫在兩格交界處中間的一個小圓形/小方形徽章裡：
  - 水平相鄰 (r,c)-(r,c+1): 徽章大約在該列的垂直中線、兩格交界的 x 座標上
  - 垂直相鄰 (r,c)-(r+1,c): 徽章大約在該欄的水平中線、兩格交界的 y 座標上

分類邏輯 (不需要事先準備範本圖):
  1. 用 HSV 的 V (亮度) 通道二值化該小區域，找出深色線條(前景)的輪廓。
     注意：實測發現符號本身是「棕色」(跟太陽圖示同色系、飽和度也不低)，
     不是中性灰/黑；但它比背景暗很多、也比太陽/月亮圖示暗很多
     (背景 V≈248~255、圖示 V≈233~234、符號 V≈148)，所以改用「V 值比背景
     暗超過一個門檻」來判斷符號前景，不能單純用飽和度篩掉「彩色」像素
     (那樣會把符號本身也濾掉)。
  2. 濾掉「棋盤格線本身」的輪廓：格線是一條貫穿整個裁切區域、很細的直線，
     方向與兩格的排列方向垂直 (水平相鄰格之間的格線是「豎線」貫穿整個裁切
     區域的高度；垂直相鄰格之間的格線是「橫線」貫穿整個裁切區域的寬度)。
     這種貫穿裁切區域且很細的輪廓不算符號，濾掉後才判斷剩下的輪廓。
  3. 前景面積太小 -> 沒有符號 (None)。
  4. 看剩下輪廓的長寬比:
       "=" 是兩條扁平的橫槓 -> 輪廓寬度明顯大於高度 (w/h 大)
       "×" 是交叉的兩條斜線 -> 輪廓接近正方形 (w ≈ h)，因為兩條線在中心相交
"""

from dataclasses import dataclass
from typing import Literal

import cv2
import numpy as np

PATCH_SIZE_RATIO = 0.3  # 徽章裁切區域邊長，相對於格子寬/高的比例
FOREGROUND_MIN_AREA_RATIO = 0.03  # 前景面積至少要佔裁切區域這個比例，否則視為無符號
EQUAL_ASPECT_RATIO_THRESHOLD = 1.8  # w/h 或 h/w 超過此值視為扁平橫槓 (=)
GRIDLINE_SPAN_RATIO = 0.75  # 輪廓跨越裁切區域某方向達此比例，視為貫穿的格線
GRIDLINE_THICKNESS_RATIO = 0.3  # 且另一方向的寬度在此比例以下，才判定為格線(而非符號)
SYMBOL_DARKNESS_MARGIN = 40  # 像素亮度需比背景暗這麼多，才算符號前景 (避免雜訊/格線殘影誤判)

Orientation = Literal["h", "v"]


@dataclass
class EdgeMark:
    symbol: str | None  # "=" / "x" / None


def _square_patch(image: np.ndarray, cx: int, cy: int, size: int) -> np.ndarray:
    half = size // 2
    h, w = image.shape[:2]
    x0, y0 = max(0, cx - half), max(0, cy - half)
    x1, y1 = min(w, cx + half), min(h, cy + half)
    return image[y0:y1, x0:x1]


def _is_gridline_contour(w: int, h: int, patch_w: int, patch_h: int, orientation: Orientation) -> bool:
    if orientation == "h":
        # 水平相鄰格之間的格線是貫穿裁切區域高度的細「豎線」
        return h >= patch_h * GRIDLINE_SPAN_RATIO and w <= patch_w * GRIDLINE_THICKNESS_RATIO
    else:
        # 垂直相鄰格之間的格線是貫穿裁切區域寬度的細「橫線」
        return w >= patch_w * GRIDLINE_SPAN_RATIO and h <= patch_h * GRIDLINE_THICKNESS_RATIO


def _is_centered(x: int, y: int, w: int, h: int, patch_w: int, patch_h: int) -> bool:
    cx, cy = x + w / 2, y + h / 2
    return abs(cx - patch_w / 2) <= patch_w * 0.15 and abs(cy - patch_h / 2) <= patch_h * 0.15


def _classify_patch(patch: np.ndarray, orientation: Orientation) -> str | None:
    if patch.size == 0:
        return None
    patch_h, patch_w = patch.shape[:2]
    hsv = cv2.cvtColor(patch, cv2.COLOR_BGR2HSV)
    v_channel = hsv[:, :, 2]

    # 不用 Otsu：Otsu 在幾乎全一色、沒有真正符號的裁切區塊上也會硬找出一個切點，
    # 導致雜訊或格線殘影被誤判成符號。改用「明顯比背景暗」的絕對門檻：
    # 先估計這塊區域的背景亮度 (中位數，對少數符號前景像素不敏感)，
    # 只有比背景暗超過 SYMBOL_DARKNESS_MARGIN 的像素才算符號前景。
    # 用 V (亮度) 而不是灰階亮度：飽和色的灰階亮度 (加權平均) 可能偏低而被誤判，
    # 但 V=max(R,G,B) 對太陽/月亮這種鮮豔亮色仍然維持很高的值，能跟真正較暗的
    # 符號筆畫區分開。
    bg_estimate = float(np.median(v_channel))
    dark_threshold = bg_estimate - SYMBOL_DARKNESS_MARGIN
    _, binary = cv2.threshold(v_channel, dark_threshold, 255, cv2.THRESH_BINARY_INV)

    # 棋盤格線本身通常只有 1px 左右寬，"=" 符號的兩條橫槓則比較粗。
    # 用開運算(先侵蝕再膨脹)把細格線殘影侵蝕掉，避免它把 "=" 的兩條槓橋接成一塊。
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
    binary = cv2.morphologyEx(binary, cv2.MORPH_OPEN, kernel)

    total_area = patch_w * patch_h
    contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    boxes = [cv2.boundingRect(c) for c in contours if cv2.contourArea(c) > total_area * 0.01]

    if not boxes:
        return None

    # 只有「單一輪廓、形狀像貫穿整個裁切區域的細線、且剛好在正中央」才判定為純格線 (無符號)。
    # "=" 符號的兩條槓雖然也可能很寬很扁，但一定有兩條、且都偏離正中央，不會落入這個情況。
    if len(boxes) == 1:
        x, y, w, h = boxes[0]
        if _is_gridline_contour(w, h, patch_w, patch_h, orientation) and _is_centered(x, y, w, h, patch_w, patch_h):
            return None

    fg_area = sum(w * h for _, _, w, h in boxes)
    if fg_area < total_area * FOREGROUND_MIN_AREA_RATIO:
        return None

    ratios = [max(w / h, h / w) for _, _, w, h in boxes if h > 0]
    if not ratios:
        return None
    avg_ratio = sum(ratios) / len(ratios)
    return "=" if avg_ratio >= EQUAL_ASPECT_RATIO_THRESHOLD else "x"


def detect_h_edges(
    image: np.ndarray, cell_boxes: list[list[tuple[int, int, int, int]]]
) -> dict[tuple[int, int], str]:
    n_rows = len(cell_boxes)
    n_cols = len(cell_boxes[0])
    edges = {}
    for r in range(n_rows):
        for c in range(n_cols - 1):
            x, y, w, h = cell_boxes[r][c]
            x2, _, w2, _ = cell_boxes[r][c + 1]
            cx = x + w  # 交界處 (約等於 x2)
            cy = y + h // 2
            size = int(min(w, w2) * PATCH_SIZE_RATIO) or 1
            patch = _square_patch(image, cx, cy, max(size, 8))
            symbol = _classify_patch(patch, orientation="h")
            if symbol:
                edges[(r, c)] = symbol
    return edges


def detect_v_edges(
    image: np.ndarray, cell_boxes: list[list[tuple[int, int, int, int]]]
) -> dict[tuple[int, int], str]:
    n_rows = len(cell_boxes)
    n_cols = len(cell_boxes[0])
    edges = {}
    for r in range(n_rows - 1):
        for c in range(n_cols):
            x, y, w, h = cell_boxes[r][c]
            _, y2, _, h2 = cell_boxes[r + 1][c]
            cx = x + w // 2
            cy = y + h  # 交界處 (約等於 y2)
            size = int(min(h, h2) * PATCH_SIZE_RATIO) or 1
            patch = _square_patch(image, cx, cy, max(size, 8))
            symbol = _classify_patch(patch, orientation="v")
            if symbol:
                edges[(r, c)] = symbol
    return edges
