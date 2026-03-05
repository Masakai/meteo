#!/bin/bash

# 流星検出システム インストールスクリプト (macOS)
# Copyright (c) 2026 Masanori Sakai
# All rights reserved.

set -e

# カラー出力
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# ロゴ表示
echo -e "${BLUE}"
echo "=================================================="
echo "   流星検出システム インストーラ for macOS"
echo "=================================================="
echo -e "${NC}"

# 前提条件チェック
echo -e "${YELLOW}[1/6] 前提条件を確認中...${NC}"

# Docker Desktop チェック
if ! command -v docker &> /dev/null; then
    echo -e "${RED}エラー: Docker が見つかりません${NC}"
    echo "Docker Desktop をインストールしてください:"
    echo "https://www.docker.com/products/docker-desktop"
    exit 1
fi

if ! docker info &> /dev/null; then
    echo -e "${RED}エラー: Docker Desktop が起動していません${NC}"
    echo "Docker Desktop を起動してから再度実行してください"
    exit 1
fi

echo -e "${GREEN}✓ Docker Desktop が利用可能です${NC}"

# Python3 チェック
if ! command -v python3 &> /dev/null; then
    echo -e "${RED}エラー: Python 3 が見つかりません${NC}"
    echo "Python 3 をインストールしてください:"
    echo "https://www.python.org/downloads/"
    exit 1
fi

PYTHON_VERSION=$(python3 --version | cut -d' ' -f2)
echo -e "${GREEN}✓ Python ${PYTHON_VERSION} が利用可能です${NC}"

# インストール先ディレクトリ
INSTALL_DIR="$HOME/meteor-detector"

# 既存ディレクトリチェック
if [ -d "$INSTALL_DIR" ]; then
    echo -e "${YELLOW}警告: $INSTALL_DIR は既に存在します${NC}"
    read -p "上書きしますか? (y/N): " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo "インストールを中止しました"
        exit 1
    fi
    rm -rf "$INSTALL_DIR"
fi

