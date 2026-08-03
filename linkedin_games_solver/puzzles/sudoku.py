"""
Mini Sudoku - LinkedIn's 6x6 sudoku with 3-wide x 2-tall boxes.
Mini Sudoku —— LinkedIn 的 6x6 數獨，宮是 3 寬 x 2 高。

Rules 規則:
  - every row, column and box contains 1..N exactly once
  - 每列、每行、每宮 1..N 各出現一次

Recognition notes 辨識重點:
  * Box shape is derived from line THICKNESS - box separators are noticeably
    thicker than ordinary grid lines (measured ~8-9px vs ~2px).
    宮的形狀靠「格線粗細」判斷 —— 宮的分隔線明顯比一般格線粗（實測約 8~9px 對 2px）。
  * The solution must be UNIQUE; otherwise a digit was missed. See solve().
    解必須唯一，否則代表有數字沒讀到。見 solve()。
"""

from __future__ import annotations

import cv2
import numpy as np
from ortools.sat.python import cp_model

from ..core import BoardGrid, SolveResult, build_grid, failure
from ..core import digits as digit_ocr

NAME_EN = "Mini Sudoku"
NAME_ZH = "Mini Sudoku (迷你數獨)"
KEY = "sudoku"

#: Lines at least this thick are box separators rather than cell borders.
#: 線寬達此像素數視為宮的分隔線而不是一般格線。
THICK_LINE_MIN = 5


def _line_thickness(roi_gray: np.ndarray, position: int, axis: int, half_band: int = 10) -> int:
    if axis == 0:  # vertical line 垂直線
        band = roi_gray[:, max(0, position - half_band) : position + half_band]
        profile = (band < 170).mean(axis=0)
    else:  # horizontal line 水平線
        band = roi_gray[max(0, position - half_band) : position + half_band, :]
        profile = (band < 170).mean(axis=1)
    return int((profile > 0.7).sum())


def detect_box_shape(image: np.ndarray, grid: BoardGrid) -> tuple[int, int]:
    """Return (box_height, box_width) in cells.
    回傳宮的 (高, 寬)，以格數計。"""
    x, y, w, h = grid.board_bbox
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    roi = gray[y : y + h, x : x + w]
    n = grid.n
    cell_w, cell_h = w / n, h / n

    thick_cols = [c for c in range(1, n) if _line_thickness(roi, int(round(c * cell_w)), 0) >= THICK_LINE_MIN]
    thick_rows = [r for r in range(1, n) if _line_thickness(roi, int(round(r * cell_h)), 1) >= THICK_LINE_MIN]

    box_width = thick_cols[0] if thick_cols else _fallback_box_dim(n)
    box_height = thick_rows[0] if thick_rows else n // _fallback_box_dim(n)
    if n % box_width or n % box_height or box_width * box_height != n:
        box_width = _fallback_box_dim(n)
        box_height = n // box_width
    return box_height, box_width


def _fallback_box_dim(n: int) -> int:
    return {4: 2, 6: 3, 8: 4, 9: 3}.get(n, int(round(n**0.5)))


def read_givens(image: np.ndarray, grid: BoardGrid) -> dict[tuple[int, int], int]:
    """Read the digits already printed on the board.
    讀出盤面上題目已經給的數字。"""
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    givens = {}
    for r in range(grid.n):
        for c in range(grid.n):
            x, y, w, h = grid.cell_boxes[r][c]
            sub = gray[y + int(h * 0.15) : y + int(h * 0.85), x + int(w * 0.15) : x + int(w * 0.85)]
            mask = (sub < 128).astype(np.uint8)
            if mask.mean() < 0.01:
                continue
            # A Mini Sudoku cell can only hold 1..n, so let nothing else
            # compete. Measured on this board: excluding 0 and 7-9 raises 6's
            # template ceiling from 0.0295 to 0.0591 and 3's from 0.0785 to
            # 0.1163, improving the per-glyph margin by +0.0148 on average and
            # up to +0.0599. This is prevention, not detection - a digit that
            # never becomes a plausible runner-up cannot win.
            # Mini Sudoku 的格子只可能是 1..n，那就不要讓別的數字參與競爭。
            # 在這個盤面實測：排除 0 與 7-9 之後，6 的範本天花板從 0.0295 升到
            # 0.0591、3 從 0.0785 升到 0.1163，每個字形的差距平均改善 +0.0148、
            # 最多 +0.0599。這是「預防」而不是「偵測」——
            # 一個永遠不會成為合理第二名的數字，就不可能勝出。
            value = digit_ocr.read_number(mask, allowed=set(range(1, grid.n + 1)))
            if value is not None and 1 <= value <= grid.n:
                givens[(r, c)] = value
    return givens


