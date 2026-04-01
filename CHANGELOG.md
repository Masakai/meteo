# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [3.4.0] - 2026-04-02
### Added
- 多地点流星三角測量システムを追加（`triangulation/`, `triangulation_server.py`, `station_reporter.py`）。
  - 複数の観測拠点から同一流星を同時検出し、スキューライン最近接点アルゴリズムで3D軌道（高度・緯度経度・速度）を算出。
  - ピンホールカメラモデルによるピクセル座標 → 方位角・仰角変換（`triangulation/pixel_to_sky.py`）。
  - WGS84 / ECEF / ENU 座標変換（`triangulation/geo_utils.py`）。
  - 時刻±5秒の時間窓 + 角度相関によるイベントマッチング（`triangulation/event_matcher.py`）。
  - Flask 中央サーバ（SQLite 永続化、REST API）と Deck.gl + MapLibre GL による3Dマップ UI。
  - 高度スケール調整（1×〜100×）、観測拠点 FOV 可視化、地表面投影線、信頼度フィルター。
  - `station.json` が存在する場合に `docker-compose.yml` へ `station-reporter` サイドカーを自動追加（`generate_compose.py`）。
  - デモ用スクリプト `demo_triangulation.py`（合成データ3拠点・5流星、ポート8090）。
  - ユニットテスト40件（`tests/test_geo_utils.py`, `test_pixel_to_sky.py`, `test_triangulator.py`, `test_event_matcher.py`）。
  - アーキテクチャ・アルゴリズム・デプロイ手順を Mermaid 図付きで解説（`documents/TRIANGULATION.md`）。

## [3.3.1] - 2026-04-01
### Fixed
- YouTube Live 配信の開始/停止が正しく動作しない問題を修正。
  - go2rtc の ffmpeg 機能はストリーム削除後もプロセスが残留するバグがあったため、
    dashboard コンテナ内で ffmpeg サブプロセスを直接管理する方式に変更。
  - 停止時は `terminate()` → `kill()` で確実に RTMP 接続を切断。
  - 開始時は `-re` フラグでリアルタイム読み込みを強制し、「リアルタイムより高速」送信警告を解消。
  - `-r 20 -maxrate 2000k -bufsize 2000k` による CFR 変換と CBR 制御を追加。
  - 停止後に再開始すると失敗する問題を修正。
- go2rtc.yaml から `publish` セクションおよび `camera{N}_youtube` ストリームを削除（go2rtc 自動配信との競合解消）。

### Changed
- YouTube 配信アーキテクチャを変更: go2rtc の `publish` セクション → dashboard コンテナ内 ffmpeg サブプロセスによる直接 RTMP 送信。
- `Dockerfile.dashboard` に ffmpeg を追加。
- go2rtc の役割をカメラ RTSP 中継と WebRTC 配信のみに限定。

## [3.3.0] - 2026-03-31
### Added
- ダッシュボードからカメラ単位で YouTube Live 配信の開始/停止が可能に。
- `streamers` ファイルの4番目のフィールドに `youtube:STREAM_KEY` を指定すると、ダッシュボードに「YouTube配信」ボタンを表示。
- ダッシュボード API に `POST /youtube_start/{index}`、`POST /youtube_stop/{index}`、`GET /youtube_status/{index}` を追加。
- ダッシュボード環境変数 `CAMERA{i}_YOUTUBE_KEY`、`CAMERA{i}_RTSP_URL`、`GO2RTC_API_URL` を追加。
- 配信中は「配信中 LIVE」ボタンがパルスアニメーションで表示され、10秒間隔で配信状態を自動ポーリング。

## [3.2.5] - 2026-03-22
### Fixed
- ダッシュボードのフッタにあるバージョンリンクから `CHANGELOG.md` を開けない問題を修正し、`CHANGELOG.md` をダッシュボードコンテナへ同梱。

### Changed
- `/changelog` エンドポイントをサーバ側 Markdown レンダリングへ切り替え、モーダル表示を HTML ベースに変更。
- changelog レンダリング用に `Markdown` 依存を追加し、関連するダッシュボードテストを更新。

