# -*- coding: utf-8 -*-
"""PostToolUse hook: 触ったファイルに対応する .claude/rules/*.md を読むよう促す。

`.claude/rules/` の rules は `paths:` frontmatter で自動ロードされる想定だが、効かなかった実測（2026-08-21）があるので保険として、
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
    (
        lambda p, b: b in ("board_watch.py", "screen_marker.py", "screen_cursor.py", "move_difficulty.py"),
        ["board-watch.md"],
        "盤面監視の機能の全体像と設定キー",
    ),
    (
        lambda p, b: b.startswith("selfplay") and b.endswith(".py"),
        ["selfplay.md"],
        "自己対局ハーネスの全コマンド例と検査",
    ),
    (
        lambda p, b: b in ("engine.py", "warm_katago_sac.ps1"),
        ["environment.md"],
        "上流同期・エンジン切替・Smart App Control",
    ),
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
        "（既にコンテキストにあれば不要です）:\n%s" % (base, "\n".join(lines))
    )
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": msg}}))


if __name__ == "__main__":
    main()
