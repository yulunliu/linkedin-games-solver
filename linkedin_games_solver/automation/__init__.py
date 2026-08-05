"""
Automation layer: capture the screen, map coordinates, drive the mouse, verify.
自動化層：擷取螢幕、換算座標、操作滑鼠、驗證結果。

  capture       screen -> image + origin       螢幕 -> 影像與來源位置
  board_wait    wait for a puzzle to appear    等待題目出現
  mapper        board cell -> screen pixel     棋盤格 -> 螢幕像素
  input_driver  safe mouse / keyboard actions  安全的滑鼠鍵盤操作
  players       answer -> action sequence      答案 -> 操作序列
  verify        check and re-click             檢查與補點
"""

from .board_wait import wait_for_board
from .capture import ScreenShot, capture_region, capture_screen, default_region, from_file_image
from .input_driver import Aborted, InputDriver, focus_window_at, wait_for_mouse_release
from .mapper import BoardMapper
from .players import PlayPlan, build_plan
from .verify import VerifyReport, build_retry_plan, verify

__all__ = [
    "ScreenShot", "capture_region", "capture_screen", "default_region", "from_file_image",
    "wait_for_board",
    "InputDriver", "Aborted", "focus_window_at", "wait_for_mouse_release",
    "BoardMapper", "PlayPlan", "build_plan",
    "VerifyReport", "verify", "build_retry_plan",
]
