# レビュー報告書: カメラ単位のマスクリセット機能

- 作成日: 2026-06-27
- 対象プロジェクト: Meteo (Meteor Event Tracking and Early Observation)
- 要件トレーサビリティ: チケット番号なし（設計確定済み・指示書ベース）
- 関連実装仕様書: documents/specs/2026-06-27-camera-mask-reset.md
- 関連設計書: なし
- 関連Issue / PR: なし
- レビュー回数: 第1回

## レビュー対象

未コミットの作業ツリー差分（`git diff HEAD`、6ファイル / +221行）:

- `http_handlers.py`: 新エンドポイント `POST /reset_mask`、ヘルパー `_delete_mask_from_build_dir`、プレビューHTMLの「マスクリセット」ボタンと `resetMask()` JS
- `dashboard_camera_handlers.py`: `handle_camera_mask_reset`（`/reset_mask` へプロキシ）
- `dashboard_routes.py`: `handle_camera_mask_reset` ラッパー
- `dashboard.py`: `/camera_mask_reset/<int:camera_index>` ルート登録
- `tests/test_http_handlers.py`: `_delete_mask_from_build_dir` のテスト3件
- `documents/API_REFERENCE.md`: v3.17.0 のエンドポイント仕様

変更禁止ファイル（`meteor_detector_common.py` / `meteor_detector_realtime.py` / `astro_utils.py`）への変更なし（確認済み）。

## 合格項目

- **正しさ（マスク無効化）**: `update_exclusion_mask(None)` は `meteor_detector_realtime.py:684` で `mask_lock` 取得下に `self.exclusion_mask = new_mask` を実行するのみ。`None` 引数を正しく扱い、リセット後 `/stats` の `mask_active`（`exclusion_mask is not None`、L467）が `false` になる。仕様書の記述と一致。
- **正しさ（ファイル削除）**: 出力ディレクトリ側は `current_output_dir`/`current_camera_name` がある場合のみ、`_storage_camera_name()` 経由の固定ファイル名で `exists()` チェック後 `unlink(missing_ok=True)`。保存パス生成ロジックは `/update_mask`（L605-608）と一致しており対称性が取れている。
- **スレッドセーフティ**: pending クリアは `state.current_pending_mask_lock` 下で実行（既存 `confirm_mask_update` L641-648 / `discard_mask_update` L688-691 と同一パターン）。detector マスク更新は detector 内部の `mask_lock` で保護。lock の使い方は既存実装と完全に整合。
- **セキュリティ（パストラバーサル）**: `_delete_mask_from_build_dir`（L91-103）は既存 `_write_mask_to_build_dir`（L75-88）と同一の防御ロジック（`Path.resolve()` + `str(dest).startswith(str(build_dir) + os.sep) or dest.parent == build_dir`）。削除対象名はサーバー内部生成の固定名（`{camera}_mask.png`）で外部入力を含まない。任意ファイル削除のリスクなし。
- **既存パターンとの一貫性**: 4レイヤー（Flask route → routes ラッパー → camera_handlers → `_proxy_camera_post`）の構造とレスポンス形式（200 / application/json / `Access-Control-Allow-Origin: *`）が既存 `/camera_mask_discard` 系と完全に同形。`detector not ready` 失敗レスポンスも `confirm_mask_update` と同一。
- **ディスパッチ登録**: `dashboard.py:246` の `@app.post` で正しく登録され、4レイヤー全ての呼び出し鎖が結線されている。
- **UIの一貫性**: `resetMask()` の `btn.disabled` 制御・`finally` での1500ms文言復帰・`setMaskOverlay(false)` は既存 `updateMask()` に揃っている。f-string 内の波括弧エスケープ（`{{` `}}`）も正しい。`/stats` ポーリング（L368-377）が `mask_active=false` 検知時に overlay を再度 OFF にするため、リセット後のUI状態は二重に整合する。
- **ドキュメント同期**: API_REFERENCE.md のレスポンス例・フィールド説明（`deleted` は出力ディレクトリ側パスのみ）がコード実態（build_dir 削除は `deleted` に含めない）と一致。バージョン履歴・両層の一覧表行・詳細節を追加済み。

## 指摘事項

### [重大度: 低] http_handlers.py:710-742 `/reset_mask` 分岐はユニットテスト対象外

`do_POST` は `# pragma: no cover` クラス（`MJPEGHandler`）内のため、分岐ロジック本体（detector 未初期化の早期 return、出力側削除、pending クリアの統合）はユニットテストでカバーされていない。テストは抽出ヘルパー `_delete_mask_from_build_dir` の3件のみ。これは既存マスクエンドポイント（confirm/discard）と同じ制約であり、本変更で新たに劣化させたものではない。修正必須ではないが、将来 `do_POST` 分岐ロジックを純関数へ抽出してテスト可能にする余地がある。

