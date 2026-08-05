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
    讀取圖片，檔案不存在或無法解碼時回傳 None。

    A directory "exists" too, and np.fromfile raises IsADirectoryError /
    PermissionError for a directory or a locked file rather than returning
    nothing - both are caught here so the documented "None, never an
    exception" contract actually holds. Measured: --image <a directory>
    raised a raw PermissionError before this.
    資料夾也算「存在」，而 np.fromfile 對資料夾或被鎖住的檔案丟的是
    IsADirectoryError／PermissionError，不是回傳空值——這裡都接住，
    讓「只回傳 None、不拋例外」這個文件寫的約定真的成立。實測：
    --image <一個資料夾> 在這個修正之前會直接丟出原始的 PermissionError。
    """
    file_path = Path(path)
    if not file_path.exists() or file_path.is_dir():
        return None
    try:
        raw = np.fromfile(str(file_path), dtype=np.uint8)
    except OSError:
        return None
    if raw.size == 0:
        return None
    return cv2.imdecode(raw, flags)


def write_image(path: str | Path, image: np.ndarray) -> bool:
    """Write an image, returning True on success, False on any failure.
    寫出圖片，成功回傳 True，任何失敗都回傳 False。

    cv2.imencode raises cv2.error rather than returning ok=False under
    OpenCV 5.0.0 (the version this project ships), and tofile() raises
    OSError for an unwritable path - both used to escape uncaught, which
    broke the documented "returns bool" contract every caller relies on.
    cv2.imencode 在這個專案用的 OpenCV 5.0.0 下，是拋出 cv2.error 而不是
    回傳 ok=False；tofile() 對寫不進去的路徑則是拋 OSError——這兩種
    以前都沒接住，直接逸出，破壞了每個呼叫端都依賴的「回傳布林值」約定。
    """
    file_path = Path(path)
    # Fall back to PNG when the caller gave no extension.
    # 呼叫端沒給副檔名時預設用 PNG。
    suffix = file_path.suffix or ".png"
    try:
        ok, encoded = cv2.imencode(suffix, image)
        if not ok:
            return False
        encoded.tofile(str(file_path))
        return True
    except (cv2.error, OSError):
        return False
