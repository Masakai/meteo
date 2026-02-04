# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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
