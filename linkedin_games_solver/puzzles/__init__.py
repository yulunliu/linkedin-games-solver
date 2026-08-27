"""
Puzzle registry and the recognition pipeline that wraps every solver.
謎題註冊表，以及包在每個求解器外面的辨識流程。

Each puzzle module exposes `solve(image, n_hint) -> SolveResult`. This package
adds the robustness layer that all of them need:
每個謎題模組提供 `solve(image, n_hint) -> SolveResult`。這個套件則加上
它們共同需要的強健化處理：

  1. SCALE NORMALISATION - rescale so the board is ~800px before recognising.
     Thresholds and digit templates were calibrated on phone screenshots where
     the board is about that size. A browser board can be any size, and
     recognising at the wrong scale is unreliable: Patches read its labels
     correctly at board widths of 506px and 635px but misread them in between.
     Normalising first makes every size behave the same.
     尺度正規化 —— 辨識前先縮放到棋盤約 800px。
     各種門檻與數字範本都是在棋盤約這個大小的手機截圖上校準的。網頁棋盤大小
     不一定，用錯尺度辨識並不可靠：實測 Patches 在棋盤 506px 與 635px 時讀得
     正確，中間的尺寸卻會讀錯。先正規化就能讓所有尺寸表現一致。

  2. PROGRESSIVE CENTRE CROPPING - if the capture region is much larger than the
     board, crop tighter and retry. Tango's borderless detection in particular
     degrades when there is a lot of surrounding page content.
     漸進式置中裁切 —— 擷取範圍比棋盤大很多時，往中間裁緊再試。
     Tango 沒有外框的定位在周圍雜訊多時特別容易失準。

  3. RE-NORMALISE AFTER SUCCESS - succeeding is not the same as being correct.
     A board recognised at the wrong scale can yield a plausible but WRONG
     answer, so after any success we redo recognition at the normalised scale
     and prefer that result.
     成功之後再正規化重算 —— 「解出來了」不等於「解對了」。在錯誤尺度下辨識
     可能得到「看似合理但錯誤」的答案，所以任何一次成功之後都會用正規化尺度
     重算一次，並以重算結果為準。
"""

from __future__ import annotations

from typing import Callable

import cv2
import numpy as np

from ..core import SolveResult, action_log, build_cell_boxes, detect_type, failure
from ..core.board import BoardGrid, find_board_bbox, find_board_by_grid_lines
from . import patches, queens, sudoku, tango, zip_path

#: key -> module. Order is the order shown in the UI.
#: 鍵 -> 模組。順序就是介面上顯示的順序。
PUZZLES = {
    tango.KEY: tango,
    queens.KEY: queens,
    sudoku.KEY: sudoku,
    zip_path.KEY: zip_path,
    patches.KEY: patches,
}
DISPLAY_ORDER = list(PUZZLES)

#: Board size the recognition thresholds were calibrated at.
#: 辨識門檻校準時的棋盤大小。
TARGET_BOARD_PIXELS = 794
#: Recommended minimum board size; below this Patches' small digits blur out.
#: 建議的棋盤最小邊長；低於這個大小 Patches 的小數字會糊掉。
MIN_BOARD_PIXELS = 500

_PRESCALE_STEPS = (1.0, 1.75, 2.5)
_CROP_FRACTIONS = (1.0, 0.85, 0.72, 0.6, 0.5)

#: Crops used when re-trying the OTHER puzzle types after the detected one has
#: already failed the full ladder. Deliberately short: the full ladder for every
#: type turned a failing 1920x1080 capture into 78s of work, and by this point
#: the odds are already poor. Measured - these two rungs recover every
#: type-misdetection in the fixture set at about a fifth of the cost.
#: 判斷出來的類型已經跑完整條階梯還失敗之後，改試其他類型時用的裁切。
#: 刻意很短：對每個類型都跑完整階梯，會讓一張失敗的 1920x1080 擷取花掉 78 秒，
#: 而走到這一步時本來勝算就不高。實測這兩層就能救回測試素材裡所有的類型誤判，
#: 成本只有約五分之一。
_FALLBACK_CROPS = (1.0, 0.72)


def puzzle_name(key: str, language: str = "zh") -> str:
    module = PUZZLES.get(key)
    if module is None:
        return key
    return module.NAME_EN if language == "en" else module.NAME_ZH


