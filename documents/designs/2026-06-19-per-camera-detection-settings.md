# 設計書: カメラごとの個別検出設定

- 作成日: 2026-06-19
- 対象プロジェクト: Meteo (meteor-event-tracking)
- 要件トレーサビリティ: ユーザー要望（カメラ交換時のカメラ固有調整、口頭/チャット要件）
- 関連Issue / PR: なし（新規）

## 背景・目的

現在、ダッシュボードの `/settings` 画面は「全カメラ一括適用」しかできない（`applyAll()` → `POST /camera_settings/apply_all` → 全カメラの `POST /apply_settings` へループ送信）。

カメラ交換・設置環境差（光害・画角・ノイズ源）により 1 台だけパラメータを調整したいケースで、UI 上の手段がない。現状の回避策は `detections/runtime_settings/<camera>.json` を手編集してカメラを再起動することだが、運用者向けではない。

設定の保存先は既に `detections/runtime_settings/<camera>.json` とカメラ単位で独立しており、各カメラの `POST /apply_settings` も単一カメラ向けに設計済み。つまり**個別保存・個別適用の下地はバックエンドに揃っている**。不足しているのは「ダッシュボードから 1 台だけを指定して適用する経路」と「カメラを選んで現在値を読み込む UI」だけである。

## 設計概要

方針: **既存の一括適用フローを一切変更せず温存し、個別適用を「追加」する**。後方互換性を最優先とする。

1. **API（追加）**: ダッシュボードに `POST /camera_settings/apply_one` を新設する。リクエストで対象カメラ（`camera_index` または `camera` 内部名）を 1 つ受け取り、そのカメラの `/apply_settings` にのみ payload を中継する。`apply_all` は無変更。
2. **API（拡張）**: `GET /camera_settings/current` を拡張し、全カメラ分の設定を `results[]` に既に格納している現状を活かしつつ、レスポンス先頭の `settings`（= 1 台目）に加えてカメラ別の設定を UI から個別参照できるようにする。後方互換のため既存フィールド（`settings` / `results` / `process_min_dim` / `ok_count` / `total`）は維持し、各 `results[i]` に `process_min_dim` を含める拡張のみ行う。
3. **UI（追加）**: `/settings` 画面のツールバーに「対象カメラ」ドロップダウン（`<select>`）を追加する。
   - 既定値 `__all__`（全カメラ）を選ぶと従来どおり「全カメラに適用」ボタンが `apply_all` を叩く。
   - 個別カメラ（内部名）を選ぶと、適用ボタンが `apply_one` を叩き、「現在値を取得」はそのカメラの設定だけをフォームへ反映する。
4. **データフロー**: ダッシュボード → 対象カメラの `/apply_settings` → 当該カメラの `runtime_settings/<camera>.json`。書き分けは「どのカメラの `/apply_settings` を呼ぶか」だけで自然に成立する（カメラ側ロジックは無変更）。

変更禁止ファイル（`meteor_detector_common.py` / `meteor_detector_realtime.py` / `astro_utils.py`）には**一切触れない**。カメラ側の `http_handlers.py` の `/apply_settings`（750-1182 行）も無変更で再利用する。

## 検討した選択肢と却下理由

### A. `apply_all` を拡張して `cameras: [...]` フィルタを受け取る（却下）
`POST /camera_settings/apply_all` の payload に対象カメラ配列フィールドを混在させる案。
- 却下理由: payload は現状「検出パラメータそのもの」であり、そこに制御用フィールド（対象カメラ）を混ぜると、カメラ側 `/apply_settings` へ中継される payload に余計なキーが載るか、ダッシュボード側で除去ロジックが必要になる。設定キーと制御キーの分離が崩れ、将来の項目追加時に名前衝突リスクが出る。エンドポイントを分けた方が責務が明確。

### B. カメラ選択を「タブ」UI にする（却下）
カメラごとにタブを並べ、タブ切り替えでフォーム内容を入れ替える案。
- 却下理由: 現状フォームは単一の `id` ベース（`fields` 配列が `getElementById` で全項目を駆動）。タブごとにフォーム状態を保持するには DOM 構造と JS の大幅な作り替えが必要で、最小変更の原則に反する。ドロップダウン + 「現在値を取得」で 1 フォームを使い回す方が既存コードへの差分が小さい。

### C. ダッシュボードを介さずカメラコンテナへ直接適用（却下）
- 却下理由: ダッシュボードはカメラ内部名 → コンテナ URL の解決（`_camera_url_for_proxy` / `_camera_apply_settings_target`）と Docker 内ホスト名解決を担っており、ブラウザから各カメラへ直接到達させる前提を崩す。既存の中継アーキテクチャを踏襲する。