## [3.2.4] - 2026-03-21
### Changed
- カメラライブ通信方式の既定値を `webrtc` に変更し、`CAMERA*_STREAM_KIND` 未指定時も WebRTC を優先するよう統一。
- `generate_compose.py` の `--streaming-mode` 既定値を `webrtc` に変更し、新規生成される構成で `go2rtc` を前提としたライブ表示を有効化。
- 設定ガイドと関連テストを更新し、既定のライブ表示方式が `webrtc` であることを反映。

## [3.2.3] - 2026-03-21
### Added
- GitHub に新バージョンが push された際に自動で pull & rebuild する `auto_update.sh` を追加。
- msmtp を使ったメール通知に対応。更新完了・失敗時に `[Meteo]` 件名でメールを送信。
- msmtp 設定のサンプルファイル `msmtprc.sample` を追加。

## [3.2.2] - 2026-03-21
### Fixed
- 画像リクエストのパスが検出ディレクトリ外に逸脱するパストラバーサルを修正。

### Changed
- 各種ドキュメント（API リファレンス・アーキテクチャ・設定・Docker・運用・セキュリティ・セットアップ）を v3.2.1 の実装に合わせて改版。

## [3.2.1] - 2026-03-19
### Fixed
- 手動録画で RTSP 音声が `pcm_alaw` の場合に MP4 へ `-c copy` できず録画開始に失敗する問題を修正し、映像のみを MP4 保存するよう改善。
- 手動録画ファイルの探索先を各カメラ出力ディレクトリ配下 `manual_recordings/...` に合わせ、検出一覧カレンダーへ反映されない問題を修正。

### Changed
- 手動録画の完了後にサムネイル JPEG を自動生成し、検出一覧からプレビューしやすい表示へ改善。
- ダッシュボードの検出一覧で手動録画にも「プレビュー」と「削除」を表示し、専用削除 API で MP4/JPEG をまとめて削除できるよう改善。

## [3.2.0] - 2026-03-19
### Added
- カメラライブ画面にカメラ別の「録画予約」UIを追加し、開始時刻と録画秒数を指定して手動録画できるよう改善。
- ダッシュボードに `GET /camera_recording_status/{index}`、`POST /camera_recording_schedule/{index}`、`POST /camera_recording_stop/{index}` を追加。
- カメラ側 API に `GET /recording/status`、`POST /recording/schedule`、`POST /recording/stop` を追加し、RTSP入力を `ffmpeg` で MP4 保存できるよう改善。

### Changed
- カメラ統計レスポンス `/camera_stats/{index}` と `/stats` に録画状態を含め、予約中・録画中・完了・停止をダッシュボードへ反映するよう変更。
- 手動録画の保存先を各カメラ出力ディレクトリ配下 `manual_recordings/<camera>/` に統一。

## [3.1.1] - 2026-03-15
### Changed
- `generate_compose.py` で `--streaming-mode webrtc` を使う際、`go2rtc` の candidate host を既定でローカル IP から自動検出するよう改善。
- WebRTC / go2rtc / candidate 設定まわりの README、セットアップ、運用、API、アーキテクチャ文書を現行構成に合わせて改版。

### Fixed
- OpenCV 未導入環境で昼間画像付き `streamers` を使うと `generate_compose.py` 全体が停止し、`docker-compose.yml` や `go2rtc.yaml` が生成されない問題を修正。
- `generate_compose.py` の警告表示を見直し、OpenCV 未導入時はマスク生成のみスキップすることが分かるメッセージへ改善。

## [3.1.0] - 2026-03-15
### Added
- ダッシュボードのライブ表示方式として `WebRTC` を正式サポートし、`go2rtc` 経由のブラウザ向け低遅延配信を利用可能に。
- `generate_compose.py` に `--streaming-mode webrtc` と `--go2rtc-candidate-host` を追加し、`go2rtc.yaml` の生成と `webrtc.candidates` の明示設定を自動化。

