"""
從實際的 App 截圖校準數字字形範本，產生 digit_templates.py。

為什麼需要這一步：這個 App 用的字型 (iOS 系統字型) 有些數字跟 Windows 字型
差異夠大會誤判 (實測它的 "5" 下半部很圓，用一般字型比對容易被判成 "6")。
直接從截圖取出真正的字形當範本最準。

用法 (只有在新增樣本、或 App 改字型時才需要重跑):
    python calibrate_digits.py

會讀取 samples/ 下的截圖 + 下面寫死的正確答案，輸出 digit_templates.py。
"""

import base64
from pathlib import Path

import cv2
import numpy as np

from board import build_grid
from digit_ocr import GLYPH_SIZE, normalize_glyph
from img_io import imread_unicode

SAMPLES = Path(__file__).parent / "samples"

# Mini Sudoku 截圖裡格內已有的數字 (人工讀出來的正確答案)
SUDOKU_GRID_TRUTH = {
    (0, 0): 1, (0, 1): 2,
    (1, 0): 3, (1, 1): 4,
    (2, 0): 2, (2, 5): 1,
    (3, 0): 4, (3, 5): 3,
    (4, 4): 1, (4, 5): 2,
    (5, 4): 3, (5, 5): 5,
}


def collect_from_sudoku() -> dict[int, list[np.ndarray]]:
    out: dict[int, list[np.ndarray]] = {}
    img = imread_unicode(SAMPLES / "S__104316935_0.jpg")
    if img is None:
        return out
    grid = build_grid(img)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    for (r, c), digit in SUDOKU_GRID_TRUTH.items():
        x, y, w, h = grid.cell_boxes[r][c]
        sub = gray[y + int(h * 0.15) : y + int(h * 0.85), x + int(w * 0.15) : x + int(w * 0.85)]
        glyph = normalize_glyph(sub < 128)
        if glyph is not None:
            out.setdefault(digit, []).append(glyph)
    return out


def collect_from_sudoku_keypad() -> dict[int, list[np.ndarray]]:
    """
    數字鍵盤上有 1-6 全部的字形，可以補齊格內沒出現過的數字 (例如 6)。
    鍵盤在棋盤下方，六個按鍵排成 2 列 x 4 欄 (第 4 欄是清除/復原，不是數字)。
    """
    out: dict[int, list[np.ndarray]] = {}
    img = imread_unicode(SAMPLES / "S__104316935_0.jpg")
    if img is None:
        return out
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    h_img, w_img = gray.shape

    # 鍵盤區域 (相對整張截圖的比例，依實測截圖抓的範圍)
    top, bottom = int(h_img * 0.685), int(h_img * 0.845)
    left, right = int(w_img * 0.03), int(w_img * 0.72)
    region = gray[top:bottom, left:right]

    mask = (region < 150).astype(np.uint8)
    num, labels, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    boxes = []
    for label in range(1, num):
        x, y, w, h, area = stats[label]
        if area < 300 or h < 25:
            continue
        if not (0.25 <= w / h <= 1.3):
            continue
        boxes.append((x, y, w, h, label))

    # 依 (列, 欄) 排序: 上排是 1,2,3 下排是 4,5,6
    if len(boxes) < 6:
        return out
    boxes.sort(key=lambda b: b[1])
    row_height = np.median([b[3] for b in boxes])
    rows: list[list] = []
    for b in boxes:
        if rows and abs(b[1] - rows[-1][0][1]) <= row_height:
            rows[-1].append(b)
        else:
            rows.append([b])
    digit = 1
    for row in rows[:2]:
        row.sort(key=lambda b: b[0])
        for x, y, w, h, label in row[:3]:
            component = labels[y : y + h, x : x + w] == label
            glyph = normalize_glyph(component)
            if glyph is not None and digit <= 6:
                out.setdefault(digit, []).append(glyph)
            digit += 1
    return out


def collect_from_patches() -> dict[int, list[np.ndarray]]:
    """Patches 的標籤是彩色圓角方塊 + 白色數字，數字有 4/6/9/3/8/12/2/6/8。"""
    from puzzle_patches import find_labels  # 延後匯入避免循環依賴

    out: dict[int, list[np.ndarray]] = {}
    img = imread_unicode(SAMPLES / "S__104316936_0.jpg")
    if img is None:
        return out
    truth_by_position = {
        (0, 1): 4, (0, 5): 6, (1, 2): 6, (1, 6): 9,
        (3, 4): 3, (4, 3): 8, (6, 1): 12, (6, 5): 2,
        (7, 2): 6, (7, 6): 8,
    }
    try:
        grid = build_grid(img)
        labels = find_labels(img, grid)
    except Exception:
        return out
    for label in labels:
        digit = truth_by_position.get((label.row, label.col))
        if digit is None:
            continue
        glyphs = label.glyphs
        text = str(digit)
        if len(glyphs) != len(text):
            continue
        for glyph, ch in zip(glyphs, text):
            out.setdefault(int(ch), []).append(glyph)
    return out


def pack(glyph: np.ndarray) -> bytes:
    return np.packbits(glyph.astype(np.uint8).reshape(-1)).tobytes()


def dedupe(glyphs: list[np.ndarray]) -> list[np.ndarray]:
    kept: list[np.ndarray] = []
    for g in glyphs:
        if all(np.logical_xor(g, k).sum() > 8 for k in kept):
            kept.append(g)
    return kept


def main():
    collected: dict[int, list[np.ndarray]] = {}
    for collector in (collect_from_sudoku, collect_from_sudoku_keypad, collect_from_patches):
        try:
            part = collector()
        except Exception as e:
            print(f"  {collector.__name__} 失敗: {e}")
            continue
        print(f"  {collector.__name__}: " + ", ".join(f"{d}x{len(v)}" for d, v in sorted(part.items())))
        for digit, glyphs in part.items():
            collected.setdefault(digit, []).extend(glyphs)

    lines = [
        '"""',
        "自動產生的數字字形範本 (由 calibrate_digits.py 從實際 App 截圖校準)。",
        "不要手動編輯；要更新請重跑 calibrate_digits.py。",
        '"""',
        "",
        "APP_TEMPLATES: dict[int, list[bytes]] = {",
    ]
    for digit in sorted(collected):
        glyphs = dedupe(collected[digit])
        lines.append(f"    {digit}: [")
        for g in glyphs:
            lines.append(f"        {base64.b64decode(base64.b64encode(pack(g)))!r},")
        lines.append("    ],")
    lines.append("}")

    out_path = Path(__file__).parent / "digit_templates.py"
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"已寫出 {out_path}")
    print("涵蓋數字:", sorted(collected))


if __name__ == "__main__":
    main()
