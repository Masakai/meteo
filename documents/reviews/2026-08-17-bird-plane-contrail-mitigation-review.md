# レビュー報告書: 鳥・コウモリ・飛行機雲 誤検出対策（4方式・カメラ別フラグ切り替え）

- 作成日: 2026-08-17
- 対象プロジェクト: meteo (Meteor Event Tracking and Early Observation)
- 要件トレーサビリティ: ユーザー要望（8/16 camera2・camera3 鳥/コウモリ誤検出分析、8/17 camera3 薄明期間15件誤検出分析）
- 関連実装仕様書: `documents/specs/2026-08-17-bird-plane-contrail-mitigation.md`
- 関連設計書: `documents/designs/2026-08-17-bird-plane-contrail-mitigation.md`
- 関連Issue / PR: なし（`feature/bird-plane-contrail-mitigation` ブランチ、未コミット差分）
- レビュー回数: 第1回

## レビュー対象

ブランチ `feature/bird-plane-contrail-mitigation` の未コミット差分（16ファイル、+1197 / -75行）。

| ファイル | 変更行数 |
|---|---|
| `meteor_detector_rtsp_web.py` | +374 |
| `documents/DETECTOR_COMPONENTS.md` | +131 |
| `tests/test_meteor_detector_realtime.py` | +188 |
| `tests/test_meteor_detector_rtsp_web.py` | +114 |
| `meteor_detector_realtime.py` | +76 |
| `dashboard_templates_settings.py` | +54 |
| `http_handlers.py` | +53 |
| `detection_filters.py` | +51 |
| `documents/API_REFERENCE.md` / `ARCHITECTURE.md` / `CONFIGURATION_GUIDE.md` | +108 |
| `meteor_detector_common.py` / `detection_state.py` / `generate_compose.py` | +50 |
| `tests/test_detection_filters.py` / `tests/test_meteor_detector_common.py` | +73 |

### テスト・静的解析の再実行結果

| コマンド | 結果 |
|---|---|
| `source .venv/bin/activate && pytest -q` | **355 passed, 1 failed** — 実装仕様書の記載と一致。失敗は `tests/test_generate_compose.py::test_generate_compose_mask_path_failure` で、ワークツリーに未追跡の `masks/camera1_mask.png` が存在するため `generate_mask_file` が呼ばれず `SystemExit` が発生しない、本変更とは無関係な既知の環境依存問題 |
| `flake8 --max-line-length=120` | エラーなし |

## 合格項目