# リポジトリのクローン
echo -e "${YELLOW}[2/6] リポジトリをクローン中...${NC}"
# 現在のディレクトリをコピー（開発中の動作確認用）
# 実際のGitHubからのインストール時は以下のようにする:
# git clone https://github.com/your-username/meteor-detector.git "$INSTALL_DIR"
mkdir -p "$INSTALL_DIR"
cp -r "$(pwd)"/* "$INSTALL_DIR/"
cd "$INSTALL_DIR"
echo -e "${GREEN}✓ リポジトリをコピーしました${NC}"

# Python仮想環境のセットアップ
echo -e "${YELLOW}[3/6] Python仮想環境をセットアップ中...${NC}"
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip > /dev/null 2>&1
pip install -r requirements.txt > /dev/null 2>&1
echo -e "${GREEN}✓ Python仮想環境を作成しました${NC}"

# カメラ設定の対話的入力
echo -e "${YELLOW}[4/6] カメラ設定を行います${NC}"
echo ""

# 位置情報の入力
echo "観測地点の情報を入力してください:"
read -p "緯度 (例: 35.0000): " LATITUDE
read -p "経度 (例: 139.0000): " LONGITUDE
read -p "タイムゾーン (デフォルト: Asia/Tokyo): " TIMEZONE
TIMEZONE=${TIMEZONE:-Asia/Tokyo}

# カメラ台数の入力
read -p "カメラの台数 (1-10): " CAMERA_COUNT

if ! [[ "$CAMERA_COUNT" =~ ^[0-9]+$ ]] || [ "$CAMERA_COUNT" -lt 1 ] || [ "$CAMERA_COUNT" -gt 10 ]; then
    echo -e "${RED}エラー: カメラ台数は 1-10 の範囲で指定してください${NC}"
    exit 1
fi

echo ""
echo -e "${BLUE}各カメラの情報を入力してください${NC}"
echo ""

# docker-compose.yml の生成開始
cat > docker-compose.yml << 'EOF'
# 流星検出 Docker Compose設定
# インストーラにより自動生成

services:
  # ダッシュボード（全カメラ一覧）
  dashboard:
    build:
      context: .
      dockerfile: Dockerfile.dashboard
    container_name: meteor-dashboard
    restart: unless-stopped
    environment:
      - TZ=Asia/Tokyo
      - PORT=8080
EOF

# LATITUDEとLONGITUDEを追記
echo "      - LATITUDE=$LATITUDE" >> docker-compose.yml
echo "      - LONGITUDE=$LONGITUDE" >> docker-compose.yml
echo "      - TIMEZONE=$TIMEZONE" >> docker-compose.yml
echo "      - ENABLE_TIME_WINDOW=true" >> docker-compose.yml

# 各カメラの情報を入力
declare -a CAMERA_NAMES
declare -a CAMERA_DISPLAYS
declare -a RTSP_URLS

for i in $(seq 1 $CAMERA_COUNT); do
    echo -e "${BLUE}--- カメラ $i ---${NC}"
    read -p "カメラ名 (英数字、例: camera$i): " CAMERA_NAME
    CAMERA_NAME=${CAMERA_NAME:-camera$i}
    read -p "表示名 (日本語可、例: カメラ$i): " CAMERA_DISPLAY
    CAMERA_DISPLAY=${CAMERA_DISPLAY:-カメラ$i}
    read -p "RTSP URL (例: rtsp://user:pass@192.168.1.100/live): " RTSP_URL

    CAMERA_NAMES+=("$CAMERA_NAME")
    CAMERA_DISPLAYS+=("$CAMERA_DISPLAY")
    RTSP_URLS+=("$RTSP_URL")

    PORT=$((8080 + i))

    # dashboardの環境変数に追加
    echo "      - CAMERA${i}_NAME=$CAMERA_NAME" >> docker-compose.yml
    echo "      - CAMERA${i}_NAME_DISPLAY=$CAMERA_DISPLAY" >> docker-compose.yml
    echo "      - CAMERA${i}_URL=http://localhost:$PORT" >> docker-compose.yml

    echo ""
done

# dashboardのports, volumes, networksを追記
cat >> docker-compose.yml << 'EOF'
    ports:
      - "8080:8080"
    volumes:
      - ./detections:/output
    networks:
      - meteor-net
    depends_on:
EOF

# depends_onにカメラを追加
for i in $(seq 1 $CAMERA_COUNT); do
    echo "      - ${CAMERA_NAMES[$((i-1))]}" >> docker-compose.yml
done

echo "" >> docker-compose.yml

# 各カメラサービスを生成
for i in $(seq 1 $CAMERA_COUNT); do
    CAMERA_NAME=${CAMERA_NAMES[$((i-1))]}
    CAMERA_DISPLAY=${CAMERA_DISPLAYS[$((i-1))]}
    RTSP_URL=${RTSP_URLS[$((i-1))]}
    PORT=$((8080 + i))

    # マスク画像ファイルの確認
    MASK_IMAGE="masks/${CAMERA_NAME}_mask.png"
    if [ ! -f "$MASK_IMAGE" ]; then
        # マスク画像がない場合は作成
        mkdir -p masks
        touch "$MASK_IMAGE"
    fi

    cat >> docker-compose.yml << EOF

  # $CAMERA_DISPLAY
  $CAMERA_NAME:
    build:
      context: .
      args:
        MASK_IMAGE: $MASK_IMAGE
    container_name: meteor-$CAMERA_NAME
    restart: unless-stopped
    environment:
      - TZ=Asia/Tokyo
      - RTSP_URL=$RTSP_URL
      - CAMERA_NAME=$CAMERA_NAME
      - CAMERA_NAME_DISPLAY=$CAMERA_DISPLAY
      - SENSITIVITY=medium
      - SCALE=0.5
      - BUFFER=15
      - EXCLUDE_BOTTOM=0.0625
      - EXTRACT_CLIPS=true
      - LATITUDE=$LATITUDE
      - LONGITUDE=$LONGITUDE
      - TIMEZONE=$TIMEZONE
      - ENABLE_TIME_WINDOW=true
      - MASK_IMAGE=/app/mask_image.png
      - MASK_DILATE=20
      - MASK_SAVE=
      - FB_NORMALIZE=true
      - FB_DELETE_MOV=true
      - WEB_PORT=8080
    ports:
      - "$PORT:8080"
    volumes:
      - ./detections:/output
    networks:
      - meteor-net
    logging:
      driver: "json-file"
      options:
        max-size: "10m"
        max-file: "3"
EOF
done

# ネットワーク設定を追記
cat >> docker-compose.yml << 'EOF'

networks:
  meteor-net:
    driver: bridge
EOF

echo -e "${GREEN}✓ docker-compose.yml を生成しました${NC}"

# ディレクトリ作成
echo -e "${YELLOW}[5/6] 必要なディレクトリを作成中...${NC}"
mkdir -p detections masks
echo -e "${GREEN}✓ ディレクトリを作成しました${NC}"

# 完了メッセージ
echo ""
echo -e "${GREEN}=================================================="
echo "   インストールが完了しました！"
echo "==================================================${NC}"
echo ""
echo -e "${BLUE}インストール先:${NC} $INSTALL_DIR"
echo ""
echo -e "${BLUE}次のステップ:${NC}"
echo "  1. インストールディレクトリに移動:"
echo "     cd $INSTALL_DIR"
echo ""
echo "  2. (オプション) マスク画像を設定:"
echo "     masks/ ディレクトリにマスク画像を配置"
echo ""
echo "  3. システムを起動:"
echo "     docker compose up -d"
echo ""
echo "  4. ダッシュボードにアクセス:"
echo "     http://localhost:8080"
echo ""
for i in $(seq 1 $CAMERA_COUNT); do
    PORT=$((8080 + i))
    echo "  ${CAMERA_DISPLAYS[$((i-1))]}: http://localhost:$PORT"
done
echo ""
echo -e "${BLUE}停止するには:${NC}"
echo "  docker compose down"
echo ""
echo -e "${BLUE}ログを確認するには:${NC}"
echo "  docker compose logs -f"
echo ""
echo -e "${YELLOW}注意: 初回起動時はDockerイメージのビルドに時間がかかります${NC}"
echo ""
