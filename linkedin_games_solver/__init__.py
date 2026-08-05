"""
LinkedIn Games Solver - automatic solver for LinkedIn's five daily puzzles.
LinkedIn 謎題自動求解 —— 自動破解 LinkedIn 五款每日小遊戲。

Games 支援遊戲: Tango / Queens / Mini Sudoku / Zip / Patches

Layers 分層:
  core        shared vision + solving primitives   共用的影像與求解基礎
  puzzles     one module per game                  每款遊戲一個模組
  automation  screen capture + mouse control       螢幕擷取與滑鼠操作
  ui          desktop GUI and command line         桌面介面與命令列
"""

__version__ = "1.3.0"
