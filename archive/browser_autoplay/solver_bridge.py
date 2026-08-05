"""
橋接既有的截圖求解專案 (../tango_solver)。

重點：這裡只「匯入」既有專案的模組來重用辨識與求解邏輯，
**完全不修改** ../tango_solver 底下的任何檔案。
既有專案是一組扁平模組 (import board / import registry ...)，
所以把它的資料夾加進 sys.path 就能直接使用。
"""

import sys
from pathlib import Path

_FROZEN = getattr(sys, "frozen", False)

if _FROZEN:
    # 打包成 exe 之後，tango_solver 的模組已經一起被打包進來了，
    # 直接 import 就好，不需要外部資料夾。
    # (sys._MEIPASS 是 PyInstaller 解壓縮出來的暫存目錄)
    _SOLVER_DIR = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
else:
    _SOLVER_DIR = Path(__file__).resolve().parent.parent / "tango_solver"
    if not _SOLVER_DIR.is_dir():
        raise RuntimeError(
            f"找不到既有的求解專案資料夾: {_SOLVER_DIR}\n"
            "請確認 browser_autoplay 與 tango_solver 放在同一層目錄下。"
        )
    if str(_SOLVER_DIR) not in sys.path:
        sys.path.insert(0, str(_SOLVER_DIR))

# 以下都是既有專案的模組 (原封不動地重用)
import board  # noqa: E402
import grid_detector  # noqa: E402
import registry  # noqa: E402
from puzzle_base import PuzzleResult  # noqa: E402

PUZZLES = registry.PUZZLES
DISPLAY_ORDER = registry.DISPLAY_ORDER
detect_type = registry.detect_type

__all__ = [
    "PUZZLES",
    "DISPLAY_ORDER",
    "detect_type",
    "PuzzleResult",
    "build_board_grid",
    "solver_dir",
]


def solver_dir() -> Path:
    return _SOLVER_DIR


def build_board_grid(image, puzzle_key: str, n_hint: int | None = None):
    """
    取得棋盤的格子座標 (相對於傳入影像)。

    Tango 的棋盤沒有外框，用的是既有專案的「內容定位法」；
    其他四種謎題的棋盤都有明顯外框，走 board.build_grid。
    """
    if puzzle_key == "tango":
        n = n_hint or 6
        bbox = board.find_board_bbox(image)
        if bbox is None:
            bbox = grid_detector.detect_board_bbox_by_content(image, n)
        if bbox is None:
            raise ValueError("找不到棋盤位置")
        x, y, w, h = bbox
        cell_w, cell_h = w / n, h / n
        cell_boxes = [
            [
                (x + round(c * cell_w), y + round(r * cell_h), round(cell_w), round(cell_h))
                for c in range(n)
            ]
            for r in range(n)
        ]
        return board.BoardGrid(n=n, board_bbox=bbox, cell_boxes=cell_boxes)

    return board.build_grid(image, n_hint=n_hint)
