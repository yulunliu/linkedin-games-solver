"""
Queens 的擴充：棋盤上已經有皇冠 / X 標記時也能正確辨識色塊。

問題：既有專案的 `puzzle_queens.read_regions` 是取每格**正中央** 30%~70% 的顏色
當作該格的色塊顏色。這在「還沒開始作答」的空白盤面沒問題，但只要玩家已經放上
皇冠（或用 X 標記），皇冠正好蓋在正中央，取到的就會是黑色皇冠而不是色塊顏色，
於是黑色被當成一個新的「色塊區域」，區域數量對不上棋盤大小而辨識失敗。

作法：
  - 取整格（往內縮一點避開格線），排除掉深色像素（皇冠、X 標記都是深色），
    再取剩下像素的中位數當作色塊顏色。
  - 順便偵測每格「是不是已經放了皇冠」，這樣填答時可以跳過已經放好的格子。
"""

import cv2
import numpy as np

import solver_bridge  # noqa: F401  匯入時會把 tango_solver 加進 sys.path

#: 兩格顏色差距在此範圍內視為「同一種顏色」。
#: 只用來把完全相同的平面色歸在一起 (容忍 JPEG/縮放造成的些微差異)，
#: 所以設得很小；區分不同色塊是靠「取出現次數最多的 n 種顏色」，不是靠這個容差。
SAME_COLOR_EPSILON = 10
#: 明度低於此的像素視為「皇冠 / X 標記」，不列入色塊顏色的計算
DARK_ICON_VALUE_MAX = 110
#: 取樣時往格子內縮的比例，避開格線與相鄰色塊
CELL_INSET_RATIO = 0.14
#: 偵測格內圖案(皇冠/X)時，往格子內縮的比例。
#:
#: 這個值很關鍵：棋盤格線與外框本身是深色的，內縮不夠就會把格線算進「深色像素」，
#: 造成空白格也有 0.03~0.08 的深色比例，跟真正的皇冠混在一起。
#: 實測用真實網頁畫面校準：內縮 28% (只看正中央 44% 的區域) 時，
#: 皇冠 0.268~0.374、空白剛好 0.000，分得非常乾淨。
ICON_INSET_RATIO = 0.28

#: 格子正中央深色像素的比例門檻，用來判斷「皇冠 / X 標記 / 空白」。
#: 注意：先前這裡是用合成的皇冠校準的，門檻(0.17)訂得太高，
#: 真實網頁的皇冠只有 0.10~0.20(當時還混入格線雜訊)，導致幾乎都判定成「沒放」，
#: 驗證階段就會一直重複點已經放好的格子，反而把正確答案點掉。
QUEEN_DARK_RATIO_MIN = 0.20
X_MARK_DARK_RATIO_MIN = 0.04

STATE_QUEEN = "queen"
STATE_X = "x"


def _cell_pixels(image: np.ndarray, box: tuple[int, int, int, int], inset: float = CELL_INSET_RATIO):
    x, y, w, h = box
    inset_x, inset_y = int(w * inset), int(h * inset)
    return image[y + inset_y : y + h - inset_y, x + inset_x : x + w - inset_x]


def cell_colors(image: np.ndarray, grid) -> np.ndarray:
    """每格的代表色 (BGR)，忽略格子中央的皇冠 / X 標記。回傳 shape=(n*n, 3)。"""
    colors = []
    for r in range(grid.n):
        for c in range(grid.n):
            cell = _cell_pixels(image, grid.cell_boxes[r][c])
            if cell.size == 0:
                colors.append(np.zeros(3))
                continue
            hsv = cv2.cvtColor(cell, cv2.COLOR_BGR2HSV)
            keep = hsv[:, :, 2] > DARK_ICON_VALUE_MAX
            pixels = cell[keep] if keep.sum() >= 20 else cell.reshape(-1, 3)
            colors.append(np.median(pixels, axis=0))
    return np.array(colors, dtype=np.float32)


def _regions_are_connected(region_ids: list[list[int]], n: int, count: int) -> bool:
    """Queens 的每個色塊區域都是連在一起的一塊；分群若把一區切成兩塊代表分錯了。"""
    for target in range(count):
        cells = [(r, c) for r in range(n) for c in range(n) if region_ids[r][c] == target]
        if not cells:
            return False
        seen = {cells[0]}
        stack = [cells[0]]
        while stack:
            r, c = stack.pop()
            for dr, dc in ((0, 1), (0, -1), (1, 0), (-1, 0)):
                nb = (r + dr, c + dc)
                if nb in seen:
                    continue
                if 0 <= nb[0] < n and 0 <= nb[1] < n and region_ids[nb[0]][nb[1]] == target:
                    seen.add(nb)
                    stack.append(nb)
        if len(seen) != len(cells):
            return False
    return True


