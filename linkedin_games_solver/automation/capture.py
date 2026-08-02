"""
Screen capture, plus the mapping back to absolute screen coordinates.
螢幕擷取，以及換算回螢幕絕對座標。

The solver works on an image; the mouse works in screen coordinates. Every
capture therefore records where it came from, so "row r, column c" can be turned
back into "this pixel on screen".
求解器處理的是影像，滑鼠用的是螢幕座標。所以每次擷取都會記錄它的來源位置，
才能把「第 r 列第 c 欄」換算回「螢幕上的這個像素」。
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

#: Default capture region, sized to comfortably contain a centred game card.
#: 預設擷取範圍，大小足以涵蓋置中的遊戲卡片。
DEFAULT_REGION_WIDTH = 640
DEFAULT_REGION_HEIGHT = 700
DEFAULT_REGION_TOP = 200


@dataclass
class ScreenShot:
    """A captured image and where on screen it came from.
    擷取到的影像，以及它在螢幕上的來源位置。"""

    image: np.ndarray  # BGR
    origin_x: int
    origin_y: int

    def to_screen(self, x: int, y: int) -> tuple[int, int]:
        """Image coordinates -> absolute screen coordinates.
        影像座標 -> 螢幕絕對座標。"""
        return self.origin_x + int(x), self.origin_y + int(y)


def _mss():
    """Import mss only when the screen is actually read.
    只有真的要讀螢幕時才 import mss。

    Image mode solves a file and never captures anything, so it must not be
    stopped from starting by a screen-capture package. On a machine without a
    display, importing mss can fail outright.
    圖片模式解的是檔案、從來不擷取畫面，所以不該因為一個螢幕擷取套件而無法啟動。
    在沒有顯示裝置的機器上，import mss 有可能直接失敗。
    """
    import mss

    return mss


def _grab(monitor: dict) -> np.ndarray:
    with _mss().mss() as sct:
        raw = sct.grab(monitor)
    return cv2.cvtColor(np.asarray(raw), cv2.COLOR_BGRA2BGR)


def primary_monitor() -> dict:
    """The primary display.
    主螢幕。

    mss.monitors[1] is not necessarily primary on a multi-monitor setup, so we
    look for the one containing the origin (0,0) - that is Windows' primary.
    多螢幕時 mss.monitors[1] 不一定是主螢幕，所以找包含原點 (0,0) 的那一台，
    那才是 Windows 的主螢幕。
    """
    with _mss().mss() as sct:
        monitors = sct.monitors[1:]
    for monitor in monitors:
        if (monitor["left"] <= 0 < monitor["left"] + monitor["width"]
                and monitor["top"] <= 0 < monitor["top"] + monitor["height"]):
            return monitor
    return monitors[0]


def default_region() -> tuple[int, int, int, int]:
    """Default capture rectangle: horizontally centred on the primary monitor.
    預設擷取矩形：在主螢幕上水平置中。"""
    monitor = primary_monitor()
    left = monitor["left"] + (monitor["width"] - DEFAULT_REGION_WIDTH) // 2
    top = monitor["top"] + DEFAULT_REGION_TOP
    return left, top, DEFAULT_REGION_WIDTH, DEFAULT_REGION_HEIGHT


def capture_region(left: int, top: int, width: int, height: int) -> ScreenShot:
    monitor = {"left": int(left), "top": int(top), "width": int(width), "height": int(height)}
    return ScreenShot(image=_grab(monitor), origin_x=monitor["left"], origin_y=monitor["top"])


def capture_screen() -> ScreenShot:
    monitor = primary_monitor()
    return ScreenShot(image=_grab(monitor), origin_x=monitor["left"], origin_y=monitor["top"])


def from_file_image(image: np.ndarray) -> ScreenShot:
    """Wrap a loaded image so image mode can share the same plumbing.
    把載入的圖片包起來，讓圖片模式能共用同一套流程。

    Origin is (0,0) because a file has no screen position - image mode never
    drives the mouse, so the coordinates are only used for drawing.
    原點是 (0,0)，因為檔案沒有螢幕位置 —— 圖片模式不會操作滑鼠，
    座標只用來繪圖。
    """
    return ScreenShot(image=image, origin_x=0, origin_y=0)
