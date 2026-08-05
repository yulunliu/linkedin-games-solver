"""
read_image / write_image contract tests: never raise, always a value.
read_image／write_image 契約測試：絕不拋例外，永遠回傳一個值。
"""

import sys
import tempfile
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from linkedin_games_solver.core.image_io import read_image, write_image  # noqa: E402


def test_read_image_returns_none_for_a_directory():
    """
    Bug this guards: a directory "exists" too, and np.fromfile raises
    IsADirectoryError for one rather than returning nothing - read_image's
    own docstring promises None, never an exception. Measured before the
    fix: --image <a directory> raised a raw PermissionError.
    這個測試守住的問題：資料夾也算「存在」，np.fromfile 對資料夾丟的是
    IsADirectoryError，不是回傳空值——但 read_image 自己的文件字串承諾
    「回傳 None，絕不拋例外」。修正前實測：--image <一個資料夾>
    會直接丟出原始的 PermissionError。
    """
    with tempfile.TemporaryDirectory() as tmp:
        assert read_image(tmp) is None
    print("  read_image returns None for a directory OK")


def test_read_image_returns_none_for_a_locked_or_unreadable_path():
    """A path np.fromfile cannot open must still come back as None, not raise.
    np.fromfile 打不開的路徑，也必須回傳 None，而不是拋例外。"""
    # A path inside a nonexistent directory is unreadable in the same way a
    # locked file would be - OSError from the underlying open(), not from
    # Path.exists() (which is checked first and would already return None
    # for a plain missing file; this exercises the OSError branch instead).
    # 一個位於不存在的資料夾底下的路徑，跟被鎖住的檔案一樣打不開——
    # 錯誤來自底層 open() 的 OSError，不是 Path.exists()（那個先檢查，
    # 對單純不存在的檔案早就會回傳 None 了；這裡要測的是 OSError 那個分支）。
    with tempfile.TemporaryDirectory() as tmp:
        # A file, used as if it were a directory containing another file -
        # opening "file/sub.png" raises NotADirectoryError (an OSError) on
        # POSIX, ENOENT-family on Windows; both are OSError subclasses.
        # 把一個檔案當成資料夾、去開它底下的另一個檔案——在 POSIX 上
        # 打開 "file/sub.png" 會丟 NotADirectoryError（OSError 的子類別），
        # Windows 上是同一家族的錯誤；兩者都是 OSError 的子類別。
        real_file = Path(tmp) / "not_a_dir"
        real_file.write_bytes(b"not an image")
        bogus_path = real_file / "sub.png"
        assert read_image(bogus_path) is None
    print("  read_image returns None for an unreadable path OK")


def test_write_image_returns_false_rather_than_raising():
    """
    Bug this guards: cv2.imencode raises cv2.error rather than returning
    ok=False under OpenCV 5.0.0 (the version this project ships), and
    tofile() raises OSError for an unwritable path - both used to escape
    uncaught, violating write_image's documented "returns bool" contract.
    這個測試守住的問題：在這個專案用的 OpenCV 5.0.0 下，cv2.imencode
    是拋出 cv2.error 而不是回傳 ok=False，tofile() 對寫不進去的路徑
    則是拋 OSError——這兩種以前都沒接住，直接逸出，違反 write_image
    自己文件寫的「回傳布林值」約定。
    """
    with tempfile.TemporaryDirectory() as tmp:
        # A directory as the destination: tofile() cannot write there.
        # 把資料夾本身當成目的地：tofile() 沒辦法寫進去。
        image = np.zeros((10, 10, 3), np.uint8)
        assert write_image(tmp, image) is False
    print("  write_image returns False rather than raising OK")


def test_write_image_then_read_image_round_trips():
    """The happy path must keep working exactly as before.
    正常路徑必須完全維持原本的行為。"""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "out.png"
        image = np.zeros((12, 12, 3), np.uint8)
        image[:, :, 2] = 255  # pure red, so a decode mismatch is obvious
        assert write_image(path, image) is True
        back = read_image(path)
        assert back is not None
        assert back.shape == image.shape
        assert (back == image).all()
    print("  write_image/read_image round trip OK")


if __name__ == "__main__":
    print("Image I/O contract tests / 影像讀寫契約測試")
    test_read_image_returns_none_for_a_directory()
    test_read_image_returns_none_for_a_locked_or_unreadable_path()
    test_write_image_returns_false_rather_than_raising()
    test_write_image_then_read_image_round_trips()
    print("\nAll passed / 全部通過")
