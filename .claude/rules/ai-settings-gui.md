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

## 現在の `ai:human` 設定項目一覧

| キー | 型 | デフォルト | 備考 |
|------|-----|-----------|------|
| `human_kyu_rank` | float | -8.0 | humanSLProfile段位（-9=9段） |
| `modern_style` | bool | true | 現代布石プロファイル |
| `force_star_opening` | bool | true | 序盤に星点を優先 |
| `first_impression_deviation` | bool | false | 全盤面・中盤以降で第一感ぶれ（9路=上限1.5目、他=2.0目） |
| `first_impression_deviation_opening` | bool | false | deviation ON時、序盤でも第一感ぶれを適用 |
| `first_impression_green_blend` | bool | false | deviation ON時、緑の第一感と偏差手をgreen_ratioで選択 |
| `green_blend_green_ratio` | float | 0.5 | green_blend時の緑手確率（0.4=dev寄り/0.5=均等/0.6=緑寄り、スライダー） |

## GUI設定画面の制約

- **GridLayout行数上限**: `katrain/gui/popups.py` の `ConfigAIPopup.max_options = 15` が1戦略あたりの最大設定項目数。超過すると `GridLayoutException: Too many children in GridLayout` が発生する。項目数が多い場合は独立した戦略（`ai:新名前`）に分離すること
- **i18nコンパイル必須**: `.po` ファイル編集後は `python tools/compile_mo.py` で `.mo` を再コンパイルしないと翻訳が反映されない（戦略名が `ai:xxx` のまま表示される）

## チェックリスト（新機能追加時）

- [ ] `katrain/core/constants.py` — `AI_OPTION_VALUES` に追加
- [ ] `katrain/core/ai.py` — 対象Strategyクラスにロジック追加
- [ ] `katrain/config.json` — 対象戦略セクションにデフォルト値追加
- [ ] `C:\Users\iwaki\.katrain\config.json` — 同じキー追加（GUIに表示するため）
- [ ] CLAUDE.md を更新（新機能の説明、パラメータ等）
- [ ] 起動時リセットが必要な場合は `base_katrain.py` の `_load_config` 末尾に追加

## チェックリスト（新戦略追加時）

上記に加えて:
- [ ] `katrain/core/constants.py` — `AI_XXX` 定数追加、`AI_STRATEGIES`・`AI_STRATEGIES_RECOMMENDED_ORDER`・`AI_STRENGTH` に登録
- [ ] `katrain/core/ai.py` — import に `AI_XXX` 追加、`@register_strategy(AI_XXX)` クラス新設
- [ ] `katrain/i18n/locales/en/LC_MESSAGES/katrain.po` — `ai:xxx` / `aihelp:xxx` 追加
- [ ] `katrain/i18n/locales/jp/LC_MESSAGES/katrain.po` — 同上（日本語）
- [ ] `python tools/compile_mo.py` で `.mo` を再コンパイル
- [ ] 設定項目数が `max_options`（現在15）を超えないか確認
