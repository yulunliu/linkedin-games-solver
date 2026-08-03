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


def test_wrong_type_does_not_fake_success():
    """Forcing the wrong type must fail loudly, not invent an answer.
    指定錯誤的類型必須明確失敗，不能編一個答案出來。"""
    result = solve_image(_load("live_queens_3.png"), puzzle_key="patches")
    assert not result.ok, "should not report success / 不該回報成功"
    print("  wrong type does not fake success OK")


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


if __name__ == "__main__":
    print("Recognition tests / 辨識測試")
    test_puzzle_type_detection()
    test_all_five_puzzles_solve()
    test_live_queens_boards()
    test_live_tango_matches_screen()
    test_live_patches_with_blank_labels()
    test_wrong_type_does_not_fake_success()
    test_stops_when_board_changes()
    test_board_position_survives_the_working_size_cap()
    print("\nAll passed / 全部通過")
