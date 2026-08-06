"""
Wait for a puzzle board to appear on screen, then hand back that capture.
等待棋盤出現在螢幕上，出現後把那次擷取交出去。

WHY THIS EXISTS 為什麼需要這個
------------------------------
Until now, pressing "Solve" captured the screen immediately - so the user had
to first switch to the puzzle page, wait for it to finish rendering, THEN
switch back and press the button, and every second of that reaction time was
lost. Measured: on a real 5-puzzle sitting, that hand-off is repeated five
times a day.
以前按下「開始」是立刻擷取螢幕——所以使用者得先切到謎題頁面、等它畫面
跑完，「再」切回來按按鈕，這段反應時間全部都是純損耗。實測：一次真實的
五題流程，這個交接動作一天要重複五次。

This flips the order: press the button FIRST, while still looking at
whatever page is on screen (the puzzle hub, a blank tab, anything), and the
program itself watches the screen and fires the moment a board shows up - no
reaction time spent switching back to press anything.
這裡把順序反過來：畫面還在別的頁面時就先按下按鈕，程式自己盯著螢幕，
棋盤一出現就立刻動作——不需要花時間切回來按任何東西。

WHY A CHEAP CHECK, NOT solve_image() 為什麼用便宜的檢查，不是 solve_image()
------------------------------------------------------------------------
solve_image()'s full crop x scale ladder is built to find the RIGHT answer,
not to answer "is anything board-shaped here yet" as fast as possible -
running it every poll would burn CPU waiting for a page that has not loaded
yet. Measured on a 640x700 region: the same locators solve_image() itself
uses to find a board at all (find_board_bbox, find_board_by_grid_lines), at
1x scale only, cost 1.4ms once a board is present and 18.7ms when nothing is
there yet (both locators get tried). That is cheap enough to poll often
without the cost showing up anywhere a user would notice.
solve_image() 完整的裁切 x 縮放階梯是設計來找出「正確答案」的，不是設計來
盡快回答「這裡現在有沒有棋盤形狀的東西」——每次輪詢都跑一次階梯，
只會在頁面根本還沒載入時空燒 CPU。實測 640x700 的擷取範圍：solve_image()
自己用來定位棋盤的同一組定位器（find_board_bbox、find_board_by_grid_lines），
只用 1 倍縮放，棋盤已經出現時要 1.4 毫秒，還沒出現時（兩種都要試）要
18.7 毫秒。夠便宜，可以常常輪詢也不會讓使用者感覺到成本。

A false positive here (some other rectangular UI element gets mistaken for a
board) is not dangerous - it just triggers one solve_image() attempt, which
carries its own uniqueness/sanity guards per puzzle module and fails cleanly
rather than inventing an answer, exactly like a failed manual attempt today.
這裡的誤判（把別的矩形 UI 元素誤認成棋盤）並不危險——只會觸發一次
solve_image() 嘗試，而它自己每個謎題模組都有唯一性/合理性守門，會乾淨地
失敗而不是編一個答案，跟今天手動觸發失敗時一樣。
"""

from __future__ import annotations

import time
from typing import Callable

from ..core import action_log, build_grid
from ..core.board import find_board_by_grid_lines
from .capture import ScreenShot

#: Seconds between polls while waiting.
#: 等待期間，每次輪詢之間的間隔（秒）。
#:
#: MEASURED 量測依據: one full poll - a real screen grab of the default
#: 640x700 region plus the cheap board check - measured end to end at
#: 33.4ms average over 30 polls on live screen content with no board
#: present (the worst case for the check, since both locators get tried).
#: At 0.15s that is a 22% duty cycle of ONE core, and only while actually
#: waiting - a stretch of a few seconds per puzzle. 0.3s (11%) was tried
#: first and rejected as leaving reaction time on the table; 0.15 is the
#: user's chosen balance between detection latency and idle CPU cost.
#: 實測依據：一次完整輪詢——真的對預設 640x700 範圍擷取一次螢幕、加上
#: 便宜的棋盤檢查——對著沒有棋盤的真實螢幕內容（檢查的最壞情況，兩種
#: 定位器都會試）連續量 30 次，平均 33.4 毫秒。0.15 秒間隔等於「一顆」
#: 核心 22% 的佔用率，而且只在真正等待的那幾秒鐘內。一開始用的是
#: 0.3 秒（11%），後來否決：沒有理由自己先把反應時間留在桌上；
#: 0.15 是使用者在「偵測延遲」與「等待期 CPU 成本」之間選定的平衡點。
POLL_INTERVAL = 0.15

