# 実装仕様書: 鳥・コウモリ・飛行機雲 誤検出対策（4方式・カメラ別フラグ切り替え）

- 作成日: 2026-08-17
- 対象プロジェクト: meteo (Meteor Event Tracking and Early Observation)
- 要件トレーサビリティ: ユーザー要望（8/16 camera2・camera3 鳥/コウモリ誤検出分析、8/17 camera3 薄明期間15件誤検出分析）
- 関連設計書: `documents/designs/2026-08-17-bird-plane-contrail-mitigation.md`
- 関連レビュー報告書:
  - `documents/reviews/2026-08-17-bird-plane-contrail-mitigation-review.md`（第1回、判定「要修正」、指摘8件は是正済み）
  - `documents/reviews/2026-08-17-bird-plane-contrail-mitigation-review-2.md`（第2回、判定「要修正」、新規指摘Bは是正済み）
  - `documents/reviews/2026-08-17-bird-plane-contrail-mitigation-review-3.md`（第3回、判定「承認」。指摘C・D・Eは任意対応として本ドキュメントで是正、指摘Fは記録のみ・対応不要）
- 関連Issue / PR: なし（`feature/bird-plane-contrail-mitigation`ブランチで実装、未コミット）

## 概要

軌跡の形状・速度・時間発展という新しい特徴軸を使い、鳥・コウモリ・飛行機雲の誤検出を抑制する4方式（1a蛇行フィルタ、1b軌跡点列記録、2飛行機雲残光チェック、3薄明期間速度上限フィルタ、4薄明期間バーストレート抑制）を一括実装した。設計書の「実装タスク」節・全フェーズ（0〜5）を対象とし、段階的ロールアウトではなく一括実装した。全パラメータの既定値は無効（0またはfalse）で、既存の検出結果には一切影響しない。

## 変更ファイル一覧

| ファイル | 変更種別 | 変更内容 |
|---------|---------|---------|
| `meteor_detector_common.py` | 修正 | `calculate_heading_variance(xs, ys)`純関数を追加（方式1a）。【是正】docstringのoff-by-one記述を「点数2未満」→「点数3未満」に修正（指摘6） |
| `meteor_detector_realtime.py` | 修正 | `DetectionParams`に`max_speed`/`max_heading_variance`/`min_heading_variance_points`/`record_track_points`追加＋`validate()`拡張。`MeteorEvent`に`track_xs`/`track_ys`追加、`to_dict()`をデータ駆動化。`_finalize_track()`に方式1a・方式3の棄却分岐、`RealtimeMeteorDetector.rejected_counts`カウンタ追加。`EventMerger._merge()`で軌跡点列を連結。【是正】`validate()`の`min_heading_variance_points`下限を2→3に修正（指摘6）。【第3回是正】`RingBuffer`に`get_nearest_in_range()`メソッドを新設（指摘C） |
| `meteor_detector_rtsp_web.py` | 修正 | `check_contrail_afterglow()`関数新設（方式2）、`_TWILIGHT_SENSITIVITY_STEP_DOWN`マッピング追加、`detection_thread_worker()`に`_save_if_allowed()`ヘルパーで方式2・4方式4を統合、`TwilightRateLimiter`をワーカー内に組み込み、`main()`/`process_rtsp_stream()`に新規環境変数・runtime_overrides読み取りを追加。【第1回是正】`check_contrail_afterglow()`の判定式を背景差し引き後の超過輝度比較に変更（指摘1）、`_clamp_env_value_and_warn()`ヘルパー新設と`process_rtsp_stream()`でのクランプ適用（指摘3）。【第2回是正】`check_contrail_afterglow()`にイベント開始前のベースラインフレーム取得・比較を追加し、経路パッチ内部の静止高輝度（恒星・ホットピクセル）が超過輝度に混入する問題を是正（新規指摘B）。【第3回是正】baseline/before/afterの3フレーム取得を`RingBuffer.get_range()`+`_nearest_frame_entry()`から`RingBuffer.get_nearest_in_range()`に置き換え、不要なフレーム複製コストを削減（指摘C）。baselineの下限クランプ`max(0.0, event.start_time - window)`を撤去し、`get_nearest_in_range()`が範囲外を無視する仕様に委ねる形に変更（指摘D）。【最終レビュー是正】最後の実呼び出し元を失い未使用になった`_nearest_frame_entry()`ヘルパー本体を削除、未使用となった`typing.Tuple`importも削除 |
| `detection_filters.py` | 修正 | `TwilightRateLimiter`クラス追加（方式4）、`build_twilight_params()`に`twilight_max_speed`引数追加（方式3） |
| `detection_state.py` | 修正 | `current_mitigation_rejected_counts`辞書フィールド追加 |
| `http_handlers.py` | 修正 | `/apply_settings`の`int_fields`/`float_fields`/`startup_float_fields`/`startup_int_fields`(新設)/`startup_bool_fields`に新規パラメータ追加、`overrides_update`/`settings_updates`の対象キーにも追加、`/stats`に`mitigation_rejected_counts`追加。【是正】`int_fields`の`min_heading_variance_points`下限を2→3に修正（指摘6） |
| `dashboard_templates_settings.py` | 修正 | 「鳥・コウモリ・飛行機雲対策」パネルを新設（4方式のON/OFF・閾値入力欄）、`fields`配列・`defaultSettings`に新規キー追加。【是正】`min_heading_variance_points`のinput要素の`min`属性を2→3に修正（指摘6、`validate()`/`int_fields`とのレンジ一致要件を満たすための追加箇所） |
| `generate_compose.py` | 修正 | `generate_service()`の`environment:`ブロックに新規環境変数のデフォルト値を追加 |
| `tests/test_meteor_detector_common.py` | 修正 | `calculate_heading_variance`のテスト3件追加 |
| `tests/test_meteor_detector_realtime.py` | 修正 | 新規パラメータのレンジ検証・棄却分岐・fail-open・既定値false-negative保証テスト15件追加。【是正】`min_heading_variance_points`クランプ後の期待値を2→3に修正（指摘6）。【第3回是正】`TestRingBufferGetNearestInRange`（9件）を追加。`get_range()`+`min()`との選択結果一致、`end_exclusive`境界、タイブレーク、範囲外`None`、コピー意味論（返り値を書き換えてもバッファ内が汚れないこと）を検証（指摘C） |
| `tests/test_detection_filters.py` | 修正 | `TwilightRateLimiter`・`build_twilight_params`拡張のテスト7件追加 |
| `tests/test_meteor_detector_rtsp_web.py` | 修正 | `check_contrail_afterglow`・`_nearest_frame_entry`のテスト8件追加。【第1回是正】指摘1の判定式変更を検出できる非一様フレーム＋背景輝度スイープのテストに全面書き換え（指摘2）。【第2回是正】全ケースにベースラインフレームを追加、経路パッチ内部の静止高輝度混入テスト（`test_static_star_in_patch_is_not_flagged_when_meteor_vanishes`：背景×静止輝点×`residual_brightness_ratio`のスイープ6ケース）・恒星混入時も本物の残光は検出できることを確認するテスト（`test_static_star_does_not_mask_real_afterglow`）・ベースライン欠落時のfail-openテスト（`test_missing_baseline_frame_fails_open`）を追加（新規指摘B）。【第3回是正】`test_nearest_baseline_before_start_time_is_selected_over_older_candidate`（複数baseline候補から`start_time`直前が正しく選ばれること）・`test_baseline_older_than_tolerance_fails_open`（ベースラインが許容誤差を超えて古い場合にfail-openで通ること）の2件を追加（指摘E）。【最終レビュー是正】本番コードから最後の実呼び出し元を失った`_nearest_frame_entry()`本体の削除に伴い、参照が`TestNearestFrameEntry`（2件）のみになったためこのテストクラスごと削除 |
| `documents/DETECTOR_COMPONENTS.md` | 修正 | 「鳥・コウモリ・飛行機雲対策フィルタ（v3.19.0）」新設セクション、検出アルゴリズムフロー図・判定条件ノート・`MeteorEvent`フィールド説明・`/stats`例・`detection_filters.py`セクション更新。【第1回是正】方式2の説明（表・プロセス説明）を背景差し引き方式に改版（指摘1に付随）。【第2回是正】方式2の説明をベースライン差し引き方式（3フレーム比較）に改版し、痕の幅9px以上での見逃し・RingBuffer実効長の制約を既知の限界に追記（新規指摘B・記録のみ指摘） |
| `documents/CONFIGURATION_GUIDE.md` | 修正 | 新規環境変数8個の一覧、`max_speed`/`max_heading_variance`等のパラメータ詳細説明を追加。【第1回是正】`CONTRAIL_RESIDUAL_BRIGHTNESS_RATIO`の説明を背景差し引き方式に改版（指摘1に付随）。【第2回是正】同項目の説明をベースライン差し引き方式に改版し、推奨レンジ`0.3`~`0.7`が静止高輝度源混入下でも安全であることを明記 |
| `documents/API_REFERENCE.md` | 修正 | `/stats`レスポンス例・フィールド表、`/apply_settings`リクエスト例・フィールド表に新規パラメータを追加。【第2回是正】`min_heading_variance_points`のレンジ表記を「2以上」→「3以上」に修正（新規指摘A） |
| `documents/ARCHITECTURE.md` | 修正 | 流星検出シーケンス図に方式2（残光チェック）・方式4（レート記録）を追記、`detections.jsonl`フォーマットに`track_points`のnote追加 |

