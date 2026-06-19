# 実装仕様書: カメラごとの個別検出設定

- 実装日: 2026-06-19
- 対象バージョン: v3.16.0
- 設計書: `documents/designs/2026-06-19-per-camera-detection-settings.md`
- 実装者: メインセッション（developerサブエージェントはEdit権限の制約により実装不可だったため、設計・計画を引き継いでメインで実装）

## 概要

ダッシュボードの検出設定が「全カメラ一括」のみだった状態に、「特定 1 カメラのみへ個別適用」する経路を追加した。既存の一括適用フロー（`apply_all`）は無変更で温存し、後方互換を維持している。

決定済み方針（ユーザー確定）:
1. UI: 一括適用と個別適用の両立。
2. 対象: 検出パラメータ全項目。
3. 個別適用APIは `POST /camera_settings/apply_one` を新設。
4. payload形式は `{"camera": "<内部名>", "settings": {...}}` のネスト固定。
5. カメラ識別子は内部名（`camera1`...）。後方互換で `camera_index` 整数も受理。
6. 対象カメラ切替時は現在値を自動反映せず、「現在値を読み込む」明示ボタンで反映。

## ファイルごとの変更点

### `dashboard_camera_handlers.py`
- `handle_camera_settings_apply_one(handler, cameras, camera_apply_settings_target, request_cls, urlopen_fn)` を新設。
  - パスが `/camera_settings/apply_one` 以外なら `return False`。
  - body をJSONパース。非object / 不正JSON → 400。
  - `camera`（内部名）を `cameras` 線形探索でindex解決。`camera_index`（整数・範囲内）も許容。解決不可 → 400。
  - `settings` がdictでない → 400。
  - 対象1台の `/apply_settings` のみへ `settings` をPOST。レスポンスは `apply_all` と同形（`success`/`camera`/`applied_count`/`total:1`/`results[]`）。
- `handle_camera_settings_current`: 各 `results[i]` に `process_min_dim`（カメラ別）を追加。トップレベルの `settings`/`process_min_dim` は従来どおり先頭カメラ由来で後方互換。

### `dashboard_routes.py`
- `handle_camera_settings_apply_one(handler)` ラッパを追加。`CAMERAS` / `_camera_apply_settings_target` / `Request` / `urlopen` を渡す。

### `dashboard.py`
- `@app.post("/camera_settings/apply_one")` ルートを `apply_all` の直後に追加。

### `dashboard_templates_settings.py`
- `import html` 追加。
- 関数冒頭でXSS対策済みの `camera_options_html` を組み立て（`html.escape` で value/ラベルをエスケープ）。表示名がある場合「表示名（内部名）」、なければ内部名のみをラベルに。
- ツールバーに「対象カメラ」`<select id="target_camera">` と「現在値を読み込む」ボタンを追加。適用ボタンの `onclick` を `applyTarget()` に変更（`id="apply_btn"`）。見出しを「全カメラ設定」→「カメラ設定」に、sub文言を `id="settings_sub"` 化。
- JS追加・改修:
  - `getTargetCamera()`: 選択中の対象を返す。
  - `onTargetChange()`: 対象変更時にボタンラベル・説明文のみ更新（フォームは自動上書きしない）。
  - `loadCurrent()`: `__all__` は従来どおり先頭 `settings`。個別カメラ選択時は `results[]` を `camera` 名で引き、当該カメラの `settings` と `process_min_dim` でフォームを埋める。
  - `applyTarget()`: `__all__` → `applyAll()`、個別 → `applyOne(camera)` に振り分け。
  - `applyOne(camera)`: `/camera_settings/apply_one` へ `{camera, settings}` をPOST。
  - `applyAll()` は本体無変更。

### `dashboard_config.py`
- `VERSION` を `3.15.7` → `3.16.0`。

## 新規エンドポイント仕様: `POST /camera_settings/apply_one`

リクエスト:
```json
{ "camera": "camera1", "settings": { "diff_threshold": 20, "min_brightness": 180 } }
```
- `camera`: 内部名（`camera_index` 整数も可）
- `settings`: 検出パラメータ（`apply_all` と同一スキーマ、ネスト必須）

レスポンス（200）:
```json
{
  "success": true,
  "camera": "camera1",
  "applied_count": 1,
  "total": 1,
  "results": [ { "camera": "camera1", "success": true, "response": { "success": true, "restart_triggers": ["scale"] } } ]
}
```

エラー（400）: 不正JSON / `camera` 解決不可 / `settings` 欠落・非object。いずれも対象カメラへ中継せず即座に400を返す（誤適用防止）。

## UIの変更内容

- 「対象カメラ」ドロップダウン（`__all__` + 各カメラ内部名、ラベルに表示名併記）。
- 「現在値を読み込む」ボタン: 押下時のみ、選択中カメラの現在設定をフォームへ反映。
- 適用ボタン: 対象に応じてラベルと送信先（`apply_all` / `apply_one`）を切替。
- 対象切替（`onTargetChange`）ではフォームを書き換えず、ラベル・説明文のみ更新（未保存編集の保護）。

## 後方互換性の担保

- `apply_all` のハンドラ・ルート・payload形式・レスポンスは完全無変更。
- `current` は追加フィールド（`results[i].process_min_dim`）のみで、既存フィールドの形・意味は不変。
- カメラ側 `http_handlers.py` の `/apply_settings`、変更禁止ファイル（`meteor_detector_common.py` 他）、`detection_state.py` は無変更で再利用。
- 既存テスト `test_handle_camera_settings_apply_all` / `test_handle_camera_settings_current` は改変せず通過。

