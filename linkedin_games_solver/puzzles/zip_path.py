"""
Zip - one path that fills every cell and visits the numbered dots in order.
Zip —— 一條路徑填滿所有格子，並依序經過編號圓點。

Rules 規則:
  - the path starts at dot 1 and visits 2, 3, ... in order
  - it must pass through every cell exactly once
  - it may not cross the thick black walls
  - 路徑從 1 出發依序經過 2, 3, ...
  - 必須走過每一格恰好一次
  - 不能穿越粗黑色的牆

This is a Hamiltonian path problem, solved with CP-SAT's AddCircuit.
這是漢米頓路徑問題，用 CP-SAT 的 AddCircuit 求解。
"""

from __future__ import annotations

import cv2
import numpy as np
from ortools.sat.python import cp_model

from ..core import BoardGrid, SolveResult, build_grid, failure
from ..core import digits as digit_ocr

NAME_EN = "Zip"
NAME_ZH = "Zip (連線)"
KEY = "zip"

DARK_THRESHOLD = 90
#: Dark-pixel fraction across a cell boundary above which a wall is present.
#: 交界處深色像素比例超過此值視為有牆。
WALL_DARK_FRACTION = 0.3


#: Solidity of a disc once its printed number is filled back in.
#: 把圓盤上印的數字填回去之後的實心度。
#:
#: A circle fills pi/4 = 0.785 of its bounding box no matter what number is
#: written on it. Measured on img/capture.png, 12 discs, native 424px board:
#: 0.7785..0.8002 (0.7566..0.8035 across 8 board sizes 383..1051px).
#: 圓形佔外框 pi/4 = 0.785，跟上面寫什麼數字無關。
#: 實測 img/capture.png 原生 424px 的 12 個圓盤：0.7785~0.8002
#: （8 種棋盤大小 383~1051px 為 0.7566~0.8035）。
#:
#: WHY NOT the raw dark area 為什麼不用「原始深色面積」:
#:   That varies with how much white ink the number takes up - measured
#:   0.5972 ("10": two digits plus a counter) .. 0.7407 ("1"). The old 0.60
#:   floor sat right in the middle of that spread and silently threw the "10"
#:   disc away, which is why one of twelve dots was never detected.
#:   那個值會隨數字佔掉多少白色而變 —— 實測 0.5972（「10」：兩位數又有內孔）
#:   到 0.7407（「1」）。舊的 0.60 下限正好卡在這個範圍中間，
#:   把「10」那顆圓盤默默丟掉，這就是 12 個圓點漏掉一個的原因。
DISC_SOLIDITY_MIN = 0.70   # 0.0566 below the lowest observed 比實測最低值低 0.0566
DISC_SOLIDITY_MAX = 0.88   # 0.0765 above the highest 比實測最高值高 0.0765


def _looks_like_dot(component: np.ndarray, w: int, h: int, cell: float) -> bool:
    """Numbered dots are near-square, about half a cell, and disc-shaped.
    編號圓點接近正方形、大小約半格、形狀接近圓盤。"""
    if w == 0 or h == 0 or component.size == 0:
        return False
    if not (0.85 <= w / h <= 1.15 and cell * 0.35 <= w <= cell * 0.95):
        return False
    # Fill the printed number back in before measuring, so the answer does not
    # depend on which number is printed.
    # 量測前先把印上去的數字填回去，結果才不會取決於印的是哪個數字。
    filled = component | _enclosed_holes(component)
    return DISC_SOLIDITY_MIN <= filled.sum() / (w * h) <= DISC_SOLIDITY_MAX


def _enclosed_holes(component: np.ndarray) -> np.ndarray:
    """Pixels fully enclosed by a component - i.e. the white digit inside a dot.
    被元件完全包圍的像素 —— 也就是圓點裡的白色數字。

    KEY POINT: flood fill from the border, keeping what the water cannot reach.
      Morphological closing was tried first and distorted the disc, corrupting
      the digit. Note the padding must be filled with the SAME value as the
      background being erased, otherwise the fill clears nothing.
    關鍵：從邊界灌水，保留灌不到的地方。
      先前用形態學閉運算會讓圓盤變形、破壞數字。注意外圈 padding 必須填成
      「要被清除的背景」同值，否則灌水什麼都清不掉。
    """
    padded = np.ones((component.shape[0] + 2, component.shape[1] + 2), np.uint8)
    padded[1:-1, 1:-1] = (~component).astype(np.uint8)
    mask = np.zeros((padded.shape[0] + 2, padded.shape[1] + 2), np.uint8)
    cv2.floodFill(padded, mask, (0, 0), 0)
    return padded[1:-1, 1:-1] > 0


