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
It asks one structural question first: **can the board still be located at
all?** A GLOBAL pixel comparison was measured and rejected: the cells we are
deliberately filling in change more than a 25% dimming overlay does (MAD
36.35-112.73 for our own fills versus 44.93 for a scrim), so there is no
threshold in either direction. Per the project rule - if there is no gap the
measurement is including something it should not, and here it is including the
very cells we are drawing on.
它先問一個結構性的問題：**棋盤還定位得到嗎？**「全域」像素比對已經量測過
並否決：我們自己填進去的格子造成的變化，比整片變暗 25% 的遮罩還大
（自己填答 MAD 36.35~112.73，遮罩 44.93），兩個方向都不存在門檻。依照專案
規則 —— 沒有間隔就代表量測混進了不該包含的東西，而這裡混進的正是我們自己
正在畫的那些格子。

For PATCHES ONLY there is a second layer: when the locator fails, the parts
of the board our fills have NOT painted are compared against the frame the
plan was armed on (see the CONTENT_* constants below). That is not the
rejected global comparison - it masks the fills out first, which is exactly
what made the global version meaningless. Added 2026-08-09 after a real 8x8
fill lost the grid lines to its own fills for 7 straight checks and was
wrongly aborted.
「僅拼塊」多了第二層：定位器失敗時，把「我們的填色沒有畫到的部分」拿去跟
武裝當下的畫面比對（見下方 CONTENT_* 常數）。這不是被否決的那種全域比對——
它會先把填色遮掉，而填色正是讓全域版失去意義的原因。2026-08-09 加入，
起因是一次真實的 8x8 填答，自己的填色把格線抹掉、連續 7 次檢查失敗，
被錯誤地中止。

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

from ..core import action_log, build_grid
from ..core.board import build_grid_from_lines, mask_saturated
from ..puzzles import patches
from .capture import capture_region

#: Board size the locators were calibrated at, matching puzzles/__init__.py.
#: 定位器校準時的棋盤大小，與 puzzles/__init__.py 一致。
TARGET_BOARD_PIXELS = 794


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
    # coverage, never changes an existing answer. Shared with build_grid's
    # own fallback (core/board.py) - same failure, same fix, one definition.
    # 第二輪，只有第一輪失敗才會試：把我們自己畫的東西遮掉再試一次。
    # 一定放在「第二」而不是第一，這樣任何在原始裁切上就定位得到的棋盤
    # 完全不受影響——這一輪只會增加涵蓋範圍，不會改動任何既有的答案。
    # 跟 build_grid 自己的備援（core/board.py）共用——同一個失敗、同一個
    # 修法，只定義一次。
    masked = mask_saturated(crop)
    for locator in (build_grid, build_grid_from_lines):
        try:
            grid = locator(masked)
        except Exception:
            continue
        if grid is not None and _size_is_ours(grid.n, n):
            return grid
    return None


