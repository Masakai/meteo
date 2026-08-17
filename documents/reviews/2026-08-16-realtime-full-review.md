# レビュー報告書: meteor_detector_realtime.py ファイル全体詳細レビュー

- 作成日: 2026-08-16
- 対象プロジェクト: meteo
- 要件トレーサビリティ: v3.18.0（同時刻バースト抑制・fps推定クランプ）リリース直後のファイル全体品質確認。差分レビューではなくフルレビュー
- 関連実装仕様書: なし
- 関連設計書: `documents/DETECTOR_COMPONENTS.md`
- 関連Issue / PR: なし
- 前回レビュー: `documents/reviews/2026-08-16-burst-suppression-v4.md`（第5回・承認）
- レビュー回数: 第1回（フルレビューとして）

## レビュー対象

- `meteor_detector_realtime.py` 全体（コミット `f4c328e` v3.18.0、作業ツリーに未コミット変更なし）
- 参照: `meteor_detector_common.py`（calculate_linearity / calculate_confidence / open_video_writer）、`tests/test_meteor_detector_realtime.py`、`meteor_detector_rtsp_web.py`（呼び出し側の契約確認）、`documents/DETECTOR_COMPONENTS.md`、`CHANGELOG.md`、過去レビュー5件

---

## 総評

- 判定: **承認**（重大度「高」の指摘なし。v3.18.0はリリース・本番デプロイ済みであり、以下の指摘は次回改修時の対応候補）
- 指摘件数: **高 0件 / 中 3件 / 低 11件**
- v3.18.0で追加されたバースト抑制（ギャップクラスタリング）と fps クランプの本体ロジックには、過去5回のレビューで確認済みの結論を覆す新たな欠陥は見つからなかった。`_prune_arrival_times` の保持条件、マージ時に到着ログへ積まない実装と `start_time` 整合、非単調到着時の `sorted()` の安全性は本レビューでも再確認した。
- 中3件はいずれも v3.18.0 以前から存在する既存問題（認証情報のログ平文出力、ffmpeg サブプロセスのデッドロック可能性、検出ホットループの輪郭ごと全面マスク確保）で、今回の変更起因ではない。
- 前回申し送り6件は**全件未対応のまま残存**していることを確認した（詳細は後述）。

---

## 合格項目

- **スレッド安全性**: `RTSPReader._read_loop` は単一生産者で、Queue満杯時の `get_nowait()`→`put()` は競合しない。width/height/fps は `self.lock` 下で更新され `frame_size` も同ロックで読む。`RealtimeMeteorDetector` は `self.lock`（トラック）と `mask_lock`（マスク差し替え）を分離し、`detect_bright_objects` はロック下でマスク参照をスナップショットしてから使う正しいパターン。ロックのネスト順は `self.lock`→`mask_lock` の一方向のみでデッドロック経路なし。`EventMerger` はロックを持たないが、全呼び出し元（rtsp_web / rtsp CLI / 動画解析CLI の3経路）で検出スレッド単一からのみ使われていることを確認した。
- **バースト抑制の整合性（再確認）**: `_prune_arrival_times` は `horizon = min(oldest_pending, current_time)` を基準に `max(window, merge_max_gap_time) × 10` の履歴を保持し、既定値（クラスタ最大スパン 5×1.0=5秒 < 保持15秒）では pending 中イベントの判定に必要な到着記録を消さない。マージ成立時は到着ログに積まず、`_merge()` が `prev.start_time` を保持するため `_reject_bursts()` の集合照合と整合する。`sorted()` により非単調到着でも不正区間は生じない。
- **fps推定**: `dt > 0` フィルタで負・零の時刻差を除外。クランプ境界は `>`（1.5倍ちょうどはクランプ）でテスト（`allows_fps_just_below_ratio_limit`）と整合。`sanitized_fallback` を先に正規化してから比率判定する順序も正しい。
- **数値計算**: `MeteorEvent.length` 等が返す `np.float64` は Python `float` のサブクラスであり `json.dumps` で直列化可能（`to_dict` → `detections.jsonl` の経路は破綻しない）。`calculate_linearity` の3点未満=1.0 は本番 `min_track_points=3` では発動しない（3点以上で実計算）。`speed = length / max(0.001, duration)` のゼロ除算ガードあり。
- **`probe_rtsp_endpoint`**: 戻り文字列は host / port / 例外型のみで認証情報を含まない（`parsed.port` の ValueError もポート文字列のみ）。
- **パス操作**: `output_dir` は呼び出し側設定由来でユーザー入力の混入経路なし。`make_detection_base_name` の衝突回避はサフィックス付与で有界動作。
- **リソース管理（正常系）**: `cap.release()` は再接続ループの各周回で実行。`write_clip_with_fallback` の OpenCV フォールバックは `writer.release()` を呼ぶ。ffmpeg 失敗時の `proc.kill()`→`wait()` によるゾンビ回避あり。
- **呼び出し側契約**: `RTSPReader.read()` がタイムアウト時に返す `(True, 0, None)` は rtsp_web 側で `frame is None` チェック済み。