- 方式1a（`max_heading_variance > 0` ガード）・方式3（`max_speed > 0` ガード）の**既定値による無効化は正しく実装されている**。`_finalize_track()` の分岐は既定値 `0.0` で確実に素通りする。
- `DetectionParams` 新規4フィールドのレンジ検証が `validate()` に追加され、`/apply_settings` の検証テーブルと**レンジが文字通り一致している**（`max_speed` 0.0/None、`max_heading_variance` 0.0/None、`min_heading_variance_points` 2/None）。`overrides_update` / `settings_updates` のキーリストにも新規パラメータ10個が漏れなく登録されている。
- **スレッド安全性は問題なし**。`RealtimeMeteorDetector.rejected_counts` への書き込みは `_finalize_track()` 内で行われ、その呼び出し元は `track_objects()`（`meteor_detector_realtime.py:714` の `with self.lock:` 配下、759行）と `finalize_all()`（893行 `with self.lock:` 配下、895行）の2箇所のみで、いずれも `self.lock` 保護下にある。
- **方式4のフレーム単位評価は性能上の懸念なし**。`meteor_detector_rtsp_web.py:480` は `if twilight_rate_suppress_enabled and twilight_rate_limiter.should_suppress(timestamp):` であり、既定構成（`twilight_rate_suppress_enabled=False`）では左辺で短絡して `should_suppress()` は一切呼ばれない。本番greeng4（Intel N100）の毎フレーム負荷は増加しない。設計書の「確定イベントごと」からフレーム単位へ変更した判断自体も、感度を反映すべき対象が次の検出フレームである以上、意図と整合している。
- `record_event()` の `and twilight_rate_suppress_enabled` ガード除去（実装仕様書記載の自己発見バグ2）は**正しく修正されている**。`_save_if_allowed()` 内で `if cached_twilight:` のみを条件に記録され、観測モードでもレート分布データが蓄積される。
- `should_suppress()` の未配線（同バグ2）も `meteor_detector_rtsp_web.py:480` で配線され、`_TWILIGHT_SENSITIVITY_STEP_DOWN` による感度一段階降格が機能する。`twilight_rate_suppress_enabled=true` かつ `max_events<=0` のサイレントno-opに対する `[WARN]` ログも適切。
- `_save_if_allowed` ヘルパーによる `save_meteor_event()` 呼び出し4箇所の統一は**構造的に正しい**（551・557・603・619行）。`merger.add_event()` が内部で `flush_expired()` を呼び返す主要経路を含め全経路がヘルパーを通るため、方式2の適用漏れは構造的に防がれている。`stop_flag` チェックが呼び出し元ループ側に残っている点も、シャットダウン残処理の経路（619行）が意図的に `stop_flag` で打ち切らない既存設計を保っており問題ない。
- 設計書が「必須」とした fail-open 原則のうち、**方式1aは正しく実装されている**（`len(xs) >= min_heading_variance_points` の点数ガード、`calculate_heading_variance` の点数不足時 `0.0` 返却）。`test_finalize_track_heading_variance_fail_open_below_min_points` が実効的に検証している。
- `test_finalize_track_all_mitigation_defaults_accept_fast_zigzag_track` は、高速かつ蛇行という方式1a・方式3双方の対象になりうる軌跡が既定値で棄却されないことを直接検証しており、false-negative非増加の保証として実効性がある。
- **ダッシュボードUIの配線は完全**。`dashboard_templates_settings.py` の新規パネル「鳥・コウモリ・飛行機雲対策」は、`http_handlers.py` が受け付ける新規キー10個すべてを JS の `fields` 配列に登録しており、送信漏れはない。`defaultSettings` の各値（`max_speed: 0.0` / `max_heading_variance: 0.0` / `min_heading_variance_points: 5` / `record_track_points: false` / `contrail_check_enabled: false` / `contrail_afterglow_window: 2.0` / `contrail_residual_brightness_ratio: 0.5` / `twilight_rate_suppress_enabled: false` / `twilight_rate_window_sec: 300` / `twilight_rate_max_events: 0`）は `DetectionParams` の既定値・`generate_compose.py` の env 既定値と一致する。`input` の `min`/`max` 属性も `/apply_settings` の検証レンジと整合している（例: `contrail_residual_brightness_ratio` は `min=0 max=1`）
- `EventMerger._merge()` の軌跡点列連結は `prev.track_xs + new.track_xs` で、どちらかが空リスト（`record_track_points` 無効）なら結果も空のままとなり、既定挙動を変えない。バースト抑制・到着ログには一切手を入れておらず、設計書の非衝突要件を満たす。

## 指摘事項

### [重大度: 高] 指摘1 — `meteor_detector_rtsp_web.py:170-198` `check_contrail_afterglow()` が「経路の輝度」ではなく「絶対輝度」を比較しており、明るい背景では確定流星を誤って棄却する（fail-open原則違反）

判定ロジックは、経路上のサンプル点について終了直前フレームと `window` 秒後フレームの**パッチ平均輝度の絶対値**を比較し、`brightness_after >= brightness_before * residual_brightness_ratio`（既定0.5）なら「残光あり」と数える。

```python
brightness_before = float(np.mean(patch_before))
brightness_after = float(np.mean(patch_after))
if brightness_before <= 0:
    continue
if brightness_after >= brightness_before * residual_brightness_ratio:
    residual_hits += 1
```

この式には**背景輝度が含まれたまま**である。流星が完全に消滅しても、背景（薄明の空・月明かり・光害）が明るければ `brightness_after` は背景値のまま高く、`before`（背景＋流星）の50%を容易に超える。判定すべきは「流星の輝度超過分が残っているか」であり、現実装は「その場所が依然として明るいか」を見ている。

実測で確認した（100x100フレーム、経路上に幅3pxの輝度255の流星痕、`window=2.0`、既定 `residual_brightness_ratio=0.5`。after フレームでは流星痕は完全消滅し背景のみ）:

