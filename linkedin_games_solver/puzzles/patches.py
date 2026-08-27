"""
Patches - tile the whole board with rectangles, one per label.
Patches —— 把整個盤面切成矩形，每個標籤一塊。

Rules 規則:
  - each rectangle contains exactly one label
  - if the label shows a number, the rectangle's area must equal it
  - if it shows NO number, the size is unconstrained
  - the label's outline dictates the allowed shape:
      solid square      -> must be square
      solid wide        -> must be a horizontal rectangle
      solid tall        -> must be a vertical rectangle
      dashed            -> any of the above
  - 每個矩形恰好包含一個標籤
  - 標籤有數字時，矩形格數必須等於該數字
  - 標籤沒有數字時，大小不限
  - 標籤外觀決定允許的形狀：實心正方形 / 實心橫向 / 實心縱向 / 虛線(任一)

Recognition notes 辨識重點:
  * Dashed labels are three translucent shapes stacked together, so their FILL
    RATIO is much lower than a solid label - that is how they are told apart.
    虛線標籤是三個半透明形狀疊起來的，填滿率明顯低於實心標籤，用這點區分。
  * Digits are read from the label's CENTRE only. See read_label_value.
    數字只從標籤正中央讀取。見 read_label_value。
"""

from __future__ import annotations

from dataclasses import dataclass, field

import cv2
import numpy as np
from ortools.sat.python import cp_model

from ..core import BoardGrid, SolveResult, build_grid, failure
from ..core import digits as digit_ocr

NAME_EN = "Patches"
NAME_ZH = "Patches (拼塊)"
KEY = "patches"

SHAPE_SQUARE, SHAPE_HORIZONTAL, SHAPE_VERTICAL, SHAPE_ANY = "square", "horizontal", "vertical", "any"
SHAPE_LABEL = {
    SHAPE_SQUARE: "square / 正方形",
    SHAPE_HORIZONTAL: "horizontal / 橫向長方形",
    SHAPE_VERTICAL: "vertical / 縱向長方形",
    SHAPE_ANY: "any / 任一形狀",
}

#: Fill ratio below this means a dashed (any-shape) label.
#: Measured: solid 0.95~0.98, dashed 0.76~0.79.
#: 填滿率低於此值代表是虛線（任一形狀）標籤。實測：實心 0.95~0.98、虛線 0.76~0.79。
DASHED_FILL_MAX = 0.87
MIN_BADGE_AREA_RATIO = 0.02

#: Digits are read from this fraction of the label, centred. Dashed labels have
#: white gaps between their stacked shapes around the edges; restricting to the
#: centre excludes them.
#: 只讀標籤正中央這個比例的範圍。虛線標籤外圍的形狀之間有白色縫隙，
#: 縮小取樣範圍就能排除掉。
DIGIT_REGION_RATIO = 0.62
#: A glyph must be at least this tall (relative to the sampled region) to be a
#: digit; gap fragments are short and stubby.
#: 字形高度至少要佔取樣範圍這個比例才算數字；縫隙碎片又小又扁。
DIGIT_MIN_HEIGHT_RATIO = 0.42


@dataclass
class PatchLabel:
    row: int
    col: int
    value: int | None          # None = no number = size unconstrained 無數字 = 大小不限
    shape: str
    bbox: tuple[int, int, int, int]
    color: tuple[int, int, int]
    #: Normalised 28x28 bitmaps of the digits found on this badge, filled in by
    #: read_label_value. Used by tools/calibrate_digits.py to rebuild templates.
    #: 這個標籤上找到的數字，正規化成 28x28 的點陣圖，由 read_label_value 填入。
    #: tools/calibrate_digits.py 用它來重建範本。
    glyphs: list = field(default_factory=list)