---

## 指摘一覧

### [重大度: 中] meteor_detector_realtime.py:378, 381-382 — RTSP URL（認証情報込み）をログへ平文出力

`_read_loop` の接続失敗時に `print(f"接続失敗: {self.url} ...")` が RTSP URL をそのまま出力する。`streamers` の URL は `rtsp://user:pass@host/path` 形式であり、パスワードが stdout → docker logs、さらに `LOG_FILE` 経由で `/logs/<camera>.log`（ローテーション付き永続ファイル）に書き込まれる。また `probe_rtsp_with_ffprobe()` の失敗詳細（`result.stderr`）は ffprobe が入力 URL をエコーする形式（`rtsp://user:pass@...: Connection refused` 等）のため、`RTSP詳細診断:` 行（382行）からも漏れうる。

- **失敗シナリオ**: 接続障害のトラブルシュートでユーザーがログを共有・転記した際にカメラ認証情報が流出する。接続失敗は再接続のたびに繰り返し出力されるため、ログ内の出現頻度も高い。
- **整合性の問題**: `SECURITY.md` は RTSP 認証情報の漏洩をリスク「高」と位置づけ、同種の箇所は既に修正済み（`generate_compose.py:501-505` はパスワードを `***` にマスク、`_youtube_loop` は例外型名のみ出力。いずれも v3.4.6 対応）。本箇所だけがポリシーから漏れている。
- **推奨対応**: `generate_compose.py` と同じ `urlparse` ベースのマスク処理を共通化して適用する。ffprobe 詳細は URL 部分をマスクするか、既知のエラーパターンのみ抽出して出力する。

### [重大度: 中] meteor_detector_realtime.py:96-119 — ffmpeg サブプロセスのデッドロック可能性・無期限 wait・パイプ未クローズ

`write_mp4_clip_ffmpeg` は `stdout=PIPE` / `stderr=PIPE` で起動するが、(1) stdout は一度も読まれない、(2) stderr は全フレームの stdin 書き込み完了**後**にしか読まれない、(3) `proc.wait()` にタイムアウトがない。

- **失敗シナリオ**: フレーム書き込み中に ffmpeg が stderr へパイプバッファ（約64KB）を超える出力を行うと、ffmpeg は stderr 書き込みでブロックして stdin の消費を止め、Python 側は `proc.stdin.write()` でブロックする相互待ち（デッドロック）になる。`-loglevel error` で発生確率は低いが、発生した場合の影響は大きい: `save_meteor_event()` は検出スレッド内で直列実行されるため、**検出・保存・停止処理（`join(timeout=5.0)`）まで巻き込んで無期限に停止**する。v3.17.x 系で対処してきた「終了ログ後もスレッドが生き残る」症状と同型の障害になる。また ffmpeg 自体がハングした場合も `proc.wait()` が無期限に待つ。
- **副次**: stdout/stderr パイプを明示的に close していないため、Popen オブジェクトの GC まで FD がリークする（ResourceWarning）。
- **推奨対応**: stderr は `subprocess.DEVNULL` にするか一時ファイルへ逃がす（現状 stderr の内容は returncode≠0 時の表示にしか使っていない）。`proc.wait(timeout=...)` を設定し、超過時は kill してフォールバックへ回す。

### [重大度: 中] meteor_detector_realtime.py:520-522 — `detect_bright_objects` が輪郭ごとにフレーム全面のマスクを確保（ホットループの性能）

候補輪郭1件ごとに `np.zeros(frame.shape)` でフレーム全面のマスクを確保し、`drawContours` + `cv2.mean`（全面走査）を実行する。計算量は O(輪郭数 × フレーム画素数)。

