"""
執行辨識 + 求解，並回傳「填答需要的結構化資料」。

既有專案的 analyze() 回傳的是文字報告與疊圖，適合給人看；
但自動填答需要的是座標層級的資料 (哪一格填什麼、路徑怎麼走)。
所以這裡直接呼叫既有專案裡的偵測與求解函式取得結構化結果，
一樣**不修改**既有專案的任何檔案。
"""

from dataclasses import dataclass, field
from typing import Any

import cv2
import numpy as np

import solver_bridge  # noqa: F401  匯入時會把 tango_solver 加進 sys.path

import patches_ext  # noqa: E402
import puzzle_type  # noqa: E402
import queens_ext  # noqa: E402
import tango_ext  # noqa: E402
import board  # noqa: E402
import pipeline  # noqa: E402
import puzzle_patches  # noqa: E402
import puzzle_queens  # noqa: E402
import puzzle_sudoku  # noqa: E402
import puzzle_zip  # noqa: E402
import solver as tango_solver  # noqa: E402
from solver_bridge import build_board_grid  # noqa: E402


@dataclass
class SolveOutcome:
    ok: bool
    puzzle_key: str
    error: str | None = None
    grid: Any = None
    data: dict = field(default_factory=dict)
    info: list[str] = field(default_factory=list)


def _solve_tango(image: np.ndarray, n_hint: int | None) -> SolveOutcome:
    # 先用格線定位棋盤 (最準)；失敗才退回既有專案用圖示位置反推的作法。
    # 用圖示反推在網頁版會整個偏一格，導致最外圈的 =/× 符號完全讀不到。
    grid = tango_ext.build_grid(image, n_hint or 6)
    if grid is not None:
        puzzle, current, _readings = tango_ext.build_puzzle(image, grid)
    else:
        puzzle, current, grid, _readings = pipeline.build_puzzle_from_image(image, n_hint or 6)
    info = [
        f"棋盤 {grid.n}x{grid.n}",
        f"given {len(puzzle.givens)} 格, =/× 符號 {len(puzzle.h_edges) + len(puzzle.v_edges)} 個",
    ]
    try:
        # 這裡刻意要求「解必須唯一」：真正的 Tango 題目一定只有一組解。
        # 如果辨識漏掉了 given 或 =/× 符號，剩下的條件通常會允許很多組解 ——
        # 這時求解器還是會吐出一組「符合它看到的條件」的答案，但那是錯的。
        # 用唯一性當作辨識完整度的檢查，就能把這種「悄悄給錯答案」擋掉，
        # 讓外層的裁切/縮放重試機制去找到能完整辨識的尺度。
        solution = tango_solver.solve(puzzle, check_unique=True)
    except (tango_solver.NoSolutionError, tango_solver.MultipleSolutionsError) as e:
        return SolveOutcome(ok=False, puzzle_key="tango", error=str(e), grid=grid, info=info)

    return SolveOutcome(
        ok=True, puzzle_key="tango", grid=grid, info=info,
        data={
            "solution": solution,
            "givens": set(puzzle.givens.keys()),
            "current": current,
        },
    )


def _solve_queens(image: np.ndarray, n_hint: int | None) -> SolveOutcome:
    grid = board.build_grid(image, n_hint=n_hint)
    # 用擴充版讀色塊：盤面上可能已經放了皇冠或 X 標記，
    # 既有專案取格子正中央的顏色會取到圖案本身而不是色塊顏色
    region_ids, palette = queens_ext.read_regions(image, grid)
    info = [f"棋盤 {grid.n}x{grid.n}", f"色塊區域 {len(palette)} 個"]
    if not queens_ext.regions_look_valid(region_ids, grid.n):
        return SolveOutcome(
            ok=False, puzzle_key="queens", grid=grid, info=info,
            error="色塊分群結果不合理 (有區域是空的或被切成不相連的兩塊)，顏色辨識可能有誤",
        )
    queens = puzzle_queens.solve(grid.n, region_ids)
    if queens is None:
        return SolveOutcome(ok=False, puzzle_key="queens", grid=grid, info=info, error="找不到符合規則的解")

    states = queens_ext.read_cell_states(image, grid)
    already = {pos for pos, s in states.items() if s == queens_ext.STATE_QUEEN}
    if already:
        info.append(f"畫面上已經放了 {len(already)} 個皇冠，填答時會跳過")
    return SolveOutcome(
        ok=True, puzzle_key="queens", grid=grid, info=info,
        data={
            "queens": queens,
            "already_placed": already,
            "cell_states": states,
            # 留著原本的色塊分佈：填答後要用它確認「畫面上還是同一盤棋」，
            # 解完後網頁會播完成動畫、盤面外觀整個改變，這時不能再繼續點。
            "region_ids": region_ids,
        },
    )


