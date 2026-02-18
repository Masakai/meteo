# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [1.12.0] - 2026-02-18
### Added
- RTSP検出に電線・部分照明向けのノイズ帯マスク機能を追加（`nuisance_mask`）。
- 夜間基準画像からノイズ帯を抽出する処理を追加（`Canny + HoughLinesP + dilate`）。
- RTSP CLIに以下を追加:
  - `--nuisance-mask-image`
  - `--nuisance-from-night`
  - `--nuisance-dilate`
  - `--nuisance-overlap-threshold`
- 誤検出抑制のユニットテスト `tests/test_meteor_detector_nuisance.py` を追加。

### Changed
- `DetectionParams` に誤検出抑制パラメータを追加:
  - `nuisance_overlap_threshold`
  - `nuisance_path_overlap_threshold`
  - `min_track_points`
  - `max_stationary_ratio`
  - `small_area_threshold`
- 候補物体段階で、ノイズ帯との重なり率が高い小領域を除外する判定を追加。
- トラック確定時に、追跡点数不足・高静止率・ノイズ帯経路重なりを除外する判定を追加。
- 誤検出抑制のデバッグログ（`rejected_by=...`）を出力するよう変更。

### Documentation
- `documents/DETECTION_TUNING.md` に、電線・部分照明の誤検出を減らすための新オプション説明と推奨チューニング手順を追記。

## [1.11.18] - 2026-02-10
### Fixed
- ダッシュボード上部ステータスバー（総検出数/カメラ数/System CPU/稼働時間/検出時間帯）の値・ラベルのベースラインずれを修正。
- `stats-bar` を下端基準で揃えるレイアウトへ変更し、フォントサイズ差がある項目間でも視覚的に整列するよう改善。

## [1.11.17] - 2026-02-10
### Changed
- `GET /dashboard_stats` の `cpu_percent` を、ダッシュボードプロセスCPUではなくシステム全体CPU使用率を返す仕様へ変更。
- Linux環境では `/proc/stat` 差分でCPU使用率を算出し、取得不可時は `getloadavg()` ベースの近似へフォールバックするよう変更。
- ダッシュボード上部メトリクス表示ラベルを `Dashboard CPU` から `System CPU` に変更。

## [1.11.16] - 2026-02-10
### Changed
- カメラ監視の責務をダッシュボードのブラウザJavaScriptから `dashboard` プロセス側へ移管し、サーバー常駐スレッドで `camera*/stats` を定期監視して停止判定するよう変更。
- `GET /camera_stats/{index}` はカメラへ都度プロキシする方式から、サーバー監視キャッシュを返す方式へ変更。
- ダッシュボードUI側の自動復旧ロジック（自動トグル/自動再起動要求）を撤去し、UIは監視状態表示と操作に専念する構成へ整理。

### Added
- サーバー側カメラ監視制御を追加（`start_camera_monitor` / `stop_camera_monitor`）。
- 監視メタ情報を `camera_stats` レスポンスへ追加（`monitor_enabled` / `monitor_checked_at` / `monitor_error` / `monitor_stop_reason` / `monitor_last_restart_at` / `monitor_restart_count` / `monitor_restart_triggered`）。
- カメラ監視用の環境変数を追加（`CAMERA_MONITOR_ENABLED` / `CAMERA_MONITOR_INTERVAL` / `CAMERA_MONITOR_TIMEOUT` / `CAMERA_RESTART_TIMEOUT` / `CAMERA_RESTART_COOLDOWN_SEC`）。

## [1.11.15] - 2026-02-09
### Changed
- ダッシュボードの自動復旧を段階化し、`stream_alive` 低下時はまず「常時表示」の自動再適用（`OFF -> ON`）を実施してから、必要時のみ自動再起動へフォールバックするよう変更。

### Added
- 自動復旧の進行状況を開発者コンソールへ構造化ログ（`[auto-recovery]`）として出力する計測を追加。
- ダッシュボードテンプレートテストに、自動トグル復旧ロジックとログ出力コードの存在確認を追加。

## [1.11.14] - 2026-02-08
### Fixed
- ダッシュボード初期表示時のストリーム接続を `2秒` 間隔の段階接続に変更し、同時接続による表示途切れを抑制。

