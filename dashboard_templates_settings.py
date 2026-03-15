"""Settings page HTML rendering."""

def render_settings_html(cameras, version):
    return f'''<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>Camera Settings</title>
    <style>
        * {{ box-sizing: border-box; }}
        body {{
            margin: 0;
            font-family: 'Segoe UI', Arial, sans-serif;
            background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
            color: #eee;
            min-height: 100vh;
        }}
        .wrap {{
            max-width: 980px;
            margin: 0 auto;
            padding: 24px;
        }}
        h1 {{
            margin: 0 0 8px;
            color: #00d4ff;
        }}
        .sub {{
            color: #9ab;
            margin-bottom: 18px;
        }}
        .toolbar {{
            display: flex;
            gap: 10px;
            margin-bottom: 16px;
            flex-wrap: wrap;
        }}
        .btn {{
            border: 1px solid #00d4ff;
            background: #20335b;
            color: #d7f8ff;
            border-radius: 8px;
            padding: 8px 12px;
            cursor: pointer;
            text-decoration: none;
        }}
        .btn:hover {{
            background: #00d4ff;
            color: #0f1530;
        }}
        .panel {{
            background: #1f2a48;
            border: 1px solid #2d406d;
            border-radius: 12px;
            padding: 16px;
            margin-bottom: 14px;
        }}
        .panel h2 {{
            margin: 0 0 10px;
            font-size: 1rem;
            color: #7dd9ff;
        }}
        details.help {{
            border: 1px solid #3a5488;
            border-radius: 10px;
            background: #172544;
            padding: 10px 12px;
        }}
        details.help summary {{
            cursor: pointer;
            color: #9fe8ff;
            font-weight: 600;
        }}
        .help-note {{
            margin: 8px 0 0;
            color: #a8bfdc;
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
            border: 1px solid #36507f;
            padding: 6px 8px;
            vertical-align: top;
        }}
        .help-table th {{
            background: #13203c;
            color: #a8dfff;
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
            color: #bfd1ee;
            margin-bottom: 4px;
        }}
        input,
        select {{
            width: 100%;
            background: #13203c;
            border: 1px solid #34507f;
            color: #e6f2ff;
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
            background: #13203c;
            white-space: pre-wrap;
            font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
            font-size: 0.85rem;
            line-height: 1.4;
            border: 1px solid #34507f;
        }}
        @media (max-width: 740px) {{
            .grid {{
                grid-template-columns: 1fr;
            }}
        }}
    </style>
</head>
<body>
    <div class="wrap">
        <h1>全カメラ設定</h1>
        <div class="sub">検出パラメータを一括適用します（対象: {len(cameras)} カメラ） / v{version}</div>
        <div class="toolbar">
            <a class="btn" href="/">ダッシュボードへ戻る</a>
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
                        <tr><td>exclude_edge_ratio</td><td>画面周辺（四辺）の除外率</td><td>上げると周辺ノイズを抑制しやすい</td></tr>
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
                <div><label>画面周辺除外率（exclude_edge_ratio）</label><input id="exclude_edge_ratio" type="number" step="0.001"></div>
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
                        <tr><td>exclude_edge_ratio</td><td>画面周辺（四辺）の除外率</td><td>上げると端の固定ノイズを抑制しやすい</td></tr>
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
        const fields = [
            'sensitivity', 'scale', 'buffer', 'extract_clips',
            'clip_margin_before', 'clip_margin_after',
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
            exclude_edge_ratio: 0.0,
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
            nuisance_from_night: ''
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
                    payload[name] = value;
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
</body>
</html>'''
