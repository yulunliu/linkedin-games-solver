"""
Automation tests: click counts, resuming a half-finished board, drag continuity.
自動化測試：點擊次數、接續填一半的盤面、拖曳連續性。

No real mouse is moved - the driver runs in dry-run mode and its action log is
inspected.
不會真的移動滑鼠 —— 驅動以預演模式執行，檢查它的動作紀錄。
"""

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from linkedin_games_solver.automation import BoardMapper, InputDriver, build_plan  # noqa: E402
from linkedin_games_solver.automation.capture import ScreenShot  # noqa: E402
from linkedin_games_solver.automation import input_driver as input_driver_module  # noqa: E402
from linkedin_games_solver.automation.input_driver import DRAG_MAX_STEP_PX  # noqa: E402
from linkedin_games_solver.puzzles import queens, tango  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures"


class _FakeGrid:
    """A synthetic n x n board with 10px cells, so expected coordinates are obvious.
    合成的 n x n 棋盤，每格 10px，方便算出預期座標。"""

    def __init__(self, n):
        self.n = n
        self.board_bbox = (0, 0, n * 10, n * 10)
        self.cell_boxes = [[(c * 10, r * 10, 10, 10) for c in range(n)] for r in range(n)]

    def cell_center(self, r, c):
        return c * 10 + 5, r * 10 + 5


def _mapper(n):
    blank = np.zeros((n * 10, n * 10, 3), np.uint8)
    return BoardMapper(shot=ScreenShot(blank, 0, 0), grid=_FakeGrid(n))


def _log_of(plan):
    driver = InputDriver(dry_run=True)
    plan.run(driver)
    return driver.log


# --------------------------------------------------------------- Queens
def test_queens_resumes_half_done_board():
    """8 crowns placed, the last one only half-clicked (an X) -> 1 more click.
    8 個皇冠已放好，最後一個只點到一半（變成 X）-> 只需再點 1 下。"""
    mapper = _mapper(9)
    positions = [(i, (i * 2) % 9) for i in range(9)]
    states = {pos: queens.STATE_QUEEN for pos in positions[:-1]}
    states[positions[-1]] = queens.STATE_X

    plan = build_plan("queens", mapper, {"queens": positions, "cell_states": states})
    log = _log_of(plan)
    assert len(log) == 1, f"should touch one cell only / 只該動一格，實際 {len(log)}"
    assert "x1" in log[0], f"should click once only / 只該點 1 下: {log[0]}"
    print("  queens resume OK")


def test_queens_complete_board_does_nothing():
    mapper = _mapper(9)
    positions = [(i, (i * 2) % 9) for i in range(9)]
    states = {pos: queens.STATE_QUEEN for pos in positions}
    assert _log_of(build_plan("queens", mapper, {"queens": positions, "cell_states": states})) == []
    print("  queens complete board OK")


def test_queens_clears_misplaced_crowns():
    """A crown in the wrong place must be cleared, or the board can never be right.
    放錯位置的皇冠必須清掉，否則盤面永遠不會正確。"""
    mapper = _mapper(5)
    positions = [(0, 0), (1, 2), (2, 4), (3, 1), (4, 3)]
    states = {(4, 4): queens.STATE_QUEEN}  # not part of the answer 不在答案裡
    log = _log_of(build_plan("queens", mapper, {"queens": positions, "cell_states": states}))
    clears = [line for line in log if "clear" in line]
    assert len(clears) == 1, f"should clear exactly one / 應清掉一個: {log}"
    assert "x1" in clears[0], "clearing takes one click / 清除只要點 1 下"
    print("  queens clears misplaced crowns OK")


