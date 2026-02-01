#!/usr/bin/env python3
"""
streamersファイルからdocker-compose.ymlを自動生成

使い方:
    python generate_compose.py
    python generate_compose.py --streamers /path/to/streamers --output docker-compose.yml

Copyright (c) 2026 Masanori Sakai
All rights reserved.
"""

import argparse
import re
from pathlib import Path


def parse_rtsp_url(url: str) -> dict:
    """RTSPのURLをパース"""
    pattern = r'rtsp://(?:([^:]+):([^@]+)@)?([^:/]+)(?::(\d+))?(/.*)?'
    match = re.match(pattern, url.strip())

    if not match:
        return None

    return {
        'user': match.group(1),
        'password': match.group(2),
        'host': match.group(3),
        'port': match.group(4) or '554',
        'path': match.group(5) or '/live',
        'url': url.strip(),
    }


def generate_service(index: int, rtsp_info: dict, settings: dict, web_port: int) -> str:
    """1つのカメラ用のサービス定義を生成"""

    camera_name = f"camera{index}_{rtsp_info['host'].replace('.', '_')}"
    service_name = f"camera{index}"

    return f"""
  # カメラ{index} ({rtsp_info['host']})
  {service_name}:
    build: .
    container_name: meteor-{service_name}
    restart: unless-stopped
    environment:
      - RTSP_URL={rtsp_info['url']}
      - CAMERA_NAME={camera_name}
      - SENSITIVITY={settings['sensitivity']}
      - SCALE={settings['scale']}
      - BUFFER={settings['buffer']}
      - EXCLUDE_BOTTOM={settings['exclude_bottom']}
      - WEB_PORT=8080
    ports:
      - "{web_port}:8080"
    volumes:
      - ./detections:/output
    networks:
      - meteor-net
    logging:
      driver: "json-file"
      options:
        max-size: "10m"
        max-file: "3"
"""


def generate_dashboard(cameras: list, base_port: int) -> str:
    """ダッシュボードサービスを生成"""

    # カメラ環境変数
    camera_envs = []
    depends = []
    for i, cam in enumerate(cameras, 1):
        camera_envs.append(f"      - CAMERA{i}_NAME=camera{i} ({cam['host']})")
        camera_envs.append(f"      - CAMERA{i}_URL=http://localhost:{base_port + i}")
        depends.append(f"camera{i}")

    camera_env_str = "\n".join(camera_envs)
    depends_str = "\n      - ".join(depends)

    return f"""
  # ダッシュボード（全カメラ一覧）
  dashboard:
    build:
      context: .
      dockerfile: Dockerfile.dashboard
    container_name: meteor-dashboard
    restart: unless-stopped
    environment:
      - PORT=8080
{camera_env_str}
    ports:
      - "{base_port}:8080"
    volumes:
      - ./detections:/output:ro
    networks:
      - meteor-net
    depends_on:
      - {depends_str}
"""


def generate_compose(streamers_file: str, settings: dict, base_port: int = 8080) -> str:
    """docker-compose.ymlを生成"""

    # streamersファイルを読み込み
    with open(streamers_file, 'r') as f:
        lines = [line.strip() for line in f if line.strip() and not line.startswith('#')]

    # 各RTSPストリームをパース
    cameras = []
    services = []
    for i, url in enumerate(lines, 1):
        info = parse_rtsp_url(url)
        if info:
            cameras.append(info)
            web_port = base_port + i  # 8081, 8082, 8083, ...
            services.append(generate_service(i, info, settings, web_port))
        else:
            print(f"警告: 無効なURL (行{i}): {url}")

    if not services:
        raise ValueError("有効なRTSPストリームが見つかりません")

    # ポート一覧を生成
    port_list = [f"#   http://localhost:{base_port}/  (ダッシュボード)"]
    for i, cam in enumerate(cameras, 1):
        port_list.append(f"#   http://localhost:{base_port + i}/  (カメラ{i}: {cam['host']})")
    port_list_str = "\n".join(port_list)

    # docker-compose.yml を構築
    compose = f"""# 流星検出 Docker Compose設定（Webプレビュー付き）
# 自動生成: python generate_compose.py
#
# Copyright (c) 2026 Masanori Sakai
# All rights reserved.
#
# 使い方:
#   起動:     docker compose up -d
#   停止:     docker compose down
#   ログ確認: docker compose logs -f
#
# Webプレビュー:
{port_list_str}
#
# 検出結果は ./detections/ 以下に保存されます

services:"""

    # ダッシュボード
    compose += generate_dashboard(cameras, base_port)

    # カメラサービス
    compose += "".join(services)

    # ネットワーク
    compose += """
networks:
  meteor-net:
    driver: bridge
"""

    return compose


def main():
    parser = argparse.ArgumentParser(
        description="streamersファイルからdocker-compose.ymlを生成",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
streamersファイルの形式:
  1行に1つのRTSP URLを記載
  # で始まる行はコメント

例:
  rtsp://user:pass@192.168.1.100/live
  rtsp://user:pass@192.168.1.101/live
  # これはコメント
  rtsp://192.168.1.102:554/stream
        """
    )

    parser.add_argument("-s", "--streamers", default="streamers",
                       help="streamersファイルのパス (default: streamers)")
    parser.add_argument("-o", "--output", default="docker-compose.yml",
                       help="出力ファイル (default: docker-compose.yml)")
    parser.add_argument("--sensitivity", default="medium",
                       choices=["low", "medium", "high", "fireball"],
                       help="検出感度 (default: medium)")
    parser.add_argument("--scale", default="0.5",
                       help="処理スケール (default: 0.5)")
    parser.add_argument("--buffer", default="15",
                       help="バッファ秒数 (default: 15)")
    parser.add_argument("--exclude-bottom", default="0.0625",
                       help="下部除外範囲 (default: 0.0625)")
    parser.add_argument("--base-port", type=int, default=8080,
                       help="ベースポート番号 (default: 8080)")

    args = parser.parse_args()

    settings = {
        'sensitivity': args.sensitivity,
        'scale': args.scale,
        'buffer': args.buffer,
        'exclude_bottom': args.exclude_bottom,
    }

    # 生成
    compose = generate_compose(args.streamers, settings, args.base_port)

    # 出力
    with open(args.output, 'w') as f:
        f.write(compose)

    print(f"生成完了: {args.output}")

    # 情報表示
    with open(args.streamers, 'r') as f:
        urls = [line.strip() for line in f if line.strip() and not line.startswith('#')]

    print(f"カメラ数: {len(urls)}")
    print()
    print("Webプレビュー:")
    print(f"  http://localhost:{args.base_port}/  (ダッシュボード)")
    for i, url in enumerate(urls, 1):
        info = parse_rtsp_url(url)
        if info:
            print(f"  http://localhost:{args.base_port + i}/  (カメラ{i}: {info['host']})")
    print()
    print("使い方:")
    print("  docker compose build   # イメージをビルド")
    print("  docker compose up -d   # バックグラウンドで起動")
    print("  docker compose logs -f # ログを表示")
    print("  docker compose down    # 停止")


if __name__ == "__main__":
    main()
