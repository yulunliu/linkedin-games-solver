"""
Check the board after filling, and re-click anything that did not register.
填完後檢查盤面，並補上沒有生效的點擊。

Why this is necessary 為什麼需要:
  Automated clicks are not guaranteed to land - the page may still be loading,
  an animation may swallow one, or the window may not have focus yet. Without a
  verification pass a single dropped click silently leaves the puzzle unsolved.
  自動點擊不保證每一下都會生效 —— 頁面還在載入、動畫吃掉、視窗還沒取得焦點
  都可能造成漏點。沒有驗證的話，掉一下就會讓謎題默默沒解完。

CRITICAL - stop when the board changes:
  once a puzzle is solved the site shows a completion animation and the board's
  appearance changes entirely. Continuing to "verify and re-click" then reads
  garbage, decides the crowns are missing, and keeps clicking - which is exactly
  the "it kept controlling my mouse after finishing" symptom. Every verifier
  therefore confirms the board is still the SAME board before allowing a retry.
關鍵 —— 盤面改變時必須停手：
  解完之後網站會播完成動畫、盤面外觀整個改變。這時繼續「驗證 -> 補點」就會
  讀到垃圾、判定皇冠不見了而一直點下去 —— 這正是「解完了滑鼠還被一直控制」
  的症狀。所以每個驗證器在允許補點前，都會先確認盤面還是原本那一盤。

Supported 支援驗證的謎題: Tango, Queens, Mini Sudoku
  The others draw their answer as a path / tiling outline, which the recognisers
  do not read back, so they report "cannot verify" instead of guessing.
  其餘兩款的作答結果是路徑線與切割線，辨識器讀不回來，所以回報「無法驗證」
  而不是亂猜。
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from ..core import build_grid
from ..puzzles import queens, sudoku, tango


@dataclass
class VerifyReport:
    supported: bool
    ok: bool = False
    reason: str = ""
    #: (row, col, current, expected) for cells that are still wrong.
    #: 還沒填對的格子：(列, 欄, 目前, 應為)。
    mismatches: list[tuple[int, int, object, object]] = field(default_factory=list)
    filled: int = 0
    total: int = 0
    #: Freshly read state, so a retry uses current values not stale ones.
    #: 重新讀到的最新狀態，補點時要用它而不是舊的。
    fresh_states: dict = field(default_factory=dict)
    #: The board on screen is no longer the one we solved (usually: completed).
    #: 畫面上已經不是我們解的那盤棋（通常代表已完成）。
    board_changed: bool = False

    def summary(self) -> str:
        if self.board_changed:
            return "board changed (probably finished) - stopping / 畫面已改變（可能已完成），停止操作"
        if not self.supported:
            return f"cannot verify this puzzle / 這種謎題無法自動驗證: {self.reason}"
        if self.ok:
            return f"verified: {self.filled}/{self.total} correct / 驗證通過"
        return f"{len(self.mismatches)} cell(s) still wrong ({self.filled}/{self.total} ok) / 格未完成"


# ---------------------------------------------------------------------------
def _queens_board_unchanged(image: np.ndarray, result, n_hint):
    """Is this still the same Queens board? Returns (grid, unchanged).
    畫面上還是原本那盤 Queens 嗎？回傳 (grid, 是否相同)。"""
    try:
        grid = build_grid(image, n_hint=n_hint)
    except Exception:
        return None, False

    original = result.data.get("region_ids")
    if original is None:
        return grid, True
    if grid.n != len(original):
        return grid, False

    fresh, _ = queens.read_regions(image, grid)
    if not queens.regions_look_valid(fresh, grid.n):
        return grid, False

    # Compare WHICH CELLS SHARE A REGION, not the region ids themselves - ids are
    # assigned by colour frequency and can permute between two recognitions.
    # For each original region, find the fresh region most of its cells map to.
    # 比對「哪些格子被分在同一區」而不是區域編號本身 —— 編號是依顏色出現次數
    # 排出來的，兩次辨識之間可能整組換位置。作法是對每個原始區域，找出它的格子
    # 在新結果中最常對應到哪一區。
    n = grid.n
    cells_by_region: dict[int, list[tuple[int, int]]] = {}
    for r in range(n):
        for c in range(n):
            cells_by_region.setdefault(original[r][c], []).append((r, c))

    agree = 0
    for cells in cells_by_region.values():
        counts: dict[int, int] = {}
        for r, c in cells:
            counts[fresh[r][c]] = counts.get(fresh[r][c], 0) + 1
        agree += max(counts.values())
    return grid, agree >= n * n * 0.85


def _verify_queens(image: np.ndarray, result, n_hint) -> VerifyReport:
    grid, unchanged = _queens_board_unchanged(image, result, n_hint)
    if grid is None or not unchanged:
        return VerifyReport(supported=True, ok=True, board_changed=True)

    states = queens.read_cell_states(image, grid)
    wanted = list(result.data["queens"])
    mismatches, filled = [], 0
    for r, c in wanted:
        if states.get((r, c)) == queens.STATE_QUEEN:
            filled += 1
        else:
            mismatches.append((r, c, states.get((r, c)) or "empty/空白", "crown/皇冠"))

    extra = [pos for pos, s in states.items() if s == queens.STATE_QUEEN and pos not in set(wanted)]
    for r, c in extra:
        mismatches.append((r, c, "extra crown/多餘皇冠", "empty/空白"))

    return VerifyReport(supported=True, ok=not mismatches, mismatches=mismatches,
                        filled=filled, total=len(wanted), fresh_states=states)


def _verify_tango(image: np.ndarray, result, n_hint) -> VerifyReport:
    solution, givens = result.data["solution"], result.data["givens"]
    grid = tango._locate_board(image, n_hint or tango.DEFAULT_GRID_SIZE)
    if grid is None or grid.n != len(solution):
        return VerifyReport(supported=True, ok=True, board_changed=True)

    _puzzle, current = tango.read_board(image, grid)
    targets = [(r, c) for r in range(grid.n) for c in range(grid.n) if (r, c) not in givens]
    mismatches, filled = [], 0
    for r, c in targets:
        if current.get((r, c)) == solution[r][c]:
            filled += 1
        else:
            mismatches.append((r, c, current.get((r, c)), solution[r][c]))
    return VerifyReport(supported=True, ok=not mismatches, mismatches=mismatches,
                        filled=filled, total=len(targets), fresh_states=current)


def _verify_sudoku(image: np.ndarray, result, n_hint) -> VerifyReport:
    solution, givens = result.data["solution"], result.data["givens"]
    try:
        grid = build_grid(image, n_hint=n_hint)
    except Exception:
        return VerifyReport(supported=True, ok=True, board_changed=True)
    if grid.n != len(solution):
        return VerifyReport(supported=True, ok=True, board_changed=True)

    now = sudoku.read_givens(image, grid)
    # If the puzzle's own printed digits no longer match, this is a different screen.
    # 題目原本就印在盤上的數字若對不上，代表已經不是同一個畫面。
    still_same = sum(1 for pos, v in givens.items() if now.get(pos) == v)
    if givens and still_same < len(givens) * 0.7:
        return VerifyReport(supported=True, ok=True, board_changed=True)

    targets = [(r, c) for r in range(grid.n) for c in range(grid.n) if (r, c) not in givens]
    mismatches, filled = [], 0
    for r, c in targets:
        if now.get((r, c)) == solution[r][c]:
            filled += 1
        else:
            mismatches.append((r, c, now.get((r, c)), solution[r][c]))
    return VerifyReport(supported=True, ok=not mismatches, mismatches=mismatches,
                        filled=filled, total=len(targets), fresh_states=now)


_VERIFIERS = {queens.KEY: _verify_queens, tango.KEY: _verify_tango, sudoku.KEY: _verify_sudoku}


def verify(image: np.ndarray, result, n_hint: int | None = None) -> VerifyReport:
    verifier = _VERIFIERS.get(result.puzzle_key)
    if verifier is None:
        return VerifyReport(supported=False, reason=f"{result.puzzle_key}: answer cannot be read back / 讀不回作答結果")
    try:
        return verifier(image, result, n_hint)
    except Exception as exc:  # noqa: BLE001
        return VerifyReport(supported=False, reason=f"{type(exc).__name__}: {exc}")


def build_retry_plan(result, mapper, report: VerifyReport):
    """A plan that only touches the cells that are still wrong.
    只處理還沒填對的格子的補點計畫。"""
    from .players import build_plan

    # Never click again once the board has changed - the content is different now.
    # 盤面已經改變就絕對不能再點 —— 上面的內容已經不一樣了。
    if report.board_changed:
        return None

    key = result.puzzle_key
    wrong = {(r, c) for r, c, _got, _want in report.mismatches}
    data = dict(result.data)

    if key == tango.KEY:
        # Marking everything else as "given" makes the player skip those cells.
        # 把其他格子標成 given，player 就會跳過它們。
        data["givens"] = {
            (r, c) for r in range(mapper.n) for c in range(mapper.n) if (r, c) not in wrong
        }
        data["current"] = report.fresh_states or data.get("current", {})
        return build_plan(key, mapper, data)

    if key == sudoku.KEY:
        data["givens"] = {
            (r, c): result.data["solution"][r][c]
            for r in range(mapper.n) for c in range(mapper.n) if (r, c) not in wrong
        }
        return build_plan(key, mapper, data)

    if key == queens.KEY:
        missing = {(r, c) for r, c, _got, want in report.mismatches if "crown" in str(want)}
        extra = {(r, c) for r, c, got, _want in report.mismatches if "extra" in str(got)}
        if not missing and not extra:
            return None
        data["queens"] = [pos for pos in result.data["queens"] if pos in missing]
        # Use the freshly read states, and only for the cells we intend to touch,
        # so untouched cells cannot be disturbed.
        # 用剛剛重新讀到的狀態，而且只保留要動的格子，避免影響其他格。
        data["cell_states"] = {
            pos: state for pos, state in report.fresh_states.items()
            if pos in missing or pos in extra
        }
        return build_plan(key, mapper, data)

    return None