- **失敗シナリオ**: 雷のフラッシュ・雲の明滅・ノイズ多発時は面積フィルタを通過する輪郭が数十件規模になり、まさにバースト時＝CPU飽和が起きている局面でフレームあたりの処理コストが跳ね上がる。本番 greeng4（Intel N100、各コンテナCPU 99%前後）の飽和を増幅する。v3.18.0 のバースト抑制は保存（ffmpeg起動）側の負荷を削るが、この検出側のコストは残る。`SCALE=0.5` の縮小処理でフレームは小さくなっているため致命的ではないが、飽和条件下では効く。
- **推奨対応**: `cv2.boundingRect(contour)` で ROI を切り出し、ROI サイズのマスクで `cv2.mean` を計算する（結果は同一で、確保・走査量が輪郭外接矩形に縮小）。`_calculate_mask_overlap_ratio` へ渡す候補マスクも同様に ROI 化できる。

### [重大度: 低] meteor_detector_realtime.py:52-53 — `-r` へ渡す fps の整数丸め

`f"{target_fps:.0f}"` により推定 fps が整数に丸められる。Tapo C120 の夜間実効 fps は 9〜11 前後の非整数になりうるため、例えば 10.8fps → `-r 11` で約2%の再生尺誤差が生じる。低 fps ほど誤差率が大きい（理論上 1.4 → 1 で約40%）。GOP 計算（39行）は丸め前の値、OpenCV フォールバック（139行）は非丸め値を使うため、経路間で微妙に不整合。実害は小さいが、fps 精度をめぐる一連の修正（v3.17.2 / v3.18.0）の趣旨からは `-r` に小数（または分数）表記を渡すのが一貫する。

### [重大度: 低] meteor_detector_realtime.py:413 — フレーム時刻が `time.time()`（壁時計）由来

`timestamp = time.time() - self.start_time` は NTP ステップ調整でジャンプしうる。前方ジャンプが `max_gap_time`（2.0秒）を超えると全アクティブトラックが誤って確定・評価され、後方ジャンプは非単調時刻を生む（fps 推定側は `dt > 0` フィルタで防御済み、`EventMerger` も非単調到着に耐えることは確認済み）。`time.monotonic()` への切り替えが安全。長期稼働コンテナでの発生頻度は低く重大度は低とするが、検出コアの時刻基盤なので次回改修時の検討を推奨。

### [重大度: 低] meteor_detector_realtime.py:400-410, 440-443 — `cap.read()` にタイムアウトなし・stop() 時の VideoCapture リーク

FFmpeg バックエンドのタイムアウトオプション（`OPENCV_FFMPEG_CAPTURE_OPTIONS` の `rw_timeout` 等）が未設定のため、TCP 接続が生きたままストリームが停止すると `cap.read()` が長時間ブロックしうる（v3.17.3 の CHANGELOG にも 10秒超ブロックの実測記載あり）。その状態で `stop()` を呼ぶと `join(timeout=2.0)` が失敗し、`cap.release()` は実行されない。デーモンスレッドかつ上位ウォッチドッグ（stream_alive 判定）で緩和されているため実害は限定的。

### [重大度: 低] meteor_detector_realtime.py:527-530, 612-671 — `[DEBUG]` print が無条件・flush なし・レベル制御なし

棄却理由のデバッグ出力が本番でも無条件に出る。ノイズ多発時（輪郭・トラックが大量に棄却される局面）はホットループ内の I/O 負荷とログ肥大の一因になる。また `PYTHONUNBUFFERED` 未設定・`python -u` なしのコンテナでは flush なしの print はブロックバッファされ、flush=True の他の行と出力順序が乱れたりクラッシュ時に失われたりする。環境変数によるログレベル制御（または少なくとも flush の統一）を推奨。

### [重大度: 低] meteor_detector_realtime.py:333-335 — `RingBuffer.max_frames` が 0 になりうる

`int(max_seconds * fps)` は小さい `max_seconds` × 低 fps で 0 になり、`deque(maxlen=0)` は何も保持しない。その場合 `save_meteor_event` の `get_range` が常に空を返し、検出イベントが**無警告で**保存されなくなる。`max(1, ...)` ガードか初期化時の警告を推奨。現行の呼び出し（buffer 既定15秒）では発生しない。

### [重大度: 低] meteor_detector_realtime.py:292-323 — `DetectionParams` のレンジ検証なし（前回申し送り・継続）

`exclude_bottom_ratio` / `exclude_edge_ratio` が 0.5 超・負値でも受理され、1.0 超では `thresh` 全面がゼロ化されて検出が無警告で全滅する。`burst_window_time` / `burst_max_events` も同様に未検証（注入経路: rtsp_web の `setattr` ループ、値は WebUI 設定由来）。加えて本レビューで新規に確認した点として、`burst_max_events × burst_window_time > 10 × max(burst_window_time, merge_max_gap_time)` となる極端な設定では、`_prune_arrival_times`（809行）の保持幅をクラスタのスパンが超え、クラスタ前端の到着記録が刈られてバースト検知漏れ（破棄されない方向＝安全側）が起こりうる。既定値（5×1.0=5秒 < 15秒）では発生しない。レンジ検証を入れる際はこの整合条件も併せて検査対象にすること。

