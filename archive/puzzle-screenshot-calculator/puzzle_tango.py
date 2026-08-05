"""
Tango 謎題 (太陽/月亮)，包裝成與其他謎題一致的介面。

實際的辨識與求解邏輯在 pipeline.py / solver.py / grid_detector.py，
這裡只負責把結果轉成共用的 PuzzleResult。

註：Tango 的棋盤在手機截圖裡沒有自己的外框 (格線很淡)，所以它用的是
grid_detector.py 裡的「內容定位法」，跟其他謎題用的 board.py 不同。
"""

import numpy as np

from pipeline import analyze_image
from puzzle_base import PuzzleResult, failure
from solver import SUN, format_grid

NAME = "Tango (太陽/月亮)"

# Tango 的棋盤沒有外框可以量，內容定位法需要先知道格數；
# LinkedIn 的 Tango 一律是 6x6，所以沒指定時就用 6。
DEFAULT_GRID_SIZE = 6


def analyze(image: np.ndarray, n_hint: int | None = None, debug: bool = False) -> PuzzleResult:
    result = analyze_image(image, n_hint=n_hint or DEFAULT_GRID_SIZE, debug=debug)

    info = []
    if result.grid:
        info.append(f"偵測到棋盤大小: {result.grid.n} x {result.grid.n}")
    if result.puzzle:
        info.append(f"偵測到 given (灰底) 格數: {len(result.puzzle.givens)}")
        info.append(f"偵測到 = / × 關係符號數: {len(result.puzzle.h_edges) + len(result.puzzle.v_edges)}")

    if not result.ok:
        return failure(result.error or "分析失敗", debug_image=result.debug_image, report_lines=info)

    lines = info + ["", "=== 正解 ==="]
    lines.extend(format_grid(result.solution).split("\n"))

    if result.mistakes:
        lines.append("")
        lines.append("=== 你目前答案中填錯的格子 ===")
        for r, c, player_val, correct_val in result.mistakes:
            player = "🟠" if player_val == SUN else "🌙"
            correct = "🟠" if correct_val == SUN else "🌙"
            lines.append(f"  第 {r + 1} 列 第 {c + 1} 欄: 你填 {player} -> 應該是 {correct}")
    else:
        lines.append("")
        lines.append("目前已填的格子都正確！")

    return PuzzleResult(
        ok=True,
        report_lines=lines,
        overlay_image=result.overlay_image,
        debug_image=result.debug_image,
    )
