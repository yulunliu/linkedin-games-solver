"""
Tango 太陽/月亮謎題求解器 (Constraint solver)

規則:
  - 每格填太陽(1) 或 月亮(0)
  - 同一列或同一行中，相鄰同符號不得連續超過 2 個 (不可 3 連)
  - 每列、每行的太陽數與月亮數必須相等 (故 N 必須為偶數)
  - 用 "=" 連接的相鄰兩格必須同符號
  - 用 "×" 連接的相鄰兩格必須不同符號
  - 部分格子是題目給定的初始值 (givens)，不可更改

只使用 givens + edge 約束求解，不使用玩家目前已填的（可能有誤的）答案，
這樣才能反過來拿正解去檢查玩家哪裡填錯。
"""

import random
from dataclasses import dataclass, field
from typing import Optional

from ortools.sat.python import cp_model

SUN = 1
MOON = 0

SYMBOL_NAME = {SUN: "sun", MOON: "moon"}
SYMBOL_EMOJI = {SUN: "🟠", MOON: "🌙"}


@dataclass
class Puzzle:
    n: int
    givens: dict[tuple[int, int], int] = field(default_factory=dict)
    # h_edges[(r, c)] = '=' or 'x'  --> constraint between cell (r,c) and (r,c+1)
    h_edges: dict[tuple[int, int], str] = field(default_factory=dict)
    # v_edges[(r, c)] = '=' or 'x'  --> constraint between cell (r,c) and (r+1,c)
    v_edges: dict[tuple[int, int], str] = field(default_factory=dict)

    def validate(self) -> list[str]:
        errors = []
        if self.n % 2 != 0:
            errors.append(f"棋盤大小 n={self.n} 必須為偶數")
        for (r, c), v in self.givens.items():
            if not (0 <= r < self.n and 0 <= c < self.n):
                errors.append(f"given 座標超出範圍: {(r, c)}")
            if v not in (0, 1):
                errors.append(f"given 值不合法: {(r, c)}={v}")
        for (r, c), sym in self.h_edges.items():
            if not (0 <= r < self.n and 0 <= c < self.n - 1):
                errors.append(f"h_edge 座標超出範圍: {(r, c)}")
            if sym not in ("=", "x"):
                errors.append(f"h_edge 符號不合法: {(r, c)}={sym}")
        for (r, c), sym in self.v_edges.items():
            if not (0 <= r < self.n - 1 and 0 <= c < self.n):
                errors.append(f"v_edge 座標超出範圍: {(r, c)}")
            if sym not in ("=", "x"):
                errors.append(f"v_edge 符號不合法: {(r, c)}={sym}")
        return errors


class NoSolutionError(RuntimeError):
    pass


class MultipleSolutionsError(RuntimeError):
    def __init__(self, solutions):
        super().__init__(f"找到 {len(solutions)}+ 組解，題目可能輸入錯誤或不唯一")
        self.solutions = solutions


def build_model(puzzle: Puzzle) -> tuple[cp_model.CpModel, list[list[cp_model.IntVar]]]:
    n = puzzle.n
    model = cp_model.CpModel()
    cells = [[model.NewBoolVar(f"cell_{r}_{c}") for c in range(n)] for r in range(n)]

    # givens
    for (r, c), v in puzzle.givens.items():
        model.Add(cells[r][c] == v)

    # no 3 consecutive equal, row-wise and column-wise
    for r in range(n):
        for c in range(n - 2):
            trio = [cells[r][c], cells[r][c + 1], cells[r][c + 2]]
            model.Add(sum(trio) <= 2)
            model.Add(sum(trio) >= 1)
    for c in range(n):
        for r in range(n - 2):
            trio = [cells[r][c], cells[r + 1][c], cells[r + 2][c]]
            model.Add(sum(trio) <= 2)
            model.Add(sum(trio) >= 1)

    # equal count of sun/moon per row and per column
    half = n // 2
    for r in range(n):
        model.Add(sum(cells[r]) == half)
    for c in range(n):
        model.Add(sum(cells[r][c] for r in range(n)) == half)

    # = / x edge constraints
    for (r, c), sym in puzzle.h_edges.items():
        a, b = cells[r][c], cells[r][c + 1]
        if sym == "=":
            model.Add(a == b)
        else:
            model.Add(a != b)
    for (r, c), sym in puzzle.v_edges.items():
        a, b = cells[r][c], cells[r + 1][c]
        if sym == "=":
            model.Add(a == b)
        else:
            model.Add(a != b)

    return model, cells


def solve(puzzle: Puzzle, check_unique: bool = False) -> list[list[int]]:
    """
    求解 puzzle。

    預設 (check_unique=False)：只要找得到任何一組符合規則的解就回傳，
    若剛好有多組解 (代表 given/=/× 的辨識不足以唯一確定答案)，
    也不當作錯誤，直接隨機挑一組回傳即可 (啟用 CP-SAT 的隨機搜尋)。

    check_unique=True 是給測試用的嚴格模式：會多花一點時間確認解是否唯一，
    有多組解時丟出 MultipleSolutionsError，方便驗證 solver 邏輯本身沒問題。
    """
    errors = puzzle.validate()
    if errors:
        raise ValueError("Puzzle 定義有誤:\n" + "\n".join(errors))

    model, cells = build_model(puzzle)
    solver = cp_model.CpSolver()

    if check_unique:
        collector = _SolutionCollector(cells, limit=2)
        solver.parameters.enumerate_all_solutions = True
        status = solver.Solve(model, collector)
        if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE) or not collector.solutions:
            raise NoSolutionError("找不到符合所有規則的解，請檢查圖片辨識是否有誤")
        if len(collector.solutions) > 1:
            raise MultipleSolutionsError(collector.solutions)
        return collector.solutions[0]
    else:
        solver.parameters.randomize_search = True
        solver.parameters.random_seed = random.randint(0, 2**31 - 1)
        status = solver.Solve(model)
        if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            raise NoSolutionError("找不到符合所有規則的解，請檢查圖片辨識是否有誤")
        n = puzzle.n
        return [[solver.Value(cells[r][c]) for c in range(n)] for r in range(n)]


class _SolutionCollector(cp_model.CpSolverSolutionCallback):
    def __init__(self, cells, limit: int = 2):
        super().__init__()
        self._cells = cells
        self._limit = limit
        self.solutions: list[list[list[int]]] = []

    def on_solution_callback(self):
        n = len(self._cells)
        grid = [[self.Value(self._cells[r][c]) for c in range(n)] for r in range(n)]
        self.solutions.append(grid)
        if len(self.solutions) >= self._limit:
            self.StopSearch()


def format_grid(grid: list[list[int]]) -> str:
    return "\n".join(" ".join(SYMBOL_EMOJI[v] for v in row) for row in grid)


def diff_against_current(
    solution: list[list[int]],
    current: dict[tuple[int, int], Optional[int]],
) -> list[tuple[int, int, int, int]]:
    """回傳玩家目前答案與正解不同的格子: (r, c, player_value, correct_value)"""
    mistakes = []
    for (r, c), v in current.items():
        if v is not None and v != solution[r][c]:
            mistakes.append((r, c, v, solution[r][c]))
    return mistakes
