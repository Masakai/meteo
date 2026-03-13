# 流星検出システム (Meteor Detection System)

リアルタイムで流星を検出し、記録するシステムです。MP4 動画のオフライン解析、RTSP ストリームの常時監視、複数カメラ用ダッシュボードに対応しています。

## サンプル画面

### トップ画面

![トップ画面](documents/assets/dashboard-sample_1.png)

### カメラ画面

![カメラ画面](documents/assets/dashboard-sample_2.png)

### 設定画面

![設定画面](documents/assets/dashboard-sample_3.png)

## 主な機能

- **MP4動画の検出と再検証** - 単発の動画解析に加え、`--realtime` で RTSP Web 版と同じ検出ロジックでも再検証可能
- **RTSPストリームのリアルタイム検出** - ライブカメラを常時監視し、検出クリップ・比較明合成・JSON ログを保存
- **Webプレビューと単体カメラ操作** - `/stats`、スナップショット、マスク更新、再起動要求、検出状態確認に対応
- **複数カメラダッシュボード** - 検出一覧、カメラ一覧、全カメラ設定、CPU 使用率、検出時間帯表示を提供
- **検出ラベル管理** - 検出結果に `meteor` / `non_meteor` 系のラベルを付けて整理・一括削除可能
- **YouTubeアップロード** - ダッシュボードから検出クリップを YouTube に投稿可能
- **自動マスク生成** - 昼間画像から除外マスク、夜間画像からノイズ帯マスクを生成可能
- **Docker対応** - `streamers` から `docker-compose.yml` を生成し、複数カメラを並列監視可能

## 天文観測者向けの直感的な目安

このシステムの内部しきい値は `px`（ピクセル）と `px/s` で定義されていますが、
ATOM Cam 2 を **水平画角120度**、配信解像度を **1920x1080** として見ると、
次のように読み替えられます（現在の標準設定: `medium`）。

- 最小軌跡長 `20px` は、距離 `300km` の流星で **約6.5km** の見かけ移動に相当
- 最小速度 `50px/s` は、距離 `300km` の流星で **約16.4km/s** の見かけ速度に相当
- 距離 `100km` なら同じ条件は **約2.2km**、**約5.5km/s**

つまり直感的には、`medium` は「**数km以上の見かけ移動**」かつ「**数km/s以上の速い発光体**」を
主に検出する設定です。

補足:
- 流星までの距離は仰角で大きく変わるため、同じ `px` でも km換算値は変わります
- `SCALE=0.5` でも、検出座標は元解像度に戻して判定しているため、この換算で問題ありません

## ファイル構成

```
.
├── meteor_detector.py              # MP4動画からの流星検出
├── meteor_detector_rtsp.py         # RTSPストリームのリアルタイム検出（CLI版）
├── meteor_detector_rtsp_web.py     # RTSPストリームのリアルタイム検出（Webプレビュー付き）
├── meteor_detector_realtime.py     # RTSP検出の共通コンポーネント
├── meteor_detector_common.py       # 検出共通ユーティリティ
├── dashboard.py                    # 複数カメラのダッシュボード
├── dashboard_routes.py             # ダッシュボードAPI / カメラ中継 / YouTube連携
├── dashboard_templates.py          # ダッシュボードHTMLテンプレート
├── dashboard_config.py             # ダッシュボード設定
├── astro_utils.py                  # 日没・日出ベースの検出時間帯計算
├── generate_compose.py             # streamersからdocker-compose.ymlを自動生成
├── convert_detections_mp4_to_mov.py  # 検出クリップのMP4/MOV変換
├── authorize_youtube.py            # YouTube OAuth 認証
├── streamers.sample                # RTSPカメラURL一覧のサンプル
├── docker-compose.yml.sample       # Docker Compose設定のサンプル
├── Dockerfile                      # 検出コンテナ用Dockerfile
├── Dockerfile.dashboard            # ダッシュボード用Dockerfile
├── meteor-docker.sh                # Docker管理スクリプト
├── requirements.txt                # Python依存ライブラリ
├── requirements-docker.txt         # Docker用依存ライブラリ
├── documents/                      # 詳細ドキュメント
├── tests/                          # pytest ベースのテスト
└── README.md                       # このファイル
```

## インストール

### 必要な環境

- Python 3.11以上
- ffmpeg / ffprobe（クリップ変換や `fb_normalize` を使う場合）
- Docker / Docker Compose V2（複数カメラ監視を行う場合）

