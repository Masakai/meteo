# Docker コンテナ構成ドキュメント

## システム概要

流星検出システムは、Docker Composeで管理される4つのコンテナで構成されています。

- **1つのダッシュボードコンテナ**: 全カメラの統合管理画面
- **3つの検出コンテナ**: 各カメラごとの流星検出エンジン

## コンテナ構成図

```mermaid
graph TB
    subgraph "ホストマシン"
        Detections["./detections/<br/>共有ボリューム"]

        subgraph "Docker Network: meteor-net (bridge)"
            Dashboard["dashboard<br/>meteor-dashboard<br/>:8080→8080"]
            Camera1["camera1<br/>meteor-camera1<br/>:8081→8080"]
            Camera2["camera2<br/>meteor-camera2<br/>:8082→8080"]
            Camera3["camera3<br/>meteor-camera3<br/>:8083→8080"]
        end

        Browser["ブラウザ<br/>localhost:8080"]
    end

    subgraph "外部ネットワーク"
        RTSP1["RTSP Camera<br/>10.0.1.25:554"]
        RTSP2["RTSP Camera<br/>10.0.1.3:554"]
        RTSP3["RTSP Camera<br/>10.0.1.11:554"]
    end

    Browser -->|"HTTP"| Dashboard
    Dashboard -->|"HTTP"| Camera1
    Dashboard -->|"HTTP"| Camera2
    Dashboard -->|"HTTP"| Camera3

    Camera1 -->|"RTSP"| RTSP1
    Camera2 -->|"RTSP"| RTSP2
    Camera3 -->|"RTSP"| RTSP3

    Dashboard -->|"読み込み"| Detections
    Camera1 -->|"書き込み"| Detections
    Camera2 -->|"書き込み"| Detections
    Camera3 -->|"書き込み"| Detections

    style Dashboard fill:#1e2a4a
    style Camera1 fill:#16213e
    style Camera2 fill:#16213e
    style Camera3 fill:#16213e
    style Detections fill:#2a3f6f
```

## コンテナ詳細

### 1. Dashboard コンテナ

**役割**: 全カメラの統合ダッシュボードを提供

```mermaid
graph LR
    subgraph "meteor-dashboard コンテナ"
        Dashboard["dashboard.py<br/>HTTPサーバー"]
        AstroUtils["astro_utils.py<br/>天文計算"]
        Files["/output/<br/>マウント"]
    end

    Dashboard --> AstroUtils
    Dashboard --> Files

    style Dashboard fill:#1e2a4a
```

#### コンテナ情報

| 項目 | 値 |
|-----|-----|
| **イメージ** | `Dockerfile.dashboard` (python:3.11-slim ベース) |
| **コンテナ名** | `meteor-dashboard` |
| **ポートマッピング** | `8080:8080` (ホスト:コンテナ) |
| **再起動ポリシー** | `unless-stopped` |
| **依存関係** | camera1, camera2, camera3 |
| **ボリューム** | `./detections:/output` (読み込み専用的使用) |
| **ネットワーク** | `meteor-net` (bridge) |

#### 環境変数

| 変数名 | デフォルト値 | 説明 |
|-------|------------|------|
| `TZ` | `Asia/Tokyo` | タイムゾーン |
| `PORT` | `8080` | HTTPサーバーポート |
| `LATITUDE` | `35.6762` | 観測地の緯度（東京） |
| `LONGITUDE` | `139.6503` | 観測地の経度（東京） |
| `TIMEZONE` | `Asia/Tokyo` | タイムゾーン名 |
| `ENABLE_TIME_WINDOW` | `true` | 天文薄暮時間帯制限 |
| `CAMERA1_NAME` | `camera1 (10.0.1.25)` | カメラ1の表示名 |
| `CAMERA1_URL` | `http://localhost:8081` | カメラ1のURL |
| `CAMERA2_NAME` | `camera2 (10.0.1.3)` | カメラ2の表示名 |
| `CAMERA2_URL` | `http://localhost:8082` | カメラ2のURL |
| `CAMERA3_NAME` | `camera3 (10.0.1.11)` | カメラ3の表示名 |
| `CAMERA3_URL` | `http://localhost:8083` | カメラ3のURL |

#### Dockerfile.dashboard

```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY dashboard.py .
COPY astro_utils.py .
RUN pip install --no-cache-dir astral
ENV TZ=Asia/Tokyo
EXPOSE 8080
CMD ["python", "dashboard.py"]
```

---

