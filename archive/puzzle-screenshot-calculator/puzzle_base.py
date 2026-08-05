"""
所有謎題模組共用的介面定義。

每個謎題模組 (puzzle_tango / puzzle_queens / puzzle_sudoku / puzzle_zip /
puzzle_patches) 都要提供：

    NAME: str                  顯示用的謎題名稱
    analyze(image, n_hint=None, debug=False) -> PuzzleResult

這樣 GUI 和 CLI 就能用同一套流程處理所有謎題，只要換一個模組。
"""

from dataclasses import dataclass, field

import numpy as np


@dataclass
class PuzzleResult:
    ok: bool
    error: str | None = None
    # 給使用者看的文字報告 (每個元素一行)
    report_lines: list[str] = field(default_factory=list)
    # 在原圖上疊加答案的圖
    overlay_image: np.ndarray | None = None
    # 辨識過程的除錯圖 (只有 debug=True 時才產生)
    debug_image: np.ndarray | None = None


def failure(error: str, debug_image: np.ndarray | None = None, report_lines: list[str] | None = None) -> PuzzleResult:
    return PuzzleResult(
        ok=False,
        error=error,
        report_lines=report_lines or [],
        debug_image=debug_image,
    )