### Changed
- ダッシュボードの WebRTC 埋め込みを専用ページ化し、`go2rtc` アセットのプロキシ配信とホスト名ベースの WebSocket 接続へ変更。
- Docker 配下で WebRTC が `MSE` にフォールバックしやすかった構成を見直し、`go2rtc` がブラウザから到達可能な candidate を返せる運用手順とサンプル設定へ更新。

### Fixed
- `go2rtc` が Docker/NAT 配下で不達な candidate を返し、ブラウザ表示が `MSE` にフォールバックする問題を修正。
- ダッシュボードの WebRTC オーバーレイ表示と `visibility` 復帰処理がライブ映像を覆ってしまう問題を修正。

## [3.0.0] - 2026-03-15
### Removed
- 標準の MP4 直出力に対して実効性のなかった旧互換オプション `fb_normalize` / `fb_delete_mov` を削除。
- カメラ設定 UI、`generate_compose.py`、`install.sh`、Docker 起動オプションから `fb_normalize` / `fb_delete_mov` の設定経路を削除。

### Changed
- 関連ドキュメントとサンプル設定を、MP4 直出力を前提とした現行仕様に更新。

## [2.0.0] - 2026-03-15
### Changed
- ダッシュボードの未使用な `GET /camera_stream/{index}` 中継ルートを削除し、ブラウザから各カメラの `/stream` へ直接接続する構成に整理。
- 設定画面 HTML 生成 (`render_settings_html`) を `dashboard_templates_settings.py` へ分割し、ダッシュボード画面テンプレートとの責務を分離。
- マスク生成ロジック（除外マスク / ノイズ帯マスク）を `meteor_mask_utils.py` へ分割し、`meteor_detector_rtsp_web.py` と `generate_compose.py` で共通利用する構成に整理。
- カメラ操作系ハンドラ（snapshot/mask/restart/settings反映）を `dashboard_camera_handlers.py` へ分割し、`dashboard_routes.py` はルーティング調停と監視系処理に集中する構成へ整理。
- カメラ設定一括反映で、成功時に「反映完了: X / Y 台」ダイアログを表示するよう改善。

### Fixed
- カメラ設定画面で API が `HTTP 200` かつ `success: false` を返した場合に `Error: HTTP 200` と表示される問題を修正し、API の失敗理由を優先表示するよう改善。
- カメラコンテナの起動時に `meteor_mask_utils` が見つからず再起動ループに入る問題を修正し、Docker イメージへ `meteor_mask_utils.py` を同梱。

## [1.24.1] - 2026-03-14
### Added
- ダッシュボードに `GET /health` を追加し、コンテナやリバースプロキシ配下からの疎通確認をしやすく改善。

### Changed
- `dashboard.py` を Flask のアプリファクトリ構成へ整理し、`app = create_app()` を公開して WSGI 配備やコンテナ運用で扱いやすい構成へ変更。
- 監視スレッドの起動を初回リクエスト時にも行うよう見直し、`python dashboard.py` 以外の起動経路でもカメラ監視・検出監視が有効になるよう改善。
- ダッシュボード関連レスポンスの no-cache ヘッダー付与を共通化。

### Fixed
- Flask アプリとして import して起動した場合に、バックグラウンド監視が開始されないケースを修正。

## [1.24.0] - 2026-03-14
### Added
- 検出データの運用整備として、ID ベース移行・孤立ファイル救済・検出ディレクトリ統合を行う各種スクリプトを追加。
- カメラ側 `/stats` とランタイム設定に `detection_enabled` を反映し、ダッシュボードから全カメラの検出停止・再開を制御できるよう改善。
- RTSP 接続障害の切り分けをしやすくする診断ログと到達性確認ロジックを追加。

### Changed
- 検出 ID の生成規則を、`timestamp` に加えて `start_time` / `end_time` / `start_point` / `end_point` を含む現行形式へ統一し、保存ファイル名もその ID 断片を含む形式へ更新。
- `faint` 感度プリセットの現行実装値 (`diff_threshold=16`, `min_brightness=150`, `min_area=5`, `max_distance=90`) と、RTSP Webでの追跡輝度自動調整（`min_brightness_tracking=120`）に合わせて、README と技術ドキュメントの記述を更新。
- `CAMERA_NAME_DISPLAY` は UI 表示専用であり、保存先ディレクトリ・マスク保存名・ランタイム設定ファイル名には内部名を使い続ける点を、README と運用/設定ドキュメントへ追記。