def _solve_sudoku(image: np.ndarray, n_hint: int | None) -> SolveOutcome:
    grid = board.build_grid(image, n_hint=n_hint)
    box_h, box_w = puzzle_sudoku.detect_box_shape(image, grid)
    givens = puzzle_sudoku.read_givens(image, grid)
    info = [f"棋盤 {grid.n}x{grid.n}", f"宮 {box_h}x{box_w}", f"已填數字 {len(givens)} 個"]
    if not givens:
        return SolveOutcome(ok=False, puzzle_key="sudoku", grid=grid, info=info, error="讀不到任何已填數字")
    solution = puzzle_sudoku.solve(grid.n, box_h, box_w, givens)
    if solution is None:
        return SolveOutcome(ok=False, puzzle_key="sudoku", grid=grid, info=info, error="找不到符合規則的解")
    # 同樣用「解必須唯一」檢查數字有沒有漏讀 (漏讀會讓解變多組，答案就不可信)
    if not _sudoku_solution_is_unique(grid.n, box_h, box_w, givens):
        return SolveOutcome(
            ok=False, puzzle_key="sudoku", grid=grid, info=info,
            error="解不唯一，代表有數字沒讀到，答案不可信",
        )
    return SolveOutcome(
        ok=True, puzzle_key="sudoku", grid=grid, info=info,
        data={"solution": solution, "givens": givens},
    )


def _sudoku_solution_is_unique(n: int, box_h: int, box_w: int, givens: dict) -> bool:
    """數獨題目一定只有一組解；若能找到兩組，代表有數字沒被讀出來。"""
    from ortools.sat.python import cp_model

    model = cp_model.CpModel()
    cells = [[model.NewIntVar(1, n, f"c{r}_{c}") for c in range(n)] for r in range(n)]
    for (r, c), v in givens.items():
        model.Add(cells[r][c] == v)
    for r in range(n):
        model.AddAllDifferent(cells[r])
    for c in range(n):
        model.AddAllDifferent([cells[r][c] for r in range(n)])
    for br in range(0, n, box_h):
        for bc in range(0, n, box_w):
            model.AddAllDifferent(
                [cells[r][c] for r in range(br, br + box_h) for c in range(bc, bc + box_w)]
            )

    class _Counter(cp_model.CpSolverSolutionCallback):
        def __init__(self):
            super().__init__()
            self.count = 0

        def on_solution_callback(self):
            self.count += 1
            if self.count >= 2:
                self.StopSearch()

    counter = _Counter()
    solver = cp_model.CpSolver()
    solver.parameters.enumerate_all_solutions = True
    solver.parameters.max_time_in_seconds = 10.0
    solver.Solve(model, counter)
    return counter.count == 1


def _solve_zip(image: np.ndarray, n_hint: int | None) -> SolveOutcome:
    grid = board.build_grid(image, n_hint=n_hint)
    dots = puzzle_zip.find_dots(image, grid)
    h_walls, v_walls = puzzle_zip.find_walls(image, grid)
    info = [
        f"棋盤 {grid.n}x{grid.n}",
        f"編號圓點 {len(dots)} 個, 牆 {len(h_walls)}+{len(v_walls)} 道",
    ]
    if len(dots) < 2:
        return SolveOutcome(ok=False, puzzle_key="zip", grid=grid, info=info, error="編號圓點少於 2 個")
    values = sorted(dots.values())
    if values != list(range(1, len(values) + 1)):
        return SolveOutcome(ok=False, puzzle_key="zip", grid=grid, info=info, error=f"圓點編號不連續 {values}")
    path = puzzle_zip.solve(grid.n, dots, h_walls, v_walls)
    if path is None:
        return SolveOutcome(ok=False, puzzle_key="zip", grid=grid, info=info, error="找不到符合規則的路徑")
    return SolveOutcome(ok=True, puzzle_key="zip", grid=grid, info=info, data={"path": path, "dots": dots})