【第1回是正】【第2回是正】は本ドキュメントがそれぞれのレビュー報告書の是正処置記録に基づき追加で行った修正箇所を示す。

`astro_utils.py`は設計書の結論通り変更していない。

## 実装の詳細

### 方式1a（蛇行フィルタ）

`meteor_detector_common.py`の`calculate_heading_variance(xs, ys)`が、連続する軌跡点間の進行方向角度（`atan2(dy, dx)`）の隣接差（`[-pi, pi]`にラップアラウンド正規化）の標準偏差を返す。点数3未満（角度差を計算できない）は`0.0`（判定不能）を返す。

`_finalize_track()`（`meteor_detector_realtime.py`）で`linearity`判定の直後に棄却分岐を追加した。`max_heading_variance > 0`かつ軌跡点数が`min_heading_variance_points`（既定5）以上の場合のみ判定し、それ以外はフィルタを適用せず通す（fail-open）。

本番`min_track_points=3`（2026-08-13にfps低下対策として5から3へ再変更済み）では隣接角度差が高々1〜2個しか取れず、既定の`min_heading_variance_points=5`のもとでは事実上fail-openとなり方式1aは無効化された状態で動作する。これはオープンクエスチョン1に対する回答であり、欠陥ではなく既定構成での意図された挙動としてドキュメントに明記した。

### 方式1b（軌跡点列の記録、観測専用）

`MeteorEvent`に`track_xs: List[int]`/`track_ys: List[int]`（`field(default_factory=list)`）を追加。`_finalize_track()`が`record_track_points`有効時のみ値を渡す。`EventMerger._merge()`は断片マージ時に`prev`と`new`の点列を連結する（設計書に明記のない部分だが、観測データとして有用な選択として採用）。

`to_dict()`は`track_xs`/`track_ys`が非空の場合のみ`track_points`キーを出力する**データ駆動**の設計にした。設計書のタスク12は「`to_dict()`にオプション引数を追加する」としていたが、`save_meteor_event()`が`event.to_dict()`を引数なしで呼び出しており、オプション引数を追加しても到達不能なコード（デッドコード）になる。データ非空性で判定することで、`record_track_points`が真の場合にのみ`track_xs`/`track_ys`が値を持つという構造上の保証（`_finalize_track()`側の制御）を使い、追加の配線なしで同じ挙動を実現した（**設計からの逸脱1**）。

### 方式2（飛行機雲の残光チェック）

`meteor_detector_rtsp_web.py`に`check_contrail_afterglow(ring_buffer, event, params, *, window, residual_brightness_ratio, sample_points, frame_time_tolerance_ratio, min_excess_brightness)`を新設。経路上5点（既定）をサンプリングし、終了直前フレーム（`event.end_time`に最も近い）と終了`window`秒後フレーム（`event.end_time + window`に最も近い）を比較する。各サンプル点で経路パッチ（半径3px）の平均輝度から、その外側のリング状領域（内半径6px〜外半径10px、隙間を空けて経路自体の輝度の混入を避ける）の中央値を背景推定値として差し引いた「超過輝度」を求め、終了直前比で終了直後の超過輝度が`residual_brightness_ratio`（既定0.5）以上残っているサンプル点が半数以上あれば真（飛行機雲疑い）を返す。

**設計からの逸脱2**: 設計書は「`save_meteor_event()`に渡す予定の`frames_for_save`を再利用する」としていたが、`save_meteor_event()`（`meteor_detector_realtime.py`、変更禁止ファイル）はフレームを内部で`ring_buffer.get_range()`により取得しており、呼び出し元はフレームを保持していない。再利用するには`save_meteor_event()`のシグネチャ変更が必要になり、変更禁止ファイルへの追加変更を避ける設計方針（設計書の全体方針4）と矛盾する。`contrail_check_enabled`は既定`False`で確定イベント自体が低頻度のため、`check_contrail_afterglow()`内で独立して`ring_buffer.get_range()`を1回（before/after合わせて2回）呼ぶ実装とした。