# ---------------------------------------------------------------------------
# Reference-content check (Patches only) 參考內容比對（僅拼塊使用）
# ---------------------------------------------------------------------------
# WHY THIS EXISTS 為什麼需要這個:
# A real 8x8 Patches fill (2026-08-09, session log + screen recording + two
# auto-saved abort frames, reproduced IDENTICALLY twice) lost detect_grid_size
# for 7 consecutive checks on a board that never moved, exceeding
# PATCHES_FAILURE_TOLERANCE=6 and aborting a correct fill. Structural
# re-detection fundamentally cannot survive a Patches fill: our own fills
# progressively erase the interior grid lines the locator needs, and they do
# not come back. The user's insight, adopted here: we already KNOW what we
# filled and where - so when the locator fails, compare the parts of the
# board we did NOT paint against the frame the plan was armed on, instead of
# trying to re-derive the grid from scratch.
# 一次真實的 8x8 拼塊填答（2026-08-09，執行記錄＋螢幕錄影＋兩張自動存下的
# 中止畫面，完全相同地重現了兩次）在一個根本沒動過的棋盤上，讓
# detect_grid_size 連續失敗 7 次、超過 PATCHES_FAILURE_TOLERANCE=6，把一次
# 正確進行中的填答中止了。結構性重新偵測在拼塊上本質上撐不住：我們自己的
# 填色會逐步抹掉定位器需要的內部格線，而且不會恢復。這裡採用的是使用者
# 提出的想法：我們本來就「知道」自己填了什麼、填在哪——所以定位器失敗時，
# 改拿「我們沒有畫到的部分」跟武裝當下的畫面比對，而不是從頭重新推算格線。
#
# WHY THE OLD "no pixel comparison" RULE DOES NOT APPLY 為什麼舊的「不做像素
# 比對」規則不適用: the module docstring records that a GLOBAL pixel
# comparison was measured and rejected - our own fills change more pixels
# than a scrim does. That comparison INCLUDED the cells being painted. This
# check is the complement: it masks out everything saturated (the fills) and
# compares only what remains, one-directionally (the reference's structure
# must still be there). Measured over every real same-board pair available
# (see the constants below), the two problems do not overlap.
# 模組文件字串記載過：「全域」像素比對量測後被否決——我們自己的填色改動的
# 像素比遮罩還多。那個比對「包含了」正在被畫的格子。這裡是它的補集：把
# 飽和的部分（填色）全部遮掉，只比對剩下的內容，而且只做單向（參考畫面的
# 結構必須還在）。對手上每一組真實同棋盤配對量測過（見下方常數），
# 兩個問題並不重疊。
#
# AFFIRMATIVE-ONLY BY DESIGN 只做正面認證，絕不做否定判決:
# this check can only ever say "the un-painted content still matches - keep
# going" (which resets the tolerance counter) or "I could not affirm that"
# (which falls through to the ORIGINAL tolerance counting, unchanged). It
# never aborts anything by itself. An earlier revision also had an
# immediate-abort verdict; an adversarial review (2026-08-09) killed it with
# a reproduced counter-example: the real 2026-08-06 board pair drifted ~1%
# in SCALE between arm and check (bbox 415 -> 419), translation search
# cannot compensate scale, the pair scored 0.2257 under the production crop
# protocol, and the immediate-abort verdict re-broke the exact false abort
# PATCHES_FAILURE_TOLERANCE=6 was raised to fix. With the affirmative-only
# contract, EVERY scenario is provably no worse than the old behaviour:
# the worst this check can do is decline to affirm, which IS the old path.
# 這個檢查只可能說「沒被填色的內容仍然吻合——繼續」（把容忍計數歸零），
# 或「我無法認證」（落回「原本的」容忍計數，完全不變）。它自己絕不中止
# 任何事。先前的版本還有一個「立即中止」的判決；2026-08-09 的對抗性審查
# 用一個重現出來的反例把它否決了：2026-08-06 那組真實棋盤在武裝與檢查
# 之間有約 1% 的「縮放」漂移（bbox 415 -> 419），平移搜尋補償不了縮放，
# 那組配對在正式裁切協定下只拿 0.2257 分，立即中止的判決會把
# PATCHES_FAILURE_TOLERANCE=6 當初特地修好的那次誤判重新引爆。改成
# 只做正面認證之後，「每一種」情境都可證明不會比舊行為差：這個檢查
# 最壞也只是拒絕認證，而那正是舊路徑本身。
#
# MEASURED 量測依據 (final sweep 2026-08-09, real captures; includes every
# counter-example the adversarial review produced. Production-representative
# pairs are same-source and aligned - the guard re-grabs the SAME absolute
# screen rect every check):
#   AFFIRMED (same board; must be, or today's bug comes back)
#     pristine vs 10-rects-filled (TODAY'S exact     score 1.0000, shift 0
#       failure state, video + both mss aborts)
#     abort1 vs abort2 (mss, 2 min apart)            score 1.0000, shift 0
#     mid_drag 1of6 vs 5of6 (video)                  score 1.0000, shift 0
#     pristine + gaussian noise sigma 2              score 1.0000, shift ~0
#   NOT AFFIRMED -> falls back to the old tolerance path (= old behaviour)
#     flat gray, ANY level 0..255 (incl. the         contrast requirement
#       adversarial 225..244 band that beat the        fails: no pixel is
#       earlier revision)                              dark vs BOTH bgs
#     different game (tango) in the rect             0.5138
#     DIFFERENT patches board (pristine)             0.3840
#     DIFFERENT patches board, same 8x8 size,        0.7602 - the review's
#       heavily filled (grid self-similarity)          strongest attack;
#                                                      below MATCH_MIN 0.90
#     our board shrunk to 80% / 60%                  0.0738 / 0.0519
#     random noise                                   mask/basis floors
#     15%..75% white scrim / dim over the filled     score ~1.0 BUT contrast
#       board (the review showed the earlier           retained is exactly
#       revision let these run forever; the old        1-strength: 0.85 at
#       tolerance path aborted them - restored         15% down to 0.25 at
#       via the CONTENT_CONTRAST_KEEP gate)            75% -> declined
#     2026-08-06 browser pair (real ~1% scale        0.2257 under production
#       drift between captures)                        crops -> not affirmed
#                                                      -> old tolerance path,
#                                                      which that puzzle's
#                                                      tolerance=6 covers -
#                                                      same as today
# KNOWN RESIDUAL GAP, stated honestly 已知殘餘缺口，誠實記錄: a partial DARK
# desaturated occluder (e.g. a dark opaque panel over part of the board,
# page NOT dimmed) keeps every reference-structure pixel "still dark" and
# can be affirmed while it persists. Indistinguishable in principle from
# our own desaturated fills (brown fill measured S=29, gray~151 - the same
# signature). Bounded: the guard only runs during a finite plan, so the
# exposure ends with the plan; the realistic overlay (a page-dimming modal)
# shifts structure brightness and IS declined by the shift gate.
# 已知殘餘缺口：局部的「深色去飽和遮擋物」（例如一塊深色不透明面板蓋住
# 部分棋盤、頁面沒有變暗）會讓參考結構像素「維持是暗的」，存在期間可能
# 被認證通過。原理上跟我們自己的去飽和填色（棕色實測 S=29、灰階約 151，
# 同一種特徵）無法區分。但有邊界：守衛只在有限長度的計畫期間運作，
# 曝險隨計畫結束而結束；而現實中的覆蓋（會把整頁變暗的對話框）會讓
# 結構亮度偏移，「會」被亮度偏移守門拒絕認證。
CONTENT_SAT_REF = 50        # same measured threshold as mask_saturated 與 mask_saturated 同一個實測門檻
CONTENT_SAT_CUR = 25        # stricter on the current side: excludes fill-edge halos 目前畫面側更嚴：排除填色邊緣的半飽和光暈
CONTENT_REL_MARGIN = 20     # "structure" = darker than background median by this 「結構」＝比背景中位數暗至少這麼多
CONTENT_KEEP_MARGIN = 10    # structure must STAY this much darker than BOTH backgrounds 結構「維持」比兩邊背景都暗至少這麼多
CONTENT_MIN_MASK_FRACTION = 0.05  # below this the comparison declines to affirm 低於此比例拒絕認證
CONTENT_MIN_STRUCT = 150    # minimum structure pixels for a meaningful affirmation 有意義認證所需的最少結構像素數
#: +-px jitter tolerance. Production frames are same-rect mss grabs and all
#: affirmed pairs measured at shift 0; 1px covers sub-pixel wobble. Kept
#: small on purpose - the review measured the +-2 search at 25 evaluations
#: costing 405-493ms on a 794px board; +-1 is 9, with an early exit at the
#: centre offset for the common (matching) case.
#: 容忍擷取抖動的±像素。正式運作的畫面是同一塊矩形的 mss 擷取，所有
#: 認證通過的配對實測偏移都是 0；1px 足以涵蓋次像素等級的晃動。刻意
#: 保持小——審查實測 ±2 搜尋要 25 次評估、在 794px 棋盤上花 405~493 毫秒；
#: ±1 是 9 次，而且常見（吻合）情況在中心偏移就提前返回。
CONTENT_SHIFT_SEARCH = 1
#: Affirmation floor. Every production-representative same-board pair
#: measured EXACTLY 1.0000; the strongest NATURALLY-RENDERED impostor
#: (another real 8x8 patches board, heavily filled - grid self-similarity)
#: reached 0.7602. 0.90 affirms only near-perfect matches. NOT a rejection
#: threshold - scores below simply fall back to the old tolerance path.
#: BOUNDARY, measured by the re-review and recorded honestly: that berth
#: holds only at natural line rendering. The same impostor with its dark
#: lines artificially thickened by a 4-5px minimum filter AND saturated
#: bands placed to break the locator scores 0.99 and IS affirmed - the
#: one-directional score cannot see a dark superset of the reference's
#: structure. No real page rendering produces 3px-thicker, pixel-aligned
#: grid lines, so this sits in the same disclosed family as the
#: dark-desaturated-occluder residual below; recorded so a future reader
#: knows the margin's shape instead of trusting "wide berth" blindly.
#: 認證下限。每一組正式環境等價的同棋盤配對實測都「剛好」1.0000；
#: 「自然渲染」下最強的冒牌貨（另一塊真實 8x8、已填大半的拼塊棋盤——
#: 網格自相似）到 0.7602。0.90 只認證幾乎完美的吻合。這不是拒絕門檻——
#: 低於它只是落回舊容忍路徑。邊界（複審量出，誠實記錄）：這個距離只在
#: 自然線條渲染下成立。同一個冒牌貨若把深色線條用 4~5px 最小值濾波
#: 人為加粗、再放上剛好弄壞定位器的飽和色帶，能拿 0.99 並「會」被認證
#: ——單向分數看不見「參考結構的深色超集」。真實網頁渲染不會產生粗
#: 3px、又逐像素對齊的格線，所以這屬於下方「深色去飽和遮擋物」同一類
#: 已揭露的殘餘缺口；記下來是讓未來的讀者知道餘裕的真實形狀，
#: 而不是盲目相信「距離很寬」。
CONTENT_MATCH_MIN = 0.90
#: Affirmation also requires the masked content's CONTRAST (median minus
#: 2nd percentile of gray) to be retained. A white scrim of opacity a maps
#: v -> (1-a)v + 255a, so distance-from-white - and therefore this ratio -
#: scales by EXACTLY (1-a); a multiplicative dim by factor f scales it by
#: f. Verified on the production-representative mss-vs-mss pairs (armed
#: frame and checks are both mss grabs of the same rect in production):
#:     same-board baseline (abort1 vs abort2)   1.0000
#:     white scrim 10/15/20/25/50%              0.897/0.853/0.809/0.750/0.500
#:     multiplicative dim x0.90/0.85/0.80       0.897/0.853/0.809
#: 0.85 declines every scrim/dim of 15%+ (the earlier struct-median-shift
#: gate was measured and REJECTED: this board's structure is dominated by
#: light dashes whose median barely moves under a scrim - 25% shifted it
#: only +3). One-sided on purpose: a ratio ABOVE 1 just means the current
#: frame is crisper than the reference (the video-sourced test reference is
#: softer than mss), and an impostor cannot exploit it - affirmation still
#: requires the 0.90 structure score first. Residual, documented: scrims
#: and dims BELOW 15% are affirmable; at that strength the board beneath is
#: fully visible and the old tolerance path is the only thing that ever
#: caught them.
#: 認證同時要求遮罩內內容的「對比」（灰階中位數減第 2 百分位）被保留。
#: 濃度 a 的白色遮罩把 v 映成 (1-a)v+255a，「與白的距離」——也就是這個
#: 比值——會「精確」縮成 (1-a) 倍；乘法式調暗（係數 f）則縮成 f 倍。
#: 在正式環境等價的 mss 對 mss 配對上驗證過（正式運作時武裝畫面與檢查
#: 都是同一塊矩形的 mss 擷取）：上表。0.85 擋掉所有 15% 以上的遮罩/調暗
#: （先前的「結構中位數偏移」門檻量測後否決：這塊棋盤的結構以淺色虛線
#: 為主，中位數在遮罩下幾乎不動——25% 只偏移 +3）。刻意只設單邊：比值
#: 高於 1 只代表目前畫面比參考更銳利（測試用的影片來源參考比 mss 軟），
#: 冒牌貨利用不了這一點——認證仍然要先過 0.90 的結構分數。已知殘餘、
#: 誠實記錄：15% 以下的遮罩/調暗可能被認證；那種強度下底下的棋盤完全
#: 可見，而且那種情況以前也只有容忍路徑「碰巧」擋得住。
CONTENT_CONTRAST_KEEP = 0.85


