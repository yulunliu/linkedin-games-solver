"""
Turn a solved puzzle into a sequence of mouse actions.
把解好的答案轉成一連串滑鼠操作。

Each game is played differently, so there is one player per game. The click
counts below follow each game's own on-screen instructions.
每款遊戲的操作方式不同，所以每款一個 player。下面的點擊次數都依照
各遊戲畫面上寫的玩法。

IMPORTANT - click counts depend on the CURRENT state, not just the target:
  these games cycle through states on repeated clicks (Tango: empty -> sun ->
  moon -> empty; Queens: empty -> X -> crown -> empty). Assuming a cell starts
  empty would overshoot when resuming a half-finished board and turn a correct
  cell into a wrong one.
重要 —— 點擊次數取決於「目前狀態」而不只是目標：
  這些遊戲的格子是循環切換的（Tango：空白->太陽->月亮->空白；
  Queens：空白->X->皇冠->空白）。若一律假設從空白開始，接續填一半的盤面時
  就會點過頭，把原本正確的格子弄錯。
"""

from __future__ import annotations

from dataclasses import dataclass

from ..puzzles import patches, queens, sudoku, tango, zip_path
from .input_driver import InputDriver
from .mapper import BoardMapper


@dataclass
class PlayPlan:
    """What will be done, plus the callable that does it.
    要做什麼，以及實際執行的函式。"""

    description: list[str]
    run: object  # callable(driver: InputDriver) -> None


class BasePlayer:
    def __init__(self, mapper: BoardMapper):
        self.mapper = mapper

    def build_plan(self, data: dict) -> PlayPlan:
        raise NotImplementedError


# ---------------------------------------------------------------------------
class TangoPlayer(BasePlayer):
    """One click = sun, two = moon (cycle: empty -> sun -> moon -> empty).
    點一下 = 太陽，兩下 = 月亮（循環：空白 -> 太陽 -> 月亮 -> 空白）。"""

    #: Position of each state in the click cycle.
    #: 每個狀態在點擊循環中的位置。
    _CYCLE = {None: 0, tango.SUN: 1, tango.MOON: 2}

    def build_plan(self, data: dict) -> PlayPlan:
        solution, givens, current = data["solution"], data["givens"], data["current"]
        actions, description = [], []

        for r in range(self.mapper.n):
            for c in range(self.mapper.n):
                if (r, c) in givens:
                    continue
                target = solution[r][c]
                # Clicks = distance around the 3-state cycle from here to target.
                # 點擊次數 = 從目前狀態到目標，在三態循環上的距離。
                clicks = (self._CYCLE[target] - self._CYCLE.get(current.get((r, c)), 0)) % 3
                if clicks == 0:
                    continue
                x, y = self.mapper.cell_center(r, c)
                name = "sun/太陽" if target == tango.SUN else "moon/月亮"
                actions.append((x, y, clicks, f"({r+1},{c+1}) {name}"))
                description.append(f"  ({r+1},{c+1}) -> {name} x{clicks}")

        if not actions:
            description.append("  already complete / 盤面已完成")

        def run(driver: InputDriver):
            for x, y, clicks, label in actions:
                driver.click(x, y, clicks=clicks, label=label)

        return PlayPlan(description, run)


# ---------------------------------------------------------------------------
class QueensPlayer(BasePlayer):
    """Tap once for X, twice for a crown (per the in-game instructions).
    輕點一次放 X，兩次放皇后（依遊戲內說明）。"""

    def build_plan(self, data: dict) -> PlayPlan:
        wanted = list(data["queens"])
        wanted_set = set(wanted)
        states = data.get("cell_states") or {}
        actions, description = [], []

        # Clear crowns in the wrong place first. A previous failed run (or the
        # user experimenting) can leave stray crowns; without this the board can
        # never become correct. One more click turns a crown back to empty.
        # 先清掉放錯位置的皇冠。上一次跑失敗、或使用者自己亂點過都可能留下，
        # 不清掉的話盤面永遠不會正確。皇冠再點 1 下就會變回空白。
        for (r, c), state in sorted(states.items()):
            if state == queens.STATE_QUEEN and (r, c) not in wanted_set:
                x, y = self.mapper.cell_center(r, c)
                actions.append((x, y, 1, f"({r+1},{c+1}) clear/清掉"))
                description.append(f"  ({r+1},{c+1}) -> clear misplaced crown / 清掉放錯的皇冠")

        for r, c in wanted:
            clicks = queens.clicks_needed(states.get((r, c)))
            if clicks == 0:
                description.append(f"  ({r+1},{c+1}) -> already placed / 已放好，跳過")
                continue
            x, y = self.mapper.cell_center(r, c)
            actions.append((x, y, clicks, f"({r+1},{c+1}) crown/皇后"))
            description.append(f"  ({r+1},{c+1}) -> crown/皇后 x{clicks}")

        if not actions:
            description.append("  already complete / 盤面已完成")

        def run(driver: InputDriver):
            for x, y, clicks, label in actions:
                driver.click(x, y, clicks=clicks, label=label)

        return PlayPlan(description, run)