# ---------------------------------------------------------------------------
# Label detection 標籤偵測
# ---------------------------------------------------------------------------
def find_labels(image: np.ndarray, grid: BoardGrid) -> list[PatchLabel]:
    x0, y0, w0, h0 = grid.board_bbox
    cell = (w0 / grid.n + h0 / grid.n) / 2

    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    sat, val = hsv[:, :, 1], hsv[:, :, 2]

    # Labels are coloured, or dark (one variant is a dark slate that is not very
    # saturated); the board itself is white.
    # 標籤是彩色的，或是深色的（有一種深灰藍彩度不高）；盤面本身是白的。
    mask = ((sat > 70) | (val < 190)).astype(np.uint8)
    mask[: y0 + 2, :] = 0
    mask[y0 + h0 - 2 :, :] = 0
    mask[:, : x0 + 2] = 0
    mask[:, x0 + w0 - 2 :] = 0
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))

    num, labels_img, stats, centroids = cv2.connectedComponentsWithStats(mask, connectivity=8)
    min_area = cell * cell * MIN_BADGE_AREA_RATIO

    found: list[PatchLabel] = []
    for i in range(1, num):
        x, y, w, h, area = stats[i]
        if area < min_area or w < 8 or h < 8:
            continue
        cx, cy = centroids[i]
        row, col = int((cy - y0) / cell), int((cx - x0) / cell)
        if not (0 <= row < grid.n and 0 <= col < grid.n):
            continue

        aspect, fill = w / h, area / (w * h)
        if fill <= DASHED_FILL_MAX:
            shape = SHAPE_ANY
        elif aspect >= 1.25:
            shape = SHAPE_HORIZONTAL
        elif aspect <= 0.8:
            shape = SHAPE_VERTICAL
        else:
            shape = SHAPE_SQUARE

        component = labels_img[y : y + h, x : x + w] == i
        colored = component & (val[y : y + h, x : x + w] < 250)
        pixels = image[y : y + h, x : x + w][colored]
        color = tuple(int(v) for v in np.median(pixels, axis=0)) if len(pixels) else (0, 0, 0)

        found.append(PatchLabel(row, col, None, shape, (x, y, w, h), color))

    found.sort(key=lambda lb: (lb.row, lb.col))
    return found


def _split_wide_boxes(boxes: list[tuple[int, int, int, int, int]]) -> list[tuple[int, int, int, int, int]]:
    """Split any unusually wide box into digit-width slices.
    把異常寬的方框切成好幾片數字寬度的切片。

    CAPABILITY GAP FOUND 2026-08-26 發現的缺口: core/digits.py's own module
    docstring claims connected components support multi-digit values "such
    as Patches' 12" via split_digit_glyphs' wide-component splitting - but
    read_label_value (the only Patches caller) never called it, or
    reimplemented the same idea. Two touching digit glyphs merged into one
    connected component (a tight "12"/"16" badge at low capture resolution)
    were read as a single mis-shaped glyph, which almost always just fails
    MIN_SCORE/MIN_MARGIN (an explicit "unreadable" - safe, per this
    project's own rule, but a real capability gap the docstring promised
    was already covered). Fixed by porting split_digit_glyphs' own
    technique (same 0.62 ratio) here as its own function, rather than
    calling split_digit_glyphs directly: that function's own noise filter
    is AREA-based (>=5% of total mask), while read_label_value needs its
    HEIGHT-based filter first (applied by its caller, before this function
    ever sees the boxes) to reject dashed-label gap fragments - see
    read_label_value's own "KEY POINT" note - which split_digit_glyphs does
    not do, so the two cannot simply share one call.
    2026-08-26 發現的缺口：core/digits.py 自己的模組文件字串宣稱，連通
    元件透過 split_digit_glyphs 的「寬元件切割」支援多位數（文件字串原文
    舉的例子就是「Patches 的 12」）——但 read_label_value（唯一的 Patches
    呼叫端）從來沒有呼叫過它，也沒有自己重做一份同樣的邏輯。兩個黏在
    一起的數字字形合成一個連通元件（擷取解析度低時，很緊的「12」／「16」
    標籤）會被當成一個形狀不對的單一字形讀取，幾乎都會直接沒通過
    MIN_SCORE/MIN_MARGIN（回報「讀不出來」——依照這個專案自己的規則這是
    安全的，但文件字串承諾過已經涵蓋的能力，實際上有缺口）。修法：把
    split_digit_glyphs 自己的技巧（同樣的 0.62 比例）搬過來，獨立成自己
    的函式，而不是直接呼叫 split_digit_glyphs——因為那個函式自己的雜訊
    過濾是用「面積」（>= 總遮罩面積 5%），而 read_label_value 需要先做
    「自己的」高度過濾（由呼叫端在這個函式看到 boxes 之前就做好）來擋掉
    虛線標籤的縫隙碎片（見 read_label_value 自己的「KEY POINT」說明）——
    split_digit_glyphs 沒有這一步，所以兩者沒辦法直接共用一次呼叫。
    """
    heights = [b[3] for b in boxes]
    median_height = float(np.median(heights)) if heights else 0.0
    sliced = []
    for bx, by, bw, bh, index in boxes:
        parts = max(1, int(round(bw / (median_height * 0.62)))) if median_height > 0 else 1
        if parts <= 1:
            sliced.append((bx, by, bw, bh, index))
            continue
        step = bw // parts
        for i in range(parts):
            x0 = bx + i * step
            x1 = bx + bw if i == parts - 1 else bx + (i + 1) * step
            sliced.append((x0, by, x1 - x0, bh, index))
    return sliced


