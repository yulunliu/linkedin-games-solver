"""
Puzzle registry and the recognition pipeline that wraps every solver.
謎題註冊表，以及包在每個求解器外面的辨識流程。

Each puzzle module exposes `solve(image, n_hint) -> SolveResult`. This package
adds the robustness layer that all of them need:
每個謎題模組提供 `solve(image, n_hint) -> SolveResult`。這個套件則加上
它們共同需要的強健化處理：

  1. SCALE NORMALISATION - rescale so the board is ~800px before recognising.
     Thresholds and digit templates were calibrated on phone screenshots where
     the board is about that size. A browser board can be any size, and
     recognising at the wrong scale is unreliable: Patches read its labels
     correctly at board widths of 506px and 635px but misread them in between.
     Normalising first makes every size behave the same.
     尺度正規化 —— 辨識前先縮放到棋盤約 800px。
     各種門檻與數字範本都是在棋盤約這個大小的手機截圖上校準的。網頁棋盤大小
     不一定，用錯尺度辨識並不可靠：實測 Patches 在棋盤 506px 與 635px 時讀得
     正確，中間的尺寸卻會讀錯。先正規化就能讓所有尺寸表現一致。

  2. PROGRESSIVE CENTRE CROPPING - if the capture region is much larger than the
     board, crop tighter and retry. Tango's borderless detection in particular
     degrades when there is a lot of surrounding page content.
     漸進式置中裁切 —— 擷取範圍比棋盤大很多時，往中間裁緊再試。
     Tango 沒有外框的定位在周圍雜訊多時特別容易失準。

  3. RE-NORMALISE AFTER SUCCESS - succeeding is not the same as being correct.
     A board recognised at the wrong scale can yield a plausible but WRONG
     answer, so after any success we redo recognition at the normalised scale
     and prefer that result.
     成功之後再正規化重算 —— 「解出來了」不等於「解對了」。在錯誤尺度下辨識
     可能得到「看似合理但錯誤」的答案，所以任何一次成功之後都會用正規化尺度
     重算一次，並以重算結果為準。
"""

from __future__ import annotations

import cv2
import numpy as np

from ..core import SolveResult, build_cell_boxes, detect_type
from ..core.board import BoardGrid, find_board_bbox, find_board_by_grid_lines
from . import patches, queens, sudoku, tango, zip_path

#: key -> module. Order is the order shown in the UI.
#: 鍵 -> 模組。順序就是介面上顯示的順序。
PUZZLES = {
    tango.KEY: tango,
    queens.KEY: queens,
    sudoku.KEY: sudoku,
    zip_path.KEY: zip_path,
    patches.KEY: patches,
}
DISPLAY_ORDER = list(PUZZLES)

#: Board size the recognition thresholds were calibrated at.
#: 辨識門檻校準時的棋盤大小。
TARGET_BOARD_PIXELS = 794
#: Recommended minimum board size; below this Patches' small digits blur out.
#: 建議的棋盤最小邊長；低於這個大小 Patches 的小數字會糊掉。
MIN_BOARD_PIXELS = 500

_PRESCALE_STEPS = (1.0, 1.75, 2.5)
_CROP_FRACTIONS = (1.0, 0.85, 0.72, 0.6, 0.5)


def puzzle_name(key: str, language: str = "zh") -> str:
    module = PUZZLES.get(key)
    if module is None:
        return key
    return module.NAME_EN if language == "en" else module.NAME_ZH


def _scaled(image: np.ndarray, factor: float) -> np.ndarray:
    if abs(factor - 1.0) < 1e-6:
        return image
    interpolation = cv2.INTER_CUBIC if factor > 1 else cv2.INTER_AREA
    return cv2.resize(image, None, fx=factor, fy=factor, interpolation=interpolation)


def _center_crop(image: np.ndarray, fraction: float):
    if fraction >= 1.0:
        return image, (0, 0)
    h, w = image.shape[:2]
    nw, nh = int(w * fraction), int(h * fraction)
    ox, oy = (w - nw) // 2, (h - nh) // 2
    return image[oy : oy + nh, ox : ox + nw], (ox, oy)


def _locate_board(image: np.ndarray):
    """Find the board, pre-scaling if its faint border is missed at 1x.
    找出棋盤；淡色邊框在原尺寸抓不到時先放大再找。"""
    for prescale in _PRESCALE_STEPS:
        candidate = _scaled(image, prescale)
        bbox = find_board_bbox(candidate)
        if bbox is None:
            found = find_board_by_grid_lines(candidate)
            bbox = found[0] if found else None
        if bbox is not None:
            return prescale, bbox
    return None


def _rescale_grid(grid: BoardGrid, factor: float, offset=(0, 0)) -> BoardGrid:
    """Map grid coordinates back to the original image.
    把棋盤座標換算回原始影像。"""
    ox, oy = offset
    if abs(factor - 1.0) < 1e-6 and ox == 0 and oy == 0:
        return grid
    x, y, w, h = grid.board_bbox
    bbox = (round(x / factor) + ox, round(y / factor) + oy, round(w / factor), round(h / factor))
    return BoardGrid(n=grid.n, board_bbox=bbox, cell_boxes=build_cell_boxes(bbox, grid.n))


