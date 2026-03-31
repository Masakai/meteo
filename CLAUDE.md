# CLAUDE.md

## プロジェクト概要

RTSPカメラストリームから流星をリアルタイム検出するPythonシステム。
OpenCVによる画像処理、Flaskによる状態確認WebUI、Dockerによるマルチカメラ並列運用を提供する。

**バージョン:** `dashboard_config.py` の `VERSION` を正とする
**ライセンス:** MIT

---

## アーキテクチャ

| コンポーネント | ファイル | 役割 |
|---|---|---|
| 検出コア | `meteor_detector_common.py` | 共通検出ロジック |
| リアルタイム検出 | `meteor_detector_realtime.py` | RTSP共通コンポーネント |
| Webプレビュー付き検出 | `meteor_detector_rtsp_web.py` | コンテナエントリポイント |
| RTSPクライアント | `meteor_detector_rtsp.py` | RTSPストリーム検出（CLI版） |
| ダッシュボード | `dashboard.py`, `dashboard_routes.py` | 複数カメラ統合UI |
| ダッシュボード（補助） | `dashboard_config.py`, `dashboard_templates.py` | 設定・テンプレート |
| ダッシュボード（補助） | `dashboard_camera_handlers.py`, `dashboard_templates_settings.py` | カメラ処理・設定画面 |
| Compose生成 | `generate_compose.py` | streamers から docker-compose.yml 自動生成 |
| 管理スクリプト | `meteor-docker.sh` | Docker操作ショートカット |

**技術スタック:** Python 3.11 / OpenCV 4.5+ / NumPy / Flask 3.0+ / astral / Docker Compose V2 / go2rtc

---

## 開発ルール

### テストは必ずコンテナ内で行う

このプロジェクトはDockerコンテナでの動作が大前提。
コンテナ環境特有の挙動（ネットワーク、パス、環境変数等）に依存しているため、
**ホスト上での直接実行（`python dashboard.py` 等）は行わない。**

```bash
# テスト実行（コンテナ内）
# <camera名> は streamers ファイルに設定したカメラ名に合わせる
docker compose run --rm <camera名> pytest -q
```

### ローカルでのユニットテスト

コンテナ依存のない純粋なユニットテストのみ、仮想環境で実行可能：

```bash
python3.14   -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pytest -q
```

---

## よく使うコマンド

```bash
# Docker環境の起動・停止
./meteor-docker.sh start
./meteor-docker.sh stop

# ログ確認
./meteor-docker.sh logs
./meteor-docker.sh logs camera1

# docker-compose.yml の再生成（streamers ファイル更新後）
python generate_compose.py

# テスト
pytest -q
```

---

## 重要なファイル・ディレクトリ

| パス | 内容 |
|---|---|
| `streamers` | RTSPカメラURL一覧（.gitignore対象、ユーザー設定） |
| `docker-compose.yml` | 自動生成（手動編集不要） |
| `masks/` | カメラごとのマスク画像 |
| `detections/` | 検出結果出力（.gitignore対象） |
| `documents/` | 詳細ドキュメント群 |
| `tests/` | pytestユニットテスト（`pytest --collect-only -q` で件数確認） |

---

## コーディング規約

- Python 3.11 対応
- Docker環境では `opencv-python-headless` を使用（GUI不要）
- セキュリティ: パストラバーサル等の入力値検証を厳守（`documents/SECURITY.md` 参照）
- 環境変数で設定を注入するDockerパターンを維持する