def _solve_patches(image: np.ndarray, n_hint: int | None) -> SolveOutcome:
    grid = board.build_grid(image, n_hint=n_hint)
    labels = puzzle_patches.find_labels(image, grid)
    info = [f"棋盤 {grid.n}x{grid.n}", f"標籤 {len(labels)} 個"]
    if not labels:
        return SolveOutcome(ok=False, puzzle_key="patches", grid=grid, info=info, error="找不到任何標籤")
    # 防呆：真正的 Patches 題目一定有好幾個標籤。標籤太少通常代表
    # 這根本不是 Patches (謎題類型判斷錯了)，此時若硬解會得到一個
    # 「用一兩塊矩形蓋滿整個盤面」的無意義答案，卻回報成功。
    if len(labels) < 3:
        return SolveOutcome(
            ok=False, puzzle_key="patches", grid=grid, info=info,
            error=f"只找到 {len(labels)} 個標籤，不像是 Patches 題目；"
                  "請確認謎題類型是否判斷正確 (可在上方手動指定)",
        )

    # 沒有數字的標籤代表「大小不限」，是合法的題目；只有「有字但讀不出來」才算辨識失敗
    usable, unreadable = patches_ext.classify_labels(labels, image=image)
    if unreadable:
        # 數字讀不出來時，先試著把它當成「大小不限」再解一次。
        # 如果這樣切法仍然唯一，代表答案跟那個數字無關，可以安心採用；
        # 只有在切法不唯一時才真的算失敗。
        where = "、".join(f"({lb.row + 1},{lb.col + 1})" for lb in unreadable)
        relaxed = usable + unreadable
        rects = patches_ext.solve_unique(grid.n, relaxed)
        if rects is not None:
            info.append(f"標籤 {where} 的數字讀不出來，但忽略它之後切法仍然唯一，可安心使用")
            return SolveOutcome(
                ok=True, puzzle_key="patches", grid=grid, info=info,
                data={"rects": rects, "labels": relaxed},
            )
        return SolveOutcome(
            ok=False, puzzle_key="patches", grid=grid, info=info,
            error=f"有 {len(unreadable)} 個標籤的數字讀不出來 (位置 {where})，"
                  "且忽略它們之後切法不唯一，無法確定答案",
        )

    blank_count = sum(1 for lb in usable if lb.value is None)
    if blank_count:
        info.append(f"其中 {blank_count} 個標籤沒有數字 (大小不限)")

    numbered_total = sum(lb.value for lb in usable if lb.value is not None)
    if blank_count == 0:
        if numbered_total != grid.n * grid.n:
            return SolveOutcome(
                ok=False, puzzle_key="patches", grid=grid, info=info,
                error=f"標籤數字總和 ({numbered_total}) 不等於格數 ({grid.n * grid.n})",
            )
    elif numbered_total >= grid.n * grid.n:
        return SolveOutcome(
            ok=False, puzzle_key="patches", grid=grid, info=info,
            error=f"標籤數字總和 ({numbered_total}) 已經不小於格數 ({grid.n * grid.n})，"
                  "但還有大小不限的標籤要放，數字辨識可能有誤",
        )

    rects = patches_ext.solve(grid.n, usable)
    if rects is None:
        return SolveOutcome(ok=False, puzzle_key="patches", grid=grid, info=info, error="找不到符合規則的切法")
    return SolveOutcome(
        ok=True, puzzle_key="patches", grid=grid, info=info,
        data={"rects": rects, "labels": usable},
    )


_SOLVERS = {
    "tango": _solve_tango,
    "queens": _solve_queens,
    "sudoku": _solve_sudoku,
    "zip": _solve_zip,
    "patches": _solve_patches,
}


#: 找棋盤時的預先放大倍率。棋盤太小時淡色邊框 (例如 Patches 的虛線) 會偵測不到，
#: 放大後才找得到。
_PRESCALE_STEPS = (1.0, 1.75, 2.5)