# --------------------------------------------------------------- Tango
def test_tango_click_counts_follow_current_state():
    """Clicks cycle empty -> sun -> moon -> empty, so counts depend on the state.
    點擊循環是 空白 -> 太陽 -> 月亮 -> 空白，次數取決於目前狀態。"""
    mapper = _mapper(2)
    solution = [[tango.SUN, tango.MOON], [tango.MOON, tango.SUN]]

    cases = [
        ({}, "all empty / 全空白", {(0, 0): 1, (0, 1): 2, (1, 0): 2, (1, 1): 1}),
        ({(0, 0): tango.SUN, (0, 1): tango.MOON, (1, 0): tango.MOON, (1, 1): tango.SUN},
         "already correct / 已填對", {}),
        # (0,0) shows a moon but needs a sun: moon -> empty -> sun = 2 clicks
        # (0,0) 目前是月亮但要太陽：月亮 -> 空白 -> 太陽 = 2 下
        ({(0, 0): tango.MOON}, "wrong symbol / 填錯", {(0, 0): 2, (0, 1): 2, (1, 0): 2, (1, 1): 1}),
        # (0,1) shows a sun but needs a moon: sun -> moon = 1 click
        # (0,1) 目前是太陽但要月亮：太陽 -> 月亮 = 1 下
        ({(0, 1): tango.SUN}, "one step away / 差一步", {(0, 0): 1, (0, 1): 1, (1, 0): 2, (1, 1): 1}),
    ]

    for current, label, expected in cases:
        full = {(r, c): current.get((r, c)) for r in range(2) for c in range(2)}
        plan = build_plan("tango", mapper, {"solution": solution, "givens": set(), "current": full})
        got = {}
        for line in _log_of(plan):
            coords = line.split("(")[1].split(")")[0].split(",")
            x, y = int(coords[0]), int(coords[1])
            got[((y - 5) // 10, (x - 5) // 10)] = int(line.split(" x")[1].split(" ")[0])
        assert got == expected, f"{label}: expected {expected}, got {got}"
    print("  tango click counts OK")


# --------------------------------------------------------------- Patches
def test_patches_asks_the_guard_for_every_rect():
    """Every rectangle asks the guard - unconditionally, with no exceptions
    for position in the plan.
    每一塊矩形都會詢問保護——無條件，不因為在計畫裡的位置而有例外。

    2026-08-04: an earlier design had PatchesPlayer skip the guard for a
    fixed position (the last two rectangles), to work around a fully-tiled
    board defeating the guard's structural re-check. Replaced by
    BoardWatch.failure_tolerance (automation/board_watch.py), which reacts to
    OBSERVED persistent failure instead - a real capture showed the puzzle's
    edge-touching regions are not reliably drawn last, so a position-based
    skip could not be trusted. This test proves PatchesPlayer itself no
    longer makes that decision at all.
    2026-08-04：先前的設計是讓 PatchesPlayer 對固定位置（最後兩塊矩形）
    跳過保護，用來繞開填滿的棋盤讓保護的結構性重新檢查失效這件事。
    已經換成 BoardWatch.failure_tolerance（automation/board_watch.py），
    改成對「觀察到的持續失敗」做反應——一張真實擷取顯示碰到邊緣的區塊
    不一定排在最後畫，位置判斷法不可信。這個測試證明 PatchesPlayer
    自己完全不再做那個決定。
    """
    mapper = _mapper(6)
    rects = [(0, 0, 2, 2), (0, 2, 2, 2), (0, 4, 2, 2),
             (2, 0, 2, 2), (2, 2, 2, 2), (2, 4, 2, 2)]
    plan = build_plan("patches", mapper, {"rects": rects})

    guard_calls = []
    driver = InputDriver(dry_run=True)
    driver.guard = lambda: (guard_calls.append(1), True)[1]
    plan.run(driver)

    assert len(guard_calls) == len(rects), (
        f"expected the guard to be asked once per rectangle ({len(rects)}), "
        f"got {len(guard_calls)} / "
        f"預期保護每一塊矩形都被問一次（{len(rects)} 次），實際 {len(guard_calls)} 次"
    )
    print("  Patches asks the guard for every rect OK")


# --------------------------------------------------------------- dragging
def test_drag_is_interpolated():
    """
    Zip drags must be continuous. The page decides the path from which cells the
    pointer crossed; teleporting cell-to-cell skipped cells and the game replied
    "you must follow the number order".
    Zip 的拖曳必須連續。網頁是靠指標經過哪些格子決定路徑的；一格一格瞬移會跳過
    中間的格子，遊戲就會回「您必須按照數字的順序」。
    """
    driver = InputDriver(dry_run=True)
    for cell_size in (47, 69, 115):
        points = [(100 + cell_size * i, 200) for i in range(8)]
        dense = driver._interpolate(points, DRAG_MAX_STEP_PX)
        steps = [max(abs(b[0] - a[0]), abs(b[1] - a[1])) for a, b in zip(dense, dense[1:])]
        assert max(steps) <= DRAG_MAX_STEP_PX, f"step too big / 步距過大: {max(steps)}"
        assert all(p in dense for p in points), "must pass through every cell centre / 必須經過每格中心"
        assert dense[0] == points[0] and dense[-1] == points[-1]
    print("  drag interpolation OK")


def test_dry_run_does_not_act():
    """Dry run must record actions without performing them.
    預演模式只記錄動作、不執行。"""
    driver = InputDriver(dry_run=True)
    driver.click(10, 20, clicks=2, label="test")
    driver.press_key("3")
    driver.drag_path([(0, 0), (50, 50)])
    assert len(driver.log) == 3
    assert "preview" in driver.summary().lower() or "預演" in driver.summary()
    print("  dry run OK")


def test_stop_aborts():
    from linkedin_games_solver.automation import Aborted

    driver = InputDriver(dry_run=True)
    driver.stop()
    try:
        driver.click(1, 1)
        raise AssertionError("should have raised Aborted / 應丟出 Aborted")
    except Aborted:
        pass
    print("  stop aborts OK")


def test_stop_mid_drag_from_another_thread_still_releases_the_mouse():
    """
    Bug this guards: the GUI's window-close handler used to just call
    root.destroy() - the worker thread is a daemon, so once the process
    exits every daemon thread is killed outright, wherever it happens to be.
    Traced with a fake pyautogui before the fix: MOUSE_DOWN 1, MOUSE_UP 0 -
    drag_path's own `finally: mouseUp()` never got to run. This test proves
    the mechanism the fix actually relies on: driver.stop() called from
    another thread makes an in-flight drag release the mouse and return,
    rather than needing the drag to finish on its own first.
    這個測試守住的問題：GUI 的視窗關閉處理常式以前只會呼叫 root.destroy()——
    工作執行緒是 daemon，行程一結束，不管當下在做什麼都會直接被砍掉。
    修正前用假的 pyautogui 追蹤過：MOUSE_DOWN 1、MOUSE_UP 0——drag_path
    自己的 `finally: mouseUp()` 從來沒機會執行。這個測試證明修正實際依賴
    的機制：從另一個執行緒呼叫 driver.stop()，會讓一筆進行中的拖曳放開
    滑鼠鍵並返回，不需要等那筆拖曳自己先跑完。
    """
    import threading
    import time as time_module

    from linkedin_games_solver.automation import Aborted

    class _RecordingGui:
        def __init__(self):
            self.calls = []

        def moveTo(self, *a, **k): self.calls.append("move")
        def click(self, *a, **k): self.calls.append("click")
        def mouseDown(self, *a, **k): self.calls.append("down")
        def mouseUp(self, *a, **k): self.calls.append("up")
        def press(self, *a, **k): self.calls.append("press")

    stub = _RecordingGui()
    saved = input_driver_module._pyautogui
    input_driver_module._pyautogui = stub
    try:
        driver = InputDriver(dry_run=False)
        # Enough points, spaced far enough apart, that the drag is still in
        # flight when stop() is called from the main thread below - not
        # finished before we get the chance to interrupt it.
        # 點數夠多、間距夠遠，這樣下面主執行緒呼叫 stop() 時這筆拖曳還在
        # 進行中——不會在我們有機會中斷它之前就先跑完了。
        points = [(0, 0), (10_000, 0)]  # interpolates to ~830 steps at 12px/step
        result = {}

        def run():
            try:
                driver.drag_path(points)
                result["aborted"] = False
            except Aborted:
                result["aborted"] = True

        thread = threading.Thread(target=run, daemon=True)
        thread.start()
        # Wait until the drag has genuinely started (mouseDown recorded)
        # before pulling the rug out from under it.
        # 等到這筆拖曳真的開始了（記錄到 mouseDown）才把它中斷。
        deadline = time_module.perf_counter() + 2.0
        while "down" not in stub.calls and time_module.perf_counter() < deadline:
            time_module.sleep(0.005)
        assert "down" in stub.calls, "drag never started / 拖曳從來沒有開始"
        assert "up" not in stub.calls, "drag finished before it could be interrupted / 拖曳在能被中斷之前就跑完了"

        driver.stop()
        thread.join(timeout=2.0)

        assert not thread.is_alive(), (
            "thread did not stop within the timeout - it would be killed mid-drag / "
            "執行緒沒有在逾時內停下——會在拖曳進行中被砍掉"
        )
        assert result.get("aborted") is True, "drag_path did not raise Aborted / drag_path 沒有丟出 Aborted"
        assert stub.calls.count("down") == stub.calls.count("up") == 1, (
            f"mouse button left in an inconsistent state / 滑鼠鍵狀態不一致: {stub.calls}"
        )
    finally:
        input_driver_module._pyautogui = saved
    print("  stop mid-drag from another thread still releases the mouse OK")


def test_dry_run_checks_abort_as_often_as_a_live_run():
    """
    Bug this guards: dry run returned before the per-click loop and before the
    drag interpolation loop, so it reached _check_abort far less often than a
    live run. Measured before the fix: a 2-click cell checked once in dry run
    and three times live; a 500px drag checked once versus 43 times.
    這個測試守住的問題：預演在「逐次點擊」與「拖曳插值」兩個迴圈之前就 return，
    所以它碰到 _check_abort 的次數遠少於實際執行。修正前實測：
    兩下的格子預演 1 次、實際 3 次；500px 的拖曳預演 1 次、實際 43 次。

    Why it matters: any test asserting WHERE a plan stopped would be measuring
    a code path the user never runs. A guard that aborts mid-plan cannot be
    honestly tested until the two agree.
    為什麼重要：任何「計畫停在哪裡」的測試，量到的都會是使用者不會走的路徑。
    在兩者一致之前，中途中止的保護根本無法被誠實驗證。
    """
    class _StubGui:
        """Stands in for pyautogui so a 'live' run touches no real mouse.
        代替 pyautogui，讓「實際執行」也不會碰到真的滑鼠。"""

        def moveTo(self, *a, **k): pass
        def click(self, *a, **k): pass
        def mouseDown(self, *a, **k): pass
        def mouseUp(self, *a, **k): pass
        def press(self, *a, **k): pass

    def count_checks(dry: bool, action):
        driver = InputDriver(dry_run=dry)
        # No sleeping in the "live" run - we are counting checks, not timing.
        # 「實際執行」不要真的睡 —— 這裡數的是檢查次數，不是時間。
        driver.click_interval = driver.settle_after_move = 0.0
        driver.move_duration = driver.drag_step_delay = driver.same_spot_gap = 0.0
        calls = []
        original = driver._check_abort
        driver._check_abort = lambda *a, **k: (calls.append(1), original(*a, **k))[1]
        saved = input_driver_module._pyautogui
        input_driver_module._pyautogui = _StubGui()
        try:
            action(driver)
        finally:
            input_driver_module._pyautogui = saved
        return len(calls), list(driver.log)

    cases = [
        ("2-click cell / 兩下的格子", lambda d: d.click(100, 100, clicks=2)),
        ("500px drag / 500px 拖曳", lambda d: d.drag_path([(100, 100), (600, 100)])),
        ("key press / 按鍵", lambda d: d.press_key("3")),
    ]
    for name, action in cases:
        dry_checks, dry_log = count_checks(True, action)
        live_checks, live_log = count_checks(False, action)
        assert dry_checks == live_checks, (
            f"{name}: dry run checked {dry_checks} times, live checked {live_checks} "
            f"/ 預演檢查 {dry_checks} 次、實際執行 {live_checks} 次"
        )
        assert dry_log == live_log, f"{name}: log differs / 紀錄不同"
    print("  dry run checks abort as often as live OK")


def test_dry_run_touches_no_mouse_module():
    """Dry run must never resolve pyautogui at all - not even to no-op on it.
    預演絕不能去解析 pyautogui —— 連拿到它再不做事都不行。"""
    saved = input_driver_module._pyautogui
    input_driver_module._pyautogui = None

    def explode():
        raise AssertionError("dry run resolved the mouse module / 預演去載入了滑鼠模組")

    saved_gui = input_driver_module._gui
    input_driver_module._gui = explode
    try:
        driver = InputDriver(dry_run=True)
        driver.click(10, 20, clicks=3, label="x")
        driver.press_key("5")
        # (0,0) is pyautogui's FAILSAFE corner - a live run here would raise.
        # (0,0) 是 pyautogui 的 FAILSAFE 角落 —— 實際執行到這裡會拋錯。
        driver.drag_path([(0, 0), (400, 400)])
        assert len(driver.log) == 3
    finally:
        input_driver_module._gui = saved_gui
        input_driver_module._pyautogui = saved
    print("  dry run touches no mouse module OK")


def test_image_mode_needs_no_screen_packages():
    """
    Bug this guards: `mss` and `pyautogui` were imported at module level, so
    importing the app at all required them. Image mode never captures a screen
    or moves a mouse, and on Linux importing pyautogui fails outright without
    X11 - so "image mode works anywhere" was not actually true.
    這個測試守住的問題：`mss` 與 `pyautogui` 原本是在模組層級 import 的，
    所以光是 import 這個程式就需要它們。圖片模式從不擷取畫面、也不動滑鼠，
    而在 Linux 上沒有 X11 時 import pyautogui 會直接失敗 ——
    所以「圖片模式在任何平台都能用」其實並不成立。

    SECOND bug this guards, found by an audit of the FIRST one: this test
    used to only import ui.app, never construct SolverApp - and importing
    was fine, constructing was what broke. _apply_settings() calls
    default_region() on every first run (DEFAULTS["region"] is None until a
    region is saved) regardless of mode, which reached mss even in image
    mode. The test was a false safety signal: it would stay green while the
    exact bug it claimed to cover was still there. Now actually constructs
    SolverApp when a display is available; gracefully skips just that part
    on a genuinely headless machine (CI's Ubuntu jobs) rather than failing
    for an unrelated reason.
    這個測試守住的第二個問題，是稽核第一個問題時發現的：這個測試以前只有
    匯入 ui.app，從來沒有真的建構 SolverApp——匯入沒事，建構才會壞。
    _apply_settings() 在每一次第一次啟動時都會呼叫 default_region()
    （DEFAULTS["region"] 在存過一次範圍之前都是 None），不管是哪個模式，
    這會讓圖片模式也碰到 mss。這個測試以前是一個假的安全訊號：它真正該
    守住的那個 bug 還在，測試卻一直是綠的。現在會在有顯示裝置時真的去
    建構 SolverApp；在真正沒有顯示裝置的機器上（CI 的 Ubuntu job）只會
    優雅地跳過這一段，而不是因為無關的原因失敗。
    """
    import subprocess

    # A subprocess, because import side effects cannot be undone in-process.
    # 用子行程，因為 import 的副作用在同一個行程裡收不回來。
    code = (
        "import sys, builtins\n"
        "real = builtins.__import__\n"
        "def blocked(name, *a, **k):\n"
        "    if name.split('.')[0] in ('pyautogui', 'mss'):\n"
        "        raise ImportError('blocked: ' + name)\n"
        "    return real(name, *a, **k)\n"
        "builtins.__import__ = blocked\n"
        "sys.path.insert(0, r'" + str(Path(__file__).resolve().parents[1]) + "')\n"
        "import tempfile as _tempfile\n"
        "from pathlib import Path as _Path\n"
        "from linkedin_games_solver.core import action_log\n"
        "action_log.LOG_DIR = _Path(_tempfile.mkdtemp())\n"
        "from linkedin_games_solver.automation import InputDriver, from_file_image, build_plan\n"
        "import linkedin_games_solver.ui.app\n"
        "from linkedin_games_solver.core import read_image\n"
        "from linkedin_games_solver.puzzles import solve_image\n"
        "r = solve_image(read_image(r'" + str(FIXTURES / 'live_queens_3.png') + "'))\n"
        "assert r.ok, r.error\n"
        "d = InputDriver(dry_run=True); d.click(1, 2, clicks=2)\n"
        "assert len(d.log) == 1\n"
        "try:\n"
        "    InputDriver(dry_run=False).click(1, 1)\n"
        "    raise SystemExit('real mouse use should have failed')\n"
        "except ImportError:\n"
        "    pass\n"
        "import tkinter as tk\n"
        "try:\n"
        "    root = tk.Tk()\n"
        "except Exception as exc:\n"
        "    print('SKIPPED_NO_DISPLAY: ' + repr(exc))\n"
        "else:\n"
        "    import tempfile, os\n"
        "    from linkedin_games_solver.ui import settings as settings_store\n"
        "    from pathlib import Path as _Path\n"
        "    # A settings file already exists on any machine this has run on\n"
        "    # before (region gets saved on first use), and _apply_settings()\n"
        "    # only reaches default_region() when NO region is saved yet -\n"
        "    # so this must point at a genuinely fresh path to actually\n"
        "    # exercise the first-run code path, or this check silently\n"
        "    # passes without testing anything (confirmed: it did, against\n"
        "    # this same dev machine's real settings file).\n"
        "    # 只要這台機器跑過一次，就會有一份存好的設定檔（第一次使用就會\n"
        "    # 存下 region），而 _apply_settings() 只有在完全沒存過 region\n"
        "    # 時才會走到 default_region()——所以這裡一定要指向一個真正全新\n"
        "    # 的路徑，才會真的走到第一次啟動的程式碼，否則這段檢查會悄悄\n"
        "    # 通過、卻什麼都沒測到（已確認：對著這台開發機真正的設定檔，\n"
        "    # 就是這樣）。\n"
        "    settings_store.SETTINGS_PATH = _Path(tempfile.mkdtemp()) / 'settings.json'\n"
        "    try:\n"
        "        app = linkedin_games_solver.ui.app.SolverApp(root)\n"
        "    finally:\n"
        "        root.destroy()\n"
        "    print('APP_CONSTRUCTED')\n"
        "print('OK')\n"
    )
    result = subprocess.run([sys.executable, "-c", code], capture_output=True,
                            text=True, encoding="utf-8", errors="replace")
    out = result.stdout or ""
    assert "OK" in out, \
        "image mode requires screen packages / 圖片模式需要螢幕相關套件:\n" + \
        (result.stderr or "")[-600:]
    if "SKIPPED_NO_DISPLAY" in out:
        print("  image mode works without pyautogui/mss OK (SolverApp construction skipped - no display)")
    else:
        assert "APP_CONSTRUCTED" in out, \
            "SolverApp did not construct without screen packages / SolverApp 沒有螢幕相關套件時建構失敗:\n" + \
            (result.stderr or "")[-600:]
        print("  image mode works without pyautogui/mss OK (SolverApp construction verified)")


def test_stop_interrupts_an_in_progress_solve():
    """
    Bug this guards (T1): the GUI had no time budget, and pressing "Stop"
    while a solve was still running (not yet filling) did nothing - it only
    checked driver.stop() between fill actions, which never happens until
    solve_image() has already returned. A slow/failing solve (e.g. a bad
    capture that fools no recogniser) used to run the full multi-second
    ladder to completion no matter what the user clicked.
    這個測試守住的問題（T1）：GUI 原本沒有時間預算，在求解階段（還沒開始
    填答）按下「停止」完全沒有作用——它只在填答動作之間檢查
    driver.stop()，而那要等到 solve_image() 已經回傳才會發生。一張騙過
    所有辨識器的失敗截圖，以前不管使用者按什麼都會把整個要花好幾秒的
    ladder 跑完。

    Verified separately (test_recognition.py) that solve_image()'s own
    should_continue callback cuts a failing ladder from ~9.23s to ~0.10s.
    This test proves the GUI actually wires driver.stop_requested into that
    callback end-to-end: self.result (set synchronously right after
    solve_image() returns, BEFORE any of the log lines that follow it) must
    flip to a cancelled result soon after Stop is pressed, not after the
    full ladder.
    另外在 test_recognition.py 驗證過 solve_image() 自己的 should_continue
    回呼能把一次失敗的 ladder 從約 9.23 秒縮短到約 0.10 秒。這個測試要
    證明的是 GUI 有沒有把 driver.stop_requested 真的接到那個回呼上、整條
    路線通不通：self.result（在 solve_image() 一回傳就同步設定，早於它
    後面那串記錄訊息）必須在按下停止後很快變成已取消的結果，而不是等
    整條 ladder 跑完。

    Deliberately does NOT assert on total worker-thread lifetime. Measured
    in this environment: each self._ui(...) call (root.after() from a
    background thread) costs roughly 1s of genuine Tcl cross-thread
    notifier latency regardless of whether the main thread is pumping
    events - a pre-existing cost of every _ui() call in the whole app, not
    something this fix introduced or could reduce, and the failure path
    alone makes 7 such calls. Asserting on that total would make the test's
    passing bound a property of this machine's Tk notifier, not of T1.
    刻意不對「整個工作執行緒的存活時間」做斷言。在這個環境量測到的結果：
    每一次 self._ui(...) 呼叫（從背景執行緒呼叫 root.after()）都要花大約
    1 秒真正的 Tcl 跨執行緒通知延遲，不管主執行緒有沒有在抽事件佇列——
    這是全 app 每一次 _ui() 呼叫本來就有的成本，不是這次修正造成、
    也不是這次修正能縮短的，而失敗路徑光是記錄訊息就有 7 次這種呼叫。
    如果斷言在這個總時間上，測試能不能過就變成這台機器 Tk 通知延遲的
    屬性，而不是 T1 本身的屬性。
    """
    import subprocess

    code = (
        "import sys, tempfile, time\n"
        "from pathlib import Path as _Path\n"
        "sys.path.insert(0, r'" + str(Path(__file__).resolve().parents[1]) + "')\n"
        "import numpy as np\n"
        "import tkinter as tk\n"
        "try:\n"
        "    root = tk.Tk()\n"
        "except Exception as exc:\n"
        "    print('SKIPPED_NO_DISPLAY: ' + repr(exc))\n"
        "    sys.exit(0)\n"
        "from linkedin_games_solver.ui import settings as settings_store\n"
        "settings_store.SETTINGS_PATH = _Path(tempfile.mkdtemp()) / 'settings.json'\n"
        "from linkedin_games_solver.core import action_log\n"
        "action_log.LOG_DIR = _Path(tempfile.mkdtemp())\n"
        "import linkedin_games_solver.ui.app as app_module\n"
        "from linkedin_games_solver.puzzles import CANCELLED\n"
        "from linkedin_games_solver.automation import from_file_image\n"
        "app = app_module.SolverApp(root)\n"
        "rng = np.random.default_rng(0)\n"
        "noise = rng.integers(0, 255, (700, 640, 3), dtype='uint8')\n"
        "app.mode_var.set('image')\n"
        "app.shot = from_file_image(noise)\n"
        "app._run(fill_answers=False)\n"
        "t0 = time.perf_counter()\n"
        "time.sleep(0.5)\n"
        "app._on_stop()\n"
        "cancelled_at = None\n"
        "for _ in range(80):\n"
        "    if app.result is not None:\n"
        "        cancelled_at = time.perf_counter() - t0\n"
        "        break\n"
        "    time.sleep(0.05)\n"
        "result = app.result\n"
        "# Generous - only guards against a permanent hang (e.g. a should_continue\n"
        "# wiring that silently never fires), not against the ~1s/call _ui() cost\n"
        "# above stacking up across the failure path's log lines.\n"
        "# 給得寬鬆——只防真正的永久卡死（例如 should_continue 接線悄悄沒生效），\n"
        "# 不是在防上面那個「每次呼叫約 1 秒」的 _ui() 成本，在失敗路徑的\n"
        "# 記錄訊息上疊加起來。\n"
        "app._worker_thread.join(timeout=20)\n"
        "still_alive = app._worker_thread.is_alive()\n"
        "root.destroy()\n"
        "assert result is not None, 'self.result never set after stop / 按下停止後 self.result 從未被設定'\n"
        "assert result.error == CANCELLED, 'solve was not cancelled: %r / 求解沒有被取消：%r' % (result.error, result.error)\n"
        "assert cancelled_at < 4.0, 'cancellation took too long: %.2fs / 取消花了太久：%.2f 秒' % (cancelled_at, cancelled_at)\n"
        "assert not still_alive, 'worker never finished draining its UI updates / 工作執行緒從未結束、卡在排入畫面更新'\n"
        "print('CANCELLED_AT=%.2f' % cancelled_at)\n"
        "print('OK')\n"
    )
    result = subprocess.run([sys.executable, "-c", code], capture_output=True,
                            text=True, encoding="utf-8", errors="replace")
    out = result.stdout or ""
    assert "OK" in out, \
        "stop did not interrupt an in-progress solve / 停止沒有中斷進行中的求解:\n" + \
        (result.stderr or "")[-1200:]
    if "SKIPPED_NO_DISPLAY" in out:
        print("  stop interrupts an in-progress solve OK (skipped - no display)")
    else:
        print(f"  stop interrupts an in-progress solve OK ({out.strip().splitlines()[-2]})")


def test_the_window_cannot_sit_inside_the_capture_region():
    """
    Bug this guards: a real session (2026-08-08) showed the app's own
    window sitting directly on top of a Mini Sudoku board's first column,
    for the rest of that session - confirmed by matching a saved diagnostic
    capture against the screen recording (92.9% correlation at the matching
    frame). The obscured column's given digits were never seen, the puzzle
    read as under-constrained, and every solve attempt correctly - but
    uselessly - failed with "solution not unique". The old hide-window
    logic ran once, before continuous mode's first wait; the taskbar entry
    a minimised window keeps exists specifically so it CAN be restored (to
    reach Stop) - and once restored, nothing put it back for the rest of
    that multi-puzzle session.
    這個測試守住的問題：一次真實執行（2026-08-08）顯示，程式自己的視窗
    整段時間都疊在 Mini Sudoku 棋盤的第一欄上——已經用存下的診斷畫面
    比對螢幕錄影確認過（在吻合的那一幀相關係數 92.9%）。被擋住的那一欄，
    原本印的數字從來沒被看到，題目就被讀成條件不足，之後每一次嘗試都
    「正確但沒用」地失敗在「解不唯一」。舊的隱藏視窗邏輯只在連續模式
    第一次等待之前執行一次；最小化視窗留著的工作列入口，就是故意讓它
    「能」被還原（好去按停止）——一旦被還原，接下來整個多題的過程中都
    沒有東西把它挪開過。

    Three configurations, one call each: fullscreen forces iconify no
    matter what; hide-window on iconifies; hide-window off keeps the
    window VISIBLE (2026-08-08's session needed it reachable to switch
    speed tiers between rounds) but moves it clear of the capture rect.
    三種設定各呼叫一次：全螢幕不管怎樣都強制最小化；勾了隱藏視窗就
    最小化；沒勾隱藏視窗會維持視窗「看得到」（2026-08-08 那次執行需要
    在兩輪之間切換速度檔，視窗要碰得到），但會被移到擷取矩形外面。
    """
    import subprocess

    code = (
        "import sys, tempfile\n"
        "from pathlib import Path as _Path\n"
        "sys.path.insert(0, r'" + str(Path(__file__).resolve().parents[1]) + "')\n"
        "import tkinter as tk\n"
        "try:\n"
        "    root = tk.Tk()\n"
        "except Exception as exc:\n"
        "    print('SKIPPED_NO_DISPLAY: ' + repr(exc))\n"
        "    sys.exit(0)\n"
        "from linkedin_games_solver.ui import settings as settings_store\n"
        "settings_store.SETTINGS_PATH = _Path(tempfile.mkdtemp()) / 'settings.json'\n"
        "from linkedin_games_solver.core import action_log\n"
        "action_log.LOG_DIR = _Path(tempfile.mkdtemp())\n"
        "import linkedin_games_solver.ui.app as app_module\n"
        "app = app_module.SolverApp(root)\n"
        "region = (200, 200, 640, 700)\n"
        "app.x_var.set(str(region[0])); app.y_var.set(str(region[1]))\n"
        "app.w_var.set(str(region[2])); app.h_var.set(str(region[3]))\n"
        "app.settings['fullscreen'] = False\n"
        ""
        "# 1) hide-window off, window placed squarely inside the region -\n"
        "# must stay visible (not iconic) but move clear of it.\n"
        "app.hide_var.set(False)\n"
        "root.geometry('400x470+250+250')\n"
        "root.update_idletasks()\n"
        "app._keep_window_clear_of_capture()\n"
        "root.update_idletasks()\n"
        "wx, wy = root.winfo_x(), root.winfo_y()\n"
        "ww, wh = root.winfo_width(), root.winfo_height()\n"
        "rl, rt, rw, rh = region\n"
        "overlaps = not (wx + ww <= rl or wx >= rl + rw or wy + wh <= rt or wy >= rt + rh)\n"
        "assert root.state() != 'iconic', 'hide-window off must not iconify / 沒勾隱藏視窗卻被最小化了'\n"
        "assert not overlaps, f'window still overlaps the capture region after being moved / 移動後仍然重疊: ({wx},{wy},{ww},{wh}) vs {region}'\n"
        "print('MOVED_CLEAR_OK')\n"
        ""
        "# 2) hide-window on -> iconify, same as before.\n"
        "root.deiconify(); root.geometry('400x470+250+250'); app._minimized_for_wait = False\n"
        "root.update_idletasks()\n"
        "app.hide_var.set(True)\n"
        "app._keep_window_clear_of_capture()\n"
        "root.update()\n"
        "assert root.state() == 'iconic', 'hide-window on must iconify / 勾了隱藏視窗却沒最小化'\n"
        "print('ICONIFY_ON_HIDE_OK')\n"
        ""
        "# 3) fullscreen -> iconify regardless of hide-window.\n"
        "root.deiconify(); app._minimized_for_wait = False\n"
        "root.update_idletasks()\n"
        "app.hide_var.set(False)\n"
        "app.settings['fullscreen'] = True\n"
        "app._keep_window_clear_of_capture()\n"
        "root.update()\n"
        "assert root.state() == 'iconic', 'fullscreen must iconify even with hide-window off / 全螢幕模式即使沒勾隱藏視窗也應該最小化'\n"
        "print('ICONIFY_ON_FULLSCREEN_OK')\n"
        ""
        "root.destroy()\n"
        "print('OK')\n"
    )
    result = subprocess.run([sys.executable, "-c", code], capture_output=True,
                            text=True, encoding="utf-8", errors="replace")
    out = result.stdout or ""
    assert "OK" in out, \
        "the app window can still land inside the capture region / 程式視窗仍然可能落在擷取範圍裡:\n" + \
        (result.stderr or "")[-1500:]
    if "SKIPPED_NO_DISPLAY" in out:
        print("  the window cannot sit inside the capture region OK (skipped - no display)")
    else:
        assert "MOVED_CLEAR_OK" in out and "ICONIFY_ON_HIDE_OK" in out and "ICONIFY_ON_FULLSCREEN_OK" in out, \
            "one of the three configurations failed / 三種設定裡有一種沒通過:\n" + out
        print("  the window cannot sit inside the capture region OK")


def test_park_mouse_clear_of_capture_avoids_the_region_and_the_failsafe_corner():
    """
    Bug this guards: a real 2026-08-12 Queens board failed with "colour
    grouping looks wrong" - one region read as split into a 31-cell blob
    plus a disconnected 4-cell island, and a separate cell measured a third,
    different colour again. Correlated against the session recording: the
    OS cursor was sitting on the board at the exact capture moment -
    LinkedIn's own :hover styling darkens whatever cell is under it, and
    colour-based region reading has no way to tell that apart from a
    genuinely different region. See InputDriver.park's own docstring for
    the full story.
    這個測試守住的問題：一次真實的 2026-08-12 Queens 棋盤失敗在「色塊分群
    結果不合理」——其中一個色塊被讀成拆成 31 格的主體加上不相連的 4 格
    孤島，另外還有一格單獨量到了第三種不同的顏色。對照螢幕錄影確認：
    擷取的那一刻，滑鼠游標剛好停在棋盤上——LinkedIn 自己的 :hover 樣式
    會把游標底下那格的顏色變深，而以顏色為準的色塊判讀沒有辦法把這個
    跟「真的是不同色塊」分開來。完整脈絡見 InputDriver.park 自己的文件
    字串。

    Three configurations: room beside the region -> park just outside it;
    no room anywhere -> the corner fallback, which must NOT be the literal
    (0,0) pyautogui FAILSAFE pixel; fullscreen -> no safe position exists,
    so this must be a no-op (nothing appended to the driver's log).
    三種設定：旁邊有空間 -> 停在範圍外側緊鄰的地方；哪裡都沒空間 ->
    角落備案，但不能是 pyautogui FAILSAFE 那個 (0,0) 像素本身；全螢幕 ->
    沒有安全的位置，所以必須什麼都不做（driver 的記錄不會多出東西）。
    """
    import subprocess

    code = (
        "import sys, tempfile\n"
        "from pathlib import Path as _Path\n"
        "sys.path.insert(0, r'" + str(Path(__file__).resolve().parents[1]) + "')\n"
        "import tkinter as tk\n"
        "try:\n"
        "    root = tk.Tk()\n"
        "except Exception as exc:\n"
        "    print('SKIPPED_NO_DISPLAY: ' + repr(exc))\n"
        "    sys.exit(0)\n"
        "from linkedin_games_solver.ui import settings as settings_store\n"
        "settings_store.SETTINGS_PATH = _Path(tempfile.mkdtemp()) / 'settings.json'\n"
        "from linkedin_games_solver.core import action_log\n"
        "action_log.LOG_DIR = _Path(tempfile.mkdtemp())\n"
        "import linkedin_games_solver.ui.app as app_module\n"
        "from linkedin_games_solver.automation import InputDriver\n"
        "app = app_module.SolverApp(root)\n"
        "app.driver = InputDriver(dry_run=True)\n"
        "app.driver.reset()\n"
        "app.settings['fullscreen'] = False\n"
        "screen_w, screen_h = root.winfo_screenwidth(), root.winfo_screenheight()\n"
        ""
        "# 1) room to the right of the region -> parked just outside its right edge.\n"
        "region = (200, 200, 640, 700)\n"
        "app.x_var.set(str(region[0])); app.y_var.set(str(region[1]))\n"
        "app.w_var.set(str(region[2])); app.h_var.set(str(region[3]))\n"
        "app._park_mouse_clear_of_capture()\n"
        "log_line = app.driver.log[-1]\n"
        "assert 'park mouse' in log_line, f'no park action recorded / 沒有記錄到停放動作: {log_line!r}'\n"
        "import re\n"
        "mx, my = (int(v) for v in re.search(r'\\((\\d+),(\\d+)\\)', log_line).groups())\n"
        "rl, rt, rw, rh = region\n"
        "assert not (rl <= mx < rl + rw and rt <= my < rt + rh), f'parked INSIDE the region / 停在範圍裡面: ({mx},{my}) vs {region}'\n"
        "assert mx >= rl + rw, f'expected beside the right edge / 預期在右邊緊鄰: {(mx, my)}'\n"
        "print('BESIDE_REGION_OK')\n"
        ""
        "# 2) region fills the whole screen -> corner fallback, not the literal (0,0) FAILSAFE pixel.\n"
        "app.driver.reset()\n"
        "region2 = (0, 0, screen_w, screen_h)\n"
        "app.x_var.set(str(region2[0])); app.y_var.set(str(region2[1]))\n"
        "app.w_var.set(str(region2[2])); app.h_var.set(str(region2[3]))\n"
        "app._park_mouse_clear_of_capture()\n"
        "log_line2 = app.driver.log[-1]\n"
        "mx2, my2 = (int(v) for v in re.search(r'\\((\\d+),(\\d+)\\)', log_line2).groups())\n"
        "assert (mx2, my2) != (0, 0), 'parked on the literal pyautogui FAILSAFE corner / 停在 pyautogui FAILSAFE 的那個角落像素上'\n"
        "print('CORNER_FALLBACK_NOT_FAILSAFE_OK')\n"
        ""
        "# 3) fullscreen -> no safe position exists, must be a no-op.\n"
        "app.driver.reset()\n"
        "app.settings['fullscreen'] = True\n"
        "app._park_mouse_clear_of_capture()\n"
        "assert len(app.driver.log) == 0, f'fullscreen must not park the mouse / 全螢幕模式不該停放滑鼠: {app.driver.log}'\n"
        "print('FULLSCREEN_NOOP_OK')\n"
        ""
        "root.destroy()\n"
        "print('OK')\n"
    )
    result = subprocess.run([sys.executable, "-c", code], capture_output=True,
                            text=True, encoding="utf-8", errors="replace")
    out = result.stdout or ""
    assert "OK" in out, \
        "mouse parking can still land inside the capture region or the FAILSAFE corner / 停放滑鼠仍然可能落在擷取範圍裡或 FAILSAFE 角落上:\n" + \
        (result.stderr or "")[-1500:]
    if "SKIPPED_NO_DISPLAY" in out:
        print("  park mouse clear of capture avoids the region and the failsafe corner OK (skipped - no display)")
    else:
        assert all(marker in out for marker in (
            "BESIDE_REGION_OK", "CORNER_FALLBACK_NOT_FAILSAFE_OK", "FULLSCREEN_NOOP_OK",
        )), out
        print("  park mouse clear of capture avoids the region and the failsafe corner OK")


def test_round_parks_the_mouse_and_recaptures_before_solving():
    """
    End-to-end companion to the unit-level park test above: a real round
    must actually USE the feature, not just have it available. Forces a
    guaranteed-clean solve (a real Queens fixture, correct type) and checks
    that (a) the mouse was parked before solve_image ever ran, and (b) the
    capture solve_image analysed was a FRESH one taken after parking, not
    the (potentially cursor-tainted) frame wait_for_board handed in - proven
    by capture_fn being called MORE than once even though nothing here ever
    fails and needs a retry.
    跟上面單元測試互補的端到端測試：真正的一輪求解，必須「真的用上」這個
    功能，不能只是功能本身存在。強制一次保證乾淨的求解（真實的 Queens
    測試圖、類型給對），檢查 (a) 滑鼠在 solve_image 開始跑之前就已經被
    停放過，(b) solve_image 實際分析的是停放「之後」重新擷取的新畫面，
    不是 wait_for_board 傳進來、可能還被游標影響的那一張——用
    capture_fn 被呼叫超過一次來證明，即使這裡從頭到尾都沒有失敗、
    不需要任何重試。
    """
    import subprocess

    code = (
        "import sys, tempfile\n"
        "from pathlib import Path as _Path\n"
        "sys.path.insert(0, r'" + str(Path(__file__).resolve().parents[1]) + "')\n"
        "import tkinter as tk\n"
        "try:\n"
        "    root = tk.Tk()\n"
        "except Exception as exc:\n"
        "    print('SKIPPED_NO_DISPLAY: ' + repr(exc))\n"
        "    sys.exit(0)\n"
        "from linkedin_games_solver.ui import settings as settings_store\n"
        "settings_store.SETTINGS_PATH = _Path(tempfile.mkdtemp()) / 'settings.json'\n"
        "from linkedin_games_solver.core import action_log\n"
        "action_log.LOG_DIR = _Path(tempfile.mkdtemp())\n"
        "import linkedin_games_solver.ui.app as app_module\n"
        "from linkedin_games_solver.automation import InputDriver, from_file_image\n"
        "from linkedin_games_solver.core import read_image\n"
        "app = app_module.SolverApp(root)\n"
        "app._ui = lambda func, *a: func(*a)\n"
        "app._ui_wait = lambda func, timeout=1.0: func()\n"
        ""
        "board = read_image(r'" + str(FIXTURES / 'live_queens_3.png') + "')\n"
        "calls = {'n': 0}\n"
        "def grab():\n"
        "    calls['n'] += 1\n"
        "    return from_file_image(board)\n"
        "app.driver = InputDriver(dry_run=True)\n"
        "app.driver.reset()\n"
        "app.hide_var.set(True)\n"
        "app.settings['fullscreen'] = False\n"
        "root.geometry('400x470+100+100')\n"
        "root.update_idletasks()\n"
        ""
        "outcome, text = app._round(grab(), 'queens', True, grab)\n"
        "assert outcome == 'done', f'expected a clean solve, got {outcome!r}: {text!r}'\n"
        "assert calls['n'] >= 2, f'expected capture_fn called again after parking (1 for the caller + at least 1 inside _round), got {calls[\"n\"]}'\n"
        "park_index = next((i for i, line in enumerate(app.driver.log) if 'park mouse' in line), None)\n"
        "assert park_index is not None, 'no park action recorded in the round / 這一輪沒有記錄到停放動作'\n"
        "assert park_index == 0, f'park must be the FIRST driver action, before any click - got position {park_index} in {app.driver.log}'\n"
        "print('PARKED_BEFORE_SOLVE_OK')\n"
        ""
        "root.destroy()\n"
        "print('OK')\n"
    )
    result = subprocess.run([sys.executable, "-c", code], capture_output=True,
                            text=True, encoding="utf-8", errors="replace")
    out = result.stdout or ""
    assert "OK" in out, \
        "a round no longer parks the mouse before solving / 一輪求解不再會於求解前停放滑鼠:\n" + \
        (result.stderr or "")[-1500:]
    if "SKIPPED_NO_DISPLAY" in out:
        print("  round parks the mouse and recaptures before solving OK (skipped - no display)")
    else:
        assert "PARKED_BEFORE_SOLVE_OK" in out, out
        print("  round parks the mouse and recaptures before solving OK")


def test_region_monitor_size_only_restamps_when_the_region_actually_changes():
    """
    Guards the resolution-change warning's ONE correctness requirement (see
    ui/app.py's _save_settings comment): the recorded screen size must only
    move when the region VALUE itself was just recalibrated, never merely
    because _save_settings() ran (Start press, language change, ...) with
    the region untouched - otherwise the warning would fire once and then
    go silent forever even though the region is still wrong for the new
    screen.
    這個測試守住解析度改變警告唯一的正確性要求（見 ui/app.py
    _save_settings 的註解）：記錄的螢幕尺寸只能在範圍「數值本身」剛被
    重新校準時才移動，絕不能只因為 _save_settings() 被呼叫過（按開始、
    切語言……）就跟著動，否則警告只會出現一次、之後永遠安靜下去，
    即使範圍其實還是對不上新螢幕。
    """
    import subprocess

    code = (
        "import sys, tempfile\n"
        "from pathlib import Path as _Path\n"
        "sys.path.insert(0, r'" + str(Path(__file__).resolve().parents[1]) + "')\n"
        "import tkinter as tk\n"
        "try:\n"
        "    root = tk.Tk()\n"
        "except Exception as exc:\n"
        "    print('SKIPPED_NO_DISPLAY: ' + repr(exc))\n"
        "    sys.exit(0)\n"
        "from linkedin_games_solver.ui import settings as settings_store\n"
        "settings_store.SETTINGS_PATH = _Path(tempfile.mkdtemp()) / 'settings.json'\n"
        "from linkedin_games_solver.core import action_log\n"
        "action_log.LOG_DIR = _Path(tempfile.mkdtemp())\n"
        "import linkedin_games_solver.ui.app as app_module\n"
        "app = app_module.SolverApp(root)\n"
        "app_module.primary_monitor_size = lambda: (1920, 1080)\n"
        ""
        "# Force the 'previously stored region' to an explicit, unmistakably\n"
        "# different sentinel before the first save - not just trusting that\n"
        "# whatever SolverApp defaulted app.settings['region'] to (mss missing\n"
        "# -> automation.capture's own fallback rectangle) happens to differ\n"
        "# from the values set below. It does not always: a real CI run with no\n"
        "# mss installed defaults to (100,100,640,700), which used to be\n"
        "# EXACTLY the values this test set as its 'first calibration' - the\n"
        "# 'region changed' check then correctly saw no change and skipped the\n"
        "# stamp, failing this test for a reason that had nothing to do with\n"
        "# the stamping logic itself.\n"
        "app.settings['region'] = None\n"
        ""
        "# First save with a region: nothing was stored before, so this counts\n"
        "# as a real calibration - must stamp the (faked) current size.\n"
        "app.x_var.set('100'); app.y_var.set('100'); app.w_var.set('640'); app.h_var.set('700')\n"
        "app._save_settings()\n"
        "assert app.settings['region_monitor_size'] == [1920, 1080], app.settings['region_monitor_size']\n"
        "print('FIRST_STAMP_OK')\n"
        ""
        "# Screen size 'changes' but the region fields are untouched (this is\n"
        "# exactly what pressing Start does) - must NOT restamp.\n"
        "app_module.primary_monitor_size = lambda: (2560, 1440)\n"
        "app._save_settings()\n"
        "assert app.settings['region_monitor_size'] == [1920, 1080], (\n"
        "    'restamped even though the region value did not change / '\n"
        "    '範圍數值沒變卻被重新記錄了: ' + repr(app.settings['region_monitor_size']))\n"
        "print('NO_RESTAMP_ON_UNCHANGED_REGION_OK')\n"
        ""
        "# Now the region VALUE actually changes (a real recalibration) -\n"
        "# must restamp with whatever the current (faked) size is NOW.\n"
        "app.w_var.set('650')\n"
        "app._save_settings()\n"
        "assert app.settings['region_monitor_size'] == [2560, 1440], app.settings['region_monitor_size']\n"
        "print('RESTAMP_ON_CHANGED_REGION_OK')\n"
        ""
        "root.destroy()\n"
        "print('OK')\n"
    )
    result = subprocess.run([sys.executable, "-c", code], capture_output=True,
                            text=True, encoding="utf-8", errors="replace")
    out = result.stdout or ""
    assert "OK" in out, \
        "region_monitor_size stamping logic is wrong / region_monitor_size 的記錄邏輯不對:\n" + \
        (result.stderr or "")[-1500:]
    if "SKIPPED_NO_DISPLAY" in out:
        print("  region_monitor_size only restamps when the region actually changes OK (skipped - no display)")
    else:
        assert all(marker in out for marker in (
            "FIRST_STAMP_OK", "NO_RESTAMP_ON_UNCHANGED_REGION_OK", "RESTAMP_ON_CHANGED_REGION_OK",
        )), out
        print("  region_monitor_size only restamps when the region actually changes OK")


def test_resolution_change_warning_fires_only_when_sizes_differ():
    """
    _warn_if_resolution_changed must log its hint when the current screen
    size disagrees with what was recorded at calibration time, and must
    stay quiet when they match - a warning on every run regardless of
    whether anything changed would just be noise the user learns to ignore.
    _warn_if_resolution_changed 在目前螢幕尺寸跟校準時記錄的不一樣時，
    必須把提示寫進記錄；兩者相符時必須保持安靜——如果不管有沒有變都跳
    警告，使用者很快就會學會忽略它，等於沒有這個功能。
    """
    import subprocess

    code = (
        "import sys, tempfile\n"
        "from pathlib import Path as _Path\n"
        "sys.path.insert(0, r'" + str(Path(__file__).resolve().parents[1]) + "')\n"
        "import tkinter as tk\n"
        "try:\n"
        "    root = tk.Tk()\n"
        "except Exception as exc:\n"
        "    print('SKIPPED_NO_DISPLAY: ' + repr(exc))\n"
        "    sys.exit(0)\n"
        "from linkedin_games_solver.ui import settings as settings_store\n"
        "settings_store.SETTINGS_PATH = _Path(tempfile.mkdtemp()) / 'settings.json'\n"
        "from linkedin_games_solver.core import action_log\n"
        "action_log.LOG_DIR = _Path(tempfile.mkdtemp())\n"
        "import linkedin_games_solver.ui.app as app_module\n"
        "from linkedin_games_solver.i18n import translator\n"
        "app = app_module.SolverApp(root)\n"
        "app.settings['region_monitor_size'] = [1920, 1080]\n"
        ""
        "# Same size as recorded -> quiet.\n"
        "app_module.primary_monitor_size = lambda: (1920, 1080)\n"
        "app._clear_log()\n"
        "app._warn_if_resolution_changed()\n"
        "assert app.log_text.get('1.0', 'end').strip() == '', (\n"
        "    'warned even though the size matches / 尺寸相符卻還是警告了: ' + app.log_text.get('1.0', 'end'))\n"
        "print('QUIET_WHEN_UNCHANGED_OK')\n"
        ""
        "# Different size -> warns, with both the old and new size in the message.\n"
        "app_module.primary_monitor_size = lambda: (2560, 1440)\n"
        "app._clear_log()\n"
        "app._warn_if_resolution_changed()\n"
        "log = app.log_text.get('1.0', 'end')\n"
        "expected = translator('log_resolution_changed', old='1920x1080', new='2560x1440')\n"
        "assert expected in log, 'expected: %r, got: %r' % (expected, log)\n"
        "print('WARNS_WHEN_CHANGED_OK')\n"
        ""
        "root.destroy()\n"
        "print('OK')\n"
    )
    result = subprocess.run([sys.executable, "-c", code], capture_output=True,
                            text=True, encoding="utf-8", errors="replace")
    out = result.stdout or ""
    assert "OK" in out, \
        "resolution-change warning is broken / 解析度改變警告有問題:\n" + \
        (result.stderr or "")[-1500:]
    if "SKIPPED_NO_DISPLAY" in out:
        print("  resolution change warning fires only when sizes differ OK (skipped - no display)")
    else:
        assert "QUIET_WHEN_UNCHANGED_OK" in out and "WARNS_WHEN_CHANGED_OK" in out, out
        print("  resolution change warning fires only when sizes differ OK")


def test_continuous_mode_alerts_and_stops_after_a_failed_round():
    """
    Bug this guards: continuous mode used to leave a failed round completely
    silent - the status text changed but, with the window minimised (hide-window
    or wait-first both iconify it), nothing on screen showed it, and the loop
    would go on to wait for a board that structurally never disappears (the
    user never navigated away from the failed puzzle). This proves the fix
    end to end: a puzzle forced through the WRONG solver (guaranteed to fail
    all MAX_SOLVE_ATTEMPTS retries, same technique test_recognition.py's
    "wrong type does not fake success" uses) makes the window come back into
    view, the status turn into the alert text, and the worker return instead
    of looping on.
    這個測試守住的問題：連續模式以前對一輪失敗完全沒有反應——狀態文字換了，
    但視窗被最小化時（隱藏視窗或先等題目模式都會讓它最小化）畫面上完全
    看不到，迴圈接著會去等一個結構上不會消失的棋盤（使用者根本沒有切離
    那個失敗的題目）。這個測試從頭到尾驗證修正：把一張圖強制用「錯的」
    求解器去解（保證會讓 MAX_SOLVE_ATTEMPTS 全部重試失敗，跟
    test_recognition.py「wrong type does not fake success」用的是同一招），
    視窗要被還原、狀態要變成提醒文字、工作執行緒要直接返回而不是繼續迴圈。

    Also covers the persistent-vs-transient distinction added alongside this
    alert: since capture_fn keeps returning the IDENTICAL image on every
    retry, all MAX_SOLVE_ATTEMPTS attempts must produce the exact same error,
    so self._last_failure_persistent must end up True and the extra hint
    must appear in the log.
    也一併涵蓋跟這個提醒一起加上的「持續性 vs 暫時性」判斷：因為 capture_fn
    每次重試都回傳「一模一樣」的圖，MAX_SOLVE_ATTEMPTS 次嘗試必然得到完全
    相同的錯誤，所以 self._last_failure_persistent 最後必須是 True，
    而且記錄裡要出現那段額外的提示文字。
    """
    import subprocess

    code = (
        "import sys, tempfile\n"
        "from pathlib import Path as _Path\n"
        "sys.path.insert(0, r'" + str(Path(__file__).resolve().parents[1]) + "')\n"
        "import tkinter as tk\n"
        "try:\n"
        "    root = tk.Tk()\n"
        "except Exception as exc:\n"
        "    print('SKIPPED_NO_DISPLAY: ' + repr(exc))\n"
        "    sys.exit(0)\n"
        "from linkedin_games_solver.ui import settings as settings_store\n"
        "settings_store.SETTINGS_PATH = _Path(tempfile.mkdtemp()) / 'settings.json'\n"
        "from linkedin_games_solver.core import action_log\n"
        "action_log.LOG_DIR = _Path(tempfile.mkdtemp())\n"
        "import linkedin_games_solver.ui.app as app_module\n"
        "from linkedin_games_solver.automation import InputDriver, from_file_image\n"
        "from linkedin_games_solver.core import read_image\n"
        "from linkedin_games_solver.i18n import translator\n"
        "app = app_module.SolverApp(root)\n"
        "# _ui/_ui_wait exist to hop onto the Tk thread from the WORKER thread;\n"
        "# this test calls _worker() directly on the main (Tk-owning) thread, so\n"
        "# the normal root.after()-based versions would deadlock waiting for an\n"
        "# event loop nothing is pumping. Made synchronous for this reason only -\n"
        "# the cross-thread handoff itself is covered elsewhere\n"
        "# (test_stop_mid_drag_from_another_thread_still_releases_the_mouse).\n"
        "app._ui = lambda func, *a: func(*a)\n"
        "app._ui_wait = lambda func, timeout=1.0: func()\n"
        ""
        "board = read_image(r'" + str(FIXTURES / 'live_queens_3.png') + "')\n"
        "def grab():\n"
        "    return from_file_image(board)\n"
        "app.driver = InputDriver(dry_run=True)\n"
        "app.driver.reset()\n"
        "app.hide_var.set(True)\n"
        "app.settings['fullscreen'] = False\n"
        "root.geometry('400x470+100+100')\n"
        "root.update_idletasks()\n"
        ""
        "# Forcing a real Queens fixture through Tango's solver is guaranteed to\n"
        "# fail (structural guards, not a threshold call) - see\n"
        "# test_recognition.py's 'wrong type does not fake success'.\n"
        "app._worker(None, 'tango', True, capture_fn=grab, driver_kwargs=dict(dry_run=True))\n"
        ""
        "assert root.state() != 'iconic', 'window was not restored after the alert / 提醒後視窗沒有被還原'\n"
        "print('WINDOW_RESTORED_OK')\n"
        "assert app.status_label.cget('text') == translator('status_solve_failed_stopped'), app.status_label.cget('text')\n"
        "print('STATUS_TEXT_OK')\n"
        "log = app.log_text.get('1.0', 'end')\n"
        "assert translator('log_solve_failed_alert', n=app_module.MAX_SOLVE_ATTEMPTS) in log, log\n"
        "print('LOG_MESSAGE_OK')\n"
        "assert app._last_failure_persistent is True, (\n"
        "    'identical errors on every retry were not recognised as persistent / '\n"
        "    '每次重試都得到一樣的錯誤，卻沒有被判定成持續性失敗')\n"
        "assert translator('log_persistent_failure_hint', n=app_module.MAX_SOLVE_ATTEMPTS) in log, log\n"
        "print('PERSISTENT_HINT_OK')\n"
        "assert str(app.start_btn.cget('state')) == 'normal', 'worker did not reach _finish() / 工作執行緒沒有走到 _finish()'\n"
        "print('FINISHED_OK')\n"
        ""
        "root.destroy()\n"
        "print('OK')\n"
    )
    result = subprocess.run([sys.executable, "-c", code], capture_output=True,
                            text=True, encoding="utf-8", errors="replace")
    out = result.stdout or ""
    assert "OK" in out, \
        "repeated-failure alert is broken / 連續失敗提醒有問題:\n" + \
        (result.stderr or "")[-1500:]
    if "SKIPPED_NO_DISPLAY" in out:
        print("  continuous mode alerts and stops after a failed round OK (skipped - no display)")
    else:
        assert all(marker in out for marker in (
            "WINDOW_RESTORED_OK", "STATUS_TEXT_OK", "LOG_MESSAGE_OK",
            "PERSISTENT_HINT_OK", "FINISHED_OK",
        )), out
        print("  continuous mode alerts and stops after a failed round OK")


def test_guard_abort_does_not_kill_continuous_mode():
    """
    Bug this guards: a real 2026-08-17 session solved three puzzles cleanly,
    then round 4 misread a stale, already-solved board as a fresh puzzle -
    the mid-plan guard correctly rejected it (InputDriver._check_abort's
    "guard rejected the next action -> aborting plan"), but continuous mode
    then silently stopped instead of moving on to the next puzzle, right as
    the user was opening it - wasting the time it took them to notice and
    press Start again.

    Root cause: a guard abort LATCHES the driver's stop_requested flag (the
    "latch, so nothing restarts it" comment in _check_abort) so a click
    cannot slip through after rejection. wait_for_board_gone(), called right
    after _round() returns "guard", runs on that SAME driver instance - the
    next round's genuinely fresh one is not built until the top of the next
    loop iteration - and reads that exact latched flag as its
    should_continue check, so it returns instantly (0 polls) and the loop's
    `if not wait_for_board_gone(...): break` ends the WHOLE continuous run.
    The fix resets the latch on that same instance the moment "guard" comes
    back, before wait_for_board_gone runs.

    This test never touches real image recognition - it fakes _round()
    directly to return "guard" then "stop", and fakes wait_for_board /
    wait_for_board_gone to return exactly what their `should_continue`
    argument evaluates to, mirroring the real functions' own short-circuit
    behaviour. Without the fix, should_continue() (the `alive` closure)
    reads the still-latched flag as False right after round 1's "guard",
    wait_for_board_gone returns False, and round 2 never happens.
    這個測試守住的問題：一次真實的 2026-08-17 遊玩乾淨解完三題後，第 4 輪
    誤讀了一個已經解完、過期的棋盤當成新題目——填答中途的保護正確地拒絕了
    它（InputDriver._check_abort 的「guard rejected the next action ->
    aborting plan」），但連續模式接著卻悄悄停了下來，而不是繼續下一題——
    剛好停在使用者正要打開下一題的那一刻，浪費的是使用者發現、重新按下
    開始的那段時間。

    根本原因：守衛中止會鎖住 driver 的 stop_requested 旗標
    （_check_abort 裡「鎖定，不會被重啟」那句註解），確保拒絕之後不會再
    滑進一個動作。_round() 回傳 "guard" 之後立刻呼叫的
    wait_for_board_gone()，用的是「同一個」driver 實例——下一輪真正全新
    的實例要到下一次迴圈開頭才會建立——讀的正是那個已經鎖住的旗標當作
    should_continue，所以會立刻回傳（0 次輪詢），讓迴圈的
    `if not wait_for_board_gone(...): break` 把整個連續流程結束掉。
    修正在 "guard" 一回來、wait_for_board_gone 執行之前，就在同一個實例上
    重設這個鎖定。

    這個測試完全不碰真正的影像辨識——直接假造 _round() 依序回傳 "guard"
    再 "stop"，並假造 wait_for_board / wait_for_board_gone，讓它們回傳的
    值就是自己 `should_continue`參數算出來的結果，模擬真正函式自己的
    短路行為。沒有這個修正的話，should_continue()（也就是 `alive`
    closure）在第 1 輪的 "guard" 之後會讀到還鎖著的旗標、算出 False，
    wait_for_board_gone 回傳 False，第 2 輪永遠不會發生。
    """
    import subprocess

    code = (
        "import sys, tempfile\n"
        "from pathlib import Path as _Path\n"
        "sys.path.insert(0, r'" + str(Path(__file__).resolve().parents[1]) + "')\n"
        "import tkinter as tk\n"
        "try:\n"
        "    root = tk.Tk()\n"
        "except Exception as exc:\n"
        "    print('SKIPPED_NO_DISPLAY: ' + repr(exc))\n"
        "    sys.exit(0)\n"
        "from linkedin_games_solver.ui import settings as settings_store\n"
        "settings_store.SETTINGS_PATH = _Path(tempfile.mkdtemp()) / 'settings.json'\n"
        "from linkedin_games_solver.core import action_log\n"
        "action_log.LOG_DIR = _Path(tempfile.mkdtemp())\n"
        "import linkedin_games_solver.ui.app as app_module\n"
        "from linkedin_games_solver.automation import InputDriver\n"
        "app = app_module.SolverApp(root)\n"
        "app._ui = lambda func, *a: func(*a)\n"
        "app._ui_wait = lambda func, timeout=1.0: func()\n"
        ""
        "app.driver = InputDriver(dry_run=False)\n"
        "app.driver.reset()\n"
        ""
        "calls = {'round': 0}\n"
        "gone_calls = []\n"
        "def fake_wait_for_board(capture_fn, should_continue=None):\n"
        "    return object()  # any non-None 'shot' is enough for the loop\n"
        "def fake_wait_for_board_gone(capture_fn, should_continue=None):\n"
        "    result = should_continue()\n"
        "    gone_calls.append(result)\n"
        "    return result\n"
        "def fake_round(shot, puzzle_key, fill_answers, capture_fn, wait_time=None):\n"
        "    calls['round'] += 1\n"
        "    if calls['round'] == 1:\n"
        "        # Reproduce exactly what a real guard rejection leaves\n"
        "        # behind on the driver - see InputDriver._check_abort.\n"
        "        app.driver.stopped_by_guard = True\n"
        "        app.driver._stop_requested = True\n"
        "        return 'guard', 'stopped by guard'\n"
        "    return 'stop', 'ended for the test'\n"
        "app_module.wait_for_board = fake_wait_for_board\n"
        "app_module.wait_for_board_gone = fake_wait_for_board_gone\n"
        "app._round = fake_round\n"
        ""
        "app._worker(None, 'auto', True, capture_fn=lambda: object(), driver_kwargs=dict(dry_run=False))\n"
        ""
        "assert calls['round'] == 2, (\n"
        "    'continuous mode stopped after the guard abort instead of moving on / '\n"
        "    '連續模式在守衛中止之後就停了，沒有繼續下一輪: %r' % calls)\n"
        "print('ROUND_2_REACHED_OK')\n"
        "assert gone_calls == [True], (\n"
        "    'wait_for_board_gone saw a still-latched stop flag right after '\n"
        "    'the guard abort / wait_for_board_gone 在守衛中止之後看到的還是'\n"
        "    '鎖住的停止旗標: %r' % gone_calls)\n"
        "print('LATCH_RESET_OK')\n"
        ""
        "root.destroy()\n"
        "print('OK')\n"
    )
    result = subprocess.run([sys.executable, "-c", code], capture_output=True,
                            text=True, encoding="utf-8", errors="replace")
    out = result.stdout or ""
    assert "OK" in out, \
        "a guard abort still kills continuous mode / 守衛中止還是會讓連續模式停下來:\n" + \
        (result.stderr or "")[-1500:]
    if "SKIPPED_NO_DISPLAY" in out:
        print("  guard abort does not kill continuous mode OK (skipped - no display)")
    else:
        assert all(marker in out for marker in (
            "ROUND_2_REACHED_OK", "LATCH_RESET_OK",
        )), out
        print("  guard abort does not kill continuous mode OK")


def test_solve_failed_frame_is_saved_for_diagnosis():
    """
    Bug this guards: a 2026-08-10 Patches failure ("28 label(s) unreadable ...
    tiling is ambiguous", every crop/scale in the ladder) could not be
    root-caused afterwards because nothing kept the actual bytes the
    recogniser saw - a hand screenshot taken around the same time solved
    cleanly, proving it was not the same capture. This proves the fix: a
    solve that exhausts every retry must save the LAST attempted capture
    (the exact image `result` came from, not a fresh grab) to captures_dir()
    and log where it went, mirroring the existing guard boardwatch_stop save.
    這個測試守住的問題：2026-08-10 有一次 Patches 失敗（「28 個標籤讀不出來
    …切法不唯一」，階梯裡每個裁切／縮放都試過）事後完全查不出根因，因為
    沒有任何東西留住辨識器當時實際看到的位元組——差不多同時間手動截的圖
    卻能乾淨解出來，證明根本不是同一張擷取畫面。這個測試驗證修正：重試
    全部用盡後的失敗，必須把「最後一次嘗試」用的擷取畫面（也就是產生
    `result` 的那張圖，不是重新擷取的新畫面）存進 captures_dir()，並在
    記錄裡寫出存去哪裡，做法比照既有的守衛 boardwatch_stop 存檔。
    """
    import subprocess

    code = (
        "import sys, tempfile\n"
        "from pathlib import Path as _Path\n"
        "sys.path.insert(0, r'" + str(Path(__file__).resolve().parents[1]) + "')\n"
        "import tkinter as tk\n"
        "try:\n"
        "    root = tk.Tk()\n"
        "except Exception as exc:\n"
        "    print('SKIPPED_NO_DISPLAY: ' + repr(exc))\n"
        "    sys.exit(0)\n"
        "from linkedin_games_solver.ui import settings as settings_store\n"
        "settings_store.SETTINGS_PATH = _Path(tempfile.mkdtemp()) / 'settings.json'\n"
        "captures_root = _Path(tempfile.mkdtemp())\n"
        "settings_store.captures_dir = lambda: captures_root\n"
        "from linkedin_games_solver.core import action_log\n"
        "action_log.LOG_DIR = _Path(tempfile.mkdtemp())\n"
        "import linkedin_games_solver.ui.app as app_module\n"
        "from linkedin_games_solver.automation import InputDriver, from_file_image\n"
        "from linkedin_games_solver.core import read_image\n"
        "from linkedin_games_solver.i18n import translator\n"
        "app = app_module.SolverApp(root)\n"
        "app._ui = lambda func, *a: func(*a)\n"
        "app._ui_wait = lambda func, timeout=1.0: func()\n"
        ""
        "board = read_image(r'" + str(FIXTURES / 'live_queens_3.png') + "')\n"
        "def grab():\n"
        "    return from_file_image(board)\n"
        "app.driver = InputDriver(dry_run=True)\n"
        "app.driver.reset()\n"
        "app.hide_var.set(True)\n"
        "app.settings['fullscreen'] = False\n"
        "root.geometry('400x470+100+100')\n"
        "root.update_idletasks()\n"
        ""
        "# Same guaranteed-failure technique as the repeated-failure alert test:\n"
        "# forcing a real Queens fixture through Tango's solver fails cleanly on\n"
        "# structural guards (test_recognition.py's 'wrong type does not fake\n"
        "# success'), never on a threshold call, so this cannot flake.\n"
        "app._worker(None, 'tango', True, capture_fn=grab, driver_kwargs=dict(dry_run=True))\n"
        ""
        "saved = list(captures_root.glob('solve_failed_*.png'))\n"
        "assert len(saved) == 1, 'expected exactly one saved failure frame / 應該存下剛好一張失敗畫面: %r' % saved\n"
        "print('FRAME_SAVED_OK')\n"
        "log = app.log_text.get('1.0', 'end')\n"
        "assert translator('log_solve_failed_frame_saved') in log, log\n"
        "print('LOG_MESSAGE_OK')\n"
        ""
        "root.destroy()\n"
        "print('OK')\n"
    )
    result = subprocess.run([sys.executable, "-c", code], capture_output=True,
                            text=True, encoding="utf-8", errors="replace")
    out = result.stdout or ""
    assert "OK" in out, \
        "solve-failed diagnostic save is broken / 求解失敗診斷存檔有問題:\n" + \
        (result.stderr or "")[-1500:]
    if "SKIPPED_NO_DISPLAY" in out:
        print("  solve failed frame is saved for diagnosis OK (skipped - no display)")
    else:
        assert all(marker in out for marker in ("FRAME_SAVED_OK", "LOG_MESSAGE_OK")), out
        print("  solve failed frame is saved for diagnosis OK")


def test_harvest_calibration_candidates_only_saves_safe_ground_truth():
    """
    Guards _harvest_calibration_candidates' whole reason for existing: it
    must save a cell we filled ourselves that could not be read back
    confidently (got=None - genuine ground truth, since `want` is what OUR
    OWN solver chose and the driver clicked/typed), and must refuse the
    three unsafe cases - a CONFIDENTLY wrong reading (ground truth is
    suspect - could be a real misread or a dropped click), a changed board,
    and any puzzle other than Sudoku (the only one verify() reads back cell
    by cell).
    守住 _harvest_calibration_candidates 存在的全部理由：它必須存下一個
    我們自己填的、讀不回來的格子（got=None——真值可信，因為 `want` 是
    「我們自己的」求解器選中、driver 親自點擊/打字打上去的），並且必須
    拒絕三種不安全的情況——讀對了但錯的數字（真值本身可疑，可能真的
    誤讀、也可能是點擊沒生效）、盤面已改變、以及數獨以外的任何題目
    （verify() 只有數獨會逐格讀回）。
    """
    import subprocess

    code = (
        "import sys, tempfile\n"
        "from pathlib import Path as _Path\n"
        "sys.path.insert(0, r'" + str(Path(__file__).resolve().parents[1]) + "')\n"
        "import tkinter as tk\n"
        "try:\n"
        "    root = tk.Tk()\n"
        "except Exception as exc:\n"
        "    print('SKIPPED_NO_DISPLAY: ' + repr(exc))\n"
        "    sys.exit(0)\n"
        "from linkedin_games_solver.ui import settings as settings_store\n"
        "settings_store.SETTINGS_PATH = _Path(tempfile.mkdtemp()) / 'settings.json'\n"
        "captures_root = _Path(tempfile.mkdtemp())\n"
        "settings_store.captures_dir = lambda: captures_root\n"
        "from linkedin_games_solver.core import action_log\n"
        "action_log.LOG_DIR = _Path(tempfile.mkdtemp())\n"
        "import linkedin_games_solver.ui.app as app_module\n"
        "from linkedin_games_solver.automation import VerifyReport\n"
        "from linkedin_games_solver.puzzles import sudoku, queens\n"
        "from linkedin_games_solver.i18n import translator\n"
        "import numpy as np, types\n"
        "app = app_module.SolverApp(root)\n"
        "app._ui = lambda func, *a: func(*a)\n"
        "image = np.zeros((10, 10, 3), dtype='uint8')\n"
        "candidates_dir = captures_root / 'calibration_candidates'\n"
        ""
        "# Case 1: got=None - we filled it, OCR could not confirm -> harvested.\n"
        "app.result = types.SimpleNamespace(puzzle_key=sudoku.KEY)\n"
        "report = VerifyReport(supported=True, ok=False, mismatches=[(0, 0, None, 5)])\n"
        "app._clear_log()\n"
        "app._harvest_calibration_candidates(image, report)\n"
        "saved = list(candidates_dir.glob('*.png'))\n"
        "assert len(saved) == 1, 'expected exactly one saved candidate / 應該存下剛好一個候選: %r' % saved\n"
        "log = app.log_text.get('1.0', 'end')\n"
        "assert translator('log_calibration_candidate_saved', n=1) in log, log\n"
        "print('UNREAD_CELL_HARVESTED_OK')\n"
        ""
        "# Case 2: got is a WRONG digit (read confidently, just not what we\n"
        "# filled) -> must NOT be harvested, the ground truth itself is suspect.\n"
        "report2 = VerifyReport(supported=True, ok=False, mismatches=[(1, 1, 3, 5)])\n"
        "app._harvest_calibration_candidates(image, report2)\n"
        "saved2 = list(candidates_dir.glob('*.png'))\n"
        "assert len(saved2) == 1, 'a confidently-wrong digit was harvested / 讀對但錯的數字被收集了: %r' % saved2\n"
        "print('WRONG_DIGIT_NOT_HARVESTED_OK')\n"
        ""
        "# Case 3: board_changed -> must NOT be harvested.\n"
        "report3 = VerifyReport(supported=True, ok=False, board_changed=True, mismatches=[(2, 2, None, 5)])\n"
        "app._harvest_calibration_candidates(image, report3)\n"
        "saved3 = list(candidates_dir.glob('*.png'))\n"
        "assert len(saved3) == 1, 'harvested from a changed board / 從已改變的盤面收集了: %r' % saved3\n"
        "print('BOARD_CHANGED_NOT_HARVESTED_OK')\n"
        ""
        "# Case 4: not Sudoku -> must NOT be harvested (verify() only reads\n"
        "# individual cells back for Sudoku).\n"
        "app.result = types.SimpleNamespace(puzzle_key=queens.KEY)\n"
        "report4 = VerifyReport(supported=True, ok=False, mismatches=[(3, 3, None, 5)])\n"
        "app._harvest_calibration_candidates(image, report4)\n"
        "saved4 = list(candidates_dir.glob('*.png'))\n"
        "assert len(saved4) == 1, 'harvested from a non-Sudoku puzzle / 從非數獨題目收集了: %r' % saved4\n"
        "print('NON_SUDOKU_NOT_HARVESTED_OK')\n"
        ""
        "root.destroy()\n"
        "print('OK')\n"
    )
    result = subprocess.run([sys.executable, "-c", code], capture_output=True,
                            text=True, encoding="utf-8", errors="replace")
    out = result.stdout or ""
    assert "OK" in out, \
        "calibration-candidate harvesting is broken / 校準候選資料收集有問題:\n" + \
        (result.stderr or "")[-1500:]
    if "SKIPPED_NO_DISPLAY" in out:
        print("  harvest calibration candidates only saves safe ground truth OK (skipped - no display)")
    else:
        assert all(marker in out for marker in (
            "UNREAD_CELL_HARVESTED_OK", "WRONG_DIGIT_NOT_HARVESTED_OK",
            "BOARD_CHANGED_NOT_HARVESTED_OK", "NON_SUDOKU_NOT_HARVESTED_OK",
        )), out
        print("  harvest calibration candidates only saves safe ground truth OK")


def test_harvest_raw_board_capture_only_for_digit_puzzles():
    """
    Guards _harvest_raw_board_capture: it must save the pristine pre-fill
    board for Sudoku, Zip and Patches (the only puzzles that read digits -
    see core/digits.py), and must NOT save for Queens or Tango, which never
    call into digit recognition at all.
    守住 _harvest_raw_board_capture：必須為 Sudoku、Zip、Patches（唯三會讀
    數字的題目——見 core/digits.py）存下填答前的乾淨畫面，且絕不能為皇后
    或雙子星存——它們從來不會呼叫數字辨識。
    """
    import subprocess

    code = (
        "import sys, tempfile\n"
        "from pathlib import Path as _Path\n"
        "sys.path.insert(0, r'" + str(Path(__file__).resolve().parents[1]) + "')\n"
        "import tkinter as tk\n"
        "try:\n"
        "    root = tk.Tk()\n"
        "except Exception as exc:\n"
        "    print('SKIPPED_NO_DISPLAY: ' + repr(exc))\n"
        "    sys.exit(0)\n"
        "from linkedin_games_solver.ui import settings as settings_store\n"
        "settings_store.SETTINGS_PATH = _Path(tempfile.mkdtemp()) / 'settings.json'\n"
        "captures_root = _Path(tempfile.mkdtemp())\n"
        "settings_store.captures_dir = lambda: captures_root\n"
        "from linkedin_games_solver.core import action_log\n"
        "action_log.LOG_DIR = _Path(tempfile.mkdtemp())\n"
        "import linkedin_games_solver.ui.app as app_module\n"
        "from linkedin_games_solver.puzzles import sudoku, zip_path, patches, queens, tango\n"
        "from linkedin_games_solver.i18n import translator\n"
        "import numpy as np\n"
        "app = app_module.SolverApp(root)\n"
        "app._ui = lambda func, *a: func(*a)\n"
        "image = np.zeros((10, 10, 3), dtype='uint8')\n"
        "candidates_dir = captures_root / 'calibration_candidates'\n"
        ""
        "# The three digit puzzles -> each saves exactly one raw capture.\n"
        "for key in (sudoku.KEY, zip_path.KEY, patches.KEY):\n"
        "    app._clear_log()\n"
        "    app._harvest_raw_board_capture(image, key)\n"
        "    matches = list(candidates_dir.glob(key + '_raw_*.png'))\n"
        "    assert len(matches) == 1, 'expected one raw capture for %r / 應該存下一張原始畫面: %r' % (key, matches)\n"
        "    log = app.log_text.get('1.0', 'end')\n"
        "    assert translator('log_raw_board_saved') in log, log\n"
        "print('DIGIT_PUZZLES_HARVESTED_OK')\n"
        ""
        "# Queens and Tango never read digits -> must NOT be saved.\n"
        "before = len(list(candidates_dir.glob('*.png')))\n"
        "app._harvest_raw_board_capture(image, queens.KEY)\n"
        "app._harvest_raw_board_capture(image, tango.KEY)\n"
        "after = len(list(candidates_dir.glob('*.png')))\n"
        "assert after == before, 'a non-digit puzzle was harvested / 非數字題目也被存了: before=%r after=%r' % (before, after)\n"
        "print('NON_DIGIT_PUZZLES_NOT_HARVESTED_OK')\n"
        ""
        "root.destroy()\n"
        "print('OK')\n"
    )
    result = subprocess.run([sys.executable, "-c", code], capture_output=True,
                            text=True, encoding="utf-8", errors="replace")
    out = result.stdout or ""
    assert "OK" in out, \
        "raw board capture harvesting is broken / 原始棋盤畫面收集有問題:\n" + \
        (result.stderr or "")[-1500:]
    if "SKIPPED_NO_DISPLAY" in out:
        print("  harvest raw board capture only for digit puzzles OK (skipped - no display)")
    else:
        assert all(marker in out for marker in (
            "DIGIT_PUZZLES_HARVESTED_OK", "NON_DIGIT_PUZZLES_NOT_HARVESTED_OK",
        )), out
        print("  harvest raw board capture only for digit puzzles OK")


def test_harvest_overlay_capture_only_for_digit_puzzles():
    """
    Guards _harvest_overlay_capture: it must save the already-computed
    answer overlay for Sudoku, Zip and Patches, must NOT save for Queens or
    Tango, and must NOT save when there is no overlay to save (None - the
    same thing render_overlay itself returns on failure).
    守住 _harvest_overlay_capture：必須為 Sudoku、Zip、Patches 存下已經算好
    的答案疊圖，絕不能為皇后或雙子星存，也絕不能在沒有疊圖可存時存
    （None——跟 render_overlay 失敗時自己回傳的東西一樣）。
    """
    import subprocess

    code = (
        "import sys, tempfile\n"
        "from pathlib import Path as _Path\n"
        "sys.path.insert(0, r'" + str(Path(__file__).resolve().parents[1]) + "')\n"
        "import tkinter as tk\n"
        "try:\n"
        "    root = tk.Tk()\n"
        "except Exception as exc:\n"
        "    print('SKIPPED_NO_DISPLAY: ' + repr(exc))\n"
        "    sys.exit(0)\n"
        "from linkedin_games_solver.ui import settings as settings_store\n"
        "settings_store.SETTINGS_PATH = _Path(tempfile.mkdtemp()) / 'settings.json'\n"
        "captures_root = _Path(tempfile.mkdtemp())\n"
        "settings_store.captures_dir = lambda: captures_root\n"
        "from linkedin_games_solver.core import action_log\n"
        "action_log.LOG_DIR = _Path(tempfile.mkdtemp())\n"
        "import linkedin_games_solver.ui.app as app_module\n"
        "from linkedin_games_solver.puzzles import sudoku, zip_path, patches, queens, tango\n"
        "from linkedin_games_solver.i18n import translator\n"
        "import numpy as np\n"
        "app = app_module.SolverApp(root)\n"
        "app._ui = lambda func, *a: func(*a)\n"
        "overlay = np.zeros((10, 10, 3), dtype='uint8')\n"
        "candidates_dir = captures_root / 'calibration_candidates'\n"
        ""
        "# The three digit puzzles -> each saves exactly one overlay.\n"
        "for key in (sudoku.KEY, zip_path.KEY, patches.KEY):\n"
        "    app._clear_log()\n"
        "    app._harvest_overlay_capture(overlay, key)\n"
        "    matches = list(candidates_dir.glob(key + '_answer_*.png'))\n"
        "    assert len(matches) == 1, 'expected one overlay for %r / 應該存下一張疊圖: %r' % (key, matches)\n"
        "    log = app.log_text.get('1.0', 'end')\n"
        "    assert translator('log_answer_overlay_saved') in log, log\n"
        "print('DIGIT_PUZZLES_HARVESTED_OK')\n"
        ""
        "# Queens and Tango never read digits -> must NOT be saved.\n"
        "before = len(list(candidates_dir.glob('*.png')))\n"
        "app._harvest_overlay_capture(overlay, queens.KEY)\n"
        "app._harvest_overlay_capture(overlay, tango.KEY)\n"
        "after = len(list(candidates_dir.glob('*.png')))\n"
        "assert after == before, 'a non-digit puzzle was harvested / 非數字題目也被存了: before=%r after=%r' % (before, after)\n"
        "print('NON_DIGIT_PUZZLES_NOT_HARVESTED_OK')\n"
        ""
        "# No overlay (render_overlay failed) -> must NOT be saved.\n"
        "before2 = len(list(candidates_dir.glob('*.png')))\n"
        "app._harvest_overlay_capture(None, sudoku.KEY)\n"
        "after2 = len(list(candidates_dir.glob('*.png')))\n"
        "assert after2 == before2, 'a None overlay was harvested / None 疊圖也被存了: before=%r after=%r' % (before2, after2)\n"
        "print('NO_OVERLAY_NOT_HARVESTED_OK')\n"
        ""
        "root.destroy()\n"
        "print('OK')\n"
    )
    result = subprocess.run([sys.executable, "-c", code], capture_output=True,
                            text=True, encoding="utf-8", errors="replace")
    out = result.stdout or ""
    assert "OK" in out, \
        "answer overlay harvesting is broken / 答案疊圖收集有問題:\n" + \
        (result.stderr or "")[-1500:]
    if "SKIPPED_NO_DISPLAY" in out:
        print("  harvest overlay capture only for digit puzzles OK (skipped - no display)")
    else:
        assert all(marker in out for marker in (
            "DIGIT_PUZZLES_HARVESTED_OK", "NON_DIGIT_PUZZLES_NOT_HARVESTED_OK",
            "NO_OVERLAY_NOT_HARVESTED_OK",
        )), out
        print("  harvest overlay capture only for digit puzzles OK")


if __name__ == "__main__":
    print("Automation tests / 自動化測試")
    test_queens_resumes_half_done_board()
    test_queens_complete_board_does_nothing()
    test_queens_clears_misplaced_crowns()
    test_tango_click_counts_follow_current_state()
    test_patches_asks_the_guard_for_every_rect()
    test_drag_is_interpolated()
    test_dry_run_does_not_act()
    test_stop_aborts()
    test_stop_mid_drag_from_another_thread_still_releases_the_mouse()
    test_dry_run_checks_abort_as_often_as_a_live_run()
    test_dry_run_touches_no_mouse_module()
    test_image_mode_needs_no_screen_packages()
    test_stop_interrupts_an_in_progress_solve()
    test_the_window_cannot_sit_inside_the_capture_region()
    test_park_mouse_clear_of_capture_avoids_the_region_and_the_failsafe_corner()
    test_round_parks_the_mouse_and_recaptures_before_solving()
    test_region_monitor_size_only_restamps_when_the_region_actually_changes()
    test_resolution_change_warning_fires_only_when_sizes_differ()
    test_continuous_mode_alerts_and_stops_after_a_failed_round()
    test_guard_abort_does_not_kill_continuous_mode()
    test_solve_failed_frame_is_saved_for_diagnosis()
    test_harvest_calibration_candidates_only_saves_safe_ground_truth()
    test_harvest_raw_board_capture_only_for_digit_puzzles()
    test_harvest_overlay_capture_only_for_digit_puzzles()
    print("\nAll passed / 全部通過")
