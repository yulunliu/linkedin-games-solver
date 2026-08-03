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
        "print('OK')\n"
    )
    result = subprocess.run([sys.executable, "-c", code], capture_output=True,
                            text=True, encoding="utf-8", errors="replace")
    assert "OK" in (result.stdout or ""), \
        "image mode requires screen packages / 圖片模式需要螢幕相關套件:\n" + \
        (result.stderr or "")[-600:]
    print("  image mode works without pyautogui/mss OK")


if __name__ == "__main__":
    print("Automation tests / 自動化測試")
    test_queens_resumes_half_done_board()
    test_queens_complete_board_does_nothing()
    test_queens_clears_misplaced_crowns()
    test_tango_click_counts_follow_current_state()
    test_drag_is_interpolated()
    test_dry_run_does_not_act()
    test_stop_aborts()
    test_dry_run_checks_abort_as_often_as_a_live_run()
    test_dry_run_touches_no_mouse_module()
    test_image_mode_needs_no_screen_packages()
    print("\nAll passed / 全部通過")
