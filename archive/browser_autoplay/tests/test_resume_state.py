"""
「盤面已經填了一部分」時的行為測試。

這是實際使用時最常遇到的狀況：自動填答跑到一半漏點了一格、或使用者自己點了幾格。
重跑時必須依「每格目前的狀態」決定還要點幾下，不能一律當成從空白開始，
否則會多點而把已經對的格子又弄錯。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import queens_ext  # noqa: E402
from board_mapper import BoardMapper  # noqa: E402
from capture import ScreenShot  # noqa: E402
from input_driver import InputDriver  # noqa: E402
from players import PLAYERS  # noqa: E402

import numpy as np  # noqa: E402


class _FakeGrid:
    """假的棋盤幾何：n x n，每格 10x10，方便算預期座標。"""

    def __init__(self, n):
        self.n = n
        self.board_bbox = (0, 0, n * 10, n * 10)
        self.cell_boxes = [
            [(c * 10, r * 10, 10, 10) for c in range(n)] for r in range(n)
        ]

    def cell_center(self, r, c):
        return c * 10 + 5, r * 10 + 5


def _mapper(n):
    shot = ScreenShot(image=np.zeros((n * 10, n * 10, 3), np.uint8), origin_x=0, origin_y=0)
    return BoardMapper(shot=shot, grid=_FakeGrid(n))


def _clicks(plan):
    driver = InputDriver(dry_run=True)
    plan.run(driver)
    return driver.log


# ---------------------------------------------------------------- Queens
def test_queens_click_counts_depend_on_state():
    assert queens_ext.clicks_needed(None) == 2, "空白 -> 皇冠 要點 2 下"
    assert queens_ext.clicks_needed(queens_ext.STATE_X) == 1, "X -> 皇冠 只要再點 1 下"
    assert queens_ext.clicks_needed(queens_ext.STATE_QUEEN) == 0, "已是皇冠不用再點"
    print("  Queens 各狀態所需點擊數正確")


def test_queens_resumes_half_done_board():
    """8 個放好、最後一個只點到一半 (停在 X) —— 應該只補點 1 下。"""
    mapper = _mapper(9)
    queens = [(i, (i * 2) % 9) for i in range(9)]
    states = {pos: queens_ext.STATE_QUEEN for pos in queens[:-1]}
    states[queens[-1]] = queens_ext.STATE_X

    plan = PLAYERS["queens"](mapper).build_plan(
        {"queens": queens, "cell_states": states}
    )
    log = _clicks(plan)
    assert len(log) == 1, f"應該只補 1 格，實際 {len(log)} 格"
    assert "x1" in log[0], f"應該只點 1 下，實際 {log[0]}"
    print(f"  Queens 續跑：只補最後一格且只點 1 下 -> {log[0]}")


def test_queens_fully_solved_does_nothing():
    mapper = _mapper(9)
    queens = [(i, (i * 2) % 9) for i in range(9)]
    states = {pos: queens_ext.STATE_QUEEN for pos in queens}
    plan = PLAYERS["queens"](mapper).build_plan({"queens": queens, "cell_states": states})
    assert _clicks(plan) == [], "已完成的盤面不應該再點任何一下"
    print("  Queens 已完成時不做任何操作")


# ---------------------------------------------------------------- Tango
def test_tango_click_counts_depend_on_state():
    """空白->太陽->月亮->空白 的循環，點擊數要依目前狀態算。"""
    mapper = _mapper(2)
    solution = [[1, 0], [0, 1]]  # 1=太陽 0=月亮

    cases = [
        ({}, "全空白", {(0, 0): 1, (0, 1): 2, (1, 0): 2, (1, 1): 1}),
        ({(0, 0): 1, (0, 1): 0, (1, 0): 0, (1, 1): 1}, "全部已填對", {}),
        # (0,0) 目前是月亮，目標太陽 -> 月亮(2)->空白(0)->太陽(1) 要點 2 下
        ({(0, 0): 0}, "填錯成月亮", {(0, 0): 2, (0, 1): 2, (1, 0): 2, (1, 1): 1}),
        # (0,1) 目前是太陽，目標月亮 -> 只要再點 1 下
        ({(0, 1): 1}, "填錯成太陽", {(0, 0): 1, (0, 1): 1, (1, 0): 2, (1, 1): 1}),
    ]

    for current, label, expected in cases:
        full_current = {(r, c): current.get((r, c)) for r in range(2) for c in range(2)}
        plan = PLAYERS["tango"](mapper).build_plan(
            {"solution": solution, "givens": set(), "current": full_current}
        )
        log = _clicks(plan)
        got = {}
        for line in log:
            # 例: "click (5,5) x2  ((1,1) 太陽)"
            coords = line.split("(")[1].split(")")[0].split(",")
            x, y = int(coords[0]), int(coords[1])
            r, c = (y - 5) // 10, (x - 5) // 10
            got[(r, c)] = int(line.split(" x")[1].split(" ")[0])
        assert got == expected, f"{label}: 預期 {expected} 實際 {got}"
        print(f"  Tango {label}: {got}")


if __name__ == "__main__":
    print("續跑 / 部分填答狀態測試")
    test_queens_click_counts_depend_on_state()
    test_queens_resumes_half_done_board()
    test_queens_fully_solved_does_nothing()
    test_tango_click_counts_depend_on_state()
    print("\n全部通過。")
