# レビュー報告書: realtime.py フルレビュー指摘13件の修正

- 作成日: 2026-08-17
- 対象プロジェクト: meteo
- 要件トレーサビリティ: `documents/reviews/2026-08-16-realtime-full-review.md` の指摘14件のうち13件（中2件・低11件）。セキュリティ中1件「RTSP URL認証情報のログ平文出力」はユーザー判断により対応不要として除外（本レビューでも再指摘しない）
- 関連実装仕様書: `documents/specs/2026-08-16-realtime-review-fixes.md`
- 関連設計書: `documents/DETECTOR_COMPONENTS.md`
- 関連タスクリスト: `documents/reviews/2026-08-16-realtime-full-review-tasklist.md`
- 関連Issue / PR: なし
- レビュー回数: 第1回（本修正に対して）

## レビュー対象

未コミットの作業ツリー差分（`git diff`）。

| ファイル | 差分 |
|---|---|
| `meteor_detector_realtime.py` | +250 / -57 相当 |
| `tests/test_meteor_detector_realtime.py` | +112 |
| `documents/DETECTOR_COMPONENTS.md` | +38 |
| `documents/CONFIGURATION_GUIDE.md` | +2 |
| `.claude/agents/reviewer.md` | +1 / -1（**スコープ外**、後述） |

参照確認: `meteor_detector_rtsp_web.py`（setattr注入経路・process_scale・終了処理）、`http_handlers.py`（`/apply_settings` レンジ検証テーブル・マスクリサイズ）、`detection_filters.py`（sensitivityプリセット）、`generate_compose.py`（コンテナ環境変数）、`detection_state.py`、jsonl下流（`dashboard_routes.py` / `scripts/*.py`）。

---

## 総評

- 判定: **承認**
- 指摘件数: **高 0件 / 中 0件 / 低 6件**（スコープ違反1件は別枠）
- 前回13件はすべて対応済みで、対応内容と実装が一致していることを確認した。実装仕様書の記述と実コードの乖離は見つからなかった。
- 重点確認事項6項目（ROI化の等価性、monotonic化のセマンティクス、ffmpegデッドロック対策、RTSP_RW_TIMEOUT_USのopt-in判断、DetectionParamsレンジ検証、テストアサーション実効化）は、いずれも**実装は正しい**ことを実測で確認した。
- 低6件はいずれも「実装の正しさ」ではなく、テストの検出力・パラメータの到達可能性・ドキュメント記述の精度に関するもので、リリースをブロックしない。

---

## 合格項目（実測で確認した内容）

### タスク2（ROI化）: 旧実装との等価性を実測で確認

ランダム生成した400輪郭（フレーム端に接する多角形・不定形を含む）に対し、旧方式（フレーム全面 `np.zeros` + `drawContours` + `cv2.mean`）と新方式（`boundingRect` + `offset=(-rx, -ry)` + マスクスライス）の `brightness` / `nuisance_overlap_ratio` を比較し、**最大絶対差 0.0**（完全一致）を確認した。

`nuisance_mask` のスライス（`nuisance_mask[ry:ry+rh, rx:rx+rw]`）の安全性も確認済み。`_calculate_mask_overlap_ratio` は要素ごとの `&` を取るのみでリサイズを行わないため、旧実装の全面呼び出しも元々「フレームと同一解像度」を前提としていた。`meteor_detector_rtsp_web.py:152` および `http_handlers.py:1086` で `nuisance_img` は `(proc_width, proc_height)` へリサイズされてから渡されており、`detect_bright_objects` が受け取る `frame`（`proc_frame` 由来）と同一解像度である。したがってROI座標系の一致は保たれている。

### タスク4（monotonic化）: セマンティクス破壊なし

`RTSPReader.start_time` の読み手をリポジトリ全体で再grepし、`meteor_detector_realtime.py` の2箇所（設定 :514 / 差分計算 :534）のみであることを確認した（`grep -rn "start_time"` の結果、他ファイルの `start_time` は `start_time_global`、または jsonl レコードの不透明なパススルーのみ）。

