# レビュー報告書: カメラごとの個別検出設定（v3.16.0）

- 作成日: 2026-06-19
- 対象プロジェクト: Meteo (meteor-event-tracking)
- 要件トレーサビリティ: ユーザー要望（カメラ交換時のカメラ固有調整、口頭/チャット要件）
- 関連実装仕様書: documents/specs/2026-06-19-per-camera-detection-settings.md
- 関連設計書: documents/designs/2026-06-19-per-camera-detection-settings.md
- 関連Issue / PR: なし（新規）
- レビュー回数: 第1回

## レビュー対象

base コミット c74889d との差分（10ファイル / +442 -20）:

コード:
- `dashboard.py`（`POST /camera_settings/apply_one` ルート追加）
- `dashboard_camera_handlers.py`（`handle_camera_settings_apply_one` 新設、`handle_camera_settings_current` に `process_min_dim` 追加）
- `dashboard_routes.py`（`apply_one` ラッパ追加）
- `dashboard_templates_settings.py`（対象カメラドロップダウン、`applyTarget`/`applyOne`/`onTargetChange` JS、`html.escape` による option 組み立て）
- `dashboard_config.py`（VERSION 3.15.7 → 3.16.0）

テスト:
- `tests/test_dashboard_routes.py`（apply_one の正常系/異常系、current の process_min_dim）
- `tests/test_dashboard_templates_settings.py`（ドロップダウン存在、XSSエスケープ）

ドキュメント:
- `documents/API_REFERENCE.md`, `documents/ARCHITECTURE.md`, `documents/CONFIGURATION_GUIDE.md`

## 合格項目

- **後方互換性（apply_all）**: `handle_camera_settings_apply_all` のハンドラ・ルート・payload形式・レスポンスは完全無変更。差分に出現しない。BC-1/BC-2/BC-3 を満たす。
- **後方互換性（current）**: `results[i]` への `process_min_dim` 追加は純粋な追加フィールド。トップレベル `settings`/`process_min_dim`/`ok_count`/`total` の形・意味は不変。既存テスト `test_handle_camera_settings_current` は改変なしで通過。
- **process_min_dim 抽出ロジック**: 先頭成功カメラ判定（`if not first_settings ...`）が `cam_process_min_dim` を介して従来と同値を保持。回帰なし。
- **正確性（1台中継）**: `camera_index` を線形解決し `camera_apply_settings_target(camera_index)` のみ呼び出す。テスト `apply_one_success`/`does_not_touch_others` で1回のみ中継・対象外カメラ不可触を検証済み。実カメラの index→URL 解決は既存 `_camera_apply_settings_target` を再利用。
- **入力検証（誤適用防止）**: 不正JSON / 非object payload / `camera` 解決不可 / `settings` 非dict のいずれも、中継前に 400 を返し対象カメラへ到達しない。`urlopen` を AssertionError 化したテストで中継ゼロを担保。
- **レスポンス整合**: `results[]` 形式・`error` キーが `apply_all` と同形。UI の `extractApiError`（`data.error` → `results[].error` の順で拾う）と整合し、中継例外時の `result.error` を表示できる。
- **XSS対策**: option の value は `html.escape(internal_name, quote=True)`、ラベルは `html.escape(label)` でエスケープ。`<script>` 注入テストで生タグ非出力・`&lt;script&gt;` 出力を検証。JS の `applyOne(camera)` は `JSON.stringify` でボディ化しており文字列連結インジェクションなし。`alert`/`setStatus` への camera 名差し込みは DOM textContent / alert 引数であり HTML 解釈されない。
- **未保存編集の保護**: `onTargetChange` はボタンラベルと説明文のみ更新し `fillForm` を呼ばない。現在値反映は「現在値を読み込む」明示ボタンのみ（仕様 FR-2 / 決定事項6に合致）。
- **px換算**: `loadCurrent` が個別カメラ選択時に `found.process_min_dim` を `processMinDim` に反映。`collectPayload` の `exclude_edge_ratio` 換算がカメラ別 dim を使うようになり精度向上。`__all__` 時は従来どおり先頭基準。
- **変更禁止ファイル**: `meteor_detector_common.py` / `meteor_detector_realtime.py` / `astro_utils.py` / カメラ側 `http_handlers.py` は git diff で無変更を確認。
- **バージョン**: 新機能追加につき MINOR を上げ 3.16.0。セマンティックバージョニング規約に準拠。
- **テスト**: 対象5スイート 61 passed。flake8 変更7ファイル exit 0。
- **ドキュメント同期**: API_REFERENCE（バージョン履歴・一覧表・詳細節・current レスポンス例）、ARCHITECTURE（設定反映2経路）、CONFIGURATION_GUIDE（一括/個別・推奨手順）いずれも実装と一致。エンドポイント・レスポンス例・バージョン番号に齟齬なし。

