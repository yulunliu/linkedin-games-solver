"""
Settings persistence tests: a malformed region must never reach a caller.
設定檔持久化測試：不合法的擷取範圍絕不能傳到呼叫端手上。

No tkinter here - ui/settings.py has no display dependency, so this runs
in CI (including headless Ubuntu) exactly like every other suite.
這裡不碰 tkinter —— ui/settings.py 沒有顯示裝置的相依，所以這組測試
在 CI（包含沒有顯示裝置的 Ubuntu）跑起來跟其他測試組完全一樣。
"""

import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from linkedin_games_solver.core import action_log  # noqa: E402
from linkedin_games_solver.ui import settings as settings_store  # noqa: E402


def test_valid_region():
    """Exactly four ints, width and height both positive - nothing else.
    剛好四個整數，寬跟高都是正數——其他一律不行。"""
    good = [
        [100, 100, 640, 700],
        (100, 100, 640, 700),
        [0, 0, 1, 1],
    ]
    bad = [
        [100, 100, 640],              # wrong length / 長度不對
        [100, 100, 640, 700, 1],      # wrong length / 長度不對
        [100, 100, 0, 700],           # zero width / 寬是 0
        [100, 100, 640, 0],           # zero height / 高是 0
        [100, 100, -640, 700],        # negative width / 寬是負數
        [100, 100, 640, -1],          # negative height / 高是負數
        "100,100,640,700",            # not a list at all / 根本不是 list
        ["a", "b", "c", "d"],         # not ints / 不是整數
        None,
        123,
    ]
    for value in good:
        assert settings_store._valid_region(value), f"{value!r} should be valid"
    for value in bad:
        assert not settings_store._valid_region(value), f"{value!r} should be invalid"
    print("  valid region check OK")


def test_load_drops_a_malformed_region_instead_of_passing_it_on():
    """
    Bug this guards: _apply_settings used to do str(int(v)) over whatever
    load() handed back, with no shape check first. Eight malformed shapes
    were tried by hand-editing the settings file and each raised at GUI
    startup - in the shipped windowed .exe that is "double-click, and
    nothing happens". load() now sanitizes region itself, so every caller
    (GUI startup, a future second UI) gets either a valid 4-int list or None,
    never something that crashes int().
    這個測試守住的問題：_apply_settings 以前是對 load() 回傳的東西直接做
    str(int(v))，完全沒先檢查形狀。手改設定檔試過八種不合法的形狀，
    每一種都會在 GUI 啟動時拋錯——在打包好的視窗版 exe 上就是
    「點兩下，什麼都沒發生」。load() 現在自己會清理 region，
    所以每個呼叫端（GUI 啟動、未來可能的第二套介面）拿到的不是合法的
    四個整數 list，就是 None，絕不會是一個會讓 int() 當掉的東西。
    """
    original_path = settings_store.SETTINGS_PATH
    with tempfile.TemporaryDirectory() as tmp:
        settings_store.SETTINGS_PATH = Path(tmp) / "settings.json"
        try:
            malformed = [
                [100, 100, 0, 700],       # zero width / 寬是 0
                [100, 100, 640],          # wrong length / 長度不對
                "100,100,640,700",        # not a list / 不是 list
                [100, 100, -640, 700],    # negative width / 寬是負數
                ["a", "b", "c", "d"],     # not ints / 不是整數
            ]
            for bad_region in malformed:
                settings_store.SETTINGS_PATH.write_text(
                    json.dumps({"region": bad_region}), encoding="utf-8")
                data = settings_store.load()
                assert data["region"] is None, (
                    f"{bad_region!r} should have been dropped, got {data['region']!r}"
                )

            # A genuinely valid region survives load() unchanged.
            # 真的合法的範圍，load() 之後要維持不變。
            settings_store.SETTINGS_PATH.write_text(
                json.dumps({"region": [10, 20, 640, 700]}), encoding="utf-8")
            data = settings_store.load()
            assert data["region"] == [10, 20, 640, 700]
        finally:
            settings_store.SETTINGS_PATH = original_path
    print("  load() drops a malformed region instead of passing it on OK")


