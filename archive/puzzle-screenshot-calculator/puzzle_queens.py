"""
Queens 謎題：在 N x N 盤面上放皇后。

規則:
  - 每行、每列、每個色塊區域中恰好有一個皇后
  - 任兩個皇后不能相鄰，包含對角線相鄰也不行

辨識:
  盤面每格是一個純色色塊，取每格中央的顏色分群就能得到色塊區域劃分。
"""

import cv2
import numpy as np
from ortools.sat.python import cp_model

from board import BoardGrid, build_grid
from puzzle_base import PuzzleResult, failure

NAME = "Queens (皇后)"

COLOR_MATCH_TOLERANCE = 30  # 兩格顏色差距在此範圍內視為同一個色塊區域


def read_regions(image: np.ndarray, grid: BoardGrid) -> tuple[list[list[int]], list[tuple[int, int, int]]]:
    """
    回傳 (region_ids, palette)。
    region_ids[r][c] 是該格所屬色塊區域的編號，palette[i] 是該區域的代表色 (BGR)。
    """
    palette: list[np.ndarray] = []
    region_ids = [[-1] * grid.n for _ in range(grid.n)]

    for r in range(grid.n):
        for c in range(grid.n):
            x, y, w, h = grid.cell_boxes[r][c]
            patch = image[y + int(h * 0.3) : y + int(h * 0.7), x + int(w * 0.3) : x + int(w * 0.7)]
            color = np.median(patch.reshape(-1, 3), axis=0)

            matched = None
            for idx, known in enumerate(palette):
                if np.abs(known - color).max() <= COLOR_MATCH_TOLERANCE:
                    matched = idx
                    break
            if matched is None:
                palette.append(color)
                matched = len(palette) - 1
            region_ids[r][c] = matched

    return region_ids, [tuple(int(v) for v in col) for col in palette]


def solve(n: int, region_ids: list[list[int]]) -> list[tuple[int, int]] | None:
    """回傳皇后座標清單 [(row, col), ...]，無解回傳 None。"""
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

    # 相鄰 (含對角線) 不能同時有皇后
    for r in range(n):
        for c in range(n):
            for dr, dc in ((0, 1), (1, 0), (1, 1), (1, -1)):
                nr, nc = r + dr, c + dc
                if 0 <= nr < n and 0 <= nc < n:
                    model.AddAtMostOne([cells[r][c], cells[nr][nc]])

    solver = cp_model.CpSolver()
    status = solver.Solve(model)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return None
    return [(r, c) for r in range(n) for c in range(n) if solver.Value(cells[r][c])]


def _draw_crown(img, center, size, color=(0, 0, 0)):
    cx, cy = center
    half = size // 2
    base_y = cy + half // 2
    pts = np.array(
        [
            [cx - half, cy - half // 2],
            [cx - half // 2, cy],
            [cx, cy - half],
            [cx + half // 2, cy],
            [cx + half, cy - half // 2],
            [cx + half, base_y],
            [cx - half, base_y],
        ],
        dtype=np.int32,
    )
    cv2.fillPoly(img, [pts], color, lineType=cv2.LINE_AA)
    cv2.polylines(img, [pts], True, (255, 255, 255), 2, lineType=cv2.LINE_AA)


def draw_overlay(image, grid: BoardGrid, queens: list[tuple[int, int]]) -> np.ndarray:
    out = image.copy()
    for r, c in queens:
        x, y, w, h = grid.cell_boxes[r][c]
        _draw_crown(out, grid.cell_center(r, c), max(14, min(w, h) // 2))
        cv2.rectangle(out, (x + 3, y + 3), (x + w - 3, y + h - 3), (0, 0, 0), 3)
    return out


def draw_debug(image, grid: BoardGrid, region_ids) -> np.ndarray:
    dbg = image.copy()
    for r in range(grid.n):
        for c in range(grid.n):
            x, y, w, h = grid.cell_boxes[r][c]
            cv2.rectangle(dbg, (x, y), (x + w, y + h), (0, 255, 0), 1)
            cv2.putText(
                dbg, str(region_ids[r][c]), (x + 6, y + 24),
                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2,
            )
    return dbg


def analyze(image: np.ndarray, n_hint: int | None = None, debug: bool = False) -> PuzzleResult:
    try:
        grid = build_grid(image, n_hint=n_hint)
    except ValueError as e:
        return failure(f"辨識失敗: {e}")

    region_ids, palette = read_regions(image, grid)
    debug_image = draw_debug(image, grid, region_ids) if debug else None

    info = [
        f"偵測到棋盤大小: {grid.n} x {grid.n}",
        f"偵測到色塊區域數: {len(palette)}",
    ]

    if len(palette) != grid.n:
        return failure(
            f"色塊區域數 ({len(palette)}) 與棋盤大小 ({grid.n}) 不一致，"
            "顏色辨識可能有誤，請確認截圖沒有被裁切或壓縮失真。",
            debug_image=debug_image,
            report_lines=info,
        )

    queens = solve(grid.n, region_ids)
    if queens is None:
        return failure("找不到符合規則的解，可能是色塊辨識有誤。", debug_image=debug_image, report_lines=info)

    lines = info + ["", "=== 皇后位置 (第X列, 第Y欄) ==="]
    for r, c in queens:
        lines.append(f"  第 {r + 1} 列, 第 {c + 1} 欄")

    lines.append("")
    lines.append("=== 盤面 ===")
    for r in range(grid.n):
        lines.append(" ".join("♛" if (r, c) in queens else "·" for c in range(grid.n)))

    return PuzzleResult(
        ok=True,
        report_lines=lines,
        overlay_image=draw_overlay(image, grid, queens),
        debug_image=debug_image,
    )