### Fixed
- 孤立検出ファイルの救済で新規追加されるレコードの `id` が独自規則になっていた問題を修正し、本流の検出 ID 管理と一致する形式へ是正。

## [1.23.1] - 2026-03-09
### Changed
- ダッシュボードの検出インディケータを、検出中・期間外・期間内だが停止疑い・状態確認中で判別できる表示へ変更。
- カメラサーバの `Detect` 表示を `IDLE` 一括表示から見直し、`DETECTING` / `OUT_OF_WINDOW` / `WAITING_FRAME` / `STREAM_LOST` を返せるよう改善。

### Fixed
- 検出時間帯の計算ロジックを修正し、定義どおり「当日日没から翌日の日出まで」を夜間ウィンドウとして扱うよう是正。
- 検出時間帯判定まわりとダッシュボード表示まわりの回帰テストを追加。

## [1.23.0] - 2026-03-09
### Added
- 短く暗い流星の取りこぼし低減を目的とした新しい感度プリセット `faint` を追加。既存の `medium` / `high` を崩さず、設定UIやランタイム設定から切り替え可能に。

### Changed
- `README.md`、検出チューニング、構成ガイド、Docker関連ドキュメントを改版し、感度プリセットに `faint` を反映。

### Fixed
- カレンダービューに追加していた夜間天気表示を撤去し、API仕様上の期間制限で `--` 表示に落ちる問題を解消。

## [1.22.0] - 2026-03-08
### Added
- ダッシュボードにカメラ専用ページ `GET /cameras` を追加し、検出一覧中心のトップページとライブカメラ表示を分離。
- 最近の検出表示をカレンダービュー化し、日付単位で検出件数と対象イベントを追いやすく改善。
- ダッシュボード最上部に Meteo ロゴと `Meteor Detection Dashboard` ヘッダーを追加。

### Changed
- ダッシュボードのトップページ `/` を検出一覧中心の構成へ見直し、カメラライブ表示は `/cameras` 側へ集約。
- ブラウザからのライブ表示で、条件が合う場合はダッシュボード中継ではなく各カメラの `/stream` へ直接接続するよう変更し、表示の安定性を改善。
- カメラ内部名と表示名の扱いを整理し、UIでは表示名を優先しつつ、ディレクトリ名・API・ファイル参照では内部名を維持。
- 単体カメラおよびダッシュボードのマスク更新フローを、プレビュー生成後に適用・破棄を選べる確認方式へ統一。
- 検出画像と動画の参照を、ログ記録値よりも実在ファイルを優先して解決するよう改善。
- 検出クリップの標準出力形式を `.mov` から `.mp4` へ変更し、`isom` / `avc1` / `Constrained Baseline` / `30fps` / `15360 tbn` を満たす MP4 を直接出力するよう変更。
- クリップ保存処理を `ffmpeg` 直書き優先へ変更し、従来の MOV 中間ファイル経由を不要化。

### Fixed
- カレンダービューのテンプレート展開不備を修正し、月別グリッドが正しく描画されるよう改善。
- ダッシュボードでのストリーム再接続処理を簡素化し、不要な再試行や画面遷移時の不安定さを軽減。
- MP4 直接出力経路で常に OpenCV フォールバックへ落ちていた保存処理を修正し、意図した `ffmpeg` エンコード条件が実際に適用されるよう改善。

## [1.20.4] - 2026-03-06
### Fixed
- ダッシュボードの「それ以外」一括削除 API (`POST /bulk_delete_non_meteor/<camera>`) で、パス解析のオフバイワンによりカメラ名先頭1文字が欠落し、対象ディレクトリを特定できず削除できない問題を修正。
- 一括削除ルートの回帰テストを追加し、通常のカメラ名と実運用形式（例: `camera1_10_0_1_25`）の両方で正しく処理されることを検証。

