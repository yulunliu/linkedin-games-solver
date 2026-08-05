"""
cv2.imread / cv2.imwrite 在 Windows 上遇到路徑含非 ASCII 字元 (例如中文資料夾、
中文檔名) 時會靜默失敗 (回傳 None / False，不丟例外)。這裡的路徑本身就含中文
("linkedin謎題暴力解")，使用者選圖的路徑也很可能含中文 (桌面、下載等資料夾)，
所以一律改用 np.fromfile + cv2.imdecode / cv2.imencode + tofile 來讀寫。
"""

from pathlib import Path

import cv2
import numpy as np


def imread_unicode(path: str | Path, flags: int = cv2.IMREAD_COLOR) -> np.ndarray | None:
    p = Path(path)
    if not p.exists():
        return None
    data = np.fromfile(str(p), dtype=np.uint8)
    if data.size == 0:
        return None
    return cv2.imdecode(data, flags)


def imwrite_unicode(path: str | Path, image: np.ndarray) -> bool:
    p = Path(path)
    ext = p.suffix if p.suffix else ".png"
    ok, encoded = cv2.imencode(ext, image)
    if not ok:
        return False
    encoded.tofile(str(p))
    return True
