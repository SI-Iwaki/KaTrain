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

**盤サイズ別の既定をこの `default_value` に書かない**: `self.settings` は config.json の `ai/<戦略>` セクション
そのもので、同梱 config.json（とそれを写したユーザー設定）は全キーを持つ＝**config にあるキーのコード既定は
決して使われない**。攻城・狩猟は `BOARD_PARAMS[13]` / `if bx <= 13:` に13路の既定を持ち、マニュアルと rules に
「既定（19路 / 13路）」と載せていたが、実装（2026-04-09）から 2026-09-18 まで一度も効いていなかった
（config の19路の値が常に勝つ）。盤ごとに値を変えたいなら**盤別キー**（`jigo_endgame_move_13` /
`fighting_human_max_loss_9` のような接尾辞。解決は `_fighting_loss_thresholds` のような純関数）を
両方の config.json に足す。逆に config に**無い**キーはコード既定がそのまま実効値になる
（例: `ai:hunt_diverge` の `hunt_focus_stddev`＝`hunt_default_focus_stddev`）。

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

- **項目欄は行の高さ固定のスクロールリスト**（2026-09-18）: `popups.kv` の `<ConfigAIPopup>` で `ScrollView` に `GridLayout(cols=2, row_default_height=34dp, row_force_default)` を入れてある＝**行数の上限は無い**（旧 `max_options`/`ai_options_grid_rows` は撤去）。固定枠に行を詰め込む方式は 20 項目超で 1 行が 16px まで潰れ、長いキー名が 2 行に折り返して上下の行に重なった。項目名（英語キー）は `AIOptionNameLabel` が列幅に 1 行で収まるまで文字を縮める。スクロールは**ホイールとスクロールバーだけ**（`scroll_type: ['bars']`＝本文ドラッグでスクロールさせるとスライダー操作が 250ms 遅れる）。スクロールが要る戦略では、項目欄の上のホイールはスライダーの値ではなくリストのスクロールになる。回帰テスト: `tests/test_ai_options_grid.py`
- **説明欄＝概要＋【各項目】を自動で組み立てる**（`katrain/gui/ai_help.py`）: `aihelp:<strategy>` は**戦略の概要だけ**を書き、各項目の解説は `aiopt:` の訳文から画面と同じ順（`ai_option_display_order`）で「■ 英語キー（日本語名）［既定 X］: 解説」と並ぶ（既定は同梱 config.json から自動）。画面の項目名が英語キーのままなので、**解説側に英語キーを必ず出す**のが目的（ユーザー要望 2026-09-18）。調整の目安などを一覧の後ろに置きたいときは `aihelptips:<strategy>`。説明欄はクリックで拡大表示（`open_help_popup`）
- **日本語の説明文は `cjk_wrap_friendly` を通す**: Kivy は半角スペースでしか改行できず、スペースの後ろの長い日本語を丸ごと次の行へ送って行が幅の途中で切れる（実測 500px 幅で 125px・96px の行）。英単語どうしの間以外の半角スペースを NBSP にして文字単位で折り返させる
- **i18nコンパイル必須**: `.po` ファイル編集後は `python tools/compile_mo.py` で `.mo` を再コンパイルしないと翻訳が反映されない（戦略名が `ai:xxx` のまま表示される）

## チェックリスト（新機能追加時）

- [ ] `katrain/core/constants.py` — `AI_OPTION_VALUES` に追加
- [ ] `katrain/core/ai.py` — 対象Strategyクラスにロジック追加
- [ ] `katrain/config.json` — 対象戦略セクションにデフォルト値追加
- [ ] `C:\Users\iwaki\.katrain\config.json` — 同じキー追加（GUIに表示するため）
- [ ] `katrain/i18n/locales/jp/LC_MESSAGES/katrain.po` — `msgid "aiopt:<param_name>"` に「1 行目＝日本語名、2 行目以降＝解説（意味と上げる／下げるとどうなるか）」を足す（**無いと `tests/test_ai_help_text.py` が落ちる**）。同じキーでも戦略で意味が違うときは `aiopt:<strategy>/<key>`、難解系（enigma9/13/19 と＋版）は共通文面 `aiopt:enigma*_<suffix>`、韜晦系（veil9/13/19）は `aiopt:veil*_<suffix>`（文中の `{p}` が `enigma13plus` / `veil13` 等の接頭辞に置き換わる）。`aihelp:<strategy>` には項目の解説を書かない（概要だけ・二重になる）。※旧来の短ラベル `msgid "<param_name>"` は画面に出ていない
- [ ] `python tools/compile_mo.py` で `.mo` 再コンパイル
- [ ] CLAUDE.md を更新（新機能の説明、パラメータ等）
- [ ] 起動時リセットが必要な場合は `base_katrain.py` の `_load_config` 末尾に追加

## チェックリスト（新戦略追加時）

上記に加えて:
- [ ] `katrain/core/constants.py` — `AI_XXX` 定数追加、`AI_STRATEGIES`・`AI_STRATEGIES_RECOMMENDED_ORDER`・`AI_STRENGTH` に登録
- [ ] `katrain/core/ai.py` — import に `AI_XXX` 追加、`@register_strategy(AI_XXX)` クラス新設
- [ ] `katrain/i18n/locales/en/LC_MESSAGES/katrain.po` — `ai:xxx` / `aihelp:xxx` 追加
- [ ] `katrain/i18n/locales/jp/LC_MESSAGES/katrain.po` — 同上（日本語）
- [ ] `python tools/compile_mo.py` で `.mo` を再コンパイル
- [ ] `aihelp:xxx`（概要）は項目の解説を含めず短く書く（項目は `aiopt:` から自動で並ぶ）
