"""
Summarise one session log produced by core/action_log.py.
彙整一份由 core/action_log.py 產生的執行記錄。

    python tools/log_summary.py <path-to-run_*.log>

WHY this exists 為什麼需要這支腳本:
  A five-puzzle sitting can log hundreds of GUARD/SOLVE lines - reading the
  whole file top to bottom to answer "did anything unusual happen" is slow.
  This prints the shape of the session first (how long, how many of each
  category) and every WARN/ERROR line verbatim, so you know where to open the
  full file and start reading closely - each line's timestamp lines up
  directly against a screen recording's real time.
  一輪五題下來，記錄檔可能有幾百行 GUARD/SOLVE——想知道「有沒有不尋常的事
  發生」，從頭讀到尾太慢。這支腳本會先印出這次執行的輪廓（多長、每個類別
  各幾行），以及每一行 WARN/ERROR 的原文，讓你知道該打開完整檔案、
  從哪裡開始細看——每一行的時間戳記可以直接對上螢幕錄影的實際時間。
"""

from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

_CATEGORIES = ("RUN", "SOLVE", "GUARD", "ACTION", "VERIFY", "STOP", "WARN", "ERROR")


def summarise(path: Path) -> None:
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    if not lines:
        print("empty log file / 空的記錄檔")
        return

    counts: Counter = Counter()
    notable: list[str] = []
    first_ts = lines[0].split(" | ", 1)[0] if " | " in lines[0] else "?"
    last_ts = first_ts

    for line in lines:
        if " | " not in line:
            continue
        ts, rest = line.split(" | ", 1)
        last_ts = ts
        category = rest.split(" | ", 1)[0].strip()
        counts[category] += 1
        if category in ("WARN", "ERROR"):
            notable.append(line)
        # A tolerated guard failure is a near-miss even though the category
        # is GUARD, not WARN - surface it the same way.
        # 被容忍的守衛失敗雖然類別是 GUARD 不是 WARN，仍然是一次驚險時刻，
        # 用同樣的方式呈現出來。
        if category == "GUARD" and "TOLERATED" in rest:
            notable.append(line)

    print(f"file / 檔案: {path}")
    print(f"span / 時間範圍: {first_ts} -> {last_ts}")
    print(f"total lines / 總行數: {sum(counts.values())}")
    print()
    print("by category / 依類別:")
    for cat in _CATEGORIES:
        if counts[cat]:
            print(f"  {cat:<7} {counts[cat]}")
    other = sum(v for k, v in counts.items() if k not in _CATEGORIES)
    if other:
        print(f"  (other) {other}")

    if notable:
        print()
        print(f"WARN / ERROR / tolerated-GUARD lines ({len(notable)}):")
        for line in notable:
            print(f"  {line}")
    else:
        print()
        print("no WARN, ERROR, or tolerated-guard-failure lines / "
              "沒有 WARN、ERROR、或被容忍的守衛失敗")


def main():
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(1)
    path = Path(sys.argv[1])
    if not path.is_file():
        print(f"not a file / 不是檔案: {path}")
        sys.exit(1)
    summarise(path)


if __name__ == "__main__":
    main()
