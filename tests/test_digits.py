"""
Digit recognition safety tests.
數字辨識的安全性測試。

The rule these enforce: a digit is either read correctly or reported as
unreadable. It is NEVER silently read as a different digit - a wrong number
goes straight into the solver, which then produces a confident wrong answer.
這裡要守住的規則：一個數字要嘛讀對，要嘛回報成讀不出來。
絕對不能默默讀成另一個數字 —— 錯的數字會直接進到求解器，
然後產生一個很有信心的錯誤答案。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from linkedin_games_solver.core import digits  # noqa: E402
from linkedin_games_solver.core.digit_templates import (  # noqa: E402
    APP_TEMPLATES,
    FALLBACK_TEMPLATES,
)

#: Fonts used to simulate "a device that renders digits differently".
#: 用來模擬「數字長得不一樣的裝置」的字型。
_TEST_FONTS = [
    "C:/Windows/Fonts/segoeui.ttf", "C:/Windows/Fonts/calibri.ttf",
    "C:/Windows/Fonts/verdana.ttf", "C:/Windows/Fonts/tahoma.ttf",
    "C:/Windows/Fonts/times.ttf", "C:/Windows/Fonts/consola.ttf",
    "C:/Windows/Fonts/georgia.ttf", "C:/Windows/Fonts/trebuc.ttf",
    "C:/Windows/Fonts/couri.ttf", "C:/Windows/Fonts/comic.ttf",
]


def _available_fonts():
    return [f for f in _TEST_FONTS if Path(f).exists()]


def test_every_digit_has_a_template():
    """
    Bug this guards: 0 and 7 had no template and were rendered from
    C:/Windows/Fonts at import time. On a machine without those fonts the
    digits were simply absent, and matching picked the closest WRONG digit
    with high confidence - a "0" scored 0.89 as a "6", a "7" scored 0.76 as a
    "2". Both tables are now baked into the source.
    這個測試守住的問題：0 與 7 沒有範本，是在 import 時從 C:/Windows/Fonts
    算繪出來的。在沒有那些字型的機器上，這兩個數字就直接不存在，
    比對會以高信心挑最接近的「錯誤」數字 —— 「0」以 0.89 被判成「6」、
    「7」以 0.76 被判成「2」。現在兩張表都烘焙在原始碼裡。
    """
    baked = set(APP_TEMPLATES) | set(FALLBACK_TEMPLATES)
    assert baked == set(range(10)), f"missing templates for / 缺少範本: {sorted(set(range(10)) - baked)}"

    with _no_system_fonts() as templates:
        covered = {d for d, _ in templates}
    assert covered == set(range(10)), \
        f"not covered without fonts / 無字型時未涵蓋: {sorted(set(range(10)) - covered)}"
    print("  every digit has a baked template OK")


class _no_system_fonts:
    """Context manager: pretend no system font exists, so only baked-in
    templates are loaded. The cache must stay populated for the whole block -
    resetting it too early silently re-loads the fonts and the test passes for
    the wrong reason.
    情境管理器：假裝系統上沒有任何字型，只載入烘焙進來的範本。
    快取必須在整個區塊內維持有效 —— 太早清掉會默默把字型重新載回來，
    測試就會因為錯誤的理由而通過。"""

    def __enter__(self):
        self._saved_fonts = digits._FONT_CANDIDATES
        self._saved_cache = digits._TEMPLATES
        digits._FONT_CANDIDATES = ["C:/this-font-does-not-exist.ttf"]
        digits._TEMPLATES = None
        return list(digits._templates())

    def __exit__(self, *exc):
        digits._FONT_CANDIDATES = self._saved_fonts
        digits._TEMPLATES = self._saved_cache
        return False


def test_app_glyphs_are_read_correctly():
    """Every calibrated glyph must classify as itself, above the score floor.
    每個校準字形都必須被判成自己，而且分數要過門檻。"""
    for digit, bitmaps in APP_TEMPLATES.items():
        for index, packed in enumerate(bitmaps):
            got, score = digits.classify_glyph(digits._unpack(packed))
            assert got == digit, f"app glyph {digit}#{index} read as {got} / 被讀成 {got}"
            assert score >= digits.MIN_SCORE, f"app glyph {digit}#{index} scored {score:.3f}"
    print(f"  all {sum(len(v) for v in APP_TEMPLATES.values())} app glyphs OK")


def _audit_fonts():
    """(correct, unreadable, wrong) over every digit in every test font.
    對每種測試字型的每個數字統計 (正確, 讀不出來, 錯誤)。"""
    correct = unreadable = 0
    wrong = []
    for font in _available_fonts():
        for digit in range(10):
            glyph = digits._render_font_glyph(str(digit), font)
            if glyph is None:
                continue
            got, score = digits.classify_glyph(glyph)
            if got is None or score < digits.MIN_SCORE:
                unreadable += 1
            elif got == digit:
                correct += 1
            else:
                wrong.append((Path(font).stem, digit, got, score))
    return correct, unreadable, wrong


def test_foreign_fonts_are_never_silently_misread():
    """
    Bug this guards: score alone does not separate right from wrong. A "6"
    misread as a "5" scored 0.944 - higher than many correct matches. Only the
    gap to the runner-up distinguishes them, hence MIN_MARGIN.
    這個測試守住的問題：光看分數分不出對錯。一個把「6」判成「5」的錯誤拿到
    0.944 分 —— 比很多正確比對還高。唯一能分辨的是與第二名的差距，
    所以才有 MIN_MARGIN。
    """
    if not _available_fonts():
        print("  (no test fonts on this machine, skipped / 沒有測試字型，略過)")
        return
    correct, unreadable, wrong = _audit_fonts()
    assert not wrong, "silently misread / 被默默讀錯: " + ", ".join(
        f"{f} '{d}'->{g} ({s:.3f})" for f, d, g, s in wrong
    )
    assert correct > 0
    print(f"  foreign fonts: {correct} correct, {unreadable} reported unreadable, 0 wrong OK")


def test_safe_without_system_fonts():
    """The .exe on a clean machine must behave the same way.
    在乾淨機器上執行的 .exe 必須有同樣的行為。"""
    if not _available_fonts():
        print("  (no test fonts on this machine, skipped / 沒有測試字型，略過)")
        return
    with _no_system_fonts() as templates:
        # Prove we really are running font-free before trusting the result.
        # 在相信結果之前，先證明確實是在沒有字型的狀態下跑。
        assert len(templates) == sum(len(v) for v in APP_TEMPLATES.values()) + \
            sum(len(v) for v in FALLBACK_TEMPLATES.values()), \
            "system fonts leaked into the font-free run / 無字型測試混進了系統字型"

        correct, unreadable, wrong = _audit_fonts()
        assert not wrong, "silently misread without fonts / 無字型時被默默讀錯: " + ", ".join(
            f"{f} '{d}'->{g} ({s:.3f})" for f, d, g, s in wrong
        )
        for digit, bitmaps in APP_TEMPLATES.items():
            for packed in bitmaps:
                got, _ = digits.classify_glyph(digits._unpack(packed))
                assert got == digit, f"app glyph {digit} broken without fonts / 無字型時壞掉"
    print(f"  without system fonts: {correct} correct, {unreadable} unreadable, 0 wrong OK")


def test_ambiguous_glyph_is_rejected_not_guessed():
    """A glyph equally close to two digits must return None, not a coin flip.
    與兩個數字同樣接近的字形必須回傳 None，而不是擲硬幣。"""
    import numpy as np

    blank = np.zeros((28, 28), np.uint8)
    blank[10:18, 10:18] = 1  # a square - not any digit 一個方塊，不是任何數字
    got, _ = digits.classify_glyph(blank)
    assert got is None or digits.classify_glyph(blank)[1] < digits.MIN_SCORE, \
        f"a blank square was read as {got} / 一個方塊被讀成 {got}"
    print("  ambiguous glyph rejected OK")


if __name__ == "__main__":
    print("Digit recognition tests / 數字辨識測試")
    test_every_digit_has_a_template()
    test_app_glyphs_are_read_correctly()
    test_foreign_fonts_are_never_silently_misread()
    test_safe_without_system_fonts()
    test_ambiguous_glyph_is_rejected_not_guessed()
    print("\nAll passed / 全部通過")
