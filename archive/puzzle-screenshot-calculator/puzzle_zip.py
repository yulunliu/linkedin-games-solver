"""
Zip 謎題：一條路徑填滿所有格子，並依序經過編號圓點。

規則 (畫面說明):
  - 「按順序將點連接起來」：路徑從 1 出發，依序經過 2, 3, ... 最後一個編號
  - 「填滿每個格子」：路徑必須走過盤面上每一格恰好一次
  - 粗黑線是牆，路徑不能穿越

辨識:
  - 編號圓點是黑色實心圓 (中央有白色數字)：找接近正方形、填滿率約 0.77 的
    黑色連通元件，再讀出裡面的白色數字
  - 牆是畫在格線上的粗黑線：把圓點從黑色遮罩中挖掉後，檢查每一組相鄰格
    交界處是否有大量黑色像素
"""

import cv2
import numpy as np
from ortools.sat.python import cp_model

import digit_ocr
from board import BoardGrid, build_grid
from puzzle_base import PuzzleResult, failure

NAME = "Zip (連線)"

DARK_THRESHOLD = 90
WALL_DARK_FRACTION = 0.3  # 交界處黑色像素比例超過此值視為有牆


def find_dots(image: np.ndarray, grid: BoardGrid) -> dict[tuple[int, int], int]:
    """回傳 {(row, col): 編號}。"""
    x0, y0, w0, h0 = grid.board_bbox
    cell = (w0 / grid.n + h0 / grid.n) / 2
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    dark = (gray < DARK_THRESHOLD).astype(np.uint8)

    num, labels_img, stats, centroids = cv2.connectedComponentsWithStats(dark, connectivity=8)
    dots: dict[tuple[int, int], int] = {}

    for i in range(1, num):
        x, y, w, h, area = stats[i]
        if w == 0 or h == 0:
            continue
        # 圓點：近似正方形、大小約半格、填滿率接近圓形佔外框的比例 (pi/4≈0.79)
        if not (0.85 <= w / h <= 1.15):
            continue
        if not (cell * 0.35 <= w <= cell * 0.95):
            continue
        if not (0.6 <= area / (w * h) <= 0.92):
            continue
        cx, cy = centroids[i]
        row = int((cy - y0) / cell)
        col = int((cx - x0) / cell)
        if not (0 <= row < grid.n and 0 <= col < grid.n):
            continue

        # 圓點是實心黑圓、數字是白的，所以數字剛好是這個黑色連通元件「內部的洞」
        component = labels_img[y : y + h, x : x + w] == i
        digit_mask = _enclosed_holes(component)
        value = digit_ocr.read_number(digit_mask.astype(np.uint8))
        if value is None:
            continue
        dots[(row, col)] = value

    return dots


def _enclosed_holes(component: np.ndarray) -> np.ndarray:
    """
    取出連通元件內部被完全包圍的洞。
    圓點是實心黑圓、中央數字是白色，所以數字就是這個黑圓內部的洞，
    用「從邊界往內灌水、灌不到的背景就是洞」精確取出，不會受形態學運算變形影響。
    """
    # 外圈補一層「背景」，這樣從角落灌水就能把所有connected的外部背景清掉，
    # 剩下 1 的地方就是被元件完全包圍的洞。
    padded = np.ones((component.shape[0] + 2, component.shape[1] + 2), np.uint8)
    padded[1:-1, 1:-1] = (~component).astype(np.uint8)
    flood_mask = np.zeros((padded.shape[0] + 2, padded.shape[1] + 2), np.uint8)
    cv2.floodFill(padded, flood_mask, (0, 0), 0)
    return padded[1:-1, 1:-1] > 0


def find_walls(image: np.ndarray, grid: BoardGrid) -> tuple[set, set]:
    """
    回傳 (h_walls, v_walls)。
    h_walls 內含 (r, c) 表示 (r,c) 與 (r,c+1) 之間有牆。
    v_walls 內含 (r, c) 表示 (r,c) 與 (r+1,c) 之間有牆。
    """
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    mask = (gray < DARK_THRESHOLD).astype(np.uint8)
    x0, y0, w0, h0 = grid.board_bbox
    cell = (w0 / grid.n + h0 / grid.n) / 2

    # 把編號圓點挖掉，避免圓點被誤判成牆
    num, _, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    for i in range(1, num):
        x, y, w, h, area = stats[i]
        if w == 0 or h == 0:
            continue
        if 0.85 <= w / h <= 1.15 and cell * 0.35 <= w <= cell * 0.95 and 0.6 <= area / (w * h) <= 0.92:
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


