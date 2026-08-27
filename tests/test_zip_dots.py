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

    # Hide FIVE single-digit numbers, not four. 2026-08-27 加入第三個 Patches
    # 校準來源之後 (見 tools/calibrate_digits.py 的 BROWSER_PATCHES_GIVENS_2)，
    # 這張圖上原本讀不出來的「8」(位於 (5,1)) 現在能正確讀出來了 —— 範本變準是
    # 好事，但這個測試原本悄悄依賴著那個辨識缺口：真正的 find_dots() 留下
    # 恰好一個 unread，加上這裡刻意藏起的四個，合計五個讀不出來的圓點，才會
    # 觸發下面的「太多可能編號」。範本一旦補齊該缺口，unread 變成空字典，只藏
    # 四個就不夠模稜兩可了 —— _resolve_unread 反而能唯一推出答案（這是
    # 2026-08-27 測試回歸時實測到的：resolved 不再是 None）。
    # 修法：不要依賴「這張圖剛好有一個讀不出來的圓點」這種會隨辨識準確度變動
    # 的巧合，改成連同這一個也一起明確藏起來 —— 藏五個位數不大的數字，
    # 效果與從前完全一樣（同樣落入 _MAX_ASSIGNMENTS 的「太多種」拒答分支），
    # 但不再受未來範本品質改善影響。
    #
    # Hiding five single-digit numbers instead of four. Before the 2026-08-27
    # calibration source was added (see tools/calibrate_digits.py's
    # BROWSER_PATCHES_GIVENS_2), the real find_dots() on this image happened to
    # leave exactly one dot ("8" at (5,1)) genuinely unread, which combined
    # with the four hidden here to trip the "too many possible numberings"
    # refusal below. Once the templates got better at reading real digits,
    # that incidental gap closed and find_dots() left nothing unread - so
    # hiding only four was no longer ambiguous enough, and _resolve_unread()
    # deduced a full, unique answer instead of refusing (caught by this test
    # actually failing after the 2026-08-27 template regen). Fixed by hiding
    # the fifth dot explicitly instead of relying on this fixture happening to
    # have an unreadable digit - same effect (still lands in the same
    # _MAX_ASSIGNMENTS "too many" branch), but no longer coupled to how good
    # digit recognition happens to be.
    hide = [p for p, v in sorted(dots.items(), key=lambda kv: kv[1]) if v < 10][:5]
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


#: Hand-read from tests/fixtures/live_zip_browser_2.png (originally
#: training-data/img/calibration_candidates/zip_raw_1787401245336.png,
#: auto-harvested on a real successful solve). Cross-checked against
#: find_dots()'s own auto-detected positions - every disc matched by eye
#: except (1, 3), which find_dots() reported as an unread single-glyph disc
#: (see the bug this test guards, below).
#: 人工從 tests/fixtures/live_zip_browser_2.png 讀出（原始檔案是
#: training-data/img/calibration_candidates/zip_raw_1787401245336.png，
#: 一次真實成功求解時自動存下）。跟 find_dots() 自己偵測到的位置互相核對過
#: ——除了 (1, 3) 以外每一顆都跟人工讀出的一致，(1, 3) 被 find_dots() 回報成
#: 一個讀不出來、只有一個字形的圓盤（見下面這個測試守住的問題）。
LIVE_ZIP_2_TRUTH = {
    (1, 1): 4, (1, 2): 3, (1, 3): 8, (1, 6): 9,
    (2, 1): 5, (2, 2): 6, (2, 5): 7,
    (3, 1): 1, (4, 6): 2,
    (5, 2): 12, (5, 5): 13, (5, 6): 10,
    (6, 1): 16, (6, 4): 15, (6, 5): 14, (6, 6): 11,
}


def test_live_zip_browser_2_reads_the_eight():
    """
    Bug this guards: before 2026-08-27, Zip had NO dedicated calibration
    source at all - every Zip digit template was borrowed from Sudoku (1-6),
    Patches (0-9) and system fonts (0, 7), never checked against Zip's own
    widget rendering. Measured directly on this real capture before the fix:
    the "8" at (1, 3) scored 0.9845 against those borrowed templates, but
    runner-up "6" scored 0.9659 - a margin of 0.0186, under MIN_MARGIN
    (0.020). classify_glyph correctly refused to guess (find_dots() reported
    it as an unread, single-glyph disc) - the exact same failure shape as
    BROWSER_PATCHES_GIVENS's "8 vs 6" case on 2026-08-25, just on Zip's own
    widget instead of Patches'. This sat undetected in training-data/ the
    whole time because nobody had run find_dots() against these real captures
    before - Zip's one recorded real-world incident (2026-08-16) was a slow
    retry that still finished correctly, never a hard misread, so nothing
    forced the gap into the open.
    這個測試守住的問題：在 2026-08-27 之前，Zip 完全沒有專屬的校準來源——
    它的每一個數字範本，全部是跟 Sudoku（1-6）、Patches（0-9）、系統字型
    （0、7）借來的，從來沒有用 Zip 自己元件畫出來的數字驗證過。修正前直接在
    這張真實截圖上量過：(1, 3) 的「8」對這些借來的範本只拿到 0.9845 分，
    第二名「6」拿到 0.9659 分——差距 0.0186，不到 MIN_MARGIN（0.020）。
    classify_glyph 正確地拒絕用猜的（find_dots() 把它回報成讀不出來、只有
    一個字形的圓盤）——跟 2026-08-25 BROWSER_PATCHES_GIVENS 那次「8 對 6」
    完全同一種失敗形狀，只是這次是 Zip 自己的元件，不是 Patches 的。這個
    缺口一直沒被發現，純粹是因為在這之前沒有人拿這些真實截圖真的跑過
    find_dots()——Zip 唯一一次留下記錄的真實事故（2026-08-16）只是重試
    多花了時間、最後答案還是對的，從來不是真的讀錯，所以沒有任何事情逼著
    這個缺口浮上檯面。

    Fixed by adding Zip's first dedicated calibration source
    (tools/calibrate_digits.py's ZIP_SOURCES, three real boards) and
    regenerating core/digit_templates.py from it.
    修法：在 tools/calibrate_digits.py 加入 Zip 第一個專屬校準來源
    （ZIP_SOURCES，三張真實棋盤），並用它重新產生 core/digit_templates.py。
    """
    image = read_image(FIXTURES / "live_zip_browser_2.png")
    grid = build_grid(image)
    dots, unread = zip_path.find_dots(image, grid)
    assert dots == LIVE_ZIP_2_TRUTH, dots
    assert not unread, f"still unreadable / 仍然讀不出來: {unread}"
    print("  live zip browser 2 reads the eight OK")


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
    test_live_zip_browser_2_reads_the_eight()
    test_other_zip_fixtures_still_read()
    print("\nAll passed / 全部通過")
