"""
CLI：擷取螢幕上的謎題 -> 辨識 -> 求解 -> 自動填答。

**預設是預演模式 (dry-run)**，只會列出「打算怎麼點」但不會真的操作滑鼠。
確認動作正確之後，加上 --go 才會真的執行。

用法:
    python autoplay.py                          # 用預設的固定棋盤位置，預演
    python autoplay.py --go                     # 用預設位置，真的自動填答
    python autoplay.py --region 660,210,600,620 # 自己指定螢幕區域
    python autoplay.py --window chrome          # 擷取標題含 chrome 的視窗
    python autoplay.py --screen                 # 擷取整個主螢幕
    python autoplay.py --save shot.png          # 順便把擷取到的畫面存檔
"""

import argparse
import sys
import time
from pathlib import Path

import capture
import solver_bridge
from board_mapper import BoardMapper
from input_driver import Aborted, InputDriver, focus_window_at, wait_for_mouse_release
from players import PLAYERS
from solve_puzzle import solve_from_image

sys.path.insert(0, str(solver_bridge.solver_dir()))
from img_io import imwrite_unicode  # noqa: E402


def parse_args():
    p = argparse.ArgumentParser(description="LinkedIn 謎題：讀取網頁畫面並自動填答")
    source = p.add_mutually_exclusive_group()
    source.add_argument("--screen", action="store_true", help="擷取整個主螢幕")
    source.add_argument("--window", metavar="標題關鍵字", help="擷取標題含此關鍵字的視窗")
    source.add_argument("--region", metavar="L,T,W,H", help="擷取指定螢幕區域")
    source.add_argument("--image", metavar="檔案", help="改用圖片檔測試 (不擷取螢幕，也不會點擊)")

    p.add_argument("--type", choices=solver_bridge.DISPLAY_ORDER, default=None, help="謎題類型 (預設自動判斷)")
    p.add_argument("--grid-size", type=int, default=None, help="棋盤格數 (預設自動偵測)")
    p.add_argument("--go", action="store_true", help="真的執行滑鼠操作 (預設只預演)")
    p.add_argument("--countdown", type=int, default=4, help="開始操作前的倒數秒數 (預設 4)")
    p.add_argument(
        "--slowdown", type=float, default=2.0, metavar="倍率",
        help="動作速度倍率，數字越大越慢 (預設 2.0；網頁跟不上就調大)",
    )
    p.add_argument(
        "--retry", type=int, default=1, metavar="次數",
        help="填完後重新擷取檢查，對沒填到的格子補點的最多輪數 (預設 1，設 0 關閉)",
    )
    p.add_argument("--save", metavar="檔案", default=None, help="把擷取到的畫面存檔")
    p.add_argument("--save-overlay", metavar="檔案", default=None, help="把辨識疊圖存檔，用來確認辨識正確")
    return p.parse_args()


def acquire(args) -> capture.ScreenShot | None:
    if args.image:
        image = _read_image(args.image)
        if image is None:
            print(f"讀不到圖片: {args.image}")
            return None
        return capture.ScreenShot(image=image, origin_x=0, origin_y=0)

    if args.window:
        windows = capture.list_windows(args.window)
        if not windows:
            print(f"找不到標題含 '{args.window}' 的視窗")
            return None
        win = windows[0]
        print(f"擷取視窗: {win.title}")
        try:
            win.activate()
            time.sleep(0.4)
        except Exception:
            pass
        return capture.capture_window(win)

    if args.region:
        try:
            left, top, width, height = (int(v) for v in args.region.split(","))
        except ValueError:
            print("--region 格式應為 L,T,W,H，例如 100,200,800,800")
            return None
        return capture.capture_region(left, top, width, height)

    if args.screen:
        return capture.capture_screen()

    # 沒指定來源時，用預設的固定棋盤位置
    region = capture.default_region()
    print(f"使用預設擷取範圍: {region}")
    return capture.capture_region(*region)


def _read_image(path):
    from img_io import imread_unicode

    return imread_unicode(path)


def _recapture(args, previous):
    """用跟第一次相同的來源重新擷取畫面 (用來檢查填得對不對)。"""
    if args.region:
        left, top, width, height = (int(v) for v in args.region.split(","))
        return capture.capture_region(left, top, width, height)
    return capture.capture_region(
        previous.origin_x, previous.origin_y, previous.image.shape[1], previous.image.shape[0]
    )