**fail-open条件の強化**（advisorレビューで発見・修正）: 当初の実装は`_nearest_frame()`が要求時刻からどれだけ離れたフレームでも「最も近い」という理由だけで採用してしまい、`RingBuffer`が観測窓分のフレームにまだ到達していない場合（ストリーム終端付近、`finalize_all()`/`flush_all()`のシャットダウン経路）に、終了直後のフレームを誤って「window秒後の輝度」として比較してしまう欠陥があった。これは確定流星が誤って「残光あり」と判定され棄却されるリスク（fail-open原則違反）に直結する。`frame_time_tolerance_ratio`（既定0.25、`window`に対する比率、下限0.05秒）による許容誤差ガードを追加し、要求時刻から許容誤差を超えてずれたフレームしか取得できない場合は評価不能としてfail-openで通すよう修正した。

**判定ロジック本体のfail-open違反の是正（第1回レビュー指摘1、本ドキュメントは是正後の記述）**: 当初の実装は経路パッチの絶対輝度（`brightness_after >= brightness_before * residual_brightness_ratio`）を直接比較しており、判定式に背景輝度が含まれたままだった。流星が完全に消滅しても背景（薄明の空・月明かり・光害）が明るければ`brightness_after`は背景値のまま高く、`brightness_before`（背景+流星）の`residual_brightness_ratio`倍を容易に超えてしまい、確定流星が誤って「残光あり」と棄却される。前後フレームが完全に同一の静止シーンでも常に真を返す（比が常に1.0になるため）という、fail-open原則に正面から違反する欠陥だった。特に誤棄却が起きる背景輝度域（実測でおおむね100以上）が本機能の主対象である薄明期間そのものと一致しており重大だった。

是正として、各サンプル点で経路パッチの平均輝度から周辺リング領域（背景）の中央値を差し引いた「超過輝度」で比較する方式に変更した。背景輝度そのものはbefore/after双方で相殺されるため、背景が明るくても流星が実際に消滅していれば正しく通過する。加えて、終了直前の超過輝度が`min_excess_brightness`（既定8.0）未満のサンプル点は「流星由来の輝度上昇がこの点に観測できない＝判定不能」として`residual_hits`の分母（`valid_samples`）から除外するようにした。この結果、前後フレームが完全に同一の静止シーンでは全サンプル点がこの条件でスキップされ`valid_samples == 0`となり、確実に`False`（残光なしとして通す）を返す。この変更に伴い`valid_samples`の意味も「経路がフレーム範囲内にあるサンプル点数」から「流星由来の輝度超過が観測できた（判定可能だった）サンプル点数」に変わっている。

**追加のfail-openガード（自己発見バグ、advisorレビューで発見・修正）**: `valid_samples`の意味変更により、判定可能なサンプル点が少数（極端には1点）のみの場合、星やホットピクセル等の単発ノイズによる残光っぽい値1点だけで`residual_hits / valid_samples`比が跳ね上がり誤棄却しうる欠陥が新たに生じることに気づいた。これは指摘1と同じ「低情報量の状況でfail-openにならない」というクラスの欠陥であるため、判定可能なサンプル点数が`sample_points`の過半数（`max(2, (sample_points + 1) // 2)`、既定`sample_points=5`なら3点）未満の場合は判定不能としてfail-openで通すガードを追加した（`test_single_informative_sample_fails_open`で検証）。

既知の限界: 飛行機雲がwindow秒以内に周囲へ拡散した場合、背景推定用のリング領域も明るくなり超過輝度が過小評価される可能性がある。これは見逃し方向（false negativeではなくfalse positiveの取りこぼし）でありfail-open原則には反しないが、方式2の感度上の制約として認識しておく必要がある。

**パッチ内部の静止高輝度混入によるfail-open違反の是正（第2回レビュー新規指摘B、本ドキュメントは是正後の記述）**: 指摘1の是正（リング背景差し引き）は、経路パッチの**周囲**の輝度しか除去できない。パッチ**内部**に恒常的に存在する高輝度源（恒星・ホットピクセル・固定光源）がある場合、その輝度はbefore/after双方の超過輝度に等しく残ってしまう。`excess_before = 静止輝度 + 流星の寄与`、`excess_after = 静止輝度`となるため、静止輝度が十分明るいと`excess_after >= excess_before * residual_brightness_ratio`を満たしてしまい、流星が完全に消滅していても「残光あり」と誤棄却する。第2回レビューの実測では、`residual_brightness_ratio`の推奨レンジ下限（`CONFIGURATION_GUIDE.md`記載の`r=0.3`）において、背景輝度100（薄明相当）に対し絶対輝度152程度の静止輝点（通常の恒星の輝度域）でこの誤棄却が発生することが判明した。指摘1と同じクラスのfail-open違反であり、`check_contrail_afterglow()`は`exclusion_mask`/`nuisance_mask`のいずれも参照しないため、運用者によるマスクでの緩和も効かない構造だった。

是正として、イベント開始前（流星が写り込む前、`event.start_time`より厳密に前）の**ベースラインフレーム**を`ring_buffer`から追加で取得し、同じリング差し引き後の超過輝度（`excess_base`）を求める。終了直前・終了直後の超過輝度からそれぞれ`excess_base`を差し引いた`m_before`・`m_after`を実際の比較対象とすることで、before/after/baseの3フレームすべてに等しく存在する静止成分（恒星等）を相殺した。`residual_brightness_ratio`の意味（「流星自身の寄与のうちどれだけが残ったか」の比）は変わらないため、`CONFIGURATION_GUIDE.md`の推奨レンジ`0.3`~`0.7`はそのまま維持できる。

ベースラインフレームの取得には`_nearest_frame_entry()`を再利用し、`event.start_time`を目標時刻として、before/after判定と同じ`frame_time_tolerance_ratio`ベースの許容誤差ガードを適用する。`ring_buffer.get_range()`は閉区間（`start_time <= t <= end_time`）を返すため、`t == event.start_time`のフレーム（流星が写り込んだ最初の追跡フレーム、`MeteorEvent.start_time = min(times)`）を誤ってベースラインに選ばないよう、`t < event.start_time`で厳密に絞り込んだ。ベースラインフレームが取得できない（`RingBuffer`の保持範囲外、シェイプ不一致等）場合は他のフレーム欠落と同様に評価不能としてfail-openで通す。

RingBufferの実効長は`process_rtsp_stream()`内で`min(buffer_seconds, max_duration + 2.0)`に制限される（既定値では`max_duration=10.0`により約12秒）。ベースライン取得にはイベント継続時間+観測窓（`window`秒）程度の余裕が必要なため、この点を既知の限界としてドキュメント化した（実際の流星は継続時間1秒未満が大半のため、通常運用では十分な余裕がある）。

