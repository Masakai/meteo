# API リファレンス (API Reference)

---

**Copyright (c) 2026 Masanori Sakai**

Licensed under the MIT License

---


## 概要

流星検出システムが提供するHTTP APIの完全なリファレンスです。

## 目次

- [バージョン履歴](#バージョン履歴)
- [dashboard.py API](#dashboardpy-api)
- [meteor_detector_rtsp_web.py API](#meteor_detector_rtsp_webpy-api)
- [環境変数](#環境変数)
- [共通仕様](#共通仕様)
- [エラーコード](#エラーコード)
- [使用例](#使用例)

---

## バージョン履歴

### v3.11.0 - カメラ名をインデックスベースに変更・既存データ移行スクリプト追加

- **変更**: `generate_compose.py` — `CAMERA_NAME` を IP ベース（例: `camera1_192_168_1_10`）からインデックスベース（例: `camera1`）に変更。IP アドレスが変わってもカメラ名が変わらない
- **変更**: `dashboard_config.py` — デフォルト CAMERAS 名をインデックスベースに更新
- **変更**: `dashboard_routes.py` — docstring 例をインデックスベース名に更新
- **追加**: `migrate_camera_dirs.py` — 既存の IP ベースディレクトリを `camera1`/`camera2`/`camera3` に安全移行するスタンドアロンスクリプト（`--dry-run` / `--yes` 対応）
- **追加**: `tests/test_migrate_camera_dirs.py` — 移行スクリプトのユニットテスト22件

### v3.10.0 - 手動更新マスクの自動保護

- **追加**: `generate_compose.py` — SHA256ハッシュによるマスク保護。`masks/.generated_hashes.json` にハッシュを記録し、手動更新済みマスクを再実行時に上書きしない
- **追加**: `generate_compose.py` — `--force-overwrite-masks` フラグで保護対象マスクの強制上書きが可能
- **追加**: `generate_compose.py` — マスクあり時のみ `MASK_BUILD_DIR` 環境変数と `./masks:/app/masks_build` ボリュームマウントを生成
- **追加**: `http_handlers.py` — `/confirm_mask_update` でホスト側 `masks/` への同期書き込み（`MASK_BUILD_DIR` 環境変数経由、パストラバーサル防止済み）

### v3.9.0 - 統計ページに時間帯×カメラの検出数グラフ追加

- **追加**: `dashboard_routes.py` / `dashboard_templates.py` — 時間帯×カメラの検出数グループ棒グラフ（Plotly.js）を統計ページに追加
- **追加**: `detection_store.py` — `compute_hourly_stats()`: 5秒グリーディー重複除去後、ローカル時刻の時単位で集計
- **変更**: `GET /stats_data` レスポンスに `hourly` キー（時間帯別検出数）を追加

### v3.8.0 - ダッシュボード UI 全面リニューアル

- **変更**: `dashboard_templates.py` — ライトモード移行・左固定サイドバーナビゲーション（ダーク）＋アンバーアクセントボーダー導入
- **変更**: フォント刷新: Orbitron（見出し）/ Inter（本文）/ JetBrains Mono（数値）
- **変更**: カラーパレット刷新: ロゴタイプブルー `#1a8fc4`・アンバー `#d4860a` を軸に再設計
- **変更**: YouTube Live ボタンをカメラヘッダー内に移動。未設定カメラはグレーアウト表示
- **追加**: ナビゲーションに `aria-current="page"` を追加（アクセシビリティ改善）

### v3.7.0 - 流星統計ビュー追加

- **追加**: `dashboard_routes.py` — `GET /stats` 統計ページ（カメラ別・夜別流星数の積み重ね棒グラフ）
- **追加**: `dashboard_routes.py` — `GET /stats_data` 夜別流星統計 JSON API（重複除去済み）
- **追加**: `detection_store.py` — `query_detections_for_stats()` 統計ページ向けクエリメソッド
- **テスト**: `tests/test_stats.py` — `/stats` / `/stats_data` エンドポイント単体テスト追加

### v3.6.2 - meteor_detector_rtsp_web.py リファクタリング（責務分割）

- **リファクタリング**: `meteor_detector_rtsp_web.py` — 2,274行のモノリシック実装を4ファイルに分割（機能変更なし）
- **追加**: `detection_state.py` — グローバル変数60個を `DetectionState` dataclass に集約
- **追加**: `detection_filters.py` — フィルタ・パラメータ関数群（純粋関数）
- **追加**: `recording_manager.py` — 録画ジョブ管理・ffmpegプロセス制御
- **追加**: `http_handlers.py` — `MJPEGHandler` クラス・`ThreadedHTTPServer`
- **テスト**: `tests/test_detection_state.py` / `tests/test_detection_filters.py` 追加

### v3.6.1 - 移動する黒点（鳥シルエット）除外フィルタ追加

- **追加**: `meteor_detector_rtsp_web.py` — `filter_dark_objects()` 関数。輝度が閾値未満のオブジェクト（鳥シルエット等）を除外
- **追加**: 環境変数 `BIRD_FILTER_ENABLED` / `BIRD_MIN_BRIGHTNESS` — 通常時の黒点フィルタ設定（デフォルト無効）
- **追加**: 環境変数 `TWILIGHT_BIRD_FILTER_ENABLED` / `TWILIGHT_BIRD_MIN_BRIGHTNESS` — 薄明時の黒点フィルタ設定（デフォルト有効）
- **テスト**: `tests/test_filter_dark_objects.py` — `filter_dark_objects()` 単体テスト8ケース追加

### v3.6.0 - SQLite移行（パフォーマンス改善・アーキテクチャ変更）

- **追加**: `detection_store.py` — スレッドセーフSQLite操作モジュール（WALモード・JSONL増分同期）
- **追加**: `scripts/migrate_jsonl_to_sqlite.py` — 既存JSONLデータのSQLite移行スクリプト
- **変更**: `dashboard_routes.py` — 検出結果のJSONL全行読み込みをSQLiteクエリに置換。削除・ラベル操作もSQLiteベースに変更
- **テスト**: `tests/test_detection_store.py` — `detection_store` 単体テスト追加
- **テスト**: `tests/test_dashboard_routes.py` — SQLite対応フィクスチャを追加

### v3.5.1 - 薄明環境変数追加・CI整備・カバレッジ改善

- **修正**: `generate_compose.py` — `TWILIGHT_DETECTION_MODE` / `TWILIGHT_TYPE` / `TWILIGHT_SENSITIVITY` / `TWILIGHT_MIN_SPEED` の4環境変数をコンテナテンプレートに追加（機能的欠陥の修正）
- **リファクタリング**: `meteor_detector_rtsp_web.py` — 薄明感度プリセット適用ロジックを `build_twilight_params()` ヘルパー関数に切り出し
- **CI**: `.github/workflows/ci.yml` — `--cov-fail-under=70` を追加しカバレッジ70%未満でCIが失敗するように設定
- **CI**: `.coveragerc` を新規作成しカバレッジ計測設定を追加
- **テスト**: `tests/test_generate_compose.py` — 薄明環境変数の出力検証テスト追加
- **テスト**: `tests/test_astro_twilight.py` — 朝方薄明 True 分岐カバーテスト修正
- **テスト**: `tests/test_meteor_detector_rtsp_web.py` — `TestBuildTwilightParams` 全フィールド検証追加

### v3.4.7 - セキュリティ修正・コード品質改善・UI調整

- **セキュリティ**: `dashboard.py` — `camera_embed` エンドポイントに `html.escape()` を適用し XSS を対策
- **セキュリティ**: `dashboard_camera_handlers.py` — YouTube ストリームキーのログ漏洩を防止
- **セキュリティ**: `generate_compose.py` — 無効URL警告ログの RTSP 認証情報をマスク
- **品質**: `dashboard.py` — `go2rtc_asset` エンドポイントのエラーハンドリング追加
- **品質**: `generate_compose.py` — 関数内 `import os` 解消・非推奨の `_replace()` 除去
- **品質**: `pytest.ini` — `testpaths` 設定追加
- **テスト**: セキュリティ修正に対応するテスト5件追加
- **UI**: `dashboard_templates.py` — 削除ボタンの表示制御変更
- **管理**: `go2rtc.yaml` を git 管理下から除外

### v3.4.6 - 全選択UI常時表示・Dockerfile.dashboard改善
- **変更**: 検出結果一覧の全選択UIを常時表示化（選択モードトグル廃止）
- **修正**: `Dockerfile.dashboard` の apt インストールを BuildKit cache mount 方式に変更

### v3.4.5 - YouTube配信エンコーダ3段階フォールバック・Dockerfile修正
- **変更**: YouTube 配信エンコーダを QSV → VAAPI → libx264 の3段階フォールバックに拡張
  - Intel QSV 利用可能時: `h264_qsv` 720p 2000kbps
  - QSV 不可・VAAPI 利用可能時: `h264_vaapi` 720p 2000kbps（旧世代 Intel / AMD GPU）
  - どちらも不可: `libx264 ultrafast` 720p 2000kbps
- **変更**: `Dockerfile.dashboard` を `python:3.11-slim-bookworm` (Debian 12) ベースに変更（Mac 上の GPG エラー解消）

### v3.4.4 - YouTube配信のマルチプラットフォーム対応
- **変更**: Intel QSV ハードウェアエンコードを自動検出し、利用可能な場合は `h264_qsv`、非対応環境は `libx264 ultrafast` に自動フォールバック
- **変更**: YouTube 配信に自動再接続ループを追加（ffmpeg 終了後 15 秒待機して再接続）
- **変更**: 映像解像度を 1280×720 に統一（CPU/GPU 負荷軽減）
- **変更**: Dockerfile.dashboard を Ubuntu 24.04 ベースに変更

### v3.3.0 - YouTube Live配信
- **追加**: `POST /youtube_start/{index}` — カメラのYouTube Live配信を開始
- **追加**: `POST /youtube_stop/{index}` — カメラのYouTube Live配信を停止
- **追加**: `GET /youtube_status/{index}` — カメラのYouTube Live配信状態を取得
- **追加**: ダッシュボード環境変数 `CAMERA{i}_YOUTUBE_KEY`、`CAMERA{i}_RTSP_URL`、`GO2RTC_API_URL`
- **変更**: YouTube 配信停止は dashboard コンテナ内の ffmpeg プロセスを terminate/kill で終了

### v3.2.5 - メンテナンスアップデート
- **変更**: ダッシュボードのバージョンを 3.2.5 へ更新
- **変更**: 各種ドキュメント（ARCHITECTURE.md, DETECTOR_COMPONENTS.md）を最新のコード実態に合わせて改版

### v3.2.1 - 手動録画の一覧統合とサムネイル対応
- **修正**: 手動録画で `pcm_alaw` 音声を含む RTSP を MP4 へ保存する際に失敗していた問題を修正し、映像のみ保存するよう改善
- **修正**: 手動録画ファイルの探索先を各カメラ出力ディレクトリ配下 `manual_recordings/...` に合わせ、検出一覧カレンダーへ反映されるよう修正
- **変更**: 手動録画完了後にサムネイル JPEG を自動生成し、検出一覧でプレビュー可能化
- **追加**: ダッシュボードに `DELETE /manual_recording/{path}` を追加し、手動録画 MP4 とサムネイルを削除可能化

### v3.2.0 - カメラ別手動録画予約の追加
- **追加**: ダッシュボードに `GET /camera_recording_status/{index}`、`POST /camera_recording_schedule/{index}`、`POST /camera_recording_stop/{index}` を追加
- **追加**: カメラ側 API に `GET /recording/status`、`POST /recording/schedule`、`POST /recording/stop` を追加
- **変更**: `/camera_stats/{index}` と `/stats` のレスポンスへ `recording` オブジェクトを追加し、予約状態・録画状態・保存先を取得可能化

### v3.1.1 - WebRTC candidate 自動検出と生成安定化
- **変更**: `generate_compose.py` が `go2rtc` の candidate host を既定でローカル IP から自動検出するよう改善
- **修正**: OpenCV 未導入時でも `docker-compose.yml` / `go2rtc.yaml` の生成を継続し、マスク生成のみスキップするよう改善
- **変更**: ダッシュボードおよび Docker / WebRTC 構成の関連ドキュメントを現行仕様へ改版

### v3.1.0 - WebRTC ライブ表示の正式対応
- **追加**: Docker 構成で `go2rtc` を利用する WebRTC ライブ表示設定を正式サポート
- **変更**: ダッシュボードのライブ表示設定に `CAMERA*_STREAM_KIND=webrtc` / `CAMERA*_STREAM_URL` を追加
- **変更**: ダッシュボードのヘルスチェック例の `version` 表示を `3.1.1` に更新

### v3.0.0 - 旧互換 MP4 正規化設定の削除
- **削除**: `GET /stats` の `settings` から `fb_normalize` / `fb_delete_mov` を削除
- **削除**: カメラ設定 API の起動時依存設定から `fb_normalize` / `fb_delete_mov` を削除
- **変更**: ダッシュボードのヘルスチェック例の `version` 表示を `3.0.0` に更新

### v1.24.1 - ダッシュボードの Flask アプリ運用整備
- **新規エンドポイント**: `GET /health`
  - ダッシュボードのヘルスチェックを返却
  - レスポンス例: `{ "status": "ok", "version": "3.4.4", "camera_count": 3 }`
- **変更**: `dashboard.py` を Flask のアプリファクトリ構成へ整理し、WSGI 配備やコンテナ運用時でも監視スレッドが初回リクエストで起動するよう改善

### v1.24.0 - 検出 ID 管理と運用制御の拡張
- **機能追加**: `/camera_settings/current` および `/camera_settings/apply_all` で `detection_enabled` を扱えるようにし、全カメラの検出停止・再開を一括制御可能化
- **変更**: 検出レコードの `id` を、`timestamp` に加えて `start_time` / `end_time` / `start_point` / `end_point` を含む現行ルールへ統一
- **運用改善**: 検出データの移行・孤立ファイル救済・ディレクトリ統合を補助するメンテナンススクリプトを追加

### v1.23.1 - 検出時間帯判定と状態表示の修正
- **修正**: 検出時間帯の計算を「当日日没から翌日の日出まで」に是正
- **機能追加**: `GET /stats` レスポンスに検出状態詳細フィールドを追加
  - `detection_status`: `DETECTING` / `OUT_OF_WINDOW` / `WAITING_FRAME` / `STREAM_LOST`
  - `detection_window_enabled`: 検出時間帯制限の有効/無効
  - `detection_window_active`: 現在が検出時間帯内か
  - `detection_window_start`: 現在参照中の検出開始時刻
  - `detection_window_end`: 現在参照中の検出終了時刻

### v1.18.0 - 一括削除機能
- **新規エンドポイント**: `POST /bulk_delete_non_meteor/{camera_name}`
  - カメラごとに非流星検出（`label="non-meteor"`）を一括削除
  - 削除件数とファイルリストを返却

### v1.17.0 - カメラ監視機能
- **機能追加**: `/camera_stats/{index}` レスポンスに監視関連フィールドを追加
  - `monitor_enabled`: 監視機能の有効/無効
  - `monitor_checked_at`: 最終監視確認時刻
  - `monitor_error`: 監視エラーメッセージ
  - `monitor_stop_reason`: 監視停止理由
  - `monitor_last_restart_at`: 最終再起動時刻
  - `monitor_restart_count`: 再起動回数
  - `monitor_restart_triggered`: 再起動トリガー発動中か
- **環境変数**: カメラ監視設定（`CAMERA_MONITOR_*`, `CAMERA_RESTART_*`）

### v1.16.0 - 画面端ノイズ除外
- **パラメータ追加**: `exclude_edge_ratio`
  - `/stats` レスポンスの `settings.exclude_edge_ratio`
  - `/apply_settings` リクエストボディ
  - 画面四辺の指定割合をノイズ除外エリアとして設定

### v1.14.0 - 録画マージン設定
- **パラメータ追加**: 録画前後マージン
  - `/stats` レスポンスの `settings.clip_margin_before`, `settings.clip_margin_after`
  - `/apply_settings` リクエストボディ
  - 検出前後に録画する追加秒数を設定可能

### v1.13.0 - 全カメラ設定UI
- **新規エンドポイント**: `GET /settings` - 全カメラ設定ページ
- **新規エンドポイント**: `GET /camera_settings/current` - 各カメラの現在設定取得
- **新規エンドポイント**: `POST /camera_settings/apply_all` - 全カメラへ設定一括適用

### v1.10.0 - 検出ラベル機能
- **新規エンドポイント**: `POST /detection_label`
  - 検出に任意ラベル（`meteor`, `non-meteor` など）を設定
- **機能追加**: `/detections` レスポンスに `label` フィールド追加
- **機能追加**: `/detections_mtime` がラベルファイル（`detection_labels.json`）も監視対象に（SQLite移行後は `detections.db` の更新時刻を返す）

---

## dashboard.py API

ダッシュボードが提供するエンドポイント（デフォルトポート: 8080）

### エンドポイント一覧

| エンドポイント | メソッド | 説明 |
|--------------|---------|------|
| `/health` | GET | ダッシュボードヘルスチェック |
| `/` | GET | ダッシュボードHTML |
| `/cameras` | GET | カメラライブ画面HTML |
| `/settings` | GET | 全カメラ設定ページ |
| `/detection_window` | GET | 検出時間帯取得 |
| `/detections` | GET | 検出一覧取得 |
| `/detections_mtime` | GET | 検出ログ更新時刻取得 |
| `/camera_embed/{index}` | GET | WebRTC 埋め込みページ |
| `/go2rtc_asset/{name}` | GET | go2rtc フロント資産プロキシ |
| `/camera_settings/current` | GET | カメラ設定の現在値取得 |
| `/camera_settings/apply_all` | POST | 設定を全カメラへ一括適用 |
| `/camera_snapshot/{index}` | GET | カメラスナップショット取得（`?download=1` でDL） |
| `/camera_recording_status/{index}` | GET | カメラ手動録画状態取得 |
| `/camera_recording_schedule/{index}` | POST | カメラ手動録画の予約/即時開始 |
| `/camera_recording_stop/{index}` | POST | カメラ手動録画の停止 |
| `/camera_restart/{index}` | POST | カメラ再起動要求 |
| `/youtube_start/{index}` | POST | YouTube Live配信を開始 |
| `/youtube_stop/{index}` | POST | YouTube Live配信を停止 |
| `/youtube_status/{index}` | GET | YouTube Live配信状態を取得 |
| `/camera_stats/{index}` | GET | カメラ統計情報取得 |
| `/image/{camera}/{filename}` | GET | 画像ファイル取得 |
| `/detection/{camera}/{id}` | DELETE | 検出結果削除 |
| `/dashboard_stats` | GET | ダッシュボードCPU統計取得 |
| `/manual_recording/{path}` | DELETE | 手動録画ファイル削除 |
| `/bulk_delete_non_meteor/{camera_name}` | POST | カメラの非流星検出を一括削除 |
| `/detection_label` | POST | 検出にラベルを設定 |
| `/changelog` | GET | CHANGELOG表示 |
| `/stats` | GET | 夜別流星統計ページ（HTML） |
| `/stats_data` | GET | 夜別流星統計データ取得（JSON） |

---

### GET /health

**説明**: ダッシュボードのプロセス状態と構成情報を返す

**レスポンス**:
- Content-Type: `application/json`
- Status: 200 OK

**レスポンスボディ**:
```json
{
  "status": "ok",
  "version": "3.4.4",
  "camera_count": 3
}
```

**使用例**:
```bash
curl http://localhost:8080/health
```

---

### GET /

**説明**: ダッシュボードのHTMLページを返す

**レスポンス**:
- Content-Type: `text/html; charset=utf-8`
- Status: 200 OK

**使用例**:
```bash
curl http://localhost:8080/
```

---

### GET /cameras

**説明**: カメラライブ表示用のHTMLページを返す

**レスポンス**:
- Content-Type: `text/html; charset=utf-8`
- Status: 200 OK

**補足**:
- `CAMERA*_STREAM_KIND=mjpeg` の場合は各カメラの `/stream` を直接参照
- `CAMERA*_STREAM_KIND=webrtc` の場合は `/camera_embed/{index}` を iframe で埋め込み

---

### GET /settings

**説明**: 全カメラ設定UIページを返す

**レスポンス**:
- Content-Type: `text/html; charset=utf-8`
- Status: 200 OK

**使用例**:
```bash
curl http://localhost:8080/settings
```

---

### GET /camera_embed/{index}

**説明**: WebRTC ライブ表示用の埋め込みHTMLを返す

**レスポンス**:
- Content-Type: `text/html; charset=utf-8`
- Status: 200 OK

**補足**:
- `CAMERA*_STREAM_KIND=webrtc` のカメラのみ有効
- 埋め込みページ内で `/go2rtc_asset/video-stream.js` を読み込み、`go2rtc` の `/api/ws?src=...` へ接続
- 表示モードは `webrtc,mse,hls,mjpeg` の優先順で自動選択

---

### GET /go2rtc_asset/{name}

**説明**: `go2rtc` の `video-stream.js` / `video-rtc.js` をダッシュボード経由で配信

**レスポンス**:
- Content-Type: `application/javascript; charset=utf-8`
- Status: 200 OK

**補足**:
- WebRTC 埋め込みページからのみ利用
- Docker 内では `go2rtc` コンテナを名前解決し、ホスト側公開アドレスと分離して取得

---

### GET /detection_window

**説明**: 天文薄暮期間（検出時間帯）を取得

**クエリパラメータ**:

| パラメータ | 型 | 必須 | 説明 | 例 |
|-----------|-----|------|------|-----|
| `lat` | float | No | 緯度 | `35.6762` |
| `lon` | float | No | 経度 | `139.6503` |

**レスポンス**:
- Content-Type: `application/json`
- Status: 200 OK

**レスポンスボディ**:
```json
{
  "start": "2026-02-01 16:45:23",
  "end": "2026-02-02 06:12:45",
  "enabled": true,
  "latitude": 35.6762,
  "longitude": 139.6503
}
```

**フィールド説明**:

| フィールド | 型 | 説明 |
|-----------|-----|------|
| `start` | string | 検出開始時刻（YYYY-MM-DD HH:MM:SS） |
| `end` | string | 検出終了時刻（YYYY-MM-DD HH:MM:SS） |
| `enabled` | boolean | 時間帯制限の有効/無効 |
| `latitude` | float | 使用された緯度 |
| `longitude` | float | 使用された経度 |

**エラーレスポンス**:
```json
{
  "start": "",
  "end": "",
  "enabled": false,
  "error": "meteor_detector module not available"
}
```

**使用例**:
```bash
# デフォルト座標で取得
curl "http://localhost:8080/detection_window" | jq

# 座標を指定
curl "http://localhost:8080/detection_window?lat=35.6762&lon=139.6503" | jq

# JavaScriptから取得
fetch('/detection_window?lat=35.6762&lon=139.6503')
  .then(r => r.json())
  .then(data => console.log(data));
```

---

### GET /detections

**説明**: 全カメラの検出結果一覧を取得

**レスポンス**:
- Content-Type: `application/json`
- Status: 200 OK

**レスポンスボディ**:
```json
{
  "total": 15,
  "recent": [
    {
      "time": "2026-02-02 06:55:33",
      "camera": "camera1",
      "confidence": "87%",
      "image": "camera1/meteor_20260202_065533_composite.jpg",
      "mp4": "camera1/meteor_20260202_065533.mp4",
      "composite_original": "camera1/meteor_20260202_065533_composite_original.jpg"
    },
    {
      "time": "2026-02-02 05:32:18",
      "camera": "camera2",
      "confidence": "92%",
      "image": "camera2/meteor_20260202_053218_composite.jpg",
      "mp4": "camera2/meteor_20260202_053218.mp4",
      "composite_original": "camera2/meteor_20260202_053218_composite_original.jpg"
    }
  ]
}
```

**フィールド説明**:

| フィールド | 型 | 説明 |
|-----------|-----|------|
| `total` | integer | 総検出数 |
| `recent` | array | 検出リスト（時刻降順） |
| `recent[].time` | string | 検出時刻 |
| `recent[].camera` | string | カメラ名 |
| `recent[].confidence` | string | 信頼度（パーセント表示） |
| `recent[].image` | string | 画像パス |
| `recent[].mp4` | string | 動画パス（通常は `.mp4`） |
| `recent[].composite_original` | string | 元画像の比較明合成パス |
| `recent[].label` | string | 検出ラベル（v1.10.0以降、未設定時は空文字） |
| `recent[].source_type` | string | `"manual_recording"` の場合は手動録画（v3.2.1以降、手動録画エントリのみ付与） |

**使用例**:
```bash
# curlで取得
curl http://localhost:8080/detections | jq

# 総検出数のみ取得
curl -s http://localhost:8080/detections | jq '.total'

# 最新の検出のみ取得
curl -s http://localhost:8080/detections | jq '.recent[0]'

# JavaScriptから取得
fetch('/detections')
  .then(r => r.json())
  .then(data => {
    console.log('Total:', data.total);
    data.recent.forEach(d => console.log(d.time, d.camera));
  });
```

---

### GET /detections_mtime

**説明**: `$DETECTIONS_DIR/detections.db` の更新時刻（UNIXエポック秒）を取得

**レスポンス**:
- Content-Type: `application/json`
- Status: 200 OK

**レスポンスボディ**:
```json
{
  "mtime": 1751461442.123
}
```

**使用例**:
```bash
curl http://localhost:8080/detections_mtime | jq
```

```javascript
fetch('/detections_mtime')
  .then(r => r.json())
  .then(data => console.log('mtime:', data.mtime));
```

---

### GET /camera_stats/{index}

**説明**: 指定カメラの統計情報を取得（v1.17.0で監視機能を追加、v3.2.0で `recording` フィールドを追加）

**URLパラメータ**:

| パラメータ | 型 | 説明 | 例 |
|-----------|-----|------|-----|
| `index` | integer | カメラインデックス（0始まり） | `0` |

**レスポンス**:
- Content-Type: `application/json`
- Status: 200 OK

**レスポンスボディ**:
```json
{
  "detections": 5,
  "elapsed": 3600.5,
  "camera": "camera1",
  "stream_alive": true,
  "time_since_last_frame": 0.03,
  "is_detecting": true,
  "monitor_enabled": true,
  "monitor_checked_at": "2026-02-24 12:34:56",
  "monitor_error": null,
  "monitor_stop_reason": null,
  "monitor_last_restart_at": "2026-02-24 10:00:00",
  "monitor_restart_count": 2,
  "monitor_restart_triggered": false
}
```

**フィールド説明**:

| フィールド | 型 | 説明 |
|-----------|-----|------|
| `detections` | integer | 検出数 |
| `elapsed` | float | 稼働時間（秒） |
| `camera` | string | カメラ名 |
| `stream_alive` | boolean | ストリーム生存確認 |
| `time_since_last_frame` | float | 最終フレームからの経過時間（秒） |
| `is_detecting` | boolean | 現在検出処理中か |
| `monitor_enabled` | boolean | カメラ監視機能の有効/無効 |
| `monitor_checked_at` | string/null | 最終監視確認時刻 |
| `monitor_error` | string/null | 監視エラーメッセージ |
| `monitor_stop_reason` | string/null | 監視停止理由 |
| `monitor_last_restart_at` | string/null | 最終再起動時刻 |
| `monitor_restart_count` | integer | 再起動回数 |
| `monitor_restart_triggered` | boolean | 再起動トリガー発動中か |
| `recording` | object/null | 手動録画状態（v3.2.0以降、カメラが対応している場合に含まれる） |

**使用例**:
```bash
# curlで取得
curl http://localhost:8080/camera_stats/0 | jq

# JavaScriptから定期取得
setInterval(() => {
  fetch('/camera_stats/0')
    .then(r => r.json())
    .then(data => {
      console.log('Stream alive:', data.stream_alive);
      console.log('Monitor enabled:', data.monitor_enabled);
      console.log('Restart count:', data.monitor_restart_count);
    });
}, 5000);
```

---

### GET /image/{camera}/{filename}

**説明**: 検出画像ファイルを取得

**URLパラメータ**:

| パラメータ | 型 | 説明 | 例 |
|-----------|-----|------|-----|
| `camera` | string | カメラディレクトリ名 | `camera1` |
| `filename` | string | ファイル名 | `meteor_20260202_065533_composite.jpg` |

**レスポンス**:
- Content-Type: `image/jpeg` または `image/png`
- Status: 200 OK
- Body: バイナリ画像データ

**エラーレスポンス**:
- Status: 404 Not Found

**使用例**:
```bash
# 画像をダウンロード
curl -O "http://localhost:8080/image/camera1/meteor_20260202_065533_composite.jpg"

# HTMLから表示
<img src="/image/camera1/meteor_20260202_065533_composite.jpg" alt="Meteor">

# ダウンロードリンク
<a href="/image/camera1/meteor_20260202_065533_composite.jpg" download>
  Download Image
</a>
```

---

### GET /camera_snapshot/{index}

**説明**: 指定カメラの現在フレームをJPEGで取得

**URLパラメータ**:

| パラメータ | 型 | 説明 | 例 |
|-----------|-----|------|-----|
| `index` | integer | カメラインデックス（0始まり） | `0` |

**クエリパラメータ**:

| パラメータ | 型 | 必須 | 説明 | 例 |
|-----------|-----|------|------|-----|
| `download` | string | No | `1/true/yes` で `Content-Disposition: attachment` を付与 | `1` |

**レスポンス**:
- Content-Type: `image/jpeg`
- Status: 200 OK

**使用例**:
```bash
# 画像を直接表示
curl "http://localhost:8080/camera_snapshot/0" --output snapshot.jpg

# ダウンロード用途（attachmentヘッダ付き）
curl -OJ "http://localhost:8080/camera_snapshot/0?download=1"
```

---

### GET /camera_recording_status/{index}

**説明**: 指定カメラの手動録画状態を取得

**レスポンス**:
- Content-Type: `application/json`
- Status: 200 OK

**レスポンスボディ**:
```json
{
  "success": true,
  "recording": {
    "supported": true,
    "state": "idle",
    "camera": "camera1",
    "job_id": "",
    "start_at": "",
    "scheduled_at": "",
    "started_at": "",
    "ended_at": "",
    "duration_sec": 0,
    "remaining_sec": 0,
    "output_path": "",
    "error": ""
  }
}
```

---

### DELETE /manual_recording/{path}

**説明**: 手動録画の MP4 と対応するサムネイル JPEG を削除

**補足**:
- 対象は `manual_recordings` 配下の `.mp4` のみ
- 同名 `.jpg` があれば合わせて削除

**使用例**:
```bash
curl -X DELETE "http://localhost:8080/manual_recording/camera1/manual_recordings/camera1/manual_camera1_20260319_213000_90s.mp4" | jq
```

---

### POST /camera_recording_schedule/{index}

**説明**: 指定カメラの手動録画を予約または即時開始

**リクエストボディ**:
```json
{
  "start_at": "2026-03-19T21:30:00",
  "duration_sec": 90
}
```

**補足**:
- `start_at` を空文字または省略すると即時開始
- `duration_sec` は 1 以上 86400 以下

**使用例**:
```bash
curl -X POST "http://localhost:8080/camera_recording_schedule/0" \
  -H "Content-Type: application/json" \
  -d '{"start_at":"2026-03-19T21:30:00","duration_sec":90}' | jq
```

---

### POST /camera_recording_stop/{index}

**説明**: 予約中または録画中の手動録画を停止

**レスポンス**:
- Content-Type: `application/json`
- Status: 200 OK

**使用例**:
```bash
curl -X POST "http://localhost:8080/camera_recording_stop/0" | jq
```

---

### POST /camera_restart/{index}

**説明**: 指定カメラに再起動を要求（非同期）

**URLパラメータ**:

| パラメータ | 型 | 説明 | 例 |
|-----------|-----|------|-----|
| `index` | integer | カメラインデックス（0始まり） | `1` |

**レスポンス**:
- Content-Type: `application/json`
- Status: 202 Accepted

**レスポンスボディ**:
```json
{
  "success": true,
  "message": "restart requested"
}
```

**使用例**:
```bash
curl -X POST "http://localhost:8080/camera_restart/1" | jq
```

---

### POST /youtube_start/{index}

**説明**: 指定カメラのYouTube Live配信を開始する。dashboard コンテナ内で ffmpeg サブプロセスを起動し、go2rtc の RTSP リレー経由で YouTube へ直接 RTMP 送信する。

**URLパラメータ**:

| パラメータ | 型 | 説明 | 例 |
|-----------|-----|------|-----|
| `index` | integer | カメラインデックス（0始まり） | `2` |

**前提条件**: 対象カメラに `CAMERA{i}_YOUTUBE_KEY` が設定されていること

**レスポンス**:
- Content-Type: `application/json`
- Status: 200 OK / 400 Bad Request / 502 Bad Gateway

```json
{"success": true}
```

**使用例**:
```bash
curl -X POST "http://localhost:8080/youtube_start/2" | jq
```

---

### POST /youtube_stop/{index}

**説明**: 指定カメラのYouTube Live配信を停止する。dashboard コンテナ内の ffmpeg サブプロセスを terminate/kill で確実に終了する。

**URLパラメータ**:

| パラメータ | 型 | 説明 | 例 |
|-----------|-----|------|-----|
| `index` | integer | カメラインデックス（0始まり） | `2` |

**レスポンス**:
- Content-Type: `application/json`
- Status: 200 OK / 400 Bad Request / 502 Bad Gateway

```json
{"success": true}
```

**使用例**:
```bash
curl -X POST "http://localhost:8080/youtube_stop/2" | jq
```

---

### GET /youtube_status/{index}

**説明**: 指定カメラのYouTube Live配信状態を取得する。dashboard コンテナ内の ffmpeg サブプロセスの生死を確認。

**URLパラメータ**:

| パラメータ | 型 | 説明 | 例 |
|-----------|-----|------|-----|
| `index` | integer | カメラインデックス（0始まり） | `2` |

**レスポンス**:
- Content-Type: `application/json`
- Status: 200 OK

```json
{"streaming": true}
```

**使用例**:
```bash
curl "http://localhost:8080/youtube_status/2" | jq
```

---

### GET /camera_settings/current

**説明**: 各カメラの `/stats.settings` を取得し、設定ページ表示用に返す

**レスポンス**:
- Content-Type: `application/json`
- Status: 200 OK

**レスポンスボディ（例）**:
```json
{
  "success": true,
  "settings": {
    "diff_threshold": 20,
    "nuisance_overlap_threshold": 0.6
  },
  "results": [
    {
      "camera": "camera1",
      "success": true,
      "settings": {
        "diff_threshold": 20
      }
    }
  ],
  "ok_count": 1,
  "total": 1
}
```

**使用例**:
```bash
curl -s http://localhost:8080/camera_settings/current | jq
```

---

### POST /camera_settings/apply_all

**説明**: 指定した設定値を全カメラへ一括適用（各カメラの `POST /apply_settings` を呼び出し）

**リクエストボディ（例）**:
```json
{
  "diff_threshold": 20,
  "min_brightness": 180,
  "nuisance_overlap_threshold": 0.60,
  "nuisance_path_overlap_threshold": 0.70,
  "min_track_points": 4,
  "max_stationary_ratio": 0.40
}
```

**レスポンス**:
- Content-Type: `application/json`
- Status: 200 OK

**レスポンスボディ（例）**:
```json
{
  "success": true,
  "applied_count": 3,
  "total": 3,
  "results": [
    {
      "camera": "camera1",
      "success": true,
      "response": {
        "success": true,
        "restart_required": true,
        "restart_requested": true,
        "restart_triggers": ["sensitivity", "scale"]
      }
    },
    { "camera": "camera2", "success": true, "response": { "success": true } },
    { "camera": "camera3", "success": false, "error": "timeout" }
  ]
}
```

**使用例**:
```bash
curl -X POST "http://localhost:8080/camera_settings/apply_all" \
  -H "Content-Type: application/json" \
  -d '{"diff_threshold":20,"nuisance_overlap_threshold":0.60}' | jq
```

---

### DELETE /detection/{camera}/{id}

**説明**: 検出結果を削除（動画、画像、JSONLエントリ）

**URLパラメータ**:

| パラメータ | 型 | 説明 | 例 |
|-----------|-----|------|-----|
| `camera` | string | カメラディレクトリ名 | `camera1` |
| `id` | string | 検出ID（`/detections` レスポンスの `id` フィールド） | `det_a1b2c3d4e5f6789012` |

**レスポンス**:
- Content-Type: `application/json`
- Status: 200 OK

**成功レスポンス**:
```json
{
  "success": true,
  "id": "det_a1b2c3d4e5f6789012",
  "deleted_files": [
    "meteor_20260202_065533.mp4",
    "meteor_20260202_065533_composite.jpg",
    "meteor_20260202_065533_composite_original.jpg"
  ],
  "message": "3個のファイルを削除しました"
}
```

**エラーレスポンス**:
```json
{
  "success": false,
  "error": "detection id not found: camera1 det_a1b2c3d4e5f6789012"
}
```

**使用例**:
```bash
# curlで削除（idは/detectionsで取得）
curl -X DELETE "http://localhost:8080/detection/camera1/det_a1b2c3d4e5f6789012"

# JavaScriptから削除
fetch(`/detection/camera1/${detectionId}`, {
  method: 'DELETE'
})
.then(r => r.json())
.then(data => {
  if (data.success) {
    alert(data.message);
  } else {
    alert('削除失敗: ' + data.error);
  }
});
```

---

### GET /dashboard_stats

**説明**: ダッシュボードプロセスの CPU 使用率を取得

**レスポンス**:
- Content-Type: `application/json`
- Status: 200 OK

**レスポンスボディ**:
```json
{
  "cpu_percent": 12.3
}
```

**フィールド説明**:

| フィールド | 型 | 説明 |
|-----------|-----|------|
| `cpu_percent` | float | CPU使用率（%、0.0〜100.0） |

**使用例**:
```bash
curl http://localhost:8080/dashboard_stats | jq
```

---

### POST /bulk_delete_non_meteor/{camera_name}

**説明**: 指定カメラの「それ以外」検出（ラベルが `post_detected` の検出）を一括削除（v1.18.0）

**URLパラメータ**:

| パラメータ | 型 | 説明 | 例 |
|-----------|-----|------|-----|
| `camera_name` | string | カメラディレクトリ名 | `camera1` |

**レスポンス**:
- Content-Type: `application/json`
- Status: 200 OK

**成功レスポンス**:
```json
{
  "success": true,
  "deleted_count": 5,
  "deleted_detections": [
    {
      "time": "2026-02-02 06:55:33",
      "deleted_files": [
        "meteor_20260202_065533.mp4",
        "meteor_20260202_065533_composite.jpg",
        "meteor_20260202_065533_composite_original.jpg"
      ]
    },
    {
      "time": "2026-02-02 05:32:18",
      "deleted_files": [
        "meteor_20260202_053218.mp4",
        "meteor_20260202_053218_composite.jpg",
        "meteor_20260202_053218_composite_original.jpg"
      ]
    }
  ],
  "message": "5件の非流星検出を削除しました（合計15ファイル）"
}
```

**エラーレスポンス**:
```json
{
  "success": false,
  "error": "camera directory not found: camera1"
}
```

**使用例**:
```bash
# curlで一括削除
curl -X POST "http://localhost:8080/bulk_delete_non_meteor/camera1" | jq

# JavaScriptから一括削除
fetch('/bulk_delete_non_meteor/camera1', {
  method: 'POST'
})
.then(r => r.json())
.then(data => {
  if (data.success) {
    alert(`${data.deleted_count}件の「それ以外」検出を削除しました`);
  } else {
    alert('削除失敗: ' + data.error);
  }
});
```

---

### POST /detection_label

**説明**: 検出にラベルを設定（v1.10.0）

**リクエストボディ**:
```json
{
  "camera": "camera1",
  "id": "det_a1b2c3d4e5f6789012",
  "label": "detected"
}
```

**パラメータ説明**:

| パラメータ | 型 | 必須 | 説明 | 例 |
|-----------|-----|------|------|-----|
| `camera` | string | Yes | カメラディレクトリ名 | `camera1` |
| `id` | string | Yes | 検出ID（`/detections` レスポンスの `id` フィールド） | `det_a1b2c3d4e5f6789012` |
| `label` | string | Yes | ラベル（`detected` または `post_detected`） | `detected` |

**レスポンス**:
- Content-Type: `application/json`
- Status: 200 OK

**成功レスポンス**:
```json
{
  "success": true,
  "message": "Label updated"
}
```

**エラーレスポンス**:
```json
{
  "success": false,
  "error": "Detection not found"
}
```

**使用例**:
```bash
# curlでラベル設定
curl -X POST "http://localhost:8080/detection_label" \
  -H "Content-Type: application/json" \
  -d '{
    "camera": "camera1",
    "id": "det_a1b2c3d4e5f6789012",
    "label": "detected"
  }' | jq

# JavaScriptからラベル設定
fetch('/detection_label', {
  method: 'POST',
  headers: {'Content-Type': 'application/json'},
  body: JSON.stringify({
    camera: 'camera1',
    id: detectionId,
    label: 'detected'
  })
})
.then(r => r.json())
.then(data => {
  if (data.success) {
    alert('ラベル設定完了');
  } else {
    alert('エラー: ' + data.error);
  }
});
```

**ラベルの活用**:
- `detected`: 流星として確認済み
- `post_detected`: 自動検出後に「それ以外」と判定されたもの（`bulk_delete_non_meteor` の削除対象）

---

### GET /changelog

**説明**: CHANGELOG.mdの内容を取得

**レスポンス**:
- Content-Type: `text/plain; charset=utf-8`
- Status: 200 OK
- Body: CHANGELOG.mdの内容（テキスト）

**使用例**:
```bash
curl http://localhost:8080/changelog
```

---

### GET /stats

**説明**: カメラ別・夜別（日没〜翌日の日の出）の流星統計を表示するHTMLページ。
ナビゲーションバーの「統計」タブから遷移する。データは `/stats_data` から非同期取得する。

**レスポンス**:
- Content-Type: `text/html; charset=utf-8`
- Status: 200 OK

**使用例**:
```
http://localhost:8080/stats
```

---

### GET /stats_data

**説明**: カメラ別・夜別（日没〜翌日の日の出）の流星統計をJSONで返す。
複数カメラが5秒以内に同一流星を検出した場合は重複除去し1件として集計する。

**クエリパラメータ**:
| パラメータ | 型 | デフォルト | 説明 |
|-----------|-----|---------|------|
| `days` | integer | 30 | 遡る日数（1〜365） |

**レスポンス**:
- Content-Type: `application/json`
- Status: 200 OK

```json
{
  "nights": [
    {
      "date": "2026-04-12",
      "sunset": "2026-04-12 18:30",
      "sunrise": "2026-04-13 05:20",
      "total": 7,
      "by_camera": {
        "East": 4,
        "South": 3,
        "West": 2
      },
      "duplicates": 2,
      "ongoing": false
    }
  ],
  "cameras": ["East", "South", "West"],
  "total_events": 73,
  "hourly": {
    "hours": [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23],
    "cameras": ["East", "South", "West"],
    "by_hour": {
      "East": [0, 0, 3, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 5, 2, 1],
      "South": [0, 0, 2, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 3, 1, 0],
      "West": [0, 0, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 2, 0, 0]
    }
  }
}
```

| フィールド | 説明 |
|-----------|------|
| `nights` | 夜ごとの集計（新しい順） |
| `nights[].date` | 日没側の日付（YYYY-MM-DD） |
| `nights[].total` | 重複除去後の流星数 |
| `nights[].by_camera` | カメラ表示名ごとの検出数 |
| `nights[].duplicates` | 重複として除去した件数 |
| `nights[].ongoing` | 現在進行中の夜（日の出前）の場合 true |
| `cameras` | カメラ表示名一覧 |
| `total_events` | 全期間の流星総数（重複除去後） |
| `hourly` | 時間帯別集計（集計期間全体の合算） |
| `hourly.hours` | 時刻一覧（0〜23の固定配列） |
| `hourly.cameras` | カメラ表示名一覧 |
| `hourly.by_hour` | カメラ表示名ごとの時刻別検出数（インデックス=時刻） |

**使用例**:
```bash
# 過去30日分を取得
curl http://localhost:8080/stats_data

# 過去90日分を取得
curl "http://localhost:8080/stats_data?days=90"
```

---

## meteor_detector_rtsp_web.py API

各カメラコンテナが提供するエンドポイント（デフォルトポート: 8080）

### エンドポイント一覧

| エンドポイント | メソッド | 説明 |
|--------------|---------|------|
| `/` | GET | プレビューHTML |
| `/stream` | GET | MJPEGストリーム |
| `/snapshot` | GET | 現在フレームJPEG |
| `/stats` | GET | 統計情報 |
| `/recording/status` | GET | 手動録画状態取得 |
| `/recording/schedule` | POST | 手動録画の予約/即時開始 |
| `/recording/stop` | POST | 手動録画の停止 |
| `/update_mask` | POST | 現在フレームからマスク再生成 |
| `/apply_settings` | POST | 設定値をランタイム反映 |
| `/restart` | POST | プロセス再起動要求 |

---

### GET /

**説明**: カメラプレビューのHTMLページを返す

**レスポンス**:
- Content-Type: `text/html; charset=utf-8`
- Status: 200 OK

**使用例**:
```bash
# camera1のプレビュー
curl http://localhost:8081/

# ブラウザで開く
open http://localhost:8081/
```

---

### GET /stream

**説明**: MJPEGストリーム（Motion JPEG）を返す

**補足**:
- 各カメラコンテナ (`meteor_detector_rtsp_web.py`) が提供するライブ表示用エンドポイント
- ダッシュボードが `mjpeg` 構成のときはブラウザがこのURLを直接参照
- ダッシュボードが `webrtc` 構成のときは、ライブ表示の主経路は `go2rtc` 経由になり、この `/stream` は主表示には使われません

**レスポンス**:
- Content-Type: `multipart/x-mixed-replace; boundary=frame`
- Status: 200 OK
- Body: 連続的なJPEGフレーム（約30fps）

**ストリームフォーマット**:
```
--frame\r\n
Content-Type: image/jpeg\r\n\r\n
<JPEG binary data>
\r\n
--frame\r\n
Content-Type: image/jpeg\r\n\r\n
<JPEG binary data>
\r\n
...
```

**使用例**:
```bash
# HTMLで表示
<img src="http://localhost:8081/stream" alt="Live Stream">

# VLCで再生
vlc http://localhost:8081/stream

# ffmpegで録画
ffmpeg -i http://localhost:8081/stream -t 60 output.mp4
```

**特徴**:
- リアルタイムプレビュー
- 検出中の物体が緑丸で表示
- 追跡中の軌跡が黄線で表示
- 流星検出時に赤で表示
- フレームレート: 約30fps
- 画質: JPEG品質70%

---

### GET /stats

**説明**: カメラの統計情報を取得

**レスポンス**:
- Content-Type: `application/json`
- Status: 200 OK

**レスポンスボディ**:
```json
{
  "detections": 5,
  "elapsed": 3600.5,
  "camera": "camera1",
  "settings": {
    "sensitivity": "medium",
    "scale": 0.5,
    "buffer": 15.0,
    "extract_clips": true,
    "source_fps": 20.0,
    "exclude_bottom": 0.0625,
    "exclude_bottom_ratio": 0.0625,
    "mask_image": "/app/mask_image.png",
    "mask_from_day": "",
    "mask_dilate": 5,
    "nuisance_mask_image": "",
    "nuisance_from_night": "",
    "nuisance_dilate": 3,
    "nuisance_overlap_threshold": 0.6
  },
  "runtime_fps": 19.83,
  "stream_alive": true,
  "time_since_last_frame": 0.03,
  "is_detecting": true,
  "detection_status": "DETECTING",
  "detection_window_enabled": true,
  "detection_window_active": true,
  "detection_window_start": "2026-03-09 17:46:53",
  "detection_window_end": "2026-03-10 06:03:38",
  "twilight_active": false,
  "twilight_detection_mode": "reduce",
  "twilight_type": "nautical",
  "recording": {
    "supported": true,
    "state": "scheduled",
    "start_at": "2026-03-19T21:30:00+09:00",
    "duration_sec": 90,
    "remaining_sec": 42,
    "output_path": "/output/manual_recordings/camera1/manual_camera1_20260319_213000_90s.mp4",
    "error": ""
  }
}
```

**フィールド説明**:

| フィールド | 型 | 説明 |
|-----------|-----|------|
| `detections` | integer | 検出数 |
| `elapsed` | float | 稼働時間（秒） |
| `camera` | string | カメラ名 |
| `settings` | object | 設定情報 |
| `settings.sensitivity` | string | 感度プリセット |
| `settings.scale` | float | 処理スケール |
| `settings.buffer` | float | バッファ秒数 |
| `settings.extract_clips` | boolean | 動画保存の有効/無効 |
| `settings.source_fps` | float | 接続時に取得した入力ストリームFPS |
| `settings.exclude_bottom` | float | 画面下部除外率 |
| `settings.exclude_bottom_ratio` | float | 画面下部除外率（内部キー） |
| `settings.exclude_edge_ratio` | float | 画面端ノイズ除外率（v1.16.0、デフォルト0.0） |
| `settings.clip_margin_before` | float | 録画前マージン秒数（v1.14.0、デフォルト0.5） |
| `settings.clip_margin_after` | float | 録画後マージン秒数（v1.14.0、デフォルト0.5） |
| `settings.mask_image` | string | マスク画像（優先） |
| `settings.mask_from_day` | string | 昼間画像から生成するマスク |
| `settings.mask_dilate` | integer | マスク拡張ピクセル数 |
| `settings.nuisance_overlap_threshold` | float | ノイズ帯重なり閾値 |
| `settings.nuisance_path_overlap_threshold` | float | ノイズ帯経路重なり閾値 |
| `settings.min_track_points` | integer | 最小追跡点数 |
| `settings.max_stationary_ratio` | float | 静止率上限 |
| `settings.small_area_threshold` | integer | 小領域判定閾値 |
| `settings.nuisance_mask_image` | string | ノイズ帯マスク画像 |
| `settings.nuisance_from_night` | string | 夜間画像からのノイズ帯生成元 |
| `settings.nuisance_dilate` | integer | ノイズ帯マスク拡張ピクセル数 |
| `runtime_fps` | float | 直近フレームから算出した実効FPS |
| `stream_alive` | boolean | ストリーム生存確認 |
| `time_since_last_frame` | float | 最終フレームからの経過時間（秒） |
| `is_detecting` | boolean | 現在検出処理中か |
| `detection_status` | string | 検出状態詳細。`DETECTING` / `OUT_OF_WINDOW` / `TWILIGHT_SKIP` / `WAITING_FRAME` / `STREAM_LOST` |
| `detection_window_enabled` | boolean | 検出時間帯制限が有効か |
| `detection_window_active` | boolean | 現在が検出時間帯内か |
| `detection_window_start` | string | 現在参照中の検出開始時刻 |
| `detection_window_end` | string | 現在参照中の検出終了時刻 |
| `twilight_active` | boolean | 現在が薄明期間内か |
| `twilight_detection_mode` | string | 薄明時の検出モード。`reduce`（感度低下）/ `skip`（検出停止） |
| `twilight_type` | string | 薄明種別。`civil` / `nautical` / `astronomical` |
| `recording` | object | 手動録画状態 |
| `recording.supported` | boolean | 手動録画機能が利用可能か |
| `recording.state` | string | `idle` / `scheduled` / `recording` / `completed` / `failed` / `stopped` |
| `recording.start_at` | string | 予約開始時刻 |
| `recording.duration_sec` | integer | 録画予定秒数 |
| `recording.remaining_sec` | integer | 残り秒数 |
| `recording.output_path` | string | 保存先MP4パス |
| `recording.error` | string | 失敗・停止理由 |

**使用例**:
```bash
# curlで取得
curl http://localhost:8081/stats | jq

# 検出数のみ取得
curl -s http://localhost:8081/stats | jq '.detections'

# ストリーム状態を確認
curl -s http://localhost:8081/stats | jq '.stream_alive'

# 全カメラの統計を一括取得
for port in 8081 8082 8083; do
  echo "Port $port:"
  curl -s "http://localhost:$port/stats" | jq '{camera, detections, stream_alive}'
done

# JavaScriptから定期取得
setInterval(() => {
  fetch('http://localhost:8081/stats')
    .then(r => r.json())
    .then(data => {
      console.log('Detections:', data.detections);
      console.log('Stream alive:', data.stream_alive);
      console.log('Is detecting:', data.is_detecting);
    });
}, 2000);  // 2秒ごと
```

---

### GET /recording/status

**説明**: カメラコンテナ内の手動録画状態を取得

**レスポンス**:
- Content-Type: `application/json`
- Status: 200 OK

**レスポンスボディ**:
```json
{
  "success": true,
  "recording": {
    "supported": true,
    "state": "recording",
    "camera": "camera1",
    "job_id": "rec_1742387400000",
    "start_at": "2026-03-19T21:30:00+09:00",
    "scheduled_at": "2026-03-19T21:29:10+09:00",
    "started_at": "2026-03-19T21:30:00+09:00",
    "ended_at": "",
    "duration_sec": 90,
    "remaining_sec": 37,
    "output_path": "/output/manual_recordings/camera1/manual_camera1_20260319_213000_90s.mp4",
    "error": ""
  }
}
```

---

### POST /recording/schedule

**説明**: RTSP入力を `ffmpeg` で MP4 へ保存する手動録画ジョブを予約または即時開始

**リクエストボディ**:
```json
{
  "start_at": "2026-03-19T21:30:00",
  "duration_sec": 90
}
```

**補足**:
- `start_at` 省略時は即時開始
- 既に `scheduled` または `recording` のジョブがある場合は失敗
- 保存先は `manual_recordings/<camera>/` 配下

---

### POST /recording/stop

**説明**: 予約中または録画中の手動録画ジョブを停止

**レスポンス**:
- Content-Type: `application/json`
- Status: 200 OK

---

### GET /snapshot

**説明**: 現在フレームをJPEGで取得

**レスポンス**:
- Content-Type: `image/jpeg`
- Status: 200 OK

**使用例**:
```bash
curl "http://localhost:8081/snapshot" --output camera1_snapshot.jpg
```

---

### POST /update_mask

**説明**: 現在フレームから除外マスクを再生成して即時反映（固定カメラ向け）

**レスポンス**:
- Content-Type: `application/json`
- Status: 200 OK

**レスポンスボディ**:
```json
{
  "success": true,
  "message": "mask updated",
  "saved": "/output/masks/camera1_mask.png"
}
```

**フィールド説明**:

| フィールド | 型 | 説明 |
|-----------|-----|------|
| `success` | boolean | 更新成功/失敗 |
| `message` | string | 結果メッセージ |
| `saved` | string | 保存先（永続化ファイル） |

**使用例**:
```bash
# マスク更新
curl -X POST http://localhost:8081/update_mask | jq
```

---

### POST /apply_settings

**説明**: 設定をランタイム反映。起動時依存の項目は設定保存後に自動再起動を要求

**リクエストボディ（例）**:
```json
{
  "sensitivity": "medium",
  "scale": 0.5,
  "buffer": 15,
  "extract_clips": true,
  "diff_threshold": 20,
  "min_brightness": 180,
  "min_linearity": 0.7,
  "nuisance_overlap_threshold": 0.6,
  "nuisance_path_overlap_threshold": 0.7,
  "min_track_points": 4,
  "max_stationary_ratio": 0.4,
  "small_area_threshold": 40,
  "mask_dilate": 20,
  "nuisance_dilate": 3,
  "exclude_edge_ratio": 0.0,
  "clip_margin_before": 0.5,
  "clip_margin_after": 0.5
}
```

**レスポンスボディ（例）**:
```json
{
  "success": true,
  "applied": {
    "sensitivity": "medium",
    "scale": 0.5,
    "diff_threshold": 20
  },
  "errors": [],
  "restart_required": true,
  "restart_requested": true,
  "restart_triggers": ["sensitivity", "scale"]
}
```

**反映ルール**:
- 再起動不要: `diff_threshold` など検出ロジック/誤検出抑制の閾値群
- 自動再起動で反映: `sensitivity` / `scale` / `buffer` / `extract_clips`
- 設定は `output/runtime_settings/<camera>.json` に永続化され、再起動後も維持

**使用例**:
```bash
curl -X POST http://localhost:8081/apply_settings \
  -H "Content-Type: application/json" \
  -d '{"diff_threshold":20,"nuisance_overlap_threshold":0.60}' | jq
```

---

### POST /restart

**説明**: カメラプロセスへ再起動を要求（Dockerの `restart: unless-stopped` 運用を想定）

**レスポンス**:
- Content-Type: `application/json`
- Status: 202 Accepted

**レスポンスボディ**:
```json
{
  "success": true,
  "message": "restart requested"
}
```

**使用例**:
```bash
curl -X POST http://localhost:8081/restart | jq
```

---

## 共通仕様

### CORS（Cross-Origin Resource Sharing）

**現在の設定**:
```python
# /stats /update_mask /apply_settings /restart はCORS許可
self.send_header('Access-Control-Allow-Origin', '*')
```

**制限事項**:
- 他のエンドポイントはCORS未対応
- 外部ドメインからのアクセスは制限される

**カスタマイズ例**:
```python
# すべてのエンドポイントでCORS許可（セキュリティ注意）
def end_headers(self):
    self.send_header('Access-Control-Allow-Origin', '*')
    self.send_header('Access-Control-Allow-Methods', 'GET, POST, DELETE')
    self.send_header('Access-Control-Allow-Headers', 'Content-Type')
    BaseHTTPRequestHandler.end_headers(self)
```

---

### レート制限

**現在の制限**: なし

**推奨実装** (Nginxリバースプロキシ):
```nginx
# /etc/nginx/sites-available/meteor
limit_req_zone $binary_remote_addr zone=api:10m rate=10r/s;

server {
    location /api/ {
        limit_req zone=api burst=20;
        proxy_pass http://localhost:8080/;
    }
}
```

---

### タイムアウト

| エンドポイント | タイムアウト | 理由 |
|--------------|------------|------|
| `/stream` | なし | ストリーミング |
| その他 | 30秒 | ブラウザデフォルト |

---

## 環境変数

### カメラ監視機能（v1.17.0）

カメラの自動監視と再起動を制御する環境変数です。

| 環境変数 | デフォルト | 説明 |
|---------|----------|------|
| `CAMERA_MONITOR_ENABLED` | `true` | カメラ監視機能の有効/無効 |
| `CAMERA_MONITOR_INTERVAL` | `2.0` | 監視チェック間隔（秒） |
| `CAMERA_MONITOR_TIMEOUT` | `6.0` | カメラ統計取得タイムアウト（秒） |
| `CAMERA_RESTART_TIMEOUT` | `5.0` | 再起動リクエストタイムアウト（秒） |
| `CAMERA_RESTART_COOLDOWN_SEC` | `120` | 再起動後のクールダウン時間（秒） |
| `CAMERA_MONITOR_FAIL_THRESHOLD` | `12` | 統計取得失敗が連続でこの回数に達すると再起動を試みる |
| `DETECTION_MONITOR_INTERVAL` | `2.0` | 検出キャッシュ更新間隔（秒） |

**使用例（docker-compose.yml）**:
```yaml
services:
  dashboard:
    image: meteor-dashboard:latest
    environment:
      - CAMERA_MONITOR_ENABLED=true
      - CAMERA_MONITOR_INTERVAL=2.0
      - CAMERA_MONITOR_TIMEOUT=6.0
      - CAMERA_RESTART_TIMEOUT=5.0
      - CAMERA_RESTART_COOLDOWN_SEC=120
      - CAMERA_MONITOR_FAIL_THRESHOLD=12
    ports:
      - "8080:8080"
```

**監視機能の動作**:
1. 各カメラの `/stats` エンドポイントを定期的に確認
2. `time_since_last_frame` が `CAMERA_MONITOR_TIMEOUT` を超えた場合、フレーム停止と判定
3. `CAMERA_RESTART_ENABLED=true` の場合、自動的に `/restart` を呼び出し
4. 再起動回数が `CAMERA_RESTART_MAX_COUNT` を超えると監視を停止
5. 監視状態は `/camera_stats/{index}` で確認可能

**監視を無効化する場合**:
```yaml
environment:
  - CAMERA_MONITOR_ENABLED=false
```

---

## エラーコード

### HTTPステータスコード

| コード | 説明 | 発生条件 |
|-------|------|---------|
| 200 | OK | 成功 |
| 404 | Not Found | ファイルまたはエンドポイントが存在しない |
| 500 | Internal Server Error | サーバー内部エラー |

### エラーレスポンス例

```json
{
  "success": false,
  "error": "File not found"
}
```

---

## 使用例

### Python

```python
import requests

# 検出一覧を取得
response = requests.get('http://localhost:8080/detections')
data = response.json()
print(f"Total detections: {data['total']}")

# 統計情報を取得
stats = requests.get('http://localhost:8081/stats').json()
print(f"Camera: {stats['camera']}, Detections: {stats['detections']}")

# 検出結果を削除
delete_response = requests.delete(
    'http://localhost:8080/detection/camera1/2026-02-02 06:55:33'
)
print(delete_response.json())
```

---

### JavaScript（ブラウザ）

```javascript
// 検出一覧を取得して表示
async function loadDetections() {
  const response = await fetch('/detections');
  const data = await response.json();

  console.log(`Total: ${data.total}`);
  data.recent.forEach(detection => {
    console.log(`${detection.time} - ${detection.camera} (${detection.confidence})`);
  });
}

// 統計情報を定期取得
setInterval(async () => {
  const stats = await fetch('http://localhost:8081/stats').then(r => r.json());
  document.getElementById('detections').textContent = stats.detections;
  document.getElementById('status').textContent = stats.stream_alive ? 'Online' : 'Offline';
}, 2000);

// 検出結果を削除
async function deleteDetection(camera, timestamp) {
  const response = await fetch(`/detection/${camera}/${timestamp}`, {
    method: 'DELETE'
  });
  const result = await response.json();

  if (result.success) {
    alert(result.message);
    loadDetections();  // リストを更新
  } else {
    alert(`Error: ${result.error}`);
  }
}

// 非流星検出を一括削除
async function bulkDeleteNonMeteor(camera) {
  const response = await fetch(`/bulk_delete_non_meteor/${camera}`, {
    method: 'POST'
  });
  const result = await response.json();

  if (result.success) {
    alert(`${result.deleted_count}件の非流星検出を削除しました`);
    loadDetections();  // リストを更新
  } else {
    alert(`Error: ${result.error}`);
  }
}

// 検出にラベルを設定
async function setDetectionLabel(camera, timestamp, label) {
  const response = await fetch('/detection_label', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({camera, timestamp, label})
  });
  const result = await response.json();

  if (result.success) {
    alert('ラベル設定完了');
    loadDetections();  // リストを更新
  } else {
    alert(`Error: ${result.error}`);
  }
}
```

---

### Node.js

```javascript
const axios = require('axios');

// 全カメラの統計を取得
async function getAllStats() {
  const cameras = [8081, 8082, 8083];
  const promises = cameras.map(port =>
    axios.get(`http://localhost:${port}/stats`)
  );

  const results = await Promise.all(promises);
  results.forEach((res, i) => {
    console.log(`Camera ${i+1}:`, res.data.detections, 'detections');
  });
}

getAllStats();
```

---

### Bash

```bash
#!/bin/bash
# 全カメラの統計を表示

echo "=== Meteor Detection Stats ==="
for port in 8081 8082 8083; do
  stats=$(curl -s "http://localhost:$port/stats")
  camera=$(echo "$stats" | jq -r '.camera')
  detections=$(echo "$stats" | jq -r '.detections')
  alive=$(echo "$stats" | jq -r '.stream_alive')

  echo "$camera: $detections detections (stream: $alive)"
done

# 検出一覧を取得
echo ""
echo "=== Recent Detections ==="
curl -s "http://localhost:8080/detections" | \
  jq -r '.recent[] | "\(.time) - \(.camera) (\(.confidence))"'
```

---

### PowerShell

```powershell
# 検出一覧を取得
$detections = Invoke-RestMethod -Uri "http://localhost:8080/detections"
Write-Host "Total detections: $($detections.total)"

# 統計情報を取得
$stats = Invoke-RestMethod -Uri "http://localhost:8081/stats"
Write-Host "Camera: $($stats.camera), Detections: $($stats.detections)"

# 検出結果を削除
$deleteResult = Invoke-RestMethod `
  -Uri "http://localhost:8080/detection/camera1/2026-02-02%2006:55:33" `
  -Method Delete
Write-Host $deleteResult.message
```

---

## Webhook連携例

### 検出時にSlackに通知

```python
# webhook_notifier.py
import requests
import time
import json

SLACK_WEBHOOK_URL = "https://hooks.slack.com/services/YOUR/WEBHOOK/URL"
last_count = {}

def check_detections():
    for port in [8081, 8082, 8083]:
        stats = requests.get(f'http://localhost:{port}/stats').json()
        camera = stats['camera']
        count = stats['detections']

        if camera not in last_count:
            last_count[camera] = count

        if count > last_count[camera]:
            # 新しい検出があった
            message = {
                "text": f"🌠 流星検出！\nカメラ: {camera}\n検出数: {count}"
            }
            requests.post(SLACK_WEBHOOK_URL, json=message)
            last_count[camera] = count

# 10秒ごとに確認
while True:
    check_detections()
    time.sleep(10)
```

---

### 検出時にメール送信

```python
# email_notifier.py
import requests
import smtplib
from email.mime.text import MIMEText

def send_email(subject, body):
    msg = MIMEText(body)
    msg['Subject'] = subject
    msg['From'] = 'meteor@example.com'
    msg['To'] = 'admin@example.com'

    with smtplib.SMTP('smtp.example.com', 587) as server:
        server.starttls()
        server.login('user', 'password')
        server.send_message(msg)

def monitor():
    last_count = {}
    while True:
        detections = requests.get('http://localhost:8080/detections').json()

        for detection in detections['recent']:
            key = f"{detection['camera']}_{detection['time']}"
            if key not in last_count:
                send_email(
                    f"流星検出: {detection['camera']}",
                    f"時刻: {detection['time']}\n信頼度: {detection['confidence']}"
                )
                last_count[key] = True

        time.sleep(30)

monitor()
```

---

## APIクライアントライブラリ例

### Python用シンプルクライアント

```python
# meteor_client.py
import requests
from typing import List, Dict, Optional

class MeteorDetectionClient:
    def __init__(self, dashboard_url: str = "http://localhost:8080"):
        self.dashboard_url = dashboard_url

    def get_detections(self) -> Dict:
        """検出一覧を取得"""
        response = requests.get(f"{self.dashboard_url}/detections")
        return response.json()

    def get_detection_window(self, lat: float = None, lon: float = None) -> Dict:
        """検出時間帯を取得"""
        params = {}
        if lat: params['lat'] = lat
        if lon: params['lon'] = lon

        response = requests.get(
            f"{self.dashboard_url}/detection_window",
            params=params
        )
        return response.json()

    def delete_detection(self, camera: str, timestamp: str) -> Dict:
        """検出結果を削除"""
        response = requests.delete(
            f"{self.dashboard_url}/detection/{camera}/{timestamp}"
        )
        return response.json()

    def bulk_delete_non_meteor(self, camera: str) -> Dict:
        """非流星検出を一括削除"""
        response = requests.post(
            f"{self.dashboard_url}/bulk_delete_non_meteor/{camera}"
        )
        return response.json()

    def set_detection_label(self, camera: str, timestamp: str, label: str) -> Dict:
        """検出にラベルを設定"""
        response = requests.post(
            f"{self.dashboard_url}/detection_label",
            json={"camera": camera, "timestamp": timestamp, "label": label}
        )
        return response.json()

    def get_camera_stats(self, port: int) -> Dict:
        """カメラの統計情報を取得"""
        response = requests.get(f"http://localhost:{port}/stats")
        return response.json()

    def get_camera_stats_from_dashboard(self, index: int) -> Dict:
        """ダッシュボード経由でカメラ統計を取得（監視情報含む）"""
        response = requests.get(f"{self.dashboard_url}/camera_stats/{index}")
        return response.json()

# 使用例
if __name__ == "__main__":
    client = MeteorDetectionClient()

    # 検出一覧を取得
    detections = client.get_detections()
    print(f"Total: {detections['total']}")

    # カメラ統計を取得
    stats = client.get_camera_stats(8081)
    print(f"Camera: {stats['camera']}, Detections: {stats['detections']}")

    # ダッシュボード経由でカメラ統計取得（監視情報含む）
    dashboard_stats = client.get_camera_stats_from_dashboard(0)
    print(f"Monitor enabled: {dashboard_stats['monitor_enabled']}")
    print(f"Restart count: {dashboard_stats['monitor_restart_count']}")

    # 検出にラベルを設定
    result = client.set_detection_label(
        camera="camera1",
        timestamp="2026-02-02 06:55:33",
        label="meteor"
    )
    print(result)

    # 非流星検出を一括削除
    delete_result = client.bulk_delete_non_meteor("camera1")
    print(f"Deleted {delete_result['deleted_count']} non-meteor detections")
```

---

## 関連ドキュメント

- [OPERATIONS_GUIDE.md](OPERATIONS_GUIDE.md) - 運用ガイド
- [ARCHITECTURE.md](ARCHITECTURE.md) - システムアーキテクチャ
- [DETECTOR_COMPONENTS.md](DETECTOR_COMPONENTS.md) - 検出コンポーネント詳細