#: Consecutive successful detections required before committing.
#: 連續幾次偵測成功才算數，才會真的採信。
#:
#: WHY THIS STAYS AT 2 為什麼維持 2 不拿掉:
#: a page transition can show a half-rendered frame for one poll that
#: happens to look board-shaped (a loading skeleton, the board drawn but
#: its icons/digits not yet) before the page settles. Requiring 2 in a
#: row - reset to 0 on any miss, the same consecutive-count shape as
#: BoardWatch.failure_tolerance - costs exactly one extra POLL_INTERVAL
#: (0.15s) once the real board appears. Removing it was considered and
#: rejected on measured numbers: a premature solve_image() on a
#: half-rendered frame does not just "fail fast" - every module's
#: uniqueness guard rejects the incomplete board, so the FULL crop x scale
#: ladder plus the fallback-type sweep runs to exhaustion, measured at up
#: to ~9.2s on content that never resolves. Risking ~9s to save 0.15s is
#: the wrong side of that trade a hundred times over.
#: 為什麼維持 2 不拿掉：頁面切換時，可能有一次輪詢剛好拍到畫到一半、
#: 看起來像棋盤形狀的影格（載入中的骨架畫面，或棋盤畫出來了但裡面的
#: 圖示/數字還沒畫）。要求連續 2 次——中間斷一次就歸零，跟
#: BoardWatch.failure_tolerance 同一種連續計數邏輯——在真正的棋盤出現後
#: 只多花「一個」POLL_INTERVAL（0.15 秒）。「拿掉它」評估過、用量測數字
#: 否決：對半成品影格提早跑一次 solve_image() 不是「很快失敗」而已——
#: 每個謎題模組的唯一性守門都會拒絕不完整的盤面，於是完整的裁切 x 縮放
#: 階梯加上備援類型全掃會跑到耗盡為止，對永遠解不出來的內容實測要花到
#: 約 9.2 秒。為了省 0.15 秒去賭 9 秒，這個交換怎麼算都是虧的。
STABLE_POLLS = 2


def _board_present(image) -> bool:
    """A board counts as present only when a FULL grid - border AND interior
    cell structure - can be located, at 1x only.
    只有在「完整」的棋盤——外框「加上」內部格線結構——都定位得到時，
    才算棋盤存在。只用 1 倍縮放。

    WHY the full grid, not just a bounding box 為什麼要完整格線、不能只看外框:
    measured from a real session log (2026-08-06 19:47): the puzzle's entrance
    animation draws the OUTER border before the interior grid lines finish
    rendering. A bbox-only check fired on that frame, and solve_image() then
    burned ~9s running the full ladder plus the fallback-type sweep against a
    capture whose grid size was genuinely undetectable - every attempt failed
    with "grid size not detected". Requiring detect_grid_size (inside
    build_grid) to succeed means we simply keep polling for the extra
    fraction of a second the animation needs, instead of committing to a
    frame that cannot be solved.
    為什麼要完整格線、不能只看外框：真實執行記錄（2026-08-06 19:47）量到：
    謎題的進場動畫會先畫「外框」、內部格線稍後才渲染完。只看外框的檢查在
    那一幀就觸發了，solve_image() 接著對一張格數真的讀不出來的截圖白跑了
    約 9 秒的完整階梯＋備援類型全掃——每一次嘗試都失敗在「無法偵測棋盤
    格數」。要求 build_grid（內含 detect_grid_size）成功，代表我們只是多
    輪詢動畫需要的那零點幾秒，而不是拍板一張根本解不出來的影格。
    """
    try:
        if build_grid(image) is not None:
            return True
    except ValueError:
        pass
    found = find_board_by_grid_lines(image)
    return found is not None


