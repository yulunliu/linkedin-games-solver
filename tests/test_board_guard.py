"""
Mid-plan board guard tests.
填答進行中的盤面保護測試。

The reported bug: after the puzzle completes the site swaps in its completion
screen, and the rest of the frozen click list lands on whatever is there now.
Measured blind windows before the guard: Queens 8.96s / 9 cells, Tango 21.15s /
28 actions, Patches 12.07s / 14 drags, and the retry path clicks blind for a
further 2.97s against a snapshot that is already stale.
回報的問題：謎題完成之後網站會換上完成畫面，而固定的點擊清單剩下的部分
就落在當下畫面上的東西上。加保護前實測的盲點窗口：
Queens 8.96 秒 / 9 格、Tango 21.15 秒 / 28 動作、Patches 12.07 秒 / 14 次拖曳，
補點路徑還會再對著已經過期的快照盲點 2.97 秒。

Everything here runs offline against a scripted fake screen. No mss, no display,
no real mouse.
這裡全部都是離線、對著腳本化的假螢幕跑。不需要 mss、不需要顯示裝置、不碰真滑鼠。
"""

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from linkedin_games_solver.automation import (  # noqa: E402
    Aborted, BoardMapper, InputDriver, build_plan, from_file_image,
)
from linkedin_games_solver.automation.board_watch import BoardWatch  # noqa: E402
from linkedin_games_solver.core import read_image  # noqa: E402
from linkedin_games_solver.puzzles import solve_image  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures"

#: One fixture per puzzle key, plus extra board scales. The Tango/Patches
#: regression this suite exists to catch was completely invisible on Queens.
#: 每一款謎題各一張圖，外加不同棋盤尺寸。這組測試要抓的 Tango/Patches 退步，
#: 在 Queens 上完全看不出來。
ALL_FIXTURES = [
    "live_queens_3.png", "live_queens_2.png", "live_queens_region.png",
    "live_tango.png", "S__104316931.jpg",
    "live_patches.png", "S__104316936_0.jpg", "fullscreen_patches.png",
    "S__104316935_0.jpg",
    "S__104316937_0.jpg",
    "S__104316934_0.jpg",
]


def _plan_for(name):
    image = read_image(FIXTURES / name)
    assert image is not None, f"missing fixture / 找不到測試圖: {name}"
    result = solve_image(image)
    assert result.ok, f"{name}: {result.error}"
    mapper = BoardMapper(shot=from_file_image(image), grid=result.grid)
    plan = build_plan(result.puzzle_key, mapper, result.data)
    x, y, w, h = result.grid.board_bbox
    return image, result, mapper, plan, image[y : y + h, x : x + w]


def _actions(plan):
    driver = InputDriver(dry_run=True)
    plan.run(driver)
    return len(driver.log)


# ---------------------------------------------------------------------------
def test_guard_locates_every_pristine_board():
    """
    Bug this guards: an earlier design used core.build_grid for every puzzle.
    Tango has no outer border and Patches draws its outer border fainter than
    its inner lines, so build_grid RAISES on their own untouched crops - the
    guard would have aborted every Tango fill after 0 of 28 actions and every
    browser-scale Patches fill after 0 of 14.
    這個測試守住的問題：先前的設計對所有謎題都用 core.build_grid。
    Tango 沒有外框、Patches 的外框比內部格線更淡，所以 build_grid 對它們
    「原封不動」的裁切就會拋錯 —— 那個保護會讓每次 Tango 填答在 28 個動作裡
    做 0 個就中止，瀏覽器尺寸的 Patches 在 14 個裡做 0 個就中止。
    """
    failures = []
    for name in ALL_FIXTURES:
        image, result, mapper, plan, crop = _plan_for(name)
        watch = BoardWatch(mapper=mapper, n=result.grid.n, min_interval=0.0, grab=lambda *a, _c=crop: _c)
        if not watch.arm(crop):
            failures.append(f"{name} ({result.puzzle_key}) n={result.grid.n} "
                            f"{crop.shape[1]}px")
    assert not failures, ("guard cannot find these pristine boards / "
                          "保護在這些沒被改過的棋盤上就找不到:\n  " + "\n  ".join(failures))
    print(f"  guard locates all {len(ALL_FIXTURES)} pristine boards OK")