### 2. Camera コンテナ (×3)

**役割**: 個別カメラの流星検出とWebプレビュー提供

```mermaid
graph TB
    subgraph "meteor-camera1 コンテナ"
        Detector["meteor_detector_rtsp_web.py"]
        Astro["astro_utils.py"]
        Output["/output/camera1_10_0_1_25/"]

        subgraph "内部スレッド"
            RTSP["RTSPReader"]
            Detection["detection_thread_worker"]
            Web["MJPEGHandler"]
        end

        Detector --> RTSP
        Detector --> Detection
        Detector --> Web
        Detector --> Astro
        Detection --> Output
    end

    style Detector fill:#16213e
    style Output fill:#2a3f6f
```

#### コンテナ情報（camera1の例）

| 項目 | 値 |
|-----|-----|
| **イメージ** | `Dockerfile` (python:3.11-slim + OpenCV) |
| **コンテナ名** | `meteor-camera1` / `meteor-camera2` / `meteor-camera3` |
| **ポートマッピング** | `8081:8080` / `8082:8080` / `8083:8080` |
| **再起動ポリシー** | `unless-stopped` |
| **ボリューム** | `./detections:/output` (読み書き) |
| **ネットワーク** | `meteor-net` (bridge) |

#### 環境変数（camera1の例）

| 変数名 | 値 | 説明 |
|-------|-----|------|
| `TZ` | `Asia/Tokyo` | タイムゾーン |
| `RTSP_URL` | `rtsp://6199:4003@10.0.1.25/live` | RTSPストリームURL |
| `CAMERA_NAME` | `camera1_10_0_1_25` | カメラ識別名（ディレクトリ名） |
| `SENSITIVITY` | `medium` | 感度 (low/medium/high/fireball) |
| `SCALE` | `0.5` | 処理スケール (0.0-1.0) |
| `BUFFER` | `15` | リングバッファ秒数 |
| `EXCLUDE_BOTTOM` | `0.0625` | 画面下部除外率 (1/16) |
| `EXTRACT_CLIPS` | `true` | MP4クリップ保存の有効化 |
| `LATITUDE` | `35.6762` | 観測地の緯度 |
| `LONGITUDE` | `139.6503` | 観測地の経度 |
| `TIMEZONE` | `Asia/Tokyo` | タイムゾーン名 |
| `ENABLE_TIME_WINDOW` | `true` | 天文薄暮時間帯制限 |
| `WEB_PORT` | `8080` | 内部HTTPポート |

#### Dockerfile

```dockerfile
FROM python:3.11-slim
WORKDIR /app

# Python依存ライブラリ
COPY requirements-docker.txt .
RUN pip install --no-cache-dir -r requirements-docker.txt

# OpenCV用システムライブラリ
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        libxcb1 libglib2.0-0 libgomp1 && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# アプリケーションコード
COPY meteor_detector_rtsp_web.py .
COPY astro_utils.py .

# 出力ディレクトリ
RUN mkdir -p /output

# タイムゾーン設定
ENV TZ=Asia/Tokyo

EXPOSE 8080

CMD python meteor_detector_rtsp_web.py \
    "${RTSP_URL}" \
    -o "/output/${CAMERA_NAME}" \
    --sensitivity "${SENSITIVITY}" \
    --scale "${SCALE}" \
    --buffer "${BUFFER}" \
    --exclude-bottom "${EXCLUDE_BOTTOM}" \
    --web-port "${WEB_PORT}" \
    --camera-name "${CAMERA_NAME}"
```

---

## ネットワーク構成

### meteor-net (bridge)

Docker Composeで自動作成されるブリッジネットワーク

```mermaid
graph TB
    subgraph "Docker Network: meteor-net"
        subgraph "IPアドレス自動割り当て"
            Dashboard["dashboard<br/>172.x.x.2"]
            Camera1["camera1<br/>172.x.x.3"]
            Camera2["camera2<br/>172.x.x.4"]
            Camera3["camera3<br/>172.x.x.5"]
        end
    end

    Host["ホストマシン<br/>docker0インターフェース"]

    Dashboard -.->|"内部通信"| Camera1
    Dashboard -.->|"内部通信"| Camera2
    Dashboard -.->|"内部通信"| Camera3

    Host -->|"ポート転送"| Dashboard
    Host -->|"ポート転送"| Camera1
    Host -->|"ポート転送"| Camera2
    Host -->|"ポート転送"| Camera3

    style Dashboard fill:#1e2a4a
    style Camera1 fill:#16213e
    style Camera2 fill:#16213e
    style Camera3 fill:#16213e
```

