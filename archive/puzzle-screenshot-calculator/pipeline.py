"""
共用的「圖片 -> 辨識 -> 求解 -> 結果」流程，供 CLI (main.py) 和 GUI (gui.py) 共用。
"""

from dataclasses import dataclass

import cv2
import numpy as np

from cell_classifier import CellReading, read_all_cells
from edge_classifier import detect_h_edges, detect_v_edges
from grid_detector import BoardGrid, build_grid
from solver import (
    MOON,
    SUN,
    MultipleSolutionsError,
    NoSolutionError,
    Puzzle,
    diff_against_current,
    solve,
)

SYMBOL_TO_VALUE = {"sun": SUN, "moon": MOON}
VALUE_TO_COLOR_BGR = {SUN: (0, 140, 255), MOON: (200, 120, 30)}  # 橘 / 藍 (BGR)


@dataclass
class AnalysisResult:
    ok: bool
    error: str | None = None
    grid: BoardGrid | None = None
    puzzle: Puzzle | None = None
    readings: list[list[CellReading]] | None = None
    current: dict[tuple[int, int], int | None] | None = None
    solution: list[list[int]] | None = None
    mistakes: list[tuple[int, int, int, int]] | None = None
    overlay_image: np.ndarray | None = None
    debug_image: np.ndarray | None = None


def build_puzzle_from_image(image: np.ndarray, n_hint: int | None):
    grid = build_grid(image, n_hint=n_hint)
    readings = read_all_cells(image, grid.cell_boxes)
    h_edges = detect_h_edges(image, grid.cell_boxes)
    v_edges = detect_v_edges(image, grid.cell_boxes)

    givens = {}
    current = {}
    for r, row in enumerate(readings):
        for c, reading in enumerate(row):
            value = SYMBOL_TO_VALUE.get(reading.symbol) if reading.symbol else None
            current[(r, c)] = value
            if reading.given and value is not None:
                givens[(r, c)] = value

    puzzle = Puzzle(n=grid.n, givens=givens, h_edges=h_edges, v_edges=v_edges)
    return puzzle, current, grid, readings