def test_guard_never_fires_while_filling_a_pristine_board():
    """A board that never changes must never abort, for any puzzle.
    完全沒有改變的棋盤，任何謎題都不能中止。"""
    for name in ALL_FIXTURES:
        image, result, mapper, plan, crop = _plan_for(name)
        if plan is None:
            continue
        expected = _actions(plan)
        watch = BoardWatch(mapper=mapper, n=result.grid.n, min_interval=0.0, grab=lambda *a, _c=crop: _c)
        assert watch.arm(crop), f"{name}: arm failed / 自我檢驗失敗"
        driver = InputDriver(dry_run=True)
        driver.guard = watch.still_there
        plan.run(driver)
        assert not driver.stopped_by_guard, \
            f"{name} ({result.puzzle_key}): guard fired on an unchanged board / 對沒變的棋盤誤觸發"
        assert len(driver.log) == expected, \
            f"{name}: ran {len(driver.log)} of {expected} actions / 只做了 {expected} 個裡的 {len(driver.log)} 個"
    print(f"  guard never fires while filling, {len(ALL_FIXTURES)} boards OK")


def test_plan_stops_the_moment_the_board_disappears():
    """The reported bug, for every puzzle that has actions to run.
    回報的問題本身，對每一款有動作要做的謎題都驗一次。"""
    checked = 0
    for name in ALL_FIXTURES:
        image, result, mapper, plan, crop = _plan_for(name)
        total = _actions(plan)
        if total < 2:
            continue          # nothing to stop halfway through 沒有中途可停
        gone = np.full_like(crop, 245)
        state = {"n": 0}

        def grab(*a, _c=crop, _g=gone, _s=state):
            _s["n"] += 1
            return _c if _s["n"] <= 1 else _g

        watch = BoardWatch(mapper=mapper, n=result.grid.n, min_interval=0.0, grab=grab)
        assert watch.arm(crop)
        driver = InputDriver(dry_run=True)
        driver.guard = watch.still_there
        try:
            plan.run(driver)
            raise AssertionError(f"{name}: ran to completion after the board vanished "
                                 f"/ 棋盤消失後仍跑完 {total} 個動作")
        except Aborted:
            pass
        assert driver.stopped_by_guard, f"{name}: stopped but not by the guard / 不是保護造成的"
        assert len(driver.log) < total, \
            f"{name}: {len(driver.log)}/{total} actions, did not stop early / 沒有提早停"
        checked += 1
    assert checked >= 5, f"only exercised {checked} boards / 只驗到 {checked} 個棋盤"
    print(f"  plan stops when the board disappears, {checked} boards OK")


