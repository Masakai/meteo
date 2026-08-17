# 設計書: 鳥・コウモリ・飛行機雲 誤検出対策（4方式・カメラ別フラグ切り替え）

- 作成日: 2026-08-17
- 対象プロジェクト: meteo (Meteor Event Tracking and Early Observation)
- 要件トレーサビリティ: ユーザー要望（8/16 camera2・camera3 鳥/コウモリ誤検出分析、8/17 camera3 薄明期間15件誤検出分析）
- 関連Issue / PR: なし（新規ブランチで実装予定）
- 前提となる分析: 8/16 速度・長さ・輝度・confidence・linearity いずれも確定流星80件と分布重複、単純閾値で分離不可。8/17 薄明期間（この日は04:38〜05:06）に15件集中、うち1件をコンポジット画像で飛行機雲と確定。`twilight_min_speed=200px/s`（下限のみ）は速い鳥・飛行機雲（実測513〜1518px/s）に無力。

## 背景・目的

既存の薄明対策（`TWILIGHT_MIN_SPEED` 下限フィルタ、`filter_dark_objects` 暗色除外）は「遅く暗い」誤検出を主眼に設計されており、「速く明るい」鳥・コウモリ・飛行機雲には効かないことが実データで確認されている。単一の閾値調整では確定流星との分布重複を解消できないため、軌跡の形状・時間発展という別の特徴軸を使う新規フィルタが必要。

4方式は仮説の確度・実装コストが異なるため、本番1台構成のまま並行検証できるよう、カメラごとに異なる方式の組み合わせを有効化し、実運用データで効果を比較する。

## 設計概要

### 前提の訂正（コード確認により判明した事実）

ユーザー提示の背景説明では「軌跡点列（xs, ys の全点）は`MeteorEvent`にも`detections.jsonl`にも保存されない設計」とあるが、これは**イベント確定後**の話であり、**追跡中の全期間**では既に保持されている。

`RealtimeMeteorDetector.active_tracks: Dict[int, List[Tuple[float, int, int, float]]]`（`meteor_detector_realtime.py:592`）は各トラックの全時刻・x・y・輝度を保持し続けており、`_finalize_track()`（同734-823行）は753-754行で `xs = [p[1] for p in track_points]` / `ys = [p[2] for p in track_points]` として実際に取り出している。破棄されるのはこの直後、`MeteorEvent(frames=[], ...)` を生成する時点（822行）で、`xs`/`ys` 自体を保持するフィールドが `MeteorEvent` に存在しないためである。

この事実により、方式1は2段階に分離できる。

- **方式1a（蛇行フィルタ本体）**: `_finalize_track()` 内で既に取り出し済みの `xs`/`ys` から統計量を計算するだけ。新規データ構造・新規メモリ確保は不要、計算コストはトラック確定時のみ・点数N（本番`min_track_points=3`前提で数点〜十数点）のO(N)。フレーム毎のホットループには影響しない。
- **方式1b（軌跡点列の永続化）**: `MeteorEvent`・`detections.jsonl` に `xs`/`ys` を保存する部分。これは1aの実装・閾値決定に先立ち、実データで羽ばたき統計量の分布を観測するために必要な、効果測定専用の拡張。

### 座標系に関する既知の注意（新規コードでは踏襲しない）

`meteor_detector_rtsp_web.py:308-311` で `objects` の centroid は `scale_factor`（`1.0/process_scale`）倍されてフル解像度座標に変換されてから `track_objects()`（313行）に渡る。したがって `active_tracks` の xs/ys は**フル解像度座標**である。

一方、`nuisance_mask` は proc 解像度（`(proc_w, proc_h)`、`SCALE` 倍後）で生成される（`meteor_detector_rtsp_web.py:151-153`, `meteor_mask_utils.py`）。既存の `_calculate_line_overlap_ratio()`（`meteor_detector_realtime.py:862-874`）は `nuisance_mask` と同サイズの `np.zeros_like` にフル解像度座標の `start_point`/`end_point` で線を描いており、`SCALE < 1.0` の場合はスケール不整合が生じている可能性がある（未検証・本設計のスコープ外の既存挙動）。

本設計で新設する方式1a（蛇行角度）・方式2（残光チェック）は、この既存パターンをコピーしない。具体的には、方式1aは角度（スケール不変）を主指標にする、方式2はフル解像度フレームに対してフル解像度座標のまま処理する、という原則で座標系不整合を新規に持ち込まない。

### 全体方針