## [1.20.3] - 2026-03-06
### Fixed
- ダッシュボードのライブストリーム復帰安定性を改善。バックグラウンド復帰後に `通信遅延を検知（再接続中）` と `接続中` を往復し続けるケースに対し、再接続の多重発行抑止・段階的リカバリウェーブ・ウォームアップ期間中の過剰再試行抑制を追加。
- ストリーム表示で白いプレースホルダ矩形が見える問題を軽減。再接続時にプレースホルダ画像への差し替えを挟まないよう変更し、視覚的なチラつきを抑制。
- `stream_alive` が正常な場合にフロント側の生存時刻を更新するよう修正し、`onload` 取りこぼし時の誤判定再接続ループを抑制。
- `fb_normalize` / `fb_delete_mov` 利用時に `.mov` しか残らない問題への対策として、カメラコンテナに `ffmpeg` を同梱。あわせて `ffmpeg` / `ffprobe` 未導入時の警告ログを明確化。

## [1.20.2] - 2026-02-25
### Fixed
- 日本語名のカメラ（例: 東側）でスナップショット保存が失敗する問題を修正。Pythonの `str.isalnum()` は日本語文字に対しても `True` を返すため、ダウンロードファイル名に日本語が含まれると HTTP ヘッダーの `latin-1` エンコードで `UnicodeEncodeError` が発生し、レスポンスが壊れてダウンロードできなかった。`c.isascii()` も条件に追加することで ASCII 文字のみをファイル名に使用するよう修正。

## [1.20.1] - 2026-02-25
### Fixed
- 日本語名のカメラディレクトリ（例: 東側、西側）で画像が表示されない問題を修正。`handle_image` でURLパスのカメラ名をURLデコードしていなかったため、`%E6%9D%B1%E5%81%B4` のようなエンコード済み文字列でファイルを検索して見つからなくなっていた。
- 同じ原因で、日本語名カメラの検出を削除しても「0個のファイルを削除しました」となる問題を修正。`handle_delete_detection` でもカメラ名をURLデコードするよう修正。

## [1.20.0] - 2026-02-25
### Added
- streamersファイルの第3パラメータとしてカメラ表示名を追加し、UI上でIPアドレス表記ではなく分かりやすい名称（例: 東側、南側、西側）で表示可能に。
- 環境変数 `CAMERA_NAME_DISPLAY` を新設し、UI表示専用の名称を設定可能に（システム内部では従来通り `CAMERA_NAME` を使用）。
- generate_compose.py でstreamersファイルの3番目のパラメータを `display_name` として解析し、Docker Compose設定に `CAMERA_NAME_DISPLAY` を自動生成。

### Changed
- ダッシュボードのカメラカード、再起動確認ダイアログでカメラ表示名を使用するよう改善。
- カメラサーバのWebページタイトルとヘッダーでカメラ表示名を使用するよう改善。
- docker-compose.ymlのコメントをIPアドレス表記から表示名に変更し、可読性を向上。

### Fixed
- 一時的にCAMERA_NAMEに表示名を設定していた実装を修正し、ディレクトリ名・ファイルパス・API通信では従来通りのカメラ名（例: camera1_10_0_1_25）を使用するよう是正。
- スクリーンショットのダウンロードファイル名が正しく生成されない問題を、CAMERA_NAMEとCAMERA_NAME_DISPLAYの分離により解決。

## [1.19.0] - 2026-02-25
### Changed
- 最近の検出リストの表示方法を、カメラ別グループ化から時系列順（日付内で新しい順）に変更し、全カメラの検出を一覧で確認しやすく改善。
- 検出アイテムの時刻表示にカメラ名を追加（例: `2026-02-25 05:30:00 | camera1_10_0_1_25`）し、時系列表示でもどのカメラの検出かが即座に判別可能に。
- カメラ別の「それ以外を一括削除」ボタンを日付ヘッダーに移動し、時系列表示でもカメラごとの一括削除が可能。

### Changed
- すべてのUIボーダー（カメラカード、日付グループ、検出グループタイトル等）を統一スタイル（3px solid #4a6f9f）に変更し、視認性を向上。

