import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from solver import MOON, SUN, Puzzle, format_grid, solve  # noqa: E402


def check_rules(puzzle: Puzzle, grid: list[list[int]]) -> list[str]:
    """獨立於 solver 實作之外，重新檢查一次規則，避免 solver 本身寫錯卻自我驗證通過。"""
    n = puzzle.n
    errors = []

    for r in range(n):
        for c in range(n - 2):
            trio = {grid[r][c], grid[r][c + 1], grid[r][c + 2]}
            if len(trio) == 1:
                errors.append(f"列 {r} 欄 {c}-{c+2} 三連")
    for c in range(n):
        for r in range(n - 2):
            trio = {grid[r][c], grid[r + 1][c], grid[r + 2][c]}
            if len(trio) == 1:
                errors.append(f"欄 {c} 列 {r}-{r+2} 三連")

    half = n // 2
    for r in range(n):
        if sum(grid[r]) != half:
            errors.append(f"列 {r} 數量不相等")
    for c in range(n):
        if sum(grid[r][c] for r in range(n)) != half:
            errors.append(f"欄 {c} 數量不相等")

    for (r, c), v in puzzle.givens.items():
        if grid[r][c] != v:
            errors.append(f"given 未被滿足: {(r, c)}")

    for (r, c), sym in puzzle.h_edges.items():
        a, b = grid[r][c], grid[r][c + 1]
        if sym == "=" and a != b:
            errors.append(f"h_edge = 未滿足: {(r, c)}")
        if sym == "x" and a == b:
            errors.append(f"h_edge x 未滿足: {(r, c)}")

    for (r, c), sym in puzzle.v_edges.items():
        a, b = grid[r][c], grid[r + 1][c]
        if sym == "=" and a != b:
            errors.append(f"v_edge = 未滿足: {(r, c)}")
        if sym == "x" and a == b:
            errors.append(f"v_edge x 未滿足: {(r, c)}")

    return errors


def test_simple_4x4():
    # 手動設計一個 4x4、有唯一解的小題目
    puzzle = Puzzle(
        n=4,
        givens={
            (0, 0): SUN,
            (0, 1): SUN,
            (3, 2): MOON,
            (3, 3): MOON,
        },
        h_edges={(1, 0): "="},
        v_edges={(0, 3): "x"},
    )
    grid = solve(puzzle)
    print("4x4 test solution:")
    print(format_grid(grid))
    errors = check_rules(puzzle, grid)
    assert not errors, errors


def test_no_solution_raises():
    from solver import NoSolutionError

    # 矛盾的題目：同一格同時被要求是 sun 又是 moon (透過 = 與相反 given 造成矛盾)
    puzzle = Puzzle(
        n=4,
        givens={(0, 0): SUN, (0, 1): MOON},
        h_edges={(0, 0): "="},  # 要求 (0,0)==(0,1) 但 givens 相反 -> 無解
    )
    try:
        solve(puzzle)
        assert False, "應該要拋出 NoSolutionError"
    except NoSolutionError:
        pass


def test_multiple_solutions_picks_one_by_default():
    from solver import MultipleSolutionsError

    # 完全沒有 given / 邊約束的 4x4 題目，一定有不只一組解。
    puzzle = Puzzle(n=4)

    # 預設模式：不當作錯誤，直接回傳其中一組合法解。
    grid = solve(puzzle)
    errors = check_rules(puzzle, grid)
    assert not errors, errors

    # 多跑幾次，確認每次都回傳「某一組」合法解就好，不要求每次不同。
    for _ in range(5):
        grid = solve(puzzle)
        errors = check_rules(puzzle, grid)
        assert not errors, errors

    # 嚴格模式 (check_unique=True) 仍然要能偵測出「不只一組解」。
    try:
        solve(puzzle, check_unique=True)
        assert False, "應該要拋出 MultipleSolutionsError"
    except MultipleSolutionsError:
        pass


if __name__ == "__main__":
    test_simple_4x4()
    test_no_solution_raises()
    test_multiple_solutions_picks_one_by_default()
    print("All tests passed.")
