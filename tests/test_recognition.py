"""
Recognition tests against real captures.
用真實擷取畫面做的辨識測試。

Every fixture here corresponds to a bug that was actually hit and fixed. Keeping
them as tests stops those bugs coming back.
這裡每一張圖都對應一個實際遇到並修好的問題。留成測試可以避免它們再次發生。
"""

import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from linkedin_games_solver.core import detect_type, read_image  # noqa: E402
from linkedin_games_solver.core.detect_type import _board_roi  # noqa: E402
from linkedin_games_solver.core.digit_templates import APP_TEMPLATES  # noqa: E402
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
        ("live_mini_sudoku_browser.png", "sudoku"),
        ("S__104316934_0.jpg", "queens"),
        ("S__104316931.jpg", "tango"),
        ("S__104316935_0.jpg", "sudoku"),
        ("S__104316936_0.jpg", "patches"),
        ("S__104316937_0.jpg", "zip"),
        ("puzzle_answer.png", "tango"),           # fully filled 全部填滿
        ("zip_faint_walls_20260811.png", "zip"),  # faint walls, real near-miss 淡牆，真實的差點誤判
    ]
    for name, expected in cases:
        got = detect_type(_load(name))
        assert got == expected, f"{name}: expected {expected}, got {got}"
    print(f"  puzzle type detection: {len(cases)} cases OK")


def test_mini_sudoku_survives_extra_colour_noise():
    """
    Bug this guards: two real 2026-08-10 production runs (run_20260810_181407
    and run_20260810_185005) show detect_type guessing "tango" for a genuine
    Mini Sudoku board, which only resolved correctly several seconds later via
    the fallback sweep - costing ~6-9s per occurrence while the real board sat
    on screen the whole time (dist/logs). Measured cause: the only live
    fixture on file, live_mini_sudoku_browser.png, has a coloured ratio
    (sub-box shading) of 0.00366 against the OLD NO_COLOR_RATIO=0.006 - only a
    1.6x margin - and that colour is itself 88.7% orange/blue, so crossing the
    ratio threshold sent it straight into "tango" with no further check.
    Ordinary capture variance (zoom, monitor DPI scaling, anti-aliasing) is
    enough to cross a 1.6x margin.

    This reproduces that class of variance by synthetically colouring an
    extra ~0.34% of the image blue-ish, landing the ratio at ~0.0072 -
    ABOVE the old 0.006 threshold (would have flipped to tango) but still
    below the new NO_COLOR_RATIO=0.01. Must still resolve as sudoku.
    這個測試守住的問題：兩筆真實 2026-08-10 執行記錄（run_20260810_181407
    與 run_20260810_185005）顯示 detect_type 把一個真的 Mini Sudoku 盤面
    猜成「tango」，要等備援掃描跑完好幾秒後才解對——每次白燒 6~9 秒，
    而真正的棋盤其實整段時間都在畫面上（見 dist/logs）。量測到的原因：
    目前唯一的真實測試圖 live_mini_sudoku_browser.png，彩色比例（子九宮格
    底色）是 0.00366，對上舊門檻 NO_COLOR_RATIO=0.006 只有 1.6 倍安全邊界，
    而且那個顏色本身有 88.7% 是橘／藍，一旦跨過比例門檻就會直接被當成
    「tango」，不會再做任何檢查。一般擷取誤差（縮放、螢幕 DPI、反鋸齒）
    就足以跨過 1.6 倍邊界。

    這裡合成著色圖片裡額外約 0.34% 的像素成偏藍色，模擬那種誤差，讓比例落在
    約 0.0072——「高於」舊門檻 0.006（照舊門檻會誤判成 tango），但「低於」
    新門檻 NO_COLOR_RATIO=0.01。在新門檻下仍然必須解成 sudoku。
    """
    image = _load("live_mini_sudoku_browser.png").copy()
    h, w = image.shape[:2]
    rng = np.random.RandomState(0)
    n_pixels = int(h * w * 0.0034)
    ys = rng.randint(0, h, n_pixels)
    xs = rng.randint(0, w, n_pixels)
    image[ys, xs] = (200, 120, 60)  # BGR - saturated, blue-ish (matches the real hue mix)

    got = detect_type(image)
    assert got == "sudoku", (
        f"expected sudoku to survive ordinary capture-variance-level colour "
        f"noise, got {got}"
    )
    print("  mini sudoku survives extra colour noise: OK")


