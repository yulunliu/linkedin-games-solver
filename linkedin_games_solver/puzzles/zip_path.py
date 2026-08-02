"""
Zip - one path that fills every cell and visits the numbered dots in order.
Zip —— 一條路徑填滿所有格子，並依序經過編號圓點。

Rules 規則:
  - the path starts at dot 1 and visits 2, 3, ... in order
  - it must pass through every cell exactly once
  - it may not cross the thick black walls
  - 路徑從 1 出發依序經過 2, 3, ...
  - 必須走過每一格恰好一次
  - 不能穿越粗黑色的牆

This is a Hamiltonian path problem, solved with CP-SAT's AddCircuit.
這是漢米頓路徑問題，用 CP-SAT 的 AddCircuit 求解。
"""

from __future__ import annotations

import cv2
import numpy as np
from ortools.sat.python import cp_model

from ..core import BoardGrid, SolveResult, build_grid, failure
from ..core import digits as digit_ocr

NAME_EN = "Zip"
NAME_ZH = "Zip (連線)"
KEY = "zip"

DARK_THRESHOLD = 90
#: Dark-pixel fraction across a cell boundary above which a wall is present.
#: 交界處深色像素比例超過此值視為有牆。
WALL_DARK_FRACTION = 0.3


def _looks_like_dot(w: int, h: int, area: int, cell: float) -> bool:
    """Numbered dots are near-square, about half a cell, and disc-shaped.
    編號圓點接近正方形、大小約半格，且填滿率接近圓形佔外框的比例 (pi/4)。"""
    if w == 0 or h == 0:
        return False
    return (
        0.85 <= w / h <= 1.15
        and cell * 0.35 <= w <= cell * 0.95
        and 0.6 <= area / (w * h) <= 0.92
    )


def _enclosed_holes(component: np.ndarray) -> np.ndarray:
    """Pixels fully enclosed by a component - i.e. the white digit inside a dot.
    被元件完全包圍的像素 —— 也就是圓點裡的白色數字。

    KEY POINT: flood fill from the border, keeping what the water cannot reach.
      Morphological closing was tried first and distorted the disc, corrupting
      the digit. Note the padding must be filled with the SAME value as the
      background being erased, otherwise the fill clears nothing.
    關鍵：從邊界灌水，保留灌不到的地方。
      先前用形態學閉運算會讓圓盤變形、破壞數字。注意外圈 padding 必須填成
      「要被清除的背景」同值，否則灌水什麼都清不掉。
    """
    padded = np.ones((component.shape[0] + 2, component.shape[1] + 2), np.uint8)
    padded[1:-1, 1:-1] = (~component).astype(np.uint8)
    mask = np.zeros((padded.shape[0] + 2, padded.shape[1] + 2), np.uint8)
    cv2.floodFill(padded, mask, (0, 0), 0)
    return padded[1:-1, 1:-1] > 0


def find_dots(image: np.ndarray, grid: BoardGrid) -> dict[tuple[int, int], int]:
    """Locate the numbered dots and read their numbers.
    找出編號圓點並讀出號碼。"""
    x0, y0, w0, h0 = grid.board_bbox
    cell = (w0 / grid.n + h0 / grid.n) / 2
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    dark = (gray < DARK_THRESHOLD).astype(np.uint8)

    num, labels_img, stats, centroids = cv2.connectedComponentsWithStats(dark, connectivity=8)
    dots: dict[tuple[int, int], int] = {}
    for i in range(1, num):
        x, y, w, h, area = stats[i]
        if not _looks_like_dot(w, h, area, cell):
            continue
        cx, cy = centroids[i]
        row, col = int((cy - y0) / cell), int((cx - x0) / cell)
        if not (0 <= row < grid.n and 0 <= col < grid.n):
            continue
        component = labels_img[y : y + h, x : x + w] == i
        value = digit_ocr.read_number(_enclosed_holes(component).astype(np.uint8))
        if value is not None:
            dots[(row, col)] = value
    return dots