1. カメラ別フラグ切り替えは、2026-06-19設計済み・v3.18.0で稼働中の**カメラ個別設定機構**（`/settings` 画面の対象カメラドロップダウン → `POST /camera_settings/apply_one` → 当該カメラの `POST /apply_settings` → `runtime_settings/camera{N}.json`）にそのまま乗せる。`generate_compose.py`・streamers フォーマットの変更は不要。
2. 新設パラメータは環境変数（コンテナ起動時デフォルト）+ `runtime_settings/<camera>.json`（WebUI経由の永続オーバーライド、優先）という既存の二層構造に従う。データ構造・処理経路に関わる方式1b・方式2は`bird_filter_enabled`と同様「起動時反映（`startup_bool_fields`、変更時はコンテナ再起動）」とし、閾値のみの方式1a・方式3は「即時反映（`float_fields`/`int_fields`、`detector.lock`下のsetattr）」とする。
3. `meteor_detector_common.py` に新規の純関数（蛇行角度計算等）を追加する。理由: (a) `calculate_linearity`/`calculate_confidence` と同種のアルゴリズム純関数の既存置き場であること、(b) RTSP非依存でコンテナなしのユニットテストが可能なこと、(c) `meteor_detector_realtime.py` への diff を最小化できること。`astro_utils.py` は天文計算のみを扱う既存の役割を変える理由がなく、変更不要。
4. `meteor_detector_realtime.py`（変更禁止ファイル）への変更は最小限にとどめる。方式2・方式4は `meteor_detector_rtsp_web.py` 側の検出ループ・保存フロー拡張のみで実現でき、`meteor_detector_realtime.py` の変更が不要。

## 検討した選択肢と却下理由

### 蛇行フィルタの実装位置: `meteor_detector_realtime.py` 内 vs `meteor_detector_common.py` 純関数 + 呼び出し（採用）

`_finalize_track()` 内にロジックをベタ書きする案も検討したが、却下。理由: (1) ユニットテストがコンテナ非依存で書けなくなる（`meteor_detector_realtime.py` は `cv2`/`Thread`等の依存を含む）、(2) `calculate_linearity`と同様に「軌跡点列→スカラー特徴量」という既に確立されたパターンに揃えることで、将来の閾値調整時の見通しが良くなる。純関数を`meteor_detector_common.py`に置き、`_finalize_track()`からは数行の呼び出しのみに留める。

### 方式2の判定タイミング: イベント確定を保留して残光を待つ vs 確定後に非同期でポストチェック（後者を採用）

「トラック確定後、残光ウィンドウ分だけ判定を遅延させる」案を検討したが却下。理由: `EventMerger` は `merge_max_gap_time`（既定1.5秒）分イベントを`pending`に滞留させてから`flush_expired()`で確定させる設計であり、ここに独自の待機ロジックを追加すると、v3.18.0で3回のレビューを経て確立したバースト抑制のギャップクラスタリング（到着ログの整合性）と衝突するリスクが高い。

採用案: `merger.flush_expired()` が返す確定イベント（`meteor_detector_rtsp_web.py:341`以降）に対して、`save_meteor_event()` 呼び出しの前に残光チェックを行う。この時点で `_finalize_track()` の発火条件（`gap > max_gap_time` 既定2.0秒）と `merge_max_gap_time`（既定1.5秒）により、イベント終了時刻から少なくとも約3.5秒後まで `RingBuffer` にフレームが蓄積済みであることが構造的に保証される。残光ウィンドウを2秒以内に収める限り、追加の待機は不要。

### 方式2のフレーム取得: 追加の `RingBuffer.get_range()` 呼び出し vs 既存 `save_meteor_event()` の frames 再利用（後者を優先、不足時のみ前者）

`RingBuffer.get_range()` はレンジ内の全フレームを `f.copy()` する（`meteor_detector_realtime.py:462`）。フル解像度20fps×数秒では数百MB規模の複製になりうる。`save_meteor_event()` は既に `event.start_time - clip_margin_before` 〜 `event.end_time + clip_margin_after` のフレームを取得済みのため、残光チェックの観測窓を `clip_margin_after` と同一かそれ以下に設定できる場合は追加取得を行わず、`save_meteor_event()` に渡す前の `frames` を再利用する。観測窓が `clip_margin_after` を超える設定の場合のみ、追加で `get_range()` を1回呼ぶ（詳細は後述の性能見積もり参照）。

### 方式4のバースト抑制への統合 vs 独立実装（独立実装を採用）