def test_save_logs_a_warning_instead_of_failing_silently():
    """
    Bug this guards: save() used to swallow every write failure with a bare
    `except Exception: pass` and no log line at all - inconsistent with
    load()'s own philosophy a few lines above (it explicitly WARNs when it
    discards a malformed region, specifically so a silent failure is never
    the only trace). A permission error, a locked file, a full disk, or the
    settings path becoming a directory would all silently no-op: the
    user's calibrated region, language, speed, and region_monitor_size
    stamp would fail to persist with nothing in the log explaining why
    settings keep resetting between sessions.
    這個測試守住的問題：save() 以前用一個空的 `except Exception: pass`
    吞掉每一次寫入失敗，完全不留下任何記錄——跟前面幾行 load() 自己的
    做法不一致（它在丟棄格式錯誤的 region 時，會明確寫一行 WARN，就是
    為了不讓「悄悄失敗」變成唯一的痕跡）。權限錯誤、檔案被鎖、硬碟滿了，
    或設定檔路徑變成了一個資料夾，都會在這裡悄悄什麼都不做：使用者
    校準好的擷取範圍、語言、速度、region_monitor_size 標記都會存不進去，
    而 log 裡完全沒有任何線索說明為什麼設定在不同執行之間一直被重設。
    """
    original_path = settings_store.SETTINGS_PATH
    with tempfile.TemporaryDirectory() as tmp:
        # A directory, not a file - write_text() on this must raise, giving
        # a real (not simulated) write failure to guard against.
        # 是一個資料夾，不是檔案——對它呼叫 write_text() 一定會拋錯，
        # 提供一個真的（不是模擬的）寫入失敗來守住這個測試。
        settings_store.SETTINGS_PATH = Path(tmp)  # tmp itself is a directory
        warnings = []
        original_log = action_log.log
        action_log.log = lambda category, message: warnings.append((category, message))
        try:
            settings_store.save({"language": "en"})
        finally:
            action_log.log = original_log
            settings_store.SETTINGS_PATH = original_path

        assert warnings, "save() failed silently - nothing was logged / save() 悄悄失敗了，log 裡什麼都沒有"
        assert any(cat == "WARN" and "settings.save()" in msg for cat, msg in warnings), (
            f"expected a WARN mentioning settings.save(), got / 預期要有一行提到 settings.save() 的 WARN，得到: {warnings}"
        )
    print("  save() logs a warning instead of failing silently OK")


def test_region_monitor_size_round_trips_and_defaults_to_none():
    """
    region_monitor_size (added for the resolution-change warning in
    ui/app.py) must behave exactly like every other settings key: absent
    until saved, then round-trips through save()/load() unchanged.
    region_monitor_size（為了 ui/app.py 的解析度改變警告新增的）行為必須
    跟其他每一個設定值一樣：存過之前是預設值，存過之後 save()/load()
    要能原封不動地讀回來。
    """
    original_path = settings_store.SETTINGS_PATH
    with tempfile.TemporaryDirectory() as tmp:
        settings_store.SETTINGS_PATH = Path(tmp) / "settings.json"
        try:
            fresh = settings_store.load()
            assert fresh["region_monitor_size"] is None, \
                f"should default to None / 預設應為 None: {fresh['region_monitor_size']!r}"

            fresh["region_monitor_size"] = [1920, 1080]
            settings_store.save(fresh)
            reloaded = settings_store.load()
            assert reloaded["region_monitor_size"] == [1920, 1080], \
                f"did not round-trip / 讀回來的值不對: {reloaded['region_monitor_size']!r}"
        finally:
            settings_store.SETTINGS_PATH = original_path
    print("  region_monitor_size round-trips and defaults to None OK")


