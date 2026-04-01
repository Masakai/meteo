# 多地点流星三角測量システム

---

**Copyright (c) 2026 Masanori Sakai**

Licensed under the MIT License

---

## 概要

複数の観測拠点に配置した流星検出システムからの検出結果を統合し、同一流星を2拠点以上から同時観測した場合に三角測量を行い、流星の3D軌道（緯度・経度・高度）を算出するシステムです。

SonotaCo Network や Global Meteor Network (GMN) と同じ原理に基づいています。

## 全体アーキテクチャ

```mermaid
graph TB
    subgraph "拠点A（例: 富士北麓）"
        RTSP_A1["RTSPカメラ 1"]
        RTSP_A2["RTSPカメラ 2"]
        Det_A1["meteor_detector<br/>カメラ1"]
        Det_A2["meteor_detector<br/>カメラ2"]
        JSONL_A["detections.jsonl"]
        Reporter_A["station_reporter.py"]
        StationJSON_A["station.json"]

        RTSP_A1 --> Det_A1
        RTSP_A2 --> Det_A2
        Det_A1 -->|"検出結果書込"| JSONL_A
        Det_A2 -->|"検出結果書込"| JSONL_A
        JSONL_A -->|"JSONL監視"| Reporter_A
        StationJSON_A -->|"カメラ方位/FOV"| Reporter_A
    end

    subgraph "拠点B（例: 箱根）"
        RTSP_B["RTSPカメラ"]
        Det_B["meteor_detector"]
        JSONL_B["detections.jsonl"]
        Reporter_B["station_reporter.py"]
        StationJSON_B["station.json"]

        RTSP_B --> Det_B
        Det_B -->|"検出結果書込"| JSONL_B
        JSONL_B -->|"JSONL監視"| Reporter_B
        StationJSON_B -->|"カメラ方位/FOV"| Reporter_B
    end

    subgraph "三角測量サーバ（中央）"
        API["Flask API<br/>/api/detections"]
        Matcher["EventMatcher<br/>イベントマッチング"]
        Triangulator["Triangulator<br/>3D三角測量"]
        DB["SQLite<br/>triangulation.db"]
        MapUI["3D Map UI<br/>Deck.gl + MapLibre"]

        API --> Matcher
        Matcher -->|"時刻マッチ"| Triangulator
        Triangulator -->|"結果保存"| DB
        DB -->|"結果取得"| MapUI
    end

    Reporter_A -->|"HTTP POST<br/>天球座標付き検出"| API
    Reporter_B -->|"HTTP POST<br/>天球座標付き検出"| API

    User["ユーザー<br/>ブラウザ"] -->|"HTTP GET /"| MapUI

    style Reporter_A fill:#e94560,color:#fff
    style Reporter_B fill:#e94560,color:#fff
    style Triangulator fill:#4ecca3,color:#000
    style MapUI fill:#58a6ff,color:#000
```

## ファイル構成

```mermaid
graph LR
    subgraph "triangulation/ パッケージ"
        models["models.py<br/>データクラス定義"]
        geo["geo_utils.py<br/>WGS84座標変換"]
        p2s["pixel_to_sky.py<br/>ピクセル→天球変換"]
        matcher["event_matcher.py<br/>イベントマッチング"]
        tri["triangulator.py<br/>3D三角測量"]
    end

    subgraph "アプリケーション"
        server["triangulation_server.py<br/>Flask中央サーバ"]
        templates["triangulation_templates.py<br/>3D地図UI"]
        reporter["station_reporter.py<br/>拠点サイドカー"]
        demo["demo_triangulation.py<br/>デモ用"]
    end

    subgraph "設定・Docker"
        station["station.json.sample<br/>拠点設定サンプル"]
        df_rep["Dockerfile.reporter"]
        df_tri["Dockerfile.triangulation"]
    end

    server --> models
    server --> matcher
    server --> templates
    reporter --> models
    reporter --> p2s
    matcher --> tri
    tri --> geo
    p2s --> models
    p2s --> geo
```