def _attempt(image: np.ndarray, puzzle_key: str | None, n_hint: int | None) -> SolveResult:
    key = puzzle_key or detect_type(image)
    module = PUZZLES.get(key)
    if module is None:
        return SolveResult(ok=False, puzzle_key=key, error=f"unsupported puzzle / 不支援的謎題: {key}")
    try:
        return module.solve(image, n_hint)
    except ValueError as exc:
        return SolveResult(ok=False, puzzle_key=key, error=f"recognition failed / 辨識失敗: {exc}")
    except Exception as exc:  # noqa: BLE001 - surface any failure as a readable message
        return SolveResult(ok=False, puzzle_key=key, error=f"{type(exc).__name__}: {exc}")


def _renormalise(sub, result: SolveResult, factor: float, puzzle_key, n_hint):
    """Redo recognition at the calibrated scale and prefer that result.
    用校準尺度重做辨識，並以重算結果為準。

    Succeeding at the wrong scale can silently produce a wrong answer: Tango at
    a ~390px board detected only 1 of its 4 constraint marks, and the solver
    dutifully returned an answer consistent with what it saw. That is worse than
    failing, so we always re-run normalised.
    在錯誤尺度下成功可能悄悄給出錯誤答案：Tango 在棋盤約 390px 時 4 個條件符號
    只抓到 1 個，求解器就照它看到的條件給出答案。這比失敗更糟，所以一律重算。
    """
    detected_width = result.grid.board_bbox[2] if result.grid else 0
    if detected_width <= 0:
        return factor, result
    board_width_in_sub = detected_width / factor
    ideal = TARGET_BOARD_PIXELS / board_width_in_sub
    if abs(ideal - factor) / max(ideal, factor) <= 0.15:
        return factor, result
    better = _attempt(_scaled(sub, ideal), puzzle_key, n_hint)
    return (ideal, better) if better.ok else (factor, result)


def solve_image(image: np.ndarray, puzzle_key: str | None = None, n_hint: int | None = None) -> SolveResult:
    """Recognise and solve. Grid coordinates are relative to the image passed in.
    辨識並求解。回傳的棋盤座標相對於傳入的原始影像。"""
    last: SolveResult | None = None

    for fraction in _CROP_FRACTIONS:
        sub, offset = _center_crop(image, fraction)
        if min(sub.shape[:2]) < 120:
            break

        # Prefer the scale that puts the board at the calibrated size; fall back
        # to plain pre-scales if the board cannot be located yet.
        # 優先用「讓棋盤達到校準尺寸」的縮放；還定位不到棋盤時才退回固定倍率。
        candidates: list[float] = []
        located = _locate_board(sub)
        if located is not None:
            prescale, bbox = located
            candidates.append(prescale * (TARGET_BOARD_PIXELS / bbox[2]))
        candidates.extend(_PRESCALE_STEPS)

        tried: list[float] = []
        for factor in candidates:
            if any(abs(factor - t) < 0.02 for t in tried):
                continue
            tried.append(factor)

            result = _attempt(_scaled(sub, factor), puzzle_key, n_hint)
            if result.ok:
                factor, result = _renormalise(sub, result, factor, puzzle_key, n_hint)
                result.grid = _rescale_grid(result.grid, factor, offset)
                # The overlay was drawn on a scaled/cropped copy, so it no longer
                # matches the caller's image; render_overlay redraws it.
                # 疊圖是畫在縮放/裁切過的複本上，跟呼叫端的影像對不上；
                # 需要時由 render_overlay 重新繪製。
                result.overlay = None
                notes = []
                if fraction < 1.0:
                    notes.append(f"crop {fraction:.0%} / 裁切")
                if abs(factor - 1.0) > 0.02:
                    notes.append(f"scale {factor:.2f}x / 縮放")
                if notes:
                    result.info.append("(" + ", ".join(notes) + ")")
                return result
            last = last or result

    if last is None:
        last = SolveResult(ok=False, puzzle_key=puzzle_key or "unknown",
                           error="board not found / 找不到棋盤")

    # Board too small is by far the most common cause; say so explicitly.
    # 棋盤太小是最常見的原因，直接講明。
    bbox = find_board_bbox(image)
    board_px = bbox[2] if bbox else None
    if board_px is None or board_px < MIN_BOARD_PIXELS:
        hint = (f"board is only ~{board_px}px / 棋盤只有約 {board_px}px" if board_px
                else "no board found / 畫面上找不到棋盤")
        last.error = (
            f"{last.error}\n{hint}. Zoom in with Ctrl + "
            f"(recommend >= {MIN_BOARD_PIXELS}px) / 建議放大頁面後再試。"
        )
    return last


def render_overlay(image: np.ndarray, result: SolveResult) -> np.ndarray | None:
    """Draw the answer on the caller's image using the mapped-back grid.
    用換算回原尺度的棋盤座標，把答案畫在呼叫端的影像上。"""
    if not result.ok or result.grid is None:
        return None
    module = PUZZLES.get(result.puzzle_key)
    if module is None:
        return None
    grid, data = result.grid, result.data
    try:
        if result.puzzle_key == queens.KEY:
            return module.draw_overlay(image, grid, data["queens"])
        if result.puzzle_key == tango.KEY:
            return module.draw_overlay(image, grid, data["solution"], data["current"])
        if result.puzzle_key == sudoku.KEY:
            return module.draw_overlay(image, grid, data["solution"], data["givens"])
        if result.puzzle_key == zip_path.KEY:
            return module.draw_overlay(image, grid, data["path"])
        if result.puzzle_key == patches.KEY:
            return module.draw_overlay(image, grid, data["labels"], data["rects"])
    except Exception:
        return None
    return None


__all__ = ["PUZZLES", "DISPLAY_ORDER", "solve_image", "render_overlay", "puzzle_name",
           "MIN_BOARD_PIXELS", "TARGET_BOARD_PIXELS"]