| 背景輝度 | before パッチ平均 | after パッチ平均 | 比 | 判定 |
|---|---|---|---|---|
| 5 | 153.0 | 5.0 | 0.033 | 通過 |
| 40 | 167.2 | 40.0 | 0.239 | 通過 |
| 80 | 183.6 | 80.0 | 0.436 | 通過 |
| **100** | 191.7 | 100.0 | **0.522** | **棄却** |
| **120** | 199.9 | 120.0 | **0.600** | **棄却** |
| **150** | 212.1 | 150.0 | **0.707** | **棄却** |

さらに端的な反証として、**前後フレームが完全に同一の静止シーン（何も起きていない）でも `True`（飛行機雲疑いで棄却）を返す**:

```
IDENTICAL static frames -> rejected_as_contrail = True
```

`before == after` なら比は常に1.0であり、`residual_brightness_ratio < 1.0` である限り必ず残光ありと判定される。すなわちこのフィルタは「変化がないこと」を「残光」と誤読する。

**重大性**: 誤棄却が起きる背景輝度域（おおむね100以上）は、まさに**薄明期間**である。方式2は薄明期の飛行機雲対策として設計され、設計書のカメラ割り当て案（設計書207行）では camera3 で有効化する想定になっている。フィルタが最も誤動作する条件と、運用上有効化する条件が一致している。設計書222行・実装仕様書115行が「必須要件」と明記した fail-open 原則（判定不能・不確実時に確定流星を棄却しない）に正面から違反する。

なお `contrail_check_enabled` は既定 `False` のため、**既定構成の既存検出結果には影響しない**。影響が出るのは本機能を有効化した時点であり、有効化＝本対策の目的そのものであるため、この既定値による無効化は緩和要因にならない。

**修正方針の例**（実装は developer 判断）: 背景を差し引いた超過輝度で比較する。経路から十分離れた近傍領域の輝度を背景推定値として引く、または `before`/`after` それぞれについて「パッチ平均 − フレーム全体（もしくは経路周辺リング状領域）の中央値」を残光量として比較する。

### [重大度: 高] 指摘2 — 指摘1を検出できないテスト設計（`tests/test_meteor_detector_rtsp_web.py:106-190`）

`TestCheckContrailAfterglow` の6件はすべて `np.full(...)` による**一様塗りつぶしフレーム**を使っている。

```python
frame_before = np.full((100, 100), 200, dtype=np.uint8)
frame_after = np.full((100, 100), 10, dtype=np.uint8)
```

一様フレームでは「経路上の流星の輝度」と「背景の輝度」が数値として区別不能であり、アルゴリズムが混同している2つの量をテストが分離できない。そのため:

- `test_no_residual_brightness_is_not_flagged_as_contrail`（200→10）は「背景ごと暗くなった」ケースを検証しており、実際の流星消滅（背景は変わらず痕だけ消える）を模していない。
- `test_residual_brightness_along_path_is_flagged_as_contrail`（200→190）も同様に、背景が明るいままであれば流星でも成立する条件であり、飛行機雲固有の性質を検証していない。

指摘1の修正時には、**背景を持つ非一様フレーム**（暗い背景＋経路上のみ高輝度の線分、after では線分のみ消失）を使ったテストを追加し、薄明相当の明るい背景（輝度100〜150）で流星が通過することを必ず確認すること。上表の背景輝度スイープをそのままテスト化するのが有効。

### [重大度: 中] 指摘3 — `meteor_detector_rtsp_web.py:1074-1097` 環境変数経由の新規パラメータにレンジ検証がなく、UI経路と検証が非対称

設計書221行は「レンジ検証の二重実装が必須」とし、`DetectionParams.validate()` と `/apply_settings` の検証テーブル双方への追加を求めている。`DetectionParams` のフィールドである3個（`max_speed` / `max_heading_variance` / `min_heading_variance_points`）は両方に入っており適合している。

しかし `contrail_afterglow_window` / `contrail_residual_brightness_ratio` / `twilight_rate_window_sec` / `twilight_rate_max_events` の4個は `DetectionParams` のフィールドではなく、**クランプが `/apply_settings` にしか存在しない**。`main()` の読み取りは素の `float()` / `int()` で、`ValueError` のフォールバックはあるがレンジチェックがない。

```python
contrail_residual_brightness_ratio = float(
    os.environ.get("CONTRAIL_RESIDUAL_BRIGHTNESS_RATIO", "0.5")
)
```

