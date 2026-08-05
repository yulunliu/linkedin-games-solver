"""
滑鼠/鍵盤輸入驅動，包含安全機制。

自動點擊會實際操作使用者的電腦，所以預設是 **dry-run (只列出要做什麼，不真的點)**。
要真的執行必須明確把 dry_run 設成 False。

安全機制:
  - pyautogui 的 FAILSAFE：把滑鼠快速移到螢幕左上角 (0,0) 會直接中止
  - 開始前有倒數，可以趁機切換到瀏覽器視窗或反悔
  - 每個動作之間有可調的間隔，避免點太快讓網頁來不及反應
  - 可以隨時用 stop() 要求中止 (GUI 的「停止」按鈕會用到)
"""

import math
import time
from dataclasses import dataclass, field

import pyautogui

pyautogui.FAILSAFE = True  # 滑鼠移到左上角 (0,0) 即中止
pyautogui.PAUSE = 0.0  # 間隔自行控制


class Aborted(RuntimeError):
    pass


def wait_for_mouse_release(timeout: float = 2.0) -> float:
    """
    等使用者把實體滑鼠左鍵放開，回傳實際等了幾秒。

    為什麼需要：使用者剛按完「開始自動解答」時手還按著滑鼠，
    這時候程式去移動游標會跟實體滑鼠互相搶控制權，點擊就會跑掉。
    與其固定等一段時間 (放開得快的人白等)，不如直接偵測按鍵狀態，
    放開了就馬上開始，把延遲壓到最短。
    """
    started = time.perf_counter()
    try:
        import ctypes

        user32 = ctypes.windll.user32
        VK_LBUTTON = 0x01
        while time.perf_counter() - started < timeout:
            # 最高位為 1 代表該鍵目前是被按住的
            if not (user32.GetAsyncKeyState(VK_LBUTTON) & 0x8000):
                break
            time.sleep(0.02)
    except Exception:
        time.sleep(0.3)
    # 放開後給作業系統一點時間把那次點擊事件處理完
    time.sleep(0.12)
    return time.perf_counter() - started


def focus_window_at(x: int, y: int) -> str | None:
    """
    把「螢幕上這個座標所屬的視窗」切到最前面，回傳視窗標題。

    為什麼需要：如果 Chrome 不在最前面，第一次點擊會被作業系統當成
    「啟用視窗」而被吃掉，網頁收不到那一下 —— 結果就是第一格沒被填。
    倒數秒數設 0 時特別容易發生 (使用者沒時間自己切到瀏覽器)。
    這裡在開始點擊前直接用 Win32 API 啟用目標視窗，就不會浪費第一下。
    """
    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        point = wintypes.POINT(int(x), int(y))
        hwnd = user32.WindowFromPoint(point)
        if not hwnd:
            return None
        root = user32.GetAncestor(hwnd, 2) or hwnd  # GA_ROOT = 2
        user32.SetForegroundWindow(root)
        buf = ctypes.create_unicode_buffer(256)
        user32.GetWindowTextW(root, buf, 256)
        time.sleep(0.25)
        return buf.value or None
    except Exception:
        return None


#: 同一個位置連點時，兩次點擊之間至少要隔這麼久 (秒)。
#:
#: 實測發現：在同一點快速連點，作業系統會把它們歸類成「雙擊/三擊」手勢
#: (Tk 收到的是 <Double-Button-1>/<Triple-Button-1> 而不是多個 <Button-1>)。
#: 遊戲若把「點兩下」當成兩次獨立的點擊來循環狀態 (例如 Tango 的
#: 空白->太陽->月亮)，連點太快就可能只被算成一次操作。
#: Windows 預設的雙擊判定時間是 500ms，所以這裡取略高於它的值。
SAME_SPOT_CLICK_GAP = 0.55


#: 拖曳時每一步最多移動幾像素。
#:
#: 這是 Zip 這種「拖曳畫路徑」的關鍵：網頁是靠滑鼠經過哪些格子來判斷路徑的，
#: 如果一次就從這一格中心「瞬移」到下一格中心，網頁可能只收到起訖兩個位置、
#: 中間經過的格子完全沒被記錄，畫出來的路徑就會跳格、順序錯亂
#: (實測會跳出「您必須按照數字的順序」)。
#: 把每段切成很多小步，網頁才追得上。
DRAG_MAX_STEP_PX = 12


