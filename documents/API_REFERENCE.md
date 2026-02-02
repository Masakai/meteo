# API リファレンス (API Reference)

## 概要

流星検出システムが提供するHTTP APIの完全なリファレンスです。

## 目次

- [dashboard.py API](#dashboardpy-api)
- [meteor_detector_rtsp_web.py API](#meteor_detector_rtsp_webpy-api)
- [共通仕様](#共通仕様)
- [エラーコード](#エラーコード)
- [使用例](#使用例)

---

## dashboard.py API

ダッシュボードが提供するエンドポイント（デフォルトポート: 8080）

### エンドポイント一覧

| エンドポイント | メソッド | 説明 |
|--------------|---------|------|
| `/` | GET | ダッシュボードHTML |
| `/detection_window` | GET | 検出時間帯取得 |
| `/detections` | GET | 検出一覧取得 |
| `/image/{camera}/{filename}` | GET | 画像ファイル取得 |
| `/detection/{camera}/{timestamp}` | DELETE | 検出結果削除 |
| `/changelog` | GET | CHANGELOG表示 |

---

### GET /

**説明**: ダッシュボードのHTMLページを返す

**レスポンス**:
- Content-Type: `text/html; charset=utf-8`
- Status: 200 OK

**使用例**:
```bash
curl http://localhost:8080/
```

---

### GET /detection_window

**説明**: 天文薄暮期間（検出時間帯）を取得

**クエリパラメータ**:

| パラメータ | 型 | 必須 | 説明 | 例 |
|-----------|-----|------|------|-----|
| `lat` | float | No | 緯度 | `35.6762` |
| `lon` | float | No | 経度 | `139.6503` |

**レスポンス**:
- Content-Type: `application/json`
- Status: 200 OK

**レスポンスボディ**:
```json
{
  "start": "2026-02-01 16:45:23",
  "end": "2026-02-02 06:12:45",
  "enabled": true,
  "latitude": 35.6762,
  "longitude": 139.6503
}
```

**フィールド説明**:

| フィールド | 型 | 説明 |
|-----------|-----|------|
| `start` | string | 検出開始時刻（YYYY-MM-DD HH:MM:SS） |
| `end` | string | 検出終了時刻（YYYY-MM-DD HH:MM:SS） |
| `enabled` | boolean | 時間帯制限の有効/無効 |
| `latitude` | float | 使用された緯度 |
| `longitude` | float | 使用された経度 |

**エラーレスポンス**:
```json
{
  "start": "",
  "end": "",
  "enabled": false,
  "error": "meteor_detector module not available"
}
```

**使用例**:
```bash
# デフォルト座標で取得
curl "http://localhost:8080/detection_window" | jq

# 座標を指定
curl "http://localhost:8080/detection_window?lat=35.6762&lon=139.6503" | jq

# JavaScriptから取得
fetch('/detection_window?lat=35.6762&lon=139.6503')
  .then(r => r.json())
  .then(data => console.log(data));
```

---

### GET /detections

**説明**: 全カメラの検出結果一覧を取得

**レスポンス**:
- Content-Type: `application/json`
- Status: 200 OK

**レスポンスボディ**:
```json
{
  "total": 15,
  "recent": [
    {
      "time": "2026-02-02 06:55:33",
      "camera": "camera1_10_0_1_25",
      "confidence": "87%",
      "image": "camera1_10_0_1_25/meteor_20260202_065533_composite.jpg"
    },
    {
      "time": "2026-02-02 05:32:18",
      "camera": "camera2_10_0_1_3",
      "confidence": "92%",
      "image": "camera2_10_0_1_3/meteor_20260202_053218_composite.jpg"
    }
  ]
}
```

**フィールド説明**:

| フィールド | 型 | 説明 |
|-----------|-----|------|
| `total` | integer | 総検出数 |
| `recent` | array | 最新10件の検出リスト |
| `recent[].time` | string | 検出時刻 |
| `recent[].camera` | string | カメラ名 |
| `recent[].confidence` | string | 信頼度（パーセント表示） |
| `recent[].image` | string | 画像パス |

**使用例**:
```bash
# curlで取得
curl http://localhost:8080/detections | jq

# 総検出数のみ取得
curl -s http://localhost:8080/detections | jq '.total'

# 最新の検出のみ取得
curl -s http://localhost:8080/detections | jq '.recent[0]'

# JavaScriptから取得
fetch('/detections')
  .then(r => r.json())
  .then(data => {
    console.log('Total:', data.total);
    data.recent.forEach(d => console.log(d.time, d.camera));
  });
```

---

### GET /image/{camera}/{filename}

**説明**: 検出画像ファイルを取得

**URLパラメータ**:

| パラメータ | 型 | 説明 | 例 |
|-----------|-----|------|-----|
| `camera` | string | カメラディレクトリ名 | `camera1_10_0_1_25` |
| `filename` | string | ファイル名 | `meteor_20260202_065533_composite.jpg` |

**レスポンス**:
- Content-Type: `image/jpeg` または `image/png`
- Status: 200 OK
- Body: バイナリ画像データ

**エラーレスポンス**:
- Status: 404 Not Found

**使用例**:
```bash
# 画像をダウンロード
curl -O "http://localhost:8080/image/camera1_10_0_1_25/meteor_20260202_065533_composite.jpg"

# HTMLから表示
<img src="/image/camera1_10_0_1_25/meteor_20260202_065533_composite.jpg" alt="Meteor">

# ダウンロードリンク
<a href="/image/camera1_10_0_1_25/meteor_20260202_065533_composite.jpg" download>
  Download Image
</a>
```

---

### DELETE /detection/{camera}/{timestamp}

**説明**: 検出結果を削除（MP4、画像、JSONLエントリ）

**URLパラメータ**:

| パラメータ | 型 | 説明 | 例 |
|-----------|-----|------|-----|
| `camera` | string | カメラディレクトリ名 | `camera1_10_0_1_25` |
| `timestamp` | string | 検出時刻（URL encoded） | `2026-02-02 06:55:33` |

**レスポンス**:
- Content-Type: `application/json`
- Status: 200 OK

**成功レスポンス**:
```json
{
  "success": true,
  "deleted_files": [
    "meteor_20260202_065533.mp4",
    "meteor_20260202_065533_composite.jpg",
    "meteor_20260202_065533_composite_original.jpg"
  ],
  "message": "3個のファイルを削除しました"
}
```

**エラーレスポンス**:
```json
{
  "success": false,
  "error": "File not found"
}
```

**使用例**:
```bash
# curlで削除
curl -X DELETE "http://localhost:8080/detection/camera1_10_0_1_25/2026-02-02%2006:55:33"

# JavaScriptから削除
fetch('/detection/camera1_10_0_1_25/2026-02-02 06:55:33', {
  method: 'DELETE'
})
.then(r => r.json())
.then(data => {
  if (data.success) {
    alert(data.message);
  } else {
    alert('削除失敗: ' + data.error);
  }
});
```

---

### GET /changelog

**説明**: CHANGELOG.mdの内容を取得

**レスポンス**:
- Content-Type: `text/plain; charset=utf-8`
- Status: 200 OK
- Body: CHANGELOG.mdの内容（テキスト）

**使用例**:
```bash
curl http://localhost:8080/changelog
```

---

## meteor_detector_rtsp_web.py API

各カメラコンテナが提供するエンドポイント（デフォルトポート: 8080）

### エンドポイント一覧

| エンドポイント | メソッド | 説明 |
|--------------|---------|------|
| `/` | GET | プレビューHTML |
| `/stream` | GET | MJPEGストリーム |
| `/stats` | GET | 統計情報 |

---

### GET /

**説明**: カメラプレビューのHTMLページを返す

**レスポンス**:
- Content-Type: `text/html; charset=utf-8`
- Status: 200 OK

**使用例**:
```bash
# camera1のプレビュー
curl http://localhost:8081/

# ブラウザで開く
open http://localhost:8081/
```

---

### GET /stream

**説明**: MJPEGストリーム（Motion JPEG）を返す

**レスポンス**:
- Content-Type: `multipart/x-mixed-replace; boundary=frame`
- Status: 200 OK
- Body: 連続的なJPEGフレーム（約30fps）

**ストリームフォーマット**:
```
--frame\r\n
Content-Type: image/jpeg\r\n\r\n
<JPEG binary data>
\r\n
--frame\r\n
Content-Type: image/jpeg\r\n\r\n
<JPEG binary data>
\r\n
...
```

**使用例**:
```bash
# HTMLで表示
<img src="http://localhost:8081/stream" alt="Live Stream">

# VLCで再生
vlc http://localhost:8081/stream

# ffmpegで録画
ffmpeg -i http://localhost:8081/stream -t 60 output.mp4
```

**特徴**:
- リアルタイムプレビュー
- 検出中の物体が緑丸で表示
- 追跡中の軌跡が黄線で表示
- 流星検出時に赤で表示
- フレームレート: 約30fps
- 画質: JPEG品質70%

---

### GET /stats

**説明**: カメラの統計情報を取得

**レスポンス**:
- Content-Type: `application/json`
- Status: 200 OK

**レスポンスボディ**:
```json
{
  "detections": 5,
  "elapsed": 3600.5,
  "camera": "camera1_10_0_1_25",
  "settings": {
    "sensitivity": "medium",
    "scale": 0.5,
    "buffer": 15.0,
    "extract_clips": true,
    "exclude_bottom": 0.0625
  },
  "stream_alive": true,
  "time_since_last_frame": 0.03,
  "is_detecting": true
}
```

**フィールド説明**:

| フィールド | 型 | 説明 |
|-----------|-----|------|
| `detections` | integer | 検出数 |
| `elapsed` | float | 稼働時間（秒） |
| `camera` | string | カメラ名 |
| `settings` | object | 設定情報 |
| `settings.sensitivity` | string | 感度プリセット |
| `settings.scale` | float | 処理スケール |
| `settings.buffer` | float | バッファ秒数 |
| `settings.extract_clips` | boolean | MP4保存の有効/無効 |
| `settings.exclude_bottom` | float | 画面下部除外率 |
| `stream_alive` | boolean | ストリーム生存確認 |
| `time_since_last_frame` | float | 最終フレームからの経過時間（秒） |
| `is_detecting` | boolean | 現在検出処理中か |

**使用例**:
```bash
# curlで取得
curl http://localhost:8081/stats | jq

# 検出数のみ取得
curl -s http://localhost:8081/stats | jq '.detections'

# ストリーム状態を確認
curl -s http://localhost:8081/stats | jq '.stream_alive'

# 全カメラの統計を一括取得
for port in 8081 8082 8083; do
  echo "Port $port:"
  curl -s "http://localhost:$port/stats" | jq '{camera, detections, stream_alive}'
done

# JavaScriptから定期取得
setInterval(() => {
  fetch('http://localhost:8081/stats')
    .then(r => r.json())
    .then(data => {
      console.log('Detections:', data.detections);
      console.log('Stream alive:', data.stream_alive);
      console.log('Is detecting:', data.is_detecting);
    });
}, 2000);  // 2秒ごと
```

---

## 共通仕様

### CORS（Cross-Origin Resource Sharing）

**現在の設定**:
```python
# /stats エンドポイントのみCORS許可
self.send_header('Access-Control-Allow-Origin', '*')
```

**制限事項**:
- 他のエンドポイントはCORS未対応
- 外部ドメインからのアクセスは制限される

**カスタマイズ例**:
```python
# すべてのエンドポイントでCORS許可（セキュリティ注意）
def end_headers(self):
    self.send_header('Access-Control-Allow-Origin', '*')
    self.send_header('Access-Control-Allow-Methods', 'GET, POST, DELETE')
    self.send_header('Access-Control-Allow-Headers', 'Content-Type')
    BaseHTTPRequestHandler.end_headers(self)
```

---

### レート制限

**現在の制限**: なし

**推奨実装** (Nginxリバースプロキシ):
```nginx
# /etc/nginx/sites-available/meteor
limit_req_zone $binary_remote_addr zone=api:10m rate=10r/s;

server {
    location /api/ {
        limit_req zone=api burst=20;
        proxy_pass http://localhost:8080/;
    }
}
```

---

### タイムアウト

| エンドポイント | タイムアウト | 理由 |
|--------------|------------|------|
| `/stream` | なし | ストリーミング |
| その他 | 30秒 | ブラウザデフォルト |

---

## エラーコード

### HTTPステータスコード

| コード | 説明 | 発生条件 |
|-------|------|---------|
| 200 | OK | 成功 |
| 404 | Not Found | ファイルまたはエンドポイントが存在しない |
| 500 | Internal Server Error | サーバー内部エラー |

### エラーレスポンス例

```json
{
  "success": false,
  "error": "File not found"
}
```

---

## 使用例

### Python

```python
import requests

# 検出一覧を取得
response = requests.get('http://localhost:8080/detections')
data = response.json()
print(f"Total detections: {data['total']}")

# 統計情報を取得
stats = requests.get('http://localhost:8081/stats').json()
print(f"Camera: {stats['camera']}, Detections: {stats['detections']}")

# 検出結果を削除
delete_response = requests.delete(
    'http://localhost:8080/detection/camera1_10_0_1_25/2026-02-02 06:55:33'
)
print(delete_response.json())
```

---

### JavaScript（ブラウザ）

```javascript
// 検出一覧を取得して表示
async function loadDetections() {
  const response = await fetch('/detections');
  const data = await response.json();

  console.log(`Total: ${data.total}`);
  data.recent.forEach(detection => {
    console.log(`${detection.time} - ${detection.camera} (${detection.confidence})`);
  });
}

// 統計情報を定期取得
setInterval(async () => {
  const stats = await fetch('http://localhost:8081/stats').then(r => r.json());
  document.getElementById('detections').textContent = stats.detections;
  document.getElementById('status').textContent = stats.stream_alive ? 'Online' : 'Offline';
}, 2000);

// 検出結果を削除
async function deleteDetection(camera, timestamp) {
  const response = await fetch(`/detection/${camera}/${timestamp}`, {
    method: 'DELETE'
  });
  const result = await response.json();

  if (result.success) {
    alert(result.message);
    loadDetections();  // リストを更新
  } else {
    alert(`Error: ${result.error}`);
  }
}
```

---

### Node.js

```javascript
const axios = require('axios');

// 全カメラの統計を取得
async function getAllStats() {
  const cameras = [8081, 8082, 8083];
  const promises = cameras.map(port =>
    axios.get(`http://localhost:${port}/stats`)
  );

  const results = await Promise.all(promises);
  results.forEach((res, i) => {
    console.log(`Camera ${i+1}:`, res.data.detections, 'detections');
  });
}

getAllStats();
```

---

### Bash

```bash
#!/bin/bash
# 全カメラの統計を表示

echo "=== Meteor Detection Stats ==="
for port in 8081 8082 8083; do
  stats=$(curl -s "http://localhost:$port/stats")
  camera=$(echo "$stats" | jq -r '.camera')
  detections=$(echo "$stats" | jq -r '.detections')
  alive=$(echo "$stats" | jq -r '.stream_alive')

  echo "$camera: $detections detections (stream: $alive)"
done

# 検出一覧を取得
echo ""
echo "=== Recent Detections ==="
curl -s "http://localhost:8080/detections" | \
  jq -r '.recent[] | "\(.time) - \(.camera) (\(.confidence))"'
```

---

### PowerShell

```powershell
# 検出一覧を取得
$detections = Invoke-RestMethod -Uri "http://localhost:8080/detections"
Write-Host "Total detections: $($detections.total)"

# 統計情報を取得
$stats = Invoke-RestMethod -Uri "http://localhost:8081/stats"
Write-Host "Camera: $($stats.camera), Detections: $($stats.detections)"

# 検出結果を削除
$deleteResult = Invoke-RestMethod `
  -Uri "http://localhost:8080/detection/camera1_10_0_1_25/2026-02-02%2006:55:33" `
  -Method Delete
Write-Host $deleteResult.message
```

---

## Webhook連携例

### 検出時にSlackに通知

```python
# webhook_notifier.py
import requests
import time
import json

SLACK_WEBHOOK_URL = "https://hooks.slack.com/services/YOUR/WEBHOOK/URL"
last_count = {}

def check_detections():
    for port in [8081, 8082, 8083]:
        stats = requests.get(f'http://localhost:{port}/stats').json()
        camera = stats['camera']
        count = stats['detections']

        if camera not in last_count:
            last_count[camera] = count

        if count > last_count[camera]:
            # 新しい検出があった
            message = {
                "text": f"🌠 流星検出！\nカメラ: {camera}\n検出数: {count}"
            }
            requests.post(SLACK_WEBHOOK_URL, json=message)
            last_count[camera] = count

# 10秒ごとに確認
while True:
    check_detections()
    time.sleep(10)
```

---

### 検出時にメール送信

```python
# email_notifier.py
import requests
import smtplib
from email.mime.text import MIMEText

def send_email(subject, body):
    msg = MIMEText(body)
    msg['Subject'] = subject
    msg['From'] = 'meteor@example.com'
    msg['To'] = 'admin@example.com'

    with smtplib.SMTP('smtp.example.com', 587) as server:
        server.starttls()
        server.login('user', 'password')
        server.send_message(msg)

def monitor():
    last_count = {}
    while True:
        detections = requests.get('http://localhost:8080/detections').json()

        for detection in detections['recent']:
            key = f"{detection['camera']}_{detection['time']}"
            if key not in last_count:
                send_email(
                    f"流星検出: {detection['camera']}",
                    f"時刻: {detection['time']}\n信頼度: {detection['confidence']}"
                )
                last_count[key] = True

        time.sleep(30)

monitor()
```

---

## APIクライアントライブラリ例

### Python用シンプルクライアント

```python
# meteor_client.py
import requests
from typing import List, Dict, Optional

class MeteorDetectionClient:
    def __init__(self, dashboard_url: str = "http://localhost:8080"):
        self.dashboard_url = dashboard_url

    def get_detections(self) -> Dict:
        """検出一覧を取得"""
        response = requests.get(f"{self.dashboard_url}/detections")
        return response.json()

    def get_detection_window(self, lat: float = None, lon: float = None) -> Dict:
        """検出時間帯を取得"""
        params = {}
        if lat: params['lat'] = lat
        if lon: params['lon'] = lon

        response = requests.get(
            f"{self.dashboard_url}/detection_window",
            params=params
        )
        return response.json()

    def delete_detection(self, camera: str, timestamp: str) -> Dict:
        """検出結果を削除"""
        response = requests.delete(
            f"{self.dashboard_url}/detection/{camera}/{timestamp}"
        )
        return response.json()

    def get_camera_stats(self, port: int) -> Dict:
        """カメラの統計情報を取得"""
        response = requests.get(f"http://localhost:{port}/stats")
        return response.json()

# 使用例
if __name__ == "__main__":
    client = MeteorDetectionClient()

    # 検出一覧を取得
    detections = client.get_detections()
    print(f"Total: {detections['total']}")

    # カメラ統計を取得
    stats = client.get_camera_stats(8081)
    print(f"Camera: {stats['camera']}, Detections: {stats['detections']}")
```

---

## 関連ドキュメント

- [OPERATIONS_GUIDE.md](OPERATIONS_GUIDE.md) - 運用ガイド
- [ARCHITECTURE.md](ARCHITECTURE.md) - システムアーキテクチャ
- [DETECTOR_COMPONENTS.md](DETECTOR_COMPONENTS.md) - 検出コンポーネント詳細
