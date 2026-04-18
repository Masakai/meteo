"""dashboard_templates_settings.py のユニットテスト"""

import base64
from pathlib import Path
from unittest import mock


def test_render_settings_html_basic_structure():
    """render_settings_html がHTMLの基本構造を返すこと"""
    from dashboard_templates_settings import render_settings_html

    html = render_settings_html(cameras=[], version="1.0.0")
    assert "<!DOCTYPE html>" in html
    assert "カメラ設定" in html
    assert "1.0.0" in html


def test_render_settings_html_with_cameras():
    """カメラリストを渡してもHTMLが正常に生成されること"""
    from dashboard_templates_settings import render_settings_html

    cameras = [
        {"name": "camera1", "url": "http://camera1:8080"},
        {"name": "camera2", "url": "http://camera2:8080"},
    ]
    html = render_settings_html(cameras=cameras, version="2.0.0")
    assert "<!DOCTYPE html>" in html
    assert "2.0.0" in html


def test_render_settings_html_text_fallback_when_no_svg(tmp_path, monkeypatch):
    """SVGファイルが存在しない場合はテキストフォールバックが使われること"""
    import dashboard_templates_settings as mod

    # logotype_path.exists() が False になるよう __file__ を tmp_path に向ける
    fake_file = str(tmp_path / "dashboard_templates_settings.py")
    monkeypatch.setattr(mod, "__file__", fake_file)

    # モジュールを再実行せずに関数を直接呼ぶ（__file__は関数実行時に参照される）
    html = mod.render_settings_html(cameras=[], version="0.0.1")
    assert '<span class="brand-text">METEO</span>' in html


def test_render_settings_html_uses_svg_when_exists(tmp_path, monkeypatch):
    """SVGファイルが存在する場合はbase64埋め込み画像が使われること"""
    import dashboard_templates_settings as mod

    # tmp_path に documents/assets/meteo-logotype.svg を作成する
    assets_dir = tmp_path / "documents" / "assets"
    assets_dir.mkdir(parents=True)
    svg_content = b'<svg xmlns="http://www.w3.org/2000/svg"></svg>'
    (assets_dir / "meteo-logotype.svg").write_bytes(svg_content)

    # __file__ を tmp_path 内のファイルとして認識させる
    fake_file = str(tmp_path / "dashboard_templates_settings.py")
    monkeypatch.setattr(mod, "__file__", fake_file)

    html = mod.render_settings_html(cameras=[], version="0.0.1")
    expected_b64 = base64.b64encode(svg_content).decode("ascii")
    assert f"data:image/svg+xml;base64,{expected_b64}" in html
    assert '<img src=' in html