@dataclass
class InputDriver:
    dry_run: bool = True
    #: 整體速度倍率：數字越大越慢。網頁跟不上時把這個調大。
    slowdown: float = 2.0
    click_interval: float = 0.06  # 不同格子之間的間隔 (秒)
    same_spot_gap: float = SAME_SPOT_CLICK_GAP  # 同一格連點之間的間隔 (秒)
    move_duration: float = 0.04  # 滑鼠移動時間 (0 = 瞬移，會讓網頁追不上)
    #: 移動到目標後、按下之前的緩衝時間。有些網頁要先收到 mousemove/hover
    #: 才會把該格視為作用中；移動完立刻點擊有機會被忽略。
    settle_after_move: float = 0.12
    drag_step_delay: float = 0.008
    log: list[str] = field(default_factory=list)
    _stop_requested: bool = False

    def _pause(self, seconds: float):
        if seconds > 0:
            time.sleep(seconds * self.slowdown)

    def stop(self):
        self._stop_requested = True

    def reset(self):
        self._stop_requested = False
        self.log.clear()

    def _check_abort(self):
        if self._stop_requested:
            raise Aborted("已中止")

    def _record(self, message: str):
        self.log.append(message)

    def countdown(self, seconds: int, on_tick=None):
        for remaining in range(seconds, 0, -1):
            self._check_abort()
            if on_tick:
                on_tick(remaining)
            time.sleep(1)

    def click(self, x: int, y: int, clicks: int = 1, label: str = ""):
        self._check_abort()
        suffix = f"  ({label})" if label else ""
        self._record(f"click ({x},{y}) x{clicks}{suffix}")
        if self.dry_run:
            return
        pyautogui.moveTo(x, y, duration=self.move_duration * self.slowdown)
        self._pause(self.settle_after_move)
        for i in range(clicks):
            self._check_abort()
            pyautogui.click()
            # 同一格要連點時，間隔要拉長到超過系統雙擊判定時間，
            # 否則會被當成雙擊手勢而不是兩次獨立點擊。
            # (這個間隔是作業系統的判定門檻，不隨速度倍率縮放)
            if i < clicks - 1:
                time.sleep(self.same_spot_gap)
            else:
                self._pause(self.click_interval)

    def press_key(self, key: str, label: str = ""):
        self._check_abort()
        suffix = f"  ({label})" if label else ""
        self._record(f"key '{key}'{suffix}")
        if self.dry_run:
            return
        pyautogui.press(key)
        time.sleep(self.click_interval)

    @staticmethod
    def _interpolate(points: list[tuple[int, int]], max_step: int) -> list[tuple[int, int]]:
        """把相鄰兩點之間切成不超過 max_step 像素的小步，讓軌跡連續。"""
        dense: list[tuple[int, int]] = [points[0]]
        for (x0, y0), (x1, y1) in zip(points, points[1:]):
            distance = max(abs(x1 - x0), abs(y1 - y0))
            steps = max(1, math.ceil(distance / max_step))
            for i in range(1, steps + 1):
                dense.append((round(x0 + (x1 - x0) * i / steps), round(y0 + (y1 - y0) * i / steps)))
        return dense

    def drag_path(self, points: list[tuple[int, int]], label: str = ""):
        """
        按住左鍵沿著一連串座標拖曳 (Zip 的路徑、Patches 的矩形都會用到)。

        會先把路徑內插成很多小步再走，否則網頁只會收到「起點」和「終點」，
        中間經過的格子沒被記錄，Zip 就會判定順序錯誤。
        """
        self._check_abort()
        if len(points) < 2:
            return
        suffix = f"  ({label})" if label else ""
        self._record(f"drag {len(points)} 點: {points[0]} -> {points[-1]}{suffix}")
        if self.dry_run:
            return

        dense = self._interpolate(points, DRAG_MAX_STEP_PX)
        pyautogui.moveTo(dense[0][0], dense[0][1], duration=self.move_duration * self.slowdown)
        self._pause(self.settle_after_move)
        pyautogui.mouseDown()
        try:
            for x, y in dense[1:]:
                self._check_abort()
                pyautogui.moveTo(x, y)
                self._pause(self.drag_step_delay)
        finally:
            self._pause(self.settle_after_move)
            pyautogui.mouseUp()
        self._pause(self.click_interval)

    def summary(self) -> str:
        mode = "預演 (不會真的點擊)" if self.dry_run else "實際執行"
        return f"[{mode}] 共 {len(self.log)} 個動作"