クロックドメインの混在も確認した。フレーム `timestamp`（monotonic相対秒）を消費するのは `ring_buffer.add()` / `detector.track_objects()` / `merger.flush_expired(timestamp)` / `save_meteor_event` であり、いずれも同一の相対ドメイン内で完結する。壁時計を使う箇所（`state.last_frame_time`、`state.start_time_global` による elapsed 表示、終了処理の `shutdown_save_deadline`、`now_mono`（変数名に反し `time.time()`、薄明判定の60秒キャッシュ専用））は、いずれもフレーム `timestamp` と比較・混合されない。`detections.jsonl` の `start_time` / `end_time` は「プロセス起動からの相対秒」というセマンティクスのままで、変更前後で意味は変わらない。

### タスク8（レンジ検証）: 既存テーブルと一致・プリセットに影響なし

クランプ範囲は `http_handlers.py:921-922` の `float_fields`（`exclude_bottom_ratio` 0.0〜1.0、`exclude_edge_ratio` 0.0〜0.5）と literal 一致を確認した。二層で食い違わない。

`detection_filters.py:76-103` の sensitivity プリセット4種（low / high / faint / fireball）は `exclude_*` / `burst_*` のいずれも変更しないため、今回のクランプが既存の運用値を静かに書き換えることはない。既定値（`exclude_bottom_ratio=1/16`、`exclude_edge_ratio=0.0`、`burst_window_time=1.0`、`burst_max_events=5`）もすべてレンジ内で、クランプもWARNも発動しない（実測確認）。

新設の整合条件WARNの式 `10 * max(burst_window_time, merge_max_gap_time)` は、`_prune_arrival_times()`（:937付近）の実装 `keep_after = horizon - max(window, merge_max_gap_time) * 10` と一致しており、古い式を参照していない。既定値では `span=5.0 < retention=15.0` で発動しない。

**クランプでなくWARNのみとした設計判断は妥当**と評価する。この条件は3変数（`burst_max_events` / `burst_window_time` / `merge_max_gap_time`）の関係式であり、どの変数をどちらへ寄せるかが一意に決まらない。さらに違反時の帰結は「バースト検知漏れ＝破棄されない方向＝安全側」であり、運用者の明示的な設定を自動的に別の値へ書き換える副作用の方が害が大きい。無警告にしない（可視化する）という選択も、前回レビューの主旨（無警告の機能停止を避ける）と整合する。

### タスク12（テストアサーション実効化）: 実挙動と一致し、回帰検出力もある

両アサーションが実際の挙動を正しく固定していることを実行して確認した。

- `test_event_merger_handles_non_monotonic_arrival_order`: 実行結果は `finalized == []`、`_burst_dropped == 7`。アサーションと一致。
- `test_event_merger_does_not_burst_reject_merged_fragments`: 実行結果は2件（`start=100.0/end=100.55` と `start=100.6/end=100.85`）、`_burst_dropped == 0`。アサーションと一致。

さらに `== 2` が固定値の丸暗記でなく回帰を検出することを確認するため、`merge_max_speed_ratio` を変化させて感度を測定した: 0.3 → 3件、0.5（既定）→ 2件、0.9 → 1件。マージ挙動が変われば確実に失敗する。

### タスク1（ffmpegデッドロック対策）: 目的は達成、フォールバックへ正しく到達

実機ffmpegで各経路を実測した。

| 経路 | 結果 |
|---|---|
| 正常系（非整数fps 10.8） | `True`、MP4生成（2382 bytes）、0.09秒 |
| 異常系（不正size、ffmpeg大量stderr出力） | `False`、ハングなし、stderrは一時ファイル経由で出力 |
| `wait_timeout` 発動（stdin を読み切って終了しない子プロセス） | `False`、1.01秒（`wait_timeout=1.0` 指定時）で回収 |
| タイムアウト後のフォールバック | `write_clip_with_fallback` がOpenCV経路へ到達し `True`、ファイル生成を確認 |

指摘対象だったstderrパイプ相互ブロックは、`stderr=TemporaryFile` / `stdout=DEVNULL` により**パイプそのものが存在しなくなる**ため構造的に解消されている。FDリークも同様に解消。

`contextlib.suppress(Exception)` の抑制範囲は `finally` 節の `proc.stdin.close()` **1文のみ**で、他の失敗を握りつぶさない。成功経路で `close()` が失敗した場合は `try` 節側の `except Exception` に捕捉され `kill()` → `return False` → フォールバックへ回るため、失敗が「成功」として報告される経路はない。抑制の判断は妥当。

### タスク5（RTSP_RW_TIMEOUT_US）: opt-in判断は妥当

