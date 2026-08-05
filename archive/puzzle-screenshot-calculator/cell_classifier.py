"""
辨識每一格的內容：
  - icon: "sun" (橘色圓圈) / "moon" (藍色月亮) / None (空白，玩家還沒填)
  - given: True (灰底，題目給定不可更改) / False (白底，可填)

作法：
  - 用 HSV 的飽和度(S) 把「有顏色的圖示像素」跟「中性背景(白/灰)像素」分開。
  - 圖示像素中，橘色與藍色的色相(H)範圍不同，用來判斷 sun / moon。
  - 背景像素的亮度(V) 用來判斷是白底還是灰底 (灰底通常比白底暗一些)。

下面的門檻值是先給合理預設，之後要用真實截圖(calibrate.py)校準。
"""

from dataclasses import dataclass
from enum import Enum

import cv2
import numpy as np

# --- 可調整的門檻值 (用 calibrate.py 對照真實截圖調整) ---
SATURATION_ICON_THRESHOLD = 60      # S 值高於此視為「有顏色的圖示像素」
ICON_MIN_PIXEL_RATIO = 0.05         # 圖示像素至少要佔格子面積這個比例，否則視為空白
ORANGE_HUE_RANGE = (5, 35)          # OpenCV Hue 0-179
BLUE_HUE_RANGE = (95, 135)
GIVEN_BG_VALUE_MAX = 253            # 背景 V 值低於此判斷為「灰底 (given)」(實測 given 淡紫底 V≈248, 白底 V=255)
CELL_MARGIN_RATIO = 0.08            # 裁切格子時內縮比例，避免格線/相鄰格污染


class Symbol(Enum):
    SUN = "sun"
    MOON = "moon"
    EMPTY = None


@dataclass
class CellReading:
    symbol: str | None  # "sun" / "moon" / None
    given: bool
    mean_hue: float | None
    bg_value: float


def _crop_with_margin(image: np.ndarray, box: tuple[int, int, int, int], margin_ratio: float) -> np.ndarray:
    x, y, w, h = box
    mx, my = int(w * margin_ratio), int(h * margin_ratio)
    return image[y + my : y + h - my, x + mx : x + w - mx]


def read_cell(image: np.ndarray, box: tuple[int, int, int, int]) -> CellReading:
    cell = _crop_with_margin(image, box, CELL_MARGIN_RATIO)
    if cell.size == 0:
        return CellReading(symbol=None, given=False, mean_hue=None, bg_value=255.0)

    hsv = cv2.cvtColor(cell, cv2.COLOR_BGR2HSV)
    h_ch, s_ch, v_ch = hsv[:, :, 0], hsv[:, :, 1], hsv[:, :, 2]

    icon_mask = s_ch > SATURATION_ICON_THRESHOLD
    icon_ratio = icon_mask.mean()

    bg_mask = ~icon_mask
    # 用中位數而非平均數：邊界上的 =/× 符號有時會侵入格子邊緣的裁切區域，
    # 平均數容易被少數暗色雜訊像素拉低，中位數比較穩定。
    bg_value = float(np.median(v_ch[bg_mask])) if bg_mask.any() else float(np.median(v_ch))
    given = bg_value < GIVEN_BG_VALUE_MAX

    if icon_ratio < ICON_MIN_PIXEL_RATIO:
        return CellReading(symbol=None, given=given, mean_hue=None, bg_value=bg_value)

    mean_hue = float(h_ch[icon_mask].mean())
    lo, hi = ORANGE_HUE_RANGE
    if lo <= mean_hue <= hi:
        symbol = "sun"
    else:
        lo2, hi2 = BLUE_HUE_RANGE
        if lo2 <= mean_hue <= hi2:
            symbol = "moon"
        else:
            # 落在未預期範圍，用離兩個中心色相較近的一個決定，並在呼叫端可用 mean_hue debug
            orange_center = sum(ORANGE_HUE_RANGE) / 2
            blue_center = sum(BLUE_HUE_RANGE) / 2
            symbol = "sun" if abs(mean_hue - orange_center) < abs(mean_hue - blue_center) else "moon"

    return CellReading(symbol=symbol, given=given, mean_hue=mean_hue, bg_value=bg_value)


def read_all_cells(image: np.ndarray, cell_boxes: list[list[tuple[int, int, int, int]]]) -> list[list[CellReading]]:
    return [[read_cell(image, box) for box in row] for row in cell_boxes]
