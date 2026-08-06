# 力戦派 悪手フィルタ閾値の GUI 化（盤面サイズ別・フェーズ別）設計

- 日付: 2026-08-06
- 対象: `katrain/core/ai.py` `FightingStrategy._generate_human()`
- 関連: `docs/superpowers/specs/2026-05-30-fighting-complexity-design.md`

## 目的

力戦派の `fighting_mode: human` / `complex` の悪手フィルタ閾値は現在ハードコードで、GUI から変更できない。
**閾値を引き下げて手を締める**（悪手を減らす）ことを主目的に、9路と 13/19路を独立したスライダーで
調整できるようにする。

引き上げではなく引き下げが目的である点は設計判断に効く（後述「安全弁を触らない理由」）。

## 現状

`_generate_human()` は盤面サイズ×フェーズの4値をハードコードで持つ（`ai.py:5642-5649`）。

| | 序盤 | 中盤以降 |
|---|---|---|
| 13/19路 | 2.8 | 5.6 |
| 9路 | 0.5 | 3.3 |

序盤境界は `ceil(0.14 × 盤面マス数)`（19路=51手目、9路=12手目）。この値が
`BAD_MOVE_THRESHOLD` として `human` の単一閾値フィルタと `complex` の無条件通過帯
（`_complexity_loss_filter` の `base_threshold`）の両方に使われている。

complex の上限側 `complexity_base_max_loss` / `complexity_max_loss` は GUI 調整可能だが
**盤面サイズ非依存**で、既定 5.6 / 10.0 は 13/19路を想定した値。9路で使うと base 3.3 に対して
5.6 まで開いてしまう（現状の漏れ）。

## スコープ

**適用範囲は力戦派の `human` / `complex` モードのみ。**

- 新キーは `ai:p:fighting` 配下に置く。`generate_ai_move` → `STRATEGY_REGISTRY[ai_mode](game, ai_settings)`
  で戦略ごとの設定セクションが渡されるため、他戦略からは参照されない（`ai.py:8575-8581`）。
- `classic` は悪手フィルタを持たない。`scoreloss` は従来どおり `fighting_max_loss` を使う（変更なし）。
- `ai:human`（HumanStyleStrategy）・攻城・狩猟・持碁・一致率追随は各自の閾値を持ち、影響を受けない。

## パラメータ（新規6キー）

| キー | 既定 | 適用 |
|---|---|---|
| `fighting_human_opening_max_loss` | 2.8 | 13/19路・序盤 |
| `fighting_human_max_loss` | 5.6 | 13/19路・中盤以降 |
| `fighting_human_opening_max_loss_9` | 0.5 | 9路・序盤 |
| `fighting_human_max_loss_9` | 3.3 | 9路・中盤以降 |
| `complexity_base_max_loss_9` | 3.3 | 9路・complex のゲート付き帯の上限 |
| `complexity_max_loss_9` | 6.0 | 9路・complex のリード連動上限 |

既存 `complexity_base_max_loss`（5.6）/ `complexity_max_loss`（10.0）は **13/19路専用**に意味を狭める。
既定値はすべて現行のハードコード値と一致するため、**既定のままなら挙動は完全に現状維持**。

`AI_OPTION_VALUES` の候補値は引き下げ方向に刻みを厚くし、現行既定値を必ず含める:

```python
"fighting_human_max_loss":           [1.0, 1.5, 2.0, 2.5, 3.0, 4.0, 5.6, 7.0, 9.0],
"fighting_human_opening_max_loss":   [0.5, 1.0, 1.5, 2.0, 2.8, 4.0],
"fighting_human_max_loss_9":         [0.5, 1.0, 1.5, 2.0, 2.5, 3.3, 4.0, 5.0],
"fighting_human_opening_max_loss_9": [0.2, 0.3, 0.5, 1.0, 1.5, 2.0],
"complexity_base_max_loss_9":        [2.0, 2.5, 3.3, 4.0, 5.0, 6.0],
"complexity_max_loss_9":             [4.0, 5.0, 6.0, 8.0, 10.0],
```

GUI 項目数は 17 → 23。`ai_options_grid_rows` が行数を自動拡張するので `GridLayoutException` は
発生しない（回帰: `tests/test_ai_options_grid.py`）。1行の縦幅は縮むが許容範囲とする。

## アーキテクチャ

変更は閾値の**決定**だけに閉じ、フィルタ本体（`_filter_moves` / `_complexity_loss_filter` /
`_complexity_relaxed_cap` / `_passes_complexity_gate`）は無変更。

### 新規ユニット（純関数・KataGo 非依存）

```python
def _fighting_loss_thresholds(settings, board_size, current_move):
    """力戦派 human/complex の損失閾値を盤面サイズ×フェーズで解決する。

    戻り値: (bad_move_threshold, complexity_base_max_loss, complexity_max_loss)
    """
```

- 盤面判定は現行と同じ `bx == 9 and by == 9`（それ以外は 13/19路扱い）。
- 序盤境界 `ceil(0.14 * bx * by)` はこの関数の内部で計算する。
- 依存は `settings`（dict）と `board_size`、`current_move` のみ＝単体テスト可能。