def draw_debug_image(image, grid, readings, h_edges, v_edges) -> np.ndarray:
    dbg = image.copy()
    for r, row in enumerate(grid.cell_boxes):
        for c, (x, y, w, h) in enumerate(row):
            cv2.rectangle(dbg, (x, y), (x + w, y + h), (0, 255, 0), 1)
            reading = readings[r][c]
            label = f"{reading.symbol or '?'}{'G' if reading.given else ''}"
            cv2.putText(dbg, label, (x + 3, y + 15), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 0, 255), 1)
    for (r, c), sym in h_edges.items():
        x, y, w, h = grid.cell_boxes[r][c]
        cv2.putText(dbg, sym, (x + w - 8, y + h // 2), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 0, 255), 2)
    for (r, c), sym in v_edges.items():
        x, y, w, h = grid.cell_boxes[r][c]
        cv2.putText(dbg, sym, (x + w // 2, y + h - 4), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 0, 255), 2)
    return dbg


def _sample_bg_color(image, x, y, w, h) -> tuple[int, int, int]:
    """
    取格子內部的背景顏色，畫月亮缺角時用來跟背景融合。

    直接裁切格子角落容易裁到棋盤外框的黑色粗邊線 (尤其是第一列/最後一列/
    第一欄/最後一欄的格子)，混進來的話背景色會被拉得很暗，畫出來的缺角
    會變成一塊黑斑。所以改成：往格子內縮一點再裁切，並排除掉飽和度高的
    像素 (太陽/月亮圖示本身的顏色)，剩下的像素取中位數才是乾淨的背景色。
    """
    margin_x, margin_y = max(4, w // 6), max(4, h // 6)
    inner = image[y + margin_y : y + h - margin_y, x + margin_x : x + w - margin_x]
    if inner.size == 0:
        return (255, 255, 255)
    hsv = cv2.cvtColor(inner, cv2.COLOR_BGR2HSV)
    bg_mask = hsv[:, :, 1] <= 60  # 排除飽和度高的圖示像素
    pixels = inner.reshape(-1, 3)
    candidates = pixels[bg_mask.reshape(-1)] if bg_mask.any() else pixels
    median = np.median(candidates, axis=0)
    return (int(median[0]), int(median[1]), int(median[2]))


def _draw_sun_icon(img, center, radius, color, bg_color):
    cx, cy = center
    ray_len = max(3, int(radius * 0.55))
    ray_gap = max(2, int(radius * 0.25))
    thickness = max(2, radius // 5)
    for angle_deg in range(0, 360, 45):
        angle = np.deg2rad(angle_deg)
        x1 = int(cx + (radius + ray_gap) * np.cos(angle))
        y1 = int(cy + (radius + ray_gap) * np.sin(angle))
        x2 = int(cx + (radius + ray_gap + ray_len) * np.cos(angle))
        y2 = int(cy + (radius + ray_gap + ray_len) * np.sin(angle))
        cv2.line(img, (x1, y1), (x2, y2), color, thickness, lineType=cv2.LINE_AA)
    cv2.circle(img, (cx, cy), radius, color, thickness=-1, lineType=cv2.LINE_AA)
    cv2.circle(img, (cx, cy), radius, (60, 90, 160), thickness=1, lineType=cv2.LINE_AA)


def _draw_moon_icon(img, center, radius, color, bg_color):
    cx, cy = center
    cv2.circle(img, (cx, cy), radius, color, thickness=-1, lineType=cv2.LINE_AA)
    # 用背景色畫一個偏移的圓「挖」出缺角，做出弦月的形狀
    cutout_radius = int(radius * 0.82)
    offset = int(radius * 0.55)
    cv2.circle(img, (cx + offset, cy - offset // 2), cutout_radius, bg_color, thickness=-1, lineType=cv2.LINE_AA)
    cv2.circle(img, (cx, cy), radius, (150, 90, 30), thickness=1, lineType=cv2.LINE_AA)


def draw_solution_overlay(image, grid, solution, current) -> np.ndarray:
    out = image.copy()
    for r, row in enumerate(grid.cell_boxes):
        for c, (x, y, w, h) in enumerate(row):
            cx, cy = x + w // 2, y + h // 2
            correct = solution[r][c]
            color = VALUE_TO_COLOR_BGR[correct]
            player_val = current.get((r, c))
            radius = max(8, min(w, h) // 4)
            bg_color = _sample_bg_color(image, x, y, w, h)

            if player_val is None:
                draw_icon = _draw_sun_icon if correct == SUN else _draw_moon_icon
                draw_icon(out, (cx, cy), radius, color, bg_color)
            elif player_val != correct:
                cv2.rectangle(out, (x + 2, y + 2), (x + w - 2, y + h - 2), (0, 0, 255), 3)
                draw_icon = _draw_sun_icon if correct == SUN else _draw_moon_icon
                draw_icon(out, (cx, cy), radius, color, bg_color)
    return out


def analyze_image(image: np.ndarray, n_hint: int | None = None, debug: bool = False) -> AnalysisResult:
    try:
        puzzle, current, grid, readings = build_puzzle_from_image(image, n_hint)
    except ValueError as e:
        return AnalysisResult(ok=False, error=f"辨識失敗: {e}")

    debug_image = None
    if debug:
        debug_image = draw_debug_image(image, grid, readings, puzzle.h_edges, puzzle.v_edges)

    try:
        solution = solve(puzzle)
    except (NoSolutionError, MultipleSolutionsError) as e:
        return AnalysisResult(
            ok=False,
            error=f"求解失敗: {e}\n可能是圖片辨識有誤 (given / = / × 抓錯)。",
            grid=grid,
            puzzle=puzzle,
            readings=readings,
            current=current,
            debug_image=debug_image,
        )

    mistakes = diff_against_current(solution, current)
    overlay_image = draw_solution_overlay(image, grid, solution, current)

    return AnalysisResult(
        ok=True,
        grid=grid,
        puzzle=puzzle,
        readings=readings,
        current=current,
        solution=solution,
        mistakes=mistakes,
        overlay_image=overlay_image,
        debug_image=debug_image,
    )