#### ポートマッピング

| コンテナ | ホストポート | コンテナポート | プロトコル | 用途 |
|---------|------------|--------------|----------|------|
| dashboard | 8080 | 8080 | HTTP | ダッシュボードWeb UI |
| camera1 | 8081 | 8080 | HTTP | カメラ1プレビュー |
| camera2 | 8082 | 8080 | HTTP | カメラ2プレビュー |
| camera3 | 8083 | 8080 | HTTP | カメラ3プレビュー |

---

## ボリューム構成

### 共有ボリューム: ./detections

```mermaid
graph TB
    Host["ホストマシン<br/>./detections/"]

    subgraph "マウント (読み書き)"
        Camera1["/output/ in camera1"]
        Camera2["/output/ in camera2"]
        Camera3["/output/ in camera3"]
    end

    subgraph "マウント (読み込み)"
        Dashboard["/output/ in dashboard"]
    end

    Host --> Camera1
    Host --> Camera2
    Host --> Camera3
    Host --> Dashboard

    style Host fill:#2a3f6f
    style Camera1 fill:#16213e
    style Camera2 fill:#16213e
    style Camera3 fill:#16213e
    style Dashboard fill:#1e2a4a
```

### ディレクトリ構造

```
./detections/
  ├── camera1_10_0_1_25/
  │   ├── detections.jsonl
  │   ├── meteor_20260202_065533.mp4
  │   ├── meteor_20260202_065533_composite.jpg
  │   └── meteor_20260202_065533_composite_original.jpg
  ├── camera2_10_0_1_3/
  │   └── ...
  └── camera3_10_0_1_11/
      └── ...
```

#### ボリューム使用パターン

| コンテナ | パス | モード | 操作 |
|---------|------|--------|------|
| camera1 | `/output` | rw | 検出結果の書き込み |
| camera2 | `/output` | rw | 検出結果の書き込み |
| camera3 | `/output` | rw | 検出結果の書き込み |
| dashboard | `/output` | rw | 検出結果の読み込み、削除 |

---

## ロギング設定

各カメラコンテナのログローテーション設定:

```yaml
logging:
  driver: "json-file"
  options:
    max-size: "10m"     # ログファイル最大サイズ
    max-file: "3"       # 保持するログファイル数
```

**合計ログ容量**: 各カメラ 30MB (10MB × 3ファイル)

---

## 起動シーケンス

```mermaid
sequenceDiagram
    participant User
    participant DockerCompose
    participant Network
    participant Camera1
    participant Camera2
    participant Camera3
    participant Dashboard

    User->>DockerCompose: docker compose up -d

    DockerCompose->>Network: meteor-netを作成

    par コンテナ起動（並列）
        DockerCompose->>Camera1: コンテナ起動
        Camera1->>Camera1: meteor_detector_rtsp_web.py起動
        Camera1->>Camera1: RTSP接続開始

        DockerCompose->>Camera2: コンテナ起動
        Camera2->>Camera2: meteor_detector_rtsp_web.py起動
        Camera2->>Camera2: RTSP接続開始

        DockerCompose->>Camera3: コンテナ起動
        Camera3->>Camera3: meteor_detector_rtsp_web.py起動
        Camera3->>Camera3: RTSP接続開始
    end

    Note over Camera1,Camera3: depends_onによりカメラ起動完了を待つ

    DockerCompose->>Dashboard: コンテナ起動
    Dashboard->>Dashboard: dashboard.py起動
    Dashboard->>Dashboard: HTTPサーバー起動 (0.0.0.0:8080)

    Dashboard-->>User: http://localhost:8080/ アクセス可能
```

---

## 依存関係グラフ

```mermaid
graph TD
    Compose["docker-compose.yml"]

    Compose --> Dashboard
    Compose --> Camera1
    Compose --> Camera2
    Compose --> Camera3

    Dashboard -.->|"depends_on"| Camera1
    Dashboard -.->|"depends_on"| Camera2
    Dashboard -.->|"depends_on"| Camera3

    Camera1 --> Dockerfile
    Camera2 --> Dockerfile
    Camera3 --> Dockerfile
    Dashboard --> DockerfileDashboard["Dockerfile.dashboard"]

    Dockerfile --> Requirements["requirements-docker.txt"]

    style Compose fill:#1e2a4a
    style Dashboard fill:#16213e
    style Camera1 fill:#2a3f6f
    style Camera2 fill:#2a3f6f
    style Camera3 fill:#2a3f6f
```

