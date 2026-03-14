# リポジトリ戦略（meteo / meteo-core / meteo-box）

## 役割
- `meteo`（現行）: 上流開発母体。検出ロジックを最初に開発・検証する。
- `meteo-core`: コアライブラリ。製品側が依存する配布インターフェース。
- `meteo-box`: 商用機能を持つ製品リポジトリ。

## 推奨変更フロー
1. コア変更を `meteo` で実装・テスト
2. `meteo-core` に同期してバージョン更新（SemVer）
3. `meteo-box` で `meteo-core` バージョンを更新
4. 結合テスト後に `meteo-box` をリリース

## 分離時の責務境界
- `meteo-core` に入れる:
  - 検出アルゴリズム
  - 画像処理ユーティリティ
  - データモデル
  - コアテスト
- `meteo-box` に入れる:
  - 認証/権限
  - UI/ダッシュボード
  - 通知連携
  - ライセンス/課金
  - 運用管理

## 初期セットアップ
```bash
./scaffold/scripts/bootstrap_repos.sh /Users/sakaimasanori/Dropbox
```
