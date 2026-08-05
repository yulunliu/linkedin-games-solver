"""
用「從實際網頁擷取下來的畫面」做迴歸測試。

這些圖是實際使用時擷取或從錄影抽出的真實畫面，每一張都對應過一個實際遇到的
辨識失敗，修好之後放進來，避免之後改動又壞掉。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import solver_bridge  # noqa: E402
from solve_puzzle import solve_from_image  # noqa: E402

sys.path.insert(0, str(solver_bridge.solver_dir()))
import puzzle_patches as pp  # noqa: E402
from img_io import imread_unicode  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures"


def _load(name):
    image = imread_unicode(FIXTURES / name)
    assert image is not None, f"讀不到 {name}"
    return image


def check_patches_tiling(labels, rects, n):
    covered = {}
    for label, (r0, c0, height, width) in zip(labels, rects):
        if label.value is not None:
            assert height * width == label.value, f"面積 {height*width} 與數字 {label.value} 不符"
        assert pp._shape_allowed(label.shape, height, width), "形狀不符"
        assert r0 <= label.row < r0 + height and c0 <= label.col < c0 + width, "標籤不在自己的矩形內"
        for r in range(r0, r0 + height):
            for c in range(c0, c0 + width):
                assert (r, c) not in covered, f"格子 {(r,c)} 被重複覆蓋"
                covered[(r, c)] = True
    assert len(covered) == n * n, f"只覆蓋了 {len(covered)}/{n*n} 格"


def test_live_patches_with_blank_labels():
    """
    實際遇到的失敗：7x7 盤面、14 個標籤，其中 7 個沒有數字。

    舊的字形切割會把虛線標籤的白色縫隙當成數字筆畫，
    有 2 個標籤被切出 3~4 個碎片而判定「數字讀不出來」，整個辨識中斷。
    """
    outcome = solve_from_image(_load("live_patches.png"))
    assert outcome.ok, f"應該要能解出來，實際錯誤: {outcome.error}"
    assert outcome.puzzle_key == "patches"

    labels = outcome.data["labels"]
    assert len(labels) == 14, f"應該有 14 個標籤，實際 {len(labels)}"

    numbered = sorted(lb.value for lb in labels if lb.value is not None)
    assert numbered == [2, 2, 2, 4, 4, 4, 4], f"數字應為 2,2,2,4,4,4,4 實際 {numbered}"
    assert sum(1 for lb in labels if lb.value is None) == 7, "應該有 7 個沒有數字的標籤"

    check_patches_tiling(labels, outcome.data["rects"], outcome.grid.n)
    print(f"  live_patches: 7x7、14 標籤 (7 個無數字)，切法覆蓋 49 格且完全符合規則")


def test_live_tango():
    """實際網頁的 Tango：棋盤沒有外框，要用格線定位才不會整個偏一格。"""
    outcome = solve_from_image(_load("live_tango.png"))
    assert outcome.ok, f"應該要能解出來，實際錯誤: {outcome.error}"
    assert outcome.puzzle_key == "tango"

    solution = outcome.data["solution"]
    n = len(solution)
    # 畫面上實際的 given (人工核對過)
    truth = {(0, 2): 1, (0, 3): 1, (1, 1): 1, (1, 4): 0, (4, 1): 1, (4, 4): 1, (5, 2): 0, (5, 3): 1}
    assert set(outcome.data["givens"]) == set(truth), "given 位置與畫面不符"
    for (r, c), v in truth.items():
        assert solution[r][c] == v, f"given ({r+1},{c+1}) 的值不符"

    for r in range(n):
        assert sum(solution[r]) == n // 2, f"第 {r+1} 列數量不對"
    for c in range(n):
        assert sum(solution[r][c] for r in range(n)) == n // 2, f"第 {c+1} 行數量不對"
    for r in range(n):
        for c in range(n - 2):
            assert len({solution[r][c], solution[r][c + 1], solution[r][c + 2]}) > 1, "有橫向三連"
    for c in range(n):
        for r in range(n - 2):
            assert len({solution[r][c], solution[r + 1][c], solution[r + 2][c]}) > 1, "有縱向三連"
    print("  live_tango: 6x6、8 個 given 與畫面相符，解通過所有規則")


def test_live_queens_variants():
    """實際網頁的 Queens：配色比手機版接近，且盤面可能已經放了皇冠。"""
    import queens_ext

    for name in ("live_queens_region.png", "live_queens_2.png", "live_queens_with_crowns.png"):
        image = _load(name)
        outcome = solve_from_image(image)
        assert outcome.ok, f"{name} 應該要能解出來，實際錯誤: {outcome.error}"
        n = outcome.grid.n
        queens = outcome.data["queens"]

        regions, _ = queens_ext.read_regions(image, outcome.grid)
        assert queens_ext.regions_look_valid(regions, n), f"{name} 色塊分群不合理"
        assert sorted(r for r, _ in queens) == list(range(n)), f"{name} 每列沒有恰好一個"
        assert sorted(c for _, c in queens) == list(range(n)), f"{name} 每欄沒有恰好一個"
        assert len({regions[r][c] for r, c in queens}) == n, f"{name} 每個色塊沒有恰好一個"
        for i, a in enumerate(queens):
            for b in queens[i + 1 :]:
                assert max(abs(a[0] - b[0]), abs(a[1] - b[1])) > 1, f"{name} 有皇后相鄰"
        print(f"  {name}: {n}x{n} 解通過所有規則")


def test_puzzle_type_detection():
    """
    謎題類型判斷。實際遇到的失敗：淡色系的 Queens 盤面 (大量淺灰、米色)
    彩度太低，被誤判成 Patches，然後「解」出一個把整個盤面用一塊矩形蓋住的
    無意義答案卻回報成功。
    """
    import puzzle_type

    cases = [
        ("live_queens_3.png", "queens"),      # 淡色系 Queens (曾被誤判成 patches)
        ("live_queens_region.png", "queens"),
        ("live_queens_2.png", "queens"),
        ("live_queens_with_crowns.png", "queens"),
        ("live_tango.png", "tango"),          # 曾被誤判成 patches
        ("live_patches.png", "patches"),
    ]
    for name, expected in cases:
        got = puzzle_type.detect_type(_load(name))
        assert got == expected, f"{name} 應判定為 {expected}，實際 {got}"

    samples = solver_bridge.solver_dir() / "samples"
    for name, expected in [
        ("S__104316934_0.jpg", "queens"),
        ("S__104316931.jpg", "tango"),
        ("S__104316935_0.jpg", "sudoku"),
        ("S__104316936_0.jpg", "patches"),
        ("S__104316937_0.jpg", "zip"),
        ("puzzle_answer.png", "tango"),  # 全部填滿的 Tango 不能被誤判成 Queens
    ]:
        got = puzzle_type.detect_type(imread_unicode(samples / name))
        assert got == expected, f"{name} 應判定為 {expected}，實際 {got}"
    print("  謎題類型判斷: 13 種情境全部正確")


def test_wrong_type_does_not_fake_success():
    """
    就算謎題類型被指定錯，也不能吐出一個看似成功的假答案。
    (先前把 Queens 當 Patches 解，會產生「用一塊 9x9 矩形蓋滿全盤」的結果。)
    """
    outcome = solve_from_image(_load("live_queens_3.png"), puzzle_key="patches")
    assert not outcome.ok, "類型錯誤時不該回報成功"
    assert "標籤" in (outcome.error or ""), f"錯誤訊息應說明標籤太少，實際: {outcome.error}"
    print("  類型指定錯誤時正確回報失敗，不會給出假答案")


def test_live_queens_pastel():
    """淡色系 Queens 盤面 (實際遇到的失敗案例)。"""
    import queens_ext

    image = _load("live_queens_3.png")
    outcome = solve_from_image(image)
    assert outcome.ok, f"應該要能解出來，實際錯誤: {outcome.error}"
    assert outcome.puzzle_key == "queens", f"應判定為 queens，實際 {outcome.puzzle_key}"

    n = outcome.grid.n
    assert n == 9, f"應為 9x9，實際 {n}"
    queens = outcome.data["queens"]
    regions, _ = queens_ext.read_regions(image, outcome.grid)
    assert queens_ext.regions_look_valid(regions, n), "色塊分群不合理"
    assert sorted(r for r, _ in queens) == list(range(n)), "每列沒有恰好一個"
    assert sorted(c for _, c in queens) == list(range(n)), "每欄沒有恰好一個"
    assert len({regions[r][c] for r, c in queens}) == n, "每個色塊沒有恰好一個"
    for i, a in enumerate(queens):
        for b in queens[i + 1 :]:
            assert max(abs(a[0] - b[0]), abs(a[1] - b[1])) > 1, "有皇后相鄰"
    print(f"  live_queens_3 (淡色系): 9x9 解通過所有規則")


def test_stops_when_board_changed():
    """
    解完之後網頁會跳出完成畫面、盤面外觀整個變掉。
    這時如果還照常「驗證 -> 補點」，就會因為讀不到皇冠而繼續亂點滑鼠。
    必須偵測到「已經不是原本那盤棋」並停手。
    """
    import cv2
    import numpy as np

    from board_mapper import BoardMapper
    from capture import ScreenShot
    from verify import build_retry_plan, verify

    image = _load("live_queens_3.png")
    outcome = solve_from_image(image)
    assert outcome.ok and outcome.puzzle_key == "queens"
    mapper = BoardMapper(shot=ScreenShot(image=image, origin_x=0, origin_y=0), grid=outcome.grid)

    # 盤面沒變 -> 應該正常補點
    same = verify(image, outcome)
    assert not same.board_changed, "盤面沒變卻被判定成已改變"
    assert build_retry_plan(outcome, mapper, same) is not None, "盤面沒變時應該要能補點"

    # 完成畫面：盤面被蓋掉 -> 必須停手
    done = image.copy()
    x, y, w, h = outcome.grid.board_bbox
    cv2.rectangle(done, (x, y), (x + w, y + h), (245, 245, 245), -1)
    changed = verify(done, outcome)
    assert changed.board_changed, "盤面被蓋掉時應判定成已改變"
    assert build_retry_plan(outcome, mapper, changed) is None, "畫面已改變時不能再補點"

    # 換成完全不同的謎題 -> 也要停手
    other = verify(_load("live_patches.png"), outcome)
    assert other.board_changed, "換成別的謎題時應判定成已改變"
    assert build_retry_plan(outcome, mapper, other) is None, "畫面已改變時不能再補點"

    # 只是放上皇冠 -> 盤面沒變，不能誤判
    with_crowns = _load("live_queens_with_crowns.png")
    outcome2 = solve_from_image(with_crowns)
    report = verify(with_crowns, outcome2)
    assert not report.board_changed, "只是放了皇冠不該被判定成畫面改變"
    print("  完成畫面/換盤面時正確停手，放皇冠不會誤判")


if __name__ == "__main__":
    print("真實網頁畫面迴歸測試")
    test_puzzle_type_detection()
    test_stops_when_board_changed()
    test_wrong_type_does_not_fake_success()
    test_live_patches_with_blank_labels()
    test_live_tango()
    test_live_queens_variants()
    test_live_queens_pastel()
    print("\n全部通過。")
