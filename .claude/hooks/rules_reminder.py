# -*- coding: utf-8 -*-
"""PostToolUse hook: 触ったファイルに対応する .claude/rules/*.md を読むよう促す。

`.claude/rules/` は Claude Code の組み込み機能ではなく自動ロードされないので、
Read/Edit/Write が対象ファイルに触った時点で additionalContext に「読め」を注入する。
セッションごとに rules 1本につき1回だけ出す（同じ促しの連投を避ける）。

入力: stdin の hook JSON（session_id / tool_input.file_path / tool_response.filePath）
出力: stdout に hookSpecificOutput.additionalContext（該当なしなら何も出さない）
"""

import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
STATE_DIR = os.path.join(REPO, ".claude", ".rules_reminded")

# (判定関数, rules ファイル, 一言) — 上から順に全部評価する（複数該当あり）
RULES = [
    (
        lambda p, b: b == "ai.py",
        ["ai-strategies.md", "ai-parameters.md", "ai-humanstyle.md"],
        "AI戦略の設計と実測・全パラメータ値・フィルタ実装",
    ),
    (
        lambda p, b: b.startswith("tsumego") or "tsumego_solver" in p or "native/tsumego" in p,
        ["tsumego.md", "tsumego-parameters.md"],
        "詰碁の全体像と「やってはいけないこと」44項目・回帰手順／パラメータ値",
    ),
    (
        lambda p, b: b == "constants.py" or p.endswith("katrain/config.json"),
        ["ai-settings-gui.md"],
        "AI設定ウィジェットの追加手順",
    ),
    (lambda p, b: b == "base_katrain.py", ["base-katrain-config.md"], "JsonStore構造・起動時リセットパターン"),
    (lambda p, b: b.endswith(".log"), ["log-analysis.md"], "ログ解析のGrepパターン"),
]


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        return

    tool_input = data.get("tool_input") or {}
    tool_response = data.get("tool_response") or {}
    path = tool_response.get("filePath") or tool_input.get("file_path") or ""
    if not path:
        return
    norm = path.replace("\\", "/")
    base = os.path.basename(norm)

    hits = []
    for matches, files, why in RULES:
        try:
            if matches(norm, base):
                hits.append((files, why))
        except Exception:
            pass
    if not hits:
        return

    # セッションごとに1回だけ
    session = str(data.get("session_id") or "nosession").replace("/", "_").replace("\\", "_")
    marker = os.path.join(STATE_DIR, session)
    try:
        os.makedirs(STATE_DIR, exist_ok=True)
        seen = set(open(marker, encoding="utf-8").read().split()) if os.path.exists(marker) else set()
    except Exception:
        seen = set()

    lines, fresh = [], []
    for files, why in hits:
        new = [f for f in files if f not in seen]
        if not new:
            continue
        fresh.extend(new)
        lines.append("  - " + ", ".join("`.claude/rules/%s`" % f for f in new) + " — " + why)
    if not lines:
        return

    try:
        with open(marker, "a", encoding="utf-8") as fh:
            fh.write("\n".join(fresh) + "\n")
    except Exception:
        pass

    msg = (
        "[rules] `%s` に触りました。**着手する前に以下を Read すること**"
        "（`.claude/rules/` は自動ロードされません）:\n%s" % (base, "\n".join(lines))
    )
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": msg}}))


if __name__ == "__main__":
    main()
