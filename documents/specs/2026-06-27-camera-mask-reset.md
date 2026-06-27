# 実装仕様書: カメラ単位のマスクリセット機能

- 作成日: 2026-06-27
- 対象プロジェクト: Meteo
- 要件トレーサビリティ: （設計確定済み・チケット番号は引き継ぎなし）
- 関連設計書: なし（指示書ベースで実装）
- 関連Issue / PR: なし

## 概要

指定カメラの除外マスクを無効化する操作を追加した。既存の `/update_mask`→`/confirm_mask_update`（マスク設定）の対称となる新エンドポイント `/reset_mask`（カメラ層）と `/camera_mask_reset/{index}`（ダッシュボード層）を実装し、カメラプレビュー画面に「マスクリセット」ボタンを追加した。実行後は `/stats` の `mask_active` が `false` になる。

## 変更ファイル一覧

| ファイル | 変更種別 | 変更内容 |
|---------|---------|---------|
| http_handlers.py | 修正 | ヘルパー `_delete_mask_from_build_dir` 追加、`do_POST` に `/reset_mask` 分岐追加、プレビューHTMLに「マスクリセット」ボタンと `resetMask()` JS追加 |
| dashboard_camera_handlers.py | 修正 | `handle_camera_mask_reset` 追加（`/reset_mask` へプロキシ） |
| dashboard_routes.py | 修正 | `handle_camera_mask_reset` ラッパー追加 |
| dashboard.py | 修正 | `/camera_mask_reset/<int:camera_index>` ルート追加 |
| tests/test_http_handlers.py | 修正 | `_delete_mask_from_build_dir` のテスト3件追加 |
| documents/API_REFERENCE.md | 修正 | v3.17.0 履歴・両層エンドポイント一覧行・仕様節を追加 |

## 実装の詳細

### http_handlers.py

- **`_delete_mask_from_build_dir(mask_build_dir, save_path_name)`**: 既存 `_write_mask_to_build_dir` と同じパストラバーサル防御（`dest` が `build_dir` 直下であることを `str(dest).startswith(str(build_dir) + os.sep) or dest.parent == build_dir` で確認）を行い、条件を満たす場合のみ `dest.unlink(missing_ok=True)` で削除する。`mask_build_dir` または `save_path_name` が空の場合は何もしない。例外は既存スタイルに合わせ握りつぶす。
- **`/reset_mask` 分岐**（`/discard_mask_update` 直後）: レスポンスヘッダは他POST分岐と同一（200 / application/json / `Access-Control-Allow-Origin: *`）。`state.current_detector is None` の場合は `{"success": False, "error": "detector not ready"}` を返す。それ以外は (1) `state.current_detector.update_exclusion_mask(None)`、(2) 出力ディレクトリ側 `current_output_dir/"masks"/f"{_storage_camera_name(...)}_mask.png"` を存在チェックして `unlink(missing_ok=True)`（削除パスを `deleted` に集約、例外握りつぶし）と `MASK_BUILD_DIR` 側の同名ファイル削除、(3) `current_pending_mask_lock` 下で pending をクリア、を実行し `{"success": True, "message": "mask reset", "deleted": [...]}` を返す。出力側削除は `current_output_dir` かつ `current_camera_name` がある場合のみ実施する（保存パス生成ロジックを `/update_mask` と揃えた）。
- **UI**: `<div class="actions">` に「マスクリセット」ボタンを1つ追加。`resetMask()` は `confirm('マスクをリセットします。よろしいですか？')` 確認後 `fetch('/reset_mask', {method:'POST'})` を呼び、成功時はオーバーレイ表示を `setMaskOverlay(false)` でOFF、ボタン文言を一時的に「リセット完了」にする。`btn.disabled` 制御と `finally` での文言復帰（1500ms）は既存 `updateMask()` に揃えた。f-string 内のため波括弧は `{{` `}}` でエスケープ済み。

### dashboard_camera_handlers.py / dashboard_routes.py / dashboard.py

`/camera_mask_discard`（既存）と完全に同形のプロキシを追加。`handle_camera_mask_reset` は `/camera_mask_reset/` で始まらなければ False、それ以外は `_proxy_camera_post(handler, "/reset_mask", 200, *args)`。ダッシュボード側ルートは `/camera_mask_reset/<int:camera_index>` を POST で受け、`routes.handle_camera_mask_reset` にディスパッチする。

### tests/test_http_handlers.py

`_delete_mask_from_build_dir` のテスト3件を既存 `_write_mask_to_build_dir` テスト群と同じスタイルで追加:
- (a) `MASK_BUILD_DIR` 配下のファイルを正しく削除する
- (b) `MASK_BUILD_DIR` が空文字なら何もしない（例外を出さない）
- (c) `../secret.png` のような名前でも build_dir 外（`tmp_path/secret.png`）を削除しないことを確認

## テスト結果

| テストコマンド | 結果 |
|-------------|-----|
| `python -m pytest tests/test_http_handlers.py -q`（コンテナ内・bind mount） | PASSED（12件） |
| `python -m pytest -q`（全体・コンテナ内） | 306 passed, 2 failed（※既存failure・本変更と無関係） |
| `flake8 http_handlers.py dashboard_camera_handlers.py dashboard_routes.py dashboard.py tests/test_http_handlers.py` | クリーン（exit 0） |

### テスト実行に関する補足

コンテナイメージ（`meteo-camera1:latest`）は `requirements-docker.txt` ベースで pytest を含まず、`tests/` も COPY していないため、`docker compose run --rm camera1 pytest` は実行できない。CLAUDE.md の「テストはコンテナ内」要件を満たすため、同イメージにプロジェクトを bind mount し pytest をその場でインストールして実行した（`docker run --rm -v "$PWD":/app -w /app --entrypoint sh meteo-camera1:latest -c "pip install pytest && python -m pytest ..."`）。Python 3.11 / opencv-python-headless のコンテナ環境で実行している。

全体テストの2件の失敗（`test_dashboard_app.py::test_create_app_go2rtc_asset_proxy`、`test_generate_compose.py::test_generate_compose_mask_path_failure`）は、本変更5ファイルを `git stash` した clean tree でも同様に失敗することを確認済みで、本実装とは無関係の既存failureである。

## 残課題・既知の制限

- ダッシュボード層の `/camera_mask` / `/camera_mask_confirm` / `/camera_mask_discard` 系プロキシは元々 API_REFERENCE のエンドポイント一覧表に記載がなく、本対応では新規追加した `/camera_mask_reset/{index}` のみ表へ追記した（スコープ限定のため既存欠落の補完は行っていない）。
- 既存テストの2件failureは本スコープ外。

## reviewerへの引き継ぎ事項

- `/reset_mask` のパストラバーサル防御は `_delete_mask_from_build_dir` が `_write_mask_to_build_dir` と同一ロジックである点を確認してほしい。出力ディレクトリ側削除はカメラ名から組み立てた固定ファイル名（`_storage_camera_name` 経由）を使うため外部入力を含まない。
- `do_POST` の `/reset_mask` 分岐は `# pragma: no cover` クラス内のためユニットテスト対象外。ヘルパー `_delete_mask_from_build_dir` のみテスト済み。
- VERSION定数更新・CHANGELOG追記・git操作は未実施（release-manager担当）。バージョンは v3.17.0 を想定して API_REFERENCE に記載済み。
