"""
CLI 入口：輸入一張 LinkedIn 謎題截圖，自動辨識 + 求解 + 輸出答案。

支援 Tango / Queens / Mini Sudoku / Zip / Patches 五種謎題。

用法:
    python main.py puzzle.jpg                 # 自動判斷謎題類型
    python main.py puzzle.jpg --type queens    # 指定謎題類型
    python main.py puzzle.jpg --debug          # 額外輸出辨識除錯圖
"""

import argparse
import sys
from pathlib import Path

from img_io import imread_unicode, imwrite_unicode
from registry import DISPLAY_ORDER, PUZZLES, detect_type


def parse_args():
    p = argparse.ArgumentParser(description="LinkedIn 謎題自動求解 (Tango / Queens / Sudoku / Zip / Patches)")
    p.add_argument("image", help="謎題截圖路徑")
    p.add_argument("--type", choices=DISPLAY_ORDER, default=None, help="謎題類型 (預設自動判斷)")
    p.add_argument("--grid-size", type=int, default=None, help="棋盤格數 (預設自動偵測)")
    p.add_argument("--debug", action="store_true", help="輸出偵測過程的除錯圖")
    p.add_argument("--out", default=None, help="輸出答案疊圖路徑")
    return p.parse_args()


def main():
    args = parse_args()
    sys.stdout.reconfigure(encoding="utf-8")

    image_path = Path(args.image)
    image = imread_unicode(image_path)
    if image is None:
        print(f"讀不到圖片: {image_path}")
        sys.exit(1)

    puzzle_key = args.type or detect_type(image)
    module = PUZZLES[puzzle_key]
    print(f"謎題類型: {module.NAME}" + ("" if args.type else " (自動判斷)"))

    result = module.analyze(image, n_hint=args.grid_size, debug=args.debug)

    for line in result.report_lines:
        print(line)

    if args.debug and result.debug_image is not None:
        dbg_path = image_path.with_name(f"{image_path.stem}_debug.png")
        imwrite_unicode(dbg_path, result.debug_image)
        print(f"\n除錯圖已輸出: {dbg_path}")

    if not result.ok:
        print(f"\n{result.error}")
        sys.exit(1)

    if result.overlay_image is not None:
        out_path = Path(args.out) if args.out else image_path.with_name(f"{image_path.stem}_solved.png")
        imwrite_unicode(out_path, result.overlay_image)
        print(f"\n答案疊圖已輸出: {out_path}")


if __name__ == "__main__":
    main()
