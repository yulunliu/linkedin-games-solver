"""
The result type every puzzle solver returns.
所有謎題求解器共用的回傳型別。

Keeping one shape for all five puzzles is what lets the UI and the automation
layer stay puzzle-agnostic: they read `ok`, `info`, `overlay` and `data`
without knowing which game produced them.
五款謎題共用同一個回傳型別，才能讓介面層與自動化層完全不必知道是哪一款遊戲 ——
它們只讀 `ok`、`info`、`overlay`、`data` 就夠了。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np


@dataclass
class SolveResult:
    ok: bool
    puzzle_key: str
    error: str | None = None

    #: Located board geometry, in the coordinates of the image that was passed in.
    #: 定位到的棋盤幾何，座標相對於傳入的原始影像。
    grid: Any = None

    #: Puzzle-specific structured answer (queen positions, path, tiling, ...).
    #: The automation layer turns this into clicks/drags.
    #: 各謎題自己的結構化答案（皇后位置、路徑、切法……）。自動化層據此產生點擊/拖曳。
    data: dict = field(default_factory=dict)

    #: Human-readable lines shown in the UI.
    #: 顯示在介面上的人類可讀訊息。
    info: list[str] = field(default_factory=list)

    #: Optional image with the answer drawn on it (used by image mode).
    #: 畫上答案的疊圖（圖片模式會用到）。
    overlay: np.ndarray | None = None


def failure(puzzle_key: str, error: str, **kwargs) -> SolveResult:
    return SolveResult(ok=False, puzzle_key=puzzle_key, error=error, **kwargs)
