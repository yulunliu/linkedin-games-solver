"""
Tango 的擴充：用「格線」而不是「格內圖示」來定位棋盤。

問題：Tango 的棋盤沒有粗外框，既有專案改用「格內太陽/月亮圖示的位置分佈」
反推棋盤範圍。但網頁版的棋盤比較小、而且圖示不會佈滿每一欄，
實測會把整個格線網格「往旁邊偏一格」——讀出來的 given 位置整排位移，
畫在最外圈欄位的 `=` / `×` 符號就完全落在範圍外，
結果條件不足、解出一堆組解（或直接解錯）。

作法：Tango 的棋盤其實有淡淡的格線，只是沒有外框。
直接找出「整條都比背景暗一點」的橫線與直線，取其中等距的一段，
就能精準得到棋盤範圍與格數，不必依賴圖示落在哪裡。
"""

import cv2
import numpy as np

import solver_bridge  # noqa: F401  匯入時會把 tango_solver 加進 sys.path

from board import cluster_positions  # noqa: E402

#: 嘗試的亮度門檻。Tango 的格線是很淡的米色，比白色背景只暗一點點。
_LINE_THRESHOLDS = (215, 225, 230, 238, 244, 248)
_LINE_MIN_FRACTIONS = (0.45, 0.55, 0.65)
#: 等距判定的容忍度 (相對於平均間距)
_SPACING_TOLERANCE = 0.12


def _column_line_positions(gray: np.ndarray, threshold: int, min_fraction: float) -> list[float]:
    """直線 (垂直格線) 的 x 座標：整欄大多是暗像素的那些欄。"""
    dark_fraction = (gray < threshold).mean(axis=0)  # 每一「欄」的暗像素比例
    raw = [float(i) for i, v in enumerate(dark_fraction) if v > min_fraction]
    return cluster_positions(raw, tol=4.0)


def _row_line_positions(gray: np.ndarray, threshold: int, min_fraction: float) -> list[float]:
    """橫線 (水平格線) 的 y 座標：整列大多是暗像素的那些列。"""
    dark_fraction = (gray < threshold).mean(axis=1)  # 每一「列」的暗像素比例
    raw = [float(i) for i, v in enumerate(dark_fraction) if v > min_fraction]
    return cluster_positions(raw, tol=4.0)


def _longest_even_run(positions: list[float]) -> list[float]:
    """從一堆線的位置中，取出最長的一段「等距」連續線。"""
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


def find_board(image: np.ndarray, n_hint: int | None = None) -> tuple[tuple[int, int, int, int], int] | None:
    """
    用格線定位 Tango 棋盤。回傳 ((x, y, w, h), n)，找不到回傳 None。
    """
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    best = None  # (分數, bbox, n)

    for threshold in _LINE_THRESHOLDS:
        for min_fraction in _LINE_MIN_FRACTIONS:
            x_lines = _longest_even_run(_column_line_positions(gray, threshold, min_fraction))
            y_lines = _longest_even_run(_row_line_positions(gray, threshold, min_fraction))
            if len(x_lines) < 4 or len(y_lines) < 4:
                continue

            # 線數 - 1 = 格數；橫豎要一致才可信
            n_x, n_y = len(x_lines) - 1, len(y_lines) - 1
            if n_x != n_y:
                continue
            n = n_x
            if n_hint is not None and n != n_hint:
                continue
            if not (4 <= n <= 12):
                continue

            width = x_lines[-1] - x_lines[0]
            height = y_lines[-1] - y_lines[0]
            if width <= 0 or height <= 0:
                continue
            # 棋盤要接近正方形
            if not (0.9 <= width / height <= 1.11):
                continue

            bbox = (round(x_lines[0]), round(y_lines[0]), round(width), round(height))
            score = len(x_lines) + len(y_lines)
            if best is None or score > best[0]:
                best = (score, bbox, n)

    if best is None:
        return None
    return best[1], best[2]


def build_grid(image: np.ndarray, n_hint: int | None = None):
    """用格線定位出 Tango 的棋盤，回傳與既有專案相同格式的 BoardGrid。"""
    import board as board_mod

    found = find_board(image, n_hint)
    if found is None:
        return None
    (x, y, w, h), n = found
    cell_w, cell_h = w / n, h / n
    cell_boxes = [
        [
            (x + round(c * cell_w), y + round(r * cell_h), round(cell_w), round(cell_h))
            for c in range(n)
        ]
        for r in range(n)
    ]
    return board_mod.BoardGrid(n=n, board_bbox=(x, y, w, h), cell_boxes=cell_boxes)


def build_puzzle(image: np.ndarray, grid):
    """
    用指定的棋盤格座標讀出 Tango 題目。

    等同於既有專案 pipeline.build_puzzle_from_image 的內容，
    差別只在棋盤是我們自己用格線定位出來的 (比較準)，
    格內圖示與 =/× 符號的辨識仍然直接沿用既有專案的函式。
    """
    import cell_classifier
    import edge_classifier
    from solver import MOON, SUN, Puzzle

    symbol_to_value = {"sun": SUN, "moon": MOON}
    readings = cell_classifier.read_all_cells(image, grid.cell_boxes)
    h_edges = edge_classifier.detect_h_edges(image, grid.cell_boxes)
    v_edges = edge_classifier.detect_v_edges(image, grid.cell_boxes)

    givens, current = {}, {}
    for r, row in enumerate(readings):
        for c, reading in enumerate(row):
            value = symbol_to_value.get(reading.symbol) if reading.symbol else None
            current[(r, c)] = value
            if reading.given and value is not None:
                givens[(r, c)] = value

    puzzle = Puzzle(n=grid.n, givens=givens, h_edges=h_edges, v_edges=v_edges)
    return puzzle, current, readings
