"""
Mouse / keyboard driver, with safety rails.
滑鼠鍵盤驅動，含安全機制。

Automation moves the user's real mouse, so the default is DRY RUN: actions are
logged but nothing is clicked. Callers must explicitly set dry_run=False.
自動化會實際移動使用者的滑鼠，所以預設是「預演」：只記錄動作、不真的點擊。
呼叫端必須明確設定 dry_run=False 才會執行。

Safety 安全機制:
  - pyautogui FAILSAFE: slamming the mouse into the top-left corner aborts
  - stop() can be called from the UI at any time
  - every delay scales with `slowdown`, so a page that cannot keep up can be
    accommodated without touching the code
  - pyautogui 的 FAILSAFE：把滑鼠甩到左上角即中止
  - 介面可隨時呼叫 stop()
  - 所有延遲都會乘上 `slowdown`，網頁跟不上時不必改程式就能放慢
"""

# Required for `str | None` style annotations to work on Python 3.9, which this
# project supports. Without it the union is evaluated at def time and raises
# TypeError on import - every other module in the package already has it.
# 這行是為了讓 `str | None` 這種型別註記能在 Python 3.9 上運作（本專案支援 3.9）。
# 少了它，聯集會在 def 當下就被求值，import 時直接丟 TypeError ——
# 套件裡其他每個模組本來都有這一行。
from __future__ import annotations

import math
import time
from dataclasses import dataclass, field

from ..core import action_log


def _gui():
    """Load pyautogui on first real use, not at import time.
    第一次真的要用時才載入 pyautogui，而不是在 import 時。

    WHY lazy 為什麼要延後載入:
      importing pyautogui needs a display - on Linux it raises outright without
      X11. Image mode never moves the mouse, and dry runs never move the mouse,
      so neither should be blocked from even starting by a package they will
      never call. Only the code path that actually drives the mouse requires it.
      import pyautogui 需要顯示裝置 —— 在 Linux 上沒有 X11 會直接拋錯。
      圖片模式不會動滑鼠，預演也不會動滑鼠，
      兩者都不該因為一個永遠不會被呼叫的套件而連啟動都不行。
      只有真正要操作滑鼠的那條路徑才需要它。
    """
    global _pyautogui
    if _pyautogui is None:
        import pyautogui

        pyautogui.FAILSAFE = True  # abort by slamming the mouse into a corner 甩到角落即中止
        pyautogui.PAUSE = 0.0      # we time our own gaps 間隔自行控制
        _pyautogui = pyautogui
    return _pyautogui


_pyautogui = None


class Aborted(RuntimeError):
    pass


def wait_for_mouse_release(timeout: float = 2.0) -> float:
    """
    Wait for the user's physical left button to come up. Returns seconds waited.
    等使用者把實體滑鼠左鍵放開，回傳實際等了幾秒。

    WHY 為什麼需要:
      Right after pressing "Solve & Fill" the user's finger is still on the
      button. Moving the cursor then makes the program and the physical mouse
      fight over control and the clicks land in the wrong places. Polling the
      key state rather than waiting a fixed time means someone who lets go
      quickly is not made to wait - which matters, because the whole point is
      to save seconds.
      使用者剛按完「開始自動解答」時手還按著滑鼠。這時候程式去移動游標，
      會跟實體滑鼠互相搶控制權，點擊就會跑掉。直接輪詢按鍵狀態而不是固定等待，
      放開得快的人就不必白等 —— 這很重要，因為這整件事的目的就是省秒數。

    Windows only; elsewhere it falls back to a short fixed wait.
    僅限 Windows；其他平台退回一段固定的短等待。
    """
    started = time.perf_counter()
    try:
        import ctypes

        user32 = ctypes.windll.user32
        VK_LBUTTON = 0x01
        while time.perf_counter() - started < timeout:
            # Top bit set means the key is currently held down.
            # 最高位為 1 代表該鍵目前是被按住的。
            if not (user32.GetAsyncKeyState(VK_LBUTTON) & 0x8000):
                break
            time.sleep(0.02)
    except Exception:
        time.sleep(0.3)
    # Give the OS a moment to finish dispatching that click.
    # 放開後給作業系統一點時間把那次點擊事件處理完。
    time.sleep(0.12)
    return time.perf_counter() - started


