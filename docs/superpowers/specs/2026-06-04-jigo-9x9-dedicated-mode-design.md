# 持碁（9路）専用モード 設計仕様

- 日付: 2026-06-04
- 対象: `katrain/core/ai.py`（`JigoStrategy` / 新 `Jigo9Strategy`）, `katrain/core/constants.py`, 設定ファイル, i18n, デバッグCLI
- 関連: [既存 JigoStrategy](../../../.claude/rules/ai-parameters.md#持碁戦略jigostrategy), [jigo-deception phase 設計](2026-05-16-jigo-deception-phase-design.md)

## 背景・目的

現在の `JigoStrategy`（`ai:jigo`）は19/13/9路すべてに対応し、GUI設定が17項目ある。その多くが盤面固有（`jigo_force_sanrensei`=19路専用、`jigo_deception_13_*`×4=13路専用スライダー）で、9路ユーザーには無関係な項目が混在し**紛らわしい**。

加えて、deception（中盤に僅差で負けて相手を油断させる）機構の9路タイミングが**ハードコードで調整不可**:

```
JIGO_DECEPTION_PHASE_TABLE[9] = [(8,"phase1"),(20,"phase2"),(38,"phase3")]
JIGO_DECEPTION_TARGETS[(9,"phase1")] = (-1.5,-0.5)
JIGO_DECEPTION_TARGETS[(9,"phase2")] = (-0.5, 0.0)
```

phase3（ユーザー設定値に復帰＝挽回開始）が38手目固定だが、9路は40〜60手で終局するため**挽回が間に合わない**ケースがある。13路には5つの調整スライダーがあるが9路には無い。

### ゴール
1. 9路専用の独立戦略 `ai:jigo9`（持碁（9路））を新規追加し、9路に関係する設定だけを表示する
2. 既存 `ai:jigo` から9路サポートを外し、19/13路専用に整理する
3. 9路 deception を13路同様の5スライダーで調整可能にし、phase3開始の前倒しで挽回を間に合わせられるようにする

## 非ゴール（YAGNI）

- 既存 `ai:jigo` の19/13路挙動の変更（9路除去以外は現状維持）
- 9路への `jigo_dynamic_rank` / `jigo_large_lead_*` / `jigo_equivalent_epsilon` / `human_profile` 選択の提供（いったん不要。将来9路特有の調整項目が必要になった時点で追加）
- batch評価による deception 効果検証（trajectory形成型のためGUI実戦のみで検証可能）

## アーキテクチャ方針

**承認済み: 案A（`JigoStrategy` を継承し deception スライダー読み取りを汎用化）**

```python
@register_strategy(AI_JIGO_9)
class Jigo9Strategy(JigoStrategy):
    FORCED_SETTINGS = {
        "jigo_equivalent_epsilon": 0.0,
        "jigo_large_lead_delta": float("inf"),  # large-lead 緩和を無効化（実効 max_loss を常に一定に）
        "jigo_dynamic_rank": False,
        "human_profile": "rank_9d",
    }
```

`generate_move` は親の実装をほぼ流用。deception ブロックの `board_size==13` 分岐に並列で `board_size==9` 分岐を追加する。アルゴリズム本体を1箇所に保ち、差分を最小化する。

却下案:
- 案B（コア処理を共有ヘルパーに抽出）: 既存 jigo への影響が大きくリスク増
- 案C（generate_move 完全複製）: 発散リスク高

## コンポーネント設計

### 1. 戦略登録（`constants.py`）

- 定数: `AI_JIGO_9 = "ai:jigo9"`
- `AI_STRATEGIES_ENGINE` に追加（既存 `AI_JIGO` と同じエンジン系）
- `AI_STRATEGIES_RECOMMENDED_ORDER` の `AI_JIGO` 直後に挿入
- `AI_STRENGTH[AI_JIGO_9] = float("nan")`

### 2. 設定項目（計11項目）

**コア6項目（既存キーを流用）**

| キー | ウィジェット | 9路デフォルト | 備考 |
|---|---|---|---|
| `target_score` | 既存スライダー流用 | 0.5 | 狙う目差 |
| `target_score_max` | [5,10,15] | **5.0** | 9路は10目で実質勝勢のため5.0既定 |
| `max_loss_per_move` | [3.0,**3.3**,4.0,5.6,7.0] | **3.3** | 9路 HumanStyle NORMAL=3.3 に合わせる。共有リストに3.3を追加（既存jigoへ無害な選択肢追加） |
| `min_human_policy` | 既存（(0.005..0.05)） | 0.02 | humanPolicy 最低閾値 |
| `jigo_mode` | natural/maintain | natural | |
| `jigo_deception` | bool | false | deception 有効化 |

**deception スライダー5項目（新キー・9路専用レンジ）**

| キー | 選択肢 | デフォルト | 備考 |
|---|---|---|---|
| `jigo9_phase1_start` | [4,6,8,10] | 6 | phase0→1 境界手数 |
| `jigo9_phase2_start` | [12,16,20,24] | 16 | phase1→2 境界手数 |
| `jigo9_phase3_start` | [26,30,34,38] | **30** | phase2→3（挽回開始）。**現状38→30に前倒し**が既定 |
| `jigo9_phase1_target` | [-1.0,-1.5,-2.0,-2.5] | -1.5 | eff_target。target_max = target+1.0 を自動算出 |
| `jigo9_phase2_target` | [-0.5,-1.0,-1.5] | -0.5 | 同上 |

`AI_OPTION_ORDER` に `target_score`(0) → ... → `jigo_deception`(5) → `jigo9_phase1_start`(6) ... `jigo9_phase2_target`(10) の順で登録。

**外す4機能の扱い**: GUI非表示・config非格納・コードで確実に無効化、の3点を `FORCED_SETTINGS` で両立する（後述）。

### 3. deception スライダー読み取り（`ai.py`・13路機構の転用）

`generate_move` の deception ブロックに `board_size==9` 分岐を追加:

```python
if board_size_for_phase == 9:
    phase_table_override = [
        (self.settings.get("jigo9_phase1_start", 6),  "phase1"),
        (self.settings.get("jigo9_phase2_start", 16), "phase2"),
        (self.settings.get("jigo9_phase3_start", 30), "phase3"),
    ]
    p1 = self.settings.get("jigo9_phase1_target", -1.5)
    p2 = self.settings.get("jigo9_phase2_target", -0.5)
    target_overrides = {"phase1": (p1, p1 + 1.0), "phase2": (p2, p2 + 1.0)}
```

- `_jigo_resolve_phase` は既に `phase_table_override` / `target_overrides` を受け付けるため**改修不要**。安全弁（±5目で phase3 強制ジャンプ）もそのまま機能
- eff_target/eff_target_max 解決: `_jigo_resolve_13path_overrides` を `_jigo_resolve_path_overrides(phase, default_target, default_target_max, settings, key_prefix)` に**汎用化**（`key_prefix` で `"jigo9"` / `"jigo_deception_13"` を切替）。13路呼び出しは `key_prefix="jigo_deception_13"` に置換
- `generate_move` の eff_target 解決部を `==13` / `==9` / else（テーブル）の3分岐に整理

**consequence（仕様変更点）**: 9路 phase2 の target_max が現状 `(-0.5, 0.0)`（幅0.5）から、スライダー機構の `target+1.0` 規約に従い `(-0.5, 0.5)`（幅1.0）になる。13路と同じ幅規約に統一する意図的変更。挙動微変だが許容範囲。

### 4. 無効化機構（`_jigo_get` + `FORCED_SETTINGS`）

継承で `generate_move` を共有するため、ai:jigo9 の config からキーを省くだけでは**コード側デフォルトに落ちる**（例: `jigo_equivalent_epsilon` を省略すると 0.5 が効き 0.0 にならない）。かつ GUI に出さないには config にキーを置けない（GUI は config 内かつ `AI_OPTION_VALUES` 登録済みキーを表示する）。

そこで:

- `JigoStrategy` にクラス属性 `FORCED_SETTINGS = {}`（基底は空）と、ヘルパー `_jigo_get(self, key, default)` を新設:
  ```python
  def _jigo_get(self, key, default):
      if key in self.FORCED_SETTINGS:
          return self.FORCED_SETTINGS[key]
      return self.settings.get(key, default)
  ```
- `generate_move` 内の対象 read（`jigo_equivalent_epsilon`, `jigo_large_lead_delta`, `jigo_dynamic_rank`, `human_profile`）を `self._jigo_get(...)` 経由に変更
- `Jigo9Strategy.FORCED_SETTINGS` で上記4キーを無効化値に固定
- 効果: GUI 非表示・config 非格納・コードで確実に無効化、の3点を両立。基底 `JigoStrategy`（19/13路）は `FORCED_SETTINGS` が空のため挙動不変

### 5. 既存 JigoStrategy からの9路除去

「9路を外す」を以下で実施:

- `JIGO_DECEPTION_PHASE_TABLE` から `9:` エントリ削除
- `JIGO_DECEPTION_TARGETS` から `(9, *)` 4エントリ削除
- `JIGO_LARGE_LEAD_9X9_CAP` 定数を削除
- `_jigo_compute_effective_max_loss` の `board_size <= 9` キャップ分岐を削除

**注記（継承の帰結）**: deception の `==9` 分岐は共有 `generate_move` 内にあるため、旧 `ai:jigo` を誤って9路盤で選んだ場合も `==9` 分岐に到達し、`jigo9_*` キーは旧 jigo config に無いのでコードデフォルト（phase3=30 等）で安全に動作する。クラッシュしない下位互換。9路は新モード推奨であることを i18n ヘルプに明記する。

## 変更ファイル一覧

| ファイル | 変更内容 |
|---|---|
| `katrain/core/constants.py` | `AI_JIGO_9` 定数 / 3箇所登録（ENGINE・ORDER・STRENGTH） / `AI_OPTION_VALUES` に `jigo9_phase*` 5キー追加＋`max_loss_per_move` に 3.3 追加 / `AI_OPTION_ORDER` に5キー |
| `katrain/core/ai.py` | `Jigo9Strategy` 新設＋register / `import AI_JIGO_9` / `_jigo_resolve_13path_overrides`→`_jigo_resolve_path_overrides`（key_prefix引数）/ `generate_move` に `==9` 分岐＋eff_target 3分岐整理 / `_jigo_get`＋`FORCED_SETTINGS` 機構 / 9路定数・キャップ削除 |
| `katrain/config.json`（パッケージ） | `"ai:jigo9"` セクション新設（11キーのデフォルト） |
| `C:\Users\iwaki\.katrain\config.json`（ユーザー） | 同上（**メインセッションで直接 Edit**。サブエージェント委任不可） |
| `katrain/i18n/locales/en/.../katrain.po` | `ai:jigo9` / `aihelp:jigo9` 戦略名・説明、`jigo9_phase*` 短ラベル |
| `katrain/i18n/locales/jp/.../katrain.po` | 同上（日本語） |
| `python tools/compile_mo.py` 実行 | `.mo` 再コンパイル |
| `katrain_debug/runner.py` | `STRATEGY_NAME_MAP` に `"jigo9": AI_JIGO_9` 追加 |
| `katrain_debug/batch_eval.py` | jigo_metrics 分岐（L193 `strategy_name == "jigo"`）を `in ("jigo","jigo9")` に拡張 |
| `.claude/rules/ai-parameters.md` / `CLAUDE.md` | パラメータ表・概要更新 |

## テスト・検証

### ユニットテスト（`tests/`）
- `_jigo_resolve_path_overrides` の `key_prefix="jigo9"` 動作（phase1/2 で 9路スライダー値を返す、phase0/3 はデフォルト）
- 9路 phase 解決: phase3=30 で move_num≥30 が phase3 になること、安全弁 ±5目ジャンプ
- `Jigo9Strategy.FORCED_SETTINGS` が `_jigo_get` で効くこと（epsilon=0.0, large_lead_delta=inf 等）
- 基底 `JigoStrategy` の `FORCED_SETTINGS` が空で挙動不変であること

### CLI（対局不要）
```bash
python -m katrain_debug --sgf <9路SGF> --move N --strategy jigo9 --output text
```

### GUI実戦（必須）
- deception ON/OFF で9路対局。phase3 前倒し（30手）で挽回が間に合うかを score_lead 推移で確認
- deception は trajectory 形成型のため batch 評価では測れない（lead 誘導は SGF 固定だと両条件同一になる）。GUI 実戦のみで検証

## 設計上の制約・既知の限界

- 旧 jigo の「9路設計上の限界」（相手が毎手大損失手を連続で打つ極端な棋力差では target 収束が保証されない）は新モードでも同様。主目的「バレないこと」は維持される
- 9路は終局が早く `current_lead` 変動が激しいため、deception の安全弁が頻繁に発動して phase3 へ早期ジャンプする可能性がある。GUI 実戦で phase 遷移ログ（`Deception: ... phase=`）を確認しながら既定値を校正する