#: Never work on an image wider or taller than this. Upscaling cannot add
#: information, so enlarging an already-large capture only costs time: measured,
#: a 1920x1080 capture taken to the 2.5x prescale becomes 4800x2700 and the
#: ladder spends 26-30s on it. The board itself is what needs to reach
#: TARGET_BOARD_PIXELS, and if the board is already large the prescale has
#: nothing to do.
#: 絕不在超過這個尺寸的影像上工作。放大不會增加資訊，
#: 把本來就很大的擷取再放大只是浪費時間：實測 1920x1080 被 2.5 倍預放大之後
#: 變成 4800x2700，階梯要花 26~30 秒。需要達到 TARGET_BOARD_PIXELS 的是「棋盤」，
#: 棋盤本來就夠大時預放大根本無事可做。
MAX_WORKING_PIXELS = 2600


def _effective_factor(image: np.ndarray, factor: float) -> float:
    """The factor that will ACTUALLY be applied, after the working-size cap.
    套用工作尺寸上限之後「實際會用」的倍率。

    THE CAP AND THE COORDINATE MAPPING MUST AGREE. _scaled used to clamp the
    factor privately and throw the real value away, while _rescale_grid mapped
    the answer back using the UNCLAMPED one. Measured on a 500px board centred
    on an 870x1882 canvas: ok=True, but the reported board was (162,601,436,437)
    against a true (185,691,500,500) - 1.6 cells out vertically, and those are
    the coordinates the mouse would have used.
    上限與座標換算必須一致。_scaled 原本是私下把倍率夾住、把真正的值丟掉，
    而 _rescale_grid 卻用「沒夾住」的倍率把答案換算回去。
    實測：500px 的棋盤置中在 870x1882 的畫布上，回報 ok=True，
    但棋盤位置是 (162,601,436,437) 而真值是 (185,691,500,500) ——
    垂直差 1.6 格，而那正是滑鼠會用的座標。
    """
    if factor <= 1.0:
        return factor
    side = max(image.shape[0], image.shape[1])
    if side <= 0 or side * factor <= MAX_WORKING_PIXELS:
        return factor
    return max(1.0, MAX_WORKING_PIXELS / side)


def _scaled(image: np.ndarray, factor: float) -> np.ndarray:
    factor = _effective_factor(image, factor)
    if abs(factor - 1.0) < 1e-6:
        return image
    interpolation = cv2.INTER_CUBIC if factor > 1 else cv2.INTER_AREA
    return cv2.resize(image, None, fx=factor, fy=factor, interpolation=interpolation)


def _center_crop(image: np.ndarray, fraction: float):
    if fraction >= 1.0:
        return image, (0, 0)
    h, w = image.shape[:2]
    nw, nh = int(w * fraction), int(h * fraction)
    ox, oy = (w - nw) // 2, (h - nh) // 2
    return image[oy : oy + nh, ox : ox + nw], (ox, oy)


def _locate_board(image: np.ndarray):
    """Find the board, pre-scaling if its faint border is missed at 1x.
    找出棋盤；淡色邊框在原尺寸抓不到時先放大再找。"""
    for prescale in _PRESCALE_STEPS:
        candidate = _scaled(image, prescale)
        bbox = find_board_bbox(candidate)
        if bbox is None:
            found = find_board_by_grid_lines(candidate)
            bbox = found[0] if found else None
        if bbox is not None:
            return prescale, bbox
    return None


def _rescale_grid(grid: BoardGrid, factor: float, offset=(0, 0)) -> BoardGrid:
    """Map grid coordinates back to the original image.
    把棋盤座標換算回原始影像。"""
    ox, oy = offset
    if abs(factor - 1.0) < 1e-6 and ox == 0 and oy == 0:
        return grid
    x, y, w, h = grid.board_bbox
    bbox = (round(x / factor) + ox, round(y / factor) + oy, round(w / factor), round(h / factor))
    return BoardGrid(n=grid.n, board_bbox=bbox, cell_boxes=build_cell_boxes(bbox, grid.n))


def _solve_as(image: np.ndarray, key: str, n_hint: int | None) -> SolveResult:
    """Run one puzzle module, turning any exception into a readable failure.
    跑一個謎題模組，把任何例外轉成可讀的失敗訊息。"""
    module = PUZZLES.get(key)
    if module is None:
        return SolveResult(ok=False, puzzle_key=key, error=f"unsupported puzzle / 不支援的謎題: {key}")
    try:
        return module.solve(image, n_hint)
    except ValueError as exc:
        return SolveResult(ok=False, puzzle_key=key, error=f"recognition failed / 辨識失敗: {exc}")
    except Exception as exc:  # noqa: BLE001 - surface any failure as a readable message
        return SolveResult(ok=False, puzzle_key=key, error=f"{type(exc).__name__}: {exc}")


