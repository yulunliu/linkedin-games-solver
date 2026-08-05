"""
Core layer: everything that is shared by all five puzzles.
核心層：五款謎題共用的部分。

  image_io     Unicode-safe image read/write        支援 Unicode 路徑的圖片讀寫
  board        find the grid, split it into cells   找出棋盤並切格
  digits       digit recognition                    數字辨識
  detect_type  which puzzle is this?                這是哪一款謎題？
  result       shared return type                   共用回傳型別
"""

from . import action_log
from .board import BoardGrid, build_cell_boxes, build_grid, build_grid_from_lines
from .detect_type import detect_type
from .image_io import read_image, write_image
from .result import SolveResult, failure

__all__ = [
    "BoardGrid",
    "build_grid",
    "build_grid_from_lines",
    "build_cell_boxes",
    "detect_type",
    "read_image",
    "write_image",
    "SolveResult",
    "failure",
    "action_log",
]