既定無効（opt-in）への変更は妥当と評価する。`grep` の結果、`generate_compose.py` / `docker-compose.yml` / Dockerfile のいずれも `OPENCV_FFMPEG_CAPTURE_OPTIONS` を設定していないため、実装仕様書が挙げた「既存設定を上書きするリスク」は現時点では顕在化しないが、RTSPデムクサーが `rw_timeout` を解釈するか未検証という理由(2)だけでも既定無効の判断を支持できる。効果未検証のオプションを既定で出荷して「対応済み」と誤認するリスクを避けており、`CONFIGURATION_GUIDE.md` にも未検証である旨が明記されている。既定挙動が変更前と同一である点も確認した。

### その他の合格項目

- タスク3: `-r` の `{target_fps:.3f}` 化。GOP計算・OpenCVフォールバックはいずれも丸め前の `target_fps` を使用しており、経路間の整合は保たれている。実機で非整数fps（10.8）の書き出し成功を確認。
- タスク6: `_DEBUG_LOG_ENABLED` をモジュール読み込み時に一度だけ判定する設計は、ホットループ内で `os.getenv` を呼ばない意図と合致。8箇所の `print` がすべて `_debug_log` に置換されていることを差分で確認した。
- タスク7: `max(1, int(max_seconds * fps))` により `deque(maxlen=0)` による無警告のイベント消失を防止。
- タスク9 / 11: WARNログの追加箇所（fpsクランプ、`get_range` 空、クリップ書き出し失敗、`cv2.imwrite` 失敗2箇所）はいずれも `flush=True` 付きで、前回指摘の「無言で消える」経路を塞いでいる。クリップ書き出し失敗時の文言も ffmpeg 実行エラーを包含する表現に是正されている。
- タスク10: `if not events: return events` が関数先頭へ移動され、`_burst_start_times()`（`sorted` 含む）の無駄な実行を回避。
- タスク13: DETECTOR_COMPONENTS.md の5点（`length` の定義訂正、`frames` が常に空である旨、fpsクランプ仕様の新設、行番号参照の関数名化、生存バイアス限界）がすべて反映されていることを差分で確認した。

---

## 指摘事項

### [重大度: 低] tests/test_meteor_detector_realtime.py:355-402 — ROI等価性テストがoffsetズレ・スライス誤りを検出できない

`test_detect_bright_objects_roi_matches_full_frame_calculation` は、`offset` を完全に削除した変異（`offset=(0, 0)`）は検出できるが、以下2つの変異を**通してしまう**ことを変異テストで確認した。

| 変異 | テスト結果 |
|---|---|
| `offset=(-rx, -ry)` → `offset=(0, 0)`（offset削除） | **失敗**（検出できる） |
| `offset=(-rx, -ry)` → `offset=(-rx + 1, -ry)`（1pxずれ） | **通過**（検出できない） |
| `nuisance_mask[ry:ry+rh, rx:rx+rw]` → `[rx:rx+rw, ry:ry+rh]`（座標入れ替え） | **通過**（検出できない） |

原因はテストフィクスチャの幾何が対称すぎること。ノイズ帯と重なる矩形は `(60,60)-(68,68)` で外接矩形が `(60, 60, 9, 9)` となり `rx == ry` かつ `rw == rh` のため、座標入れ替え変異が数学的に同一の操作になる。またノイズ帯 `(55,55)-(75,75)` が候補矩形を余裕をもって内包するため、1pxずれても `overlap_ratio` は 1.0 のままになる。

実装仕様書は「`git stash` で旧コードに戻して同じ結果になることを確認した」としているが、等価性テストの性質上この確認では上記の変異を検出できない（旧実装にはそもそも `offset` もスライスも存在しないため）。

**改善案（実測で有効性を確認済み）**: 非対称な外接矩形（`rx != ry`、`rw != rh`）と、ノイズ帯が候補矩形を部分的にのみ覆うケースを追加する。例として輪郭 `(30,70)-(46,76)`・ノイズ帯 `(30,70)-(38,76)` を用いると、現行実装は `overlap=0.5304` を返すのに対し、1pxずれ変異は `0.4909` を返して差が出る。座標入れ替え変異は形状不一致で `ValueError: operands could not be broadcast together with shapes (7,17) (17,7)` を送出し、確実に検出される。

**なお実装そのものは正しい**（400輪郭のランダム等価性検証で最大差0.0）。本指摘はテストの検出力に関するものであり、検出結果の正しさを疑うものではない。