### [重大度: 低] tests/test_http_handlers.py — エッジケースの追加余地

追加3件（正常削除 / 空 build_dir / パストラバーサル防御）は `_write_mask_to_build_dir` のテスト群と同スタイルで妥当。ただし以下は未カバー（必須ではない）:
- `save_path_name` が空文字のケース（`not (mask_build_dir and save_path_name)` の後半条件）
- 削除対象ファイルが存在しないケース（`unlink(missing_ok=True)` が例外を出さないこと）

正常系・防御・no-op の主要3分岐は押さえられており、テストは実動作を検証している（形式的テストではない）。

### [重大度: 低] resetMask() JS: 失敗時にオーバーレイ状態を変更しない

`data.success` が false（detector 未初期化等）の場合、ボタン文言を「失敗」にするのみで `overlay` の状態には触れない。これは既存挙動と整合し問題ないが、リセット失敗時にマスクが残っている状態をユーザーが視認しづらい可能性がある。動作上の欠陥ではなく、改善の余地として記録するに留める。

## セキュリティ検査結果

- **パストラバーサル**: `_delete_mask_from_build_dir` は既存の書き込みヘルパーと同等の `resolve()` + 境界チェックを実装。削除名は内部生成の固定名で外部入力なし。テストで `../secret.png` が build_dir 外を削除しないことを検証済み（`name` 抽出で `secret.png` に正規化され build_dir 直下に閉じる）。任意ファイル削除リスクなし。**問題なし**。
- **コマンドインジェクション**: シェルコマンド実行なし。**対象外**。
- **XSS**: `/reset_mask` のレスポンス・UIともユーザー入力をHTMLへ展開しない。`deleted` 配列はJSONレスポンスとして返されるのみ（DOMへ未挿入）。**問題なし**。
- **認証情報漏洩**: 例外は既存スタイルで握りつぶし、エラーメッセージは固定文字列（`detector not ready`）のみ。内部パスは `deleted` に出力されるが、これは既存 `confirm_mask_update` の `saved` フィールドと同パターンであり、管理用WebUIの想定運用範囲内。**新規リスクなし**。
- **メモ整合**: `_write_mask_to_build_dir` の `dest == build_dir` ではなく `dest.parent == build_dir` を使う点（reviewerメモ security_patterns.md に記載の「より正確な保護」）を本ヘルパーは正しく踏襲している。

## ドキュメント整合性

- `documents/API_REFERENCE.md` の記述はコード実態と一致（`deleted` は出力ディレクトリ側のみ、`mask_active` が false になる、detector 未初期化時の失敗レスポンス形式）。
- 仕様書（`documents/specs/2026-06-27-camera-mask-reset.md`）は変更ファイル一覧・実装詳細・テスト結果・残課題が正確。
- 既知の制限として、ダッシュボード層の既存 `/camera_mask` / `/camera_mask_confirm` / `/camera_mask_discard` がエンドポイント一覧表に未記載である点が仕様書に明記されている。本スコープでは `/camera_mask_reset` のみ追記しており、スコープ判断として妥当。
- VERSION定数（`dashboard_config.py`）更新・CHANGELOG追記は未実施（release-manager 担当）。API_REFERENCE は v3.17.0 を前提に記載済みのため、リリース時にVERSIONを `3.17.0` へ更新する必要がある（下記申し送り）。

## 総評

- 判定: **承認**
- ブロッカー: **なし**。重大度「高」「中」の指摘はゼロ。指摘は全て重大度「低」（テストカバレッジの追加余地・UI改善余地）であり、いずれもリリースを妨げない。
- 本変更は既存マスクエンドポイント（update/confirm/discard）の確立されたパターンを正確に踏襲しており、正しさ・スレッドセーフティ・パストラバーサル防御・4レイヤープロキシ構造・レスポンス形式・ドキュメント同期のいずれも合格。

### release-manager への申し送り

- VERSION 定数（`dashboard_config.py`）を **3.17.0** へ更新すること。API_REFERENCE.md は既に v3.17.0 前提で記載済み。
- CHANGELOG へ「カメラ単位のマスクリセット機能（`/reset_mask`, `/camera_mask_reset/{index}`）」を追記すること。
- 変更種別は新機能追加のため MINOR 上げ（v3.16.0 → v3.17.0）で正しい。
- 全体テストの既存failure 2件（`test_create_app_go2rtc_asset_proxy`, `test_generate_compose_mask_path_failure`）は本変更と無関係（clean tree で再現確認済み）。リリースブロッカーではないが、別途追跡を推奨。
