"""
五種謎題的「填答動作」：把解答轉成一連串滑鼠/鍵盤操作。

每種遊戲的操作方式不同，這裡依各遊戲畫面上寫的玩法實作：

  Tango    點一下放太陽、點兩下放月亮 (空白 -> 太陽 -> 月亮 -> 空白 循環)
  Queens   畫面說明寫「輕點一次放置 X，輕點兩次放置皇后」-> 點兩下
  Sudoku   先點格子再按數字鍵
  Zip      從編號 1 沿著路徑按住拖曳到終點
  Patches  每塊矩形從左上角拖曳到右下角

注意: 網頁版的實際操作手感可能與手機版略有差異 (例如點擊循環順序)。
每個 Player 的操作參數都集中在 class 屬性，實測後可直接調整。
先用 dry-run 預覽，確認動作合理再實際執行。
"""

from dataclasses import dataclass

from board_mapper import BoardMapper
from input_driver import InputDriver


@dataclass
class PlayPlan:
    """一份填答計畫：描述要做什麼，以及實際執行的函式。"""

    description: list[str]
    run: object  # callable(driver: InputDriver) -> None


class BasePlayer:
    #: 需要既有專案解出來的哪些資料
    puzzle_key = ""

    def __init__(self, mapper: BoardMapper):
        self.mapper = mapper

    def build_plan(self, solved) -> PlayPlan:
        raise NotImplementedError


# --------------------------------------------------------------------------
# Tango
# --------------------------------------------------------------------------
class TangoPlayer(BasePlayer):
    puzzle_key = "tango"

    #: 點擊會依「空白 -> 太陽 -> 月亮 -> 空白」循環，這是每個狀態在循環中的位置。
    #: 要點幾下 = (目標位置 - 目前位置) 對 3 取餘數。
    #: 不能一律假設從空白開始：如果上一次跑到一半、格子已經是太陽或月亮，
    #: 還照「空白->目標」的次數點就會多點，反而把對的變成錯的。
    _CYCLE = {None: 0, 1: 1, 0: 2}  # None=空白, 1=太陽, 0=月亮

    def build_plan(self, solved) -> PlayPlan:
        solution = solved["solution"]  # list[list[int]] 1=sun 0=moon
        givens = solved["givens"]  # set[(r,c)] 題目給的，不能改
        current = solved["current"]  # dict[(r,c)] -> 1/0/None 目前畫面上的狀態

        actions = []
        description = []
        for r in range(self.mapper.n):
            for c in range(self.mapper.n):
                if (r, c) in givens:
                    continue
                target = solution[r][c]
                now = current.get((r, c))
                clicks = (self._CYCLE[target] - self._CYCLE.get(now, 0)) % 3
                if clicks == 0:
                    continue  # 已經填對了，不用動
                x, y = self.mapper.cell_center(r, c)
                name = "太陽" if target == 1 else "月亮"
                actions.append((x, y, clicks, f"({r+1},{c+1}) {name}"))
                description.append(f"  第 {r+1} 列 第 {c+1} 欄 -> {name} (點 {clicks} 下)")
        if not actions:
            description.append("  盤面已經完成，不需要任何操作。")

        def run(driver: InputDriver):
            for x, y, clicks, label in actions:
                driver.click(x, y, clicks=clicks, label=label)

        return PlayPlan(description=description, run=run)


