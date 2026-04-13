#!/usr/bin/env python3
"""流星検出データ転送ツール（インタラクティブエクスポート＋インポート）

サブコマンド:
  export  - TUI で検出データを選択し ZIP を作成する。必要なら scp で転送。
  import  - ZIP またはディレクトリから検出データを取り込む。

使い方（エクスポート側）:
    # インタラクティブに選択して ZIP 作成
    python scripts/transfer_detections.py export

    # ZIP 作成後に scp で転送
    python scripts/transfer_detections.py export --scp user@192.168.1.10:/home/user/

    # カメラを絞り込む
    python scripts/transfer_detections.py export --camera camera1_10_0_1_25

使い方（インポート側）:
    # ドライラン（デフォルト）
    python scripts/transfer_detections.py import transfer_20260413.zip

    # 実際に取り込む
    python scripts/transfer_detections.py import transfer_20260413.zip --apply

    # ディレクトリから取り込む（旧システムの detections/ を指定）
    python scripts/transfer_detections.py import /mnt/other/detections --apply

    # カメラ名をマッピング（別名で運用していた場合）
    python scripts/transfer_detections.py import transfer.zip \\
        --camera-map old_cam:camera1_10_0_1_25 --apply

TUI キー操作（export モード）:
    ↑ ↓ / j k : 移動
    Space       : 選択 / 解除
    a           : 全選択 / 全解除トグル
    f           : フィルターパネルを開く
    e / Enter   : 選択したデータをエクスポート
    q / Esc     : キャンセル

フィルターパネルキー操作:
    Tab / Shift+Tab : フィールド移動
    ↑ ↓            : 選択肢変更
    Enter           : フォーカス中フィールドを確定 / [適用] 実行
    Esc             : キャンセル
"""

from __future__ import annotations

import argparse
import curses
import json
import shutil
import socket
import subprocess
import sys
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPT_DIR.parent
sys.path.insert(0, str(_PROJECT_ROOT))

import detection_store  # noqa: E402

_SKIP_DIRS = {"masks", "runtime_settings", "manual_recordings"}
_SKIP_FILES = {".DS_Store", "detections.db", "detection_labels.json"}
_SKIP_EXTS = {".jsonl", ".db"}
_ZIP_ROOT = "meteo_transfer"


# ──────────────────────────────────────────────────────────────────────────────
# 共通ユーティリティ
# ──────────────────────────────────────────────────────────────────────────────

def _load_jsonl_records(jsonl_path: Path) -> list[tuple[str, dict]]:
    if not jsonl_path.exists():
        return []
    results = []
    for line in jsonl_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        try:
            results.append((stripped, json.loads(stripped)))
        except json.JSONDecodeError:
            pass
    return results


def _rewrite_asset_paths(record: dict, old_camera: str, new_camera: str) -> dict:
    updated = dict(record)
    prefix_old = old_camera + "/"
    prefix_new = new_camera + "/"
    for field in ("clip_path", "image_path", "composite_original_path"):
        v = updated.get(field)
        if isinstance(v, str) and v.startswith(prefix_old):
            updated[field] = prefix_new + v[len(prefix_old):]
    alt = updated.get("alternate_clip_paths")
    if isinstance(alt, list):
        updated["alternate_clip_paths"] = [
            prefix_new + p[len(prefix_old):] if isinstance(p, str) and p.startswith(prefix_old) else p
            for p in alt
        ]
    return updated


def _collect_media_files(cam_dir: Path) -> list[Path]:
    files = []
    for p in cam_dir.iterdir():
        if p.is_dir() or p.name in _SKIP_FILES or p.suffix.lower() in _SKIP_EXTS:
            continue
        files.append(p)
    return sorted(files, key=lambda p: p.name)


def _sync_to_sqlite(target_dir: Path, camera_name: str) -> int:
    db_path = str(target_dir / "detections.db")
    detection_store.init_db(db_path)
    detection_store.reset_sync_state(db_path, camera_name)
    from dashboard_routes import _normalize_detection_record  # noqa: PLC0415
    cam_dir = target_dir / camera_name
    return detection_store.sync_camera_from_jsonl(
        camera_name, cam_dir, db_path, _normalize_detection_record
    )