def solve(n: int, dots: dict[tuple[int, int], int], h_walls: set, v_walls: set) -> list[tuple[int, int]] | None:
    """回傳路徑上依序的格子座標，無解回傳 None。"""
    if not dots:
        return None
    ordered = sorted(dots.items(), key=lambda kv: kv[1])
    start = ordered[0][0]

    total = n * n
    index = {(r, c): r * n + c for r in range(n) for c in range(n)}
    dummy = total

    def passable(a: tuple[int, int], b: tuple[int, int]) -> bool:
        (r1, c1), (r2, c2) = a, b
        if r1 == r2:
            left = min(c1, c2)
            return (r1, left) not in h_walls
        top = min(r1, r2)
        return (top, c1) not in v_walls

    model = cp_model.CpModel()
    arcs = []
    arc_literals: dict[tuple[int, int], object] = {}

    # 虛擬節點 dummy -> start 固定成立，讓 AddCircuit 形成
    # dummy -> start -> ... -> end -> dummy 的環，也就是 start 到任意 end 的漢米頓路徑
    always_true = model.NewBoolVar("dummy_start")
    model.Add(always_true == 1)
    arcs.append((dummy, index[start], always_true))

    for r in range(n):
        for c in range(n):
            u = index[(r, c)]
            back = model.NewBoolVar(f"end_{r}_{c}")
            arcs.append((u, dummy, back))
            for dr, dc in ((0, 1), (0, -1), (1, 0), (-1, 0)):
                nr, nc = r + dr, c + dc
                if not (0 <= nr < n and 0 <= nc < n):
                    continue
                if not passable((r, c), (nr, nc)):
                    continue
                lit = model.NewBoolVar(f"a_{r}_{c}_{nr}_{nc}")
                arcs.append((u, index[(nr, nc)], lit))
                arc_literals[(u, index[(nr, nc)])] = lit

    model.AddCircuit(arcs)

    # 路徑順序：pos[start]=0，沿著被選中的邊每走一步 +1
    pos = {cellpos: model.NewIntVar(0, total - 1, f"p_{cellpos}") for cellpos in index}
    model.Add(pos[start] == 0)
    for (u, v), lit in arc_literals.items():
        ur, uc = divmod(u, n)
        vr, vc = divmod(v, n)
        model.Add(pos[(vr, vc)] == pos[(ur, uc)] + 1).OnlyEnforceIf(lit)

    # 編號圓點必須依序被經過
    for (cell_a, _), (cell_b, _) in zip(ordered, ordered[1:]):
        model.Add(pos[cell_a] < pos[cell_b])

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 60.0
    solver.parameters.num_workers = 8
    status = solver.Solve(model)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return None

    order = sorted(index, key=lambda cellpos: solver.Value(pos[cellpos]))
    return order


def draw_overlay(image, grid: BoardGrid, path: list[tuple[int, int]]) -> np.ndarray:
    out = image.copy()
    points = [grid.cell_center(r, c) for r, c in path]
    thickness = max(4, min(grid.cell_boxes[0][0][2], grid.cell_boxes[0][0][3]) // 8)
    for a, b in zip(points, points[1:]):
        cv2.line(out, a, b, (0, 90, 230), thickness, lineType=cv2.LINE_AA)
    cv2.circle(out, points[0], thickness * 2, (0, 190, 0), -1, lineType=cv2.LINE_AA)
    cv2.circle(out, points[-1], thickness * 2, (0, 0, 230), -1, lineType=cv2.LINE_AA)
    return out


def draw_debug(image, grid: BoardGrid, dots, h_walls, v_walls) -> np.ndarray:
    dbg = image.copy()
    for row in grid.cell_boxes:
        for x, y, w, h in row:
            cv2.rectangle(dbg, (x, y), (x + w, y + h), (0, 200, 0), 1)
    for (r, c), value in dots.items():
        x, y, w, h = grid.cell_boxes[r][c]
        cv2.putText(dbg, str(value), (x + 8, y + 30), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (255, 0, 255), 2)
    for r, c in h_walls:
        x, y, w, h = grid.cell_boxes[r][c]
        cv2.line(dbg, (x + w, y + 6), (x + w, y + h - 6), (255, 0, 255), 4)
    for r, c in v_walls:
        x, y, w, h = grid.cell_boxes[r][c]
        cv2.line(dbg, (x + 6, y + h), (x + w - 6, y + h), (255, 0, 255), 4)
    return dbg


def analyze(image: np.ndarray, n_hint: int | None = None, debug: bool = False) -> PuzzleResult:
    try:
        grid = build_grid(image, n_hint=n_hint)
    except ValueError as e:
        return failure(f"辨識失敗: {e}")

    dots = find_dots(image, grid)
    h_walls, v_walls = find_walls(image, grid)
    debug_image = draw_debug(image, grid, dots, h_walls, v_walls) if debug else None

    info = [
        f"偵測到棋盤大小: {grid.n} x {grid.n}",
        f"偵測到編號圓點: {len(dots)} 個 -> "
        + ", ".join(f"{v}@({r + 1},{c + 1})" for (r, c), v in sorted(dots.items(), key=lambda kv: kv[1])),
        f"偵測到牆: 水平向 {len(h_walls)} 道, 垂直向 {len(v_walls)} 道",
    ]

    if len(dots) < 2:
        return failure("編號圓點少於 2 個，辨識可能有誤。", debug_image=debug_image, report_lines=info)

    values = sorted(dots.values())
    if values != list(range(1, len(values) + 1)):
        return failure(
            f"圓點編號不連續 ({values})，數字辨識可能有誤。",
            debug_image=debug_image, report_lines=info,
        )

    path = solve(grid.n, dots, h_walls, v_walls)
    if path is None:
        return failure(
            "找不到符合規則的路徑，可能是圓點或牆的辨識有誤。",
            debug_image=debug_image, report_lines=info,
        )

    lines = info + ["", "=== 路徑順序 (第X列, 第Y欄) ==="]
    lines.append(" -> ".join(f"({r + 1},{c + 1})" for r, c in path))

    lines.append("")
    lines.append("=== 每格的行走順序 ===")
    order_map = {cellpos: i + 1 for i, cellpos in enumerate(path)}
    width = len(str(grid.n * grid.n))
    for r in range(grid.n):
        lines.append(" ".join(f"{order_map[(r, c)]:>{width}}" for c in range(grid.n)))

    return PuzzleResult(
        ok=True,
        report_lines=lines,
        overlay_image=draw_overlay(image, grid, path),
        debug_image=debug_image,
    )
