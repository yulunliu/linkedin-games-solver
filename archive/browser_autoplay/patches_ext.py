"""
Patches 的擴充：支援「沒有數字的標籤」。

規則原文：「如果形狀內標有數字，則其大小必須與該數字相符。」
反過來說，**沒有標數字的標籤代表大小不限**，只受形狀型別 (正方形 / 縱向 /
橫向 / 任一) 限制。

既有專案的 `puzzle_patches` 要求每個標籤都要有數字，遇到空白標籤會直接報錯
(而使用者實際遇到的題目就有空白標籤)。這裡在不修改既有專案的前提下，
擴充成允許 value=None 的標籤。

怎麼分辨「空白標籤」與「數字讀不出來」：
  `puzzle_patches.find_labels` 會把切出來的字形放在 label.glyphs。
  - glyphs 是空的  -> 標籤裡本來就沒有數字 (空白標籤)
  - glyphs 有東西但 value 是 None -> 真的讀不出來，這是辨識失敗要回報
"""

from ortools.sat.python import cp_model

import solver_bridge  # noqa: F401  匯入時會把 tango_solver 加進 sys.path

import puzzle_patches  # noqa: E402
from puzzle_patches import (  # noqa: E402
    SHAPE_ANY,
    SHAPE_HORIZONTAL,
    SHAPE_SQUARE,
    SHAPE_VERTICAL,
    _shape_allowed,
)


#: 讀數字時只看標籤正中央這個比例的範圍。
#: 數字一定畫在標籤正中央；虛線標籤的邊緣與三個半透明形狀之間的白色縫隙
#: 則在外圍，縮小取樣範圍就能把那些縫隙排除掉。
DIGIT_REGION_RATIO = 0.62
#: 一個字形的高度至少要佔取樣範圍的這個比例，才算是數字。
#: 虛線縫隙造成的碎片通常又小又扁，用高度就能濾掉。
DIGIT_MIN_HEIGHT_RATIO = 0.42


def read_label_value(image, label) -> tuple[int | None, bool]:
    """
    重新讀一個標籤的數字，回傳 (數值, 是否真的有數字)。

    既有專案是取整個標籤外框內、扣掉一點邊界的所有「亮且低彩度」像素當數字。
    對實心標籤沒問題，但虛線標籤是三個半透明形狀疊起來的，
    形狀之間的白色縫隙也會被當成數字筆畫 —— 於是「沒有數字的虛線標籤」
    會切出一堆碎片，被判定成「有字但讀不出來」而中斷整個辨識。

    這裡改成只看標籤正中央、而且只接受夠高的字形，就能穩定分辨
    「真的有數字」與「本來就沒有數字」。
    """
    import cv2
    import numpy as np

    import digit_ocr

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
        return None, False  # 沒有夠高的字形 -> 這是沒有數字的標籤

    boxes.sort(key=lambda b: b[0])  # 由左至右
    digits = []
    for bx, by, bw, bh, idx in boxes:
        glyph = digit_ocr.normalize_glyph(labels_img[by : by + bh, bx : bx + bw] == idx)
        if glyph is None:
            return None, True
        value, score = digit_ocr.classify_glyph(glyph)
        if value is None or score < 0.55:
            return None, True  # 確實有字形但認不出來 -> 辨識失敗
        digits.append(str(value))

    try:
        return int("".join(digits)), True
    except ValueError:
        return None, True


def classify_labels(labels, image=None) -> tuple[list, list]:
    """
    把標籤分成 (可用的, 讀不出來的)。沒有數字的標籤算可用 (大小不限)。

    有傳 image 進來時，會用比較嚴謹的方式重讀每個標籤的數字，
    避免虛線標籤的白色縫隙被誤判成數字。
    """
    usable, unreadable = [], []
    for label in labels:
        if image is not None:
            value, has_digit = read_label_value(image, label)
            label.value = value
            if has_digit and value is None:
                unreadable.append(label)
            else:
                usable.append(label)
            continue

        if label.value is None and label.glyphs:
            unreadable.append(label)
        else:
            usable.append(label)
    return usable, unreadable


