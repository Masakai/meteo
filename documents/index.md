# Meteo ドキュメントサイト

Meteo は、RTSP カメラ映像を対象にした流星・雲検出システムです。  
このサイトでは、導入から運用、API、内部構造までを段階的に確認できます。

## まず読む

- 初回導入: [セットアップマニュアル](SETUP_GUIDE.md)
- 基本設定: [設定ガイド](CONFIGURATION_GUIDE.md)
- 日常運用: [運用ガイド](OPERATIONS_GUIDE.md)

## 開発・運用向け

- API 利用: [API リファレンス](API_REFERENCE.md)
- 検出精度改善: [検出感度チューニングガイド](DETECTION_TUNING.md)
- セキュリティ運用: [セキュリティガイド](SECURITY.md)

## 内部設計

- 全体設計: [アーキテクチャドキュメント](ARCHITECTURE.md)
- Docker 構成: [Docker コンテナ構成](DOCKER_ARCHITECTURE.md)
- 検出処理の内訳: [内部コンポーネント仕様](DETECTOR_COMPONENTS.md)
- 日照・天文計算: [天文計算モジュール仕様](ASTRO_UTILS.md)