def _build_model(n: int, box_h: int, box_w: int, givens: dict):
    model = cp_model.CpModel()
    cells = [[model.NewIntVar(1, n, f"c_{r}_{c}") for c in range(n)] for r in range(n)]
    for (r, c), value in givens.items():
        model.Add(cells[r][c] == value)
    for r in range(n):
        model.AddAllDifferent(cells[r])
    for c in range(n):
        model.AddAllDifferent([cells[r][c] for r in range(n)])
    for br in range(0, n, box_h):
        for bc in range(0, n, box_w):
            model.AddAllDifferent(
                [cells[r][c] for r in range(br, br + box_h) for c in range(bc, bc + box_w)]
            )
    return model, cells


def solve_grid(n: int, box_h: int, box_w: int, givens: dict) -> list[list[int]] | None:
    model, cells = _build_model(n, box_h, box_w, givens)
    solver = cp_model.CpSolver()
    if solver.Solve(model) not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return None
    return [[int(solver.Value(cells[r][c])) for c in range(n)] for r in range(n)]


def has_unique_solution(n: int, box_h: int, box_w: int, givens: dict) -> bool:
    """A real sudoku has exactly one solution; two means a digit was missed.
    真正的數獨只有一組解；找到兩組代表有數字沒被讀出來。"""
    model, _cells = _build_model(n, box_h, box_w, givens)

    class _Counter(cp_model.CpSolverSolutionCallback):
        def __init__(self):
            super().__init__()
            self.count = 0

        def on_solution_callback(self):
            self.count += 1
            if self.count >= 2:
                self.StopSearch()

    counter = _Counter()
    solver = cp_model.CpSolver()
    solver.parameters.enumerate_all_solutions = True
    solver.parameters.max_time_in_seconds = 10.0
    solver.Solve(model, counter)
    return counter.count == 1


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
            cv2.putText(out, text, (x + (w - tw) // 2, y + (h + th) // 2),
                        cv2.FONT_HERSHEY_SIMPLEX, scale, (0, 140, 255), thickness, cv2.LINE_AA)
    return out


def solve(image: np.ndarray, n_hint: int | None = None) -> SolveResult:
    try:
        grid = build_grid(image, n_hint=n_hint)
    except ValueError as exc:
        return failure(KEY, str(exc))

    box_h, box_w = detect_box_shape(image, grid)
    givens = read_givens(image, grid)
    info = [f"{grid.n}x{grid.n}", f"box / 宮 {box_h}x{box_w}", f"givens {len(givens)}"]

    if not givens:
        return failure(KEY, "no digits read / 讀不到任何已填數字", grid=grid, info=info)

    solution = solve_grid(grid.n, box_h, box_w, givens)
    if solution is None:
        return failure(KEY, "no solution / 找不到符合規則的解", grid=grid, info=info)
    if not has_unique_solution(grid.n, box_h, box_w, givens):
        return failure(
            KEY,
            "solution not unique - a digit was missed / 解不唯一，代表有數字沒讀到",
            grid=grid, info=info,
        )

    return SolveResult(
        ok=True, puzzle_key=KEY, grid=grid, info=info,
        data={"solution": solution, "givens": givens},
        overlay=draw_overlay(image, grid, solution, givens),
    )
