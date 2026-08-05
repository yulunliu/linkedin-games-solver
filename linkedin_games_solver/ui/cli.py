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
from ..automation import board_watch
from ..core import action_log, read_image, write_image
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


def _parse_region(text: str) -> tuple[int, int, int, int] | None:
    """Parse 'L,T,W,H', printing a reason and returning None on anything
    invalid - including width/height <= 0, which used to reach mss
    unvalidated and escape as a raw mss.ScreenShotError.
    解析 'L,T,W,H'，任何不合法的情況（包含寬或高 <= 0）都印出原因、
    回傳 None——寬高 <= 0 以前完全沒驗證，會一路傳進 mss，
    以原始的 mss.ScreenShotError 逸出。
    """
    try:
        left, top, width, height = (int(v) for v in text.split(","))
    except ValueError:
        print("--region must be L,T,W,H / 格式應為 L,T,W,H")
        return None
    if width <= 0 or height <= 0:
        print(f"--region width and height must be positive, got {width}x{height} / "
              f"--region 的寬與高必須是正數，收到的是 {width}x{height}")
        return None
    return left, top, width, height


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
        region = _parse_region(args.region)
        if region is None:
            return None
        return capture_region(*region)
    region = default_region()
    print(f"using default region / 使用預設擷取範圍: {region}")
    return capture_region(*region)


def main():
    # Reconfigure BEFORE parse_args(), not after: argparse prints --help (and
    # usage/error text) DURING parse_args() itself and can exit before this
    # line ever runs. Both strings contain Chinese, so on a non-UTF-8 console
    # --help used to crash with UnicodeEncodeError before ever reaching a line
    # that would have fixed the encoding. --out and error text can carry
    # non-ASCII too, so stderr is reconfigured for the same reason.
    # 一定要在 parse_args() 之前重設編碼，不是之後：argparse 印 --help
    # （以及用法／錯誤訊息）是在 parse_args() 「裡面」發生的，還可能在
    # 這一行執行到之前就結束程式。兩種文字都含中文，所以在非 UTF-8 的
    # 主控台上，--help 以前會在還沒機會修正編碼之前，就先丟出
    # UnicodeEncodeError 當掉。--out 跟錯誤訊息也可能含非 ASCII 字元，
    # 所以 stderr 也一併重設，理由相同。
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    args = parse_args()

    shot = acquire(args)
    if shot is None:
        sys.exit(1)

    action_log.log("RUN", f"CLI run start: type={args.type or 'auto'} go={args.go} "
                    f"slowdown={args.slowdown} retry={args.retry}")
    print(f"log file / 記錄檔: {action_log.path()}")

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
            # A failed --out must not abort a --go run: solving already
            # succeeded, and the answer overlay is a nice-to-have debug
            # artifact, not a precondition for filling. write_image now
            # honours its documented bool contract instead of raising, so
            # this is a plain check, not a try/except.
            # --out 失敗不該中止一次 --go 執行：求解已經成功了，答案疊圖只是
            # 附加的除錯素材，不是填答的前提。write_image 現在真的遵守自己
            # 文件寫的布林值約定、不會拋例外，所以這裡只是單純檢查回傳值，
            # 不需要 try/except。
            if write_image(Path(args.out), overlay):
                print(f"answer image saved / 答案疊圖已存: {args.out}")
            else:
                print(f"could not save answer image, continuing / "
                      f"答案疊圖存不了，繼續執行: {args.out}")

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
            # Attach the mid-plan board guard - the SAME wiring the GUI uses,
            # not a separate one written out here. Measured before this fix:
            # on a scripted screen where the board is replaced after 3
            # actions, the GUI stopped after 3 of 28; --go, which never had
            # this at all, ran all 28, 25 of them onto the replaced board.
            # See board_watch.attach's own docstring.
            # 掛上填答進行中的盤面保護——用跟 GUI 完全一樣的接線，不是在這裡
            # 另外寫一份。修正前實測：對一個腳本化、盤面在第 3 個動作後被換掉
            # 的畫面，GUI 在 28 個動作裡走 3 個就停；`--go` 完全沒有接過這段，
            # 28 個全部走完，25 個點在被換掉的盤面上。見 board_watch.attach
            # 自己的文件字串。
            watch = board_watch.attach(driver, mapper, result, shot.image)
            if not watch.armed:
                print(f"  {watch.reason}")

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
    except (Aborted, KeyboardInterrupt) as exc:
        action_log.log("ERROR", f"plan aborted: {type(exc).__name__}: {exc} "
                        f"stopped_by_guard={getattr(driver, 'stopped_by_guard', False)}")
        print("aborted / 已中止")
        sys.exit(1)
    except Exception as exc:  # pyautogui failsafe etc.
        action_log.log("ERROR", f"{type(exc).__name__}: {exc}")
        print(f"interrupted / 操作中斷: {type(exc).__name__}: {exc}")
        sys.exit(1)

    timings["total"] = time.perf_counter() - started
    print(f"\n{driver.summary()}")
    print("elapsed / 耗時: " + ", ".join(f"{k} {v:.2f}s" for k, v in timings.items()))
    if not args.go:
        print("Preview only - add --go to actually play / 以上只是預演，加 --go 才會真的執行。")


def _recapture(args, previous):
    if args.region:
        # Reuse the same validated parser as the initial capture, rather than
        # a second unguarded int() conversion - args.region is already known
        # good at this point (acquire() validated it at startup), so region
        # is never actually None here; the fallback exists so a retry cannot
        # crash on a path the initial capture already proved safe.
        # 沿用跟第一次擷取一樣、經過驗證的解析器，而不是再寫一次沒防護的
        # int() 轉換——這個時間點 args.region 早就確定沒問題了（acquire()
        # 在一開始就驗證過），所以這裡 region 實際上不會是 None；
        # 保留退路只是為了不讓補點階段在一條「第一次擷取已經證明安全」的
        # 路徑上當掉。
        region = _parse_region(args.region)
        if region is not None:
            return capture_region(*region)
    return capture_region(previous.origin_x, previous.origin_y,
                          previous.image.shape[1], previous.image.shape[0])


def _verify_and_retry(args, shot, result, mapper, driver):
    previous_wrong = None
    for attempt in range(1, args.retry + 1):
        action_log.log("VERIFY", f"CLI check round {attempt}/{args.retry} starting")
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
