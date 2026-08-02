"""
Regenerate core/digit_templates.py from real screenshots.
從真實截圖重新產生 core/digit_templates.py。

    python tools/calibrate_digits.py

WHY this exists 為什麼需要這支腳本:
  The app draws its digits in the iOS system font, and some of them differ
  enough from Windows fonts to be misread - its "5" has an unusually round
  bowl that most fonts classify as a "6". Glyphs taken from the app itself
  match exactly, so recognition becomes a lookup rather than a guess.
  這個 App 的數字是用 iOS 系統字型畫的，其中有幾個跟 Windows 字型差夠多而會誤判 ——
  它的「5」下半部特別圓，多數字型會判成「6」。直接取自 App 本身的字形完全吻合，
  辨識就從「猜」變成「查表」。

WHEN to run it 什麼時候要重跑:
  - the app changes its font 這個 App 換字型
  - you are on a device whose digits look different (another phone, a tablet)
    你的裝置數字長得不一樣（別支手機、平板）
  - you have a screenshot containing a digit the current set lacks (0 or 7)
    你有一張截圖含有目前缺的數字（0 或 7）

HOW to add your own samples 怎麼加入自己的樣本:
  1. put the screenshot in tests/fixtures/ 把截圖放進 tests/fixtures/
  2. point SUDOKU_IMAGE / PATCHES_IMAGE at it, and update the matching truth
     table (SUDOKU_GIVENS / PATCHES_LABELS) with what each position really is
     把 SUDOKU_IMAGE / PATCHES_IMAGE 指向它，並更新對應的答案表
     （SUDOKU_GIVENS / PATCHES_LABELS），寫出每個位置實際上是什麼數字
  3. or add a new collector function and list it in main()
     或者新增一個收集器函式，並在 main() 裡列上它
  4. run this script and re-run the tests 執行這支腳本，然後重跑測試

The truth tables are read by eye from the screenshots. That is the point - the
templates must come from ground truth, not from what the current recogniser
happens to output, or errors would be baked in and reinforced.
底下的對照表是人工看著截圖讀出來的。這正是重點 —— 範本必須來自事實，
而不是來自目前辨識器剛好輸出的結果，否則錯誤會被烘焙進去並自我強化。
"""

from __future__ import annotations

import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from linkedin_games_solver.core import build_grid, read_image  # noqa: E402
from linkedin_games_solver.core.digits import (  # noqa: E402
    _render_font_glyph,
    normalize_glyph,
)
from linkedin_games_solver.puzzles import patches  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures"
OUTPUT = ROOT / "linkedin_games_solver" / "core" / "digit_templates.py"

#: Digits that no screenshot contains yet, filled in from system fonts.
#: 目前沒有任何截圖含有的數字，改用系統字型補齊。
FALLBACK_DIGITS = (0, 7)
FALLBACK_FONTS = [
    "C:/Windows/Fonts/arialbd.ttf",
    "C:/Windows/Fonts/arial.ttf",
    "C:/Windows/Fonts/segoeuib.ttf",
    "C:/Windows/Fonts/segoeui.ttf",
    "C:/Windows/Fonts/calibrib.ttf",
    "C:/Windows/Fonts/verdana.ttf",
]

# --------------------------------------------------------------------------
# Ground truth, read by eye. 人工判讀的正確答案。
# --------------------------------------------------------------------------
#: Mini Sudoku givens: (row, col) -> digit. 數獨題目給的數字。
SUDOKU_GIVENS = {
    (0, 0): 1, (0, 1): 2,
    (1, 0): 3, (1, 1): 4,
    (2, 0): 2, (2, 5): 1,
    (3, 0): 4, (3, 5): 3,
    (4, 4): 1, (4, 5): 2,
    (5, 4): 3, (5, 5): 5,
}

#: Patches labels: (row, col) -> number on the badge. Patches 標籤上的數字。
PATCHES_LABELS = {
    (0, 1): 4, (0, 5): 6, (1, 2): 6, (1, 6): 9,
    (3, 4): 3, (4, 3): 8, (6, 1): 12, (6, 5): 2,
    (7, 2): 6, (7, 6): 8,
}

SUDOKU_IMAGE = "S__104316935_0.jpg"
PATCHES_IMAGE = "S__104316936_0.jpg"


# --------------------------------------------------------------------------
# Collectors 收集器
# --------------------------------------------------------------------------
def from_sudoku_cells() -> dict[int, list[np.ndarray]]:
    """Digits printed inside the Sudoku grid. 數獨格子裡印的數字。"""
    out: dict[int, list[np.ndarray]] = {}
    image = read_image(FIXTURES / SUDOKU_IMAGE)
    if image is None:
        return out
    grid = build_grid(image)
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    for (r, c), digit in SUDOKU_GIVENS.items():
        x, y, w, h = grid.cell_boxes[r][c]
        # Inset well inside the cell so grid lines are not read as strokes.
        # 往格子內縮很多，避免把格線讀成筆畫。
        sub = gray[y + int(h * 0.15) : y + int(h * 0.85), x + int(w * 0.15) : x + int(w * 0.85)]
        glyph = normalize_glyph(sub < 128)
        if glyph is not None:
            out.setdefault(digit, []).append(glyph)
    return out


