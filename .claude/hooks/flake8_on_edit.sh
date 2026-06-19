#!/usr/bin/env bash
# Python ファイルを Edit/Write した直後に flake8 を実行する PostToolUse フック。
# pre-commit / CI より早く、編集のたびにエラーを表面化させて手戻りを減らす。
# .flake8 設定（プロジェクトルート）を自動参照する。
#
# stdin に PostToolUse の JSON が渡される。tool_input.file_path / tool_response.filePath
# から対象ファイルを取り出し、.py のみ flake8 にかける。
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
FLAKE8="$REPO_DIR/.venv/bin/flake8"

# 対象ファイルパスを取得（tool_response 優先、なければ tool_input）
file="$(jq -r '.tool_response.filePath // .tool_input.file_path // empty' 2>/dev/null || true)"

# .py 以外、空、flake8 未導入なら静かに終了（フックでブロックしない）
[ -z "$file" ] && exit 0
case "$file" in
    *.py) : ;;
    *) exit 0 ;;
esac
[ -x "$FLAKE8" ] || exit 0
[ -f "$file" ] || exit 0

# flake8 実行。エラーがあれば内容を Claude へフィードバック（PostToolUse の additionalContext）
out="$("$FLAKE8" "$file" 2>&1 || true)"
if [ -n "$out" ]; then
    # JSON で additionalContext を返し、エラーを次の手番に伝える
    jq -nc --arg ctx "flake8 で指摘あり ($file):"$'\n'"$out" \
        '{hookSpecificOutput: {hookEventName: "PostToolUse", additionalContext: $ctx}}'
fi
exit 0
