"""
Board geometry: find the puzzle grid in a screenshot and split it into cells.
棋盤幾何：在截圖中找出謎題棋盤並切出每一格。

All five LinkedIn puzzles share the same page layout: a square board sitting in
a centred card, surrounded by browser chrome, navigation bars and help text.
Everything downstream (icon recognition, digit OCR, mouse coordinates) depends
on locating that square accurately, so this module is the foundation.
五款 LinkedIn 謎題的頁面結構一樣：一個正方形棋盤放在置中的卡片裡，周圍是
瀏覽器工具列、導覽列與說明文字。後續所有處理（圖示辨識、數字辨識、滑鼠座標）
都依賴能不能準確定位這個正方形，所以這支模組是整個流程的基礎。

Two location strategies 兩種定位策略:
  1. find_board_bbox - looks for the largest square-ish contour. Works for
     Queens / Sudoku / Zip / Patches, which all draw a visible board border.
  2. find_board_by_grid_lines - measures the faint grid lines themselves.
     Needed for Tango, whose board has no outer border at all.
  1. find_board_bbox：找畫面中最大的近似正方形輪廓。適用於 Queens / Sudoku /
     Zip / Patches，它們都有可見的棋盤外框。
  2. find_board_by_grid_lines：直接量測淡淡的格線本身。
     Tango 需要用這個，因為它的棋盤完全沒有外框。
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np


@dataclass
class BoardGrid:
    """A located board: its size, its bounding box, and every cell rectangle.
    定位到的棋盤：格數、外框範圍，以及每一格的矩形。"""

    n: int
    board_bbox: tuple[int, int, int, int]  # x, y, w, h in image coordinates 影像座標
    cell_boxes: list[list[tuple[int, int, int, int]]]  # [row][col] -> x, y, w, h

    def cell_center(self, row: int, col: int) -> tuple[int, int]:
        x, y, w, h = self.cell_boxes[row][col]
        return x + w // 2, y + h // 2


def cluster_positions(positions: list[float], tol: float) -> list[float]:
    """Merge nearby coordinates into one representative value.
    把相近的座標合併成一個代表值。

    A drawn line is several pixels wide, so raw detection yields a run of
    adjacent indices; this collapses each run to its mean.
    畫出來的線有數個像素寬，偵測結果會是一串相鄰的索引；這裡把每一串收成平均值。
    """
    if not positions:
        return []
    positions = sorted(positions)
    clusters: list[list[float]] = [[positions[0]]]
    for value in positions[1:]:
        if value - clusters[-1][-1] <= tol:
            clusters[-1].append(value)
        else:
            clusters.append([value])
    return [sum(group) / len(group) for group in clusters]


def build_cell_boxes(bbox: tuple[int, int, int, int], n: int):
    """Split a board bounding box into an n x n grid of cell rectangles.
    把棋盤外框切成 n x n 的格子矩形。"""
    x, y, w, h = bbox
    cell_w, cell_h = w / n, h / n
    return [
        [
            (x + round(c * cell_w), y + round(r * cell_h), round(cell_w), round(cell_h))
            for c in range(n)
        ]
        for r in range(n)
    ]


# ---------------------------------------------------------------------------
# Strategy 1: outer border contour  策略一：外框輪廓
# ---------------------------------------------------------------------------
def find_board_bbox(image: np.ndarray) -> tuple[int, int, int, int] | None:
    """Find the largest square-ish contour, or None.
    找出最大的近似正方形輪廓，找不到回傳 None。"""
    height, width = image.shape[:2]
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    edges = cv2.Canny(blurred, 30, 100)
    edges = cv2.dilate(edges, np.ones((3, 3), np.uint8), iterations=2)

    contours, _ = cv2.findContours(edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    best, best_area = None, 0
    image_area = height * width
    for contour in contours:
        x, y, w, h = cv2.boundingRect(contour)
        area = w * h
        if area < image_area * 0.15:
            continue
        aspect = w / h if h else 0
        if not (0.9 <= aspect <= 1.1):
            continue
        if area > best_area:
            best_area, best = area, (x, y, w, h)
    return best


# ---------------------------------------------------------------------------
# Grid size 格數推算
# ---------------------------------------------------------------------------
def _line_positions(gray: np.ndarray, axis: int, threshold: int, min_fraction: float) -> list[float]:
    """Columns (axis=0) or rows (axis=1) that are mostly dark - i.e. grid lines.
    大部分像素偏暗的欄(axis=0)或列(axis=1)，也就是格線。"""
    dark_fraction = (gray < threshold).mean(axis=0 if axis == 0 else 1)
    raw = [float(i) for i, value in enumerate(dark_fraction) if value > min_fraction]
    return cluster_positions(raw, tol=max(4.0, gray.shape[0] * 0.01))


def _is_evenly_spaced(positions: list[float], tolerance: float = 0.18) -> bool:
    if len(positions) < 3:
        return False
    diffs = [positions[i + 1] - positions[i] for i in range(len(positions) - 1)]
    mean = sum(diffs) / len(diffs)
    if mean <= 0:
        return False
    return all(abs(d - mean) <= mean * tolerance for d in diffs)


def _median_spacing(positions: list[float]) -> float | None:
    if len(positions) < 3:
        return None
    diffs = sorted(positions[i + 1] - positions[i] for i in range(len(positions) - 1))
    return diffs[len(diffs) // 2]


def detect_grid_size(board_roi: np.ndarray, candidates: range = range(4, 13)) -> int | None:
    """Work out how many cells across the board is.
    推算棋盤有幾格寬。

    KEY POINT: this divides board width by *line spacing* rather than counting
    lines. Patches draws its outermost border fainter than the inner grid lines,
    so at a mid threshold only the inner lines are found and a count-based
    estimate is short by two - spacing is unaffected.
    關鍵：這裡是用「棋盤寬度 / 格線間距」推算，而不是數格線數量。Patches 的
    最外圈邊界線比內部格線更淡，中等門檻下只會抓到內部格線，用數量推算會少算
    兩條；但間距不受影響。
    """
    gray = cv2.cvtColor(board_roi, cv2.COLOR_BGR2GRAY)
    board_size = (gray.shape[0] + gray.shape[1]) / 2
    votes: dict[int, int] = {}

    # Sweep thresholds because line darkness varies a lot between puzzles
    # (Queens has thick black lines, Patches has faint dashes).
    # 掃描多組門檻，因為各謎題的格線深淺差很多
    # （Queens 是粗黑線，Patches 是很淡的虛線）。
    for threshold in (150, 180, 200, 215, 230, 240, 248):
        for min_fraction in (0.35, 0.5, 0.65):
            vertical = _line_positions(gray, 0, threshold, min_fraction)
            horizontal = _line_positions(gray, 1, threshold, min_fraction)
            if not (_is_evenly_spaced(vertical) and _is_evenly_spaced(horizontal)):
                continue
            spacings = [s for s in (_median_spacing(vertical), _median_spacing(horizontal)) if s]
            if len(spacings) != 2:
                continue
            spacing = sum(spacings) / 2
            n = round(board_size / spacing)
            if n not in candidates:
                continue
            # Sanity: spacing * n must reconstruct the board width.
            # 合理性檢查：間距 * 格數要能還原棋盤寬度。
            if abs(spacing * n - board_size) > board_size * 0.05:
                continue
            votes[n] = votes.get(n, 0) + 1

    return max(votes.items(), key=lambda kv: kv[1])[0] if votes else None


def build_grid(image: np.ndarray, n_hint: int | None = None) -> BoardGrid:
    """Locate a bordered board and split it into cells. Raises ValueError if not found.
    定位有外框的棋盤並切格。找不到時丟出 ValueError。"""
    bbox = find_board_bbox(image)
    if bbox is None:
        raise ValueError("board not found / 偵測不到棋盤外框")

    x, y, w, h = bbox
    n = n_hint or detect_grid_size(image[y : y + h, x : x + w])
    if n is None:
        raise ValueError("grid size not detected / 無法自動偵測棋盤格數")
    return BoardGrid(n=n, board_bbox=bbox, cell_boxes=build_cell_boxes(bbox, n))


# ---------------------------------------------------------------------------
# Strategy 2: grid lines only (for borderless boards, i.e. Tango)
# 策略二：只靠格線（給沒有外框的棋盤，也就是 Tango）
# ---------------------------------------------------------------------------
_LINE_THRESHOLDS = (215, 225, 230, 238, 244, 248)
_LINE_MIN_FRACTIONS = (0.45, 0.55, 0.65)
_SPACING_TOLERANCE = 0.12


def _longest_even_run(positions: list[float]) -> list[float]:
    """Longest evenly-spaced consecutive subsequence of line positions.
    在一串線位置中，取出最長的一段等距連續線。

    Picks the real grid out of a list that also contains card edges, button
    outlines and text baselines - only the grid is perfectly evenly spaced.
    這串位置裡也混著卡片邊緣、按鈕外框、文字基線；只有真正的格線是完全等距的。
    """
    best: list[float] = []
    for start in range(len(positions)):
        for end in range(start + 2, len(positions) + 1):
            segment = positions[start:end]
            diffs = [segment[i + 1] - segment[i] for i in range(len(segment) - 1)]
            mean = sum(diffs) / len(diffs)
            if mean <= 4:
                continue
            if all(abs(d - mean) <= mean * _SPACING_TOLERANCE for d in diffs):
                if len(segment) > len(best):
                    best = segment
    return best


def _column_lines(gray: np.ndarray, threshold: int, min_fraction: float) -> list[float]:
    dark = (gray < threshold).mean(axis=0)  # one value per column 每欄一個值
    return cluster_positions([float(i) for i, v in enumerate(dark) if v > min_fraction], 4.0)


def _row_lines(gray: np.ndarray, threshold: int, min_fraction: float) -> list[float]:
    dark = (gray < threshold).mean(axis=1)  # one value per row 每列一個值
    return cluster_positions([float(i) for i, v in enumerate(dark) if v > min_fraction], 4.0)


def find_board_by_grid_lines(
    image: np.ndarray, n_hint: int | None = None
) -> tuple[tuple[int, int, int, int], int] | None:
    """Locate a borderless board from its grid lines. Returns ((x,y,w,h), n).
    用格線定位沒有外框的棋盤。回傳 ((x,y,w,h), 格數)。"""
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    best = None  # (score, bbox, n)

    for threshold in _LINE_THRESHOLDS:
        for min_fraction in _LINE_MIN_FRACTIONS:
            x_lines = _longest_even_run(_column_lines(gray, threshold, min_fraction))
            y_lines = _longest_even_run(_row_lines(gray, threshold, min_fraction))
            if len(x_lines) < 4 or len(y_lines) < 4:
                continue
            # lines - 1 = cells; both directions must agree to be trustworthy
            # 線數 - 1 = 格數；橫豎要一致才可信
            if len(x_lines) != len(y_lines):
                continue
            n = len(x_lines) - 1
            if (n_hint is not None and n != n_hint) or not (4 <= n <= 12):
                continue

            width = x_lines[-1] - x_lines[0]
            height = y_lines[-1] - y_lines[0]
            if width <= 0 or height <= 0 or not (0.9 <= width / height <= 1.11):
                continue

            score = len(x_lines) + len(y_lines)
            if best is None or score > best[0]:
                best = (score, (round(x_lines[0]), round(y_lines[0]), round(width), round(height)), n)

    return (best[1], best[2]) if best else None


def build_grid_from_lines(image: np.ndarray, n_hint: int | None = None) -> BoardGrid | None:
    """BoardGrid for a borderless board, or None if the lines cannot be found.
    沒有外框的棋盤的 BoardGrid；找不到格線時回傳 None。"""
    found = find_board_by_grid_lines(image, n_hint)
    if found is None:
        return None
    bbox, n = found
    return BoardGrid(n=n, board_bbox=bbox, cell_boxes=build_cell_boxes(bbox, n))
