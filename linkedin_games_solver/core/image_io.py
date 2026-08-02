"""
Unicode-safe image reading / writing.
支援 Unicode 路徑的圖片讀寫。

Why this exists 為什麼需要這支模組:
  On Windows, cv2.imread / cv2.imwrite fail *silently* when the path contains
  non-ASCII characters - they return None / False instead of raising. A user
  whose Desktop path contains Chinese characters would just see "cannot read
  image" with no clue why. Routing every read/write through np.fromfile +
  cv2.imdecode (and cv2.imencode + tofile) sidesteps the OpenCV path handling
  entirely.
  在 Windows 上，路徑含非 ASCII 字元時 cv2.imread / cv2.imwrite 會「靜默失敗」
  ——回傳 None / False 而不是丟例外。使用者的桌面路徑只要有中文，就會看到
  「讀不到圖片」卻毫無線索。改走 np.fromfile + cv2.imdecode（寫入則是
  cv2.imencode + tofile）就完全繞開 OpenCV 的路徑處理。

Always use these helpers; never call cv2.imread / cv2.imwrite directly.
請一律使用這裡的函式，不要直接呼叫 cv2.imread / cv2.imwrite。
"""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np


def read_image(path: str | Path, flags: int = cv2.IMREAD_COLOR) -> np.ndarray | None:
    """Read an image, returning None if it does not exist or cannot be decoded.
    讀取圖片，檔案不存在或無法解碼時回傳 None。"""
    file_path = Path(path)
    if not file_path.exists():
        return None
    raw = np.fromfile(str(file_path), dtype=np.uint8)
    if raw.size == 0:
        return None
    return cv2.imdecode(raw, flags)


def write_image(path: str | Path, image: np.ndarray) -> bool:
    """Write an image, returning True on success.
    寫出圖片，成功回傳 True。"""
    file_path = Path(path)
    # Fall back to PNG when the caller gave no extension.
    # 呼叫端沒給副檔名時預設用 PNG。
    suffix = file_path.suffix or ".png"
    ok, encoded = cv2.imencode(suffix, image)
    if not ok:
        return False
    encoded.tofile(str(file_path))
    return True