## [1.18.0] - 2026-02-24
### Added
- ダッシュボードに「それ以外」ラベルが付いた検出の一括削除機能を追加し、カメラごとに非流星イベントを効率的に削除可能化。
- 検出リストの各カメラグループタイトルに「それ以外を一括削除」ボタンを追加し、該当件数を表示。
- favicon.svg を追加し、マスコットのカメラレンズ部分をベースにしたブランドアイコンを提供。

### Fixed
- 検出ラベルを「それ以外」に変更した時点で一括削除ボタンが即座に表示されない問題を修正し、リロードなしで UI を更新するよう改善。

## [1.17.0] - 2026-02-23
### Added
- ダッシュボードのカメラカードに「カメラサーバ生存」インディケータを追加し、サーバ監視状態（応答あり/応答なし/判定保留）を可視化。
- 各インディケータ（ストリーム接続・カメラサーバ生存・検出処理・マスク適用）にホバー時ヘルプメッセージを追加。

### Changed
- インディケータ表示を `monitor_stop_reason` と連動させ、サーバ未到達時は赤、初期/一時停止時は灰で表示するよう改善。

## [1.16.0] - 2026-02-19
### Added
- 検出パラメータに `exclude_edge_ratio`（画面四辺の周辺除外率）を追加し、端部ノイズを検出対象から除外できるよう改善。
- 全カメラ設定画面に `exclude_edge_ratio` の入力欄とHELP説明を追加。
- 全カメラ設定画面で、デフォルト値から変更された入力項目を赤枠表示する差分ハイライトを追加。

### Changed
- `POST /apply_settings` とランタイム設定保存に `exclude_edge_ratio` を追加し、再起動後も設定が維持されるよう改善。

## [1.15.0] - 2026-02-19
### Added
- 全カメラ設定画面に「デフォルト値に戻す」ボタンを追加し、既定値をフォームへ即時反映できるように改善。
- 全カメラ設定画面の各セクション（運用プリセット、基本検出、追跡・結合、誤検出抑制）に、折りたたみ式 HELP を追加。

### Changed
- 全カメラ設定画面の `sensitivity` 入力を自由入力から選択式（`low` / `medium` / `high` / `fireball`）へ変更。
- 全カメラ設定画面の `select` 高さを他フォームと統一し、UIの視認性を改善。
- ランタイム設定の保存先を共通パス（`/output/runtime_settings/<camera>.json`）優先に変更し、従来パスとの互換読み込みを維持。
- `POST /apply_settings` 適用時の保存処理を強化し、再起動後も変更パラメータを復元できるように改善。

## [1.14.0] - 2026-02-19
### Added
- ダッシュボードの全カメラ設定UIに、録画前後マージン設定（`clip_margin_before` / `clip_margin_after`）を追加。
- 各設定項目に日本語説明を追加し、項目名の末尾にパラメータ名を併記する表示へ変更。
- 関連ドキュメントに誤検出抑制機能（nuisance mask系）とランタイム設定反映手順を追記。

### Changed
- ダッシュボードから適用した設定をカメラプロセスへ即時反映できる項目を拡張し、再ビルド不要で主要パラメータを変更可能化。
- カメラ側 `POST /apply_settings` で `clip_margin_before` / `clip_margin_after` を受け付け、保存動画の前後余白時間を運用時に調整可能化。
- `save_meteor_event` 呼び出し時の固定余白値を設定値連動へ変更し、複合クリップ（`composite_after`）にも反映。

## [1.13.0] - 2026-02-19
### Added
- ダッシュボードに全カメラ設定ページ `GET /settings` を追加し、検出パラメータを一括編集できるUIを実装。
- ダッシュボードに設定APIを追加:
  - `GET /camera_settings/current`（現在値取得）
  - `POST /camera_settings/apply_all`（全カメラへ一括適用）
- カメラ側にランタイム設定反映API `POST /apply_settings` を追加。
- ダッシュボードの設定機能に関するルート/テンプレートテストを追加。