def find_dots(image: np.ndarray, grid: BoardGrid, debug_masks: dict | None = None):
    """Locate the numbered dots and read their numbers.
    找出編號圓點並讀出號碼。

    Returns (dots, unread) where `unread` maps the position of every disc whose
    number could not be read to HOW MANY digit glyphs it showed. That digit
    count is what lets solve() reason about which number it must be - see
    _resolve_unread().
    回傳 (dots, unread)。`unread` 把「號碼讀不出來的圓盤」的位置，
    對應到它顯示了幾個數字字形。那個位數是 solve() 用來推論「它一定是哪個號碼」
    的依據，見 _resolve_unread()。

    `debug_masks`, if given, is filled in with {(row, col): mask} for every
    disc found - the same raw bitmap read_number() classifies from, BEFORE
    classification. Every ordinary caller leaves this None (zero cost - the
    dict write only happens when a caller asks for it). It exists solely so
    tools/calibrate_digits.py's from_zip_dots() can turn real Zip captures
    into digit templates via the SAME extraction this function actually uses,
    instead of a second, drifting reimplementation - this mirrors how
    puzzles/patches.py's PatchLabel.glyphs already does the same job for
    Patches labels.
    `debug_masks`（如果有給）會被填入 {(row, col): mask} —— 跟 read_number()
    拿去分類的、分類「之前」的同一份原始點陣圖。一般呼叫端都不會給這個參數
    （成本是零——只有呼叫端主動要，才會寫進這個字典）。它存在的唯一理由是讓
    tools/calibrate_digits.py 的 from_zip_dots() 能用這個函式「真正在用」的
    同一套抽取邏輯，把真實的 Zip 截圖轉成數字範本，而不是另外寫一份會慢慢
    跟正式邏輯不同步的重複實作——這跟 puzzles/patches.py 的
    PatchLabel.glyphs 對 Patches 標籤做的事完全一樣。
    """
    x0, y0, w0, h0 = grid.board_bbox
    cell = (w0 / grid.n + h0 / grid.n) / 2
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    dark = (gray < DARK_THRESHOLD).astype(np.uint8)

    num, labels_img, stats, centroids = cv2.connectedComponentsWithStats(dark, connectivity=8)
    dots: dict[tuple[int, int], int] = {}
    unread: dict[tuple[int, int], int] = {}
    for i in range(1, num):
        x, y, w, h, area = stats[i]
        window = labels_img[y : y + h, x : x + w]
        component = window == i
        if not _looks_like_dot(component, w, h, cell):
            continue
        cx, cy = centroids[i]
        row, col = int((cy - y0) / cell), int((cx - x0) / cell)
        if not (0 <= row < grid.n and 0 <= col < grid.n):
            continue

        # A digit with an enclosed counter (0 4 6 8 9) leaves that counter as a
        # SEPARATE dark component, so it is not part of `component`, the flood
        # fill cannot reach it, and _enclosed_holes hands the digit back with
        # its holes filled solid. Anything that is itself dark cannot be part of
        # the white number, so intersect with "not dark".
        # Measured on img/capture.png at native 424px, top-1 digit and margin:
        #   (1,1) "0"  before 9@0.9129 m=0.0001 (WRONG)  after 0@0.9816 m=0.0517
        #   (0,1) "9"  before rejected                    after 9@0.9672 m=0.0516
        #   (4,1) "6"                                     after 6@0.9763 m=0.0425
        # After this change all 12 discs have the correct top-1 digit.
        # 帶封閉內孔的數字（0 4 6 8 9），內孔是「另一個」深色元件，不屬於 component，
        # 灌水也灌不到，_enclosed_holes 會把它當成孔一起交回 —— 等於把洞填實了。
        # 本身就是深色的像素不可能是白色數字的一部分，所以跟「非深色」取交集。
        # 實測 img/capture.png 原生 424px，第一名數字與差距：
        #   (1,1) 的「0」修正前 9@0.9129 差距 0.0001（第一名就是錯的）
        #                修正後 0@0.9816 差距 0.0517
        # 修正後 12 個圓盤的第一名數字全部正確。
        holes = _enclosed_holes(component) & (window == 0)
        mask = holes.astype(np.uint8)
        if debug_masks is not None:
            debug_masks[(row, col)] = mask
        value = digit_ocr.read_number(mask)
        if value is not None:
            dots[(row, col)] = value
        else:
            # Remember how many digit glyphs this disc showed. A disc with one
            # glyph is a single-digit number, one with two is a two-digit
            # number - which is often enough to pin it down. See
            # _resolve_unread().
            # 記住這個圓盤顯示了幾個數字字形。一個字形代表個位數、兩個代表兩位數，
            # 這通常就足以把它釘死。見 _resolve_unread()。
            unread[(row, col)] = len(digit_ocr.split_digit_glyphs(mask))
    return dots, unread