`EventMerger` の既存バースト抑制（`burst_window_time`既定1.0秒、`burst_max_events`既定5件）は「同一フレーム群内の空間的散発」を検出する秒オーダーの機構。camera3の8/17事例（15件が28分間に分散）は分オーダーのレート現象であり時間スケールが異なる。`EventMerger`内に混在させると、到着ログの整合性（マージ時に到着として数えない等、v3.18.0で3回のレビューを要した設計）を壊すリスクが高いため、完全に独立したレート監視コンポーネントとして実装する。パラメータ名も `burst_*` と混同しないよう `twilight_rate_*` とする。

### カメラ別フラグの切り替え手段: streamers拡張 vs 既存カメラ個別設定機構の再利用（後者を採用）

`generate_compose.py` の `generate_service()` は現状 `settings` 引数（`config.json` 由来のグローバル辞書）から環境変数を注入しており、streamersファイルの行フォーマット（`url|mask_path|display_name|youtube:key`）にカメラ別の検出パラメータ拡張フィールドは存在しない。streamersフォーマットを拡張してカメラ別デフォルトを注入する案も検討したが、`docker-compose.yml`は「自動生成・手動編集不要」の方針（CLAUDE.md）であり、streamers拡張は影響範囲が`generate_compose.py`本体・パーサ・テストに及び手間が大きい。

2026-06-19設計・v3.18.0で稼働中の「カメラ個別設定」機構（`POST /camera_settings/apply_one` → 当該カメラの `runtime_settings/<camera>.json`）が既に「1台だけ設定を変える」経路を提供しているため、これをそのまま利用する。ただし方式1b・方式2のような「起動時反映（コンテナ再起動要）」フラグは、個別適用後に**該当カメラのみ**再起動する必要がある（`apply_one`のレスポンスに含まれる`restart_required`/`restart_triggers`で判別可能、既存UI動線）。

## 影響範囲

| ファイル | 変更種別 | 変更内容 |
|---------|---------|---------|
| `meteor_detector_common.py` | 修正 | 方式1a用の純関数 `calculate_heading_variance(xs, ys)` （進行方向角度の分散/蛇行度）を追加。既存 `calculate_linearity` の直後に配置し、同様にコンテナ非依存でユニットテスト可能にする |
| `meteor_detector_realtime.py`（変更禁止・今回は許可済み） | 修正 | ① `DetectionParams` に新規パラメータ追加（後述）＋`validate()`にレンジ検証追加。② `MeteorEvent` に `track_xs: List[int]` / `track_ys: List[int]`（方式1b、既定空リストで後方互換）フィールド追加、`to_dict()`は既定でこれを出力しない（オプトイン、詳細は後述）。③ `_finalize_track()` に方式1a（蛇行判定）・方式3（速度上限判定）の棄却分岐を追加。④ `_finalize_track()` が `xs`/`ys` を `MeteorEvent` に渡す1行を追加（方式1b有効時のみ） |
| `meteor_detector_rtsp_web.py` | 修正 | ① `detection_thread_worker()` に方式2（飛行機雲残光チェック）・方式4（薄明期間バーストレート抑制）のロジック追加。② 新規環境変数の読み取り・`current_settings`/`runtime_overrides`反映を追加。③ 方式別棄却カウンタを `state` 経由で `/stats` に露出 |
| `detection_filters.py` | 修正 | 方式4用の純関数 `TwilightRateLimiter`（レート監視クラス、状態はローカル保持）を追加。`build_twilight_params`は変更なし（方式3の`twilight_max_speed`は`DetectionParams`側で完結するため） |
| `detection_state.py` | 修正 | `current_settings` の初期値辞書、および方式別棄却カウンタ用フィールド（`current_mitigation_rejected_counts: dict`）を追加 |
| `http_handlers.py` | 修正 | `/apply_settings` の `int_fields`/`float_fields`/`startup_bool_fields`/`startup_float_fields` テーブルに新規パラメータを追加。`/stats` レスポンスに方式別棄却カウンタを追加 |
| `dashboard_templates_settings.py` | 修正 | `/settings` 画面フォームに4方式のON/OFFチェックボックス・閾値入力欄を追加。JSの `fields` 配列に新規キーを追加 |
| `generate_compose.py` | 修正 | 新規環境変数のグローバルデフォルト値を`generate_service()`の`environment:`ブロックに追加（カメラ別の値は`apply_one`経由のオーバーライドで対応するため、ここはデフォルトのみ） |
| `tests/test_meteor_detector_common.py` | 修正 | `calculate_heading_variance` のユニットテスト追加（直線軌跡・蛇行軌跡・点数不足のケース） |
| `tests/test_meteor_detector_realtime.py` | 修正 | 方式1a・方式3の棄却分岐、`DetectionParams`新規パラメータのレンジ検証テスト追加 |
| `tests/test_detection_filters.py` | 修正 | `TwilightRateLimiter` のユニットテスト追加 |
| `documents/DETECTOR_COMPONENTS.md` | 修正 | 4方式の仕様・パラメータ表・検出フローへの追記 |
| `documents/CONFIGURATION_GUIDE.md` | 修正 | 新規環境変数の一覧・チューニング指針を追加 |
| `astro_utils.py` | 変更なし | 天文計算のみの既存役割を変える理由がない |