def reference_content_matches(reference: np.ndarray, current: np.ndarray) -> bool:
    """True only on AFFIRMATIVE evidence that the un-painted content of
    `current` is still the board `reference` shows. False means "could not
    affirm" - it is NEVER proof of replacement, and callers must treat it
    as "behave exactly as before this check existed".
    只有在有「正面證據」證明 `current` 裡沒被填色蓋住的內容仍然是
    `reference` 上那個棋盤時才回傳 True。False 的意思是「無法認證」——
    它「絕不是」被換掉的證明，呼叫端必須把它當成「照這個檢查存在之前
    的方式行動」。

    Affirmation requires ALL of 認證需要「同時」滿足:
      1. enough mutually low-saturation content to compare (floors below)
         夠多雙方都低飽和的內容可以比對（下限見常數）
      2. the reference's structure still reads dark relative to BOTH
         frames' own backgrounds - requiring contrast in the CURRENT frame
         is what stops a uniform gray replacement from scoring perfectly
         (the adversarial review's flat-225..244 counter-example)
         參考畫面的結構相對「兩邊各自的」背景都仍然是暗的——要求目前
         畫面自己也有對比，就是擋住整片單色替換拿滿分的那一關
         （對抗性審查的 225~244 整片灰反例）
      3. the masked content retains at least CONTENT_CONTRAST_KEEP of the
         reference's contrast - a scrim/dim compresses contrast by exactly
         its own strength (see the constant's measurements)
         遮罩內內容至少保留參考畫面 CONTENT_CONTRAST_KEEP 的對比——
         遮罩/調暗會把對比精確壓縮成它自己的強度（量測見該常數）
    One-directional by design: the reverse check ("no NEW structure") was
    measured and rejected - LinkedIn's palette contains desaturated fills
    (brown S=29) whose legitimate darkening is indistinguishable from new
    structure.
    刻意只做單向：反向檢查（「不能出現新結構」）量測後否決——LinkedIn 的
    配色含去飽和填色（棕色 S=29），其正當的變暗跟新結構無法區分。
    """
    if reference is None or current is None:
        return False
    if getattr(reference, "shape", None) != getattr(current, "shape", None):
        return False
    sat_ref = cv2.cvtColor(reference, cv2.COLOR_BGR2HSV)[:, :, 1]
    gray_ref = cv2.cvtColor(reference, cv2.COLOR_BGR2GRAY)
    h, w = reference.shape[:2]
    # Centre offset first: the common (matching) case exits after ONE
    # evaluation instead of paying for the whole search.
    # 中心偏移排最前面：常見（吻合）的情況評估「一次」就返回，
    # 不用付整趟搜尋的成本。
    offsets = sorted(
        ((dx, dy)
         for dy in range(-CONTENT_SHIFT_SEARCH, CONTENT_SHIFT_SEARCH + 1)
         for dx in range(-CONTENT_SHIFT_SEARCH, CONTENT_SHIFT_SEARCH + 1)),
        key=lambda o: abs(o[0]) + abs(o[1]))
    for dx, dy in offsets:
        if dx or dy:
            m = np.float32([[1, 0, dx], [0, 1, dy]])
            shifted = cv2.warpAffine(current, m, (w, h),
                                     borderValue=(255, 255, 255))
        else:
            shifted = current
        sat_cur = cv2.cvtColor(shifted, cv2.COLOR_BGR2HSV)[:, :, 1]
        gray_cur = cv2.cvtColor(shifted, cv2.COLOR_BGR2GRAY)
        mask = ((sat_ref <= CONTENT_SAT_REF)
                & (sat_cur <= CONTENT_SAT_CUR)).astype(np.uint8)
        mask = cv2.erode(mask, np.ones((5, 5), np.uint8))
        picked = mask.astype(bool)
        if picked.mean() < CONTENT_MIN_MASK_FRACTION:
            continue
        ref_vals = gray_ref[picked].astype(np.float64)
        cur_vals = gray_cur[picked].astype(np.float64)
        bg_ref = np.median(ref_vals)
        bg_cur = np.median(cur_vals)
        struct = ref_vals < bg_ref - CONTENT_REL_MARGIN
        if int(struct.sum()) < CONTENT_MIN_STRUCT:
            continue
        cur_struct = cur_vals[struct]
        kept = ((cur_struct < bg_ref - CONTENT_KEEP_MARGIN)
                & (cur_struct < bg_cur - CONTENT_KEEP_MARGIN))
        score = float(kept.mean())
        if score < CONTENT_MATCH_MIN:
            continue
        ref_contrast = bg_ref - np.percentile(ref_vals, 2)
        cur_contrast = bg_cur - np.percentile(cur_vals, 2)
        if ref_contrast <= 0 \
                or cur_contrast < ref_contrast * CONTENT_CONTRAST_KEEP:
            continue
        return True
    return False


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