def _digits_in(value: int) -> int:
    return len(str(value))


#: How many candidate assignments to enumerate before giving up. Small on
#: purpose: past a handful of unreadable dots the board is too degraded to
#: trust at all, and a big search would only be dressing up a guess.
#: 列舉幾種候選指派之後就放棄。刻意設小：讀不出來的圓點一多，
#: 這個盤面就根本不值得信任，搜尋再大也只是把猜測包裝得比較漂亮。
_MAX_ASSIGNMENTS = 24


def _consistent_assignments(dots: dict, unread: dict):
    """Every numbering consistent with "1..k with no gaps" and the digit counts.
    所有符合「1..k 連續無缺口」與各圓盤位數的編號方式。

    Returns (list_of_assignments, why_none) - the list is capped at
    _MAX_ASSIGNMENTS + 1 so the caller can tell "too many" from "exactly one".
    回傳 (指派清單, 沒有的原因)。清單最多到 _MAX_ASSIGNMENTS + 1，
    讓呼叫端能分辨「太多種」與「恰好一種」。
    """
    total = len(dots) + len(unread)
    missing = sorted(set(range(1, total + 1)) - set(dots.values()))
    if len(missing) != len(unread):
        return [], (f"read numbers {sorted(dots.values())} do not leave exactly "
                    f"{len(unread)} gap(s) / 已讀出的號碼沒有剛好留下 {len(unread)} 個空缺")

    positions = sorted(unread)
    candidates = []
    for pos in positions:
        want = unread[pos]
        # A glyph count of 0 means we could not even split the mask, so it tells
        # us nothing - allow any missing number for that disc.
        # 字形數 0 代表連遮罩都切不開，那就什麼資訊都沒有 —— 該圓盤允許任何缺號。
        fits = [v for v in missing if want == 0 or _digits_in(v) == want]
        if not fits:
            return [], (f"disc at ({pos[0] + 1},{pos[1] + 1}) shows {want} digit(s) but no "
                        f"missing number has that many / ({pos[0] + 1},{pos[1] + 1}) 的圓盤"
                        f"有 {want} 位數，但沒有任何缺號是那個位數")
        candidates.append(fits)

    out = []

    def assign(i, used, acc):
        if len(out) > _MAX_ASSIGNMENTS:
            return
        if i == len(positions):
            out.append(dict(acc))
            return
        for v in candidates[i]:
            if v in used:
                continue
            acc[positions[i]] = v
            assign(i + 1, used | {v}, acc)
            del acc[positions[i]]

    assign(0, frozenset(), {})
    return out, ""


