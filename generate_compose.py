#!/usr/bin/env python3
"""
streamersファイルからdocker-compose.ymlを自動生成

使い方:
    python generate_compose.py
    python generate_compose.py --streamers /path/to/streamers --output docker-compose.yml

Copyright (c) 2026 Masanori Sakai
Licensed under the MIT License
"""

import argparse
import re
from pathlib import Path

try:
    import cv2
except ImportError:
    cv2 = None

try:
    from meteor_detector_rtsp_web import build_exclusion_mask
except Exception:
    build_exclusion_mask = None

VERSION = "1.4.0"


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


def parse_streamers_line(line: str) -> dict:
    if '|' in line:
        url, mask_path = [part.strip() for part in line.split('|', 1)]
        return {"url": url, "mask_path": mask_path}
    return {"url": line.strip(), "mask_path": ""}


def expand_mask_path(mask_template: str, index: int, rtsp_info: dict, base_dir: Path) -> str:
    if not mask_template:
        return ""
    expanded = (mask_template
                .replace("{index}", str(index))
                .replace("{host}", rtsp_info["host"]))
    path = Path(expanded)
    if path.is_absolute():
        try:
            return str(path.relative_to(base_dir))
        except ValueError:
            print(f"警告: マスク画像が作業ディレクトリ外のためビルドで失敗する可能性があります: {expanded}")
            return expanded
    return expanded


def generate_mask_file(mask_src: Path, output_path: Path, scale: float, dilate: int) -> str:
    if cv2 is None or build_exclusion_mask is None:
        raise RuntimeError("OpenCVが利用できないためマスク生成に失敗しました")

    img = cv2.imread(str(mask_src))
    if img is None:
        raise RuntimeError(f"マスク元画像を読み込めません: {mask_src}")

    height, width = img.shape[:2]
    proc_w = max(1, int(width * scale))
    proc_h = max(1, int(height * scale))
    output_path.parent.mkdir(parents=True, exist_ok=True)

    mask = build_exclusion_mask(str(mask_src), (proc_w, proc_h), dilate_px=dilate, save_path=output_path)
    if mask is None:
        raise RuntimeError(f"マスク生成に失敗しました: {mask_src}")

    return str(output_path)


def generate_service(index: int, rtsp_info: dict, settings: dict, web_port: int, mask_image: str) -> str:
    """1つのカメラ用のサービス定義を生成"""

    camera_name = f"camera{index}_{rtsp_info['host'].replace('.', '_')}"
    service_name = f"camera{index}"
    mask_env = "/app/mask_image.png" if mask_image else ""
    mask_build_arg = mask_image if mask_image else "mask_none.jpg"

    return f"""
  # カメラ{index} ({rtsp_info['host']})
  {service_name}:
    build:
      context: .
      args:
        MASK_IMAGE: {mask_build_arg}
    container_name: meteor-{service_name}
    restart: unless-stopped
    environment:
      - TZ=Asia/Tokyo
      - RTSP_URL={rtsp_info['url']}
      - CAMERA_NAME={camera_name}
      - SENSITIVITY={settings['sensitivity']}
      - SCALE={settings['scale']}
      - BUFFER={settings['buffer']}
      - EXCLUDE_BOTTOM={settings['exclude_bottom']}
      - EXTRACT_CLIPS={settings['extract_clips']}
      - LATITUDE={settings.get('latitude', '35.3606')}
      - LONGITUDE={settings.get('longitude', '138.7274')}
      - TIMEZONE=Asia/Tokyo
      - ENABLE_TIME_WINDOW={settings.get('enable_time_window', 'true')}
      - MASK_IMAGE={mask_env}
      - MASK_DILATE={settings.get('mask_dilate', '5')}
      - MASK_SAVE={settings.get('mask_save', '')}
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


def generate_dashboard(cameras: list, base_port: int, settings: dict) -> str:
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
      - TZ=Asia/Tokyo
      - PORT=8080
      - LATITUDE={settings.get('latitude', '35.3606')}
      - LONGITUDE={settings.get('longitude', '138.7274')}
      - TIMEZONE=Asia/Tokyo
      - ENABLE_TIME_WINDOW={settings.get('enable_time_window', 'true')}
{camera_env_str}
    ports:
      - "{base_port}:8080"
    volumes:
      - ./detections:/output
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
    mask_output_dir = Path(settings.get("mask_output_dir", "masks"))
    streamers_path = Path(streamers_file)
    for i, line in enumerate(lines, 1):
        parsed = parse_streamers_line(line)
        info = parse_rtsp_url(parsed["url"])
        if info:
            cameras.append(info)
            web_port = base_port + i  # 8081, 8082, 8083, ...
            mask_image = ""
            if parsed["mask_path"]:
                mask_src = Path(parsed["mask_path"])
                if not mask_src.is_absolute():
                    mask_src = (streamers_path.parent / mask_src).resolve()
                mask_output = mask_output_dir / f"camera{i}_mask.png"
                mask_image = generate_mask_file(
                    mask_src,
                    Path(mask_output),
                    float(settings["scale"]),
                    int(settings.get("mask_dilate", "5")),
                )
                try:
                    mask_image = str(Path(mask_image).relative_to(Path.cwd()))
                except ValueError:
                    pass
            services.append(generate_service(i, info, settings, web_port, mask_image))
        else:
            print(f"警告: 無効なURL (行{i}): {parsed['url']}")

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
    compose += generate_dashboard(cameras, base_port, settings)

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
    parser.add_argument("--extract-clips", default="true",
                       choices=["true", "false"],
                       help="クリップ動画を保存 (default: true)")
    parser.add_argument("--base-port", type=int, default=8080,
                       help="ベースポート番号 (default: 8080)")
    parser.add_argument("--latitude", default="35.3606",
                       help="観測地点の緯度 (default: 35.3606 = 富士山頂)")
    parser.add_argument("--longitude", default="138.7274",
                       help="観測地点の経度 (default: 138.7274 = 富士山頂)")
    parser.add_argument("--enable-time-window", default="true",
                       choices=["true", "false"],
                       help="天文薄暮期間のみ検出を有効化 (default: true)")
    parser.add_argument("--mask-output-dir", default="masks",
                       help="生成したマスク画像の保存先ディレクトリ (default: masks)")
    parser.add_argument("--mask-dilate", default="20",
                       help="除外マスクの拡張ピクセル数 (default: 20)")
    parser.add_argument("--mask-save", default="",
                       help="生成マスク画像の保存先 (空で保存しない)")

    args = parser.parse_args()

    settings = {
        'sensitivity': args.sensitivity,
        'scale': args.scale,
        'buffer': args.buffer,
        'exclude_bottom': args.exclude_bottom,
        'extract_clips': args.extract_clips,
        'latitude': args.latitude,
        'longitude': args.longitude,
        'enable_time_window': args.enable_time_window,
        'mask_output_dir': args.mask_output_dir,
        'mask_dilate': args.mask_dilate,
        'mask_save': args.mask_save,
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
