"""
Persisted user settings.
使用者設定的存取。

Stored in the home directory rather than next to the executable, so the app
works from a read-only folder and settings survive replacing the .exe.
存在家目錄而不是執行檔旁邊，這樣程式放在唯讀資料夾也能運作，
而且換掉 .exe 之後設定還在。
"""

from __future__ import annotations

import json
from pathlib import Path

SETTINGS_PATH = Path.home() / ".linkedin_games_solver.json"

DEFAULTS = {
    "region": None,        # None = compute from the current monitor 由目前螢幕算出
    "fullscreen": False,
    "speed": "normal",
    "language": "zh",
    "mode": "screen",      # "screen" or "image" 螢幕或圖片模式
}


def load() -> dict:
    data = dict(DEFAULTS)
    try:
        if SETTINGS_PATH.exists():
            stored = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
            if isinstance(stored, dict):
                data.update({k: v for k, v in stored.items() if k in DEFAULTS})
    except Exception:
        # Corrupt settings must never stop the app from starting.
        # 設定檔壞掉絕對不能讓程式開不起來。
        pass
    return data


def save(data: dict) -> None:
    try:
        SETTINGS_PATH.write_text(
            json.dumps({k: data.get(k, v) for k, v in DEFAULTS.items()}, ensure_ascii=False),
            encoding="utf-8",
        )
    except Exception:
        pass