## [1.11.13] - 2026-02-08
### Fixed
- ダッシュボードの `GET /camera_stream/{index}` プロキシで MJPEG 読み取りタイムアウトを `300s` に延長し、30秒ごとの切断を抑制。
- MJPEG 中継チャンクサイズを `4KB` から `64KB` に拡大し、ストリーム転送効率を改善。
- クライアント切断時（`BrokenPipeError` / `ConnectionResetError`）の例外処理を追加し、不要なエラー応答を抑制。

## [1.11.12] - 2026-02-08
### Added
- ダッシュボード自身のCPU使用率を返す `GET /dashboard_stats` を追加。
- ダッシュボード上部の統計バーに `Dashboard CPU` 表示を追加し、5秒ごとに更新するよう変更。

### Changed
- 監視スレッドでダッシュボードCPU使用率のサンプル更新を行うよう変更。
- ルートテストに `GET /dashboard_stats` の検証を追加。

## [1.11.11] - 2026-02-08
### Added
- ダッシュボードのカメラ操作行に「常時表示」チェックボックスを追加し、カメラごとにライブストリーム常時表示のON/OFFを選択可能に変更。

### Changed
- 「常時表示」OFFのカメラはストリーム接続と再接続を停止し、カード上で `常時表示オフ` を表示するよう変更（検出統計取得と操作は継続）。
- ストリーム常時表示の選択状態を `localStorage` に保存し、ページ再読み込み後も設定を維持するよう変更。

## [1.11.10] - 2026-02-08
### Changed
- ダッシュボードの検出キャッシュ監視間隔（`DETECTION_MONITOR_INTERVAL`）のデフォルトを `0.5s` から `2.0s` に変更。
- ダッシュボードの検出一覧ポーリング基準（`detectionPollBaseDelay`）を `3s` から `5s` に変更。

## [1.11.9] - 2026-02-08
### Fixed
- iPad Safari でダッシュボード再読み込み時に表示が途中で止まるように見える問題を改善。
- 初期描画時のMJPEG同時接続を避けるため、ストリーム接続をページ初期化後の段階的開始へ変更。

## [1.11.8] - 2026-02-08
### Changed
- ダッシュボードに検出情報キャッシュ監視スレッドを追加し、`detections.jsonl` とラベルの差分監視を常駐化。
- `GET /detections` と `GET /detections_mtime` をキャッシュ参照に変更し、リクエストごとのファイル全走査を削減。
- ダッシュボード起動・終了時に検出監視スレッドを開始/停止する制御を追加。

## [1.11.7] - 2026-02-08
### Fixed
- ダッシュボードの「スナップショット保存」でストリーム表示や他API取得に影響が出る問題を修正。
- スナップショット保存処理をブラウザダウンロード方式へ変更し、連続取得時の失敗を軽減。
- ストリーム再接続の保険処理を対象カメラ限定に変更し、`/detections_mtime` 取得失敗（`Load failed`）を抑制。

## [1.11.6] - 2026-02-08
### Fixed
- ダッシュボードのライブプレビューが一度失敗すると復帰しない問題を修正し、ストリーム画像の自動再接続（指数バックオフ）を追加。
- `camera_stream` プロキシのタイムアウトを調整し、MJPEG中継時の耐性を改善。
- クエリ付きパス（例: `/camera_stream/0?t=...`）でカメラインデックス解析に失敗しないよう修正。

## [1.11.5] - 2026-02-08
### Changed
- ダッシュボードの検出時間帯計算で、ブラウザ位置情報の取得を廃止し、サーバー設定（`LATITUDE` / `LONGITUDE`）を常時使用するよう変更。

### Documentation
- README の検出時間帯説明を、ブラウザ位置情報ではなくサーバー設定座標を使用する内容へ更新。

## [1.11.4] - 2026-02-08
### Fixed
- ダッシュボード「最近の検出」の分類ラジオボタン文言を、`流星` / `それ以外` に変更し、判定意図が直感的に分かるよう改善。

## [1.11.3] - 2026-02-08
### Documentation
- README 冒頭に、ATOM Cam 2（水平画角120度）前提での流星検出しきい値の直感的な換算目安（km / km/s）を追加。
- `documents/CONFIGURATION_GUIDE.md` に、`min_length=20px` / `min_speed=50px/s` を距離別（100/200/300km）で読み替える表を追加。

## [1.11.2] - 2026-02-08
### Changed
- ダッシュボード「最近の検出」の認識分類UIをプルダウンからラジオボタンへ変更し、`検出` / `後検出` の2択に統一。
- ラベルAPIの許可値を `detected` / `post_detected` のみへ整理し、既存の旧ラベル値は表示時に `detected` へ正規化。