### Changed
- ダッシュボードのヘッダーに「全カメラ設定」への導線を追加。
- `POST /apply_settings` で、基本検出・追跡/結合・誤検出抑制（nuisance関連）・マスク系パスの即時反映に対応。
- `/stats` の `settings` に、一括設定UIで扱う主要パラメータ（`diff_threshold`、`min_linearity`、`nuisance_*` など）を含めるよう拡張。

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

### Changed
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

### Changed
- README の検出時間帯説明を、ブラウザ位置情報ではなくサーバー設定座標を使用する内容へ更新。

## [1.11.4] - 2026-02-08
### Fixed
- ダッシュボード「最近の検出」の分類ラジオボタン文言を、`流星` / `それ以外` に変更し、判定意図が直感的に分かるよう改善。

## [1.11.3] - 2026-02-08
### Changed
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

### Changed
- API/アーキテクチャ資料の `/stats` 仕様を `runtime_fps` / `settings.source_fps` に対応。

## [1.8.0] - 2026-02-07
### Added
- ダッシュボードにカメラ単位の「再起動」ボタンを追加（`POST /camera_restart/{index}`）。
- ダッシュボードにカメラ単位の「スナップショット保存」ボタンを追加（`GET /camera_snapshot/{index}`）。
- カメラAPIに `GET /snapshot`（現在フレームJPEG取得）と `POST /restart`（再起動要求）を追加。

### Changed
- ダッシュボードHTTPサーバーに `do_POST` を追加し、カメラ操作系API（マスク更新/再起動）を正式サポート。

### Changed
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

### Changed
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

### Changed
- マスク機能とstreamersの拡張形式、API/設定/運用手順を追加

## [1.1.0] - 2026-02-02

### Added
- 天文薄暮期間の検出制限機能（緯度・経度・タイムゾーンを考慮した検出期間の設定）
- 実行オプションおよび環境変数による検出期間の制御機能

### Changed
- 著作権表記を「MIT License」に統一
- `.gitignore` にユーザー固有設定（`streamers`）を追加
- サンプルストリーマー設定ファイル（`streamers.sample`）を作成

### Changed
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