## 実装タスク

段階的ロールアウトを前提に、以下の順序で実装する（詳細は後述の「段階的ロールアウト案」参照）。

### フェーズ0: 共通基盤（棄却カウンタ・ログ）

1. `DetectionParams` に4方式共通の下地となるレンジ検証パターンを確認し、新規パラメータ追加時のクランプ実装方針を統一する。
2. `detection_state.py` に `current_mitigation_rejected_counts: dict`（キー: `heading_variance` / `max_speed` / `contrail_afterglow` / `twilight_rate`、値: カウント）を追加。
3. `http_handlers.py` の `/stats` レスポンスに `mitigation_rejected_counts` を追加。
4. `_finalize_track()` 系の棄却ログは既存の `_debug_log`（`METEOR_DEBUG_LOG`既定OFF）ではなく、頻度が低い（トラック確定時のみ）ことを踏まえ既定ONの `print(f"[INFO] rejected_by=...")` 形式で出す（既存の `rejected_by=nuisance_overlap` 等のパターンに揃えつつ、デバッグログの高頻度ノイズとは別扱いにする）。

### フェーズ1: 方式3（薄明期間速度上限フィルタ）

5. `DetectionParams` に `max_speed: float = 0.0`（既定0.0=無効、`exclude_edge_ratio`の既存慣習に倣う）を追加。`validate()`に `max_speed >= 0` のクランプを追加。
6. `_finalize_track()` の既存 `min_speed` チェック（792-795行付近）の直下に対称の棄却分岐を追加。
   ```
   if speed < self.params.min_speed:
       ...(既存)
   if self.params.max_speed > 0 and speed > self.params.max_speed:
       _debug_log(...)  # → [INFO] rejected_by=max_speed
       return None
   ```
7. `detection_filters.py` の `build_twilight_params()` に `twilight_max_speed` 引数を追加し、薄明時のみ `max_speed` を上書きできるようにする（通常時は無効=0.0のまま）。
8. 環境変数 `TWILIGHT_MAX_SPEED`（既定 `0`=無効）を `meteor_detector_rtsp_web.py` の `main()` に追加し、`build_twilight_params()` 呼び出しに渡す。
9. `http_handlers.py` の `float_fields` に `("max_speed", 0.0, None)` を追加（即時反映）。`current_settings` にも反映。

### フェーズ2: 方式1b（軌跡点列の記録・観測専用）

10. `MeteorEvent` に `track_xs: List[int] = field(default_factory=list)` / `track_ys: List[int] = field(default_factory=list)` を追加（`frames`と同様デフォルト空リストで後方互換）。
11. `_finalize_track()` の `MeteorEvent(...)` 生成箇所で、`record_track_points`フラグが真の場合のみ `track_xs=xs, track_ys=ys` を渡す（既定は偽、`frames=[]`のまま=既定挙動不変）。
12. `MeteorEvent.to_dict()` は方式1bが有効な場合のみ `track_points`（`[[x1,y1],[x2,y2],...]`）を出力するオプション引数を追加（`detections.jsonl`のレコードサイズ増加を既定では避ける）。
13. `DetectionParams` に `record_track_points: bool = False` を追加。
14. `http_handlers.py` の `startup_bool_fields` に `record_track_points` を追加（起動時反映＝再起動要。データ構造が変わるため）。
15. 実データで羽ばたき統計量（進行方向角度の分散、屈曲角標準偏差）の分布を観測し、方式1aの閾値を決定する（このタスクは developer/architect 双方が関与する分析タスクであり、実装完了後にユーザー・分析担当と合意する）。

### フェーズ3: 方式1a（蛇行フィルタ本体）