# ---------------------------------------------------------------------------
class SudokuPlayer(BasePlayer):
    """Click the cell, then press the digit key.
    點格子，再按數字鍵。"""

    def build_plan(self, data: dict) -> PlayPlan:
        solution, givens = data["solution"], data["givens"]
        actions, description = [], []
        for r in range(self.mapper.n):
            for c in range(self.mapper.n):
                if (r, c) in givens:
                    continue
                value = solution[r][c]
                x, y = self.mapper.cell_center(r, c)
                actions.append((x, y, str(value), f"({r+1},{c+1})={value}"))
                description.append(f"  ({r+1},{c+1}) -> {value}")

        def run(driver: InputDriver):
            for x, y, key, label in actions:
                driver.click(x, y, clicks=1, label=f"select {label}")
                driver.press_key(key, label=label)

        return PlayPlan(description, run)


# ---------------------------------------------------------------------------
class ZipPlayer(BasePlayer):
    """Drag from dot 1 along the whole path.
    從編號 1 沿著整條路徑拖曳。"""

    def build_plan(self, data: dict) -> PlayPlan:
        path = data["path"]
        points = [self.mapper.cell_center(r, c) for r, c in path]
        description = [
            f"  drag ({path[0][0]+1},{path[0][1]+1}) -> ({path[-1][0]+1},{path[-1][1]+1})",
            f"  {len(path)} cells / 格",
        ]

        def run(driver: InputDriver):
            # drag_path interpolates internally - the page tracks which cells the
            # pointer crossed, so jumping cell-to-cell would skip cells and the
            # game would reject the path order.
            # drag_path 內部會做內插 —— 網頁是靠指標經過哪些格子判斷路徑的，
            # 直接一格一格瞬移會跳過中間的格子，遊戲就會判定順序錯誤。
            driver.drag_path(points, label="Zip path / 路徑")

        return PlayPlan(description, run)


# ---------------------------------------------------------------------------
class PatchesPlayer(BasePlayer):
    """Drag each rectangle from its top-left cell to its bottom-right cell.
    每塊矩形從左上角格子拖到右下角格子。

    Tolerance for the guard's own detection failing partway through a fully-
    tiled board lives in BoardWatch.failure_tolerance (automation/board_watch.py),
    computed by board_watch.attach() itself from the puzzle key - not here.
    (STALE UNTIL 2026-08-26 直到 2026-08-26 都是過時的: this used to say
    "set from ui/app.py when arming the watch for a Patches plan" - a
    review found that was never true; app.py just calls attach() and never
    touches failure_tolerance/use_content_check at all. Corrected.)
    An earlier version had THIS class skip the guard for a fixed position (the
    last two rectangles); replaced because a real capture showed the puzzle's
    edge-touching regions are not reliably drawn last. See
    failure_tolerance's own docstring for the measurement.
    保護的偵測在填滿整個棋盤的過程中失效時，容忍多少次的邏輯放在
    BoardWatch.failure_tolerance（automation/board_watch.py），由
    board_watch.attach() 自己根據題目類型算出來——不是放在這裡。
    （直到 2026-08-26 都是過時的：這裡原本寫「由 ui/app.py 在替拼塊計畫
    掛上保護時設定」——經檢查從來不是事實，app.py 只會呼叫 attach()，
    完全沒有碰過 failure_tolerance／use_content_check。已更正。）
    先前的版本是讓這個類別對固定位置（最後兩塊矩形）跳過保護；已經換掉，
    因為一張真實擷取顯示碰到邊緣的區塊不一定排在最後畫。量測依據見
    failure_tolerance 自己的文件字串。
    """

    def build_plan(self, data: dict) -> PlayPlan:
        rects = data["rects"]
        actions, description = [], []
        for r0, c0, height, width in rects:
            start = self.mapper.cell_center(r0, c0)
            end = self.mapper.cell_center(r0 + height - 1, c0 + width - 1)
            actions.append((start, end, f"({r0+1},{c0+1}) {height}x{width}"))
            description.append(f"  ({r0+1},{c0+1}) -> ({r0+height},{c0+width}) = {height}x{width}")

        def run(driver: InputDriver):
            for start, end, label in actions:
                driver.drag_path([start, end], label=label)

        return PlayPlan(description, run)


PLAYERS = {
    tango.KEY: TangoPlayer,
    queens.KEY: QueensPlayer,
    sudoku.KEY: SudokuPlayer,
    zip_path.KEY: ZipPlayer,
    patches.KEY: PatchesPlayer,
}


def build_plan(puzzle_key: str, mapper: BoardMapper, data: dict) -> PlayPlan | None:
    player_cls = PLAYERS.get(puzzle_key)
    return player_cls(mapper).build_plan(data) if player_cls else None