### セットアップ

```bash
# 仮想環境の作成（推奨）
python3 -m venv .venv
source .venv/bin/activate  # macOS/Linux
# .venv\Scripts\activate   # Windows

# 依存ライブラリのインストール
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

ローカルで Docker なしにダッシュボードを確認したい場合は、各カメラ側プロセスを起動したうえで次を実行します。

```bash
python dashboard.py
```

## 使い方

### 1. MP4動画から流星を検出

```bash
# 基本的な使い方
python meteor_detector.py input.mp4

# 出力動画を生成
python meteor_detector.py input.mp4 --output detected.mp4

# プレビュー表示しながら検出
python meteor_detector.py input.mp4 --preview

# 検出画像とJSONの出力先を変更
python meteor_detector.py input.mp4 --output-dir ./detections_from_file

# 検出感度を調整
python meteor_detector.py input.mp4 --sensitivity high

# 取りこぼし低減モード（短く暗い流星向け）
python meteor_detector.py input.mp4 --sensitivity faint

# 火球検出モード（長時間・長距離・明るい流星）
python meteor_detector.py input.mp4 --sensitivity fireball

# 画像保存やJSON出力を抑制
python meteor_detector.py input.mp4 --no-images --no-json
```

#### 検出感度プリセット

- `low` - 誤検出を減らす（明るい流星のみ）
- `medium` - バランス（デフォルト）
- `high` - 暗い流星も検出
- `faint` - 取りこぼし低減（短く暗い流星向け、誤検出は増えやすい）
- `fireball` - 火球検出（長時間・長距離・明滅対応）

#### 高速化オプション

```bash
# 高速モード（解像度半分 + 1フレームおき）
python meteor_detector.py input.mp4 --fast

# 処理解像度を半分に（約4倍速）
python meteor_detector.py input.mp4 --scale 0.5

# 1フレームおきに処理（約2倍速）
python meteor_detector.py input.mp4 --skip 2
```

### 2. RTSPストリームからリアルタイム検出

```bash
# RTSPストリームを監視（Webプレビュー付き）
python meteor_detector_rtsp_web.py rtsp://192.168.1.100:554/stream --web-port 8080

# ブラウザでプレビューを確認
# http://localhost:8080/
```

単体カメラの Web プレビューでは、マスクの表示/更新、スナップショット取得、再起動要求、ストリーム・検出・マスク状態の確認ができます。`/stats` では実効 FPS `runtime_fps`、検出時間帯状態、実行中設定も確認できます。

#### オプション

```bash
python meteor_detector_rtsp_web.py \
  rtsp://192.168.1.100:554/stream \
  --output ./detections \
  --sensitivity medium \
  --scale 0.5 \
  --buffer 15 \
  --web-port 8080 \
  --camera-name "camera1" \
  --mask-from-day ./camera1_day.jpg \
  --nuisance-from-night ./camera1_night.jpg \
  --extract-clips           # クリップ動画を保存（デフォルト）
```

RTSP Web版では `--buffer` は上限値として扱われ、検出前後1秒 + 最大検出時間（デフォルト12秒）に合わせて自動調整されます。

CLI だけで確認したい場合は、従来版の `meteor_detector_rtsp.py` も使えます。

```bash
python meteor_detector_rtsp.py rtsp://192.168.1.100:554/stream --preview
```

#### クリップ動画の保存

検出した流星のクリップ動画（MOV/H.264）を保存するかどうかを制御できます：

```bash
# クリップ動画を保存（デフォルト）
python meteor_detector_rtsp_web.py rtsp://... --extract-clips