結果として、`/apply_settings` は `contrail_residual_brightness_ratio` を `[0.0, 1.0]` に制限する（`http_handlers.py:944`）一方、`docker-compose.yml` / `config.json` 経由では `5.0` や負値がそのまま通る。`twilight_rate_window_sec` も UI では `[1.0, 3600.0]` だが env では `0` や負値が通り、負の `window_sec` は `TwilightRateLimiter._prune()` の `cutoff = now - self.window_sec` が未来時刻となって記録が即座に全消去され、レート監視が恒常的に0になる。

`generate_compose.py` がこれらを `settings`（`config.json` 由来）から注入する経路を新設した以上、env 側にもクランプを設けるべき。

### [重大度: 中] 指摘4 — 方式1aの判定が `EventMerger` のマージ**前**に行われるため、断片化した鳥の軌跡には構造的に効かない

`calculate_heading_variance()` は `_finalize_track()` 内で評価される（`meteor_detector_realtime.py:849`）。一方 `EventMerger._merge()` による軌跡点列の連結（`meteor_detector_realtime.py:1116-1119`）はその**後**に起こる。したがって方式1aは常に「マージ前の断片」の点数・形状で判定する。

実測（`calculate_heading_variance`）:

```
3点断片（ジグザグ）の variance: 0.0
9点にマージ後の variance:      1.5547
```

鳥の軌跡が3点ずつ3断片に分かれて確定した場合、各断片は3点しかなく既定の `min_heading_variance_points=5` を下回るため毎回 fail-open で通過する。マージ後の9点軌跡は分散1.55と明確に蛇行を示すにもかかわらず、その値は方式1aの判定に**一度も使われない**。`_merge()` で連結された `track_xs`/`track_ys` は `to_dict()` による記録（方式1b）にのみ使われる。

実装仕様書44行は「本番 `min_track_points=3` では既定 `min_heading_variance_points=5` のもと事実上 fail-open」と記述しているが、それは断片の点数の問題であり、**マージ後なら判定可能な点数に達しうる**ことは記載されていない。方式1aの効果を実際に得るには、マージ後イベントに対する再判定が必要になる可能性がある。既定無効のため既存挙動への影響はないが、方式1aの有効化を検討する段階（実装仕様書の残課題）でこの構造的制約を前提に判断する必要がある。実装仕様書の「残課題・既知の制限」への追記を推奨する。

### [重大度: 中] 指摘5 — `meteor_detector_rtsp_web.py:603, 619` 終了処理2経路で、既定構成でもログ出力が変化する

要件「既定値での完全な無影響」に対する差分。変更前の `finalize_all()` 後の保存ループとシャットダウン残処理ループは、`state.detection_count += 1` と `save_meteor_event()` のみを行い、**`流星検出 #N` / `長さ:` の print を出していなかった**（`git show HEAD:meteor_detector_rtsp_web.py` の398-430行で確認）。

`_save_if_allowed()` はこれらを無条件に print するため、統一の副作用として終了処理時に新たなログ行が出る。

```python
state.detection_count += 1
print(f"\n[{ev.timestamp.strftime('%H:%M:%S')}] 流星検出 #{state.detection_count}")
print(f"  長さ: {ev.length:.1f}px, 時間: {ev.duration:.2f}秒")
```

検出結果・保存ファイル・カウンタ値には影響せず、ログ行が増えるのみ。むしろ従来の非対称（通常経路では出て終了経路では出なかった）が解消される方向の変更であり、実害は小さい。ただし「ログ出力に一切変化がない」という宣言とは異なるため、実装仕様書のテスト結果節の記述を実態に合わせて修正すること。

### [重大度: 低] 指摘6 — `meteor_detector_common.py:47-49` docstring と実装のガード条件が不一致

docstring は「点数が2未満（角度差を1つも計算できない）の場合は判定不能として0.0を返す」と書くが、実装は `if len(xs) < 3: return 0.0` であり**3未満**でガードしている。

実装が正しい（角度差 `np.diff(headings)` を1つ得るには方向ベクトルが2本＝点が3個必要）。テスト `test_calculate_heading_variance_insufficient_points_returns_zero` も `len==2` で `0.0` を期待しており実装側と整合する。

同じ off-by-one は**3箇所**に現れている。