16. `meteor_detector_common.py` に `calculate_heading_variance(xs, ys) -> float` を追加。連続する軌跡点間の進行方向角度（`atan2(dy, dx)`）を求め、隣接角度差の標準偏差（ラジアン、角度のラップアラウンドを考慮）を返す。点数2未満は`0.0`（判定不能、後述のフォールセーフ設計）を返す。
17. `DetectionParams` に `max_heading_variance: float = 0.0`（既定0.0=無効）・`min_heading_variance_points: int = 5`（この点数未満では判定をスキップし通す、フェーズ2の観測データで`min_track_points`本番値3との整合を確認してから決定）を追加。`validate()`にレンジ検証を追加。
18. `_finalize_track()` に方式1aの棄却分岐を追加（`linearity`判定の直後が自然な位置）。点数不足時はフィルタを適用せず通す（fail-open）。
19. `http_handlers.py` の `float_fields`/`int_fields` に対応エントリを追加（即時反映）。

**フェーズ3実装前の必須確認事項（オープンクエスチョン参照）**: `min_track_points=3`（本番値）では蛇行角度が高々1〜2個しか取れず統計的に不安定になりうる。フェーズ2の観測データで、過去の鳥・コウモリ誤検出トラックが実際に何点で確定していたかを先に確認し、方式1aが有効に機能する点数域か判断する。

### フェーズ4: 方式2（飛行機雲の残光チェック）

20. `meteor_detector_rtsp_web.py` に `check_contrail_afterglow(ring_buffer, event, frames_for_save, params) -> bool`（残存判定、真=飛行機雲疑いで棄却）を追加。
    - 観測窓 `contrail_afterglow_window`（既定2.0秒、`clip_margin_after`以下に設定する運用を推奨）が既存の`frames_for_save`（`save_meteor_event`に渡す予定のフレーム列）でカバーされる場合はそれを再利用。超える場合のみ `ring_buffer.get_range(event.end_time, event.end_time + window)` を追加取得。
    - 判定方法: `event.start_point`〜`event.end_point`を結ぶ線分（軌跡経路）上の数点（間引きサンプル、既定5点程度）について、イベント終了直後のフレームで同位置の輝度がイベント終了直前フレームと比べて有意に残存しているかを比較する。既存の`_calculate_line_overlap_ratio`と異なり、マスクとの重なりではなく時系列の輝度残存を見る新規ロジックのため、`meteor_detector_realtime.py`ではなく`meteor_detector_rtsp_web.py`側に置く（変更禁止ファイルへの追加変更を避ける）。
    - 評価不能（フレーム不足、終了時刻がストリーム末尾に近い等）の場合はフィルタを適用せず通す（fail-open）。
21. `detection_thread_worker()` の `merger.flush_expired()` 直後（`save_meteor_event()`呼び出し前）に、`contrail_check_enabled`が真の場合のみ`check_contrail_afterglow()`を呼び、棄却時は`save_meteor_event()`をスキップして`[INFO] rejected_by=contrail_afterglow`をログ出力。
22. 環境変数 `CONTRAIL_CHECK_ENABLED`（既定`false`）・`CONTRAIL_AFTERGLOW_WINDOW`（既定`2.0`）・`CONTRAIL_RESIDUAL_BRIGHTNESS_RATIO`（既定`0.5`、終了直前比でこの比率以上輝度が残っていれば残光ありと判定）を追加。
23. `http_handlers.py` の `startup_bool_fields`に`contrail_check_enabled`、`startup_float_fields`に`contrail_afterglow_window`・`contrail_residual_brightness_ratio`を追加（起動時反映。追加のRingBuffer解析処理が発生するため）。

### フェーズ5: 方式4（薄明期間バーストレート抑制、観測モードから開始）

24. `detection_filters.py` に `TwilightRateLimiter` クラスを追加。直近`twilight_rate_window_sec`（既定300秒=5分）以内に確定した薄明期間中のイベント数を保持し、`twilight_rate_max_events`（既定不明、観測後に決定）を超えた場合に真を返す`should_suppress(now) -> bool`メソッドを持つ。イベント数のカウントのみ行い、既定では抑制を発動しない「観測専用モード」から開始する。
25. `detection_thread_worker()` の薄明`reduce`モード分岐に、確定イベントごとに`TwilightRateLimiter`へ計上する処理を追加。`twilight_rate_suppress_enabled`（既定`false`）が真の場合のみ、感度を一時的に下げる（`build_twilight_params`のプリセットを1段階下げる、または`min_brightness`を引き上げる）処理を追加。
26. 環境変数 `TWILIGHT_RATE_WINDOW_SEC`・`TWILIGHT_RATE_MAX_EVENTS`・`TWILIGHT_RATE_SUPPRESS_ENABLED` を追加。
27. `/stats` に直近ウィンドウの検出レート（観測用）を追加。

## テスト方針