#: The failure_tolerance value ui/app.py applies specifically to Patches.
#: Measurement and reasoning live on BoardWatch.failure_tolerance itself -
#: this is just the number, kept next to the class it configures rather than
#: hidden inside the UI layer.
#: ui/app.py 專門套用在拼塊上的 failure_tolerance 值。量測依據跟理由都寫在
#: BoardWatch.failure_tolerance 自己身上——這裡只是那個數字，跟它設定的
#: class 放在一起，不要藏在 UI 層裡面。
#:
#: RAISED 2 -> 6 on 2026-08-06, from a real aborted run 從一次真實中止的執行
#: 提高：
#: A real 7x7 puzzle (session log + screen recording, 2026-08-06) solved
#: into just 6 rectangles, FOUR of them full-width rows - unlike every
#: existing Patches fixture (10-14 rects, none full-width; see
#: tests/test_board_guard.py). Reproduced directly against the real
#: captured frames: with only 2 of those 6 rows filled, detect_grid_size
#: (with the mask_saturated fallback) failed 3 checks in a row and the
#: guard aborted a plan that was still correctly in progress - the user
#: went on to solve the same board by hand with no problem. Worse: even
#: the PRISTINE frame (0 filled) failed to locate on 1 of 20 near-identical
#: re-captures (tiny per-pixel noise only) - this puzzle's margin is thin
#: even before anything is drawn. 6 covers this exact puzzle's full plan
#: even in the worst case where NO check after the first ever recovers.
#: This is deliberately NOT unlimited: a genuinely replaced board is still
#: caught once persistent failure exceeds 6, and every fixture surveyed
#: (10-14 rects, no full-width rows) is far less likely to lose enough
#: grid-line visibility to need anywhere near this many in a row.
#: 一個真實的 7x7 題目（執行記錄 + 螢幕錄影，2026-08-06）解出來只有
#: 6 塊矩形，其中 4 塊是貫穿全寬的整列——這跟現有的每一張 Patches 測試圖
#: 都不一樣（10~14 塊，沒有任何一塊貫穿全寬；見 test_board_guard.py）。
#: 直接對著真實擷取的畫面重現：那 6 塊裡只填了 2 塊，`detect_grid_size`
#: （含遮色備援）就連續 3 次檢查失敗，守衛把一個其實還在正常進行的計畫
#: 中止了——使用者後來手動接著解完，完全沒問題。更糟的是：連「完全空白」
#: 的畫面，對 20 次幾乎相同的重新擷取（只有極微小的像素雜訊），都有 1 次
#: 定位失敗——這道題目的容錯空間，在還沒開始畫任何東西之前就已經很薄。
#: 6 這個數字，讓「這道題目」完整跑完整條計畫，就算「除了第一次以外的
#: 每一次檢查都失敗」這種最壞情況也撐得住。刻意不設成無限制：真的被換掉
#: 的棋盤，只要持續失敗超過 6 次還是抓得到；而調查過的每一張既有測試圖
#: （10~14 塊、沒有貫穿全寬的）都遠不容易在連續格線可見度上輸到需要
#: 撐這麼多次。
PATCHES_FAILURE_TOLERANCE = 6


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

    #: How many CONSECUTIVE real structural-detection failures to tolerate
    #: before concluding the board is actually gone. 0 (the default) is the
    #: original strict behaviour: any failure aborts immediately.
    #: 連續幾次「真正的結構偵測失敗」可以被容忍，才會判定棋盤真的不見了。
    #: 預設 0 是原本嚴格的行為：任何一次失敗就立刻中止。
    #:
    #: WHY THIS EXISTS 為什麼需要這個:
    #:   Patches tiles the WHOLE board, so once enough drawn regions touch the
    #:   board's own edges, detect_grid_size can stay broken for the REST of a
    #:   fill even though the board never actually moved (see mask_saturated
    #:   in core/board.py for the underlying cause, and CHANGELOG's 1.2.0 entry
    #:   for the measured evidence). An earlier fix skipped the guard for a
    #:   FIXED position - the last two rectangles of a Patches plan - which
    #:   only helps if THAT specific puzzle's edge-touching regions happen to
    #:   be drawn last. Measured directly on a real capture: they are not -
    #:   one of the two edge-touching regions in a real 6-rectangle puzzle was
    #:   drawn SECOND, not fifth or sixth. A position-based skip could not have
    #:   protected that run at all.
    #:   拼塊會鋪滿整個棋盤，一旦夠多已畫的區塊碰到棋盤自己的邊緣，
    #:   detect_grid_size 可能會在填答「剩下的全部時間」都保持失效，即使棋盤
    #:   根本沒有真的移動過（根本原因見 core/board.py 的 mask_saturated，
    #:   量測依據見 CHANGELOG 的 1.2.0 條目）。先前的修法是對「固定位置」
    #:   （拼塊計畫的最後兩塊矩形）關閉保護——這只在「這一題」剛好把碰邊的
    #:   區塊排在最後時才有用。直接用一張真實擷取量過：並不是這樣——
    #:   一個真實 6 塊矩形的拼塊裡，兩塊碰邊的區塊其中一塊是**第二個**畫的，
    #:   不是第五或第六個。用位置判斷的做法，對那一次執行完全沒有保護作用。
    #:
    #:   Tolerating N consecutive failures instead is layout-independent: it
    #:   reacts to OBSERVED persistent failure wherever it happens, not to a
    #:   guess about where it will happen. It also keeps a real backstop that
    #:   the position-based skip did not have - a genuine board replacement
    #:   still gets caught once it has failed more than N times in a row,
    #:   wherever in the plan that occurs, instead of never being checked at
    #:   all during a hard-coded tail.
    #:   改成容忍連續 N 次失敗則跟版面無關：它是對「觀察到的持續失敗」
    #:   做反應，不管發生在哪裡，而不是用猜的去猜會發生在哪裡。這樣做也保留了
    #:   位置判斷法沒有的真正防線——真的棋盤被換掉，只要連續失敗超過 N 次
    #:   一樣會被抓到，不管發生在計畫的哪個位置，而不是在寫死的尾段完全不檢查。
    #:
    #:   VALUE MEASURED, NOT GUESSED 數值是量出來的，不是猜的:
    #:   on the real capture above, the failure window lasted ~2.4s against a
    #:   ~1.6s average time between drag-entry checks - about 2 consecutive
    #:   checks. 2 is applied only to Patches, from app.py, matching the
    #:   user-approved trade-off this replaces: a LIMITED, documented
    #:   reopening of the guard's blind spot, not an unlimited one.
    #:   在上面那次真實擷取裡，失效的時間窗大約 2.4 秒，對照每次拖曳前檢查
    #:   平均間隔約 1.6 秒——大約是連續 2 次檢查。2 這個值只套用在拼塊，
    #:   從 app.py 設定，維持跟它取代的那個做法一樣、經使用者同意的取捨：
    #:   保護的盲點被有限度、有記錄地重新打開一小段，不是無限制打開。
    failure_tolerance: int = 0

    #: Enable the reference-content fallback (Patches only - see the
    #: CONTENT_* constants above for the measurements). When the locator
    #: fails, the un-painted content is compared against `reference`
    #: instead of blindly consuming the failure tolerance:
    #: match -> keep going (counter resets), mismatch -> abort IMMEDIATELY
    #: (faster than the tolerance path catches a real replacement),
    #: cannot-judge -> the original tolerance counting, unchanged.
    #: 啟用參考內容備援（僅拼塊——量測依據見上方 CONTENT_* 常數）。定位器
    #: 失敗時，改拿沒被填色的內容跟 `reference` 比對，而不是盲目消耗容忍
    #: 次數：吻合 -> 繼續（計數歸零）、不吻合 -> 「立刻」中止（比容忍路徑
    #: 更快抓到真的被換掉）、無法判斷 -> 走原本的容忍計數，完全不變。
    use_content_check: bool = False
    #: The armed frame's board crop, kept for the content check. Only stored
    #: when use_content_check is on.
    #: 武裝當下那一幀的棋盤裁切，留給內容比對用。只在 use_content_check
    #: 開啟時保存。
    reference: object = None
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
    _consecutive_failures: int = field(default=0)

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
        if self.armed and self.use_content_check:
            # Kept as-is (a copy), never re-derived: this is the ground truth
            # the plan itself was built from.
            # 原封不動保存（複本）、絕不重新推算：這就是計畫本身所依據的真值。
            self.reference = board_image.copy()
        if not self.armed:
            self.reason = ("board watch disabled: locator could not find the board in "
                           "the plan's own frame / 中途保護未啟用：定位器在計畫自己的"
                           "畫面裡就找不到棋盤")
        action_log.log("GUARD", f"arm: n={self.n} tolerance={self.failure_tolerance} "
                        f"-> {'armed' if self.armed else 'FAILED: ' + self.reason}")
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
            action_log.log("GUARD", f"check #{self._checks}: capture failed -> gone: "
                            f"{type(exc).__name__}: {exc}")
            return False
        image = getattr(shot, "image", shot)
        if self.locate(image, self.n) is None:
            # Before consuming tolerance blindly, ask the reference-content
            # check (Patches only). AFFIRMATIVE-ONLY: a match is positive
            # evidence the board is still ours, so the counter resets; ANY
            # other outcome falls through to the original tolerance counting
            # completely unchanged - never to an immediate abort. See the
            # CONTENT_* constants for the measurements and for the
            # adversarial counter-example that killed the immediate-abort
            # variant of this branch.
            # 在盲目消耗容忍次數之前，先問參考內容比對（僅拼塊）。只做正面
            # 認證：吻合是「棋盤還是我們的」的正面證據，計數歸零；「任何」
            # 其他結果都原封不動落回原本的容忍計數——絕不落到立即中止。
            # 量測依據、以及否決掉「立即中止」版本的對抗性反例，見
            # CONTENT_* 常數的說明。
            if self.use_content_check and self.reference is not None:
                # An exception inside the affirmation is treated as a
                # decline, never a crash - the guard's failure direction
                # must always be "fall back to the old path", and a raise
                # here would otherwise propagate through driver.guard into
                # the plan run. Unreachable with production frames (mss
                # always hands back same-shape uint8 BGR), so this only
                # hardens against the unexpected.
                # 認證內部的例外一律當成「拒絕認證」，絕不當機——守衛的
                # 失敗方向永遠必須是「退回舊路徑」，否則這裡拋出的例外會
                # 穿過 driver.guard 傳進填答流程。正式畫面碰不到這種情況
                # （mss 回傳的一定是同形狀的 uint8 BGR），這裡只是對
                # 預期外狀況的加固。
                try:
                    affirmed = reference_content_matches(self.reference, image)
                except Exception as exc:
                    affirmed = False
                    action_log.log("GUARD", f"check #{self._checks}: content check "
                                    f"raised {type(exc).__name__}: {exc} -> treated "
                                    f"as declined")
                if affirmed:
                    self._consecutive_failures = 0
                    action_log.log("GUARD", f"check #{self._checks}: locate failed, "
                                    f"but the reference content still matches -> ok")
                    return True
            self._consecutive_failures += 1
            if self._consecutive_failures <= self.failure_tolerance:
                # Tolerated: report "still there" without latching _gone, so a
                # failure that recovers on the NEXT real check (this counter
                # resets below) never trips the guard at all. Only sustained,
                # back-to-back failure past the tolerance is treated as real.
                # 容忍：回報「還在」，不鎖定 _gone，所以只要下一次真正檢查
                # 恢復正常（下面會把這個計數器歸零），就完全不會觸發保護。
                # 只有持續、連續超過容忍次數的失敗才會被當真。
                # Logged even though it is tolerated - this is exactly the
                # kind of near-miss that used to be completely invisible;
                # see the module docstring on WHY every check is logged.
                # 就算是被容忍的也要記錄——這正是以前完全看不到的驚險時刻；
                # 為什麼每一次檢查都要記錄，見模組文件字串。
                action_log.log("GUARD", f"check #{self._checks}: locate failed, "
                                f"TOLERATED ({self._consecutive_failures}/{self.failure_tolerance})")
                return True
            self._gone = True
            self.last_image = image
            self.reason = ("board is no longer where it was - stopping so the "
                           "remaining clicks do not land on something else / "
                           "棋盤已不在原處，停止動作以免剩下的點擊落在別的東西上")
            action_log.log("GUARD", f"check #{self._checks}: locate failed persistently "
                            f"({self._consecutive_failures} in a row) -> gone")
            return False
        self._consecutive_failures = 0
        action_log.log("GUARD", f"check #{self._checks}: ok")
        return True

    def checks_made(self) -> int:
        return self._checks


