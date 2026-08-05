"""
共用的棋盤幾何偵測：從手機截圖中找出棋盤範圍、推算格數、切出每格座標。

LinkedIn 這幾款謎題 App (Tango / Queens / Mini Sudoku / Zip / Patches) 的畫面
結構很類似：整張截圖包含狀態列、標題列、棋盤、按鈕、說明文字，棋盤本身是一個
明顯的正方形區域，內部由格線分隔成 N x N。

不同謎題的格線深淺差很多 (Queens 是粗黑線、Sudoku 是灰線、Zip 是細灰線、
Patches 是很淡的虛線)，所以格線偵測會嘗試多組亮度門檻，挑出「線條數量合理且
間距均勻」的那一組來推算 N。
"""

from dataclasses import dataclass

import cv2
import numpy as np


@dataclass
class BoardGrid:
    n: int
    board_bbox: tuple[int, int, int, int]  # x, y, w, h (原圖座標)
    cell_boxes: list[list[tuple[int, int, int, int]]]  # [row][col] -> x, y, w, h

    def cell_center(self, r: int, c: int) -> tuple[int, int]:
        x, y, w, h = self.cell_boxes[r][c]
        return x + w // 2, y + h // 2


def cluster_positions(positions: list[float], tol: float) -> list[float]:
    """把接近的座標合併成一個代表值 (同一條線可能有好幾個像素寬)。"""
    if not positions:
        return []
    positions = sorted(positions)
    clusters = [[positions[0]]]
    for p in positions[1:]:
        if p - clusters[-1][-1] <= tol:
            clusters[-1].append(p)
        else:
            clusters.append([p])
    return [sum(c) / len(c) for c in clusters]


def find_board_bbox(image: np.ndarray) -> tuple[int, int, int, int] | None:
    """找出畫面中最大的近似正方形輪廓當作棋盤外框，找不到回傳 None。"""
    h, w = image.shape[:2]
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    edges = cv2.Canny(blurred, 30, 100)
    edges = cv2.dilate(edges, np.ones((3, 3), np.uint8), iterations=2)

    contours, _ = cv2.findContours(edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    best, best_area = None, 0
    image_area = h * w
    for cnt in contours:
        x, y, cw, ch = cv2.boundingRect(cnt)
        area = cw * ch
        if area < image_area * 0.15:
            continue
        aspect = cw / ch if ch else 0
        if not (0.9 <= aspect <= 1.1):
            continue
        if area > best_area:
            best_area, best = area, (x, y, cw, ch)
    return best


def _line_positions(gray: np.ndarray, axis: int, threshold: int, min_fraction: float) -> list[float]:
    """找出整行/整列大多是暗像素的位置 (也就是格線)。axis=0 找垂直線, axis=1 找水平線。"""
    dark_fraction = (gray < threshold).mean(axis=1 - axis)
    raw = [float(i) for i, v in enumerate(dark_fraction) if v > min_fraction]
    return cluster_positions(raw, tol=max(4.0, gray.shape[0] * 0.01))


def _is_evenly_spaced(positions: list[float], tolerance: float = 0.18) -> bool:
    if len(positions) < 3:
        return False
    diffs = [positions[i + 1] - positions[i] for i in range(len(positions) - 1)]
    mean_diff = sum(diffs) / len(diffs)
    if mean_diff <= 0:
        return False
    return all(abs(d - mean_diff) <= mean_diff * tolerance for d in diffs)


def _median_spacing(positions: list[float]) -> float | None:
    if len(positions) < 3:
        return None
    diffs = sorted(positions[i + 1] - positions[i] for i in range(len(positions) - 1))
    return diffs[len(diffs) // 2]


def detect_grid_size(board_roi: np.ndarray, candidates: range = range(4, 13)) -> int | None:
    """
    推算棋盤格數 N。

    用「格線間距」而不是「格線數量」來推算：N = 棋盤寬度 / 格線間距。
    因為某些謎題 (例如 Patches 的淡虛線) 的最外圈邊界線比內部格線更淡，
    在中等門檻下只抓到內部格線、漏掉最外兩條，用數量推算就會少算格數；
    但間距不受影響，所以用間距換算穩定得多。
    """
    gray = cv2.cvtColor(board_roi, cv2.COLOR_BGR2GRAY)
    board_size = (gray.shape[0] + gray.shape[1]) / 2
    votes: dict[int, int] = {}

    for threshold in (150, 180, 200, 215, 230, 240, 248):
        for min_fraction in (0.35, 0.5, 0.65):
            v_lines = _line_positions(gray, axis=0, threshold=threshold, min_fraction=min_fraction)
            h_lines = _line_positions(gray, axis=1, threshold=threshold, min_fraction=min_fraction)
            if not (_is_evenly_spaced(v_lines) and _is_evenly_spaced(h_lines)):
                continue
            spacings = [s for s in (_median_spacing(v_lines), _median_spacing(h_lines)) if s]
            if len(spacings) != 2:
                continue
            spacing = sum(spacings) / 2
            n = round(board_size / spacing)
            if n not in candidates:
                continue
            # 換算出來的格數要能讓間距跟棋盤寬度自洽 (誤差 5% 內)
            if abs(spacing * n - board_size) > board_size * 0.05:
                continue
            votes[n] = votes.get(n, 0) + 1

    if not votes:
        return None
    return max(votes.items(), key=lambda kv: kv[1])[0]


def build_grid(image: np.ndarray, n_hint: int | None = None) -> BoardGrid:
    bbox = find_board_bbox(image)
    if bbox is None:
        raise ValueError("偵測不到棋盤外框，請確認截圖有包含完整的棋盤區域")

    x, y, w, h = bbox
    roi = image[y : y + h, x : x + w]

    n = n_hint or detect_grid_size(roi)
    if n is None:
        raise ValueError("無法自動偵測棋盤格數，請手動指定格數")

    cell_w, cell_h = w / n, h / n
    cell_boxes = [
        [
            (x + round(c * cell_w), y + round(r * cell_h), round(cell_w), round(cell_h))
            for c in range(n)
        ]
        for r in range(n)
    ]
    return BoardGrid(n=n, board_bbox=bbox, cell_boxes=cell_boxes)