def _candidate_rects(n: int, label, all_labels) -> list[tuple[int, int, int, int]]:
    """
    列出這個標籤所有可能的矩形 (r0, c0, height, width)。
    label.value 是 None 時代表大小不限，只受形狀型別限制。
    """
    other_cells = {(lb.row, lb.col) for lb in all_labels if lb is not label}
    rects = []

    if label.value is None:
        size_options = [
            (h, w) for h in range(1, n + 1) for w in range(1, n + 1)
        ]
    else:
        size_options = []
        for h in range(1, n + 1):
            if label.value % h:
                continue
            w = label.value // h
            if w <= n:
                size_options.append((h, w))

    for height, width in size_options:
        if not _shape_allowed(label.shape, height, width):
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
    choices, rect_options = [], []

    for label in labels:
        rects = _candidate_rects(n, label, labels)
        if not rects:
            return None, None, None
        variables = [model.NewBoolVar(f"r{label.row}_{label.col}_{i}") for i in range(len(rects))]
        model.AddExactlyOne(variables)
        choices.append(variables)
        rect_options.append(rects)

    covering = {(r, c): [] for r in range(n) for c in range(n)}
    for variables, rects in zip(choices, rect_options):
        for var, (r0, c0, height, width) in zip(variables, rects):
            for r in range(r0, r0 + height):
                for c in range(c0, c0 + width):
                    covering[(r, c)].append(var)
    for vars_covering in covering.values():
        model.AddExactlyOne(vars_covering)

    return model, choices, rect_options


def solve(n: int, labels) -> list[tuple[int, int, int, int]] | None:
    """把盤面完全切成矩形，每個標籤一塊。回傳順序與 labels 相同。"""
    model, choices, rect_options = _build_model(n, labels)
    if model is None:
        return None

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 30.0
    solver.parameters.num_workers = 8
    if solver.Solve(model) not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return None

    result = []
    for variables, rects in zip(choices, rect_options):
        result.append(next(rect for var, rect in zip(variables, rects) if solver.Value(var)))
    return result


def solve_unique(n: int, labels) -> list[tuple[int, int, int, int]] | None:
    """
    只有在「切法唯一」時才回傳答案，否則回傳 None。

    用途：某個標籤的數字讀不出來時，可以把它當成「大小不限」再解一次；
    如果這樣仍然只有唯一一種切法，那答案就跟有沒有讀到那個數字無關，
    可以安心採用。若有多種切法就代表真的需要那個數字，只能回報失敗。
    """
    model, choices, rect_options = _build_model(n, labels)
    if model is None:
        return None

    class _Collector(cp_model.CpSolverSolutionCallback):
        def __init__(self):
            super().__init__()
            self.solutions = []

        def on_solution_callback(self):
            picked = []
            for variables, rects in zip(choices, rect_options):
                picked.append(next(r for v, r in zip(variables, rects) if self.Value(v)))
            self.solutions.append(picked)
            if len(self.solutions) >= 2:
                self.StopSearch()

    collector = _Collector()
    solver = cp_model.CpSolver()
    solver.parameters.enumerate_all_solutions = True
    solver.parameters.max_time_in_seconds = 30.0
    solver.Solve(model, collector)

    if len(collector.solutions) == 1:
        return collector.solutions[0]
    return None


def describe_label(label) -> str:
    size = "大小不限" if label.value is None else f"大小 {label.value}"
    return f"({label.row + 1},{label.col + 1}) {size}, 形狀={puzzle_patches.SHAPE_LABEL_ZH[label.shape]}"


__all__ = [
    "classify_labels",
    "solve",
    "describe_label",
    "SHAPE_ANY",
    "SHAPE_SQUARE",
    "SHAPE_HORIZONTAL",
    "SHAPE_VERTICAL",
]