**`get_range()`の3回呼び出しによる不要なフレーム複製の是正（第3回レビュー指摘C）**: `check_contrail_afterglow()`は当初、baseline/before/afterそれぞれについて`RingBuffer.get_range()`（範囲内の全フレームを`f.copy()`で複製したリストを返す）を呼び、その結果を`_nearest_frame_entry()`（`min(frames, key=...)`で1件選ぶ）に渡していた。本関数は3フレームのうち1枚しか使わないため、範囲内の全フレーム分の複製が常に無駄になる。1920x1080・30fps・12秒バッファ想定でイベントごとに約946MBの複製と約149msの検出スレッド停止が発生し、`ring_buffer.add()`と同じ`detection_thread_worker()`ループ内で実行されるため、停止中に`RTSPReader`のフレームキュー（`maxsize=30`、約1秒分）が埋まり最古フレームが破棄される（フレーム落ち）リスクがあった。

是正として、`RingBuffer`（`meteor_detector_realtime.py`）に`get_nearest_in_range(target_time, start_time, end_time, *, end_exclusive=False)`メソッドを新設した。範囲内の候補をタイムスタンプ比較のみで走査し、最も`target_time`に近い1件が見つかった時点でその1フレームのみを複製して返す。既存の`get_range()`は他の呼び出し元（`save_meteor_event()`等、変更禁止ファイル内）への影響を避けるため変更していない。ロックは`get_range()`と同じ`self.lock`（`with self.lock:`ブロックで走査からコピーまでを保護）を使い、スレッド安全性を維持した。

`end_exclusive`引数は、baseline取得（`t < event.start_time`で厳密に絞り込む必要がある半開区間）とbefore/after取得（`t == 目標時刻`を許容する閉区間）で境界の扱いが異なるために設けた。before側は`get_nearest_in_range(event.end_time, event.end_time - window, event.end_time)`（`end_exclusive`省略＝閉区間、`target_time`が上限と一致）、after側は`get_nearest_in_range(target_after_time, event.end_time, target_after_time)`（同様に閉区間）、baseline側は`get_nearest_in_range(event.start_time, event.start_time - window, event.start_time, end_exclusive=True)`（半開区間、`t == event.start_time`を除外）とした。従来コードの`baseline_frames = [tf for tf in baseline_frames if tf[0] < event.start_time]`という呼び出し側フィルタと同じ効果を、メソッド内の`end_exclusive`判定に集約した。

同距離の候補が複数ある場合のタイブレーク（バッファ内で時刻が古い方を優先）は、`min(frames, key=...)`が最初の最小値を返す挙動（deque挿入順=時刻昇順のため実質的に「最初に見つかった最小距離の候補」＝古い方）と一致させた（`best is None or dist < best_dist`という厳密不等号での更新、`test_tie_break_prefers_older_frame_like_get_range_plus_min`で検証）。

本番コードから`get_range()`+`_nearest_frame_entry()`の組み合わせを置き換えたため、`_nearest_frame_entry()`は本番コード（`check_contrail_afterglow()`）からは未使用になった。【最終レビュー是正】最後の実呼び出し元を失ったこのヘルパーは、最終確認レビューでデッドコードと指摘され、関数本体と参照が`TestNearestFrameEntry`（2件）のみになっていたテストクラスをあわせて削除した。削除後に`_nearest_frame_entry`への参照が残っていないことを`grep`で確認済み。

**`start_time == 0.0`でベースラインが取得できない不具合の是正（第3回レビュー指摘D）**: 従来コードは`ring_buffer.get_range(max(0.0, event.start_time - window), event.start_time)`のように下限を`max(0.0, ...)`でクランプしていた。`RingBuffer`のタイムスタンプはストリーム開始を0とする相対時刻（`meteor_detector_rtsp_web.py`の`RTSPReader._read_loop()`が`time.monotonic() - self.start_time`で算出）であり、`event.start_time == 0.0`（ストリーム最初のフレームちょうどでイベントが開始する、確率は低いが起こりうる）の場合、クランプ後の範囲が`[0.0, 0.0]`となり、直後の厳密フィルタ`t < event.start_time`で必ず空集合になっていた。方向はfail-open（ベースライン取得失敗→残光チェック自体がスキップされ確定流星は守られる）だが、本来意図しない無効化だった。

`get_range()`・新設の`get_nearest_in_range()`はいずれも範囲外を単に無視する実装のため、下限を`0.0`に丸める必要は元々ない。是正として`max(0.0, event.start_time - window)`のクランプを撤去し、`event.start_time - window`（負値になりうる）をそのまま`get_nearest_in_range()`に渡すよう変更した。負のタイムスタンプを持つフレームはバッファに存在しないため実害はなく、単に「範囲の下限が実際のバッファ内容より広く空振りする」だけの挙動になる。

### テストの網羅漏れの是正（第3回レビュー指摘E）

第3回レビューの変異テストで、`TestCheckContrailAfterglow`が以下2つの性質を固定できていないことが判明した（実装のバグではなくテストの網羅漏れ）。

1. **ベースライン候補が複数あるとき、`event.start_time`直前の候補が正しく選ばれること**: レビューが提示した変異（targetを`event.end_time`に差し替える）は、baseline候補が全て`t < event.start_time < event.end_time`を満たす場合、`|t - start_time|`と`|t - end_time|`がともに`t`について単調減少なためargminが常に同一フレームになる**等価変異**であり、原理的にどのフィクスチャでもkillできないことを実際に変異を注入して確認した（後述のテスト結果を参照）。代替として、`t < event.start_time`の候補集合の中で「より古い候補（星なし）」と「`start_time`直前の候補（星あり）」を用意し、正しい選択（`start_time`直前）が選ばれれば静止成分が相殺されてFalse、誤って古い候補を選べば静止成分が相殺されずTrueになる、という判定結果の違いで検証する`test_nearest_baseline_before_start_time_is_selected_over_older_candidate`を追加した。このテストは`RingBuffer.get_nearest_in_range()`の選択ロジック自体のバグ（「最初にマッチした候補を無条件に選ぶ」等）を、`TestRingBufferGetNearestInRange`側のユニットテストと合わせて確実に検出できることを、実際に該当ロジックへ変異を注入して確認した。
2. **ベースラインが許容誤差（`tolerance = max(window * frame_time_tolerance_ratio, 0.05)`）を超えて古い場合にfail-openで通ること**: `test_baseline_older_than_tolerance_fails_open`を追加した。before/afterを本物の残光（背景から独立した高輝度がafterもほぼ変わらず残る）にし、ベースライン取得ができていれば本来True（棄却）になるはずのケースで、許容誤差超過ガードによりFalseになることを確認する。このテストが該当ガード（`if abs(baseline_entry[0] - event.start_time) > tolerance: return False`）の削除で実際に赤くなることを確認済み。

### 方式3（薄明期間速度上限フィルタ）

`_finalize_track()`の既存`min_speed`判定の直下に対称の棄却分岐を追加。`max_speed > 0`かつ`speed > max_speed`で棄却する。`build_twilight_params()`に`twilight_max_speed`引数（末尾・既定`0.0`、位置引数互換を維持）を追加し、`0.0`超のときのみ薄明時に`max_speed`を上書きする。