def _attempt(image: np.ndarray, puzzle_key: str | None, n_hint: int | None) -> SolveResult:
    """Solve, falling back to the other puzzle types if the detected one fails.
    求解；判斷出來的類型失敗時，改試其他類型。

    WHY the fallback 為什麼要有備援:
      detect_type reasons about colour statistics over the board region, and
      when it cannot locate the board it falls back to the WHOLE image. A board
      that is a small part of a large capture then has its colour diluted:
      measured on a 1920x1080 capture whose Tango board is 390px wide, the
      coloured-pixel ratio is 0.00186 against a 0.006 threshold, so it is filed
      as Sudoku. Everything downstream then fails with "board not found", which
      tells the user nothing about the real problem.
      detect_type 是對棋盤區域的顏色統計做推論，而當它定位不到棋盤時，
      會退回用「整張圖」。棋盤只佔大擷取範圍一小塊時，顏色就被稀釋：
      實測一張 1920x1080、Tango 棋盤寬 390px 的擷取，彩色像素比例是 0.00186，
      門檻是 0.006，於是被歸成 Sudoku。接下來整條路都會失敗在「找不到棋盤」，
      而那個訊息完全沒告訴使用者真正的問題。

      Trying the others costs one solve attempt each and is safe, because every
      module carries its own guards: Queens checks its colour regions are
      exactly n and contiguous, Patches needs at least three labels, Zip needs
      consecutive dot numbers, and Tango, Sudoku and Patches all require a
      unique solution. tests/test_recognition.py asserts that forcing the wrong
      type fails rather than inventing an answer.
      試其他類型每種只多花一次求解，而且是安全的，因為每個模組都自帶守門：
      Queens 檢查色塊剛好 n 塊且連通、Patches 要求至少三個標籤、
      Zip 要求圓點編號連續，而 Tango、Sudoku、Patches 都要求解唯一。
      tests/test_recognition.py 就在驗證「指定錯誤類型會失敗而不是編一個答案」。

    An explicit puzzle_key from the user is honoured exactly - if they say it is
    a Tango board, we do not quietly solve it as something else.
    使用者明確指定的類型會被完全遵守 —— 他說是 Tango，我們就不會偷偷當別的解。
    """
    if puzzle_key:
        return _solve_as(image, puzzle_key, n_hint)
    return _solve_as(image, detect_type(image), n_hint)


def _renormalise(sub, result: SolveResult, factor: float, n_hint):
    """Redo recognition at the calibrated scale and prefer that result.
    用校準尺度重做辨識，並以重算結果為準。

    Succeeding at the wrong scale can silently produce a wrong answer: Tango at
    a ~390px board detected only 1 of its 4 constraint marks, and the solver
    dutifully returned an answer consistent with what it saw. That is worse than
    failing, so we always re-run normalised.
    在錯誤尺度下成功可能悄悄給出錯誤答案：Tango 在棋盤約 390px 時 4 個條件符號
    只抓到 1 個，求解器就照它看到的條件給出答案。這比失敗更糟，所以一律重算。

    BUG FOUND 2026-08-26 發現的問題: the re-attempt below used to be called
    with the caller's ORIGINAL `puzzle_key` parameter, not `result.puzzle_key`
    (the type that just succeeded). In the default auto-detect path
    (puzzle_key=None, e.g. the GUI's "auto" dropdown), _attempt() with a
    falsy puzzle_key runs detect_type() FRESH on the rescaled image instead
    of reusing the type that already succeeded - and detect_type is
    independently documented elsewhere (test_recognition.py) as fragile to
    exactly the kind of perturbation a rescale is. A board that first solved
    as, say, tango could rescale into something detect_type now reads as
    queens; if queens' OWN guards (region count/connectivity, uniqueness)
    happen to pass on the same pixels, `better.ok` is True with
    better.puzzle_key="queens" and THIS function would hand back a
    completely different puzzle's answer with no cross-check that it is even
    the same game - exactly the "succeeding at the wrong [something] can
    silently produce a wrong answer" failure this function's own docstring
    above says it exists to prevent, just one layer up (wrong TYPE instead
    of wrong SCALE). Fixed by forcing the retry to the type that already
    won, never re-detecting.
    2026-08-26 發現的問題：下面的重試呼叫，以前傳的是呼叫端「原始」的
    puzzle_key 參數，不是 result.puzzle_key（剛剛成功的那個類型）。在預設的
    自動判斷路徑下（puzzle_key=None，例如 GUI 的「自動」下拉選單），
    _attempt() 收到假值的 puzzle_key 時，會對縮放後的影像重新跑一次
    detect_type()，而不是沿用已經成功的類型——而 detect_type 已經在別處
    （test_recognition.py）被記錄過，對「縮放」這種擾動本來就脆弱。一個
    原本判定成 tango 並解出來的棋盤，縮放後可能被 detect_type 讀成
    queens；如果 queens「自己的」守門（色塊數量／連通性、唯一性）剛好在
    同一批像素上通過，`better.ok` 就會是 True、`better.puzzle_key` 是
    "queens"，這個函式就會回傳一個完全不同題目的答案，而且完全沒有核對過
    是不是同一款遊戲——正是這個函式自己上面文件字串說要防止的「在錯的
    [什麼] 下成功會悄悄給出錯誤答案」，只是換了一層（錯的「類型」而不是
    錯的「尺度」）。修法：強制重試沿用已經成功的類型，絕不重新判斷。
    """
    detected_width = result.grid.board_bbox[2] if result.grid else 0
    if detected_width <= 0:
        return factor, result
    board_width_in_sub = detected_width / factor
    ideal = TARGET_BOARD_PIXELS / board_width_in_sub
    if abs(ideal - factor) / max(ideal, factor) <= 0.15:
        return factor, result
    ideal = _effective_factor(sub, ideal)
    better = _attempt(_scaled(sub, ideal), result.puzzle_key, n_hint)
    return (ideal, better) if better.ok else (factor, result)


