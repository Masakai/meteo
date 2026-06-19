#!/usr/bin/env python3
"""検出コア（変更禁止ファイル）への Edit/Write を検知し、確認を挟む PreToolUse フック。

CLAUDE.md で「明示指示なく変更禁止」とされている検出アルゴリズムのコアファイルを
人間・エージェント問わず誤って書き換える事故を防ぐ。完全ブロックではなく
permissionDecision="ask" を返して確認を促す（明示指示があれば承認して進められる）。

stdin に PreToolUse の JSON が渡される。tool_input.file_path を見て判定する。
"""
import json
import os
import sys

# 変更禁止ファイル（CLAUDE.md の「変更禁止ファイル（検出コア）」と一致させる）
PROTECTED = {
    "meteor_detector_common.py",
    "meteor_detector_realtime.py",
    "astro_utils.py",
}


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        # 入力が壊れていてもフックでツールを止めない（フェイルオープン）
        sys.exit(0)

    tool_input = data.get("tool_input", {}) or {}
    file_path = tool_input.get("file_path", "") or ""
    if not file_path:
        sys.exit(0)

    basename = os.path.basename(file_path)
    if basename in PROTECTED:
        decision = {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "ask",
                "permissionDecisionReason": (
                    f"{basename} は検出アルゴリズムのコア（CLAUDE.md で変更禁止指定）です。"
                    "本当に変更してよいか確認してください。明示的な指示がある場合のみ承認してください。"
                ),
            }
        }
        print(json.dumps(decision, ensure_ascii=False))
        sys.exit(0)

    # 対象外は何も出力せず通過
    sys.exit(0)


if __name__ == "__main__":
    main()
