# 実装仕様書: realtime.py フルレビュー指摘13件の修正

- 作成日: 2026-08-17（是正処置対応により更新）
- 対象プロジェクト: meteo
- 要件トレーサビリティ: `documents/reviews/2026-08-16-realtime-full-review.md` 指摘13件（セキュリティ中1件「RTSP URL認証情報のログ平文出力」は除外・ユーザー判断により対応不要）、および `documents/reviews/2026-08-17-realtime-fixes-review.md`（判定: 承認、是正処置記録の低5件）
- 関連設計書: なし（レビュー報告書に基づく直接実装）
- 関連Issue / PR: なし
- 進捗管理: `documents/reviews/2026-08-16-realtime-full-review-tasklist.md`

## 概要

`meteor_detector_realtime.py` フルレビュー（2026-08-16）で指摘された中2件・低11件（計13件）を、重大度にかかわらず全件修正した。`meteor_detector_realtime.py` は通常変更禁止ファイルだが、ユーザーから明示的に変更許可を得て作業した。`meteor_detector_common.py` / `astro_utils.py` は変更していない。

## 変更ファイル一覧

| ファイル | 変更種別 | 変更内容 |
|---------|---------|---------|
| `meteor_detector_realtime.py` | 修正 | 13件中12件の実装対応（タスク12はテストのみ） |
| `tests/test_meteor_detector_realtime.py` | 修正・追加 | 既存テスト2件の実効性改善、新規テスト4件追加（計24件） |
| `documents/DETECTOR_COMPONENTS.md` | 修正 | 記述不足5点の追記・訂正 |
| `documents/CONFIGURATION_GUIDE.md` | 修正 | 新設環境変数2件（`RTSP_RW_TIMEOUT_US` / `METEOR_DEBUG_LOG`）を追記 |

## 実装の詳細

### タスク1（中）: ffmpegサブプロセスのデッドロック可能性

`write_mp4_clip_ffmpeg()` を修正。
- `stderr` を `subprocess.PIPE` から `tempfile.TemporaryFile()` に変更し、フレーム書き込み中にffmpegがstderrバッファ溢れでブロックし `proc.stdin.write()` と相互待ちになる経路を除去した。
- `stdout` は未使用のため `subprocess.DEVNULL` に変更。
- `proc.wait()` に `wait_timeout`（デフォルト60秒、引数で調整可）を追加。タイムアウト時は `kill()` → `wait()` で確実に回収してからフォールバックへ回す。
- returncode≠0時の診断表示は `stderr_file.seek(0)` → `read()` で一時ファイルから読み出す形に変更（機能は維持）。
- `finally`節での `proc.stdin.close()` は `contextlib.suppress(Exception)` で例外を抑制する。`kill()` 後は stdin バッファに未送出データが残っている場合があり、死んだプロセスへのパイプを close すると `BrokenPipeError` を送出しうる。素朴に close するとその例外が `write_mp4_clip_ffmpeg` の外へ伝播し、`write_clip_with_fallback` がOpenCVフォールバックへ到達できず検出スレッドで未処理例外になる（レビューで指摘され修正）。

実機のffmpegで正常系（非整数fps対応含む）・異常系（無効なsize指定でreturncode≠0）の両方を手動検証し、想定通り動作することを確認した。

**是正処置対応（2026-08-17）**: `wait_timeout` が唯一の本番呼び出し元 `write_clip_with_fallback` から転送されておらず本番で到達不能という指摘を受け、`write_clip_with_fallback` にも `wait_timeout: float = 60.0` を追加し `write_mp4_clip_ffmpeg` へ転送するようにした。デフォルト値は既存の60.0秒を維持しており、唯一の呼び出し元（`save_meteor_event` 内、既定値のまま呼び出し）の挙動は変わらない。

### タスク2（中）: detect_bright_objectsのROI化

輪郭ごとにフレーム全面で `np.zeros` + `drawContours` + `cv2.mean`（全面走査）していた処理を、`cv2.boundingRect(contour)` で輪郭の外接矩形（ROI）に限定する実装に変更した。`cv2.drawContours` には `offset=(-rx, -ry)` を指定してROI内座標系に変換（これを忘れるとマスクが空になり全候補が無言棄却される罠があるため注意）。`nuisance_mask` との重なり判定（`_calculate_mask_overlap_ratio`）も同じ矩形でスライスして渡す。

