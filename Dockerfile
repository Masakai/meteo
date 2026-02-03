# 流星検出用Dockerイメージ
#
# Copyright (c) 2026 Masanori Sakai
# Licensed under the MIT License

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
COPY astro_utils.py .

# マスク画像（デフォルトは空ファイル）
ARG MASK_FROM_DAY=mask_none.jpg
ARG MASK_IMAGE=mask_none.jpg
COPY ${MASK_FROM_DAY} /app/mask_from_day.jpg
COPY ${MASK_IMAGE} /app/mask_image.png

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
ENV MASK_FROM_DAY="/app/mask_from_day.jpg"
ENV MASK_IMAGE=""
ENV MASK_DILATE="5"
ENV MASK_SAVE=""

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
    --mask-image "${MASK_IMAGE}" \
    --mask-from-day "${MASK_FROM_DAY}" \
    --mask-dilate "${MASK_DILATE}" \
    --mask-save "${MASK_SAVE}" \
    --web-port "${WEB_PORT}" \
    --camera-name "${CAMERA_NAME}"
