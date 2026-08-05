"""
把「棋盤的第 r 列第 c 欄」換算成「螢幕上的絕對座標」。

偵測出來的 cell_boxes 是相對於擷取影像的座標，
再加上擷取影像在螢幕上的原點就是滑鼠要去點的位置。
"""

from dataclasses import dataclass

from capture import ScreenShot


@dataclass
class BoardMapper:
    shot: ScreenShot
    grid: object  # solver_bridge 取得的 BoardGrid

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
        return (
            f"棋盤 {self.n}x{self.n}，螢幕位置 ({left},{top}) 大小 {w}x{h}，"
            f"每格約 {cw}x{ch} px"
        )