[Unreleased]: https://github.com/Masakai/meteo/compare/v3.3.0...HEAD
[3.3.0]: https://github.com/Masakai/meteo/compare/v3.2.5...v3.3.0
[3.2.5]: https://github.com/Masakai/meteo/compare/v3.2.4...v3.2.5
[3.2.4]: https://github.com/Masakai/meteo/compare/v3.2.3...v3.2.4
[3.2.3]: https://github.com/Masakai/meteo/compare/v3.2.2...v3.2.3
[3.2.2]: https://github.com/Masakai/meteo/compare/v3.2.1...v3.2.2
[3.2.1]: https://github.com/Masakai/meteo/compare/v3.2.0...v3.2.1
[3.2.0]: https://github.com/Masakai/meteo/compare/v3.1.1...v3.2.0
[3.1.1]: https://github.com/Masakai/meteo/compare/v3.1.0...v3.1.1
[3.1.0]: https://github.com/Masakai/meteo/compare/v3.0.0...v3.1.0
[3.0.0]: https://github.com/Masakai/meteo/compare/v2.0.0...v3.0.0
[2.0.0]: https://github.com/Masakai/meteo/compare/v1.24.1...v2.0.0
[1.24.1]: https://github.com/Masakai/meteo/compare/v1.24.0...v1.24.1
[1.24.0]: https://github.com/Masakai/meteo/compare/v1.23.1...v1.24.0
[1.23.1]: https://github.com/Masakai/meteo/compare/v1.23.0...v1.23.1
[1.23.0]: https://github.com/Masakai/meteo/compare/v1.22.0...v1.23.0
[1.22.0]: https://github.com/Masakai/meteo/compare/v1.20.4...v1.22.0
[1.20.4]: https://github.com/Masakai/meteo/compare/v1.20.3...v1.20.4
[1.20.3]: https://github.com/Masakai/meteo/compare/v1.20.2...v1.20.3
[1.20.2]: https://github.com/Masakai/meteo/compare/v1.20.1...v1.20.2
[1.20.1]: https://github.com/Masakai/meteo/compare/v1.20.0...v1.20.1
[1.20.0]: https://github.com/Masakai/meteo/compare/v1.19.0...v1.20.0
[1.19.0]: https://github.com/Masakai/meteo/compare/v1.18.0...v1.19.0
[1.18.0]: https://github.com/Masakai/meteo/compare/v1.17.0...v1.18.0
[1.17.0]: https://github.com/Masakai/meteo/compare/v1.16.0...v1.17.0
[1.16.0]: https://github.com/Masakai/meteo/compare/v1.15.0...v1.16.0
[1.15.0]: https://github.com/Masakai/meteo/compare/v1.14.0...v1.15.0
[1.14.0]: https://github.com/Masakai/meteo/compare/v1.13.0...v1.14.0
[1.13.0]: https://github.com/Masakai/meteo/compare/v1.12.0...v1.13.0
[1.12.0]: https://github.com/Masakai/meteo/compare/v1.11.18...v1.12.0
[1.11.18]: https://github.com/Masakai/meteo/compare/v1.11.17...v1.11.18
[1.11.17]: https://github.com/Masakai/meteo/compare/v1.11.16...v1.11.17
[1.11.16]: https://github.com/Masakai/meteo/compare/v1.11.15...v1.11.16
[1.11.15]: https://github.com/Masakai/meteo/compare/v1.11.14...v1.11.15
[1.11.14]: https://github.com/Masakai/meteo/compare/v1.11.13...v1.11.14
[1.11.13]: https://github.com/Masakai/meteo/compare/v1.11.12...v1.11.13
[1.11.12]: https://github.com/Masakai/meteo/compare/v1.11.11...v1.11.12
[1.11.11]: https://github.com/Masakai/meteo/compare/v1.11.10...v1.11.11
[1.11.10]: https://github.com/Masakai/meteo/compare/v1.11.9...v1.11.10
[1.11.9]: https://github.com/Masakai/meteo/compare/v1.11.8...v1.11.9
[1.11.8]: https://github.com/Masakai/meteo/compare/v1.11.7...v1.11.8
[1.11.7]: https://github.com/Masakai/meteo/compare/v1.11.6...v1.11.7
[1.11.6]: https://github.com/Masakai/meteo/compare/v1.11.5...v1.11.6
[1.11.5]: https://github.com/Masakai/meteo/compare/v1.11.4...v1.11.5
[1.11.4]: https://github.com/Masakai/meteo/compare/v1.11.3...v1.11.4
[1.11.3]: https://github.com/Masakai/meteo/compare/v1.11.2...v1.11.3
[1.11.2]: https://github.com/Masakai/meteo/compare/v1.11.1...v1.11.2
[1.11.1]: https://github.com/Masakai/meteo/compare/v1.11.0...v1.11.1
[1.11.0]: https://github.com/Masakai/meteo/compare/v1.10.0...v1.11.0
[1.10.0]: https://github.com/Masakai/meteo/compare/v1.9.0...v1.10.0
[1.9.0]: https://github.com/Masakai/meteo/compare/v1.8.0...v1.9.0
[1.8.0]: https://github.com/Masakai/meteo/compare/v1.7.0...v1.8.0
[1.7.0]: https://github.com/Masakai/meteo/compare/v1.6.0...v1.7.0
[1.6.0]: https://github.com/Masakai/meteo/compare/v1.5.0...v1.6.0
[1.5.0]: https://github.com/Masakai/meteo/compare/v1.4.0...v1.5.0
[1.4.0]: https://github.com/Masakai/meteo/compare/v1.3.0...v1.4.0
[1.3.0]: https://github.com/Masakai/meteo/compare/v1.2.0...v1.3.0
[1.2.0]: https://github.com/Masakai/meteo/compare/v1.1.0...v1.2.0
[1.1.0]: https://github.com/Masakai/meteo/compare/v1.0.0...v1.1.0
[1.0.0]: https://github.com/Masakai/meteo/releases/tag/v1.0.0

## Project Information

**Copyright**: © 2026 Masanori Sakai
**License**: MIT License
**Company**: 株式会社リバーランズ・コンサルティング
