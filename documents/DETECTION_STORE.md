# 検出結果ストレージ仕様 (Detection Store)

**バージョン: v3.11.1**

---

**Copyright (c) 2026 Masanori Sakai**

Licensed under the MIT License

---


## 概要

v3.6.0 以降、検出結果の **正本（source of truth）** は SQLite データベース `$DETECTIONS_DIR/detections.db` に移行しました。検出エンジンは引き続き各カメラの `detections.jsonl` に追記し、ダッシュボードが増分同期で SQLite へ取り込む 2 層構造になっています。

- **検出エンジン（書き込み側）**: `meteor_detector_rtsp_web.py` が `camera{i}/detections.jsonl` に 1 行追記
- **ダッシュボード（読み取り側）**: `detection_store.sync_camera_from_jsonl()` で新規行のみ SQLite に取り込み、以降の読み取り・削除・ラベル更新は SQLite 上で実施
- **ロールバック**: SQLite を使わない状態に戻すには `detections.db` を削除するだけ（JSONL は保持されるため検出データは失われない）

モジュール実装は `detection_store.py` に集約されています。本ドキュメントはその仕様・スキーマ・主要 API・関連マイグレーションスクリプトをまとめます。

## 目次

- [SQLite スキーマ](#sqlite-スキーマ)
- [JSONL → SQLite 同期アルゴリズム](#jsonl--sqlite-同期アルゴリズム)
- [主要 API](#主要-api)
- [マイグレーションスクリプト](#マイグレーションスクリプト)
- [運用ポイント](#運用ポイント)

---

## SQLite スキーマ

`detection_store.init_db(db_path)` がスキーマを作成します。WAL モード・外部キー有効で接続し、スレッドローカル接続をキャッシュします。

### detections テーブル

検出結果本体。1 行 = 1 検出イベント。

```sql
CREATE TABLE IF NOT EXISTS detections (
    id                      TEXT PRIMARY KEY,
    camera                  TEXT NOT NULL,
    timestamp               TEXT NOT NULL,
    confidence              REAL,
    base_name               TEXT,
    clip_path               TEXT DEFAULT '',
    image_path              TEXT DEFAULT '',
    composite_original_path TEXT DEFAULT '',
    alternate_clip_paths    TEXT DEFAULT '',
    label                   TEXT DEFAULT '',
    deleted                 INTEGER DEFAULT 0,
    raw_json                TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_camera    ON detections(camera);
CREATE INDEX IF NOT EXISTS idx_timestamp ON detections(timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_active    ON detections(deleted) WHERE deleted = 0;
```

### カラムの役割

| カラム | 型 | 説明 |
|---|---|---|
| `id` | TEXT | SHA-1 ベースの検出ID（`det_` + 先頭20桁）。`migrate_detection_ids.py` 由来 |
| `camera` | TEXT | カメラ内部名。v3.11.0 以降は検出ディレクトリ名が `camera{i}` に固定されたため、新規書き込みでも `camera{i}` が入る（`TEXT` 型自体は変更なし） |
| `timestamp` | TEXT | ISO 8601 形式の検出時刻 |
| `confidence` | REAL | 信頼度 0.0〜1.0 |
| `base_name` | TEXT | ベースファイル名（例: `meteor_20260202_065533`） |
| `clip_path` | TEXT | 動画ファイルのカメラディレクトリ相対パス |
| `image_path` | TEXT | コンポジット画像のパス |
| `composite_original_path` | TEXT | 元画像の比較明合成パス |
| `alternate_clip_paths` | TEXT | 追加クリップパス（JSON配列として保存） |
| `label` | TEXT | ラベル（`""` / `"meteor"` / `"non-meteor"` 等、v1.10.0+） |
| `deleted` | INTEGER | 論理削除フラグ（0=アクティブ、1=削除済み） |
| `raw_json` | TEXT | JSONL の元レコード全文（監査・再解析用） |

### jsonl_sync_state テーブル

`sync_camera_from_jsonl()` が各カメラごとに読み取り位置を記憶するための内部テーブル。

```sql
CREATE TABLE IF NOT EXISTS jsonl_sync_state (
    camera  TEXT PRIMARY KEY,
    offset  INTEGER NOT NULL DEFAULT 0,
    mtime   REAL    NOT NULL DEFAULT 0.0
);
```

| カラム | 説明 |
|---|---|
| `camera` | 対象カメラ内部名 |
| `offset` | 最後まで読んだバイトオフセット |
| `mtime` | 最後に参照した JSONL の `mtime`（POSIX 秒） |

---

## JSONL → SQLite 同期アルゴリズム

関数: `sync_camera_from_jsonl(camera_name, cam_dir, db_path, normalize_fn) -> int`

`dashboard_routes.py` からカメラごとに呼び出され、新規行のみを SQLite に取り込みます。戻り値は新規挿入件数。

### 処理フロー

```
1. 前回の (offset, mtime) を jsonl_sync_state から取得
2. 現在の detections.jsonl の (current_size, current_mtime) を stat() で取得
3. ショートサーキット: current_mtime == prev_mtime かつ current_size <= prev_offset
   → 変更なしとみなして 0 を返す
4. 切り詰め検知: current_size < prev_offset → offset=0 から再読込
5. 前回 offset から EOF まで読み、各行について:
   - 空行はスキップ
   - JSON パース → normalize_fn(camera_name, cam_dir, raw) で正規化
   - INSERT OR IGNORE で検出テーブルに挿入（id 衝突は無視）
   - 行処理後の f.tell() で new_offset を更新
6. jsonl_sync_state を (camera, new_offset, current_mtime) で UPSERT
7. commit
```

### INSERT OR IGNORE による冪等性

同じ JSONL ファイルを再度頭から読んでも、`id` が PRIMARY KEY なので重複行は無視されます。これによりマイグレーションや同期の再実行が常に安全です。

### normalize_fn の責務

`dashboard_routes._normalize_detection_record()` が使われます。以下を行います:

- `id` の扱い: 生 JSONL に `id` フィールドがあればそのまま使用し、無い場合のみ `_make_detection_id()`（`timestamp` / `start_time` / `end_time` / `start_point` / `end_point` の SHA-1 ダイジェスト先頭20桁）で新規発番する（実装: `dashboard_routes.py:_normalize_detection_id`）
- `base_name` を timestamp から推測
- 相対パス `clip_path` / `image_path` / `composite_original_path` を組み立て（JSONL 側のファイル名にカメラディレクトリを前置）
- `alternate_clip_paths` を既存ファイル探索で補完（`.mov` / `.mp4` の並存対応）
- 外部ラベルファイル（`detection_labels.json`）を `label` にマージ

### ファイル切り詰め / 再作成への耐性

検出エンジンが JSONL を一度消して書き直すような場面（マイグレーション直後など）でも、`current_size < prev_offset` 検知で自動的に頭から再読込するため整合性を保ちます。

---

## 主要 API

### init_db(db_path)

スキーマ作成。ダッシュボード起動時に 1 度だけ呼ばれる。

### sync_camera_from_jsonl(camera_name, cam_dir, db_path, normalize_fn) -> int

上記「同期アルゴリズム」参照。

### query_detections(db_path, *, camera=None, deleted=False, limit=None) -> list[dict]

検出結果の読み取り。デフォルトでは `deleted = 0` のみを返す。

```python
# 全カメラの最新 100 件（アクティブ）
rows = detection_store.query_detections(db_path, limit=100)

# 特定カメラの削除済みレコード
rows = detection_store.query_detections(db_path, camera="camera1", deleted=True)
```

戻り値の各 dict には `alternate_clip_paths` が **パース済みのリスト** として含まれます（SQLite 上は JSON 文字列）。

### query_detections_for_stats(db_path, start_ts, end_ts) -> list[dict]

統計用の軽量クエリ。`id` / `camera` / `timestamp` のみを返し、期間フィルタ（`timestamp >= start_ts AND timestamp < end_ts`）を適用します。統計ページ（`/stats_data`）のバックエンドで使用。

### get_detection_by_id(db_path, detection_id) -> dict | None

ID 1 件取得。`DELETE /detection/{camera}/{id}` から削除対象のパス情報を得るために使用。

### soft_delete(db_path, detection_id)

論理削除（`UPDATE detections SET deleted = 1 WHERE id = ?`）。JSONL は変更しない。

### set_label(db_path, detection_id, label)

ラベル更新。`POST /detection_label` から呼ばれる。

### count_asset_references(db_path, asset_path, *, exclude_id="") -> int

指定ファイルパスを参照しているアクティブレコード数を返す。

- `clip_path` / `image_path` / `composite_original_path` の 3 スカラー列を完全一致で確認
- `alternate_clip_paths` の JSON 文字列は `LIKE ? ESCAPE '\\'` でワイルドカード検索（パス文字列を `"path"` で囲むパターンにマッチ）
- `exclude_id` を指定すると自分自身を除外した参照数を返す

削除 API がメディアファイルを物理削除する前に `exclude_id=id` で呼び出し、返り値が 0 のときだけ `os.remove()` を行う、というガードに使用されます。

### reset_sync_state(db_path, camera_name)

JSONL の sync state を 0 にリセットする。`sync_camera_from_jsonl` が次回呼ばれた際にファイル全体を再読込する。JSONL を外部から書き換えた・削除した場合に使用する。

---

## マイグレーションスクリプト

### scripts/migrate_jsonl_to_sqlite.py

v3.6.0 への初回アップデート時に実行。既存の `detections.jsonl` と `detection_labels.json` を SQLite へ一括取り込みます。

- **冪等**: `INSERT OR IGNORE` により再実行しても重複しない
- **JSONL は非破壊**: 削除されずそのまま残る（ロールバックソース）
- **ラベル統合**: 別ファイルの `detection_labels.json` を同時に取り込む
- **引数**: なし（argparse を持たない）。対象ディレクトリは環境変数 `DETECTIONS_DIR`（既定: `detections`）で指定する
- **実行**: `DETECTIONS_DIR=./detections python scripts/migrate_jsonl_to_sqlite.py`

### scripts/migrate_detection_ids.py

検出 ID 命名規則の統一（timestamp + start_time + end_time + start_point + end_point の SHA-1 ハッシュ）を過去データにも適用します。旧形式で ID が付与されていないか、古い規則で付与されていたレコードを一括で再発番します。

- **対象**: 主に `detections.jsonl`（再書き出し）
- **ID ロジック**: `make_detection_id()` — SHA-1 20桁を `det_` プレフィックスで包んで返す
- **実行**: `python scripts/migrate_detection_ids.py`

### migrate_camera_dirs.py（プロジェクトルート）

v3.11.0 への初回アップデート時に実行。IP 含みのディレクトリ名を `camera{i}` に統合し、SQLite の `camera` 列・パス列も一括更新します。

- **最初の実行は必ず `--dry-run` から**: `migrate_camera_dirs.py` は他スクリプトと異なりデフォルトで本実行する。必ず `--dry-run` で内容を確認してから本実行すること
- **自動バックアップ**: `detections.db.bak_<timestamp>`
- **元ディレクトリの残置**: 移動完了後は `camera{i}_*.migrated_<timestamp>/` にリネーム
- **実行**: `python migrate_camera_dirs.py --dry-run` → `python migrate_camera_dirs.py`
- **詳細**: [OPERATIONS_GUIDE.md](OPERATIONS_GUIDE.md#v3110--カメラ名インデックス化アップデート)

### 3 つのスクリプトの関係

| 発生順序 | スクリプト | 変更対象 |
|---|---|---|
| 1. v3.6.0 アップデート時 | `scripts/migrate_jsonl_to_sqlite.py` | JSONL → SQLite 初回取り込み |
| 2. 必要に応じて | `scripts/migrate_detection_ids.py` | JSONL 内の ID 付与漏れ補修 |
| 3. v3.11.0 アップデート時 | `migrate_camera_dirs.py` | ディレクトリ名 + SQLite の camera 列 |

いずれも冪等性が確保されているため、複数回実行しても安全です。

---

## 運用ポイント

### バックアップ

```bash
# SQLite DB と JSONL を一緒にアーカイブ
tar -czf detections-backup-$(date +%Y%m%d).tar.gz detections/
```

SQLite WAL ファイルも含めるため、バックアップ時はダッシュボード停止が望ましいです。

### 状態ダンプ

```bash
# 全検出（削除済みを除く）を table 形式で表示
python scripts/dump_detections_db.py

# 特定カメラの最新 20 件を JSON 形式で
python scripts/dump_detections_db.py --camera camera1 --limit 20 --format json

# sync_state テーブルを見る
python scripts/dump_detections_db.py --table sync
```

`scripts/dump_detections_db.py` は読み取り専用なので運用中でも安全に使えます。

### トラブルシューティング

!!! warning "DB 削除前には必ずバックアップを取る"
    `detections.db` を削除すると `jsonl_sync_state` もリセットされるため、JSONL が残っていても再同期中に別の問題が出る可能性があります。削除前には以下を実行してください。

    ```bash
    cp detections/detections.db detections/detections.db.bak_$(date +%s)
    ```

- **検出が UI に出ない**: `dump_detections_db.py` で DB に入っているか確認 → 入っていないなら JSONL の sync が詰まっている可能性。`reset_sync_state` または DB 削除 → `migrate_jsonl_to_sqlite.py` 再実行（削除前に上記バックアップを取る）
- **誤削除をリカバリしたい**: `detections.db` を事前にバックアップしてから削除し、`scripts/migrate_jsonl_to_sqlite.py` を再実行。ただしラベル情報は `detection_labels.json` が残っていれば復元できる
- **マイグレーション失敗**: `detections.db.bak_<timestamp>` が自動保存されているので `cp detections.db.bak_<timestamp> detections.db` で戻せる（`migrate_camera_dirs.py` 実行時）

---

## 関連ドキュメント

- [ARCHITECTURE.md](ARCHITECTURE.md) - 検出結果削除シーケンス（SQLite ベース）
- [API_REFERENCE.md](API_REFERENCE.md) - `/detections` / `DELETE /detection/{camera}/{id}` / `/detection_label` の仕様
- [OPERATIONS_GUIDE.md](OPERATIONS_GUIDE.md) - バージョン別マイグレーション手順
- [SCRIPTS_REFERENCE.md](SCRIPTS_REFERENCE.md) - 運用スクリプト全一覧
- [CONFIGURATION_GUIDE.md](CONFIGURATION_GUIDE.md) - `DETECTIONS_DIR` 等の環境変数