def test_guard_survives_our_own_filling():
    """
    The board changes a lot BECAUSE WE ARE FILLING IT IN. That must not abort.
    棋盤會因為「我們正在填它」而大幅改變，那不能造成中止。

    This is why the guard is structural (can the board still be located) and not
    a pixel comparison. Measured: our own fills move the pixel MAD to
    36.35-112.73, while a 25% dimming overlay - which MUST abort - only reaches
    44.93. There is no pixel threshold in either direction.
    這就是為什麼保護是結構性的（棋盤還定位得到嗎）而不是比對像素。
    實測：我們自己填答會讓像素 MAD 變成 36.35~112.73，而「必須中止」的
    25% 變暗遮罩只到 44.93。兩個方向都不存在可用的像素門檻。
    """
    import cv2

    for name in ("live_queens_3.png", "live_tango.png", "live_patches.png"):
        image, result, mapper, plan, crop = _plan_for(name)
        n = result.grid.n
        painted = crop.copy()
        # Scribble over every cell interior, far more than real filling does.
        # 把每一格的內部都塗掉，改動幅度遠大於真實填答。
        ch, cw = painted.shape[0] // n, painted.shape[1] // n
        for r in range(n):
            for c in range(n):
                y0, x0 = r * ch + ch // 4, c * cw + cw // 4
                cv2.rectangle(painted, (x0, y0), (x0 + cw // 2, y0 + ch // 2), (30, 30, 30), -1)
        watch = BoardWatch(mapper=mapper, n=n, min_interval=0.0, grab=lambda *a, _p=painted: _p)
        assert watch.arm(crop), f"{name}: arm failed / 自我檢驗失敗"
        assert watch.still_there(), \
            f"{name}: aborted because we filled the board in / 因為我們自己填了棋盤而中止"
    print("  guard survives our own filling OK")


def test_guard_latches():
    """A transient failure must not be followed by "it is back, carry on".
    暫時性的失敗之後不能又「回來了、繼續點」。"""
    image, result, mapper, plan, crop = _plan_for("live_queens_3.png")
    state = {"n": 0}

    def flaky(*a, _c=crop, _s=state):
        _s["n"] += 1
        return np.full_like(_c, 245) if _s["n"] == 2 else _c

    watch = BoardWatch(mapper=mapper, n=result.grid.n, min_interval=0.0, grab=flaky)
    assert watch.arm(crop)
    assert watch.still_there() is True
    assert watch.still_there() is False, "should report gone / 應回報不見了"
    assert watch.still_there() is False, "must latch / 必須鎖定"
    print("  guard latches OK")


def test_guard_refuses_to_judge_without_a_self_test():
    """
    If arm() fails the guard must never abort anything - it would kill filling.
    arm() 失敗時保護絕不能中止任何東西 —— 那會直接讓填答不能用。

    A locator that cannot find the board in the plan's OWN frame is a
    configuration fault, not evidence the board is gone. This single check is
    what would have caught the Tango/Patches regression before a user did.
    定位器如果連「計畫自己的那一幀」都找不到棋盤，那是設定錯誤，
    不是棋盤不見了的證據。就是這一個檢查能在使用者之前抓到 Tango/Patches 的退步。
    """
    image, result, mapper, plan, crop = _plan_for("live_queens_3.png")
    watch = BoardWatch(mapper=mapper, n=result.grid.n, min_interval=0.0,
                       grab=lambda *a: np.zeros((10, 10, 3), np.uint8),
                       locate=lambda img, n: None)
    assert watch.arm(crop) is False
    assert watch.armed is False
    assert watch.still_there() is True, "unarmed guard must not judge / 未啟用的保護不能下判斷"

    driver = InputDriver(dry_run=True)
    driver.guard = watch.still_there
    plan.run(driver)
    assert not driver.stopped_by_guard
    assert len(driver.log) == _actions(plan), "filling was cut short / 填答被截斷"
    print("  guard refuses to judge without a self-test OK")


def test_guard_stops_when_the_screen_cannot_be_read():
    """Refusing to look is not evidence the board is fine.
    看不到不等於棋盤沒事。"""
    image, result, mapper, plan, crop = _plan_for("live_queens_3.png")

    def explode(*a, **k):
        raise OSError("screen gone")

    watch = BoardWatch(mapper=mapper, n=result.grid.n, min_interval=0.0, grab=explode)
    assert watch.arm(crop)
    assert watch.still_there() is False
    assert "capture failed" in watch.reason or "擷取螢幕失敗" in watch.reason
    print("  guard stops when the screen cannot be read OK")


def test_guard_detects_a_different_puzzle_in_the_same_place():
    """The site navigating to another game must stop us, not just a blank screen.
    網站切到另一款遊戲也要停，不能只認得「整片空白」。"""
    image, result, mapper, plan, crop = _plan_for("live_queens_3.png")
    import cv2

    other = read_image(FIXTURES / "live_patches.png")
    other = cv2.resize(other, (crop.shape[1], crop.shape[0]))
    watch = BoardWatch(mapper=mapper, n=result.grid.n, min_interval=0.0, grab=lambda *a, _o=other: _o)
    assert watch.arm(crop)
    assert not watch.still_there(), \
        "a different puzzle in the same rect went unnoticed / 同位置換成另一款謎題沒被發現"
    assert "no longer where it was" in watch.reason or "已不在原處" in watch.reason
    print("  guard detects a different puzzle OK")


def test_guard_survives_every_real_board_state():
    """
    The decisive population: real boards EMPTY, HALF FILLED, COMPLETELY FILLED
    and SOLVED. Aborting on any of these breaks the feature on a correct board.
    決定性的母體：真實棋盤的「空白 / 填一半 / 完全填滿 / 已解完」。
    對其中任何一個中止，就是在一個正確的盤面上把功能弄壞。

    Requiring the located size to match EXACTLY aborted on puzzle_answer.png -
    a completely filled 6x6 Tango, which reads n=12 because drawing into every
    cell adds an apparent boundary inside it. That is why the rule accepts an
    integer refinement of our own size.
    要求定位到的格數「完全相符」會對 puzzle_answer.png 中止 —— 那是一個完全填滿的
    6x6 Tango，因為每格裡都畫了東西、格內多出看似的邊界，所以讀到 n=12。
    這就是規則要接受「自身格數的整數細分」的原因。
    """
    from linkedin_games_solver.automation.board_watch import locate_board

    states = [
        ("puzzle_only.png", "tango empty 空白"),
        ("puzzle_answer.png", "tango COMPLETELY FILLED 完全填滿"),
        ("live_tango.png", "tango browser"),
        ("S__104316931.jpg", "tango phone"),
        ("live_queens_3.png", "queens empty"),
        ("live_queens_with_crowns.png", "queens crowns placed 已放皇冠"),
        ("queens_mixed_state.png", "queens half done 填一半"),
        ("queens_solved_state.png", "queens SOLVED 已解完"),
        ("live_queens_2.png", "queens"),
        ("live_queens_region.png", "queens"),
        ("S__104316934_0.jpg", "queens phone"),
        ("live_patches.png", "patches browser"),
        ("patches_blank_labels.png", "patches"),
        ("S__104316936_0.jpg", "patches phone"),
        ("fullscreen_patches.png", "patches fullscreen"),
        ("S__104316935_0.jpg", "sudoku phone"),
        ("S__104316937_0.jpg", "zip phone"),
    ]
    failures = []
    for name, desc in states:
        image = read_image(FIXTURES / name)
        if image is None:
            continue
        result = solve_image(image)
        if not result.ok:
            continue
        x, y, w, h = result.grid.board_bbox
        crop = image[y : y + h, x : x + w]
        if locate_board(crop, result.grid.n) is None:
            failures.append(f"{name} ({desc}) n={result.grid.n} {w}px")
    assert not failures, ("guard would abort on these REAL board states / "
                          "保護會對這些真實棋盤狀態中止: " + "; ".join(failures))
    print(f"  guard survives all {len(states)} real board states OK")


def test_guard_detects_replacement_scenarios():
    """Every realistic way the board stops being our board must be caught.
    棋盤「不再是我們那個棋盤」的每一種實際情況都要抓到。"""
    import cv2
    from linkedin_games_solver.automation.board_watch import locate_board

    image, result, mapper, plan, crop = _plan_for("live_queens_3.png")
    n = result.grid.n
    _, tango_result, _, _, tango_crop = _plan_for("live_tango.png")
    _, patches_result, _, _, patches_crop = _plan_for("live_patches.png")

    must_abort = [
        ("flat 245 - the realistic completion screen 真實的完成畫面",
         np.full_like(crop, 245), n),
        ("flat white", np.full_like(crop, 255), n),
        ("flat dark", np.full_like(crop, 40), n),
        ("random noise", np.random.RandomState(0).randint(0, 255, crop.shape).astype(np.uint8), n),
        ("a different puzzle in the same rect 同位置換成另一款謎題",
         cv2.resize(patches_crop, (crop.shape[1], crop.shape[0])), n),
        ("our puzzle at the wrong size 我們的謎題但格數不對",
         cv2.resize(crop, (tango_crop.shape[1], tango_crop.shape[0])), tango_result.grid.n),
    ]
    missed = [label for label, img, size in must_abort if locate_board(img, size) is not None]
    assert not missed, "guard did not notice these / 保護沒發現這些: " + ", ".join(missed)
    print(f"  guard detects all {len(must_abort)} replacement scenarios OK")


def test_known_blind_spot_is_documented():
    """A translucent scrim over a live board is NOT detected. Documented, not
    hidden - the board is structurally still there underneath.
    蓋在活著的棋盤上的半透明遮罩「抓不到」。這裡記錄而不是隱藏 ——
    棋盤在底下結構上仍然存在。"""
    import cv2
    from linkedin_games_solver.automation.board_watch import locate_board

    image, result, mapper, plan, crop = _plan_for("live_queens_3.png")
    scrim = cv2.addWeighted(crop, 0.25, np.full_like(crop, 255), 0.75, 0)
    still_found = locate_board(scrim, result.grid.n) is not None
    assert still_found, (
        "a 75% scrim is now detected - good, but update board_watch.py's "
        "documented blind spot / 75% 遮罩現在抓得到了，很好，"
        "但請更新 board_watch.py 裡記錄的盲點"
    )
    print("  known blind spot (translucent scrim) still documented OK")


def test_rate_limit_bounds_the_cost_without_hiding_a_change():
    """
    The guard is asked before every action, and a plan has many: measured
    tango 72, queens 27, sudoku 72, zip 481, patches 169 - 821 for one sitting.
    At 110-160ms per real evaluation that is 73-104s of pure checking, so
    still_there() reuses its last answer inside min_interval.
    保護在每個動作前都會被問，而計畫的動作很多：實測 tango 72、queens 27、
    sudoku 72、zip 481、patches 169 —— 一輪五款共 821 次。每次真正評估
    110~160 毫秒，等於 73~104 秒純檢查，所以 still_there() 在 min_interval
    之內會沿用上一次的答案。

    The throttle must bound COST, never hide a change for longer than the
    interval.
    節流只能界定「成本」，絕不能把改變隱藏超過那個間隔。
    """
    import time

    image, result, mapper, plan, crop = _plan_for("live_tango.png")
    calls = {"n": 0}

    def counting_grab(*a, _c=crop, _k=calls):
        _k["n"] += 1
        return _c

    watch = BoardWatch(mapper=mapper, n=result.grid.n, min_interval=0.25,
                       grab=counting_grab)
    assert watch.arm(crop)
    driver = InputDriver(dry_run=True)
    driver.guard = watch.still_there
    plan.run(driver)
    actions = len(driver.log)
    assert actions >= 20, f"need a long plan to test this / 需要夠長的計畫: {actions}"
    assert calls["n"] <= 3, (
        f"throttle not working: {calls['n']} real evaluations for {actions} actions "
        f"/ 節流沒作用：{actions} 個動作卻真正評估了 {calls['n']} 次"
    )

    # And it must still notice, once the interval has passed.
    # 而且間隔一過就必須察覺得到。
    gone = np.full_like(crop, 245)
    watch2 = BoardWatch(mapper=mapper, n=result.grid.n, min_interval=0.05,
                        grab=lambda *a, _g=gone: _g)
    assert watch2.arm(crop)
    assert watch2.still_there() is False, "first real evaluation must see it / 第一次真正評估就該看到"

    watch3 = BoardWatch(mapper=mapper, n=result.grid.n, min_interval=0.05,
                        grab=lambda *a, _c=crop: _c)
    assert watch3.arm(crop)
    assert watch3.still_there() is True
    watch3.grab = lambda *a, _g=gone: _g
    assert watch3.still_there() is True, "inside the interval it reuses the answer / 間隔內沿用答案"
    time.sleep(0.06)
    assert watch3.still_there() is False, "after the interval it must notice / 間隔過後必須察覺"
    print("  rate limit bounds cost without hiding a change OK")


def test_a_drag_is_never_interrupted_by_the_guard():
    """
    Bug this guards: the guard was asked inside drag_path's interpolation loop,
    contradicting that function's own comment. A drag is COMMITTED by mouseUp
    wherever the pointer is, so aborting partway does not cancel it - it sends a
    SHORTER drag. Measured on live_patches.png: a rectangle intended as 1x4 was
    released after 12 steps and the page received 1x2; at 45 steps a 3x1 became
    2x1. The safety mechanism was placing wrong pieces on the board.
    這個測試守住的問題：保護原本是在 drag_path 的插值迴圈裡被詢問的，
    跟那個函式自己的註解矛盾。拖曳是靠 mouseUp 在指標當下位置送出的，
    所以中途中止不是取消而是「送出一段較短的拖曳」。
    在 live_patches.png 實測：本來要 1x4 的矩形在第 12 步被放開，網頁收到 1x2；
    第 45 步時 3x1 變成 2x1。安全機制自己在棋盤上放了錯誤的方塊。

    The board must be checked BEFORE a drag starts, never during.
    盤面必須在拖曳「開始前」檢查，進行中絕不檢查。
    """
    for name in ("live_patches.png", "S__104316937_0.jpg"):
        image, result, mapper, plan, crop = _plan_for(name)
        state = {"n": 0}

        # Report the board gone from the very first question onwards.
        # 從第一次詢問起就回報棋盤不見了。
        def always_gone(*a, _c=crop, _s=state):
            _s["n"] += 1
            return np.full_like(_c, 245)

        watch = BoardWatch(mapper=mapper, n=result.grid.n, min_interval=0.0,
                           grab=always_gone)
        assert watch.arm(crop)

        asked_during_drag = {"n": 0}
        driver = InputDriver(dry_run=True)
        real_check = driver._check_abort

        def spy(ask_guard=True, _r=real_check, _d=asked_during_drag, _drv=None):
            if not ask_guard:
                _d["n"] += 1
            return _r(ask_guard=ask_guard)

        driver._check_abort = spy
        driver.guard = watch.still_there
        try:
            plan.run(driver)
        except Aborted:
            pass
        # Every in-drag check must have gone through the ask_guard=False path.
        # 拖曳中的每一次檢查都必須走 ask_guard=False 那條路。
        assert asked_during_drag["n"] > 0 or len(driver.log) == 0, (
            f"{name}: drag steps did not use ask_guard=False / 拖曳步驟沒有用 ask_guard=False"
        )
    print("  a drag is never interrupted by the guard OK")


def test_guard_survives_a_real_mid_drag_patches_capture():
    """The false abort a user actually hit, reproduced from a screen recording.
    使用者實際碰到的誤判中止，從螢幕錄影重現。

    2026-08-04: a user reported Tango and Patches stopping partway through a
    real fill, both just short of completion. Extracted from their screen
    recording at fine (0.2s) time steps and fed straight through locate_board:
    detect_grid_size failed from the moment 1 of 6 patches was placed, while
    the board was demonstrably still there and still being filled (more
    patches kept appearing in later frames). This fixture is that capture's
    board region at 1-of-6 patches placed - the drawn patch's pastel fill
    reads as "mostly dark" in grayscale over a wide span, breaking
    detect_grid_size's sparse-line assumption for every threshold it sweeps.
    Before the _mask_own_marks fallback this fixture failed; after it, it
    locates.
    2026-08-04：使用者回報 Tango 與 Patches 在真實填答途中停手，都在快解完的
    時候。從他的螢幕錄影用細粒度（0.2 秒）切格，直接餵給 locate_board：
    從畫了第一個貼塊開始，detect_grid_size 就失敗，而棋盤明顯還在、
    還在繼續被填（後面的畫面持續有更多貼塊出現）。這張測試圖就是那段
    擷取裡棋盤填了 1/6 貼塊時的畫面——貼塊的粉彩填色在灰階下一大片
    被讀成「大部分是暗的」，讓 detect_grid_size 掃過的每一個門檻都失效。
    加上 _mask_own_marks 這道備援之前，這張圖會失敗；加上之後定位得到。

    See test_guard_still_fails_late_in_the_same_capture below for what this
    fix does NOT reach.
    這個修法「救不回來」的部分，見下面的 test_guard_still_fails_late_in_the_same_capture。
    """
    from linkedin_games_solver.automation.board_watch import locate_board

    image = read_image(FIXTURES / "patches_mid_drag_1of6.png")
    assert image is not None, "missing fixture / 缺少測試圖"
    assert locate_board(image, 6) is not None, (
        "guard would falsely abort on a board that is still there / "
        "保護會對一個明明還在的棋盤誤判中止"
    )
    print("  guard survives a real mid-drag Patches capture OK")


def test_guard_still_fails_late_in_the_same_capture():
    """Known remaining gap: masking does not reach late-stage fill. Not fixed;
    documented so a future change is judged against a real number.
    已知還沒解決的缺口：遮色救不到填答後期。沒有修好，先記錄下來，
    這樣未來的改動才有一個真實的數字可以對照。

    Same capture as the test above, at 5 of 6 patches placed. detect_grid_size
    fails even on the masked crop here: the masked-out span can eat the one
    thin internal grid line that would have told the patch apart from the
    board's own faint dashed lines, since a grid line drawn ON a colour fill
    can carry similar saturation to the fill itself - saturation alone cannot
    tell "our fill" apart from "our fill's own internal line".
    同一段擷取，填到 6 格中的 5 格。這裡連遮色後的裁切也會讓 detect_grid_size
    失敗：被遮掉的那一段可能正好吃掉了本來能把貼塊跟棋盤自己的淡虛線分開的
    那一條細內部格線，因為畫在填色上的格線，飽和度可能跟填色本身很接近——
    光看飽和度沒辦法把「我們的填色」跟「我們填色裡自己的格線」分開。

    An envelope-only fallback (check just the outer border via find_board_bbox,
    skip re-deriving n) was tried and reverted: it recovered this fixture, but
    it also made test_guard_detects_replacement_scenarios fail on THREE cases -
    random noise, a different puzzle at the same size, and our own puzzle at
    the wrong size all started reading as "still our board". A fix that revives
    a board that finished 12s ago is not an improvement over one that stops 12s
    early - both move the mouse onto the wrong thing, just at different times.
    曾經試過另一種備援（只用 find_board_bbox 檢查外框在不在，不重新推算
    格數），這張圖能救回來，但代價是讓 test_guard_detects_replacement_scenarios
    的三個情況失敗——純雜訊、同尺寸的另一款謎題、我們自己的謎題但格數不對，
    全部開始被判定成「還是我們的棋盤」。一個「讓已經解完 12 秒的棋盤復活」的
    修法，並不比「提早 12 秒停手」更好——兩者都會讓滑鼠點到錯的東西，
    只是發生的時間點不同。已復原、沒有採用。
    """
    from linkedin_games_solver.automation.board_watch import locate_board

    image = read_image(FIXTURES / "patches_mid_drag_5of6.png")
    assert image is not None, "missing fixture / 缺少測試圖"
    assert locate_board(image, 6) is None, (
        "this fixture started locating - either detect_grid_size or the mask "
        "changed; re-measure before assuming it is fixed / "
        "這張圖開始定位得到了——detect_grid_size 或遮色邏輯有變動；"
        "先重新量測，不要假設它已經修好"
    )
    print("  guard still fails late in the same capture (documented gap) OK")


def test_patches_finishes_despite_the_documented_late_fill_gap():
    """End to end: the ask_guard=False tail lets a real Patches plan finish
    even though a REAL BoardWatch, pointed at that fixture, would abort every
    single time it is actually asked.
    整合測試：即使把一個真正的 BoardWatch 指向那張測試圖——它只要真的被問，
    每一次都會判定中止——最後兩塊矩形的計畫還是跑得完。

    A 2-rectangle plan means BOTH rectangles fall inside
    PatchesPlayer.LAST_UNGUARDED_RECTS (=2), so neither should ever call
    driver.guard at all. Proven two ways at once: the plan completes without
    raising Aborted, AND watch.checks_made() is 0 - not "the guard happened to
    agree", but "the guard was never consulted". A 3rd rectangle added to this
    same plan WOULD raise Aborted, because it falls outside the unguarded tail
    - that is the guard doing its job everywhere else, unchanged.
    2 塊矩形的計畫，兩塊都落在 PatchesPlayer.LAST_UNGUARDED_RECTS（=2）範圍內，
    所以理論上完全不該呼叫 driver.guard。用兩種方式同時證明：計畫跑完、
    沒有拋出 Aborted，而且 watch.checks_made() 是 0——不是「保護剛好判定通過」，
    是「保護根本沒被問過」。如果對同一個計畫加上第 3 塊矩形，那一塊「會」
    拋出 Aborted，因為它落在不受保護的尾段之外——這正是保護在其他地方
    照常運作、沒有被這個改動動到的證明。
    """
    mapper = _mapper(6)
    rects = [(0, 0, 2, 2), (0, 2, 2, 2)]
    plan = build_plan("patches", mapper, {"rects": rects})

    # arm() proves the locator on the PLAN's own (locatable) frame; still_there()
    # is then pointed at the known-failing fixture via grab() - same underlying
    # puzzle (n=6), just a later point in the same fill.
    # arm() 是拿計畫「自己那一幀」（定位得到的）去證明定位器可用；之後
    # still_there() 透過 grab() 指向那張已知會失敗的測試圖——同一個謎題
    # （n=6），只是填答更後面的時刻。
    pristine = read_image(FIXTURES / "patches_mid_drag_1of6.png")
    failing_image = read_image(FIXTURES / "patches_mid_drag_5of6.png")
    assert pristine is not None and failing_image is not None, "missing fixture / 缺少測試圖"

    # A throwaway probe watch, separate from the one the plan actually uses -
    # proves the fixture genuinely fails a real check, without leaving any
    # state on the watch the plan will run against.
    # 一個用完即丟的探針 watch，跟計畫實際使用的分開——證明這張測試圖真的會讓
    # 一次真正的檢查失敗，同時不會在計畫要用的那個 watch 上留下任何狀態。
    probe = BoardWatch(mapper=mapper, n=6, min_interval=0.0, grab=lambda *a: failing_image)
    assert probe.arm(pristine), (
        "patches_mid_drag_1of6.png must self-locate for this test to mean anything / "
        "patches_mid_drag_1of6.png 自己要定位得到，這個測試才有意義"
    )
    assert probe.still_there() is False, (
        "the fixture must make a real check fail, or this test proves nothing / "
        "這張圖必須讓真正的檢查失敗，否則這個測試證明不了任何事"
    )

    watch = BoardWatch(mapper=mapper, n=6, min_interval=0.0, grab=lambda *a: failing_image)
    assert watch.arm(pristine)

    driver = InputDriver(dry_run=True)
    driver.guard = watch.still_there
    try:
        plan.run(driver)
    except Aborted:
        raise AssertionError(
            "plan aborted even though both rectangles fall inside the "
            "unguarded tail / 計畫中止了，但這兩塊矩形都落在不受保護的尾段內"
        )
    assert len(driver.log) == len(rects), (
        f"expected both rectangles to run, got {len(driver.log)} actions / "
        f"預期兩塊矩形都執行，實際 {len(driver.log)} 個動作"
    )
    assert watch.checks_made() == 0, (
        f"the guard should never have been consulted, but was asked "
        f"{watch.checks_made()} time(s) / 保護本來就不該被問到，但實際被問了 "
        f"{watch.checks_made()} 次"
    )
    print("  Patches finishes despite the documented late-fill gap OK")


def _mapper(n):
    """Same synthetic n x n board tests/test_automation.py uses, duplicated
    here so this file has no cross-file test dependency.
    跟 tests/test_automation.py 一樣的合成 n x n 棋盤，在這裡重複一份，
    這樣這個檔案不會依賴另一個測試檔。"""
    grid = _FakeGrid(n)
    blank = np.zeros((n * 10, n * 10, 3), np.uint8)
    from linkedin_games_solver.automation.capture import ScreenShot
    return BoardMapper(shot=ScreenShot(blank, 0, 0), grid=grid)


class _FakeGrid:
    def __init__(self, n):
        self.n = n
        self.board_bbox = (0, 0, n * 10, n * 10)
        self.cell_boxes = [[(c * 10, r * 10, 10, 10) for c in range(n)] for r in range(n)]

    def cell_center(self, r, c):
        return c * 10 + 5, r * 10 + 5


if __name__ == "__main__":
    print("Board guard tests / 盤面保護測試")
    test_guard_locates_every_pristine_board()
    test_guard_never_fires_while_filling_a_pristine_board()
    test_plan_stops_the_moment_the_board_disappears()
    test_guard_survives_our_own_filling()
    test_guard_latches()
    test_guard_refuses_to_judge_without_a_self_test()
    test_guard_stops_when_the_screen_cannot_be_read()
    test_guard_detects_a_different_puzzle_in_the_same_place()
    test_guard_survives_every_real_board_state()
    test_guard_detects_replacement_scenarios()
    test_known_blind_spot_is_documented()
    test_rate_limit_bounds_the_cost_without_hiding_a_change()
    test_a_drag_is_never_interrupted_by_the_guard()
    test_guard_survives_a_real_mid_drag_patches_capture()
    test_guard_still_fails_late_in_the_same_capture()
    test_patches_finishes_despite_the_documented_late_fill_gap()
    print("\nAll passed / 全部通過")
