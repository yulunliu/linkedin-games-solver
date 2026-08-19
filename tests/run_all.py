"""
Run every test suite. / 執行全部測試。

    python tests/run_all.py
"""

import runpy
import sys
import tempfile
from pathlib import Path

SUITES = ["test_compat.py", "test_solvers.py", "test_digits.py",
          "test_recognition.py", "test_automation.py",
          "test_board_guard.py", "test_board_wait.py", "test_zip_dots.py",
          "test_settings.py", "test_image_io.py", "test_cli.py"]


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    here = Path(__file__).parent

    # Nearly every suite now exercises code that calls core/action_log.log()
    # (build_grid, solve_image, verify, board_watch, input_driver all do) -
    # without this, a full test run writes real session log files into the
    # project's own logs/ folder instead of a throwaway location.
    # 幾乎每一組測試現在都會跑到會呼叫 core/action_log.log() 的程式碼
    # （build_grid、solve_image、verify、board_watch、input_driver 全部都會）——
    # 沒有這行，跑一次完整測試會把真的執行記錄檔寫進專案自己的 logs/ 資料夾，
    # 而不是一個用完即丟的位置。
    sys.path.insert(0, str(here.parent))
    from linkedin_games_solver.core import action_log
    action_log.LOG_DIR = Path(tempfile.mkdtemp(prefix="lgs_test_logs_"))
    failed = []
    for name in SUITES:
        print(f"\n===== {name} =====")
        try:
            runpy.run_path(str(here / name), run_name="__main__")
        except Exception as exc:
            failed.append(name)
            print(f"FAILED / 失敗: {type(exc).__name__}: {exc}")

    print("\n" + "=" * 40)
    if failed:
        print("failed suites / 失敗的測試檔: " + ", ".join(failed))
        sys.exit(1)
    print(f"{len(SUITES)} suites passed / {len(SUITES)} 個測試檔全部通過")


if __name__ == "__main__":
    main()