環境変数`TWILIGHT_MAX_SPEED`（既定`0`）は、既存の`TWILIGHT_MIN_SPEED`と同様に`/apply_settings`の対応テーブルが存在しない（dead end）構造であることを確認したため、UIには意図的に公開していない（**設計からの逸脱ではなく、既存の`twilight_min_speed`と同じ扱いに揃えた設計判断**）。

### 方式4（薄明期間バーストレート抑制）

`detection_filters.py`に`TwilightRateLimiter`クラスを追加。`record_event(now)`/`current_rate(now)`/`should_suppress(now)`を持ち、状態はインスタンスのローカルdeque。`max_events <= 0`（既定、`twilight_rate_suppress_enabled=False`時は常にこの状態）は観測専用モードで`should_suppress()`は常に偽。

`detection_thread_worker()`の薄明reduceモード分岐内で、確定イベントごとではなく**フレーム単位**で`should_suppress()`を評価し、真の場合は`_TWILIGHT_SENSITIVITY_STEP_DOWN`マッピング（`faint→high→medium→low`、`low`はそのまま）で感度プリセットを一段階下げてから`build_twilight_params()`を呼ぶ（**設計からの逸脱3**: 設計書は「確定イベントごと」の評価を想定していたが、実際に感度を反映すべきは次の検出フレームであり、フレーム単位評価にした。`TwilightRateLimiter`内部のdeque剪定はO(1)償却のため性能上の懸念はない）。

`record_event()`は`cached_twilight`が真の間、`twilight_rate_suppress_enabled`の値に関わらず常に呼ばれる（レビューで発見した欠陥を修正: 当初`and twilight_rate_suppress_enabled`のガードがあり、観測モード＝既定構成では常にイベント数0のままでレート分布データが一切蓄積できなかった）。`state.current_mitigation_rejected_counts["twilight_rate"]`には直近ウィンドウの現在のレート（累積ではない）を書き込み、薄明期間終了時に0へリセットする。

`should_suppress()`自体は`meteor_detector_rtsp_web.py`のメインループ内で組み込んだ（advisorレビューで発見・修正: 実装当初は`TwilightRateLimiter`インスタンスと`record_event`呼び出しのみが存在し、`should_suppress()`がどこからも呼ばれておらず抑制機能が完全に配線されていなかった）。

`twilight_rate_suppress_enabled=true`かつ`twilight_rate_max_events<=0`はサイレントno-op（コンストラクタが`max_events`を0に固定するため）になる構造上の落とし穴のため、`process_rtsp_stream()`起動時にこの組み合わせを検出して`[WARN]`ログを出す処理を追加した。

### カウンタの集約方式

方式1a・方式3の棄却カウンタは`RealtimeMeteorDetector.rejected_counts`（インスタンスローカル辞書）に持たせ、`meteor_detector_rtsp_web.py`側で毎フレーム`state.current_mitigation_rejected_counts`へコピーする（**設計からの逸脱4**: 設計書は`detection_state.py`への直接カウントを想定しているように読めるが、`meteor_detector_realtime.py`は現状`detection_state`に依存しておらず、直接カウントすると変更禁止ファイルへ新規の`core→state`依存が生じる。detector側にローカル保持し、`meteor_detector_rtsp_web.py`の境界でのみ合算する設計とし、この依存追加を避けた）。方式2・方式4のカウンタは元々`meteor_detector_rtsp_web.py`側の処理のため直接`state`を更新する。

### save_meteor_event呼び出しの一本化

`detection_thread_worker()`内に`_save_if_allowed(ev)`ローカルヘルパーを新設し、4箇所あった`save_meteor_event()`呼び出し（通常フロー・タイムアウト排出・`finalize_all()`後・シャットダウン残処理）をすべてこのヘルパー経由に統一した（**設計からの逸脱5**: 設計書は「`merger.flush_expired()`直後」の1箇所のみに言及していたが、実際には`merger.add_event()`が内部で`flush_expired()`を呼び返す経路（メインの確定イベント経路）を含め計4箇所が確定イベントの保存経路になっており、1箇所だけにフィルタを組み込むと主要経路が素通りしてしまう。全経路を一本化することで方式2の適用漏れを構造的に防いだ）。

### 環境変数/config.json経路のレンジ検証（第1回レビュー指摘3の是正）

`contrail_afterglow_window` / `contrail_residual_brightness_ratio` / `twilight_rate_window_sec` / `twilight_rate_max_events`の4個は`DetectionParams`のフィールドではないため、`DetectionParams.validate()`の対象外で、`main()`の環境変数読み取りにもレンジチェックがなかった。結果として`/apply_settings`（UI経由、`http_handlers.py`の`startup_float_fields`/`startup_int_fields`）はクランプされる一方、`docker-compose.yml`（環境変数）や`config.json`（`runtime_overrides`）経由では範囲外の値がそのまま通っていた。特に`twilight_rate_window_sec`に0や負値が設定されると、`TwilightRateLimiter._prune()`の`cutoff = now - self.window_sec`が未来時刻となり記録が即座に全消去され、レート監視が恒常的に0になる欠陥があった。

是正として、`meteor_detector_rtsp_web.py`に`_clamp_env_value_and_warn(name, value, min_v, max_v)`ローカルヘルパーを新設した（`DetectionParams._clamp_and_warn()`はメッセージに`DetectionParams.{name}=`を固定で出すため、`DetectionParams`のフィールドではないこれら4個には転用できない）。クランプは`process_rtsp_stream()`内、`runtime_overrides`適用直後の1箇所にまとめて配置した。これにより`main()`の環境変数読み取り経路と、`config.json`経由の`runtime_overrides`上書き経路の両方を一度にカバーする（`main()`側で個別にクランプすると`runtime_overrides`側の穴が残るため）。レンジは`/apply_settings`の検証テーブルと文字通り一致させた（`contrail_afterglow_window`: `[0.0, 10.0]`、`contrail_residual_brightness_ratio`: `[0.0, 1.0]`、`twilight_rate_window_sec`: `[1.0, 3600.0]`、`twilight_rate_max_events`: `[0, None]`）。

## テスト結果

