"""
填答後的驗證與補點。

自動點擊不保證每一下都會被網頁收到 (視窗剛切換、頁面還在載入、動畫進行中
都可能吃掉點擊)。所以填完之後重新擷取畫面、重新辨識一次，比對「畫面現在的
狀態」與「應該要的答案」，把沒填到或填錯的格子列出來，必要時再補點。

目前支援可以直接從畫面讀出目前狀態的兩種謎題：
  Tango   ─ 每格是太陽/月亮/空白，可直接讀
  Sudoku  ─ 每格的數字可直接讀

Queens / Zip / Patches 的作答結果 (皇冠、路徑線、切割線) 既有專案沒有對應的
辨識器，所以無法自動驗證，會回報「不支援驗證」。
"""

from dataclasses import dataclass, field

import numpy as np

import solver_bridge  # noqa: F401  匯入時會把 tango_solver 加進 sys.path

import board  # noqa: E402
import pipeline  # noqa: E402
import puzzle_sudoku  # noqa: E402

SUPPORTED = {"tango", "sudoku"}


@dataclass
class VerifyReport:
    supported: bool
    ok: bool = False
    reason: str = ""
    #: 還沒填對的格子: (row, col, 目前狀態, 應該要的狀態)
    mismatches: list[tuple[int, int, object, object]] = field(default_factory=list)
    filled: int = 0
    total: int = 0
    #: 重新擷取後讀到的每格最新狀態 (補點時要用最新的，不能用第一次擷取的舊狀態)
    fresh_states: dict = field(default_factory=dict)
    #: 畫面上已經不是原本那盤棋了 (通常代表解完後跳出完成畫面)。
    #: 這種情況絕對不能再補點 —— 盤面內容都變了，再點只是亂點。
    board_changed: bool = False

    def summary(self) -> str:
        if self.board_changed:
            return "畫面已經不是原本那盤棋 (可能已完成)，停止操作"
        if not self.supported:
            return f"這種謎題無法自動驗證: {self.reason}"
        if self.ok:
            return f"驗證通過: {self.filled}/{self.total} 格都正確"
        return f"還有 {len(self.mismatches)} 格不正確 ({self.filled}/{self.total} 已正確)"


def _verify_tango(image: np.ndarray, outcome, n_hint: int | None) -> VerifyReport:
    solution = outcome.data["solution"]
    givens = outcome.data["givens"]
    try:
        _puzzle, current, grid, _readings = pipeline.build_puzzle_from_image(image, n_hint or 6)
    except Exception:
        # 連棋盤都找不到了 -> 畫面已經換掉 (多半是解完的完成畫面)
        return VerifyReport(supported=True, ok=True, board_changed=True)
    if grid.n != len(solution):
        return VerifyReport(supported=True, ok=True, board_changed=True)

    mismatches = []
    filled = 0
    target_cells = [
        (r, c) for r in range(grid.n) for c in range(grid.n) if (r, c) not in givens
    ]
    for r, c in target_cells:
        want = solution[r][c]
        got = current.get((r, c))
        if got == want:
            filled += 1
        else:
            mismatches.append((r, c, got, want))

    return VerifyReport(
        supported=True, ok=not mismatches, mismatches=mismatches,
        filled=filled, total=len(target_cells),
    )


def _verify_sudoku(image: np.ndarray, outcome, n_hint: int | None) -> VerifyReport:
    solution = outcome.data["solution"]
    givens = outcome.data["givens"]
    try:
        grid = board.build_grid(image, n_hint=n_hint)
    except Exception:
        return VerifyReport(supported=True, ok=True, board_changed=True)
    if grid.n != len(solution):
        return VerifyReport(supported=True, ok=True, board_changed=True)

    now = puzzle_sudoku.read_givens(image, grid)
    # 題目原本就有的數字若對不上，代表畫面已經不是同一盤 (例如完成畫面)
    still_same = sum(1 for pos, v in givens.items() if now.get(pos) == v)
    if givens and still_same < len(givens) * 0.7:
        return VerifyReport(supported=True, ok=True, board_changed=True)

    mismatches = []
    filled = 0
    target_cells = [
        (r, c) for r in range(grid.n) for c in range(grid.n) if (r, c) not in givens
    ]
    for r, c in target_cells:
        want = solution[r][c]
        got = now.get((r, c))
        if got == want:
            filled += 1
        else:
            mismatches.append((r, c, got, want))

    return VerifyReport(
        supported=True, ok=not mismatches, mismatches=mismatches,
        filled=filled, total=len(target_cells),
    )


