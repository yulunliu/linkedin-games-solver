"""
真・端對端測試：把謎題畫到實際螢幕上，再從螢幕擷取、辨識、求解，
最後驗證「算出來要點的螢幕座標」確實落在正確的格子裡。

這個測試會用一個 Tk 視窗把樣本圖顯示在螢幕上 (模擬瀏覽器畫面)，
所以需要有實體桌面環境才能跑。不會有任何滑鼠點擊 (全程 dry-run)。
"""

import sys
import threading
import time
import tkinter as tk
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import capture  # noqa: E402
import solver_bridge  # noqa: E402
from board_mapper import BoardMapper  # noqa: E402
from input_driver import InputDriver  # noqa: E402
from players import PLAYERS  # noqa: E402
from solve_puzzle import solve_from_image  # noqa: E402

sys.path.insert(0, str(solver_bridge.solver_dir()))
import cv2  # noqa: E402
from img_io import imread_unicode  # noqa: E402
from PIL import Image, ImageTk  # noqa: E402

SAMPLES = solver_bridge.solver_dir() / "samples"

WINDOW_X, WINDOW_Y = 60, 60
#: 把手機截圖縮到這個高度顯示，模擬網頁上的尺寸。
#: 用 1300 讓棋盤約 550px，超過 solve_puzzle.MIN_BOARD_PIXELS 的建議值。
DISPLAY_HEIGHT = 1300


def show_image_and_capture(image_path: Path):
    """在螢幕上顯示圖片，擷取該區域，然後關閉視窗。"""
    src = imread_unicode(image_path)
    assert src is not None, f"讀不到 {image_path}"

    scale = DISPLAY_HEIGHT / src.shape[0]
    shown = cv2.resize(src, (int(src.shape[1] * scale), DISPLAY_HEIGHT), interpolation=cv2.INTER_AREA)

    root = tk.Tk()
    root.overrideredirect(True)  # 去掉標題列，讓視窗內容就是圖片本身
    root.geometry(f"{shown.shape[1]}x{shown.shape[0]}+{WINDOW_X}+{WINDOW_Y}")
    root.attributes("-topmost", True)

    photo = ImageTk.PhotoImage(Image.fromarray(cv2.cvtColor(shown, cv2.COLOR_BGR2RGB)))
    tk.Label(root, image=photo, borderwidth=0, highlightthickness=0).pack()

    captured = {}

    def do_capture():
        # 視窗要一點時間才會真的畫出來；擷取後確認內容跟來源一致，不一致就重試
        for _ in range(10):
            time.sleep(0.5)
            shot = capture.capture_region(WINDOW_X, WINDOW_Y, shown.shape[1], shown.shape[0])
            if shot.image.shape == shown.shape and cv2.absdiff(shot.image, shown).mean() < 1.0:
                captured["shot"] = shot
                break
            captured["shot"] = shot
        root.after(0, root.destroy)

    threading.Thread(target=do_capture, daemon=True).start()
    root.mainloop()

    assert "shot" in captured, "螢幕擷取失敗"
    return captured["shot"], shown


def check(sample_name: str, expected_key: str):
    shot, shown = show_image_and_capture(SAMPLES / sample_name)

    # 擷取到的畫面應該跟顯示出來的內容一致 (尺寸相同)
    assert shot.image.shape[:2] == shown.shape[:2], (
        f"擷取尺寸 {shot.image.shape[:2]} 與顯示尺寸 {shown.shape[:2]} 不符"
    )

    outcome = solve_from_image(shot.image)
    assert outcome.ok, f"{sample_name} 求解失敗: {outcome.error}"
    assert outcome.puzzle_key == expected_key, (
        f"{sample_name} 類型判斷錯誤: 期望 {expected_key} 得到 {outcome.puzzle_key}"
    )

    mapper = BoardMapper(shot=shot, grid=outcome.grid)
    plan = PLAYERS[outcome.puzzle_key](mapper).build_plan(outcome.data)

    driver = InputDriver(dry_run=True)
    plan.run(driver)
    assert driver.log, "沒有產生任何操作"

    # 驗證座標映射：每一格算出來的螢幕座標，必須落在該格在螢幕上的實際範圍內
    left, top, bw, bh = mapper.board_rect_on_screen()
    for r in range(mapper.n):
        for c in range(mapper.n):
            sx, sy = mapper.cell_center(r, c)
            cell_left = left + bw * c / mapper.n
            cell_right = left + bw * (c + 1) / mapper.n
            cell_top = top + bh * r / mapper.n
            cell_bottom = top + bh * (r + 1) / mapper.n
            assert cell_left <= sx <= cell_right, f"({r},{c}) x 座標 {sx} 不在 [{cell_left},{cell_right}]"
            assert cell_top <= sy <= cell_bottom, f"({r},{c}) y 座標 {sy} 不在 [{cell_top},{cell_bottom}]"

    # 棋盤必須落在我們顯示視窗的範圍內
    assert WINDOW_X <= left and top >= WINDOW_Y, "棋盤位置超出顯示視窗"
    assert left + bw <= WINDOW_X + shown.shape[1] + 2, "棋盤右緣超出顯示視窗"

    print(f"  {sample_name}: {outcome.puzzle_key} OK, {mapper.describe()}, {len(driver.log)} 個動作")
    return True


def main():
    cases = [
        ("S__104316934_0.jpg", "queens"),
        ("S__104316935_0.jpg", "sudoku"),
        ("S__104316936_0.jpg", "patches"),
        ("S__104316937_0.jpg", "zip"),
        ("S__104316931.jpg", "tango"),
    ]
    print("端對端測試 (顯示到螢幕 -> 擷取 -> 辨識 -> 求解 -> 座標映射)")
    for name, key in cases:
        check(name, key)
    print("\n全部通過。")


if __name__ == "__main__":
    main()