### [重大度: 低] meteor_detector_realtime.py:67, 184 — `wait_timeout` が本番経路から到達不能

`write_mp4_clip_ffmpeg` に追加された `wait_timeout` 引数（既定60.0秒）は、唯一の本番呼び出し元である `write_clip_with_fallback` が受け取りも転送もしていない（`write_mp4_clip_ffmpeg(output_path, frames, fps=fps, size=size)`）。結果として本番では常に既定の60秒固定であり、運用側から調整する手段がない。実測でも `write_clip_with_fallback` 経由のタイムアウト発動は30秒経過時点で継続し、`wait_timeout` 指定が効かないことを確認した。

ただし**これは退行ではない**。変更前の `proc.wait()` はタイムアウトなし（無限）であり、最悪ケースは ∞ → 60秒へ短縮されている。`SHUTDOWN_SAVE_BUDGET_SEC`（4.0秒）との比較で問題視すべきものでもない。`meteor_detector_rtsp_web.py:421-428` の期限判定は `if idx > 0 and time.time() > shutdown_save_deadline` であり、各イベント保存の**前**に判定するゲートであって、1件の保存処理中を打ち切る仕組みではない。したがって「1件の保存が長時間ブロックする」状況に対しては変更前から予算は機能しておらず、本変更はその最悪ケースを改善している。

**推奨対応**: `write_clip_with_fallback` に `wait_timeout` を追加して転送するか、引数を削除してモジュール定数にする（現状は使われない引数がAPI表面に残り、調整可能であるかのように誤読される）。

### [重大度: 低] meteor_detector_realtime.py:146-148 — `proc.stdin.write()` は依然として無制限にブロックしうる

`wait_timeout` が制約するのは `proc.wait()` のみで、フレーム書き込みループ内の `proc.stdin.write()` には上限がない。stdinを読まなくなったが死にもしない子プロセスに対しては、検出スレッドが無期限にブロックする。ffmpegを模した「stdinを一切読まない子プロセス」で実測し、`wait_timeout=2.0` を指定していても**15秒経過時点でスレッドが生存し続ける**ことを確認した。

前回指摘の主眼だったstderrパイプ起因のデッドロック（ffmpegがstderr書き込みでブロックし stdin 消費を止める相互待ち）は、パイプを廃したことで構造的に解消されている。本指摘はそれとは別に残る、より発生条件の狭い経路（ffmpegが出力先の書き込みでストールする等）についてのものであり、変更前も同様に存在していた。タスク1の目的は達成されているという評価は変わらない。

**推奨対応**: 将来的な改善案として、書き込みを別スレッドへ逃がして全体に期限を設けるか、少なくとも本残課題を実装仕様書の「残課題」節へ明記する。

### [重大度: 低] meteor_detector_realtime.py:42-47 / documents/CONFIGURATION_GUIDE.md:130 — `RTSP_RW_TIMEOUT_US` が transport を暗黙にTCPへ切り替える

設定される値は `f"rtsp_transport;tcp|rw_timeout;{_rw_timeout_us}"` であり、タイムアウトだけでなく **RTSPトランスポートのTCP強制**を副作用として含む。`generate_compose.py` / `docker-compose.yml` / Dockerfile のいずれも `OPENCV_FFMPEG_CAPTURE_OPTIONS` を設定していないことを確認済みのため、現状は `setdefault` が成功して確実に反映される。すなわち、タイムアウト値だけを設定したつもりの運用者が、同時にトランスポートも変更することになる。OpenCVビルドの既定トランスポートがUDPの場合、これは検出経路の挙動を変える。

`CONFIGURATION_GUIDE.md` の該当行はタイムアウトについてのみ説明しており、トランスポート変更に言及していない。また本設定は**モジュール読み込み時に一度だけ評価される**ため、`/apply_settings` 等による実行時変更が効かない点も未記載。

**推奨対応**: ガイドの説明に「有効化するとRTSPトランスポートがTCPに固定される」「プロセス起動時のみ評価される」を追記する。

### [重大度: 低] documents/specs/2026-08-16-realtime-review-fixes.md — 新規テスト件数の記載が実際と不一致

