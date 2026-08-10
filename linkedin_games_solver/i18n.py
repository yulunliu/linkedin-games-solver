"""
Bilingual UI text (English / Traditional Chinese).
雙語介面文字（英文／繁體中文）。

Why a flat dict instead of gettext / .po files:
  the app ships as a single-file executable, so avoiding external catalogue
  files keeps packaging trivial. There are only ~80 strings, so a plain
  dictionary is easier to review than a translation toolchain.
為什麼用單純的字典而不是 gettext / .po 檔：
  這個程式會打包成單一執行檔，不依賴外部語言檔可以讓打包簡單很多。
  而且總共只有約 80 條字串，用字典比整套翻譯工具鏈更好檢視。
"""

from __future__ import annotations

# Supported languages. The key is stored in the settings file.
# 支援的語言。這個 key 會被存進設定檔。
LANGUAGES = {"en": "English", "zh": "中文"}
DEFAULT_LANGUAGE = "zh"

# Every UI string lives here as {key: {lang: text}}.
# 所有介面字串都放在這裡，格式為 {鍵: {語言: 文字}}。
_TEXTS: dict[str, dict[str, str]] = {
    # ---- Window / general 視窗與通用 ----
    "app_title": {"en": "LinkedIn Games Solver", "zh": "LinkedIn 謎題自動求解"},
    "language": {"en": "Language", "zh": "語言"},
    "mode": {"en": "Mode", "zh": "模式"},
    "mode_screen": {"en": "Screen (auto-play)", "zh": "螢幕（自動填答）"},
    "mode_image": {"en": "Image file", "zh": "圖片檔"},
    # ---- Board region 棋盤範圍 ----
    "board_pos": {"en": "Board", "zh": "棋盤位置"},
    "reset": {"en": "Reset", "zh": "預設"},
    "test_region": {"en": "Test", "zh": "測範圍"},
    "pick_image": {"en": "Choose image...", "zh": "選擇圖片..."},
    "no_image": {"en": "No image selected", "zh": "尚未選擇圖片"},
    # ---- Options 選項 ----
    "puzzle_type": {"en": "Puzzle", "zh": "謎題類型"},
    "auto_detect": {"en": "Auto-detect", "zh": "自動判斷"},
    "speed": {"en": "Speed", "zh": "速度"},
    "speed_fastest": {"en": "Fastest", "zh": "超急快"},
    "speed_faster": {"en": "Faster", "zh": "極快"},
    "speed_fast": {"en": "Fast", "zh": "快"},
    "speed_normal": {"en": "Normal", "zh": "標準"},
    "speed_slow": {"en": "Slow", "zh": "慢"},
    "speed_slowest": {"en": "Slowest", "zh": "最慢"},
    "dry_run": {"en": "Preview", "zh": "預演"},
    "hide_window": {"en": "Hide", "zh": "隱藏"},
    "verify_retry": {"en": "Verify", "zh": "檢查補點"},
    # ---- Actions 執行 ----
    "start": {"en": "Solve & Fill", "zh": "開始自動解答"},
    "solve_only": {"en": "Solve only", "zh": "只求解"},
    "stop": {"en": "Stop", "zh": "停止"},
    "save_capture": {"en": "Save", "zh": "存圖"},
    # ---- Status 狀態 ----
    "status_capturing": {"en": "Capturing...", "zh": "擷取畫面中..."},
    "status_solving": {"en": "Recognising and solving...", "zh": "辨識與求解中..."},
    "status_filling": {"en": "Filling in answers...", "zh": "填答中..."},
    "status_checking": {"en": "Checking...", "zh": "檢查中..."},
    "status_waiting_mouse": {"en": "Waiting for mouse release...", "zh": "等待放開滑鼠..."},
    "status_done": {"en": "Done", "zh": "完成"},
    "status_preview_done": {"en": "Preview finished", "zh": "預演完成"},
    "status_solved_only": {"en": "Solved (not filled)", "zh": "求解完成（未填答）"},
    "status_stopped": {"en": "Stopped", "zh": "已中止"},
    "status_failed": {"en": "Recognition failed", "zh": "辨識失敗"},
    "status_error": {"en": "Error", "zh": "發生錯誤"},
    "status_stopping": {"en": "Stopping...", "zh": "停止中..."},
    "status_waiting_board": {
        "en": "Watching the screen - open the puzzle now...",
        "zh": "偵測畫面中——現在去開啟題目...",
    },
    "status_waiting_next": {
        "en": "Round finished - open the next puzzle, or press Stop...",
        "zh": "本輪結束——請開啟下一題，或按停止...",
    },
    "status_solve_failed_stopped": {
        "en": "Recognition failed - stopped, please check",
        "zh": "辨識失敗——已自動停止，請確認畫面",
    },
    # ---- Log messages 訊息 ----
    "log_file": {"en": "Session log file", "zh": "本次執行的記錄檔"},
    "log_waiting_hint": {
        "en": "Continuous mode: every puzzle that appears in the capture region "
              "gets solved and filled automatically, one after another, until "
              "you press Stop. Open the first puzzle now.",
        "zh": "連續模式：擷取範圍內每出現一題就會自動求解並填答，一題接一題，"
              "直到你按「停止」為止。現在請開啟第一題。",
    },
    "log_board_appeared": {"en": "Puzzle appeared after", "zh": "題目出現，等待了"},
    "log_round": {"en": "Round {n}", "zh": "第 {n} 輪"},
    "log_solve_retry": {
        "en": "Recognition failed - retrying on a fresh capture",
        "zh": "辨識失敗——重新擷取畫面再試一次",
    },
    "log_puzzle_type": {"en": "Puzzle type", "zh": "謎題類型"},
    "log_plan": {"en": "=== Fill plan ===", "zh": "=== 填答計畫 ==="},
    "log_elapsed": {"en": "Elapsed", "zh": "耗時"},
    "log_preview_note": {
        "en": "Preview only. Uncheck 'Preview' to actually move the mouse.",
        "zh": "以上只是預演。取消勾選「預演」才會真的操作滑鼠。",
    },
    "log_focus_window": {"en": "Focused window", "zh": "切到目標視窗"},
    "log_wait_mouse": {"en": "Waited for mouse release", "zh": "等待放開滑鼠"},
    "log_check_round": {"en": "Check round", "zh": "檢查 第"},
    "log_board_changed": {
        "en": "  Stopped; no longer controlling the mouse.",
        "zh": "  已停止操作，不再控制滑鼠。",
    },
    "log_complete_stop": {"en": "  Complete, stopping.", "zh": "  已完成，停止操作。"},
    "log_guard_frame_saved": {
        "en": "  Saved the frame that triggered the stop",
        "zh": "  已存下觸發停止的那一張畫面",
    },
    "log_solve_failed_frame_saved": {
        "en": "  Saved the capture recognition failed on, for later diagnosis",
        "zh": "  已存下辨識失敗當時的擷取畫面，供事後排查",
    },
    "log_failsafe": {
        "en": "  Stopped: the mouse hit a screen corner (pyautogui's fail-safe).",
        "zh": "  已停止：滑鼠碰到了螢幕角落（pyautogui 的安全逃生機制）。",
    },
    "log_retry": {"en": "  Re-clicking", "zh": "  補點"},
    "log_no_improve": {
        "en": "  No improvement; stopping to avoid undoing correct cells.",
        "zh": "  補點後沒有改善，停止補點以免破壞已填對的格子。",
    },
    "log_region_preview": {"en": "Capture region preview", "zh": "擷取範圍預覽"},
    "log_region_hint": {
        "en": "Check the preview above contains the whole board. If not, adjust X/Y/W/H.",
        "zh": "請確認上方預覽圖裡有完整的棋盤。若沒有，調整 X/Y/寬/高 再測一次。",
    },
    "log_board_small": {
        "en": "Note: board is only {px}px. If results look wrong, zoom the page in with Ctrl +.",
        "zh": "注意: 棋盤只有 {px}px；若結果怪怪的，可在 Chrome 按 Ctrl + 放大頁面。",
    },
    "log_fail_hint": {
        "en": "Press 'Test' to confirm the board is fully captured, or 'Save' to keep the image for debugging.",
        "zh": "可以先按「測範圍」確認棋盤有被完整擷取到，或按「存圖」把畫面存起來以便排查。",
    },
    "log_calibration_candidate_saved": {
        "en": "  Saved {n} cell(s) we filled ourselves but could not read "
              "back confidently, as a future digit-calibration candidate "
              "(not used automatically).",
        "zh": "  已把 {n} 個我們自己填的、但辨識信心不足的格子存成未來數字"
              "校準的候選資料（不會自動生效）。",
    },
    "log_persistent_failure_hint": {
        "en": "All {n} attempts (each on a fresh screen capture) gave the "
              "exact same result. This does not look like a rendering-timing "
              "issue - it may mean some digits or icons on this screen are "
              "drawn differently from the calibrated reference images.",
        "zh": "全部 {n} 次嘗試（每次都用新擷取的畫面）得到完全相同的結果。"
              "這看起來不像是畫面還沒渲染完的暫時性問題——可能是這個畫面上"
              "的某些數字或圖示，跟目前校準用的參考畫面畫法不太一樣。",
    },
    "log_solve_failed_alert": {
        "en": "Recognition still failed after {n} attempts on this puzzle. "
              "Continuous mode has been stopped so this is not missed - check "
              "the puzzle is fully visible in the capture region, or press "
              "'Test' to inspect it, then press 'Solve & Fill' again.",
        "zh": "這一題辨識重試 {n} 次後仍然失敗。已自動停止連續模式，避免這個情況"
              "沒被發現——請確認題目是否完整落在擷取範圍內，或按「測範圍」檢查"
              "畫面，確認沒問題後再按一次「開始自動解答」。",
    },
    "log_resolution_changed": {
        "en": "Screen size looks different from when the capture region was "
              "last set (was {old}, now {new}). If solving fails, press "
              "'Reset' or 'Test' to recalibrate.",
        "zh": "目前螢幕尺寸跟上次設定擷取範圍時不一樣（當時 {old}，現在 "
              "{new}）。如果解不出題目，請按「預設」或「測範圍」重新校準。",
    },
    # ---- Dialogs 對話框 ----
    "dlg_capture_failed": {"en": "Capture failed", "zh": "擷取失敗"},
    "dlg_read_failed": {"en": "Cannot read image", "zh": "讀不到圖片"},
    "dlg_saved": {"en": "Saved", "zh": "已儲存"},
    "dlg_save_failed": {
        "en": "Could not save - check the path is writable",
        "zh": "存檔失敗——請確認路徑可以寫入",
    },
    "dlg_nothing_to_save": {"en": "Nothing captured yet", "zh": "尚未擷取"},
    "dlg_save_title": {"en": "Save captured image", "zh": "存下擷取畫面"},
    "dlg_pick_image": {"en": "Choose a puzzle screenshot", "zh": "選擇謎題截圖"},
    # ---- Image mode 圖片模式 ----
    "img_answer_saved": {"en": "Answer image saved to", "zh": "答案疊圖已存到"},
    "img_save_answer": {"en": "Save answer image...", "zh": "另存答案圖片..."},
    "img_hint": {
        "en": "Pick a screenshot (phone or desktop); the answer is drawn on it. No mouse control.",
        "zh": "選一張截圖（手機或電腦皆可），答案會畫在圖上。不會操作滑鼠。",
    },
}


class Translator:
    """
    Holds the current language and looks strings up.
    保存目前語言並負責查表。

    Missing keys fall back to the key itself, so a typo shows up in the UI
    instead of raising at runtime and killing the window.
    找不到的 key 會直接顯示 key 本身，這樣打錯字只會在畫面上看到怪字串，
    而不會在執行期丟例外把視窗弄掛。
    """

    def __init__(self, language: str = DEFAULT_LANGUAGE):
        self.language = language if language in LANGUAGES else DEFAULT_LANGUAGE

    def set_language(self, language: str) -> None:
        if language in LANGUAGES:
            self.language = language

    def __call__(self, key: str, **kwargs) -> str:
        entry = _TEXTS.get(key)
        if entry is None:
            return key
        text = entry.get(self.language) or entry.get(DEFAULT_LANGUAGE) or key
        return text.format(**kwargs) if kwargs else text


#: Shared instance used across the UI.
#: 介面各處共用的實例。
translator = Translator()
