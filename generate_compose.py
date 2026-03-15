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
import ipaddress
import re
import socket
import subprocess
from pathlib import Path

try:
    import cv2
except ImportError:
    cv2 = None

try:
    from meteor_mask_utils import build_exclusion_mask
except Exception:
    build_exclusion_mask = None

VERSION = "1.7.0"


def _is_usable_candidate_ip(value: str) -> bool:
    try:
        addr = ipaddress.ip_address(value)
    except ValueError:
        return False
    return addr.version == 4 and not addr.is_loopback and not addr.is_unspecified


def detect_local_ip() -> str:
    """WebRTC candidate に使うローカルIPを推定"""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("8.8.8.8", 80))
            value = sock.getsockname()[0]
            if _is_usable_candidate_ip(value):
                return value
    except OSError:
        pass

    try:
        for _, _, _, _, sockaddr in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            value = sockaddr[0]
            if _is_usable_candidate_ip(value):
                return value
    except OSError:
        pass

    try:
        result = subprocess.run(
            ["ifconfig"],
            capture_output=True,
            text=True,
            check=True,
        )
        for match in re.finditer(r"\binet (\d+\.\d+\.\d+\.\d+)\b", result.stdout):
            value = match.group(1)
            if _is_usable_candidate_ip(value):
                return value
    except (OSError, subprocess.SubprocessError):
        pass

    return ""


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
    parts = [part.strip() for part in line.split('|')]
    url = parts[0] if len(parts) > 0 else line.strip()
    mask_path = parts[1] if len(parts) > 1 else ""
    display_name = parts[2] if len(parts) > 2 else ""
    return {"url": url, "mask_path": mask_path, "display_name": display_name}


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
    display_name = rtsp_info.get('display_name', '')
    service_name = f"camera{index}"
    mask_env = "/app/mask_image.png" if mask_image else ""
    mask_build_arg = mask_image if mask_image else "mask_none.jpg"

    # CAMERA_NAME_DISPLAY環境変数を追加（表示名がある場合のみ）
    display_name_env = f"      - CAMERA_NAME_DISPLAY={display_name}\n" if display_name else ""

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
{display_name_env}      - SENSITIVITY={settings['sensitivity']}
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

    streaming_mode = settings.get("streaming_mode", "mjpeg").strip().lower()
    go2rtc_api_port = int(settings.get("go2rtc_api_port", 1984))

    # カメラ環境変数
    camera_envs = []
    depends = []
    for i, cam in enumerate(cameras, 1):
        camera_envs.append(f"      - CAMERA{i}_NAME={cam['name']}")
        if cam.get('display_name'):
            camera_envs.append(f"      - CAMERA{i}_NAME_DISPLAY={cam['display_name']}")
        camera_envs.append(f"      - CAMERA{i}_URL=http://localhost:{base_port + i}")
        if streaming_mode == "webrtc":
            camera_envs.append(f"      - CAMERA{i}_STREAM_KIND=webrtc")
            camera_envs.append(
                f"      - CAMERA{i}_STREAM_URL=http://localhost:{go2rtc_api_port}/stream.html?src=camera{i}&mode=webrtc&mode=mse&mode=hls&mode=mjpeg&background=false"
            )
        else:
            camera_envs.append(f"      - CAMERA{i}_STREAM_KIND=mjpeg")
            camera_envs.append(f"      - CAMERA{i}_STREAM_URL=http://localhost:{base_port + i}")
        depends.append(f"camera{i}")
    if streaming_mode == "webrtc":
        depends.append("go2rtc")

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


def generate_go2rtc_service(settings: dict) -> str:
    """WebRTC中継用の go2rtc サービスを生成"""

    api_port = int(settings.get("go2rtc_api_port", 1984))
    webrtc_port = int(settings.get("go2rtc_webrtc_port", 8555))
    config_path = settings.get("go2rtc_config_path", "./go2rtc.yaml")
    return f"""
  # WebRTC中継
  go2rtc:
    image: alexxit/go2rtc:latest
    container_name: meteor-go2rtc
    restart: unless-stopped
    ports:
      - "{api_port}:1984"
      - "{webrtc_port}:8555/tcp"
      - "{webrtc_port}:8555/udp"
    volumes:
      - {config_path}:/config/go2rtc.yaml:ro
    networks:
      - meteor-net
"""


