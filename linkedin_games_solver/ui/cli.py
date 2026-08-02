"""
Command line interface.
命令列介面。

Defaults to DRY RUN - it prints what it would click but does not touch the
mouse. Add --go to actually play.
預設是「預演」——只印出打算怎麼點，不會操作滑鼠。加上 --go 才會真的執行。

Examples 範例:
    python -m linkedin_games_solver.ui.cli --image shot.png     solve a file 解圖片檔
    python -m linkedin_games_solver.ui.cli                      preview screen 預演螢幕
    python -m linkedin_games_solver.ui.cli --go                 play for real 真的填答
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from ..automation import (
    Aborted,
    BoardMapper,
    InputDriver,
    build_plan,
    build_retry_plan,
    capture_region,
    capture_screen,
    default_region,
    focus_window_at,
    from_file_image,
    verify,
    wait_for_mouse_release,
)
from ..core import read_image, write_image
from ..puzzles import puzzle_name, render_overlay, solve_image


def parse_args():
    parser = argparse.ArgumentParser(description="LinkedIn Games Solver / LinkedIn 謎題自動求解")
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--image", metavar="FILE", help="solve an image file / 解圖片檔（不操作滑鼠）")
    source.add_argument("--screen", action="store_true", help="capture the whole screen / 擷取整個螢幕")
    source.add_argument("--region", metavar="L,T,W,H", help="capture this region / 擷取指定區域")

    parser.add_argument("--type", default=None, help="puzzle type / 指定謎題類型")
    parser.add_argument("--grid-size", type=int, default=None, help="board size / 棋盤格數")
    parser.add_argument("--go", action="store_true", help="really move the mouse / 真的操作滑鼠")
    parser.add_argument("--slowdown", type=float, default=2.0,
                        help="delay multiplier, higher = slower / 速度倍率，越大越慢")
    parser.add_argument("--retry", type=int, default=1, help="verify-and-retry rounds / 檢查補點輪數")
    parser.add_argument("--out", metavar="FILE", default=None,
                        help="save the answer overlay / 存下答案疊圖")
    return parser.parse_args()


def acquire(args):
    if args.image:
        image = read_image(args.image)
        if image is None:
            print(f"cannot read image / 讀不到圖片: {args.image}")
            return None
        return from_file_image(image)
    if args.screen:
        return capture_screen()
    if args.region:
        try:
            left, top, width, height = (int(v) for v in args.region.split(","))
        except ValueError:
            print("--region must be L,T,W,H / 格式應為 L,T,W,H")
            return None
        return capture_region(left, top, width, height)
    region = default_region()
    print(f"using default region / 使用預設擷取範圍: {region}")
    return capture_region(*region)


def main():
    args = parse_args()
    sys.stdout.reconfigure(encoding="utf-8")

    shot = acquire(args)
    if shot is None:
        sys.exit(1)

    timings = {}
    started = time.perf_counter()
    t0 = time.perf_counter()
    result = solve_image(shot.image, puzzle_key=args.type, n_hint=args.grid_size)
    timings["solve"] = time.perf_counter() - t0

    print(f"puzzle / 謎題: {puzzle_name(result.puzzle_key, 'en')}"
          + ("" if args.type else " (auto / 自動判斷)"))
    for line in result.info:
        print(f"  {line}")

    if not result.ok:
        print(f"\nfailed / 失敗: {result.error}")
        sys.exit(1)

    if args.out:
        overlay = render_overlay(shot.image, result)
        if overlay is not None:
            write_image(Path(args.out), overlay)
            print(f"answer image saved / 答案疊圖已存: {args.out}")

    mapper = BoardMapper(shot=shot, grid=result.grid)
    print(f"  {mapper.describe()}")

    plan = build_plan(result.puzzle_key, mapper, result.data)
    if plan is None:
        sys.exit(0)
    print("\n=== plan / 填答計畫 ===")
    for line in plan.description:
        print(line)

    # A file has no screen position, so its coordinates cannot drive the mouse.
    # 檔案沒有螢幕位置，它的座標無法用來操作滑鼠。
    if args.image and args.go:
        print("\n--image mode never moves the mouse / 圖片模式不會操作滑鼠。")
        args.go = False

    driver = InputDriver(dry_run=not args.go, slowdown=args.slowdown)
    try:
        if args.go:
            cx, cy = mapper.cell_center(0, 0)
            print(f"focused window / 切到目標視窗: {focus_window_at(cx, cy) or '?'}")
            print(f"waited for mouse release / 等待放開滑鼠: {wait_for_mouse_release():.2f}s")

        t0 = time.perf_counter()
        plan.run(driver)
        timings["fill"] = time.perf_counter() - t0

        if args.go and args.retry > 0:
            t0 = time.perf_counter()
            _verify_and_retry(args, shot, result, mapper, driver)
            timings["verify"] = time.perf_counter() - t0
    except (Aborted, KeyboardInterrupt):
        print("aborted / 已中止")
        sys.exit(1)
    except Exception as exc:  # pyautogui failsafe etc.
        print(f"interrupted / 操作中斷: {type(exc).__name__}: {exc}")
        sys.exit(1)

    timings["total"] = time.perf_counter() - started
    print(f"\n{driver.summary()}")
    print("elapsed / 耗時: " + ", ".join(f"{k} {v:.2f}s" for k, v in timings.items()))
    if not args.go:
        print("Preview only - add --go to actually play / 以上只是預演，加 --go 才會真的執行。")


def _recapture(args, previous):
    if args.region:
        left, top, width, height = (int(v) for v in args.region.split(","))
        return capture_region(left, top, width, height)
    return capture_region(previous.origin_x, previous.origin_y,
                          previous.image.shape[1], previous.image.shape[0])


def _verify_and_retry(args, shot, result, mapper, driver):
    previous_wrong = None
    for attempt in range(1, args.retry + 1):
        time.sleep(0.9)
        fresh = _recapture(args, shot)
        report = verify(fresh.image, result, n_hint=args.grid_size)
        print(f"\n[check {attempt} / 檢查第 {attempt} 輪] {report.summary()}")

        if report.board_changed:
            print("    stopped, no longer controlling the mouse / 已停止，不再控制滑鼠。")
            return
        if not report.supported or report.ok:
            return

        wrong = len(report.mismatches)
        if previous_wrong is not None and wrong >= previous_wrong:
            print("    no improvement, stopping / 沒有改善，停止補點。")
            return
        previous_wrong = wrong

        retry_plan = build_retry_plan(result, mapper, report)
        if retry_plan is None:
            return
        print(f"    re-clicking {wrong} cell(s) / 補點 {wrong} 格...")
        retry_plan.run(driver)


if __name__ == "__main__":
    main()