# クリップ動画を保存しない（コンポジット画像のみ）
python meteor_detector_rtsp_web.py rtsp://... --no-clips
```

ストレージ容量を節約したい場合は `--no-clips` を使用してください。

#### ダッシュボードから全カメラ一括設定（再ビルド不要）

ダッシュボード上部の「全カメラ設定」から `/settings` を開くと、
複数カメラに対して設定を一括反映できます。

- `GET /settings`: 設定UIページ
- `GET /camera_settings/current`: 現在値を取得
- `POST /camera_settings/apply_all`: 全カメラへ一括適用

一括適用はカメラ側 `POST /apply_settings` を呼び出して反映します。

- 即時反映（再起動不要）:
  - `diff_threshold`, `min_brightness`, `min_linearity` など検出ロジックのしきい値
  - `nuisance_*`, `min_track_points`, `max_stationary_ratio` など誤検出抑制パラメータ
  - マスク更新系（`mask_dilate`, `nuisance_dilate`, `mask_*`/`nuisance_*` の画像パス）
- 自動再起動で反映（再ビルド不要）:
  - `sensitivity`, `scale`, `buffer`, `extract_clips`

起動時に効く設定は `output/runtime_settings/<camera>.json` に保存され、
コンテナ再起動後も維持されます。

#### ダッシュボードでできること

- `/` は検出一覧、`/cameras` は全カメラ一覧、`/settings` は全カメラ設定 UI
- 検出ラベル付け、`non_meteor` 系の一括削除、画像・動画の参照、検出件数取得
- ダッシュボード自身の CPU 使用率、各カメラの疎通、検出処理状態の監視
- `/changelog` で変更履歴の参照

#### 検出動画を YouTube にアップロード

ダッシュボードの検出一覧では、動画付きの検出に `YOUTUBE` ボタンが表示されます。
利用前に Google OAuth の準備が1回必要です。

```bash
source .venv/bin/activate
pip install -r requirements.txt
python authorize_youtube.py \
  --client-secrets ./client_secret.json \
  --token-file ./youtube_token.json
```

環境変数でダッシュボードへ設定します。

```bash
export YOUTUBE_CLIENT_SECRETS_FILE=./client_secret.json
export YOUTUBE_TOKEN_FILE=./youtube_token.json
export YOUTUBE_PRIVACY_STATUS=unlisted
export YOUTUBE_CATEGORY_ID=22
```

- `YOUTUBE_CLIENT_SECRETS_FILE`: Google Cloud で作成した OAuth クライアント JSON
- `YOUTUBE_TOKEN_FILE`: `authorize_youtube.py` が保存するトークン JSON
- `YOUTUBE_PRIVACY_STATUS`: `public` / `unlisted` / `private`
- `YOUTUBE_CATEGORY_ID`: YouTube 動画カテゴリ ID（既定値 `22`）

既存の `detections/` を `id` ベースへ移行し、整合性を確認するには次を実行します。

```bash
python scripts/migrate_detection_ids.py --detections-dir detections
python scripts/migrate_detection_ids.py --detections-dir detections --apply
```

### 3. Web版と同じ検出ロジックでファイル再検証

```bash
python meteor_detector.py input.mp4 --realtime
```

`--realtime` を付けると Web版と同じ検出ロジックを使って再検出します。
マスクを使う場合は `--mask-image` / `--mask-from-day` / `--mask-dilate` / `--mask-save` が利用できます。

### 4. 検出クリップの変換（MP4/MOV）

検出結果のクリップを一括変換したい場合は `convert_detections_mp4_to_mov.py` を使います。
`ffmpeg` が必要です。

```bash
# detections/ 配下の MP4 を MOV に変換
python convert_detections_mp4_to_mov.py --mov

# 出力先を指定（ディレクトリ構成は維持）
python convert_detections_mp4_to_mov.py --mov --output ./output

# 再エンコードせずにコンテナだけ変換
python convert_detections_mp4_to_mov.py --mov --copy

# 既存ファイルを上書き
python convert_detections_mp4_to_mov.py --mov --overwrite
```

### 5. Docker Composeで複数カメラを監視

#### streamersファイルの設定

`streamers` ファイルに 1 行 1 カメラで記載します。URL は必須で、2列目がマスク画像、3列目が表示名です。マスクなしで表示名だけ指定する場合は 2 列目を空にしてください。

```
# コメント行（#で始まる）
rtsp://user:pass@10.0.1.25/live
rtsp://user:pass@10.0.1.3/live||玄関カメラ
rtsp://user:pass@10.0.1.11/live|camera3.jpg|駐車場
```

書式は次の 4 パターンに対応しています。

- `URL`
- `URL|マスク画像`
- `URL||表示名`
- `URL|マスク画像|表示名`

**昼間画像による自動マスク（任意）**

RTSP URL の末尾に `| 昼間画像パス` または `| 昼間画像パス | 表示名` を付けると、`generate_compose.py` 実行時に
除外マスクを生成してコンテナに同梱します（他PCへの展開が簡単になります）。
なるべく雲のない青空の画像を使ってください。
マスクを使うと、木の枝や電柱・建物の輪郭、地上の常灯（街灯など）、車のヘッドライトの建物への反射による誤検出を軽減できます。

```
rtsp://user:pass@10.0.1.25/live | camera1.jpg
rtsp://user:pass@10.0.1.3/live  | camera2.jpg | 玄関カメラ
rtsp://user:pass@10.0.1.11/live
```

- 右側の画像は相対パスでOK（`streamers` と同じフォルダ基準）
- マスク生成には **OpenCV** が必要です（ローカル実行時）

#### docker-compose.ymlの自動生成

`generate_compose.py` は `streamers` ファイルから `docker-compose.yml` を自動生成するツールです。

```bash
# streamersファイルからdocker-compose.ymlを生成（基本）
python3 generate_compose.py