### [重大度: 低] meteor_detector_realtime.py:195-197 — fps クランプ発動時の WARN ログなし（前回申し送り・継続、通算5回目）

クランプ発動は CPU 飽和の代理指標であり、無言クランプは症状を塗り潰して観測不能にする。5回のレビューで繰り返し指摘しており未対応。

### [重大度: 低] meteor_detector_realtime.py:874-876 — `_reject_bursts` が events 空でも `_burst_start_times()`（sorted 含む）を先に実行（前回申し送り・継続）

`flush_expired()` は毎フレーム呼ばれ、大半の周回で確定イベントは空。`if not events: return events` を先頭に出すだけで回避できる。現状の `_arrival_times` は保持幅15秒ぶん（バースト直後でも百数十件程度）に有界のため実測負荷は軽微であり、重大度は低のまま。

### [重大度: 低] meteor_detector_realtime.py:966-967, 979-984, 1010-1011 — 保存失敗時の記録・通知の欠落

(1) `get_range` が空を返した場合は無言で `None` を返し、イベントは痕跡なく消える（ログ1行も出ない）。(2) クリップ書き出し失敗時は WARN のみで jsonl 記録・コンポジットも書かれずイベント全体が失われる（WARN 文言「エンコーダの初期化に失敗」は ffmpeg 実行時エラーのケースも包含しており不正確）。(3) `cv2.imwrite` の戻り値未確認（ディスクフル等で無警告。ただし `exists()` チェックにより record への誤記載はない）。少なくとも (1) にログを追加し、(2) はクリップなしでも jsonl とコンポジットを残す設計の検討を推奨。

### [重大度: 低] tests/test_meteor_detector_realtime.py:196, 247 — テスト実効性2件（前回申し送り・継続）

- `test_event_merger_handles_non_monotonic_arrival_order` の最終アサーションは `assert isinstance(finalized, list)` のままで、常に真（実際の挙動「7件全件破棄」を検証も主張もしていない）。
- `test_event_merger_does_not_burst_reject_merged_fragments` は `assert 0 < len(finalized) <= len(fragments)` のままで、部分的な誤破棄（実測値は2件）の回帰を検出できない。

いずれも v4 報告書の是正処置記録に記載済み・未対応。

### [重大度: 低] documents/DETECTOR_COMPONENTS.md — 既知の設計限界・仕様の文書化不足

1. **`length` の説明「軌跡長（ピクセル）」（568行）が実装と不一致**。実装は始点・終点間の直線距離（`meteor_detector_realtime.py:273-276`）であり、屈曲・断片マージ後の軌跡では実際の移動距離より短くなる。「始点終点間の直線距離」と明記すべき。
2. **`frames` フィールドがリアルタイム経路では常に空**（`_finalize_track` / `_merge` とも `frames=[]`。軌跡点列は MeteorEvent に保存されず、保存動画は RingBuffer から時刻範囲で切り出す設計）である旨が未記載。「フレームリスト」という説明だけでは中身が入っていると誤読する。
3. **`estimate_fps_from_frames` / `max_ratio_to_fallback` のクランプ仕様が未記載**。CHANGELOG とリリースノート（`documents/releases/2026-08-16-v3.18.0.md`）には詳述されているが、コンポーネント仕様書側に対応する記述がない（`documents/` は GitHub Pages 公開対象であり、コード変更と対応ドキュメントの改版が本プロジェクトの方針）。
4. ドキュメント中のソース行番号参照（「実装: meteor_detector_realtime.py:262-273 / 879-892」）が v3.18.0 の行ずれで乖離している。行番号ではなく関数名参照を推奨。
5. 731件実データ検証の生存バイアス限界が未記載（v4 指摘3・継続）。

なおバースト抑制自体の文書化（パラメータ表・方式の経緯・マージ経路との相互作用・`CONFIGURATION_GUIDE.md` のパラメータ追記）は正確で網羅的であることを確認した。

---

## セキュリティ検査結果

