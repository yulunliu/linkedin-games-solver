"""
Patches 謎題：把整個盤面完全切成一塊塊矩形。

規則 (畫面下方說明):
  - 每個矩形內恰好包含一個數字標籤，矩形的格數必須等於該數字
  - 標籤的外觀決定矩形允許的形狀：
      實心正方形標籤   -> 只能是正方形
      實心橫向長方形   -> 只能是橫向長方形 (寬 > 高)
      實心縱向長方形   -> 只能是縱向長方形 (高 > 寬)
      虛線 (半透明疊三種形狀) -> 以上任一種都可以
  - 所有格子都要被覆蓋，且不能重疊

辨識:
  標籤是彩色圓角方塊 + 白色數字。
  - 用「有彩度或偏暗」的遮罩找出標籤色塊 (盤面底色是白的)
  - 標籤外接框的長寬比決定形狀型別
  - 「填滿率」(色塊面積 / 外接框面積) 用來分辨實心與虛線標籤：
    虛線標籤其實是三個半透明形狀疊在一起、中間有空隙，填滿率明顯較低
    (實測 實心 0.95~0.98、虛線 0.76~0.79)
  - 白色數字用 digit_ocr 讀出數值 (可能是兩位數，例如 12)
"""

from dataclasses import dataclass, field

import cv2
import numpy as np
from ortools.sat.python import cp_model

import digit_ocr
from board import BoardGrid, build_grid
from puzzle_base import PuzzleResult, failure

NAME = "Patches (拼塊)"

SHAPE_SQUARE = "square"
SHAPE_HORIZONTAL = "horizontal"
SHAPE_VERTICAL = "vertical"
SHAPE_ANY = "any"

SHAPE_LABEL_ZH = {
    SHAPE_SQUARE: "正方形",
    SHAPE_HORIZONTAL: "橫向長方形",
    SHAPE_VERTICAL: "縱向長方形",
    SHAPE_ANY: "任一形狀",
}

DASHED_FILL_MAX = 0.87  # 填滿率低於此視為虛線標籤 (任一形狀)
MIN_BADGE_AREA_RATIO = 0.02  # 標籤面積至少要佔一格面積的比例


@dataclass
class PatchLabel:
    row: int
    col: int
    value: int | None
    shape: str
    bbox: tuple[int, int, int, int]
    color: tuple[int, int, int]
    glyphs: list[np.ndarray] = field(default_factory=list)


