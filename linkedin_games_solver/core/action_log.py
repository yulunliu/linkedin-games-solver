"""
A timestamped, append-only record of what the program actually did.
帶時間戳記、只增不改的「程式實際做了什麼」記錄。

WHY THIS EXISTS 為什麼需要這個
------------------------------
The GUI's on-screen log panel only ever showed a handful of high-level lines
(puzzle type, a final action count) - never a timestamped trace of every
click, every guard check, every recognition attempt. A user who screen-records
a session then has no way to answer "what was the program doing at this exact
moment in the video?" - only what is visible on screen, which for a mid-plan
guard decision or a solve-ladder retry is nothing at all.
GUI 畫面上的記錄欄以前只會顯示幾行高層級訊息（謎題類型、最後的動作總數）——
從來不是「每一次點擊、每一次守衛檢查、每一次辨識嘗試」的帶時間戳記軌跡。
使用者把畫面錄下來之後，完全沒辦法回答「影片這一刻，程式到底在做什麼」——
畫面上看得到的東西，對於填答中途的守衛判斷或求解階梯的重試，根本什麼都沒有。

Because the real target puzzle can only be played once a day, there is no
"try again and add more logging" loop here - the log has to be complete
enough on the FIRST real session to answer questions about it afterwards.
That is why this logs actions, not just errors: a click that landed exactly
where intended is what proves a LATER click that did not was something the
board guard or verify() decided, not a driver bug.
因為真正的目標謎題一天只能玩一次，這裡沒有「錄一次不夠再錄一次、順便多加
一點記錄」的餘地——第一次真正的遊玩就必須留下足夠完整的記錄，事後才問得出
問題。這正是為什麼這裡記錄的是「動作」而不只是「錯誤」：一次點對地方的點擊，
正是用來證明「後面那次沒點對的點擊」是守衛或 verify() 的判斷造成的，
不是驅動程式本身的臭蟲。

WHAT GETS LOGGED, BY CATEGORY 依類別，記錄了什麼
-------------------------------------------------
  RUN     A session/run starting or ending - mode, puzzle, flags. 一次執行的開始或結束。
  SOLVE   Each recognition-ladder attempt and the final result. 每一次辨識嘗試與最終結果。
  GUARD   Every mid-plan board-guard check, including TOLERATED failures that
          would otherwise be invisible (see BoardWatch.failure_tolerance).
          每一次填答中途的盤面守衛檢查，包含容忍住、原本完全看不到的失敗。
  ACTION  Every click, key press and drag - what input_driver.py actually did.
          每一次點擊、按鍵、拖曳——input_driver.py 真正做了什麼。
  VERIFY  Post-fill verification rounds and what they found. 填答後的驗證與發現。
  STOP    A stop/cancel request and where it took effect. 停止／取消要求，以及在哪裡生效。
  WARN    A recovered-from fallback firing (e.g. the mask_saturated retry in
          core/board.py) - not a failure, but exactly the kind of "this is
          where things get fragile" spot worth a record even when nothing
          visibly went wrong. 一個有救回來的備援被觸發（例如 core/board.py
          的 mask_saturated 重試）——不是失敗，但正是「這裡容易出狀況」的
          地方，就算表面上沒出錯，也值得留下記錄。
  ERROR   An exception, an unhandled abort, or a guard/verify decision that
          stopped the mouse. 例外、沒被處理的中止，或讓滑鼠停手的守衛／驗證判斷。

HOW TO READ ONE AFTERWARDS 事後怎麼看
--------------------------------------
Every line starts with a local wall-clock timestamp to millisecond precision,
so it lines up directly against a screen recording's real time (or the
recording file's own creation time) - no separate clock sync step needed.
Categories are grep-able: `grep GUARD run_*.log` isolates every board-guard
decision. `tools/log_summary.py <file>` prints a per-category count plus every
WARN/ERROR line verbatim, as a starting point before reading the full file.
每一行開頭都是精確到毫秒的本機牆上時鐘時間，所以能直接對上螢幕錄影的實際
時間（或錄影檔自己的建立時間）——不需要另外做時鐘同步。類別可以直接
grep：`grep GUARD run_*.log` 就能抓出每一次盤面守衛的判斷。
`tools/log_summary.py <file>` 會印出每個類別的次數，以及每一行 WARN/ERROR
的原文，作為讀完整檔案之前的起點。

A log write must never be able to break the feature it is describing - if the
disk is full or the folder is read-only, logging silently does nothing rather
than raising into the middle of a mouse-driving loop.
記錄動作絕不能反過來弄壞它正在描述的功能——磁碟滿了或資料夾唯讀，
記錄就靜靜地什麼都不做，而不是在操作滑鼠的迴圈中間拋出例外。
"""