def test_a_faint_walled_zip_board_is_not_misread_as_tango():
    """
    Bug this guards: a real 2026-08-11 production run shows detect_type
    guessing "tango" for a genuine Zip board, burning a full 12-attempt tango
    ladder (all "multiple solutions" or "no solution") before a fallback-type
    sweep eventually reached zip - 5.8s wasted, which was the ENTIRE measured
    gap that day between "puzzle detected" and the first mouse action.
    Root cause, measured directly on the exact frame captured from the
    session recording at the moment solve_image first ran on it
    (zip_faint_walls_20260811.png): dark-pixel ratio 0.0494, just under the
    OLD ZIP_DARK_RATIO=0.05 - missing the Zip branch by a hair and falling
    through to the colour/hue check, where its own path (97.2% blue) reads
    as tango. Same class of fragility as
    test_mini_sudoku_survives_extra_colour_noise, a different board falling
    through a different one of detect_type's checks.
    這個測試守住的問題：一個真實的 2026-08-11 正式執行顯示 detect_type 把一個
    真的 Zip 棋盤猜成「tango」，燒完整條 12 次嘗試的 tango 階梯（全部「多組
    解」或「無解」）才靠備援類型全掃找到 zip——白燒 5.8 秒，正好是那天
    「偵測到題目」到「滑鼠第一次動作」之間量到的全部空檔。根因，直接對著
    從螢幕錄影截下來、solve_image 第一次對它出手那一刻的畫面實測
    （zip_faint_walls_20260811.png）：深色像素比例 0.0494，只比舊門檻
    ZIP_DARK_RATIO=0.05 低一點點，以毫釐之差沒進到 Zip 分支，落到彩色／
    色相檢查，它自己的路徑（97.2% 藍色）就被讀成 tango。跟
    test_mini_sudoku_survives_extra_colour_noise 是同一類脆弱，只是另一個
    棋盤從 detect_type 另一道檢查的縫隙漏過去。
    """
    image = _load("zip_faint_walls_20260811.png")
    roi = _board_roi(image)
    gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
    dark_ratio = float((gray < 90).mean())
    assert dark_ratio < 0.05, (
        f"the near-miss fixture's dark ratio is no longer below the OLD "
        f"0.05 threshold ({dark_ratio:.4f}) - this test's premise (the "
        f"fixture reproduces a real near-miss) no longer holds, re-check "
        f"against a fresh real capture / "
        f"這張差點誤判的測試圖深色比例已經不再低於舊門檻 0.05"
        f"（{dark_ratio:.4f}）——這個測試的前提（測試圖真的重現了一次真實的"
        f"差點誤判）不再成立，請對照新的真實擷取重新確認"
    )
    got = detect_type(image)
    assert got == "zip", f"expected zip, got {got}"
    print("  a faint-walled zip board is not misread as tango: OK")


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


