#!/bin/bash
#
# 流星検出Docker管理スクリプト
#
# 使い方:
#   ./meteor-docker.sh start     # 起動
#   ./meteor-docker.sh stop      # 停止
#   ./meteor-docker.sh restart   # 再起動
#   ./meteor-docker.sh status    # 状態確認
#   ./meteor-docker.sh logs      # ログ表示
#   ./meteor-docker.sh logs camera1  # 特定カメラのログ
#   ./meteor-docker.sh build     # イメージ再ビルド
#   ./meteor-docker.sh generate  # docker-compose.yml再生成

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

# 色付き出力
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# コマンド
case "$1" in
    start)
        log_info "流星検出を起動中..."
        docker compose up -d
        log_info "起動完了"
        docker compose ps
        echo ""
        log_info "ログを確認: ./meteor-docker.sh logs"
        log_info "検出結果: ./detections/"
        ;;

    stop)
        log_info "流星検出を停止中..."
        docker compose down
        log_info "停止完了"
        ;;

    restart)
        log_info "流星検出を再起動中..."
        docker compose restart
        log_info "再起動完了"
        docker compose ps
        ;;

    status)
        echo "=== コンテナ状態 ==="
        docker compose ps
        echo ""
        echo "=== リソース使用状況 ==="
        docker stats --no-stream $(docker compose ps -q) 2>/dev/null || echo "コンテナが起動していません"
        echo ""
        echo "=== 検出結果 ==="
        if [ -d "./detections" ]; then
            for dir in ./detections/*/; do
                if [ -d "$dir" ]; then
                    camera=$(basename "$dir")
                    count=$(find "$dir" -name "*.mp4" 2>/dev/null | wc -l | tr -d ' ')
                    latest=$(ls -t "$dir"/*.mp4 2>/dev/null | head -1)
                    if [ -n "$latest" ]; then
                        latest_time=$(stat -f "%Sm" -t "%Y-%m-%d %H:%M" "$latest" 2>/dev/null || stat -c "%y" "$latest" 2>/dev/null | cut -d. -f1)
                        echo "  $camera: ${count}件 (最新: $latest_time)"
                    else
                        echo "  $camera: 0件"
                    fi
                fi
            done
        else
            echo "  検出結果なし"
        fi
        ;;

    logs)
        if [ -n "$2" ]; then
            docker compose logs -f "$2"
        else
            docker compose logs -f
        fi
        ;;

    build)
        log_info "イメージをビルド中..."
        docker compose build --no-cache
        log_info "ビルド完了"
        ;;

    generate)
        log_info "docker-compose.ymlを生成中..."
        if [ -f "streamers" ]; then
            python3 generate_compose.py "$@"
        else
            log_error "streamersファイルが見つかりません"
            exit 1
        fi
        ;;

    clean)
        log_warn "古い検出結果を削除しますか？ (y/N)"
        read -r confirm
        if [ "$confirm" = "y" ] || [ "$confirm" = "Y" ]; then
            # 7日以上前のファイルを削除
            find ./detections -type f -mtime +7 -delete 2>/dev/null || true
            log_info "7日以上前のファイルを削除しました"
        fi
        ;;

    *)
        echo "流星検出Docker管理スクリプト"
        echo ""
        echo "使い方: $0 <コマンド>"
        echo ""
        echo "コマンド:"
        echo "  start     全カメラの検出を開始"
        echo "  stop      全カメラの検出を停止"
        echo "  restart   全カメラを再起動"
        echo "  status    状態と検出結果を表示"
        echo "  logs      ログを表示（Ctrl+Cで終了）"
        echo "  logs <カメラ名>  特定カメラのログを表示"
        echo "  build     Dockerイメージを再ビルド"
        echo "  generate  streamersからdocker-compose.ymlを再生成"
        echo "  clean     古い検出結果を削除（7日以上前）"
        echo ""
        echo "例:"
        echo "  $0 start"
        echo "  $0 logs camera1"
        echo "  $0 generate --sensitivity fireball"
        exit 1
        ;;
esac