### 採用案
上記 A〜C を却下し、「`apply_one` 新設 + `current` の軽微拡張 + ドロップダウン追加」を採用。バックエンドの中継パターン・カメラ側ロジック・既存一括フローを温存できる。

## 要件の整理

### 機能要件
- FR-1: `/settings` 画面で「対象カメラ」を全カメラ（既定）または特定 1 台から選べる。
- FR-2: 特定カメラ選択時、「現在値を取得」はそのカメラの現在設定のみをフォームへ反映する。
- FR-3: 特定カメラ選択時、適用ボタンはそのカメラの `runtime_settings/<camera>.json` にのみ反映する。他カメラの設定は変化しない。
- FR-4: 全カメラ選択時（既定）は従来どおり全カメラへ一括適用する（既存挙動を完全維持）。
- FR-5: 対象パラメータは現行の一括設定と同一の全項目（`fields` 配列 = `sensitivity`, `scale`, `buffer`, `extract_clips`, `clip_margin_*`, `twilight_*`, `bird_*`, `diff_threshold`, `min_brightness`, `min_linearity`, `min_speed`, `min_area`/`max_area`, `nuisance_*`, `mask_*` など全 40 項目超）。

### 非機能要件
- NFR-1: 既存の `apply_all` / `current` のレスポンス契約を壊さない（既存 UI・curl 利用・既存テストが通る）。
- NFR-2: パストラバーサル等の入力検証はカメラ側 `/apply_settings`（`_validate_app_path`, 916-946 行）に既存実装があり、個別適用でも同じ経路を通るため検証は維持される。ダッシュボード側では `camera_index` の範囲検証を必須とする。
- NFR-3: 即時反映項目／再起動必須項目（`sensitivity`/`scale`/`buffer`/`extract_clips`）の扱いはカメラ側で従来どおり判定される。個別適用でも `restart_required` / `restart_requested` がレスポンスに返る。

### 後方互換性要件
- BC-1: 既存エンドポイント（`apply_all`, `current`）のパス・メソッド・必須フィールドを変更しない。
- BC-2: 既存テスト（`tests/test_dashboard_routes.py::test_handle_camera_settings_apply_all`, `::test_handle_camera_settings_current`）を改変せず通す。
- BC-3: 「対象カメラ」未選択（= `__all__`）時の挙動は現行と完全一致。

## UI の設計

対象ファイル: `dashboard_templates_settings.py`（`render_settings_html(cameras, version)`）。`cameras` を既に受け取っているため、ドロップダウンの option 生成に追加引数は不要。

### 1. カメラ選択ドロップダウン
ツールバー（248-254 行付近）に以下を追加する。

```html
<select id="target_camera">
    <option value="__all__">全カメラ</option>
    <!-- cameras をループ: value=内部名(cam["name"]), 表示=display_name or name -->
    <option value="camera1">北空（camera1）</option>
    ...
</select>
```
- `value` には**内部名**（`cam["name"]`）を入れる（`runtime_settings/<camera>.json` のキーと一致させるため）。
- 表示ラベルは `cam.get("display_name", cam["name"])` を使い、内部名を括弧書きで併記する（運用者が内部名と表示名の対応を把握できるようにする）。
- 見出し `<h1>全カメラ設定` と `<div class="sub">…一括適用します` は、対象選択に応じて文言を JS で出し分ける（例: 個別選択時「camera1 のみに適用します」）。静的文言は据え置きでも可（オープンクエスチョン参照）。

### 2. 適用ボタンの分岐
既存の「全カメラに適用」ボタン（253 行 `onclick="applyAll()"`）はそのまま残し、JS 側で対象に応じて分岐する。`applyAll()` を以下のように振り分ける（または新関数 `applyTarget()` を追加してボタンの onclick を差し替える）。

```js
async function applyTarget() {
    const target = document.getElementById('target_camera').value;
    const payload = collectPayload();   // 既存ロジック流用
    if (target === '__all__') {
        // 既存 applyAll の本体（/camera_settings/apply_all へ POST）
    } else {
        // /camera_settings/apply_one へ { camera: target, settings: payload } を POST
    }
}
```
ボタンラベルも対象に応じて「全カメラに適用 / camera1 に適用」と JS で切り替える。

### 3. 現在値の読み込み（GET 系）
既存 `loadCurrent()`（620-634 行）は `/camera_settings/current` を叩き、レスポンス先頭の `settings`（1 台目）でフォームを埋めている。個別対応のため次のいずれか:

- 推奨: `GET /camera_settings/current` のレスポンスを 1 度だけ取得し、JS 側で `results[]` を `camera` 名で引けるよう保持する。対象ドロップダウン変更時／個別「現在値を取得」時に、`results.find(r => r.camera === target).settings` でフォームを埋める。`__all__` 選択時は従来どおり先頭 `settings` を使う。
  - この方式なら**新規 GET エンドポイントは不要**。`current` は既に全カメラ分を `results[]` で返している。
  - ただし `process_min_dim` が現状レスポンス全体に 1 つ（先頭カメラ由来）しかないため、カメラ別に `exclude_edge_ratio` の px 換算を正確にするには各 `results[i]` に `process_min_dim` を含める拡張が望ましい（FR-2 の精度向上。スコープに含める）。

レスポンス契約は追加フィールドのみで後方互換。

## API の設計

### 新規: `POST /camera_settings/apply_one`

- **説明**: 指定した 1 カメラへ設定を適用（当該カメラの `POST /apply_settings` のみ呼び出し）。
- **リクエストボディ**:
```json
{
  "camera": "camera1",
  "settings": {
    "diff_threshold": 20,
    "min_brightness": 180,
    "min_linearity": 0.8
  }
}
```
  - `camera`: 対象カメラの**内部名**（`CAMERAS[i]["name"]`）。代替として `camera_index`（0 始まり整数）も受理可とする（実装簡素化のため、内部名を `CAMERAS` から index 解決する）。
  - `settings`: 適用する検出パラメータ（`apply_all` の payload と同一スキーマ）。
  - 後方互換のため、`settings` キーが無く payload 直下にパラメータが並ぶ形式も許容するかは実装判断（オープンクエスチョン）。推奨は `{camera, settings}` のネスト形式で統一。
- **バリデーション**: `camera` が `CAMERAS` に存在しない／`camera_index` が範囲外 → 400 を返す（NFR-2）。
- **レスポンス**（`apply_all` の単一カメラ版に揃える）:
```json
{
  "success": true,
  "camera": "camera1",
  "applied_count": 1,
  "total": 1,
  "results": [
    {
      "camera": "camera1",
      "success": true,
      "response": {
        "success": true,
        "applied": {"diff_threshold": 20},
        "restart_required": true,
        "restart_requested": true,
        "restart_triggers": ["sensitivity", "scale"]
      }
    }
  ]
}
```
  `results[]` 形式を `apply_all` と揃えることで、UI 側の `extractApiError()`（600-618 行）をそのまま再利用できる。

### 拡張: `GET /camera_settings/current`

- 既存フィールド（`success`, `settings`, `results`, `ok_count`, `total`, `process_min_dim`）を維持。
- 各 `results[i]` に `process_min_dim` を追加（カメラ別 px 換算用）。`handle_camera_settings_current`（`dashboard_camera_handlers.py` 287-335 行）で、現状 `first_process_min_dim` だけ拾っている箇所を各カメラ分も格納するよう拡張。
- これは追加のみで後方互換。

### 無変更: `POST /camera_settings/apply_all`
変更しない。

## データフローの設計

```
[ブラウザ /settings]
  対象 = __all__:
    collectPayload() → POST /camera_settings/apply_all
      → dashboard_camera_handlers.handle_camera_settings_apply_all
      → for cam in CAMERAS: POST {cam}/apply_settings
      → 各カメラが runtime_settings/<camera>.json を更新（_save_runtime_overrides）

  対象 = camera1:
    {camera:"camera1", settings: collectPayload()}
      → POST /camera_settings/apply_one
      → dashboard_camera_handlers.handle_camera_settings_apply_one
      → camera_index = name→index 解決 → _camera_apply_settings_target(index)
      → camera1 の POST /apply_settings のみ
      → camera1 が runtime_settings/camera1.json のみ更新
```

書き分けは「呼び出すカメラを 1 台に絞る」だけで成立する。カメラ側 `/apply_settings`（即時反映 vs 再起動必須の判定、`_save_runtime_overrides` での永続化）は一括・個別で完全に同一コードを通る。これにより「一括と個別で永続化挙動が乖離する」リスクを排除できる。

## 影響範囲

