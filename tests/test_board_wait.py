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

from linkedin_games_solver.automation import (  # noqa: E402
    from_file_image,
    wait_for_board,
    wait_for_board_gone,
)
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
    comes back, and it is the BOARD frame, not one of the blanks. Detection
    commits on the FIRST full-grid sighting (STABLE_POLLS=1) - see the
    constant's HISTORY note for why one sighting is enough now.
    核心承諾：空畫面、空畫面、……棋盤 -> 回傳那次擷取，而且是「棋盤」那一幀，
    不是空白的那幾幀。偵測在「第一次」看到完整棋盤時就拍板
    （STABLE_POLLS=1）——為什麼一次就夠，見常數的沿革註解。"""
    board = _board_frame()
    grab, state = _scripted_capture([_BLANK, _BLANK, _BLANK, board])
    shot = wait_for_board(grab, poll_interval=0.001)
    assert shot is not None
    assert _board_present(shot.image), "returned a frame with no board on it / 回傳了一張沒有棋盤的影格"
    # 3 blanks + 1 full-grid sighting = 4 grabs.
    # 3 張空白 + 1 次完整棋盤 = 4 次擷取。
    assert state["i"] == 4, f"expected 4 grabs, got {state['i']} / 預期擷取 4 次"
    print("  returns the capture once the board appears OK")


def test_the_stability_window_mechanism_still_works_when_asked_for():
    """The consecutive-count machinery must remain correct for any caller
    that configures stable_polls > 1: a single sighting followed by a miss
    resets the count.
    連續計數的機制對任何設定 stable_polls > 1 的呼叫端仍然要正確：
    看到一次之後斷掉，計數必須歸零。"""
    board = _board_frame()
    grab, state = _scripted_capture([_BLANK, board, _BLANK, _BLANK, board, board])
    shot = wait_for_board(grab, poll_interval=0.001, stable_polls=2)
    assert shot is not None
    assert state["i"] == 6, f"expected 6 grabs, got {state['i']} / 預期擷取 6 次"
    print("  the stability-window mechanism still works when asked for OK")


def test_board_already_on_screen_fires_on_the_first_poll():
    """Pressing the button with the puzzle ALREADY open must still work - the
    old workflow is a special case of the new one, committing on the very
    first poll.
    題目「已經開著」才按按鈕也必須能動——舊的操作流程是新流程的特例，
    第一次輪詢就拍板。"""
    board = _board_frame()
    grab, state = _scripted_capture([board])
    shot = wait_for_board(grab, poll_interval=0.001)
    assert shot is not None
    assert state["i"] == 1, f"expected 1 grab, got {state['i']}"
    print("  board already on screen fires on the first poll OK")


def test_a_border_without_grid_lines_is_not_a_board():
    """
    The exact frame that broke a real Patches run (session log 2026-08-06
    19:47): the entrance animation had drawn the OUTER border but not the
    interior grid lines. The old bbox-only check fired on it, and
    solve_image() burned ~9s failing every attempt with "grid size not
    detected". A border with no interior must NOT count as present.
    真實 Patches 執行失敗的那一幀（執行記錄 2026-08-06 19:47）：進場動畫
    畫出了「外框」、內部格線還沒畫完。舊的只看外框檢查在那一幀就觸發，
    solve_image() 白跑了約 9 秒、每次都失敗在「無法偵測棋盤格數」。
    只有外框、沒有內部的畫面「不能」算棋盤存在。
    """
    import cv2
    border_only = np.full((700, 640, 3), 250, dtype=np.uint8)
    cv2.rectangle(border_only, (100, 100), (540, 540), (60, 60, 60), 3)
    assert _board_present(border_only) is False, \
        "a bare border counts as a board - the mid-animation bug is back / 光一個外框就被算成棋盤，動畫中誤觸發的問題回來了"
    print("  a border without grid lines is not a board OK")


def test_wait_for_gone_returns_once_the_board_leaves():
    """Continuous mode's between-rounds step: the finished board must leave
    the screen before the next detection arms, or the round that just ended
    would re-trigger on its own board.
    連續模式兩輪之間的步驟：剛結束的棋盤要先離開畫面，下一輪偵測才能
    重新武裝，否則會對著自己剛處理完的棋盤重新觸發。"""
    board = _board_frame()
    grab, state = _scripted_capture([board, board, _BLANK])
    assert wait_for_board_gone(grab, poll_interval=0.001) is True
    # 2 board frames + STABLE_POLLS(2) absences = 4 grabs.
    # 2 張棋盤 + 連續 2 次消失 = 4 次擷取。
    assert state["i"] == 4, f"expected 4 grabs, got {state['i']}"
    print("  wait-for-gone returns once the board leaves OK")


def test_a_single_flicker_does_not_end_the_gone_wait():
    """A completion animation can hide the board for one poll mid-transition;
    one absence followed by the board again must reset the count.
    完成動畫的過場可能讓棋盤只消失一次輪詢；消失一次之後又出現，
    必須把計數歸零。"""
    board = _board_frame()
    grab, state = _scripted_capture([board, _BLANK, board, _BLANK, _BLANK])
    assert wait_for_board_gone(grab, poll_interval=0.001) is True
    assert state["i"] == 5, f"expected 5 grabs, got {state['i']}"
    print("  a single flicker does not end the gone-wait OK")


def test_stop_while_waiting_for_gone_returns_false():
    """Stop pressed while waiting for the board to leave must exit promptly.
    在等棋盤離開時按下停止，必須立刻結束。"""
    board = _board_frame()
    grab, state = _scripted_capture([board])
    calls = {"n": 0}

    def stop_after_two():
        calls["n"] += 1
        return calls["n"] <= 2

    assert wait_for_board_gone(grab, should_continue=stop_after_two,
                               poll_interval=0.001) is False
    assert state["i"] == 2, f"kept polling after the stop: {state['i']}"
    print("  stop while waiting for gone returns False OK")


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
    test_the_stability_window_mechanism_still_works_when_asked_for()
    test_board_already_on_screen_fires_on_the_first_poll()
    test_a_border_without_grid_lines_is_not_a_board()
    test_wait_for_gone_returns_once_the_board_leaves()
    test_a_single_flicker_does_not_end_the_gone_wait()
    test_stop_while_waiting_for_gone_returns_false()
    test_stop_while_waiting_returns_none()
    print("\nAll passed / 全部通過")