#: 找到棋盤後，會把整張畫面縮放成「棋盤約這麼大」再做辨識。
#: 既有專案的辨識門檻與數字範本都是在手機截圖 (棋盤約 800px) 上校準的，
#: 先正規化到同樣尺度，辨識結果會穩定很多。
#: 實測 Patches 在未正規化時，棋盤 506px/635px 可行但 529~719px 之間會讀錯數字；
#: 正規化之後從 500px 到原尺寸都能穩定辨識。
TARGET_BOARD_PIXELS = 794

#: 建議的棋盤最小邊長。低於這個大小，Patches 的標籤數字會糊到讀不出來。
MIN_BOARD_PIXELS = 500


def _rescale_grid(grid, factor: float, offset: tuple[int, int] = (0, 0)):
    """
    把在「縮放過、而且可能有裁切過」的影像上偵測到的棋盤座標，
    換算回最原始那張影像的座標。
    """
    ox, oy = offset
    if factor == 1.0 and ox == 0 and oy == 0:
        return grid
    x, y, w, h = grid.board_bbox
    bbox = (round(x / factor) + ox, round(y / factor) + oy, round(w / factor), round(h / factor))
    cell_boxes = [
        [
            (round(cx / factor) + ox, round(cy / factor) + oy, round(cw / factor), round(ch / factor))
            for (cx, cy, cw, ch) in row
        ]
        for row in grid.cell_boxes
    ]
    return board.BoardGrid(n=grid.n, board_bbox=bbox, cell_boxes=cell_boxes)


#: 依序嘗試的「置中裁切比例」。
#:
#: Tango 的棋盤沒有外框，既有專案是用格內圖示的分佈反推棋盤範圍，而它把
#: 「畫面較短邊 / 格數」當成預期的格子邊長。如果擷取範圍比棋盤大很多，
#: 這個預期值就會偏太大而認不出真正的棋盤。所以擷取範圍偏大時，
#: 會再往中間裁緊一點重試。
_CROP_FRACTIONS = (1.0, 0.85, 0.72, 0.6, 0.5)


def _renormalise(sub: np.ndarray, outcome: SolveOutcome, factor: float, puzzle_key, n_hint):
    """
    辨識成功之後，再用「棋盤正好是校準尺度」的縮放重跑一次。

    為什麼必要：辨識成功不代表辨識**正確**。實測 Tango 的棋盤縮到約 390px 時，
    4 個 =/× 符號只會抓到 1 個 —— 求解器仍然會吐出一組「符合它看到的那些條件」
    的答案，但那是錯的答案。這種錯比直接失敗更危險。
    既有專案的各種門檻是在棋盤約 800px 上校準的，所以這裡一律再用正規化後的
    尺度重算一次，並以重算的結果為準。
    """
    detected_width = outcome.grid.board_bbox[2]
    if detected_width <= 0:
        return factor, outcome
    board_width_in_sub = detected_width / factor
    ideal = TARGET_BOARD_PIXELS / board_width_in_sub

    if abs(ideal - factor) / max(ideal, factor) <= 0.15:
        return factor, outcome  # 已經接近校準尺度了

    better = _attempt(_scaled(sub, ideal), puzzle_key, n_hint)
    if better.ok:
        return ideal, better
    return factor, outcome


def _center_crop(image: np.ndarray, fraction: float) -> tuple[np.ndarray, tuple[int, int]]:
    if fraction >= 1.0:
        return image, (0, 0)
    h, w = image.shape[:2]
    nw, nh = int(w * fraction), int(h * fraction)
    ox, oy = (w - nw) // 2, (h - nh) // 2
    return image[oy : oy + nh, ox : ox + nw], (ox, oy)


def _attempt(image: np.ndarray, puzzle_key: str | None, n_hint: int | None) -> SolveOutcome:
    # 用 puzzle_type 而不是既有專案的 registry.detect_type：
    # 後者靠「彩色像素比例」認 Queens，遇到淡色系的 Queens 盤面會誤判成 Patches，
    # 然後用 Patches 的邏輯「解」出一個無意義的答案卻回報成功。
    key = puzzle_key or puzzle_type.detect_type(image)
    if key not in _SOLVERS:
        return SolveOutcome(ok=False, puzzle_key=key, error=f"不支援的謎題類型: {key}")
    try:
        return _SOLVERS[key](image, n_hint)
    except ValueError as e:
        return SolveOutcome(ok=False, puzzle_key=key, error=f"辨識失敗: {e}")
    except Exception as e:  # noqa: BLE001 - 這裡要把任何辨識例外轉成可讀訊息
        return SolveOutcome(ok=False, puzzle_key=key, error=f"處理時發生錯誤: {type(e).__name__}: {e}")