| ファイル | 変更種別 | 変更内容 |
|---------|---------|---------|
| `dashboard_camera_handlers.py` | 修正 | `handle_camera_settings_apply_one(handler, cameras, camera_apply_settings_target, request_cls, urlopen_fn)` を新設（`apply_all` を 1 カメラ向けに切り出した実装）。`handle_camera_settings_current` で各 `results[i]` に `process_min_dim` を追加 |
| `dashboard_routes.py` | 修正 | `handle_camera_settings_apply_one(handler)` ラッパを追加（`_camera_apply_settings_target`, `Request`, `urlopen`, `CAMERAS` を渡す）。内部名→index 解決ヘルパを追加 |
| `dashboard.py` | 修正 | `@app.post("/camera_settings/apply_one")` ルートを追加し `_dispatch(routes.handle_camera_settings_apply_one, path="/camera_settings/apply_one")` を呼ぶ |
| `dashboard_templates_settings.py` | 修正 | ツールバーに `#target_camera` ドロップダウン追加（`cameras` ループで option 生成）。JS に `applyTarget()`／対象別ラベル切替／`results[]` をカメラ名で引く現在値反映ロジックを追加。見出し・sub 文言の出し分け |
| `meteor_detector_common.py` | 変更なし | 変更禁止ファイル。触れない |
| `meteor_detector_realtime.py` | 変更なし | 変更禁止ファイル。触れない |
| `astro_utils.py` | 変更なし | 変更禁止ファイル。触れない |
| `http_handlers.py`（カメラ側 `/apply_settings`） | 変更なし | 既存の単一カメラ適用ロジックを無変更で再利用 |
| `detection_state.py` | 変更なし | `_runtime_override_paths` / `_load_runtime_overrides` を無変更で利用 |

新規ファイルは作成しない（全て既存ファイルへの追加で完結）。

## 実装タスク

1. `dashboard_camera_handlers.py`: `handle_camera_settings_apply_one` を追加。
   - パスは `/camera_settings/apply_one` のみ受理（それ以外は `return False`）。
   - body をパースし、`camera`（内部名）または `camera_index` を取得。`settings` ネストを取り出す（無ければ payload 直下を settings とみなすかは実装判断）。
   - 対象カメラを `cameras` から解決。見つからなければ 400。
   - `camera_apply_settings_target(index)` へ `settings` を POST。レスポンスを `apply_all` と同形（`results[]`, `applied_count`, `total`, `camera`）で返す。
2. `dashboard_camera_handlers.py`: `handle_camera_settings_current` 内で各カメラの `data.get("process_min_dim")` を `results[i]["process_min_dim"]` に格納。
3. `dashboard_routes.py`: `handle_camera_settings_apply_one(handler)` ラッパ追加。内部名→index 解決（`CAMERAS` を線形探索、なければ `camera_index` をそのまま使用、範囲外は handler 側で 400）。
4. `dashboard.py`: `POST /camera_settings/apply_one` ルートを `apply_all` ルートの直後に追加。
5. `dashboard_templates_settings.py`:
   - ツールバーに `#target_camera` ドロップダウン（`__all__` + 各カメラ）を追加。
   - JS `applyTarget()` を実装し、適用ボタンの `onclick` を差し替え（または `applyAll` をラップ）。
   - `loadCurrent()` を、取得済み `results[]` を保持して対象カメラの `settings` でフォームを埋める形へ拡張。`__all__` は従来どおり先頭 `settings`。
   - 対象に応じてボタンラベル・見出し文言を切り替え。
6. テスト追加（下記テスト方針参照）。

## テスト方針

### 既存テストへの影響
- `tests/test_dashboard_routes.py::test_handle_camera_settings_apply_all` / `::test_handle_camera_settings_current`: レスポンスは追加フィールドのみのため**改変不要で通る**ことを確認（`process_min_dim` を `results[i]` に追加しても既存アサーションは `settings` / `applied_count` を見ているだけ）。
- `tests/test_dashboard_templates_settings.py`: テンプレート構造テスト。ドロップダウン追加で既存アサーションが壊れないこと（`render_settings_html` の戻り値に必要要素が残ること）を確認。必要なら `#target_camera` の存在アサーションを追加。

### 新規ユニットテスト（`tests/test_dashboard_routes.py` / `tests/test_dashboard_camera_handlers.py`）
- `test_handle_camera_settings_apply_one_success`: `camera="cam1"` 指定で、`fake_urlopen` が `/apply_settings` を **1 回だけ**呼ぶこと、`applied_count==1`、`camera=="cam1"` を検証。
- `test_handle_camera_settings_apply_one_does_not_touch_others`: 複数カメラ登録時、対象外カメラの `/apply_settings` が呼ばれないこと（FR-3）。
- `test_handle_camera_settings_apply_one_invalid_camera`: 存在しない `camera` / 範囲外 `camera_index` で 400 を返すこと（NFR-2）。
- `test_handle_camera_settings_apply_one_invalid_payload`: 不正 JSON で 400。
- `test_handle_camera_settings_current_includes_per_camera_process_min_dim`: `results[i]` に `process_min_dim` が含まれること。
- テンプレート: `test_render_settings_html_has_target_camera_select`（`#target_camera` と各カメラ option が出ること）。