# 全オプション指定の例
python3 generate_compose.py \
  --sensitivity fireball \          # 火球検出モード
  --scale 0.5 \                     # 処理解像度スケール
  --buffer 15 \                     # バッファ秒数
  --exclude-bottom 0.0625 \         # 下部除外範囲
  --extract-clips true \            # クリップ動画保存
  --latitude 35.3606 \              # 観測地点の緯度（デフォルト: 富士山頂）
  --longitude 138.7274 \            # 観測地点の経度（デフォルト: 富士山頂）
  --enable-time-window true \       # 天文薄暮期間のみ検出
  --mask-output-dir masks \         # 生成マスクの保存先
  --base-port 8080                  # ベースポート番号
```

**補足**: `streamers` に `| 昼間画像パス` を付けた場合、`generate_compose.py` 実行時に
マスクを自動生成して `--mask-output-dir` に保存します。OpenCV が必要です。

#### 天文薄暮期間の検出制限

`--enable-time-window true` を指定すると、夜間ウィンドウのみ検出処理を実行します。
当日日没から翌日の日出までを検出時間帯として扱い、深夜から当日日出までは前日日没から当日日出のウィンドウを参照します。
それ以外の時間帯はストリーム表示のみで、検出処理は行いません。

```bash
# 東京の座標で天文薄暮期間のみ検出
python3 generate_compose.py \
  --latitude 35.6762 \
  --longitude 139.6503 \
  --enable-time-window true

# デフォルト（富士山頂）で天文薄暮期間のみ検出
python3 generate_compose.py --enable-time-window true
```

ダッシュボード（http://localhost:8080/）に検出時間帯が表示されます。
検出時間の計算には、サーバー設定（`LATITUDE` / `LONGITUDE`）の座標を使用します。

#### ダッシュボードのインディケータ仕様

カメラライブ画面の 3 つの主要インディケータは次の意味です。

- ストリーム接続: 緑は接続中、赤は切断または映像更新停止、灰は常時表示オフ
- カメラサーバ生存: 緑は `/stats` 応答あり、赤は応答なしまたは監視閾値超過、灰は判定保留や一時的な取得失敗
- 検出処理: 赤点滅は検出期間内で処理中、緑は検出期間外、黄は検出期間内だが停止疑い、灰は状態確認中

単体カメラ画面の `Detect` 表示は `/stats` の `detection_status` と対応しており、`DETECTING` / `OUT_OF_WINDOW` / `WAITING_FRAME` / `STREAM_LOST` を表示します。

#### 起動と管理（3つの方法）

Dockerシステムの起動・管理には3つの方法があります：

##### 1. meteor-docker.sh を使う（推奨）

最も簡単な方法です。日常的な操作はこのスクリプトを使用してください。

```bash
./meteor-docker.sh start      # 起動
./meteor-docker.sh stop       # 停止
./meteor-docker.sh status     # 状態確認（検出件数も表示）
./meteor-docker.sh logs       # ログ確認
./meteor-docker.sh logs camera1  # 特定カメラのログ
./meteor-docker.sh restart    # 再起動
./meteor-docker.sh build      # 再ビルド
./meteor-docker.sh rebuild    # ビルドして再起動
./meteor-docker.sh generate   # docker-compose.ymlを再生成
./meteor-docker.sh clean      # 古い検出結果を削除（7日以上前）
./meteor-docker.sh cleanup    # 未使用のDockerイメージ・コンテナを削除
```

`generate` コマンドはオプションも渡せます：

```bash
./meteor-docker.sh generate --enable-time-window true --latitude 35.6762 --longitude 139.6503
```

##### 2. docker compose コマンドを直接使う

より細かい制御が必要な場合や、Docker Composeの全機能を使いたい場合：

```bash
# ビルドと起動
docker compose build
docker compose up -d

