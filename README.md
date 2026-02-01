# 流星検出システム (Meteor Detection System)

リアルタイムで流星を検出し、記録するシステムです。MP4動画とRTSPストリームの両方に対応しています。

![ダッシュボード](dashboard.png)

## 主な機能

- **MP4動画からの流星検出** - 録画した動画ファイルから流星を検出
- **RTSPストリームのリアルタイム検出** - ライブカメラストリームから流星を自動検出
- **Webプレビュー** - ブラウザで検出状況をリアルタイム確認
- **ダッシュボード** - 複数カメラの検出状況を一画面で表示
- **Docker対応** - 複数カメラを並列監視可能

## ファイル構成

```
.
├── meteor_detector.py              # MP4動画からの流星検出
├── meteor_detector_rtsp.py         # RTSPストリームのリアルタイム検出（CLI版）
├── meteor_detector_rtsp_web.py     # RTSPストリームのリアルタイム検出（Webプレビュー付き）
├── dashboard.py                    # 複数カメラのダッシュボード
├── generate_compose.py             # streamersからdocker-compose.ymlを自動生成
├── streamers                       # RTSPカメラURL一覧
├── docker-compose.yml              # Docker Compose設定
├── Dockerfile                      # 検出コンテナ用Dockerfile
├── Dockerfile.dashboard            # ダッシュボード用Dockerfile
├── meteor-docker.sh                # Docker管理スクリプト
├── requirements.txt                # Python依存ライブラリ
├── requirements-docker.txt         # Docker用依存ライブラリ
└── README.md                       # このファイル
```

## インストール

### 必要な環境

- Python 3.11以上
- OpenCV 4.5以上
- NumPy 1.20以上

### セットアップ

```bash
# 仮想環境の作成（推奨）
python -m venv .venv
source .venv/bin/activate  # macOS/Linux
# .venv\Scripts\activate   # Windows

# 依存ライブラリのインストール
pip install opencv-python numpy

# Dockerを使う場合は不要です
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

# 検出感度を調整
python meteor_detector.py input.mp4 --sensitivity high

# 火球検出モード（長時間・長距離・明るい流星）
python meteor_detector.py input.mp4 --sensitivity fireball
```

#### 検出感度プリセット

- `low` - 誤検出を減らす（明るい流星のみ）
- `medium` - バランス（デフォルト）
- `high` - 暗い流星も検出
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

#### オプション

```bash
python meteor_detector_rtsp_web.py \
  rtsp://192.168.1.100:554/stream \
  --output ./detections \
  --sensitivity medium \
  --scale 0.5 \
  --buffer 15 \
  --web-port 8080 \
  --camera-name "camera1"
```

### 3. Docker Composeで複数カメラを監視

#### streamersファイルの設定

`streamers` ファイルにRTSP URLを1行1カメラで記載：

```
# コメント行（#で始まる）
rtsp://user:pass@10.0.1.25/live
rtsp://user:pass@10.0.1.3/live
rtsp://user:pass@10.0.1.11/live
```

#### docker-compose.ymlの自動生成

```bash
# streamersファイルからdocker-compose.ymlを生成
python generate_compose.py

# オプション指定
python generate_compose.py --sensitivity fireball  # 火球検出モード
python generate_compose.py --scale 0.25            # 処理解像度を1/4に
python generate_compose.py --base-port 9080        # ポート番号を変更
```

#### 起動と管理

```bash
# ビルド＆起動
docker compose build
docker compose up -d

# 管理スクリプトを使う場合
./meteor-docker.sh start      # 起動
./meteor-docker.sh stop       # 停止
./meteor-docker.sh status     # 状態確認（検出件数も表示）
./meteor-docker.sh logs       # ログ確認
./meteor-docker.sh logs camera1  # 特定カメラのログ
./meteor-docker.sh restart    # 再起動
./meteor-docker.sh build      # 再ビルド
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
├── meteor_20240101_123456.mp4              # 流星イベントの動画クリップ
├── meteor_20240101_123456_composite.jpg    # 比較明合成（マーク付き）
├── meteor_20240101_123456_composite_original.jpg
└── detections.jsonl                        # 検出ログ（JSONL形式）
```

## 検出アルゴリズム

1. **フレーム差分** - 前フレームとの差分から移動物体を検出
2. **輝度フィルタ** - 明るい物体のみを抽出
3. **物体追跡** - 時間的に近い物体を追跡
4. **特徴判定** - 長さ、速度、直線性から流星を判定
5. **信頼度計算** - 各特徴をスコア化して総合信頼度を算出

## トラブルシューティング

### 誤検出が多い場合

- `--sensitivity low` で感度を下げる
- `--min-brightness` を上げる（デフォルト200）
- `--exclude-bottom` を増やして除外範囲を広げる

### 流星を見逃す場合

- `--sensitivity high` で感度を上げる
- `--min-brightness` を下げる（180など）
- `--min-speed` を下げる（3.0など）

### 処理が遅い場合

- `--fast` で高速モードを使う
- `--scale 0.5` で処理解像度を下げる
- `--skip 2` でフレームスキップを増やす

### RTSPストリームに接続できない場合

- RTSP URLが正しいか確認
- ネットワーク接続を確認
- カメラの認証情報が正しいか確認（`rtsp://user:pass@host:port/path`）

## Docker環境のカスタマイズ

`docker-compose.yml` で各カメラの設定を変更できます：

```yaml
camera1:
  environment:
    - RTSP_URL=rtsp://user:pass@10.0.1.25/live
    - CAMERA_NAME=camera1_10.0.1.25
    - SENSITIVITY=medium        # low/medium/high/fireball
    - SCALE=0.5                 # 処理解像度スケール
    - BUFFER=15                 # バッファ秒数
    - EXCLUDE_BOTTOM=0.0625     # 下部除外範囲（1/16）
    - WEB_PORT=8080
  ports:
    - "8081:8080"               # ホスト:コンテナ
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

- 2024-02-01: RTSP検出、Webプレビュー、Dockerサポート追加
- 2024-01-31: MP4動画検出、火球モード、高速化オプション追加
