"""
Is our board still on screen? Checked between actions, mid-plan.
我們的棋盤還在螢幕上嗎？在動作與動作之間、填答進行中檢查。

WHY THIS EXISTS 為什麼需要這個
------------------------------
A fill plan is a frozen list of clicks built from ONE screenshot. Before this
module the whole list ran with no further look at the screen: measured, a 9-cell
Queens fill clicked blind for 8.96s and a Tango fill for 21.15s. If the puzzle
completes partway through - because the site auto-finishes, or because the user
had already placed some pieces - the site swaps in its completion screen and
every remaining click lands on whatever is there now.
填答計畫是根據「一張」截圖產生的固定動作清單。在這個模組之前，整串清單會
一路執行完、中途完全不再看螢幕：實測 9 格的 Queens 盲點 8.96 秒、Tango 盲點
21.15 秒。如果謎題在中途就完成（網站自動結束，或使用者本來就放好了幾個），
網站會換上完成畫面，而剩下的每一次點擊都會落在當下畫面上的任何東西上。

That is the reported bug: "解答完成後依然會控制滑鼠，就算畫面已經改變".
這正是回報的問題：「解答完成後依然會控制滑鼠，就算畫面已經改變」。

WHAT IT CHECKS, AND WHAT IT DELIBERATELY DOES NOT 檢查什麼、刻意不檢查什麼
------------------------------------------------------------------------
It asks one structural question: **can the board still be located at all?**
It does NOT compare pixels. A pixel comparison was measured and rejected: the
cells we are deliberately filling in change more than a 25% dimming overlay
does (MAD 36.35-112.73 for our own fills versus 44.93 for a scrim), so there is
no threshold in either direction. Per the project rule - if there is no gap the
measurement is including something it should not, and here it is including the
very cells we are drawing on.
它只問一個結構性的問題：**棋盤還定位得到嗎？**
它不比對像素。像素比對已經量測過並否決：我們自己填進去的格子造成的變化，
比整片變暗 25% 的遮罩還大（自己填答 MAD 36.35~112.73，遮罩 44.93），
兩個方向都不存在門檻。依照專案規則 —— 沒有間隔就代表量測混進了不該包含的東西，
而這裡混進的正是我們自己正在畫的那些格子。

So: filling the board in does not trip it; the board being replaced does.
所以：把棋盤填滿不會觸發它，棋盤被換掉才會。

MEASURED COVERAGE, INCLUDING WHAT IT MISSES 實測涵蓋範圍，包含抓不到的
------------------------------------------------------------------------
17 real boards in every state (empty / half filled / completely filled / solved,
phone and browser scales, all five puzzles): 0 false aborts.
8 replacement scenarios: 6 detected.

    detected 抓得到   flat fill (the realistic completion screen), flat white,
                     flat dark, random noise, a different puzzle scaled into
                     the same rectangle, our own puzzle at a different size
    MISSED 抓不到     a 50% or 75% white scrim laid over the board

The scrim case is a genuine blind spot and is documented rather than papered
over: the board is still structurally present underneath, so no structural test
can see it. If LinkedIn ever shows a translucent modal over a live board instead
of navigating away, clicks would land on the modal and this guard would not stop
them. The realistic completion behaviour - replacing the board - IS caught.
17 個真實棋盤的各種狀態（空白／填一半／完全填滿／已解完，手機與瀏覽器尺寸，
五款謎題全包）：0 次誤中止。8 種被替換的情境：抓到 6 種。
半透明遮罩是真正的盲點，這裡誠實記錄而不是掩蓋：棋盤在底下結構上仍然存在，
所以任何結構性判斷都看不到它。如果 LinkedIn 哪天改成在活著的棋盤上蓋一層
半透明對話框、而不是直接換頁，點擊會落在對話框上而這個保護擋不住。
真實的完成行為 —— 把棋盤換掉 —— 是抓得到的。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

import cv2
import numpy as np

from ..core import build_grid
from ..core.board import build_grid_from_lines
from .capture import capture_region

#: Board size the locators were calibrated at, matching puzzles/__init__.py.
#: 定位器校準時的棋盤大小，與 puzzles/__init__.py 一致。
TARGET_BOARD_PIXELS = 794


#: Saturation (HSV) above which a pixel is treated as OUR OWN drawn mark
#: rather than board structure, and is masked to white before a second
#: locate attempt.
#: 高於這個飽和度（HSV）的像素視為「我們自己畫上去的東西」而不是棋盤結構，
#: 第二次定位嘗試前會先把它遮成白色。
#:
#: MEASURED on a real mid-drag Patches capture (extracted from a screen
#: recording, board_watch.py's own locate_board on the raw crop, 2026-08-04):
#: a drawn patch's fill is S 76-94 over a broad area (p90-p96 of the whole
#: crop); the same board's UNFILLED background is S <3 for 90% of pixels,
#: with the only high-S outliers being the small pre-printed number badges
#: (S up to 213, but confined to tiny circles, not lines). The gap between
#: "broad drawn fill" (76+) and "background, plus small label dots" (<3,
#: with rare isolated spikes) is wide enough that masking >50 removes the
#: fill without touching grid lines, which are gray/black and low-S by
#: construction.
#: 對一次真實的、拖曳到一半的 Patches 擷取實測（從螢幕錄影切出來，
#: 用 board_watch.py 自己的 locate_board 對原始裁切測，2026-08-04）：
#: 已畫的貼塊填色在一大片範圍內飽和度是 76~94（整張裁切的 p90~p96）；
#: 同一張棋盤「還沒畫」的背景 90% 像素飽和度 <3，唯一的高飽和度離群值是
#: 印在格子上的小數字標籤圓圈（最高到 213，但只佔一小塊圓形，不是線）。
#: 「大片填色」（76 以上）跟「背景加上零星小標籤」（<3，偶爾有孤立尖峰）
#: 之間的差距很大，遮住 >50 足以去掉填色，又不會動到格線本身——
#: 格線是灰色或黑色，本來就是低飽和度。
_OWN_MARK_SATURATION = 50


def _mask_own_marks(crop: np.ndarray) -> np.ndarray:
    """Replace our own high-saturation drawn marks with white.
    把我們自己畫的高飽和度標記換成白色。

    WHY this exists 為什麼需要這個: detect_grid_size works on grayscale
    brightness, expecting only THIN grid lines to read as dark. A drawn
    Patches rectangle's pastel fill is not black, but it is dark enough in
    grayscale to make a whole column or row read as "mostly dark" instead of
    "mostly light with one thin dark line" - which breaks the sparse-line
    assumption for every threshold the sweep tries, not just one. Confirmed by
    direct reproduction: build_grid raised "grid size not detected" on a real
    mid-drag Patches capture where a drawn rectangle touched two board edges.
    為什麼需要這個：detect_grid_size 是靠灰階亮度工作的，預期只有「細細的格線」
    會被讀成暗色。Patches 畫上去的粉彩填色不是黑的，但轉成灰階已經暗到讓
    整欄或整列被讀成「大部分是暗的」而不是「大部分是亮的、只有一條細暗線」——
    這會讓掃描的每一個門檻都失效，不是只有某一個。已直接重現確認：對一張
    真實的、有矩形貼塊碰到兩側棋盤邊的拖曳中截圖，build_grid 拋出
    「無法自動偵測棋盤格數」。
    """
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    masked = crop.copy()
    masked[hsv[:, :, 1] > _OWN_MARK_SATURATION] = (255, 255, 255)
    return masked


def locate_board(crop: np.ndarray, n: int):
    """Whichever locator this board actually needs. Returns a grid or None.
    這個棋盤真正需要的定位器。回傳 grid 或 None。

    BOTH strategies are required - neither works alone. Measured on the
    project's own fixtures, feeding each board its own pristine crop:
    兩種策略都必要，任何一種單獨用都不行。用專案自己的測試圖實測，
    每個棋盤餵它自己「完全沒被改過」的裁切：

        fixture                  build_grid   build_grid_from_lines
        live_tango.png           RAISE        OK n=6
        S__104316931.jpg         RAISE        OK n=6
        live_patches.png         RAISE        OK n=7
        fullscreen_patches.png   RAISE        OK n=8
        every queens fixture     OK           None

    build_grid finds an outer border contour, and core/board.py records that
    Tango has no outer border at all while Patches draws its outer border
    fainter than its inner lines. build_grid_from_lines finds evenly spaced grid
    lines, which Queens boards do not have (adjacent same-colour regions leave
    no line). Using build_grid alone would abort every Tango and browser-scale
    Patches fill before the first click.
    build_grid 找的是外框輪廓，而 core/board.py 記載 Tango 根本沒有外框、
    Patches 的外框比內部格線更淡。build_grid_from_lines 找的是等距格線，
    而 Queens 沒有（相鄰同色區塊之間不會留下線）。
    只用 build_grid 的話，每一次 Tango 與瀏覽器尺寸的 Patches 填答，
    都會在第一次點擊之前就中止。
    """
    if crop is None or crop.size == 0 or min(crop.shape[:2]) < 40:
        return None

    # Normalise to the calibrated size first, exactly as the solve pipeline
    # does. Measured: live_patches.png at its native 415px RAISES, and the same
    # crop resized to 794px locates fine.
    # 先正規化到校準尺寸，跟求解流程做的一樣。實測：live_patches.png
    # 在原生 415px 會拋錯，同一塊裁切放大到 794px 就定位得到。
    side = max(crop.shape[0], crop.shape[1])
    if side > 0 and abs(side - TARGET_BOARD_PIXELS) / TARGET_BOARD_PIXELS > 0.15:
        factor = TARGET_BOARD_PIXELS / side
        interp = cv2.INTER_CUBIC if factor > 1 else cv2.INTER_AREA
        crop = cv2.resize(crop, None, fx=factor, fy=factor, interpolation=interp)

    # NEVER pass n_hint here, and check the size that comes back. The guard's
    # job is to VERIFY, and a hint tells the locator the answer instead of
    # asking it. Measured on a 7x7 Patches board scaled into a 9x9 Queens
    # board's rectangle:
    #     n_hint=None -> build_grid RAISES, build_grid_from_lines returns n=7
    #     n_hint=9    -> build_grid happily returns n=9
    # With the hint, swapping one game for another went completely unnoticed and
    # a Queens fill would have carried on clicking into a different puzzle.
    # 這裡絕不能傳 n_hint，而且要檢查回來的格數。保護的工作是「驗證」，
    # 傳 hint 等於把答案告訴定位器，而不是問它。
    # 實測：把 7x7 的 Patches 縮放到 9x9 Queens 的矩形裡 ——
    #     n_hint=None -> build_grid 拋錯、build_grid_from_lines 回傳 n=7
    #     n_hint=9    -> build_grid 高高興興回傳 n=9
    # 帶 hint 的話，遊戲被換掉完全不會被發現，Queens 的填答會繼續點進另一款謎題。
    for locator in (build_grid, build_grid_from_lines):
        try:
            grid = locator(crop)
        except Exception:
            continue
        if grid is not None and _size_is_ours(grid.n, n):
            return grid

    # Second pass, only if the first failed: mask our own drawn marks and try
    # again. Tried SECOND, never first, so every board that already located
    # fine on the raw crop keeps doing exactly that - this only ever adds
    # coverage, never changes an existing answer.
    # 第二輪，只有第一輪失敗才會試：把我們自己畫的東西遮掉再試一次。
    # 一定放在「第二」而不是第一，這樣任何在原始裁切上就定位得到的棋盤
    # 完全不受影響——這一輪只會增加涵蓋範圍，不會改動任何既有的答案。
    masked = _mask_own_marks(crop)
    for locator in (build_grid, build_grid_from_lines):
        try:
            grid = locator(masked)
        except Exception:
            continue
        if grid is not None and _size_is_ours(grid.n, n):
            return grid
    return None


#: A filled board may read as an integer multiple of its true size, because
#: drawing into every cell adds an apparent boundary inside each one - the
#: sub-structure is a refinement of the original grid, so the line count scales.
#: 填好的棋盤可能被讀成真實格數的整數倍：在每一格裡畫東西，等於在格子內部
#: 多出一條看似的邊界 —— 子結構是原網格的細分，所以線數會成倍增加。
#:
#: Measured on real boards in every state (17 fixtures: empty, half filled,
#: completely filled, phone and browser scales):
#:     puzzle_answer.png  a COMPLETELY FILLED 6x6 Tango reads n=12 (2x6)
#:     every other state reads its true n
#: Requiring an exact match aborted on that filled Tango - i.e. it would have
#: killed a Tango fill partway through a perfectly correct board.
#: 實測真實棋盤的各種狀態（17 張圖：空白、填一半、完全填滿、手機與瀏覽器尺寸）：
#:     puzzle_answer.png 完全填滿的 6x6 Tango 讀到 n=12（2x6）
#:     其他狀態都讀到真實格數
#: 要求完全相符會對那個填滿的 Tango 中止 —— 等於在一個完全正確的盤面填到一半時
#: 把 Tango 弄壞。
_MAX_REFINEMENT = 3


def _size_is_ours(found: int, ours: int) -> bool:
    if found <= 0 or ours <= 0:
        return False
    return found == ours or (found % ours == 0 and found // ours <= _MAX_REFINEMENT)


@dataclass
class BoardWatch:
    """Answers still_there() for the board a plan was built from.
    回答「計畫所依據的那個棋盤還在嗎」。

    `grab` and `locate` are injected so tests can drive a scripted screen with
    no mss and no display.
    `grab` 與 `locate` 由外部注入，讓測試可以用腳本化的假螢幕驅動，
    不需要 mss、也不需要顯示裝置。
    """

    mapper: object          # BoardMapper
    n: int
    grab: object = capture_region
    locate: object = locate_board

    #: Minimum seconds between two real evaluations. In between, the last answer
    #: is reused.
    #: 兩次真正評估之間的最短間隔（秒）。中間直接沿用上一次的答案。
    #:
    #: WHY 為什麼:
    #:   The guard is asked before every action, and a plan has a lot of actions:
    #:   measured, tango 72, queens 27, sudoku 72, zip 481, patches 169 - 821 for
    #:   one sitting of five puzzles. Each real evaluation costs a screen grab
    #:   (18-33ms) plus locate_board (89-127ms), so unthrottled that is 73-104
    #:   seconds of pure checking added to a sitting.
    #:   保護在每個動作前都會被問，而一個計畫的動作很多：實測 tango 72、
    #:   queens 27、sudoku 72、zip 481、patches 169 —— 五款一輪共 821 次。
    #:   每次真正評估要一次螢幕擷取（18~33 毫秒）加上 locate_board（89~127 毫秒），
    #:   不節流的話等於替一輪加上 73~104 秒純檢查時間。
    #:
    #:   0.25s bounds the exposure: the board can be gone for at most a quarter
    #:   of a second before we notice, which is well under the time any single
    #:   click takes at the default speed (about 1s per Queens cell).
    #:   0.25 秒界定了曝險：棋盤最多消失四分之一秒就會被發現，
    #:   這遠短於預設速度下任何一次點擊所需的時間（Queens 每格約 1 秒）。
    min_interval: float = 0.25

    #: Set once arm() succeeds. Until then the watch refuses to judge anything.
    #: arm() 成功之後才會設為 True。在那之前這個 watch 拒絕對任何事下判斷。
    armed: bool = False
    #: Why we stopped, for the log. 停止的原因，寫進記錄。
    reason: str = ""
    #: The frame that failed to locate, so a real abort can be inspected after
    #: the fact instead of guessed at. None unless still_there() just returned
    #: False because locate() failed - never set for a screen-capture failure,
    #: since there is no frame to save in that case.
    #: 判定失敗的那一張畫面，讓真正發生的中止事後能被檢視，而不是用猜的。
    #: 只有在 still_there() 因為 locate() 失敗才剛回傳 False 時才會設定 ——
    #: 螢幕擷取本身失敗的情況不會設定，因為那種情況下根本沒有畫面可存。
    last_image: object = None
    _gone: bool = False
    _checks: int = field(default=0)
    _last_at: float = field(default=0.0)

    def arm(self, board_image: np.ndarray) -> bool:
        """Prove the locator can find the board in the frame the plan came from.
        證明定位器能在「計畫所依據的那一幀」裡找到棋盤。

        THIS IS THE SELF-TEST THAT MATTERS. A locator that cannot find the board
        in its own plan-time frame is a configuration fault, not "board gone" -
        and if we let it judge anyway it would abort before the first click.
        That is exactly the regression that a review caught: an earlier design
        used build_grid for everything and killed Tango and Patches outright.
        On failure we refuse to attach, log loudly, and let the run proceed with
        the old post-plan verify() behaviour rather than breaking filling.
        這就是關鍵的自我檢驗。定位器如果連「計畫所依據的那一幀」都找不到棋盤，
        那是設定錯誤，不是「棋盤不見了」—— 若還讓它判斷，它會在第一次點擊之前
        就中止。這正是審查抓到的退步：先前的設計對所有謎題都用 build_grid，
        直接讓 Tango 與 Patches 完全不能用。
        失敗時我們拒絕掛上這個保護、大聲記錄，讓這次執行退回舊的「事後 verify()」
        行為，而不是把填答弄壞。
        """
        self.armed = self.locate(board_image, self.n) is not None
        if not self.armed:
            self.reason = ("board watch disabled: locator could not find the board in "
                           "the plan's own frame / 中途保護未啟用：定位器在計畫自己的"
                           "畫面裡就找不到棋盤")
        return self.armed

    def still_there(self) -> bool:
        """False once the board can no longer be located. Latches.
        棋盤定位不到之後回傳 False，且會鎖定不再回頭。

        Latching matters: a transient failure must not be followed by "it is
        back, carry on clicking" halfway through a plan built for a board that
        may since have changed.
        鎖定很重要：不能在計畫進行到一半時，因為某次暫時失敗之後又「回來了」
        就繼續點 —— 那個計畫依據的棋盤可能早就變了。
        """
        if not self.armed:
            return True          # never judge when we were not able to self-test
        if self._gone:
            return False
        # Rate limit. Between real evaluations reuse the last answer - see
        # min_interval for the measured cost this avoids.
        # 節流。兩次真正評估之間沿用上一次的答案 —— 省下的成本見 min_interval。
        now = time.perf_counter()
        if self._last_at and (now - self._last_at) < self.min_interval:
            return True
        self._last_at = now
        self._checks += 1
        left, top, w, h = self.mapper.board_rect_on_screen()
        try:
            shot = self.grab(left, top, w, h)
        except Exception as exc:
            # Cannot read the screen at all -> stop. Refusing to look is not
            # evidence the board is fine.
            # 完全讀不到螢幕 -> 停。看不到不等於棋盤沒事。
            self._gone = True
            self.reason = f"screen capture failed / 擷取螢幕失敗: {type(exc).__name__}: {exc}"
            return False
        image = getattr(shot, "image", shot)
        if self.locate(image, self.n) is None:
            self._gone = True
            self.last_image = image
            self.reason = ("board is no longer where it was - stopping so the "
                           "remaining clicks do not land on something else / "
                           "棋盤已不在原處，停止動作以免剩下的點擊落在別的東西上")
            return False
        return True

    def checks_made(self) -> int:
        return self._checks