def test_patches_splits_a_wide_merged_digit_component():
    """
    Bug this guards: see patches._split_wide_boxes' own docstring for the
    full story - core/digits.py's module docstring promises multi-digit
    Patches labels like "12" are handled by splitting a wide connected
    component, but read_label_value never actually did this until
    2026-08-26. Tests the extracted _split_wide_boxes() directly against
    plain (x, y, w, h, index) tuples rather than a real capture, because the
    behaviour is a pure geometric property (does a box wider than ~1.6x a
    normal digit's width get cut into the right number of same-height
    slices at the right x positions) that does not need - and should not
    depend on - font rendering or classify_glyph's confidence gates.
    這個測試守住的問題：完整故事見 patches._split_wide_boxes 自己的文件
    字串——core/digits.py 的模組文件字串承諾過，Patches 多位數標籤（例如
    「12」）會靠切割寬的連通元件來處理，但 read_label_value 一直到
    2026-08-26 之前都沒有真的這樣做。這裡直接對著單純的
    (x, y, w, h, index) 元組測試抽出來的 _split_wide_boxes()，不是對著
    真實擷取畫面——因為這個行為是純粹的幾何性質（一個比正常數字寬約 1.6
    倍以上的方框，會不會被切成正確片數、同樣高度、正確 x 位置的切片），
    不需要、也不應該依賴字型算繪或 classify_glyph 的信心門檻。
    """
    # A normal single digit: width roughly 0.62x its own height (the ratio
    # this whole mechanism is built around) - must NOT be split.
    # 一個正常的單一數字：寬度大約是自己高度的 0.62 倍（整個機制建立在這個
    # 比例上）——絕不能被切開。
    single = [(10, 5, 25, 40, 7)]
    assert patches._split_wide_boxes(single) == single, (
        "a normal-width digit was split / 正常寬度的數字被切開了")

    # A component roughly 2 digit-widths wide (two touching digits merged) -
    # must split into exactly 2 slices, same y/height/index, contiguous and
    # covering the original width exactly.
    # 一個大約兩個數字寬的元件（兩個黏在一起的數字）——必須剛好切成兩片，
    # y／高度／index 都相同，切片彼此相鄰且完整涵蓋原本的寬度。
    merged = [(10, 5, 50, 40, 3)]  # 50 ~= 2 * (0.62 * 40) = 49.6
    result = patches._split_wide_boxes(merged)
    assert len(result) == 2, f"expected 2 slices for a merged '12'-style box, got {len(result)} / 預期切成 2 片，得到 {len(result)}"
    (x0, y0, w0, h0, i0), (x1, y1, w1, h1, i1) = result
    assert (y0, h0, i0) == (5, 40, 3) and (y1, h1, i1) == (5, 40, 3), (
        f"y/height/index must be preserved on both slices / 兩片的 y／高度／index 都要保留: {result}")
    assert x0 == 10, f"first slice must start where the original box started / 第一片要從原本的方框起點開始: {result}"
    assert x0 + w0 == x1, f"slices must be contiguous, no gap or overlap / 切片必須相鄰，不能有縫隙或重疊: {result}"
    assert x1 + w1 == 60, f"slices must exactly cover the original width (10..60) / 切片必須完整涵蓋原本的寬度: {result}"
    print("  patches splits a wide merged digit component OK")


def test_read_label_value_actually_calls_the_wide_box_splitter():
    """
    Complements test_patches_splits_a_wide_merged_digit_component: that test
    proves the splitting MATH is correct in isolation; this one proves
    read_label_value actually WIRES IT IN, by spying on
    patches._split_wide_boxes while reading a real label from a real
    fixture. Needed because none of the project's current real fixtures
    happen to contain a genuinely merged two-digit badge (that failure mode
    is rare enough that it has never been caught on camera), so no
    end-to-end test can exercise the split producing a correct multi-digit
    read - only that the call site exists and is reached.
    補充 test_patches_splits_a_wide_merged_digit_component：那個測試證明
    切割的「數學」本身在單獨測試下是對的；這個測試證明 read_label_value
    真的有「接上」它——做法是在讀取一張真實測試圖的真實標籤時，
    監視 patches._split_wide_boxes 有沒有被呼叫。需要這個測試是因為專案
    目前的真實測試圖裡，剛好沒有一張真的出現兩個數字黏在一起的標籤
    （這種失敗情況本來就很少見，從來沒被實際拍到過），所以沒有任何
    端對端測試能驗證「切開之後真的讀出正確的多位數」——只能驗證
    「呼叫點確實存在、確實會被執行到」。
    """
    image = _load("live_patches_browser.png")
    grid = patches.build_grid(image)
    labels = patches.find_labels(image, grid)
    assert labels, "fixture has no labels - test setup is wrong / 測試圖沒有任何標籤，測試設計有誤"

    calls = []
    original = patches._split_wide_boxes

    def spy(boxes):
        calls.append(boxes)
        return original(boxes)

    patches._split_wide_boxes = spy
    try:
        for label in labels:
            patches.read_label_value(image, label)
    finally:
        patches._split_wide_boxes = original

    assert calls, "read_label_value never called _split_wide_boxes / read_label_value 從來沒有呼叫過 _split_wide_boxes"
    print("  read_label_value actually calls the wide-box splitter OK")


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