# 個別サービスの操作
docker compose restart camera1        # camera1のみ再起動
docker compose logs -f dashboard      # ダッシュボードのログ
docker compose stop camera2           # camera2のみ停止

# 完全な停止とクリーンアップ
docker compose down                   # コンテナ削除
docker compose down -v                # ボリュームも削除
```

##### 3. generate_compose.py を直接使う

設定を変更して `docker-compose.yml` を再生成する場合：

```bash
# 設定を変更して再生成
python3 generate_compose.py --enable-time-window true --sensitivity fireball

# 再起動して反映
docker compose up -d
```

##### 使い分けのポイント

- **日常操作**: `meteor-docker.sh` を使用（簡潔で分かりやすい）
- **設定変更**: `generate_compose.py` または `meteor-docker.sh generate` で再生成
- **個別制御**: `docker compose` コマンドを直接使用
- **トラブル時**: `docker compose` でより詳細な情報を取得

**基本的には `meteor-docker.sh` だけで全ての操作が可能です。**

#### ディスク容量の管理

Dockerイメージは再ビルドの度に蓄積されるため、定期的なクリーンアップを推奨します。

```bash
# このプロジェクトの未使用イメージ・コンテナを削除
./meteor-docker.sh cleanup
```

**安全性の保証:**

`meteor-docker.sh`の全てのコマンドは**他のDockerプロジェクトに一切影響を与えません。**

- 全てのコマンドが`docker compose`経由で実行され、カレントディレクトリの`docker-compose.yml`のみを参照します
- `cleanup`コマンドは`docker compose config --images`で取得したイメージ名のみを処理対象とします
- グローバルなDockerコマンド（`docker system prune`等）は使用していません
- ファイル操作も全て`./detections`ディレクトリ内のみです

**注意事項:**
- `cleanup`コマンドは**このプロジェクトのみ**を対象とします
- `docker-compose.yml`で定義されているイメージ名のみを処理対象とします
- 現在使用中のイメージは削除されません
- `build`コマンド実行後に`cleanup`を実行することを推奨します

**全てのDockerリソースをクリーンアップしたい場合:**
```bash
# 警告: 他のプロジェクトにも影響します
docker system prune -a  # 全未使用リソースを削除
```

#### アクセス先

- **ダッシュボード（全カメラ一覧）**: http://localhost:8080/
- **カメラ1**: http://localhost:8081/
- **カメラ2**: http://localhost:8082/
- **カメラ3**: http://localhost:8083/

検出結果は `./detections/` に保存されます。

## 検出パラメータ

`meteor_detector.py` と `meteor_detector_rtsp_web.py` の両方で、以下のパラメータを調整可能です。

```python
@dataclass
class DetectionParams:
    diff_threshold: int = 30          # フレーム差分の閾値
    min_brightness: int = 200         # 最小輝度
    min_length: int = 20              # 最小長さ（ピクセル）
    max_length: int = 5000            # 最大長さ
    min_duration: int = 2             # 最小継続フレーム数
    max_duration: int = 300           # 最大継続フレーム数
    min_speed: float = 3.0            # 最小速度（ピクセル/フレーム）
    min_linearity: float = 0.7        # 最小直線性（0-1）
    min_area: int = 5                 # 最小面積
    max_area: int = 10000             # 最大面積
    exclude_bottom_ratio: float = 1/16  # 下部の除外範囲（0-1）
```

コマンドラインから一部パラメータを変更できます：

```bash
python meteor_detector.py input.mp4 \
  --diff-threshold 40 \
  --min-brightness 220 \
  --min-length 30 \
  --min-speed 8.0 \
  --exclude-bottom 0.1
```

## 出力ファイル

### MP4動画検出の場合

```
input_meteors/
├── meteor_001_frame012345.jpg              # 流星検出フレーム（マーク付き）
├── meteor_001_frame012345_original.jpg     # 元画像
├── meteor_001_composite.jpg                # 比較明合成（マーク付き）
├── meteor_001_composite_original.jpg       # 比較明合成（元画像）
├── meteor_002_frame023456.jpg
└── ...