## 指摘事項

### [重大度: Low] dashboard_camera_handlers.py:421-432 — `camera_index` の型・境界検証が `bool` を弾かない
`isinstance(payload.get("camera_index"), int)` は Python では `True`/`False` も `int` として通る（`bool` は `int` のサブクラス）。`camera_index: true` を渡すと `idx=True`（=1）と解釈され、カメラが2台以上ある環境で index=1 のカメラへ適用されうる。負値・範囲外は `0 <= idx < len(cameras)` で正しく弾かれるため誤適用範囲は限定的だが、API堅牢性として `bool` を明示除外（`isinstance(x, int) and not isinstance(x, bool)`）するのが望ましい。なお UI は常に内部名 `camera` を送るため実運用経路では発生しない。

### [重大度: Low] tests/test_dashboard_routes.py — `camera_index` 経路・bool 境界・空文字camera・settings=null/配列の異常系が未カバー
追加テストは `camera`（内部名）経路のみを検証している。設計・仕様で受理対象としている `camera_index` 整数経路、および以下の境界が未テスト:
- `camera_index` 範囲外（負値・`len(cameras)` 以上）→ 400
- `camera_index: true`（上記Low指摘の回帰検出用）
- `camera: ""`（空文字）/ `camera: null` → 400
- `settings: null` / `settings: []`（配列）→ 400

`settings` 欠落・不正JSON・存在しないカメラ名はカバー済み。上記は仕様で「受理/拒否」を明記している経路なので、回帰防止のため追加を推奨（必須ではない）。

### [重大度: Info] dashboard_camera_handlers.py:405 — `handle_camera_settings_apply_all` との重複コード
`apply_one` は `apply_all` のループ本体（Request生成・urlopen・レスポンス整形）をほぼ複製している。設計の「最小変更・apply_all 無変更」方針により意図的な複製であり、今回の指摘ではない。将来 `/apply_settings` 中継の共通処理が3箇所目に増える場合はヘルパ抽出を検討。

### [重大度: Info] dashboard_templates_settings.py:645 — ブラウザの select 状態復元時に初回ラベルがずれる可能性
ページロード時 `onTargetChange()` は呼ばれず、`apply_btn` の初期ラベルは静的に「全カメラに適用」。通常は select 初期値 `__all__` と一致し問題ない。ただしブラウザがフォーム状態を復元して個別カメラが選択された状態で表示されると、ボタンラベルだけ「全カメラに適用」のまま残りうる（クリック時は `getTargetCamera()` が実値を読むため適用先自体は正しい）。表示上の軽微な不整合。初期化時に `onTargetChange()` を一度呼ぶと解消する。

## セキュリティ検査結果