def test_live_patches_browser_reads_the_ambiguous_eight():
    """
    Bug this guards: a real 2026-08-25 session (log + a saved
    solve_failed_patches_*.png capture) had the browser Patches widget's
    "8" badge score 0.9735 against APP_TEMPLATES with "6" as the runner-up
    at 0.9552 - a margin of 0.0183, under MIN_MARGIN (0.020). classify_glyph
    correctly refused to guess (that is the safety margin working as
    designed - see classify_glyph's own docstring), so every crop/scale in
    solve_image's ladder reported the same "8" as unreadable and the puzzle
    could not be solved. Not a logic bug in the gate - the browser widget's
    own rendering of "8" simply was not close enough to the phone-app "8"
    template, exactly like test_live_browser_mini_sudoku_reads_every_given's
    "3" below. Fixed the same way: added a second, independent Patches
    source (BROWSER_PATCHES_GIVENS in tools/calibrate_digits.py) and
    regenerated core/digit_templates.py from it.
    這個測試守住的問題：一次真實的 2026-08-25 執行（記錄檔 + 一張存下的
    solve_failed_patches_*.png）顯示，瀏覽器版 Patches 元件的「8」標籤對
    APP_TEMPLATES 只拿到 0.9735 分，第二名「6」拿到 0.9552 分——差距
    0.0183，不到 MIN_MARGIN（0.020）。classify_glyph 正確地拒絕用猜的
    （這正是安全邊界原本設計要做的事——見 classify_glyph 自己的文件
    字串），於是 solve_image 階梯裡每一次裁切／縮放都把同一個「8」讀成
    讀不出來，整題無法解出。不是安全邊界的邏輯錯誤——純粹是瀏覽器元件
    自己畫的「8」，跟手機 App 的「8」範本不夠像，跟下面
    test_live_browser_mini_sudoku_reads_every_given 的「3」是同一種狀況。
    修法也相同：在 tools/calibrate_digits.py 加入第二個獨立的 Patches
    來源（BROWSER_PATCHES_GIVENS），並用它重新產生 core/digit_templates.py。
    """
    image = _load("live_patches_browser.png")
    result = solve_image(image, puzzle_key="patches")
    assert result.ok, result.error
    labels = result.data["labels"]

    numbered = {(lb.row, lb.col): lb.value for lb in labels if lb.value is not None}
    assert numbered == {(1, 1): 6, (2, 3): 4, (3, 2): 9, (4, 4): 8}, numbered
    blanks = {(lb.row, lb.col) for lb in labels if lb.value is None}
    assert blanks == {(0, 0), (0, 4), (5, 1), (5, 5)}, blanks
    print("  live patches browser reads the ambiguous eight OK")