---

## リソース要件

### メモリ使用量（推定値）

| コンテナ | ベースイメージ | アプリメモリ | 合計（推定） |
|---------|--------------|------------|-------------|
| dashboard | ~50MB | ~30MB | **~80MB** |
| camera1 | ~120MB | ~200MB (リングバッファ含む) | **~320MB** |
| camera2 | ~120MB | ~200MB | **~320MB** |
| camera3 | ~120MB | ~200MB | **~320MB** |
| **合計** | | | **~1040MB (約1GB)** |

### ディスク使用量

| 項目 | サイズ（推定） |
|-----|--------------|
| Dockerイメージ (dashboard) | ~200MB |
| Dockerイメージ (camera) × 3 | ~600MB |
| 検出結果 (1時間あたり) | ~100MB-1GB (検出数依存) |

### CPU使用率

- **camera1-3**: 各コンテナ 30-50% (1コア)
- **dashboard**: 5-10% (1コア)

---

## docker-compose.yml コマンド

### 基本操作

```bash
# 起動（バックグラウンド）
docker compose up -d

# 停止
docker compose down

# 再起動
docker compose restart

# ログ確認（全コンテナ）
docker compose logs -f

# 特定コンテナのログ
docker compose logs -f camera1

# 状態確認
docker compose ps

# リソース使用状況
docker stats
```

### イメージ管理

```bash
# イメージのビルド
docker compose build

# キャッシュなしでビルド
docker compose build --no-cache

# イメージ削除
docker compose down --rmi all

# 未使用イメージの削除
docker image prune -a
```

### コンテナ管理

```bash
# 特定コンテナの再起動
docker compose restart camera1

# 特定コンテナに入る
docker compose exec camera1 /bin/bash

# 特定コンテナを停止
docker compose stop camera1

# 特定コンテナを起動
docker compose start camera1
```

---

## トラブルシューティング

### コンテナが起動しない

```bash
# ログを確認
docker compose logs camera1

# コンテナの状態を確認
docker compose ps

# ネットワークを確認
docker network ls
docker network inspect meteor-net
```

### RTSP接続エラー

```bash
# カメラコンテナ内でRTSP接続をテスト
docker compose exec camera1 /bin/bash
# コンテナ内で
apt-get update && apt-get install -y ffmpeg
ffmpeg -i "${RTSP_URL}" -frames:v 1 test.jpg
```

### ディスク容量不足

```bash
# 検出結果のクリーンアップ
rm -rf ./detections/*/meteor_*.mp4  # MP4のみ削除

# Dockerのクリーンアップ
docker system prune -a --volumes
```

### ポート競合

```bash
# ポート使用状況を確認
lsof -i :8080
lsof -i :8081

# docker-compose.ymlのポート番号を変更
# ports:
#   - "18080:8080"  # ホストポートを変更
```

---

## セキュリティ考慮事項

### 1. RTSP認証情報

⚠️ **注意**: docker-compose.ymlにRTSP URLの認証情報が平文で含まれています

**推奨対策**:
```bash
# .envファイルを使用
echo 'RTSP_URL_CAMERA1=rtsp://user:pass@10.0.1.25/live' > .env
chmod 600 .env
```

docker-compose.ymlで参照:
```yaml
environment:
  - RTSP_URL=${RTSP_URL_CAMERA1}
```

### 2. ネットワークアクセス制限

```yaml
# 内部ネットワークのみ許可（外部アクセス不要な場合）
services:
  camera1:
    networks:
      meteor-net:
        internal: true  # 外部アクセス遮断
```

### 3. ファイルシステムパーミッション

```bash
# 検出結果ディレクトリの権限設定
chmod 755 ./detections
chown -R 1000:1000 ./detections  # コンテナ内のユーザーIDに合わせる
```

---

## カメラの追加・削除（スケーリング）

### generate_compose.py による自動生成

`docker-compose.yml`は`generate_compose.py`スクリプトで自動生成されます。

#### 処理フロー

```mermaid
flowchart LR
    Streamers["streamers ファイル<br/>RTSP URLリスト"]
    Script["generate_compose.py"]
    Compose["docker-compose.yml"]

    Streamers -->|"読み込み"| Script
    Script -->|"生成"| Compose

    style Script fill:#2a3f6f
    style Compose fill:#16213e
```

### カメラ追加手順