def wait_for_board(
    capture_fn: Callable[[], ScreenShot],
    should_continue: Callable[[], bool] | None = None,
    poll_interval: float = POLL_INTERVAL,
    stable_polls: int = STABLE_POLLS,
) -> ScreenShot | None:
    """Poll capture_fn() until a board is detected STABLE_POLLS times in a
    row, then return that capture. Returns None if should_continue() turns
    False first (the user pressed Stop before a puzzle ever appeared).
    輪詢 capture_fn()，直到連續 stable_polls 次都偵測到棋盤，回傳那次擷取。
    如果 should_continue() 先變成 False（使用者在題目出現之前就按了停止），
    回傳 None。

    capture_fn is injected (rather than this module reading settings itself)
    so it can be a screen grab in real use and a scripted sequence in tests -
    the same pattern BoardWatch's `grab`/`locate` fields use.
    capture_fn 用注入的（不是這個模組自己讀設定），實際使用時是真的螢幕
    擷取，測試時可以是腳本化的序列——跟 BoardWatch 的 `grab`/`locate`
    欄位是同一種做法。
    """
    action_log.log("RUN", "waiting for puzzle to appear on screen")
    started = time.perf_counter()
    consecutive = 0
    polls = 0
    while should_continue is None or should_continue():
        shot = capture_fn()
        polls += 1
        if _board_present(shot.image):
            consecutive += 1
            if consecutive >= stable_polls:
                action_log.log("RUN", f"puzzle detected after {polls} poll(s), "
                                f"{time.perf_counter() - started:.2f}s waiting")
                return shot
        else:
            consecutive = 0
        time.sleep(poll_interval)
    action_log.log("STOP", f"cancelled while waiting for the puzzle, "
                    f"{polls} poll(s), {time.perf_counter() - started:.2f}s")
    return None


def wait_for_board_gone(
    capture_fn: Callable[[], ScreenShot],
    should_continue: Callable[[], bool] | None = None,
    poll_interval: float = POLL_INTERVAL,
    stable_polls: int = STABLE_POLLS,
) -> bool:
    """Poll until NO board is detected stable_polls times in a row. True when
    the board is gone, False if cancelled first.
    輪詢到連續 stable_polls 次都「偵測不到」棋盤為止。棋盤消失回傳 True，
    先被取消回傳 False。

    WHY THIS EXISTS 為什麼需要這個: continuous mode loops wait -> solve ->
    fill -> wait again. Without this step between rounds, the round that
    just finished would immediately re-trigger on ITS OWN board - the solved
    board (or a failed board the user has not navigated away from yet) is
    still sitting in the capture region. Waiting for absence first means the
    next detection can only be a genuinely NEW puzzle.
    為什麼需要這個：連續模式的迴圈是 等待 -> 求解 -> 填答 -> 再等待。
    兩輪之間少了這一步，剛結束的那一輪會立刻對「自己那個棋盤」重新觸發——
    解完的棋盤（或辨識失敗、使用者還沒切走的棋盤）都還留在擷取範圍裡。
    先等它消失，下一次偵測到的才保證是真正的「新」題目。

    The same stability logic as wait_for_board, mirrored: a completion
    animation can hide the board for one poll mid-transition; requiring
    stable_polls consecutive misses keeps a flicker from ending the wait
    early.
    跟 wait_for_board 同一套穩定邏輯，方向相反：完成動畫的過場可能讓棋盤
    只消失一次輪詢；要求連續 stable_polls 次都看不到，過場的閃爍才不會
    提早結束等待。
    """
    action_log.log("RUN", "waiting for the current board to leave the screen")
    started = time.perf_counter()
    consecutive = 0
    polls = 0
    while should_continue is None or should_continue():
        shot = capture_fn()
        polls += 1
        if _board_present(shot.image):
            consecutive = 0
        else:
            consecutive += 1
            if consecutive >= stable_polls:
                action_log.log("RUN", f"board gone after {polls} poll(s), "
                                f"{time.perf_counter() - started:.2f}s")
                return True
        time.sleep(poll_interval)
    action_log.log("STOP", f"cancelled while waiting for the board to go, "
                    f"{polls} poll(s), {time.perf_counter() - started:.2f}s")
    return False