## [1.11.1] - 2026-02-07
### Changed
- ダッシュボード「最近の検出」の操作行を2段構成（表示系 / 管理系）に整理し、誤タップしづらいレイアウトへ調整。
- `VIDEO` / `合成` / `元画像` / ラベル選択 / `削除` のタップ領域を拡張し、押しやすさを改善。

## [1.11.0] - 2026-02-07
### Added
- ダッシュボードでストリーム停止を検知した際に、対象カメラへ自動で再起動要求（`POST /camera_restart/{index}`）を送る自動復旧処理を追加。
- 自動再起動後も復旧しない場合に「カメラの電源が入っていないかハングアップしています」とダイアログ表示する通知を追加。
- ダッシュボードHTML生成テスト `tests/test_dashboard_templates.py` を追加。

## [1.10.0] - 2026-02-07
### Added
- ダッシュボードの「最近の検出」にラベル分類機能を追加（`未分類` / `誤検出` / `要確認` / `真検出`）。
- ラベル更新API `POST /detection_label` を追加。
- ルートテストにラベルAPIおよび検出一覧へのラベル反映テストを追加。

### Changed
- 検出一覧API `GET /detections` が各検出に `label` を含むよう変更。
- 更新検知API `GET /detections_mtime` がラベルファイル更新も監視するよう変更。
- 検出削除時に対応ラベルを同時に削除するよう変更。

## [1.9.0] - 2026-02-07
### Added
- `meteor_detector_rtsp_web.py` の `/stats` に `runtime_fps`（実効FPS）を追加。
- ダッシュボードのカメラ情報に FPS 表示を追加（`runtime_fps` 優先、未計測時は `source_fps`）。
- `tests/test_meteor_detector_realtime.py` を追加（FPS正規化/推定のテスト）。

### Changed
- クリップ保存FPSを固定値ではなく、フレーム時刻差から推定した実効FPSに変更。
- Facebook正規化時の30fps固定を廃止し、入力クリップFPSに追従するよう変更。

### Documentation
- API/アーキテクチャ資料の `/stats` 仕様を `runtime_fps` / `settings.source_fps` に対応。

## [1.8.0] - 2026-02-07
### Added
- ダッシュボードにカメラ単位の「再起動」ボタンを追加（`POST /camera_restart/{index}`）。
- ダッシュボードにカメラ単位の「スナップショット保存」ボタンを追加（`GET /camera_snapshot/{index}`）。
- カメラAPIに `GET /snapshot`（現在フレームJPEG取得）と `POST /restart`（再起動要求）を追加。

### Changed
- ダッシュボードHTTPサーバーに `do_POST` を追加し、カメラ操作系API（マスク更新/再起動）を正式サポート。

### Documentation
- API/アーキテクチャ/運用/READMEを新エンドポイントとUI操作に合わせて改版。

## [1.7.0] - 2026-02-06
### Added
- Facebook向けにH.264 MP4へ正規化するオプションを `meteor_detector_rtsp_web.py` に追加（`--fb-normalize` / `--fb-delete-mov`）。
- `convert_detections_mp4_to_mov.py` をFacebook互換MP4出力に対応（H.264 baseline, 30fps, faststart）。

## [1.6.0] - 2026-02-05

### Added
- `meteor_detector.py` に `--realtime` を追加し、Web版と同じ検出ロジックでファイル再検出が可能に

### Changed
- クリップ動画の拡張子を `.mov` に変更（H.264互換を優先）
- ダッシュボードの稼働時間表示をサーバ起動時刻基準に変更
- ダッシュボードの動画配信を `.mov` / `.mp4` 両対応に拡張

## [1.5.0] - 2026-02-05

### Added
- 検出共通ユーティリティ（`meteor_detector_common.py`）を追加してRTSP実装を共通化
- 基本ユニットテストを追加

### Changed
- RTSP検出のバッファを検出前後1秒 + 最大検出時間に合わせて自動調整
- 追跡時の輝度閾値を感度プリセットに連動
- 天文薄暮期間の判定をキャッシュし、再計算頻度を抑制

### Removed
- 未使用のフレームバッファを削除

## [1.4.0] - 2026-02-05

### Added
- Webプレビュー（単体カメラ）にマスク表示/更新ボタンとオーバーレイ表示を追加
- Webプレビュー（単体カメラ）にストリーム/検出/マスク状態のステータス表示を追加

## [1.3.0] - 2026-02-04

