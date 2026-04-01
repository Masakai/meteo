"""三角測量結果の地図表示テンプレート (Deck.gl + MapLibre GL JS 3D)"""
from __future__ import annotations

import json
from typing import List


def render_map_page(stations: List[dict]) -> str:
    """Deck.gl + MapLibre GL JS ベースの3D地図ページを生成

    Args:
        stations: 拠点情報のリスト [{station_id, station_name, latitude, longitude, cameras}]
    """
    stations_json = json.dumps(stations, ensure_ascii=False)

    return f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>流星三角測量 3Dマップ</title>
<link href="https://unpkg.com/maplibre-gl@4.7.1/dist/maplibre-gl.css" rel="stylesheet" />
<script src="https://unpkg.com/maplibre-gl@4.7.1/dist/maplibre-gl.js"></script>
<script src="https://unpkg.com/deck.gl@9.1.7/dist.min.js"></script>
<style>
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #0d1117; color: #e0e0e0; }}
#map-container {{ width: 100%; height: 70vh; position: relative; }}
#map {{ width: 100%; height: 100%; }}
#tooltip {{ position: absolute; z-index: 10; pointer-events: none; background: rgba(13,17,23,0.92); color: #e0e0e0; padding: 10px 14px; border-radius: 8px; font-size: 13px; line-height: 1.6; max-width: 320px; border: 1px solid #30363d; display: none; backdrop-filter: blur(6px); }}
#tooltip .tt-title {{ font-weight: bold; color: #e94560; margin-bottom: 4px; font-size: 14px; }}
#tooltip .tt-row {{ display: flex; justify-content: space-between; gap: 16px; }}
#tooltip .tt-label {{ color: #8b949e; }}
#tooltip .tt-value {{ color: #e0e0e0; font-weight: 500; }}
.header {{ padding: 10px 20px; background: #161b22; display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid #30363d; }}
.header h1 {{ font-size: 1.15em; color: #e94560; }}
.controls {{ padding: 8px 20px; background: #0d1117; display: flex; gap: 15px; align-items: center; flex-wrap: wrap; border-bottom: 1px solid #30363d; }}
.controls label {{ font-size: 0.82em; color: #8b949e; }}
.controls input, .controls select {{ background: #161b22; color: #e0e0e0; border: 1px solid #30363d; padding: 4px 8px; border-radius: 4px; font-size: 0.82em; }}
.controls button {{ background: #e94560; color: white; border: none; padding: 5px 14px; border-radius: 4px; cursor: pointer; font-size: 0.82em; }}
.controls button:hover {{ background: #c73450; }}
.controls button.secondary {{ background: #30363d; }}
.controls button.secondary:hover {{ background: #484f58; }}
.stats {{ padding: 6px 20px; background: #161b22; font-size: 0.8em; display: flex; gap: 20px; border-bottom: 1px solid #30363d; }}
.stats .stat-item {{ color: #8b949e; }}
.stats .stat-value {{ color: #e94560; font-weight: bold; }}
#meteor-list {{ max-height: 25vh; overflow-y: auto; padding: 8px 20px; }}
.meteor-item {{ padding: 8px 12px; margin: 3px 0; background: #161b22; border-radius: 6px; cursor: pointer; display: flex; justify-content: space-between; align-items: center; border: 1px solid transparent; transition: all 0.15s; }}
.meteor-item:hover {{ background: #1c2333; border-color: #30363d; }}
.meteor-item .time {{ color: #e94560; font-weight: 600; font-size: 0.85em; }}
.meteor-item .details {{ color: #8b949e; font-size: 0.8em; text-align: right; }}
.meteor-item .details .alt {{ color: #58a6ff; }}
.meteor-item .details .speed {{ color: #f0883e; margin-left: 8px; }}
.meteor-item .confidence {{ color: #4ecca3; font-weight: 600; font-size: 0.85em; min-width: 40px; text-align: right; }}
.legend {{ position: absolute; bottom: 20px; left: 20px; background: rgba(13,17,23,0.88); padding: 10px 14px; border-radius: 8px; font-size: 12px; z-index: 5; border: 1px solid #30363d; backdrop-filter: blur(6px); }}
.legend-item {{ display: flex; align-items: center; gap: 8px; margin: 3px 0; }}
.legend-dot {{ width: 10px; height: 10px; border-radius: 50%; }}
.view-hint {{ position: absolute; top: 12px; right: 12px; background: rgba(13,17,23,0.7); color: #8b949e; padding: 6px 10px; border-radius: 6px; font-size: 11px; z-index: 5; pointer-events: none; }}
</style>
</head>
<body>

<div class="header">
    <h1>Meteor Triangulation 3D Map</h1>
</div>

<div class="controls">
    <label>日付: <input type="date" id="date-filter" /></label>
    <label>最小信頼度:
        <input type="range" id="confidence-filter" min="0" max="100" value="0" />
        <span id="confidence-value">0%</span>
    </label>
    <label>高度スケール:
        <input type="range" id="altitude-scale" min="1" max="100" value="30" />
        <span id="altitude-scale-value">30x</span>
    </label>
    <button onclick="loadMeteors()">更新</button>
    <button class="secondary" onclick="resetView()">視点リセット</button>
    <button class="secondary" onclick="toggleFov()">FOV切替</button>
</div>

<div class="stats">
    <span class="stat-item">三角測量済: <span class="stat-value" id="total-count">-</span></span>
    <span class="stat-item">拠点数: <span class="stat-value" id="station-total">-</span></span>
    <span class="stat-item">最終検出: <span class="stat-value" id="last-detection">-</span></span>
</div>

<div id="map-container">
    <div id="map"></div>
    <div id="tooltip"></div>
    <div class="legend">
        <div class="legend-item"><div class="legend-dot" style="background:#4ecca3"></div> 始点 (高高度)</div>
        <div class="legend-item"><div class="legend-dot" style="background:#ff6b6b"></div> 終点 (低高度)</div>
        <div class="legend-item"><div class="legend-dot" style="background:#e94560"></div> 観測拠点</div>
        <div class="legend-item"><div style="width:20px;height:0;border-top:2px dashed #4ecca3;opacity:0.6"></div> 地表投影</div>
        <div style="margin-top:6px;color:#8b949e;font-size:11px">右ドラッグで回転 / Ctrl+ドラッグで傾斜</div>
    </div>
    <div class="view-hint" id="view-hint">Ctrl+ドラッグで3D表示</div>
</div>
<div id="meteor-list"></div>

<script>
const STATIONS = {stations_json};
let meteors = [];
let deckgl = null;
let showFov = true;
let altitudeScale = 30;

const INITIAL_VIEW = {{
    longitude: STATIONS.length > 0 ? STATIONS[0].longitude : 139.0,
    latitude: STATIONS.length > 0 ? STATIONS[0].latitude : 35.5,
    zoom: 8,
    pitch: 55,
    bearing: -20,
}};

function init() {{
    deckgl = new deck.DeckGL({{
        container: 'map',
        mapStyle: 'https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json',
        initialViewState: INITIAL_VIEW,
        controller: true,
        getTooltip: getTooltip,
    }});

    document.getElementById('station-total').textContent = STATIONS.length;

    const confSlider = document.getElementById('confidence-filter');
    const confLabel = document.getElementById('confidence-value');
    confSlider.oninput = () => {{ confLabel.textContent = confSlider.value + '%'; }};

    const altSlider = document.getElementById('altitude-scale');
    const altLabel = document.getElementById('altitude-scale-value');
    altSlider.oninput = () => {{
        altLabel.textContent = altSlider.value + 'x';
        altitudeScale = parseInt(altSlider.value);
        updateLayers();
    }};

    // 初回ピッチ変更でヒントを消す
    setTimeout(() => {{ document.getElementById('view-hint').style.display = 'none'; }}, 5000);

    loadMeteors();
}}

function getTooltip(info) {{
    if (!info.object) return null;
    const obj = info.object;

    if (obj._type === 'meteor-line') {{
        const m = obj._meteor;
        return {{
            html: `
                <div class="tt-title">流星 ${{m.id.substring(0, 16)}}</div>
                <div class="tt-row"><span class="tt-label">時刻</span><span class="tt-value">${{new Date(m.timestamp).toLocaleString('ja-JP')}}</span></div>
                <div class="tt-row"><span class="tt-label">始点高度</span><span class="tt-value">${{m.start_alt.toFixed(1)}} km</span></div>
                <div class="tt-row"><span class="tt-label">終点高度</span><span class="tt-value">${{m.end_alt.toFixed(1)}} km</span></div>
                <div class="tt-row"><span class="tt-label">速度</span><span class="tt-value">${{m.velocity ? m.velocity.toFixed(1) + ' km/s' : 'N/A'}}</span></div>
                <div class="tt-row"><span class="tt-label">誤差(始/終)</span><span class="tt-value">${{m.miss_distance_start.toFixed(2)}} / ${{m.miss_distance_end.toFixed(2)}} km</span></div>
                <div class="tt-row"><span class="tt-label">信頼度</span><span class="tt-value">${{((m.confidence||0)*100).toFixed(0)}}%</span></div>
            `,
            style: {{ background: 'rgba(13,17,23,0.92)', color: '#e0e0e0', padding: '10px 14px', borderRadius: '8px', border: '1px solid #30363d', fontSize: '13px', lineHeight: '1.6', backdropFilter: 'blur(6px)' }}
        }};
    }}

    if (obj._type === 'station') {{
        return {{
            html: `
                <div class="tt-title">${{obj.station_name}}</div>
                <div class="tt-row"><span class="tt-label">ID</span><span class="tt-value">${{obj.station_id}}</span></div>
                <div class="tt-row"><span class="tt-label">位置</span><span class="tt-value">${{obj.latitude.toFixed(4)}}, ${{obj.longitude.toFixed(4)}}</span></div>
                <div class="tt-row"><span class="tt-label">カメラ数</span><span class="tt-value">${{(obj.cameras||[]).length}}</span></div>
            `,
            style: {{ background: 'rgba(13,17,23,0.92)', color: '#e0e0e0', padding: '10px 14px', borderRadius: '8px', border: '1px solid #30363d', fontSize: '13px', lineHeight: '1.6' }}
        }};
    }}

    return null;
}}

function confColor(conf) {{
    if (conf >= 0.8) return [78, 204, 163, 220];
    if (conf >= 0.5) return [249, 237, 105, 200];
    return [255, 107, 107, 200];
}}

function buildLayers() {{
    const layers = [];
    const altMult = altitudeScale;  // 高度を強調するスケール倍率

    // --- 流星軌道: 3Dライン ---
    const meteorLineData = meteors.map(m => ({{
        sourcePosition: [m.start_lon, m.start_lat, m.start_alt * 1000 * altMult],
        targetPosition: [m.end_lon, m.end_lat, m.end_alt * 1000 * altMult],
        _meteor: m,
        _type: 'meteor-line',
    }}));

    layers.push(new deck.LineLayer({{
        id: 'meteor-lines',
        data: meteorLineData,
        getSourcePosition: d => d.sourcePosition,
        getTargetPosition: d => d.targetPosition,
        getColor: d => confColor(d._meteor.confidence),
        getWidth: 4,
        widthMinPixels: 2,
        widthMaxPixels: 8,
        pickable: true,
    }}));

    // --- 流星の始点ドット（緑）と終点ドット（赤） ---
    const startPoints = meteors.map(m => ({{
        position: [m.start_lon, m.start_lat, m.start_alt * 1000 * altMult],
        color: [78, 204, 163, 230],
        _type: 'start-point',
        _meteor: m,
    }}));
    const endPoints = meteors.map(m => ({{
        position: [m.end_lon, m.end_lat, m.end_alt * 1000 * altMult],
        color: [255, 107, 107, 230],
        _type: 'end-point',
        _meteor: m,
    }}));

    layers.push(new deck.ScatterplotLayer({{
        id: 'meteor-endpoints',
        data: [...startPoints, ...endPoints],
        getPosition: d => d.position,
        getFillColor: d => d.color,
        getRadius: 800,
        radiusMinPixels: 4,
        radiusMaxPixels: 12,
        pickable: false,
    }}));

    // --- 流星の垂直ドロップライン（地表→始点、地表→終点） ---
    const dropLines = [];
    meteors.forEach(m => {{
        dropLines.push({{
            sourcePosition: [m.start_lon, m.start_lat, 0],
            targetPosition: [m.start_lon, m.start_lat, m.start_alt * 1000 * altMult],
        }});
        dropLines.push({{
            sourcePosition: [m.end_lon, m.end_lat, 0],
            targetPosition: [m.end_lon, m.end_lat, m.end_alt * 1000 * altMult],
        }});
    }});

    layers.push(new deck.LineLayer({{
        id: 'drop-lines',
        data: dropLines,
        getSourcePosition: d => d.sourcePosition,
        getTargetPosition: d => d.targetPosition,
        getColor: [100, 100, 120, 80],
        getWidth: 1,
        widthMinPixels: 1,
        pickable: false,
    }}));

    // --- 地表投影線（流星軌道を地表面に投影） ---
    const projLines = meteors.map(m => ({{
        sourcePosition: [m.start_lon, m.start_lat, 0],
        targetPosition: [m.end_lon, m.end_lat, 0],
        _meteor: m,
    }}));

    layers.push(new deck.LineLayer({{
        id: 'ground-projection',
        data: projLines,
        getSourcePosition: d => d.sourcePosition,
        getTargetPosition: d => d.targetPosition,
        getColor: d => {{
            const c = confColor(d._meteor.confidence);
            return [c[0], c[1], c[2], 90];
        }},
        getWidth: 2,
        widthMinPixels: 1,
        widthMaxPixels: 4,
        pickable: false,
        getDashArray: [6, 4],
        dashJustified: true,
        extensions: [new deck.PathStyleExtension({{ dash: true }})],
    }}));

    // 地表投影の始点・終点マーカー（小さなリング）
    const projEndpoints = [];
    meteors.forEach(m => {{
        projEndpoints.push({{
            position: [m.start_lon, m.start_lat, 0],
            color: [78, 204, 163, 120],
        }});
        projEndpoints.push({{
            position: [m.end_lon, m.end_lat, 0],
            color: [255, 107, 107, 120],
        }});
    }});

    layers.push(new deck.ScatterplotLayer({{
        id: 'ground-projection-endpoints',
        data: projEndpoints,
        getPosition: d => d.position,
        getFillColor: [0, 0, 0, 0],
        getLineColor: d => d.color,
        getRadius: 600,
        radiusMinPixels: 3,
        radiusMaxPixels: 8,
        stroked: true,
        filled: false,
        lineWidthMinPixels: 1,
        pickable: false,
    }}));

    // --- 拠点マーカー ---
    const stationData = STATIONS.map(s => ({{ ...s, _type: 'station' }}));
    layers.push(new deck.ScatterplotLayer({{
        id: 'stations',
        data: stationData,
        getPosition: d => [d.longitude, d.latitude, 0],
        getFillColor: [233, 69, 96, 230],
        getRadius: 1200,
        radiusMinPixels: 6,
        radiusMaxPixels: 14,
        pickable: true,
        stroked: true,
        getLineColor: [255, 255, 255, 150],
        lineWidthMinPixels: 2,
    }}));

    // --- 拠点→流星への観測ライン（接続線） ---
    // 各流星について、検出した拠点から流星始点への薄いラインを描画
    const obsLines = [];
    meteors.forEach(m => {{
        if (m.detections) {{
            m.detections.forEach(det => {{
                const st = STATIONS.find(s => s.station_id === det.station_id);
                if (st) {{
                    obsLines.push({{
                        sourcePosition: [st.longitude, st.latitude, 0],
                        targetPosition: [m.start_lon, m.start_lat, m.start_alt * 1000 * altMult],
                    }});
                }}
            }});
        }}
    }});

    layers.push(new deck.LineLayer({{
        id: 'observation-lines',
        data: obsLines,
        getSourcePosition: d => d.sourcePosition,
        getTargetPosition: d => d.targetPosition,
        getColor: [233, 69, 96, 40],
        getWidth: 1,
        widthMinPixels: 1,
        pickable: false,
    }}));

    // --- FOV 扇形 ---
    if (showFov) {{
        const fovPolygons = [];
        STATIONS.forEach(st => {{
            if (!st.cameras) return;
            st.cameras.forEach(cam => {{
                const pts = [];
                const radius = 0.45; // 約50km in degrees
                const startA = cam.azimuth - cam.fov_horizontal / 2;
                const endA = cam.azimuth + cam.fov_horizontal / 2;
                pts.push([st.longitude, st.latitude]);
                for (let a = startA; a <= endA; a += 2) {{
                    const rad = a * Math.PI / 180;
                    const dlon = radius * Math.sin(rad) / Math.cos(st.latitude * Math.PI / 180);
                    const dlat = radius * Math.cos(rad);
                    pts.push([st.longitude + dlon, st.latitude + dlat]);
                }}
                pts.push([st.longitude, st.latitude]);
                fovPolygons.push({{ contour: pts }});
            }});
        }});

        layers.push(new deck.PolygonLayer({{
            id: 'fov-cones',
            data: fovPolygons,
            getPolygon: d => d.contour,
            getFillColor: [233, 69, 96, 12],
            getLineColor: [233, 69, 96, 60],
            lineWidthMinPixels: 1,
            pickable: false,
            stroked: true,
        }}));
    }}

    return layers;
}}

function updateLayers() {{
    if (!deckgl) return;
    deckgl.setProps({{ layers: buildLayers() }});
}}

function loadMeteors() {{
    const dateInput = document.getElementById('date-filter').value;
    const minConf = parseInt(document.getElementById('confidence-filter').value) / 100;

    let url = '/api/triangulated?limit=200';
    if (dateInput) url += '&since=' + dateInput + 'T00:00:00';

    fetch(url)
        .then(r => r.json())
        .then(data => {{
            meteors = data.filter(m => (m.confidence || 0) >= minConf);
            updateLayers();
            updateList();
            document.getElementById('total-count').textContent = meteors.length;
            if (meteors.length > 0) {{
                document.getElementById('last-detection').textContent =
                    new Date(meteors[0].timestamp).toLocaleString('ja-JP');
            }}
        }})
        .catch(e => console.error('Load error:', e));
}}

function resetView() {{
    deckgl.setProps({{ initialViewState: {{ ...INITIAL_VIEW, transitionDuration: 800 }} }});
}}

function toggleFov() {{
    showFov = !showFov;
    updateLayers();
}}

function updateList() {{
    const list = document.getElementById('meteor-list');
    list.innerHTML = '';

    meteors.forEach(m => {{
        const div = document.createElement('div');
        div.className = 'meteor-item';
        const ts = new Date(m.timestamp).toLocaleString('ja-JP');
        div.innerHTML = `
            <span class="time">${{ts}}</span>
            <span class="details">
                <span class="alt">${{m.start_alt.toFixed(0)}}&rarr;${{m.end_alt.toFixed(0)}} km</span>
                <span class="speed">${{m.velocity ? m.velocity.toFixed(0) + ' km/s' : ''}}</span>
            </span>
            <span class="confidence">${{((m.confidence||0)*100).toFixed(0)}}%</span>
        `;
        div.onclick = () => {{
            deckgl.setProps({{
                initialViewState: {{
                    longitude: (m.start_lon + m.end_lon) / 2,
                    latitude: (m.start_lat + m.end_lat) / 2,
                    zoom: 10,
                    pitch: 55,
                    bearing: -20,
                    transitionDuration: 600,
                }}
            }});
        }};
        list.appendChild(div);
    }});
}}

document.addEventListener('DOMContentLoaded', init);
</script>
</body>
</html>"""