**等価性の検証**: 新規テスト `test_detect_bright_objects_roi_matches_full_frame_calculation` で、複数輪郭・ノイズ帯マスクとの重なりを含むケースを作成し、ROI化後の `brightness` / `nuisance_overlap_ratio` が旧実装（全面マスク方式）と完全一致することを確認した。`git stash` で一時的に旧コードに戻し、同一テストが同じ結果で通ることも確認済み。

**是正処置対応（2026-08-17）**: reviewerが変異テストで、当初のテストフィクスチャ（対称な外接矩形・ノイズ帯が候補矩形を完全内包/完全非重複のいずれか）では `offset=(-rx, -ry)` の1pxずれや `nuisance_mask` のROIスライス座標入れ替え（`[rx:rx+rw, ry:ry+rh]` → `[rx:rx+rw, ry:ry+rh]`）を検出できないことを実証したため、3つ目の候補矩形を非対称な外接矩形（輪郭 `(30,70)-(46,76)`、ノイズ帯 `(30,70)-(38,76)` で部分重なり）に置き換えた。実装コード経由の実測値は `overlap_ratio=0.5304`（`round(x,4)`で固定）で、1pxずれ変異では`0.4909`、座標入れ替え変異では形状不一致による`ValueError`となり、いずれも確実に検出できることを手元で変異を入れて確認した（確認後は元のコードに復元済み）。

### タスク3（低）: `-r`へ渡すfpsの整数丸め

`f"{target_fps:.0f}"` を `f"{target_fps:.3f}"` に変更し、ffmpegへ小数のfps値を渡すようにした。GOP計算（`gop = int(target_fps * 2)`）とOpenCVフォールバック（`write_clip_with_fallback`）はいずれも丸め前の `target_fps` を使用しているため、経路間の整合は元々保たれており追加対応は不要だった。

### タスク4（低）: フレーム時刻のmonotonic化

`RTSPReader.start_time` の設定（`time.time()`）とフレーム受信時刻の差分計算（`time.time() - self.start_time`）を、両方同時に `time.monotonic()` へ変更した。着手前に `RTSPReader.start_time` の全読み手を `grep` で洗い出し、`meteor_detector_realtime.py` 内の2箇所（設定・差分計算）のみで完結していることを確認した。`detection_state.py` の `start_time_global`（`/stats` の elapsed 表示用）は別変数であり無関係。`start_time`（イベントの相対秒セマンティクス、`detections.jsonl` のフィールド）は変更していない。

### タスク5（低）: cap.read()タイムアウト

`RTSP_RW_TIMEOUT_US` 環境変数が明示的に設定された場合のみ、`OPENCV_FFMPEG_CAPTURE_OPTIONS` に `rw_timeout`（TCP読み書きタイムアウト、マイクロ秒）を設定する opt-in 実装にした。**既定では何も設定しない**（デプロイ直後の挙動は変更前とバイト単位で同一）。

無条件にデフォルト値を設定しなかった理由は2点。(1) `OPENCV_FFMPEG_CAPTURE_OPTIONS` は既存のオプションを丸ごと置き換えるため、コンテナのOpenCVビルドが元々どのデフォルトを使っていたか未検証のまま上書きするリスクがある。(2) `rtsp://` 入力に対してFFmpegのRTSPデムクサーが解釈するのは主に `timeout`（旧`stimeout`）オプションであり、汎用AVIOオプションの `rw_timeout` はRTSP経由では無視されることが多い。効果が未検証のまま既定で有効化すると、無意味なオプション設定を出荷しつつ「対応済み」と誤認するリスクがある。当初は`os.environ.setdefault()`で無条件に60秒を設定する実装にしていたが、レビューでこのリスクを指摘され opt-in に変更した。

v3.17.3でストリーム監視ウォッチドッグ（`STREAM_TIMEOUT`、デフォルト30秒）を10秒から30秒に緩和した経緯があるため、有効化する場合はそれより短い値を設定しないよう`CONFIGURATION_GUIDE.md`に注記した。

**stop()時のVideoCaptureリークは対応を見送った**。読み取りスレッドが `cap.read()` でブロック中に別スレッドから `cap.release()` を呼ぶのは未定義動作であり、下手に対処すると新たなクラッシュ要因を持ち込むリスクがあるため。

