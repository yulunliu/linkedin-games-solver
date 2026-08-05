"""
Mini Sudoku 謎題：N x N 數獨 (LinkedIn 版通常是 6x6，宮是 3 寬 x 2 高)。

規則:
  - 每列、每行、每個宮 (粗線分隔的區塊) 內 1..N 各出現恰好一次

辨識:
  - 宮的大小靠「格線粗細」判斷：宮的分隔線明顯比一般格線粗
    (實測一般格線約 2px、宮分隔線約 8~9px)
  - 格內既有數字用 digit_ocr 讀出
"""

import cv2
import numpy as np
from ortools.sat.python import cp_model

import digit_ocr
from board import BoardGrid, build_grid
from puzzle_base import PuzzleResult, failure

NAME = "Mini Sudoku (迷你數獨)"

THICK_LINE_MIN = 5  # 線寬達此像素數視為宮的分隔線


def _line_thickness(roi_gray: np.ndarray, position: int, axis: int, half_band: int = 10) -> int:
    if axis == 0:  # 垂直線
        band = roi_gray[:, max(0, position - half_band) : position + half_band]
        profile = (band < 170).mean(axis=0)
    else:  # 水平線
        band = roi_gray[max(0, position - half_band) : position + half_band, :]
        profile = (band < 170).mean(axis=1)
    return int((profile > 0.7).sum())


def detect_box_shape(image: np.ndarray, grid: BoardGrid) -> tuple[int, int]:
    """
    回傳 (box_height, box_width)：宮的高與寬 (以格數計)。
    找出哪些內部格線是粗線，粗線之間的距離就是宮的邊長。
    """
    x0, y0, w0, h0 = grid.board_bbox
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    roi = gray[y0 : y0 + h0, x0 : x0 + w0]
    n = grid.n
    cell_w, cell_h = w0 / n, h0 / n

    thick_cols = [
        c for c in range(1, n)
        if _line_thickness(roi, int(round(c * cell_w)), axis=0) >= THICK_LINE_MIN
    ]
    thick_rows = [
        r for r in range(1, n)
        if _line_thickness(roi, int(round(r * cell_h)), axis=1) >= THICK_LINE_MIN
    ]

    box_width = thick_cols[0] if thick_cols else _fallback_box_dim(n)
    box_height = thick_rows[0] if thick_rows else n // _fallback_box_dim(n)
    if n % box_width or n % box_height or box_width * box_height != n:
        # 偵測不可靠時退回常見設定
        box_width = _fallback_box_dim(n)
        box_height = n // box_width
    return box_height, box_width


def _fallback_box_dim(n: int) -> int:
    return {4: 2, 6: 3, 8: 4, 9: 3}.get(n, int(round(n**0.5)))


def read_givens(image: np.ndarray, grid: BoardGrid) -> dict[tuple[int, int], int]:
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    givens = {}
    for r in range(grid.n):
        for c in range(grid.n):
            x, y, w, h = grid.cell_boxes[r][c]
            sub = gray[y + int(h * 0.15) : y + int(h * 0.85), x + int(w * 0.15) : x + int(w * 0.85)]
            mask = (sub < 128).astype(np.uint8)
            if mask.mean() < 0.01:
                continue
            value = digit_ocr.read_number(mask)
            if value is not None and 1 <= value <= grid.n:
                givens[(r, c)] = value
    return givens


def solve(n: int, box_height: int, box_width: int, givens: dict[tuple[int, int], int]) -> list[list[int]] | None:
    model = cp_model.CpModel()
    cells = [[model.NewIntVar(1, n, f"c_{r}_{c}") for c in range(n)] for r in range(n)]

    for (r, c), v in givens.items():
        model.Add(cells[r][c] == v)
    for r in range(n):
        model.AddAllDifferent(cells[r])
    for c in range(n):
        model.AddAllDifferent([cells[r][c] for r in range(n)])
    for br in range(0, n, box_height):
        for bc in range(0, n, box_width):
            box = [
                cells[r][c]
                for r in range(br, br + box_height)
                for c in range(bc, bc + box_width)
            ]
            model.AddAllDifferent(box)

    solver = cp_model.CpSolver()
    status = solver.Solve(model)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return None
    return [[int(solver.Value(cells[r][c])) for c in range(n)] for r in range(n)]


def draw_overlay(image, grid: BoardGrid, solution, givens) -> np.ndarray:
    out = image.copy()
    for r in range(grid.n):
        for c in range(grid.n):
            if (r, c) in givens:
                continue
            x, y, w, h = grid.cell_boxes[r][c]
            text = str(solution[r][c])
            scale = min(w, h) / 45.0
            thickness = max(2, int(scale * 2))
            (tw, th), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, scale, thickness)
            cv2.putText(
                out, text, (x + (w - tw) // 2, y + (h + th) // 2),
                cv2.FONT_HERSHEY_SIMPLEX, scale, (0, 140, 255), thickness, cv2.LINE_AA,
            )
    return out


def draw_debug(image, grid: BoardGrid, givens) -> np.ndarray:
    dbg = image.copy()
    for r in range(grid.n):
        for c in range(grid.n):
            x, y, w, h = grid.cell_boxes[r][c]
            cv2.rectangle(dbg, (x, y), (x + w, y + h), (0, 255, 0), 1)
            label = str(givens.get((r, c), "."))
            cv2.putText(dbg, label, (x + 6, y + 26), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)
    return dbg


def analyze(image: np.ndarray, n_hint: int | None = None, debug: bool = False) -> PuzzleResult:
    try:
        grid = build_grid(image, n_hint=n_hint)
    except ValueError as e:
        return failure(f"辨識失敗: {e}")

    box_height, box_width = detect_box_shape(image, grid)
    givens = read_givens(image, grid)
    debug_image = draw_debug(image, grid, givens) if debug else None

    info = [
        f"偵測到棋盤大小: {grid.n} x {grid.n}",
        f"偵測到宮的大小: {box_height} 高 x {box_width} 寬",
        f"偵測到已填數字: {len(givens)} 個",
    ]

    if not givens:
        return failure("讀不到任何已填數字，請確認截圖清晰度。", debug_image=debug_image, report_lines=info)

    solution = solve(grid.n, box_height, box_width, givens)
    if solution is None:
        return failure("找不到符合規則的解，可能是數字辨識有誤。", debug_image=debug_image, report_lines=info)

    lines = info + ["", "=== 完整解答 (括號為題目原有數字) ==="]
    for r in range(grid.n):
        row_parts = []
        for c in range(grid.n):
            v = solution[r][c]
            row_parts.append(f"({v})" if (r, c) in givens else f" {v} ")
        lines.append("".join(row_parts))

    return PuzzleResult(
        ok=True,
        report_lines=lines,
        overlay_image=draw_overlay(image, grid, solution, givens),
        debug_image=debug_image,
    )