def test_live_patches_browser_2_reads_the_zero_and_seven():
    """
    Bug this guards: before 2026-08-27, digits "0" and "7" had ZERO real
    APP_TEMPLATES samples anywhere in the project - every classification of
    those two digits fell back entirely to FALLBACK_TEMPLATES (system-font
    renders). core/digit_templates.py's own docstring already documents the
    risk class this creates: a machine with different/missing fonts once
    read a real "7" as "2". "0" is even harder to catch by inspection because
    it can only ever appear as the leading digit of a two-digit value like
    "10" - no Patches or Zip puzzle ever shows a bare "0" badge.
    這個測試守住的問題：在 2026-08-27 之前，數字「0」與「7」在整個專案裡
    完全沒有任何一張真實 APP_TEMPLATES 樣本——這兩個數字的每一次辨識都
    完全依賴 FALLBACK_TEMPLATES（系統字型算繪）。core/digit_templates.py
    自己的文件字串就已經記載了這種缺口會造成的風險：曾經有一台缺字型／
    字型不同的機器把真實的「7」讀成「2」。「0」又更難光用肉眼檢查發現，
    因為它只可能以兩位數（例如「10」）的十位數出現——沒有任何 Patches
    或 Zip 題目會顯示單獨一個「0」的標籤。

    Fixed by adding a third, independent Patches calibration source
    (tools/calibrate_digits.py's BROWSER_PATCHES_GIVENS_2, harvested from a
    clean frame in training-data/video/LinkedIn_20260812_加速版.mp4 at t=33s)
    and regenerating core/digit_templates.py from it. This fixture is a crop
    of that same frame, so this test is checking the exact real-world pixels
    the new templates were calibrated from - not a synthetic stand-in.
    修法：在 tools/calibrate_digits.py 加入第三個獨立的 Patches 校準來源
    （BROWSER_PATCHES_GIVENS_2，取自 training-data/video/
    LinkedIn_20260812_加速版.mp4 在 t=33s 的一個乾淨畫面），並用它重新
    產生 core/digit_templates.py。這張測試圖就是那個畫面的裁切，所以這個
    測試核對的就是新範本實際校準所用的那些真實像素，不是找替代品湊數。

    (0, 3) is deliberately excluded from ground truth and asserted as a blank
    below - a zoomed look at the raw capture showed it is one of this
    project's OWN diagnostic overlays (a tiny circled annotation plus a mouse
    cursor baked into the frame), not a real LinkedIn-rendered digit.
    下面把 (0, 3) 歸類在 blanks 裡是刻意的——放大看過原始畫面後，那其實是
    這個程式自己畫的診斷疊加圖層（一個小小的圈起來的註記，還有畫面裡的
    滑鼠游標），不是 LinkedIn 真正畫出來的數字。
    """
    # The actual gap this fixes: APP_TEMPLATES used to have NO real samples
    # at all for these two digits. Checked directly, not just via an
    # end-to-end solve - a solve can pass on FALLBACK_TEMPLATES alone (as it
    # did before this fix, on this very machine's own system fonts), so it
    # would not have caught the missing-font risk this session's evidence
    # (core/digit_templates.py's own docstring) documents.
    # 這裡真正要修的缺口：APP_TEMPLATES 這兩個數字以前完全沒有任何真實樣本。
    # 直接檢查這件事，而不是只做端到端求解——求解光靠 FALLBACK_TEMPLATES
    # 也可能通過（改動前在這台機器自己的系統字型上就是如此），沒辦法真的
    # 守住「缺字型的機器會讀錯」這個風險（見 core/digit_templates.py 自己
    # 的文件字串所記載的證據）。
    assert len(APP_TEMPLATES.get(0, [])) > 0, "digit 0 still has no real screenshot sample"
    assert len(APP_TEMPLATES.get(7, [])) > 0, "digit 7 still has no real screenshot sample"

    image = _load("live_patches_browser_2.png")
    result = solve_image(image, puzzle_key="patches")
    assert result.ok, result.error
    labels = result.data["labels"]

    numbered = {(lb.row, lb.col): lb.value for lb in labels if lb.value is not None}
    assert numbered == {
        (3, 1): 7, (3, 3): 10, (3, 5): 5,
        (6, 0): 3, (6, 2): 5, (6, 4): 3, (6, 6): 3,
    }, numbered
    blanks = {(lb.row, lb.col) for lb in labels if lb.value is None}
    assert blanks == {(1, 0), (1, 2), (0, 4), (0, 6)}, blanks
    print("  live patches browser 2 reads the zero and seven OK")


