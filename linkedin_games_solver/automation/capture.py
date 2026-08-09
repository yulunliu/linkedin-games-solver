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

from ..core import action_log

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


def primary_monitor_size() -> tuple[int, int] | None:
    """Current primary monitor's (width, height), or None if it cannot be read.
    目前主螢幕的 (寬, 高)；讀不到時回傳 None。

    Used to notice when the screen this app is running on has changed size
    since the capture region was last calibrated - see ui/app.py's
    resolution-change warning. Kept separate from primary_monitor() (which
    returns mss's raw monitor dict) because callers here only ever need the
    two numbers, not the dict shape mss happens to use - and because a
    caller that only wants "did the screen change" should not need to know
    mss exists at all.
    用來察覺「這個程式現在所在的螢幕，跟上次校準擷取範圍時比起來尺寸變了」——
    見 ui/app.py 的解析度改變警告。跟 primary_monitor()（回傳 mss 原始的
    monitor dict）分開，是因為這裡的呼叫端只需要兩個數字，不需要 mss
    剛好用的那種 dict 形狀——而且只是想知道「螢幕是不是變了」的呼叫端，
    不應該連 mss 存在都要知道。
    """
    try:
        monitor = primary_monitor()
    except Exception:
        return None
    return monitor["width"], monitor["height"]


#: Fallback origin used when mss cannot even be imported (see default_region).
#: Not centred on anything real - it exists only so the app can start; the
#: region controls remain fully editable once it does.
#: mss 連匯入都失敗時的退路原點（見 default_region）。沒有對齊任何真實的
#:東西——它存在的唯一目的是讓程式能啟動；啟動之後範圍欄位還是完全可以編輯。
_FALLBACK_LEFT = 100
_FALLBACK_TOP = 100


def default_region() -> tuple[int, int, int, int]:
    """Default capture rectangle: horizontally centred on the primary monitor.
    預設擷取矩形：在主螢幕上水平置中。

    Falls back to a fixed rectangle if the primary monitor cannot even be
    read. WHY 為什麼: this is called on every GUI first run regardless of
    mode - DEFAULTS["region"] is None until the user saves one - so a
    machine where mss cannot be imported (no display, or the package is
    simply missing) used to prevent the GUI from starting AT ALL, even in
    image mode, which never captures anything. README and pyproject both
    promise image mode needs neither mss nor pyautogui; this is what makes
    that true at startup too, not just while running.
    如果連主螢幕都讀不到，退回一個固定的矩形。為什麼：這個函式在 GUI 每一次
    第一次啟動時都會被呼叫，不管是哪個模式——DEFAULTS["region"] 在使用者
    存過一次之前都是 None——所以一台 mss 連匯入都失敗的機器（沒有顯示裝置，
    或單純沒裝這個套件），以前會讓 GUI 完全開不起來，即使是根本不會擷取
    任何畫面的圖片模式。README 跟 pyproject 都保證圖片模式不需要 mss 或
    pyautogui；這個修正讓這件事在「啟動的當下」也成立，不是只在執行期間。
    """
    try:
        monitor = primary_monitor()
    except Exception as exc:
        action_log.log("WARN", f"primary_monitor() failed ({type(exc).__name__}: {exc}), "
                        f"falling back to a fixed region")
        return _FALLBACK_LEFT, _FALLBACK_TOP, DEFAULT_REGION_WIDTH, DEFAULT_REGION_HEIGHT
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