| ファイル | 役割 |
|---|---|
| `triangulation/__init__.py` | パッケージ初期化 |
| `triangulation/models.py` | StationConfig, CameraCalibration, DetectionReport, TriangulatedMeteor |
| `triangulation/geo_utils.py` | WGS84座標変換 (LLA↔ECEF, ENU↔ECEF, 方位仰角↔ENU) |
| `triangulation/pixel_to_sky.py` | ピクセル座標 → 方位角・仰角変換 |
| `triangulation/event_matcher.py` | 時間窓ベースのイベントマッチング |
| `triangulation/triangulator.py` | スキューライン最近接点法による3D位置決定 |
| `triangulation_server.py` | Flask中央サーバ (API + SQLite + 3D地図UI) |
| `triangulation_templates.py` | Deck.gl + MapLibre GL JS による3D地図 |
| `station_reporter.py` | 各拠点のサイドカー (JSONL監視 → 天球変換 → POST) |
| `demo_triangulation.py` | デモ用サーバ起動スクリプト（サンプルデータ投入） |
| `station.json.sample` | 拠点設定ファイルのサンプル |
| `Dockerfile.reporter` | station_reporter 用コンテナ |
| `Dockerfile.triangulation` | 三角測量サーバ用コンテナ |

## データフロー

```mermaid
sequenceDiagram
    participant Camera as RTSPカメラ
    participant Detector as meteor_detector
    participant JSONL as detections.jsonl
    participant Reporter as station_reporter
    participant Server as triangulation_server
    participant DB as SQLite
    participant UI as 3D Map UI

    Camera->>Detector: RTSPフレーム
    Detector->>JSONL: 流星検出結果<br/>(ピクセル座標, タイムスタンプ)

    Reporter->>JSONL: ポーリング監視 (5秒間隔)
    JSONL-->>Reporter: 新規検出行

    Note over Reporter: ピクセル座標 → 天球座標<br/>(方位角・仰角) に変換

    Reporter->>Server: POST /api/detections<br/>{station_id, start_az, start_el, ...}

    Note over Server: EventMatcher:<br/>時間窓±5秒で他拠点の検出と照合

    alt 他拠点の検出とマッチ
        Note over Server: Triangulator:<br/>2本の観測線の最近接点を計算<br/>→ ECEF座標 → 緯度経度高度
        Server->>DB: 三角測量結果を保存
    else マッチなし
        Note over Server: バッファに保持 (30秒)
    end

    UI->>Server: GET /api/triangulated
    Server-->>UI: 三角測量済み流星リスト
    Note over UI: Deck.gl で3D描画<br/>流星軌道 + 地表投影 + 拠点FOV
```

## 核心アルゴリズム

### 1. ピクセル→天球座標変換 (pixel_to_sky.py)

カメラ画像上のピクセル座標を、天球上の方位角・仰角に変換します。

```mermaid
graph LR
    Pixel["ピクセル座標<br/>(px, py)"] --> Norm["正規化座標<br/>nx, ny ∈ [-1, 1]"]
    Norm --> CamDir["カメラ座標系<br/>方向ベクトル<br/>(nx/fx, ny/fy, 1)"]
    CamDir --> Roll["ロール回転<br/>(Z軸周り)"]
    Roll --> CamToENU["カメラ→ENU<br/>座標系変換"]
    CamToENU --> Elev["仰角回転<br/>(East軸周り)"]
    Elev --> Az["方位角回転<br/>(Up軸周り)"]
    Az --> AzEl["天球座標<br/>(方位角, 仰角)"]

    style Pixel fill:#58a6ff,color:#000
    style AzEl fill:#4ecca3,color:#000
```

**ピンホールカメラモデル（直線射影）の処理手順:**

1. ピクセルを正規化: `nx = (px - W/2) / (W/2)`, `ny = (H/2 - py) / (H/2)`
2. FOVから焦点距離を算出: `fx = 1 / tan(FOV_h / 2)`
3. カメラ座標系で方向ベクトルを生成: `(nx/fx, ny/fy, 1)` → 正規化
4. ロール → カメラ→ENU変換 → 仰角回転 → 方位角回転を順に適用
5. 結果のENU方向ベクトルから `atan2` で方位角・仰角を算出