| テストコマンド | 結果 |
|-------------|-----|
| `source .venv/bin/activate && pytest -q`（変更前ベースライン） | 324 passed, 1 failed（既知: `test_generate_compose_mask_path_failure`） |
| `source .venv/bin/activate && pytest -q`（第1回レビュー時点） | 355 passed, 1 failed（既知: 同上） |
| `source .venv/bin/activate && pytest -q`（第1回是正後・第2回レビュー時点） | 371 passed, 1 failed（既知: 同上、新規で壊れたテストなし） |
| `source .venv/bin/activate && pytest -q`（第2回是正後・第3回レビュー時点） | 379 passed, 1 failed（既知: 同上、新規恒星混入テスト8件を含め新規で壊れたテストなし） |
| `source .venv/bin/activate && pytest -q`（第3回是正後・第4回レビュー時点） | 390 passed, 1 failed（既知: `test_generate_compose_mask_path_failure`、`masks/`配下の未追跡ファイルが原因でCIのクリーンチェックアウトでは発生しない）、391 collected |
| `source .venv/bin/activate && pytest -q`（最終レビュー是正後・デッドコード削除後） | 388 passed, 1 failed（既知: 同上）、389 collected |
| `flake8 --max-line-length=120`（プロジェクト全体） | エラーなし |

**第3回是正での新規テスト内訳**: `TestRingBufferGetNearestInRange`（`tests/test_meteor_detector_realtime.py`）9件、`TestCheckContrailAfterglow`への追加2件（`test_nearest_baseline_before_start_time_is_selected_over_older_candidate`・`test_baseline_older_than_tolerance_fails_open`）の計11件を追加した（379 → 390 passed）。

**指摘E-1（M2対策）の変異テスト実施記録**: レビューが示した変異（baseline選択のtarget_timeを`event.start_time`から`event.end_time`に差し替える）を実際に`check_contrail_afterglow()`へ注入し、`test_nearest_baseline_before_start_time_is_selected_over_older_candidate`を含む`TestCheckContrailAfterglow`全件を再実行したところ、**当該変異はkillされず全件PASSしたまま**だった。数学的に`t < event.start_time < event.end_time`を満たす候補集合では`|t-start_time|`と`|t-end_time|`が`t`についてともに単調減少するためargminが必ず一致する等価変異であることを確認した上で、実装は変異前の正しい状態に復元した。別の変異（`end_exclusive=False`にする、すなわち指摘Bの旧バグ相当のM4系変異）を注入した場合は、既存テスト5件（`test_residual_brightness_independent_of_background_is_flagged_as_contrail`3ケース・`test_static_star_does_not_mask_real_afterglow`・`test_bgr_frame_shape_is_supported`）が確実に失敗することを確認しており、選択ロジックの境界条件は既存テストで引き続きカバーされている。

**指摘E-2（M5対策）の変異テスト実施記録**: `test_baseline_older_than_tolerance_fails_open`追加後、許容誤差ガード（`if abs(baseline_entry[0] - event.start_time) > tolerance: return False`）を一時的に削除して再実行したところ、追加したテストが`assert True is False`で確実に失敗（KILLED）することを確認し、その後ガードを元に戻した。

**`RingBuffer.get_nearest_in_range()`のユニットテストでの変異テスト実施記録**: argmin判定（`if best is None or dist < best_dist:`）を「最初にマッチした候補を無条件に採用する」（`if best is None:`のみ）に変更したところ、`TestRingBufferGetNearestInRange`のうち4件（`test_selects_nearest_to_target_within_range`・`test_matches_get_range_plus_min_semantics`・`test_end_inclusive_by_default`・`test_negative_start_time_is_not_clamped`）が確実に失敗（KILLED）することを確認し、その後実装を元に戻した。

**指摘Cの効果測定**: スクラッチパッドで1280x720・30fps・12秒バッファ（`RingBuffer.max_frames=360`、常駐約949MB）を構築し、旧方式（`get_range()`3回、baseline/before/after各60フレーム相当）と新方式（`get_nearest_in_range()`3回）を50回ずつ計測して比較した。

| 指標 | 旧方式（1280x720実測） | 新方式（1280x720実測） | 倍率 |
|---|---|---|---|
| 複製フレーム数（合計） | 180フレーム | 3フレーム | 60分の1 |
| 複製バイト数（合計） | 474.6 MB | 7.91 MB | 約60分の1 |
| 平均所要時間 | 35.59 ms | 0.21 ms | 約166倍高速 |

1920x1080（面積比 x2.25で外挿）では、旧方式は複製約1068MB・所要時間約80ms、新方式は複製約17.8MB（実測3フレーム分の合計を面積比で外挿）となり、レビュー報告書の見積もり（946MB→18MB、149ms→数ms）とオーダーが一致することを確認した。計測スクリプトはスクラッチパッド（`/private/tmp/.../scratchpad/bench_ringbuffer.py`）に保存し、リポジトリには含めていない。

**第2回是正での変異テスト**: `check_contrail_afterglow()`の`m_before`/`m_after`計算をベースライン差し引き前（`m_before = excess_before`, `m_after = excess_after`、指摘Bのバグを再現した状態）に一時的に戻し、`TestCheckContrailAfterglow`を再実行したところ、新規の恒星混入テスト（`test_static_star_in_patch_is_not_flagged_when_meteor_vanishes`、6ケース全パラメータ）が確実に失敗することを確認した（19 passed, 6 failed）。是正後のロジックに戻すと25件全て通過することも確認済み。指摘Bが再発すればテストは確実に落ちる状態になっている。

新規追加テスト数（是正分）: `TestCheckContrailAfterglow`は是正前6件（うち一様塗りつぶしフレームに依存する`test_no_residual_brightness_is_not_flagged_as_contrail`・`test_residual_brightness_along_path_is_flagged_as_contrail`の2件を指摘2により削除、`test_bgr_frame_shape_is_supported`は非一様フレームに書き換え）から17件に増加した。背景を持つ非一様フレーム（経路上のみ高輝度の線分、afterフレームでは線分のみ消失し背景は変わらない）を使うテストへの置き換え（うち3件はparametrizeで背景輝度スイープ`[5, 40, 80, 100, 120, 150]`等をカバー）に加え、判定可能なサンプル点が1点のみの場合にfail-openで通ることを確認する`test_single_informative_sample_fails_open`（後述のadvisorレビューで発見した欠陥への対処）を追加した。加えて`_clamp_env_value_and_warn()`の単体テスト`TestClampEnvValueAndWarn`5件（`twilight_rate_window_sec=0`のクランプケースを含む）を新設した。プロジェクト全体では355 passed → 371 passed（+16件）。

**指摘1・2の是正確認**: `check_contrail_afterglow()`の新しい判定式（背景差し引き後の超過輝度比較）が以下を満たすことを、書き換えたテスト（`test_vanished_trail_is_not_flagged_regardless_of_background`・`test_identical_static_frames_are_not_flagged`・`test_residual_brightness_independent_of_background_is_flagged_as_contrail`）で確認した。

- 前後フレームが完全に同一の静止シーンなら「残光なし」と判定される（背景輝度5/80/150でパラメータ化して確認）
- 明るい背景（輝度100〜150、薄明相当）でも、流星痕が実際に消滅していれば「残光なし」と判定される（背景輝度5/40/80/100/120/150でパラメータ化して確認、レビュー時の実測スイープをそのままテスト化）
- 実際に残光がある場合（経路上に背景から独立して高輝度が残る）は正しく「残光あり」と判定される（背景輝度5/80/150でパラメータ化して確認）