def test_live_patches_browser_stuck_session_still_reads_correctly():
    """
    Not a bug fix - a coverage/robustness addition. 2026-08-27's deep review of
    training-data/ for training reference material (per the user's explicit
    request to harvest every available real board regardless of whether it
    solved) found a real Patches session that got stuck and STAYED stuck for
    over a minute (img/Patches_20260810.png, _2.png, and four
    solve_failed_patches_*.png spanning 20:28-20:30 on 2026-08-14 all show the
    identical board, "卡關了嗎?" hint prompt still showing). Every label here
    already classified correctly before this fixture was added - the value is
    independent real samples from a puzzle that was hard for the PLAYER, not
    for recognition, added via tools/calibrate_digits.py's
    BROWSER_PATCHES_GIVENS_3.
    不是修 bug——是覆蓋率／穩健性的補強。2026-08-27 為了收集訓練參考資料
    （使用者明確要求：不管有沒有解成功，只要有的題目都收集起來）深度檢視
    training-data/ 時，找到一次真的卡住、而且卡了超過一分鐘的真實 Patches
    對局（img/Patches_20260810.png、_2.png，以及跨越 2026-08-14
    20:28-20:30 的四張 solve_failed_patches_*.png 都是同一個盤面，
    「卡關了嗎？」提示一直沒消失）。這裡每個標籤在加入這張固定資料之前就已經
    分類正確——價值在於這是一組獨立的真實樣本，卡住的是「玩家」不是
    「辨識」，透過 tools/calibrate_digits.py 的 BROWSER_PATCHES_GIVENS_3
    加入。
    """
    image = _load("live_patches_browser_4.png")
    result = solve_image(image, puzzle_key="patches")
    assert result.ok, result.error
    labels = result.data["labels"]
    numbered = {(lb.row, lb.col): lb.value for lb in labels if lb.value is not None}
    assert numbered == {
        (0, 0): 2, (0, 1): 6, (1, 4): 5, (2, 3): 3,
        (3, 2): 4, (4, 1): 8, (5, 4): 2, (5, 5): 6,
    }, numbered
    print("  live patches browser stuck session still reads correctly OK")


def test_live_patches_browser_large_colourful_board_reads_correctly():
    """
    Not a bug fix - a coverage/robustness addition, same 2026-08-27 review as
    test_live_patches_browser_stuck_session_still_reads_correctly above. This
    fixture's original file was misleadingly named
    img/Mini_Sudoku_20260809_1.png - confirmed by eye (and by solve_image()
    succeeding here under puzzle_key="patches") that it is actually a large
    8x8 Patches board with unusually rich colour variety in one single
    capture, harvested via BROWSER_PATCHES_GIVENS_4.
    不是修 bug——覆蓋率／穩健性補強，跟上面
    test_live_patches_browser_stuck_session_still_reads_correctly 同一輪
    2026-08-27 的檢視。這張固定資料的原始檔名誤植成
    img/Mini_Sudoku_20260809_1.png——已用肉眼核對過（並且 solve_image() 在
    puzzle_key="patches" 下確實成功求解），其實是一張顏色特別豐富的 8x8
    Patches 大棋盤，透過 BROWSER_PATCHES_GIVENS_4 收集進來。
    """
    image = _load("live_patches_browser_5.png")
    result = solve_image(image, puzzle_key="patches")
    assert result.ok, result.error
    labels = result.data["labels"]
    numbered = {(lb.row, lb.col): lb.value for lb in labels if lb.value is not None}
    assert numbered == {
        (0, 0): 4, (0, 4): 8, (1, 3): 3, (2, 2): 3,
        (3, 1): 2, (3, 3): 2, (3, 7): 4, (4, 0): 8,
        (4, 4): 6, (4, 6): 6, (5, 5): 3, (6, 4): 3,
        (7, 3): 4, (7, 7): 4,
    }, numbered
    blanks = {(lb.row, lb.col) for lb in labels if lb.value is None}
    assert blanks == {(6, 6), (1, 1)}, blanks
    print("  live patches browser large colourful board reads correctly OK")


