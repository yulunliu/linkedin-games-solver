"""
在「整張螢幕截圖」裡自動找出謎題棋盤的位置。

為什麼需要這支模組：
既有專案的 `board.find_board_bbox` 是設計給「已經大致裁切好的截圖」用的，
它要求棋盤面積至少佔畫面 15%。但整個 1920x1080 螢幕裡，棋盤大概只佔 8%
(瀏覽器工具列、書籤列、LinkedIn 導覽列、遊戲卡片、說明文字都算進去)，
所以直接丟整張螢幕會找不到。

這裡用比較寬鬆的條件先挑出「可能是棋盤」的方形區域，再逐一用既有專案的
格線偵測去驗證，驗證得過的才是真正的棋盤。這樣使用者完全不用自己框選或
設定座標，只要謎題有顯示在畫面上就能自動定位。
"""

from dataclasses import dataclass

import cv2
import numpy as np

import solver_bridge  # noqa: F401  匯入時會把 tango_solver 加進 sys.path

import board  # noqa: E402
import grid_detector  # noqa: E402

#: 候選方形區域的面積佔整張畫面的比例範圍
MIN_AREA_RATIO = 0.003
MAX_AREA_RATIO = 0.45
#: 棋盤在畫面上的最小邊長 (太小的方形多半是圖示、按鈕)
MIN_SIDE_PIXELS = 140
#: 裁切時往外多留的比例，避免把棋盤最外圈的格線切掉
CROP_PAD_RATIO = 0.06


@dataclass
class BoardRegion:
    x: int
    y: int
    w: int
    h: int
    grid_size: int | None = None

    def as_tuple(self) -> tuple[int, int, int, int]:
        return self.x, self.y, self.w, self.h


def _square_candidates(image: np.ndarray) -> list[tuple[int, int, int, int]]:
    h_img, w_img = image.shape[:2]
    image_area = h_img * w_img

    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    edges = cv2.Canny(blurred, 30, 100)
    edges = cv2.dilate(edges, np.ones((3, 3), np.uint8), iterations=2)
    contours, _ = cv2.findContours(edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)

    seen: set[tuple[int, int, int, int]] = set()
    candidates = []
    for cnt in contours:
        x, y, w, h = cv2.boundingRect(cnt)
        if w < MIN_SIDE_PIXELS or h < MIN_SIDE_PIXELS:
            continue
        aspect = w / h
        if not (0.85 <= aspect <= 1.18):
            continue
        ratio = (w * h) / image_area
        if not (MIN_AREA_RATIO <= ratio <= MAX_AREA_RATIO):
            continue
        # 位置相近的重複輪廓只留一個
        key = (x // 12, y // 12, w // 12, h // 12)
        if key in seen:
            continue
        seen.add(key)
        candidates.append((x, y, w, h))

    # 大的先試：棋盤通常是畫面上最大的方形內容
    candidates.sort(key=lambda b: b[2] * b[3], reverse=True)
    return candidates


def _crop_with_pad(image: np.ndarray, box: tuple[int, int, int, int]) -> tuple[np.ndarray, tuple[int, int]]:
    h_img, w_img = image.shape[:2]
    x, y, w, h = box
    pad = int(max(w, h) * CROP_PAD_RATIO)
    x0, y0 = max(0, x - pad), max(0, y - pad)
    x1, y1 = min(w_img, x + w + pad), min(h_img, y + h + pad)
    return image[y0:y1, x0:x1], (x0, y0)


#: 驗證時嘗試的放大倍率。網頁上的棋盤比手機截圖小很多，
#: 淡色邊框 (Patches 的虛線) 與小圖示 (Tango 的太陽月亮) 在原尺寸可能偵測不到，
#: 放大後才抓得到。
_VALIDATE_SCALES = (1.0, 1.75, 2.5)


def _validate_once(crop: np.ndarray) -> int | None:
    try:
        bbox = board.find_board_bbox(crop)
        if bbox is not None:
            x, y, w, h = bbox
            n = board.detect_grid_size(crop[y : y + h, x : x + w])
            if n:
                return n
    except Exception:
        pass
    try:
        # Tango 的棋盤沒有外框，改用內容定位法確認
        if grid_detector.detect_board_bbox_by_content(crop, 6) is not None:
            return 6
    except Exception:
        pass
    return None


def _validate(crop: np.ndarray) -> int | None:
    """確認這塊裁切區域裡真的有棋盤，回傳格數；不是棋盤則回傳 None。"""
    if crop.size == 0 or min(crop.shape[:2]) < MIN_SIDE_PIXELS:
        return None
    for scale in _VALIDATE_SCALES:
        candidate = (
            crop if scale == 1.0
            else cv2.resize(crop, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
        )
        n = _validate_once(candidate)
        if n is not None:
            return n
    return None


def find_board_region(image: np.ndarray) -> BoardRegion | None:
    """
    在整張畫面裡找出包含棋盤的區域。
    回傳的是「可以直接丟給辨識流程的裁切範圍」(比棋盤稍大一點)。
    """
    for box in _square_candidates(image):
        crop, (ox, oy) = _crop_with_pad(image, box)
        n = _validate(crop)
        if n is not None:
            return BoardRegion(x=ox, y=oy, w=crop.shape[1], h=crop.shape[0], grid_size=n)
    return None
