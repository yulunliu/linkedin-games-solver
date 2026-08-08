"""
Recognition tests against real captures.
用真實擷取畫面做的辨識測試。

Every fixture here corresponds to a bug that was actually hit and fixed. Keeping
them as tests stops those bugs coming back.
這裡每一張圖都對應一個實際遇到並修好的問題。留成測試可以避免它們再次發生。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from linkedin_games_solver.core import detect_type, read_image  # noqa: E402
from linkedin_games_solver.puzzles import patches, queens, solve_image  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures"


def _load(name):
    image = read_image(FIXTURES / name)
    assert image is not None, f"missing fixture / 找不到測試圖: {name}"
    return image


# --------------------------------------------------------------- type
def test_puzzle_type_detection():
    """
    Bug this guards: a pastel Queens board has low colour saturation and was
    misfiled as Patches, then "solved" as one giant rectangle - reported as
    success. Also: a fully-filled Tango must not look like Queens.
    這個測試守住的問題：淡色系的 Queens 盤面彩度低，曾被誤判成 Patches，
    然後「解」成一塊大矩形卻回報成功。另外，全部填滿的 Tango 不能被當成 Queens。
    """
    cases = [
        ("live_queens_3.png", "queens"),          # pastel board 淡色系
        ("live_queens_region.png", "queens"),
        ("live_queens_2.png", "queens"),
        ("live_queens_with_crowns.png", "queens"),
        ("live_tango.png", "tango"),
        ("live_patches.png", "patches"),
        ("S__104316934_0.jpg", "queens"),
        ("S__104316931.jpg", "tango"),
        ("S__104316935_0.jpg", "sudoku"),
        ("S__104316936_0.jpg", "patches"),
        ("S__104316937_0.jpg", "zip"),
        ("puzzle_answer.png", "tango"),           # fully filled 全部填滿
    ]
    for name, expected in cases:
        got = detect_type(_load(name))
        assert got == expected, f"{name}: expected {expected}, got {got}"
    print(f"  puzzle type detection: {len(cases)} cases OK")


# --------------------------------------------------------------- solving
def test_all_five_puzzles_solve():
    cases = [
        ("S__104316931.jpg", "tango"),
        ("S__104316934_0.jpg", "queens"),
        ("S__104316935_0.jpg", "sudoku"),
        ("S__104316936_0.jpg", "patches"),
        ("S__104316937_0.jpg", "zip"),
    ]
    for name, expected in cases:
        result = solve_image(_load(name))
        assert result.ok, f"{name} failed: {result.error}"
        assert result.puzzle_key == expected
    print("  all five puzzles solve OK")


def _check_queens_rules(image, result):
    n = result.grid.n
    positions = result.data["queens"]
    regions, _ = queens.read_regions(image, result.grid)
    assert queens.regions_look_valid(regions, n), "regions invalid / 色塊分群不合理"
    assert sorted(r for r, _ in positions) == list(range(n))
    assert sorted(c for _, c in positions) == list(range(n))
    assert len({regions[r][c] for r, c in positions}) == n
    for i, a in enumerate(positions):
        for b in positions[i + 1 :]:
            assert max(abs(a[0] - b[0]), abs(a[1] - b[1])) > 1


def test_live_queens_boards():
    for name in ("live_queens_region.png", "live_queens_2.png",
                 "live_queens_with_crowns.png", "live_queens_3.png"):
        image = _load(name)
        result = solve_image(image)
        assert result.ok and result.puzzle_key == "queens", f"{name}: {result.error}"
        _check_queens_rules(image, result)
    print("  live queens boards OK")


def test_live_tango_matches_screen():
    """
    Bug this guards: Tango's board has no border, and inferring the grid from
    icon positions landed one column off - every given shifted and the "=" marks
    in the outer columns fell outside the board.
    這個測試守住的問題：Tango 棋盤沒有外框，用圖示位置反推網格會整個偏一欄 ——
    所有 given 跟著位移，最外圈欄位的 "=" 符號完全落在棋盤外。
    """
    result = solve_image(_load("live_tango.png"))
    assert result.ok, result.error
    solution = result.data["solution"]
    n = len(solution)

    # Read off the real screenshot by hand. 人工從真實截圖核對。
    truth = {(0, 2): 1, (0, 3): 1, (1, 1): 1, (1, 4): 0,
             (4, 1): 1, (4, 4): 1, (5, 2): 0, (5, 3): 1}
    assert set(result.data["givens"]) == set(truth), "givens do not match the screen / given 與畫面不符"
    for (r, c), v in truth.items():
        assert solution[r][c] == v

    for r in range(n):
        assert sum(solution[r]) == n // 2
    for c in range(n):
        assert sum(solution[r][c] for r in range(n)) == n // 2
    print("  live tango matches the screen OK")


def test_live_patches_with_blank_labels():
    """
    Bug this guards: dashed labels are stacked translucent shapes whose white
    gaps were read as digit strokes - a real "4" split into 4 fragments and a
    blank label into 3, both reported as "unreadable" and aborting the solve.
    這個測試守住的問題：虛線標籤是疊起來的半透明形狀，形狀之間的白色縫隙曾被
    當成數字筆畫 —— 一個真的「4」被切成 4 塊碎片，空白標籤切成 3 塊，
    兩者都被判成「讀不出來」而中斷辨識。
    """
    image = _load("live_patches.png")
    result = solve_image(image)
    assert result.ok, result.error
    labels = result.data["labels"]
    assert len(labels) == 14, f"expected 14 labels, got {len(labels)}"

    numbered = sorted(lb.value for lb in labels if lb.value is not None)
    assert numbered == [2, 2, 2, 4, 4, 4, 4], f"numbers wrong / 數字不符: {numbered}"
    assert sum(1 for lb in labels if lb.value is None) == 7, "expected 7 blank labels / 應有 7 個無數字標籤"

    n = result.grid.n
    covered = {}
    for label, (r0, c0, h, w) in zip(labels, result.data["rects"]):
        if label.value is not None:
            assert h * w == label.value
        assert patches.shape_allowed(label.shape, h, w)
        for r in range(r0, r0 + h):
            for c in range(c0, c0 + w):
                assert (r, c) not in covered
                covered[(r, c)] = True
    assert len(covered) == n * n
    print("  live patches with blank labels OK")


def test_live_browser_mini_sudoku_reads_every_given():
    """
    Bug this guards: a real session (2026-08-08 log + screen recording) showed
    digit "3" scoring only 0.876-0.898 against the digit templates on this
    board - short of MIN_SCORE (0.90) - while every OTHER digit on the same
    board scored 0.94-0.99. classify_glyph correctly refused to guess
    (that is the safety mechanism working as designed), so the puzzle read as
    under-constrained and every solve attempt correctly - but uselessly -
    failed with "solution not unique". Not a logic bug: this board's own
    rendering of "3" (LinkedIn's in-BROWSER Mini Sudoku widget) simply was not
    close enough to the templates, which had come only from a phone-app
    screenshot. Fixed by adding this board's own digits as a second
    calibration source (tools/calibrate_digits.py's BROWSER_SUDOKU_GIVENS) -
    not by loosening MIN_SCORE, which would have let a genuinely ambiguous
    glyph through on every OTHER board too.
    這個測試守住的問題：一次真實執行（2026-08-08 執行記錄 + 螢幕錄影）
    顯示，這個棋盤上的數字「3」對數字範本只拿到 0.876~0.898 分——不到
    MIN_SCORE（0.90）——而同一個棋盤上其他每個數字都拿到 0.94~0.99 分。
    classify_glyph 正確地拒絕用猜的（這正是安全機制設計上該有的行為），
    於是題目被讀成條件不足，每一次求解嘗試都正確地——但沒有用地——失敗在
    「解不唯一」。這不是邏輯錯誤：這個棋盤自己畫的「3」（LinkedIn 瀏覽器內建
    的 Mini Sudoku 元件），純粹跟範本不夠像，而範本原本只來自一張手機 App
    截圖。修法是把這個棋盤自己的數字加進第二個校準來源
    （tools/calibrate_digits.py 的 BROWSER_SUDOKU_GIVENS）——不是放寬
    MIN_SCORE，那樣會讓其他每一個棋盤上真正模稜兩可的字形也一起被放行。
    """
    image = _load("live_mini_sudoku_browser.png")
    result = solve_image(image)
    assert result.ok, result.error
    assert result.puzzle_key == "sudoku"

    givens = result.data["givens"]
    expected = {
        (0, 0): 1, (0, 2): 2, (0, 5): 3,
        (2, 0): 2, (2, 2): 4,
        (3, 3): 4, (3, 5): 5,
        (5, 0): 3, (5, 3): 5, (5, 5): 1,
    }
    assert givens == expected, f"givens mismatch / 給定數字不符: {givens}"
    print("  live browser Mini Sudoku reads every given OK")


def test_wrong_type_does_not_fake_success():
    """Forcing the wrong type must fail loudly, not invent an answer.
    指定錯誤的類型必須明確失敗，不能編一個答案出來。"""
    result = solve_image(_load("live_queens_3.png"), puzzle_key="patches")
    assert not result.ok, "should not report success / 不該回報成功"
    print("  wrong type does not fake success OK")


def test_zoom_hint_is_not_appended_to_a_comfortably_large_borderless_board():
    """
    Bug this guards: the final failure handler measured board size with
    find_board_bbox ALONE, which structurally cannot see Tango (it has no
    outer border - see core/board.py). So board_px was always None for
    Tango, and EVERY Tango failure got "board too small / not found. Zoom in
    with Ctrl +" tacked on regardless of the real cause or the real size.
    S__104316931.jpg's board is 799px - nowhere near MIN_BOARD_PIXELS=500 -
    yet the old code would still have claimed otherwise.
    這個測試守住的問題：最後的失敗處理只用 find_board_bbox 量棋盤大小，
    而它結構上就看不到 Tango（Tango 沒有外框——見 core/board.py）。
    所以 Tango 的 board_px 以前永遠是 None，不管真正原因或真正大小是什麼，
    每一次 Tango 失敗都會被硬加上「棋盤太小／找不到。可按 Ctrl + 放大」。
    S__104316931.jpg 的棋盤有 799px，離 MIN_BOARD_PIXELS=500 還遠得很，
    但舊的程式碼還是會宣稱相反的事。
    """
    # n_hint=99 forces every attempt to fail regardless of the board's real,
    # comfortably-large size - isolating the zoom-hint logic from whether
    # the puzzle would otherwise have solved.
    # n_hint=99 強迫每一次嘗試都失敗，不管棋盤真正的大小其實很夠——
    # 這樣才能把「zoom 提示的邏輯」跟「這題本來會不會解成功」分開來測。
    result = solve_image(_load("S__104316931.jpg"), puzzle_key="tango", n_hint=99)
    assert not result.ok
    assert "Zoom in" not in result.error and "放大" not in result.error, (
        f"a 799px board must not be reported as too small / "
        f"799px 的棋盤不該被講成太小: {result.error!r}"
    )
    print("  zoom hint is not falsely appended to a large borderless board OK")


def test_initial_recognition_survives_a_partially_filled_patches_board():
    """
    Bug this guards: solve_image() - the INITIAL scan, not the mid-plan
    guard - used to fail with the unhelpful "grid size not detected" on a
    Patches board that already had some cells filled in. Reachable if a
    user starts the tool after manually placing a piece, or a caller
    re-solves mid-fill. build_grid() now retries with high-saturation marks
    masked out before giving up (core/board.py) - the same fix already
    proven for the mid-plan guard, shared rather than duplicated.
    這個測試守住的問題：solve_image()——初次掃描，不是填答中途的保護——
    以前對一個已經有幾格被填過的拼塊棋盤，只會給一個沒有幫助的
    「無法自動偵測棋盤格數」。使用者手動放了一塊再啟動工具、或呼叫端在
    填答途中重新求解，都碰得到。build_grid() 現在會在放棄之前，先把
    高飽和度的標記遮掉再試一次（core/board.py）——這是已經在中途保護上
    證明有效的同一個修法，共用而不是複製一份。

    Confirms two things: the grid is actually located (n=6, not a guess),
    and if the fill happens to have obscured a label, the failure that
    follows is a specific, honest one - never a fabricated answer.
    確認兩件事：格數真的定位得到（n=6，不是用猜的），而且如果填色剛好
    蓋住了某個標籤，接下來的失敗是具體、誠實的——絕不是編出來的答案。
    """
    from linkedin_games_solver.core.board import build_grid

    image = _load("patches_mid_drag_1of6.png")
    grid = build_grid(image)
    assert grid.n == 6, f"expected n=6, got {grid.n}"

    result = solve_image(image)
    # This particular fixture has a label obscured by the drawn fill, so the
    # solver correctly refuses to guess - but it must fail SPECIFICALLY, not
    # with the old generic "grid size not detected".
    # 這張測試圖剛好有一個標籤被填色蓋住，所以求解器正確地拒絕用猜的——
    # 但失敗訊息必須是「具體的」，不能是舊的那句籠統的「無法自動偵測棋盤格數」。
    if not result.ok:
        assert "grid size not detected" not in result.error, (
            f"recognition should get past grid detection now / "
            f"辨識現在應該能通過格數偵測這一步: {result.error!r}"
        )
    print("  initial recognition survives a partially filled Patches board OK")


# --------------------------------------------------------------- verify
def test_stops_when_board_changes():
    """
    Bug this guards: after solving, the site shows a completion screen. The
    verify-and-retry loop then read garbage, decided crowns were missing, and
    kept clicking - "it kept controlling my mouse after finishing".
    這個測試守住的問題：解完之後網站會顯示完成畫面。驗證補點迴圈會讀到垃圾、
    判定皇冠不見而繼續點 —— 也就是「解完了滑鼠還被一直控制」。
    """
    import cv2

    from linkedin_games_solver.automation import (
        BoardMapper, build_retry_plan, from_file_image, verify,
    )

    image = _load("live_queens_3.png")
    result = solve_image(image)
    assert result.ok
    mapper = BoardMapper(shot=from_file_image(image), grid=result.grid)

    unchanged = verify(image, result)
    assert not unchanged.board_changed, "same board flagged as changed / 沒變卻判定成改變"
    assert build_retry_plan(result, mapper, unchanged) is not None

    # Completion screen: board painted over. 完成畫面：盤面被蓋掉。
    covered = image.copy()
    x, y, w, h = result.grid.board_bbox
    cv2.rectangle(covered, (x, y), (x + w, y + h), (245, 245, 245), -1)
    changed = verify(covered, result)
    assert changed.board_changed, "covered board not detected / 盤面被蓋掉沒偵測到"
    assert build_retry_plan(result, mapper, changed) is None, "must not retry / 不能再補點"

    # A different puzzle entirely. 換成完全不同的謎題。
    other = verify(_load("live_patches.png"), result)
    assert other.board_changed
    assert build_retry_plan(result, mapper, other) is None

    # Crowns placed is NOT a board change. 放上皇冠不算盤面改變。
    with_crowns = _load("live_queens_with_crowns.png")
    result2 = solve_image(with_crowns)
    assert not verify(with_crowns, result2).board_changed
    print("  stops when the board changes OK")


def test_stops_when_the_board_shifts_without_disappearing():
    """
    Bug this guards: every verifier compares cells by grid INDEX, which is
    translation-invariant - a board that MOVED within the same capture
    (page scroll, window resize, a card growing) reads exactly the same as
    one that never moved. Measured before this fix: a 9x9 Queens board
    (89px cells) shifted 80px down still verified as unchanged; swept -120px
    to +300px and board_changed was False at every single offset, while
    build_grid on the same frame correctly reported the new bbox the whole
    time. The retry plan then clicks the OLD pixel coordinates, which now
    belong to a different cell - a silent wrong click, not a crash.
    這個測試守住的問題：每個驗證器都是用格子「索引」比對，那對平移是不敏感
    的——棋盤在同一塊擷取範圍裡「移動」過（捲頁、視窗改變大小、卡片長高），
    讀起來會跟完全沒動過一模一樣。修正前實測：一個 9x9、格子 89px 的 Queens
    棋盤往下移 80px，依然被判定沒有改變；掃過 -120px 到 +300px，
    board_changed 在每一個偏移量都是 False，而同一張畫面上 build_grid
    卻一路正確回報新的 bbox。補點計畫接著會點下「舊的」像素座標，
    那個位置現在屬於另一格——是安靜的錯誤點擊，不是當機。

    Checked for all three verifiers that support retry (Queens, Tango,
    Sudoku) - the fix is the same one line in each, and each needs its own
    proof it actually took effect.
    對支援補點的三個驗證器都測過（Queens、Tango、Sudoku）——修法在每一個
    裡面都是同一行，各自都需要自己的證據證明真的生效了。
    """
    import numpy as np

    from linkedin_games_solver.automation import verify

    def shifted(image, dy):
        canvas = np.full_like(image, 255)
        src_top, dst_top = max(0, -dy), max(0, dy)
        h = image.shape[0] - abs(dy)
        canvas[dst_top:dst_top + h, :] = image[src_top:src_top + h, :]
        return canvas.astype(image.dtype)

    for name in ("live_queens_3.png", "live_tango.png", "S__104316935_0.jpg"):
        image = _load(name)
        result = solve_image(image)
        assert result.ok, f"{name}: {result.error}"

        # A shift smaller than the tolerance must NOT be reported as changed -
        # this is what stops the fix from being trigger-happy on ordinary
        # sub-pixel jitter between two independent detections of the SAME,
        # unmoved board.
        # 小於容忍範圍的偏移絕不能被判定成改變——這是為了不讓這個修正對
        # 「同一個沒動過的棋盤」兩次獨立辨識之間本來就會有的次像素級誤差
        # 反應過度。
        small = verify(shifted(image, 3), result)
        assert not small.board_changed, f"{name}: 3px jitter falsely flagged as moved / 誤判成移動"

        # A shift clearly beyond one cell must be caught.
        # 明顯超過一格的偏移必須被抓到。
        cell = result.grid.board_bbox[2] / result.grid.n
        big = verify(shifted(image, round(cell * 1.5)), result)
        assert big.board_changed, f"{name}: a {cell * 1.5:.0f}px shift was not detected / 沒有偵測到位移"
    print("  stops when the board shifts without disappearing OK")


def test_board_position_survives_the_working_size_cap():
    """
    Bug this guards: MAX_WORKING_PIXELS clamped the scale factor inside _scaled
    and threw the real value away, while the grid was mapped back using the
    UNCLAMPED factor. Result: ok=True, a correct answer, and a board rectangle
    up to 1.6 cells from the real board - and those are the coordinates the
    mouse uses.
    這個測試守住的問題：MAX_WORKING_PIXELS 在 _scaled 內部把倍率夾住、
    把真正的值丟掉，而棋盤座標卻是用「沒夾住」的倍率換算回去的。
    結果是 ok=True、答案正確，但棋盤矩形跟真實位置差到 1.6 格 ——
    而那正是滑鼠會用的座標。

    The trigger is a TALL capture with a board small enough that
    max_side * (794 / board_px) exceeds the cap - not any of the square-ish
    fixtures, all of which are correct either way.
    觸發條件是「直式的擷取」加上「棋盤小到 max_side * (794/board_px) 超過上限」——
    不是那些接近正方形的測試圖，那些不管有沒有上限都正確。
    """
    import cv2
    import numpy as np

    base = _load("live_queens_2.png")
    result = solve_image(base)
    assert result.ok
    x, y, w, h = result.grid.board_bbox
    card = base[y : y + h, x : x + w]

    for target, (canvas_w, canvas_h) in [(500, (870, 1882)), (450, (870, 1882)),
                                         (560, (1000, 2000)), (700, (1200, 1400))]:
        factor = target / max(card.shape[:2])
        scaled = cv2.resize(card, None, fx=factor, fy=factor, interpolation=cv2.INTER_AREA)
        canvas = np.full((canvas_h, canvas_w, 3), 255, np.uint8)
        oy, ox = (canvas_h - scaled.shape[0]) // 2, (canvas_w - scaled.shape[1]) // 2
        canvas[oy : oy + scaled.shape[0], ox : ox + scaled.shape[1]] = scaled

        got = solve_image(canvas)
        assert got.ok, f"{canvas_w}x{canvas_h} board {target}px: {got.error}"
        bx, by, bw, bh = got.grid.board_bbox
        cell = scaled.shape[1] / got.grid.n
        off_x, off_y = abs(bx - ox) / cell, abs(by - oy) / cell
        assert off_x < 0.2 and off_y < 0.2, (
            f"{canvas_w}x{canvas_h} board {target}px: reported ({bx},{by}) vs true "
            f"({ox},{oy}) = {off_x:.2f},{off_y:.2f} cells out / 位置偏差過大"
        )
    print("  board position survives the working-size cap OK")


def test_should_continue_cuts_a_failing_solve_short():
    """
    Bug this guards: solve_image had no time budget and no cancellation -
    Stop could not interrupt a solve in progress. Measured before this fix:
    a 4K screen grab took 29-49s, an 8000x8000 one 238-312s, with no check-in
    point anywhere in that time. On a timed game, silence is indistinguishable
    from a hang.
    這個測試守住的問題：solve_image 以前沒有時間預算、也沒有取消機制——
    「停止」中斷不了正在進行的求解。修正前實測：4K 螢幕擷取要 29~49 秒，
    8000x8000 要 238~312 秒，這整段時間裡完全沒有任何檢查點。
    在計時的遊戲裡，安靜跟當機分不出來。

    Pure noise fails every rung of every puzzle type's ladder, so it is
    guaranteed to keep going until should_continue says stop - proving the
    callback is actually consulted, not just accepted and ignored.
    純雜訊會讓每一款謎題、每一階階梯都失敗，保證會一路跑到 should_continue
    喊停為止——這證明這個回呼真的有被詢問，不是被接受了卻沒有用。
    """
    import time as time_module

    import numpy as np

    from linkedin_games_solver.puzzles import CANCELLED

    noise = np.random.RandomState(0).randint(0, 255, (900, 900, 3)).astype(np.uint8)

    t0 = time_module.perf_counter()
    full = solve_image(noise)
    full_elapsed = time_module.perf_counter() - t0
    assert not full.ok

    calls = {"n": 0}

    def cancel_after_3():
        calls["n"] += 1
        return calls["n"] <= 3

    t0 = time_module.perf_counter()
    cancelled = solve_image(noise, should_continue=cancel_after_3)
    cancelled_elapsed = time_module.perf_counter() - t0

    assert not cancelled.ok
    assert cancelled.error == CANCELLED, f"expected {CANCELLED!r}, got {cancelled.error!r}"
    assert calls["n"] > 0, "should_continue was never called / should_continue 從來沒被呼叫過"
    assert cancelled_elapsed < full_elapsed * 0.5, (
        f"cancelling after 3 calls ({cancelled_elapsed:.2f}s) should be far "
        f"faster than the full ladder ({full_elapsed:.2f}s) / "
        f"3 次後取消（{cancelled_elapsed:.2f}s）應該要遠比跑完整條階梯"
        f"（{full_elapsed:.2f}s）快"
    )
    print("  should_continue cuts a failing solve short OK")


if __name__ == "__main__":
    print("Recognition tests / 辨識測試")
    test_puzzle_type_detection()
    test_all_five_puzzles_solve()
    test_live_queens_boards()
    test_live_tango_matches_screen()
    test_live_patches_with_blank_labels()
    test_live_browser_mini_sudoku_reads_every_given()
    test_wrong_type_does_not_fake_success()
    test_zoom_hint_is_not_appended_to_a_comfortably_large_borderless_board()
    test_initial_recognition_survives_a_partially_filled_patches_board()
    test_stops_when_board_changes()
    test_stops_when_the_board_shifts_without_disappearing()
    test_board_position_survives_the_working_size_cap()
    test_should_continue_cuts_a_failing_solve_short()
    print("\nAll passed / 全部通過")
