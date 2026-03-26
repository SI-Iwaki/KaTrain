---
description: HumanStyleStrategyに新しいAI設定を追加する手順（constants.pyやconfig.json編集時に参照）
paths:
  - "katrain/core/constants.py"
  - "katrain/config.json"
---

# HumanStyleStrategy AI設定追加ガイド

## 必須変更ファイル（3箇所）

| ファイル | 変更内容 | 理由 |
|------|----------|------|
| `katrain/core/constants.py` | `AI_OPTION_VALUES` に新キーを追加 | GUIのウィジェット種別を決定する |
| `katrain/config.json`（パッケージ） | `"ai:human"` にデフォルト値を追加 | 初回起動時のデフォルト設定 |
| `C:\Users\iwaki\.katrain\config.json`（ユーザー） | `"ai:human"` に同じキーを追加 | **GUIは保存済みキーのみ表示する** |

> **落とし穴**: `constants.py` だけ更新してもGUIに表示されない。両方の `config.json` にキーを追加しないとチェックボックス/スライダーが現れない。

## 設定の型とウィジェット対応

| `AI_OPTION_VALUES` の値 | GUIウィジェット |
|---|---|
| `"bool"` | チェックボックス |
| `range(...)` or `[...]` | スライダー |
| `[(value, label), ...]` | スライダー（ラベル付き） |

## ai.py での設定読み取り

```python
self.settings.get("your_new_setting", default_value)
```

## humanPolicyの罠（重要）

`modern_style=true` の高段者プロファイルは現代布石（3-3等）を好むため、星点（4-4）などの手に `humanPolicy=0` を返すことがある。
フィルタで `moves` リストに入らない手を**強制したい場合**は、`human_policy[idx]`が0でもMoveを直接生成するフォールバックが必要：

```python
star_moves = [(m, w) for m, w in moves if m.coords in target_stars]
if not star_moves:
    for (sx, sy) in target_stars:
        if self.game.board[sy][sx] == -1:
            idx = (board_size[1] - sy - 1) * board_size[0] + sx
            weight = human_policy[idx] if idx < len(human_policy) and human_policy[idx] > 0 else 1.0
            star_moves.append((Move((sx, sy), player=self.cn.next_player), weight))
```

## チェックリスト（新機能追加時）

- [ ] `katrain/core/constants.py` — `AI_OPTION_VALUES` に追加
- [ ] `katrain/core/ai.py` — `HumanStyleStrategy.generate_move()` にロジック追加
- [ ] `katrain/config.json` — `"ai:human"` にデフォルト値追加
- [ ] `C:\Users\iwaki\.katrain\config.json` — `"ai:human"` に同じキー追加
- [ ] CLAUDE.md を更新（新機能の説明、パラメータ等）
