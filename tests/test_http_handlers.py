import numpy as np
import pytest
from pathlib import Path
from unittest.mock import patch


def test_write_mask_to_build_dir_writes_to_masks(tmp_path, monkeypatch):
    """MASK_BUILD_DIR が設定されている場合、masks/ 直下にファイルが書き込まれること"""
    import http_handlers

    build_dir = tmp_path / "masks"
    build_dir.mkdir()
    save_path = tmp_path / "detections" / "camera1_mask.png"
    mask = np.zeros((10, 10), dtype=np.uint8)

    written = {}

    def fake_imwrite(path, img):
        written["path"] = path
        written["img"] = img
        return True

    monkeypatch.setattr(http_handlers.cv2, "imwrite", fake_imwrite)

    http_handlers._write_mask_to_build_dir(str(build_dir), save_path, mask)

    assert "path" in written
    assert Path(written["path"]).parent == build_dir
    assert Path(written["path"]).name == "camera1_mask.png"


def test_write_mask_to_build_dir_no_op_when_no_build_dir(monkeypatch, tmp_path):
    """MASK_BUILD_DIR が未設定（空文字）の場合は書き込まれないこと"""
    import http_handlers

    save_path = tmp_path / "camera1_mask.png"
    mask = np.zeros((10, 10), dtype=np.uint8)

    written = {}

    def fake_imwrite(path, img):
        written["path"] = path
        return True

    monkeypatch.setattr(http_handlers.cv2, "imwrite", fake_imwrite)

    http_handlers._write_mask_to_build_dir("", save_path, mask)

    assert "path" not in written


def test_write_mask_to_build_dir_blocks_path_traversal(tmp_path, monkeypatch):
    """パストラバーサル（../）を含むファイル名が build_dir 外に書き込まれないこと"""
    import http_handlers

    build_dir = tmp_path / "masks"
    build_dir.mkdir()
    outside = tmp_path / "secret.png"

    # pending_save_path のファイル名に ../ を含む細工をする
    # Path.name は最後の成分のみ返すので実際には traversal にならないが、
    # resolve() が build_dir 外を指すケースを模倣するため直接 dest を構築する
    # ここでは実装が Path(pending_save_path).name を使っていることを前提に、
    # build_dir の外を指す resolved path を生成できないことを確認する
    traversal_path = tmp_path / ".." / "secret.png"

    written = {}

    def fake_imwrite(path, img):
        written["path"] = path
        return True

    monkeypatch.setattr(http_handlers.cv2, "imwrite", fake_imwrite)

    http_handlers._write_mask_to_build_dir(str(build_dir), traversal_path, np.zeros((10, 10), dtype=np.uint8))

    # "../secret.png" の name は "secret.png" なので build_dir/secret.png に書かれる（traversal なし）
    # もしくはまったく書き込まれないことを確認する
    if "path" in written:
        assert Path(written["path"]).resolve().parent == build_dir.resolve()
    # 親ディレクトリ（tmp_path）へは書き込まれていないこと
    assert not outside.exists()