def test_live_patches_browser_four_sevens_reads_correctly():
    """
    Coverage addition, not a bug fix - same 2026-08-27 review as the two
    tests above. LinkedIn_20260807_加速版.mp4 at t=36s happens to show digit
    "7" in FOUR different badge colours on one real board (this same layout
    was found stuck for ~100s before recovering, per that review, but every
    label here already classified correctly - the stuck-ness was the player,
    not recognition). Harvested via BROWSER_PATCHES_GIVENS_5 specifically to
    reinforce "7", which - along with "0" - had zero real samples before
    2026-08-27 and remains the thinnest-covered digit even after
    BROWSER_PATCHES_GIVENS_2 added the first one.
    覆蓋率補強，不是修 bug——跟上面兩個測試同一輪 2026-08-27 的檢視。
    LinkedIn_20260807_加速版.mp4 在 t=36s 剛好有一張真實盤面，數字「7」
    同時以四種不同標籤顏色出現（同一輪檢視也發現這個排列曾經卡關約 100 秒
    才恢復，但這裡每個標籤本來就分類正確——卡住的是玩家，不是辨識）。
    透過 BROWSER_PATCHES_GIVENS_5 收集進來，專門用來加強「7」——它跟「0」
    是 2026-08-27 之前唯二完全沒有真實樣本的數字，就算 BROWSER_PATCHES_
    GIVENS_2 補了第一個之後，仍然是所有數字裡真實樣本最少的。
    """
    image = _load("live_patches_browser_6.png")
    result = solve_image(image, puzzle_key="patches")
    assert result.ok, result.error
    labels = result.data["labels"]
    numbered = {(lb.row, lb.col): lb.value for lb in labels if lb.value is not None}
    assert numbered == {(0, 1): 7, (1, 4): 7, (2, 0): 7, (6, 5): 7}, numbered
    blanks = {(lb.row, lb.col) for lb in labels if lb.value is None}
    assert blanks == {(4, 6), (5, 2)}, blanks
    print("  live patches browser four sevens reads correctly OK")


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


