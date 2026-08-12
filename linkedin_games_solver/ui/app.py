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
    primary_monitor_size,
    verify,
    verify_supports,
    wait_for_board,
    wait_for_board_gone,
    wait_for_mouse_release,
)
from ..automation import board_watch
from ..core import action_log, read_image, write_image
from ..i18n import LANGUAGES, translator
from ..puzzles import (
    CANCELLED,
    DISPLAY_ORDER,
    MIN_BOARD_PIXELS,
    puzzle_name,
    render_overlay,
    solve_image,
    sudoku,
)
from . import settings as settings_store

#: Preview is deliberately small so the message area always has room, and so the
#: window stays compact enough to sit beside a browser while screen-recording.
#: 預覽圖刻意做小，確保訊息區一定有空間，也讓視窗夠精簡，錄影時能跟瀏覽器並排。
MAX_PREVIEW = 150
MOUSE_RELEASE_TIMEOUT = 2.0

#: How many solve attempts one detected board gets, each on a FRESH capture.
#: 一個偵測到的棋盤最多嘗試求解幾次，每一次都用「新擷取」的畫面。
#:
#: WHY 為什麼: a real session log (2026-08-06 19:47) showed the entrance
#: animation can still be settling when detection fires - that capture's
#: grid was genuinely unreadable and a single attempt failed the whole run,
#: while the same board solved fine seconds later. A failed first attempt
#: already costs seconds (the full ladder runs to exhaustion), so by the
#: time attempt 2 starts the animation is long finished - retrying on a
#: fresh frame turns "failed today" into "solved a few seconds later".
#: 3 bounds the cost when the board is REALLY unreadable (wrong zoom etc.).
#: 為什麼：真實執行記錄（2026-08-06 19:47）顯示，偵測觸發時進場動畫可能
#: 還沒完全結束——那一幀的格線真的讀不出來，單次嘗試就讓整輪失敗，
#: 但同一個棋盤幾秒後就能正常解出。第一次失敗本身就要花好幾秒（整條
#: 階梯會跑到耗盡），所以第二次嘗試開始時動畫早就結束了——用新的一幀
#: 重試，就把「今天解不了」變成「晚幾秒解出來」。上限 3 次是為了在棋盤
#: 「真的」讀不出來時（縮放不對等等）把成本鎖住。
MAX_SOLVE_ATTEMPTS = 3

#: Pause before re-capturing for a retry (seconds).
#: 重試前、重新擷取畫面之前的停頓（秒）。
#:
#: Only matters when the failed attempt was CHEAP (an immediate "board not
#: found" takes ~1-2s) - it gives the page that little bit longer to finish
#: rendering. After an expensive failure the animation is already long done
#: and this adds a negligible half second.
#: 只有在上一次失敗「很便宜」時才有意義（立刻「找不到棋盤」約 1~2 秒）——
#: 多給頁面一點時間把畫面畫完。在昂貴的失敗之後，動畫早就結束了，
#: 這半秒的影響可以忽略。
SOLVE_RETRY_DELAY = 0.5

#: Gap (pixels) between the parked cursor and the capture rectangle's edge -
#: also the corner fallback's offset from the literal screen corner.
#: 停放游標跟擷取矩形邊緣之間的間隔（像素）——同一個數字也用來當角落備案
#: 離「螢幕角落像素本身」的偏移量。
#:
#: WHY NOT 0 為什麼不是 0: pyautogui's FAILSAFE aborts the moment the cursor
#: sits on the LITERAL corner pixel (0,0) etc. - see input_driver.py's
#: module docstring. A cursor sitting exactly on the capture rectangle's own
#: edge is also a real (if smaller) risk: anti-aliasing at a cell boundary
#: could still tint the outermost row/column of cells. 5px clears both with
#: room to spare without meaningfully changing where "clear of the board"
#: means - see _park_mouse_clear_of_capture.
#: 為什麼不是 0：pyautogui 的 FAILSAFE 會在游標剛好停在角落那個像素本身
#: （(0,0) 等）時中止——見 input_driver.py 的模組文件字串。游標剛好停在
#: 擷取矩形自己的邊緣上也是一個（比較小的）真實風險：格子邊界的反鋸齒
#: 仍然可能染到最外圍那一列/欄的格子。5 像素兩邊都有餘裕地避開，
#: 也不會實質改變「離開棋盤」這件事的意思——見 _park_mouse_clear_of_capture。
PARK_MARGIN_PX = 5

#: Seconds to wait for the page to finish redrawing before the verify pass
#: recaptures the screen, per speed tier.
#: 驗證步驟重新擷取畫面之前，等網頁重畫完成的秒數，依速度檔各自設定。
#:
#: The original fixed 0.9s was chosen for the default speed. At the faster
#: tiers the page has already demonstrated it keeps up with much tighter
#: input timing, so the settle can shrink with the tier - UNVALIDATED like
#: the tiers themselves; the failure sign is a verify round reporting wrong
#: cells that a later round finds correct (the capture ran mid-redraw).
#: Queens is the one to watch: a mid-redraw frame could make it "clear" a
#: crown that was actually fine.
#: 原本固定的 0.9 秒是為預設速度選的。在較快的檔位，網頁已經證明跟得上
#: 更緊湊的輸入節奏，所以這個緩衝可以跟著檔位縮短——跟檔位本身一樣屬於
#: 未驗證；失敗徵兆是某一輪驗證回報有格子錯了、下一輪又發現是對的
#: （代表擷取撞上重畫中）。要特別盯 Queens：重畫中的畫面可能讓它把
#: 其實沒問題的皇冠「清掉」。
VERIFY_DELAYS = {"fastest": 0.5, "faster": 0.6, "fast": 0.8,
                 "normal": 0.9, "slow": 0.9, "slowest": 0.9}