def attach(driver, mapper, result, image: np.ndarray) -> BoardWatch:
    """Arm a BoardWatch for this plan and wire it into driver.guard.
    Always returns the watch, armed or not, so the caller can log
    watch.reason and inspect watch.last_image after an abort.
    替這次計畫掛上一個 BoardWatch，並接進 driver.guard。不管有沒有成功
    掛上都會回傳這個 watch，讓呼叫端可以記錄 watch.reason、在中止後
    檢查 watch.last_image。

    WHY THIS IS SHARED, NOT INLINED PER CALLER 為什麼共用而不是各自寫一份:
    Measured on a scripted screen where the board is replaced after 3
    actions: the GUI path (which had this wiring inline) stopped after 3 of
    28 actions; the CLI's `--go` path (which never had it at all) ran all 28,
    25 of them onto the replaced board. `--go` is the closest thing this
    project has to "five puzzles fully automatically", and it was the one
    path that ran blind - not because the guard doesn't work for it, but
    because nothing ever called it. One shared function that every caller
    goes through is what makes a THIRD caller unable to forget this again.
    對一個腳本化的畫面實測：盤面在第 3 個動作後被換掉——GUI 路徑（這段接線
    是寫在它自己裡面的）在 28 個動作裡走了 3 個就停；CLI 的 `--go` 路徑
    （從來沒有接過這段）28 個全部走完，25 個點在被換掉的盤面上。`--go`
    是這個專案最接近「五題全自動」的東西，卻是唯一盲目執行的路徑——不是
    因為保護對它不管用，是因為根本沒有人呼叫過它。讓每個呼叫端都走同一個
    共用函式，才能讓「第三個呼叫者」不會再忘記接這段。
    """
    bx, by, bw, bh = result.grid.board_bbox
    # Patches tiles the whole board, so the guard's own detection can go on
    # failing for the rest of a fill even though the board never moved - see
    # BoardWatch.failure_tolerance for the measurement. Every other puzzle
    # keeps the strict default (0).
    # 拼塊會鋪滿整個棋盤，保護自己的偵測可能在填答剩下的過程中持續失效，
    # 即使棋盤根本沒有移動過——量測依據見 BoardWatch.failure_tolerance。
    # 其他每一款謎題都維持嚴格的預設值（0）。
    is_patches = result.puzzle_key == patches.KEY
    tolerance = PATCHES_FAILURE_TOLERANCE if is_patches else 0
    # Patches also gets the reference-content affirmation: the 2026-08-09
    # real failure showed 7 STRAIGHT locate failures on an unmoved board -
    # exceeding this very tolerance - because our own fills erase the grid
    # lines for good. Content matching is affirmative evidence the board is
    # still ours, so it resets the counter instead of consuming it. It can
    # ONLY extend a correct fill's life - anything it cannot affirm goes
    # through the exact tolerance path that exists today, so no replacement
    # scenario is ever handled worse than before. Every other puzzle keeps
    # the exact original behaviour.
    # 拼塊同時啟用參考內容認證：2026-08-09 的真實失敗顯示，一個沒動過的
    # 棋盤讓定位「連續」失敗了 7 次——超過這個容忍度本身——因為我們自己的
    # 填色把格線永久抹掉了。內容吻合是「棋盤還是我們的」的正面證據，所以
    # 它把計數歸零而不是消耗它。它「只可能」延長一次正確填答的壽命——
    # 任何它無法認證的情況，都走今天本來就存在的那條容忍路徑，所以沒有
    # 任何被替換情境會被處理得比以前差。其他每一款謎題維持完全原本的行為。
    watch = BoardWatch(mapper=mapper, n=result.grid.n, failure_tolerance=tolerance,
                       use_content_check=is_patches)
    action_log.log("GUARD", f"attach: puzzle={result.puzzle_key} n={result.grid.n} "
                    f"tolerance={tolerance} content_check={is_patches}")
    if watch.arm(image[by : by + bh, bx : bx + bw]):
        driver.guard = watch.still_there
    return watch
