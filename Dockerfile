# 流星検出用Dockerイメージ
FROM python:3.11-slim

# OpenCV-headless用の依存ライブラリ
RUN apt-get update && apt-get install -y --no-install-recommends \
    libglib2.0-0 \
    libgomp1 \
    libxcb1 \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# 作業ディレクトリ
WORKDIR /app

# Python依存ライブラリ（Docker用のheadlessバージョン）
COPY requirements-docker.txt .
RUN pip install --no-cache-dir -r requirements-docker.txt

# アプリケーションコード
COPY meteor_detector_rtsp_web.py .

# 出力ディレクトリ
RUN mkdir -p /output

# 環境変数のデフォルト値
ENV RTSP_URL=""
ENV SENSITIVITY="medium"
ENV SCALE="0.5"
ENV BUFFER="15"
ENV EXCLUDE_BOTTOM="0.125"
ENV CAMERA_NAME="camera"
ENV WEB_PORT="8080"

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