def _import_camera(
    source_cam_dir: Path,
    target_dir: Path,
    source_camera: str,
    target_camera: str,
    apply: bool,
) -> dict:
    target_cam_dir = target_dir / target_camera
    source_jsonl = source_cam_dir / "detections.jsonl"
    target_jsonl = target_cam_dir / "detections.jsonl"
    camera_renamed = source_camera != target_camera

    source_records = _load_jsonl_records(source_jsonl)
    target_set: set[str] = set()
    if target_jsonl.exists():
        for raw_line, _ in _load_jsonl_records(target_jsonl):
            target_set.add(raw_line)

    media_files = _collect_media_files(source_cam_dir)

    new_lines: list[str] = []
    skipped_jsonl = 0
    for raw_line, record in source_records:
        if camera_renamed:
            record = _rewrite_asset_paths(record, source_camera, target_camera)
            raw_line = json.dumps(record, ensure_ascii=False, separators=(",", ":"))
        if raw_line in target_set:
            skipped_jsonl += 1
        else:
            new_lines.append(raw_line)

    files_to_copy: list[tuple[Path, Path]] = []
    files_skipped = 0
    for src in media_files:
        dest = target_cam_dir / src.name
        if dest.exists():
            files_skipped += 1
        else:
            files_to_copy.append((src, dest))

    result = {
        "records_total": len(source_records),
        "records_new": len(new_lines),
        "records_skipped": skipped_jsonl,
        "files_to_copy": len(files_to_copy),
        "files_skipped": files_skipped,
        "sqlite_inserted": 0,
    }

    if not apply:
        return result

    target_cam_dir.mkdir(parents=True, exist_ok=True)
    for src, dest in files_to_copy:
        shutil.copy2(str(src), str(dest))
    if new_lines:
        with open(target_jsonl, "a", encoding="utf-8") as f:
            for line in new_lines:
                f.write(line + "\n")
    try:
        result["sqlite_inserted"] = _sync_to_sqlite(target_dir, target_camera)
    except Exception as exc:
        print(f"  WARNING: SQLite 同期エラー: {exc}", file=sys.stderr)

    return result


def _parse_camera_map(entries: list[str]) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for entry in entries:
        parts = entry.split(":", 1)
        if len(parts) != 2 or not parts[0] or not parts[1]:
            raise SystemExit(f"--camera-map の形式が不正です（'OLD:NEW' で指定）: {entry!r}")
        mapping[parts[0]] = parts[1]
    return mapping


# ──────────────────────────────────────────────────────────────────────────────
# 検出データの読み込み
# ──────────────────────────────────────────────────────────────────────────────

