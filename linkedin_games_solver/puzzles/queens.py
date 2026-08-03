"""
Queens - place one crown per row, per column and per colour region.
Queens —— 每行、每列、每個色塊區域各放一個皇后。

Rules 規則:
  - exactly one crown in every row, every column and every colour region
  - no two crowns may touch, not even diagonally
  - 每行、每列、每個色塊區域恰好一個皇后
  - 任兩個皇后不能相鄰，包含對角線

Recognition notes 辨識重點:
  * Region colours are read from a ring inside each cell, EXCLUDING dark pixels,
    because a crown or an X mark sits in the middle of the cell and would
    otherwise be sampled as the region colour.
    色塊顏色取自格子內側並排除深色像素 —— 因為皇冠或 X 標記就在格子正中央，
    否則會把圖案顏色當成色塊顏色。
  * Cells are grouped into exactly n colours by frequency, NOT by a fixed colour
    tolerance. See read_regions for why.
    格子依「出現次數」分成剛好 n 種顏色，而不是用固定色差容忍度。原因見 read_regions。
"""

from __future__ import annotations

import cv2
import numpy as np
from ortools.sat.python import cp_model

from ..core import BoardGrid, SolveResult, build_grid, failure

NAME_EN = "Queens"
NAME_ZH = "Queens (皇后)"
KEY = "queens"

# --- Cell sampling 取樣參數 -------------------------------------------------
#: Inset used when sampling a cell's colour. 取色塊顏色時往內縮的比例。
CELL_INSET_RATIO = 0.14
#: Pixels darker than this are a crown or X mark, not the region colour.
#: 比這更暗的像素是皇冠或 X 標記，不是色塊顏色。
DARK_ICON_VALUE_MAX = 110
#: Colours within this distance count as "the same flat colour".
#: 色差在此範圍內視為「同一種平面色」。
SAME_COLOR_EPSILON = 10

# --- Cell state detection 格內狀態偵測 --------------------------------------
#: Inset used when detecting the icon. Deeper than the colour inset so the dark
#: grid lines and board border are excluded - they otherwise register as an icon.
#: 偵測圖示時往內縮的比例。比取色時更深，才能排除深色格線與棋盤外框
#: （否則它們會被算成圖示）。
#: Calibrated on real web captures: crown 0.268~0.374, empty exactly 0.000.
#: 用真實網頁畫面校準：皇冠 0.268~0.374、空白剛好 0.000。
ICON_INSET_RATIO = 0.28
QUEEN_DARK_RATIO_MIN = 0.20
X_MARK_DARK_RATIO_MIN = 0.04

STATE_QUEEN = "queen"
STATE_X = "x"


def _cell_pixels(image: np.ndarray, box: tuple[int, int, int, int], inset: float = CELL_INSET_RATIO):
    x, y, w, h = box
    ix, iy = int(w * inset), int(h * inset)
    return image[y + iy : y + h - iy, x + ix : x + w - ix]


# ---------------------------------------------------------------------------
# Colour regions 色塊區域
# ---------------------------------------------------------------------------
def cell_colors(image: np.ndarray, grid: BoardGrid) -> np.ndarray:
    """Representative colour of every cell, ignoring any crown / X mark.
    每格的代表色，忽略皇冠與 X 標記。"""
    colors = []
    for r in range(grid.n):
        for c in range(grid.n):
            cell = _cell_pixels(image, grid.cell_boxes[r][c])
            if cell.size == 0:
                colors.append(np.zeros(3))
                continue
            hsv = cv2.cvtColor(cell, cv2.COLOR_BGR2HSV)
            keep = hsv[:, :, 2] > DARK_ICON_VALUE_MAX
            pixels = cell[keep] if keep.sum() >= 20 else cell.reshape(-1, 3)
            colors.append(np.median(pixels, axis=0))
    return np.array(colors, dtype=np.float32)