実装仕様書は変更ファイル一覧および「テスト結果」節で「新規テスト5件追加（計24件）」と記載しているが、差分上の新規テスト関数は**4件**（`test_detection_params_default_values_are_not_clamped` / `test_detection_params_clamps_out_of_range_values` / `test_detection_params_warns_when_burst_span_exceeds_prune_retention` / `test_detect_bright_objects_roi_matches_full_frame_calculation`）である。既存20件 + 新規4件 = 24件で、pytest の実行結果（24件）とも整合するため、「5件」の方が誤り。

実装仕様書はトレーサビリティ用の成果物であり、後から対応範囲を追跡する際の根拠になる。数値の不一致は実害こそ小さいが、修正を推奨する。

### [重大度: 低] documents/CONFIGURATION_GUIDE.md:130-131 — 「次回リリースで追加」という表現がリリース後に陳腐化する

新設2行の説明に「（次回リリースで追加）」と記載されている。`documents/` はGitHub Pages公開対象であり、リリース後は「次回」が指す対象が変わって誤読を招く。同ファイル内の既存行が採用している版番号表記（例: `STREAM_TIMEOUT` の「v3.17.3+」）に合わせるのが一貫する。`DETECTOR_COMPONENTS.md:1046` の「（次回リリースで追加）」も同様。

**推奨対応**: release-manager がバージョン確定時に該当箇所を版番号表記へ置換する（下記申し送り参照）。

---

## スコープ外の変更（コード品質の指摘とは別枠）

### `.claude/agents/reviewer.md`（`model: inherit` → `model: opus`）

`git diff --stat` に本ファイルが含まれている。今回の13タスクのいずれとも無関係なエージェント設定ファイルの変更であり、変更ファイル一覧にも実装仕様書にも記載がない。

```
-model: inherit
+model: opus
```

CLAUDE.md の作業ルール「スコープを守る」（タスクで変更が必要なファイル以外に触れない）に反する。コミット前に revert するか、別コミット・別作業として切り出し、ユーザーの明示的な承認を得ることを推奨する。

---

## セキュリティ検査結果

- **認証情報漏洩**: 除外指定のRTSP URL平文出力を除き、今回の変更で新たに認証情報が出力される経路は追加されていない。新設のWARN/DEBUGログの出力内容を確認したが、いずれもパラメータ名・数値・`base_name`・フレーム時刻のみで、URL・パスワードを含まない。ffmpegのstderrを一時ファイル経由で `sys.stderr` へ書き出す経路は変更前と同じ内容（`-i pipe:0` であり入力URLを含まない）。
- **コマンドインジェクション**: `subprocess.Popen` はリスト形式・`shell=False` のまま。`wait_timeout` / `-r` の値はいずれも数値フォーマット済みで、シェル解釈の経路はない。
- **パストラバーサル**: 本変更でパス構築ロジックは変更されていない。`tempfile.TemporaryFile()` は名前を持たないFDであり、シンボリックリンク攻撃・予測可能名の競合の対象にならない（`NamedTemporaryFile` ではない点は適切）。
- **入力値検証**: `DetectionParams.validate()` の追加により、`__post_init__` 経由の生成では範囲外値がクランプされWARNが出るようになった。ただし後述のとおり `meteor_detector_rtsp_web.py` の setattr 注入経路はカバーされない（残課題として妥当な切り分け、下記参照）。
- **XSS**: 本ファイルはHTMLを生成しない。対象外。

### タスク8の残課題（setattr注入経路の非カバー）についての評価

実装仕様書が「`__post_init__` 経由のみカバー、`meteor_detector_rtsp_web.py:550-553` の `__dict__.update` / `setattr` ループは対象外」と切り分けている点は**妥当**と評価する。理由は3点。

1. WebUI由来の値は `http_handlers.py:900-928` の `int_fields` / `float_fields` テーブルで既にレンジ検証されており、同じ範囲（`exclude_bottom_ratio` 0.0〜1.0、`exclude_edge_ratio` 0.0〜0.5）が適用されている。二層のうち手前の層が機能している。
2. `apply_sensitivity_preset`（`detection_filters.py`）が更新するフィールドに `exclude_*` / `burst_*` は含まれないため、`__dict__.update(preset.__dict__)` 経路でレンジ外値が混入する経路が実際には存在しない。
3. `meteor_detector_rtsp_web.py` は今回のタスクリスト対象外であり、スコープを守る判断として適切。

残るのは「起動時の環境変数・CLI引数で直接注入する経路」だが、そちらは `DetectionParams()` 生成後の代入であり、次回改修時にユーザー判断を仰ぐという整理でよい。