### 2. 三角測量 (triangulator.py)

2つの観測拠点からの観測線（方位角・仰角で定義される3D直線）の最近接点を求めます。

```mermaid
graph TB
    subgraph "入力"
        StA["拠点A<br/>(lat, lon, alt)"]
        DirA["観測方向A<br/>(az, el)"]
        StB["拠点B<br/>(lat, lon, alt)"]
        DirB["観測方向B<br/>(az, el)"]
    end

    subgraph "座標変換"
        ECEF_A["拠点A ECEF位置"]
        ECEF_B["拠点B ECEF位置"]
        Vec_A["観測方向A<br/>ECEFベクトル"]
        Vec_B["観測方向B<br/>ECEFベクトル"]
    end

    subgraph "最近接点計算"
        Line["2本のスキューライン<br/>L1: P1 + t*d1<br/>L2: P2 + s*d2"]
        Solve["連立方程式を解く<br/>t = (b*e - c*d) / (a*c - b²)<br/>s = (a*e - b*d) / (a*c - b²)"]
        Mid["最近接2点の中点<br/>= 流星推定位置"]
        Miss["miss_distance<br/>= 三角測量精度指標"]
    end

    subgraph "出力"
        LLA["緯度, 経度, 高度(km)"]
        Check["高度チェック<br/>40-200 km"]
    end

    StA --> ECEF_A
    StB --> ECEF_B
    DirA --> Vec_A
    DirB --> Vec_B
    ECEF_A --> Line
    ECEF_B --> Line
    Vec_A --> Line
    Vec_B --> Line
    Line --> Solve
    Solve --> Mid
    Solve --> Miss
    Mid -->|"ECEF→LLA変換"| LLA
    LLA --> Check

    style Mid fill:#4ecca3,color:#000
    style Miss fill:#f0883e,color:#000
    style Check fill:#e94560,color:#fff
```

**スキューラインの最近接点（Closest Point of Approach）:**

2本の直線 `L1: P1 + t*d1` と `L2: P2 + s*d2` に対し:

```
w0 = P1 - P2
a = dot(d1, d1),  b = dot(d1, d2),  c = dot(d2, d2)
d = dot(d1, w0),  e = dot(d2, w0)
denom = a*c - b²

t = (b*e - c*d) / denom
s = (a*e - b*d) / denom

closest_1 = P1 + t*d1
closest_2 = P2 + s*d2
midpoint = (closest_1 + closest_2) / 2    ← 流星推定位置
miss_distance = |closest_1 - closest_2|   ← 精度指標
```

### 3. イベントマッチング (event_matcher.py)

```mermaid
graph TB
    New["新規検出レポート到着<br/>(拠点A)"]
    Buffer["スライディングウィンドウバッファ<br/>(直近30秒の検出を保持)"]
    Search["異なる拠点の検出を検索<br/>時間差 ≤ 5秒"]

    New --> Buffer
    Buffer --> Search

    Search -->|"候補あり"| Try["三角測量を試行"]
    Search -->|"候補なし"| Wait["バッファに保持して待機"]

    Try -->|"高度 40-200km"| Success["マッチ成功<br/>TriangulatedMeteor 生成"]
    Try -->|"高度範囲外"| Reject["棄却<br/>(偶然の時刻一致)"]

    style New fill:#58a6ff,color:#000
    style Success fill:#4ecca3,color:#000
    style Reject fill:#e94560,color:#fff
```

**マッチング条件:**
1. **異なる拠点** からの検出であること
2. **時間差が±5秒以内** (NTP同期前提、流星持続0.1〜2秒)
3. **三角測量結果の高度が40〜200km** (典型的な流星の消滅高度範囲)

## 座標系