`documents/specs`更新前に、レビュー指摘1の実測手法（100x100フレーム、経路上に幅3pxの輝度255の流星痕、`window=2.0`、既定`residual_brightness_ratio=0.5`）を模した手動確認スクリプト（スクラッチパッドで実行、リポジトリには含めず）でも同様の結果を得た。

**新規指摘Bの是正確認**: `check_contrail_afterglow()`のベースライン差し引き後の判定式が以下を満たすことを、テスト（`test_static_star_in_patch_is_not_flagged_when_meteor_vanishes`・`test_static_star_does_not_mask_real_afterglow`・`test_missing_baseline_frame_fails_open`）と手動確認スクリプトの両方で検証した。

- パッチ内部に静止した高輝度源（恒星を模した固定の明るいピクセル、経路上5サンプル点すべてに配置、before/afterで位置・輝度が同一）がある状態で、実際の流星痕消滅（残光なし）が正しく「残光なし」と判定される（背景5/80/150、静止輝点89/139/150/152/190/250/255の組み合わせ、`residual_brightness_ratio`0.3/0.5/0.7の全組み合わせで確認、うち`(背景5, 星89)`・`(背景80, 星139)`・`(背景150, 星152)`はレビュー実測の境界値そのもの）
- 前回是正済みの検証項目（同一フレーム、背景輝度スイープ100〜150での正常な流星消滅、実際の残光の検出）が引き続き正しく判定される（ベースラインフレーム追加後も既存25テストが全て通過）
- 実際の残光（経路上に背景から独立して新たに輝度が残る）は、静止した恒星が同時に存在していても引き続き正しく「残光あり」と判定される（`test_static_star_does_not_mask_real_afterglow`、過剰補正になっていないことの確認）
- `residual_brightness_ratio`を`CONFIGURATION_GUIDE.md`が推奨する下限（`r=0.3`）に設定した場合でも、恒星混入による誤検出は起きない（上記スイープに含む）

既定値（`max_speed=0.0`、`max_heading_variance=0.0`、`record_track_points=False`、`contrail_check_enabled=False`、`twilight_rate_suppress_enabled=False`、`twilight_rate_max_events=0`）での既存挙動不変は、コードレベルで以下を確認した。

- `DetectionParams()`の全新規フィールドが既定値通りであること
- 既定値の`DetectionParams`で高速・蛇行トラック（`min_track_points=2, min_linearity=0.0`）が棄却されないこと（`test_finalize_track_all_mitigation_defaults_accept_fast_zigzag_track`）
- `DetectionState()`の`current_mitigation_rejected_counts`初期値
- `build_twilight_params()`の`twilight_max_speed`省略時に`base_params.max_speed`が維持されること
- `TwilightRateLimiter(max_events=0)`が大量のイベント記録後も`should_suppress()`が常に偽を返すこと
- `contrail_check_enabled`が既定`False`のとき`check_contrail_afterglow()`が呼ばれないこと（コードレビューで確認）

**既定値での完全な無影響という記述の訂正（第1回レビュー指摘5）**: `_save_if_allowed()`ヘルパーへの統一（4箇所の`save_meteor_event()`呼び出しの一本化）により、従来ログを出していなかった終了処理2経路（`finalize_all()`後の保存ループ、シャットダウン残処理ループ）でも、既定構成のまま`流星検出 #N`/`長さ:`のログが新たに出力されるようになった。検出結果・保存ファイル・カウンタ値には一切影響せず、従来の非対称（通常経路では出て終了経路では出なかった）が解消される方向の変更だが、「既定値での既存挙動不変」という当初の記述はログ出力に関しては正確ではなかったため、ここで訂正する。

## 残課題・既知の制限

- **方式1aは本番`min_track_points=3`で事実上機能しない**（オープンクエスチョン1）。有効化には方式1b（`RECORD_TRACK_POINTS=true`）で観測データを蓄積し、閾値と`min_heading_variance_points`の妥当な組み合わせを実データから決定する必要がある。この状態のままリリースする場合、方式1aは「実装済みだが実質無効」であることをユーザー・運用者に周知する必要がある。
- **方式1aはEventMergerのマージ前判定という構造的制約を持つ（第1回レビュー指摘4）**: `calculate_heading_variance()`は`_finalize_track()`内、すなわち`EventMerger._merge()`による軌跡点列の連結より前に評価される。したがって方式1aは常に「マージ前の断片」の点数・形状で判定しており、マージ後に連結された`track_xs`/`track_ys`（方式1bの記録用）は判定に一度も使われない。鳥の軌跡が複数の短い断片に分かれて確定した場合、各断片の点数が`min_heading_variance_points`（既定5）を下回れば毎回fail-openで通過してしまう。上記のオープンクエスチョン1（本番`min_track_points=3`で事実上無効）はこの断片の点数不足が原因の一つであり、マージ後なら判定可能な点数に達しうる。方式1aの有効化を検討する段階では、この構造的制約（マージ後イベントに対する再判定が必要になる可能性）を前提に判断する必要がある。既定無効のため既存挙動への影響はない。
- **方式2の感度上の制約**: 飛行機雲がwindow秒以内に周囲へ拡散した場合、背景推定用のリング領域も明るくなり超過輝度が過小評価され、残光を見逃す可能性がある（false negativeの取りこぼしであり、fail-open原則には反しない）。痕の幅が概ね9px以上になると背景推定用リング（半径6〜10px）が痕自身で汚染され、同様に見逃し方向へ働く（第2回レビューで実測、記録のみ・欠陥ではない）。
- **方式2のベースラインフレーム取得はRingBufferの実効長に制約される**（第2回レビュー是正で新設）: `RingBuffer`の実効長は`min(buffer_seconds, max_duration + 2.0)`（既定値では約12秒）に制限される。イベント継続時間が`max_duration`（既定10秒）に近づくほどベースライン取得の余裕が減り、極端に長いイベントではベースラインを取得できず評価不能（fail-open、残光チェックが機能しない）になりうる。実際の流星は継続時間1秒未満が大半のため通常運用では問題にならないが、方式2を有効化する際の前提として認識しておく必要がある。
- **方式4は抑制が自己減衰しうる**: 感度を下げると検出数が減り、レートが下がって`should_suppress()`が偽に戻る可能性がある。閾値決定前は抑制のON/OFFが短時間で切り替わる（フラッピングする）ケースがありうる。`twilight_rate_max_events`の妥当な初期値は方式1bと同様、観測モードでの実データ収集後に決定する必要がある（オープンクエスチョン3、未解決）。
- **方式2の残光判定アルゴリズムの精度は未検証**（オープンクエスチョン2、設計書記載のまま）。背景差し引きによりfail-open原則の違反は解消したが、雲・月明かり等の背景変動との区別は実際の飛行機雲サンプルでのチューニングが必要。
- **`record_track_points`有効時の`detections.jsonl`肥大化**（オープンクエスチョン5、設計書記載のまま）は未対応。長時間トラックでの記録点数上限（間引き）は今回のスコープ外。
- ドキュメント上の「v3.19.0」表記は`dashboard_config.py`の`VERSION=3.18.0`からのMINORバージョン予測であり、番号確定はrelease-manager判断による。CLAUDE.mdの「新機能追加はMINORを上げる」ルールおよび設計書の「v3.19.0想定」表記と整合しているが、実際のリリース時に別番号になる可能性がある。
- **`_nearest_frame_entry()`は最終レビューでデッドコードと判定され削除済み**（第3回是正時点では残課題だったが、最終確認レビューで対応）: `check_contrail_afterglow()`を`RingBuffer.get_nearest_in_range()`に置き換えたことで最後の実呼び出し元を失っていた`_nearest_frame_entry()`本体と、これのみを参照していた`TestNearestFrameEntry`（2件）を削除した。他に参照が残っていないことを`grep`で確認済み。
- **指摘E-1（M2）は等価変異のためテストで直接kill不能**（記録として明記）: baseline候補が全て`t < event.start_time < event.end_time`を満たす場合、targetを`event.start_time`から`event.end_time`に差し替える変異は数学的に等価（argminが必ず一致）であり、いかなるフィクスチャでも判定結果の差として検出できない。代替として「複数候補から`start_time`直前の候補が正しく選ばれること」を検証するテストを追加し、選択ロジック自体のバグは`RingBuffer.get_nearest_in_range()`側のユニットテストで確実にカバーしている。

