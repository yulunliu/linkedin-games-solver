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
1x scale only, cost 1.4ms once a board is present and 30.0ms when nothing is
there yet (both locators get tried). That is cheap enough to poll often
without the cost showing up anywhere a user would notice.

UPDATE 2026-08-10: 1x alone is not always enough - see BORDER_RETRY_SCALE.
When 1x finds nothing, one retry at 1.75x is tried before giving up on that
poll, which raises the "nothing there yet" cost to 150.9ms (still under
POLL_INTERVAL's own budget, and never paid once a board - at either scale -
is actually present).
solve_image() 完整的裁切 x 縮放階梯是設計來找出「正確答案」的，不是設計來
盡快回答「這裡現在有沒有棋盤形狀的東西」——每次輪詢都跑一次階梯，
只會在頁面根本還沒載入時空燒 CPU。實測 640x700 的擷取範圍：solve_image()
自己用來定位棋盤的同一組定位器（find_board_bbox、find_board_by_grid_lines），
只用 1 倍縮放，棋盤已經出現時要 1.4 毫秒，還沒出現時（兩種都要試）要
30.0 毫秒。夠便宜，可以常常輪詢也不會讓使用者感覺到成本。

更新 2026-08-10：只用 1 倍不一定夠——見 BORDER_RETRY_SCALE。1 倍找不到時
會再用 1.75 倍重試一次才放棄這次輪詢，讓「還沒出現」的成本提高到
150.9 毫秒（還是在 POLL_INTERVAL 自己的預算內，而且只要任一倍率真的找到
棋盤就不會付這筆成本）。

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

import cv2

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

#: Consecutive successful detections required before committing to a board.
#: 連續幾次偵測成功才算數、才會真的採信棋盤出現了。
#:
#: HISTORY 沿革: this was 2, guarding against half-rendered transition
#: frames. Two later changes made the second confirmation redundant and it
#: went back to 1: (a) presence now requires the FULL grid to locate
#: (build_grid incl. detect_grid_size - see _board_present), so the exact
#: frame class that burned a real run (border drawn, interior not) can no
#: longer pass at all; (b) if a frame passes the grid check but its
#: icons/labels are still fading in, the solve fails cheaply against a
#: readable grid and the caller's fresh-capture retry (ui/app.py
#: MAX_SOLVE_ATTEMPTS) recovers it. With both nets in place the extra
#: 0.15s poll bought nothing.
#: 沿革：原本是 2，防的是切換中的半成品影格。後來兩個改動讓第二次確認
#: 變成多餘的，於是改回 1：(a) 存在判定現在要求「完整棋盤」定位得到
#: （build_grid 含 detect_grid_size——見 _board_present），所以真的燒掉
#: 一輪的那類影格（外框畫了、內部沒畫）根本過不了關；(b) 就算某一幀
#: 過了格線檢查、圖示／標籤還在淡入，對著讀得到的格線求解會便宜地失敗，
#: 呼叫端的新擷取重試（ui/app.py 的 MAX_SOLVE_ATTEMPTS）會把它救回來。
#: 兩張網都在之後，多等的那 0.15 秒買不到任何東西。
STABLE_POLLS = 1

#: Consecutive MISSES required before declaring the board gone - kept at 2,
#: NOT lowered alongside STABLE_POLLS, because the failure modes differ: a
#: completion animation can hide the board for a single poll mid-transition,
#: and a premature "gone" verdict makes continuous mode immediately re-detect
#: the SAME still-present board as a "new puzzle" and re-solve it. Detection
#: committing early is caught by the solve-retry net; gone-detection has no
#: such net, so it keeps the stability window.
#: 連續幾次「看不到」才判定棋盤消失——維持 2，「不」跟著 STABLE_POLLS 一起
#: 降，因為失敗情境不同：完成動畫的過場可能讓棋盤只消失一次輪詢，而過早
#: 判定「消失了」會讓連續模式立刻把「還在原地的同一個棋盤」當成新題目
#: 重新偵測、重新求解。偵測太早拍板有求解重試那張網接著；消失判定沒有
#: 這種網，所以它保留穩定窗。
GONE_STABLE_POLLS = 2