def test_renormalise_never_lets_the_puzzle_type_change():
    """
    Bug this guards: a 2026-08-26 code review found _renormalise() (the
    "redo recognition at the calibrated scale" step, run whenever a solve
    succeeds at a scale far from TARGET_BOARD_PIXELS) called the internal
    retry with the ORIGINAL caller-supplied puzzle_key, not
    result.puzzle_key (the type that just succeeded). In the default
    auto-detect path (puzzle_key=None, e.g. the GUI's "auto" dropdown),
    that falsy value made the retry run detect_type() FRESH on the
    rescaled image instead of reusing the type that already won -
    detect_type is independently documented (this file's own
    test_mini_sudoku_survives_extra_colour_noise) as fragile to exactly
    the kind of perturbation a rescale is. A board that first solved as
    one puzzle type could rescale into something detect_type reads as a
    DIFFERENT type entirely; if that other type's own guards happen to
    pass on the same pixels, the wrong puzzle's answer would silently
    replace the right one, with no cross-check they are even the same
    game. Fixed by forcing the retry to result.puzzle_key, never
    re-detecting.
    這個測試守住的問題：2026-08-26 的程式碼審查發現 _renormalise()
    (「用校準尺度重做辨識」這一步，只要求解在離 TARGET_BOARD_PIXELS
    很遠的尺度下成功就會執行）呼叫內部重試時，用的是呼叫端「原始」的
    puzzle_key 參數，不是 result.puzzle_key（剛剛成功的那個類型）。在
    預設的自動判斷路徑下（puzzle_key=None，例如 GUI 的「自動」下拉
    選單），這個假值會讓重試對縮放後的影像重新跑一次 detect_type()，
    而不是沿用已經成功的類型——detect_type 已經在本檔案自己的
    test_mini_sudoku_survives_extra_colour_noise 裡被記錄過，對「縮放」
    這種擾動本來就脆弱。一個原本判定成某種類型並解出來的棋盤，縮放後
    可能被 detect_type 讀成完全不同的類型；如果那個類型自己的守門剛好
    在同一批像素上通過，錯的題目答案就會悄悄取代對的，完全沒有核對過
    是不是同一款遊戲。修法：強制重試沿用 result.puzzle_key，絕不重新
    判斷。
    """
    import linkedin_games_solver.puzzles as puzzles_module
    from linkedin_games_solver.core import BoardGrid
    from linkedin_games_solver.puzzles import SolveResult

    calls = []

    def fake_attempt(image, puzzle_key, n_hint):
        calls.append(puzzle_key)
        if puzzle_key:
            # Forced to a specific type - behaves correctly (mirrors real
            # _attempt: an explicit puzzle_key is honoured exactly).
            return SolveResult(ok=True, puzzle_key=puzzle_key,
                                grid=BoardGrid(n=6, board_bbox=(0, 0, 794, 794), cell_boxes=[]))
        # No type forced - simulates detect_type() misreading the rescaled
        # image as a totally different puzzle whose OWN guards happen to
        # pass. This is the exact bug: if _renormalise ever reaches this
        # branch, it has already failed to pin the type down.
        return SolveResult(ok=True, puzzle_key="queens",
                            grid=BoardGrid(n=6, board_bbox=(0, 0, 794, 794), cell_boxes=[]))

    original_attempt = puzzles_module._attempt
    puzzles_module._attempt = fake_attempt
    try:
        sub = np.zeros((400, 400, 3), dtype="uint8")
        # detected_width=400 at factor=1.0 is far from TARGET_BOARD_PIXELS
        # (794), so ideal != factor by far more than the 15% tolerance -
        # this guarantees the rescale-and-retry path actually runs.
        original = SolveResult(ok=True, puzzle_key="tango",
                                grid=BoardGrid(n=6, board_bbox=(0, 0, 400, 400), cell_boxes=[]))
        _factor, final = puzzles_module._renormalise(sub, original, 1.0, None)
    finally:
        puzzles_module._attempt = original_attempt

    assert calls, "the rescale-and-retry path never ran - test setup is wrong / 重算重試路徑根本沒有執行，測試設計有誤"
    assert calls[-1] == "tango", (
        f"_renormalise called _attempt with puzzle_key={calls[-1]!r} instead of "
        f"the original result's type 'tango' / _renormalise 呼叫 _attempt 時傳的是 "
        f"{calls[-1]!r}，不是原本結果的類型 'tango'"
    )
    assert final.puzzle_key == "tango", (
        f"final result's puzzle_key silently changed to {final.puzzle_key!r} / "
        f"最終結果的 puzzle_key 被悄悄換成了 {final.puzzle_key!r}"
    )
    print("  renormalise never lets the puzzle type change OK")


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
    test_mini_sudoku_survives_extra_colour_noise()
    test_a_faint_walled_zip_board_is_not_misread_as_tango()
    test_all_five_puzzles_solve()
    test_live_queens_boards()
    test_live_tango_matches_screen()
    test_patches_splits_a_wide_merged_digit_component()
    test_read_label_value_actually_calls_the_wide_box_splitter()
    test_live_patches_with_blank_labels()
    test_live_patches_browser_reads_the_ambiguous_eight()
    test_live_patches_browser_2_reads_the_zero_and_seven()
    test_live_patches_browser_stuck_session_still_reads_correctly()
    test_live_patches_browser_large_colourful_board_reads_correctly()
    test_live_patches_browser_four_sevens_reads_correctly()
    test_live_browser_mini_sudoku_reads_every_given()
    test_wrong_type_does_not_fake_success()
    test_zoom_hint_is_not_appended_to_a_comfortably_large_borderless_board()
    test_initial_recognition_survives_a_partially_filled_patches_board()
    test_stops_when_board_changes()
    test_stops_when_the_board_shifts_without_disappearing()
    test_board_position_survives_the_working_size_cap()
    test_renormalise_never_lets_the_puzzle_type_change()
    test_should_continue_cuts_a_failing_solve_short()
    print("\nAll passed / 全部通過")