### ユニットテスト（コンテナ非依存、`.venv`で実行可能）

- `tests/test_meteor_detector_common.py`:
  - `calculate_heading_variance`: 完全な直線（分散0付近）、ジグザグ軌跡（高分散）、点数2未満（判定不能扱いの戻り値）。
- `tests/test_meteor_detector_realtime.py`:
  - `DetectionParams`: 新規パラメータ（`max_speed`, `max_heading_variance`, `record_track_points`等）のデフォルト値・レンジ外値のクランプ+WARN。
  - `_finalize_track`: 方式3（`max_speed`超過での棄却、`max_speed=0`で無効化されること）。方式1a（`max_heading_variance`超過での棄却、`min_heading_variance_points`未満でfail-open通過）。
  - `MeteorEvent.to_dict()`: `record_track_points`無効時に`track_points`キーが出力されないこと（既存jsonlフォーマットとの後方互換）。
- `tests/test_detection_filters.py`:
  - `TwilightRateLimiter`: ウィンドウ内イベント数のカウント、ウィンドウ外イベントの除外、`should_suppress`の閾値境界。
  - `build_twilight_params`: `twilight_max_speed`引数追加後も既存呼び出し（引数省略時）が壊れないこと。

### 統合テスト（コンテナ内、`docker compose run --rm <camera> pytest -q`）

- 方式2（残光チェック）は`RingBuffer`・実フレームに依存するため、合成フレーム（一定輝度の矩形を経路上に残す/残さない）を使った統合テストを`meteor_detector_rtsp_web.py`のテストに追加。
- `/apply_settings`・`/stats`エンドポイントのレンジ検証・新規フィールド疎通確認。

### 手動確認

- 各方式を単体でON/OFFし、既存の80件確定流星サンプル（8/16分析で使用したデータ）が誤って棄却されないことを確認（false positive削減が目的で、false negativeを増やさないことが必須要件）。
- カメラ別に異なる方式の組み合わせを`/settings`画面から適用し、`runtime_settings/camera{N}.json`にカメラごとに異なる設定が保存されること、再起動要否の判定が正しく機能することを確認。
- `/stats`の`mitigation_rejected_counts`が方式別に正しく増加すること。

## ログ出力・データ記録の設計（効果測定）

- 各方式の棄却は`_finalize_track()`（方式1a・方式3）または`detection_thread_worker()`（方式2・方式4）で、`[INFO] rejected_by=<方式名>`形式のログを既定ONで出力する（`_debug_log`のホットループ高頻度ノイズとは分離し、トラック確定時のみの低頻度ログとして扱う）。
- `detection_state.py`に方式別カウンタ（`current_mitigation_rejected_counts`）を追加し、`/stats`のJSONレスポンスに`mitigation_rejected_counts: {"heading_variance": N, "max_speed": N, "contrail_afterglow": N, "twilight_rate": N}`として露出する。既存の`_burst_dropped`がWARN文中にしか現れず集計に使えていない反省を踏まえ、必ず構造化された形で`/stats`から参照可能にする。
- 方式1bが有効なカメラでは`detections.jsonl`に`track_points`が記録されるため、これを使って事後にオフラインで閾値のチューニング・各方式の的中率を計算できる。

## 各方式の性能影響の見積もり

本番greeng4はIntel N100、コンテナCPUが90%前後で飽和傾向にある前提。

| 方式 | 発火頻度 | 追加コスト | 見積もり |
|---|---|---|---|
| 1a（蛇行フィルタ） | トラック確定時のみ（本番実績で1晩あたり数十〜百件規模） | O(N)、N=軌跡点数（本番`min_track_points=3`前提で数点〜十数点） | 無視できる水準。フレーム毎のホットループ（`detect_bright_objects`）には影響しない |
| 1b（点列記録） | トラック確定時のみ | `MeteorEvent`に2つのリスト追加（数点〜数十点のint）、`detections.jsonl`のレコードサイズ微増 | メモリ・I/Oともに軽微。ただし`record_track_points`はデータ構造変更のため起動時反映（再起動要）とし、既定OFFで運用に影響しない |
| 3（速度上限） | トラック確定時のみ | 既存`min_speed`判定と対称の1条件分岐 | 無視できる水準 |
| 2（残光チェック） | 確定イベントごと（1晩あたり数件〜数十件、方式1と異なり全確定イベントが対象） | 既存`frames`再利用時はほぼ無償。観測窓が`clip_margin_after`を超える設定の場合、追加`RingBuffer.get_range()`1回（フル解像度×観測窓秒数のフレームコピー、数十MB規模になりうる） | 確定イベント発生頻度自体が低い（フレーム毎ではない）ため、CPU飽和への影響は限定的。ただし観測窓を広げるほど`get_range`のコピー量が線形に増えるため、既定値2.0秒を超える設定は非推奨とし、必要ならログで観測窓超過を警告する |
| 4（レートリミッタ、観測モード） | 確定イベントごと | カウンタ更新のみ、O(1)〜O(ウィンドウ内イベント数)の古い記録の刈り込み | 無視できる水準。抑制発動時（`twilight_rate_suppress_enabled=true`）は感度プリセット切り替えのみで、追加の重い処理はない |

