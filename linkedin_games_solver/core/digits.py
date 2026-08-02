"""
Lightweight digit recognition (used by Mini Sudoku, Patches and Zip).
輕量數字辨識（Mini Sudoku、Patches、Zip 都會用到）。

No external OCR engine 不依賴外部 OCR 引擎:
  Tesseract would add a heavy native dependency to a single-file executable for
  what is a very narrow problem - reading one or two clean, high-contrast digits
  rendered in a fixed UI font. Normalised template matching is a few hundred
  lines and packages trivially.
  為了讀一兩個乾淨、高對比、固定字型的數字而引入 Tesseract，會讓單一執行檔
  背上沉重的原生相依。正規化後的範本比對只要幾百行，而且打包毫無負擔。

Pipeline 流程:
  1. binarise the region, take connected components as candidate glyphs
     (supports multi-digit values such as Patches' "12")
  2. crop each glyph to its bounding box, scale and centre it into a fixed
     28x28 bitmap - this makes recognition independent of screen resolution
  3. compare against templates and take the best match
  1. 二值化後取連通元件當候選字形（支援多位數，例如 Patches 的 "12"）
  2. 每個字形裁到外接框、等比縮放並置中到固定的 28x28 —— 這一步讓辨識
     不受螢幕解析度影響
  3. 跟範本比對取最相似的
"""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

GLYPH_SIZE = 28

#: Minimum similarity for a glyph to be accepted at all.
#: 一個字形要被接受的最低相似度。
#:
#: Digits from the app itself score 0.995 and above. Rendered in ten other
#: fonts, correct matches sit at 0.83+ while the ambiguous "1" shapes (a bare
#: stroke with no flag) land at 0.70-0.79 - and those are exactly the ones that
#: get misread. Raising the floor to 0.75 costs one correct read out of a
#: hundred and removes a whole family of wrong ones.
#: 來自 App 本身的數字分數都在 0.995 以上。用另外十種字型算繪時，
#: 正確比對落在 0.83 以上，而模稜兩可的「1」（沒有起筆撇的單一豎線）
#: 落在 0.70~0.79 —— 而那些正是會被讀錯的。門檻拉到 0.75 只損失百分之一的
#: 正確讀取，卻消掉一整類的錯誤。
MIN_SCORE = 0.75

#: Minimum gap between the best digit and the runner-up.
#: 最佳數字與第二名之間必須拉開的差距。
#:
#: Score alone does not separate right from wrong. Measured over every
#: calibrated glyph plus the same digits rendered in six other fonts:
#:   correct matches   - margin 0.048 and above (median 0.102)
#:   incorrect matches - margin 0.031 and below (but scoring up to 0.944!)
#: A wrong "6"->"5" scored 0.944, comfortably over any sensible score floor, and
#: was only distinguishable by how close the runner-up was. Anything inside the
#: gap is reported as unreadable, which callers already handle.
#: 光看分數分不出對錯。用全部校準字形，加上同樣的數字以另外六種字型算繪，實測：
#:   正確比對 —— 差距 0.048 以上（中位數 0.102）
#:   錯誤比對 —— 差距 0.031 以下（但分數可高達 0.944！）
#: 一個把「6」判成「5」的錯誤拿到 0.944 分，遠高於任何合理的分數門檻，
#: 唯一能分辨的線索就是第二名貼得多近。落在這個間隔內一律回報成讀不出來，
#: 呼叫端本來就有處理這種情形。
MIN_MARGIN = 0.04

#: Extra fonts consulted at import time, on top of the baked-in templates.
#: Purely additive - the program works without any of them.
#: 除了烘焙進來的範本之外，import 時再參考的字型。純粹是加分項 —— 一個都沒有也能運作。
_FONT_CANDIDATES = [
    "C:/Windows/Fonts/arialbd.ttf",
    "C:/Windows/Fonts/arial.ttf",
    "C:/Windows/Fonts/segoeuib.ttf",
]


def normalize_glyph(mask: np.ndarray, size: int = GLYPH_SIZE) -> np.ndarray | None:
    """Crop to bounding box, scale proportionally, centre into a size x size bitmap.
    裁到外接框、等比縮放並置中到 size x size 的點陣圖。"""
    ys, xs = np.nonzero(mask)
    if len(xs) == 0:
        return None
    crop = mask[ys.min() : ys.max() + 1, xs.min() : xs.max() + 1].astype(np.uint8) * 255
    h, w = crop.shape
    scale = (size - 6) / max(h, w)
    new_h, new_w = max(1, int(round(h * scale))), max(1, int(round(w * scale)))
    resized = cv2.resize(crop, (new_w, new_h), interpolation=cv2.INTER_AREA)
    out = np.zeros((size, size), np.uint8)
    oy, ox = (size - new_h) // 2, (size - new_w) // 2
    out[oy : oy + new_h, ox : ox + new_w] = resized
    return (out > 110).astype(np.uint8)


def _render_font_glyph(char: str, font_path: str, size: int = GLYPH_SIZE) -> np.ndarray | None:
    from PIL import Image, ImageDraw, ImageFont

    font = ImageFont.truetype(font_path, 64)
    canvas = Image.new("L", (140, 140), 0)
    ImageDraw.Draw(canvas).text((70, 70), char, fill=255, font=font, anchor="mm")
    return normalize_glyph(np.array(canvas) > 110, size)


def _unpack(packed: bytes) -> np.ndarray:
    bits = np.unpackbits(np.frombuffer(packed, dtype=np.uint8))
    return bits[: GLYPH_SIZE * GLYPH_SIZE].reshape(GLYPH_SIZE, GLYPH_SIZE).astype(np.uint8)


