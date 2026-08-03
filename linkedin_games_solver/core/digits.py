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
#: Measured over 325 system fonts that render 10 distinct numerals, at sizes
#: 18/26/40/64 = 13,000 samples, plus every glyph in the project's own captures.
#: 實測母體：325 種能畫出 10 個相異數字的系統字型 × 18/26/40/64 四種尺寸
#: = 13,000 個樣本，再加上專案自己所有截圖裡的字形。
MIN_SCORE = 0.90

#: Absolute floor on the gap between the best digit and the runner-up.
#: 最佳數字與第二名之間差距的絕對下限。
#:
#: THIS NUMBER IS BOUNDED BY THE TEMPLATES THEMSELVES, not chosen freely.
#: A glyph can only beat the runner-up by as much as the two templates differ.
#: Pairwise over all 45 templates, the closest cross-digit pair is 6 vs 8 at
#: similarity 0.9705, so a glyph matching an 8 PERFECTLY beats 6 by at most
#: 0.0295. Per-digit ceilings (1 - closest other digit):
#:     0: 0.067   1: 0.170   2: 0.161   3: 0.079   4: 0.170
#:     5: 0.059   6: 0.0295  7: 0.161   8: 0.0295  9: 0.067
#: The previous value of 0.04 was 136% of the ceiling for 6 and 8 - physically
#: unreachable, so every 6 and 8 was rejected however good the match. That is
#: why a Patches label scoring 0.9931 was thrown away.
#: 這個數字的上限是「範本本身」決定的，不能隨意挑。
#: 一個字形能贏第二名多少，受限於兩個範本本身差多少。45 個範本兩兩比對，
#: 最接近的跨數字組合是 6 對 8，相似度 0.9705 —— 所以即使完全吻合 8 的範本，
#: 也最多只能贏 6 0.0295。上表是每個數字的上限。
#: 舊值 0.04 是 6 與 8 上限的 136%，物理上不可能達成，
#: 所以不管比對多好，每個 6 和 8 都會被拒絕。這就是 0.9931 分的 Patches 標籤
#: 被丟掉的原因。
#:
#: 0.020 uses 68% of that ceiling. The headroom is only 1.5x, so THIS MUST BE
#: RE-MEASURED whenever tools/calibrate_digits.py is re-run - template
#: similarity is what sets the ceiling. test_min_margin_is_reachable_for_every_digit
#: enforces it.
#: 0.020 用掉上限的 68%，餘裕只有 1.5 倍。所以每次重跑
#: tools/calibrate_digits.py 都必須重新量測 —— 上限是由範本相似度決定的。
#: test_min_margin_is_reachable_for_every_digit 會強制檢查這件事。
MIN_MARGIN = 0.020

#: Required gap as a fraction of the room left below a perfect match.
#: 要求的差距，佔「距離完全吻合還剩多少」的比例。
#:
#: The gap a correct reading can achieve shrinks as the match approaches 1.000,
#: so a fixed absolute gap is the wrong shape. Required gap becomes
#:     max(MIN_MARGIN, MIN_RELATIVE_MARGIN * (1 - best_score))
#: 正確讀取能拉開的差距，會隨著吻合度接近 1.000 而變小，
#: 所以「固定的絕對差距」形狀就是錯的。要求的差距改成上式。
#:
#: DO NOT describe 0.80 as the midpoint of a gap. THERE IS NO GAP. Over the
#: 13,000-sample sweep the wrong readings' relative margin reaches 2.4 and the
#: correct readings' reaches 0.00 - the distributions overlap outright. 0.80 is
#: the LARGEST relative requirement that still lets img/capture2.png resolve,
#: and the only candidate measured to admit zero wrong readings that the old
#: gate blocked:
#:     gate                              correct admitted  wrong admitted  NEWLY wrong
#:     old   s>=0.75 & m>=0.040                 7,445            491            -
#:           s>=0.85 & max(0.012, 0.28d)        7,768            260           60
#:           s>=0.85 & max(0.020, 0.55d)        6,239            131            1
#:     this  s>=0.90 & max(0.020, 0.80d)        4,522             20            0
#: 不要把 0.80 說成「間隔的中點」。根本沒有間隔。在 13,000 個樣本的掃描裡，
#: 錯誤讀取的相對差距最高到 2.4，正確讀取最低到 0.00，兩個分布是重疊的。
#: 0.80 是「還能讓 img/capture2.png 解出來」的最嚴要求，
#: 也是唯一實測「不會放行任何舊門檻擋得住的錯誤」的候選。
#:
#: Boundary cases worth quoting 值得記下的邊界案例:
#:   capture2.png label (1,1) "8" 0.9879 / runner-up 0.9594 -> accepted 接受
#:   capture.png  dot   (5,1) "8" 0.9788 / runner-up 0.9703 -> rejected 拒絕
#: The second is a genuine coin flip and being rejected is correct.
#: 第二個是真的難分軒輊，被拒絕才是對的。
#:
#: NO MARGIN RULE DETECTS STROKE LOSS. Under heavy JPEG ringing a "4" loses its
#: diagonal and crossbar and genuinely IS a "1" in the pixels. The classifier is
#: not confused - it is confidently reading a different digit that is really
#: there. No confidence statistic can see that; only a better capture can.
#: 任何差距規則都偵測不到「筆畫掉了」。JPEG 壓縮嚴重時，「4」的斜線與橫槓會消失，
#: 在像素上它「真的就是」一個「1」。分類器沒有困惑 —— 它很有信心地讀出了
#: 一個確實存在的、不同的數字。沒有任何信心指標看得到這件事，只有更好的截圖可以。
#:
#: Cost, stated honestly: 18 of 100 foreign-font glyphs that read correctly
#: under the old gate now fail loudly. Documented fallback if that proves too
#: strict in practice: 0.85 / 0.020 / 0.55 still fixes capture2.png to the
#: identical tiling and adds exactly one new misread.
#: 誠實記錄代價：舊門檻下讀得出來的 100 個外來字型字形，現在有 18 個會明確失敗。
#: 若實務上證明太嚴，已記錄的退路是 0.85 / 0.020 / 0.55 ——
#: 一樣能讓 capture2.png 解出完全相同的切法，只多放行一個新的誤讀。
MIN_RELATIVE_MARGIN = 0.80

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


