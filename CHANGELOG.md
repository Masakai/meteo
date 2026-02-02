# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
