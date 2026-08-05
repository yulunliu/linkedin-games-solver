"""
五種謎題求解器的單元測試 (純邏輯，不依賴圖片)。

每個測試都用「獨立於求解器實作之外」的檢查函式重新驗證一次規則，
避免求解器本身寫錯卻自我驗證通過。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import puzzle_patches as patches  # noqa: E402
import puzzle_queens as queens  # noqa: E402
import puzzle_sudoku as sudoku  # noqa: E402
import puzzle_zip as zipp  # noqa: E402


def test_queens():
    # 一個 5x5 的色塊劃分：每列一個橫條當一個區域，正解就是標準 5-queens 排列
    n = 5
    regions = [[r for _ in range(n)] for r in range(n)]
    result = queens.solve(n, regions)
    assert result is not None, "應該要有解"
    assert len(result) == n

    rows = [r for r, _ in result]
    cols = [c for _, c in result]
    assert sorted(rows) == list(range(n)), "每列恰好一個"
    assert sorted(cols) == list(range(n)), "每欄恰好一個"
    assert len({regions[r][c] for r, c in result}) == n, "每個區域恰好一個"
    for i, (r1, c1) in enumerate(result):
        for r2, c2 in result[i + 1 :]:
            assert max(abs(r1 - r2), abs(c1 - c2)) > 1, f"皇后 {(r1,c1)} 與 {(r2,c2)} 相鄰"
    print("queens OK:", sorted(result))


def test_queens_unsolvable():
    # 3x3 全部一個區域 -> 需要 3 個皇后但只允許 1 個 -> 無解
    regions = [[0] * 3 for _ in range(3)]
    assert queens.solve(3, regions) is None


def test_sudoku():
    givens = {
        (0, 0): 1, (0, 1): 2,
        (1, 0): 3, (1, 1): 4,
        (2, 0): 2, (2, 5): 1,
        (3, 0): 4, (3, 5): 3,
        (4, 4): 1, (4, 5): 2,
        (5, 4): 3, (5, 5): 5,
    }
    n, box_h, box_w = 6, 2, 3
    grid = sudoku.solve(n, box_h, box_w, givens)
    assert grid is not None, "應該要有解"

    for r in range(n):
        assert sorted(grid[r]) == list(range(1, n + 1)), f"第 {r} 列有重複"
    for c in range(n):
        assert sorted(grid[r][c] for r in range(n)) == list(range(1, n + 1)), f"第 {c} 欄有重複"
    for br in range(0, n, box_h):
        for bc in range(0, n, box_w):
            box = [grid[r][c] for r in range(br, br + box_h) for c in range(bc, bc + box_w)]
            assert sorted(box) == list(range(1, n + 1)), f"宮 ({br},{bc}) 有重複"
    for (r, c), v in givens.items():
        assert grid[r][c] == v, f"given {(r,c)} 未被滿足"
    print("sudoku OK")


def test_sudoku_unsolvable():
    # 同一列放兩個 1 -> 無解
    assert sudoku.solve(6, 2, 3, {(0, 0): 1, (0, 1): 1}) is None


def test_zip():
    # 3x3 沒有牆，1 在左上、2 在右下 -> 應該找到走完 9 格的路徑
    n = 3
    dots = {(0, 0): 1, (2, 2): 2}
    path = zipp.solve(n, dots, set(), set())
    assert path is not None, "應該要有解"
    assert len(path) == n * n, "必須走過每一格"
    assert len(set(path)) == n * n, "不能重複走同一格"
    assert path[0] == (0, 0), "必須從編號 1 出發"
    for (r1, c1), (r2, c2) in zip(path, path[1:]):
        assert abs(r1 - r2) + abs(c1 - c2) == 1, f"{(r1,c1)} 與 {(r2,c2)} 不相鄰"
    order = {cell: i for i, cell in enumerate(path)}
    assert order[(0, 0)] < order[(2, 2)], "編號順序錯誤"
    print("zip OK:", path)


def test_zip_respects_walls():
    # 2x2，把 (0,0)-(0,1) 與 (0,0)-(1,0) 都用牆封住 -> (0,0) 出不去 -> 無解
    walls_h = {(0, 0)}
    walls_v = {(0, 0)}
    assert zipp.solve(2, {(0, 0): 1, (1, 1): 2}, walls_h, walls_v) is None

    # 只封一邊仍然可解，且解不能穿牆
    path = zipp.solve(2, {(0, 0): 1, (1, 1): 2}, {(0, 0)}, set())
    assert path is not None
    for (r1, c1), (r2, c2) in zip(path, path[1:]):
        if r1 == r2:
            assert (r1, min(c1, c2)) not in {(0, 0)}, "穿越了水平牆"
    print("zip walls OK:", path)


def _label(row, col, value, shape):
    return patches.PatchLabel(row=row, col=col, value=value, shape=shape, bbox=(0, 0, 1, 1), color=(0, 0, 0))


def test_patches():
    # 4x4 = 16 格，切成 4 塊各 4 格：左邊兩個直條 + 右邊兩個 2x2 正方形
    n = 4
    labels = [
        _label(0, 0, 4, patches.SHAPE_VERTICAL),  # 4 高 x 1 寬，第 0 欄
        _label(1, 1, 4, patches.SHAPE_VERTICAL),  # 4 高 x 1 寬，第 1 欄
        _label(0, 3, 4, patches.SHAPE_SQUARE),    # 2x2，rows 0-1, cols 2-3
        _label(3, 2, 4, patches.SHAPE_SQUARE),    # 2x2，rows 2-3, cols 2-3
    ]
    rects = patches.solve(n, labels)
    assert rects is not None, "應該要有解"

    covered = {}
    for label, (r0, c0, height, width) in zip(labels, rects):
        assert height * width == label.value, "面積與數字不符"
        assert patches._shape_allowed(label.shape, height, width), "形狀不符"
        assert r0 <= label.row < r0 + height and c0 <= label.col < c0 + width, "標籤不在自己的矩形內"
        for r in range(r0, r0 + height):
            for c in range(c0, c0 + width):
                assert (r, c) not in covered, f"格子 {(r,c)} 被重複覆蓋"
                covered[(r, c)] = True
    assert len(covered) == n * n, "沒有覆蓋所有格子"
    print("patches OK:", rects)


def test_patches_unsolvable():
    # 面積總和不等於盤面格數 -> 無解
    labels = [_label(0, 0, 3, patches.SHAPE_ANY)]
    assert patches.solve(2, labels) is None


if __name__ == "__main__":
    test_queens()
    test_queens_unsolvable()
    test_sudoku()
    test_sudoku_unsolvable()
    test_zip()
    test_zip_respects_walls()
    test_patches()
    test_patches_unsolvable()
    print("\nAll puzzle solver tests passed.")