### 呼び出し側の変更（`_generate_human`）

1. `ai.py:5642-5649` のハードコード分岐を `_fighting_loss_thresholds()` の呼び出しに置換。
2. `ai.py:5729` `complexity_max_loss = self.settings.get("complexity_max_loss", 10.0)` と
   `ai.py:5731` `complexity_base_max_loss = self.settings.get("complexity_base_max_loss", BAD_MOVE_THRESHOLD)`
   を、上記関数が返した盤面別の値に置換。
3. それ以外は無変更。`_complexity_loss_filter` に渡る引数の**値**が変わるだけで、シグネチャも
   ロジックも触らない。

## 引き下げ時の挙動

### 段階的緩和フェイルセーフは維持する

`human` は通過0手のとき閾値を ×1.5 → ×2.0 → 絶対上限 9.0 と自動緩和し、それでも0手なら
最善スコア手を強制する（`ai.py:5755-5784`）。閾値を下げると候補ゼロの局面が増えるため
この経路の発動頻度は上がるが、**候補ゼロで戦略が破綻するのを防ぐ安全網**なので維持する。

倍率方式なので引き下げは緩和後の値にも波及する（例: 2.0 に下げれば緩和先は 3.0 / 4.0）。
発動は debug ログの `Filter relaxed:` で追跡できる。`_FILTER_ABSOLUTE_CAP`(9.0) も据え置き
（引き下げ用途では下から当たらない）。

### 安全弁（`_SAFETY_LOSS_THRESHOLD`）を触らない理由

`human` の安全弁は 4.0 固定（`ai.py:5819`）で、「最多探索手 v1 / 最高重み候補 v2 の loss が
4.0 以上なら最善スコア手を強制」する。閾値を 4.0 以下に**引き下げる**用途では、フィルタが先に
候補を切るため v2 は原理的に発動せず、安全弁は無害に空回りする（現行9路が既にこの関係）。

引き上げ用途なら安全弁が実効的な天井になるため連動が必要になるが、本設計のスコープ外。
将来引き上げる場合はここを再検討すること。

### complex のゲート構造は不変

`complex` の実効上限は `max(complexity_base_max_loss, relaxed_cap)` で、`relaxed_cap` は
`_complexity_relaxed_cap` が `current_lead < lead_threshold` のとき `base_threshold` を返す。
盤面別の値に差し替えても `base_threshold <= relaxed_cap` の不変条件は保たれる。

`complexity_base_max_loss` を `base_threshold` より小さく設定した場合はゲート付き帯が消えて
無条件通過帯だけになる（`max()` に吸収される）。異常ではないが、意図しない設定になりうるので
debug ログの `cap=... (base=...)` 行で実効値を確認できるようにする（既存ログで出力済み）。

## 検証方法

1. **純関数の単体テスト**（`tests/test_fighting_complexity.py` に追加）
   - 既定設定・19路・序盤/中盤以降で (2.8, 5.6) を返す
   - 既定設定・9路・序盤/中盤以降で (0.5, 3.3) を返す
   - 13路が 13/19路系の値を返す（9路系に落ちない）
   - 設定値を与えたときそれが優先される
   - complex 用の2値が盤面サイズで切り替わる
2. **既定値の回帰**: 設定を変えずに
   `python -m katrain_debug --sgf FILE --strategy fighting --batch` を実行し、変更前と
   平均損失・AI一致率が一致すること（3run 平均。単一 run は温度サンプリング分散に埋もれる）
3. **引き下げの効果**:
   `--settings fighting_human_max_loss=3.0` で平均損失が下がり AI 一致率が上がること
4. **GUI 表示確認**: 力戦派の設定画面に6スライダーが出て、値が保存・再読込されること

## 既知の限界

- 13路と19路は分離しない（現行の2クラス構造を踏襲）。13路で19路向けの値が使われる状態は変わらない。
- `fighting_max_loss` は `scoreloss` 専用のまま。名前が全モード共通に見える紛らわしさは残る
  （改名は設定移行を伴うので本スコープ外）。ドキュメントとi18n説明で明示する。
- `ai:human`（HumanStyleStrategy）の同種のハードコード閾値は対象外。

## 変更ファイル

- `katrain/core/ai.py` — `_fighting_loss_thresholds` 追加、`_generate_human` の3箇所置換
- `katrain/core/constants.py` — `AI_OPTION_VALUES` に6キー、`AI_OPTION_ORDER` に表示順
- `katrain/config.json` — `ai:p:fighting` に既定値6キー
- `C:\Users\iwaki\.katrain\config.json` — 同じ6キー（GUI は保存済みキーのみ表示する）
- `katrain/i18n/locales/{en,jp}/LC_MESSAGES/katrain.po` — 短ラベル＋`aihelp:ai:p:fighting` 本文に追記
  → `python tools/compile_mo.py` で `.mo` 再コンパイル
- `tests/test_fighting_complexity.py` — 純関数テスト追加
- `.claude/rules/ai-parameters.md` — 力戦派パラメータ表を更新
- `CLAUDE.md` — 力戦派の説明に反映
