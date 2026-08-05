"""
螢幕擷取：把瀏覽器畫面抓成 OpenCV 影像，並記錄它在螢幕上的絕對位置。

之所以要記錄絕對位置，是因為後面要把「影像裡的第 r 列第 c 欄」換算回
「螢幕上的哪個像素」才能移動滑鼠去點。
"""

from dataclasses import dataclass

import cv2
import mss
import numpy as np


@dataclass
class ScreenShot:
    """一張螢幕截圖，以及它在螢幕上的原點座標。"""

    image: np.ndarray  # BGR
    origin_x: int
    origin_y: int

    def to_screen(self, x: int, y: int) -> tuple[int, int]:
        """影像座標 -> 螢幕絕對座標。"""
        return self.origin_x + int(x), self.origin_y + int(y)


def _grab(monitor: dict) -> np.ndarray:
    with mss.mss() as sct:
        raw = sct.grab(monitor)
    frame = np.asarray(raw)  # BGRA
    return cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR)


def capture_screen(monitor_index: int = 1) -> ScreenShot:
    """擷取整個螢幕 (monitor_index=1 是主螢幕，0 是所有螢幕合併)。"""
    with mss.mss() as sct:
        monitor = sct.monitors[monitor_index]
    image = _grab(monitor)
    return ScreenShot(image=image, origin_x=monitor["left"], origin_y=monitor["top"])


def capture_region(left: int, top: int, width: int, height: int) -> ScreenShot:
    """擷取螢幕上指定的矩形區域。"""
    monitor = {"left": int(left), "top": int(top), "width": int(width), "height": int(height)}
    image = _grab(monitor)
    return ScreenShot(image=image, origin_x=monitor["left"], origin_y=monitor["top"])


def list_windows(title_contains: str | None = None) -> list:
    """列出目前可見的視窗 (可用標題關鍵字過濾)，用來挑瀏覽器視窗。"""
    import pygetwindow as gw

    windows = []
    for win in gw.getAllWindows():
        if not win.title.strip():
            continue
        if win.width <= 0 or win.height <= 0:
            continue
        if title_contains and title_contains.lower() not in win.title.lower():
            continue
        windows.append(win)
    return windows


def capture_window(window) -> ScreenShot:
    """擷取某個視窗所在的螢幕範圍。"""
    left, top = max(0, window.left), max(0, window.top)
    return capture_region(left, top, window.width, window.height)


#: 預設擷取範圍的大小。LinkedIn 遊戲頁面的棋盤是置中顯示的，
#: 這個大小足以涵蓋各種謎題的棋盤 (實測棋盤約 410px)，又不會納入太多無關內容。
DEFAULT_REGION_WIDTH = 640
DEFAULT_REGION_HEIGHT = 700
DEFAULT_REGION_TOP = 200


def default_region() -> tuple[int, int, int, int]:
    """
    依螢幕大小算出預設的擷取範圍：水平置中、從瀏覽器內容區開始往下抓一塊。

    (不提供拖曳框選功能：在同一個程式裡再開第二個 tk.Tk() 根視窗會讓
     整個視窗崩潰。改用可直接輸入的固定座標，配合「測試擷取範圍」預覽。)
    """
    primary = primary_monitor()
    left = primary["left"] + (primary["width"] - DEFAULT_REGION_WIDTH) // 2
    top = primary["top"] + DEFAULT_REGION_TOP
    return left, top, DEFAULT_REGION_WIDTH, DEFAULT_REGION_HEIGHT


def primary_monitor() -> dict:
    """
    取得主螢幕。mss 的 monitors[1] 不一定是主螢幕 (多螢幕時可能是副螢幕)，
    所以優先找包含原點 (0,0) 的那一台，那才是 Windows 的主螢幕。
    """
    with mss.mss() as sct:
        monitors = sct.monitors[1:]
    for mon in monitors:
        if mon["left"] <= 0 < mon["left"] + mon["width"] and mon["top"] <= 0 < mon["top"] + mon["height"]:
            return mon
    return monitors[0]