**是正処置対応（2026-08-17）**: `RTSP_RW_TIMEOUT_US` を有効化すると `rtsp_transport;tcp|rw_timeout;...` が設定され、タイムアウトだけでなく**RTSPトランスポートがTCPに強制される**副作用があることが判明した（OpenCVビルドの既定トランスポートがUDPの場合、検出経路の挙動が変わりうる）。また本設定は**モジュール読み込み時に一度だけ評価される**ため、`/apply_settings` 等の実行時変更は反映されない（コンテナ再起動が必要）。いずれも`documents/CONFIGURATION_GUIDE.md`の該当行に追記した。

### タスク6（低）: [DEBUG] printのログレベル制御

環境変数 `METEOR_DEBUG_LOG`（`1`/`true`/`yes`/`on` で有効化、デフォルト無効）でデバッグログの出力を制御する `_debug_log()` ヘルパー関数を追加し、8箇所の棄却理由printをすべて置き換えた。ホットループ内で毎回 `os.getenv` を呼ばないよう、モジュール読み込み時に一度だけ判定してモジュールレベル変数 `_DEBUG_LOG_ENABLED` に保持する設計にした。有効時は `flush=True` で出力する。

### タスク7（低）: RingBuffer.max_framesが0になりうる

`self.max_frames = int(max_seconds * fps)` を `max(1, int(max_seconds * fps))` に変更し、`deque(maxlen=0)` による無警告のイベント消失を防いだ。

### タスク8（低）: DetectionParamsのレンジ検証

`DetectionParams` に `validate()` メソッドを追加し、`__post_init__` から呼び出す。
- `exclude_bottom_ratio`: 0.0〜1.0にクランプ（http_handlers.pyの既存テーブルと同じレンジ）
- `exclude_edge_ratio`: 0.0〜0.5にクランプ（同上）
- `burst_window_time`: 0.0以上にクランプ
- `burst_max_events`: 1以上にクランプ
- クランプ発動時は必ず `[WARN]` ログを出す（無警告の機能停止を避けるため）

加えて、レビューで新規指摘された整合条件 `burst_max_events × burst_window_time > 10 × max(burst_window_time, merge_max_gap_time)`（`_prune_arrival_times()` の保持幅を超え、バースト検知漏れが起こりうる条件）についても、値が3変数の関係でクランプ先を一意に決められないため、クランプはせず `[WARN]` ログのみ出す設計にした。

**既知の限界（重要）**: この検証は `DetectionParams()` の生成時（`__post_init__` 経由）のみ有効。`meteor_detector_rtsp_web.py` の設定反映ループ（`setattr(params, field, value)`、552-553行）や `params.__dict__.update(preset.__dict__)`（550行）は dataclass の再初期化を経由しないため、このクランプは通らない。ただし `http_handlers.py` の `/apply_settings` エンドポイント（900-928行）は別途独自のレンジ検証テーブル（`int_fields` / `float_fields`）を持っており、そちらは対応済み。CLI版（`meteor_detector_rtsp.py`）や `RealtimeMeteorDetector` を直接インスタンス化する経路は本対応でカバーされる。

### タスク9（低）: fpsクランプ発動時のWARNログ

`estimate_fps_from_frames()` のクランプ発動箇所（`estimated_fps > sanitized_fallback * max_ratio_to_fallback`）に `[WARN]` ログを追加した。CPU飽和の代理指標として可視化するため。

### タスク10（低）: `_reject_bursts`の早期return

`if not events: return events` を関数先頭に移動し、空イベントでも `_burst_start_times()`（sorted含む）を実行していた無駄な処理を回避した。

### タスク11（低）: 保存失敗時の記録・通知欠落

`save_meteor_event()` の3箇所を修正。
1. `get_range` が空の場合、無言で `None` を返していた箇所に `[WARN]` ログを追加。
2. クリップ書き出し失敗時のWARN文言「エンコーダの初期化に失敗」を「動画クリップの書き出しに失敗しました（ffmpeg実行エラー、またはOpenCVフォールバックのエンコーダ初期化失敗）」に修正し、ffmpeg実行時エラーも包含する不正確さを是正した。
3. `cv2.imwrite` の戻り値チェックを追加し、失敗時（ディスクフル等）に `[WARN]` ログを出すようにした。

**設計変更は行っていない**（クリップなしでもjsonl・コンポジットを残す設計への変更）。下流（ダッシュボード/DB取り込み）が `clip_path` の存在を前提にしている可能性があり、スコープを超えるため。ログ・文言の是正のみに留めた。

