"""
LinkedIn 謎題 - 網頁自動填答 GUI

流程：擷取螢幕上固定的棋盤位置 -> 辨識題目 -> 求解 -> 自動移動滑鼠填答。

使用方式：在 Chrome 開好謎題，然後按「開始自動解答」就會一路做完。
擷取範圍是固定座標（可調整並自動記住），不需要每次框選。

安全設計：
  - 預設是「預演模式」，只列出打算怎麼點，不會真的操作滑鼠。
  - 執行前有倒數，可以趁機切到瀏覽器視窗。
  - 執行中可按「停止」，或把滑鼠快速移到螢幕左上角 (0,0) 緊急中止。
"""

import json
import sys
import threading
import time
import tkinter as tk
import traceback
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import cv2
from PIL import Image, ImageTk

import capture
import solver_bridge
from board_mapper import BoardMapper
from input_driver import Aborted, InputDriver, focus_window_at, wait_for_mouse_release
from players import PLAYERS
from solve_puzzle import MIN_BOARD_PIXELS, solve_from_image

sys.path.insert(0, str(solver_bridge.solver_dir()))
from img_io import imwrite_unicode  # noqa: E402

#: 預覽圖最大顯示尺寸。刻意壓小，讓視窗保持精簡、方便錄影展示，
#: 同時確保訊息區一定有空間顯示辨識結果與錯誤原因。
MAX_PREVIEW = 150
AUTO_LABEL = "自動判斷"
SETTINGS_PATH = Path.home() / ".linkedin_puzzle_autoplay.json"

#: 等實體滑鼠放開的最長秒數 (放開就立刻開始，不會白等)
MOUSE_RELEASE_TIMEOUT = 2.0

#: 速度選項 -> 速度倍率 (數字越大越慢)。
#: 網頁要靠滑鼠移動事件判斷經過哪些格子，移動太快會漏掉中間的格子；
#: 預設用「標準(慢)」，比最初的版本慢約兩倍，實測比較穩。
SPEED_CHOICES = {
    "快": 1.0,
    "標準(慢)": 2.0,
    "很慢": 3.5,
    "超慢": 5.0,
}
SPEED_DEFAULT = "標準(慢)"


class AutoPlayApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("LinkedIn 謎題自動填答")
        self.root.geometry("375x450")
        self.root.minsize(365, 330)

        self.shot = None
        self.outcome = None
        self.mapper = None
        self.plan = None
        self.driver: InputDriver | None = None
        self.tk_photo = None
        self.busy = False

        self._type_choices = [AUTO_LABEL] + [solver_bridge.PUZZLES[k].NAME for k in solver_bridge.DISPLAY_ORDER]
        self._name_to_key = {solver_bridge.PUZZLES[k].NAME: k for k in solver_bridge.DISPLAY_ORDER}

        self._build_widgets()
        self._load_settings()

    # ---------------- UI ----------------
    def _build_widgets(self):
        pad = {"padx": 6, "pady": 2}

        # 版面刻意做窄，方便錄影展示：每列元件都控制在視窗寬度內
        region = ttk.Frame(self.root, padding=(6, 4, 6, 0))
        region.pack(fill="x")
        self.x_var, self.y_var = tk.StringVar(), tk.StringVar()
        self.w_var, self.h_var = tk.StringVar(), tk.StringVar()
        for i, (label, var) in enumerate(
            [("X", self.x_var), ("Y", self.y_var), ("寬", self.w_var), ("高", self.h_var)]
        ):
            ttk.Label(region, text=label).grid(row=0, column=i * 2, sticky="e", padx=(0 if i == 0 else 5, 1))
            ttk.Entry(region, width=5, textvariable=var).grid(row=0, column=i * 2 + 1, sticky="w")
        ttk.Button(region, text="預設", width=4, command=self.on_reset_region).grid(row=0, column=8, padx=(6, 2))
        ttk.Button(region, text="測範圍", width=7, command=self.on_test_region).grid(row=0, column=9)

        opts = ttk.Frame(self.root, padding=(6, 4, 6, 0))
        opts.pack(fill="x")
        # 謎題類型與速度放同一行，維持視窗窄小
        self.type_var = tk.StringVar(value=AUTO_LABEL)
        ttk.Combobox(opts, textvariable=self.type_var, values=self._type_choices,
                     state="readonly", width=13).grid(row=0, column=0, sticky="w")
        ttk.Label(opts, text="速度").grid(row=0, column=1, sticky="w", padx=(6, 2))
        self.speed_var = tk.StringVar(value=SPEED_DEFAULT)
        ttk.Combobox(opts, textvariable=self.speed_var, values=list(SPEED_CHOICES),
                     state="readonly", width=8).grid(row=0, column=2, sticky="w")

        checks = ttk.Frame(self.root, padding=(6, 4, 6, 0))
        checks.pack(fill="x")
        self.dry_run_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(checks, text="預演", variable=self.dry_run_var).grid(row=0, column=0, sticky="w")
        self.hide_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(checks, text="隱藏", variable=self.hide_var).grid(row=0, column=1, sticky="w", padx=(8, 0))
        self.verify_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(checks, text="檢查補點", variable=self.verify_var).grid(row=0, column=2, sticky="w", padx=(8, 0))
        self.fullscreen_var = tk.BooleanVar(value=False)
        self.countdown_var = tk.StringVar(value="0")

        act = ttk.Frame(self.root, padding=(6, 6, 6, 2))
        act.pack(fill="x")
        self.start_btn = ttk.Button(act, text="開始自動解答", width=14, command=self.on_start)
        self.start_btn.grid(row=0, column=0)
        self.preview_btn = ttk.Button(act, text="只求解", width=7, command=self.on_preview_only)
        self.preview_btn.grid(row=0, column=1, padx=3)
        self.stop_btn = ttk.Button(act, text="停止", width=5, command=self.on_stop, state="disabled")
        self.stop_btn.grid(row=0, column=2)
        ttk.Button(act, text="存圖", width=5, command=self.on_save_capture).grid(row=0, column=3, padx=3)

        # 計時顯示：錄影展示時可以直接看到各階段花了幾秒
        self.timer_label = ttk.Label(
            self.root, text="", foreground="#06c", font=("Consolas", 8, "bold"),
            wraplength=380, justify="left",
        )
        self.timer_label.pack(fill="x", padx=6)
        self.status_label = ttk.Label(self.root, text="", foreground="#0a6", wraplength=380, justify="left")
        self.status_label.pack(fill="x", padx=6)

        # 訊息區用 side="bottom" 先佔位，確保錯誤原因一定看得到
        log_frame = ttk.Frame(self.root, padding=(6, 2, 6, 6))
        log_frame.pack(side="bottom", fill="both", expand=True)
        # width 要指定，否則 Tk 預設 80 字元寬會把視窗撐開
        self.log_text = tk.Text(log_frame, width=30, height=9, wrap="word", font=("Consolas", 8))
        self.log_text.pack(fill="both", expand=True, side="left")
        bar = ttk.Scrollbar(log_frame, command=self.log_text.yview)
        bar.pack(side="right", fill="y")
        self.log_text["yscrollcommand"] = bar.set

        self.image_label = ttk.Label(self.root)
        self.image_label.pack(side="top", pady=2)

    # ---------------- 設定存取 ----------------
    def _load_settings(self):
        data = {}
        try:
            if SETTINGS_PATH.exists():
                data = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
        except Exception:
            data = {}
        region = data.get("region")
        if not (isinstance(region, list) and len(region) == 4):
            region = list(capture.default_region())
        for var, value in zip((self.x_var, self.y_var, self.w_var, self.h_var), region):
            var.set(str(int(value)))
        self.fullscreen_var.set(bool(data.get("fullscreen", False)))
        self.countdown_var.set(str(data.get("countdown", 0)))
        speed = data.get("speed")
        if speed in SPEED_CHOICES:
            self.speed_var.set(speed)

    def _save_settings(self):
        try:
            SETTINGS_PATH.write_text(
                json.dumps(
                    {
                        "region": list(self._region()),
                        "fullscreen": self.fullscreen_var.get(),
                        "countdown": self.countdown_var.get(),
                        "speed": self.speed_var.get(),
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
        except Exception:
            pass

    def _region(self) -> tuple[int, int, int, int]:
        try:
            return (
                int(self.x_var.get()), int(self.y_var.get()),
                int(self.w_var.get()), int(self.h_var.get()),
            )
        except ValueError:
            return capture.default_region()

    def on_reset_region(self):
        for var, value in zip((self.x_var, self.y_var, self.w_var, self.h_var), capture.default_region()):
            var.set(str(value))
        self._log("已回到預設擷取範圍。")

    # ---------------- 擷取 ----------------
    def _do_capture(self):
        if self.hide_var.get():
            self.root.withdraw()
            self.root.update()
            time.sleep(0.35)
        try:
            if self.fullscreen_var.get():
                return capture.capture_screen()
            return capture.capture_region(*self._region())
        finally:
            if self.hide_var.get():
                self.root.deiconify()
                self.root.update()

    def on_test_region(self):
        try:
            shot = self._do_capture()
        except Exception:
            messagebox.showerror("擷取失敗", traceback.format_exc().splitlines()[-1])
            return
        self.shot = shot
        self._show_image(shot.image)
        self._clear_log()
        self._log(
            f"擷取範圍預覽：螢幕位置 ({shot.origin_x},{shot.origin_y})，"
            f"大小 {shot.image.shape[1]}x{shot.image.shape[0]}"
        )
        self._log("請確認上方預覽圖裡有完整的棋盤。若沒有，調整 X/Y/寬/高 再測一次。")
        self._save_settings()

    # ---------------- 執行 ----------------
    def on_preview_only(self):
        self._run_flow(fill_answers=False)

    def on_start(self):
        self._run_flow(fill_answers=True)

    def _run_flow(self, fill_answers: bool):
        if self.busy:
            return
        dry = self.dry_run_var.get()
        # 不再跳確認視窗：按下按鈕就是明確的執行意圖，
        # 多一層確認只會拖慢速度(遊戲有計時)，而且按確認的那一下還會搶走滑鼠焦點。
        # 安全把關改由「預演模式」負責 —— 要真的動滑鼠必須自己取消勾選。

        self._save_settings()
        self.busy = True
        self._clear_log()
        self.start_btn.config(state="disabled")
        self.preview_btn.config(state="disabled")
        self.stop_btn.config(state="normal")
        self.status_label.config(text="擷取畫面中...")
        self.root.update_idletasks()

        try:
            shot = self._do_capture()
        except Exception:
            self._finish("擷取失敗")
            messagebox.showerror("擷取失敗", traceback.format_exc().splitlines()[-1])
            return

        self.shot = shot
        self._show_image(shot.image)
        chosen = self.type_var.get()
        puzzle_key = None if chosen == AUTO_LABEL else self._name_to_key[chosen]
        slowdown = SPEED_CHOICES.get(self.speed_var.get(), SPEED_CHOICES[SPEED_DEFAULT])
        self.driver = InputDriver(dry_run=dry, slowdown=slowdown)
        self.driver.reset()

        threading.Thread(
            target=self._worker, args=(shot, puzzle_key, fill_answers), daemon=True
        ).start()

    def _worker(self, shot, puzzle_key, fill_answers):
        timings: dict[str, float] = {}
        started_all = time.perf_counter()
        try:
            self._ui(self.status_label.config, {"text": "辨識與求解中..."})
            t0 = time.perf_counter()
            outcome = solve_from_image(shot.image, puzzle_key=puzzle_key)
            timings["辨識+求解"] = time.perf_counter() - t0
            self._ui(self._show_timings, timings, started_all)
            self.outcome = outcome

            module = solver_bridge.PUZZLES.get(outcome.puzzle_key)
            name = module.NAME if module else outcome.puzzle_key
            self._ui(self._log, f"謎題類型: {name}")
            for line in outcome.info:
                self._ui(self._log, f"  {line}")

            if not outcome.ok:
                reason = outcome.error or "辨識失敗"
                self._ui(self._log, "")
                self._ui(self._log, f"【辨識失敗】{reason}")
                self._ui(self._log, "")
                self._ui(self._log, "可以先按「測試擷取範圍」確認棋盤有被完整擷取到，")
                self._ui(self._log, "或按「存下擷取畫面...」把畫面存起來以便排查。")
                # 狀態列也顯示原因，不用捲動訊息區就看得到
                self._ui(self._finish, f"辨識失敗：{reason.splitlines()[0]}")
                return

            self.mapper = BoardMapper(shot=shot, grid=outcome.grid)
            self._ui(self._log, f"  {self.mapper.describe()}")
            board_px = outcome.grid.board_bbox[2]
            if board_px < MIN_BOARD_PIXELS:
                self._ui(
                    self._log,
                    f"  注意: 棋盤只有 {board_px}px；若結果怪怪的，"
                    f"可在 Chrome 按 Ctrl 加號放大頁面。",
                )

            self.plan = PLAYERS[outcome.puzzle_key](self.mapper).build_plan(outcome.data)
            self._ui(self._log, "")
            self._ui(self._log, "=== 填答計畫 ===")
            for line in self.plan.description:
                self._ui(self._log, line)

            self._ui(self._show_overlay, module)

            if not fill_answers:
                self._ui(self._finish, "求解完成（未填答）")
                return

            driver = self.driver
            countdown = self._countdown_seconds()
            if not driver.dry_run and countdown:
                driver.countdown(
                    countdown,
                    on_tick=lambda s: self._ui(
                        self.status_label.config, {"text": f"{s} 秒後開始..."}
                    ),
                )

            if not driver.dry_run:
                t0 = time.perf_counter()
                # 先把棋盤所在的視窗 (瀏覽器) 切到最前面。
                # 否則第一次點擊會被作業系統拿去「啟用視窗」而被吃掉，第一格就會沒填到。
                cx, cy = self.mapper.cell_center(0, 0)
                title = focus_window_at(cx, cy)
                self._ui(self._log, f"  切到目標視窗: {title or '(無標題)'}")
                # 等使用者的實體滑鼠鍵放開再開始，避免跟使用者搶滑鼠。
                # 放開得快就幾乎不會等，不是固定延遲。
                self._ui(self.status_label.config, {"text": "等待放開滑鼠..."})
                waited = wait_for_mouse_release(MOUSE_RELEASE_TIMEOUT)
                timings["起步"] = time.perf_counter() - t0
                self._ui(self._log, f"  等待放開滑鼠 {waited:.2f} 秒")

            self._ui(self.status_label.config, {"text": "填答中..."})
            t0 = time.perf_counter()
            self.plan.run(driver)
            timings["填答"] = time.perf_counter() - t0
            self._ui(self._show_timings, timings, started_all)

            if not driver.dry_run and self.verify_var.get():
                self._ui(self.status_label.config, {"text": "檢查中..."})
                t0 = time.perf_counter()
                self._verify_and_retry(driver)
                timings["檢查補點"] = time.perf_counter() - t0

            timings["總計"] = time.perf_counter() - started_all
            self._ui(self._show_timings, timings, started_all)

            self._ui(self._log, "")
            self._ui(self._log, driver.summary())
            self._ui(self._log, "耗時: " + "、".join(f"{k} {v:.2f}s" for k, v in timings.items()))
            if driver.dry_run:
                self._ui(self._log, "以上只是預演。取消勾選「預演」才會真的操作滑鼠。")
                for line in driver.log:
                    self._ui(self._log, f"  {line}")
            self._ui(self._finish, "預演完成" if driver.dry_run else "完成")

        except Aborted:
            self._ui(self._finish, "已中止")
        except Exception:
            text = traceback.format_exc()
            self._ui(self._log, text)
            self._ui(self._finish, "發生錯誤")

    def _verify_and_retry(self, driver, max_rounds: int = 3):
        """
        填完後重新擷取檢查，只補「確實還沒填對」的格子。

        安全機制：如果補點之後「沒填對的格數」沒有減少，就立刻停手。
        因為那代表辨識判斷有問題，繼續點下去只會把已經正確的格子又點掉
        (點擊是循環的：皇冠再點一下就變回空白)。
        """
        from verify import build_retry_plan, verify

        previous_wrong = None
        for attempt in range(1, max_rounds + 1):
            time.sleep(0.9)  # 等網頁把畫面更新完
            fresh = (
                capture.capture_screen() if self.fullscreen_var.get()
                else capture.capture_region(*self._region())
            )
            report = verify(fresh.image, self.outcome)
            self._ui(self._log, f"[檢查 第 {attempt} 輪] {report.summary()}")

            if report.board_changed:
                # 盤面已經換掉 (通常是解完跳出完成畫面)，再點下去只是亂點
                self._ui(self._log, "  已停止操作，不再控制滑鼠。")
                return
            if not report.supported:
                return
            if report.ok:
                self._ui(self._log, "  已完成，停止操作。")
                return

            wrong = len(report.mismatches)
            if previous_wrong is not None and wrong >= previous_wrong:
                self._ui(
                    self._log,
                    f"  補點後沒有改善 ({previous_wrong} -> {wrong} 格)，"
                    "為避免把已經填對的格子點掉，停止補點。",
                )
                return
            previous_wrong = wrong

            retry_plan = build_retry_plan(self.outcome, self.mapper, report)
            if retry_plan is None:
                return
            self._ui(self._log, f"  補點 {wrong} 格...")
            retry_plan.run(driver)

    def _show_timings(self, timings: dict, started_all: float):
        """把各階段耗時顯示在視窗上，錄影時可以直接看到秒數。"""
        parts = [f"{name} {seconds:.2f}s" for name, seconds in timings.items()]
        if "總計" not in timings:
            parts.append(f"進行中 {time.perf_counter() - started_all:.2f}s")
        self.timer_label.config(text="⏱ " + "  |  ".join(parts))

    def _countdown_seconds(self) -> int:
        try:
            return max(0, int(self.countdown_var.get()))
        except ValueError:
            return 4

    def _show_overlay(self, module):
        try:
            result = module.analyze(self.shot.image, debug=False)
            if result.overlay_image is not None:
                self._show_image(result.overlay_image)
        except Exception:
            pass

    def _finish(self, status: str):
        self.busy = False
        self.start_btn.config(state="normal")
        self.preview_btn.config(state="normal")
        self.stop_btn.config(state="disabled")
        self.status_label.config(text=status)

    def on_stop(self):
        if self.driver:
            self.driver.stop()
        self.status_label.config(text="停止中...")

    def on_save_capture(self):
        if self.shot is None:
            messagebox.showinfo("尚未擷取", "請先按「測試擷取範圍」或「開始自動解答」。")
            return
        path = filedialog.asksaveasfilename(
            title="存下擷取畫面", defaultextension=".png",
            initialfile="capture.png", filetypes=[("PNG 圖片", "*.png")],
        )
        if not path:
            return
        imwrite_unicode(Path(path), self.shot.image)
        messagebox.showinfo("已儲存", f"已存到:\n{path}")

    # ---------------- 小工具 ----------------
    def _ui(self, func, *args):
        """從背景執行緒安全地更新畫面。"""
        self.root.after(0, lambda: func(*args))

    def _log(self, *lines):
        for line in lines:
            self.log_text.insert(tk.END, str(line) + "\n")
        self.log_text.see(tk.END)

    def _clear_log(self):
        self.log_text.delete("1.0", tk.END)

    def _show_image(self, cv_image):
        rgb = cv2.cvtColor(cv_image, cv2.COLOR_BGR2RGB)
        pil = Image.fromarray(rgb)
        w, h = pil.size
        scale = min(MAX_PREVIEW / w, MAX_PREVIEW / h, 1.0)
        if scale < 1.0:
            pil = pil.resize((int(w * scale), int(h * scale)), Image.LANCZOS)
        self.tk_photo = ImageTk.PhotoImage(pil)
        self.image_label.config(image=self.tk_photo)


def main():
    if sys.platform == "win32":
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass
    root = tk.Tk()
    app = AutoPlayApp(root)
    root.protocol("WM_DELETE_WINDOW", lambda: (app._save_settings(), root.destroy()))
    root.mainloop()


if __name__ == "__main__":
    main()
