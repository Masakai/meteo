# 自作流星検出システムに三角測量を組み込み、流星の高度・軌道を3Dマップに描画した話

流星の動画クリップが録れるのは楽しい。しかし「どの高度で発光したか」「地面からどんな角度で突入したか」は、1台のカメラだけではわからない。2拠点以上から同じ流星を撮れば三角測量で3D軌道が求まる――SonotaCo Network や Global Meteor Network（GMN）がやっていることをそのまま自分のシステムに組み込んでみた。

本記事では、既存の流星検出 OSS「[Meteo](https://github.com/Masakai/meteo)」に追加した三角測量システムの設計・実装・アルゴリズムを解説する。新規外部依存は NumPy のみ（既存）、地図 UI は Deck.gl + MapLibre を CDN で使用。

---

## システム全体像

### ハブ＆スポーク型アーキテクチャ

既存の各拠点は Docker Compose で動いており、検出結果を `detections.jsonl` に追記している。これを変えずに済む設計にした。

```
拠点A（例: 富士北麓）
  ├─ meteor_detector × N  →  detections.jsonl
  └─ station_reporter        ← 新規サイドカー
       │ HTTP POST（天球座標付き検出）
       ▼
三角測量サーバ（中央）
  ├─ EventMatcher  （時刻±5秒でマッチング）
  ├─ Triangulator  （スキューライン最近接点）
  └─ Deck.gl 3Dマップ

拠点B（例: 箱根）
  └─ station_reporter  ──────────────────────┘
```

**設計方針:**

- 既存コンテナはノータッチ。`station.json` を置くだけで `station_reporter` サイドカーが自動追加される（`generate_compose.py` を修正）
- 検出数は1夜で 0〜20件程度なので MQ は不要。HTTP POST で十分
- 地図 UI はビルドなしで使える CDN ベース

---

## ピクセル座標 → 天球座標変換

流星検出器が出力するのは **ピクセル座標** だが、三角測量に必要なのは **方位角・仰角** だ。ピンホールカメラモデル（直線射影）で変換する。

### アルゴリズム

1. **正規化**: `nx = (px - W/2) / (W/2)`, `ny = (H/2 - py) / (H/2)`
2. **焦点距離換算**: `fx = 1 / tan(FOV_h / 2)`
3. **カメラ座標系の方向ベクトル**: `v = (nx/fx, ny/fy, 1)` → 正規化
4. **回転適用**: ロール → カメラ→ENU → 仰角 → 方位角 の順に回転行列を乗算
5. **方位・仰角抽出**: `atan2` でENUベクトルから算出

### 実装上のハマりポイント

方位角の回転行列で痛い目を見た。

コンパス方位（0=北, 90=東）は **時計回り** だが、数学の標準的な角度は反時計回りなので符号を誤りやすい。

```python
# 誤: 反時計回り（数学的標準）
R_az = np.array([
    [ cos_az, -sin_az, 0],
    [ sin_az,  cos_az, 0],
    [0,        0,      1],
])

# 正: 時計回り（コンパス方位に合わせる）
R_az = np.array([
    [ cos_az, sin_az, 0],
    [-sin_az, cos_az, 0],
    [0,       0,      1],
])
```

テストで「カメラ方位 90°（東向き）の中心ピクセルは方位角 90° になるはず」という検証を書いておいたおかげで、すぐ気づけた。

```python
# tests/test_pixel_to_sky.py より
def test_center_pixel_returns_camera_azimuth():
    calib = CameraCalibration(
        azimuth=90.0, elevation=45.0, roll=0.0,
        fov_horizontal=90.0, fov_vertical=60.0,
        resolution=(960, 540),
    )
    az, el = pixel_to_sky(480, 270, calib)  # 中心ピクセル
    assert abs(az - 90.0) < 0.1
    assert abs(el - 45.0) < 0.1
```

---

## 三角測量: スキューライン最近接点法

2つの観測拠点から「この方向に流星がいた」という観測線（3D直線）が引ける。2本の直線は空間的に交わらない（スキューライン）のが普通なので、最も近づく2点の中点を流星位置と推定する。

### 座標系の選択

**ECEF（地球中心・地球固定）座標**を使った。理由:

- 地球の曲率を自動的に考慮できる
- 拠点間の距離が数十kmになると、平面近似 ENU では誤差が無視できない
- NumPy だけで完結する

```
LLA（緯度経度高度） ↔ ECEF（地球中心直交）変換
ENU（東北上のローカル座標） ↔ ECEF 変換
```

### 最近接点の計算

2直線 `L1: P1 + t*d1`、`L2: P2 + s*d2` の最近接点を解く。

```python
w0 = P1 - P2
a, b, c = dot(d1,d1), dot(d1,d2), dot(d2,d2)
d, e    = dot(d1,w0), dot(d2,w0)
denom   = a*c - b**2        # 平行なら 0 → ガード必要

t = (b*e - c*d) / denom
s = (a*e - b*d) / denom

closest1 = P1 + t * d1
closest2 = P2 + s * d2
midpoint = (closest1 + closest2) / 2   # 流星推定位置
miss_distance = norm(closest2 - closest1)  # 精度指標
```

`miss_distance` が小さいほど三角測量の精度が高い。これを信頼度スコアに変換して地図の色分けに使っている。

### 高度の妥当性チェック

算出した高度が 40〜200 km の範囲外なら「外れ検出のマッチ」として棄却する。流星の発光高度は経験的に 70〜120 km が中心なので、これで誤マッチの大半を弾ける。

```python
MIN_ALTITUDE_KM = 40
MAX_ALTITUDE_KM = 200

_, _, alt_km = ecef_to_lla(midpoint)
if not (MIN_ALTITUDE_KM <= alt_km <= MAX_ALTITUDE_KM):
    return None  # 棄却
```

---

## イベントマッチング

「同じ流星を複数拠点が検出した」と判定するには、**時刻の一致** と **角度の妥当性** を見る。

### 時間窓ベースのスライディングバッファ

```python
# event_matcher.py の概略
class EventMatcher:
    def __init__(self, time_window_sec=5.0, buffer_sec=30.0):
        self._buffer: list[DetectionReport] = []

    def add_detection(self, report: DetectionReport) -> MatchedEvent | None:
        self._expire_old(report.timestamp)
        # 異なる拠点の既存検出と時間窓内でマッチするか探す
        for candidate in reversed(self._buffer):
            if candidate.station_id == report.station_id:
                continue
            dt = abs((report.timestamp - candidate.timestamp).total_seconds())
            if dt <= self.time_window_sec:
                result = triangulate_meteor(candidate, report)
                if result:
                    return MatchedEvent(candidate, report, result)
        self._buffer.append(report)
        return None
```

**時間窓 ±5 秒** の根拠:
- NTP 同期が取れていれば誤差は数 ms 以下
- 流星の持続時間は 0.1〜2 秒
- ±5 秒は十分な余裕で、誤マッチは高度チェックで弾く

---

## 3D 地図 UI（Deck.gl + MapLibre GL JS）

ビルドなし・CDN のみで動く 3D マップを実装した。

```
https://unpkg.com/deck.gl@9.1.7/dist.min.js
https://unpkg.com/maplibre-gl@4.7.1/dist/maplibre-gl.js
```

### 描画レイヤー構成

| レイヤー | 表現 |
|---|---|
| `LineLayer`（流星軌道） | 始点〜終点を3D空間で結ぶ線 |
| `ScatterplotLayer`（流星端点） | 始点（緑）・終点（赤） |
| `LineLayer`（ドロップライン） | 各端点から地表への垂直線 |
| `LineLayer`（地表投影） | 軌道の地表面への投影（破線） |
| `ScatterplotLayer`（地表端点） | 投影の始点・終点リング |
| `ScatterplotLayer`（拠点） | 観測拠点マーカー |
| `PolygonLayer`（FOV） | カメラの視野角を地図上に表示 |

### 高度のスケーリング

流星の高度（80 km 前後）を地図上の緯度経度スケールと直接比較すると、見た目が潰れる。スライダーで 1×〜100× の係数を掛けられるようにした。

```javascript
// deck.gl の LineLayer に渡す座標変換
function applyAltitudeScale([lon, lat, altM]) {
  return [lon, lat, altM * altitudeScale];
}
```

---

## Docker Compose への統合

`station.json` が存在する場合のみ `station-reporter` サービスを追加するよう `generate_compose.py` を修正した。

```python
# generate_compose.py の追加部分
def generate_station_reporter(station_config_path, server_url):
    return {
        "station-reporter": {
            "build": {"context": ".", "dockerfile": "Dockerfile.reporter"},
            "volumes": [
                "./detections:/detections:ro",
                f"{station_config_path}:/station.json:ro",
            ],
            "environment": [
                "STATION_CONFIG=/station.json",
                f"TRIANGULATION_SERVER_URL={server_url}",
            ],
            "restart": "unless-stopped",
        }
    }
```

---

## テスト構成

純粋な計算ロジックなのでユニットテストが書きやすく、40件のテストを追加した。

| ファイル | 件数 | 内容 |
|---|---|---|
| `test_geo_utils.py` | 17 | LLA↔ECEF ラウンドトリップ、ENU↔ECEF、高度変換誤差検証 |
| `test_pixel_to_sky.py` | 11 | 中心ピクセル→カメラ方位一致、FOV端点の角度検証、ロール回転 |
| `test_triangulator.py` | 7 | 既知位置からの逆算検証（誤差 < 500m）、miss_distance 計算 |
| `test_event_matcher.py` | 5 | 時間窓マッチ/アンマッチ、バッファ期限切れ、同拠点スキップ |

**統合テストの考え方**: 既知の流星位置（例: 北緯35.5°、東経139.0°、高度85km）から、2拠点がそれぞれ観測したはずの方位角・仰角を逆算して入力し、三角測量結果が元の位置と一致するかを検証する。

```python
def test_triangulation_known_position():
    # 既知の流星位置
    target_lat, target_lon, target_alt_km = 35.5, 139.0, 85.0

    # 2拠点の設定（実際のテストコードは test_triangulator.py を参照）
    result = triangulate_meteor(report_a, report_b)

    assert result is not None
    assert abs(result.latitude - target_lat) < 0.05    # ~5km
    assert abs(result.longitude - target_lon) < 0.05
    assert abs(result.altitude_km - target_alt_km) < 5.0
```

---

## デモの動かし方

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python demo_triangulation.py   # ポート 8090 で起動
```

デモは富士北麓・箱根・秩父の3拠点を仮想設定し、5件の合成流星データ（既知の軌道から逆算した方位角・仰角）をあらかじめ SQLite に投入した状態で起動する。

---

## 今後の課題

- **カメラキャリブレーション**: 現在は `station.json` に手入力した方位角・仰角・FOVを使っているが、既知位置の恒星（ベガ、アルタイル等）の検出結果と照合してキャリブレーションするツールを作りたい
- **2拠点以上のマッチング**: 現在は2拠点ペアのみ。3拠点以上の場合は最小二乗法で精度向上できる
- **リアルタイムアラート**: 高信頼度の三角測量が成立したら Slack や LINE に通知する

---

コードはすべて [GitHub (Masakai/meteo)](https://github.com/Masakai/meteo) で公開している。三角測量関連は `triangulation/` ディレクトリ以下にまとまっている。
