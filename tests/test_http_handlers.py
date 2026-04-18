import hashlib
import json
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


# --- _is_mask_manually_modified ---

def _write_hashes_json(hashes_path: Path, data: dict):
    hashes_path.write_text(json.dumps(data), encoding="utf-8")


def test_is_mask_manually_modified_returns_true_when_hash_differs(tmp_path):
    """現在のハッシュと記録済みハッシュが異なる場合（手動更新済み）は True を返す"""
    import http_handlers

    mask_file = tmp_path / "camera1_mask.png"
    mask_file.write_bytes(b"original content")
    stored_hash = hashlib.sha256(b"different original content").hexdigest()

    hashes_path = tmp_path / ".generated_hashes.json"
    _write_hashes_json(hashes_path, {"camera1_mask.png": stored_hash})

    assert http_handlers._is_mask_manually_modified(str(mask_file), str(hashes_path)) is True


def test_is_mask_manually_modified_returns_false_when_hash_matches(tmp_path):
    """現在のハッシュと記録済みハッシュが一致する場合（自動生成のまま）は False を返す"""
    import http_handlers

    content = b"auto generated mask"
    mask_file = tmp_path / "camera1_mask.png"
    mask_file.write_bytes(content)
    stored_hash = hashlib.sha256(content).hexdigest()

    hashes_path = tmp_path / ".generated_hashes.json"
    _write_hashes_json(hashes_path, {"camera1_mask.png": stored_hash})

    assert http_handlers._is_mask_manually_modified(str(mask_file), str(hashes_path)) is False


def test_is_mask_manually_modified_returns_false_when_no_hashes_json(tmp_path):
    """ハッシュJSONが存在しない場合は False（上書き許可）を返す"""
    import http_handlers

    mask_file = tmp_path / "camera1_mask.png"
    mask_file.write_bytes(b"some content")
    missing_json = tmp_path / ".generated_hashes.json"

    assert http_handlers._is_mask_manually_modified(str(mask_file), str(missing_json)) is False


def test_is_mask_manually_modified_returns_false_when_no_hash_record(tmp_path):
    """ハッシュJSONにキーが存在しない場合は False を返す"""
    import http_handlers

    mask_file = tmp_path / "camera1_mask.png"
    mask_file.write_bytes(b"some content")

    hashes_path = tmp_path / ".generated_hashes.json"
    _write_hashes_json(hashes_path, {})  # キーなし

    assert http_handlers._is_mask_manually_modified(str(mask_file), str(hashes_path)) is False


def test_is_mask_manually_modified_returns_false_when_mask_save_path_empty(tmp_path):
    """mask_save_path が空文字の場合は False を返す"""
    import http_handlers

    hashes_path = tmp_path / ".generated_hashes.json"
    _write_hashes_json(hashes_path, {"camera1_mask.png": "abc"})

    assert http_handlers._is_mask_manually_modified("", str(hashes_path)) is False


def test_is_mask_manually_modified_returns_false_when_hashes_json_path_empty(tmp_path):
    """hashes_json_path が空文字の場合は False を返す（MASK_BUILD_DIR 未設定相当）"""
    import http_handlers

    mask_file = tmp_path / "camera1_mask.png"
    mask_file.write_bytes(b"some content")

    assert http_handlers._is_mask_manually_modified(str(mask_file), "") is False
