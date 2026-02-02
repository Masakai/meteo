# 流星検出用Dockerイメージ
#
# Copyright (c) 2026 Masanori Sakai
# All rights reserved.

FROM python:3.11-slim

# 作業ディレクトリ
WORKDIR /app

# Python依存ライブラリを先にインストール
COPY requirements-docker.txt .
RUN pip install --no-cache-dir -r requirements-docker.txt

# OpenCV実行に必要な最小限のシステムライブラリをインストール
# libxcb1はopencv-python-headlessでも必要
# -o APT::Keep-Downloaded-Packages=false でキャッシュを無効化してディスク容量を節約
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        -o APT::Keep-Downloaded-Packages=false \
        libxcb1 \
        libglib2.0-0 \
        libgomp1 && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# アプリケーションコード
COPY meteor_detector_rtsp_web.py .

# 出力ディレクトリ
RUN mkdir -p /output

# タイムゾーン設定
ENV TZ=Asia/Tokyo
RUN ln -sf /usr/share/zoneinfo/Asia/Tokyo /etc/localtime && \
    echo "Asia/Tokyo" > /etc/timezone

# 環境変数のデフォルト値
ENV RTSP_URL=""
ENV SENSITIVITY="medium"
ENV SCALE="0.5"
ENV BUFFER="15"
ENV EXCLUDE_BOTTOM="0.125"
ENV CAMERA_NAME="camera"
ENV WEB_PORT="8080"
ENV EXTRACT_CLIPS="true"

# Webプレビュー用ポート
EXPOSE 8080

# 起動コマンド
CMD python meteor_detector_rtsp_web.py \
    "${RTSP_URL}" \
    -o "/output/${CAMERA_NAME}" \
    --sensitivity "${SENSITIVITY}" \
    --scale "${SCALE}" \
    --buffer "${BUFFER}" \
    --exclude-bottom "${EXCLUDE_BOTTOM}" \
    --web-port "${WEB_PORT}" \
    --camera-name "${CAMERA_NAME}"