def find_walls(image: np.ndarray, grid: BoardGrid) -> tuple[set, set]:
    """Walls between adjacent cells. Returns (h_walls, v_walls).
    相鄰格之間的牆。回傳 (水平相鄰的牆, 垂直相鄰的牆)。"""
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    mask = (gray < DARK_THRESHOLD).astype(np.uint8)
    x0, y0, w0, h0 = grid.board_bbox
    cell = (w0 / grid.n + h0 / grid.n) / 2

    # Erase the numbered dots first, otherwise a dot near a boundary reads as a wall.
    # 先把編號圓點挖掉，否則靠近邊界的圓點會被誤判成牆。
    num, _, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    for i in range(1, num):
        x, y, w, h, area = stats[i]
        if _looks_like_dot(w, h, area, cell):
            cv2.rectangle(mask, (x - 4, y - 4), (x + w + 4, y + h + 4), 0, -1)

    def dark_fraction(x_from, x_to, y_from, y_to) -> float:
        sub = mask[max(0, y_from) : y_to, max(0, x_from) : x_to]
        return float(sub.mean()) if sub.size else 0.0

    h_walls, v_walls = set(), set()
    for r in range(grid.n):
        for c in range(grid.n - 1):
            x, y, w, h = grid.cell_boxes[r][c]
            band = max(4, w // 12)
            if dark_fraction(x + w - band, x + w + band, y + int(h * 0.2), y + int(h * 0.8)) > WALL_DARK_FRACTION:
                h_walls.add((r, c))
    for r in range(grid.n - 1):
        for c in range(grid.n):
            x, y, w, h = grid.cell_boxes[r][c]
            band = max(4, h // 12)
            if dark_fraction(x + int(w * 0.2), x + int(w * 0.8), y + h - band, y + h + band) > WALL_DARK_FRACTION:
                v_walls.add((r, c))
    return h_walls, v_walls


def solve_path(n: int, dots: dict, h_walls: set, v_walls: set) -> list[tuple[int, int]] | None:
    """Find the Hamiltonian path. Returns cells in visiting order.
    找出漢米頓路徑，回傳依序經過的格子。"""
    if not dots:
        return None
    ordered = sorted(dots.items(), key=lambda kv: kv[1])
    start = ordered[0][0]

    total = n * n
    index = {(r, c): r * n + c for r in range(n) for c in range(n)}
    dummy = total

    def passable(a, b) -> bool:
        (r1, c1), (r2, c2) = a, b
        if r1 == r2:
            return (r1, min(c1, c2)) not in h_walls
        return (min(r1, r2), c1) not in v_walls

    model = cp_model.CpModel()
    arcs = []
    arc_literals: dict[tuple[int, int], object] = {}

    # A dummy node turns "Hamiltonian path from start to anywhere" into a
    # Hamiltonian circuit, which AddCircuit can express directly:
    #   dummy -> start -> ... -> end -> dummy
    # 用一個虛擬節點把「從 start 出發到任意終點的漢米頓路徑」轉成
    # AddCircuit 能直接表達的漢米頓環：dummy -> start -> ... -> end -> dummy
    always_true = model.NewBoolVar("dummy_start")
    model.Add(always_true == 1)
    arcs.append((dummy, index[start], always_true))

    for r in range(n):
        for c in range(n):
            u = index[(r, c)]
            arcs.append((u, dummy, model.NewBoolVar(f"end_{r}_{c}")))
            for dr, dc in ((0, 1), (0, -1), (1, 0), (-1, 0)):
                nr, nc = r + dr, c + dc
                if not (0 <= nr < n and 0 <= nc < n) or not passable((r, c), (nr, nc)):
                    continue
                lit = model.NewBoolVar(f"a_{r}_{c}_{nr}_{nc}")
                arcs.append((u, index[(nr, nc)], lit))
                arc_literals[(u, index[(nr, nc)])] = lit

    model.AddCircuit(arcs)

    # Position along the path, so the dot ordering can be constrained.
    # 路徑上的順序，用來限制編號圓點的先後。
    pos = {cell: model.NewIntVar(0, total - 1, f"p_{cell}") for cell in index}
    model.Add(pos[start] == 0)
    for (u, v), lit in arc_literals.items():
        ur, uc = divmod(u, n)
        vr, vc = divmod(v, n)
        model.Add(pos[(vr, vc)] == pos[(ur, uc)] + 1).OnlyEnforceIf(lit)

    for (cell_a, _), (cell_b, _) in zip(ordered, ordered[1:]):
        model.Add(pos[cell_a] < pos[cell_b])

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 60.0
    solver.parameters.num_workers = 8
    if solver.Solve(model) not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return None
    return sorted(index, key=lambda cell: solver.Value(pos[cell]))


def draw_overlay(image, grid: BoardGrid, path) -> np.ndarray:
    out = image.copy()
    points = [grid.cell_center(r, c) for r, c in path]
    _, _, cw, ch = grid.cell_boxes[0][0]
    thickness = max(4, min(cw, ch) // 8)
    for a, b in zip(points, points[1:]):
        cv2.line(out, a, b, (0, 90, 230), thickness, lineType=cv2.LINE_AA)
    cv2.circle(out, points[0], thickness * 2, (0, 190, 0), -1, lineType=cv2.LINE_AA)
    cv2.circle(out, points[-1], thickness * 2, (0, 0, 230), -1, lineType=cv2.LINE_AA)
    return out


def solve(image: np.ndarray, n_hint: int | None = None) -> SolveResult:
    try:
        grid = build_grid(image, n_hint=n_hint)
    except ValueError as exc:
        return failure(KEY, str(exc))

    dots = find_dots(image, grid)
    h_walls, v_walls = find_walls(image, grid)
    info = [f"{grid.n}x{grid.n}", f"dots / 圓點 {len(dots)}", f"walls / 牆 {len(h_walls)}+{len(v_walls)}"]

    if len(dots) < 2:
        return failure(KEY, "fewer than 2 dots found / 編號圓點少於 2 個", grid=grid, info=info)
    values = sorted(dots.values())
    if values != list(range(1, len(values) + 1)):
        return failure(KEY, f"dot numbers not consecutive / 圓點編號不連續 {values}", grid=grid, info=info)

    path = solve_path(grid.n, dots, h_walls, v_walls)
    if path is None:
        return failure(KEY, "no valid path / 找不到符合規則的路徑", grid=grid, info=info)

    return SolveResult(
        ok=True, puzzle_key=KEY, grid=grid, info=info,
        data={"path": path, "dots": dots},
        overlay=draw_overlay(image, grid, path),
    )
