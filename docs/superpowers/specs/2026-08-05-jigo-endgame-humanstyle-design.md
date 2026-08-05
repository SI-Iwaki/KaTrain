# 持碁モード ヨセ段階の HumanStyle 9段委譲 設計仕様

- 日付: 2026-08-05
- 対象: `katrain/core/ai.py`（`JigoStrategy` / `Jigo9Strategy`）, `katrain/core/constants.py`, 設定ファイル, i18n, テスト
- 関連: [持碁戦略パラメータ](../../../.claude/rules/ai-parameters.md#持碁戦略jigostrategy), [jigo-deception phase 設計](2026-05-16-jigo-deception-phase-design.md), [持碁（9路）専用モード](2026-06-04-jigo-9x9-dedicated-mode-design.md)

## 背景・目的

持碁モード（`ai:jigo` / `ai:jigo9`）は目差を target 範囲に収めるため、リードが target を超えている間は「target 最接近手」を選ぶ。序盤・中盤ではこれが自然な緩手として機能するが、**終盤のヨセでは手抜きが露骨に見える**。ヨセは1手ごとの目数がほぼ確定していて手順もほぼ一本道なので、大きい場所を放置して小さい場所に打つ選択は人間の対局相手から見て明らかに不自然で、「AIが手加減している」と気づかれる。

### ゴール

終盤のヨセ段階に入ったら target 追従をやめ、HumanStyle 9段（`rank_9d`）としてそのまま打つオプションを追加する。設定画面のチェックボックスで ON/OFF し、切替手数はスライダーで調整できる。

## 非ゴール（YAGNI）

- チェックボックス OFF 時の挙動変更（既存の持碁挙動は完全に現状維持）
- ownership ベースのヨセ自動判定（閾値の校正が GUI 実戦でしかできず、実装コストとリスクに見合わない。手数スライダーで代替する）
- ヨセ中の目差監視・jigo への復帰（下記「sticky」参照）
- HumanStyle 側の追加オプション（`first_impression_*` / `force_star_opening` 等）の受け渡し。委譲するのは素の9段のみ

## 設計判断（ブレインストーミングでの確定事項）

| 論点 | 決定 | 理由 |
|---|---|---|
| ヨセ判定 | **手数スライダー** | ヨセ開始は碁ごとに前後するので実戦で合わせ込みたい。`hunt_endgame_move` の前例あり |
| ヨセ中の target | **完全無視・純粋の9段** | 手抜きをゼロにすることが目的。鋭手除外を残すと「大きい場所を避ける」挙動が残りバレるリスクが消えない |
| 適用範囲 | **`ai:jigo` と `ai:jigo9` の両方** | `Jigo9Strategy` は `JigoStrategy` を継承しているので実装は共通、GUI 登録と既定値だけ盤サイズ別 |
| 劣勢時の扱い | **target に戻るまで jigo を続ける** | `lead < target_score` のとき jigo は「target 最接近手」＝実質最善手を打つので手抜きは起きない。deception の挽回（phase3）を取りこぼさずに完了できる |

## コンポーネント設計

### 1. 設定キー（新規4つ）

| セクション | キー | ウィジェット | 既定値 |
|---|---|---|---|
| `ai:jigo`, `ai:jigo9` | `jigo_endgame_humanstyle` | チェックボックス（`"bool"`） | `false` |
| `ai:jigo` | `jigo_endgame_move` | スライダー `range(120, 210, 10)` | `150`（19路用） |
| `ai:jigo` | `jigo_endgame_move_13` | スライダー `range(55, 95, 5)` | `85`（13路用） |
| `ai:jigo9` | `jigo9_endgame_move` | スライダー `[22, 26, 30, 34, 38]` | `30` |

チェックボックスのキーは**両モードで共通**（`jigo_endgame_humanstyle`）にして判定を1本化する。手数スライダーは既存の盤サイズ別キー分割の規約（`jigo_deception_13_*` / `jigo9_*`）に合わせて分ける。

既定手数は 19路150 / 13路85 / 9路30。19路と9路は **deception phase3 の開始手数と同じ**にしてあり、deception の ON/OFF で切替タイミングが動かないので挙動が予測しやすい。13路だけは phase3 開始が 83 でスライダーの刻み（5刻み）に乗らないため、既存の共通規約 `ceil(0.5 × 169) = 85`（他戦略のヨセ閾値と同じ式）を採る。83 と 85 の差は2手なので実質同じ。

`AI_OPTION_ORDER` は既存の持碁ブロックの末尾に続ける:

```
jigo_endgame_humanstyle: 17
jigo_endgame_move:       18   # ai:jigo のみ
jigo_endgame_move_13:    19   # ai:jigo のみ
jigo9_endgame_move:      18   # ai:jigo9 のみ（別セクションなので値の重複は問題ない）
```

### 2. 判定（純関数）

`ai.py` の JigoStrategy pure-function helpers ブロックに追加する。

```python
def _jigo_endgame_threshold(board_size, settings):
    """盤サイズ → ヨセ切替手数。未知の盤は既存共通規約 ceil(0.5 × 盤面マス数)。"""

def _jigo_endgame_handoff(board_size, move_num, last_lead, target_score, settings, sticky=False):
    """HumanStyle 9段へ委譲すべきか。

    True の条件:
        settings["jigo_endgame_humanstyle"] が True、かつ
        （sticky が True） または
        （move_num >= 閾値 かつ last_lead is not None かつ last_lead >= target_score）
    """
```

- `board_size` は既存呼び出し規約に合わせ `max(self.game.board_size)`。19/13/9 以外は `math.ceil(0.5 * bx * by)`（他戦略と同じ共通規約）にフォールバックする。
- **比較対象はユーザー設定の `target_score`**（`eff_target` ではない）。deception の phase1/2 は `eff_target` が負なので、`eff_target` と比べると「劣勢に留まる設計どおりの状態」を到達とみなして即委譲してしまう。
- `last_lead` は `game._jigo_last_current_lead`（前手のキャッシュ。`jigo_dynamic_rank` が既に使っている値）。Stage2 を撃つ前に判定して無駄なクエリを避けるので、**目差の判定には1手ラグがある**。ヨセの1手ぶんなので実害なしと判断。
- `last_lead is None`（初手・キャッシュなし）は False。

### 3. sticky（一度委譲したら戻らない）

`game._jigo_endgame_handoff`（bool、初期値なし＝`getattr` で False）に立てる。ヨセ中に目差が target を割っても jigo には戻らない。

理由は2つ。(a) 手番ごとに jigo と9段を往復すると挙動が振れて、かえって不自然に見える。(b) 劣勢側の jigo は結局ほぼ最善手なので、戻す実利がない。

なお委譲後は `_jigo_last_current_lead` が更新されなくなる（Stage2 を撃たないため）ので、sticky でなければどのみち古い値で判定し続けることになる。sticky はその暗黙の挙動を明示化したもの。

### 4. 委譲

`JigoStrategy.generate_move()` の**設定読み込み直後・Stage1 発行前**に判定を置く。成立したら:

```python
delegate = HumanStyleStrategy(self.game, {"human_kyu_rank": -8, "modern_style": True})
move, thoughts = delegate.generate_move()
return move, f"[Jigo→9d yose] {thoughts}"
```

- `human_kyu_rank=-8` + `modern_style=True` → `HumanStyleStrategy` 内で `human_profile = "rank_9d"`。Jigo の Stage1 既定（`rank_9d`）と一致する。
- `first_impression_*` / `force_star_opening` は渡さない＝すべて `False` 相当の素の9段。
- `Jigo9Strategy` は `generate_move` を継承しているので自動的に同じ経路に乗る。
- `last_decision_info` は委譲前に `{"rank_used": "rank_9d", "score_lead": last_lead, "endgame_handoff": True, "filter_relaxed": False, "score_lead_biased": False, "selected_hp": None, "selected_score": None}` で埋める（`katrain_debug/batch_eval.py:160` が `getattr(strategy, "last_decision_info", None)` で参照するため）。`endgame_handoff` は新キーで、既存の読み手は無視する。

### 5. ログ

```
[JigoStrategy] Endgame handoff: move=152 >= thr=150, lead=2.30 >= target=0.50 → HumanStyle rank_9d
[JigoStrategy] Endgame handoff: sticky (already handed off) → HumanStyle rank_9d
[JigoStrategy] Endgame pending: move=152 >= thr=150 but lead=-1.20 < target=0.50
```

`OUTPUT_DEBUG`。`--batch` では per-move ログが抑制されるので、発火確認は `--move N` の個別実行か GUI 実戦ログで行う。

### 6. 付随作業

- `katrain/core/constants.py` — `AI_OPTION_VALUES` に4キー、`AI_OPTION_ORDER` に順序
- `katrain/config.json`（パッケージ） — `ai:jigo` に3キー、`ai:jigo9` に2キー
- `C:\Users\iwaki\.katrain\config.json`（ユーザー） — 同じキー（**メインセッションで直接 Edit する。サブエージェントに委任しない**）
- `katrain/i18n/locales/{en,jp}/LC_MESSAGES/katrain.po` — 4キーの短ラベル＋ `aihelp:ai:jigo` / `aihelp:ai:jigo9` 本文に動作説明を追記 → `python tools/compile_mo.py`
- `.claude/rules/ai-parameters.md` の持碁テーブル、`CLAUDE.md` の概要

## テスト

`tests/test_jigo_endgame_handoff.py`（Kivy 不要の純関数テスト）:

- 閾値の境界: `move_num` が閾値−1 で False、閾値ちょうどで True
- チェックボックス OFF なら常に False（他の条件がすべて成立していても）
- `last_lead is None` で False
- `last_lead < target_score` で False、`== target_score` で True
- sticky=True なら手数・lead に関係なく True
- 盤サイズ別キー選択: 19→`jigo_endgame_move` / 13→`jigo_endgame_move_13` / 9→`jigo9_endgame_move`
- 未知の盤サイズ（例: 15路）で `ceil(0.5 × 15 × 15) = 113` にフォールバック

既存回帰: `pytest --ignore=tests/test_ai.py`（humanSL モデル非依存の範囲）。

## 検証

GUI 実戦（19路・13路・9路それぞれ1局）で、ログの `Endgame handoff` 行が想定手数に出ること、および委譲後の手が `[HumanStyleStrategy]` の経路を通っていることを確認する。deception ON での確認も1局行い、phase3 の挽回が完了してから委譲されることを見る。

`katrain_debug --batch` は trajectory 形成型の機能を測れない（[既知の制約](../../../CLAUDE.md)）ので、目差の収束評価には使わない。

## 承知しておく副作用・限界

- **最終的な目差は target を超えて広がりうる**。相手が弱いとヨセで素直に稼ぐため。「バレないこと」を優先した設計上の帰結で、目差収束とのトレードオフ。
- 目差判定は1手ラグ（前手のキャッシュ）。ヨセの1手ぶんの誤差。
- sticky なので、ヨセに入った後に相手が大石を殺すような大逆転が起きても jigo には戻らない。