def read_label_value(image: np.ndarray, label: PatchLabel) -> tuple[int | None, bool]:
    """Read a label's number. Returns (value, has_a_number).
    讀出標籤的數字。回傳 (數值, 是否真的有數字)。

    KEY POINT - centre-only sampling plus a height filter:
      a dashed label is three translucent shapes stacked together and the white
      gaps between them used to be picked up as digit strokes. A real "4" got
      chopped into 4 fragments (unreadable) and a blank label produced 3
      fragments (reported as "has digits but unreadable"), which aborted the
      whole solve. Restricting to the centre and demanding tall glyphs fixes both.
    關鍵 —— 只取正中央並加上高度門檻：
      虛線標籤是三個半透明形狀疊起來的，形狀之間的白色縫隙以前會被當成數字筆畫。
      一個真的「4」被切成 4 塊碎片而讀不出來；空白標籤切出 3 塊碎片，被判成
      「有字但讀不出來」而中斷整個辨識。限制在中央並要求字形夠高就同時解決兩者。
    """
    x, y, w, h = label.bbox
    margin_x = int(w * (1 - DIGIT_REGION_RATIO) / 2)
    margin_y = int(h * (1 - DIGIT_REGION_RATIO) / 2)
    region = image[y + margin_y : y + h - margin_y, x + margin_x : x + w - margin_x]
    if region.size == 0:
        return None, False

    hsv = cv2.cvtColor(region, cv2.COLOR_BGR2HSV)
    mask = ((hsv[:, :, 1] < 60) & (hsv[:, :, 2] > 200)).astype(np.uint8)
    if mask.sum() == 0:
        return None, False

    num, labels_img, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    min_height = region.shape[0] * DIGIT_MIN_HEIGHT_RATIO
    boxes = [
        (stats[i][0], stats[i][1], stats[i][2], stats[i][3], i)
        for i in range(1, num)
        if stats[i][3] >= min_height
    ]
    if not boxes:
        return None, False  # no tall glyph -> this label has no number 沒有夠高的字形 -> 沒有數字

    boxes.sort(key=lambda b: b[0])
    boxes = _split_wide_boxes(boxes)

    digits = []
    label.glyphs = []
    for bx, by, bw, bh, index in boxes:
        glyph = digit_ocr.normalize_glyph(labels_img[by : by + bh, bx : bx + bw] == index)
        if glyph is None:
            return None, True
        # Keep the normalised bitmaps on the label. tools/calibrate_digits.py
        # harvests them to rebuild the template set from real screenshots.
        # 把正規化後的點陣圖留在標籤上。tools/calibrate_digits.py 會取用它們，
        # 從真實截圖重建範本集合。
        label.glyphs.append(glyph)
        # classify_glyph returns None when the runner-up digit is too close, so
        # an ambiguous glyph lands here rather than silently becoming a number.
        # 第二名的數字貼太近時 classify_glyph 會回傳 None，
        # 模稜兩可的字形因此走到這裡，而不是默默變成一個數字。
        value, score = digit_ocr.classify_glyph(glyph)
        if value is None or score < digit_ocr.MIN_SCORE:
            return None, True  # glyphs present but unreadable 有字形但認不出來
        digits.append(str(value))

    try:
        return int("".join(digits)), True
    except ValueError:
        return None, True


def classify_labels(image: np.ndarray, labels: list[PatchLabel]):
    """Split labels into (usable, unreadable). Blank labels count as usable.
    把標籤分成 (可用, 讀不出來)。空白標籤算可用（大小不限）。"""
    usable, unreadable = [], []
    for label in labels:
        value, has_digit = read_label_value(image, label)
        label.value = value
        (unreadable if (has_digit and value is None) else usable).append(label)
    return usable, unreadable


# ---------------------------------------------------------------------------
# Solver 求解
# ---------------------------------------------------------------------------
def shape_allowed(shape: str, height: int, width: int) -> bool:
    if shape == SHAPE_SQUARE:
        return height == width
    if shape == SHAPE_HORIZONTAL:
        return width > height
    if shape == SHAPE_VERTICAL:
        return height > width
    return True


