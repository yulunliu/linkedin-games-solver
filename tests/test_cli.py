"""
CLI argument-parsing tests. No display needed - importing ui.cli does not
touch mss/pyautogui at module level, same as automation generally.
CLI 參數解析測試。不需要顯示裝置——匯入 ui.cli 在模組層級不會碰
mss/pyautogui，跟 automation 整體的設計一樣。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from linkedin_games_solver.ui.cli import _parse_region  # noqa: E402


def test_parse_region_accepts_a_valid_rectangle():
    assert _parse_region("100,200,640,700") == (100, 200, 640, 700)
    assert _parse_region("-50,-50,10,10") == (-50, -50, 10, 10)  # off-screen left/top is legal
    print("  parse_region accepts a valid rectangle OK")


def test_parse_region_rejects_non_positive_dimensions():
    """
    Bug this guards: width/height <= 0 used to reach mss unvalidated and
    escape as a raw mss.ScreenShotError instead of a clear message.
    這個測試守住的問題：寬或高 <= 0 以前完全沒驗證就傳進 mss，
    以原始的 mss.ScreenShotError 逸出，而不是一句清楚的訊息。
    """
    for text in ("0,0,0,700", "0,0,640,0", "0,0,-1,700", "0,0,640,-1", "0,0,0,0"):
        assert _parse_region(text) is None, f"{text!r} should be rejected"
    print("  parse_region rejects non-positive dimensions OK")


def test_parse_region_rejects_malformed_text():
    for text in ("abc", "1,2,3", "1,2,3,4,5", "", "1,2,x,4"):
        assert _parse_region(text) is None, f"{text!r} should be rejected"
    print("  parse_region rejects malformed text OK")


if __name__ == "__main__":
    print("CLI tests / 命令列測試")
    test_parse_region_accepts_a_valid_rectangle()
    test_parse_region_rejects_non_positive_dimensions()
    test_parse_region_rejects_malformed_text()
    print("\nAll passed / 全部通過")
