"""
Python version compatibility tests.
Python 版本相容性測試。

pyproject.toml declares `requires-python = ">=3.9"`. Nothing enforced that, and
v1.0.0 shipped with a `str | None` return annotation that raises TypeError on
import under 3.9 - CI caught it only after publishing. These tests make the
claim checkable on ANY interpreter, so a regression fails locally instead of
in CI.
pyproject.toml 宣告 `requires-python = ">=3.9"`，但沒有任何東西在把關。
v1.0.0 就帶著一個 `str | None` 回傳註記出門，在 3.9 上 import 會丟 TypeError ——
CI 是在發布之後才抓到。這些測試讓那個宣告在**任何**直譯器上都可被檢查，
相容性倒退會在本機就失敗，而不是等到 CI。

This file itself must stay 3.9-compatible, so it parses pyproject.toml with a
regex rather than tomllib (3.11+).
這個檔案本身也必須維持 3.9 相容，所以它用正則而不是 tomllib（3.11+）解析
pyproject.toml。
"""

import ast
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

ROOT = Path(__file__).resolve().parents[1]

#: The oldest interpreter the project claims to support.
#: 專案宣稱支援的最舊直譯器。
MIN_PYTHON = (3, 9)

_SOURCE_DIRS = ("linkedin_games_solver", "tests", "tools")


def _source_files():
    for name in _SOURCE_DIRS:
        for path in sorted((ROOT / name).rglob("*.py")):
            if "__pycache__" not in str(path):
                yield path
    for name in ("run.py", "run_cli.py"):
        path = ROOT / name
        if path.exists():
            yield path


def test_declared_minimum_matches_this_file():
    """pyproject.toml and MIN_PYTHON must not drift apart.
    pyproject.toml 與 MIN_PYTHON 不能各說各話。"""
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    match = re.search(r'requires-python\s*=\s*"[>=~^]*\s*(\d+)\.(\d+)', text)
    assert match, "requires-python not found in pyproject.toml / 找不到 requires-python"
    declared = (int(match.group(1)), int(match.group(2)))
    assert declared == MIN_PYTHON, (
        f"pyproject declares {declared[0]}.{declared[1]} but this test checks "
        f"{MIN_PYTHON[0]}.{MIN_PYTHON[1]} / 兩處宣告不一致"
    )
    print(f"  declared minimum is {declared[0]}.{declared[1]} OK")


def test_every_file_parses_on_the_minimum_version():
    """Catches syntax 3.9 cannot read: match statements, and so on.
    抓出 3.9 讀不懂的語法：match 陳述句等等。"""
    failures = []
    for path in _source_files():
        source = path.read_text(encoding="utf-8")
        try:
            ast.parse(source, feature_version=MIN_PYTHON)
        except SyntaxError as exc:
            failures.append(f"{path.relative_to(ROOT)}:{exc.lineno}: {exc.msg}")
    assert not failures, (
        f"not parseable on {MIN_PYTHON[0]}.{MIN_PYTHON[1]} / 無法在該版本解析:\n  "
        + "\n  ".join(failures)
    )
    print(f"  all files parse on {MIN_PYTHON[0]}.{MIN_PYTHON[1]} OK")


class _UnionInAnnotation(ast.NodeVisitor):
    """Collect `X | Y` appearing in annotations, which 3.9 evaluates at runtime.
    收集出現在型別註記裡的 `X | Y`，3.9 會在執行期求值。"""

    def __init__(self):
        self.hits = []

    def _scan(self, node, where):
        if node is None:
            return
        for sub in ast.walk(node):
            if isinstance(sub, ast.BinOp) and isinstance(sub.op, ast.BitOr):
                self.hits.append((sub.lineno, where))

    def visit_FunctionDef(self, node):
        args = node.args
        for arg in list(args.posonlyargs) + list(args.args) + list(args.kwonlyargs):
            self._scan(arg.annotation, f"argument '{arg.arg}' of {node.name}()")
        for arg in (args.vararg, args.kwarg):
            if arg is not None:
                self._scan(arg.annotation, f"argument '{arg.arg}' of {node.name}()")
        self._scan(node.returns, f"return type of {node.name}()")
        self.generic_visit(node)

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_AnnAssign(self, node):
        self._scan(node.annotation, "variable annotation")
        self.generic_visit(node)


def test_pep604_unions_have_the_future_import():
    """
    `str | None` parses fine on 3.9 but is EVALUATED when the def executes, so
    importing the module raises TypeError. `from __future__ import annotations`
    turns annotations into strings and makes it safe.
    `str | None` 在 3.9 上解析沒問題，但它會在 def 執行的當下**被求值**，
    所以 import 該模組就會丟 TypeError。
    `from __future__ import annotations` 會把註記變成字串，就安全了。

    This is exactly the bug that shipped in v1.0.0.
    這正是 v1.0.0 帶出門的那個 bug。
    """
    failures = []
    for path in _source_files():
        source = path.read_text(encoding="utf-8")
        if "from __future__ import annotations" in source:
            continue
        finder = _UnionInAnnotation()
        finder.visit(ast.parse(source))
        for lineno, where in finder.hits:
            line = source.split("\n")[lineno - 1].strip()
            failures.append(f"{path.relative_to(ROOT)}:{lineno} ({where})\n      {line}")

    assert not failures, (
        "PEP 604 union without `from __future__ import annotations` - "
        f"crashes on import under {MIN_PYTHON[0]}.{MIN_PYTHON[1]} / "
        "少了 future import 的型別聯集，在該版本 import 時會當掉:\n  "
        + "\n  ".join(failures)
    )
    print("  no runtime-evaluated unions OK")


def test_no_features_newer_than_the_minimum():
    """Constructs 3.9 parses but cannot execute.
    3.9 解析得了、但執行不了的用法。"""
    failures = []
    for path in _source_files():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
                continue
            names = {kw.arg for kw in node.keywords}
            if node.func.id == "zip" and "strict" in names:
                failures.append(f"{path.relative_to(ROOT)}:{node.lineno}: zip(strict=) is 3.10+")
            if node.func.id == "dataclass" and names & {"slots", "kw_only"}:
                failures.append(f"{path.relative_to(ROOT)}:{node.lineno}: dataclass(slots=/kw_only=) is 3.10+")
    assert not failures, "newer-than-minimum features / 用到比最低版本更新的功能:\n  " + "\n  ".join(failures)
    print("  no 3.10+ only constructs OK")


if __name__ == "__main__":
    print("Compatibility tests / 相容性測試")
    test_declared_minimum_matches_this_file()
    test_every_file_parses_on_the_minimum_version()
    test_pep604_unions_have_the_future_import()
    test_no_features_newer_than_the_minimum()
    print("\nAll passed / 全部通過")
