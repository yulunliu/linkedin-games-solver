"""
LinkedIn 謎題自動求解 - 桌面 GUI

支援 Tango / Queens / Mini Sudoku / Zip / Patches 五種謎題。

用法 (開發模式): python gui.py
打包成 exe 後: 雙擊執行即可，不需要開終端機、不需要打指令。
"""

import sys
import threading
import tkinter as tk
import traceback
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import cv2
from PIL import Image, ImageTk

from img_io import imread_unicode, imwrite_unicode
from registry import DISPLAY_ORDER, PUZZLES, detect_type

MAX_DISPLAY_SIZE = 520
AUTO_LABEL = "自動判斷"


class PuzzleSolverApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("LinkedIn 謎題自動求解")
        self.root.geometry("680x900")

        self.image_path: Path | None = None
        self.cv_image = None
        self.result = None
        self.tk_photo = None  # 保留參照，避免被 GC 回收

        self._type_choices = [AUTO_LABEL] + [PUZZLES[key].NAME for key in DISPLAY_ORDER]
        self._name_to_key = {PUZZLES[key].NAME: key for key in DISPLAY_ORDER}

        self._build_widgets()

    def _build_widgets(self):
        top = ttk.Frame(self.root, padding=10)
        top.pack(fill="x")
        self.select_btn = ttk.Button(top, text="選擇圖片...", command=self.on_select_image)
        self.select_btn.grid(row=0, column=0, padx=(0, 8))
        self.path_label = ttk.Label(top, text="尚未選擇圖片", foreground="#555")
        self.path_label.grid(row=0, column=1, sticky="w")

        opts = ttk.Frame(self.root, padding=(10, 0))
        opts.pack(fill="x")

        ttk.Label(opts, text="謎題類型:").grid(row=0, column=0, sticky="w")
        self.type_var = tk.StringVar(value=AUTO_LABEL)
        self.type_combo = ttk.Combobox(
            opts, textvariable=self.type_var, values=self._type_choices, state="readonly", width=22
        )
        self.type_combo.grid(row=0, column=1, sticky="w", padx=(6, 20))

        ttk.Label(opts, text="棋盤格數 (留空自動):").grid(row=0, column=2, sticky="w")
        self.grid_size_var = tk.StringVar(value="")
        ttk.Entry(opts, width=5, textvariable=self.grid_size_var).grid(row=0, column=3, sticky="w", padx=(6, 20))

        self.debug_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            opts, text="顯示辨識除錯圖", variable=self.debug_var, command=self.refresh_display
        ).grid(row=1, column=0, columnspan=3, sticky="w", pady=(6, 0))

        action = ttk.Frame(self.root, padding=10)
        action.pack(fill="x")
        self.solve_btn = ttk.Button(action, text="分析並求解", command=self.on_solve, state="disabled")
        self.solve_btn.pack(side="left")
        self.save_btn = ttk.Button(action, text="另存答案圖片...", command=self.on_save, state="disabled")
        self.save_btn.pack(side="left", padx=(8, 0))

        self.status_label = ttk.Label(self.root, text="", foreground="#0a6")
        self.status_label.pack(fill="x", padx=10)

        self.image_label = ttk.Label(self.root)
        self.image_label.pack(padx=10, pady=8)

        report_frame = ttk.Frame(self.root, padding=(10, 0, 10, 10))
        report_frame.pack(fill="both", expand=True)
        self.report_text = tk.Text(report_frame, height=14, wrap="none", font=("Consolas", 10))
        self.report_text.pack(fill="both", expand=True, side="left")
        scrollbar = ttk.Scrollbar(report_frame, command=self.report_text.yview)
        scrollbar.pack(side="right", fill="y")
        self.report_text["yscrollcommand"] = scrollbar.set

    def on_select_image(self):
        path = filedialog.askopenfilename(
            title="選擇謎題截圖",
            filetypes=[("圖片檔", "*.png *.jpg *.jpeg *.bmp *.webp"), ("所有檔案", "*.*")],
        )
        if not path:
            return
        self.image_path = Path(path)
        image = imread_unicode(self.image_path)
        if image is None:
            messagebox.showerror("錯誤", f"讀不到圖片:\n{self.image_path}")
            self.image_path = None
            return

        self.cv_image = image
        self.result = None
        self.path_label.config(text=self.image_path.name)
        self.solve_btn.config(state="normal")
        self.save_btn.config(state="disabled")
        self.report_text.delete("1.0", tk.END)
        self._show_cv_image(image)

        try:
            detected = detect_type(image)
            self.status_label.config(text=f"自動判斷為: {PUZZLES[detected].NAME}")
        except Exception:
            self.status_label.config(text="")

    def on_solve(self):
        if self.cv_image is None:
            return
        n_hint = None
        raw = self.grid_size_var.get().strip()
        if raw:
            try:
                n_hint = int(raw)
            except ValueError:
                messagebox.showerror("錯誤", "棋盤格數必須是整數")
                return

        chosen = self.type_var.get()
        puzzle_key = None if chosen == AUTO_LABEL else self._name_to_key[chosen]

        self.solve_btn.config(state="disabled")
        self.status_label.config(text="分析中... (Zip 這類路徑題可能需要數十秒)")
        self.root.update_idletasks()

        # Zip 的漢米頓路徑求解可能要跑好幾秒到數十秒，放到背景執行緒避免視窗凍結
        threading.Thread(target=self._solve_worker, args=(puzzle_key, n_hint), daemon=True).start()

    def _solve_worker(self, puzzle_key, n_hint):
        try:
            key = puzzle_key or detect_type(self.cv_image)
            module = PUZZLES[key]
            result = module.analyze(self.cv_image, n_hint=n_hint, debug=True)
            self.root.after(0, self._on_solved, key, result, None)
        except Exception:
            self.root.after(0, self._on_solved, None, None, traceback.format_exc())

    def _on_solved(self, key, result, error_text):
        self.solve_btn.config(state="normal")
        if error_text:
            self.status_label.config(text="")
            messagebox.showerror("發生未預期的錯誤", error_text.splitlines()[-1])
            print(error_text)
            return

        self.result = result
        self.solved_key = key
        self.status_label.config(text=f"謎題類型: {PUZZLES[key].NAME}")
        self._render_report(key, result)
        self.refresh_display()
        self.save_btn.config(state="normal" if result.ok and result.overlay_image is not None else "disabled")

    def refresh_display(self):
        if self.result is None:
            return
        if self.debug_var.get() and self.result.debug_image is not None:
            self._show_cv_image(self.result.debug_image)
        elif self.result.overlay_image is not None:
            self._show_cv_image(self.result.overlay_image)
        elif self.cv_image is not None:
            self._show_cv_image(self.cv_image)

    def _render_report(self, key, result):
        self.report_text.delete("1.0", tk.END)
        lines = [f"謎題類型: {PUZZLES[key].NAME}", ""]
        lines.extend(result.report_lines)
        if not result.ok:
            lines.append("")
            lines.append(result.error or "分析失敗")
            lines.append("")
            lines.append("提示：勾選「顯示辨識除錯圖」查看是哪裡辨識錯誤，")
            lines.append("或手動指定謎題類型 / 棋盤格數再試一次。")
        self.report_text.insert("1.0", "\n".join(lines))

    def _show_cv_image(self, cv_image):
        rgb = cv2.cvtColor(cv_image, cv2.COLOR_BGR2RGB)
        pil_img = Image.fromarray(rgb)
        w, h = pil_img.size
        scale = min(MAX_DISPLAY_SIZE / w, MAX_DISPLAY_SIZE / h, 1.0)
        if scale < 1.0:
            pil_img = pil_img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)
        self.tk_photo = ImageTk.PhotoImage(pil_img)
        self.image_label.config(image=self.tk_photo)

    def on_save(self):
        if not self.result or self.result.overlay_image is None:
            return
        default_name = (self.image_path.stem + "_solved.png") if self.image_path else "solved.png"
        path = filedialog.asksaveasfilename(
            title="另存答案圖片",
            initialfile=default_name,
            defaultextension=".png",
            filetypes=[("PNG 圖片", "*.png")],
        )
        if not path:
            return
        imwrite_unicode(path, self.result.overlay_image)
        messagebox.showinfo("已儲存", f"答案圖片已儲存至:\n{path}")


def main():
    if sys.platform == "win32":
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass
    root = tk.Tk()
    PuzzleSolverApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
