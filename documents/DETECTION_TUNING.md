# 検出感度チューニングガイド (Detection Tuning Guide)

---

**Copyright (c) 2026 Masanori Sakai**

Licensed under the MIT License

---

## 目的

「流星が検出されない」場合に、現場で調整すべきパラメータと手順を整理します。
本ガイドは **見逃しを減らす方向の調整** にフォーカスしています。

## まず確認すること（調整前チェック）

1. **ストリーム入力が安定しているか**
   - `stream_alive` が `true` か、フレームが途切れていないかを確認。
2. **検出時間帯の制限**
   - `ENABLE_TIME_WINDOW=true` の場合、時間外は検出されません。
3. **除外マスク**
   - `--mask-image` や `--mask-from-day` により、流星が写る領域を除外していないか。
4. **除外範囲**
   - `--exclude-bottom` が大きすぎると低空の流星が消えます。

## 最初に試す基本調整（見逃し対策）

### 1. 感度プリセットを上げる

**MP4 / RTSP 共通**
```bash
--sensitivity high
```

**火球向け**
```bash
--sensitivity fireball
```

### 2. 解像度スケールを上げる（RTSPで重要）

`--scale` を 1.0 にすると検出は有利になります（処理負荷は増加）。

```bash
--scale 1.0
```

### 3. 除外範囲を狭くする

```bash
--exclude-bottom 0.02
```

## MP4検出の詳細調整

MP4検出では以下のパラメータを直接調整できます。

| パラメータ | 下げるとどうなるか | 目安 |
|-----------|--------------------|------|
| `--diff-threshold` | 小さな変化も検出しやすくなる | 30 → 20 |
| `--min-brightness` | 暗い流星も拾いやすくなる | 200 → 180 |
| `--min-length` | 短い痕跡でも検出しやすくなる | 20 → 15 |
| `--min-speed` | 遅い流星も検出しやすくなる | 5.0 → 3.0 |

**例**
```bash
python meteor_detector.py input.mp4 \
  --sensitivity high \
  --diff-threshold 20 \
  --min-brightness 180 \
  --min-length 15 \
  --min-speed 3.0
```

## RTSP検出の調整ポイント

RTSP版は CLI から調整できる項目が限定されています。
また、ダッシュボードの `/settings` から全カメラへ一括設定することも可能です。

**有効な調整**
- `--sensitivity`（low / medium / high / fireball）
- `--scale`（処理解像度）
- `--exclude-bottom`（画面下部の除外率）
- マスク関連 (`--mask-image`, `--mask-from-day`)
- ノイズ帯マスク関連 (`--nuisance-mask-image`, `--nuisance-from-night`, `--nuisance-dilate`)
- ノイズ帯重なり閾値 (`--nuisance-overlap-threshold`)

**例**
```bash
python meteor_detector_rtsp_web.py rtsp://... \
  --sensitivity high \
  --scale 1.0 \
  --exclude-bottom 0.02 \
  --nuisance-from-night ./night_reference.jpg \
  --nuisance-dilate 3 \
  --nuisance-overlap-threshold 0.60
```

## 誤検出（電線・部分照明）を減らす調整

夜間の電線や電柱付近が車のヘッドライトで一時的に光るケース向けに、
RTSP版には以下の抑制が追加されています。

- 小さい候補がノイズ帯マスクと大きく重なる場合に除外
- 追跡点数が少ないトラックを除外
- 連続点の移動が少ない（ほぼ静止）トラックを除外
- トラック軌跡がノイズ帯と強く重なる場合に除外

### 推奨手順

1. `--nuisance-from-night` で夜間基準画像からノイズ帯マスクを自動生成
2. 電柱・電線が多い場合は `--nuisance-mask-image` で手動マスクを併用
3. 誤検出が多い場合は `--nuisance-overlap-threshold` を `0.55` へ下げる
4. 見逃しが増える場合は `--nuisance-overlap-threshold` を `0.65` へ上げる

## ダッシュボード一括設定での反映タイミング

`/settings` で反映する場合、項目によって適用タイミングが異なります。

- 即時反映（再起動不要）:
  - `diff_threshold`, `min_brightness`, `min_linearity`
  - `nuisance_overlap_threshold`, `nuisance_path_overlap_threshold`
  - `min_track_points`, `max_stationary_ratio`, `small_area_threshold`
  - `mask_dilate`, `nuisance_dilate`, `mask_image`, `mask_from_day`, `nuisance_mask_image`, `nuisance_from_night`
- 自動再起動で反映（再ビルド不要）:
  - `sensitivity`, `scale`, `buffer`, `extract_clips`, `fb_normalize`, `fb_delete_mov`

起動時設定は `output/runtime_settings/<camera>.json` に保存されるため、
コンテナ再起動後も有効です。

## Docker環境での調整例

`generate_compose.py` で設定を変更して再生成してください。

```bash
python3 generate_compose.py \
  --sensitivity high \
  --scale 1.0 \
  --exclude-bottom 0.02
docker compose up -d
```

## それでも検出されない場合（コード調整）

さらに追い込む場合は `DetectionParams` を直接調整します。

- `meteor_detector.py` の `DetectionParams`
- `meteor_detector_rtsp_web.py` の `DetectionParams`

例:
- `min_duration` を下げる（短時間の流星を拾う）
- `min_linearity` を下げる（曲がった軌道を許容）
- `max_gap_frames` を増やす（明滅に強くする）

コード変更後のみ `./meteor-docker.sh rebuild` が必要です。
設定値の変更だけであれば、`/settings` または `/apply_settings` で再ビルド不要で反映できます。

## よくあるパターン

- **暗い流星が検出されない**: `min_brightness` を下げる、`--scale` を上げる
- **短い流星が検出されない**: `min_length` を下げる、`min_duration` を下げる
- **低空の流星が検出されない**: `--exclude-bottom` を小さくする
- **瞬間的な流星が検出されない**: `--skip` を 1 に戻す（MP4）

## 注意点

- 見逃しを減らすと **誤検出は増えやすくなります**。
- 調整は一度に1つずつ変えて、効果を確認してください。
