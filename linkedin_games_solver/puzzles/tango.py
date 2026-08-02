"""
Tango - fill every cell with a sun or a moon.
Tango —— 每格填入太陽或月亮。

Rules 規則:
  - every cell holds a sun or a moon
  - no more than 2 identical symbols may be adjacent horizontally or vertically
  - every row and column has equal numbers of suns and moons
  - cells joined by "=" are the same type; cells joined by "x" are opposite
  - grey-background cells are given by the puzzle and must not change
  - 每格填太陽或月亮
  - 水平或垂直方向相鄰的同符號不得超過 2 個
  - 每列每行的太陽數與月亮數相同
  - "=" 連接的兩格同類型；"x" 連接的兩格相反
  - 灰底的格子是題目給定的，不能更改

Recognition notes 辨識重點:
  * Tango's board has NO outer border, so it is located from the faint grid
    lines rather than a contour. See _locate_board.
    Tango 的棋盤沒有外框，要靠淡淡的格線定位而不是找輪廓。見 _locate_board。
  * The "=" / "x" marks are BROWN, not neutral grey - the same hue family as the
    sun icon. See detect_edges.
    "=" / "x" 符號是棕色而不是中性灰，跟太陽同色系。見 detect_edges。
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

import cv2
import numpy as np
from ortools.sat.python import cp_model

from ..core import BoardGrid, SolveResult, build_grid_from_lines, failure
from ..core.board import build_cell_boxes, find_board_bbox

NAME_EN = "Tango"
NAME_ZH = "Tango (太陽/月亮)"
KEY = "tango"

SUN, MOON = 1, 0
SYMBOL_EMOJI = {SUN: "\U0001f7e0", MOON: "\U0001f319"}

#: LinkedIn's Tango is always 6x6. 這款遊戲的棋盤固定是 6x6。
DEFAULT_GRID_SIZE = 6

# --- Cell appearance thresholds 格內外觀門檻 -------------------------------
SATURATION_ICON_THRESHOLD = 60
ICON_MIN_PIXEL_RATIO = 0.05
ORANGE_HUE_RANGE = (5, 35)
BLUE_HUE_RANGE = (95, 135)
#: Given cells have a very pale lavender background: V ~248 vs white 255.
#: The margin is tiny, so this threshold has to sit close to pure white.
#: 題目給定格的底色是很淡的淡紫：V 約 248，白色是 255。
#: 差距很小，所以門檻必須貼近純白。
GIVEN_BG_VALUE_MAX = 253
CELL_MARGIN_RATIO = 0.08

# --- Edge mark thresholds =/x 符號門檻 -------------------------------------
PATCH_SIZE_RATIO = 0.3
FOREGROUND_MIN_AREA_RATIO = 0.03
EQUAL_ASPECT_RATIO_THRESHOLD = 1.8
GRIDLINE_SPAN_RATIO = 0.75
GRIDLINE_THICKNESS_RATIO = 0.3
#: A pixel must be this much darker than the local background to count as a mark.
#: 像素要比周圍背景暗這麼多才算符號筆畫。
SYMBOL_DARKNESS_MARGIN = 40


@dataclass
class TangoPuzzle:
    n: int
    givens: dict[tuple[int, int], int] = field(default_factory=dict)
    h_edges: dict[tuple[int, int], str] = field(default_factory=dict)  # (r,c)|(r,c+1)
    v_edges: dict[tuple[int, int], str] = field(default_factory=dict)  # (r,c)|(r+1,c)


class NoSolution(RuntimeError):
    pass


class MultipleSolutions(RuntimeError):
    pass


# ---------------------------------------------------------------------------
# Cell reading 讀格內容
# ---------------------------------------------------------------------------
@dataclass
class CellReading:
    symbol: int | None  # SUN / MOON / None
    given: bool


def read_cell(image: np.ndarray, box: tuple[int, int, int, int]) -> CellReading:
    x, y, w, h = box
    mx, my = int(w * CELL_MARGIN_RATIO), int(h * CELL_MARGIN_RATIO)
    cell = image[y + my : y + h - my, x + mx : x + w - mx]
    if cell.size == 0:
        return CellReading(None, False)

    hsv = cv2.cvtColor(cell, cv2.COLOR_BGR2HSV)
    hue, sat, val = hsv[:, :, 0], hsv[:, :, 1], hsv[:, :, 2]

    icon_mask = sat > SATURATION_ICON_THRESHOLD
    background = ~icon_mask
    # Median, not mean: an edge mark bleeding in from the cell boundary would
    # drag a mean down and make an ordinary white cell look like a given cell.
    # 用中位數而非平均：邊界上的 =/× 符號侵入格子邊緣時會把平均拉低，
    # 讓普通白格看起來像題目給定的灰底格。
    bg_value = float(np.median(val[background])) if background.any() else float(np.median(val))
    given = bg_value < GIVEN_BG_VALUE_MAX

    if icon_mask.mean() < ICON_MIN_PIXEL_RATIO:
        return CellReading(None, given)

    mean_hue = float(hue[icon_mask].mean())
    if ORANGE_HUE_RANGE[0] <= mean_hue <= ORANGE_HUE_RANGE[1]:
        return CellReading(SUN, given)
    if BLUE_HUE_RANGE[0] <= mean_hue <= BLUE_HUE_RANGE[1]:
        return CellReading(MOON, given)
    orange_center = sum(ORANGE_HUE_RANGE) / 2
    blue_center = sum(BLUE_HUE_RANGE) / 2
    closer_to_orange = abs(mean_hue - orange_center) < abs(mean_hue - blue_center)
    return CellReading(SUN if closer_to_orange else MOON, given)


# ---------------------------------------------------------------------------
# Edge marks =/x 符號
# ---------------------------------------------------------------------------
def _is_gridline(w: int, h: int, patch_w: int, patch_h: int, orientation: str) -> bool:
    if orientation == "h":
        return h >= patch_h * GRIDLINE_SPAN_RATIO and w <= patch_w * GRIDLINE_THICKNESS_RATIO
    return w >= patch_w * GRIDLINE_SPAN_RATIO and h <= patch_h * GRIDLINE_THICKNESS_RATIO


def _is_centered(x, y, w, h, patch_w, patch_h) -> bool:
    cx, cy = x + w / 2, y + h / 2
    return abs(cx - patch_w / 2) <= patch_w * 0.15 and abs(cy - patch_h / 2) <= patch_h * 0.15


def _classify_mark(patch: np.ndarray, orientation: str) -> str | None:
    """Return "=", "x" or None for a small patch straddling a cell boundary.
    對跨在格子交界處的小區塊回傳 "="、"x" 或 None。

    KEY POINT - use HSV Value, not greyscale luminance:
      the marks are BROWN (V~148), the same hue family as the sun icon and with
      similar saturation. An earlier version filtered out "colourful" pixels to
      avoid icon bleed and thereby erased the marks themselves. Value separates
      them cleanly: background 248~255, icons 233~234, marks ~148.
    關鍵 —— 用 HSV 的明度而不是灰階亮度：
      符號是棕色（V 約 148），跟太陽同色系、飽和度也不低。先前的版本為了避免
      圖示干擾而濾掉「彩色」像素，結果把符號本身也濾掉了。改用明度就分得很乾淨：
      背景 248~255、圖示 233~234、符號約 148。
    """
    if patch.size == 0:
        return None
    patch_h, patch_w = patch.shape[:2]
    value = cv2.cvtColor(patch, cv2.COLOR_BGR2HSV)[:, :, 2]

    # Absolute margin below the local background, NOT Otsu: Otsu always finds a
    # split even on a blank patch, inventing marks out of noise.
    # 用「比背景暗固定幅度」而不是 Otsu：Otsu 在一片空白上也會硬找出切點，
    # 把雜訊變成不存在的符號。
    threshold = float(np.median(value)) - SYMBOL_DARKNESS_MARGIN
    _, binary = cv2.threshold(value, threshold, 255, cv2.THRESH_BINARY_INV)

    # Erode away the 1px grid line so it cannot bridge the two bars of "=".
    # 用開運算侵蝕掉 1px 的格線，避免它把 "=" 的兩條橫槓橋接成一塊。
    binary = cv2.morphologyEx(binary, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3)))

    total_area = patch_w * patch_h
    contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    boxes = [cv2.boundingRect(c) for c in contours if cv2.contourArea(c) > total_area * 0.01]
    if not boxes:
        return None

    # A single thin, centred, spanning contour is just the grid line.
    # 單一、細、置中且貫穿整塊的輪廓只是格線而已。
    if len(boxes) == 1:
        x, y, w, h = boxes[0]
        if _is_gridline(w, h, patch_w, patch_h, orientation) and _is_centered(x, y, w, h, patch_w, patch_h):
            return None

    if sum(w * h for _, _, w, h in boxes) < total_area * FOREGROUND_MIN_AREA_RATIO:
        return None

    ratios = [max(w / h, h / w) for _, _, w, h in boxes if h > 0]
    if not ratios:
        return None
    # "=" is two flat bars (high aspect); "x" is two crossing strokes (~square).
    # "=" 是兩條扁平橫槓（長寬比大）；"x" 是交叉的兩條線（接近正方形）。
    return "=" if sum(ratios) / len(ratios) >= EQUAL_ASPECT_RATIO_THRESHOLD else "x"


def _square_patch(image, cx, cy, size):
    half = size // 2
    h, w = image.shape[:2]
    return image[max(0, cy - half) : min(h, cy + half), max(0, cx - half) : min(w, cx + half)]


def detect_edges(image: np.ndarray, grid: BoardGrid):
    """Find all "=" / "x" marks between adjacent cells.
    找出所有相鄰格之間的 "=" / "x" 符號。"""
    h_edges, v_edges = {}, {}
    for r in range(grid.n):
        for c in range(grid.n - 1):
            x, y, w, h = grid.cell_boxes[r][c]
            size = max(int(w * PATCH_SIZE_RATIO) or 1, 8)
            mark = _classify_mark(_square_patch(image, x + w, y + h // 2, size), "h")
            if mark:
                h_edges[(r, c)] = mark
    for r in range(grid.n - 1):
        for c in range(grid.n):
            x, y, w, h = grid.cell_boxes[r][c]
            size = max(int(h * PATCH_SIZE_RATIO) or 1, 8)
            mark = _classify_mark(_square_patch(image, x + w // 2, y + h, size), "v")
            if mark:
                v_edges[(r, c)] = mark
    return h_edges, v_edges


# ---------------------------------------------------------------------------
# Solver 求解
# ---------------------------------------------------------------------------
def solve_puzzle(puzzle: TangoPuzzle, require_unique: bool = True) -> list[list[int]]:
    """Solve, raising NoSolution / MultipleSolutions.
    求解，無解或多解時丟出對應例外。"""
    n = puzzle.n
    model = cp_model.CpModel()
    cells = [[model.NewBoolVar(f"c_{r}_{c}") for c in range(n)] for r in range(n)]

    for (r, c), value in puzzle.givens.items():
        model.Add(cells[r][c] == value)

    # No 3 in a row, in both directions: any window of 3 must contain both types.
    # 不可三連（兩個方向）：任意連續 3 格必須同時含有兩種符號。
    for r in range(n):
        for c in range(n - 2):
            trio = [cells[r][c], cells[r][c + 1], cells[r][c + 2]]
            model.Add(sum(trio) <= 2)
            model.Add(sum(trio) >= 1)
    for c in range(n):
        for r in range(n - 2):
            trio = [cells[r][c], cells[r + 1][c], cells[r + 2][c]]
            model.Add(sum(trio) <= 2)
            model.Add(sum(trio) >= 1)

    half = n // 2
    for r in range(n):
        model.Add(sum(cells[r]) == half)
    for c in range(n):
        model.Add(sum(cells[r][c] for r in range(n)) == half)

    for (r, c), mark in puzzle.h_edges.items():
        a, b = cells[r][c], cells[r][c + 1]
        model.Add(a == b) if mark == "=" else model.Add(a != b)
    for (r, c), mark in puzzle.v_edges.items():
        a, b = cells[r][c], cells[r + 1][c]
        model.Add(a == b) if mark == "=" else model.Add(a != b)

    solver = cp_model.CpSolver()

    if not require_unique:
        solver.parameters.randomize_search = True
        solver.parameters.random_seed = random.randint(0, 2**31 - 1)
        if solver.Solve(model) not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            raise NoSolution("no solution / 找不到符合規則的解")
        return [[int(solver.Value(cells[r][c])) for c in range(n)] for r in range(n)]

    collector = _SolutionCollector(cells, limit=2)
    solver.parameters.enumerate_all_solutions = True
    status = solver.Solve(model, collector)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE) or not collector.solutions:
        raise NoSolution("no solution / 找不到符合規則的解")
    if len(collector.solutions) > 1:
        raise MultipleSolutions("multiple solutions / 找到多組解")
    return collector.solutions[0]


class _SolutionCollector(cp_model.CpSolverSolutionCallback):
    def __init__(self, cells, limit=2):
        super().__init__()
        self._cells = cells
        self._limit = limit
        self.solutions: list[list[list[int]]] = []

    def on_solution_callback(self):
        n = len(self._cells)
        self.solutions.append([[self.Value(self._cells[r][c]) for c in range(n)] for r in range(n)])
        if len(self.solutions) >= self._limit:
            self.StopSearch()


def format_grid(solution) -> list[str]:
    return [" ".join(SYMBOL_EMOJI[v] for v in row) for row in solution]


# ---------------------------------------------------------------------------
# Drawing 疊圖
# ---------------------------------------------------------------------------
def _sample_bg_color(image, x, y, w, h):
    """Background colour of a cell, excluding the icon.
    格子的背景色，排除圖示本身。

    Sampled from inside the cell (not the corner) because the corner of an edge
    cell catches the thick board border and would produce a dark blob.
    取樣點在格子內側而非角落：邊緣格的角落會取到粗黑外框，畫出來會是一塊黑斑。
    """
    mx, my = max(4, w // 6), max(4, h // 6)
    inner = image[y + my : y + h - my, x + mx : x + w - mx]
    if inner.size == 0:
        return (255, 255, 255)
    hsv = cv2.cvtColor(inner, cv2.COLOR_BGR2HSV)
    background = hsv[:, :, 1] <= 60
    pixels = inner.reshape(-1, 3)
    chosen = pixels[background.reshape(-1)] if background.any() else pixels
    median = np.median(chosen, axis=0)
    return (int(median[0]), int(median[1]), int(median[2]))


def _draw_sun(img, center, radius, color):
    cx, cy = center
    ray_len, gap = max(3, int(radius * 0.55)), max(2, int(radius * 0.25))
    thickness = max(2, radius // 5)
    for angle_deg in range(0, 360, 45):
        angle = np.deg2rad(angle_deg)
        p0 = (int(cx + (radius + gap) * np.cos(angle)), int(cy + (radius + gap) * np.sin(angle)))
        p1 = (int(cx + (radius + gap + ray_len) * np.cos(angle)),
              int(cy + (radius + gap + ray_len) * np.sin(angle)))
        cv2.line(img, p0, p1, color, thickness, lineType=cv2.LINE_AA)
    cv2.circle(img, (cx, cy), radius, color, -1, lineType=cv2.LINE_AA)
    cv2.circle(img, (cx, cy), radius, (60, 90, 160), 1, lineType=cv2.LINE_AA)


def _draw_moon(img, center, radius, color, bg_color):
    cx, cy = center
    cv2.circle(img, (cx, cy), radius, color, -1, lineType=cv2.LINE_AA)
    # Carve a crescent by painting an offset circle in the background colour.
    # 用背景色畫一個偏移的圓「挖」出弦月形狀。
    offset = int(radius * 0.55)
    cv2.circle(img, (cx + offset, cy - offset // 2), int(radius * 0.82), bg_color, -1, lineType=cv2.LINE_AA)
    cv2.circle(img, (cx, cy), radius, (150, 90, 30), 1, lineType=cv2.LINE_AA)


VALUE_TO_COLOR = {SUN: (0, 140, 255), MOON: (200, 120, 30)}


def draw_overlay(image, grid: BoardGrid, solution, current) -> np.ndarray:
    out = image.copy()
    for r in range(grid.n):
        for c in range(grid.n):
            x, y, w, h = grid.cell_boxes[r][c]
            target = solution[r][c]
            if current.get((r, c)) == target:
                continue
            radius = max(8, min(w, h) // 4)
            bg = _sample_bg_color(image, x, y, w, h)
            if current.get((r, c)) is not None:
                cv2.rectangle(out, (x + 2, y + 2), (x + w - 2, y + h - 2), (0, 0, 255), 3)
            if target == SUN:
                _draw_sun(out, grid.cell_center(r, c), radius, VALUE_TO_COLOR[SUN])
            else:
                _draw_moon(out, grid.cell_center(r, c), radius, VALUE_TO_COLOR[MOON], bg)
    return out


# ---------------------------------------------------------------------------
# Entry point 入口
# ---------------------------------------------------------------------------
def _locate_board(image: np.ndarray, n: int) -> BoardGrid | None:
    """Locate Tango's borderless board.
    定位 Tango 沒有外框的棋盤。

    KEY POINT: grid lines first, contour second.
      Tango draws no board border, so an earlier version inferred the grid from
      where the sun/moon icons sat. On the smaller web board the icons do not
      span every column and the inferred lattice landed one column off - every
      given shifted, and the "=" marks (drawn in the outermost columns) fell
      outside the board entirely, leaving the puzzle under-constrained.
    關鍵：先用格線，再退回輪廓。
      Tango 沒有棋盤外框，先前的版本改用「太陽/月亮圖示的位置」反推格線。
      在較小的網頁棋盤上圖示不會佈滿每一欄，反推出來的網格整個偏了一欄 ——
      所有 given 位置跟著位移，而畫在最外圈欄位的 "=" 符號完全落在棋盤外，
      題目條件因此不足。
    """
    grid = build_grid_from_lines(image, n)
    if grid is not None:
        return grid
    bbox = find_board_bbox(image)
    if bbox is None:
        return None
    return BoardGrid(n=n, board_bbox=bbox, cell_boxes=build_cell_boxes(bbox, n))


def read_board(image: np.ndarray, grid: BoardGrid):
    """Read givens, current state and edge marks from a located board.
    從定位好的棋盤讀出 given、目前狀態與 =/x 符號。"""
    givens, current = {}, {}
    for r in range(grid.n):
        for c in range(grid.n):
            reading = read_cell(image, grid.cell_boxes[r][c])
            current[(r, c)] = reading.symbol
            if reading.given and reading.symbol is not None:
                givens[(r, c)] = reading.symbol
    h_edges, v_edges = detect_edges(image, grid)
    return TangoPuzzle(n=grid.n, givens=givens, h_edges=h_edges, v_edges=v_edges), current


def solve(image: np.ndarray, n_hint: int | None = None) -> SolveResult:
    n = n_hint or DEFAULT_GRID_SIZE
    grid = _locate_board(image, n)
    if grid is None:
        return failure(KEY, "board not found / 偵測不到棋盤位置")

    puzzle, current = read_board(image, grid)
    info = [
        f"{grid.n}x{grid.n}",
        f"givens {len(puzzle.givens)}, marks / 符號 {len(puzzle.h_edges) + len(puzzle.v_edges)}",
    ]

    try:
        # Insist on a UNIQUE solution. A real Tango puzzle has exactly one; if
        # recognition missed a given or a mark the remaining constraints usually
        # admit many, and the solver would happily return one of them - a wrong
        # answer reported as success, which is worse than an outright failure.
        # Failing here lets the caller retry at another crop/scale.
        # 這裡刻意要求「解必須唯一」。真正的 Tango 題目只有一組解；如果辨識漏掉
        # given 或符號，剩下的條件通常允許很多組解，求解器會吐出其中一組 ——
        # 那是「悄悄給錯答案」，比直接失敗更糟。在這裡失敗可以讓呼叫端換個
        # 裁切/縮放再試。
        solution = solve_puzzle(puzzle, require_unique=True)
    except (NoSolution, MultipleSolutions) as exc:
        return failure(KEY, str(exc), grid=grid, info=info)

    return SolveResult(
        ok=True, puzzle_key=KEY, grid=grid, info=info,
        data={"solution": solution, "givens": set(puzzle.givens), "current": current},
        overlay=draw_overlay(image, grid, solution, current),
    )