def test_captures_dir_respects_the_shared_data_dir_env_var():
    """
    captures_dir() (and calibration_candidates_dir(), which is built on top
    of it) must use LGS_DATA_DIR/img when that environment variable is set -
    this is how several local checkouts/worktrees of this project can share
    one folder instead of each accumulating its own dist/img/ - and must
    fall back to the normal "next to the program" behaviour when it is not
    set, which is what every ordinary user of the published exe gets.
    captures_dir()（以及建立在它之上的 calibration_candidates_dir()）在
    LGS_DATA_DIR 這個環境變數有設定時，必須使用 LGS_DATA_DIR/img——這就是
    本機好幾份 checkout/worktree 能共用同一個資料夾、而不是各自累積一份
    dist/img/ 的方式——沒有設定時則必須退回原本「程式旁邊」的行為，這正是
    已發布 exe 的一般使用者會拿到的行為。
    """
    original_env = os.environ.get(action_log.LOG_DIR_ENV_VAR)
    with tempfile.TemporaryDirectory() as tmp:
        os.environ[action_log.LOG_DIR_ENV_VAR] = tmp
        try:
            captures = settings_store.captures_dir()
            assert captures == Path(tmp) / "img", \
                f"did not honour the env var / 沒有遵守環境變數: {captures!r}"
            assert captures.is_dir(), "captures_dir() did not create the folder / 沒有建立資料夾"

            candidates = settings_store.calibration_candidates_dir()
            assert candidates == Path(tmp) / "img" / "calibration_candidates", \
                f"did not build on the env var / 沒有建立在環境變數之上: {candidates!r}"
            assert candidates.is_dir()
        finally:
            if original_env is None:
                os.environ.pop(action_log.LOG_DIR_ENV_VAR, None)
            else:
                os.environ[action_log.LOG_DIR_ENV_VAR] = original_env
    print("  captures_dir respects LGS_DATA_DIR, falls back when unset OK")


def test_log_dir_respects_the_shared_data_dir_env_var():
    """
    Same override, same reasoning, for action_log._resolve_dir() -
    core/action_log.py's own LOG_DIR global (used by other tests to
    redirect logging into a scratch folder) must be None here so the
    function actually reaches the env-var check instead of short-circuiting
    on that override first.
    跟上面同一個覆寫機制、同一個理由，套用在 action_log._resolve_dir() 上——
    core/action_log.py 自己的 LOG_DIR 全域變數（其他測試會用它把記錄導向
    暫存資料夾）這裡必須是 None，函式才會真的走到環境變數檢查，
    而不是先被那個覆寫短路掉。
    """
    original_env = os.environ.get(action_log.LOG_DIR_ENV_VAR)
    original_log_dir = action_log.LOG_DIR
    with tempfile.TemporaryDirectory() as tmp:
        os.environ[action_log.LOG_DIR_ENV_VAR] = tmp
        action_log.LOG_DIR = None
        try:
            resolved = action_log._resolve_dir()
            assert resolved == Path(tmp) / "logs", \
                f"did not honour the env var / 沒有遵守環境變數: {resolved!r}"
            assert resolved.is_dir()
        finally:
            if original_env is None:
                os.environ.pop(action_log.LOG_DIR_ENV_VAR, None)
            else:
                os.environ[action_log.LOG_DIR_ENV_VAR] = original_env
            action_log.LOG_DIR = original_log_dir
    print("  action_log._resolve_dir respects LGS_DATA_DIR OK")


if __name__ == "__main__":
    print("Settings tests / 設定檔測試")
    test_valid_region()
    test_load_drops_a_malformed_region_instead_of_passing_it_on()
    test_save_logs_a_warning_instead_of_failing_silently()
    test_region_monitor_size_round_trips_and_defaults_to_none()
    test_captures_dir_respects_the_shared_data_dir_env_var()
    test_log_dir_respects_the_shared_data_dir_env_var()
    print("\nAll passed / 全部通過")