# --------------------------------------------------------------------------
# Queens
# --------------------------------------------------------------------------
class QueensPlayer(BasePlayer):
    puzzle_key = "queens"

    CLICKS_FOR_QUEEN = 2  # 畫面說明：輕點兩次放置皇后

    def build_plan(self, solved) -> PlayPlan:
        import queens_ext

        queens = solved["queens"]  # list[(r,c)]
        wanted = set(queens)
        states = solved.get("cell_states") or {}
        actions, description = [], []

        # 先清掉放錯位置的皇冠。上一次跑失敗、或使用者自己亂點過，
        # 盤面上可能留著不該有的皇冠；不清掉的話答案永遠是錯的。
        # 點擊是循環的 (空白->X->皇冠->空白)，所以皇冠再點 1 下就會清成空白。
        for (r, c), state in sorted(states.items()):
            if state == queens_ext.STATE_QUEEN and (r, c) not in wanted:
                x, y = self.mapper.cell_center(r, c)
                actions.append((x, y, 1, f"({r+1},{c+1}) 清掉放錯的皇冠"))
                description.append(f"  第 {r+1} 列 第 {c+1} 欄 -> 清掉放錯的皇冠 (點 1 下)")

        for r, c in queens:
            # 依該格目前的狀態決定還要點幾下：空白要 2 下、已經是 X 只要 1 下、
            # 已經是皇冠就跳過。這樣重跑或補點時都不會點過頭。
            clicks = queens_ext.clicks_needed(states.get((r, c)))
            if clicks == 0:
                description.append(f"  第 {r+1} 列 第 {c+1} 欄 -> 已經放好了，跳過")
                continue
            x, y = self.mapper.cell_center(r, c)
            actions.append((x, y, clicks, f"({r+1},{c+1}) 皇后"))
            description.append(f"  第 {r+1} 列 第 {c+1} 欄 -> 放皇后 (點 {clicks} 下)")
        if not actions:
            description.append("  盤面已經完成，不需要任何操作。")

        def run(driver: InputDriver):
            for x, y, clicks, label in actions:
                driver.click(x, y, clicks=clicks, label=label)

        return PlayPlan(description=description, run=run)


# --------------------------------------------------------------------------
# Mini Sudoku
# --------------------------------------------------------------------------
class SudokuPlayer(BasePlayer):
    puzzle_key = "sudoku"

    def build_plan(self, solved) -> PlayPlan:
        solution = solved["solution"]
        givens = solved["givens"]  # dict[(r,c)] -> value
        actions, description = [], []
        for r in range(self.mapper.n):
            for c in range(self.mapper.n):
                if (r, c) in givens:
                    continue
                value = solution[r][c]
                x, y = self.mapper.cell_center(r, c)
                actions.append((x, y, str(value), f"({r+1},{c+1}) = {value}"))
                description.append(f"  第 {r+1} 列 第 {c+1} 欄 -> 填 {value}")

        def run(driver: InputDriver):
            for x, y, key, label in actions:
                driver.click(x, y, clicks=1, label=f"選格 {label}")
                driver.press_key(key, label=label)

        return PlayPlan(description=description, run=run)


# --------------------------------------------------------------------------
# Zip
# --------------------------------------------------------------------------
class ZipPlayer(BasePlayer):
    puzzle_key = "zip"

    def build_plan(self, solved) -> PlayPlan:
        path = solved["path"]  # list[(r,c)] 依序
        points = [self.mapper.cell_center(r, c) for r, c in path]
        description = [
            f"  從 ({path[0][0]+1},{path[0][1]+1}) 一路拖曳到 ({path[-1][0]+1},{path[-1][1]+1})",
            f"  共經過 {len(path)} 格",
        ]

        def run(driver: InputDriver):
            driver.drag_path(points, label="Zip 路徑")

        return PlayPlan(description=description, run=run)


# --------------------------------------------------------------------------
# Patches
# --------------------------------------------------------------------------
class PatchesPlayer(BasePlayer):
    puzzle_key = "patches"

    def build_plan(self, solved) -> PlayPlan:
        rects = solved["rects"]  # list[(r0,c0,height,width)]
        actions, description = [], []
        for r0, c0, height, width in rects:
            start = self.mapper.cell_center(r0, c0)
            end = self.mapper.cell_center(r0 + height - 1, c0 + width - 1)
            actions.append((start, end, f"({r0+1},{c0+1}) {height}x{width}"))
            description.append(
                f"  從 ({r0+1},{c0+1}) 拖到 ({r0+height},{c0+width}) -> {height} 高 x {width} 寬"
            )

        def run(driver: InputDriver):
            for start, end, label in actions:
                driver.drag_path([start, end], label=label)

        return PlayPlan(description=description, run=run)


PLAYERS = {
    "tango": TangoPlayer,
    "queens": QueensPlayer,
    "sudoku": SudokuPlayer,
    "zip": ZipPlayer,
    "patches": PatchesPlayer,
}
