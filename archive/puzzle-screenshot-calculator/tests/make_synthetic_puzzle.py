"""
產生一張合成的 Tango 謎題截圖，用來端對端測試整個 CV + 求解流程
(不需要真實截圖也能驗證幾何切割、顏色分類、符號偵測、求解器有沒有兜起來)。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import cv2
import numpy as np

CELL = 80
N = 6
MARGIN = 20

# 顏色設計要符合 cell_classifier.py 的假設: S>60 才算圖示、V<245 才算 given 灰底
ORANGE = (0, 150, 230)  # BGR, hue ~ 12
BLUE = (200, 120, 30)   # BGR, hue ~ 113
WHITE_BG = (255, 255, 255)
GRAY_BG = (225, 225, 225)  # V ~ 225 < 245 -> given
DARK_MARK = (60, 60, 60)

# 一個手動設計、符合所有 Tango 規則的 6x6 唯一解 (0=moon, 1=sun)
SOLUTION = [
    [1, 1, 0, 0, 1, 0],
    [0, 0, 1, 1, 0, 1],
    [0, 1, 1, 0, 0, 1],
    [1, 0, 0, 1, 1, 0],
    [1, 0, 1, 0, 0, 1],
    [0, 1, 0, 1, 1, 0],
]

# 選幾格當作 given (灰底)
GIVENS = {(0, 0), (0, 4), (2, 2), (3, 3), (4, 5), (5, 1)}

# 選幾個跟 solution 一致的 =/× 邊 (h: 同列相鄰; v: 同欄相鄰)
H_EDGES = {(1, 0): "=", (4, 2): "x"}
V_EDGES = {(0, 1): "x", (3, 0): "="}


def cell_origin(r, c):
    return MARGIN + c * CELL, MARGIN + r * CELL


def draw_puzzle():
    size = MARGIN * 2 + CELL * N
    img = np.full((size, size, 3), WHITE_BG, dtype=np.uint8)

    for r in range(N):
        for c in range(N):
            x, y = cell_origin(r, c)
            bg = GRAY_BG if (r, c) in GIVENS else WHITE_BG
            cv2.rectangle(img, (x, y), (x + CELL, y + CELL), bg, thickness=-1)
            cv2.rectangle(img, (x, y), (x + CELL, y + CELL), (200, 200, 200), thickness=1)

            cx, cy = x + CELL // 2, y + CELL // 2
            color = ORANGE if SOLUTION[r][c] == 1 else BLUE
            cv2.circle(img, (cx, cy), CELL // 4, color, thickness=-1)

    patch = int(CELL * 0.35)
    half = patch // 2

    for (r, c), sym in H_EDGES.items():
        x, y = cell_origin(r, c)
        bx, by = x + CELL, y + CELL // 2
        if sym == "=":
            cv2.line(img, (bx - half, by - 5), (bx + half, by - 5), DARK_MARK, 4)
            cv2.line(img, (bx - half, by + 5), (bx + half, by + 5), DARK_MARK, 4)
        else:
            cv2.line(img, (bx - half, by - half), (bx + half, by + half), DARK_MARK, 4)
            cv2.line(img, (bx - half, by + half), (bx + half, by - half), DARK_MARK, 4)

    for (r, c), sym in V_EDGES.items():
        x, y = cell_origin(r, c)
        bx, by = x + CELL // 2, y + CELL
        if sym == "=":
            cv2.line(img, (bx - half, by - 5), (bx + half, by - 5), DARK_MARK, 4)
            cv2.line(img, (bx - half, by + 5), (bx + half, by + 5), DARK_MARK, 4)
        else:
            cv2.line(img, (bx - half, by - half), (bx + half, by + half), DARK_MARK, 4)
            cv2.line(img, (bx - half, by + half), (bx + half, by - half), DARK_MARK, 4)

    return img


if __name__ == "__main__":
    from img_io import imwrite_unicode

    out_path = Path(__file__).with_name("synthetic_puzzle.png")
    img = draw_puzzle()
    ok = imwrite_unicode(out_path, img)
    print(f"Saved ({ok}): {out_path}")