def _board_still_the_same(image: np.ndarray, outcome, n_hint: int | None) -> tuple[object, bool]:
    """
    確認畫面上還是原本那盤棋。回傳 (grid, 是否相同)。

    解完之後網頁會播完成動畫、或整個換掉盤面外觀。這時如果還照常「驗證 -> 補點」，
    就會因為讀不到皇冠而繼續亂點 —— 使用者看到的就是「明明已經完成了，
    滑鼠還被程式一直控制」。所以補點前一定要先確認盤面沒變。
    """
    import queens_ext

    try:
        grid = board.build_grid(image, n_hint=n_hint)
    except Exception:
        return None, False

    original = outcome.data.get("region_ids")
    if original is None:
        return grid, True
    if grid.n != len(original):
        return grid, False

    fresh, _palette = queens_ext.read_regions(image, grid)
    if not queens_ext.regions_look_valid(fresh, grid.n):
        return grid, False

    # 比對「哪些格子被分在同一區」，而不是直接比對區域編號 ——
    # 編號是依顏色出現次數排出來的，兩次辨識之間可能整組換位置。
    # 作法：對每個原始區域，找出它的格子在新結果中最常對應到哪一區，
    # 再看有多少格子符合這個對應關係。
    n = grid.n
    cells_by_region: dict[int, list[tuple[int, int]]] = {}
    for r in range(n):
        for c in range(n):
            cells_by_region.setdefault(original[r][c], []).append((r, c))

    agree = 0
    for cells in cells_by_region.values():
        counts: dict[int, int] = {}
        for r, c in cells:
            key = fresh[r][c]
            counts[key] = counts.get(key, 0) + 1
        agree += max(counts.values())

    return grid, agree >= n * n * 0.85


def _verify_queens(image: np.ndarray, outcome, n_hint: int | None) -> VerifyReport:
    import queens_ext

    grid, unchanged = _board_still_the_same(image, outcome, n_hint)
    if grid is None or not unchanged:
        return VerifyReport(supported=True, ok=True, board_changed=True)

    states = queens_ext.read_cell_states(image, grid)
    wanted = list(outcome.data["queens"])

    mismatches = []
    filled = 0
    for r, c in wanted:
        state = states.get((r, c))
        if state == queens_ext.STATE_QUEEN:
            filled += 1
        else:
            mismatches.append((r, c, state or "空白", "皇冠"))

    # 也要檢查有沒有多放：不該有皇冠的地方卻有
    extra = [pos for pos, s in states.items() if s == queens_ext.STATE_QUEEN and pos not in set(wanted)]
    for r, c in extra:
        mismatches.append((r, c, "多餘的皇冠", "應該是空白"))

    return VerifyReport(
        supported=True, ok=not mismatches, mismatches=mismatches,
        filled=filled, total=len(wanted), fresh_states=states,
    )


_VERIFIERS = {"tango": _verify_tango, "sudoku": _verify_sudoku, "queens": _verify_queens}


def verify(image: np.ndarray, outcome, n_hint: int | None = None) -> VerifyReport:
    key = outcome.puzzle_key
    if key not in _VERIFIERS:
        return VerifyReport(
            supported=False,
            reason=f"{key} 的作答結果 (皇冠/路徑/切割線) 沒有對應的辨識器",
        )
    try:
        return _VERIFIERS[key](image, outcome, n_hint)
    except Exception as e:  # noqa: BLE001
        return VerifyReport(supported=False, reason=f"驗證時發生錯誤: {type(e).__name__}: {e}")


def build_retry_plan(outcome, mapper, report: VerifyReport):
    """針對還沒填對的格子，產生一份只補這些格子的填答計畫。"""
    from players import PLAYERS

    # 畫面已經不是原本那盤棋 (多半是解完跳出完成畫面)，絕對不能再點
    if report.board_changed:
        return None

    key = outcome.puzzle_key
    if key == "tango":
        # 只保留還沒填對的格子：把其他格子當成 given 就不會被再點一次
        wrong = {(r, c) for r, c, _got, _want in report.mismatches}
        trimmed = dict(outcome.data)
        trimmed["givens"] = {
            (r, c)
            for r in range(mapper.n)
            for c in range(mapper.n)
            if (r, c) not in wrong
        }
        # current 用實際讀到的狀態，讓 player 決定要點幾下
        return PLAYERS[key](mapper).build_plan(trimmed)

    if key == "sudoku":
        wrong = {(r, c) for r, c, _got, _want in report.mismatches}
        trimmed = dict(outcome.data)
        trimmed["givens"] = {
            (r, c): outcome.data["solution"][r][c]
            for r in range(mapper.n)
            for c in range(mapper.n)
            if (r, c) not in wrong
        }
        return PLAYERS[key](mapper).build_plan(trimmed)

    if key == "queens":
        missing = {(r, c) for r, c, _got, want in report.mismatches if want == "皇冠"}
        extra = {(r, c) for r, c, got, _want in report.mismatches if got == "多餘的皇冠"}
        if not missing and not extra:
            return None
        trimmed = dict(outcome.data)
        # 只處理需要動的格子：要補的放進 queens，放錯的靠 cell_states 讓 player 清掉
        trimmed["queens"] = [pos for pos in outcome.data["queens"] if pos in missing]
        # 用剛剛重新擷取讀到的狀態，才能算對「還要再點幾下」；
        # 只保留「要補的」與「要清掉的」，其他格子不要出現，才不會被誤動。
        trimmed["cell_states"] = {
            pos: state
            for pos, state in report.fresh_states.items()
            if pos in missing or pos in extra
        }
        return PLAYERS[key](mapper).build_plan(trimmed)

    return None