def from_sudoku_keypad() -> dict[int, list[np.ndarray]]:
    """The on-screen number pad below the board. 棋盤下方的數字鍵盤。

    Worth harvesting because it shows all of 1-6 even when the board itself
    never displays some of them.
    值得取樣，因為就算棋盤上沒出現過某些數字，鍵盤上 1-6 一定都有。
    """
    out: dict[int, list[np.ndarray]] = {}
    image = read_image(FIXTURES / SUDOKU_IMAGE)
    if image is None:
        return out
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    h_img, w_img = gray.shape

    # Keypad location as a fraction of the screenshot, measured on the sample.
    # 鍵盤位置，以截圖比例表示；數值是量這張樣本得到的。
    region = gray[int(h_img * 0.685) : int(h_img * 0.845), int(w_img * 0.03) : int(w_img * 0.72)]
    mask = (region < 150).astype(np.uint8)
    num, labels, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)

    boxes = []
    for label in range(1, num):
        x, y, w, h, area = stats[label]
        if area < 300 or h < 25:
            continue
        if not (0.25 <= w / h <= 1.3):  # digit-shaped 數字的長寬比
            continue
        boxes.append((x, y, w, h, label))
    if len(boxes) < 6:
        return out

    # Two rows of three: 1 2 3 / 4 5 6. 兩排各三個：1 2 3 / 4 5 6。
    boxes.sort(key=lambda b: b[1])
    row_height = float(np.median([b[3] for b in boxes]))
    rows: list[list] = []
    for box in boxes:
        if rows and abs(box[1] - rows[-1][0][1]) <= row_height:
            rows[-1].append(box)
        else:
            rows.append([box])

    digit = 1
    for row in rows[:2]:
        row.sort(key=lambda b: b[0])
        for x, y, w, h, label in row[:3]:
            glyph = normalize_glyph(labels[y : y + h, x : x + w] == label)
            if glyph is not None and digit <= 6:
                out.setdefault(digit, []).append(glyph)
            digit += 1
    return out


def from_patches_labels() -> dict[int, list[np.ndarray]]:
    """White digits on the coloured Patches badges, including "12".
    Patches 彩色標籤上的白色數字，包含兩位數的「12」。"""
    out: dict[int, list[np.ndarray]] = {}
    image = read_image(FIXTURES / PATCHES_IMAGE)
    if image is None:
        return out
    try:
        grid = build_grid(image)
        labels = patches.find_labels(image, grid)
        # find_labels only locates the badges; read_label_value is what extracts
        # the digit bitmaps onto label.glyphs.
        # find_labels 只負責找到標籤位置；是 read_label_value 才把數字點陣圖
        # 抽出來放進 label.glyphs。
        for label in labels:
            patches.read_label_value(image, label)
    except Exception:
        return out

    for label in labels:
        digit = PATCHES_LABELS.get((label.row, label.col))
        if digit is None:
            continue
        text = str(digit)
        # Only trust a label whose glyph count matches the expected digit count,
        # otherwise the split was wrong and the pairing would be garbage.
        # 只信任「切出的字形數量」與「預期位數」相符的標籤，
        # 否則就是切錯了，配對起來會是垃圾。
        if len(label.glyphs) != len(text):
            continue
        for glyph, char in zip(label.glyphs, text):
            out.setdefault(int(char), []).append(glyph)
    return out


def from_fonts() -> dict[int, list[np.ndarray]]:
    """System-font stand-ins for digits no screenshot covers.
    截圖沒涵蓋到的數字，用系統字型補。"""
    out: dict[int, list[np.ndarray]] = {}
    for digit in FALLBACK_DIGITS:
        for font in FALLBACK_FONTS:
            if not Path(font).exists():
                continue
            try:
                glyph = _render_font_glyph(str(digit), font)
            except Exception:
                continue
            if glyph is not None:
                out.setdefault(digit, []).append(glyph)
    return out


# --------------------------------------------------------------------------
# Output 輸出
# --------------------------------------------------------------------------
def pack(glyph: np.ndarray) -> bytes:
    return np.packbits(glyph.astype(np.uint8).reshape(-1)).tobytes()


def dedupe(glyphs: list[np.ndarray]) -> list[np.ndarray]:
    """Drop near-identical glyphs; more copies of the same shape add nothing.
    丟掉幾乎相同的字形；同一個形狀存很多份沒有幫助。"""
    kept: list[np.ndarray] = []
    for glyph in glyphs:
        if all(np.logical_xor(glyph, k).sum() > 8 for k in kept):
            kept.append(glyph)
    return kept