def classify_glyph(glyph: np.ndarray, allowed=None) -> tuple[int | None, float]:
    """Best matching digit and its score, or (None, score) if too ambiguous.
    最相符的數字與分數；太模稜兩可時回傳 (None, 分數)。

    Returns None when the runner-up digit is within MIN_MARGIN, because a
    confident-looking score on an ambiguous glyph is exactly how a wrong number
    reaches the solver unnoticed.
    當第二名的數字距離不到 MIN_MARGIN 時回傳 None ——
    因為「模稜兩可的字形拿到很高的分數」正是錯誤數字混進求解器的途徑。
    """
    # `allowed` lets a caller exclude digits the puzzle CANNOT contain. This is
    # not a shortcut - it removes impossible answers from the competition, so
    # the runner-up is a digit that could really be there.
    # Measured: a 6x6 Mini Sudoku holds only 1..6, and 6's closest confusable is
    # 8. Excluding 7-9 and 0 raises 6's template ceiling from 0.0295 to 0.0591 -
    # double the room - and 3's from 0.0785 to 0.1163. On the real Sudoku
    # fixture the per-glyph margin improves by +0.0148 on average, up to +0.0599.
    # Zip numbers 1..12 use all ten digits, so it gains nothing there; Patches
    # areas run to n*n which is likewise every digit. Sudoku is the only caller
    # that benefits, and pretending otherwise would be dressing up a no-op.
    # `allowed` 讓呼叫端排除「這個謎題不可能出現」的數字。這不是抄捷徑 ——
    # 它把不可能的答案移出競爭，讓第二名是一個真的可能出現的數字。
    # 實測：6x6 的 Mini Sudoku 只可能有 1~6，而 6 最容易混淆的是 8。
    # 排除 7-9 與 0 之後，6 的範本天花板從 0.0295 升到 0.0591（空間翻倍），
    # 3 從 0.0785 升到 0.1163。在真實 Sudoku 測試圖上，每個字形的差距
    # 平均改善 +0.0148，最多 +0.0599。
    # Zip 的 1~12 用到全部十個數字，所以那裡什麼都買不到；Patches 的面積
    # 上看 n*n 同樣涵蓋所有數字。Sudoku 是唯一受益的呼叫端，
    # 假裝其他地方也有效等於把一個空操作包裝成改進。
    best_per_digit: dict[int, float] = {}
    for digit, template in _templates():
        if allowed is not None and digit not in allowed:
            continue
        score = _similarity(glyph, template)
        if score > best_per_digit.get(digit, -1.0):
            best_per_digit[digit] = score
    if not best_per_digit:
        return None, 0.0

    ranked = sorted(best_per_digit.items(), key=lambda kv: -kv[1])
    best_digit, best_score = ranked[0]
    runner_up = ranked[1][1] if len(ranked) > 1 else -1.0

    # One gate, here. Callers used to apply MIN_SCORE themselves while this
    # function applied MIN_MARGIN, so the two halves of one decision lived in
    # different files and could drift apart.
    # 判斷集中在這裡。以前呼叫端自己套 MIN_SCORE、這個函式套 MIN_MARGIN，
    # 同一個決定的兩半散在不同檔案裡，可能各走各的。
    if best_score < MIN_SCORE:
        return None, best_score
    if best_score - runner_up < max(MIN_MARGIN, MIN_RELATIVE_MARGIN * (1.0 - best_score)):
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


def read_number(mask: np.ndarray, min_confidence: float = MIN_SCORE, allowed=None) -> int | None:
    """Read a whole (possibly multi-digit) integer, or None if unsure.
    讀出一個整數（可能多位數），信心不足時回傳 None。

    `allowed` restricts which DIGITS may be considered - see classify_glyph.
    Note it constrains the digits, not the resulting number: a caller wanting
    to bound the number itself must check the return value.
    `allowed` 限制的是可以被考慮的「數字」，見 classify_glyph。
    注意它限制的是數字而不是組出來的數值：想限制數值範圍的呼叫端要自己檢查回傳值。
    """
    glyphs = split_digit_glyphs(mask)
    if not glyphs:
        return None
    digits = []
    for glyph in glyphs:
        digit, score = classify_glyph(glyph, allowed=allowed)
        if digit is None or score < min_confidence:
            return None
        digits.append(str(digit))
    try:
        return int("".join(digits))
    except ValueError:
        return None
