"""
Run every test suite. / 執行全部測試。

    python tests/run_all.py
"""

import runpy
import sys
from pathlib import Path

SUITES = ["test_solvers.py", "test_digits.py", "test_recognition.py", "test_automation.py"]


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    here = Path(__file__).parent
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
