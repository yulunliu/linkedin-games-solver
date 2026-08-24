"""
Automation layer: capture the screen, map coordinates, drive the mouse, verify.
自動化層：擷取螢幕、換算座標、操作滑鼠、驗證結果。

  capture       screen -> image + origin       螢幕 -> 影像與來源位置
  board_wait    wait for a puzzle to appear    等待題目出現
  board_watch   is our board still there?      填答途中：棋盤還是原本那個嗎？
                asked mid-plan, between actions 動作之間逐一詢問
  mapper        board cell -> screen pixel     棋盤格 -> 螢幕像素
  input_driver  safe mouse / keyboard actions  安全的滑鼠鍵盤操作
  players       answer -> action sequence      答案 -> 操作序列
  verify        check and re-click             檢查與補點

Not re-exported here like the others - callers reach it as
`from ..automation import board_watch` and use `board_watch.attach(...)`
directly, since its public surface is one entry point plus a result object,
not a handful of top-level names worth flattening.
這裡沒有像其他模組一樣重新匯出——呼叫端是用
`from ..automation import board_watch`、直接呼叫
`board_watch.attach(...)`，因為它對外只有一個進入點加一個結果物件，
沒有多個頂層名稱值得攤平匯出。
"""

from .board_wait import wait_for_board, wait_for_board_gone
from .capture import (
    ScreenShot,
    capture_region,
    capture_screen,
    default_region,
    from_file_image,
    primary_monitor_size,
)
from .input_driver import Aborted, InputDriver, focus_window_at, wait_for_mouse_release
from .mapper import BoardMapper
from .players import PlayPlan, build_plan
from .verify import VerifyReport, build_retry_plan, verify
from .verify import supports as verify_supports

__all__ = [
    "ScreenShot", "capture_region", "capture_screen", "default_region", "from_file_image",
    "primary_monitor_size",
    "wait_for_board", "wait_for_board_gone",
    "InputDriver", "Aborted", "focus_window_at", "wait_for_mouse_release",
    "BoardMapper", "PlayPlan", "build_plan",
    "VerifyReport", "verify", "verify_supports", "build_retry_plan",
]