def read_regions(image: np.ndarray, grid: BoardGrid):
    """Assign every cell to one of exactly n colour regions.
    把每一格分到剛好 n 個色塊區域之一。

    WHY frequency grouping instead of a colour tolerance:
      the web palette is much closer together than the mobile one - measured
      blue(165,187,246) vs purple(182,158,219) differ by only 29, and
      taupe(182,178,161) vs pink(204,155,188) by 27. A tolerance loose enough to
      absorb hover shading merges those pairs; a tight one splits a region when
      the mouse darkens one cell. Since the number of regions always equals the
      board size, taking the n most frequent flat colours sidesteps the problem.
    為什麼用「出現次數」分群而不是色差容忍度：
      網頁版的配色比手機版接近很多 —— 實測 藍(165,187,246) 與 紫(182,158,219)
      只差 29、米灰(182,178,161) 與 粉(204,155,188) 只差 27。容忍度放寬到能吸收
      滑鼠 hover 造成的深淺變化，就會把這兩組併掉；收緊又會因為 hover 把一區
      拆成兩塊。既然區域數一定等於棋盤格數，直接取「出現次數最多的 n 種平面色」
      就完全避開這個兩難。

      k-means was tried and rejected: its random initial centres made the same
      board sometimes succeed and sometimes split a region, i.e. not reproducible.
      曾經改用 k-means 但放棄：它的初始中心是隨機的，同一個盤面有時正常、
      有時把某一區切成兩塊，結果不可重現。
    """
    n = grid.n
    colors = cell_colors(image, grid)

    groups: list[list[np.ndarray]] = []
    for color in colors:
        for group in groups:
            if np.abs(group[0] - color).max() <= SAME_COLOR_EPSILON:
                group.append(color)
                break
        else:
            groups.append([color])

    groups.sort(key=len, reverse=True)
    centers = [np.median(np.array(g), axis=0) for g in groups[:n]]

    region_ids = [[0] * n for _ in range(n)]
    for index, color in enumerate(colors):
        distances = [np.abs(center - color).max() for center in centers]
        region_ids[index // n][index % n] = int(np.argmin(distances))

    palette = [tuple(int(v) for v in center) for center in centers]
    return region_ids, palette


def _regions_are_connected(region_ids: list[list[int]], n: int) -> bool:
    """Every colour region in Queens is one contiguous blob.
    Queens 的每個色塊區域都是連在一起的一塊。"""
    for target in range(n):
        cells = [(r, c) for r in range(n) for c in range(n) if region_ids[r][c] == target]
        if not cells:
            return False
        seen, stack = {cells[0]}, [cells[0]]
        while stack:
            r, c = stack.pop()
            for dr, dc in ((0, 1), (0, -1), (1, 0), (-1, 0)):
                nb = (r + dr, c + dc)
                if nb in seen:
                    continue
                if 0 <= nb[0] < n and 0 <= nb[1] < n and region_ids[nb[0]][nb[1]] == target:
                    seen.add(nb)
                    stack.append(nb)
        if len(seen) != len(cells):
            return False
    return True


def regions_look_valid(region_ids: list[list[int]], n: int) -> bool:
    """Sanity check: n non-empty, contiguous regions.
    合理性檢查：n 個非空且連通的區域。"""
    used = {region_ids[r][c] for r in range(n) for c in range(n)}
    return len(used) == n and _regions_are_connected(region_ids, n)


# ---------------------------------------------------------------------------
# Current board state 目前盤面狀態
# ---------------------------------------------------------------------------
def read_cell_states(image: np.ndarray, grid: BoardGrid) -> dict[tuple[int, int], str]:
    """What is currently drawn in each cell: crown / X / (absent = empty).
    每格目前畫了什麼：皇冠 / X /（沒列出 = 空白）。

    This is what makes "resume a half-finished board" and "verify after filling"
    possible - we need to know the current state to compute how many more clicks
    a cell needs.
    這是「接續填一半的盤面」與「填完後驗證補點」的基礎 ——
    要知道目前狀態才能算出某一格還要再點幾下。
    """
    states: dict[tuple[int, int], str] = {}
    for r in range(grid.n):
        for c in range(grid.n):
            cell = _cell_pixels(image, grid.cell_boxes[r][c], inset=ICON_INSET_RATIO)
            if cell.size == 0:
                continue
            hsv = cv2.cvtColor(cell, cv2.COLOR_BGR2HSV)
            dark_ratio = float((hsv[:, :, 2] <= DARK_ICON_VALUE_MAX).mean())
            if dark_ratio >= QUEEN_DARK_RATIO_MIN:
                states[(r, c)] = STATE_QUEEN
            elif dark_ratio >= X_MARK_DARK_RATIO_MIN:
                states[(r, c)] = STATE_X
    return states


def clicks_needed(state: str | None) -> int:
    """Clicks to turn a cell into a crown (cycle: empty -> X -> crown).
    要把一格變成皇冠還需要點幾下（循環：空白 -> X -> 皇冠）。"""
    if state == STATE_QUEEN:
        return 0
    if state == STATE_X:
        return 1
    return 2


# ---------------------------------------------------------------------------
# Solver 求解
# ---------------------------------------------------------------------------
#: Wall-clock cap for the crown search. Every other solver in the project has
#: one; this was the only solver with no bound at all.
#: 皇冠搜尋的時間上限。專案裡其他求解器都有；這裡原本是唯一完全沒有上限的。
SOLVE_TIME_LIMIT = 20.0


def solve_positions(n: int, region_ids: list[list[int]], require_unique: bool = True):
    """Constraint-solve the crown positions.
    用約束求解算出皇后位置。

    require_unique is the guard this solver was missing entirely.
    require_unique 是這個求解器原本完全沒有的守門。

    Queens was the only puzzle with no uniqueness check. A published board has
    exactly one crown layout, so a SECOND layout means the colour regions were
    misread - and unlike a missing region or a non-contiguous one, a misread
    that still yields n contiguous regions passes regions_look_valid() and
    every check downstream.
    Queens 是唯一沒有唯一性檢查的謎題。出版的盤面只有一種皇冠佈局，
    所以找得到「第二種」就代表色塊被讀錯了 —— 而且跟「少一塊」或「不連通」不同，
    一個仍然產生 n 塊連通色塊的誤讀，會通過 regions_look_valid() 與下游每一道檢查。

    Measured on live_queens_2.png (n=9, genuinely unique): moving ONE cell into
    an orthogonally adjacent region gives 7 perturbations that still pass
    regions_look_valid AND change the answer, 6 of which have more than one
    solution. Nothing downstream catches it: automation/verify.py accepts 85%
    region agreement, so a 1-in-81 misread is 1.2% and passes, and the verifier
    then only asks whether the crowns IT chose are present - so the wrong
    layout is clicked and reported "9/9 correct".
    在 live_queens_2.png（n=9，本身唯一）實測：把「一格」移到正交相鄰的色塊，
    有 7 種擾動仍然通過 regions_look_valid 而且改變了答案，其中 6 種有多組解。
    下游沒有任何東西攔得住：automation/verify.py 接受 85% 的色塊吻合度，
    所以 81 分之 1 的誤讀只有 1.2%、直接通過，而驗證器接著只問
    「它自己選的那些皇冠在不在」—— 於是錯誤佈局被點下去，還回報「9/9 正確」。
    """
    model = cp_model.CpModel()
    cells = [[model.NewBoolVar(f"q_{r}_{c}") for c in range(n)] for r in range(n)]

    for r in range(n):
        model.AddExactlyOne(cells[r])
    for c in range(n):
        model.AddExactlyOne(cells[r][c] for r in range(n))

    regions: dict[int, list] = {}
    for r in range(n):
        for c in range(n):
            regions.setdefault(region_ids[r][c], []).append(cells[r][c])
    for vars_in_region in regions.values():
        model.AddExactlyOne(vars_in_region)

    # No two crowns adjacent, including diagonally.
    # 任兩個皇后不能相鄰（含對角線）。
    for r in range(n):
        for c in range(n):
            for dr, dc in ((0, 1), (1, 0), (1, 1), (1, -1)):
                nr, nc = r + dr, c + dc
                if 0 <= nr < n and 0 <= nc < n:
                    model.AddAtMostOne([cells[r][c], cells[nr][nc]])

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = SOLVE_TIME_LIMIT

    if not require_unique:
        if solver.Solve(model) not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            return None
        return [(r, c) for r in range(n) for c in range(n) if solver.Value(cells[r][c])]

    # Enumerate, stopping at two. Two layouts means a region was misread.
    # 列舉，找到兩組就停。有兩種佈局就代表某個色塊被讀錯了。
    class _Collector(cp_model.CpSolverSolutionCallback):
        def __init__(self):
            super().__init__()
            self.found = []

        def on_solution_callback(self):
            self.found.append([(r, c) for r in range(n) for c in range(n)
                               if self.Value(cells[r][c])])
            if len(self.found) >= 2:
                self.StopSearch()

    collector = _Collector()
    solver.parameters.enumerate_all_solutions = True
    solver.Solve(model, collector)
    if len(collector.found) != 1:
        return None
    return collector.found[0]


# ---------------------------------------------------------------------------
# Drawing 疊圖
# ---------------------------------------------------------------------------
def _draw_crown(image, center, size, color=(0, 0, 0)):
    cx, cy = center
    half = size // 2
    points = np.array(
        [
            [cx - half, cy - half // 2], [cx - half // 2, cy], [cx, cy - half],
            [cx + half // 2, cy], [cx + half, cy - half // 2],
            [cx + half, cy + half // 2], [cx - half, cy + half // 2],
        ],
        dtype=np.int32,
    )
    cv2.fillPoly(image, [points], color, lineType=cv2.LINE_AA)
    cv2.polylines(image, [points], True, (255, 255, 255), 2, lineType=cv2.LINE_AA)


def draw_overlay(image, grid: BoardGrid, queens) -> np.ndarray:
    out = image.copy()
    for r, c in queens:
        x, y, w, h = grid.cell_boxes[r][c]
        _draw_crown(out, grid.cell_center(r, c), max(14, min(w, h) // 2))
        cv2.rectangle(out, (x + 3, y + 3), (x + w - 3, y + h - 3), (0, 0, 0), 3)
    return out


# ---------------------------------------------------------------------------
# Entry point 入口
# ---------------------------------------------------------------------------
def solve(image: np.ndarray, n_hint: int | None = None) -> SolveResult:
    try:
        grid = build_grid(image, n_hint=n_hint)
    except ValueError as exc:
        return failure(KEY, str(exc))

    region_ids, palette = read_regions(image, grid)
    info = [f"{grid.n}x{grid.n}", f"regions / 色塊區域: {len(palette)}"]

    if not regions_look_valid(region_ids, grid.n):
        return failure(
            KEY,
            "colour grouping looks wrong (empty or split region) "
            "/ 色塊分群結果不合理（有區域是空的或被切成不相連的兩塊）",
            grid=grid, info=info,
        )

    queens = solve_positions(grid.n, region_ids)
    if queens is None:
        # Distinguish the two ways this fails - they mean different things to
        # the user. No solution at all means the regions are wrong in a way that
        # makes the puzzle impossible; more than one means the regions are wrong
        # in a way that still looks legal, which is the dangerous case.
        # 區分兩種失敗方式 —— 對使用者的意義不同。完全無解代表色塊錯到讓謎題
        # 不可能成立；多組解代表色塊錯得「看起來仍然合法」，那才是危險的情況。
        if solve_positions(grid.n, region_ids, require_unique=False) is None:
            return failure(KEY, "no solution / 找不到符合規則的解", grid=grid, info=info)
        return failure(KEY, "more than one crown layout fits - a colour region was "
                            "misread / 有多種皇冠佈局都成立，代表色塊讀錯了",
                       grid=grid, info=info)

    states = read_cell_states(image, grid)
    already = {pos for pos, s in states.items() if s == STATE_QUEEN}
    if already:
        info.append(f"already placed / 畫面上已放置: {len(already)}")

    return SolveResult(
        ok=True, puzzle_key=KEY, grid=grid, info=info,
        data={
            "queens": queens,
            "cell_states": states,
            "already_placed": already,
            # Kept so the automation layer can confirm the board has not changed
            # after filling (see automation/verify.py).
            # 保留下來讓自動化層在填完後確認盤面沒變（見 automation/verify.py）。
            "region_ids": region_ids,
        },
        overlay=draw_overlay(image, grid, queens),
    )