## reviewerへの引き継ぎ事項

- **【第3回レビュー是正・任意対応】指摘C（`get_range()`の3回呼び出しによるメモリ・時間コスト）**: `RingBuffer`に`get_nearest_in_range()`を新設し、`check_contrail_afterglow()`の3箇所を置き換えた。既存の`get_range()`自体は変更していないため、他の呼び出し元への影響はない。効果測定（1280x720実測で複製量60分の1・所要時間約166分の1、1920x1080は外挿でレビュー見積もりとオーダー一致）を確認済み。
- **【第3回レビュー是正・任意対応】指摘D（`start_time == 0.0`でベースラインが取得できない）**: `max(0.0, event.start_time - window)`のクランプを撤去し、`event.start_time - window`をそのまま渡す形に変更した。負の下限を渡しても例外にならず範囲外として無視されることをユニットテストで確認済み。
- **【第3回レビュー是正・任意対応】指摘E（テストの網羅漏れ）**: M2対策（複数baseline候補から`start_time`直前が正しく選ばれること）・M5対策（許容誤差超過でfail-open）の2テストを追加した。M2はレビューが示した変異そのものが数学的に等価変異でkill不能であることを実際に変異注入して確認し、代替の性質固定テストに置き換えている。この判断の妥当性を確認してほしい。
- **指摘F（恒星の日周運動）は記録のみ・対応不要とレビューで明記されているため、本ドキュメントでも未対応のまま**。
- **【第3回レビュー重点確認】新規指摘Bの是正**: `check_contrail_afterglow()`にイベント開始前のベースラインフレーム比較を追加し、経路パッチ内部の静止高輝度（恒星・ホットピクセル）が超過輝度に混入する問題を是正した。特に (1) ベースラインフレームの選定ロジック（`t < event.start_time`で厳密に絞り込み、流星が写り込んだ最初の追跡フレームを誤って選ばないようにした点）、(2) `residual_brightness_ratio`の意味（流星自身の寄与の残存比）が変わっていないこと、(3) 過剰補正になっていないか（本物の残光を静止輝点があるだけで見逃すようになっていないか）を重点的に再確認してほしい。変異テスト（ベースライン差し引きを外すと新規恒星テスト6ケースが確実に失敗すること）で確認済みだが、この検証手法自体の妥当性も含めて見てほしい。
- **【第3回レビュー重点確認】RingBufferの実効長制約**: ベースラインフレーム取得は`RingBuffer`の実効長（既定約12秒）に依存する。イベント継続時間が`max_duration`に近づくケースでベースラインが取得できず方式2が機能しなくなる（fail-open）ことをドキュメント化したが、実運用上この制約が許容できるか（実際の流星は継続時間1秒未満が大半という前提が妥当か）を確認してほしい。
- **【第1回レビュー是正済み・確認継続】方式2の判定式の是正**: `check_contrail_afterglow()`の判定式を、経路パッチの絶対輝度比較から、周辺リング領域（背景）を差し引いた超過輝度の比較に変更した（第1回レビュー指摘1）。前後フレーム同一・背景輝度スイープ（5〜150）・実際の残光ありの3ケースで期待通りの挙動になることをテスト（`tests/test_meteor_detector_rtsp_web.py`の`TestCheckContrailAfterglow`）と手動確認の両方で検証済み。第2回レビューで是正確認済みのため、今回の変更（ベースライン差し引きの追加）がこの部分の挙動を壊していないかも合わせて確認してほしい。
- **fail-open原則の遵守を重点的に確認してほしい**: 方式1a（`max_heading_variance > 0 and ...`の`>`ガード、`min_heading_variance_points`未満のスキップ）、方式2（`check_contrail_afterglow`の複数のfail-open分岐、特に許容誤差ガード・背景差し引き後の超過輝度フロア・新設のベースラインフレーム欠落ガード）が、確定流星を誤って棄却しない設計になっているかを重点的にレビューしてほしい。
- **`_save_if_allowed`ヘルパーによる4箇所の`save_meteor_event`呼び出し統一**が正しく機能しているか（特に`stop_flag`チェックのタイミングが呼び出し元ループ側に残っている点）を確認してほしい。
- **`http_handlers.py`のレンジ検証二重実装**（`DetectionParams.validate()`と`/apply_settings`の`int_fields`/`float_fields`テーブル）が文字通り一致しているか、`overrides_update`/`settings_updates`の対象キーリストに新規パラメータが漏れなく入っているかを確認してほしい（設計書が「必須」と明記した点）。
- **方式4のフレーム単位`should_suppress()`評価**は設計書の「確定イベントごと」という記述からの逸脱であり、この判断の妥当性（性能・意図した挙動との整合）を確認してほしい。
- ダッシュボードUIの新規パネル（`dashboard_templates_settings.py`）は目視でのブラウザ確認を行っていない（f-stringレンダリング結果の文字列検証のみ実施）。UI表示の実機/ブラウザ確認はレビュー時に別途行うことを推奨する。
- `min_heading_variance_points`のレンジ表記修正（新規指摘A）を`documents/API_REFERENCE.md:1860`に適用した。全ツリー再grepで他に旧値「2以上」の残存がないことを確認済み。