#: Prescale tried when the 1x check finds nothing at all, before giving up on
#: this poll. Same value as puzzles/__init__.py's _PRESCALE_STEPS[1] - this is
#: the SAME problem _locate_board's docstring already names ("pre-scaling if
#: its faint border is missed at 1x"), just reappearing here because this
#: module's cheap check only ever tried 1x.
#:
#: MEASURED 量測依據: a real Patches capture (dist/img/Patches_20260810_2.png,
#: 2026-08-10, saved via the "測範圍" button - i.e. the exact bytes
#: BoardWatch's own capture path produces, not a screen recording) never
#: locates at 1x - find_board_bbox's largest contour is 7,980px^2 against the
#: 15%-of-frame threshold of 67,200px^2; Canny+dilate's fixed-size kernels
#: only pick up the individual number badges (several ~57x57 squares), never
#: the board's own faint outer line. At 1.75x the same capture locates
#: cleanly (bbox area scales with pixels, but the border becomes thick enough
#: in absolute pixels for the same fixed kernels to close it into one
#: contour). Confirmed this is not a video-recording artefact: the SAME
#: region, screen-recorded in LinkedIn_20260810_2_加速版.mp4 at the same
#: nominal coordinates, DOES locate at 1x - only BoardWatch's own real
#: capture needs the rescale, which is why this went unnoticed until a real
#: capture was saved and inspected directly.
#: Cost: measured over 30 calls on the real capture above (640x700, no board
#: found at either scale - the worst case, since both scales are always
#: tried): 1x alone averages 30.0ms; adding this 1.75x retry brings it to
#: 150.9ms. Both stay well under POLL_INTERVAL's own budget - this only
#: slows down polling while genuinely nothing is on screen yet, never once a
#: board (at either scale) is found, and never during a fill.
#: 同一顆問題 _locate_board 的文件字串早就取了名字（「淡色邊框在原尺寸抓不到
#: 時先放大再找」）——這裡會重演，純粹是因為這個模組的便宜檢查一直只試
#: 1 倍。量測依據：一張真實的拼塊擷取（dist/img/Patches_20260810_2.png，
#: 2026-08-10，用面板上的「測範圍」按鈕存的——也就是 BoardWatch 自己擷取
#: 路徑真正產生的位元組，不是螢幕錄影）在 1 倍下完全定位不到——
#: find_board_bbox 找到的最大輪廓只有 7,980 平方像素，門檻（畫面 15%）是
#: 67,200；Canny+dilate 固定尺寸的核只抓得到一顆顆數字標籤（幾個約 57x57
#: 的正方形），抓不到棋盤本身那圈很淡的外框線。放大到 1.75 倍，同一張擷取
#: 乾淨定位成功（bbox 面積隨像素數縮放，但外框線在絕對像素上變粗到同一組
#: 固定核能把它接成一圈輪廓）。確認過這不是螢幕錄影的假象：同一個範圍，
#: 用同樣的座標從 LinkedIn_20260810_2_加速版.mp4 錄影截出來，在 1 倍下就
#: 定位得到——只有 BoardWatch 自己真正的擷取需要放大，這也是為什麼直到
#: 真的存下一張真實擷取直接檢視之前，這個問題完全沒被發現。
#: 成本：對著上面那張真實擷取（640x700，兩種倍率都找不到棋盤——兩種倍率
#: 都一定會試到的最壞情況）量 30 次：只用 1 倍平均 30.0ms；加上這次
#: 1.75 倍重試後變成 150.9ms。兩者都還在 POLL_INTERVAL 自己的預算之內——
#: 這只會讓「畫面上真的還沒有任何東西」時的輪詢變慢，一旦任一倍率找得到
#: 棋盤就不會多花這筆成本，填答期間也完全不會用到。
BORDER_RETRY_SCALE = 1.75


def _board_present_at(image) -> bool:
    """A board counts as present only when a FULL grid - border AND interior
    cell structure - can be located, at whatever scale `image` already is.
    只有在「完整」的棋盤——外框「加上」內部格線結構——都定位得到時，
    才算棋盤存在，用傳進來的這個縮放倍率判斷。

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


def _board_present(image) -> bool:
    """A board counts as present when _board_present_at succeeds at 1x, or -
    if not - at BORDER_RETRY_SCALE. See BORDER_RETRY_SCALE for why the retry
    exists: some boards' own border is too faint for either locator to close
    into a contour at native capture resolution, no matter how long polling
    continues, unless it is retried at a larger scale.
    _board_present_at 在 1 倍下成功、或（不成功的話）在 BORDER_RETRY_SCALE
    下成功，就算棋盤存在。為什麼需要這次重試見 BORDER_RETRY_SCALE 的說明：
    某些棋盤自己的外框在原始擷取解析度下太淡，不管兩種定位器、也不管輪詢
    多久，都接不成一圈輪廓，除非用更大的倍率重試。
    """
    if _board_present_at(image):
        return True
    scaled = cv2.resize(image, None, fx=BORDER_RETRY_SCALE, fy=BORDER_RETRY_SCALE,
                         interpolation=cv2.INTER_CUBIC)
    return _board_present_at(scaled)


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
    stable_polls: int = GONE_STABLE_POLLS,
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
