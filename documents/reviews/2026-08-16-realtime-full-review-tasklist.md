# タスクリスト: realtime.py フルレビュー指摘対応

- 元レビュー: `documents/reviews/2026-08-16-realtime-full-review.md`
- 対象: `meteor_detector_realtime.py`（変更禁止ファイル、ユーザーから「realtime.pyそのものの改善」として変更許可済み）・`meteor_detector_common.py`・`tests/test_meteor_detector_realtime.py`・`documents/DETECTOR_COMPONENTS.md`
- 除外: 中1（RTSP URL認証情報のログ平文出力、meteor_detector_realtime.py:378, 381-382）— ローカル環境限定運用を前提とし、ユーザー判断により対応不要（[[feedback_local-only-security-scope]]参照）
- 方針: 除外項目を除き、重大度にかかわらず全件修正する

## ステータス凡例
- [ ] 未着手
- [~] 着手中
- [x] 完了

## タスク一覧

| # | 重大度 | 内容 | 該当箇所 | 状態 |
|---|---|---|---|---|
| 1 | 中 | ffmpeg サブプロセスのデッドロック可能性（stderr未読・wait無タイムアウト・FD未クローズ） | realtime.py:96-119 | [x] |
| 2 | 中 | detect_bright_objects の輪郭ごと全面マスク確保（ROI化で削減） | realtime.py:520-522 | [x] |
| 3 | 低 | `-r` へ渡す fps の整数丸め（再生尺誤差） | realtime.py:52-53 | [x] |
| 4 | 低 | フレーム時刻が time.time()（壁時計）由来、monotonic化推奨 | realtime.py:413 | [x] |
| 5 | 低 | cap.read() タイムアウトなし・stop()時のVideoCaptureリーク | realtime.py:400-410, 440-443 | [x]（rw_timeoutのみ対応。VideoCaptureリークは未対応・理由は仕様書参照） |
| 6 | 低 | [DEBUG] print が無条件・flushなし・レベル制御なし | realtime.py:527-530, 612-671 | [x] |
| 7 | 低 | RingBuffer.max_frames が0になりうる（無警告でイベント消失） | realtime.py:333-335 | [x] |
| 8 | 低 | DetectionParams のレンジ検証なし（前回申し送り継続、prune保持幅との整合条件含む） | realtime.py:292-323 | [x]（`__post_init__`経由のみ対応。rtsp_web.pyのsetattr注入経路は未カバー・仕様書参照） |
| 9 | 低 | fps クランプ発動時の WARN ログなし（前回申し送り継続・通算5回目） | realtime.py:195-197 | [x] |
| 10 | 低 | `_reject_bursts` が events 空でも sorted 等を先に実行（前回申し送り継続） | realtime.py:874-876 | [x] |
| 11 | 低 | 保存失敗時の記録・通知欠落（get_range空・クリップ失敗・imwrite戻り値未確認） | realtime.py:966-967, 979-984, 1010-1011 | [x] |
| 12 | 低 | テスト実効性2件（isinstance のみ／緩い範囲アサーション、前回申し送り継続） | tests/test_meteor_detector_realtime.py:196, 247 | [x] |
| 13 | 低 | DETECTOR_COMPONENTS.md の記述不足5点（length説明・frames空・fpsクランプ仕様・行番号参照・生存バイアス限界） | documents/DETECTOR_COMPONENTS.md | [x] |

## 進捗ログ
- 2026-08-16: タスクリスト作成、developerエージェントへ実装依頼
- 2026-08-17: 全13件を実装完了。テスト24件全通過（新規4件追加）。flake8エラーなし。
  詳細は `documents/specs/2026-08-16-realtime-review-fixes.md` を参照。

## 是正処置対応（reviewer報告書 2026-08-17 分）

- 元レビュー: `documents/reviews/2026-08-17-realtime-fixes-review.md`（判定: 承認、低6件＋スコープ違反1件）

| # | 重大度 | 内容 | 該当箇所 | 状態 |
|---|---|---|---|---|
| 0 | スコープ | `.claude/agents/reviewer.md` の `model: inherit`→`model: opus` 変更 | `.claude/agents/reviewer.md` | [x] 確認済み・対応不要（別コミット予定、変更はそのまま残す） |
| 1 | 低 | ROI等価性テストが非対称フィクスチャ不足で1pxずれ・座標入れ替え変異を検出できない | `tests/test_meteor_detector_realtime.py` | [x] |
| 2 | 低 | `wait_timeout` が `write_clip_with_fallback` から転送されず本番到達不能 | `meteor_detector_realtime.py:67,176-193` | [x] |
| 3 | 低 | `proc.stdin.write()` 無制限ブロック残課題を仕様書に明記 | `documents/specs/2026-08-16-realtime-review-fixes.md` | [x] |
| 4 | 低 | `RTSP_RW_TIMEOUT_US` のTCP強制・起動時のみ評価の副作用未文書化 | `documents/CONFIGURATION_GUIDE.md:130` | [x] |
| 5 | 低 | 実装仕様書の新規テスト件数「5件」表記の誤り（正しくは4件） | `documents/specs/2026-08-16-realtime-review-fixes.md` | [x] |

対応不要（release-manager担当）: 「次回リリースで追加」表記の版番号への置換（`CONFIGURATION_GUIDE.md:130-131`、`DETECTOR_COMPONENTS.md:1046`）。

### 進捗ログ（是正処置対応）
- 2026-08-17: 低5件を対応完了。ROI等価性テストを非対称フィクスチャに置き換え、変異テスト（offset 1pxずれ・座標入れ替え）で検出力を確認（元コードへ復元済み）。`write_clip_with_fallback` に `wait_timeout` パラメータを追加し `write_mp4_clip_ffmpeg` へ転送（デフォルト60.0秒維持）。`proc.stdin.write()` 残課題を実装仕様書に明記。`RTSP_RW_TIMEOUT_US` のTCP強制・起動時のみ評価の副作用を `CONFIGURATION_GUIDE.md` に追記。実装仕様書のテスト件数「5件」を「4件」に訂正。全体テスト324 passed/1 failed（既知の無関係な失敗のみ）、flake8エラーなしを確認。スコープ違反（`.claude/agents/reviewer.md`）は指示通り対応せず確認のみ。詳細は `documents/specs/2026-08-16-realtime-review-fixes.md` の「是正処置対応（2026-08-17）」節を参照。
