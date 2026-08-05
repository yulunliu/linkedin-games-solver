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
import sys
from pathlib import Path

from ..core import action_log

SETTINGS_PATH = Path.home() / ".linkedin_games_solver.json"

#: Folder offered by default when saving a capture.
#: 存下擷取畫面時，對話框預設開啟的資料夾。
#:
#: WHY this exists 為什麼需要這個:
#:   The save dialog used to pass no starting folder, so Windows fell back to
#:   "the last folder any file dialog used" - which was a previous project's
#:   samples directory. Saved captures landed somewhere unrelated to this app
#:   and were easy to lose.
#:   存檔對話框原本沒有指定起始資料夾，Windows 就會退回「上次任何檔案對話框
#:   用過的資料夾」—— 那是另一個舊專案的樣本目錄。存下來的畫面會跑到跟這個
#:   程式無關的地方，很容易搞丟。
CAPTURES_DIRNAME = "img"


def captures_dir() -> Path:
    """Where to offer saving captures. Created on demand.
    存擷取畫面的預設位置，需要時才建立。

    Next to the app when that is writable - captures belong with the project
    they came from. Falls back to the home directory when running from a
    read-only folder, which is the same reasoning as SETTINGS_PATH above.
    優先放在程式旁邊（畫面就該跟它來自的專案放在一起）；程式位於唯讀資料夾時
    退回家目錄 —— 理由跟上面 SETTINGS_PATH 一樣。
    """
    if getattr(sys, "frozen", False):
        base = Path(sys.executable).resolve().parent
    else:
        base = Path(__file__).resolve().parents[2]

    for candidate in (base / CAPTURES_DIRNAME, Path.home() / ".linkedin_games_solver_captures"):
        try:
            candidate.mkdir(parents=True, exist_ok=True)
            return candidate
        except OSError:
            continue
    return Path.home()

DEFAULTS = {
    "region": None,        # None = compute from the current monitor 由目前螢幕算出
    "fullscreen": False,
    "speed": "normal",
    "language": "zh",
    "mode": "screen",      # "screen" or "image" 螢幕或圖片模式
}


def _valid_region(value) -> bool:
    """Exactly four ints, width and height both positive.
    剛好四個整數，寬跟高都是正數。

    WHY 為什麼: _apply_settings used to do str(int(v)) over whatever load()
    handed back, with no shape check first. Eight malformed shapes were
    tried (wrong length, strings, nested lists, negative numbers...) and each
    raised at startup - in the shipped windowed .exe that is "double-click,
    and nothing happens", with fullscreen having no UI so hand-editing the
    settings file was the only way to reach a bad value at all.
    為什麼：_apply_settings 以前是對 load() 回傳的東西直接做 str(int(v))，
    完全沒先檢查形狀。試過八種不合法的形狀（長度不對、字串、巢狀 list、
    負數……），每一種都會在啟動時拋錯——在打包好的視窗版 exe 上就是
    「點兩下，什麼都沒發生」，而 fullscreen 又沒有介面，手改設定檔是唯一
    能碰到壞值的方式。
    """
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        return False
    try:
        left, top, width, height = (int(v) for v in value)
    except (TypeError, ValueError):
        return False
    return width > 0 and height > 0


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
    if data.get("region") is not None and not _valid_region(data["region"]):
        action_log.log("WARN", f"settings.load(): malformed region {data['region']!r} "
                        f"discarded, falling back to default")
        data["region"] = DEFAULTS["region"]  # None -> caller computes a fresh default
    return data


def save(data: dict) -> None:
    try:
        SETTINGS_PATH.write_text(
            json.dumps({k: data.get(k, v) for k, v in DEFAULTS.items()}, ensure_ascii=False),
            encoding="utf-8",
        )
    except Exception:
        pass
