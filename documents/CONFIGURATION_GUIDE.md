# 設定ガイド (Configuration Guide)

---

**Copyright (c) 2026 Masanori Sakai**

Licensed under the MIT License

---


## 概要

このガイドでは、流星検出システムの各種設定方法とチューニング手法について説明します。

## 目次

- [環境変数](#環境変数)
- [検出パラメータ](#検出パラメータ)
- [感度プリセット](#感度プリセット)
- [処理スケール設定](#処理スケール設定)
- [天文薄暮時間帯設定](#天文薄暮時間帯設定)
- [ハードウェア別推奨設定](#ハードウェア別推奨設定)
- [チューニング方法](#チューニング方法)

---

## 環境変数

### カメラコンテナの環境変数

docker-compose.ymlで設定される環境変数:

| 変数名 | デフォルト値 | 説明 | 設定例 |
|-------|------------|------|--------|
| `TZ` | `Asia/Tokyo` | タイムゾーン | `America/New_York` |
| `RTSP_URL` | - | RTSPストリームURL | `rtsp://user:pass@10.0.1.25/live` |
| `CAMERA_NAME` | `camera` | カメラ識別名 | `camera1_10_0_1_25` |
| `SENSITIVITY` | `medium` | 検出感度 | `low` / `medium` / `high` / `fireball` |
| `SCALE` | `0.5` | 処理スケール | `0.25` ~ `1.0` |
| `BUFFER` | `15` | リングバッファ秒数 | `10` ~ `30` |
| `EXCLUDE_BOTTOM` | `0.0625` | 画面下部除外率 | `0.0` ~ `0.25` |
| `EXTRACT_CLIPS` | `true` | MP4クリップ保存 | `true` / `false` |
| `LATITUDE` | `35.3606` | 観測地の緯度 | `35.6762`（東京） |
| `LONGITUDE` | `138.7274` | 観測地の経度 | `139.6503`（東京） |
| `TIMEZONE` | `Asia/Tokyo` | タイムゾーン名 | `UTC` / `Europe/London` |
| `ENABLE_TIME_WINDOW` | `false` | 天文薄暮時間帯制限 | `true` / `false` |
| `WEB_PORT` | `8080` | 内部HTTPポート | 通常変更不要 |
| `MASK_IMAGE` | `""` | 事前生成済みマスク画像（優先） | `/app/mask_image.png` |
| `MASK_FROM_DAY` | `""` | 昼間画像からマスク生成 | `/app/mask_from_day.jpg` |
| `MASK_DILATE` | `5` | マスク拡張ピクセル数 | `3` / `7` |
| `MASK_SAVE` | `""` | マスク保存先 | `/output/masks/camera1_mask.png` |

### ダッシュボードの環境変数

| 変数名 | デフォルト値 | 説明 |
|-------|------------|------|
| `PORT` | `8080` | HTTPサーバーポート |
| `LATITUDE` | `35.3606` | 観測地の緯度 |
| `LONGITUDE` | `138.7274` | 観測地の経度 |
| `TIMEZONE` | `Asia/Tokyo` | タイムゾーン名 |
| `ENABLE_TIME_WINDOW` | `false` | 天文薄暮時間帯制限 |
| `CAMERA1_NAME` | - | カメラ1の表示名 |
| `CAMERA1_URL` | - | カメラ1のURL |
| `DETECTIONS_DIR` | `/output` | 検出結果ディレクトリ |

### 環境変数の設定方法

#### 方法1: generate_compose.pyで一括設定

```bash
python generate_compose.py \
  --streamers streamers \
  --sensitivity high \
  --scale 0.5 \
  --buffer 15 \
  --latitude 35.6762 \
  --longitude 139.6503 \
  --enable-time-window true \
  --extract-clips true \
  --mask-output-dir masks
```

#### 方法2: docker-compose.ymlを直接編集

```yaml
services:
  camera1:
    environment:
      - SENSITIVITY=high
      - SCALE=0.5
      - EXTRACT_CLIPS=false
```

#### 方法3: .envファイルを使用

```bash
# .env ファイルを作成
cat > .env << 'EOF'
# 全カメラ共通設定
SENSITIVITY=medium
SCALE=0.5
BUFFER=15
EXTRACT_CLIPS=true

# 観測地点
LATITUDE=35.6762
LONGITUDE=139.6503
ENABLE_TIME_WINDOW=true

# RTSP認証情報（セキュリティ向上）
RTSP_USER=username
RTSP_PASS=password
EOF

chmod 600 .env  # パーミッション制限
```

docker-compose.ymlで参照:
```yaml
environment:
  - SENSITIVITY=${SENSITIVITY:-medium}
  - RTSP_URL=rtsp://${RTSP_USER}:${RTSP_PASS}@10.0.1.25/live
```

---

## マスク設定（固定カメラ向け）

### streamers に昼間画像を指定

`streamers` で `RTSP URL | 昼間画像` の形式にすると、`generate_compose.py` 実行時に
除外マスクを自動生成してコンテナに同梱します。

```
rtsp://user:pass@10.0.1.25/live | camera1.jpg
rtsp://user:pass@10.0.1.3/live  | camera2.jpg
rtsp://user:pass@10.0.1.11/live
```

- 画像パスは `streamers` と同じフォルダ基準（相対パス可）
- マスク生成には OpenCV が必要

### その場でマスクを更新（永続化）

ダッシュボードの「マスク更新」ボタンで、**現在フレームからマスクを再生成**できます。
保存先は `/output/masks/<camera>_mask.png` です。

---

## 検出パラメータ

### DetectionParams クラス

meteor_detector_rtsp_web.py内で定義されるパラメータ:

```python
@dataclass
class DetectionParams:
    diff_threshold: int = 30          # 差分閾値
    min_brightness: int = 200         # 最小輝度
    min_length: int = 20              # 最小軌跡長 (px)
    max_length: int = 5000            # 最大軌跡長 (px)
    min_duration: float = 0.1         # 最小継続時間 (秒)
    max_duration: float = 10.0        # 最大継続時間 (秒)
    min_speed: float = 50.0           # 最小速度 (px/s)
    min_linearity: float = 0.7        # 最小直線性 (0-1)
    min_area: int = 5                 # 最小面積 (px²)
    max_area: int = 10000             # 最大面積 (px²)
    max_gap_time: float = 0.2         # 最大トラッキング間隔 (秒)
    max_distance: float = 80          # 最大移動距離 (px)
    exclude_bottom_ratio: float = 1/16 # 画面下部除外率
```

### パラメータの詳細説明

#### diff_threshold（差分閾値）

**説明**: フレーム間差分の閾値。この値を超える変化を検出対象とする

**影響**:
- **低い値（15-20）**: 小さな変化も検出 → 感度高、誤検出も増加
- **高い値（40-50）**: 大きな変化のみ検出 → 感度低、誤検出減少

**推奨値**:
- 明るい環境: 40
- 通常環境: 30
- 暗い環境: 20

**調整例**:
```python
# コード内で直接変更する場合
params = DetectionParams()
params.diff_threshold = 25  # より敏感に
```

---

#### min_brightness（最小輝度）

**説明**: 検出対象とする最小の明るさ（0-255）

**影響**:
- **低い値（150-180）**: 暗い流星も検出
- **高い値（220-255）**: 明るい流星のみ検出

**推奨値**:
- 市街地（光害あり）: 220
- 郊外: 200
- 山間部（光害なし）: 180

---

#### min_length / max_length（軌跡長）

**説明**: 検出する軌跡の長さ範囲（ピクセル）

**min_length の影響**:
- **短い（10-15px）**: 短い軌跡も検出 → 誤検出増加
- **長い（30-50px）**: 長い軌跡のみ → 見逃し増加

**推奨値**:
- 1920x1080: min=20, max=5000
- 1280x720: min=15, max=3000
- 640x480: min=10, max=2000

---

#### min_duration / max_duration（継続時間）

**説明**: 検出する軌跡の時間範囲（秒）

**推奨値**:
- 通常の流星: min=0.1, max=10.0
- 火球専用: min=0.5, max=20.0

---

#### min_speed（最小速度）

**説明**: 検出する最小移動速度（ピクセル/秒）

**影響**:
- **低い値（20-30）**: ゆっくり動く物体も検出 → 航空機を誤検出
- **高い値（70-100）**: 速い物体のみ → 流星の見逃しが増える

**推奨値**: 50 px/s

**参考**: 流星の典型的な速度は100-500 px/s

---

#### min_linearity（最小直線性）

**説明**: 軌跡の直線度合い（0.0-1.0）。1.0が完全な直線

**影響**:
- **低い値（0.5-0.6）**: 曲がった軌跡も検出
- **高い値（0.8-0.9）**: ほぼ直線のみ検出

**推奨値**: 0.7

**計算方法**: 主成分分析（PCA）による固有値比

---

#### exclude_bottom_ratio（画面下部除外率）

**説明**: 画面下部の除外範囲（0.0-1.0）

**用途**: 地上の建物や木などの誤検出を防ぐ

**推奨値**:
- 空のみ撮影: 0.0
- 地平線が写る: 0.0625（1/16）
- 建物が多い: 0.125（1/8）

**例**:
```
画面高さ 1080px × 0.0625 = 下から67.5px を除外
```

---

## 感度プリセット

### プリセット一覧

| プリセット | diff_threshold | min_brightness | 用途 | 誤検出率 |
|-----------|----------------|----------------|------|---------|
| `low` | 40 | 220 | 明るい流星のみ | 低 |
| `medium` | 30 | 200 | バランス型（推奨） | 中 |
| `high` | 20 | 180 | 暗い流星も検出 | やや高 |
| `fireball` | 15 | 150 | 火球専用 | 高 |

### プリセットの適用

```bash
# generate_compose.pyで設定
python generate_compose.py --sensitivity high

# または docker-compose.ymlで直接設定
environment:
  - SENSITIVITY=high
```

### プリセット別の特徴

#### low（低感度）

**特徴**:
- 明るい流星のみ検出
- 誤検出が最も少ない
- 暗い流星は見逃す

**推奨環境**:
- 市街地（光害が多い）
- 満月期
- テスト運用時

**検出例**:
- -3等級以上の明るい流星
- 火球

---

#### medium（中感度）★推奨

**特徴**:
- バランスの取れた設定
- 多くの環境で良好な結果
- 誤検出と見逃しのバランスが良い

**推奨環境**:
- 郊外
- 標準的な観測環境
- 長期運用

**検出例**:
- 0等級～-3等級の流星
- 一般的な散在流星
- 流星群の流星

---

#### high（高感度）

**特徴**:
- 暗い流星も検出
- 誤検出がやや増える
- 見逃しが少ない

**推奨環境**:
- 山間部（光害が少ない）
- 新月期
- 流星群極大期

**検出例**:
- +2等級～-5等級の流星
- 微光流星

**注意点**:
- 航空機を誤検出する可能性
- ログ確認が必要

---

#### fireball（火球専用）

**特徴**:
- 最も敏感な設定
- 長時間・大きな物体を検出
- 誤検出が多い

**推奨環境**:
- 火球専用観測
- 短期集中観測

**検出例**:
- -4等級以上の火球
- 長時間光る流星

**追加設定**:
```python
max_duration = 20.0  # 長時間OK
min_speed = 20.0     # ゆっくりでもOK
min_linearity = 0.6  # 多少曲がってもOK
```

---

## 処理スケール設定

### SCALE パラメータ

**説明**: フレームを縮小して処理する比率（0.0-1.0）

**影響**:

| SCALE | 処理サイズ（1920x1080の場合） | CPU使用率 | メモリ使用量 | 検出精度 |
|-------|------------------------------|-----------|-------------|---------|
| 1.0 | 1920x1080（等倍） | 100% | 400MB | 最高 |
| 0.5 | 960x540（推奨） | 30% | 200MB | 高 |
| 0.25 | 480x270 | 15% | 100MB | 中 |

### 推奨設定

```mermaid
flowchart TD
    Start["ハードウェア性能"]
    CheckCPU{"CPUコア数"}
    CheckMem{"メモリ容量"}
    CheckCamera{"カメラ数"}

    Scale100["SCALE=1.0<br/>最高精度"]
    Scale050["SCALE=0.5<br/>推奨"]
    Scale025["SCALE=0.25<br/>省リソース"]

    Start --> CheckCPU
    CheckCPU -->|"8コア以上"| Scale100
    CheckCPU -->|"4コア"| CheckMem
    CheckCPU -->|"2コア以下"| Scale025

    CheckMem -->|"16GB以上"| Scale050
    CheckMem -->|"8GB以下"| CheckCamera

    CheckCamera -->|"1-2台"| Scale050
    CheckCamera -->|"3台以上"| Scale025

    style Scale050 fill:#00ff88
```

### スケール別の特徴

#### SCALE=1.0（等倍処理）

**メリット**:
- 最高精度
- 小さな流星も検出
- 軌跡が正確

**デメリット**:
- CPU使用率が高い（90-100%）
- メモリ消費が大きい
- 多数カメラには不向き

**推奨環境**:
- 高性能PC（8コア以上、16GB RAM以上）
- カメラ1-2台
- 短期観測

---

#### SCALE=0.5（推奨）

**メリット**:
- 精度とパフォーマンスのバランスが良い
- CPU使用率30-50%
- 多数カメラに対応可能

**デメリット**:
- 微小な流星は検出困難

**推奨環境**:
- 標準的PC（4コア、8GB RAM）
- カメラ3-5台
- 長期運用

---

#### SCALE=0.25（省リソース）

**メリット**:
- 最も軽い
- CPU使用率15-20%
- 多数カメラ対応

**デメリット**:
- 検出精度が低下
- 小さな流星は見逃す

**推奨環境**:
- 低スペックPC（2コア、4GB RAM）
- カメラ6台以上
- 明るい流星のみ検出

---

## 天文薄暮時間帯設定

### ENABLE_TIME_WINDOW の仕組み

**説明**: 天文薄暮期間（前日の日没～翌日の日出）のみ検出を有効化

```mermaid
gantt
    title 1日の検出スケジュール
    dateFormat HH:mm
    axisFormat %H:%M

    section 検出OFF
    日中（検出無効）: done, day, 06:00, 10h

    section 検出ON
    夜間（検出有効）: active, night1, 16:00, 14h
    夜間（検出有効）: active, night2, 00:00, 6h
```

### 設定方法

```bash
# generate_compose.pyで設定
python generate_compose.py \
  --enable-time-window true \
  --latitude 35.6762 \
  --longitude 139.6503

# docker-compose.ymlで直接設定
environment:
  - ENABLE_TIME_WINDOW=true
  - LATITUDE=35.6762
  - LONGITUDE=139.6503
  - TIMEZONE=Asia/Tokyo
```

### 座標の取得方法

#### 方法1: Google Mapsで取得

1. Google Mapsで観測地点を右クリック
2. 表示される座標をコピー
3. 例: `35.6762, 139.6503`

#### 方法2: コマンドラインで取得

```bash
# curlで現在地の座標を取得
curl -s "https://ipapi.co/json/" | jq '.latitude, .longitude'
```

### 主要都市の座標

| 都市 | 緯度 | 経度 |
|-----|------|------|
| 東京 | 35.6762 | 139.6503 |
| 大阪 | 34.6937 | 135.5023 |
| 札幌 | 43.0642 | 141.3469 |
| 福岡 | 33.5904 | 130.4017 |
| 那覇 | 26.2124 | 127.6809 |
| 富士山頂 | 35.3606 | 138.7274 |

### 時間帯の確認

```bash
# ダッシュボードのAPIで確認
curl "http://localhost:8080/detection_window?lat=35.6762&lon=139.6503" | jq

# レスポンス例
{
  "start": "2026-02-01 16:45:23",
  "end": "2026-02-02 06:12:45",
  "enabled": true,
  "latitude": 35.6762,
  "longitude": 139.6503
}
```

---

## ハードウェア別推奨設定

### 低スペックPC（2コア、4GB RAM）

```yaml
environment:
  - SENSITIVITY=medium
  - SCALE=0.25
  - BUFFER=10
  - EXTRACT_CLIPS=false  # MP4を保存しない
  - ENABLE_TIME_WINDOW=true
```

**カメラ数**: 最大2台

---

### 標準PC（4コア、8GB RAM）★推奨

```yaml
environment:
  - SENSITIVITY=medium
  - SCALE=0.5
  - BUFFER=15
  - EXTRACT_CLIPS=true
  - ENABLE_TIME_WINDOW=true
```

**カメラ数**: 3-5台

---

### 高性能PC（8コア以上、16GB RAM以上）

```yaml
environment:
  - SENSITIVITY=high
  - SCALE=0.75
  - BUFFER=20
  - EXTRACT_CLIPS=true
  - ENABLE_TIME_WINDOW=false  # 常時検出
```

**カメラ数**: 8台以上

---

### Raspberry Pi 4（4GB）

```yaml
environment:
  - SENSITIVITY=low
  - SCALE=0.25
  - BUFFER=10
  - EXTRACT_CLIPS=false
  - ENABLE_TIME_WINDOW=true
```

**カメラ数**: 最大1台

**注意**: 長時間運用時はヒートシンク必須

---

## チューニング方法

### ステップ1: ベースライン設定

```bash
# 推奨設定で開始
python generate_compose.py \
  --sensitivity medium \
  --scale 0.5 \
  --buffer 15

./meteor-docker.sh start
```

---

### ステップ2: 誤検出の確認

```bash
# 1時間運用後、検出結果を確認
ls -lh ./detections/camera1_*/

# ダッシュボードで確認
open http://localhost:8080/
```

**誤検出の種類**:
- 航空機（点滅する光、ゆっくり移動）
- 昆虫（不規則な動き）
- 雲の移動（広範囲、ゆっくり）
- 車のヘッドライト（画面下部）

---

### ステップ3: 感度調整

#### 誤検出が多い場合

```bash
# 感度を下げる
python generate_compose.py --sensitivity low

# または画面下部除外を増やす
python generate_compose.py --exclude-bottom 0.125
```

#### 見逃しが多い場合

```bash
# 感度を上げる
python generate_compose.py --sensitivity high
```

---

### ステップ4: パフォーマンス調整

```bash
# リソース使用率を確認
./meteor-docker.sh status

# CPU使用率が高い（70%以上）
python generate_compose.py --scale 0.25

# メモリ使用量が多い
python generate_compose.py --buffer 10
```

---

### ステップ5: 長期運用

```bash
# 1週間運用後の統計
find ./detections -name "*.mp4" | wc -l

# 誤検出率を計算
# 誤検出率 = 誤検出数 / 総検出数

# 目標: 誤検出率 < 20%
```

---

## 環境別チューニング例

### 市街地（光害あり）

**課題**: 街灯、車のライト、建物の照明が多い

**推奨設定**:
```yaml
environment:
  - SENSITIVITY=low
  - SCALE=0.5
  - EXCLUDE_BOTTOM=0.125  # 下部1/8を除外
  - ENABLE_TIME_WINDOW=true
```

**params調整**:
```python
params.min_brightness = 220  # 明るい流星のみ
params.min_speed = 70        # 遅い物体を除外
```

---

### 郊外（標準環境）

**推奨設定**:
```yaml
environment:
  - SENSITIVITY=medium
  - SCALE=0.5
  - EXCLUDE_BOTTOM=0.0625
  - ENABLE_TIME_WINDOW=true
```

**そのままでOK**

---

### 山間部（光害なし）

**課題**: 暗い流星も検出したい

**推奨設定**:
```yaml
environment:
  - SENSITIVITY=high
  - SCALE=0.75
  - EXCLUDE_BOTTOM=0.0
  - ENABLE_TIME_WINDOW=true
```

**params調整**:
```python
params.min_brightness = 180
params.diff_threshold = 20
```

---

## トラブルシューティング

### 検出数が少なすぎる

**原因**:
- 感度が低すぎる
- 時間帯設定の問題

**対策**:
```bash
# 感度を上げる
python generate_compose.py --sensitivity high

# 時間帯制限を無効化
python generate_compose.py --enable-time-window false
```

---

### 誤検出が多すぎる

**原因**:
- 感度が高すぎる
- 航空機や昆虫を検出

**対策**:
```bash
# 感度を下げる
python generate_compose.py --sensitivity low

# 画面下部を除外
python generate_compose.py --exclude-bottom 0.125
```

---

### CPUが高い

**対策**:
```bash
# 処理スケールを下げる
python generate_compose.py --scale 0.25

# カメラ数を減らす
# streamersファイルから一部削除
```

---

### ディスク容量が足りない

**対策**:
```bash
# MP4保存を無効化
# docker-compose.ymlで EXTRACT_CLIPS=false

# バッファを減らす
python generate_compose.py --buffer 10

# 古いファイルを削除
./meteor-docker.sh clean
```

---

## 関連ドキュメント

- [OPERATIONS_GUIDE.md](OPERATIONS_GUIDE.md) - 運用ガイド
- [DETECTOR_COMPONENTS.md](DETECTOR_COMPONENTS.md) - 検出アルゴリズム詳細
- [DOCKER_ARCHITECTURE.md](DOCKER_ARCHITECTURE.md) - Docker構成
- [SECURITY.md](SECURITY.md) - セキュリティガイド
