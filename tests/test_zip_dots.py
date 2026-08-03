"""
Zip dot reading: detection, extraction, and the refusal to guess.
Zip 圓點辨識：偵測、抽取，以及「拒絕猜測」。

Ground truth for img/capture.png was read off the image BY EYE, not produced by
the recogniser. A test that asserts what the code currently outputs proves
nothing.
img/capture.png 的真值是**人工看著圖讀出來的**，不是辨識器產生的。
一個「驗證程式目前輸出」的測試什麼也證明不了。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from linkedin_games_solver.core import build_grid, read_image  # noqa: E402
from linkedin_games_solver.puzzles import solve_image, zip_path  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures"

#: Hand-read from img/capture.png. Twelve dots, 1..12, on a 6x6 board.
#: 人工從 img/capture.png 讀出。6x6 盤面上 12 個圓點，編號 1~12。
CAPTURE_TRUTH = {
    (0, 1): 9, (0, 4): 2,
    (1, 1): 10, (1, 2): 1, (1, 3): 12, (1, 4): 11,
    (4, 1): 6, (4, 2): 7, (4, 3): 4, (4, 4): 5,
    (5, 1): 8, (5, 4): 3,
}
CAPTURE = ROOT / "img" / "capture.png"


def _skip_if_missing():
    if not CAPTURE.exists():
        print("  (img/capture.png not present, skipped / 沒有這張圖，略過)")
        return True
    return False


def test_every_disc_is_detected():
    """
    Bug this guards: _looks_like_dot measured the RAW dark area of the disc,
    which varies with how much white ink the printed number uses - measured
    0.5972 for "10" (two digits plus a counter) against 0.7407 for "1". The 0.60
    floor sat inside that spread and silently threw the "10" disc away, so one
    of twelve dots was never detected at all.
    這個測試守住的問題：_looks_like_dot 量的是圓盤的「原始深色面積」，
    而那個值會隨著印上去的數字佔掉多少白色而變 —— 實測「10」（兩位數又有內孔）
    是 0.5972，「1」是 0.7407。0.60 的下限正好落在這個範圍裡，
    把「10」那顆圓盤默默丟掉，於是 12 個圓點裡有一個從頭到尾沒被偵測到。

    Solidity with the number filled back in does not depend on the number:
    measured 0.7785..0.8002, centred on a circle's pi/4 = 0.785.
    把數字填回去之後的實心度與數字無關：實測 0.7785~0.8002，
    以圓形的 pi/4 = 0.785 為中心。
    """
    if _skip_if_missing():
        return
    image = read_image(CAPTURE)
    grid = build_grid(image)
    dots, unread = zip_path.find_dots(image, grid)
    found = set(dots) | set(unread)
    missing = sorted(set(CAPTURE_TRUTH) - found)
    assert not missing, f"discs never detected at / 完全沒偵測到圓盤的位置: {missing}"
    assert len(found) == len(CAPTURE_TRUTH), \
        f"found {len(found)} discs, expected {len(CAPTURE_TRUTH)} / 偵測到的圓盤數不符"
    print(f"  all {len(CAPTURE_TRUTH)} discs detected OK")


def test_read_numbers_are_never_wrong():
    """
    Bug this guards: _enclosed_holes returned the digit with its own counters
    filled in, because a counter is a SEPARATE dark component the flood fill
    cannot reach. The "0" of "10" then had a WRONG top-1 - it read as 9 with a
    margin of 0.0001, i.e. only the margin gate stood between that glyph and a
    silent misread.
    這個測試守住的問題：_enclosed_holes 交回的數字，內孔被填實了 ——
    因為內孔是「另一個」深色元件，灌水碰不到。「10」的那個「0」因此第一名是錯的：
    讀成 9、差距 0.0001，也就是只剩差距檢查擋在那個字形與一次無聲誤讀之間。

    Anything actually read must be right. Unreadable is acceptable; wrong is not.
    真的有讀出來的就必須是對的。讀不出來可以接受，讀錯不行。
    """
    if _skip_if_missing():
        return
    image = read_image(CAPTURE)
    grid = build_grid(image)
    dots, _ = zip_path.find_dots(image, grid)
    wrong = {pos: (got, CAPTURE_TRUTH.get(pos)) for pos, got in dots.items()
             if CAPTURE_TRUTH.get(pos) != got}
    assert not wrong, f"misread / 讀錯: {wrong}"
    print(f"  {len(dots)} numbers read, none wrong OK")


def test_capture_solves_with_the_correct_path():
    """End to end on the board that used to fail. Every dot must match the
    hand-read truth and the path must obey the rules.
    對原本失敗的那個盤面做端到端驗證。每個圓點都要符合人工真值，
    路徑也要符合規則。"""
    if _skip_if_missing():
        return
    result = solve_image(read_image(CAPTURE))
    assert result.ok, f"still fails / 仍然失敗: {(result.error or '').split(' / ')[0]}"

    dots = result.data["dots"]
    assert dots == CAPTURE_TRUTH, f"dots differ from the hand-read truth / 與人工真值不符: {dots}"

    n = result.grid.n
    path = result.data["path"]
    assert len(path) == n * n and len(set(path)) == n * n, "must cover every cell once / 必須每格恰好一次"
    for a, b in zip(path, path[1:]):
        assert abs(a[0] - b[0]) + abs(a[1] - b[1]) == 1, "steps must be adjacent / 每步必須相鄰"
    order = {cell: i for i, cell in enumerate(path)}
    by_number = [order[pos] for pos, _ in sorted(dots.items(), key=lambda kv: kv[1])]
    assert by_number == sorted(by_number), "dots must be visited in number order / 必須依編號順序"
    print("  capture.png solves with the correct path OK")


def test_prefix_of_numbers_is_rejected():
    """
    Bug this guards: the consecutive-number test passes on any PREFIX. Twelve
    discs of which only 1..8 could be read looked exactly like an eight-dot
    puzzle, so the solver returned a full path visiting the unread dots in the
    wrong order - a wrong route dragged with the real mouse, reported as success.
    Measured before the fix: img/capture.png at 0.70x returned ok=True with dots
    11 and 12 out of order, 3 of 3 runs.
    這個測試守住的問題：連續性檢查對任何「前綴」都會通過。12 個圓盤只讀出 1~8，
    看起來就跟一題 8 點的謎題一模一樣，求解器於是給出一條把沒讀到的點走錯順序的
    完整路徑 —— 一條錯誤路線被真實滑鼠拖出去，而且回報成功。
    修正前實測：img/capture.png 在 0.70x 回傳 ok=True 且 11、12 順序顛倒，3/3 次重現。
    """
    if _skip_if_missing():
        return
    image = read_image(CAPTURE)
    real_find = zip_path.find_dots

    def only_a_prefix(img, g):
        dots, unread = real_find(img, g)
        keep = {p: v for p, v in dots.items() if v <= 8}
        dropped = {p: 1 for p in dots if p not in keep}
        dropped.update(unread)
        return keep, dropped

    zip_path.find_dots = only_a_prefix
    try:
        result = zip_path.solve(image)
    finally:
        zip_path.find_dots = real_find
    assert not result.ok, "a prefix reading was accepted / 只讀到前綴卻被接受了"
    print("  a prefix of the numbers is rejected OK")


def test_refuses_to_guess_when_more_than_one_numbering_works():
    """
    Deduction is allowed; guessing is not. When two numberings both fit the
    digit counts AND both give a valid path, the answer is not determined and
    the only correct output is a loud failure.
    推論可以，猜測不行。當兩種編號都符合位數、而且都走得出合法路徑時，
    答案並未被決定，唯一正確的輸出就是明確失敗。
    """
    if _skip_if_missing():
        return
    image = read_image(CAPTURE)
    grid = build_grid(image)
    dots, unread = zip_path.find_dots(image, grid)
    h_walls, v_walls = zip_path.find_walls(image, grid)

    # Hide four single-digit numbers. Their digit counts no longer distinguish
    # them, so several numberings fit and more than one is walkable.
    # 藏起四個個位數。位數不再能區分它們，於是有多種編號成立，
    # 而且不只一種走得出路徑。
    hide = [p for p, v in sorted(dots.items(), key=lambda kv: kv[1]) if v < 10][:4]
    thin = {p: v for p, v in dots.items() if p not in hide}
    blind = dict(unread)
    blind.update({p: 1 for p in hide})

    resolved, note = zip_path._resolve_unread(thin, blind, grid.n, h_walls, v_walls)
    assert resolved is None, f"guessed an answer / 猜了一個答案出來: {note}"
    assert "refusing to guess" in note or "不做猜測" in note or "too many" in note or "太多" in note
    print("  refuses to guess when the numbering is not determined OK")


def test_deduction_matches_the_hand_read_truth():
    """When it does deduce, the deduction must be right - checked against the
    numbers a human read off the image.
    真的做出推論時，推論必須是對的 —— 用人工從圖上讀出的號碼核對。"""
    if _skip_if_missing():
        return
    image = read_image(CAPTURE)
    grid = build_grid(image)
    dots, unread = zip_path.find_dots(image, grid)
    if not unread:
        print("  (nothing was unreadable at this scale, skipped / 這個尺度沒有讀不出來的，略過)")
        return
    h_walls, v_walls = zip_path.find_walls(image, grid)
    resolved, note = zip_path._resolve_unread(dots, unread, grid.n, h_walls, v_walls)
    assert resolved is not None, f"could not deduce / 推不出來: {note}"
    for pos in unread:
        assert resolved[pos] == CAPTURE_TRUTH[pos], (
            f"deduced {pos} = {resolved[pos]}, truth is {CAPTURE_TRUTH[pos]} / 推錯了"
        )
    print(f"  deduced {len(unread)} number(s), all matching the truth OK")


def test_other_zip_fixtures_still_read():
    """The changes must not break the boards that already worked.
    這些改動不能弄壞本來就正常的盤面。"""
    result = solve_image(read_image(FIXTURES / "S__104316937_0.jpg"))
    assert result.ok, f"regressed / 退步了: {result.error}"
    values = sorted(result.data["dots"].values())
    assert values == list(range(1, len(values) + 1)), f"numbers not consecutive / 編號不連續: {values}"
    print(f"  S__104316937_0.jpg still reads {len(values)} dots OK")


if __name__ == "__main__":
    print("Zip dot tests / Zip 圓點測試")
    test_every_disc_is_detected()
    test_read_numbers_are_never_wrong()
    test_capture_solves_with_the_correct_path()
    test_prefix_of_numbers_is_rejected()
    test_refuses_to_guess_when_more_than_one_numbering_works()
    test_deduction_matches_the_hand_read_truth()
    test_other_zip_fixtures_still_read()
    print("\nAll passed / 全部通過")