- **XSS**: option 生成で value/ラベルとも `html.escape`（value は `quote=True`）。`display_name` 経由・`name` 経由の両方でエスケープが効く。テストで `<script>` 注入の無害化を確認。合格。
- **コマンドインジェクション**: シェル実行経路なし。該当なし。
- **パストラバーサル**: ダッシュボード側は `camera`/`camera_index` を `CAMERAS` リストの index 解決にのみ使用し、ファイルパスへ直接連結しない。マスクパス等の検証はカメラ側 `/apply_settings`（既存 `_validate_app_path`）が担い、個別適用も同一経路を通る（無変更）。誤適用は入力検証4種で防止。合格。
- **認証情報漏洩**: ログ・レスポンスへの認証情報出力なし。`result.error` に中継例外文字列が入るが URL/payload のみで秘匿情報なし。合格。
- **誤適用（横展開）**: 不正payloadで他カメラへ中継しないことをテストで担保。`bool` の `camera_index` のみ理論上の隙（上記Low）だが UI 経路では発生せず、かつ範囲チェックで影響限定。

## ドキュメント整合性

- API_REFERENCE.md: `apply_one` の説明・リクエスト/レスポンス例・バリデーション・curl例が実装と一致。`current` レスポンス例の `results[i].process_min_dim` 追記も実装どおり。バージョン履歴 v3.16.0 追加済み。
- ARCHITECTURE.md: 「6. 設定反映アーキテクチャ」に一括/個別2経路を追記。実装の中継フローと一致。
- CONFIGURATION_GUIDE.md: 対象カメラ選択・推奨手順・「切り替えてもフォームは自動で書き換わらない」旨が実装挙動（onTargetChange）と一致。
- 齟齬・未更新箇所は検出されず。

## テスト・lint 確認結果

- 対象5スイート（test_dashboard_routes / test_dashboard_templates_settings / test_dashboard_camera_handlers / test_dashboard_app / test_dashboard_config）: **61 passed**（.venv で再実行）。
- flake8（変更7ファイル）: **exit 0**（クリーン）。
- 既存失敗 `test_generate_compose.py::test_generate_compose_mask_path_failure` の本変更無関係性を検証:
  - 現状で再現（`DID NOT RAISE SystemExit`）。原因は作業ツリーに `masks/camera1_mask.png` が存在し「手動更新済みのため上書きしません」分岐に入り、テストが期待する `generate_mask_file` 例外経路に到達しないため。
  - `generate_compose.py` / `tests/test_generate_compose.py` は本変更で差分ゼロ（git diff で確認）。失敗は作業ツリーの `masks/*.png` という環境依存であり、本機能とは完全に無関係。仕様書 §既存の失敗 の記載は正確。
  - 申し送り: テスト側で `masks/` を一時ディレクトリへ隔離する修正が望ましいが、本リリースのスコープ外（別チケット推奨）。

## 総評

- 判定: **承認**
- 重大度 High 以上の指摘なし。後方互換性（apply_all/current の契約維持）、セキュリティ（XSS・誤適用防止）、正確性（1台のみ中継）、UI整合（未保存編集の保護・px換算）、ドキュメント同期のいずれも要件を満たす。テスト 61 passed・flake8 クリーン。
- 指摘は Low 2件（`camera_index` の bool 非除外、異常系テストの拡充）と Info 2件のみで、いずれもリリースを止めるものではない。UI 実運用経路（内部名送信）では Low 指摘の事象は発生しない。
- リリース可否の推奨: **リリース可**。Low 指摘は次回の小改善で取り込めば足りる。

### release-manager への申し送り

- CHANGELOG 追記・タグ・`gh release create` は未実施（release-manager 責務）。VERSION は 3.16.0 へ更新済み。
- 既存失敗 `test_generate_compose_mask_path_failure` は本変更と無関係の環境依存。CI が `masks/` を持たないクリーン環境なら通る想定。リリースブロッカーではない。
- 手動E2E（実カメラで個別適用時に対象カメラの `runtime_settings/<camera>.json` のみ更新され他カメラ不変・`restart_triggers` のUI表示）は未実施。本番 greeng4 以外の環境で確認を推奨。

## 是正処置記録

該当なし（要修正の指摘なし）。Low/Info 指摘は任意対応。