def focus_window_at(x: int, y: int) -> str | None:
    """
    Bring the window under this screen point to the front. Returns its title.
    把「螢幕上這個座標所屬的視窗」切到最前面，回傳視窗標題。

    WHY 為什麼需要:
      If Chrome is not already frontmost, the OS consumes the first click as
      "activate this window" and the page never sees it - so the first cell
      silently goes unfilled. Activating the target window up front means no
      click is wasted.
      如果 Chrome 不在最前面，作業系統會把第一次點擊當成「啟用視窗」吃掉，
      網頁根本收不到 —— 結果就是第一格沒被填。事先啟用目標視窗就不會浪費那一下。

    Windows only; returns None elsewhere or on any failure.
    僅限 Windows；其他平台或任何失敗都回傳 None。
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
        buf = ctypes.create_unicode_buffer(256)
        user32.GetWindowTextW(root, buf, 256)
        # Skip the activation (and its 0.25s settle) when the target window
        # is ALREADY foreground. WHY 為什麼: in wait-first mode the user's
        # last action before the fill starts was clicking into the browser
        # to open the puzzle - the window is already frontmost, and the
        # 0.25s settle was a measurable quarter-second of the "about a
        # second before it starts" a user reported. The settle only exists
        # to let a JUST-ACTIVATED window finish coming to the front.
        # 目標視窗「已經」在最前面時，跳過啟用動作（以及它的 0.25 秒緩衝）。
        # 為什麼：先等題目模式下，填答開始前使用者的最後一個動作就是點進
        # 瀏覽器開題目——視窗本來就在最前面，而這 0.25 秒正是使用者回報
        # 「開始前大約一秒」裡量得出來的四分之一秒。這個緩衝存在的唯一
        # 目的，是讓「剛剛才被啟用」的視窗完成切換到前景的過程。
        if user32.GetForegroundWindow() == root:
            return buf.value or None
        user32.SetForegroundWindow(root)
        time.sleep(0.25)
        return buf.value or None
    except Exception:
        return None


#: Minimum gap (seconds) between two clicks on the SAME spot.
#: 同一個位置連點時，兩次點擊之間至少要隔這麼久（秒）。
#:
#: HISTORY 沿革: this was 0.55 - just above Windows' double-click window
#: (GetDoubleClickTime() measured 500ms on this machine) - because rapid
#: same-spot clicks were observed being swallowed into one double-click
#: gesture, advancing a state-cycling cell (Tango's empty -> sun -> moon)
#: one step instead of two. BUT that observation was made against a Tkinter
#: test window, never against the real page - the project's own docs list
#: verifying it on the real site as an open item that was never done.
#: 沿革：原本是 0.55——略高於 Windows 的雙擊判定時間（這台機器用
#: GetDoubleClickTime() 量到 500ms）——因為觀察到同一點快速連點會被吞成
#: 一個雙擊手勢，讓循環狀態的格子（Tango 的 空白->太陽->月亮）只前進一步
#: 而不是兩步。但那個觀察是對著「Tkinter 測試視窗」做的，從來沒有對真實
#: 網頁驗證過——專案自己的文件一直把「在真實網站上驗證這個值」列為
#: 未完成的待辦。
#:
#: WHY 0.15 IS WORTH TRYING 為什麼值得改成 0.15:
#:   1. Browsers fire BOTH `click` events even inside the OS double-click
#:      window - `dblclick` is delivered in addition to, not instead of, the
#:      two clicks - so a web game listening to click/pointer events receives
#:      two events regardless. The Tkinter behaviour does not transfer.
#:   2. The failure mode is already covered: if a pair ever IS swallowed,
#:      the cell reads one state short, the post-fill verify pass sees it,
#:      and the retry plan recomputes clicks from the FRESH state - a
#:      distance of 1, a single click, no same-spot pair involved - so the
#:      retry converges even if every rapid pair failed.
#:   3. Measured cost of 0.55 at the default speed: one moon cell took
#:      ~0.99s (0.08 move + 0.24 settle + 0.55 gap + 0.12 interval), which
#:      is exactly the "feels like a second per moon" the user reported.
#:      At 0.15 the same cell is ~0.59s; a Tango with 12 moons saves ~4.8s.
#:   1. 瀏覽器就算在作業系統的雙擊判定時間內，也會把「兩次」click 事件都
#:      送出——dblclick 是「額外」多送一個，不是取代那兩次 click——所以
#:      監聽 click/pointer 事件的網頁遊戲無論如何都收得到兩次。Tkinter 的
#:      行為不能直接套用到網頁上。
#:   2. 失敗情況本來就有安全網：萬一連點真的被吞掉，該格會少一個狀態，
#:      填完後的驗證會看到，補點計畫會用「最新讀到的狀態」重新計算點擊
#:      次數——距離是 1，單獨一次點擊，不再有同格連點——所以就算每一組
#:      快速連點都失敗，補點也會收斂。
#:   3. 0.55 在預設速度下的實測成本：一個月亮格約 0.99 秒（移動 0.08 +
#:      緩衝 0.24 + 間隔 0.55 + 點後間隔 0.12），正是使用者回報的
#:      「每個月亮感覺停頓一秒」。改 0.15 後同一格約 0.59 秒；一盤有
#:      12 個月亮的 Tango 可省約 4.8 秒。
#:
#: TO BE VALIDATED IN REAL PLAY 待真實遊玩驗證: if cells start coming out
#: one state short (sun where a moon belongs, X where a crown belongs) and
#: the verify rounds in the session log show repeated single-click repairs,
#: THIS value is the cause - raise it back toward 0.55 and re-measure.
#: 待真實遊玩驗證：如果開始出現格子少一個狀態（該是月亮的變太陽、該是
#: 皇冠的變 X），而且執行記錄檔裡的驗證輪次顯示反覆用單擊補救，原因就是
#: 這個值——把它調回 0.55 方向並重新量測。
SAME_SPOT_CLICK_GAP = 0.15


#: Maximum pixels the pointer may jump in one step while dragging.
#: 拖曳時每一步最多移動幾像素。
#:
#: This is what makes Zip work. The page derives the path from which cells the
#: pointer crossed, so teleporting from one cell centre to the next means the
#: cells in between are never registered - the path skips cells and the game
#: replies "you must follow the number order". Chopping each leg into many
#: small steps lets the page keep up.
#: 這是 Zip 能成功的關鍵。網頁是靠指標經過哪些格子來決定路徑的，
#: 所以從這一格中心「瞬移」到下一格中心，中間經過的格子完全不會被記錄 ——
#: 路徑就會跳格，遊戲會回「您必須按照數字的順序」。
#: 把每一段切成很多小步，網頁才追得上。
DRAG_MAX_STEP_PX = 12


@dataclass
class InputDriver:
    #: Default is a dry run: actions are logged, nothing is clicked.
    #: 預設是預演：只記錄動作、不真的點擊。
    dry_run: bool = True
    #: Global speed multiplier - higher is slower. Raise it when the page
    #: cannot keep up.
    #: 整體速度倍率：數字越大越慢。網頁跟不上時把這個調大。
    slowdown: float = 2.0
    #: Gap between clicks on DIFFERENT cells (seconds).
    #: 不同格子之間的間隔（秒）。
    click_interval: float = 0.06
    #: Gap between clicks on the SAME cell (seconds). See SAME_SPOT_CLICK_GAP.
    #: 同一格連點之間的間隔（秒）。見 SAME_SPOT_CLICK_GAP。
    same_spot_gap: float = SAME_SPOT_CLICK_GAP
    #: Cursor travel time. 0 would teleport, which the page cannot follow.
    #: 滑鼠移動時間。設 0 會變成瞬移，網頁追不上。
    move_duration: float = 0.04
    #: Settling time after arriving and before pressing. Some pages only treat
    #: a cell as active once they have seen a mousemove/hover over it, so a
    #: click issued the instant the cursor lands can be ignored.
    #: 移動到目標後、按下之前的緩衝時間。有些網頁要先收到 mousemove/hover
    #: 才會把該格視為作用中；移動完立刻點擊有機會被忽略。
    settle_after_move: float = 0.12
    #: Delay between the interpolated steps of a drag.
    #: 拖曳過程中每個插值小步之間的延遲。
    drag_step_delay: float = 0.008
    #: Every action taken, in order. This is what dry run produces and what the
    #: tests assert against.
    #: 依序記錄每個動作。預演模式產出的就是這個，測試也是用它來驗證。
    log: list[str] = field(default_factory=list)
    #: Optional callable() -> bool asked before every action. Returning False
    #: aborts the plan. This is how BoardWatch stops a fill whose board has been
    #: replaced; see automation/board_watch.py.
    #: 選用的 callable() -> bool，每個動作前都會問。回傳 False 就中止計畫。
    #: BoardWatch 就是靠這個在棋盤被換掉時停下填答；見 automation/board_watch.py。
    guard: object = None
    #: Set when `guard` was the thing that stopped us, so the UI can say why.
    #: 當中止是 `guard` 造成的時設為 True，讓介面能說明原因。
    stopped_by_guard: bool = False
    _stop_requested: bool = False

    def _pause(self, seconds: float):
        if seconds > 0:
            time.sleep(seconds * self.slowdown)

    def stop(self):
        action_log.log("STOP", "InputDriver.stop() called")
        self._stop_requested = True

    @property
    def stop_requested(self) -> bool:
        """Public read of the stop flag, so a caller outside this class (the
        solve step, which runs before any click and so never calls
        _check_abort itself) can poll it without reaching into a private
        attribute.
        公開讀取停止旗標，讓這個類別以外的呼叫端（求解步驟——它在任何點擊
        之前執行，本身從來不會呼叫 _check_abort）可以用來輪詢，
        不需要直接存取私有屬性。
        """
        return self._stop_requested

    def reset(self):
        self._stop_requested = False
        self.stopped_by_guard = False
        self.log.clear()

    def _check_abort(self, ask_guard: bool = True):
        """Checked before every action, so Stop takes effect within one click.
        每個動作前都會檢查，所以按下停止後最多再過一個點擊就會生效。

        The board guard is asked here too, so every action - clicks, key
        presses, the start of a drag - is covered by construction and no player
        can forget to ask.
        盤面保護也在這裡詢問，所以所有動作（點擊、按鍵、拖曳的開始）在結構上
        就都被涵蓋，沒有哪個 player 會忘記問。

        ask_guard=False IS THE IMPORTANT PART, and it is used INSIDE a drag.
        ask_guard=False 才是重點，它用在「拖曳進行中」。

        A drag is committed by mouseUp, wherever the pointer happens to be. So
        aborting partway does not cancel anything - it SENDS A SHORTER DRAG.
        Measured on live_patches.png with the guard asked inside the drag loop:
        a rectangle intended as 1x4 was released after 12 steps and the page
        received 1x2; at 30 steps 1x4 became 1x2; at 45 steps 3x1 became 2x1.
        The safety mechanism was placing wrong pieces on the board itself.
        拖曳是靠 mouseUp 送出的，而且是在指標當下的位置送出。所以中途中止
        不會取消任何東西 —— 它會「送出一段較短的拖曳」。
        在 live_patches.png 實測，把保護放進拖曳迴圈裡問：
        本來要畫 1x4 的矩形在第 12 步被放開，網頁收到的是 1x2；
        第 30 步時 1x4 變 1x2；第 45 步時 3x1 變 2x1。
        安全機制自己在棋盤上放了錯誤的方塊。

        The cost was the other half of it. Guard calls per plan: tango 72,
        queens 27, sudoku 72, zip 481, patches 169 - 821 for one sitting, at
        roughly 110-160ms each, which is 73-104s of pure checking, and it held
        the physical left button down for 39.2s on Zip against 8.1s unguarded.
        另一半代價是成本。每個計畫問保護的次數：tango 72、queens 27、sudoku 72、
        zip 481、patches 169 —— 一輪五款共 821 次，每次約 110~160 毫秒，
        等於 73~104 秒純粹在檢查，而且讓 Zip 的實體左鍵被按住 39.2 秒
        （沒有保護時是 8.1 秒）。

        So: check the board BEFORE a drag starts, never during. Once the button
        is down the only correct thing is to finish the stroke.
        所以：在拖曳「開始前」檢查盤面，進行中絕不檢查。按鍵一旦按下，
        唯一正確的做法就是把這一筆畫完。
        """
        if self._stop_requested:
            raise Aborted("aborted / 已中止")
        if ask_guard and self.guard is not None and not self.guard():
            self.stopped_by_guard = True
            self._stop_requested = True   # latch, so nothing restarts it 鎖定，不會被重啟
            # The guard itself (board_watch.still_there) already logged WHY in
            # detail; this line marks the moment input_driver actually acted
            # on that verdict and aborted the plan, so the ACTION trace shows
            # exactly which action never happened.
            # 保護本身（board_watch.still_there）已經詳細記錄了「為什麼」；
            # 這一行標記的是 input_driver 真正依照那個判斷中止計畫的那一刻，
            # 讓動作記錄能明確看出「哪一個動作沒有發生」。
            action_log.log("GUARD", "guard rejected the next action -> aborting plan")
            raise Aborted("board changed / 盤面已改變")

    def _record(self, message: str):
        self.log.append(message)
        action_log.log("ACTION", message)

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

        # A dry run must take the SAME abort checks as a live run, so a test can
        # prove where a plan stops. Only the mouse calls and the sleeps are
        # skipped - never the loop that decides how often we check.
        # Measured before this change: a 2-click cell reached _check_abort once
        # in dry run but three times live, so any test of "where did it stop"
        # was measuring a code path the user never runs.
        # 預演必須跟實際執行走過「一樣多」的中止檢查，測試才能證明計畫停在哪裡。
        # 只跳過操作滑鼠與睡眠，絕不跳過「決定檢查幾次」的迴圈本身。
        # 改動前實測：兩下的格子在預演只檢查 1 次、實際執行檢查 3 次，
        # 所以任何「停在哪裡」的測試量到的都是使用者不會走的路徑。
        if not self.dry_run:
            _gui().moveTo(x, y, duration=self.move_duration * self.slowdown)
            self._pause(self.settle_after_move)
        for i in range(clicks):
            self._check_abort()
            if self.dry_run:
                continue
            _gui().click()
            # Repeat clicks on one cell must be spaced beyond the OS
            # double-click window, or they register as one gesture instead of
            # two separate clicks. This gap is an OS threshold, so unlike every
            # other delay here it deliberately does NOT scale with `slowdown`.
            # 同一格要連點時，間隔必須拉長到超過作業系統的雙擊判定時間，
            # 否則會被當成一個手勢而不是兩次獨立點擊。
            # 這個間隔是作業系統的門檻，所以跟這裡其他延遲不同，
            # 它刻意不隨 `slowdown` 縮放。
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
        _gui().press(key)
        time.sleep(self.click_interval)

    @staticmethod
    def _interpolate(points: list[tuple[int, int]], max_step: int) -> list[tuple[int, int]]:
        """Chop each leg into steps of at most max_step pixels, so the path is
        continuous rather than a series of jumps.
        把相鄰兩點之間切成不超過 max_step 像素的小步，讓軌跡連續而不是一連串跳躍。"""
        dense: list[tuple[int, int]] = [points[0]]
        for (x0, y0), (x1, y1) in zip(points, points[1:]):
            distance = max(abs(x1 - x0), abs(y1 - y0))
            steps = max(1, math.ceil(distance / max_step))
            for i in range(1, steps + 1):
                dense.append((round(x0 + (x1 - x0) * i / steps), round(y0 + (y1 - y0) * i / steps)))
        return dense

    def drag_path(self, points: list[tuple[int, int]], label: str = ""):
        """
        Drag with the left button held along a sequence of points.
        Used by Zip (the path) and Patches (each rectangle).
        按住左鍵沿著一連串座標拖曳。Zip 的路徑與 Patches 的每個矩形都會用到。

        The path is interpolated first. Without that the page only receives the
        start and the end, the cells in between are never registered, and Zip
        rejects the result as out of order.
        路徑會先做插值。少了這一步，網頁只會收到起點與終點，
        中間經過的格子完全不會被記錄，Zip 就會判定順序錯誤。

        Every drag asks the guard at entry, unconditionally. An earlier design
        had a caller (PatchesPlayer) skip this for specific rectangles it
        judged safe - replaced by BoardWatch.failure_tolerance, which reacts
        to OBSERVED persistent detection failure instead of a fixed position
        in the plan (see failure_tolerance's own docstring for why the
        position-based version could not be trusted). This function no longer
        needs to know anything about that.
        每一筆拖曳在進入時都會無條件詢問保護。先前的設計是讓呼叫端
        （PatchesPlayer）對它判斷安全的特定矩形跳過檢查——已經改用
        BoardWatch.failure_tolerance 取代，它是對「觀察到的持續偵測失敗」
        做反應，而不是計畫裡的固定位置（為什麼位置判斷法不可信，見
        failure_tolerance 自己的文件字串）。這個函式不再需要知道那件事。
        """
        self._check_abort()
        if len(points) < 2:
            return
        suffix = f"  ({label})" if label else ""
        self._record(f"drag {len(points)} pts / 點: {points[0]} -> {points[-1]}{suffix}")

        # As in click(): dry run walks the same loop and takes the same abort
        # checks, and skips only the mouse and the sleeps. Skipping the sleeps
        # matters as much as skipping the mouse - the Zip fixture interpolates
        # to 481 steps, which would make a "preview" sit there for ~7.7s.
        # 跟 click() 一樣：預演走同一個迴圈、做同樣的中止檢查，
        # 只跳過滑鼠與睡眠。跳過睡眠跟跳過滑鼠一樣重要 ——
        # Zip 的測試圖會插值成 481 步，不跳的話「預演」會卡在那裡約 7.7 秒。
        dense = self._interpolate(points, DRAG_MAX_STEP_PX)
        if not self.dry_run:
            _gui().moveTo(dense[0][0], dense[0][1], duration=self.move_duration * self.slowdown)
            self._pause(self.settle_after_move)
            _gui().mouseDown()
        try:
            for x, y in dense[1:]:
                # ask_guard=False: the button is already down, so aborting here
                # would COMMIT a shorter drag rather than cancel it. Only the
                # user's own Stop may interrupt a stroke in flight.
                # ask_guard=False：按鍵已經按下去了，這裡中止不是取消而是
                # 「送出一段較短的拖曳」。只有使用者自己按停止才能打斷進行中的一筆。
                self._check_abort(ask_guard=False)
                if self.dry_run:
                    continue
                _gui().moveTo(x, y)
                self._pause(self.drag_step_delay)
        finally:
            # mouseUp in `finally`: an abort mid-drag must never leave the
            # button held down, or the user's mouse is stuck selecting things.
            #
            # BUT note what that means, because it is NOT a safety net:
            # releasing partway through COMMITS a shorter drag. For Patches that
            # is a real rectangle placed on the board - a wrong piece put there
            # by the abort mechanism itself. So the board guard must be checked
            # at drag ENTRY, never inside this loop.
            # mouseUp 放在 finally：拖曳中途中止時絕對不能讓按鍵維持按下，
            # 否則使用者的滑鼠會卡在一直選取東西的狀態。
            #
            # 但要清楚這代表什麼，它「不是」安全網：中途放開等於「送出」一段較短的
            # 拖曳。對 Patches 來說那是一個真的被放上棋盤的矩形 ——
            # 由中止機制自己放上去的錯誤方塊。所以盤面檢查必須在拖曳「開始前」做，
            # 絕不能放進這個迴圈裡。
            if not self.dry_run:
                self._pause(self.settle_after_move)
                _gui().mouseUp()
        if not self.dry_run:
            self._pause(self.click_interval)

    def summary(self) -> str:
        mode = "preview, nothing clicked / 預演，不會真的點擊" if self.dry_run \
            else "live / 實際執行"
        return f"[{mode}] {len(self.log)} actions / 個動作"
