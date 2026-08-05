"""
Wait-for-board tests: the watch-then-fire flow added on the speed branch.
等待棋盤測試：速度分支新增的「先監看、出現就動作」流程。

No screen and no mouse - capture_fn is a scripted sequence of frames, the
same injection pattern test_board_guard.py uses for BoardWatch.
不碰螢幕也不碰滑鼠——capture_fn 是腳本化的影格序列，跟 test_board_guard.py
測 BoardWatch 用的注入方式相同。
"""

import sys
import tempfile
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# wait_for_board logs every wait through core/action_log; without this, each
# STANDALONE run of this file (run_all.py isolates only full-batch runs)
# drops a real log file into the project's own logs/ folder.
# wait_for_board 每次等待都會透過 core/action_log 記錄；少了這行，每次
# 「單獨」跑這個檔案（run_all.py 只隔離整批執行）都會在專案自己的 logs/
# 資料夾留下一個真的記錄檔。
from linkedin_games_solver.core import action_log  # noqa: E402
action_log.LOG_DIR = Path(tempfile.mkdtemp(prefix="lgs_board_wait_test_"))

from linkedin_games_solver.automation import from_file_image, wait_for_board  # noqa: E402
from linkedin_games_solver.automation.board_wait import _board_present  # noqa: E402
from linkedin_games_solver.core import read_image  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures"

#: A frame with no board on it. Flat mid-grey: no contour for find_board_bbox,
#: no evenly spaced lines for find_board_by_grid_lines. Asserted below rather
#: than assumed, so a locator change cannot silently invalidate every test here.
#: 一張沒有棋盤的影格。整片中灰：find_board_bbox 找不到輪廓，
#: find_board_by_grid_lines 找不到等距的線。下面會用斷言驗證而不是假設，
#: 這樣定位器改動時不會讓這裡每個測試悄悄失效。
_BLANK = np.full((700, 640, 3), 230, dtype=np.uint8)


def _board_frame():
    return read_image(str(FIXTURES / "live_queens_3.png"))


def _scripted_capture(frames):
    """capture_fn returning each frame in turn; repeats the last one forever.
    依序回傳每一張影格的 capture_fn；最後一張會一直重複。"""
    state = {"i": 0}

    def grab():
        frame = frames[min(state["i"], len(frames) - 1)]
        state["i"] += 1
        return from_file_image(frame)

    return grab, state


def test_the_blank_frame_really_has_no_board():
    """Guards the premise every other test here rests on.
    守住這個檔案裡其他每個測試依賴的前提。"""
    assert _board_present(_BLANK) is False, \
        "blank frame reads as a board - every other test here is meaningless / 空白影格被讀成棋盤，其他測試全部失去意義"
    assert _board_present(_board_frame()) is True, \
        "the fixture board is not detected - the cheap check is broken / 測試圖的棋盤沒被偵測到，便宜檢查壞了"
    print("  the blank frame really has no board OK")


def test_returns_the_capture_once_the_board_appears():
    """The core promise: blank screen, blank screen, ... board -> that capture
    comes back, and it is the BOARD frame, not one of the blanks.
    核心承諾：空畫面、空畫面、……棋盤 -> 回傳那次擷取，而且是「棋盤」那一幀，
    不是空白的那幾幀。"""
    board = _board_frame()
    grab, state = _scripted_capture([_BLANK, _BLANK, _BLANK, board])
    shot = wait_for_board(grab, poll_interval=0.001)
    assert shot is not None
    assert _board_present(shot.image), "returned a frame with no board on it / 回傳了一張沒有棋盤的影格"
    # 3 blanks + STABLE_POLLS(2) board sightings = 5 grabs.
    # 3 張空白 + 連續 2 次看到棋盤 = 5 次擷取。
    assert state["i"] == 5, f"expected 5 grabs, got {state['i']} / 預期擷取 5 次"
    print("  returns the capture once the board appears OK")


def test_a_single_transient_board_frame_does_not_trigger():
    """WHY STABLE_POLLS exists: one poll can catch a half-rendered transition
    frame that happens to look board-shaped. A single sighting followed by a
    miss must reset the count and keep waiting for a STABLE pair.
    STABLE_POLLS 存在的理由：某次輪詢可能剛好拍到畫面切換中、看起來像棋盤
    形狀的半成品影格。看到一次之後又斷掉，必須把計數歸零、繼續等到
    「連續」兩次才算數。"""
    board = _board_frame()
    grab, state = _scripted_capture([_BLANK, board, _BLANK, _BLANK, board, board])
    shot = wait_for_board(grab, poll_interval=0.001)
    assert shot is not None
    # The transient sighting at frame 2 must NOT have been enough - detection
    # commits only at frame 6, the second of the stable pair.
    # 第 2 幀那次曇花一現不能算數——要到第 6 幀、穩定連續的第二次才拍板。
    assert state["i"] == 6, f"expected 6 grabs, got {state['i']} / 預期擷取 6 次"
    print("  a single transient board frame does not trigger OK")


def test_board_already_on_screen_fires_after_the_stability_window():
    """Pressing the button with the puzzle ALREADY open must still work - the
    old workflow is a special case of the new one, costing only the stability
    window (2 polls), never a timeout or a hang.
    題目「已經開著」才按按鈕也必須能動——舊的操作流程是新流程的特例，
    代價只有穩定窗（2 次輪詢），絕不是逾時或卡住。"""
    board = _board_frame()
    grab, state = _scripted_capture([board])
    shot = wait_for_board(grab, poll_interval=0.001)
    assert shot is not None
    assert state["i"] == 2, f"expected exactly the stability window (2 grabs), got {state['i']}"
    print("  board already on screen fires after the stability window OK")


def test_stop_while_waiting_returns_none():
    """The waiting phase can be the LONGEST phase (the user may wander off) and
    Stop is its only exit - see the iconify comment in ui/app.py for why the
    fail-safe cannot cover this phase. Cancelling must return None promptly,
    never a stale capture.
    等待階段可能是最長的階段（使用者可能走開了），而「停止」是它唯一的出口——
    為什麼滑鼠甩角落的緊急煞車照顧不到這一段，見 ui/app.py 裡 iconify 的註解。
    取消時必須立刻回傳 None，絕不能回傳一張過期的擷取。"""
    grab, state = _scripted_capture([_BLANK])
    calls = {"n": 0}

    def stop_after_three():
        calls["n"] += 1
        return calls["n"] <= 3

    shot = wait_for_board(grab, should_continue=stop_after_three, poll_interval=0.001)
    assert shot is None, "cancelled wait still returned a capture / 已取消的等待仍回傳了擷取"
    assert state["i"] == 3, f"kept polling after the stop / 停止之後還在輪詢: {state['i']}"
    print("  stop while waiting returns None OK")


if __name__ == "__main__":
    print("Board wait tests / 等待棋盤測試")
    test_the_blank_frame_really_has_no_board()
    test_returns_the_capture_once_the_board_appears()
    test_a_single_transient_board_frame_does_not_trigger()
    test_board_already_on_screen_fires_after_the_stability_window()
    test_stop_while_waiting_returns_none()
    print("\nAll passed / 全部通過")