def _resolve_unread(dots, unread, n, h_walls, v_walls):
    """Fill in numbers the reader could not, using the puzzle's own rules.
    Returns (resolved_dots, note) or (None, why_not).
    用謎題自己的規則補上讀不出來的號碼。回傳 (補完的 dots, 說明) 或 (None, 原因)。

    TWO filters, both of them deductions rather than guesses:
    兩道篩選，兩道都是推論而不是猜測：

      1. Zip's dots are numbered 1..k with no gaps, so once we know how many
         discs there are we know exactly which numbers exist. A disc showing one
         glyph must be a single-digit number, two glyphs a two-digit one.
         Zip 的圓點編號是 1..k 連續無缺口，所以知道有幾個圓盤就知道有哪些號碼。
         顯示一個字形的圓盤必定是個位數、兩個字形必定是兩位數。

      2. If more than one numbering survives (1), solve each and keep only those
         that yield a valid path. A numbering that cannot be walked is not the
         puzzle. This is the same move Patches already makes with unreadable
         labels: prove the answer does not depend on what we could not read.
         如果通過 (1) 的編號不只一種，就各解一次，只留下能走出合法路徑的。
         走不出來的編號就不是這道題。這跟 Patches 對讀不出來的標籤所做的一樣：
         證明答案不取決於我們讀不出來的那部分。

    Accepted ONLY when exactly one distinct path survives. Two is a guess, and a
    guess is the one thing this project refuses to make - a wrong route would be
    dragged with the user's real mouse while reporting success.
    只有在「恰好剩下一條相異路徑」時才採用。剩兩條就是猜測，
    而猜測正是這個專案唯一拒絕做的事 —— 錯誤的路線會被真實滑鼠拖出去、
    而且回報成功。
    """
    if not unread:
        return dict(dots), ""

    options, why = _consistent_assignments(dots, unread)
    if not options:
        return None, why
    if len(options) > _MAX_ASSIGNMENTS:
        return None, (f"{len(unread)} unreadable dot(s), too many possible numberings "
                      f"to check / {len(unread)} 個圓點讀不出來，可能的編號方式太多")

    survivors = []
    for choice in options:
        merged = dict(dots)
        merged.update(choice)
        path = solve_path(n, merged, h_walls, v_walls)
        if path is not None:
            survivors.append((choice, tuple(path)))
        if len({p for _, p in survivors}) > 1:
            break

    distinct = {p for _, p in survivors}
    if len(distinct) != 1:
        return None, (f"{len(unread)} unreadable dot(s); {len(options)} numbering(s) fit the "
                      f"digit counts and {len(distinct)} give a valid path - refusing to guess "
                      f"/ {len(unread)} 個圓點讀不出來；{len(options)} 種編號符合位數，"
                      f"其中 {len(distinct)} 種走得出路徑，不做猜測")

    choice = survivors[0][0]
    resolved = dict(dots)
    resolved.update(choice)
    where = ", ".join(f"({p[0] + 1},{p[1] + 1})={v}" for p, v in sorted(choice.items()))
    extra = "" if len(options) == 1 else f" (of {len(options)} that fit the digit counts)"
    return resolved, (f"deduced {where}{extra} - only numbering with a valid path "
                      f"/ 推出 {where}，是唯一走得出路徑的編號")