input.meteors.json   # 検出結果のJSON
```

### RTSPストリーム検出の場合

```
detections/camera1/
├── meteor_20240101_123456.mp4              # 流星イベントの動画クリップ（fb_normalize 後の出力）
├── meteor_20240101_123456.mov              # 元クリップ（fb_delete_mov を使わない場合）
├── meteor_20240101_123456_composite.jpg    # 比較明合成（マーク付き）
├── meteor_20240101_123456_composite_original.jpg
└── detections.jsonl                        # 検出ログ（JSONL形式）

detections/
├── detection_labels.json                   # ダッシュボード上の検出ラベル
└── runtime_settings/
    └── camera1.json                        # ランタイム設定の永続化
```

`--extract-clips` 有効時はクリップ動画も保存されます。`--fb-normalize` を使うと H.264 / `avc1` の `.mp4` に正規化でき、`--fb-delete-mov` を併用すると元の `.mov` を削除します。`--no-clips` を指定した場合、クリップ動画は生成されません（コンポジット画像とログのみ）。

## 検出アルゴリズム

1. **マスク適用** - 除外マスクで木や建物などの固定物体を検出対象から外す
2. **フレーム差分** - 前フレームとの差分から移動物体を検出
3. **輝度フィルタ** - 明るい物体のみを抽出
4. **物体追跡** - 時間的に近い物体を追跡
5. **特徴判定** - 長さ、速度、直線性から流星を判定
6. **信頼度計算** - 各特徴をスコア化して総合信頼度を算出

## テスト

```bash
pytest -q
```

## トラブルシューティング

### 誤検出が多い場合

- `--sensitivity low` で感度を下げる
- `--min-brightness` を上げる（デフォルト200）
- `--exclude-bottom` を増やして除外範囲を広げる

### 流星を見逃す場合

- `--sensitivity high` で感度を上げる
- `--min-brightness` を下げる（180など）
- `--min-speed` を下げる（3.0など）
- 詳細は `documents/DETECTION_TUNING.md` を参照

### 処理が遅い場合

- `--fast` で高速モードを使う
- `--scale 0.5` で処理解像度を下げる
- `--skip 2` でフレームスキップを増やす

### RTSPストリームに接続できない場合

- RTSP URLが正しいか確認
- ネットワーク接続を確認
- カメラの認証情報が正しいか確認（`rtsp://user:pass@host:port/path`）

## Docker環境のカスタマイズ

### 推奨方法: generate_compose.py で設定

設定を変更する場合は、`generate_compose.py` で `docker-compose.yml` を再生成するのが推奨です：

```bash
python3 generate_compose.py \
  --sensitivity fireball \
  --scale 0.5 \
  --buffer 15 \
  --latitude 35.3606 \
  --longitude 138.7274 \
  --enable-time-window true
```

### 手動編集: docker-compose.yml を直接編集

各カメラの設定を個別に変更したい場合は、`docker-compose.yml` を直接編集できます：

```yaml
camera1:
  environment:
    - TZ=Asia/Tokyo
    - RTSP_URL=rtsp://user:pass@10.0.1.25/live
    - CAMERA_NAME=camera1_10.0.1.25
    - SENSITIVITY=medium        # low/medium/high/faint/fireball
    - SCALE=0.5                 # 処理解像度スケール
    - BUFFER=15                 # バッファ秒数
    - EXCLUDE_BOTTOM=0.0625     # 下部除外範囲（1/16）
    - EXTRACT_CLIPS=true        # クリップ動画を保存（true/false）
    - LATITUDE=35.3606          # 観測地点の緯度
    - LONGITUDE=138.7274        # 観測地点の経度
    - TIMEZONE=Asia/Tokyo       # タイムゾーン
    - ENABLE_TIME_WINDOW=false  # 天文薄暮期間制限（true/false）
    - WEB_PORT=8080
  ports:
    - "8081:8080"               # ホスト:コンテナ
```

**注意**: 手動編集した場合、次回 `generate_compose.py` を実行すると上書きされます。

## デプロイ（他のサーバーへの展開）

本システムを別のサーバーやマシンにデプロイする手順です。

### 前提条件

デプロイ先のサーバーに以下がインストールされている必要があります：

- Docker 20.10以上
- Docker Compose V2以上
- git（リポジトリからクローンする場合）

### デプロイ手順

#### 1. リポジトリのクローン

```bash
# サーバーにSSH接続
ssh user@server-ip

# リポジトリをクローン
git clone <repository-url> meteo
cd meteo
```

#### 2. streamersファイルの設定

