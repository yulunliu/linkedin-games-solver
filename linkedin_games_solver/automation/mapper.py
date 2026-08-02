"""
Turn "row r, column c" into "this pixel on screen".
把「第 r 列第 c 欄」換算成「螢幕上的這個像素」。

The solver returns board coordinates; the mouse needs screen coordinates. This
is the single place that bridges the two, so any coordinate bug has exactly one
place to look.
求解器回傳的是棋盤座標，滑鼠需要的是螢幕座標。這裡是唯一的橋接點，
所以座標相關的問題只要看這一支就好。
"""

from __future__ import annotations

from dataclasses import dataclass

from .capture import ScreenShot


@dataclass
class BoardMapper:
    shot: ScreenShot
    grid: object  # core.BoardGrid

    @property
    def n(self) -> int:
        return self.grid.n

    def cell_center(self, row: int, col: int) -> tuple[int, int]:
        x, y, w, h = self.grid.cell_boxes[row][col]
        return self.shot.to_screen(x + w // 2, y + h // 2)

    def cell_size(self) -> tuple[int, int]:
        _, _, w, h = self.grid.cell_boxes[0][0]
        return w, h

    def board_rect_on_screen(self) -> tuple[int, int, int, int]:
        x, y, w, h = self.grid.board_bbox
        left, top = self.shot.to_screen(x, y)
        return left, top, w, h

    def describe(self) -> str:
        left, top, w, h = self.board_rect_on_screen()
        cw, ch = self.cell_size()
        return f"{self.n}x{self.n} @ ({left},{top}) {w}x{h}, cell {cw}x{ch}px"
