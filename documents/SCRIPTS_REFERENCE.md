# 運用スクリプトリファレンス (Scripts Reference)

**バージョン: v3.11.1**

---

**Copyright (c) 2026 Masanori Sakai**

Licensed under the MIT License

---


## 概要

`scripts/` 配下およびプロジェクトルート直下に、検出データのマイグレーション・救済・インポート/エクスポート・調査を行うスタンドアロンスクリプトが配置されています。このドキュメントは各スクリプトの目的・引数・冪等性・破壊性を 1 ページにまとめたリファレンスです。

### 凡例

| 項目 | 意味 |
|---|---|
| **冪等性** | ○=再実行しても副作用が増えない、×=再実行で副作用増加の恐れ |
| **破壊性** | 書き込み対象（JSONL / SQLite / ファイルシステム） |
| **dry-run** | プレビューモードの有無 |

## サマリ一覧

| スクリプト | 配置 | 用途 | 冪等性 | 破壊性 | dry-run |
|---|---|---|---|---|---|
| [migrate_jsonl_to_sqlite.py](#migrate_jsonl_to_sqlitepy) | `scripts/` | v3.6.0 SQLite 初回取り込み | ○ | SQLite 書き込み（JSONL 非破壊） | dry-run なし |
| [migrate_camera_dirs.py](#migrate_camera_dirspy) | プロジェクトルート | v3.11.0 カメラ名インデックス化 | ○ | ディレクトリ移動 + SQLite 更新（自動バックアップ） | ⚠️ **デフォルト本実行**。`--dry-run` を明示しない限り書き込みが発生する（他スクリプトと挙動が逆） |
| [migrate_detection_ids.py](#migrate_detection_idspy) | `scripts/` | 検出 ID の再発番・付与漏れ補修 | ○ | JSONL 書き換え | デフォルト dry-run（`--apply` で本実行） |
| [rescue_orphan_detection_files.py](#rescue_orphan_detection_filespy) | `scripts/` | 孤立検出ファイルの救済 | ○ | `--apply` 時のみ JSONL 追記 | デフォルト dry-run |
| [import_from_other_system.py](#import_from_other_systempy) | `scripts/` | 別マシンの `detections/` を取り込む | ○ | `--apply` 時のみコピー + SQLite 同期 | デフォルト dry-run |
| [merge_detection_directories.py](#merge_detection_directoriespy) | `scripts/` | 2 つの検出ディレクトリを統合 | ○ | `--apply` 時のみ移動 + JSONL 更新 | デフォルト dry-run |
| [transfer_detections.py](#transfer_detectionspy) | `scripts/` | ZIP エクスポート/インポート（TUI） | ○ | import 側は `--apply` 指定時のみ副作用 | export は読み取りのみ / import はデフォルト dry-run |
| [dump_detections_db.py](#dump_detections_dbpy) | `scripts/` | SQLite 内容を table / JSON / CSV でダンプ | ○（読み取り専用） | なし | - |

---

## migrate_jsonl_to_sqlite.py

**配置**: `scripts/migrate_jsonl_to_sqlite.py`

**目的**: v3.6.0 で導入された SQLite ストアへ、既存の `detections.jsonl` と `detection_labels.json` を初回取り込みする。

**動作**:

- `DETECTIONS_DIR` 環境変数（未設定時はカレントの `detections/`）の各カメラディレクトリを走査
- 各カメラの JSONL を `INSERT OR IGNORE` で SQLite に取り込む
- 別ファイルの `detection_labels.json` があれば対応する検出にラベルを反映
- JSONL は**削除されない**（ロールバックソースとして保持）

**冪等性**: ○ — `INSERT OR IGNORE` によりID衝突時は無視するため、何度でも再実行できる。

**実行例**:

```bash
# ホスト（venv）上から実行
source .venv/bin/activate
python scripts/migrate_jsonl_to_sqlite.py

# コンテナ内から実行する場合
docker compose run --rm camera1 python scripts/migrate_jsonl_to_sqlite.py
```

**参照**: [DETECTION_STORE.md](DETECTION_STORE.md) - スキーマと同期アルゴリズムの詳細

---

## migrate_camera_dirs.py

**配置**: プロジェクトルート（`migrate_camera_dirs.py`）

**目的**: v3.11.0 で導入された `CAMERA{i}_NAME = camera{i}` 固定化に合わせ、旧 IP 含みディレクトリ（例: `camera1_10_0_1_25/`）を `camera1/` に統合する。SQLite の `camera` 列と各パス列も同時に更新する。

**主な引数**:

| 引数 | デフォルト | 説明 |
|---|---|---|
| `--detections-dir` | `detections` | 対象の検出ルートディレクトリ |
| `--dry-run` | オフ | 操作内容を表示するだけで実行しない |
| `--yes` | オフ | 対話確認プロンプトを省略 |

**動作**:

1. `camera{i}_` で始まるディレクトリを検索
2. メディアファイル（`.mp4` / `.jpg` / `.png`）を `Path.rename` で `camera{i}/` へ移動（同名衝突時は `_1`, `_2`, ... のサフィックス）
3. `detections.jsonl` をマージ追記（バイナリ単位）
4. `detections.db` を `detections.db.bak_<timestamp>` として**自動バックアップ**してから `camera` 列および `clip_path` / `image_path` / `composite_original_path` / `alternate_clip_paths` を `replace()` で更新
5. 元ディレクトリを `camera{i}_*.migrated_<timestamp>/` にリネームして残置

**冪等性**: ○ — 既に移行済みのディレクトリは対象外、`_unique_path()` で同名衝突を回避。

**実行例**:

```bash
# 必ず dry-run で内容確認
python migrate_camera_dirs.py --dry-run

# 本実行（対話確認あり）
python migrate_camera_dirs.py

# 非対話
python migrate_camera_dirs.py --yes

# 別パス指定
python migrate_camera_dirs.py --detections-dir /mnt/vol/detections
```

**参照**: [OPERATIONS_GUIDE.md](OPERATIONS_GUIDE.md#v3110--カメラ名インデックス化アップデート)、[SECURITY.md](SECURITY.md#カメラ名マイグレーションスクリプトv3110)

---

## migrate_detection_ids.py

**配置**: `scripts/migrate_detection_ids.py`

**目的**: 検出 ID 命名規則（`det_` + `timestamp` / `start_time` / `end_time` / `start_point` / `end_point` の SHA-1 ダイジェスト先頭20桁）を統一適用する。古い形式で ID が付与されていないレコードに再発番・付与する。

**主な引数**:

| 引数 | 説明 |
|---|---|
| `--detections-dir` | 対象の検出ディレクトリ |
| `--apply` | 指定時のみ JSONL を書き換え |

**動作**:

- 各カメラの `detections.jsonl` を読み、`id` / `base_name` が欠落している場合に補完
- `clip_path` / `image_path` / `composite_original_path` も標準命名（`<base>.mp4` / `<base>_composite.jpg` など）に合わせて埋める
- 書き戻しは tmpfile 経由で原子的に実行

**冪等性**: ○ — 既に正規化済みレコードは変更されない。

**実行例**:

```bash
# ドライラン（差分表示のみ）
python scripts/migrate_detection_ids.py

# 本実行
python scripts/migrate_detection_ids.py --apply
```

---

## rescue_orphan_detection_files.py

**配置**: `scripts/rescue_orphan_detection_files.py`

**目的**: カメラディレクトリに動画・画像ファイルが残っているのに `detections.jsonl` に該当レコードがない「孤立ファイル」を検出し、JSONL に再登録する。

**主な引数**:

| 引数 | デフォルト | 説明 |
|---|---|---|
| `--detections-dir` | `detections` | 対象の検出ルート |
| `--apply` | オフ | 指定時のみ JSONL を更新 |

**動作**:

- ファイル名規則 `meteor_YYYYMMDD_HHMMSS(_SUFFIX)?.(mp4|mov|_composite.jpg|_composite_original.jpg)` を正規表現マッチ
- 対応する JSONL レコードが無い場合、タイムスタンプと確認できる情報から最小構成のレコードを再構築
- `id` は `make_detection_id()` で生成

**冪等性**: ○ — 既に JSONL に載っているファイルは対象外。

**実行例**:

```bash
# まず dry-run で何件救済されるか確認
python scripts/rescue_orphan_detection_files.py

# 実際に JSONL へ追記
python scripts/rescue_orphan_detection_files.py --apply
```

**その後**: JSONL を書き換えたため、ダッシュボードの次回起動時に `sync_camera_from_jsonl` が新規行を SQLite に取り込みます。

---

## import_from_other_system.py

**配置**: `scripts/import_from_other_system.py`

**目的**: 別サーバーで運用していた meteo の `detections/` ディレクトリを、現在のシステムに取り込む。sshfs マウント先や rsync コピー先を入力にする想定。

**主な引数**:

| 引数 | 説明 |
|---|---|
| `--source` / `-s` | 取り込み元の検出ルート（**必須**） |
| `--target` / `-t` | 取り込み先（デフォルト: `detections`） |
| `--camera-map` / `-m` | カメラ名マッピング `OLD:NEW`。複数指定可 |
| `--cameras` | ソース側で絞り込むカメラ名リスト |
| `--apply` | 指定時のみファイルコピー + SQLite 同期を実行 |

**動作**:

- ソースの各カメラ配下のメディア・JSONL を走査
- ファイルのコピーは**既存ファイル保持**（上書きしない）
- `--camera-map` で名前変換を適用後、ターゲット側 JSONL へマージ
- `--apply` 時に `detection_store.sync_camera_from_jsonl` で SQLite にも取り込み

**冪等性**: ○ — ファイルは上書きされず、JSONL は `INSERT OR IGNORE` 相当。

**実行例**:

```bash
# dry-run（何が起こるか確認）
python scripts/import_from_other_system.py --source /mnt/other/detections

# カメラ名マッピング（旧識別子 → v3.11 表記）
python scripts/import_from_other_system.py \
    --source /mnt/other/detections \
    --camera-map cam_south:camera2 \
    --apply
```

---

## merge_detection_directories.py

**配置**: `scripts/merge_detection_directories.py`

**目的**: 同じ `detections/` ツリー内の 2 つのカメラディレクトリを統合する。検出データを誤って別ディレクトリに書き出していた場合などに使用する。

**主な引数**:

| 引数 | デフォルト | 説明 |
|---|---|---|
| `--detections-dir` | `detections` | 検出ルート |
| `--source` / `--from` | `南側` | 統合元のサブディレクトリ名（現状コードのデフォルトは初期開発時のテスト値。運用では必ず明示指定する） |
| `--target` / `--to` | `camera2_10_0_1_3` | 統合先のサブディレクトリ名（同上の理由で運用時は必ず明示指定する） |
| `--apply` | オフ | 指定時のみ実際に書き込み |
| `--cleanup-source` | オフ | マージ完了後、空になった元ファイルを削除 |

!!! warning "`--source` / `--target` のデフォルト値について"
    両デフォルトは初期開発時の検証用の値です（`scripts/merge_detection_directories.py:12` の `SKIP_DIRS` と合わせて）。運用で使用する際は必ず `--source` / `--target` を明示し、デフォルト値に依存しないでください。

**動作**:

- ソースのメディアファイルをターゲットへ移動（`SKIP_DIRS = {"masks", "runtime_settings"}` / `SKIP_FILES = {"detections.jsonl", ".DS_Store"}`（コード上の定数）を除外）
- 両者の `detections.jsonl` をマージして timestamp + id でソート、重複行を除去して書き戻し
- `--cleanup-source` 指定時は空のソースファイル・ディレクトリを削除

**冪等性**: ○ — `--apply` を付けない限り副作用なし。

**実行例**:

```bash
# dry-run
python scripts/merge_detection_directories.py --from south_tmp --to camera2

# 本実行
python scripts/merge_detection_directories.py --from south_tmp --to camera2 --apply
```

---

## transfer_detections.py

**配置**: `scripts/transfer_detections.py`

**目的**: 検出データを別マシンへ ZIP で転送する TUI ベースのインタラクティブツール。`export` と `import` のサブコマンドを持つ。

### export サブコマンド

**主な引数**:

| 引数 | 説明 |
|---|---|
| `--scp <user@host:path>` | ZIP 作成後に scp で転送 |
| `--camera <name>` | カメラ絞り込み（TUI でも選択可） |

**動作**: curses 製の TUI でカメラ・期間・ラベルを絞り込み、選択したレコードのメディア + JSONL を ZIP に固める。

**TUI キー操作**:

- `j` / `k`: カーソル上下移動
- `Space`: 現在のレコードの選択/選択解除
- `f`: フィルター（カメラ・期間・ラベル）
- `e`: エクスポート実行
- `q`: キャンセル

**副作用**: ZIP ファイル作成のみ（既存ファイルは読み取り専用）。

### import サブコマンド

**主な引数**:

| 引数 | 説明 |
|---|---|
| `ZIP_OR_DIR`（位置） | 取り込み元 ZIP ファイルまたはディレクトリ |
| `--apply` | 指定時のみファイル展開 + JSONL マージ + SQLite 同期 |
| `--camera-map OLD:NEW` | カメラ名マッピング |

**動作**: ZIP を一時ディレクトリに展開し、`import_from_other_system.py` と同じロジックで取り込む。

**冪等性**: ○（import は `INSERT OR IGNORE`、既存ファイルは保持）

**実行例**:

```bash
# 別マシンでエクスポート（TUI）
python scripts/transfer_detections.py export --scp user@host:~/meteo-transfer/

# 受信側でインポート（dry-run）
python scripts/transfer_detections.py import transfer_20260413.zip

# 本実行
python scripts/transfer_detections.py import transfer_20260413.zip --apply
```

---

## dump_detections_db.py

**配置**: `scripts/dump_detections_db.py`

**目的**: `detections.db`（SQLite）の内容を読み取り、人が確認しやすい table / JSON / CSV 形式で出力する。

**主な引数**:

| 引数 | デフォルト | 説明 |
|---|---|---|
| `--db PATH` | `detections/detections.db` | DB ファイルパス |
| `--camera CAMERA` | 全カメラ | 特定カメラのみ |
| `--deleted` | オフ | 論理削除済みレコードも含める |
| `--limit N` | 全件 | 最新 N 件のみ |
| `--table {detections,sync,all}` | `detections` | ダンプ対象テーブル |
| `--format {table,json,csv}` | `table` | 出力フォーマット |

**副作用**: なし（読み取り専用）

**実行例**:

```bash
# 全カメラ最新状態を表形式で
python scripts/dump_detections_db.py

# 特定カメラ最新 20 件を JSON で
python scripts/dump_detections_db.py --camera camera1 --limit 20 --format json

# sync state を確認
python scripts/dump_detections_db.py --table sync

# CSV 出力してスプレッドシートへ
python scripts/dump_detections_db.py --format csv > detections.csv
```

---

## Docker コンテナ内での実行

スクリプトはホストの venv でも Docker コンテナ内でも実行できます。DB パスの違いに注意してください。

```bash
# ホスト側実行（venv）
source .venv/bin/activate
python scripts/migrate_jsonl_to_sqlite.py

# Docker コンテナ内実行（DETECTIONS_DIR は /output になる）
docker compose run --rm camera1 python scripts/migrate_jsonl_to_sqlite.py
docker compose run --rm dashboard python scripts/dump_detections_db.py --db /output/detections.db

# migrate_camera_dirs.py はプロジェクトルートにあるため、コンテナ内では
# ワーキングディレクトリを合わせる必要がある
docker compose run --rm camera1 python /app/migrate_camera_dirs.py --dry-run
```

`docker compose run` は使い捨てコンテナで実行するため、他の動作中コンテナの状態を変えません。ただし SQLite への書き込みを伴うスクリプトは、動作中のダッシュボードと競合すると SQLite のロック/DB ファイル破損リスクがあるため、事前に `./meteor-docker.sh stop` で**必須**で停止してください。

---

## 関連ドキュメント

- [DETECTION_STORE.md](DETECTION_STORE.md) - SQLite スキーマと `detection_store` API
- [OPERATIONS_GUIDE.md](OPERATIONS_GUIDE.md) - アップデート時のマイグレーション手順
- [SECURITY.md](SECURITY.md) - マイグレーションスクリプトの安全機構