| 箇所 | 現在値 | あるべき値 |
|---|---|---|
| `meteor_detector_common.py` の docstring | 「点数2未満」 | 「点数3未満」 |
| `DetectionParams.validate()` の `min_heading_variance_points` 下限 | 2 | 3 |
| `http_handlers.py` `int_fields` の `min_heading_variance_points` 下限 | 2 | 3 |

`min_heading_variance_points=2` を設定でき、かつ2点のトラックが来た場合、点数ガード `len(xs) >= 2` は通過するが `calculate_heading_variance()` が `0.0` を返し `0.0 > max_heading_variance` が偽になるため、結果として fail-open が保たれ**実害はない**。ただし「2点で蛇行判定できる」という誤解を招く設定値を運用者に許してしまうため、下限を3に揃えるのが適切。下限を変更する場合は `validate()` と `int_fields` を必ず同時に修正すること（レンジ一致の要件）。設計書125行にも同じ「点数2未満」の記述があるが、こちらは設計時の想定であり実装が妥当な修正を行ったもの。

### [重大度: 低] 指摘7 — `meteor_detector_rtsp_web.py:551, 557, 603, 619` `clip_path` が代入されるのみで一度も参照されない

`clip_path = _save_if_allowed(...)` の戻り値はどこでも読まれない（`grep -n "clip_path"` の結果が代入4箇所のみ）。変更前から存在するデッドコードであり本変更が持ち込んだものではないため、flake8（F841はローカル変数未使用を検出するが `--max-line-length=120` 設定下で通過している）も通っている。本レビューのスコープ外だが、`_save_if_allowed()` が棄却時に `None` を返す設計になった今、戻り値を使わないなら代入自体を削除する方が意図が明確になる。

### [重大度: 低] 指摘8 — `/stats` レスポンスに `mitigation_rejected_counts` が既定構成でも追加される

`http_handlers.py:495` で `mitigation_rejected_counts` が無条件に追加され、既定値でも `{"heading_variance": 0, "max_speed": 0, "contrail_afterglow": 0, "twilight_rate": 0}` を返す。設計書177行が明示的に要求した仕様であり、既存キーの削除・変更はない純粋な追加のため後方互換性は保たれる。「API応答に一切変化がない」という表現とは厳密には異なる点のみ記録する。`documents/API_REFERENCE.md` に反映済みであることを確認した。

## 設計からの逸脱5件の妥当性評価

| # | 逸脱内容 | 評価 | 理由 |
|---|---|---|---|
| 1 | `to_dict()` をオプション引数でなくデータ駆動（`track_xs`/`track_ys` の非空性）で判定 | **妥当** | `save_meteor_event()`（変更禁止ファイル）が `to_dict()` を引数なしで呼ぶため、オプション引数は到達不能なデッドコードになるという指摘は正しい。`_finalize_track()` が `record_track_points` 有効時のみ値を渡す構造上の保証があり、実質的に同じオプトイン挙動を追加配線なしで実現している。`test_meteor_event_to_dict_omits_track_points_by_default` が後方互換を検証済み |
| 2 | `check_contrail_afterglow()` が `frames_for_save` を再利用せず独立に `ring_buffer.get_range()` を呼ぶ | **妥当（ただし性能面に留保）** | `save_meteor_event()` が内部でフレームを取得しており呼び出し元が保持していないという事実確認は正しく、再利用にはシグネチャ変更＝変更禁止ファイルへの追加変更が必要になる。全体方針4との整合を優先した判断は適切。ただし設計書189行が懸念した「フル解像度×観測窓のコピー」が before/after 計2回発生する形になっており、設計書の見積もり（再利用時ほぼ無償）より重い。`contrail_check_enabled` 既定 `False` かつ確定イベント頻度が低いため実害は限定的だが、有効化時は `contrail_afterglow_window` を既定2.0秒以下に保つ運用が前提となる |
| 3 | 方式4の `should_suppress()` 評価を確定イベントごとでなくフレーム単位に変更 | **妥当** | 感度プリセットが作用する対象は次の検出フレームであり、確定イベント時点で評価しても反映先がない。フレーム単位が正しい。性能面も `twilight_rate_suppress_enabled` の短絡評価（480行）により既定構成でゼロコストであることを確認済み |
| 4 | 棄却カウンタを `RealtimeMeteorDetector.rejected_counts` にローカル保持し境界で合算 | **妥当** | `meteor_detector_realtime.py`（変更禁止ファイル）に `detection_state` への新規依存を持ち込まない判断は、CLAUDE.md の変更禁止ファイル方針および設計書の全体方針4と整合する。合算は単調増加値の上書きコピーであり、`_finalize_track()` が `self.lock` 下で書き込むためスレッド安全性も確保されている |
| 5 | `save_meteor_event()` 呼び出し4箇所を `_save_if_allowed` ヘルパーに統一 | **妥当** | 設計書が1箇所（`flush_expired()` 直後）のみ想定していたのは経路の把握漏れであり、`merger.add_event()` 経由の主要経路を含む4箇所全てを通すという判断が正しい。1箇所のみへの実装ではフィルタが主要経路を素通りしていた。副作用としてログ出力が変化する点は指摘5に記載 |