### 手動確認（コンテナ内）
- `docker compose run --rm <camera> pytest -q` で全テスト通過。
- ブラウザで `/settings`: 全カメラ選択 → 従来どおり一括適用。個別選択 → 該当カメラの `runtime_settings/<camera>.json` のみ更新され、他カメラの JSON が不変であることをファイル比較で確認。
- 再起動必須項目（`scale` 等）を個別適用時に当該カメラのみ再起動すること、`restart_triggers` がレスポンスに返ることを確認。

## ドキュメント更新が必要なファイル

- `documents/API_REFERENCE.md`:
  - エンドポイント一覧表（273-274 行付近）に `POST /camera_settings/apply_one` を追加。
  - 詳細仕様セクション（`apply_all` の節 937-985 行の直後）に `apply_one` のリクエスト/レスポンス例・curl 例を追記（既存スタイルに合わせる）。
  - `GET /camera_settings/current`（900-933 行）のレスポンス例に `results[i].process_min_dim` を追記。
  - バージョン履歴に新セクション（例 `### v3.16.0 - カメラ個別検出設定`）を追加。
- `documents/CONFIGURATION_GUIDE.md`:
  - 「ダッシュボード一括設定」節（228-261 行）を「ダッシュボード設定（一括／個別）」に拡張。対象カメラドロップダウンの使い方、個別適用が `runtime_settings/<camera>.json` を 1 台分だけ更新する旨を追記。
  - 設定変更の推奨手順（254-260 行）に「対象カメラを選んでから適用」のステップを追加。
- `documents/ARCHITECTURE.md`:
  - 「6. 設定反映アーキテクチャ」（418-423 行）に、一括（全カメラループ）に加え個別（1 カメラのみ中継）の経路を追記。`apply_one` → 対象カメラ `/apply_settings` → 当該 `runtime_settings/<camera>.json` のフローを 1〜2 行で記載。
- `documents/DETECTOR_COMPONENTS.md`: 変更不要（カメラ側ロジック無変更のため）。

GitHub Pages 公開対象のため、コード変更と同一リリースでドキュメントを更新する。

## バージョン番号の提案

現行 `VERSION = "3.15.7"`（`dashboard_config.py:7` で確認済み）。

新機能追加のため MINOR を上げ **`3.16.0`** を提案する（CLAUDE.md のセマンティックバージョニング規約「新機能追加 → MINOR」に準拠）。後方互換であり MAJOR は不要。

## セキュリティ・互換性・その他の考慮事項

- **セキュリティ**: マスク画像パス等のパストラバーサル検証はカメラ側 `/apply_settings`（`_validate_app_path` 923-946 行）に既存実装があり、個別適用でも同経路を通るため検証は維持される。ダッシュボード側 `apply_one` では `camera` 内部名／`camera_index` の存在・範囲検証を必須とし、不正値で他カメラへ誤適用されないようにする。
- **後方互換性**: `apply_all` / `current` のパス・メソッド・必須フィールドを維持。`current` は追加フィールドのみ。既存 curl 利用者・既存テストに影響しない。
- **パフォーマンス**: 個別適用は 1 カメラへの単発 HTTP。一括より軽い。
- **運用**: 個別適用後の `runtime_settings/<camera>.json` はカメラごとに独立しているため、`generate_compose.py` 再生成やコンテナ再起動後も各カメラが自分の JSON を読み込み、個別設定が維持される（`meteor_detector_rtsp_web.py:413-487`, `detection_state.py:113-121`）。

## オープンクエスチョン

1. **payload 形式の統一**: `apply_one` のリクエストを `{camera, settings:{...}}` のネスト固定にするか、payload 直下にパラメータを並べる形（`{camera, diff_threshold, ...}`）も許容するか。推奨はネスト固定（制御キーと設定キーの分離が明確）。実装フェーズで確定。
2. **カメラ識別子**: `camera`（内部名）と `camera_index`（整数）の両方を受理するか、どちらかに固定するか。UI は内部名で送る前提だが、API の堅牢性として index も受けるかは実装判断。
3. **見出し・sub 文言の動的切替**: 「全カメラ設定」見出しを個別選択時に JS で書き換えるか、静的のままにするか（UI 体験の好みの問題。最小実装では静的のままでも機能要件は満たす）。
4. **「現在値を取得」の取得タイミング**: ドロップダウン変更時に自動でフォームを埋めるか、明示ボタン押下時のみか。誤って未保存の編集内容を上書きしないよう、明示ボタン方式が無難（実装フェーズで UX 確定）。