- **認証情報漏洩**: 上記指摘のとおり、`RTSPReader._read_loop` の接続失敗ログと ffprobe 診断詳細に RTSP URL（パスワード込み）が平文出力される（中）。`probe_rtsp_endpoint` は host/port のみで安全。それ以外の print / jsonl 出力に認証情報の混入経路はない。
- **コマンドインジェクション**: `subprocess.Popen` / `run` はいずれもリスト形式で `shell=False`。URL・パスは引数として渡されシェル解釈されない。問題なし。
- **パストラバーサル**: 本ファイル内のパス構築（`output_dir / f"{base_name}..."`）は、`base_name` がタイムスタンプ＋sha1 断片から機械生成され、ユーザー入力の混入経路がない。問題なし。
- **XSS**: 本ファイルは HTML を生成しない。対象外。
- **入力値検証**: `DetectionParams` のレンジ未検証（低・継続）。攻撃経路というより設定ミスによる無警告の機能停止が主リスク。

---

## 前回申し送り事項の現状確認（v4 報告書・是正処置記録6件）

| # | 内容 | 現状 |
|---|---|---|
| 1（中） | 非単調到着テストの `isinstance` のみアサーション | **未対応**（tests:247 で現存を確認） |
| 2（低） | マージ断片テストの緩い範囲アサーション | **未対応**（tests:196 で現存を確認） |
| 3（低） | 731件検証の生存バイアス限界のドキュメント未記載 | **未対応**（DETECTOR_COMPONENTS.md 該当節に記載なし） |
| 4（低） | `_reject_bursts` が空イベントでも毎回ソート | **未対応**（realtime:874 で現存を確認） |
| 5（低・通算5回目） | fps クランプ発動時の WARN ログなし | **未対応**（estimate_fps_from_frames に print なし） |
| 6（低） | `burst_window_time` 等の入力値レンジチェックなし | **未対応**（DetectionParams / rtsp_web setattr ループとも検証なし。本レビューで prune 保持幅との整合条件を追加指摘） |

6件全件が未対応のまま。いずれも承認をブロックしない性質は変わらないが、特に #1・#5 は対応コストが小さい（アサーション1行の置換・print 1行の追加）割に効果が明確なため、次回改修時の優先対応を推奨する。

---

## テスト実行結果

ローカル仮想環境（`.venv`）で実施。

- `pytest tests/test_meteor_detector_realtime.py -q` → **20件全通過**（0.85秒）
- `pytest -q`（全体）→ **320 passed / 1 failed**
  - 失敗: `tests/test_generate_compose.py::test_generate_compose_mask_path_failure`
  - **本レビュー対象ファイルとは無関係**であることを確認した。原因は作業ツリーに存在する未追跡の `masks/` ディレクトリ（本番由来の `camera1_mask.png` ほか＋`.generated_hashes.json`）。`generate_compose.py:440` が `mask_output_dir` を相対パス `masks` で解決するため、テストが cwd のローカルデータを読んでしまい「手動更新済みのためスキップ」分岐に入り、monkeypatch した `generate_mask_file` の RuntimeError に到達せず `SystemExit` が発生しない。テスト分離（cwd 依存）の問題であり、クリーンなチェックアウト（CI）では通過する。generate_compose 系テストの改修時に `mask_output_dir` を tmp_path 化することを推奨する。

---

## release-manager への申し送り

- 本レビューは v3.18.0 リリース後のフルレビューであり、リリース判定は変更しない（承認済み・デプロイ済み）。
- 中3件（認証情報ログ出力・ffmpeg デッドロック可能性・輪郭ごと全面マスク確保）はいずれも既存問題であり緊急性はないが、認証情報ログ出力は SECURITY.md のリスク評価（高）と v3.4.6 で確立したマスク方針に反する不整合のため、次回のパッチリリース候補として最優先を推奨する。修正時は「変更禁止ファイル」の変更許可をユーザーから明示的に得ること。

## 是正処置記録（承認・残存事項、承認はブロックしない）

| 指摘番号 | 指摘内容の要約 | 是正期限 | 是正担当 | 是正状況 |
|---------|-------------|---------|---------|---------|
| 1（中） | RTSP URL（認証情報込み）の接続失敗ログ平文出力・ffprobe 詳細のエコー | 次回パッチ | developer | 未対応 |
| 2（中） | write_mp4_clip_ffmpeg の stderr パイプデッドロック可能性・wait 無タイムアウト・FD 未クローズ | 任意 | developer | 未対応 |
| 3（中） | detect_bright_objects の輪郭ごと全面マスク確保（ROI 化で削減可） | 任意 | developer | 未対応 |
| 4-14（低） | 本文の低指摘11件（前回申し送り6件の残存を含む） | 任意 | developer | 未対応 |
