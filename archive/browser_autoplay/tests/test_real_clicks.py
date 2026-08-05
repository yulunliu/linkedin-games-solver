"""
真實滑鼠點擊測試：驗證「算出來的座標 -> 實際移動滑鼠點擊」真的會點到正確的格子。

作法：用一個 Tk 視窗把謎題畫在螢幕上，並在視窗上綁定滑鼠事件記錄「被點到哪一格」。
接著跑完整流程 (擷取 -> 辨識 -> 求解 -> 實際點擊)，最後比對記錄到的格子
是否與解答一致。

注意：這個測試**會實際移動並點擊滑鼠**，但只會點在自己開的測試視窗上。
執行期間請不要動滑鼠。需要實體桌面環境。
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
DISPLAY_HEIGHT = 1300


def pick_test_origin(width: int, height: int) -> tuple[int, int]:
    """
    挑一個放測試視窗的位置。

    如果有第二台螢幕就優先放在那裡：主螢幕上可能有全螢幕程式 (例如遊戲) 蓋住
    我們的測試視窗，滑鼠點擊就會點到那個程式而不是測試視窗，測試會失真。
    """
    import mss

    with mss.mss() as sct:
        monitors = sct.monitors[1:]
    for mon in monitors[::-1]:  # 從最後一台開始找，通常是副螢幕
        if mon["width"] >= width + 40 and mon["height"] >= height + 40:
            return mon["left"] + 20, mon["top"] + 20
    return 20, 20


def force_foreground(root: tk.Tk):
    """把測試視窗搶到最前面，確保滑鼠點擊真的落在它身上。"""
    root.lift()
    root.attributes("-topmost", True)
    root.focus_force()
    try:
        import ctypes

        hwnd = ctypes.windll.user32.GetParent(root.winfo_id()) or root.winfo_id()
        ctypes.windll.user32.SetForegroundWindow(hwnd)
    except Exception:
        pass


def run_case(sample_name: str, expected_key: str):
    src = imread_unicode(SAMPLES / sample_name)
    assert src is not None
    scale = DISPLAY_HEIGHT / src.shape[0]
    shown = cv2.resize(src, (int(src.shape[1] * scale), DISPLAY_HEIGHT), interpolation=cv2.INTER_AREA)

    window_x, window_y = pick_test_origin(shown.shape[1], shown.shape[0])

    root = tk.Tk()
    root.overrideredirect(True)
    root.geometry(f"{shown.shape[1]}x{shown.shape[0]}+{window_x}+{window_y}")
    root.attributes("-topmost", True)
    photo = ImageTk.PhotoImage(Image.fromarray(cv2.cvtColor(shown, cv2.COLOR_BGR2RGB)))
    label = tk.Label(root, image=photo, borderwidth=0, highlightthickness=0)
    label.pack()
    root.after(200, lambda: force_foreground(root))

    clicks: list[tuple[int, int]] = []  # 記錄 (螢幕x, 螢幕y)
    state: dict = {}

    def on_click(event):
        clicks.append((event.x_root, event.y_root))

    # 同一點快速連點會被系統歸類成雙擊/三擊手勢，Tk 送出的事件名稱會不同，
    # 所以四種都要綁，才能完整統計實際收到幾次點擊。
    for event_name in ("<Button-1>", "<Double-Button-1>", "<Triple-Button-1>", "<Quadruple-Button-1>"):
        label.bind(event_name, on_click)

    def worker():
        # 等視窗真的畫出來
        for _ in range(10):
            time.sleep(0.5)
            shot = capture.capture_region(window_x, window_y, shown.shape[1], shown.shape[0])
            if shot.image.shape == shown.shape and cv2.absdiff(shot.image, shown).mean() < 1.0:
                break
        state["shot"] = shot

        outcome = solve_from_image(shot.image)
        state["outcome"] = outcome
        if not outcome.ok:
            root.after(0, root.destroy)
            return

        mapper = BoardMapper(shot=shot, grid=outcome.grid)
        state["mapper"] = mapper
        plan = PLAYERS[outcome.puzzle_key](mapper).build_plan(outcome.data)

        driver = InputDriver(dry_run=False, click_interval=0.03)
        try:
            plan.run(driver)
        except Exception as e:  # noqa: BLE001
            state["error"] = f"{type(e).__name__}: {e}"
        time.sleep(0.4)
        root.after(0, root.destroy)

    threading.Thread(target=worker, daemon=True).start()
    root.mainloop()

    outcome = state.get("outcome")
    assert outcome is not None and outcome.ok, f"{sample_name} 求解失敗: {outcome and outcome.error}"
    assert "error" not in state, f"{sample_name} 執行出錯: {state.get('error')}"
    assert outcome.puzzle_key == expected_key

    mapper = state["mapper"]

    # 把記錄到的螢幕座標換算回「第幾列第幾欄」
    left, top, bw, bh = mapper.board_rect_on_screen()
    clicked_cells = []
    for x, y in clicks:
        col = int((x - left) / (bw / mapper.n))
        row = int((y - top) / (bh / mapper.n))
        clicked_cells.append((row, col))

    return outcome, clicked_cells


def test_queens_clicks():
    outcome, clicked = run_case("S__104316934_0.jpg", "queens")
    expected = outcome.data["queens"]
    # Queens 每格點兩下，所以每個位置會出現兩次
    unique_clicked = []
    for cell in clicked:
        if not unique_clicked or unique_clicked[-1] != cell:
            unique_clicked.append(cell)

    assert unique_clicked == list(expected), (
        f"實際點到的格子與解答不符\n  點到: {unique_clicked}\n  應為: {list(expected)}"
    )
    assert len(clicked) == len(expected) * 2, f"點擊次數不對: {len(clicked)} (應為 {len(expected)*2})"
    print(f"  Queens: 實際點擊 {len(clicked)} 次，落點全部正確 {unique_clicked}")


def test_tango_clicks():
    outcome, clicked = run_case("S__104316931.jpg", "tango")
    solution = outcome.data["solution"]
    givens = outcome.data["givens"]

    expected_cells = [
        (r, c)
        for r in range(len(solution))
        for c in range(len(solution))
        if (r, c) not in givens
    ]
    unique_clicked = []
    for cell in clicked:
        if not unique_clicked or unique_clicked[-1] != cell:
            unique_clicked.append(cell)

    assert unique_clicked == expected_cells, (
        f"實際點到的格子與計畫不符\n  點到: {unique_clicked}\n  應為: {expected_cells}"
    )
    # 太陽點 1 下、月亮點 2 下
    expected_clicks = sum(1 if solution[r][c] == 1 else 2 for r, c in expected_cells)
    assert len(clicked) == expected_clicks, f"點擊次數不對: {len(clicked)} (應為 {expected_clicks})"
    print(f"  Tango: 實際點擊 {len(clicked)} 次，{len(unique_clicked)} 格落點全部正確")


if __name__ == "__main__":
    print("真實滑鼠點擊測試 (會實際操作滑鼠，只點在測試視窗上)")
    test_queens_clicks()
    test_tango_clicks()
    print("\n全部通過：座標計算 -> 實際滑鼠點擊 都正確。")
