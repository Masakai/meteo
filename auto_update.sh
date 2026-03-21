#!/bin/bash
#
# 自動アップデートスクリプト
#
# Copyright (c) 2026 Masanori Sakai
# Licensed under the MIT License
#
# GitHub に新しいバージョンタグが存在する場合、pull して rebuild を実行する。
# cron から呼び出すことを想定しており、手動で ./meteor-docker.sh を実行した場合は通知しない。
#
# cron 設定例（1時間ごとに確認）:
#   0 * * * * /opt/meteo/auto_update.sh
#
# 通知を使う場合は NOTIFY_EMAIL を環境変数またはこのファイル内で設定する。
#
# 使い方:
#   ./auto_update.sh           # 通常実行（新バージョンがあれば更新）
#   ./auto_update.sh --check   # 確認のみ（更新しない）

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

LOG_FILE="${LOG_FILE:-$SCRIPT_DIR/auto_update.log}"
LOCK_FILE="/tmp/meteo_auto_update.lock"

# 通知設定（未設定なら通知しない）
# NOTIFY_EMAIL に宛先メールアドレスを設定すると更新結果を送信する
NOTIFY_EMAIL="${NOTIFY_EMAIL:-}"

# ---- ログ関数 ----------------------------------------------------------------

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG_FILE"
}

log_error() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] [ERROR] $*" | tee -a "$LOG_FILE" >&2
}

# ---- 通知関数 ----------------------------------------------------------------

notify() {
    local subject="$1"
    local body="$2"

    if [ -n "$NOTIFY_EMAIL" ]; then
        echo "$body" | mail -s "[Meteo] $subject" "$NOTIFY_EMAIL" \
            >> "$LOG_FILE" 2>&1 || log_error "メール通知に失敗しました"
    fi
}

# ---- バージョン比較（semver: vX.Y.Z） ----------------------------------------

# 引数1 が引数2 より新しければ 0、そうでなければ 1 を返す
is_newer() {
    local a="${1#v}"   # 先頭の "v" を除去
    local b="${2#v}"
    # sort -V で辞書的バージョン比較。異なる場合のみ newer とみなす
    [ "$a" != "$b" ] && [ "$(printf '%s\n%s' "$a" "$b" | sort -V | tail -1)" = "$a" ]
}

# ---- メイン ------------------------------------------------------------------

CHECK_ONLY=false
if [ "${1:-}" = "--check" ]; then
    CHECK_ONLY=true
fi

# 多重起動防止
exec 9>"$LOCK_FILE"
if ! flock -n 9; then
    log "別のプロセスが実行中のためスキップします"
    exit 0
fi

# git リポジトリ確認
if [ ! -d "$SCRIPT_DIR/.git" ]; then
    log_error "git リポジトリが見つかりません: $SCRIPT_DIR"
    exit 1
fi

# リモートの最新情報を取得（ローカルの作業ツリーは変更しない）
if ! git fetch --tags --quiet 2>> "$LOG_FILE"; then
    log_error "git fetch に失敗しました（ネットワーク確認）"
    exit 1
fi

# 現在のバージョンとリモートの最新タグを取得
CURRENT_TAG=$(git describe --tags --exact-match HEAD 2>/dev/null \
    || git describe --tags HEAD 2>/dev/null \
    || git rev-parse --short HEAD)
LATEST_TAG=$(git tag --sort=-version:refname | grep -E '^v[0-9]+\.[0-9]+\.[0-9]+$' | head -1)

if [ -z "$LATEST_TAG" ]; then
    log "リモートにバージョンタグが見つかりません"
    exit 0
fi

log "現在: $CURRENT_TAG  /  最新: $LATEST_TAG"

if ! is_newer "$LATEST_TAG" "$CURRENT_TAG"; then
    log "最新版です ($CURRENT_TAG)"
    exit 0
fi

log "新バージョンを検出しました: $CURRENT_TAG → $LATEST_TAG"

if $CHECK_ONLY; then
    log "--check モードのため更新をスキップします"
    exit 0
fi

# pull
log "git pull を実行します..."
if ! git pull --ff-only >> "$LOG_FILE" 2>&1; then
    log_error "git pull に失敗しました（ローカルに未コミットの変更がある可能性があります）"
    notify "自動更新失敗" "git pull に失敗しました。手動での確認が必要です。"
    exit 1
fi
log "git pull 完了"

# rebuild
log "rebuild を開始します..."
if ! "$SCRIPT_DIR/meteor-docker.sh" rebuild >> "$LOG_FILE" 2>&1; then
    log_error "rebuild に失敗しました"
    notify "自動更新失敗" "$LATEST_TAG の rebuild に失敗しました。手動での確認が必要です。"
    exit 1
fi
log "rebuild 完了"

log "自動更新が完了しました ($CURRENT_TAG → $LATEST_TAG)"
notify "自動更新完了" "$CURRENT_TAG → $LATEST_TAG に更新しました。"
