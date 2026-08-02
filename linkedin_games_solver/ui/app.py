"""
Desktop GUI with two modes.
桌面介面，含兩種模式。

  SCREEN mode - capture a fixed region of the screen, solve, and drive the mouse
                to fill the answer in the browser.
  IMAGE  mode - load a screenshot from disk (e.g. taken on a phone), solve, and
                draw the answer on the image. Never touches the mouse.
  螢幕模式 —— 擷取螢幕固定範圍、求解，再操作滑鼠在瀏覽器裡填答。
  圖片模式 —— 從磁碟載入截圖（例如手機拍的），求解後把答案畫在圖上。
              完全不會操作滑鼠。

Both modes share the same recognise-and-solve pipeline; only the input source
and the output action differ.
兩種模式共用同一套辨識求解流程，差別只在輸入來源與輸出動作。
"""

from __future__ import annotations

import sys
import threading
import time
import tkinter as tk
import traceback
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import cv2
from PIL import Image, ImageTk

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
from ..i18n import LANGUAGES, translator
from ..puzzles import (
    DISPLAY_ORDER,
    MIN_BOARD_PIXELS,
    puzzle_name,
    render_overlay,
    solve_image,
)
from . import settings as settings_store

#: Preview is deliberately small so the message area always has room, and so the
#: window stays compact enough to sit beside a browser while screen-recording.
#: 預覽圖刻意做小，確保訊息區一定有空間，也讓視窗夠精簡，錄影時能跟瀏覽器並排。
MAX_PREVIEW = 150
MOUSE_RELEASE_TIMEOUT = 2.0

#: Speed label -> delay multiplier (larger = slower).
#: 速度選項 -> 延遲倍率（數字越大越慢）。
SPEED_FACTORS = {"fast": 1.0, "normal": 2.0, "slow": 3.5, "slowest": 5.0}
SPEED_KEYS = ["fast", "normal", "slow", "slowest"]


class SolverApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.settings = settings_store.load()
        translator.set_language(self.settings.get("language", "zh"))

        self.shot = None
        self.result = None
        self.mapper = None
        self.plan = None
        self.driver: InputDriver | None = None
        self.image_path: Path | None = None
        self.tk_photo = None
        self.busy = False

        self.root.title(translator("app_title"))
        self.root.geometry("400x470")
        self.root.minsize(390, 350)
        self._build_widgets()
        self._apply_settings()

    # ------------------------------------------------------------------ UI
    def _build_widgets(self):
        # --- Row 1: language + mode 語言與模式 ---
        top = ttk.Frame(self.root, padding=(6, 6, 6, 0))
        top.pack(fill="x")
        self.lang_var = tk.StringVar(value=LANGUAGES[translator.language])
        self.lang_combo = ttk.Combobox(top, textvariable=self.lang_var, values=list(LANGUAGES.values()),
                                       state="readonly", width=8)
        self.lang_combo.grid(row=0, column=0, sticky="w")
        self.lang_combo.bind("<<ComboboxSelected>>", self._on_language_changed)

        self.mode_var = tk.StringVar(value="screen")
        self.mode_screen_rb = ttk.Radiobutton(top, text="", value="screen",
                                              variable=self.mode_var, command=self._on_mode_changed)
        self.mode_screen_rb.grid(row=0, column=1, sticky="w", padx=(10, 0))
        self.mode_image_rb = ttk.Radiobutton(top, text="", value="image",
                                             variable=self.mode_var, command=self._on_mode_changed)
        self.mode_image_rb.grid(row=0, column=2, sticky="w", padx=(6, 0))

        # --- Row 2: source (region for screen mode, file for image mode) ---
        # --- 第 2 列：來源（螢幕模式是範圍，圖片模式是檔案）---
        self.source_frame = ttk.Frame(self.root, padding=(6, 4, 6, 0))
        self.source_frame.pack(fill="x")

        self.region_frame = ttk.Frame(self.source_frame)
        self.x_var, self.y_var = tk.StringVar(), tk.StringVar()
        self.w_var, self.h_var = tk.StringVar(), tk.StringVar()
        for i, (label, var) in enumerate(
            [("X", self.x_var), ("Y", self.y_var), ("W", self.w_var), ("H", self.h_var)]
        ):
            ttk.Label(self.region_frame, text=label).grid(row=0, column=i * 2, sticky="e", padx=(0 if i == 0 else 5, 1))
            ttk.Entry(self.region_frame, width=5, textvariable=var).grid(row=0, column=i * 2 + 1, sticky="w")
        self.reset_btn = ttk.Button(self.region_frame, text="", width=6, command=self._on_reset_region)
        self.reset_btn.grid(row=0, column=8, padx=(6, 2))
        self.test_btn = ttk.Button(self.region_frame, text="", width=8, command=self._on_test_region)
        self.test_btn.grid(row=0, column=9)

        self.image_frame = ttk.Frame(self.source_frame)
        self.pick_btn = ttk.Button(self.image_frame, text="", command=self._on_pick_image)
        self.pick_btn.grid(row=0, column=0)
        self.image_label_text = ttk.Label(self.image_frame, text="", foreground="#555")
        self.image_label_text.grid(row=0, column=1, sticky="w", padx=(6, 0))

        # --- Row 3: puzzle type + speed 謎題類型與速度 ---
        opts = ttk.Frame(self.root, padding=(6, 4, 6, 0))
        opts.pack(fill="x")
        self.type_var = tk.StringVar()
        self.type_combo = ttk.Combobox(opts, textvariable=self.type_var, state="readonly", width=13)
        self.type_combo.grid(row=0, column=0, sticky="w")
        self.speed_label = ttk.Label(opts, text="")
        self.speed_label.grid(row=0, column=1, sticky="w", padx=(6, 2))
        self.speed_var = tk.StringVar()
        self.speed_combo = ttk.Combobox(opts, textvariable=self.speed_var, state="readonly", width=8)
        self.speed_combo.grid(row=0, column=2, sticky="w")

        # --- Row 4: checkboxes 勾選項 ---
        checks = ttk.Frame(self.root, padding=(6, 4, 6, 0))
        checks.pack(fill="x")
        self.dry_run_var = tk.BooleanVar(value=True)
        self.dry_cb = ttk.Checkbutton(checks, text="", variable=self.dry_run_var)
        self.dry_cb.grid(row=0, column=0, sticky="w")
        self.hide_var = tk.BooleanVar(value=True)
        self.hide_cb = ttk.Checkbutton(checks, text="", variable=self.hide_var)
        self.hide_cb.grid(row=0, column=1, sticky="w", padx=(8, 0))
        self.verify_var = tk.BooleanVar(value=True)
        self.verify_cb = ttk.Checkbutton(checks, text="", variable=self.verify_var)
        self.verify_cb.grid(row=0, column=2, sticky="w", padx=(8, 0))

        # --- Row 5: actions 執行 ---
        actions = ttk.Frame(self.root, padding=(6, 6, 6, 2))
        actions.pack(fill="x")
        self.start_btn = ttk.Button(actions, text="", width=14, command=self._on_start)
        self.start_btn.grid(row=0, column=0)
        self.solve_btn = ttk.Button(actions, text="", width=8, command=self._on_solve_only)
        self.solve_btn.grid(row=0, column=1, padx=3)
        self.stop_btn = ttk.Button(actions, text="", width=6, command=self._on_stop, state="disabled")
        self.stop_btn.grid(row=0, column=2)
        self.save_btn = ttk.Button(actions, text="", width=6, command=self._on_save)
        self.save_btn.grid(row=0, column=3, padx=3)

        # --- Timing + status 計時與狀態 ---
        self.timer_label = ttk.Label(self.root, text="", foreground="#06c",
                                     font=("Consolas", 8, "bold"), wraplength=380, justify="left")
        self.timer_label.pack(fill="x", padx=6)
        self.status_label = ttk.Label(self.root, text="", foreground="#0a6",
                                      wraplength=380, justify="left")
        self.status_label.pack(fill="x", padx=6)

        # Message area is packed to the bottom FIRST so it always keeps its space;
        # otherwise the preview image pushes it out of the window and failures
        # become invisible.
        # 訊息區先用 side="bottom" 佔位，確保它一定有空間；
        # 否則預覽圖會把它擠出視窗，失敗原因就完全看不到。
        log_frame = ttk.Frame(self.root, padding=(6, 2, 6, 6))
        log_frame.pack(side="bottom", fill="both", expand=True)
        # width must be set, or Tk's default 80 characters widens the window.
        # width 一定要指定，否則 Tk 預設 80 字元寬會把視窗撐開。
        self.log_text = tk.Text(log_frame, width=30, height=9, wrap="word", font=("Consolas", 8))
        self.log_text.pack(fill="both", expand=True, side="left")
        scrollbar = ttk.Scrollbar(log_frame, command=self.log_text.yview)
        scrollbar.pack(side="right", fill="y")
        self.log_text["yscrollcommand"] = scrollbar.set

        self.image_preview = ttk.Label(self.root)
        self.image_preview.pack(side="top", pady=2)

    def _retranslate(self):
        """Re-apply every visible string after a language change.
        語言切換後重新套用所有可見字串。"""
        t = translator
        self.root.title(t("app_title"))
        self.mode_screen_rb.config(text=t("mode_screen"))
        self.mode_image_rb.config(text=t("mode_image"))
        self.reset_btn.config(text=t("reset"))
        self.test_btn.config(text=t("test_region"))
        self.pick_btn.config(text=t("pick_image"))
        if self.image_path is None:
            self.image_label_text.config(text=t("no_image"))
        self.speed_label.config(text=t("speed"))
        self.dry_cb.config(text=t("dry_run"))
        self.hide_cb.config(text=t("hide_window"))
        self.verify_cb.config(text=t("verify_retry"))
        self.start_btn.config(text=t("start"))
        self.solve_btn.config(text=t("solve_only"))
        self.stop_btn.config(text=t("stop"))
        self.save_btn.config(text=t("save_capture"))

        # Rebuild the combo boxes, preserving the current selection by index.
        # 重建下拉選單，用索引保留目前選取項。
        type_index = self.type_combo.current()
        self.type_combo["values"] = [t("auto_detect")] + [
            puzzle_name(k, t.language) for k in DISPLAY_ORDER
        ]
        self.type_combo.current(max(0, type_index))

        speed_index = self.speed_combo.current()
        self.speed_combo["values"] = [t(f"speed_{k}") for k in SPEED_KEYS]
        self.speed_combo.current(max(0, speed_index))

    # ------------------------------------------------------------ settings
    def _apply_settings(self):
        region = self.settings.get("region") or list(default_region())
        for var, value in zip((self.x_var, self.y_var, self.w_var, self.h_var), region):
            var.set(str(int(value)))
        self.mode_var.set(self.settings.get("mode", "screen"))

        self.type_combo["values"] = [translator("auto_detect")] + [
            puzzle_name(k, translator.language) for k in DISPLAY_ORDER
        ]
        self.type_combo.current(0)
        self.speed_combo["values"] = [translator(f"speed_{k}") for k in SPEED_KEYS]
        speed = self.settings.get("speed", "normal")
        self.speed_combo.current(SPEED_KEYS.index(speed) if speed in SPEED_KEYS else 1)

        self._retranslate()
        self._on_mode_changed()

    def _save_settings(self):
        self.settings.update({
            "region": list(self._region()),
            "speed": SPEED_KEYS[max(0, self.speed_combo.current())],
            "language": translator.language,
            "mode": self.mode_var.get(),
        })
        settings_store.save(self.settings)

    def _region(self) -> tuple[int, int, int, int]:
        try:
            return (int(self.x_var.get()), int(self.y_var.get()),
                    int(self.w_var.get()), int(self.h_var.get()))
        except ValueError:
            return default_region()

    # ----------------------------------------------------------- callbacks
    def _on_language_changed(self, _event=None):
        for code, label in LANGUAGES.items():
            if label == self.lang_var.get():
                translator.set_language(code)
                break
        self._retranslate()
        self._save_settings()

    def _on_mode_changed(self):
        """Show the source controls that belong to the selected mode.
        依選擇的模式切換來源控制項。"""
        image_mode = self.mode_var.get() == "image"
        self.region_frame.pack_forget()
        self.image_frame.pack_forget()
        (self.image_frame if image_mode else self.region_frame).pack(fill="x")

        # Mouse-related options are meaningless when solving a file.
        # 解圖片檔時，跟滑鼠有關的選項沒有意義。
        state = "disabled" if image_mode else "normal"
        for widget in (self.dry_cb, self.hide_cb, self.verify_cb, self.speed_combo):
            widget.config(state=state if state == "disabled" else ("readonly" if widget is self.speed_combo else "normal"))
        self.start_btn.config(text=translator("start") if not image_mode else translator("solve_only"))
        self._save_settings()

    def _on_reset_region(self):
        for var, value in zip((self.x_var, self.y_var, self.w_var, self.h_var), default_region()):
            var.set(str(value))

    def _on_pick_image(self):
        path = filedialog.askopenfilename(
            title=translator("dlg_pick_image"),
            filetypes=[("Images", "*.png *.jpg *.jpeg *.bmp *.webp"), ("All files", "*.*")],
        )
        if not path:
            return
        image = read_image(path)
        if image is None:
            messagebox.showerror(translator("dlg_read_failed"), path)
            return
        self.image_path = Path(path)
        self.image_label_text.config(text=self.image_path.name)
        self.shot = from_file_image(image)
        self._show_image(image)
        self._clear_log()
        self._log(translator("img_hint"))

    def _on_test_region(self):
        try:
            shot = self._capture()
        except Exception:
            messagebox.showerror(translator("dlg_capture_failed"), traceback.format_exc().splitlines()[-1])
            return
        self.shot = shot
        self._show_image(shot.image)
        self._clear_log()
        self._log(f"{translator('log_region_preview')}: ({shot.origin_x},{shot.origin_y}) "
                  f"{shot.image.shape[1]}x{shot.image.shape[0]}")
        self._log(translator("log_region_hint"))
        self._save_settings()

    def _on_solve_only(self):
        self._run(fill_answers=False)

    def _on_start(self):
        # Image mode never drives the mouse, so "start" is just "solve".
        # 圖片模式不操作滑鼠，所以「開始」等同「只求解」。
        self._run(fill_answers=self.mode_var.get() == "screen")

    def _on_stop(self):
        if self.driver:
            self.driver.stop()
        self.status_label.config(text=translator("status_stopping"))

    def _on_save(self):
        """Save the capture, or the answer overlay in image mode.
        存下擷取畫面；圖片模式則存答案疊圖。"""
        if self.shot is None:
            messagebox.showinfo(translator("dlg_nothing_to_save"), "")
            return
        image = self.shot.image
        default_name = "capture.png"
        if self.result is not None and self.result.ok:
            overlay = render_overlay(self.shot.image, self.result)
            if overlay is not None:
                image = overlay
                stem = self.image_path.stem if self.image_path else "board"
                default_name = f"{stem}_solved.png"
        path = filedialog.asksaveasfilename(
            title=translator("dlg_save_title"), defaultextension=".png",
            initialfile=default_name, filetypes=[("PNG", "*.png")],
        )
        if not path:
            return
        write_image(Path(path), image)
        messagebox.showinfo(translator("dlg_saved"), path)

    # -------------------------------------------------------------- capture
    def _capture(self):
        if self.mode_var.get() == "image":
            return self.shot
        if self.hide_var.get():
            self.root.withdraw()
            self.root.update()
            time.sleep(0.35)
        try:
            if self.settings.get("fullscreen"):
                return capture_screen()
            return capture_region(*self._region())
        finally:
            if self.hide_var.get():
                self.root.deiconify()
                self.root.update()

    # ------------------------------------------------------------ main flow
    def _run(self, fill_answers: bool):
        if self.busy:
            return
        image_mode = self.mode_var.get() == "image"
        if image_mode and self.shot is None:
            messagebox.showinfo(translator("dlg_nothing_to_save"), translator("no_image"))
            return

        self._save_settings()
        self.busy = True
        self._clear_log()
        self.start_btn.config(state="disabled")
        self.solve_btn.config(state="disabled")
        self.stop_btn.config(state="normal")
        self.status_label.config(text=translator("status_capturing"))
        self.root.update_idletasks()

        try:
            shot = self._capture()
        except Exception:
            self._finish(translator("dlg_capture_failed"))
            messagebox.showerror(translator("dlg_capture_failed"), traceback.format_exc().splitlines()[-1])
            return

        self.shot = shot
        self._show_image(shot.image)

        index = self.type_combo.current()
        puzzle_key = None if index <= 0 else DISPLAY_ORDER[index - 1]
        speed = SPEED_FACTORS[SPEED_KEYS[max(0, self.speed_combo.current())]]
        self.driver = InputDriver(dry_run=self.dry_run_var.get(), slowdown=speed)
        self.driver.reset()

        threading.Thread(target=self._worker, args=(shot, puzzle_key, fill_answers), daemon=True).start()

    def _worker(self, shot, puzzle_key, fill_answers):
        timings: dict[str, float] = {}
        started = time.perf_counter()
        try:
            self._ui(self.status_label.config, {"text": translator("status_solving")})
            t0 = time.perf_counter()
            result = solve_image(shot.image, puzzle_key=puzzle_key)
            timings["solve"] = time.perf_counter() - t0
            self._ui(self._show_timings, timings, started)
            self.result = result

            name = puzzle_name(result.puzzle_key, translator.language)
            self._ui(self._log, f"{translator('log_puzzle_type')}: {name}")
            for line in result.info:
                self._ui(self._log, f"  {line}")

            if not result.ok:
                reason = result.error or translator("status_failed")
                self._ui(self._log, "")
                self._ui(self._log, reason)
                self._ui(self._log, "")
                self._ui(self._log, translator("log_fail_hint"))
                self._ui(self._finish, f"{translator('status_failed')}: {reason.splitlines()[0]}")
                return

            # Draw the answer on the ORIGINAL image (the pipeline works on a
            # scaled copy, so the overlay has to be regenerated here).
            # 把答案畫在「原始影像」上（流程內部是在縮放過的複本上運算，
            # 所以疊圖必須在這裡重新產生）。
            overlay = render_overlay(shot.image, result)
            if overlay is not None:
                self._ui(self._show_image, overlay)

            self.mapper = BoardMapper(shot=shot, grid=result.grid)
            self._ui(self._log, f"  {self.mapper.describe()}")
            board_px = result.grid.board_bbox[2]
            if board_px < MIN_BOARD_PIXELS:
                self._ui(self._log, "  " + translator("log_board_small", px=board_px))

            self.plan = build_plan(result.puzzle_key, self.mapper, result.data)
            if self.plan:
                self._ui(self._log, "")
                self._ui(self._log, translator("log_plan"))
                for line in self.plan.description:
                    self._ui(self._log, line)

            if not fill_answers or self.plan is None:
                timings["total"] = time.perf_counter() - started
                self._ui(self._show_timings, timings, started)
                self._ui(self._finish, translator("status_solved_only"))
                return

            driver = self.driver
            if not driver.dry_run:
                t0 = time.perf_counter()
                # Bring the browser to the front first, otherwise the OS eats the
                # first click just to activate the window.
                # 先把瀏覽器切到最前面，否則第一次點擊會被作業系統拿去啟用視窗。
                cx, cy = self.mapper.cell_center(0, 0)
                title = focus_window_at(cx, cy)
                self._ui(self._log, f"  {translator('log_focus_window')}: {title or '?'}")
                # Wait for the user's physical mouse button to come up, so the
                # automation is not fighting their hand.
                # 等使用者的實體滑鼠鍵放開，避免跟他們的手搶控制權。
                self._ui(self.status_label.config, {"text": translator("status_waiting_mouse")})
                waited = wait_for_mouse_release(MOUSE_RELEASE_TIMEOUT)
                timings["start"] = time.perf_counter() - t0
                self._ui(self._log, f"  {translator('log_wait_mouse')}: {waited:.2f}s")

            self._ui(self.status_label.config, {"text": translator("status_filling")})
            t0 = time.perf_counter()
            self.plan.run(driver)
            timings["fill"] = time.perf_counter() - t0
            self._ui(self._show_timings, timings, started)

            if not driver.dry_run and self.verify_var.get():
                self._ui(self.status_label.config, {"text": translator("status_checking")})
                t0 = time.perf_counter()
                self._verify_and_retry(driver)
                timings["verify"] = time.perf_counter() - t0

            timings["total"] = time.perf_counter() - started
            self._ui(self._show_timings, timings, started)
            self._ui(self._log, "")
            self._ui(self._log, driver.summary())
            self._ui(self._log, translator("log_elapsed") + ": "
                     + ", ".join(f"{k} {v:.2f}s" for k, v in timings.items()))
            if driver.dry_run:
                self._ui(self._log, translator("log_preview_note"))
            self._ui(self._finish, translator("status_preview_done") if driver.dry_run
                     else translator("status_done"))

        except Aborted:
            self._ui(self._finish, translator("status_stopped"))
        except Exception:
            self._ui(self._log, traceback.format_exc())
            self._ui(self._finish, translator("status_error"))

    def _verify_and_retry(self, driver, max_rounds: int = 3):
        """Re-capture, compare, and re-click only what is still wrong.
        重新擷取、比對，只補還沒填對的格子。"""
        previous_wrong = None
        for attempt in range(1, max_rounds + 1):
            time.sleep(0.9)  # let the page finish redrawing 等網頁畫面更新完
            fresh = capture_screen() if self.settings.get("fullscreen") else capture_region(*self._region())
            report = verify(fresh.image, self.result)
            self._ui(self._log, f"[{translator('log_check_round')} {attempt}] {report.summary()}")

            if report.board_changed:
                self._ui(self._log, translator("log_board_changed"))
                return
            if not report.supported:
                return
            if report.ok:
                self._ui(self._log, translator("log_complete_stop"))
                return

            wrong = len(report.mismatches)
            # If a round did not improve things, recognition is unreliable here;
            # clicking more would start undoing correct cells.
            # 若某一輪沒有改善，代表辨識不可靠；再點下去會開始破壞已填對的格子。
            if previous_wrong is not None and wrong >= previous_wrong:
                self._ui(self._log, translator("log_no_improve"))
                return
            previous_wrong = wrong

            retry_plan = build_retry_plan(self.result, self.mapper, report)
            if retry_plan is None:
                return
            self._ui(self._log, f"{translator('log_retry')} {wrong}")
            retry_plan.run(driver)

    # ------------------------------------------------------------- helpers
    def _finish(self, status: str):
        self.busy = False
        self.start_btn.config(state="normal")
        self.solve_btn.config(state="normal")
        self.stop_btn.config(state="disabled")
        self.status_label.config(text=status)

    def _show_timings(self, timings: dict, started: float):
        parts = [f"{k} {v:.2f}s" for k, v in timings.items()]
        if "total" not in timings:
            parts.append(f"... {time.perf_counter() - started:.2f}s")
        self.timer_label.config(text="⏱ " + "  |  ".join(parts))

    def _ui(self, func, *args):
        """Run a UI update on the Tk thread from the worker thread.
        從工作執行緒把畫面更新排回 Tk 主執行緒。"""
        self.root.after(0, lambda: func(*args))

    def _log(self, *lines):
        for line in lines:
            self.log_text.insert(tk.END, str(line) + "\n")
        self.log_text.see(tk.END)

    def _clear_log(self):
        self.log_text.delete("1.0", tk.END)

    def _show_image(self, image):
        rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        pil = Image.fromarray(rgb)
        w, h = pil.size
        scale = min(MAX_PREVIEW / w, MAX_PREVIEW / h, 1.0)
        if scale < 1.0:
            pil = pil.resize((int(w * scale), int(h * scale)), Image.LANCZOS)
        self.tk_photo = ImageTk.PhotoImage(pil)
        self.image_preview.config(image=self.tk_photo)


def main():
    if sys.platform == "win32":
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass
    root = tk.Tk()
    app = SolverApp(root)
    root.protocol("WM_DELETE_WINDOW", lambda: (app._save_settings(), root.destroy()))
    root.mainloop()