### タスク12（低）: テスト実効性2件

- `test_event_merger_handles_non_monotonic_arrival_order`: `assert isinstance(finalized, list)` を、実測した実際の挙動（7件全件が単一クラスタとしてバースト判定され破棄される）を検証する `assert finalized == []` と `assert merger._burst_dropped == 7` に置換。
- `test_event_merger_does_not_burst_reject_merged_fragments`: `assert 0 < len(finalized) <= len(fragments)` を、実測値である `assert len(finalized) == 2` に置換。分裂点（5番目の断片、index 4）と原因（`speed_ratio=0.545` が `merge_max_speed_ratio=0.5` を超過）は `EventMerger._is_mergeable()` を個別に呼び出すスクリプトで実測して確認した。

いずれも実装を変更する前にスクリプトで実測してからアサーションを固定した。

### タスク13（低）: DETECTOR_COMPONENTS.mdの記述不足5点

1. `length` プロパティの説明を「軌跡長（ピクセル）」から「始点・終点間の直線距離（ピクセル）。屈曲した軌跡や断片マージ後のイベントでは、実際の移動経路長より短く算出される」に修正。
2. `frames` フィールドがリアルタイム経路では常に空リストである旨を admonition（`!!! note`）で追記。
3. `estimate_fps_from_frames` / `max_ratio_to_fallback` のクランプ仕様を「保存処理」節に新規追加。
4. `MeteorEvent.to_dict()` の実装参照をソース行番号（`meteor_detector_realtime.py:262-273` / `879-892`）から関数名参照に置換。
5. 731件実データ検証の生存バイアス限界を admonition（`!!! warning`）で追記（目視削除判断に依存する間接検証である旨）。

## テスト結果

| テストコマンド | 結果 |
|-------------|-----|
| `source .venv/bin/activate && pytest tests/test_meteor_detector_realtime.py -q` | **24 passed**（既存20件 + 新規4件: ROI等価性1件、DetectionParamsレンジ検証3件） |
| （新規テスト関数）`test_detection_params_default_values_are_not_clamped` / `test_detection_params_clamps_out_of_range_values` / `test_detection_params_warns_when_burst_span_exceeds_prune_retention` / `test_detect_bright_objects_roi_matches_full_frame_calculation` | 4件 |
| `source .venv/bin/activate && pytest -q`（全体） | **324 passed / 1 failed** |
| `source .venv/bin/activate && flake8 meteor_detector_realtime.py tests/test_meteor_detector_realtime.py --max-line-length=120` | エラーなし |

全体スイートの唯一の失敗 `tests/test_generate_compose.py::test_generate_compose_mask_path_failure` は、作業ツリーに存在する未追跡の `masks/` ディレクトリによるcwd汚染が原因の既知の無関係な問題（ユーザー指示により無視）。

## 残課題・既知の制限

- **タスク8**: `DetectionParams` のレンジ検証は `__post_init__` 経由の生成時のみカバーする。`meteor_detector_rtsp_web.py` の設定反映ループ（setattr注入経路）は本対応の対象外。`http_handlers.py` の `/apply_settings` は既存の独自レンジ検証で別途対応済み。設定反映ループ側にも検証を追加するかはユーザー判断が必要（`meteor_detector_rtsp_web.py` は変更禁止ファイルではないが、今回のタスクリスト対象欄には明記されていなかったため変更していない）。
- **タスク5**: `stop()` 時のVideoCaptureリークは未対応。読み取りスレッド実行中の別スレッドからの `release()` は未定義動作となるリスクがあるため、対応を見送った。`RTSP_RW_TIMEOUT_US` で有効化した場合の `rw_timeout` オプションが、コンテナのOpenCV/FFmpegビルドでRTSP入力に対して実際に効くかは**未検証**（RTSPデムクサーは`timeout`/`stimeout`を優先的に解釈することが多く、汎用AVIOオプションの`rw_timeout`は無視される可能性がある）。macOSローカル環境にRTSPソースがなく検証手段がないため、既定では無効（opt-in）のまま出荷する。greeng4などコンテナ環境で有効化・実地検証してから既定値化を検討すべき。
- **タスク11**: 「クリップなしでもjsonl・コンポジットを残す」設計変更は見送り、ログ・文言の是正のみ実施。
- **タスク1（`proc.stdin.write()` の無制限ブロック残課題）**: `wait_timeout` が制約するのは `proc.wait()` のみで、フレーム書き込みループ内の `proc.stdin.write()` 自体には上限がない。stdinを読まなくなったが死にもしない子プロセスに対しては、検出スレッドが無期限にブロックしうる。reviewerがstdinを一切読まない子プロセスで実測し、`wait_timeout=2.0` を指定していても15秒経過時点でスレッドが生存し続けることを確認している（`documents/reviews/2026-08-17-realtime-fixes-review.md` 参照）。前回指摘の主眼だったstderrパイプ起因の相互待ちデッドロックは構造的に解消済みだが、本残課題は変更前から存在する、より発生条件の狭い経路（ffmpegが出力先の書き込みでストールする等）として残っている。将来的な改善案としては、書き込みを別スレッドへ逃がして全体に期限を設ける方式が考えられる。