全体として、4方式ともフレーム毎に実行される`detect_bright_objects()`のホットループには影響せず、確定イベント（トラック終了）というまれなタイミングでのみ発火する設計のため、CPU飽和への追加負荷は小さいと見積もる。最もコストが大きいのは方式2の追加`get_range()`だが、これは設定次第で回避できる。

## 実装の優先順位・段階的ロールアウト案

4方式を同時に有効化せず、以下の順で段階的に進める。

1. **フェーズ0+1（方式3、速度上限）**: 実装コスト最小（既存`min_speed`判定と対称の4行程度）、既存の`build_twilight_params`機構にそのまま乗る。まず1カメラ（例: camera3、薄明誤検出の実績があるカメラ）で有効化し即効性を検証。
2. **フェーズ2（方式1b、観測専用）**: 棄却は行わず記録のみ。1〜2週間分のデータを蓄積し、羽ばたき統計量の分布・実際のトラック点数分布を確認する。ここで方式1aの実装可否・閾値を判断する（オープンクエスチョン参照）。
3. **フェーズ3（方式1a）**: フェーズ2のデータで閾値が決定できた場合のみ実装。点数不足で判定不能なケースが大半を占めるようであれば、本フェーズは見送りまたは`min_track_points`の見直しとセットで再検討する。
4. **フェーズ4（方式2、残光チェック）**: 実装・検証コストが最も高い（新規のフレーム輝度比較ロジック）。1カメラで先行検証してからカメラを広げる。
5. **フェーズ5（方式4、レートリミッタ）**: まず観測モード（`twilight_rate_suppress_enabled=false`）のみで導入し、実際のレート分布を確認してから抑制発動を有効化するかを判断する。感度を動的に下げる副作用があるため、カメラ別A/B比較の再現性を損なわないよう、検証中は原則OFFのまま他方式との比較対象（コントロール群）に使うカメラを設ける。

カメラ割り当て例（3台構成、確定は運用側判断）:
- camera1: 対照群（4方式すべてOFF、既存挙動のベースライン）
- camera2: 方式3のみON
- camera3: 方式3 + 方式1b（観測） + 方式2 ON（薄明誤検出の実績が最も多いカメラで積極的に検証）

## ドキュメント更新が必要なファイル

- `documents/DETECTOR_COMPONENTS.md`: 「検出アルゴリズムフロー」図・「判定条件」ノートに方式1a・方式3の棄却条件を追加。新規セクション「鳥・コウモリ・飛行機雲対策フィルタ（v3.19.0想定）」を追加し、4方式の仕組み・パラメータ表・棄却ログ形式を記載。`MeteorEvent`のフィールド説明に`track_xs`/`track_ys`（既定空リスト、`record_track_points`有効時のみ）を追記。
- `documents/CONFIGURATION_GUIDE.md`: 新規環境変数（`TWILIGHT_MAX_SPEED`, `RECORD_TRACK_POINTS`, `CONTRAIL_CHECK_ENABLED`, `CONTRAIL_AFTERGLOW_WINDOW`, `CONTRAIL_RESIDUAL_BRIGHTNESS_RATIO`, `TWILIGHT_RATE_WINDOW_SEC`, `TWILIGHT_RATE_MAX_EVENTS`, `TWILIGHT_RATE_SUPPRESS_ENABLED`）を既存の「薄明」「鳥シルエット除外」節の近くに追加。カメラ別に異なる設定を適用する運用手順（`/settings`画面の対象カメラドロップダウン使用）への参照を追記。
- `documents/API_REFERENCE.md`: `/stats`レスポンス例に`mitigation_rejected_counts`を追加。`/apply_settings`の対象フィールド一覧に新規パラメータを追加。
- `documents/ARCHITECTURE.md`: 検出フロー図に方式2（残光チェック、保存前のポストチェック）・方式4（レートリミッタ、薄明ループ内）の位置づけを追記。

