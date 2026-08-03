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


#: Solidity of a disc once its printed number is filled back in.
#: 把圓盤上印的數字填回去之後的實心度。
#:
#: A circle fills pi/4 = 0.785 of its bounding box no matter what number is
#: written on it. Measured on img/capture.png, 12 discs, native 424px board:
#: 0.7785..0.8002 (0.7566..0.8035 across 8 board sizes 383..1051px).
#: 圓形佔外框 pi/4 = 0.785，跟上面寫什麼數字無關。
#: 實測 img/capture.png 原生 424px 的 12 個圓盤：0.7785~0.8002
#: （8 種棋盤大小 383~1051px 為 0.7566~0.8035）。
#:
#: WHY NOT the raw dark area 為什麼不用「原始深色面積」:
#:   That varies with how much white ink the number takes up - measured
#:   0.5972 ("10": two digits plus a counter) .. 0.7407 ("1"). The old 0.60
#:   floor sat right in the middle of that spread and silently threw the "10"
#:   disc away, which is why one of twelve dots was never detected.
#:   那個值會隨數字佔掉多少白色而變 —— 實測 0.5972（「10」：兩位數又有內孔）
#:   到 0.7407（「1」）。舊的 0.60 下限正好卡在這個範圍中間，
#:   把「10」那顆圓盤默默丟掉，這就是 12 個圓點漏掉一個的原因。
DISC_SOLIDITY_MIN = 0.70   # 0.0566 below the lowest observed 比實測最低值低 0.0566
DISC_SOLIDITY_MAX = 0.88   # 0.0765 above the highest 比實測最高值高 0.0765


def _looks_like_dot(component: np.ndarray, w: int, h: int, cell: float) -> bool:
    """Numbered dots are near-square, about half a cell, and disc-shaped.
    編號圓點接近正方形、大小約半格、形狀接近圓盤。"""
    if w == 0 or h == 0 or component.size == 0:
        return False
    if not (0.85 <= w / h <= 1.15 and cell * 0.35 <= w <= cell * 0.95):
        return False
    # Fill the printed number back in before measuring, so the answer does not
    # depend on which number is printed.
    # 量測前先把印上去的數字填回去，結果才不會取決於印的是哪個數字。
    filled = component | _enclosed_holes(component)
    return DISC_SOLIDITY_MIN <= filled.sum() / (w * h) <= DISC_SOLIDITY_MAX


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


def find_dots(image: np.ndarray, grid: BoardGrid):
    """Locate the numbered dots and read their numbers.
    找出編號圓點並讀出號碼。

    Returns (dots, disc_count). `disc_count` is how many discs were FOUND, which
    can exceed len(dots) when a number could not be read. The caller must
    compare the two - see solve().
    回傳 (dots, disc_count)。`disc_count` 是「找到幾個圓盤」，
    當某個號碼讀不出來時它會大於 len(dots)。呼叫端必須比對這兩個數字，見 solve()。
    """
    x0, y0, w0, h0 = grid.board_bbox
    cell = (w0 / grid.n + h0 / grid.n) / 2
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    dark = (gray < DARK_THRESHOLD).astype(np.uint8)

    num, labels_img, stats, centroids = cv2.connectedComponentsWithStats(dark, connectivity=8)
    dots: dict[tuple[int, int], int] = {}
    disc_count = 0
    for i in range(1, num):
        x, y, w, h, area = stats[i]
        window = labels_img[y : y + h, x : x + w]
        component = window == i
        if not _looks_like_dot(component, w, h, cell):
            continue
        cx, cy = centroids[i]
        row, col = int((cy - y0) / cell), int((cx - x0) / cell)
        if not (0 <= row < grid.n and 0 <= col < grid.n):
            continue
        disc_count += 1

        # A digit with an enclosed counter (0 4 6 8 9) leaves that counter as a
        # SEPARATE dark component, so it is not part of `component`, the flood
        # fill cannot reach it, and _enclosed_holes hands the digit back with
        # its holes filled solid. Anything that is itself dark cannot be part of
        # the white number, so intersect with "not dark".
        # Measured on img/capture.png at native 424px, top-1 digit and margin:
        #   (1,1) "0"  before 9@0.9129 m=0.0001 (WRONG)  after 0@0.9816 m=0.0517
        #   (0,1) "9"  before rejected                    after 9@0.9672 m=0.0516
        #   (4,1) "6"                                     after 6@0.9763 m=0.0425
        # After this change all 12 discs have the correct top-1 digit.
        # 帶封閉內孔的數字（0 4 6 8 9），內孔是「另一個」深色元件，不屬於 component，
        # 灌水也灌不到，_enclosed_holes 會把它當成孔一起交回 —— 等於把洞填實了。
        # 本身就是深色的像素不可能是白色數字的一部分，所以跟「非深色」取交集。
        # 實測 img/capture.png 原生 424px，第一名數字與差距：
        #   (1,1) 的「0」修正前 9@0.9129 差距 0.0001（第一名就是錯的）
        #                修正後 0@0.9816 差距 0.0517
        # 修正後 12 個圓盤的第一名數字全部正確。
        holes = _enclosed_holes(component) & (window == 0)
        value = digit_ocr.read_number(holes.astype(np.uint8))
        if value is not None:
            dots[(row, col)] = value
    return dots, disc_count