HEADER = '''"""
Auto-generated digit glyph templates, calibrated from real app screenshots.
自動產生的數字字形範本，從實際 App 截圖校準而來。

Do not edit by hand - regenerate with tools/calibrate_digits.py.
不要手動編輯；要更新請重跑 tools/calibrate_digits.py。

Why calibrated templates instead of a system font:
  this app's "5" has an unusually round bowl, and most Windows fonts classify
  it as a "6". Glyphs taken from the app itself match exactly.
為什麼要用校準範本而不是系統字型：
  這個 App 的「5」下半部特別圓，多數 Windows 字型會把它判成「6」。
  直接取自 App 本身的字形才會完全吻合。

Two tables 兩張表:
  APP_TEMPLATES      - captured from the app. Authoritative.
                       取自 App 本身，可信度最高。
  FALLBACK_TEMPLATES - font-rendered stand-ins for digits no capture contains
                       yet (0 and 7). Baked in as bytes rather than rendered at
                       runtime, so the program does not depend on a font file
                       existing on the machine - see the note below.
                       目前還沒有截到的數字（0 與 7）用系統字型算繪的替代品。
                       直接烘焙成位元組而不是執行時算繪，
                       這樣程式就不依賴機器上存在某個字型檔 —— 理由見下。

Why 0 and 7 are baked in rather than rendered on demand 為什麼 0 與 7 要烘焙進來:
  These two were previously rendered from C:/Windows/Fonts at import time. On a
  machine without those fonts the templates were simply absent, and matching
  then picked the closest WRONG digit with high confidence: a "0" scored 0.89 as
  a "6" and a "7" scored 0.76 as a "2" - both far above the acceptance floor.
  A missing font must never turn into a confidently wrong number.
  這兩個數字原本是在 import 時從 C:/Windows/Fonts 算繪出來的。在沒有那些字型的
  機器上，範本就直接不存在，比對於是以高信心挑了最接近的「錯誤」數字：
  「0」以 0.89 被判成「6」、「7」以 0.76 被判成「2」—— 兩者都遠高於接受門檻。
  缺一個字型檔，絕不能變成一個很有信心的錯誤數字。
"""
'''


def emit(name: str, table: dict[int, list[np.ndarray]], comment: list[str]) -> list[str]:
    lines = list(comment)
    lines.append(f"{name}: dict[int, list[bytes]] = {{")
    for digit in sorted(table):
        lines.append(f"    {digit}: [")
        for glyph in dedupe(table[digit]):
            lines.append(f"        {pack(glyph)!r},")
        lines.append("    ],")
    lines.append("}")
    return lines


def main() -> int:
    app: dict[int, list[np.ndarray]] = {}
    for collector in (from_sudoku_cells, from_sudoku_keypad, from_patches_labels):
        try:
            part = collector()
        except Exception as exc:
            print(f"  {collector.__name__} failed / 失敗: {exc}")
            continue
        summary = ", ".join(f"{d}x{len(v)}" for d, v in sorted(part.items())) or "(nothing)"
        print(f"  {collector.__name__}: {summary}")
        for digit, glyphs in part.items():
            app.setdefault(digit, []).extend(glyphs)

    fallback = from_fonts()
    print("  from_fonts: " + ", ".join(f"{d}x{len(v)}" for d, v in sorted(fallback.items())))

    covered = set(app) | set(fallback)
    missing = sorted(set(range(10)) - covered)
    if missing:
        # A digit with no template at all is the failure mode this whole file
        # exists to prevent - refuse to write a set that has one.
        # 「某個數字完全沒有範本」正是這整個檔案要避免的失敗模式 ——
        # 缺任何一個就拒絕寫出。
        print(f"\nREFUSING TO WRITE / 拒絕寫出: no template for {missing}.")
        print("A digit with no template is silently misread as another digit.")
        print("缺範本的數字會被默默讀成別的數字。")
        return 1

    lines = [HEADER]
    lines.extend(emit("APP_TEMPLATES", app, []))
    lines.extend(emit("FALLBACK_TEMPLATES", fallback, [
        "",
        "",
        "#: Font-rendered stand-ins for digits not yet captured from the app.",
        "#: Regenerate together with APP_TEMPLATES via tools/calibrate_digits.py.",
        "#: 尚未從 App 截到的數字，用系統字型算繪的替代品。",
        "#: 要更新請跟 APP_TEMPLATES 一起用 tools/calibrate_digits.py 重新產生。",
    ]))

    OUTPUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\nwrote / 已寫出 {OUTPUT}")
    print(f"  from app screenshots / 來自截圖: {sorted(app)}")
    print(f"  from system fonts / 來自系統字型: {sorted(fallback)}")
    print("\nNow re-run the tests / 請重跑測試: python tests/run_all.py")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