def generate_go2rtc_config(cameras: list, settings: dict | None = None) -> str:
    """go2rtc設定ファイルを生成"""

    settings = settings or {}
    lines = [
        "api:",
        '  origin: "*"',
    ]
    candidate_host = str(settings.get("go2rtc_candidate_host", "")).strip()
    candidate_port = int(settings.get("go2rtc_webrtc_port", 8555))
    if candidate_host:
        lines.extend(
            [
                "",
                "webrtc:",
                "  candidates:",
                f"    - {candidate_host}:{candidate_port}",
            ]
        )
    lines.extend(["", "streams:"])
    for i, cam in enumerate(cameras, 1):
        lines.append(f"  camera{i}:")
        lines.append(f"    - {cam['url']}")
    return "\n".join(lines) + "\n"


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
            info["name"] = f"camera{i}_{info['host'].replace('.', '_')}"
            # 表示名を保持
            if parsed["display_name"]:
                info["display_name"] = parsed["display_name"]
            cameras.append(info)
            web_port = base_port + i  # 8081, 8082, 8083, ...
            mask_image = ""
            if parsed["mask_path"]:
                mask_src = Path(parsed["mask_path"])
                if not mask_src.is_absolute():
                    mask_src = (streamers_path.parent / mask_src).resolve()
                mask_output = mask_output_dir / f"camera{i}_mask.png"
                try:
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
                except RuntimeError as exc:
                    print("警告: OpenCVがないためマスク生成をスキップしました")
                    mask_image = ""
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

    if settings.get("streaming_mode", "mjpeg").strip().lower() == "webrtc":
        compose += generate_go2rtc_service(settings)

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
  | で区切ってマスク画像パスと表示名を指定可能
    形式: URL|マスク画像|表示名

例:
  rtsp://user:pass@192.168.1.100/live
  rtsp://user:pass@192.168.1.101/live|mask1.png|玄関カメラ
  # これはコメント
  rtsp://192.168.1.102:554/stream||駐車場
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
    parser.add_argument("--streaming-mode", default="mjpeg",
                       choices=["mjpeg", "webrtc"],
                       help="ダッシュボード表示方式 (default: mjpeg)")
    parser.add_argument("--go2rtc-api-port", type=int, default=1984,
                       help="go2rtc のWeb UI / WebRTCページ公開ポート (default: 1984)")
    parser.add_argument("--go2rtc-webrtc-port", type=int, default=8555,
                       help="go2rtc の WebRTC シグナリング / メディア用ポート (default: 8555)")
    parser.add_argument("--go2rtc-config", default="go2rtc.yaml",
                       help="生成する go2rtc 設定ファイル (default: go2rtc.yaml)")
    parser.add_argument("--go2rtc-candidate-host", default="",
                       help="go2rtc がブラウザへ返す到達可能アドレスのホスト/IP (default: 自動検出)")

    args = parser.parse_args()
    if args.streaming_mode == "webrtc" and not args.go2rtc_candidate_host:
        args.go2rtc_candidate_host = detect_local_ip()

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
        'streaming_mode': args.streaming_mode,
        'go2rtc_api_port': args.go2rtc_api_port,
        'go2rtc_webrtc_port': args.go2rtc_webrtc_port,
        'go2rtc_config_path': f"./{Path(args.go2rtc_config).name}",
        'go2rtc_candidate_host': args.go2rtc_candidate_host,
    }

    # 生成
    compose = generate_compose(args.streamers, settings, args.base_port)

    with open(args.streamers, 'r') as f:
        lines = [line.strip() for line in f if line.strip() and not line.startswith('#')]

    cameras = []
    for i, line in enumerate(lines, 1):
        parsed = parse_streamers_line(line)
        info = parse_rtsp_url(parsed["url"])
        if not info:
            continue
        info["name"] = f"camera{i}_{info['host'].replace('.', '_')}"
        cameras.append(info)

    if args.streaming_mode == "webrtc":
        go2rtc_config = generate_go2rtc_config(cameras, settings)
        go2rtc_output = Path(args.go2rtc_config)
        with open(go2rtc_output, 'w', encoding='utf-8') as f:
            f.write(go2rtc_config)

    # 出力
    with open(args.output, 'w') as f:
        f.write(compose)

    print(f"生成完了: {args.output}")
    if args.streaming_mode == "webrtc":
        print(f"go2rtc設定生成: {args.go2rtc_config}")
        if args.go2rtc_candidate_host:
            print(f"go2rtc candidate host: {args.go2rtc_candidate_host}")
        else:
            print("警告: go2rtc candidate host を自動検出できませんでした。Docker/NAT 環境では WebRTC が MSE にフォールバックする可能性があります。")

    # 情報表示
    urls = lines

    print(f"カメラ数: {len(urls)}")
    print()
    print("Webプレビュー:")
    print(f"  http://localhost:{args.base_port}/  (ダッシュボード)")
    for i, url in enumerate(urls, 1):
        info = parse_rtsp_url(url)
        if info:
            print(f"  http://localhost:{args.base_port + i}/  (カメラ{i}: {info['host']})")
    if args.streaming_mode == "webrtc":
        print(
            f"  http://localhost:{args.go2rtc_api_port}/stream.html?src=camera1&mode=webrtc&mode=mse&mode=hls&mode=mjpeg  (go2rtc ストリームテスト)"
        )
    print()
    print("使い方:")
    print("  docker compose build   # イメージをビルド")
    print("  docker compose up -d   # バックグラウンドで起動")
    print("  docker compose logs -f # ログを表示")
    print("  docker compose down    # 停止")


if __name__ == "__main__":
    main()