#: Error text for a solve stopped by should_continue - one string so the UI
#: layer can recognise "the user asked for this" instead of "recognition
#: failed" without string-matching a different message per call site.
#: 被 should_continue 中止的求解用的錯誤文字——只有一個字串，讓介面層能
#: 分辨「這是使用者自己要求的」而不是「辨識失敗了」，不用對每個呼叫點
#: 各自比對不同的訊息字串。
CANCELLED = "cancelled / 已取消"


def solve_image(
    image: np.ndarray,
    puzzle_key: str | None = None,
    n_hint: int | None = None,
    should_continue: Callable[[], bool] | None = None,
) -> SolveResult:
    """Recognise and solve. Grid coordinates are relative to the image passed in.
    辨識並求解。回傳的棋盤座標相對於傳入的原始影像。

    should_continue, if given, is polled between ladder rungs - a solve on a
    large capture has no other time budget and Stop could not interrupt it.
    Measured before this: a 4K screen grab took 29-49s, an 8000x8000 one
    238-312s, and none of that time had a check-in point. Not polled inside
    a single OpenCV/OR-Tools call - only between attempts - so this bounds
    the response time to roughly one rung's cost, not the whole ladder's.
    should_continue，如果有給的話，會在階梯的每一階之間被輪詢——對一張大擷取
    求解，以前完全沒有其他時間預算，「停止」也中斷不了。修正前實測：4K
    螢幕擷取要 29~49 秒，8000x8000 要 238~312 秒，這整段時間裡沒有任何
    一個檢查點。不是在單一次 OpenCV／OR-Tools 呼叫「內部」輪詢——只在
    嘗試與嘗試之間——所以回應時間的上限大約是「一階」的成本，不是整條
    階梯的成本。
    """
    action_log.log("SOLVE", f"solve_image start: puzzle_key={puzzle_key or 'auto'} "
                    f"n_hint={n_hint} image={image.shape[1]}x{image.shape[0]}")
    if should_continue is not None and not should_continue():
        action_log.log("STOP", "solve_image cancelled by should_continue before the first attempt")
        return failure(puzzle_key or "unknown", CANCELLED)
    result = _ladder(image, puzzle_key, n_hint, should_continue=should_continue)
    if result.ok or puzzle_key:
        action_log.log("SOLVE", f"solve_image done: ok={result.ok} puzzle={result.puzzle_key} "
                        f"error={result.error!r}")
        return result
    if result.error == CANCELLED:
        return result

    # The whole ladder failed. Before giving up, try the OTHER puzzle types.
    # 整條階梯都失敗了。放棄之前，先試其他謎題類型。
    #
    # WHY 為什麼:
    #   detect_type reasons about colour over the board region, and when it
    #   cannot locate the board it falls back to the WHOLE image. A board that
    #   is a small part of a large capture then has its colour diluted -
    #   measured on a 1920x1080 capture with a 390px Tango board, the coloured
    #   ratio is 0.00186 against a 0.006 threshold, so it is filed as Sudoku and
    #   every attempt afterwards fails with "board not found", which tells the
    #   user nothing about the real problem.
    #   detect_type 是對棋盤區域算顏色，定位不到棋盤時會退回用「整張圖」。
    #   棋盤只佔大擷取範圍一小塊時顏色就被稀釋 —— 實測 1920x1080、棋盤 390px 的
    #   Tango，彩色比例 0.00186 對上門檻 0.006，於是被歸成 Sudoku，
    #   後續每次嘗試都失敗在「找不到棋盤」，完全沒說出真正的問題。
    #
    # It is safe because every module carries its own guards - Queens needs
    # exactly n contiguous colour regions, Patches at least three labels, Zip
    # consecutive dot numbers, and Tango/Sudoku/Patches all require a unique
    # solution. test_wrong_type_does_not_fake_success asserts that forcing the
    # wrong type fails rather than inventing an answer.
    # 這是安全的，因為每個模組都自帶守門 —— Queens 要剛好 n 塊連通色塊、
    # Patches 至少三個標籤、Zip 要編號連續，而 Tango/Sudoku/Patches 都要求解唯一。
    # test_wrong_type_does_not_fake_success 就在驗證「指定錯誤類型會失敗」。
    #
    # AFTER the main ladder, not inside it. Doing it per rung made a 1920x1080
    # capture take 26-33s instead of 7s, because every crop x scale x type
    # combination was tried. Now the cost is only paid when everything else has
    # already failed.
    # 放在主階梯「之後」，不是放在裡面。放在裡面會讓 1920x1080 的擷取從 7 秒
    # 變成 26~33 秒，因為每個「裁切 x 縮放 x 類型」的組合都會被試。
    # 現在這個成本只有在其他全都失敗之後才付。
    detected = result.puzzle_key
    for key in DISPLAY_ORDER:
        if key == detected:
            continue
        if should_continue is not None and not should_continue():
            action_log.log("STOP", "solve_image cancelled by should_continue "
                            "during the fallback-type sweep")
            return failure(detected, CANCELLED, grid=result.grid, info=result.info)
        action_log.log("SOLVE", f"fallback: detected={detected} failed, trying type={key}")
        other = _ladder(image, key, n_hint, fractions=_FALLBACK_CROPS, should_continue=should_continue)
        if other.ok:
            other.info.append(f"detected as {detected}, solved as {key} / "
                              f"判斷成 {detected}，實際以 {key} 解出")
            action_log.log("SOLVE", f"solve_image done: ok=True puzzle={key} "
                            f"(recovered via fallback from {detected})")
            return other
        if other.error == CANCELLED:
            return other
    action_log.log("SOLVE", f"solve_image done: ok=False puzzle={result.puzzle_key} "
                    f"error={result.error!r} (fallback sweep exhausted)")
    return result