def find_walls(image: np.ndarray, grid: BoardGrid) -> tuple[set, set]:
    """Walls between adjacent cells. Returns (h_walls, v_walls).
    相鄰格之間的牆。回傳 (水平相鄰的牆, 垂直相鄰的牆)。"""
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    mask = (gray < DARK_THRESHOLD).astype(np.uint8)
    x0, y0, w0, h0 = grid.board_bbox
    cell = (w0 / grid.n + h0 / grid.n) / 2

    # Erase the numbered dots first, otherwise a dot near a boundary reads as a wall.
    # 先把編號圓點挖掉，否則靠近邊界的圓點會被誤判成牆。
    #
    # KEEP THE LABEL IMAGE. _looks_like_dot needs the component mask to fill the
    # printed number back in. Discarding it and passing (w, h, area, cell) still
    # matches the arity, so there would be NO TypeError and pyflakes would stay
    # clean - the aspect test would just silently become false for everything and
    # this loop would erase nothing, leaving every dot to be read as a wall.
    # 一定要保留 label 影像。_looks_like_dot 需要元件遮罩才能把數字填回去。
    # 丟掉它、改傳 (w, h, area, cell) 的話「參數個數仍然吻合」——
    # 不會有 TypeError、pyflakes 也不會抱怨，只會讓比例判斷默默永遠為假、
    # 這個迴圈一個圓點都不擦，然後每個圓點都被當成牆。
    num, labels_img, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    for i in range(1, num):
        x, y, w, h, area = stats[i]
        if not _looks_like_dot(labels_img[y : y + h, x : x + w] == i, w, h, cell):
            continue
        # Clip the erase to the disc plus a small margin, bounded by the cell.
        # The size gate admits a disc up to 0.95*cell wide; padding that by 4px
        # each side would exceed the cell and wipe out the wall sampling band -
        # producing a MISSING wall, which nothing downstream catches.
        # 擦除範圍限制在圓盤加一點邊界，且不得超過一格。
        # 尺寸判斷容許圓盤寬達 0.95*cell，四邊各加 4px 就會超過一格、
        # 把量測牆的取樣帶整個擦掉 —— 造成「少一道牆」，而且下游沒有任何東西抓得到。
        pad = int(min(4, max(0, (cell - max(w, h)) / 2)))
        cv2.rectangle(mask, (x - pad, y - pad), (x + w + pad, y + h + pad), 0, -1)

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

    dots, disc_count = find_dots(image, grid)
    h_walls, v_walls = find_walls(image, grid)
    info = [f"{grid.n}x{grid.n}", f"dots / 圓點 {len(dots)}", f"walls / 牆 {len(h_walls)}+{len(v_walls)}"]

    if len(dots) < 2:
        return failure(KEY, "fewer than 2 dots found / 編號圓點少於 2 個", grid=grid, info=info)

    # A disc we found but could not read is NOT the same as a disc that is not
    # there, and the consecutive test below cannot tell the difference: it
    # passes on any PREFIX. Twelve discs of which only 1..8 were readable looks
    # exactly like an eight-dot puzzle, and the solver then returns a full path
    # that visits the unread dots in the wrong order - a wrong route, dragged
    # with the real mouse, reported as success. Measured: img/capture.png at
    # 0.70x returned ok=True with dots 11 and 12 out of order, 3 of 3 runs.
    # 「找到但讀不出來的圓盤」跟「根本沒有那個圓盤」是兩回事，
    # 而下面的連續性檢查分不出來 —— 它對任何「前綴」都會通過。
    # 12 個圓盤只讀出 1..8 的話，看起來就跟一題 8 點的謎題一模一樣，
    # 求解器接著會給出一條把沒讀到的點走錯順序的完整路徑 ——
    # 一條錯誤路線，用真實滑鼠拖出去，而且回報成功。
    # 實測：img/capture.png 在 0.70x 會回傳 ok=True 且 11、12 順序顛倒，3/3 次重現。
    #
    # LIMIT: both numbers come from the same shape gate, so this detects exactly
    # one mode - "disc found, number unreadable". It does NOT catch a disc that
    # was never detected, nor twelve discs with twelve numbers one of which is
    # wrong. Those rely on the consecutive test and on solve_path failing.
    # 限制：這兩個數字來自同一個形狀判斷，所以它只抓得到一種情況 ——
    # 「圓盤找到了、號碼讀不出來」。它抓不到「圓盤根本沒被偵測到」，
    # 也抓不到「12 個圓盤 12 個號碼但其中一個讀錯」。
    # 那兩種要靠連續性檢查與 solve_path 失敗來擋。
    if len(dots) != disc_count:
        return failure(
            KEY,
            f"{disc_count - len(dots)} of {disc_count} dot number(s) unreadable "
            f"/ {disc_count} 個圓點中有 {disc_count - len(dots)} 個號碼讀不出來",
            grid=grid, info=info,
        )

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