def find_labels(image: np.ndarray, grid: BoardGrid) -> list[PatchLabel]:
    x0, y0, w0, h0 = grid.board_bbox
    cell = (w0 / grid.n + h0 / grid.n) / 2

    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    sat, val = hsv[:, :, 1], hsv[:, :, 2]

    # 標籤是彩色的，或是深色 (例如深灰藍標籤彩度不高但很暗)；盤面底色是白的
    mask = ((sat > 70) | (val < 190)).astype(np.uint8)
    mask[: y0 + 2, :] = 0
    mask[y0 + h0 - 2 :, :] = 0
    mask[:, : x0 + 2] = 0
    mask[:, x0 + w0 - 2 :] = 0
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))

    num, labels_img, stats, centroids = cv2.connectedComponentsWithStats(mask, connectivity=8)
    min_area = cell * cell * MIN_BADGE_AREA_RATIO

    out: list[PatchLabel] = []
    for i in range(1, num):
        x, y, w, h, area = stats[i]
        if area < min_area or w < 8 or h < 8:
            continue
        cx, cy = centroids[i]
        row = int((cy - y0) / cell)
        col = int((cx - x0) / cell)
        if not (0 <= row < grid.n and 0 <= col < grid.n):
            continue

        aspect = w / h
        fill = area / (w * h)
        if fill <= DASHED_FILL_MAX:
            shape = SHAPE_ANY
        elif aspect >= 1.25:
            shape = SHAPE_HORIZONTAL
        elif aspect <= 0.8:
            shape = SHAPE_VERTICAL
        else:
            shape = SHAPE_SQUARE

        # 讀白色數字：標籤內彩度低且很亮的像素
        sub_sat = sat[y : y + h, x : x + w]
        sub_val = val[y : y + h, x : x + w]
        component = labels_img[y : y + h, x : x + w] == i
        digit_mask = (component | True) & (sub_sat < 60) & (sub_val > 200)
        # 只保留標籤外接框內側，避免把框外的白底也算進來
        inner = np.zeros_like(digit_mask)
        pad_y, pad_x = max(1, h // 8), max(1, w // 8)
        inner[pad_y : h - pad_y, pad_x : w - pad_x] = True
        digit_mask = digit_mask & inner

        glyphs = digit_ocr.split_digit_glyphs(digit_mask.astype(np.uint8))
        value = digit_ocr.read_number(digit_mask.astype(np.uint8))

        colored = component & (sub_val < 250)
        color_px = image[y : y + h, x : x + w][colored]
        color = tuple(int(v) for v in np.median(color_px, axis=0)) if len(color_px) else (0, 0, 0)

        out.append(
            PatchLabel(row=row, col=col, value=value, shape=shape, bbox=(x, y, w, h), color=color, glyphs=glyphs)
        )

    out.sort(key=lambda lb: (lb.row, lb.col))
    return out


def _shape_allowed(shape: str, height: int, width: int) -> bool:
    if shape == SHAPE_SQUARE:
        return height == width
    if shape == SHAPE_HORIZONTAL:
        return width > height
    if shape == SHAPE_VERTICAL:
        return height > width
    return True


def _candidate_rects(n: int, label: PatchLabel, all_labels: list[PatchLabel]) -> list[tuple[int, int, int, int]]:
    """列出這個標籤所有可能的矩形 (r0, c0, height, width)。"""
    value = label.value
    rects = []
    other_cells = {(lb.row, lb.col) for lb in all_labels if lb is not label}

    for height in range(1, n + 1):
        if value % height:
            continue
        width = value // height
        if width > n:
            continue
        if not _shape_allowed(label.shape, height, width):
            continue
        for r0 in range(max(0, label.row - height + 1), min(label.row, n - height) + 1):
            for c0 in range(max(0, label.col - width + 1), min(label.col, n - width) + 1):
                cells = [(r, c) for r in range(r0, r0 + height) for c in range(c0, c0 + width)]
                if any(cellpos in other_cells for cellpos in cells):
                    continue
                rects.append((r0, c0, height, width))
    return rects


def solve(n: int, labels: list[PatchLabel]) -> list[tuple[int, int, int, int]] | None:
    """回傳每個標籤對應的矩形 (r0, c0, height, width)，順序與 labels 相同。"""
    model = cp_model.CpModel()
    choices: list[list] = []
    rect_options: list[list[tuple[int, int, int, int]]] = []

    for label in labels:
        rects = _candidate_rects(n, label, labels)
        if not rects:
            return None
        vars_for_label = [model.NewBoolVar(f"r_{label.row}_{label.col}_{i}") for i in range(len(rects))]
        model.AddExactlyOne(vars_for_label)
        choices.append(vars_for_label)
        rect_options.append(rects)

    # 每個格子恰好被一個矩形覆蓋
    covering: dict[tuple[int, int], list] = {(r, c): [] for r in range(n) for c in range(n)}
    for vars_for_label, rects in zip(choices, rect_options):
        for var, (r0, c0, height, width) in zip(vars_for_label, rects):
            for r in range(r0, r0 + height):
                for c in range(c0, c0 + width):
                    covering[(r, c)].append(var)
    for vars_covering in covering.values():
        model.AddExactlyOne(vars_covering)

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 30.0
    status = solver.Solve(model)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return None

    result = []
    for vars_for_label, rects in zip(choices, rect_options):
        chosen = next(rect for var, rect in zip(vars_for_label, rects) if solver.Value(var))
        result.append(chosen)
    return result


def draw_overlay(image, grid: BoardGrid, labels: list[PatchLabel], rects) -> np.ndarray:
    out = image.copy()
    for label, (r0, c0, height, width) in zip(labels, rects):
        x, y, _, _ = grid.cell_boxes[r0][c0]
        x2, y2, cw, ch = grid.cell_boxes[r0 + height - 1][c0 + width - 1]
        cv2.rectangle(out, (x + 4, y + 4), (x2 + cw - 4, y2 + ch - 4), label.color, 5, lineType=cv2.LINE_AA)
    return out


def draw_debug(image, grid: BoardGrid, labels: list[PatchLabel]) -> np.ndarray:
    dbg = image.copy()
    for row in grid.cell_boxes:
        for x, y, w, h in row:
            cv2.rectangle(dbg, (x, y), (x + w, y + h), (0, 200, 0), 1)
    for label in labels:
        x, y, w, h = label.bbox
        cv2.rectangle(dbg, (x, y), (x + w, y + h), (255, 0, 255), 2)
        text = f"{label.value}/{label.shape[:4]}@{label.row},{label.col}"
        cv2.putText(dbg, text, (x - 10, y - 6), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 0, 255), 1)
    return dbg


