"""
Settings persistence tests: a malformed region must never reach a caller.
設定檔持久化測試：不合法的擷取範圍絕不能傳到呼叫端手上。

No tkinter here - ui/settings.py has no display dependency, so this runs
in CI (including headless Ubuntu) exactly like every other suite.
這裡不碰 tkinter —— ui/settings.py 沒有顯示裝置的相依，所以這組測試
在 CI（包含沒有顯示裝置的 Ubuntu）跑起來跟其他測試組完全一樣。
"""

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

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


if __name__ == "__main__":
    print("Settings tests / 設定檔測試")
    test_valid_region()
    test_load_drops_a_malformed_region_instead_of_passing_it_on()
    print("\nAll passed / 全部通過")
