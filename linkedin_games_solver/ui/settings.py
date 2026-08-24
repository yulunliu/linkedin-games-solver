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
import os
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

    Checks action_log.LOG_DIR_ENV_VAR first, same override and same reasoning
    as action_log._resolve_dir() - unset for every ordinary user of the
    published exe (default behaviour above is unchanged for them), only set
    locally by a developer who wants several checkouts/worktrees of this
    project to share one folder instead of each accumulating its own.
    先檢查 action_log.LOG_DIR_ENV_VAR，跟 action_log._resolve_dir() 同一個
    覆寫、同一個理由——已發布 exe 的一般使用者都不會設定（對他們來說上面的
    預設行為不變），只有想讓本機好幾份 checkout/worktree 共用同一個資料夾、
    而不是各自累積一份的開發者，才會在本機設定它。
    """
    env_dir = os.environ.get(action_log.LOG_DIR_ENV_VAR)
    if env_dir:
        candidate = Path(env_dir) / CAPTURES_DIRNAME
        candidate.mkdir(parents=True, exist_ok=True)
        return candidate

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


#: Subfolder for auto-harvested digit-calibration candidates - see
#: ui/app.py's _harvest_calibration_candidates.
#: 自動收集的數字校準候選資料子資料夾——見 ui/app.py 的
#: _harvest_calibration_candidates。
CALIBRATION_CANDIDATES_DIRNAME = "calibration_candidates"


def calibration_candidates_dir() -> Path:
    """Where auto-harvested digit-calibration candidates are saved.
    自動收集的數字校準候選資料要存到哪裡。

    A SEPARATE folder from captures_dir(), not a subfolder of it. WHY 為什麼:
    captures_dir() is what the "Save" button offers the user, and what a
    person browses when reporting a bug - it must only ever contain images a
    human chose to keep. These candidates are written automatically, without
    the user asking, specifically to be reviewed later before anything is
    fed into tools/calibrate_digits.py (see that module and this project's
    core rule: no threshold or template change without a human looking at
    real evidence first). Mixing the two would make an automatic write look
    like something the user saved on purpose.
    是跟 captures_dir() 分開的資料夾，不是它底下的子資料夾。為什麼：
    captures_dir() 是「存圖」按鈕提供的位置，也是使用者回報問題時會去看的
    地方——裡面應該只有人「主動選擇留下」的圖片。這些候選資料是程式自動、
    在使用者沒有要求的情況下寫入的，目的是留給之後人工檢視，再決定要不要
    餵進 tools/calibrate_digits.py（見該模組與本專案的核心規則：沒有人先看過
    真實證據，不能改動任何門檻或範本）。混在一起會讓自動寫入的東西看起來
    像是使用者自己存的。
    """
    base = captures_dir()
    candidate = base / CALIBRATION_CANDIDATES_DIRNAME
    try:
        candidate.mkdir(parents=True, exist_ok=True)
        return candidate
    except OSError:
        return base


DEFAULTS = {
    "region": None,        # None = compute from the current monitor 由目前螢幕算出
    "fullscreen": False,
    "speed": "normal",
    "language": "zh",
    "mode": "screen",      # "screen" or "image" 螢幕或圖片模式
    #: [width, height] of the primary monitor at the moment `region` was last
    #: actually recalibrated (Reset, Test, or an edited X/Y/W/H value) - None
    #: until then. Lets ui/app.py notice "the region was set up for a
    #: different-sized screen" instead of silently capturing the wrong spot.
    #: See ui/app.py's _warn_if_resolution_changed / _save_settings for how
    #: this is read and (deliberately not on every save) written.
    #: 上次「真的」重新校準 region 那一刻（按預設、按測範圍、或手動改過
    #: X/Y/寬/高）的主螢幕 [寬, 高]；在那之前是 None。讓 ui/app.py 能察覺
    #: 「這個範圍是照另一個尺寸的螢幕設定的」，而不是默默抓錯地方。
    #: 怎麼讀、（刻意不是每次存檔都）怎麼寫，見 ui/app.py 的
    #: _warn_if_resolution_changed／_save_settings。
    "region_monitor_size": None,
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