```mermaid
graph TB
    subgraph "WGS84 (入力/出力)"
        LLA["LLA<br/>緯度(°), 経度(°), 高度(m)"]
    end

    subgraph "ECEF (内部計算)"
        ECEF["ECEF<br/>地球中心直交座標 (m)<br/>X: 赤道面・本初子午線<br/>Y: 赤道面・東経90°<br/>Z: 北極方向"]
    end

    subgraph "ENU (ローカル)"
        ENU["ENU<br/>East(東), North(北), Up(上)<br/>観測拠点を原点とする<br/>接平面座標系"]
    end

    subgraph "カメラ座標系"
        CAM["カメラ座標<br/>X: 右, Y: 上, Z: 前(光軸)"]
    end

    LLA <-->|"lla_to_ecef<br/>ecef_to_lla"| ECEF
    ENU <-->|"enu_rotation_matrix"| ECEF
    CAM -->|"pixel_to_sky<br/>(回転行列適用)"| ENU
    ENU <-->|"az_el_to_enu<br/>enu_to_az_el"| AzEl["方位角・仰角"]

    style LLA fill:#58a6ff,color:#000
    style ECEF fill:#f0883e,color:#000
    style ENU fill:#4ecca3,color:#000
    style CAM fill:#e94560,color:#fff
```

## 拠点設定ファイル (station.json)

各観測拠点に1つ配置する設定ファイル。`station.json.sample` を参考に作成してください。

```json
{
  "station_id": "fuji-north",
  "station_name": "富士北麓観測所",
  "latitude": 35.3606,
  "longitude": 138.7274,
  "altitude": 2400.0,
  "triangulation_server_url": "https://triangulation.example.com",
  "api_key": "your-secret-api-key-here",
  "cameras": {
    "camera1_10_0_1_25": {
      "azimuth": 90.0,
      "elevation": 45.0,
      "roll": 0.0,
      "fov_horizontal": 90.0,
      "fov_vertical": 60.0,
      "resolution": [960, 540]
    }
  }
}
```

| フィールド | 説明 |
|---|---|
| `station_id` | 拠点の一意な識別子 |
| `latitude`, `longitude` | WGS84緯度経度 (度) |
| `altitude` | WGS84楕円体高 (メートル) |
| `triangulation_server_url` | 三角測量サーバのURL |
| `api_key` | API認証キー |
| `cameras.{name}.azimuth` | カメラ光軸中心の方位角 (度, 0=北, 90=東) |
| `cameras.{name}.elevation` | カメラ光軸中心の仰角 (度, 0=水平, 90=天頂) |
| `cameras.{name}.roll` | 光軸周りの回転 (度, 通常0) |
| `cameras.{name}.fov_horizontal` | 水平視野角 (度) |
| `cameras.{name}.fov_vertical` | 垂直視野角 (度) |
| `cameras.{name}.resolution` | 検出処理時の解像度 [幅, 高さ] (SCALE適用後) |

## API仕様

### POST /api/detections

拠点からの検出レポートを受信する。

**リクエスト:**
```json
{
  "station_id": "fuji-north",
  "api_key": "your-secret-key",
  "detections": [
    {
      "camera_name": "camera1_10_0_1_25",
      "timestamp": "2026-02-10T00:11:08.844611+09:00",
      "start_az": 95.3,
      "start_el": 62.1,
      "end_az": 96.8,
      "end_el": 58.4,
      "duration": 0.483,
      "confidence": 0.65,
      "peak_brightness": 218.1,
      "detection_id": "det_649eeef920f7d2333025"
    }
  ]
}
```

**レスポンス:**
```json
{
  "status": "ok",
  "received": 1,
  "triangulated": 0
}
```

### GET /api/triangulated

三角測量結果を取得する。

**パラメータ:**
- `since` (任意): ISO8601日時。この日時以降の結果のみ返す
- `limit` (任意): 最大件数 (デフォルト100, 最大500)

### GET /api/stations

登録済み拠点の一覧を取得する。

### GET /api/stats

統計情報（総レポート数、三角測量数、拠点数）を取得する。

### GET /

3D地図UIを表示する。

## 3D地図UIの機能

Deck.gl + MapLibre GL JS による3Dインタラクティブ地図。