def _load_detections(detections_dir: Path, db_path: str, camera: str | None = None) -> list[dict]:
    """SQLite から読み込む。DB がなければ JSONL から直接構築する。"""
    if Path(db_path).exists():
        return detection_store.query_detections(db_path, camera=camera)

    # JSONL フォールバック
    import hashlib
    results = []
    for cam_dir in sorted(detections_dir.iterdir()):
        if not cam_dir.is_dir() or cam_dir.name in _SKIP_DIRS:
            continue
        if camera and cam_dir.name != camera:
            continue
        jsonl_file = cam_dir / "detections.jsonl"
        if not jsonl_file.exists():
            continue
        cam_name = cam_dir.name
        for raw_line, raw in _load_jsonl_records(jsonl_file):
            ts = raw.get("timestamp", "")
            digest = hashlib.sha1(json.dumps({
                "camera": cam_name, "timestamp": ts,
                "start_time": raw.get("start_time", ""),
                "end_time": raw.get("end_time", ""),
                "start_point": raw.get("start_point", ""),
                "end_point": raw.get("end_point", ""),
            }, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:20]

            # タイムスタンプから base_name を推定してファイルを探す
            base_name = ""
            clip_path = ""
            image_path = ""
            orig_path = ""
            if ts and len(ts) >= 19:
                date_s = ts[:10].replace("-", "")
                time_s = ts[11:19].replace(":", "")
                base_name = f"meteor_{date_s}_{time_s}"
                for ext in (".mp4", ".mov"):
                    if (cam_dir / (base_name + ext)).exists():
                        clip_path = f"{cam_name}/{base_name}{ext}"
                        break
                if (cam_dir / (base_name + "_composite.jpg")).exists():
                    image_path = f"{cam_name}/{base_name}_composite.jpg"
                if (cam_dir / (base_name + "_composite_original.jpg")).exists():
                    orig_path = f"{cam_name}/{base_name}_composite_original.jpg"

            results.append({
                "id": f"det_{digest}",
                "camera": cam_name,
                "timestamp": ts,
                "confidence": raw.get("confidence"),
                "base_name": base_name,
                "clip_path": clip_path,
                "image_path": image_path,
                "composite_original_path": orig_path,
                "alternate_clip_paths": [],
                "label": "",
                "deleted": 0,
                "raw_json": raw_line,
            })
    results.sort(key=lambda r: r.get("timestamp", ""), reverse=True)
    return results


# ──────────────────────────────────────────────────────────────────────────────
# ExportSelector — curses TUI
# ──────────────────────────────────────────────────────────────────────────────

class ExportSelector:
    """curses を使ったインタラクティブ選択 TUI。"""

    # カラーペア番号
    _C_HEADER = 1  # ヘッダー（シアン）
    _C_SEL = 2  # 選択済み行（緑）
    _C_CUR = 3  # カーソル行（白背景）
    _C_FILT = 4  # フィルター有効（黄）
    _C_DLG = 5  # ダイアログ（青背景）

    def __init__(self, all_records: list[dict]):
        self.all_records = all_records
        self.filtered: list[dict] = []
        self.selected: set[str] = set()
        self.cursor = 0
        self.scroll = 0
        self.cameras: list[str] = sorted({r["camera"] for r in all_records})
        self.filter_camera: str | None = None
        self.filter_label: str | None = None   # None=全て, ""=ラベルなし, "meteor"等
        self.filter_date_from = ""
        self.filter_date_to = ""
        self.cancelled = False

    # ── 公開インターフェース ─────────────────────────────────────────────────

    def run(self) -> list[dict] | None:
        """TUI を実行し、選択されたレコードリストを返す。キャンセル時は None。"""
        self._apply_filters()
        curses.wrapper(self._main)
        if self.cancelled:
            return None
        return [r for r in self.all_records if r["id"] in self.selected]

    # ── curses メインループ ──────────────────────────────────────────────────

    def _main(self, stdscr: curses.window):
        self._init_colors()
        stdscr.keypad(True)
        curses.curs_set(0)
        while True:
            self._draw(stdscr)
            key = stdscr.getch()
            if not self._handle_key(stdscr, key):
                break

    def _init_colors(self):
        curses.start_color()
        curses.use_default_colors()
        curses.init_pair(self._C_HEADER, curses.COLOR_CYAN,    -1)
        curses.init_pair(self._C_SEL,    curses.COLOR_GREEN,   -1)
        curses.init_pair(self._C_CUR,    curses.COLOR_BLACK,   curses.COLOR_WHITE)
        curses.init_pair(self._C_FILT,   curses.COLOR_YELLOW,  -1)
        curses.init_pair(self._C_DLG,    curses.COLOR_WHITE,   curses.COLOR_BLUE)

    # ── 画面描画 ─────────────────────────────────────────────────────────────

    def _draw(self, stdscr: curses.window):
        stdscr.erase()
        h, w = stdscr.getmaxyx()

        # ヘッダー
        title = " Meteo 検出データ エクスポート "
        stats = f" 選択: {len(self.selected)}/{len(self.filtered)}件 "
        try:
            stdscr.attron(curses.color_pair(self._C_HEADER) | curses.A_BOLD)
            stdscr.addstr(0, 0, title.ljust(w - len(stats)))
            stdscr.addstr(0, w - len(stats), stats)
            stdscr.attroff(curses.color_pair(self._C_HEADER) | curses.A_BOLD)
        except curses.error:
            pass

        # フィルターバー
        cam_s = self.filter_camera or "全て"
        lbl_s = {None: "全て", "": "ラベルなし"}.get(self.filter_label, self.filter_label)
        df_s = self.filter_date_from or "----"
        dt_s = self.filter_date_to or "----"
        fbar = f" [f]フィルター  カメラ:{cam_s}  期間:{df_s}~{dt_s}  ラベル:{lbl_s} "
        fattr = curses.color_pair(self._C_FILT) if self._any_filter() else curses.A_DIM
        try:
            stdscr.addstr(1, 0, fbar[:w], fattr)
        except curses.error:
            pass

        # カラムヘッダー
        hdr = f"{'   '} {'日時':<19} {'カメラ':<24} {'信頼度':>6} {'ラベル':<12}"
        try:
            stdscr.attron(curses.A_UNDERLINE)
            stdscr.addstr(2, 0, hdr[:w])
            stdscr.attroff(curses.A_UNDERLINE)
        except curses.error:
            pass

        # リスト行
        list_h = max(1, h - 5)
        visible = self.filtered[self.scroll:self.scroll + list_h]
        for i, rec in enumerate(visible):
            y = 3 + i
            abs_idx = self.scroll + i
            is_cur = abs_idx == self.cursor
            is_sel = rec["id"] in self.selected

            mark = " ✓ " if is_sel else "   "
            ts = (rec.get("timestamp") or "")[:19].replace("T", " ")
            cam = (rec.get("camera") or "")[:24]
            conf = rec.get("confidence")
            cs = f"{conf*100:.0f}%" if conf is not None else "  - "
            lbl = str(rec.get("label") or "")[:12]

            line = f"{mark} {ts:<19} {cam:<24} {cs:>6} {lbl:<12}"

            if is_cur:
                attr = curses.color_pair(self._C_CUR) | curses.A_BOLD
            elif is_sel:
                attr = curses.color_pair(self._C_SEL)
            else:
                attr = 0
            try:
                stdscr.addstr(y, 0, line[:w - 1], attr)
            except curses.error:
                pass

        # フッター（キーヒント）
        footer = " ↑↓:移動  Space:選択  a:全選択/解除  f:フィルター  e:エクスポート  q:中止 "
        try:
            stdscr.attron(curses.A_REVERSE)
            stdscr.addstr(h - 1, 0, footer[:w - 1].ljust(w - 1))
            stdscr.attroff(curses.A_REVERSE)
        except curses.error:
            pass

        stdscr.refresh()

    # ── キー処理 ─────────────────────────────────────────────────────────────

    def _handle_key(self, stdscr: curses.window, key: int) -> bool:
        h, w = stdscr.getmaxyx()
        list_h = max(1, h - 5)
        n = len(self.filtered)

        if key in (curses.KEY_UP, ord('k')):
            if self.cursor > 0:
                self.cursor -= 1
                if self.cursor < self.scroll:
                    self.scroll = self.cursor
        elif key in (curses.KEY_DOWN, ord('j')):
            if self.cursor < n - 1:
                self.cursor += 1
                if self.cursor >= self.scroll + list_h:
                    self.scroll = self.cursor - list_h + 1
        elif key == curses.KEY_PPAGE:
            self.cursor = max(0, self.cursor - list_h)
            self.scroll = max(0, self.scroll - list_h)
        elif key == curses.KEY_NPAGE:
            self.cursor = min(max(0, n - 1), self.cursor + list_h)
            self.scroll = min(max(0, n - list_h), self.scroll + list_h)
        elif key == ord(' '):
            if 0 <= self.cursor < n:
                rid = self.filtered[self.cursor]["id"]
                if rid in self.selected:
                    self.selected.discard(rid)
                else:
                    self.selected.add(rid)
        elif key == ord('a'):
            if len(self.selected) == len(self.filtered):
                self.selected.clear()
            else:
                self.selected = {r["id"] for r in self.filtered}
        elif key == ord('n'):
            self.selected.clear()
        elif key == ord('f'):
            self._filter_dialog(stdscr)
        elif key in (ord('e'), ord('\n'), curses.KEY_ENTER):
            if self.selected:
                self.cancelled = False
                return False
        elif key in (ord('q'), 27):
            self.cancelled = True
            return False
        return True

    # ── フィルターダイアログ ────────────────────────────────────────────────

    def _filter_dialog(self, stdscr: curses.window):
        h, w = stdscr.getmaxyx()

        cam_opts = ["(全て)"] + self.cameras
        lbl_opts = ["(全て)", "meteor", "not_meteor", "(ラベルなし)"]
        lbl_vals = [None, "meteor", "not_meteor", ""]

        # 現在値を選択肢インデックスに変換
        ci = 0
        if self.filter_camera and self.filter_camera in cam_opts:
            ci = cam_opts.index(self.filter_camera)
        li = 0
        for i, v in enumerate(lbl_vals):
            if v == self.filter_label:
                li = i
                break

        date_from = self.filter_date_from
        date_to = self.filter_date_to

        # フォーカス: 0=カメラ一覧, 1=ラベル一覧, 2=開始日, 3=終了日, 4=適用, 5=キャンセル
        focus = 0

        n_cam = len(cam_opts)
        n_lbl = len(lbl_opts)
        dh = 5 + n_cam + n_lbl   # ダイアログ高さ
        dw = 44
        dh = min(dh, h - 2)
        dw = min(dw, w - 2)
        dy = (h - dh) // 2
        dx = (w - dw) // 2

        win = curses.newwin(dh, dw, dy, dx)
        win.keypad(True)

        while True:
            win.erase()
            win.attron(curses.color_pair(self._C_DLG))
            win.box()
            win.attroff(curses.color_pair(self._C_DLG))
            try:
                win.addstr(0, 2, " フィルター ", curses.A_BOLD)
            except curses.error:
                pass

            row = 1
            try:
                win.addstr(row, 1, "カメラ:", curses.A_BOLD)
            except curses.error:
                pass
            for i, opt in enumerate(cam_opts):
                if row + 1 + i >= dh - 1:
                    break
                mark = "●" if i == ci else "○"
                attr = curses.A_REVERSE if (focus == 0 and i == ci) else 0
                try:
                    win.addstr(row + 1 + i, 3, f"{mark} {opt[:dw - 6]}", attr)
                except curses.error:
                    pass

            row += n_cam + 2
            try:
                win.addstr(row, 1, "ラベル:", curses.A_BOLD)
            except curses.error:
                pass
            for i, opt in enumerate(lbl_opts):
                if row + 1 + i >= dh - 1:
                    break
                mark = "●" if i == li else "○"
                attr = curses.A_REVERSE if (focus == 1 and i == li) else 0
                try:
                    win.addstr(row + 1 + i, 3, f"{mark} {opt}", attr)
                except curses.error:
                    pass

            row += n_lbl + 2
            df_attr = curses.A_REVERSE if focus == 2 else 0
            dt_attr = curses.A_REVERSE if focus == 3 else 0
            try:
                win.addstr(row, 1, f"開始日 [{date_from or '----------':10}]", df_attr)
                win.addstr(row + 1, 1, f"終了日 [{date_to or '----------':10}]", dt_attr)
            except curses.error:
                pass

            row += 3
            apl_attr = curses.A_REVERSE if focus == 4 else 0
            cnl_attr = curses.A_REVERSE if focus == 5 else 0
            try:
                win.addstr(row, 2,  " 適用 ", apl_attr)
                win.addstr(row, 10, " キャンセル ", cnl_attr)
            except curses.error:
                pass

            win.refresh()
            key = win.getch()

            if key == 27:
                break
            elif key == ord('\t'):
                focus = (focus + 1) % 6
            elif key in (curses.KEY_BTAB,):
                focus = (focus - 1) % 6
            elif key in (curses.KEY_UP, ord('k')):
                if focus == 0:
                    ci = max(0, ci - 1)
                elif focus == 1:
                    li = max(0, li - 1)
                else:
                    focus = max(0, focus - 1)
            elif key in (curses.KEY_DOWN, ord('j')):
                if focus == 0:
                    ci = min(n_cam - 1, ci + 1)
                elif focus == 1:
                    li = min(n_lbl - 1, li + 1)
                else:
                    focus = min(5, focus + 1)
            elif key in (ord('\n'), curses.KEY_ENTER, ord(' ')):
                if focus == 4:  # 適用
                    self.filter_camera = None if ci == 0 else cam_opts[ci]
                    self.filter_label = lbl_vals[li]
                    self.filter_date_from = date_from
                    self.filter_date_to = date_to
                    self._apply_filters()
                    self.cursor = min(self.cursor, max(0, len(self.filtered) - 1))
                    self.scroll = 0
                    break
                elif focus == 5:  # キャンセル
                    break
                elif focus == 2:
                    date_from = self._inline_input(win, row, 9, date_from, 10)
                elif focus == 3:
                    date_to = self._inline_input(win, row + 1, 9, date_to, 10)

        del win
        stdscr.touchwin()
        stdscr.refresh()

    @staticmethod
    def _inline_input(win: curses.window, y: int, x: int, current: str, maxlen: int) -> str:
        """ウィンドウ内でインライン文字列入力を行う。"""
        curses.curs_set(1)
        s = current
        while True:
            try:
                win.addstr(y, x, (s or "")[:maxlen].ljust(maxlen), curses.A_REVERSE)
                win.move(y, x + min(len(s), maxlen - 1))
                win.refresh()
            except curses.error:
                pass
            key = win.getch()
            if key in (ord('\n'), curses.KEY_ENTER):
                break
            elif key == 27:
                s = current
                break
            elif key in (curses.KEY_BACKSPACE, 127, 8):
                s = s[:-1]
            elif 32 <= key <= 126 and len(s) < maxlen:
                s += chr(key)
        curses.curs_set(0)
        return s

    # ── フィルター適用 ───────────────────────────────────────────────────────

    def _apply_filters(self):
        r = self.all_records
        if self.filter_camera:
            r = [x for x in r if x["camera"] == self.filter_camera]
        if self.filter_label is not None:
            r = [x for x in r if (x.get("label") or "") == self.filter_label]
        if self.filter_date_from:
            r = [x for x in r if (x.get("timestamp") or "") >= self.filter_date_from]
        if self.filter_date_to:
            end = self.filter_date_to + "T99"
            r = [x for x in r if (x.get("timestamp") or "") <= end]
        self.filtered = r

    def _any_filter(self) -> bool:
        return bool(self.filter_camera or self.filter_label is not None
                    or self.filter_date_from or self.filter_date_to)


# ──────────────────────────────────────────────────────────────────────────────
# ZipPackager — ZIP 作成
# ──────────────────────────────────────────────────────────────────────────────

class ZipPackager:
    def __init__(self, detections_dir: Path, output_path: Path):
        self.detections_dir = detections_dir
        self.output_path = output_path

    def build(self, records: list[dict]) -> int:
        """ZIP を作成し、追加したメディアファイル数を返す。"""
        cameras: dict[str, list[str]] = {}
        for rec in records:
            cameras.setdefault(rec["camera"], []).append(rec.get("raw_json", ""))

        files_added = 0
        seen: set[str] = set()

        with zipfile.ZipFile(self.output_path, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
            # manifest.json
            manifest = {
                "version": 1,
                "created_at": datetime.now().isoformat(timespec="seconds"),
                "source_host": socket.gethostname(),
                "cameras": sorted(cameras.keys()),
                "record_count": len(records),
            }
            zf.writestr(
                f"{_ZIP_ROOT}/manifest.json",
                json.dumps(manifest, ensure_ascii=False, indent=2),
            )

            # カメラごと JSONL + メディア
            for cam_name, jsonl_lines in cameras.items():
                # JSONL（選択分のみ）
                content = "\n".join(l for l in jsonl_lines if l) + "\n"
                zf.writestr(f"{_ZIP_ROOT}/{cam_name}/detections.jsonl", content)

                # メディアファイル
                cam_dir = self.detections_dir / cam_name
                for rec in records:
                    if rec["camera"] != cam_name:
                        continue
                    asset_fields = [
                        rec.get("clip_path", ""),
                        rec.get("image_path", ""),
                        rec.get("composite_original_path", ""),
                    ] + list(rec.get("alternate_clip_paths") or [])
                    for rel in asset_fields:
                        if not rel:
                            continue
                        fname = rel.split("/")[-1]
                        arc = f"{_ZIP_ROOT}/{cam_name}/{fname}"
                        if arc in seen:
                            continue
                        seen.add(arc)
                        src = cam_dir / fname
                        if src.exists() and src.is_file():
                            zf.write(str(src), arc)
                            files_added += 1
        return files_added


# ──────────────────────────────────────────────────────────────────────────────
# cmd_export
# ──────────────────────────────────────────────────────────────────────────────

def cmd_export(args: argparse.Namespace) -> None:
    detections_dir = Path(args.detections_dir).resolve()
    db_path = args.db or str(detections_dir / "detections.db")

    if not detections_dir.exists():
        raise SystemExit(f"ERROR: detections ディレクトリが見つかりません: {detections_dir}")

    print(f"検出データを読み込み中: {detections_dir} ...", end="", flush=True)
    records = _load_detections(detections_dir, db_path, camera=args.camera or None)
    print(f" {len(records)} 件")

    if not records:
        raise SystemExit("検出データがありません。")

    # TUI 起動
    selector = ExportSelector(records)
    selected = selector.run()

    if selected is None:
        print("キャンセルしました。")
        return
    if not selected:
        print("1件も選択されていません。中止します。")
        return

    # ZIP 作成
    ts_str = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = Path(args.output) if args.output else Path(f"transfer_{ts_str}.zip")
    output_path = output_path.resolve()

    print(f"\n{len(selected)} 件を ZIP に書き出し中: {output_path} ...")
    packager = ZipPackager(detections_dir, output_path)
    files_added = packager.build(selected)
    zip_size_mb = output_path.stat().st_size / 1024 / 1024
    print(f"完了: レコード {len(selected)} 件 + メディア {files_added} ファイル"
          f" ({zip_size_mb:.1f} MB) → {output_path}")

    # scp 転送
    if args.scp:
        print(f"\nscp 転送中: {output_path} → {args.scp} ...")
        result = subprocess.run(["scp", str(output_path), args.scp])
        if result.returncode == 0:
            print("scp 転送完了。")
        else:
            print("WARNING: scp が失敗しました。ZIP ファイルは手動で転送してください。")

    # インポートコマンド案内
    print("\n─── 他システムでのインポートコマンド ───")
    zip_basename = output_path.name
    print(f"  python scripts/transfer_detections.py import {zip_basename}")
    print(f"  python scripts/transfer_detections.py import {zip_basename} --apply")
    print("────────────────────────────────────────")


# ──────────────────────────────────────────────────────────────────────────────
# cmd_import
# ──────────────────────────────────────────────────────────────────────────────

def cmd_import(args: argparse.Namespace) -> None:
    source = Path(args.source).resolve()
    target_dir = Path(args.target).resolve()
    camera_map = _parse_camera_map(args.camera_map)
    apply = args.apply
    filter_cameras: set[str] | None = set(args.cameras) if args.cameras else None

    if not source.exists():
        raise SystemExit(f"ERROR: 取り込み元が見つかりません: {source}")

    mode = "apply" if apply else "dry-run"
    print(f"モード: {mode}")
    print(f"取り込み元: {source}")
    print(f"取り込み先: {target_dir}")
    if camera_map:
        print("カメラ名マッピング:")
        for old, new in camera_map.items():
            print(f"  {old} → {new}")
    print()

    tmp_dir_obj = None

    try:
        # ZIP 展開
        if source.suffix.lower() == ".zip":
            tmp_dir_obj = tempfile.TemporaryDirectory()
            extract_root = Path(tmp_dir_obj.name)
            print(f"ZIP を展開中 ...")
            with zipfile.ZipFile(source, "r") as zf:
                for name in zf.namelist():
                    if ".." in name or name.startswith("/"):
                        raise SystemExit(f"ERROR: 不正な ZIP エントリを検出: {name!r}")
                zf.extractall(str(extract_root))
            # meteo_transfer/ サブディレクトリを優先
            source_dir = extract_root / _ZIP_ROOT
            if not source_dir.is_dir():
                source_dir = extract_root
            # manifest 表示
            mf = source_dir / "manifest.json"
            if mf.exists():
                try:
                    m = json.loads(mf.read_text(encoding="utf-8"))
                    print(f"エクスポート情報: 作成日時={m.get('created_at')} "
                          f"ホスト={m.get('source_host')} "
                          f"レコード数={m.get('record_count')}")
                    print()
                except Exception:
                    pass
        else:
            source_dir = source

        # カメラディレクトリ探索
        cam_dirs = []
        for entry in sorted(source_dir.iterdir()):
            if not entry.is_dir() or entry.name in _SKIP_DIRS or entry.name.startswith("."):
                continue
            if not (entry / "detections.jsonl").exists():
                continue
            if filter_cameras and entry.name not in filter_cameras:
                continue
            cam_dirs.append(entry)

        if not cam_dirs:
            print("取り込み対象のカメラディレクトリが見つかりませんでした。")
            return

        if apply and not target_dir.exists():
            target_dir.mkdir(parents=True, exist_ok=True)

        totals = {"records_new": 0, "files_copied": 0, "sqlite_inserted": 0}

        for cam_dir in cam_dirs:
            src_cam = cam_dir.name
            tgt_cam = camera_map.get(src_cam, src_cam)
            display = f"{src_cam} → {tgt_cam}" if src_cam != tgt_cam else src_cam
            print(f"カメラ: {display}")

            result = _import_camera(cam_dir, target_dir, src_cam, tgt_cam, apply)

            print(f"  レコード: 合計={result['records_total']}"
                  f"  新規={result['records_new']}"
                  f"  スキップ(重複)={result['records_skipped']}")
            print(f"  ファイル: コピー={result['files_to_copy']}"
                  f"  スキップ(既存)={result['files_skipped']}")
            if apply:
                print(f"  SQLite 挿入: {result['sqlite_inserted']} 件")
            print()

            totals["records_new"] += result["records_new"]
            totals["files_copied"] += result["files_to_copy"]
            totals["sqlite_inserted"] += result.get("sqlite_inserted", 0)

        print("=" * 50)
        print(f"完了: モード={mode}  カメラ数={len(cam_dirs)}")
        print(f"  新規レコード:     {totals['records_new']} 件")
        print(f"  コピーファイル:   {totals['files_copied']} 個")
        if apply:
            print(f"  SQLite 挿入:     {totals['sqlite_inserted']} 件")
        else:
            print()
            print("  ※ドライランです。実際に取り込むには --apply を追加してください。")

    finally:
        if tmp_dir_obj is not None:
            tmp_dir_obj.cleanup()


# ──────────────────────────────────────────────────────────────────────────────
# CLI パーサー
# ──────────────────────────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="流星検出データ転送ツール（エクスポート＋インポート）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # ── export ─────────────────────────────────────────────────────────────
    ep = sub.add_parser("export", help="TUI で検出データを選択し ZIP を作成する")
    ep.add_argument(
        "--detections-dir", default="detections",
        help="detections/ ルートディレクトリ（デフォルト: detections）",
    )
    ep.add_argument(
        "--db", default=None,
        help="SQLite DB パス（省略時: detections/detections.db）",
    )
    ep.add_argument(
        "--output", "-o", default=None,
        help="出力 ZIP パス（省略時: ./transfer_YYYYMMDD_HHMMSS.zip）",
    )
    ep.add_argument(
        "--scp", default=None, metavar="USER@HOST:/PATH/",
        help="ZIP 作成後に scp で転送する宛先（例: pi@192.168.1.10:/home/pi/）",
    )
    ep.add_argument(
        "--camera", default=None,
        help="表示するカメラを1つに絞る（TUI 起動前にフィルター）",
    )

    # ── import ─────────────────────────────────────────────────────────────
    ip = sub.add_parser("import", help="ZIP またはディレクトリからデータを取り込む")
    ip.add_argument(
        "source",
        help="取り込み元の ZIP ファイルまたは detections/ ディレクトリのパス",
    )
    ip.add_argument(
        "--target", "-t", default="detections",
        help="取り込み先の detections/ ルートディレクトリ（デフォルト: detections）",
    )
    ip.add_argument(
        "--camera-map", "-m", action="append", default=[], metavar="OLD:NEW",
        help="カメラ名マッピング（例: old_name:new_name）。複数指定可。",
    )
    ip.add_argument(
        "--apply", action="store_true",
        help="実際に書き込む（指定しないとドライラン）",
    )
    ip.add_argument(
        "--cameras", nargs="+", metavar="CAMERA",
        help="取り込むカメラ名を絞り込む（ソース側のカメラ名で指定）",
    )

    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.command == "export":
        cmd_export(args)
    elif args.command == "import":
        cmd_import(args)


if __name__ == "__main__":
    main()