### Added
- ダッシュボードに動画モーダル表示を追加（MP4の範囲リクエスト対応、画像/動画切り替え）
- 流星検出に追跡モードを追加（低い閾値を使用、`detect_bright_objects` に `tracking_mode` を追加）
- `dashboard_templates.py` を追加（カメラグリッドや統計情報のHTMLテンプレート）
- `mask_none.jpg` を追加

### Changed
- 流星切り出しマージンを `margin_before` / `margin_after` に分割し処理範囲を最適化
- RTSP検出のマージン制御を調整し、`max_gap_time` のデフォルトを `1.0s` に延長、イベント開始時刻を修正
- 天文薄暮期間の検出制限をデフォルト有効化（`ENABLE_TIME_WINDOW=true`）し `docker-compose.yml` と関連スクリプトへ反映
- `docker-compose.yml` のボリュームを書き込み可能に変更（read-only削除）、`generate_compose.py` も更新
- `.gitignore` にカメラ画像とマスクファイルを追加（`/camera*.jpg`、`/masks/camera*_mask.png`）
- ダッシュボードのレイアウト/スタイルを調整（アイテム表示サイズ、動画リンク統合）

### Fixed
- `generate_compose.py` の引数伝播を `$@` で修正
- `cv2.VideoWriter` の初期化で複数のFourCCを試行し、失敗時に警告を出力

### Documentation
- README にデプロイ手順を追加（サーバー展開、ファイアウォール、自動起動、リバースプロキシ、移行手順）

## [1.2.0] - 2026-02-03

### Added
- streamersの各行に`RTSP URL | 昼間画像パス`を指定し、マスクを自動生成してコンテナに同梱する機能
- 事前生成マスクを優先適用する`MASK_IMAGE`と、マスク永続化（`/output/masks/<camera>_mask.png`）
- ダッシュボードにマスク更新ボタンを追加（現在フレームからマスク再生成）
- カメラAPIに`POST /update_mask`を追加
- ダッシュボードに検出処理中インディケータを追加（赤点滅：検出処理中、グレー：停止中）
- `meteor_detector_rtsp_web.py`の`/stats` APIに`is_detecting`フィールドを追加

### Changed
- 検出ロジックに除外マスク適用を追加（差分画像でマスク領域を除外）
- マスク生成アルゴリズムを改良（空の最下端より下を除外）
- `generate_compose.py`がマスク自動生成・同梱を行うよう拡張
- ダッシュボードのカメラカード右上に2つのインディケータを配置（ストリーム接続状態と検出処理状態）

### Documentation
- マスク機能とstreamersの拡張形式、API/設定/運用手順を追加

## [1.1.0] - 2026-02-02

### Added
- 天文薄暮期間の検出制限機能（緯度・経度・タイムゾーンを考慮した検出期間の設定）
- 実行オプションおよび環境変数による検出期間の制御機能

### Changed
- 著作権表記を「MIT License」に統一
- `.gitignore` にユーザー固有設定（`streamers`）を追加
- サンプルストリーマー設定ファイル（`streamers.sample`）を作成

### Documentation
- READMEの改善（`meteor-docker.sh`の安全性に関する詳細を追記）
- `cleanup`コマンドの動作説明を改善

## [1.0.0] - 2026-02-01

### Added
- RTSPストリームから流星をリアルタイム検出する `meteor_detector_rtsp.py`
- MP4動画から流星を検出する `meteor_detector.py`
- 全カメラのプレビューを1ページで表示するダッシュボード機能
- Webプレビュー機能（カメラごとのストリーム表示）
- Docker対応（複数カメラの自動構成）
- `generate_compose.py` によるdocker-compose.yml自動生成機能
- `meteor-docker.sh` による簡単起動スクリプト
- `--extract-clips` / `--no-clips` オプションでクリップ保存の制御機能
- ダッシュボードにカメラ設定情報（感度・解像度スケール・クリップ設定）の表示
- タイムゾーン設定（Asia/Tokyo）
- 著作権情報とライセンス（MIT License）の明記
- プロジェクトドキュメント（README.md）
- ダッシュボードスクリーンショット画像

### Changed
- `.gitignore` の設定を最適化（.claude、.ideaディレクトリを除外）

### Removed
- 未使用の constellation_drawer.py と constellation_drawer_astrometry.py を削除

## Project Information

**Copyright**: © 2026 Masanori Sakai
**License**: MIT License
**Company**: 株式会社リバーランズ・コンサルティング