| 要素 | 説明 |
|---|---|
| 流星軌道ライン | 始点(緑)→終点(赤)の3Dライン。信頼度で色分け |
| 垂直ドロップライン | 地表から流星端点への灰色垂直線 (高度の視覚化) |
| 地表投影線 | 流星軌道を地表に投影した破線 (地上位置の確認) |
| 観測拠点マーカー | 各拠点の位置を赤いドットで表示 |
| 観測ライン | 拠点から流星への薄いピンク線 (どの拠点が観測したか) |
| FOV扇形 | 各カメラの視野範囲を扇形で表示 |
| ツールチップ | 流星にホバーで詳細情報 (時刻, 高度, 速度, 誤差, 信頼度) |

**操作:**
- ドラッグ: 地図移動
- Ctrl+ドラッグ: 3D傾斜
- 右ドラッグ: 回転
- 高度スケール スライダー: 高度の強調倍率 (1x〜100x)

## デプロイ構成

### 各観測拠点

既存の流星検出Docker環境に `station_reporter` サイドカーを追加する。

```bash
# station.json を作成した状態で
python generate_compose.py --station-config station.json
docker compose up -d
```

`generate_compose.py` は `station.json` が指定されている場合、自動的に `station-reporter` サービスを docker-compose.yml に追加します。

### 三角測量サーバ（中央）

```bash
# 全拠点の station.json を stations/ ディレクトリにまとめる
mkdir stations/
cp /path/to/fuji-north.json stations/
cp /path/to/hakone.json stations/

# サーバ起動
docker build -f Dockerfile.triangulation -t triangulation-server .
docker run -d -p 8090:8090 \
  -v ./stations:/app/stations \
  -v ./triangulation.db:/app/triangulation.db \
  triangulation-server
```

環境変数:
- `STATIONS_CONFIG`: 拠点設定ファイルのパスまたはディレクトリ (デフォルト: `stations/`)
- `DB_PATH`: SQLiteデータベースのパス (デフォルト: `triangulation.db`)
- `HOST`: バインドアドレス (デフォルト: `0.0.0.0`)
- `PORT`: ポート番号 (デフォルト: `8090`)

## 精度に関する考慮事項

### カメラキャリブレーション

三角測量精度の最大のボトルネックは**カメラの指向方位の精度**です。

| 方位精度 | 高度100kmでの位置誤差 |
|---|---|
| ±1° | 約±1.7 km |
| ±2° | 約±3.5 km |
| ±5° | 約±8.7 km |

コンパスと傾斜計による手動計測では2〜3°程度の精度になります。より高精度が必要な場合は、恒星の位置を使ったキャリブレーション（将来実装予定）を行ってください。

### 時刻同期

NTPによるシステム時刻同期が前提です。通常のLinux/Dockerサーバであればミリ秒精度のNTP同期が標準で行われます。流星の持続時間（0.1〜2秒）に対してマッチング時間窓（±5秒）は十分です。

### 拠点間距離

理想的な拠点間距離は **30〜200km** です。

- 近すぎる場合: 視差が小さく、三角測量の精度が低下（miss_distanceが大きくなる）
- 遠すぎる場合: 同一流星を両拠点で観測できる確率が低下

## テスト

```bash
# 三角測量関連の全テストを実行
python3 -m pytest tests/test_geo_utils.py tests/test_pixel_to_sky.py \
                   tests/test_triangulator.py tests/test_event_matcher.py -v

# デモサーバ起動（サンプルデータ付き）
python3 demo_triangulation.py
# → http://localhost:8090/ で3D地図を確認
```

テスト一覧 (40件):

| テストファイル | 件数 | 内容 |
|---|---|---|
| `tests/test_geo_utils.py` | 17 | LLA↔ECEF変換、方位仰角↔ENU変換、観測線計算 |
| `tests/test_pixel_to_sky.py` | 11 | ピクセル→天球変換の中心・端・対称性・ロール |
| `tests/test_triangulator.py` | 7 | 最近接点計算、既知位置の三角測量再現、高度範囲チェック |
| `tests/test_event_matcher.py` | 5 | 同一拠点排除、時間窓、マッチ成功、重複排除、プルーニング |