### 設計書に記載のない追加実装（`EventMerger._merge()` の軌跡点列連結）の評価

**バースト抑制・マージロジックとの整合性に問題はない**。`_merge()` は `track_xs=prev.track_xs + new.track_xs` を追加するのみで、`EventMerger` の到着ログ（`_arrival_times`）・`_prune_arrival_times()` のホライズン計算・ギャップクラスタリングには一切触れていない（設計書224行の非衝突要件を満たす）。既定構成では双方が空リストのため結果も空で、挙動不変。

ただし指摘4の通り、連結された点列が方式1aの判定に使われない（判定はマージ前に完了している）ため、観測データ（方式1b）としての価値のみを持つ実装である点を認識しておく必要がある。

## fail-open原則の検証結果

| 方式 | fail-open条件 | 検証結果 |
|---|---|---|
| 方式1a（蛇行） | `max_heading_variance == 0`（既定）で無効 | **適合**。`self.params.max_heading_variance > 0` の `>` ガードで既定0.0は必ず素通り |
| 方式1a（蛇行） | 点数不足（`< min_heading_variance_points`）でスキップ | **適合**。`len(xs) >= self.params.min_heading_variance_points` の点数ガードが機能。`calculate_heading_variance` 自体も3点未満で `0.0` を返す二重の保護。`test_finalize_track_heading_variance_fail_open_below_min_points` が実効的に検証 |
| 方式2（残光） | `contrail_check_enabled == False`（既定）で無効 | **適合**。`_save_if_allowed()` の `if contrail_check_enabled:` で既定は呼ばれない |
| 方式2（残光） | フレーム不在・形状不一致・経路が画面外 | **適合**。`before_entry is None or after_entry is None` / `frame_before.shape != frame_after.shape` / `valid_samples == 0` の各分岐が `False`（通す）を返す |
| 方式2（残光） | 例外発生時 | **適合**。`_save_if_allowed()` の `try/except` が `is_contrail = False` にフォールバックし `[WARN]` を出す |
| 方式2（残光） | RingBufferが `window` 秒後に未到達（許容誤差ガード） | **適合**。実装仕様書記載の自己発見バグ1の修正は正しく機能している。`tolerance = max(window * frame_time_tolerance_ratio, 0.05)` と `abs(after_entry[0] - target_after_time) > tolerance` の組み合わせでストリーム終端付近を評価不能として通す。`test_after_frame_too_far_from_window_target_fails_open` が1.9秒のずれで実際に検証 |
| **方式2（残光）** | **判定ロジック本体の誤棄却** | **不適合（指摘1）**。上記のガード群はすべて「評価不能な入力を通す」ためのものであり正しく機能しているが、**評価が成立した後の判定式そのものが背景輝度を含んでいるため、明るい背景では正常に消滅した流星を「残光あり」として棄却する**。前後フレームが完全に同一でも棄却する。fail-open原則の目的（確定流星の誤棄却回避）が達成されていない |
| 方式3（速度上限） | `max_speed == 0`（既定）で無効 | **適合**。`self.params.max_speed > 0` の `>` ガード |
| 方式4（レート） | `max_events <= 0`（既定）で抑制なし | **適合**。`TwilightRateLimiter.should_suppress()` が `max_events <= 0` で常に `False`。加えて呼び出し側の `twilight_rate_suppress_enabled` 短絡と、コンストラクタの `max_events if twilight_rate_suppress_enabled else 0` で三重に保護 |