def _verify_and_retry(args, shot, outcome, mapper, driver):
    """
    填完後重新擷取檢查，只補「確實還沒填對」的格子。
    若補點後沒填對的格數沒有減少就立刻停手 —— 那代表辨識有問題，
    再點下去只會把已經正確的格子點掉 (點擊是循環的)。
    """
    from verify import build_retry_plan, verify

    previous_wrong = None
    for attempt in range(1, args.retry + 1):
        time.sleep(0.9)  # 等網頁把畫面更新完
        fresh = _recapture(args, shot)
        report = verify(fresh.image, outcome, n_hint=args.grid_size)
        print(f"\n[檢查 第 {attempt} 輪] {report.summary()}")

        if report.board_changed:
            print("    已停止操作，不再控制滑鼠。")
            return
        if not report.supported:
            return
        if report.ok:
            print("    已完成，停止操作。")
            return

        for r, c, got, want in report.mismatches[:12]:
            print(f"    第 {r+1} 列 第 {c+1} 欄: 目前 {got} -> 應為 {want}")
        if len(report.mismatches) > 12:
            print(f"    ... 另外還有 {len(report.mismatches) - 12} 格")

        wrong = len(report.mismatches)
        if previous_wrong is not None and wrong >= previous_wrong:
            print(f"    補點後沒有改善 ({previous_wrong} -> {wrong} 格)，停止補點以免破壞已填對的格子。")
            return
        previous_wrong = wrong

        retry_plan = build_retry_plan(outcome, mapper, report)
        if retry_plan is None:
            return
        print(f"    補點 {wrong} 格...")
        retry_plan.run(driver)


def main():
    args = parse_args()
    sys.stdout.reconfigure(encoding="utf-8")

    shot = acquire(args)
    if shot is None:
        sys.exit(1)

    if args.save:
        imwrite_unicode(Path(args.save), shot.image)
        print(f"擷取畫面已存檔: {args.save}")

    timings: dict[str, float] = {}
    started_all = time.perf_counter()
    t0 = time.perf_counter()
    outcome = solve_from_image(shot.image, puzzle_key=args.type, n_hint=args.grid_size)
    timings["辨識+求解"] = time.perf_counter() - t0
    module = solver_bridge.PUZZLES.get(outcome.puzzle_key)
    print(f"謎題類型: {module.NAME if module else outcome.puzzle_key}" + ("" if args.type else " (自動判斷)"))
    for line in outcome.info:
        print(f"  {line}")

    if args.save_overlay:
        result = solver_bridge.PUZZLES[outcome.puzzle_key].analyze(
            shot.image, n_hint=args.grid_size, debug=True
        )
        image = result.debug_image if result.debug_image is not None else result.overlay_image
        if image is not None:
            imwrite_unicode(Path(args.save_overlay), image)
            print(f"辨識疊圖已存檔: {args.save_overlay}")

    if not outcome.ok:
        print(f"\n失敗: {outcome.error}")
        print("提示: 加上 --save-overlay debug.png 可以把辨識結果畫出來檢查哪裡抓錯。")
        sys.exit(1)

    mapper = BoardMapper(shot=shot, grid=outcome.grid)
    print(f"  {mapper.describe()}")

    plan = PLAYERS[outcome.puzzle_key](mapper).build_plan(outcome.data)
    print("\n=== 填答計畫 ===")
    for line in plan.description:
        print(line)

    if args.image and args.go:
        print("\n--image 模式不會實際操作滑鼠 (因為畫面座標不對應真實螢幕)。")
        args.go = False

    driver = InputDriver(dry_run=not args.go, slowdown=args.slowdown)

    if args.go:
        print(f"\n{args.countdown} 秒後開始自動填答，請切換到瀏覽器視窗。")
        print("中止方式: 把滑鼠快速移到螢幕左上角 (0,0)，或按 Ctrl+C。")
        try:
            driver.countdown(args.countdown, on_tick=lambda s: print(f"  {s}...", flush=True))
        except (Aborted, KeyboardInterrupt):
            print("已中止")
            sys.exit(1)

    try:
        if args.go:
            # 先把棋盤所在的視窗切到最前面，避免第一次點擊被拿去啟用視窗而失效
            cx, cy = mapper.cell_center(0, 0)
            title = focus_window_at(cx, cy)
            print(f"已將目標視窗切到最前面: {title or '(取得不到標題)'}")
            # 等實體滑鼠放開再開始，放開得快就幾乎不會等
            waited = wait_for_mouse_release()
            print(f"等待放開滑鼠 {waited:.2f} 秒")

        t0 = time.perf_counter()
        plan.run(driver)
        timings["填答"] = time.perf_counter() - t0

        if args.go and args.retry > 0:
            t0 = time.perf_counter()
            _verify_and_retry(args, shot, outcome, mapper, driver)
            timings["檢查補點"] = time.perf_counter() - t0
    except Aborted:
        print("已中止")
        sys.exit(1)
    except KeyboardInterrupt:
        print("已中止 (Ctrl+C)")
        sys.exit(1)
    except Exception as e:  # pyautogui 的 FailSafeException 等
        print(f"操作中斷: {type(e).__name__}: {e}")
        sys.exit(1)

    timings["總計"] = time.perf_counter() - started_all
    print(f"\n{driver.summary()}")
    print("耗時: " + "、".join(f"{k} {v:.2f}s" for k, v in timings.items()))
    if not args.go:
        print("以上只是預演。確認動作正確後，加上 --go 才會真的執行。")
        print("\n動作明細:")
        for line in driver.log:
            print(f"  {line}")


if __name__ == "__main__":
    main()