def _candidate_rects(n: int, label: PatchLabel, all_labels) -> list[tuple[int, int, int, int]]:
    """Every rectangle this label could occupy.
    這個標籤所有可能的矩形。"""
    other_cells = {(lb.row, lb.col) for lb in all_labels if lb is not label}
    if label.value is None:
        sizes = [(h, w) for h in range(1, n + 1) for w in range(1, n + 1)]
    else:
        sizes = [(h, label.value // h) for h in range(1, n + 1)
                 if label.value % h == 0 and label.value // h <= n]

    rects = []
    for height, width in sizes:
        if not shape_allowed(label.shape, height, width):
            continue
        for r0 in range(max(0, label.row - height + 1), min(label.row, n - height) + 1):
            for c0 in range(max(0, label.col - width + 1), min(label.col, n - width) + 1):
                cells = [(r, c) for r in range(r0, r0 + height) for c in range(c0, c0 + width)]
                if any(pos in other_cells for pos in cells):
                    continue
                rects.append((r0, c0, height, width))
    return rects


def _build_model(n: int, labels):
    model = cp_model.CpModel()
    choices, options = [], []
    for label in labels:
        rects = _candidate_rects(n, label, labels)
        if not rects:
            return None, None, None
        variables = [model.NewBoolVar(f"r{label.row}_{label.col}_{i}") for i in range(len(rects))]
        model.AddExactlyOne(variables)
        choices.append(variables)
        options.append(rects)

    # Exact cover: every cell belongs to exactly one rectangle.
    # 精確覆蓋：每個格子恰好被一個矩形覆蓋。
    covering = {(r, c): [] for r in range(n) for c in range(n)}
    for variables, rects in zip(choices, options):
        for var, (r0, c0, height, width) in zip(variables, rects):
            for r in range(r0, r0 + height):
                for c in range(c0, c0 + width):
                    covering[(r, c)].append(var)
    for vars_covering in covering.values():
        model.AddExactlyOne(vars_covering)
    return model, choices, options


def solve_tiling(n: int, labels) -> list[tuple[int, int, int, int]] | None:
    model, choices, options = _build_model(n, labels)
    if model is None:
        return None
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 30.0
    solver.parameters.num_workers = 8
    if solver.Solve(model) not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return None
    return [next(r for v, r in zip(vs, rects) if solver.Value(v)) for vs, rects in zip(choices, options)]


def solve_tiling_unique(n: int, labels) -> list[tuple[int, int, int, int]] | None:
    """Only return a tiling if it is the ONLY one.
    只有在切法唯一時才回傳答案。

    Used as a rescue when a digit cannot be read: treat that label as
    unconstrained and re-solve; if the tiling is still unique the answer does
    not depend on the missing digit and is safe to use.
    用在數字讀不出來時的救援：把該標籤當成大小不限再解一次；
    如果切法仍然唯一，代表答案跟那個讀不到的數字無關，可以安心採用。
    """
    model, choices, options = _build_model(n, labels)
    if model is None:
        return None

    class _Collector(cp_model.CpSolverSolutionCallback):
        def __init__(self):
            super().__init__()
            self.solutions = []

        def on_solution_callback(self):
            self.solutions.append(
                [next(r for v, r in zip(vs, rects) if self.Value(v)) for vs, rects in zip(choices, options)]
            )
            if len(self.solutions) >= 2:
                self.StopSearch()

    collector = _Collector()
    solver = cp_model.CpSolver()
    solver.parameters.enumerate_all_solutions = True
    solver.parameters.max_time_in_seconds = 30.0
    solver.Solve(model, collector)
    return collector.solutions[0] if len(collector.solutions) == 1 else None


def draw_overlay(image, grid: BoardGrid, labels, rects) -> np.ndarray:
    out = image.copy()
    for label, (r0, c0, height, width) in zip(labels, rects):
        x, y, _, _ = grid.cell_boxes[r0][c0]
        x2, y2, cw, ch = grid.cell_boxes[r0 + height - 1][c0 + width - 1]
        cv2.rectangle(out, (x + 4, y + 4), (x2 + cw - 4, y2 + ch - 4), label.color, 5, lineType=cv2.LINE_AA)
    return out


def solve(image: np.ndarray, n_hint: int | None = None) -> SolveResult:
    try:
        grid = build_grid(image, n_hint=n_hint)
    except ValueError as exc:
        return failure(KEY, str(exc))

    labels = find_labels(image, grid)
    info = [f"{grid.n}x{grid.n}", f"labels / 標籤 {len(labels)}"]
    if not labels:
        return failure(KEY, "no labels found / 找不到任何標籤", grid=grid, info=info)
    # A genuine Patches puzzle always has several labels. Too few usually means
    # the puzzle type was misdetected; solving anyway would produce a nonsense
    # "one giant rectangle covers the board" answer reported as success.
    # 真正的 Patches 題目一定有好幾個標籤。太少通常代表謎題類型判斷錯了；
    # 硬解會得到「用一塊大矩形蓋滿全盤」的無意義答案卻回報成功。
    if len(labels) < 3:
        return failure(
            KEY,
            f"only {len(labels)} label(s) - probably not Patches "
            f"/ 只找到 {len(labels)} 個標籤，可能不是 Patches 題目",
            grid=grid, info=info,
        )

    usable, unreadable = classify_labels(image, labels)
    if unreadable:
        where = ", ".join(f"({lb.row + 1},{lb.col + 1})" for lb in unreadable)
        relaxed = usable + unreadable
        rects = solve_tiling_unique(grid.n, relaxed)
        if rects is not None:
            info.append(f"label(s) {where} unreadable but tiling still unique / 讀不出來但切法仍唯一")
            return SolveResult(
                ok=True, puzzle_key=KEY, grid=grid, info=info,
                data={"rects": rects, "labels": relaxed},
                overlay=draw_overlay(image, grid, relaxed, rects),
            )
        return failure(
            KEY,
            f"{len(unreadable)} label(s) unreadable at {where} and tiling is ambiguous "
            f"/ 有 {len(unreadable)} 個標籤讀不出來且切法不唯一",
            grid=grid, info=info,
        )

    blank_count = sum(1 for lb in usable if lb.value is None)
    if blank_count:
        info.append(f"{blank_count} label(s) without a number / 個標籤沒有數字")

    numbered_total = sum(lb.value for lb in usable if lb.value is not None)
    if blank_count == 0 and numbered_total != grid.n * grid.n:
        return failure(
            KEY,
            f"numbers sum to {numbered_total}, board has {grid.n * grid.n} cells "
            f"/ 數字總和與格數不符",
            grid=grid, info=info,
        )
    if blank_count and numbered_total >= grid.n * grid.n:
        return failure(KEY, "numbers already fill the board / 數字總和已不小於格數", grid=grid, info=info)

    # solve_tiling_unique, NOT solve_tiling. The unique version has existed
    # since the blank-label work but was only ever reached on the unreadable
    # rescue branch above - the success path took the first tiling CP-SAT
    # happened to return.
    # 用 solve_tiling_unique，不是 solve_tiling。唯一性版本從支援空白標籤時就存在，
    # 但一直只有上面「讀不出來」的救援分支會走到 —— 成功路徑拿的是 CP-SAT
    # 剛好先找到的那一種切法。
    #
    # Measured on live_patches.png (n=7, 14 labels): blanking any one of the 7
    # numbered labels - exactly what read_label_value does when a digit fails
    # its height filter - produced a DIFFERENT tiling returned as ok=True, 7
    # times out of 7. solve_tiling_unique rejects all 7.
    # 在 live_patches.png（n=7、14 個標籤）實測：把 7 個有數字的標籤任一個變成空白 ——
    # 那正是 read_label_value 在數字沒通過高度過濾時會做的事 —— 都會產生
    # 「不同的」切法而且回報 ok=True，7 次全中。solve_tiling_unique 全部擋下。
    #
    # It is NOT conditional on blank labels, which is what the earlier analysis
    # assumed. A 6x6 with six "6" labels down the diagonal has zero blanks, its
    # numbers sum to exactly n*n, it passes both guards above, and it has four
    # legal tilings.
    # 這跟「有沒有空白標籤」無關 —— 那是先前分析的錯誤假設。
    # 6x6 對角線放六個「6」的盤面，零空白、數字總和剛好等於 n*n、
    # 通過上面兩道守門，而它有四種合法切法。
    rects = solve_tiling_unique(grid.n, usable)
    if rects is None:
        if solve_tiling(grid.n, usable) is None:
            return failure(KEY, "no valid tiling / 找不到符合規則的切法", grid=grid, info=info)
        return failure(KEY, "tiling is not unique - a label was probably misread "
                            "/ 切法不唯一，可能有標籤讀錯", grid=grid, info=info)

    return SolveResult(
        ok=True, puzzle_key=KEY, grid=grid, info=info,
        data={"rects": rects, "labels": usable},
        overlay=draw_overlay(image, grid, usable, rects),
    )