def _locate_board(image: np.ndarray) -> tuple[float, tuple[int, int, int, int]] | None:
    """
    找出棋盤位置，必要時先放大再找。回傳 (預先放大倍率, 該倍率下的 bbox)。
    Tango 的棋盤沒有外框，改用既有專案的內容定位法。
    """
    for pre in _PRESCALE_STEPS:
        candidate = (
            image if pre == 1.0
            else cv2.resize(image, None, fx=pre, fy=pre, interpolation=cv2.INTER_CUBIC)
        )
        bbox = board.find_board_bbox(candidate)
        if bbox is None:
            try:
                bbox = grid_detector.detect_board_bbox_by_content(candidate, 6)
            except Exception:
                bbox = None
        if bbox is not None:
            return pre, bbox
    return None


def _scaled(image: np.ndarray, factor: float) -> np.ndarray:
    if abs(factor - 1.0) < 1e-6:
        return image
    interp = cv2.INTER_CUBIC if factor > 1 else cv2.INTER_AREA
    return cv2.resize(image, None, fx=factor, fy=factor, interpolation=interp)


def solve_from_image(image: np.ndarray, puzzle_key: str | None = None, n_hint: int | None = None) -> SolveOutcome:
    """
    辨識並求解。回傳的 grid 座標一律是「相對於傳入的原始影像」，
    即使內部有縮放也一樣，這樣呼叫端換算螢幕座標時不用管縮放。
    """
    last = None

    for fraction in _CROP_FRACTIONS:
        sub, offset = _center_crop(image, fraction)
        if min(sub.shape[:2]) < 120:
            break

        candidates: list[float] = []
        located = _locate_board(sub)
        if located is not None:
            pre, bbox = located
            # 直接從裁切後的圖一次縮放到目標尺度，避免重複重採樣讓字形糊掉
            candidates.append(pre * (TARGET_BOARD_PIXELS / bbox[2]))
        candidates.extend(_PRESCALE_STEPS)

        tried: list[float] = []
        for factor in candidates:
            if any(abs(factor - t) < 0.02 for t in tried):
                continue
            tried.append(factor)

            outcome = _attempt(_scaled(sub, factor), puzzle_key, n_hint)
            if outcome.ok:
                factor, outcome = _renormalise(sub, outcome, factor, puzzle_key, n_hint)
                outcome.grid = _rescale_grid(outcome.grid, factor, offset)
                notes = []
                if fraction < 1.0:
                    notes.append(f"往中間裁切 {fraction:.0%}")
                if abs(factor - 1.0) > 0.02:
                    notes.append(f"縮放 {factor:.2f}x")
                if notes:
                    outcome.info.append("(" + "、".join(notes) + " 後辨識成功)")
                return outcome
            last = last or outcome

    # 棋盤在畫面上太小是最常見的失敗原因，特別是 Patches 的標籤數字會糊掉
    board_px = None
    bbox = board.find_board_bbox(image)
    if bbox is not None:
        board_px = bbox[2]
    if board_px is None or board_px < MIN_BOARD_PIXELS:
        hint = (
            f"棋盤在畫面上只有約 {board_px}px" if board_px else "在畫面上找不到棋盤"
        )
        last.error = (
            f"{last.error}\n提示: {hint}。棋盤太小會辨識不準 "
            f"(建議至少 {MIN_BOARD_PIXELS}px)，請在瀏覽器按 Ctrl + 加號放大頁面後再試。"
        )
    return last


def render_overlay(image: np.ndarray, puzzle_key: str, n_hint: int | None = None, debug: bool = False):
    """借用既有專案的疊圖功能產生預覽圖 (方便確認辨識是否正確)。"""
    module = solver_bridge.PUZZLES[puzzle_key]
    result = module.analyze(image, n_hint=n_hint, debug=debug)
    return result
