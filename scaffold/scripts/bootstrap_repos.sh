#!/usr/bin/env bash
set -euo pipefail

if [ $# -ne 1 ]; then
  echo "Usage: $0 <target-dir>"
  echo "Example: $0 /Users/sakaimasanori/Dropbox"
  exit 1
fi

TARGET_DIR="$1"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SCAFFOLD_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

CORE_DIR="$TARGET_DIR/meteo-core"
BOX_DIR="$TARGET_DIR/meteo-box"

mkdir -p "$CORE_DIR" "$BOX_DIR"

cp -R "$SCAFFOLD_ROOT/meteo-core/." "$CORE_DIR/"
cp -R "$SCAFFOLD_ROOT/meteo-box/." "$BOX_DIR/"

if [ ! -d "$CORE_DIR/.git" ]; then
  git -C "$CORE_DIR" init >/dev/null
fi

if [ ! -d "$BOX_DIR/.git" ]; then
  git -C "$BOX_DIR" init >/dev/null
fi

cat <<MSG
Created repositories:
- $CORE_DIR
- $BOX_DIR

Next steps:
1) Copy core modules from meteo into $CORE_DIR/src/meteo_core
2) Add CI and release tags for meteo-core
3) Install meteo-core in meteo-box (pip install -e or pinned release)
MSG