def read_regions(image: np.ndarray, grid) -> tuple[list[list[int]], list[tuple[int, int, int]]]:
    """
    把每格分到所屬的色塊區域。

    不用「固定顏色容差」逐格比對：網頁版的配色比手機版接近很多
    (實測 藍(165,187,246) 與 紫(182,158,219) 只差 29、
     米灰(182,178,161) 與 粉(204,155,188) 只差 27)，
    容差設太鬆會把兩區併成一區、設太緊又會被滑鼠移過去造成的深淺變化拆成兩區。

    改用已知條件：**色塊區域數一定等於棋盤格數 n**，直接把所有格子的顏色
    分成剛好 n 群。這樣顏色再接近也不會被併掉，滑鼠 hover 造成的深色格
    也會被歸回最接近的那一群。
    """
    n = grid.n
    colors = cell_colors(image, grid)

    # 用「出現次數最多的 n 種顏色」當調色盤，再把每格分到最接近的那一種。
    #
    # 不用 k-means：它的初始中心是隨機的，同一張圖跑兩次可能得到不同分群
    # (實測就遇過同一個盤面有時正常、有時把某一區切成不相連的兩塊而判定失敗)。
    # 每個色塊區域的顏色是「一模一樣的平面色」，所以直接統計出現次數最穩、
    # 而且完全可重現。滑鼠停留造成的深色格只會出現一次，不會被選進調色盤，
    # 最後會被歸到最接近的正確顏色。
    groups: list[list[np.ndarray]] = []
    for color in colors:
        for group in groups:
            if np.abs(group[0] - color).max() <= SAME_COLOR_EPSILON:
                group.append(color)
                break
        else:
            groups.append([color])

    groups.sort(key=len, reverse=True)
    centers = [np.median(np.array(g), axis=0) for g in groups[:n]]

    region_ids = [[0] * n for _ in range(n)]
    for idx, color in enumerate(colors):
        distances = [np.abs(center - color).max() for center in centers]
        region_ids[idx // n][idx % n] = int(np.argmin(distances))

    palette = [tuple(int(v) for v in center) for center in centers]
    return region_ids, palette


def regions_look_valid(region_ids: list[list[int]], n: int) -> bool:
    """檢查分群結果合理：每區都有格子、而且每區都是連通的一塊。"""
    used = {region_ids[r][c] for r in range(n) for c in range(n)}
    if len(used) != n:
        return False
    return _regions_are_connected(region_ids, n, n)


def read_cell_states(image: np.ndarray, grid) -> dict[tuple[int, int], str]:
    """
    讀出每格目前的狀態：皇冠 / X 標記 / 空白(不列入)。

    這是自動填答能「檢查並補點」的基礎：漏點的格子會停在空白或 X 的狀態，
    知道目前狀態才能算出還要再點幾下（空白->點2下、X->再點1下）。
    """
    states: dict[tuple[int, int], str] = {}
    for r in range(grid.n):
        for c in range(grid.n):
            # 用比較深的內縮，只看格子正中央，避開深色的格線與棋盤外框
            cell = _cell_pixels(image, grid.cell_boxes[r][c], inset=ICON_INSET_RATIO)
            if cell.size == 0:
                continue
            hsv = cv2.cvtColor(cell, cv2.COLOR_BGR2HSV)
            dark_ratio = float((hsv[:, :, 2] <= DARK_ICON_VALUE_MAX).mean())
            if dark_ratio >= QUEEN_DARK_RATIO_MIN:
                states[(r, c)] = STATE_QUEEN
            elif dark_ratio >= X_MARK_DARK_RATIO_MIN:
                states[(r, c)] = STATE_X
    return states


def read_placed_queens(image: np.ndarray, grid) -> set[tuple[int, int]]:
    """哪些格子已經放好皇冠了。"""
    return {pos for pos, state in read_cell_states(image, grid).items() if state == STATE_QUEEN}


def clicks_needed(state: str | None) -> int:
    """從目前狀態要變成皇冠，還需要點幾下 (空白->X->皇冠 的循環)。"""
    if state == STATE_QUEEN:
        return 0
    if state == STATE_X:
        return 1
    return 2
