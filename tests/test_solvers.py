"""
Solver logic tests - pure logic, no images.
求解邏輯測試 —— 純邏輯，不使用圖片。

Every test re-checks the rules INDEPENDENTLY of the solver, so a solver that is
wrong in the same way as its own validation cannot pass.
每個測試都用「獨立於求解器之外」的檢查重新驗證規則，
避免求解器寫錯卻自我驗證通過。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from linkedin_games_solver.puzzles import patches, queens, sudoku, tango, zip_path  # noqa: E402


# --------------------------------------------------------------- Queens
def test_queens():
    """Rule satisfaction only - this board is deliberately NOT unique.
    只驗規則滿足 —— 這個盤面刻意「不是」唯一解。

    One region per row makes the region constraint say nothing beyond the row
    constraint, so several layouts satisfy the rules. That is fine for testing
    that the rules are enforced, but it means require_unique must be off. The
    uniqueness guard itself is tested separately below.
    每列一區的話，色塊限制沒有比行限制多說任何事，所以有好幾種佈局都符合規則。
    要驗「規則有被落實」這樣沒問題，但必須關掉 require_unique。
    唯一性守門本身在下面另外測。
    """
    n = 5
    regions = [[r for _ in range(n)] for r in range(n)]  # one region per row 每列一區
    result = queens.solve_positions(n, regions, require_unique=False)
    assert result is not None
    assert sorted(r for r, _ in result) == list(range(n)), "one per row / 每列一個"
    assert sorted(c for _, c in result) == list(range(n)), "one per column / 每欄一個"
    assert len({regions[r][c] for r, c in result}) == n, "one per region / 每區一個"
    for i, a in enumerate(result):
        for b in result[i + 1 :]:
            assert max(abs(a[0] - b[0]), abs(a[1] - b[1])) > 1, "not adjacent / 不相鄰"
    print("  queens OK")


def test_queens_unsolvable():
    assert queens.solve_positions(3, [[0] * 3 for _ in range(3)],
                                  require_unique=False) is None
    print("  queens unsolvable OK")


def test_queens_click_counts():
    assert queens.clicks_needed(None) == 2
    assert queens.clicks_needed(queens.STATE_X) == 1
    assert queens.clicks_needed(queens.STATE_QUEEN) == 0
    print("  queens click counts OK")


# --------------------------------------------------------------- Tango
def _check_tango(puzzle, solution):
    n = puzzle.n
    for r in range(n):
        assert sum(solution[r]) == n // 2, f"row {r} unbalanced / 列數量不等"
    for c in range(n):
        assert sum(solution[r][c] for r in range(n)) == n // 2, f"col {c} unbalanced / 行數量不等"
    for r in range(n):
        for c in range(n - 2):
            assert len({solution[r][c], solution[r][c + 1], solution[r][c + 2]}) > 1, "3 in a row / 三連"
    for c in range(n):
        for r in range(n - 2):
            assert len({solution[r][c], solution[r + 1][c], solution[r + 2][c]}) > 1, "3 in a col / 三連"
    for (r, c), v in puzzle.givens.items():
        assert solution[r][c] == v, "given not honoured / given 未滿足"
    for (r, c), mark in puzzle.h_edges.items():
        same = solution[r][c] == solution[r][c + 1]
        assert same == (mark == "="), "h edge violated / 水平符號未滿足"
    for (r, c), mark in puzzle.v_edges.items():
        same = solution[r][c] == solution[r + 1][c]
        assert same == (mark == "="), "v edge violated / 垂直符號未滿足"


def test_tango():
    puzzle = tango.TangoPuzzle(
        n=4,
        givens={(0, 0): tango.SUN, (0, 1): tango.SUN, (3, 2): tango.MOON, (3, 3): tango.MOON},
        h_edges={(1, 0): "="},
        v_edges={(0, 3): "x"},
    )
    solution = tango.solve_puzzle(puzzle, require_unique=False)
    _check_tango(puzzle, solution)
    print("  tango OK")


def test_tango_contradiction():
    puzzle = tango.TangoPuzzle(
        n=4, givens={(0, 0): tango.SUN, (0, 1): tango.MOON}, h_edges={(0, 0): "="}
    )
    try:
        tango.solve_puzzle(puzzle, require_unique=False)
        raise AssertionError("should have raised NoSolution / 應丟出 NoSolution")
    except tango.NoSolution:
        pass
    print("  tango contradiction OK")


def test_tango_uniqueness_guard():
    """An unconstrained board has many solutions; require_unique must reject it.
    完全沒有條件的盤面有多組解，require_unique 必須拒絕。"""
    puzzle = tango.TangoPuzzle(n=4)
    try:
        tango.solve_puzzle(puzzle, require_unique=True)
        raise AssertionError("should have raised MultipleSolutions / 應丟出 MultipleSolutions")
    except tango.MultipleSolutions:
        pass
    # Without the uniqueness requirement it still returns a legal board.
    # 不要求唯一時仍會回傳一個合法盤面。
    _check_tango(puzzle, tango.solve_puzzle(puzzle, require_unique=False))
    print("  tango uniqueness guard OK")


# --------------------------------------------------------------- Sudoku
def test_sudoku():
    givens = {
        (0, 0): 1, (0, 1): 2, (1, 0): 3, (1, 1): 4,
        (2, 0): 2, (2, 5): 1, (3, 0): 4, (3, 5): 3,
        (4, 4): 1, (4, 5): 2, (5, 4): 3, (5, 5): 5,
    }
    n, box_h, box_w = 6, 2, 3
    grid = sudoku.solve_grid(n, box_h, box_w, givens)
    assert grid is not None
    for r in range(n):
        assert sorted(grid[r]) == list(range(1, n + 1))
    for c in range(n):
        assert sorted(grid[r][c] for r in range(n)) == list(range(1, n + 1))
    for br in range(0, n, box_h):
        for bc in range(0, n, box_w):
            box = [grid[r][c] for r in range(br, br + box_h) for c in range(bc, bc + box_w)]
            assert sorted(box) == list(range(1, n + 1))
    for (r, c), v in givens.items():
        assert grid[r][c] == v
    assert sudoku.has_unique_solution(n, box_h, box_w, givens)
    print("  sudoku OK")


def test_sudoku_uniqueness_guard():
    """Too few givens -> many solutions -> must be reported as not unique.
    給定數字太少 -> 多組解 -> 必須判定為不唯一。"""
    assert not sudoku.has_unique_solution(6, 2, 3, {(0, 0): 1})
    print("  sudoku uniqueness guard OK")


# --------------------------------------------------------------- Zip
def test_zip():
    n = 3
    path = zip_path.solve_path(n, {(0, 0): 1, (2, 2): 2}, set(), set())
    assert path is not None
    assert len(path) == n * n and len(set(path)) == n * n, "must cover every cell / 必須走完每格"
    assert path[0] == (0, 0), "must start at dot 1 / 必須從 1 出發"
    for a, b in zip(path, path[1:]):
        assert abs(a[0] - b[0]) + abs(a[1] - b[1]) == 1, "steps must be adjacent / 每步必須相鄰"
    order = {cell: i for i, cell in enumerate(path)}
    assert order[(0, 0)] < order[(2, 2)], "dot order / 編號順序"
    print("  zip OK")


def test_zip_walls():
    # Sealing both exits from (0,0) makes the puzzle unsolvable.
    # 把 (0,0) 的兩個出口都封住就無解。
    assert zip_path.solve_path(2, {(0, 0): 1, (1, 1): 2}, {(0, 0)}, {(0, 0)}) is None
    path = zip_path.solve_path(2, {(0, 0): 1, (1, 1): 2}, {(0, 0)}, set())
    assert path is not None
    for a, b in zip(path, path[1:]):
        if a[0] == b[0]:
            assert (a[0], min(a[1], b[1])) != (0, 0), "crossed a wall / 穿越了牆"
    print("  zip walls OK")


# --------------------------------------------------------------- Patches
def _label(row, col, value, shape):
    return patches.PatchLabel(row, col, value, shape, (0, 0, 1, 1), (0, 0, 0))


def _check_tiling(n, labels, rects):
    covered = {}
    for label, (r0, c0, h, w) in zip(labels, rects):
        if label.value is not None:
            assert h * w == label.value, "area mismatch / 面積不符"
        assert patches.shape_allowed(label.shape, h, w), "shape mismatch / 形狀不符"
        assert r0 <= label.row < r0 + h and c0 <= label.col < c0 + w, "label outside / 標籤不在矩形內"
        for r in range(r0, r0 + h):
            for c in range(c0, c0 + w):
                assert (r, c) not in covered, "overlap / 重複覆蓋"
                covered[(r, c)] = True
    assert len(covered) == n * n, "not fully covered / 未完全覆蓋"


def test_patches():
    n = 4
    labels = [
        _label(0, 0, 4, patches.SHAPE_VERTICAL),
        _label(1, 1, 4, patches.SHAPE_VERTICAL),
        _label(0, 3, 4, patches.SHAPE_SQUARE),
        _label(3, 2, 4, patches.SHAPE_SQUARE),
    ]
    rects = patches.solve_tiling(n, labels)
    assert rects is not None
    _check_tiling(n, labels, rects)
    print("  patches OK")


def test_patches_blank_labels():
    """Labels with no number mean "any size" - a legal puzzle, not an error.
    沒有數字的標籤代表「大小不限」，是合法題目而不是錯誤。"""
    n = 5
    labels = [
        _label(0, 0, 8, patches.SHAPE_ANY),
        _label(0, 4, 6, patches.SHAPE_ANY),
        _label(4, 0, None, patches.SHAPE_ANY),
        _label(4, 4, None, patches.SHAPE_ANY),
    ]
    rects = patches.solve_tiling(n, labels)
    assert rects is not None
    _check_tiling(n, labels, rects)
    blank_area = sum(h * w for lb, (_, _, h, w) in zip(labels, rects) if lb.value is None)
    assert blank_area == n * n - 8 - 6, "blanks must fill the remainder / 無數字標籤要補滿剩餘"
    print("  patches blank labels OK")


def test_patches_blank_still_respects_shape():
    n = 4
    labels = [
        _label(0, 0, None, patches.SHAPE_VERTICAL),
        _label(0, 2, None, patches.SHAPE_VERTICAL),
    ]
    rects = patches.solve_tiling(n, labels)
    assert rects is not None
    _check_tiling(n, labels, rects)
    for _, _, h, w in rects:
        assert h > w, "must stay vertical / 必須維持縱向"
    print("  patches blank shape OK")


def test_patches_unique_guard():
    n = 4
    only_one = [
        _label(0, 0, 4, patches.SHAPE_VERTICAL),
        _label(1, 1, 4, patches.SHAPE_VERTICAL),
        _label(0, 3, 4, patches.SHAPE_SQUARE),
        _label(3, 2, 4, patches.SHAPE_SQUARE),
    ]
    assert patches.solve_tiling_unique(n, only_one) is not None
    ambiguous = [_label(0, 0, None, patches.SHAPE_ANY), _label(3, 3, None, patches.SHAPE_ANY)]
    assert patches.solve_tiling_unique(n, ambiguous) is None
    print("  patches uniqueness guard OK")


# --------------------------------------------------- uniqueness guards
def test_queens_rejects_a_board_with_two_layouts():
    """
    Bug this guards: Queens was the only puzzle with NO uniqueness check. A
    published board has exactly one crown layout, so a second layout means the
    colour regions were misread - and a misread that still yields n contiguous
    regions passes regions_look_valid() and every check downstream.
    這個測試守住的問題：Queens 是唯一沒有唯一性檢查的謎題。出版的盤面只有一種
    皇冠佈局，所以出現第二種就代表色塊讀錯了 —— 而一個「仍然產生 n 塊連通色塊」
    的誤讀，會通過 regions_look_valid() 與下游每一道檢查。

    Nothing downstream caught it: automation/verify.py accepts 85% region
    agreement so a 1-in-81 misread passes, and the verifier then only asks
    whether the crowns IT chose are present - the wrong layout gets clicked and
    reported as "9/9 correct".
    下游沒有任何東西攔得住：automation/verify.py 接受 85% 的色塊吻合度，
    所以 81 分之 1 的誤讀會過關，而驗證器接著只問「它自己選的皇冠在不在」——
    錯誤佈局被點下去，還回報「9/9 正確」。
    """
    n = 4
    # Four columns as four regions: the region constraint adds nothing beyond
    # the column constraint, so several layouts satisfy the rules.
    # 四個直行當成四個色塊：色塊限制沒有比行限制多給任何條件，
    # 所以有好幾種佈局都符合規則。
    regions = [[c for c in range(n)] for _ in range(n)]
    assert queens.solve_positions(n, regions, require_unique=False) is not None, \
        "the board must be solvable at all / 這個盤面本身要有解"
    assert queens.solve_positions(n, regions) is None, \
        "a board with several layouts must be rejected / 有多種佈局的盤面必須被拒絕"
    print("  queens rejects a board with two layouts OK")


#: The colour regions read off tests/fixtures/live_queens_2.png - a real board,
#: verified to have exactly one crown layout. All four Queens fixtures are
#: unique, so the guard changes nothing for real boards.
#: 從 tests/fixtures/live_queens_2.png 讀出來的真實色塊配置，已驗證只有一種
#: 皇冠佈局。四張 Queens 測試圖全部都是唯一解，所以這個守門對真實盤面毫無影響。
REAL_QUEENS_REGIONS = [
    [0, 0, 0, 0, 0, 0, 1, 1, 1],
    [0, 2, 2, 2, 2, 0, 1, 3, 3],
    [0, 2, 2, 2, 2, 0, 1, 3, 3],
    [0, 0, 0, 1, 1, 1, 1, 3, 3],
    [4, 4, 0, 0, 0, 0, 1, 3, 3],
    [4, 4, 7, 0, 1, 1, 1, 1, 1],
    [4, 4, 7, 5, 6, 6, 6, 6, 1],
    [4, 4, 7, 5, 6, 6, 6, 6, 1],
    [8, 8, 8, 5, 5, 5, 5, 5, 5],
]


def test_queens_still_accepts_a_genuinely_unique_board():
    """The guard must not reject boards that really do have one answer.
    守門不能拒絕真的只有一個答案的盤面。"""
    n = 9
    result = queens.solve_positions(n, REAL_QUEENS_REGIONS)
    assert result is not None, "a real unique board was rejected / 真實的唯一解盤面被拒絕"
    assert sorted(r for r, _ in result) == list(range(n))
    assert sorted(c for _, c in result) == list(range(n))
    assert len({REAL_QUEENS_REGIONS[r][c] for r, c in result}) == n
    for i, a in enumerate(result):
        for b in result[i + 1:]:
            assert max(abs(a[0] - b[0]), abs(a[1] - b[1])) > 1
    print("  queens still accepts a real unique board OK")


def test_patches_success_path_requires_a_unique_tiling():
    """
    Bug this guards: solve() called solve_tiling, not solve_tiling_unique. The
    unique version existed but was only reached on the unreadable-label rescue
    branch, so the success path returned whichever tiling CP-SAT found first.
    這個測試守住的問題：solve() 呼叫的是 solve_tiling 而不是 solve_tiling_unique。
    唯一性版本存在，但只有「讀不出來」的救援分支會走到，
    所以成功路徑拿的是 CP-SAT 剛好先找到的那一種切法。

    NOT conditional on blank labels: six "6" labels down a 6x6 diagonal has zero
    blanks, sums to exactly n*n, passes both of solve()'s guards, and has
    several legal tilings.
    這跟有沒有空白標籤無關：6x6 對角線放六個「6」，零空白、總和剛好 n*n、
    通過 solve() 的兩道守門，而且有好幾種合法切法。
    """
    n = 6
    labels = [_label(i, i, 6, patches.SHAPE_ANY) for i in range(n)]
    assert patches.solve_tiling(n, labels) is not None, \
        "the board must be tileable at all / 這個盤面本身要切得出來"
    assert patches.solve_tiling_unique(n, labels) is None, \
        "a board with several tilings must be rejected / 有多種切法的盤面必須被拒絕"
    print("  patches success path requires a unique tiling OK")


if __name__ == "__main__":
    print("Solver logic tests / 求解邏輯測試")
    test_queens()
    test_queens_unsolvable()
    test_queens_click_counts()
    test_tango()
    test_tango_contradiction()
    test_tango_uniqueness_guard()
    test_sudoku()
    test_sudoku_uniqueness_guard()
    test_zip()
    test_zip_walls()
    test_patches()
    test_patches_blank_labels()
    test_patches_blank_still_respects_shape()
    test_patches_unique_guard()
    test_queens_rejects_a_board_with_two_layouts()
    test_queens_still_accepts_a_genuinely_unique_board()
    test_patches_success_path_requires_a_unique_tiling()
    print("\nAll passed / 全部通過")
