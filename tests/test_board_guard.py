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
        watch = BoardWatch(mapper=mapper, n=result.grid.n, grab=lambda *a, _c=crop: _c)
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
        watch = BoardWatch(mapper=mapper, n=result.grid.n, grab=lambda *a, _c=crop: _c)
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

        watch = BoardWatch(mapper=mapper, n=result.grid.n, grab=grab)
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
        watch = BoardWatch(mapper=mapper, n=n, grab=lambda *a, _p=painted: _p)
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

    watch = BoardWatch(mapper=mapper, n=result.grid.n, grab=flaky)
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
    watch = BoardWatch(mapper=mapper, n=result.grid.n,
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

    watch = BoardWatch(mapper=mapper, n=result.grid.n, grab=explode)
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
    watch = BoardWatch(mapper=mapper, n=result.grid.n, grab=lambda *a, _o=other: _o)
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
    print("\nAll passed / 全部通過")
