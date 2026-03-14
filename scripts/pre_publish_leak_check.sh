#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

echo "== 1) push対象の確認 =="
git status --short
echo

echo "== 2) 実際にコミットされる差分だけ確認 =="
git diff --cached || true
echo

echo "== 3) 追跡ファイル中の機微文字列検査 =="
SENSITIVE_REGEX='([A-Za-z]{20,}|AKIA[0-9A-Z]{16}|ghp_[A-Za-z0-9]{30,}|glpat-[A-Za-z0-9_-]{20,}|xox[baprs]-[A-Za-z0-9-]{10,}|rtsp://[^[:space:]]+:[^[:space:]@]+@|PRIVATE KEY|BEGIN (RSA|EC|OPENSSH) PRIVATE KEY)'
LEAK_HITS="$(git ls-files | xargs grep -nE "$SENSITIVE_REGEX" 2>/dev/null || true)"
if [ -n "$LEAK_HITS" ]; then
  echo "$LEAK_HITS"
  echo
  echo "[NG] 機微情報の疑いがある行が見つかりました。"
  LEAK_FOUND=1
else
  echo "ヒットなし"
  LEAK_FOUND=0
fi
echo

echo "== 4) .gitignoreで除外されるべきファイル確認 =="
IGNORE_CHECK="$(git check-ignore -v streamers .env scaffold/ masks/camera1_mask.png masks/camera2_mask.png masks/camera3_mask.png || true)"
if [ -n "$IGNORE_CHECK" ]; then
  echo "$IGNORE_CHECK"
else
  echo "対象のignore判定はありません（必要なら .gitignore を確認）"
fi
echo

echo "== 5) 大きすぎる追跡ファイル確認(5MB超) =="
LARGE_FILES="$(git ls-files | xargs -I{} sh -c 'test -f "{}" && [ $(wc -c < "{}") -gt 5242880 ] && echo "{}"' || true)"
if [ -n "$LARGE_FILES" ]; then
  echo "$LARGE_FILES"
  echo
  echo "[WARN] 5MB超の追跡ファイルがあります。"
else
  echo "該当なし"
fi
echo

echo "== 6) 最終: push対象コミット一覧 =="
git log --oneline --decorate -n 10
echo

if [ "$LEAK_FOUND" -ne 0 ]; then
  echo "公開前チェック結果: NG"
  exit 1
fi

echo "公開前チェック結果: OK"