## reviewerへの引き継ぎ事項

- タスク2（ROI化）は検出結果に影響しうる変更のため、`test_detect_bright_objects_roi_matches_full_frame_calculation` の等価性検証ロジックを重点的に確認してほしい。
- タスク4（monotonic化）は `start_time` セマンティクスに関わる変更のため、`RTSPReader.start_time` の読み手が本当に2箇所のみか（grep結果）を再確認してほしい。
- タスク5（rw_timeout）は当初 `os.environ.setdefault()` で無条件に60秒を設定する実装にしていたが、レビューで「既存のFFmpegキャプチャオプションを丸ごと上書きするリスク」「RTSP入力でrw_timeoutが実際に効くか未検証」の2点を指摘され、既定無効のopt-inに変更した。有効化する場合はコンテナ環境での実地検証を推奨する。
- タスク8のクランプ範囲（0.0-1.0, 0.0-0.5等）は `http_handlers.py` の既存テーブルの値をそのまま踏襲した。値そのものの妥当性はレビュー対象外だが、二層の整合性は確認済み。
- タスク1（ffmpeg修正）は実機ffmpegで正常系・異常系を手動検証したが、実際のタイムアウト発動（60秒待ち）は時間の都合上テストしていない。`finally`節での`contextlib.suppress`によるBrokenPipeError抑制もレビューで指摘され追加した箇所であり、コードレビューでの確認を推奨する。

## 是正処置対応（2026-08-17、reviewer報告書 2026-08-17分）

`documents/reviews/2026-08-17-realtime-fixes-review.md`（判定: 承認、低6件＋スコープ違反1件）の是正処置記録に基づき、低5件を対応した。詳細は上記の各タスク節に「是正処置対応（2026-08-17）」として追記済み。

| # | 指摘内容 | 対応 |
|---|---------|------|
| 1 | ROI等価性テストの検出力不足（1pxずれ・座標入れ替え変異を検出できない） | 非対称フィクスチャに置き換え、実測値`0.5304`で固定。変異テストで検出力を確認済み |
| 2 | `wait_timeout` が `write_clip_with_fallback` から転送されず本番到達不能 | `write_clip_with_fallback` に `wait_timeout: float = 60.0` を追加し転送 |
| 3 | `proc.stdin.write()` の無制限ブロック残課題が未記載 | 「残課題・既知の制限」節に追記（コード修正なし） |
| 4 | `RTSP_RW_TIMEOUT_US` のTCP強制・起動時のみ評価の副作用が未文書化 | `documents/CONFIGURATION_GUIDE.md:130` に追記 |
| 5 | 新規テスト件数「5件」の誤記（正しくは4件） | 「変更ファイル一覧」「テスト結果」節を訂正 |

**スコープ違反（対応不要）**: `.claude/agents/reviewer.md` の `model: inherit` → `model: opus` 変更は、今回の一連の作業とは無関係にユーザーが別途明示的に指示した設定変更であるため、そのまま残し変更していない。他の変更ファイルとは別コミットとして扱う想定。

### テスト結果（是正処置対応後）

| テストコマンド | 結果 |
|-------------|-----|
| `source .venv/bin/activate && pytest -q`（全体） | 324 passed / 1 failed（既知の`test_generate_compose_mask_path_failure`失敗のみ、無関係） |
| `source .venv/bin/activate && flake8 meteor_detector_realtime.py tests/test_meteor_detector_realtime.py --max-line-length=120` | エラーなし |