def find_walls(image: np.ndarray, grid: BoardGrid) -> tuple[set, set]:
    """Walls between adjacent cells. Returns (h_walls, v_walls).
    相鄰格之間的牆。回傳 (水平相鄰的牆, 垂直相鄰的牆)。"""
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    mask = (gray < DARK_THRESHOLD).astype(np.uint8)
    x0, y0, w0, h0 = grid.board_bbox
    cell = (w0 / grid.n + h0 / grid.n) / 2

    # Erase the numbered dots first, otherwise a dot near a boundary reads as a wall.
    # 先把編號圓點挖掉，否則靠近邊界的圓點會被誤判成牆。
    #
    # KEEP THE LABEL IMAGE. _looks_like_dot needs the component mask to fill the
    # printed number back in. Discarding it and passing (w, h, area, cell) still
    # matches the arity, so there would be NO TypeError and pyflakes would stay
    # clean - the aspect test would just silently become false for everything and
    # this loop would erase nothing, leaving every dot to be read as a wall.
    # 一定要保留 label 影像。_looks_like_dot 需要元件遮罩才能把數字填回去。
    # 丟掉它、改傳 (w, h, area, cell) 的話「參數個數仍然吻合」——
    # 不會有 TypeError、pyflakes 也不會抱怨，只會讓比例判斷默默永遠為假、
    # 這個迴圈一個圓點都不擦，然後每個圓點都被當成牆。
    num, labels_img, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    for i in range(1, num):
        x, y, w, h, area = stats[i]
        if not _looks_like_dot(labels_img[y : y + h, x : x + w] == i, w, h, cell):
            continue
        # Clip the erase to the disc plus a small margin, bounded by the cell.
        # The size gate admits a disc up to 0.95*cell wide; padding that by 4px
        # each side would exceed the cell and wipe out the wall sampling band -
        # producing a MISSING wall, which nothing downstream catches.
        # 擦除範圍限制在圓盤加一點邊界，且不得超過一格。
        # 尺寸判斷容許圓盤寬達 0.95*cell，四邊各加 4px 就會超過一格、
        # 把量測牆的取樣帶整個擦掉 —— 造成「少一道牆」，而且下游沒有任何東西抓得到。
        pad = int(min(4, max(0, (cell - max(w, h)) / 2)))
        cv2.rectangle(mask, (x - pad, y - pad), (x + w + pad, y + h + pad), 0, -1)

    def dark_fraction(x_from, x_to, y_from, y_to) -> float:
        sub = mask[max(0, y_from) : y_to, max(0, x_from) : x_to]
        return float(sub.mean()) if sub.size else 0.0

    h_walls, v_walls = set(), set()
    for r in range(grid.n):
        for c in range(grid.n - 1):
            x, y, w, h = grid.cell_boxes[r][c]
            band = max(4, w // 12)
            if dark_fraction(x + w - band, x + w + band, y + int(h * 0.2), y + int(h * 0.8)) > WALL_DARK_FRACTION:
                h_walls.add((r, c))
    for r in range(grid.n - 1):
        for c in range(grid.n):
            x, y, w, h = grid.cell_boxes[r][c]
            band = max(4, h // 12)
            if dark_fraction(x + int(w * 0.2), x + int(w * 0.8), y + h - band, y + h + band) > WALL_DARK_FRACTION:
                v_walls.add((r, c))
    return h_walls, v_walls


def solve_path(n: int, dots: dict, h_walls: set, v_walls: set) -> list[tuple[int, int]] | None:
    """Find the Hamiltonian path. Returns cells in visiting order.
    找出漢米頓路徑，回傳依序經過的格子。"""
    if not dots:
        return None
    ordered = sorted(dots.items(), key=lambda kv: kv[1])
    start = ordered[0][0]

    total = n * n
    index = {(r, c): r * n + c for r in range(n) for c in range(n)}
    dummy = total

    def passable(a, b) -> bool:
        (r1, c1), (r2, c2) = a, b
        if r1 == r2:
            return (r1, min(c1, c2)) not in h_walls
        return (min(r1, r2), c1) not in v_walls

    model = cp_model.CpModel()
    arcs = []
    arc_literals: dict[tuple[int, int], object] = {}

    # A dummy node turns "Hamiltonian path from start to anywhere" into a
    # Hamiltonian circuit, which AddCircuit can express directly:
    #   dummy -> start -> ... -> end -> dummy
    # 用一個虛擬節點把「從 start 出發到任意終點的漢米頓路徑」轉成
    # AddCircuit 能直接表達的漢米頓環：dummy -> start -> ... -> end -> dummy
    always_true = model.NewBoolVar("dummy_start")
    model.Add(always_true == 1)
    arcs.append((dummy, index[start], always_true))

    for r in range(n):
        for c in range(n):
            u = index[(r, c)]
            arcs.append((u, dummy, model.NewBoolVar(f"end_{r}_{c}")))
            for dr, dc in ((0, 1), (0, -1), (1, 0), (-1, 0)):
                nr, nc = r + dr, c + dc
                if not (0 <= nr < n and 0 <= nc < n) or not passable((r, c), (nr, nc)):
                    continue
                lit = model.NewBoolVar(f"a_{r}_{c}_{nr}_{nc}")
                arcs.append((u, index[(nr, nc)], lit))
                arc_literals[(u, index[(nr, nc)])] = lit

    model.AddCircuit(arcs)

    # Position along the path, so the dot ordering can be constrained.
    # 路徑上的順序，用來限制編號圓點的先後。
    pos = {cell: model.NewIntVar(0, total - 1, f"p_{cell}") for cell in index}
    model.Add(pos[start] == 0)
    for (u, v), lit in arc_literals.items():
        ur, uc = divmod(u, n)
        vr, vc = divmod(v, n)
        model.Add(pos[(vr, vc)] == pos[(ur, uc)] + 1).OnlyEnforceIf(lit)

    for (cell_a, _), (cell_b, _) in zip(ordered, ordered[1:]):
        model.Add(pos[cell_a] < pos[cell_b])

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 60.0
    solver.parameters.num_workers = 8
    if solver.Solve(model) not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return None
    return sorted(index, key=lambda cell: solver.Value(pos[cell]))


def draw_overlay(image, grid: BoardGrid, path) -> np.ndarray:
    out = image.copy()
    points = [grid.cell_center(r, c) for r, c in path]
    _, _, cw, ch = grid.cell_boxes[0][0]
    thickness = max(4, min(cw, ch) // 8)
    for a, b in zip(points, points[1:]):
        cv2.line(out, a, b, (0, 90, 230), thickness, lineType=cv2.LINE_AA)
    cv2.circle(out, points[0], thickness * 2, (0, 190, 0), -1, lineType=cv2.LINE_AA)
    cv2.circle(out, points[-1], thickness * 2, (0, 0, 230), -1, lineType=cv2.LINE_AA)
    return out


def solve(image: np.ndarray, n_hint: int | None = None) -> SolveResult:
    try:
        grid = build_grid(image, n_hint=n_hint)
    except ValueError as exc:
        return failure(KEY, str(exc))

    dots, unread = find_dots(image, grid)
    h_walls, v_walls = find_walls(image, grid)
    disc_count = len(dots) + len(unread)
    info = [f"{grid.n}x{grid.n}", f"dots / 圓點 {disc_count}",
            f"walls / 牆 {len(h_walls)}+{len(v_walls)}"]

    if disc_count < 2:
        return failure(KEY, "fewer than 2 dots found / 編號圓點少於 2 個", grid=grid, info=info)

    # Some numbers may be genuinely ambiguous at small board sizes - an "8" and
    # a "6" can be a coin flip once the board is under ~500px. But Zip's dots are
    # numbered 1..k with no gaps, so the puzzle's own rules often force the
    # answer. Take it ONLY when exactly one assignment is consistent.
    # 在小棋盤上，有些號碼是真的難分 —— 棋盤低於約 500px 時，「8」和「6」可能
    # 五五波。但 Zip 的圓點編號是 1..k 連續無缺口，所以謎題自己的規則往往就能
    # 逼出答案。只有在「恰好一種指派成立」時才採用。
    if unread:
        resolved, note = _resolve_unread(dots, unread, grid.n, h_walls, v_walls)
        if resolved is None:
            where = ", ".join(f"({r + 1},{c + 1})" for r, c in sorted(unread))
            return failure(
                KEY,
                f"{len(unread)} of {disc_count} dot number(s) unreadable at {where}; "
                f"{note} / {disc_count} 個圓點中有 {len(unread)} 個號碼讀不出來（{where}）；{note}",
                grid=grid, info=info,
            )
        dots = resolved
        info.append(note)

    # A disc we found but could not read is NOT the same as a disc that is not
    # there, and the consecutive test below cannot tell the difference: it
    # passes on any PREFIX. Twelve discs of which only 1..8 were readable looks
    # exactly like an eight-dot puzzle, and the solver then returns a full path
    # that visits the unread dots in the wrong order - a wrong route, dragged
    # with the real mouse, reported as success. Measured: img/capture.png at
    # 0.70x returned ok=True with dots 11 and 12 out of order, 3 of 3 runs.
    # 「找到但讀不出來的圓盤」跟「根本沒有那個圓盤」是兩回事，
    # 而下面的連續性檢查分不出來 —— 它對任何「前綴」都會通過。
    # 12 個圓盤只讀出 1..8 的話，看起來就跟一題 8 點的謎題一模一樣，
    # 求解器接著會給出一條把沒讀到的點走錯順序的完整路徑 ——
    # 一條錯誤路線，用真實滑鼠拖出去，而且回報成功。
    # 實測：img/capture.png 在 0.70x 會回傳 ok=True 且 11、12 順序顛倒，3/3 次重現。
    #
    # LIMIT: this catches exactly one mode - "disc found, number unreadable".
    # It does NOT catch a disc that was never detected as a disc, nor k discs
    # with k numbers one of which is simply wrong. Those rely on the consecutive
    # test below and on solve_path failing to find a route.
    # 限制：這只抓得到一種情況 ——「圓盤找到了、號碼讀不出來」。
    # 它抓不到「圓盤根本沒被當成圓盤偵測到」，也抓不到
    # 「k 個圓盤 k 個號碼但其中一個就是錯的」。
    # 那兩種要靠下面的連續性檢查、以及 solve_path 找不到路徑來擋。
    values = sorted(dots.values())
    if values != list(range(1, len(values) + 1)):
        return failure(KEY, f"dot numbers not consecutive / 圓點編號不連續 {values}", grid=grid, info=info)

    path = solve_path(grid.n, dots, h_walls, v_walls)
    if path is None:
        return failure(KEY, "no valid path / 找不到符合規則的路徑", grid=grid, info=info)

    return SolveResult(
        ok=True, puzzle_key=KEY, grid=grid, info=info,
        data={"path": path, "dots": dots},
        overlay=draw_overlay(image, grid, path),
    )