**結論**: 実装仕様書が「重点確認してほしい」とした自己発見バグ2件（方式2の許容誤差ガード、方式4の未配線・記録ガード）は**いずれも正しく修正されている**ことを確認した。一方、方式2には別種の、より根本的なfail-open違反（指摘1）が残存している。

## セキュリティ検査結果

| 検査項目 | 結果 |
|---|---|
| パストラバーサル | **問題なし**。新規パラメータはすべて数値・真偽値であり、ファイルパスを受け取る新規入力はない。既存の `startup_path_fields` に変更なし |
| XSS | **問題なし**。`dashboard_templates_settings.py` の新規パネル（`git diff` で全体を確認）は静的なラベル・HELPテーブル・`input` 要素のみで構成され、f-string による動的値の埋め込みは新規追加分に一切ない（既存の `{{` エスケープ済み JS ブロックの外側に静的HTMLとして追加されている）。値は JS が `/apply_settings` へ JSON で送信し、表示は `input.value` への代入で行われるため innerHTML 経路もない |
| コマンドインジェクション | **問題なし**。新規コードにシェル実行・`subprocess` 呼び出しはない。`generate_compose.py` の追加は `settings` 辞書からの環境変数値の f-string 展開だが、既存の同一パターン（`TWILIGHT_MIN_SPEED` 等）に揃っており、`config.json` は管理者が管理する信頼済み入力である |
| 認証情報の漏洩 | **問題なし**。新規ログ出力（`rejected_by=...`、`[WARN] twilight_rate_...`）はいずれも数値・パラメータ名のみで、RTSP URL・認証情報を含まない |
| 入力値検証 | 指摘3の通り、環境変数経路のレンジ検証が欠けている。値の逸脱は機能不全（レート監視の恒常0化等）に留まり、セキュリティ境界の突破には至らない |

## ドキュメント整合性

| ドキュメント | 状態 |
|---|---|
| `documents/DETECTOR_COMPONENTS.md` | 4方式の新設セクション・パラメータ表・`MeteorEvent` フィールド説明・検出フロー図が追加済み。**要修正**: 方式2の説明は「終了直前比で `contrail_residual_brightness_ratio`（既定0.5）以上の輝度が残っていれば飛行機雲の残光とみなす」と記述しており、**指摘1の実装（背景を含む絶対輝度比較）と一致している**。すなわちコードは自身のドキュメント通りに動いており、誤りは実装とドキュメントの双方にある。指摘1の修正時に、背景を差し引いた超過輝度で判定する旨へ両方を改版すること |
| `documents/CONFIGURATION_GUIDE.md` | 新規環境変数8個（`TWILIGHT_MAX_SPEED` / `RECORD_TRACK_POINTS` / `CONTRAIL_CHECK_ENABLED` / `CONTRAIL_AFTERGLOW_WINDOW` / `CONTRAIL_RESIDUAL_BRIGHTNESS_RATIO` / `TWILIGHT_RATE_WINDOW_SEC` / `TWILIGHT_RATE_MAX_EVENTS` / `TWILIGHT_RATE_SUPPRESS_ENABLED`）がすべて記載されていることを確認 |
| `documents/API_REFERENCE.md` | `/stats` の `mitigation_rejected_counts`、`/apply_settings` の新規パラメータ10個がすべて記載されていることを確認 |
| `documents/ARCHITECTURE.md` | 検出シーケンス図への方式2（残光チェック）追記、`detections.jsonl` フォーマットへの `track_points` note 追加を確認 |
| 実装仕様書 | **要修正**: (a) テスト結果節の「既定値での既存挙動不変」に終了処理経路のログ変化（指摘5）を反映、(b) 残課題に方式1aのマージ前判定という構造的制約（指摘4）を追記 |
| バージョン表記 | ドキュメントの「v3.19.0」は `dashboard_config.py` の `VERSION=3.18.0` からのMINOR予測。新機能追加のためMINOR繰り上げはCLAUDE.mdのルールと整合するが、番号確定はrelease-manager判断（実装仕様書に明記済みで問題なし） |

GitHub Pages公開対象のため、指摘1の修正と同一リリースで `DETECTOR_COMPONENTS.md` の方式2説明を改版すること。

## 総評

- 判定: **要修正**（重大度「高」の指摘が2件）