def _load_templates() -> list[tuple[int, np.ndarray]]:
    """Build the template set. Every digit 0-9 must be present.
    組出範本集合。0-9 每個數字都必須有範本。

    A digit with NO template is the worst possible state: matching silently
    picks the nearest wrong digit. Both tables are baked into the source, so
    coverage never depends on the machine.
    某個數字「完全沒有範本」是最糟的狀態：比對會默默挑一個最接近的錯誤數字。
    兩張表都烘焙在原始碼裡，所以涵蓋範圍不會因機器而異。
    """
    templates: list[tuple[int, np.ndarray]] = []

    from .digit_templates import APP_TEMPLATES, FALLBACK_TEMPLATES

    # Calibrated glyphs from the real app take priority (exact match).
    # 從實際 App 校準出來的字形優先（完全吻合）。
    for table in (APP_TEMPLATES, FALLBACK_TEMPLATES):
        for digit, bitmaps in table.items():
            for packed in bitmaps:
                templates.append((digit, _unpack(packed)))

    # System fonts are additive only. Previously they were the ONLY source for
    # 0 and 7, which meant a machine without the font read a "7" as a "2" at
    # 0.76 confidence. Now they merely add variants for glyphs already covered.
    # 系統字型只是加分項。它們以前是 0 與 7 的唯一來源 ——
    # 沒有那個字型的機器會用 0.76 的信心把「7」讀成「2」。
    # 現在它們只是替已經有範本的字形多加幾種寫法。
    for font_path in _FONT_CANDIDATES:
        if not Path(font_path).exists():
            continue
        try:
            for digit in range(10):
                glyph = _render_font_glyph(str(digit), font_path)
                if glyph is not None:
                    templates.append((digit, glyph))
        except Exception:
            continue
        break

    return templates


_TEMPLATES: list[tuple[int, np.ndarray]] | None = None


def _templates() -> list[tuple[int, np.ndarray]]:
    global _TEMPLATES
    if _TEMPLATES is None:
        _TEMPLATES = _load_templates()
    return _TEMPLATES


def _similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Blur-tolerant similarity, so stroke weight and anti-aliasing matter less.
    對筆畫粗細與鋸齒不敏感的相似度。"""
    sa = cv2.GaussianBlur(a.astype(np.float32), (5, 5), 1.2)
    sb = cv2.GaussianBlur(b.astype(np.float32), (5, 5), 1.2)
    denom = np.sqrt((sa * sa).sum() * (sb * sb).sum())
    return float((sa * sb).sum() / denom) if denom else 0.0


def classify_glyph(glyph: np.ndarray) -> tuple[int | None, float]:
    """Best matching digit and its score, or (None, score) if too ambiguous.
    最相符的數字與分數；太模稜兩可時回傳 (None, 分數)。

    Returns None when the runner-up digit is within MIN_MARGIN, because a
    confident-looking score on an ambiguous glyph is exactly how a wrong number
    reaches the solver unnoticed.
    當第二名的數字距離不到 MIN_MARGIN 時回傳 None ——
    因為「模稜兩可的字形拿到很高的分數」正是錯誤數字混進求解器的途徑。
    """
    best_per_digit: dict[int, float] = {}
    for digit, template in _templates():
        score = _similarity(glyph, template)
        if score > best_per_digit.get(digit, -1.0):
            best_per_digit[digit] = score
    if not best_per_digit:
        return None, 0.0

    ranked = sorted(best_per_digit.items(), key=lambda kv: -kv[1])
    best_digit, best_score = ranked[0]
    runner_up = ranked[1][1] if len(ranked) > 1 else -1.0
    if best_score - runner_up < MIN_MARGIN:
        return None, best_score
    return best_digit, best_score


def split_digit_glyphs(mask: np.ndarray) -> list[np.ndarray]:
    """Split a foreground mask into left-to-right glyphs (handles "12").
    把前景遮罩切成由左至右的字形（支援 "12" 這種兩位數）。"""
    num_labels, labels, stats, _ = cv2.connectedComponentsWithStats(
        mask.astype(np.uint8), connectivity=8
    )
    total_area = mask.sum()
    if total_area == 0:
        return []

    boxes = []
    for label in range(1, num_labels):
        x, y, w, h, area = stats[label]
        if area < total_area * 0.05:
            continue
        boxes.append((x, y, w, h, label))
    if not boxes:
        return []

    boxes.sort(key=lambda b: b[0])
    median_height = float(np.median([b[3] for b in boxes]))

    glyphs = []
    for x, y, w, h, label in boxes:
        component = labels[y : y + h, x : x + w] == label
        # An unusually wide component is two touching digits; split by width.
        # 異常寬的元件是兩個黏在一起的數字，依寬度均分切開。
        parts = max(1, int(round(w / (median_height * 0.62)))) if median_height > 0 else 1
        if parts <= 1:
            glyph = normalize_glyph(component)
            if glyph is not None:
                glyphs.append(glyph)
        else:
            step = w // parts
            for i in range(parts):
                x0 = i * step
                x1 = w if i == parts - 1 else (i + 1) * step
                glyph = normalize_glyph(component[:, x0:x1])
                if glyph is not None:
                    glyphs.append(glyph)
    return glyphs


def read_number(mask: np.ndarray, min_confidence: float = MIN_SCORE) -> int | None:
    """Read a whole (possibly multi-digit) integer, or None if unsure.
    讀出一個整數（可能多位數），信心不足時回傳 None。"""
    glyphs = split_digit_glyphs(mask)
    if not glyphs:
        return None
    digits = []
    for glyph in glyphs:
        digit, score = classify_glyph(glyph)
        if digit is None or score < min_confidence:
            return None
        digits.append(str(digit))
    try:
        return int("".join(digits))
    except ValueError:
        return None