def analyze(image: np.ndarray, n_hint: int | None = None, debug: bool = False) -> PuzzleResult:
    try:
        grid = build_grid(image, n_hint=n_hint)
    except ValueError as e:
        return failure(f"辨識失敗: {e}")

    labels = find_labels(image, grid)
    debug_image = draw_debug(image, grid, labels) if debug else None

    info = [f"偵測到棋盤大小: {grid.n} x {grid.n}", f"偵測到標籤數: {len(labels)}"]
    for lb in labels:
        info.append(
            f"  ({lb.row + 1},{lb.col + 1}) 數字={lb.value} 形狀={SHAPE_LABEL_ZH[lb.shape]}"
        )

    unreadable = [lb for lb in labels if lb.value is None]
    if unreadable:
        return failure(
            f"有 {len(unreadable)} 個標籤的數字讀不出來，請確認截圖清晰度。",
            debug_image=debug_image, report_lines=info,
        )
    if not labels:
        return failure("找不到任何標籤，請確認截圖有包含完整盤面。", debug_image=debug_image, report_lines=info)

    total = sum(lb.value for lb in labels)
    if total != grid.n * grid.n:
        return failure(
            f"標籤數字總和 ({total}) 不等於盤面格數 ({grid.n * grid.n})，數字辨識可能有誤。",
            debug_image=debug_image, report_lines=info,
        )

    rects = solve(grid.n, labels)
    if rects is None:
        return failure("找不到符合規則的切法，可能是標籤數字或形狀辨識有誤。", debug_image=debug_image, report_lines=info)

    lines = info + ["", "=== 每個標籤對應的矩形 ==="]
    for lb, (r0, c0, height, width) in zip(labels, rects):
        lines.append(
            f"  數字 {lb.value}: 左上角 (第 {r0 + 1} 列, 第 {c0 + 1} 欄), 高 {height} x 寬 {width}"
        )

    lines.append("")
    lines.append("=== 盤面切法 (同一字母為同一塊) ===")
    letters = [[" "] * grid.n for _ in range(grid.n)]
    for idx, (r0, c0, height, width) in enumerate(rects):
        ch = chr(ord("A") + idx % 26)
        for r in range(r0, r0 + height):
            for c in range(c0, c0 + width):
                letters[r][c] = ch
    for row in letters:
        lines.append(" ".join(row))

    return PuzzleResult(
        ok=True,
        report_lines=lines,
        overlay_image=draw_overlay(image, grid, labels, rects),
        debug_image=debug_image,
    )