#### 1. streamers ファイルを編集

```bash
# streamers ファイルに新しいカメラのRTSP URLを追加
echo "rtsp://user:pass@10.0.1.20/live" >> streamers
```

streamers ファイル形式:
```
rtsp://username:password@192.168.1.100/live
rtsp://username:password@192.168.1.101/live
rtsp://username:password@192.168.1.102/live
# コメント行は無視されます
rtsp://192.168.1.103:554/stream  # 認証なしも可能
```

#### 2. docker-compose.yml を再生成

```bash
# 基本的な使い方
python generate_compose.py

# オプション指定
python generate_compose.py \
  --streamers streamers \
  --output docker-compose.yml \
  --sensitivity medium \
  --scale 0.5 \
  --buffer 15 \
  --base-port 8080 \
  --latitude 35.6762 \
  --longitude 139.6503 \
  --enable-time-window true
```

#### 3. コンテナを再起動

```bash
# イメージをビルド（初回のみ）
docker compose build

# コンテナを起動
docker compose up -d

# 新しいカメラが追加されたことを確認
docker compose ps
```

### generate_compose.py のオプション

| オプション | デフォルト値 | 説明 |
|-----------|------------|------|
| `-s, --streamers` | `streamers` | RTSP URLリストファイル |
| `-o, --output` | `docker-compose.yml` | 出力ファイル名 |
| `--sensitivity` | `medium` | 検出感度 (low/medium/high/fireball) |
| `--scale` | `0.5` | 処理スケール (0.0-1.0) |
| `--buffer` | `15` | リングバッファ秒数 |
| `--exclude-bottom` | `0.0625` | 画面下部除外率 (1/16) |
| `--extract-clips` | `true` | MP4クリップ保存 |
| `--base-port` | `8080` | ベースポート番号 |
| `--latitude` | `35.3606` | 観測地の緯度（富士山頂） |
| `--longitude` | `138.7274` | 観測地の経度（富士山頂） |
| `--enable-time-window` | `false` | 天文薄暮時間帯制限 |

### 自動生成される構成

```mermaid
sequenceDiagram
    participant User
    participant Script as generate_compose.py
    participant Streamers as streamers
    participant Compose as docker-compose.yml

    User->>Script: python generate_compose.py
    Script->>Streamers: ファイル読み込み
    Streamers-->>Script: RTSP URLリスト (N行)

    loop 各RTSP URL
        Script->>Script: parse_rtsp_url()<br/>URL解析
        Script->>Script: generate_service()<br/>サービス定義生成
    end

    Script->>Script: generate_dashboard()<br/>ダッシュボード生成
    Script->>Compose: docker-compose.yml出力

    Compose-->>User: 生成完了<br/>カメラ数: N<br/>ポート: 8080-808N
```

### 生成例

**入力 (streamers)**:
```
rtsp://6199:4003@10.0.1.25/live
rtsp://6199:4003@10.0.1.3/live
```

**出力 (docker-compose.yml)**:
- ダッシュボード: `localhost:8080`
- カメラ1 (10.0.1.25): `localhost:8081`
- カメラ2 (10.0.1.3): `localhost:8082`

### カメラ削除手順

#### 1. streamers から該当行を削除

```bash
# 例: 2行目のカメラを削除
sed -i '2d' streamers
```

#### 2. docker-compose.yml を再生成

```bash
python generate_compose.py
```

#### 3. 古いコンテナを停止して再起動

```bash
# 全コンテナを停止・削除
docker compose down

# 新しい構成で起動
docker compose up -d
```

### カメラ数の制限

**技術的制限**: なし（ホストマシンのリソース次第）

**推奨値**:
- **メモリ**: 1カメラあたり約320MB → 8GBメモリで約20カメラ
- **CPU**: 1カメラあたり1コア30-50% → 4コアCPUで約8カメラ
- **ネットワーク**: 1カメラあたり約5-10Mbps → 100Mbpsで約10カメラ

---

## 関連ファイル

- `docker-compose.yml`: Docker Compose設定ファイル（自動生成）
- `Dockerfile`: カメラコンテナ用Dockerイメージ定義
- `Dockerfile.dashboard`: ダッシュボードコンテナ用Dockerイメージ定義
- `requirements-docker.txt`: Python依存パッケージ
- `generate_compose.py`: docker-compose.yml生成スクリプト
- `streamers`: RTSP URLリスト（カメラ設定ファイル）
- `streamers.sample`: streamersファイルのサンプル