```bash
# streamersファイルを作成・編集
vim streamers

# RTSP URLを1行1カメラで記載
# rtsp://user:pass@10.0.1.25/live
# rtsp://user:pass@10.0.1.3/live
# rtsp://user:pass@10.0.1.11/live

# 昼間画像による自動マスク（任意）
# rtsp://user:pass@10.0.1.25/live | camera1.jpg
```

#### 3. docker-compose.ymlの生成

```bash
# 基本設定で生成
python3 generate_compose.py

# または、カスタム設定で生成
python3 generate_compose.py \
  --sensitivity fireball \
  --scale 0.5 \
  --buffer 15 \
  --latitude 35.6762 \
  --longitude 139.6503 \
  --enable-time-window true \
  --base-port 8080
```

#### 4. Dockerイメージのビルドと起動

```bash
# イメージをビルド
docker compose build

# バックグラウンドで起動
docker compose up -d

# 状態確認
docker compose ps
```

#### 5. 動作確認

```bash
# ログを確認
docker compose logs -f

# ブラウザでアクセス
# http://server-ip:8080/  (ダッシュボード)
# http://server-ip:8081/  (カメラ1)
```

### ファイアウォール設定

外部からアクセスする場合、ファイアウォールでポートを開放する必要があります：

```bash
# UFWの場合
sudo ufw allow 8080/tcp  # ダッシュボード
sudo ufw allow 8081/tcp  # カメラ1
sudo ufw allow 8082/tcp  # カメラ2
sudo ufw allow 8083/tcp  # カメラ3

# firewalldの場合
sudo firewall-cmd --add-port=8080-8083/tcp --permanent
sudo firewall-cmd --reload
```

### systemdによる自動起動設定

サーバー再起動時に自動起動させる場合：

```bash
# systemdサービスファイルを作成
sudo vim /etc/systemd/system/meteor-detection.service
```

```ini
[Unit]
Description=Meteor Detection System
After=docker.service
Requires=docker.service

[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory=/path/to/meteo
ExecStart=/usr/bin/docker compose up -d
ExecStop=/usr/bin/docker compose down
User=your-user

[Install]
WantedBy=multi-user.target
```

```bash
# サービスを有効化
sudo systemctl enable meteor-detection.service
sudo systemctl start meteor-detection.service

# 状態確認
sudo systemctl status meteor-detection.service
```

### 既存環境からの移行

既存の環境からデプロイ先にデータを移行する場合：

```bash
# 移行元でバックアップを作成
tar -czf meteor-backup.tar.gz detections/ streamers docker-compose.yml

# デプロイ先にコピー
scp meteor-backup.tar.gz user@server-ip:/path/to/meteo/

# デプロイ先で展開
ssh user@server-ip
cd /path/to/meteo
tar -xzf meteor-backup.tar.gz

# システムを起動
docker compose up -d
```

### リバースプロキシの設定（Nginx）

HTTPSでアクセスさせたい場合や、ドメイン名でアクセスさせたい場合：

```nginx
# /etc/nginx/sites-available/meteor
server {
    listen 80;
    server_name meteor.example.com;

    location / {
        proxy_pass http://localhost:8080;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection 'upgrade';
        proxy_set_header Host $host;
        proxy_cache_bypass $http_upgrade;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

```bash
# 有効化
sudo ln -s /etc/nginx/sites-available/meteor /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx

# Let's EncryptでSSL化（オプション）
sudo certbot --nginx -d meteor.example.com
```

### デプロイ後のメンテナンス

```bash
# ログ確認
docker compose logs -f

# 状態確認
docker compose ps

# 再起動
docker compose restart

# 更新（新しいコードを取得）
git pull
docker compose build
docker compose up -d

# 古いファイルの削除
find ./detections -type f -mtime +7 -delete
```

## ライセンス

このプロジェクトはMITライセンスです。

## 開発者

- 流星検出アルゴリズム: OpenCVベースの差分検出+物体追跡
- Webプレビュー: MJPEGストリーミング
- Docker化: マルチコンテナ構成

## ライセンス

Copyright (c) 2026 Masanori Sakai
All rights reserved.

## 更新履歴

- 2024-02-02: --extract-clips / --no-clips オプション追加
- 2024-02-01: RTSP検出、Webプレビュー、Dockerサポート追加
- 2024-01-31: MP4動画検出、火球モード、高速化オプション追加