from __future__ import annotations

import datetime
import os
import sys
import threading
from pathlib import Path

#: Folder the log file is created in. Same reasoning as settings.captures_dir:
#: next to the program when that is writable (so a session's log sits with the
#: project it came from), falling back to the home directory otherwise.
#: 建立記錄檔的資料夾。理由跟 settings.captures_dir 一樣：程式旁邊可寫入時
#: 就放在那裡（這樣一次執行的記錄才會跟它來自的專案放在一起），否則退回
#: 家目錄。
LOG_DIRNAME = "logs"

#: Optional override, checked first by _resolve_dir(). Unset for every
#: ordinary user of the published exe - the default "next to the program"
#: behaviour below is completely unchanged for them. This exists only so a
#: developer running multiple local checkouts/worktrees of this project can
#: point every one of them at ONE shared folder instead of each accumulating
#: its own separate dist/logs/ - set once, locally (e.g. via `setx
#: LGS_DATA_DIR ...` on Windows), never committed to source control or baked
#: into the shipped exe.
#: 可選的覆寫，_resolve_dir() 會先檢查它。已發布 exe 的一般使用者都不會
#:設定這個，對他們來說下面「程式旁邊優先」的預設行為完全不變。這個變數
#: 存在的唯一理由，是讓在本機同時開著這個專案好幾份 checkout/worktree 的
#: 開發者，能讓每一份都指向「同一個」共用資料夾，而不是各自累積一份獨立的
#: dist/logs/——只在本機設定一次（例如 Windows 上用 `setx LGS_DATA_DIR
#: ...`），不會進版控，也不會被打包進發布的 exe 裡。
LOG_DIR_ENV_VAR = "LGS_DATA_DIR"

#: Overridable by tests (and, if ever needed, by a caller) so a run's log
#: never lands in a real user's folder during a test. None means "compute the
#: default lazily on first use" - see _resolve_dir().
#: 可被測試覆寫（未來如果需要，呼叫端也可以），這樣測試跑的記錄就不會
#: 寫進真實使用者的資料夾。None 代表「第一次用到時才計算預設值」——
#: 見 _resolve_dir()。
LOG_DIR: Path | None = None

_lock = threading.Lock()
_file = None
_path: Path | None = None


def _resolve_dir() -> Path:
    if LOG_DIR is not None:
        return LOG_DIR
    env_dir = os.environ.get(LOG_DIR_ENV_VAR)
    if env_dir:
        candidate = Path(env_dir) / LOG_DIRNAME
        candidate.mkdir(parents=True, exist_ok=True)
        return candidate
    if getattr(sys, "frozen", False):
        base = Path(sys.executable).resolve().parent
    else:
        base = Path(__file__).resolve().parents[2]
    for candidate in (base / LOG_DIRNAME, Path.home() / ".linkedin_games_solver_logs"):
        try:
            candidate.mkdir(parents=True, exist_ok=True)
            return candidate
        except OSError:
            continue
    return Path.home()


def _timestamp() -> str:
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]


def _ensure_open():
    global _file, _path
    if _file is not None:
        return
    directory = _resolve_dir()
    name = "run_" + datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3] + ".log"
    _path = directory / name
    _file = open(_path, "a", encoding="utf-8")
    _file.write(f"{_timestamp()} | RUN     | === session log started, file={_path} ===\n")
    _file.flush()


def log(category: str, message: str) -> None:
    """Append one timestamped line. Never raises - see the module docstring's
    last paragraph for why.
    附加一行帶時間戳記的記錄。絕不拋出例外——原因見模組文件字串的最後一段。
    """
    try:
        with _lock:
            _ensure_open()
            _file.write(f"{_timestamp()} | {category:<7} | {message}\n")
            _file.flush()
    except Exception:
        pass


def path() -> Path | None:
    """The current run's log file, or None if nothing has been logged yet.
    這次執行的記錄檔路徑；如果還沒記錄過任何東西則為 None。"""
    return _path


def close() -> None:
    """Close the current log file. Mainly for tests - a real run's file is
    left open for the life of the process and closed by the OS at exit.
    關閉目前的記錄檔。主要給測試用——真正執行時記錄檔會開著直到程式結束，
    由作業系統在結束時關閉。"""
    global _file, _path
    with _lock:
        if _file is not None:
            try:
                _file.close()
            except Exception:
                pass
        _file = None
        _path = None