## テスト結果

### 追加テスト
`tests/test_dashboard_routes.py`:
- `test_handle_camera_settings_current_includes_per_camera_process_min_dim`
- `test_handle_camera_settings_apply_one_success`（1台のみ中継・applied_count==1）
- `test_handle_camera_settings_apply_one_does_not_touch_others`（対象外カメラに中継しない）
- `test_handle_camera_settings_apply_one_invalid_camera`（存在しないカメラ → 400・中継なし）
- `test_handle_camera_settings_apply_one_missing_settings`（settings欠落 → 400）
- `test_handle_camera_settings_apply_one_invalid_json`（不正JSON → 400）

`tests/test_dashboard_templates_settings.py`:
- `test_render_settings_html_has_target_camera_select`（ドロップダウン・option・apply_one経路の存在）
- `test_render_settings_html_escapes_camera_label`（表示名のHTMLエスケープ）

### 実行環境と結果
- **コンテナ内実行は不可**: 本番イメージ（`meteo-camera1`）に pytest がインストールされていないため `docker compose run --rm camera1 pytest -q` は `pytest: executable file not found` で失敗。
- **代替: `.venv` で実行**（CLAUDE.mdの「コンテナ依存のない純粋ユニットテストは venv 可」方針に準拠。対象テストはFlask・標準ライブラリのみでOpenCV等のコンテナ依存なし）。
  - `pytest -q tests/test_dashboard_routes.py tests/test_dashboard_templates_settings.py tests/test_dashboard_camera_handlers.py tests/test_dashboard_app.py tests/test_dashboard_config.py` → **61 passed**
  - 全スイート `pytest -q` → **299 passed, 1 failed**
- **flake8**: 変更ファイル全てクリーン（exit 0）。

### 既存の失敗（本変更とは無関係）
`tests/test_generate_compose.py::test_generate_compose_mask_path_failure` が1件失敗。`git stash` で本変更を退避した状態でも同様に失敗することを確認済みで、**変更前から存在する既存の失敗**。原因は作業ツリーに `masks/camera1_mask.png` が存在し「手動更新済みのため上書きしない」分岐でマスク生成がスキップされ、テストが期待する `SystemExit` が発生しないため。本実装のスコープ外。

## ドキュメント更新

設計書の改版計画に従い更新済み:
- `documents/API_REFERENCE.md`: バージョン履歴に v3.16.0 追加 / エンドポイント一覧に `apply_one` 追加 / `apply_one` 詳細節を追加 / `current` レスポンス例に `process_min_dim` 追記。
- `documents/CONFIGURATION_GUIDE.md`: 「ダッシュボード設定（一括／個別）」へ拡張、対象カメラ選択の使い方と推奨手順を更新。
- `documents/ARCHITECTURE.md`: 「6. 設定反映アーキテクチャ」に一括／個別の2経路を追記。
- `documents/DETECTOR_COMPONENTS.md`: 変更不要（カメラ側ロジック無変更）。

## スコープ外の申し送り

1. **`test_generate_compose.py::test_generate_compose_mask_path_failure` の既存失敗**: 作業ツリーに `masks/camera1_mask.png` が存在する環境依存でテストが落ちる。本変更前から存在。別途、テスト側で `masks/` をモック/隔離するか、テスト用の一時マスクディレクトリを使う修正が望ましい（要判断）。
2. **本番イメージにpytestが無い件**: `docker compose run --rm <camera> pytest` が現状動かない。CIでテストをどう回しているか（テスト用イメージ/ステージ分離の有無）はci-engineerの領域。今回は触れていない。
3. **手動E2E未実施**: 実カメラ環境でのブラウザ動作確認（個別適用で対象カメラの `runtime_settings/<camera>.json` のみ更新され他カメラが不変であること、`restart_triggers` がUIに表示されること）は本作業では未実施。リリース前に本番系（greeng4）以外の環境で確認推奨。

## レビュー指摘への対応（2026-06-19 追記）

reviewer レビュー（`documents/reviews/2026-06-19-per-camera-detection-settings.md`、総合判定: 承認）の指摘に対応した。

- **Low（bool index）対応**: `apply_one` の `camera_index` 検証を `isinstance(raw_index, int) and not isinstance(raw_index, bool)` に変更。`camera_index: true` を `1` と誤解釈せず 400 を返す。
- **Low（異常系テスト不足）対応**: 以下を `tests/test_dashboard_routes.py` に追加。
  - `test_handle_camera_settings_apply_one_by_index`（camera_index経路の正常系）
  - `test_handle_camera_settings_apply_one_rejects_bool_index`（bool境界）
  - `test_handle_camera_settings_apply_one_index_out_of_range`（負値・範囲外）
  - `test_handle_camera_settings_apply_one_empty_camera`（空文字・null）
  - `test_handle_camera_settings_apply_one_settings_wrong_type`（null・配列・文字列・数値）
- **Info（初回ラベル）対応**: テンプレート末尾で `loadCurrent()` の前に `onTargetChange()` を呼び、ページロード/select状態復元時の初回ラベル・説明文を対象に同期。

再検証: 対象5スイート **66 passed**（61→66）、flake8 クリーン。

## リリース判断

新機能追加のため reviewer レビュー実施済み（承認）。レビュー指摘（Low 2件・Info 1件）対応済み。VERSION定数は `3.16.0` へ更新済みだが、CHANGELOG追記・タグ・`gh release create` 等のリリース作業は未実施（release-managerの責務）。
