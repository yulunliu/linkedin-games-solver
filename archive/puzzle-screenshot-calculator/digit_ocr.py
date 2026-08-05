"""
輕量數字辨識 (Mini Sudoku / Patches / Zip 都需要讀格內數字)。

不依賴 tesseract 等外部 OCR，作法是「正規化後的字形範本比對」：
  1. 把要辨識的區域二值化，取出前景連通元件當作一個個數字 (支援多位數，
     例如 Patches 的 "12")。
  2. 每個字形裁到外接框、等比縮放並置中到固定大小 (28x28)，這樣不同螢幕
     解析度、不同字級都能比對。
  3. 跟範本比對取最相似的。

範本來源有兩種，兩種都會用、取最高分：
  - `digit_templates.py`：直接從這個 App 的實際截圖校準出來的字形 (最準)，
    由 `calibrate_digits.py` 產生。
  - 系統字型 (Arial Bold) 即時算繪：補足校準範本沒涵蓋到的數字 (例如 0、7)。
"""

from pathlib import Path

import cv2
import numpy as np

GLYPH_SIZE = 28
_FONT_CANDIDATES = [
    "C:/Windows/Fonts/arialbd.ttf",
    "C:/Windows/Fonts/arial.ttf",
    "C:/Windows/Fonts/segoeuib.ttf",
]


def normalize_glyph(mask: np.ndarray, size: int = GLYPH_SIZE) -> np.ndarray | None:
    """把前景遮罩裁到外接框、等比縮放並置中到 size x size 的二值圖。"""
    ys, xs = np.nonzero(mask)
    if len(xs) == 0:
        return None
    crop = mask[ys.min() : ys.max() + 1, xs.min() : xs.max() + 1].astype(np.uint8) * 255
    h, w = crop.shape
    scale = (size - 6) / max(h, w)
    nh, nw = max(1, int(round(h * scale))), max(1, int(round(w * scale)))
    resized = cv2.resize(crop, (nw, nh), interpolation=cv2.INTER_AREA)
    out = np.zeros((size, size), np.uint8)
    oy, ox = (size - nh) // 2, (size - nw) // 2
    out[oy : oy + nh, ox : ox + nw] = resized
    return (out > 110).astype(np.uint8)


def _render_font_glyph(ch: str, font_path: str, size: int = GLYPH_SIZE) -> np.ndarray | None:
    from PIL import Image, ImageDraw, ImageFont

    font = ImageFont.truetype(font_path, 64)
    img = Image.new("L", (140, 140), 0)
    ImageDraw.Draw(img).text((70, 70), ch, fill=255, font=font, anchor="mm")
    return normalize_glyph(np.array(img) > 110, size)


def _load_templates() -> list[tuple[int, np.ndarray]]:
    templates: list[tuple[int, np.ndarray]] = []

    try:
        from digit_templates import APP_TEMPLATES

        for digit, bitmaps in APP_TEMPLATES.items():
            for bits in bitmaps:
                arr = np.unpackbits(np.frombuffer(bits, dtype=np.uint8))
                arr = arr[: GLYPH_SIZE * GLYPH_SIZE].reshape(GLYPH_SIZE, GLYPH_SIZE)
                templates.append((digit, arr.astype(np.uint8)))
    except Exception:
        pass

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
        break  # 一種字型就夠，多種字型混用反而容易互相干擾

    return templates


_TEMPLATES: list[tuple[int, np.ndarray]] | None = None


def _templates() -> list[tuple[int, np.ndarray]]:
    global _TEMPLATES
    if _TEMPLATES is None:
        _TEMPLATES = _load_templates()
    return _TEMPLATES


def _score(a: np.ndarray, b: np.ndarray) -> float:
    """對筆畫粗細/鋸齒不敏感的相似度：模糊後做正規化內積。"""
    sa = cv2.GaussianBlur(a.astype(np.float32), (5, 5), 1.2)
    sb = cv2.GaussianBlur(b.astype(np.float32), (5, 5), 1.2)
    denom = np.sqrt((sa * sa).sum() * (sb * sb).sum())
    return float((sa * sb).sum() / denom) if denom else 0.0


def classify_glyph(glyph: np.ndarray) -> tuple[int | None, float]:
    best_digit, best_score = None, -1.0
    for digit, template in _templates():
        s = _score(glyph, template)
        if s > best_score:
            best_digit, best_score = digit, s
    return best_digit, best_score


def split_digit_glyphs(mask: np.ndarray) -> list[np.ndarray]:
    """
    把前景遮罩切成一個個數字字形 (左到右)。支援多位數，例如 "12"。
    用連通元件而不是垂直投影，因為數字之間可能沒有完全分開的空白列。
    """
    num_labels, labels, stats, _ = cv2.connectedComponentsWithStats(mask.astype(np.uint8), connectivity=8)
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

    # 「1」這種細長字形可能被誤切；但也可能兩個數字黏在一起 (寬度異常寬)。
    # 先依 x 排序，再對明顯過寬的元件依寬度均分切開。
    boxes.sort(key=lambda b: b[0])
    median_h = float(np.median([b[3] for b in boxes]))

    glyphs = []
    for x, y, w, h, label in boxes:
        component = (labels[y : y + h, x : x + w] == label)
        # 一個正常數字的寬度不會超過高度太多；明顯過寬代表多個數字連在一起
        parts = max(1, int(round(w / (median_h * 0.62)))) if median_h > 0 else 1
        if parts <= 1:
            g = normalize_glyph(component)
            if g is not None:
                glyphs.append(g)
        else:
            step = w // parts
            for i in range(parts):
                x0 = i * step
                x1 = w if i == parts - 1 else (i + 1) * step
                g = normalize_glyph(component[:, x0:x1])
                if g is not None:
                    glyphs.append(g)
    return glyphs


def read_number(mask: np.ndarray, min_confidence: float = 0.55) -> int | None:
    """從前景遮罩讀出一個整數 (可能是多位數)。辨識信心不足回傳 None。"""
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