---

## ドキュメント整合性

- `CONFIGURATION_GUIDE.md` に新設環境変数2件（`RTSP_RW_TIMEOUT_US` / `METEOR_DEBUG_LOG`）が追記されており、既定値・目的・注意事項が記載されている。`STREAM_TIMEOUT` との関係についての注記も含まれている。
- `METEOR_DEBUG_LOG` の既定オフは、これまで無条件に出ていた `[DEBUG] rejected_by=...` 8種が `docker logs` から消えるという運用者から見える挙動変化を伴う。`documents/` 配下および `dashboard_templates*.py` / `http_handlers.py` を横断grepし、`rejected_by` を読むよう案内している運用手順・トラブルシュート記述・ダッシュボード機能が**存在しない**ことを確認した（ヒットは今回追加した `CONFIGURATION_GUIDE.md:131` のみ）。したがって陳腐化するドキュメントはない。
- `DETECTOR_COMPONENTS.md` の5点の修正はいずれも実装と一致していることを確認した。特に `length` の説明（始点終点間の直線距離）は実装（`meteor_detector_realtime.py` の `MeteorEvent.length`）と一致、`frames` が常に空である旨も `_finalize_track` / `_merge` の実装と一致する。
- 「次回リリースで追加」表記の陳腐化リスクのみ指摘（低、上記）。
- CHANGELOG.md への追記は本差分に含まれていないが、これは release-manager の担当フェーズであり本レビューでは指摘としない。

---

## テスト実行結果

`.venv` にて実施。

| コマンド | 結果 |
|---|---|
| `pytest -q`（全体） | **324 passed / 1 failed** |
| `flake8 meteor_detector_realtime.py tests/test_meteor_detector_realtime.py --max-line-length=120` | **エラーなし** |

唯一の失敗 `tests/test_generate_compose.py::test_generate_compose_mask_path_failure` は既知の無関係な問題であることを確認した。失敗時の captured stdout が `スキップ: masks/camera1_mask.png は手動更新済みのため上書きしません` であり、作業ツリーの未追跡 `masks/` によるcwd汚染という既知の原因と一致する。本レビュー対象の変更とは無関係で、新規の失敗はない。

テスト件数は前回20件から24件へ増加（新規4件: ROI等価性1件、DetectionParamsレンジ検証3件）。合計24件は実行結果とも一致する。

---

## 前回13件の対応状況確認表

| # | 前回指摘（重大度） | 対応 | 確認結果 |
|---|---|---|---|
| 1 | ffmpegデッドロック可能性・無期限wait・FD未クローズ（中） | stderr→TemporaryFile、stdout→DEVNULL、`wait(timeout=)` 追加 | **対応済**。実機4経路で実測。デッドロック要因のパイプは構造的に廃止。残課題2件を低指摘として記載 |
| 2 | detect_bright_objects の輪郭ごと全面マスク確保（中） | boundingRect + ROI化、`offset=(-rx,-ry)` | **対応済**。400輪郭のランダム検証で旧実装と最大差0.0。テスト検出力のみ低指摘 |
| 3 | `-r` へ渡すfpsの整数丸め（低） | `{target_fps:.0f}` → `{target_fps:.3f}` | **対応済**。実機で非整数fps書き出し成功を確認 |
| 4 | フレーム時刻が壁時計由来（低） | `time.time()` → `time.monotonic()`（設定・差分計算の2箇所） | **対応済**。読み手2箇所を再grepで確認。クロックドメイン混在なし。jsonlセマンティクス不変 |
| 5 | `cap.read()` タイムアウトなし・stop()時のリーク（低） | `RTSP_RW_TIMEOUT_US` によるopt-in実装。リークは見送り | **部分対応（妥当）**。opt-in判断は妥当。トランスポート副作用の文書化のみ低指摘。リーク見送りの理由（実行中 `release()` は未定義動作）も妥当 |
| 6 | `[DEBUG]` print が無条件・flushなし（低） | `METEOR_DEBUG_LOG` + `_debug_log()`、8箇所置換 | **対応済**。モジュール読み込み時1回判定でホットループのgetenv回避。有効時 `flush=True` |
| 7 | `RingBuffer.max_frames` が0になりうる（低） | `max(1, int(...))` | **対応済** |
| 8 | `DetectionParams` のレンジ検証なし（低） | `validate()` 追加、4項目クランプ + 整合条件WARN | **対応済**。範囲は `http_handlers.py` と literal 一致、プリセットに影響なし。setattr経路非カバーの切り分けも妥当 |
| 9 | fpsクランプ発動時のWARNなし（通算5回目）（低） | `[WARN] fps推定値をクランプ` 追加 | **対応済** |
| 10 | `_reject_bursts` が空でもソート実行（低） | `if not events: return events` を先頭へ | **対応済** |
| 11 | 保存失敗時の記録・通知欠落（低） | 3箇所にWARN追加・文言是正 | **対応済**。設計変更（クリップなしでもjsonl保存）見送りの理由も妥当 |
| 12 | テストアサーション実効性2件（低） | `== []` / `_burst_dropped == 7` / `== 2` へ置換 | **対応済**。実挙動と一致、回帰検出力も実測確認（speed_ratio変化で3/2/1と変動） |
| 13 | DETECTOR_COMPONENTS.md の記述不足5点（低） | 5点すべて追記・訂正 | **対応済**。実装との一致を確認 |

