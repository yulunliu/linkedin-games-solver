"""
Patches 擴充（支援無數字標籤 = 大小不限）的單元測試。

其中一個測試直接重現使用者實際遇到的題目：5x5 盤面，
左上「8」、右上「6」，左下與右下是兩個沒有數字的標籤。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import patches_ext  # noqa: E402
import puzzle_patches as pp  # noqa: E402


def _label(row, col, value, shape, glyphs=()):
    return pp.PatchLabel(
        row=row, col=col, value=value, shape=shape,
        bbox=(0, 0, 1, 1), color=(0, 0, 0), glyphs=list(glyphs),
    )


def check_tiling(n, labels, rects):
    covered = {}
    for label, (r0, c0, height, width) in zip(labels, rects):
        if label.value is not None:
            assert height * width == label.value, f"面積 {height*width} 與數字 {label.value} 不符"
        assert pp._shape_allowed(label.shape, height, width), (
            f"形狀不符: {label.shape} 卻是 {height}x{width}"
        )
        assert r0 <= label.row < r0 + height and c0 <= label.col < c0 + width, "標籤不在自己的矩形內"
        for r in range(r0, r0 + height):
            for c in range(c0, c0 + width):
                assert (r, c) not in covered, f"格子 {(r,c)} 被重複覆蓋"
                covered[(r, c)] = True
    assert len(covered) == n * n, f"只覆蓋了 {len(covered)}/{n*n} 格"


def test_blank_labels_are_usable_not_errors():
    """空白標籤 (glyphs 是空的) 要算成『大小不限』，不能當成辨識失敗。"""
    labels = [
        _label(0, 0, 8, pp.SHAPE_ANY),
        _label(0, 4, None, pp.SHAPE_ANY, glyphs=[]),          # 空白標籤
    ]
    usable, unreadable = patches_ext.classify_labels(labels)
    assert len(usable) == 2 and not unreadable

    # 有字形卻讀不出數字 -> 要被當成辨識失敗
    broken = [_label(0, 0, None, pp.SHAPE_ANY, glyphs=[object()])]
    usable, unreadable = patches_ext.classify_labels(broken)
    assert not usable and len(unreadable) == 1
    print("  空白標籤 / 讀不出來 的分類正確")


def test_user_actual_puzzle_5x5():
    """重現使用者截圖：5x5，左上 8、右上 6、左下與右下無數字。"""
    n = 5
    labels = [
        _label(0, 0, 8, pp.SHAPE_ANY),
        _label(0, 4, 6, pp.SHAPE_ANY),
        _label(4, 0, None, pp.SHAPE_ANY, glyphs=[]),
        _label(4, 4, None, pp.SHAPE_ANY, glyphs=[]),
    ]
    rects = patches_ext.solve(n, labels)
    assert rects is not None, "應該要有解"
    check_tiling(n, labels, rects)

    blank_areas = [h * w for lb, (_, _, h, w) in zip(labels, rects) if lb.value is None]
    assert sum(blank_areas) == n * n - 8 - 6, "無數字標籤應該補滿剩下的格數"
    print(f"  5x5 使用者題目 OK，切法={rects}，無數字兩塊面積={blank_areas}")


def test_blank_label_still_respects_shape():
    """無數字標籤大小不限，但仍要符合形狀型別。"""
    n = 4
    labels = [
        _label(0, 0, None, pp.SHAPE_VERTICAL, glyphs=[]),   # 必須高 > 寬
        _label(0, 2, None, pp.SHAPE_VERTICAL, glyphs=[]),
    ]
    rects = patches_ext.solve(n, labels)
    assert rects is not None
    check_tiling(n, labels, rects)
    for (_, _, h, w) in rects:
        assert h > w, f"應為縱向長方形，卻是 {h}x{w}"
    print(f"  形狀限制在無數字標籤上仍然有效，切法={rects}")


def test_numbered_only_still_works():
    """原本全部都有數字的情況要維持可解 (不能因為擴充而壞掉)。"""
    n = 4
    labels = [
        _label(0, 0, 4, pp.SHAPE_VERTICAL),
        _label(1, 1, 4, pp.SHAPE_VERTICAL),
        _label(0, 3, 4, pp.SHAPE_SQUARE),
        _label(3, 2, 4, pp.SHAPE_SQUARE),
    ]
    rects = patches_ext.solve(n, labels)
    assert rects is not None
    check_tiling(n, labels, rects)
    print(f"  全數字標籤仍可解，切法={rects}")


def test_unsolvable_returns_none():
    labels = [_label(0, 0, 3, pp.SHAPE_SQUARE)]  # 3 不能排成正方形
    assert patches_ext.solve(2, labels) is None
    print("  無解時正確回傳 None")


def test_solve_unique_distinguishes_unique_from_multiple():
    """
    數字讀不出來時會把該標籤當成「大小不限」再解一次，
    只有在切法唯一時才採用 —— 這裡驗證唯一/不唯一都判斷正確。
    """
    n = 4
    only_one = [
        _label(0, 0, 4, pp.SHAPE_VERTICAL),
        _label(1, 1, 4, pp.SHAPE_VERTICAL),
        _label(0, 3, 4, pp.SHAPE_SQUARE),
        _label(3, 2, 4, pp.SHAPE_SQUARE),
    ]
    rects = patches_ext.solve_unique(n, only_one)
    assert rects is not None, "切法唯一時應該要回傳答案"
    check_tiling(n, only_one, rects)

    # 兩個都大小不限 -> 有很多種切法 -> 不可信，必須回傳 None
    ambiguous = [
        _label(0, 0, None, pp.SHAPE_ANY, glyphs=[]),
        _label(3, 3, None, pp.SHAPE_ANY, glyphs=[]),
    ]
    assert patches_ext.solve_unique(n, ambiguous) is None, "切法不唯一時不能回傳答案"
    print("  solve_unique 正確分辨唯一解與多解")


if __name__ == "__main__":
    print("Patches 擴充（無數字標籤）測試")
    test_blank_labels_are_usable_not_errors()
    test_user_actual_puzzle_5x5()
    test_blank_label_still_respects_shape()
    test_numbered_only_still_works()
    test_unsolvable_returns_none()
    test_solve_unique_distinguishes_unique_from_multiple()
    print("\n全部通過。")