GitHub Pages公開対象のため、コード変更と同一リリースでドキュメントを更新する（プロジェクトメモリ `project_docs_github_pages` 参照）。

## セキュリティ・互換性・その他の考慮事項

- **後方互換性**: `MeteorEvent`の新規フィールド（`track_xs`/`track_ys`）は既定空リストで追加し、`to_dict()`も既定では出力しないため、既存の`detections.jsonl`パーサ・ダッシュボード側の統計処理に影響しない。`DetectionParams`の新規パラメータはすべて既定値で「無効」（`max_speed=0.0`, `max_heading_variance=0.0`, `record_track_points=False`, `contrail_check_enabled=False`, `twilight_rate_suppress_enabled=False`）となるよう設計し、未設定カメラは現行v3.18.0と完全に同一の挙動を維持する。
- **レンジ検証の二重実装が必須**: `DetectionParams.validate()`（`__post_init__`経由、`meteor_detector_realtime.py`）と`http_handlers.py`の`/apply_settings`検証テーブル（`int_fields`/`float_fields`/`startup_float_fields`）の両方に新規パラメータを追加すること。`validate()`のdocstringが明記する通り、`setattr`ループや`copy.copy`（`build_twilight_params`等）経由の更新は`__post_init__`を通らないため、片方だけでは要件を満たさない。レンジが2箇所で食い違うと運用者の正当な設定値が意図しない値にクランプされる。
- **fail-open原則**: 方式1a（点数不足）・方式2（フレーム不足・評価不能）は、判定不能時にフィルタを適用せず通す設計とする。理由: 本対策は誤検出（false positive）の削減が目的であり、判定不能を理由に確定流星まで誤って棄却する（false negative増加）リスクを避ける。
- **カメラ個別設定との整合**: 方式1b・方式2のフラグは`startup_bool_fields`（起動時反映）とするため、`/settings`画面から個別カメラに適用した際、当該カメラのみ再起動が必要になる。既存の`apply_one`は`restart_required`/`restart_triggers`をレスポンスで返す設計（2026-06-19設計書）のため、UI側の既存動線をそのまま利用できる。
- **既存バースト抑制との非衝突**: `EventMerger`のギャップクラスタリング方式（v3.18.0、`burst_window_time`=秒オーダー）と方式4（`twilight_rate_*`、分オーダー）はデータ構造・判定ロジックともに独立させる。`EventMerger`の到着ログ（`_arrival_times`）や`_prune_arrival_times`のホライズン計算には一切手を入れない。
- **座標系**: 方式1a・方式2ともフル解像度座標・フル解像度フレームで完結させ、既存の`_calculate_line_overlap_ratio`にある可能性のあるスケール不整合（前述）を新規コードに持ち込まない。

## オープンクエスチョン

1. **方式1aの実現可能性判断**: 本番`min_track_points=3`（[[project_detection-params]]、fps低下対策として2026-08-13に5→3へ再変更済み）では、蛇行角度の統計量が1〜2個の隣接角度差しか取れず判定として機能しない可能性がある。フェーズ2（方式1b、観測専用）で実際の誤検出トラックの点数分布を確認してから、方式1aを実装するか・`min_track_points`を検証カメラに限り引き上げるか（検出漏れとのトレードオフ再燃）・本方式を見送るかをユーザーと合意する必要がある。
2. **方式2の残光判定アルゴリズムの精度**: 「経路上の輝度残存」を単純な閾値比較で判定する設計としたが、雲・月明かり等の背景変動との区別が難しい可能性がある。実装後、実際の飛行機雲サンプル（8/17に確認済みの1件を含む）でチューニングが必要。
3. **方式4の`twilight_rate_max_events`の初期値**: camera3の実績（28分で15件）から逆算した目安はあるが、確定的な閾値はフェーズ5の観測データを見てから決定する。
4. **`min_heading_variance_points`とフレームレート低下の関係**: greeng4がCPU飽和で実効fpsが低下すると、同じ`min_track_points`でも捕捉される軌跡点数がさらに減る可能性がある（`estimate_fps_from_frames`のクランプ事例で既に確認された現象）。方式1a・方式2のパラメータチューニングは、CPU負荷が高い時間帯（薄明期は特に処理が重い）の実効fpsも考慮に入れる必要がある。
5. **`record_track_points`有効時の`detections.jsonl`肥大化**: 長時間トラック（`max_track_points`の上限がない）では1レコードのサイズが際限なく増える可能性がある。観測専用フェーズ2の運用期間中に実際のレコードサイズを確認し、必要なら記録点数の間引き（例: 最大N点にサンプリング）を検討する。