前回13件は**全件対応済み**。

---

## release-manager への申し送り

- 判定は**承認**。高・中の指摘はなく、リリースをブロックする要因はない。
- **コミット前に `.claude/agents/reviewer.md` の変更（`model: inherit` → `model: opus`）を差分から外すこと。** 今回のタスクと無関係なエージェント設定変更であり、混入したままコミットすべきでない。
- バージョン番号の桁は release-manager の判断に委ねる（`dashboard_config.py` の `VERSION` が正）。参考情報として、本変更はレビュー指摘の是正（バグ修正・堅牢性改善）が主体であり、新設した環境変数2件はいずれも既定で挙動を変えない opt-in である。
- `METEOR_DEBUG_LOG` の既定オフにより、これまで無条件に出ていた `[DEBUG] rejected_by=...` ログが `docker logs` から消える。運用者から見える挙動変化のため、リリースノートに明記を推奨する（トラブルシュート時は `METEOR_DEBUG_LOG=1` で復活する旨）。
- `documents/CONFIGURATION_GUIDE.md:130-131` および `documents/DETECTOR_COMPONENTS.md:1046` の「（次回リリースで追加）」表記を、確定した版番号（例: `v3.19.0+`）へ置換すること。
- `RTSP_RW_TIMEOUT_US` は既定無効であり、既存の `docker-compose.yml` やデプロイ設定の変更は不要。ただし有効化するとRTSPトランスポートがTCPに固定される副作用があるため、greeng4等での実地検証を経てから既定値化を検討すること。
- 本番 greeng4 は Intel N100 でCPU飽和傾向にあるため、タスク2（ROI化）とタスク6（DEBUGログ既定オフ）はいずれもCPU負荷低減方向に働く。デプロイ後に `[WARN] fps推定値をクランプ` の出現頻度を観測すると、飽和状況の代理指標として利用できる。

## 是正処置記録

判定が「承認」のため是正処置は必須ではない。以下は次回改修時の対応候補（いずれも承認をブロックしない）。

| 指摘番号 | 指摘内容の要約 | 重大度 | 是正期限 | 是正担当 | 是正状況 |
|---------|-------------|-------|---------|---------|---------|
| 1 | ROI等価性テストがoffsetズレ・スライス誤りを検出できない（非対称フィクスチャの追加を推奨） | 低 | 任意 | developer | 未対応 |
| 2 | `wait_timeout` が `write_clip_with_fallback` から転送されず本番で到達不能 | 低 | 任意 | developer | 未対応 |
| 3 | `proc.stdin.write()` が無制限にブロックしうる（残課題として明記を推奨） | 低 | 任意 | developer | 未対応 |
| 4 | `RTSP_RW_TIMEOUT_US` のトランスポートTCP固定副作用・起動時のみ評価が未文書化 | 低 | 任意 | developer | 未対応 |
| 5 | 実装仕様書の新規テスト件数「5件」が実際の4件と不一致 | 低 | 任意 | developer | 未対応 |
| 6 | 「次回リリースで追加」表記の版番号への置換（`CONFIGURATION_GUIDE.md:130-131` / `DETECTOR_COMPONENTS.md:1046`） | 低 | リリース時 | release-manager | 未対応 |
| — | `.claude/agents/reviewer.md` のスコープ外変更（コミット前に除外） | スコープ | コミット前 | developer | 未対応 |