4方式のうち方式1a・1b・3・4は、既定値による無効化・fail-open・スレッド安全性・レンジ検証の各要件を満たしており品質は高い。developer が自ら発見・修正した2件のバグ（方式2の許容誤差ガード、方式4の未配線と記録ガード）も、修正が正しく機能していることを実測・コード確認の双方で確認した。設計からの逸脱5件はいずれも妥当な判断であり、特に逸脱5（`_save_if_allowed` による4箇所統一）は設計書の経路把握漏れを正した改善である。

差し戻しの理由は方式2（飛行機雲残光チェック）の判定ロジック本体に限られる。周辺のfail-openガードは丁寧に作られている一方、判定式が背景輝度を差し引いていないため、**薄明期間という本機能の主対象条件で確定流星を誤棄却する**。前後フレームが完全に同一でも「残光あり」と判定する点が最も端的な証左である。これは設計書・実装仕様書がともに「必須要件」と位置づけた fail-open 原則（false negative を増やさない）に反する。既定 `contrail_check_enabled=False` により既存の検出結果は保護されているが、有効化＝本対策の運用目的そのものであるため、この既定値は緩和要因にならない。

指摘1の修正と、それを検出できる非一様フレームによるテスト（指摘2）の追加を必須とする。指摘3〜5は同時対応を推奨する。

- release-managerへの申し送り:
  - 本レビューは**要修正**判定のため、現時点ではリリース不可。指摘1・2の是正と再レビュー（第2回）完了を待つこと。
  - 是正後にリリースする場合、`contrail_check_enabled` を含む全新規パラメータは既定無効であり、既存カメラの検出挙動は変わらない。ただし `/stats` に `mitigation_rejected_counts` が追加されるため、ダッシュボード側で `/stats` レスポンスを厳密に検証している箇所がないことを確認すること。
  - 方式1a は本番 `min_track_points=3` では事実上機能しない（実装仕様書の残課題、および本報告の指摘4）。リリースノートで「実装済みだが実質無効・観測フェーズ」であることを運用者に周知すること。
  - `masks/` 配下の未追跡ファイルにより `tests/test_generate_compose.py::test_generate_compose_mask_path_failure` がローカルで失敗する。CI（クリーンチェックアウト）では発生しないが、リリース前のローカル検証時に混乱しないよう留意すること。

## 是正処置記録

| 指摘番号 | 指摘内容の要約 | 重大度 | 是正期限 | 是正担当 | 是正状況 |
|---------|-------------|-------|---------|---------|---------|
| 1 | `check_contrail_afterglow()` が背景輝度を含む絶対輝度で比較し、明るい背景（薄明期）で確定流星を誤棄却する。同一フレームでも棄却する | 高 | 2026-08-20 | developer | 未対応 |
| 2 | 一様塗りつぶしフレームのみのテストでは指摘1を検出できない。非一様フレーム＋背景輝度スイープのテストを追加する | 高 | 2026-08-20 | developer | 未対応 |
| 3 | 環境変数経路（`main()`）に新規4パラメータのレンジ検証がなく、`/apply_settings` と非対称 | 中 | 2026-08-20 | developer | 未対応 |
| 4 | 方式1aの判定が `EventMerger` マージ前に行われ、断片化した軌跡には構造的に効かない。実装仕様書の残課題へ追記 | 中 | 2026-08-20 | developer | 未対応 |
| 5 | 終了処理2経路で既定構成でもログ出力が変化する。実装仕様書のテスト結果節の記述を実態に合わせる | 中 | 2026-08-20 | developer | 未対応 |
| 6 | `min_heading_variance_points` の下限 off-by-one が3箇所（docstring「点数2未満」・`validate()` 下限2・`int_fields` 下限2）。実害はないが下限3へ揃える | 低 | 2026-08-20 | developer | 未対応 |
| 7 | `clip_path` が代入されるのみで参照されない（既存デッドコード、任意対応） | 低 | — | developer | 未対応 |
| 8 | `/stats` への `mitigation_rejected_counts` 追加（設計通り、記録のみ） | 低 | — | — | 対応不要 |

> 是正完了後、developerは対応内容をチャットで報告し、reviewerが再レビューを実施すること。
> 再レビュー時は同slugで新しいレビュー報告書を作成し（`-2`）、「レビュー回数」を第2回に増やす。