#: Speed label -> InputDriver constructor arguments.
#: 速度選項 -> InputDriver 的建構參數。
#:
#: The four original tiers are a plain delay multiplier. The two new tiers
#: cannot be expressed as a multiplier: they override the per-delay BASE
#: values (and same_spot_gap does not scale with the multiplier at all), so
#: each profile is a full argument dict instead of one number.
#: 原本的四檔只是單一延遲倍率。新的兩檔沒辦法用倍率表達：它們直接覆寫
#: 各延遲的「基準值」（而且 same_spot_gap 本來就不隨倍率縮放），
#: 所以每一檔改成一整組建構參數，而不是一個數字。
#:
#: PULLED BACK 2026-08-08 拉回：the original "fastest" (settle 0.05 / click
#: gap 0.02 / same-spot 0.05 / drag step 0.004) was a candidate FLOOR, always
#: labelled unvalidated - real play confirmed the page cannot reliably keep
#: up at that pace ("滑鼠會跟不上"). Both fast tiers are now re-derived
#: from "fast" (the one tier that HAS run a full real sitting without this
#: complaint) by repeated averaging, so both sit much closer to it:
#:     new fastest = average(old faster, fast), value by value
#:     new faster  = average(new fastest, fast), value by value
#: This keeps the same four-value shape (settle / click gap / same-spot /
#: drag step) and the same ordering (fastest < faster < fast), just with a
#: far smaller gap from the tier that is known to work. Still unvalidated -
#: only "fast" itself has a real sitting behind it - but the floor no
#: longer assumes the page can keep up with near-zero delays.
#: 2026-08-08 拉回：原本的「超急快」（緩衝 0.05／點後 0.02／同格連點
#: 0.05／拖曳步 0.004）是候選下限，一直標著未驗證——真實遊玩證實網頁在
#: 那個節奏下真的跟不上（使用者回報「滑鼠會跟不上」）。現在把兩個快檔
#: 都改成從「快」（唯一真的跑過一整輪、沒被抱怨過的檔位）反覆取平均
#: 算出來，兩者都拉近很多：
#:     新超急快 = 平均(舊極快, 快)，逐項計算
#:     新極快   = 平均(新超急快, 快)，逐項計算
#: 維持一樣的四個參數（緩衝／點後間隔／同格連點／拖曳步）跟一樣的順序
#: （超急快 < 極快 < 快），只是離「已知能動」的檔位近了很多。仍然未經
#: 驗證——只有「快」自己真的跑過一整輪——但下限已經不再假設網頁能跟上
#: 趨近於零的延遲。
#:
#: RE-MEASURED after pulling back 拉回之後重新量測 (all five real fixtures,
#: stubbed mouse, real sleeps - five-game fill total 五題填答合計):
#:     normal   37.1s
#:     fast     21.3s
#:     faster   19.6s
#:     fastest  18.0s
#: The gap between the three fast tiers is now small on purpose - the point
#: was never squeezing out more seconds, it was never producing a tier the
#: page cannot follow.
#: 三個快檔之間的差距現在刻意變小——重點從來不是再擠出幾秒鐘，
#: 是不要再生出一個網頁跟不上的檔位。
SPEED_PROFILES = {
    "fastest": dict(slowdown=1.0, settle_after_move=0.1025, click_interval=0.05,
                    same_spot_gap=0.125, drag_step_delay=0.007),
    "faster": dict(slowdown=1.0, settle_after_move=0.1113, click_interval=0.055,
                   same_spot_gap=0.1375, drag_step_delay=0.0075),
    "fast": dict(slowdown=1.0),
    "normal": dict(slowdown=2.0),
    "slow": dict(slowdown=3.5),
    "slowest": dict(slowdown=5.0),
}
SPEED_KEYS = ["fastest", "faster", "fast", "normal", "slow", "slowest"]
#: Combo fallback when the saved speed is unknown - "normal", same as before.
#: 存檔的速度值無法辨識時的預設選項——跟以前一樣是「標準」。
DEFAULT_SPEED_INDEX = SPEED_KEYS.index("normal")


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
        self._stop_before_run = False
        self._worker_thread: threading.Thread | None = None
        self._minimized_for_wait = False
        self._last_failure_persistent = False
        self.image_path: Path | None = None
        self.tk_photo = None
        self.busy = False

        self.root.title(translator("app_title"))
        self.root.geometry("400x470")
        self.root.minsize(390, 350)
        self._build_widgets()
        self._apply_settings()

        # Open the session log now, before anything else can happen, and show
        # its path immediately - if the user is about to screen-record, the
        # path needs to be on screen from the very first frame, not appear
        # only after the first solve.
        # 現在就開啟這次執行的記錄檔，在任何其他事發生之前，並立刻顯示路徑——
        # 如果使用者正要開始錄影，這個路徑要從第一格畫面就在螢幕上，
        # 不能等到第一次求解完才出現。
        action_log.log("RUN", "GUI started")
        self._log(f"{translator('log_file')}: {action_log.path()}")

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
        self.speed_combo.current(SPEED_KEYS.index(speed) if speed in SPEED_KEYS
                                 else DEFAULT_SPEED_INDEX)

        self._retranslate()
        self._on_mode_changed()

    def _save_settings(self):
        # Only overwrite the stored region with a value the Entry fields
        # ACTUALLY contain. _save_settings runs automatically on language
        # change, mode change, and every Start press - not just an explicit
        # "save" action - so if a field is mid-edit or was typo'd, silently
        # falling back to _region()'s default-on-parse-failure behaviour
        # would permanently overwrite a calibrated region with a guess. Keep
        # whatever was saved before instead.
        # 只有在輸入框「真的」裝著一個有效值時，才覆蓋存起來的擷取範圍。
        # _save_settings 會在切換語言、切換模式、每次按開始時自動執行——
        # 不是只有明確按「儲存」才會跑——所以如果欄位正在編輯中或打錯字，
        # 沿用 _region() 那種「解析失敗就退回預設值」的行為，會把校準好的
        # 範圍永久覆蓋成一個猜的值。這裡改成維持原本存的那一份。
        update = {
            "speed": SPEED_KEYS[max(0, self.speed_combo.current())],
            "language": translator.language,
            "mode": self.mode_var.get(),
        }
        parsed = self._parsed_region()
        if parsed is not None:
            update["region"] = list(parsed)
            # Only re-stamp the screen size when the region VALUE itself
            # actually changed just now (Reset, Test, or an edited field) -
            # not on every call, since _save_settings also runs on every
            # Start press, language change, etc. with the region UNCHANGED.
            # WHY THIS MATTERS 為什麼這樣做很重要: if the stamp were
            # refreshed unconditionally, then the very first run after the
            # screen actually changed would correctly warn (see
            # _warn_if_resolution_changed) - but this same call would then
            # overwrite the stamp to the NEW screen size even though the
            # region's x/y/w/h were never actually recalibrated for it. The
            # warning would silently never fire again on later runs, even
            # though the capture rectangle is still wrong. Only stamping on
            # an actual value change keeps the warning firing on every run
            # until the user really does something about it.
            # 只有在這一次「範圍本身真的變了」才重新記錄螢幕尺寸——不是
            # 每次呼叫都記，因為 _save_settings 在按開始、切語言…等情況下
            # 也會被呼叫，但範圍根本沒變。為什麼這很重要：如果每次都無條件
            # 重新記錄，螢幕真的換了之後第一次執行會正確跳出警告（見
            # _warn_if_resolution_changed），但這同一次呼叫接著就會把記錄
            # 蓋成「新」螢幕尺寸——即使擷取範圍的 x/y/寬/高 根本沒有真的
            # 針對新螢幕重新校準過。這樣警告在之後每次執行都會安靜地不再
            # 出現，即使擷取範圍其實還是錯的。只在數值真的改變時才記錄，
            # 才能讓警告在使用者真的處理之前，每次執行都繼續出現。
            if list(parsed) != list(self.settings.get("region") or []):
                self.settings["region_monitor_size"] = list(primary_monitor_size() or []) or None
        self.settings.update(update)
        settings_store.save(self.settings)

    def _parsed_region(self) -> tuple[int, int, int, int] | None:
        """Strictly parse the Entry fields. None on anything invalid - no
        silent substitution. See _save_settings for why that matters.
        嚴格解析輸入框的內容。任何不合法的情況都回傳 None——不做任何靜默替換。
        原因見 _save_settings。"""
        try:
            left, top, width, height = (int(self.x_var.get()), int(self.y_var.get()),
                                         int(self.w_var.get()), int(self.h_var.get()))
        except ValueError:
            return None
        if width <= 0 or height <= 0:
            return None
        return left, top, width, height

    def _region(self) -> tuple[int, int, int, int]:
        """Best-effort region for actually capturing the screen - falls back
        to the default rather than fail, because a capture needs SOME region
        to try. Never used for deciding what to save; see _parsed_region.
        用來真正擷取螢幕的「盡力而為」範圍——解析失敗就退回預設值，
        因為擷取總得試一個範圍。絕不用來決定要存什麼；要存的邏輯在
        _parsed_region。"""
        return self._parsed_region() or default_region()

    def _warn_if_resolution_changed(self):
        """Log a warning (never blocking) if the primary monitor's size no
        longer matches what it was when the capture region was last
        calibrated.
        如果目前主螢幕的尺寸，跟上次校準擷取範圍時不一樣，記錄一個警告
        （絕不會擋住執行）。

        WHY THIS EXISTS 為什麼需要這個: the capture region is a fixed
        rectangle of absolute screen pixels, chosen once (Reset / Test / a
        manual edit) and then reused forever - nothing previously checked
        whether the screen it was chosen on is still the screen actually in
        use. Switching monitors, changing resolution, or changing Windows
        display scaling all silently invalidate it: the app keeps grabbing
        the same pixel rectangle, which may now contain the wrong part of
        the page (or the desktop), and the only symptom is a generic "board
        not found" with no hint why.
        為什麼需要這個：擷取範圍是一個固定的螢幕絕對像素矩形，只在某一刻
        被決定過（按預設／測範圍／手動改），之後就一直沿用——先前沒有任何
        地方會檢查「當初選這個範圍時的螢幕，跟現在用的還是不是同一個」。
        換螢幕、換解析度、改 Windows 顯示縮放比例，都會讓它悄悄失效：
        程式還是繼續抓同一塊像素矩形，裡面現在可能是頁面的錯誤部分（或
        桌面），唯一的症狀就是一句通用的「找不到棋盤」，完全看不出原因。

        WHY NOT BLOCKING 為什麼不擋住執行: the region might still happen to
        be correct (unlikely but not impossible), and fullscreen mode does
        not depend on it at all. Refusing to run would be a worse failure
        mode than today's "board not found" - this just tells the user WHY
        before they have to guess, it does not stop them from trying.
        為什麼不擋住執行：範圍還是有可能剛好還是對的（機率低但不是不可能），
        而全螢幕模式完全不依賴這件事。直接拒絕執行，會是比現在「找不到
        棋盤」更糟的失敗方式——這裡只是先告訴使用者「為什麼」，不需要自己
        用猜的，不會因此不讓他們嘗試。
        """
        saved = self.settings.get("region_monitor_size")
        if not (isinstance(saved, (list, tuple)) and len(saved) == 2):
            return
        try:
            saved_size = (int(saved[0]), int(saved[1]))
        except (TypeError, ValueError):
            return
        current_size = primary_monitor_size()
        if current_size is not None and current_size != saved_size:
            action_log.log("WARN", f"primary monitor size changed since the capture region "
                            f"was last calibrated: was {saved_size}, now {current_size}")
            self._log(translator("log_resolution_changed",
                                 old=f"{saved_size[0]}x{saved_size[1]}",
                                 new=f"{current_size[0]}x{current_size[1]}"))

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

    def _clear_stale_result(self):
        """Call this every time self.shot is replaced by a NEW image.
        每次 self.shot 被換成一張新的圖，就呼叫這個。

        WHY 為什麼: pick puzzle A, solve, pick puzzle B, press Save used to
        save A's answer drawn on B's screenshot, offered under B's filename,
        dialog saying "Saved" - because self.result/mapper/plan kept
        pointing at A. Save is this project's documented bug-report channel;
        this bug made that channel lie. Cleared atomically with self.shot so
        there is no window where they can point at different images.
        為什麼：選 A 題、解完、再選 B 題、按存圖，以前會把 A 的答案畫在
        B 的截圖上、用 B 的檔名存出去、對話框還顯示「已儲存」——因為
        self.result/mapper/plan 一直指著 A。存圖是這個專案文件寫明的
        bug 回報管道；這個 bug 讓那個管道說謊。跟 self.shot 一起原子性地
        清空，就不會有兩者指著不同圖片的空窗期。
        """
        self.result = None
        self.mapper = None
        self.plan = None

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
        self._clear_stale_result()
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
        self._clear_stale_result()
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
        # Set the flag FIRST, unconditionally - not just on self.driver - so
        # a Stop pressed while _capture() is still running (its root.update()
        # calls do pump the event queue, so this is reachable) is not lost.
        # self.driver at that moment is either None (first run) or the
        # PREVIOUS run's driver; a fresh InputDriver with _stop_requested
        # reset to False gets built right after _capture() returns, silently
        # discarding a stop aimed at the driver that does not exist yet.
        # 一定先設這個旗標，而且不只在 self.driver 存在時才設——因為
        # _capture() 還在跑的時候按停止是真的按得到的（它裡面的
        # root.update() 呼叫會抽出事件佇列）。那個當下 self.driver
        # 不是 None（第一次執行）就是「上一輪」的 driver；_capture() 一
        # 回傳，馬上會建一個全新、_stop_requested 重設成 False 的
        # InputDriver，把針對「還不存在的那個 driver」的停止要求悄悄丟掉。
        action_log.log("STOP", "user pressed Stop")
        self._stop_before_run = True
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
        # Always pass a starting folder. Without initialdir, Windows reuses
        # whatever folder a file dialog last opened - which could be anything.
        # 一定要指定起始資料夾。少了 initialdir，Windows 會沿用「上次檔案對話框
        # 開過的資料夾」，那可能是任何地方。
        path = filedialog.asksaveasfilename(
            title=translator("dlg_save_title"), defaultextension=".png",
            initialdir=str(settings_store.captures_dir()),
            initialfile=default_name, filetypes=[("PNG", "*.png")],
        )
        if not path:
            return
        # write_image now honours its documented bool contract (see its own
        # docstring), so a failure here is a real False, not an uncaught
        # exception - but the return value still has to be CHECKED, or a
        # failed save keeps showing "Saved" regardless.
        # write_image 現在真的遵守自己文件寫的布林值約定（見它自己的文件字串），
        # 所以這裡的失敗是真正的 False，不是沒接住的例外——但還是要「檢查」
        # 這個回傳值，不然存檔失敗照樣顯示「已儲存」。
        if write_image(Path(path), image):
            messagebox.showinfo(translator("dlg_saved"), path)
        else:
            messagebox.showerror(translator("dlg_save_failed"), path)

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

    def _keep_window_clear_of_capture(self):
        """Tk-thread only. Make sure this app's own window cannot land
        inside whatever screen region is about to be captured.
        只能在 Tk 執行緒呼叫。確保這個程式自己的視窗不會落在即將被擷取的
        螢幕範圍裡面。

        WHY THIS EXISTS 為什麼需要這個:
        A real session (2026-08-08) showed the app window sitting directly
        on top of a Mini Sudoku board's first column, for the rest of that
        session - confirmed by matching a saved diagnostic capture against
        the screen recording (92.9% correlation at the matching frame). The
        obscured column's given digits were never seen, the puzzle read as
        under-constrained, and every attempt correctly - but uselessly -
        failed with "solution not unique". The window hiding used to run
        ONCE, right before continuous mode's first wait began; the taskbar
        entry a minimised window keeps exists specifically so it CAN be
        restored (to reach Stop) - and once restored, nothing put it back
        out of the way for the rest of that multi-puzzle session.
        為什麼需要這個：一次真實執行（2026-08-08）顯示，這個程式自己的
        視窗整段時間都疊在 Mini Sudoku 棋盤的第一欄上——已經用存下的
        診斷畫面比對螢幕錄影確認過（在吻合的那一幀相關係數 92.9%）。
        被擋住的那一欄，原本印的數字從來沒被看到，題目就被讀成條件
        不足，之後每一次嘗試都「正確但沒用」地失敗在「解不唯一」。
        隱藏視窗以前只在連續模式第一次等待開始之前執行一次；最小化的
        視窗留著工作列入口，就是故意讓它「能」被還原（好去按停止）——
        一旦被還原，接下來整個多題的執行過程中，都沒有任何東西把它
        挪開過。

        Fullscreen capture has no safe position to move to - the capture IS
        the whole monitor - so it is hidden regardless of the hide-window
        setting. Otherwise: hide-window on -> iconify, exactly as before.
        Hide-window off -> the user wants to see it (2026-08-08's session
        was rapid manual speed-tier switching between rounds, which needs
        the window reachable), so it stays VISIBLE but gets moved beside
        the capture rectangle instead of forced to iconify.
        全螢幕擷取沒有安全的位置可以躲——擷取範圍就是整個螢幕——所以
        不管「隱藏視窗」有沒有勾都會強制隱藏。其他情況：勾了隱藏視窗
        跟以前一樣直接最小化。沒勾——2026-08-08 那次執行是在多輪之間
        快速手動切換速度檔，需要隨時碰得到視窗——所以維持「看得到」，
        但會被挪到擷取矩形旁邊，而不是強制最小化。
        """
        if self.settings.get("fullscreen"):
            if not self._minimized_for_wait:
                self.root.iconify()
                self._minimized_for_wait = True
            return
        if self.hide_var.get():
            if not self._minimized_for_wait:
                self.root.iconify()
                self._minimized_for_wait = True
            return
        try:
            left, top, w, h = self._region()
        except Exception:
            return
        self.root.update_idletasks()
        ww = self.root.winfo_width() or 400
        wh = self.root.winfo_height() or 470
        wx, wy = self.root.winfo_x(), self.root.winfo_y()
        overlaps = not (wx + ww <= left or wx >= left + w
                        or wy + wh <= top or wy >= top + h)
        if not overlaps:
            return
        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        if left + w + ww <= screen_w:
            new_x, new_y = left + w + 10, top
        elif top + h + wh <= screen_h:
            new_x, new_y = left, top + h + 10
        else:
            new_x, new_y = 0, 0
        self.root.geometry(f"+{new_x}+{new_y}")
        action_log.log("WARN", f"app window overlapped the capture region "
                        f"({left},{top},{w},{h}) - moved to ({new_x},{new_y})")

    def _park_mouse_clear_of_capture(self):
        """Tk-thread only. Move the OS mouse cursor outside the region about
        to be captured and analysed - see InputDriver.park's own docstring
        for the real 2026-08-12 Queens failure this guards against.
        只能在 Tk 執行緒呼叫。把滑鼠游標移到即將被擷取、分析的範圍之外——
        這裡在防的是哪一次真實的 2026-08-12 Queens 失敗，見
        InputDriver.park 自己的文件字串。

        Same "beside the capture rectangle, corner as last resort" logic as
        _keep_window_clear_of_capture, deliberately kept the same shape so
        the two do not silently disagree about what "clear" means - just
        landing a cursor point instead of fitting a whole window, and always
        moving (a resting cursor position is not knowable in advance the way
        the app's own window position is, so there is nothing to check
        first). The corner fallback is offset by PARK_MARGIN_PX, not (0,0) -
        pyautogui's FAILSAFE aborts on the LITERAL corner pixel, and parking
        there to avoid a hover tint would trade one failure mode for a worse
        one.
        跟 _keep_window_clear_of_capture 同一套「靠在擷取矩形旁邊，角落是
        最後手段」的邏輯，刻意維持同樣的形狀，這樣兩者才不會悄悄對「清空」
        這件事有不同的認定——差別只在這裡是放一個游標「點」，不是塞一整個
        視窗，而且永遠都會移動（游標目前停在哪裡沒辦法像這個程式自己的
        視窗位置那樣事先查得到，所以沒有東西可以先檢查）。角落備案偏移了
        PARK_MARGIN_PX，不是 (0,0)——pyautogui 的 FAILSAFE 是在「那個角落
        像素本身」中止，為了閃開 hover 卻真的停在那裡，等於拿一種失敗
        換一種更糟的。

        Fullscreen capture has no safe position - the capture IS the whole
        monitor - so this is a no-op there, same reasoning as
        _keep_window_clear_of_capture's own fullscreen branch.
        全螢幕擷取沒有安全的位置——擷取範圍就是整個螢幕——所以這裡在全螢幕
        模式下什麼都不做，跟 _keep_window_clear_of_capture 自己的全螢幕
        分支是同一個道理。
        """
        if self.settings.get("fullscreen"):
            return
        try:
            left, top, w, h = self._region()
        except Exception:
            return
        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        if left + w + PARK_MARGIN_PX <= screen_w:
            x, y = left + w + PARK_MARGIN_PX, top
        elif top + h + PARK_MARGIN_PX <= screen_h:
            x, y = left, top + h + PARK_MARGIN_PX
        else:
            x, y = PARK_MARGIN_PX, PARK_MARGIN_PX
        try:
            # This runs on the Tk thread (via _ui_wait), where an Aborted
            # raised here would surface through Tkinter's own callback-error
            # path instead of the worker thread's normal abort handling -
            # confusing, not dangerous. A Stop pressed in this narrow window
            # is caught a moment later anyway, by the next should_continue()
            # check on the actual worker thread, so swallowing it here just
            # skips this best-effort step rather than mishandling it.
            # 這裡是透過 _ui_wait 在 Tk 執行緒上跑的，在這裡拋出的 Aborted
            # 會走 Tkinter 自己的回呼例外路徑，不是工作執行緒正常的中止
            # 處理——會讓人困惑，但不危險。在這個很窄的時間點按下停止，
            # 稍後工作執行緒自己的下一次 should_continue() 檢查一樣會抓到，
            # 這裡吞掉它只是跳過這個「盡力而為」的步驟，不是處理不當。
            self.driver.park(x, y)
        except Aborted:
            pass

    def _alert_solve_failure(self):
        """Tk-thread only. Make a solve failure that has already exhausted
        its retries impossible to miss, even if the window is minimised or
        the user's attention is nowhere near the capture region.
        只能在 Tk 執行緒呼叫。讓一次已經用盡重試次數的辨識失敗不可能被
        忽略，就算視窗當時被最小化、或使用者的注意力根本不在擷取範圍那邊。

        WHY THIS EXISTS 為什麼需要這個: continuous mode used to leave a
        failed round completely silent - the status text changed, but with
        "hide window" checked that text is not on screen at all, and the
        loop would go on to wait_for_board_gone() for a board that (since
        the user has not navigated away from the failed puzzle) structurally
        never disappears - silently stuck, with no way to notice short of
        checking the log file. By the time _round() reports "failed" here,
        MAX_SOLVE_ATTEMPTS fresh-capture retries have already been
        exhausted, so this is a confirmed failure, not a single-frame
        fluke - there is no reason to wait for a second one before saying so.
        為什麼需要這個：連續模式以前對一輪失敗完全沒有反應——狀態文字換了，
        但勾了「隱藏視窗」時那段文字根本不在畫面上，迴圈接著會去等棋盤
        消失，而使用者根本沒有切走那個失敗的題目，棋盤在結構上永遠不會
        消失——安靜地卡住，使用者除了去看記錄檔沒有任何辦法發現。走到
        這裡代表 MAX_SOLVE_ATTEMPTS 次「重新擷取再試」已經用盡，是已經
        確認過的失敗，不是單一影格的偶發問題——沒有理由要等第二次才說。
        """
        if self._minimized_for_wait:
            self._minimized_for_wait = False
            self.root.deiconify()
        self.root.lift()
        # Best-effort only, same spirit as every other Windows-only call in
        # this file (focus_window_at, wait_for_mouse_release) - a machine or
        # audio setup where this fails must never break the alert's other,
        # more important half (the window coming back into view).
        # 盡力而為，跟這個檔案裡其他每個 Windows-only 呼叫一樣（
        # focus_window_at、wait_for_mouse_release）——這裡失敗絕不能連累
        # 提醒機制另一半更重要的部分（把視窗還原到看得到的地方）。
        try:
            import winsound
            winsound.MessageBeep(winsound.MB_ICONHAND)
        except Exception:
            pass
        self.status_label.config(text=translator("status_solve_failed_stopped"), foreground="#c00")
        self._log("")
        self._log(translator("log_solve_failed_alert", n=MAX_SOLVE_ATTEMPTS))
        if self._last_failure_persistent:
            self._log(translator("log_persistent_failure_hint", n=MAX_SOLVE_ATTEMPTS))

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
        self._stop_before_run = False
        self._clear_log()
        # Reset from whatever a previous run's repeated-failure alert left
        # behind (see _alert_solve_failure) - starting a new run is the
        # user acting on that alert, so it should not still be red.
        # 重設掉上一輪「連續失敗提醒」可能留下的樣式（見
        # _alert_solve_failure）——使用者按下開始，就代表已經在處理那個
        # 提醒了，不該還維持紅色。
        self.status_label.config(foreground="#0a6")
        self._log(f"{translator('log_file')}: {action_log.path()}")
        if self.mode_var.get() != "image" and not self.settings.get("fullscreen"):
            self._warn_if_resolution_changed()
        self.start_btn.config(state="disabled")
        self.solve_btn.config(state="disabled")
        self.stop_btn.config(state="normal")
        self.root.update_idletasks()

        # WAIT-FIRST MODE 先等題目模式: for the fill button in screen mode, the
        # button is now pressed BEFORE the puzzle page is opened - the worker
        # thread polls the screen and fires the instant a board appears, so
        # none of the user's page-switching reaction time is spent after the
        # puzzle has loaded. Solve-only and image mode keep the old immediate
        # capture: neither drives the mouse, so there is no race to win.
        # 先等題目模式：螢幕模式的「自動解題」按鈕，現在改成在「開啟題目之前」
        # 就按——工作執行緒會輪詢螢幕，棋盤一出現就立刻開始動作，題目載入
        # 之後不再花費任何使用者切換頁面的反應時間。「只求解」與圖片模式
        # 維持原本的立即擷取：它們都不動滑鼠，沒有要搶的時間。
        wait_first = fill_answers and not image_mode

        capture_fn = None
        if wait_first:
            # Snapshot the region ON THE TK THREAD, before the worker starts -
            # the region comes from tk.StringVar fields, and Tk objects must
            # not be read from another thread.
            # 在工作執行緒啟動之前、於 Tk 執行緒上先把擷取範圍拍板——範圍
            # 來自 tk.StringVar 欄位，Tk 的物件不能從別的執行緒讀取。
            if self.settings.get("fullscreen"):
                capture_fn = capture_screen
            else:
                region = self._region()
                capture_fn = lambda _r=region: capture_region(*_r)  # noqa: E731
            shot = None
            self.status_label.config(text=translator("status_waiting_board"))
            self._log(translator("log_waiting_hint"))
            # See _keep_window_clear_of_capture's own docstring for why this
            # is not just a one-time iconify() any more - re-asserted at the
            # start of every round in the continuous loop below, not only
            # here before round 1.
            # 為什麼這裡不再只是一次性的 iconify()，見
            # _keep_window_clear_of_capture 自己的文件字串——下面連續模式
            # 迴圈的每一輪開始都會重新確認一次，不是只有這裡、只在第一輪
            # 之前做一次。
            self._keep_window_clear_of_capture()
        else:
            self.status_label.config(text=translator("status_capturing"))
            self.root.update_idletasks()
            try:
                shot = self._capture()
            except Exception:
                self._finish(translator("dlg_capture_failed"))
                messagebox.showerror(translator("dlg_capture_failed"), traceback.format_exc().splitlines()[-1])
                return

            self.shot = shot
            self._clear_stale_result()
            self._show_image(shot.image)

            # Stop pressed during _capture() sets _stop_before_run rather than
            # self.driver (see _on_stop) precisely because no driver for THIS run
            # exists until the next line - honour it here before one gets built.
            # 在 _capture() 執行期間按下的停止，設的是 _stop_before_run 而不是
            # self.driver（見 _on_stop）——因為這一輪的 driver 要到下一行才會
            # 建出來。在它被建出來之前，這裡先尊重那個停止要求。
            if self._stop_before_run:
                self._finish(translator("status_stopped"))
                return

        index = self.type_combo.current()
        puzzle_key = None if index <= 0 else DISPLAY_ORDER[index - 1]
        speed_key = SPEED_KEYS[max(0, self.speed_combo.current())]
        self._verify_delay = VERIFY_DELAYS[speed_key]
        driver_kwargs = dict(dry_run=self.dry_run_var.get(), **SPEED_PROFILES[speed_key])
        self.driver = InputDriver(**driver_kwargs)
        self.driver.reset()
        action_log.log("RUN", f"run start: mode={self.mode_var.get()} puzzle={puzzle_key or 'auto'} "
                        f"fill={fill_answers} dry_run={self.dry_run_var.get()} speed={speed_key} "
                        f"wait_first={wait_first}")

        # Kept so the window-close handler can stop this run cleanly instead
        # of letting a daemon thread get killed mid-drag - see main()'s close
        # handler for what that leaves behind.
        # 留著這個參照，讓關閉視窗的處理常式可以乾淨地停止這次執行，
        # 而不是讓一個 daemon 執行緒在拖曳進行到一半時被砍掉——
        # 那樣會留下什麼，見 main() 的關閉處理常式。
        self._worker_thread = threading.Thread(
            target=self._worker, args=(shot, puzzle_key, fill_answers, capture_fn, driver_kwargs),
            daemon=True)
        self._worker_thread.start()

    def _worker(self, shot, puzzle_key, fill_answers, capture_fn=None, driver_kwargs=None):
        # SINGLE-SHOT: image mode and solve-only capture immediately in _run
        # and run exactly one round. CONTINUOUS: screen-mode fill loops
        # wait -> solve -> fill -> wait-for-gone until the user presses Stop,
        # so the button only ever needs pressing once per sitting - the user
        # reported forgetting to press it again before opening the next
        # puzzle, which cost more time than the feature saved.
        # 單發模式：圖片模式與「只求解」在 _run 就立刻擷取，只跑一輪。
        # 連續模式：螢幕模式的填答會循環「等待 -> 求解 -> 填答 -> 等棋盤
        # 消失」直到使用者按下停止——一輪五題只需要按一次按鈕。使用者
        # 回報過會忘記在開下一題之前再按一次，忘記的代價比這個功能省下
        # 的時間還多。
        if capture_fn is None:
            _outcome, text = self._round(shot, puzzle_key, fill_answers, None)
            self._ui(self._finish, text)
            return

        round_no = 0
        while not self._stop_before_run:
            round_no += 1
            if round_no > 1:
                # Fresh driver per round: a guard abort LATCHES the previous
                # round's stop flag by design (see _check_abort), and in
                # continuous mode "the board changed" usually just means the
                # completion screen arrived - the next round must not
                # inherit that latch.
                # 每一輪用全新的 driver：守衛中止會刻意鎖死上一輪的停止旗標
                # （見 _check_abort），而在連續模式裡「盤面已改變」通常只是
                # 完成畫面出現了——下一輪不能繼承那個鎖。
                self.driver = InputDriver(**driver_kwargs)
                self.driver.reset()
                self._ui(self._log, "")
                self._ui(self._log, f"=== {translator('log_round', n=round_no)} ===")
                action_log.log("RUN", f"continuous round {round_no} start")

            def alive():
                return not self._stop_before_run and not self.driver.stop_requested

            # Re-assert before EVERY round, not just round 1 - the taskbar
            # entry a hidden window keeps exists precisely so it CAN be
            # restored (to reach Stop), and this is what puts it back out of
            # the capture's way before the next puzzle is polled for.
            # 每一輪都重新確認，不是只有第一輪——隱藏的視窗留著工作列入口，
            # 就是故意讓它「能」被還原（好去按停止），這一步就是負責在
            # 下一題開始輪詢之前，把它挪回不會擋到擷取的地方。
            self._ui_wait(self._keep_window_clear_of_capture)
            self._ui(self.status_label.config, {"text": translator("status_waiting_board")})
            t0 = time.perf_counter()
            shot = wait_for_board(capture_fn, should_continue=alive)
            if shot is None:
                break
            outcome, text = self._round(shot, puzzle_key, fill_answers, capture_fn,
                                        wait_time=time.perf_counter() - t0)
            if outcome == "stop":
                self._ui(self._finish, text)
                return
            if outcome == "failed":
                # Alert and stop rather than looping on to wait_for_board_gone()
                # for a board that - since nothing here made the user navigate
                # away from it - structurally never disappears on its own. See
                # _alert_solve_failure's own docstring for the full reasoning.
                # 提醒並停止，而不是繼續迴圈去等棋盤消失——因為這裡沒有任何
                # 動作讓使用者切離那個失敗的題目，棋盤在結構上不會自己消失。
                # 完整理由見 _alert_solve_failure 自己的文件字串。
                action_log.log("WARN", "continuous mode: solve failed after all retries "
                                "- alerting and stopping")
                self._ui_wait(self._alert_solve_failure)
                self._ui(self._finish, translator("status_solve_failed_stopped"))
                return
            if self.driver.dry_run:
                # A continuous PREVIEW would wait forever for a board that
                # nothing ever fills in - preview runs one round and stops.
                # 連續「預演」會永遠等一個沒有人會去填的棋盤——
                # 預演只跑一輪就結束。
                self._ui(self._finish, text)
                return
            self._ui(self.status_label.config, {"text": translator("status_waiting_next")})
            if not wait_for_board_gone(capture_fn, should_continue=alive):
                break
        self._ui(self._finish, translator("status_stopped"))

    def _round(self, shot, puzzle_key, fill_answers, capture_fn, wait_time=None):
        """One full solve-and-fill round. Returns (outcome, status_text) where
        outcome is "done", "failed", "guard" or "stop" - only "stop" means the
        user (or an emergency) asked for everything to end.
        完整的一輪求解填答。回傳 (結果, 狀態文字)，結果是 "done"、"failed"、
        "guard" 或 "stop"——只有 "stop" 代表使用者（或緊急機制）要求全部結束。
        """
        timings: dict[str, float] = {}
        started = time.perf_counter()
        if capture_fn is not None:
            # Move the mouse off the board before the capture solve_image
            # will actually read colours from, then re-capture - the frame
            # `shot` arrived with may still have the cursor sitting on the
            # board (it was taken by wait_for_board's own poll, before this
            # round ever ran). See _park_mouse_clear_of_capture's own
            # docstring for why this matters.
            # 在 solve_image 真正要讀顏色的那次擷取之前，先把滑鼠移出棋盤，
            # 再重新擷取一次——傳進來的 `shot` 有可能游標還停在棋盤上
            # （它是 wait_for_board 自己輪詢時拍的，比這一輪還早）。
            # 為什麼要這樣做，見 _park_mouse_clear_of_capture 自己的文件字串。
            self._ui_wait(self._park_mouse_clear_of_capture)
            shot = capture_fn()
        self.shot = shot
        self._clear_stale_result()
        self._ui(self._show_image, shot.image)
        if wait_time is not None:
            timings["wait"] = wait_time
            self._ui(self._log, f"{translator('log_board_appeared')}: {wait_time:.2f}s")
        try:
            self._ui(self.status_label.config, {"text": translator("status_solving")})
            t0 = time.perf_counter()
            # Retry failed recognition on a FRESH capture - see
            # MAX_SOLVE_ATTEMPTS for the real failure this recovers from.
            # 辨識失敗時用「新擷取」的畫面重試——這救的是哪個真實失敗，
            # 見 MAX_SOLVE_ATTEMPTS。
            # Collects the first line of every FAILED attempt's error, across
            # fresh captures - used below to tell a transient failure (an
            # animation still settling, where a fresh frame plausibly differs)
            # apart from a persistent one (the exact same reading every time,
            # which a fresh capture of otherwise-static content cannot fix).
            # 收集每一次「失敗」嘗試的錯誤訊息第一行——每次都是新擷取的畫面。
            # 下面用它來分辨「暫時性失敗」（動畫還沒播完，新的一幀有機會不同）
            # 跟「持續性失敗」（每次都讀到完全一樣的結果，對著沒有變化的靜態
            # 內容重新擷取解決不了這種問題）。
            attempt_errors: list[str] = []
            for attempt in range(1, MAX_SOLVE_ATTEMPTS + 1):
                result = solve_image(
                    shot.image, puzzle_key=puzzle_key,
                    should_continue=lambda: not self.driver.stop_requested
                                            and not self._stop_before_run)
                if not result.ok and result.error != CANCELLED:
                    attempt_errors.append(str(result.error).splitlines()[0])
                if result.ok or result.error == CANCELLED or capture_fn is None \
                        or attempt == MAX_SOLVE_ATTEMPTS:
                    break
                self._ui(self._log, f"  {translator('log_solve_retry')} "
                                    f"({attempt}/{MAX_SOLVE_ATTEMPTS})")
                action_log.log("SOLVE", f"retrying with a fresh capture "
                                f"(attempt {attempt} failed: "
                                f"{str(result.error).splitlines()[0]})")
                time.sleep(SOLVE_RETRY_DELAY)
                shot = capture_fn()
                self.shot = shot
                self._ui(self._show_image, shot.image)
            timings["solve"] = time.perf_counter() - t0
            self._ui(self._show_timings, timings, started)
            self.result = result
            # Only meaningful with >= 2 genuinely fresh attempts (single-shot
            # solve-only / image mode never retries at all - capture_fn is
            # None there, see the break condition above - so this stays False
            # for them by construction).
            # 只有在真的有 >= 2 次「新擷取」的嘗試時才有意義（只求解／圖片
            # 模式從不重試——capture_fn 在那裡是 None，見上面的 break 條件——
            # 所以這兩種模式下這裡結構上一定是 False）。
            self._last_failure_persistent = (
                not result.ok and result.error != CANCELLED
                and len(attempt_errors) >= 2 and len(set(attempt_errors)) == 1
            )

            name = puzzle_name(result.puzzle_key, translator.language)
            self._ui(self._log, f"{translator('log_puzzle_type')}: {name}")
            for line in result.info:
                self._ui(self._log, f"  {line}")

            if not result.ok:
                if result.error == CANCELLED:
                    return "stop", translator("status_stopped")
                reason = result.error or translator("status_failed")
                self._ui(self._log, "")
                self._ui(self._log, reason)
                # Save the last attempted capture so a failure that cannot be
                # reproduced live still leaves real pixels to diagnose against -
                # the same idea as the guard's boardwatch_stop save, applied to
                # a full recognition failure instead of a mid-fill abort.
                # WHY THIS EXISTS: a 2026-08-10 Patches failure ("28 label(s)
                # unreadable ... tiling is ambiguous", every crop/scale tried)
                # could not be root-caused afterwards because nothing had kept
                # the actual bytes the recogniser saw - a hand screenshot taken
                # around the same time solved cleanly, so it was not the same
                # capture. Saving here closes that gap for next time.
                # 存下最後一次嘗試用的擷取畫面，讓「事後重現不出來」的失敗
                # 還是留得下真實像素可以追——跟守衛的 boardwatch_stop 存檔
                # 同一個想法，套用在「整個辨識都失敗」而不是「填答中途中止」。
                # 為什麼需要這個：2026-08-10 有一次 Patches 失敗（「28 個標籤
                # 讀不出來…切法不唯一」，裁切／縮放試遍都一樣）事後完全查不出
                # 根因，因為沒有任何東西留住辨識器當時實際看到的那些位元組——
                # 差不多同時間手動截的圖卻能乾淨解出來，代表根本不是同一張
                # 擷取畫面。這裡存檔就是為了補上這個缺口，下一次失敗時用得上。
                try:
                    fail_path = (settings_store.captures_dir()
                                 / f"solve_failed_{result.puzzle_key}_{int(time.time() * 1000)}.png")
                    if write_image(str(fail_path), shot.image):
                        self._ui(self._log, f"  {translator('log_solve_failed_frame_saved')}: {fail_path}")
                except Exception:
                    pass
                if self._last_failure_persistent:
                    # All MAX_SOLVE_ATTEMPTS fresh captures gave the exact
                    # same reading - see attempt_errors above. Worth saying
                    # explicitly, so the user is not left assuming "try
                    # again" is the fix when it already was tried, silently,
                    # 3 times.
                    # MAX_SOLVE_ATTEMPTS 次新擷取全部讀到一模一樣的結果——
                    # 見上面的 attempt_errors。值得明講出來，不然使用者會
                    # 以為「再試一次」有機會解決，但其實已經在背後默默試過
                    # 3 次了。
                    self._ui(self._log, translator("log_persistent_failure_hint",
                                                    n=MAX_SOLVE_ATTEMPTS))
                self._ui(self._log, "")
                self._ui(self._log, translator("log_fail_hint"))
                return "failed", f"{translator('status_failed')}: {reason.splitlines()[0]}"

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
                return "done", translator("status_solved_only")

            driver = self.driver
            self.watch = None
            if not driver.dry_run:
                # Attach the mid-plan board guard. Only for a real run: a dry run
                # clicks nothing, so watching the screen would just cost captures.
                # 掛上填答進行中的盤面保護。只在真的執行時掛：預演不會點任何東西，
                # 監看螢幕只會白白花擷取的成本。
                #
                # arm() proves the locator can find the board in the plan's OWN
                # frame. If it cannot, that is a configuration fault rather than
                # "board gone", so we log it and leave the guard off - filling
                # still works and the post-plan verify() still runs. Letting an
                # unproven locator judge would abort before the first click.
                # arm() 會證明定位器能在「計畫自己的那一幀」找到棋盤。找不到的話
                # 那是設定問題而不是「棋盤不見了」，所以只記錄、不掛保護 ——
                # 填答照常運作，事後的 verify() 也照常。讓一個沒被驗證過的定位器
                # 去下判斷，會在第一次點擊之前就中止。
                #
                # Shared with ui/cli.py's --go path via board_watch.attach() -
                # see that function's own docstring for why this must not be
                # written out inline per caller.
                # 跟 ui/cli.py 的 --go 路徑共用 board_watch.attach()——
                # 為什麼這段不能每個呼叫端各寫一份，見那個函式自己的文件字串。
                watch = board_watch.attach(driver, self.mapper, result, shot.image)
                self.watch = watch if watch.armed else None
                if not watch.armed:
                    self._ui(self._log, f"  {watch.reason}")

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
            return "done", (translator("status_preview_done") if driver.dry_run
                            else translator("status_done"))

        except Aborted:
            # Say WHY. "Stopped" alone leaves the user guessing whether they hit
            # Stop, whether it failed, or whether it protected them.
            # 說明原因。只寫「已中止」會讓使用者搞不清楚是自己按了停止、
            # 是失敗了、還是它保護了自己。
            action_log.log("ERROR", f"plan aborted: stopped_by_guard="
                            f"{getattr(self.driver, 'stopped_by_guard', False)}")
            guard_stopped = (getattr(self.driver, "stopped_by_guard", False)
                             and not self._stop_before_run)
            if guard_stopped:
                reason = getattr(self.watch, "reason", "") or translator("log_board_changed")
                self._ui(self._log, f"  {reason}")
                # Save the exact frame the guard rejected. Without this, a real
                # abort and a false-positive one look identical in the log -
                # both just say "board changed". The saved frame lets it be
                # checked afterwards instead of guessed at.
                # 存下守衛判定失敗的那張畫面。少了這個，真正的中止和誤判在
                # 記錄裡看起來完全一樣——都只寫「盤面已改變」。留住那張畫面，
                # 事後才能檢查而不是用猜的。
                frame = getattr(self.watch, "last_image", None)
                if frame is not None:
                    # A diagnostic save must never break the abort-handling path
                    # itself, so failures here are swallowed even though
                    # write_image now honours its documented bool contract -
                    # this guards against something UNEXPECTED going wrong in
                    # this specific best-effort save, not against write_image
                    # itself misbehaving.
                    # 診斷用的存檔絕不能弄壞中止流程本身，所以這裡失敗就吞掉——
                    # 即使 write_image 現在已經遵守自己文件寫的布林值約定，
                    # 這裡防的是「這次盡力而為的存檔本身出了預期外的狀況」，
                    # 不是防 write_image 自己行為不對。
                    try:
                        path = (settings_store.captures_dir()
                                 / f"boardwatch_stop_{int(time.time() * 1000)}.png")
                        if write_image(str(path), frame):
                            self._ui(self._log, f"  {translator('log_guard_frame_saved')}: {path}")
                    except Exception:
                        pass
                # In continuous mode a guard abort usually IS the happy path:
                # the completion screen replaced the board mid-fill. "guard"
                # lets the loop continue to the next puzzle instead of ending
                # the whole sitting.
                # 連續模式下，守衛中止通常「就是」正常流程：填答中途完成
                # 畫面把棋盤換掉了。回傳 "guard" 讓迴圈繼續等下一題，
                # 而不是結束整輪。
                return "guard", translator("status_stopped")
            return "stop", translator("status_stopped")
        except Exception as exc:
            # pyautogui's FAILSAFE (slam the mouse into a corner to abort) is a
            # DOCUMENTED escape hatch, not a bug - but it raises, and used to
            # fall straight into the generic branch below, printing a full raw
            # traceback with the word "Error" in the log. That makes the
            # intended emergency stop look exactly like a crash. Checked by
            # class NAME rather than importing pyautogui here, which would
            # break "image mode needs no screen packages" - by the time this
            # runs, dry_run is False and the driver has already imported it.
            # pyautogui 的 FAILSAFE（把滑鼠甩到角落即中止）是文件裡寫明的緊急
            # 逃生口，不是 bug——但它是用拋例外實作的，以前會直接落進下面
            # 那個通用分支，在記錄欄印出一整段原始 traceback、還帶著
            # 「Error」字樣，讓刻意的緊急停止看起來完全像當機。這裡用類別
            # 「名稱」判斷而不是在這裡 import pyautogui——那樣會破壞「圖片
            # 模式不需要螢幕相關套件」——執行到這裡代表 dry_run 已經是
            # False，driver 早就匯入過它了。
            if type(exc).__name__ == "FailSafeException":
                action_log.log("ERROR", "pyautogui FAILSAFE triggered - emergency stop")
                self._ui(self._log, translator("log_failsafe"))
                return "stop", translator("status_stopped")
            # An unknown exception ends the whole run, continuous or not -
            # looping on after an unexplained failure would repeat it blindly.
            # 不明的例外會結束整個執行，連續模式也一樣——在無法解釋的失敗
            # 之後繼續迴圈，只是盲目地重複它。
            action_log.log("ERROR", traceback.format_exc())
            self._ui(self._log, traceback.format_exc())
            return "stop", translator("status_error")

    def _harvest_calibration_candidates(self, image, report):
        """Save real evidence for cells we filled ourselves that the
        recogniser could not confidently read back - candidates for
        tools/calibrate_digits.py, never fed to it automatically.
        把我們自己填進去、但辨識器讀不回來的格子存成真實證據——留給
        tools/calibrate_digits.py 用的候選資料，絕不自動餵給它。

        ONLY Sudoku, and ONLY got=None mismatches 只限數獨、只限 got=None
        --------------------------------------------------------------
        A mismatch has three shapes, and only one is safe to harvest from:
          - got == want: not a mismatch at all, never reaches here
          - got is a WRONG digit (read confidently, just not what we filled):
            the ground truth here is suspect - it could be a genuine misread,
            but it could just as easily mean the click never registered and
            some OTHER digit is really on screen. Harvesting this would risk
            labelling a glyph with the WRONG answer, which is worse than not
            harvesting at all.
          - got is None (nothing read with enough confidence): we filled
            this cell ourselves - `want` is exactly the digit our own solver
            chose and the driver clicked/typed, not something read off the
            screen. That is the same standard of ground truth
            tools/calibrate_digits.py's hand-verified tables already use.
        一個不符合的格子有三種可能，只有一種能安全拿來收集：
          - got == want：根本不算不符合，不會走到這裡
          - got 是個「讀對了但錯的」數字：這裡的真值本身可疑——可能真的是
            誤讀，但也同樣可能是點擊根本沒生效、畫面上其實是另一個數字。
            拿這種資料去標記字形，有可能標成錯的答案，比完全不收集更糟。
          - got 是 None（沒有任何讀法有足夠信心）：這格是我們自己填的——
            `want` 就是我們自己的求解器選中、driver 親自點擊/打字打上去的
            那個數字，不是從螢幕上讀出來的。這跟 tools/calibrate_digits.py
            人工核對過的真值表，是同一個等級的可信度。

        Only the FIRST verify round of a puzzle, never a retry round -
        build_retry_plan re-clicks a got=None cell with the SAME digit, so a
        retry round very likely reproduces the identical unreadable glyph on
        an already-saved board; harvesting every round would just pile up
        near-duplicate files for one real occurrence.
        只在一次填答的「第一輪」驗證做，不是補點之後的輪次——
        build_retry_plan 對 got=None 的格子是用同一個數字重新點一次，
        補點輪很可能重現同一個已經存過的、讀不出來的字形；每輪都收集
        只會為同一次真實情況疊出一堆幾乎重複的檔案。

        Never fed into digit_templates.py by this function or by anything it
        calls - only tools/calibrate_digits.py does that, and only when a
        human deliberately runs it after looking at what got saved here. See
        this project's core rule: no threshold or template changes without
        looking at real evidence first.
        這個函式跟它呼叫的任何東西都絕不會直接寫進 digit_templates.py——
        只有 tools/calibrate_digits.py 會做這件事，而且只在有人看過這裡
        存下的東西之後、刻意手動執行它才會發生。見本專案的核心規則：
        沒有先看過真實證據，不能改動任何門檻或範本。
        """
        if report.board_changed or self.result is None or self.result.puzzle_key != sudoku.KEY:
            return
        unread = [(r, c, want) for (r, c, got, want) in report.mismatches if got is None]
        if not unread:
            return
        try:
            folder = settings_store.calibration_candidates_dir()
            path = folder / f"sudoku_unread_{int(time.time() * 1000)}.png"
            if not write_image(str(path), image):
                return
        except Exception:
            # Best-effort only - a failed diagnostic save must never break
            # the verify/retry flow that is already in progress.
            # 盡力而為——診斷用的存檔失敗絕不能弄壞正在進行中的驗證/補點流程。
            return
        cells = ", ".join(f"({r},{c})={want}" for r, c, want in unread)
        action_log.log("CALIBRATE", f"saved a digit-calibration candidate: cell(s) we "
                        f"filled ourselves but could not read back confidently "
                        f"({cells}) -> {path}")
        self._ui(self._log, f"  {translator('log_calibration_candidate_saved', n=len(unread))}")

    def _verify_and_retry(self, driver, max_rounds: int = 3):
        """Re-capture, compare, and re-click only what is still wrong.
        重新擷取、比對，只補還沒填對的格子。"""
        # Ask BEFORE the redraw sleep and the capture whether this puzzle can
        # be verified at all - see verify.supports for the measured waste
        # this skips (~0.95s per Zip/Patches round doing nothing).
        # 在「等重畫」與「擷取」之前先問這款謎題到底能不能驗證——這裡跳過
        # 的實測浪費（Zip/Patches 每輪白花約 0.95 秒）見 verify.supports。
        if not verify_supports(self.result.puzzle_key):
            action_log.log("VERIFY", f"{self.result.puzzle_key}: not supported, "
                            f"skipped without the redraw wait")
            self._ui(self._log, f"[{translator('log_check_round')} 1] "
                                f"{self.result.puzzle_key}: cannot verify / 無法驗證，直接略過")
            return
        previous_wrong = None
        for attempt in range(1, max_rounds + 1):
            action_log.log("VERIFY", f"GUI check round {attempt}/{max_rounds} starting")
            # let the page finish redrawing; tier-dependent, see VERIFY_DELAYS
            # 等網頁畫面更新完；依速度檔而定，見 VERIFY_DELAYS
            time.sleep(getattr(self, "_verify_delay", 0.9))
            fresh = capture_screen() if self.settings.get("fullscreen") else capture_region(*self._region())
            report = verify(fresh.image, self.result)
            self._ui(self._log, f"[{translator('log_check_round')} {attempt}] {report.summary()}")
            if attempt == 1:
                # Only the FIRST round - see _harvest_calibration_candidates's
                # own docstring for why a retry round is the wrong place to
                # look for this.
                # 只在「第一輪」做——為什麼補點之後的輪次不適合看這件事，
                # 見 _harvest_calibration_candidates 自己的文件字串。
                self._harvest_calibration_candidates(fresh.image, report)

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
        # Restore the window minimised for a wait-first run, whatever way the
        # run ended (done / stopped / failed) - _finish is the one place every
        # path already goes through, so the window can never stay stuck in
        # the taskbar.
        # 把先等題目模式最小化的視窗還原，不管這次執行是怎麼結束的
        # （完成／停止／失敗）——所有路徑本來就都會經過 _finish，
        # 所以視窗絕不會卡在工作列回不來。
        if self._minimized_for_wait:
            self._minimized_for_wait = False
            self.root.deiconify()
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
        從工作執行緒把畫面更新排回 Tk 主執行緒。

        Swallows the error from a root that is already destroyed. The window
        can close while the worker thread is still mid-plan - closing joins
        the thread with a timeout (see main()'s close handler), but does not
        guarantee the worker has stopped queuing UI updates before that
        timeout elapses, and root.after() on a destroyed root raises.
        接住「root 已經被銷毀」的錯誤。視窗可以在工作執行緒還在填答途中時
        關閉——關閉的處理常式會帶著逾時去 join 這個執行緒（見 main() 的
        關閉處理常式），但不保證在逾時之前，工作執行緒就已經停止排入畫面
        更新——對已銷毀的 root 呼叫 root.after() 會拋例外。
        """
        try:
            self.root.after(0, lambda: func(*args))
        except (RuntimeError, tk.TclError):
            pass

    def _ui_wait(self, func, timeout: float = 1.0):
        """Like _ui(), but blocks the calling (worker) thread until func has
        actually RUN on the Tk thread, or timeout elapses.
        跟 _ui() 類似，但會擋住呼叫端（工作）執行緒，直到 func 真的在
        Tk 執行緒上跑完，或逾時。

        _ui() alone only guarantees the update is queued, not that it has
        happened yet - fine for a log line, wrong for
        _keep_window_clear_of_capture: the very next line starts polling
        the screen, and the window has to have actually moved (or iconified)
        by then, not merely been asked to.
        單獨用 _ui() 只保證更新「已經排進佇列」，不保證它已經發生——
        對記錄一行文字沒差，但對 _keep_window_clear_of_capture 不行：
        下一行馬上就要開始輪詢螢幕，視窗必須「已經」被移開（或最小化），
        不能只是「已經被要求」移開。
        """
        done = threading.Event()

        def _wrapped():
            try:
                func()
            finally:
                done.set()

        try:
            self.root.after(0, _wrapped)
        except (RuntimeError, tk.TclError):
            return
        done.wait(timeout)

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


#: How long to wait for the worker thread to notice a stop request and
#: release the mouse before closing anyway.
#: 關閉視窗前，最多等工作執行緒發現停止要求、放開滑鼠鍵多久。
#:
#: WHY 為什麼: the worker thread is a daemon, and WM_DELETE_WINDOW used to
#: just call root.destroy() - once mainloop() returns and the process exits,
#: every daemon thread is killed outright, wherever it happens to be. Traced
#: with a fake pyautogui: MOUSE_DOWN 1, MOUSE_UP 0 - drag_path's own
#: `finally: mouseUp()` never got to run, because the thread was already
#: dead by the time it would have. driver.stop() makes _check_abort() raise
#: on the drag loop's NEXT step (drag_step_delay defaults to 8ms, so this is
#: normally near-instant); the timeout below is what actually gives that
#: step a chance to happen before the window closes anyway.
#: 為什麼：工作執行緒是 daemon，WM_DELETE_WINDOW 以前只會呼叫
#: root.destroy()——mainloop() 一返回、行程一結束，每個 daemon 執行緒
#:不管當下在做什麼，都會直接被砍掉。用假的 pyautogui 追蹤過：
#: MOUSE_DOWN 1、MOUSE_UP 0——drag_path 自己 `finally: mouseUp()` 從來沒
#:機會執行，因為輪到它的時候執行緒早就死了。driver.stop() 會讓
#: _check_abort() 在拖曳迴圈「下一步」拋出（drag_step_delay 預設 8 毫秒，
#: 所以正常情況幾乎是立即發生）；下面這個逾時給的就是讓那一步真的有機會
#: 發生的時間，視窗才不會在那之前就關掉。
CLOSE_JOIN_TIMEOUT = 2.0


def main():
    if sys.platform == "win32":
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass
    root = tk.Tk()
    app = SolverApp(root)

    def on_close():
        action_log.log("RUN", "window closing")
        if app.driver:
            app.driver.stop()
        thread = app._worker_thread
        if thread and thread.is_alive():
            thread.join(timeout=CLOSE_JOIN_TIMEOUT)
        app._save_settings()
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", on_close)
    root.mainloop()
