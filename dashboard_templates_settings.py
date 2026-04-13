"""Settings page HTML rendering."""

import base64
from pathlib import Path


def render_settings_html(cameras, version):
    logotype_path = Path(__file__).parent / "documents" / "assets" / "meteo-logotype.svg"
    logotype_src = ""
    if logotype_path.exists():
        logotype_bytes = logotype_path.read_bytes()
        logotype_src = "data:image/svg+xml;base64," + base64.b64encode(logotype_bytes).decode("ascii")
    brand_logo_html = f'<img src="{logotype_src}" alt="METEO">' if logotype_src else '<span class="brand-text">METEO</span>'

    return f'''<!DOCTYPE html>
<html lang="ja">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Orbitron:wght@600;800&family=Inter:wght@400;500;600&family=JetBrains+Mono:wght@400;600&display=swap" rel="stylesheet">
    <title>流星検出ダッシュボード - カメラ設定</title>
    <style>
        * {{ box-sizing: border-box; }}
        body {{
            margin: 0;
            font-family: 'Inter', system-ui, sans-serif;
            background: #eef2f7;
            color: #192333;
            min-height: 100vh;
            line-height: 1.6;
            padding: 20px 20px 20px 240px;
        }}
        .topnav {{
            display: flex;
            flex-direction: column;
            align-items: stretch;
            gap: 0;
            padding: 24px 14px 20px;
            width: 220px;
            min-height: 100vh;
            background: #0f1c2d;
            border-right: 2px solid #f5a41f;
            position: fixed;
            left: 0;
            top: 0;
            z-index: 100;
            margin: 0;
            overflow-y: auto;
        }}
        .brand-link {{
            display: flex;
            align-items: center;
            justify-content: center;
            text-decoration: none;
            flex-shrink: 0;
            margin-bottom: 28px;
            padding: 4px 0;
        }}
        .brand-link img {{
            width: 100%;
            max-width: 160px;
            height: auto;
            display: block;
        }}
        .brand-text {{
            font-family: 'Orbitron', sans-serif;
            color: #dce8f5;
            font-size: 1.2em;
            font-weight: 800;
            letter-spacing: 0.1em;
        }}
        .nav-links {{
            display: flex;
            flex-direction: column;
            gap: 2px;
            flex: 1;
        }}
        .nav-link {{
            display: flex;
            align-items: center;
            padding: 10px 14px;
            border-radius: 7px;
            color: #6a8aaa;
            text-decoration: none;
            font-size: 0.88em;
            font-weight: 500;
            letter-spacing: 0.02em;
            transition: color 0.15s, background 0.15s;
            white-space: nowrap;
            min-height: 40px;
        }}
        .nav-link:hover {{
            color: #dce8f5;
            background: rgba(255,255,255,0.05);
        }}
        .nav-active {{
            color: #f5a41f;
            font-weight: 600;
            background: rgba(245, 164, 31, 0.10);
        }}
        .wrap {{
            max-width: 980px;
            margin: 0 auto;
            padding: 0 24px 24px;
        }}
        h1 {{
            margin: 0 0 8px;
            font-family: 'Orbitron', sans-serif;
            color: #1a8fc4;
        }}
        .sub {{
            color: #4e6880;
            margin-bottom: 18px;
        }}
        .toolbar {{
            display: flex;
            gap: 10px;
            margin-bottom: 16px;
            flex-wrap: wrap;
        }}
        .btn {{
            border: 1px solid #1a8fc4;
            background: #f0f7fc;
            color: #1a6090;
            border-radius: 8px;
            padding: 8px 12px;
            cursor: pointer;
            text-decoration: none;
        }}
        .btn:hover {{
            background: #1a8fc4;
            color: #ffffff;
            transition: background 0.2s, color 0.2s;
        }}
        .panel {{
            background: #ffffff;
            border: 1px solid #d0dce8;
            box-shadow: 0 1px 4px rgba(0,20,50,0.08);
            border-radius: 12px;
            padding: 16px;
            margin-bottom: 14px;
        }}
        .panel h2 {{
            margin: 0 0 10px;
            font-size: 1rem;
            color: #1a8fc4;
        }}
        details.help {{
            border: 1px solid #d0dce8;
            border-radius: 10px;
            background: #f8fafc;
            padding: 10px 12px;
        }}
        details.help summary {{
            cursor: pointer;
            color: #1a8fc4;
            font-weight: 600;
        }}
        .help-note {{
            margin: 8px 0 0;
            color: #4e6880;
            font-size: 0.85rem;
        }}
        .help-table {{
            width: 100%;
            border-collapse: collapse;
            margin-top: 10px;
            font-size: 0.84rem;
        }}
        .help-table th,
        .help-table td {{
            border: 1px solid #d0dce8;
            padding: 6px 8px;
            vertical-align: top;
        }}
        .help-table th {{
            background: #f4f8fb;
            color: #1a8fc4;
            text-align: left;
        }}
        .grid {{
            display: grid;
            grid-template-columns: repeat(2, minmax(200px, 1fr));
            gap: 10px 14px;
        }}
        label {{
            display: block;
            font-size: 0.82rem;
            color: #4e6880;
            margin-bottom: 4px;
        }}
        input,
        select {{
            width: 100%;
            background: #ffffff;
            border: 1px solid #d0dce8;
            color: #192333;
            border-radius: 8px;
            padding: 8px 10px;
            height: 36px;
            line-height: 1.2;
        }}
        input.changed-from-default,
        select.changed-from-default {{
            border-color: #ff5f5f;
            box-shadow: 0 0 0 1px rgba(255, 95, 95, 0.35);
        }}
        .status {{
            margin-top: 12px;
            padding: 10px;
            border-radius: 8px;
            background: #f8fafc;
            white-space: pre-wrap;
            font-family: 'JetBrains Mono', ui-monospace, monospace;
            font-size: 0.85rem;
            line-height: 1.4;
            border: 1px solid #d0dce8;
            color: #192333;
        }}
        @media (max-width: 740px) {{
            .grid {{
                grid-template-columns: 1fr;
            }}
        }}
        :focus-visible {{
            outline: 2px solid #1a8fc4;
            outline-offset: 2px;
            border-radius: 3px;
        }}
    </style>
</head>
<body>
    <nav class="topnav">
        <a href="/" class="brand-link">{brand_logo_html}</a>
        <div class="nav-links">
            <a class="nav-link" href="/">検出一覧</a>
            <a class="nav-link" href="/cameras">カメラ</a>
            <a class="nav-link" href="/stats">統計</a>
            <a class="nav-link nav-active" href="/settings" aria-current="page">設定</a>
        </div>
    </nav>
    <main>
    <div class="wrap">
        <h1>全カメラ設定</h1>
        <div class="sub">検出パラメータを一括適用します（対象: {len(cameras)} カメラ） / v{version}</div>
        <div class="toolbar">
            <a class="btn" href="/">ダッシュボードへ戻る</a>
            <a class="btn" href="/stats">統計</a>
            <button class="btn" type="button" onclick="loadCurrent()">現在値を取得</button>
            <button class="btn" type="button" onclick="applyDefaults()">デフォルト値に戻す</button>
            <button class="btn" type="button" onclick="applyAll()">全カメラに適用</button>
        </div>

        <div class="panel">
            <h2>運用プリセット / 起動時設定</h2>
            <details class="help">
                <summary>HELP</summary>
                <table class="help-table">
                    <thead>
                        <tr><th>パラメータ</th><th>意味</th><th>調整の目安</th></tr>
                    </thead>
                    <tbody>
                        <tr><td>sensitivity</td><td>感度プリセット</td><td>highで見逃し減、lowで誤検出減</td></tr>
                        <tr><td>scale</td><td>処理解像度スケール</td><td>上げると小さい流星に有利だが重くなる</td></tr>
                        <tr><td>buffer</td><td>リングバッファ秒数</td><td>長くすると検出前後の切り出し余裕が増える</td></tr>
                        <tr><td>extract_clips</td><td>検出時に動画クリップを保存</td><td>オフで容量節約（静止画中心運用向け）</td></tr>
                        <tr><td>clip_margin_before/after</td><td>検出前後に含める秒数</td><td>増やすと状況把握しやすい</td></tr>
                    </tbody>
                </table>
            </details>
            <div class="grid">
                <div>
                    <label>感度プリセット（sensitivity） low / medium / high / faint / fireball</label>
                    <select id="sensitivity">
                        <option value="low">low</option>
                        <option value="medium">medium</option>
                        <option value="high">high</option>
                        <option value="faint">faint</option>
                        <option value="fireball">fireball</option>
                    </select>
                </div>
                <div><label>処理解像度スケール（scale）</label><input id="scale" type="number" step="0.01"></div>
                <div><label>録画バッファ秒数（buffer）</label><input id="buffer" type="number" step="0.1"></div>
                <div><label>検出クリップ保存（extract_clips）</label><input id="extract_clips" type="checkbox"></div>
                <div><label>検出前の記録秒数（clip_margin_before）</label><input id="clip_margin_before" type="number" step="0.1"></div>
                <div><label>検出後の記録秒数（clip_margin_after）</label><input id="clip_margin_after" type="number" step="0.1"></div>
            </div>
        </div>

        <div class="panel">
            <h2>薄明時の検出設定</h2>
            <details class="help">
                <summary>HELP</summary>
                <p class="help-note">薄明（日の出・日の入り前後）に飛翔する鳥など移動が遅い物体の誤認識を抑制します。</p>
                <table class="help-table">
                    <thead>
                        <tr><th>パラメータ</th><th>意味</th><th>調整の目安</th></tr>
                    </thead>
                    <tbody>
                        <tr><td>TWILIGHT_DETECTION_MODE</td><td>薄明時の動作</td><td>reduce: 感度を下げて検出継続 / skip: 検出を停止</td></tr>
                        <tr><td>TWILIGHT_TYPE</td><td>薄明の種類（太陽の沈み角）</td><td>civil=6° / nautical=12° / astronomical=18°。深いほど薄明期間が長くなる</td></tr>
                        <tr><td>TWILIGHT_SENSITIVITY</td><td>reduce モード時の感度プリセット</td><td>lowが推奨（鳥など遅い物体の誤認識を減らす）</td></tr>
                        <tr><td>TWILIGHT_MIN_SPEED</td><td>reduce モード時の最小速度(px/秒)</td><td>鳥は遅いため高めに設定すると誤認識を抑制できる</td></tr>
                    </tbody>
                </table>
            </details>
            <div class="grid">
                <div>
                    <label>薄明時の動作モード（TWILIGHT_DETECTION_MODE）</label>
                    <select id="twilight_detection_mode">
                        <option value="reduce">reduce（感度を下げて検出継続）</option>
                        <option value="skip">skip（薄明中は検出を停止）</option>
                    </select>
                </div>
                <div>
                    <label>薄明の種類（TWILIGHT_TYPE）</label>
                    <select id="twilight_type">
                        <option value="civil">civil（太陽高度 -6°）</option>
                        <option value="nautical">nautical（太陽高度 -12°）</option>
                        <option value="astronomical">astronomical（太陽高度 -18°）</option>
                    </select>
                </div>
                <div>
                    <label>reduce モード時の感度（TWILIGHT_SENSITIVITY）</label>
                    <select id="twilight_sensitivity">
                        <option value="low">low</option>
                        <option value="medium">medium</option>
                        <option value="high">high</option>
                        <option value="faint">faint</option>
                    </select>
                </div>
                <div><label>reduce モード時の最小速度 px/秒（TWILIGHT_MIN_SPEED）</label><input id="twilight_min_speed" type="number" step="1" min="0"></div>
            </div>
        </div>

        <div class="panel">
            <h2>鳥シルエット除外フィルタ</h2>
            <details class="help">
                <summary>HELP</summary>
                <p class="help-note">移動する暗い物体（鳥のシルエット等）を輝度で除外します。流星は発光体なので高輝度、鳥は暗いシルエットなので低輝度になる性質を利用します。</p>
                <table class="help-table">
                    <thead>
                        <tr><th>パラメータ</th><th>意味</th><th>調整の目安</th></tr>
                    </thead>
                    <tbody>
                        <tr><td>BIRD_FILTER_ENABLED</td><td>通常時フィルタの有効/無効</td><td>夜間に鳥の誤認識が多い場合に有効にする</td></tr>
                        <tr><td>BIRD_MIN_BRIGHTNESS</td><td>通常時の最小輝度しきい値</td><td>これ未満の輝度の候補を除外（0-255）。80前後が目安</td></tr>
                        <tr><td>TWILIGHT_BIRD_FILTER_ENABLED</td><td>薄明時フィルタの有効/無効</td><td>薄明時はデフォルト有効</td></tr>
                        <tr><td>TWILIGHT_BIRD_MIN_BRIGHTNESS</td><td>薄明時の最小輝度しきい値</td><td>薄明時は明るいので通常時より高めでも機能する</td></tr>
                    </tbody>
                </table>
            </details>
            <div class="grid">
                <div><label><input id="bird_filter_enabled" type="checkbox"> 通常時フィルタを有効にする（BIRD_FILTER_ENABLED）</label></div>
                <div><label>通常時の最小輝度（BIRD_MIN_BRIGHTNESS）</label><input id="bird_min_brightness" type="number" step="1" min="0" max="255"></div>
                <div><label><input id="twilight_bird_filter_enabled" type="checkbox"> 薄明時フィルタを有効にする（TWILIGHT_BIRD_FILTER_ENABLED）</label></div>
                <div><label>薄明時の最小輝度（TWILIGHT_BIRD_MIN_BRIGHTNESS）</label><input id="twilight_bird_min_brightness" type="number" step="1" min="0" max="255"></div>
            </div>
        </div>

        <div class="panel">
            <h2>基本検出</h2>
            <details class="help">
                <summary>HELP</summary>
                <table class="help-table">
                    <thead>
                        <tr><th>パラメータ</th><th>意味</th><th>調整の目安</th></tr>
                    </thead>
                    <tbody>
                        <tr><td>diff_threshold</td><td>フレーム差分のしきい値</td><td>下げると暗い/細い軌跡を拾いやすい</td></tr>
                        <tr><td>min_brightness</td><td>候補採用の最小輝度</td><td>下げると暗い流星に強くなる</td></tr>
                        <tr><td>min_brightness_tracking</td><td>追跡継続時の最小輝度</td><td>下げると追跡切れしにくい</td></tr>
                        <tr><td>min_length / max_length</td><td>軌跡長の許容範囲</td><td>minを下げると短い流星に有利</td></tr>
                        <tr><td>min_duration / max_duration</td><td>継続時間の許容範囲</td><td>minを下げると瞬間的な流星を拾いやすい</td></tr>
                        <tr><td>min_speed</td><td>最低速度</td><td>下げると遅い見かけ速度も通る</td></tr>
                        <tr><td>min_linearity</td><td>直線性の下限</td><td>下げると多少ぶれた軌跡も通る</td></tr>
                        <tr><td>exclude_bottom_ratio</td><td>画面下部の除外率</td><td>下げると低空の流星を拾いやすい</td></tr>
                        <tr><td>exclude_edge_ratio (px)</td><td>画面四辺からの除外幅（px）。例: 20 → 上下左右それぞれ20pxを検出対象外にする</td><td>大きすぎると検出領域がゼロになる（1080p・スケール0.7では上限約378px）。通常は0〜30px程度</td></tr>
                    </tbody>
                </table>
            </details>
            <div class="grid">
                <div><label>差分しきい値（diff_threshold）</label><input id="diff_threshold" type="number" step="1"></div>
                <div><label>最小輝度（min_brightness）</label><input id="min_brightness" type="number" step="1"></div>
                <div><label>追跡中の最小輝度（min_brightness_tracking）</label><input id="min_brightness_tracking" type="number" step="1"></div>
                <div><label>最小軌跡長(px)（min_length）</label><input id="min_length" type="number" step="1"></div>
                <div><label>最大軌跡長(px)（max_length）</label><input id="max_length" type="number" step="1"></div>
                <div><label>最小継続時間(秒)（min_duration）</label><input id="min_duration" type="number" step="0.01"></div>
                <div><label>最大継続時間(秒)（max_duration）</label><input id="max_duration" type="number" step="0.01"></div>
                <div><label>最小速度(px/秒)（min_speed）</label><input id="min_speed" type="number" step="0.1"></div>
                <div><label>最小直線性（min_linearity）</label><input id="min_linearity" type="number" step="0.01"></div>
                <div><label>画面下部除外率（exclude_bottom_ratio）</label><input id="exclude_bottom_ratio" type="number" step="0.01"></div>
                <div><label>画面四辺除外幅 px（exclude_edge_ratio）</label><input id="exclude_edge_ratio" type="number" step="1" min="0"></div>
            </div>
        </div>

        <div class="panel">
            <h2>追跡・結合</h2>
            <details class="help">
                <summary>HELP</summary>
                <table class="help-table">
                    <thead>
                        <tr><th>パラメータ</th><th>意味</th><th>調整の目安</th></tr>
                    </thead>
                    <tbody>
                        <tr><td>min_area / max_area</td><td>候補領域サイズの許容範囲</td><td>minを下げると細い流星に有利</td></tr>
                        <tr><td>max_gap_time</td><td>追跡の途切れ許容時間</td><td>上げると点が途切れても追跡しやすい</td></tr>
                        <tr><td>max_distance</td><td>フレーム間の追跡許容距離</td><td>上げると速い移動も追いやすい</td></tr>
                        <tr><td>merge_max_gap_time</td><td>イベント結合の時間条件</td><td>上げると近接イベントをまとめやすい</td></tr>
                        <tr><td>merge_max_distance</td><td>イベント結合の距離条件</td><td>上げると近い軌跡をまとめやすい</td></tr>
                        <tr><td>merge_max_speed_ratio</td><td>イベント結合の速度差条件</td><td>上げると速度差があっても結合しやすい</td></tr>
                    </tbody>
                </table>
            </details>
            <div class="grid">
                <div><label>最小面積(px²)（min_area）</label><input id="min_area" type="number" step="1"></div>
                <div><label>最大面積(px²)（max_area）</label><input id="max_area" type="number" step="1"></div>
                <div><label>追跡切れ許容時間(秒)（max_gap_time）</label><input id="max_gap_time" type="number" step="0.1"></div>
                <div><label>追跡最大距離(px)（max_distance）</label><input id="max_distance" type="number" step="0.1"></div>
                <div><label>結合最大ギャップ(秒)（merge_max_gap_time）</label><input id="merge_max_gap_time" type="number" step="0.1"></div>
                <div><label>結合最大距離(px)（merge_max_distance）</label><input id="merge_max_distance" type="number" step="0.1"></div>
                <div><label>結合速度差比率（merge_max_speed_ratio）</label><input id="merge_max_speed_ratio" type="number" step="0.01"></div>
            </div>
        </div>

        <div class="panel">
            <h2>誤検出抑制（電線・部分照明）</h2>
            <details class="help">
                <summary>HELP</summary>
                <p class="help-note">厳しくすると誤検出は減りますが、見逃しは増えやすくなります。</p>
                <table class="help-table">
                    <thead>
                        <tr><th>パラメータ</th><th>意味</th><th>調整の目安</th></tr>
                    </thead>
                    <tbody>
                        <tr><td>exclude_edge_ratio (px)</td><td>画面四辺からの除外幅（px）。上下左右それぞれ指定pxを検出対象外にする</td><td>通常は0〜30px。大きすぎると検出領域がゼロになるため注意</td></tr>
                        <tr><td>nuisance_overlap_threshold</td><td>小領域がノイズ帯に重なる許容率</td><td>下げると電線起因の誤検出を強く抑える</td></tr>
                        <tr><td>nuisance_path_overlap_threshold</td><td>軌跡全体のノイズ帯重なり許容率</td><td>下げるとノイズ帯沿いの誤検出を抑える</td></tr>
                        <tr><td>min_track_points</td><td>確定に必要な追跡点数</td><td>上げると誤検出減、下げると見逃し減</td></tr>
                        <tr><td>max_stationary_ratio</td><td>静止成分の許容上限</td><td>下げると静止ノイズを除外しやすい</td></tr>
                        <tr><td>small_area_threshold</td><td>小領域判定の面積しきい値</td><td>上げると小さいノイズへの抑制を広げる</td></tr>
                        <tr><td>mask_dilate / nuisance_dilate</td><td>マスク膨張量</td><td>上げると除外範囲を広げる</td></tr>
                        <tr><td>mask_image / mask_from_day</td><td>除外マスクの入力元</td><td>空以外を除外して誤検出を減らす</td></tr>
                        <tr><td>nuisance_mask_image / nuisance_from_night</td><td>ノイズ帯マスクの入力元</td><td>電線・街灯帯の誤検出抑制に有効</td></tr>
                    </tbody>
                </table>
            </details>
            <div class="grid">
                <div><label>ノイズ帯重なり閾値（nuisance_overlap_threshold）</label><input id="nuisance_overlap_threshold" type="number" step="0.01"></div>
                <div><label>経路のノイズ帯重なり閾値（nuisance_path_overlap_threshold）</label><input id="nuisance_path_overlap_threshold" type="number" step="0.01"></div>
                <div><label>最小追跡点数（min_track_points）</label><input id="min_track_points" type="number" step="1"></div>
                <div><label>静止率上限（max_stationary_ratio）</label><input id="max_stationary_ratio" type="number" step="0.01"></div>
                <div><label>小領域判定しきい値（small_area_threshold）</label><input id="small_area_threshold" type="number" step="1"></div>
                <div><label>除外マスク膨張px（mask_dilate）</label><input id="mask_dilate" type="number" step="1"></div>
                <div><label>ノイズ帯マスク膨張px（nuisance_dilate）</label><input id="nuisance_dilate" type="number" step="1"></div>
                <div><label>除外マスク画像パス（mask_image）</label><input id="mask_image" type="text"></div>
                <div><label>昼間画像マスク元パス（mask_from_day）</label><input id="mask_from_day" type="text"></div>
                <div><label>ノイズ帯マスク画像パス（nuisance_mask_image）</label><input id="nuisance_mask_image" type="text"></div>
                <div><label>夜間画像ノイズ帯元パス（nuisance_from_night）</label><input id="nuisance_from_night" type="text"></div>
            </div>
        </div>

        <div class="status" id="status">準備完了</div>
    </div>
    <script>
        let processMinDim = 0;  // カメラの処理解像度 min(幅, 高さ)。exclude_edge_ratio の px 変換に使用

        const fields = [
            'sensitivity', 'scale', 'buffer', 'extract_clips',
            'clip_margin_before', 'clip_margin_after',
            'twilight_detection_mode', 'twilight_type', 'twilight_sensitivity', 'twilight_min_speed',
            'bird_filter_enabled', 'bird_min_brightness', 'twilight_bird_filter_enabled', 'twilight_bird_min_brightness',
            'diff_threshold', 'min_brightness', 'min_brightness_tracking',
            'min_length', 'max_length', 'min_duration', 'max_duration', 'min_speed',
            'min_linearity', 'exclude_bottom_ratio', 'exclude_edge_ratio',
            'min_area', 'max_area', 'max_gap_time', 'max_distance',
            'merge_max_gap_time', 'merge_max_distance', 'merge_max_speed_ratio',
            'nuisance_overlap_threshold', 'nuisance_path_overlap_threshold',
            'min_track_points', 'max_stationary_ratio', 'small_area_threshold',
            'mask_dilate', 'nuisance_dilate',
            'mask_image', 'mask_from_day', 'nuisance_mask_image', 'nuisance_from_night'
        ];
        const defaultSettings = {{
            sensitivity: 'medium',
            scale: 0.5,
            buffer: 15.0,
            extract_clips: true,
            clip_margin_before: 1.0,
            clip_margin_after: 1.0,
            diff_threshold: 30,
            min_brightness: 200,
            min_brightness_tracking: 160,
            min_length: 20,
            max_length: 5000,
            min_duration: 0.1,
            max_duration: 10.0,
            min_speed: 50.0,
            min_linearity: 0.7,
            exclude_bottom_ratio: 0.0625,
            exclude_edge_ratio: 0,
            min_area: 5,
            max_area: 10000,
            max_gap_time: 2.0,
            max_distance: 80.0,
            merge_max_gap_time: 1.5,
            merge_max_distance: 80.0,
            merge_max_speed_ratio: 0.5,
            nuisance_overlap_threshold: 0.60,
            nuisance_path_overlap_threshold: 0.70,
            min_track_points: 4,
            max_stationary_ratio: 0.40,
            small_area_threshold: 40,
            mask_dilate: 20,
            nuisance_dilate: 3,
            mask_image: '',
            mask_from_day: '',
            nuisance_mask_image: '',
            nuisance_from_night: '',
            twilight_detection_mode: 'reduce',
            twilight_type: 'nautical',
            twilight_sensitivity: 'low',
            twilight_min_speed: 200,
            bird_filter_enabled: false,
            bird_min_brightness: 80,
            twilight_bird_filter_enabled: true,
            twilight_bird_min_brightness: 80
        }};

        function setStatus(message) {{
            document.getElementById('status').textContent = message;
        }}

        function fillForm(data) {{
            fields.forEach((name) => {{
                const el = document.getElementById(name);
                if (!el) return;
                if (Object.prototype.hasOwnProperty.call(data, name) && data[name] !== null && data[name] !== undefined) {{
                    if (el.type === 'checkbox') {{
                        el.checked = data[name] === true || String(data[name]).toLowerCase() === 'true';
                    }} else if (name === 'exclude_edge_ratio') {{
                        const dim = processMinDim > 0 ? processMinDim : 0;
                        el.value = dim > 0 ? Math.round(parseFloat(data[name]) * dim) : Math.round(parseFloat(data[name]) * 100);
                    }} else {{
                        el.value = data[name];
                    }}
                }}
            }});
            refreshDiffStates();
        }}

        function _normalizeForCompare(el, value) {{
            if (el.type === 'checkbox') {{
                return value === true || String(value).toLowerCase() === 'true' ? 'true' : 'false';
            }}
            return String(value ?? '').trim();
        }}

        function updateFieldDiffState(name) {{
            const el = document.getElementById(name);
            if (!el) return;
            if (!Object.prototype.hasOwnProperty.call(defaultSettings, name)) {{
                el.classList.remove('changed-from-default');
                return;
            }}
            const current = el.type === 'checkbox'
                ? (el.checked ? 'true' : 'false')
                : String(el.value ?? '').trim();
            const def = _normalizeForCompare(el, defaultSettings[name]);
            el.classList.toggle('changed-from-default', current !== def);
        }}

        function refreshDiffStates() {{
            fields.forEach((name) => updateFieldDiffState(name));
        }}

        function collectPayload() {{
            const payload = {{}};
            fields.forEach((name) => {{
                const el = document.getElementById(name);
                if (!el) return;
                if (el.type === 'checkbox') {{
                    payload[name] = el.checked;
                    return;
                }}
                const value = String(el.value ?? '').trim();
                if (value !== '') {{
                    if (name === 'exclude_edge_ratio') {{
                        const dim = processMinDim > 0 ? processMinDim : 100;
                        payload[name] = parseFloat(value) / dim;
                    }} else {{
                        payload[name] = value;
                    }}
                }}
            }});
            return payload;
        }}

        function extractApiError(data, fallbackMessage) {{
            if (!data || typeof data !== 'object') {{
                return fallbackMessage;
            }}
            if (typeof data.error === 'string' && data.error.trim() !== '') {{
                return data.error;
            }}
            if (Array.isArray(data.results)) {{
                const failed = data.results.filter((item) => item && item.success === false);
                if (failed.length > 0) {{
                    const first = failed[0];
                    if (first && typeof first.error === 'string' && first.error.trim() !== '') {{
                        return `${{failed.length}}台で失敗: ${{first.error}}`;
                    }}
                    return `${{failed.length}}台で失敗`;
                }}
            }}
            return fallbackMessage;
        }}

        async function loadCurrent() {{
            setStatus('現在値を取得中...');
            try {{
                const res = await fetch('/camera_settings/current', {{ cache: 'no-store' }});
                const data = await res.json();
                if (!res.ok || data.success === false) {{
                    throw new Error(extractApiError(data, '現在値の取得に失敗しました'));
                }}
                if (data.process_min_dim > 0) processMinDim = data.process_min_dim;
                fillForm(data.settings || {{}});
                setStatus('現在値を取得しました');
            }} catch (e) {{
                setStatus('取得失敗: ' + e);
            }}
        }}

        function applyDefaults() {{
            fillForm(defaultSettings);
            setStatus('デフォルト値をフォームに反映しました（まだ適用していません）');
        }}

        async function applyAll() {{
            const payload = collectPayload();
            setStatus('全カメラへ適用中...');
            try {{
                const res = await fetch('/camera_settings/apply_all', {{
                    method: 'POST',
                    headers: {{ 'Content-Type': 'application/json' }},
                    body: JSON.stringify(payload),
                }});
                const data = await res.json();
                if (!res.ok || data.success === false) {{
                    throw new Error(extractApiError(data, '設定適用に失敗しました'));
                }}
                alert(`反映完了: ${{data.applied_count}} / ${{data.total}} 台`);
                setStatus(
                    '適用完了\\n' +
                    '成功: ' + data.applied_count + '/' + data.total + '\\n' +
                    JSON.stringify(data.results, null, 2)
                );
            }} catch (e) {{
                setStatus('適用失敗: ' + e);
            }}
        }}

        fields.forEach((name) => {{
            const el = document.getElementById(name);
            if (!el) return;
            if (el.type === 'checkbox') {{
                el.addEventListener('change', () => updateFieldDiffState(name));
                return;
            }}
            el.addEventListener('input', () => updateFieldDiffState(name));
            el.addEventListener('change', () => updateFieldDiffState(name));
        }});

        loadCurrent();
    </script>
    </div>
    </main>
</body>
</html>'''