def _ladder(image, puzzle_key, n_hint, fractions=None, should_continue=None) -> SolveResult:
    """One pass over the crop x scale ladder for one puzzle type.
    對單一謎題類型跑一遍「裁切 x 縮放」階梯。"""
    last: SolveResult | None = None

    for fraction in (fractions if fractions is not None else _CROP_FRACTIONS):
        if should_continue is not None and not should_continue():
            action_log.log("STOP", f"ladder cancelled before crop={fraction:.0%}")
            return last or SolveResult(ok=False, puzzle_key=puzzle_key or "unknown", error=CANCELLED)
        sub, offset = _center_crop(image, fraction)
        if min(sub.shape[:2]) < 120:
            break

        # Prefer the scale that puts the board at the calibrated size; fall back
        # to plain pre-scales if the board cannot be located yet.
        # 優先用「讓棋盤達到校準尺寸」的縮放；還定位不到棋盤時才退回固定倍率。
        candidates: list[float] = []
        located = _locate_board(sub)
        if located is not None:
            prescale, bbox = located
            candidates.append(prescale * (TARGET_BOARD_PIXELS / bbox[2]))
        candidates.extend(_PRESCALE_STEPS)

        tried: list[float] = []
        for factor in candidates:
            if should_continue is not None and not should_continue():
                action_log.log("STOP", f"ladder cancelled mid crop={fraction:.0%}")
                return last or SolveResult(ok=False, puzzle_key=puzzle_key or "unknown", error=CANCELLED)
            if any(abs(factor - t) < 0.02 for t in tried):
                continue
            tried.append(factor)

            # The cap may reduce the factor; the mapping back must use whatever
            # was actually applied, not what we asked for.
            # 上限可能把倍率調小；換算回去必須用「實際套用」的那個值，不是我們要求的值。
            factor = _effective_factor(sub, factor)
            result = _attempt(_scaled(sub, factor), puzzle_key, n_hint)
            action_log.log("SOLVE", f"attempt: crop={fraction:.0%} factor={factor:.2f} "
                            f"type={puzzle_key or result.puzzle_key} -> "
                            f"{'OK' if result.ok else 'FAIL: ' + str(result.error).splitlines()[0]}")
            if result.ok:
                factor, result = _renormalise(sub, result, factor, n_hint)
                result.grid = _rescale_grid(result.grid, factor, offset)
                # The overlay was drawn on a scaled/cropped copy, so it no longer
                # matches the caller's image; render_overlay redraws it.
                # 疊圖是畫在縮放/裁切過的複本上，跟呼叫端的影像對不上；
                # 需要時由 render_overlay 重新繪製。
                result.overlay = None
                notes = []
                if fraction < 1.0:
                    notes.append(f"crop {fraction:.0%} / 裁切")
                if abs(factor - 1.0) > 0.02:
                    notes.append(f"scale {factor:.2f}x / 縮放")
                if notes:
                    result.info.append("(" + ", ".join(notes) + ")")
                return result
            last = last or result

    if last is None:
        last = SolveResult(ok=False, puzzle_key=puzzle_key or "unknown",
                           error="board not found / 找不到棋盤")

    # Board too small is by far the most common cause; say so explicitly.
    # Try both locators, exactly as _locate_board does above - find_board_bbox
    # alone structurally CANNOT see Tango (it has no outer border), so every
    # Tango failure used to get "board too small / not found" tacked on
    # regardless of the real cause, because bbox was always None for it.
    # 棋盤太小是最常見的原因，直接講明。跟上面的 _locate_board 一樣兩種
    # 定位器都試——單用 find_board_bbox 結構上就看不到 Tango（它沒有外框），
    # 所以以前不管真正原因是什麼，每一次 Tango 失敗都會被硬加上
    # 「棋盤太小／找不到」，因為 bbox 對它來說永遠是 None。
    bbox = find_board_bbox(image)
    if bbox is None:
        found = find_board_by_grid_lines(image)
        bbox = found[0] if found else None
    board_px = bbox[2] if bbox else None
    if board_px is None or board_px < MIN_BOARD_PIXELS:
        hint = (f"board is only ~{board_px}px / 棋盤只有約 {board_px}px" if board_px
                else "no board found / 畫面上找不到棋盤")
        last.error = (
            f"{last.error}\n{hint}. Zoom in with Ctrl + "
            f"(recommend >= {MIN_BOARD_PIXELS}px) / 建議放大頁面後再試。"
        )
    return last


def render_overlay(image: np.ndarray, result: SolveResult) -> np.ndarray | None:
    """Draw the answer on the caller's image using the mapped-back grid.
    用換算回原尺度的棋盤座標，把答案畫在呼叫端的影像上。"""
    if not result.ok or result.grid is None:
        return None
    module = PUZZLES.get(result.puzzle_key)
    if module is None:
        return None
    grid, data = result.grid, result.data
    try:
        if result.puzzle_key == queens.KEY:
            return module.draw_overlay(image, grid, data["queens"])
        if result.puzzle_key == tango.KEY:
            return module.draw_overlay(image, grid, data["solution"], data["current"])
        if result.puzzle_key == sudoku.KEY:
            return module.draw_overlay(image, grid, data["solution"], data["givens"])
        if result.puzzle_key == zip_path.KEY:
            return module.draw_overlay(image, grid, data["path"])
        if result.puzzle_key == patches.KEY:
            return module.draw_overlay(image, grid, data["labels"], data["rects"])
    except Exception:
        return None
    return None


__all__ = ["PUZZLES", "DISPLAY_ORDER", "solve_image", "render_overlay", "puzzle_name",
           "MIN_BOARD_PIXELS", "TARGET_BOARD_PIXELS"]
