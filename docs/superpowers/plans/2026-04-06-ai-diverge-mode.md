# AI一致率低減モード（DivergenceStrategy）実装計画

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** KaTrain に `ai:diverge_move` 戦略モードを追加し、評価レポートの AI 最善手一致率≤30%・上位5手一致率≤40%・平均損失目数<1.00 を達成する。

**Architecture:** humanSL 9段クエリ（Stage1）で humanPolicy を取得し、クリーンクエリ（Stage2）で正確なスコアを取得。各候補手のスコアを `humanPolicy × (order+1)^divergence_power` で計算し、KataGo 下位手をブーストしてから重み付き確率選択する。

**Tech Stack:** Python 3.12, KataGo（2段階クエリ）, Kivy GUI（既存パターン流用）

---

## ファイル構成

| ファイル | 操作 | 内容 |
|---|---|---|
| `katrain/core/constants.py` | 修正 | `AI_DIVERGE` 定数・パラメータ設定追加 |
| `katrain/core/ai.py` | 修正 | `DivergenceStrategy` クラス追加・登録 |
| `katrain/config.json` | 修正 | パッケージデフォルト設定追加 |
| `C:\Users\iwaki\.katrain\config.json` | 修正 | ユーザー設定追加（GUI表示に必須） |
| `CLAUDE.md` | 修正 | 新モードのパラメータ説明を追記 |

---

## Task 1: constants.py に AI_DIVERGE を追加

**Files:**
- Modify: `katrain/core/constants.py`

- [ ] **Step 1: `AI_DIVERGE` 定数を追加**

`AI_PRO = "ai:pro"` の直後に追加する：

```python
AI_DIVERGE = "ai:diverge_move"
```

- [ ] **Step 2: `AI_STRATEGIES` と `AI_STRATEGIES_RECOMMENDED_ORDER` に追加**

```python
# 変更前
AI_STRATEGIES = AI_STRATEGIES_ENGINE + AI_STRATEGIES_POLICY + [AI_HUMAN, AI_PRO]

# 変更後
AI_STRATEGIES = AI_STRATEGIES_ENGINE + AI_STRATEGIES_POLICY + [AI_HUMAN, AI_PRO, AI_DIVERGE]
```

`AI_STRATEGIES_RECOMMENDED_ORDER` の `AI_PRO` の直後に追加：

```python
    AI_PRO,
    AI_DIVERGE,   # ← ここに追加
    AI_RANK,
```

- [ ] **Step 3: `AI_STRENGTH` に追加**

```python
# 変更前
    AI_HUMAN: float("nan"),
    AI_PRO: float("nan")

# 変更後
    AI_HUMAN: float("nan"),
    AI_PRO: float("nan"),
    AI_DIVERGE: float("nan"),
```

- [ ] **Step 4: `AI_OPTION_VALUES` にパラメータを追加**

`"green_blend_green_ratio": [...]` の直後（`"fighting_mode"` の前）に追加：

```python
    "divergence_power": [0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0, 1.2, 1.5],
    "diverge_score_filter": [1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0, 5.0],
```

`human_kyu_rank` は既に `AI_OPTION_VALUES` に存在するので追加不要。

- [ ] **Step 5: `AI_OPTION_ORDER` にパラメータの表示順を追加**

```python
    "divergence_power": 0,
    "diverge_score_filter": 1,
```

- [ ] **Step 6: コミット**

```bash
cd "C:\Users\iwaki\Documents\katrain-1.17.1.1\katrain-1.17.1.1"
git add katrain/core/constants.py
git commit -m "feat: AI_DIVERGE定数とパラメータをconstants.pyに追加"
```

---

## Task 2: ai.py に DivergenceStrategy クラスを追加

**Files:**
- Modify: `katrain/core/ai.py`

- [ ] **Step 1: インポートに `AI_DIVERGE` を追加**

`ai.py` 冒頭のインポート（8〜17行目）を編集。`AI_HUMAN, AI_PRO` の行を以下に変更：

```python
    AI_WEIGHTED, AI_WEIGHTED_ELO, CALIBRATED_RANK_ELO, OUTPUT_DEBUG,
    OUTPUT_ERROR, OUTPUT_INFO, PRIORITY_EXTRA_AI_QUERY, ADDITIONAL_MOVE_ORDER, AI_HUMAN, AI_PRO,
    AI_DIVERGE
```

- [ ] **Step 2: `ai_rank_estimation()` に AI_DIVERGE の分岐を追加**

`ai_rank_estimation()` 関数（54〜89行目）の `if strategy == AI_HUMAN:` 行の直後に追加：

```python
    if strategy == AI_DIVERGE:
        return 1 - settings.get("human_kyu_rank", -8)
```

- [ ] **Step 3: `DivergenceStrategy` クラスを `HumanStyleStrategy` の直後（ファイル末尾の `generate_ai_move` 関数の直前）に追加**

ファイル末尾の `def generate_ai_move(...)` の直前（現在 2410 行目付近）に以下を挿入：

```python
@register_strategy(AI_DIVERGE)
class DivergenceStrategy(AIStrategy):
    """Strategy that reduces AI move match rate while maintaining strength.

    Algorithm:
      Stage 1: humanSL query → humanPolicy[]
      Stage 2: clean query   → moveInfos[] with accurate scoreLead
      Score:   divergence_score[i] = humanPolicy[i] * (order[i] + 1)^divergence_power
      Filter:  loss > diverge_score_filter を除外
      Fallback: 候補 ≤ 3 の場合は humanPolicy のみ使用（divergence 無効化）
    """

    def __init__(self, game: Game, ai_settings: Dict):
        super().__init__(game, ai_settings)
        self.game.katrain.log(
            f"[DivergenceStrategy] Initializing with settings: {ai_settings}",
            OUTPUT_DEBUG,
        )

    def generate_move(self) -> Tuple[Move, str]:
        self.game.katrain.log(f"[DivergenceStrategy] Starting move generation", OUTPUT_DEBUG)

        human_kyu_rank = round(self.settings.get("human_kyu_rank", -8))
        if human_kyu_rank <= 0:
            rank_text = f"{1 - human_kyu_rank}d"
        else:
            rank_text = f"{human_kyu_rank}k"
        human_profile = f"rank_{rank_text}"

        divergence_power = float(self.settings.get("divergence_power", 0.5))
        score_filter = float(self.settings.get("diverge_score_filter", 2.5))

        self.game.katrain.log(
            f"[DivergenceStrategy] profile={human_profile}, "
            f"divergence_power={divergence_power}, score_filter={score_filter}",
            OUTPUT_DEBUG,
        )

        # --- Stage 1: humanSL クエリ（humanPolicy 取得） ---
        analysis = None
        error = False

        def set_analysis(a, partial_result):
            nonlocal analysis
            if not partial_result:
                analysis = a

        def set_error(a):
            nonlocal error
            error = True
            self.game.katrain.log(f"[DivergenceStrategy] Stage1 error: {a}", OUTPUT_ERROR)

        engine = self.game.engines[self.cn.player]
        engine.request_analysis(
            self.cn,
            callback=set_analysis,
            error_callback=set_error,
            priority=PRIORITY_EXTRA_AI_QUERY,
            include_policy=True,
            extra_settings={
                "humanSLProfile": human_profile,
                "ignorePreRootHistory": False,
                "maxVisits": 800,
            },
        )

        while not (error or analysis):
            time.sleep(0.01)
            engine.check_alive(exception_if_dead=True)

        if error or not analysis or "humanPolicy" not in analysis:
            self.game.katrain.log(
                f"[DivergenceStrategy] Stage1 failed, falling back to policy", OUTPUT_DEBUG
            )
            policy_move = self.cn.policy_ranking[0][1] if self.cn.policy_ranking else None
            if policy_move:
                return policy_move, "DivergenceStrategy: fallback to policy (Stage1 error)."
            return Move(None, player=self.cn.next_player), "DivergenceStrategy: no valid moves."

        human_policy = analysis["humanPolicy"]
        bx, by = self.game.board_size

        # --- Stage 2: クリーンクエリ（正確な scoreLead 取得） ---
        # humanSLProfile 付きクエリの scoreLead はバイアスされるため、
        # Stage2 のクリーン値を損失フィルタ判定に使用する
        clean_analysis = None
        clean_error = False

        def set_clean_analysis(a, partial_result):
            nonlocal clean_analysis
            if not partial_result:
                clean_analysis = a

        def set_clean_error(a):
            nonlocal clean_error
            clean_error = True
            self.game.katrain.log(f"[DivergenceStrategy] Stage2 error: {a}", OUTPUT_ERROR)

        engine.request_analysis(
            self.cn,
            callback=set_clean_analysis,
            error_callback=set_clean_error,
            priority=PRIORITY_EXTRA_AI_QUERY,
            include_policy=False,
            extra_settings={
                "ignorePreRootHistory": False,
                "maxVisits": 600,
                "wideRootNoise": 0.0,
            },
        )

        while not (clean_error or clean_analysis):
            time.sleep(0.01)
            engine.check_alive(exception_if_dead=True)

        if clean_analysis and not clean_error:
            move_infos = clean_analysis.get("moveInfos", [])
            self.game.katrain.log(
                f"[DivergenceStrategy] Using clean moveInfos ({len(move_infos)} moves)",
                OUTPUT_DEBUG,
            )
        else:
            move_infos = analysis.get("moveInfos", [])
            self.game.katrain.log(
                f"[DivergenceStrategy] Stage2 failed, using biased moveInfos "
                f"({len(move_infos)} moves)",
                OUTPUT_DEBUG,
            )

        # moveInfos が空の場合は humanPolicy 最上位手を返す
        if not move_infos:
            self.game.katrain.log(
                f"[DivergenceStrategy] No moveInfos, using top humanPolicy", OUTPUT_DEBUG
            )
            top_idx = max(range(len(human_policy)), key=lambda i: human_policy[i])
            x = top_idx % bx
            y = by - 1 - (top_idx // bx)
            return Move((x, y), player=self.cn.next_player), "No moveInfos available."

        # player_sign: Black=+1, White=-1（scoreLead は常に Black 視点）
        player_sign = 1 if self.cn.next_player == "B" else -1

        # best_score: 現在プレイヤー視点での最善スコア（Black=max, White=min scoreLead）
        best_score = (
            max(mi.get("scoreLead", 0) * player_sign for mi in move_infos) / player_sign
        )

        # order=0 の手がパスなら強制パス
        order0_mi = next(
            (mi for mi in move_infos if mi.get("order", 999) == 0), move_infos[0]
        )
        if order0_mi.get("move") == "pass":
            return Move(None, player=self.cn.next_player), "Best move is pass, forcing pass."

        # 候補手の divergence スコアを計算
        # divergence_score[i] = humanPolicy[i] × (order[i] + 1)^divergence_power
        # order が大きい（AI が低く評価）ほどブーストが大きくなる
        candidates = []  # [(Move, divergence_score, humanPolicy, order, loss)]
        for i, mi in enumerate(move_infos):
            gtp = mi.get("move", "")
            if not gtp or gtp == "pass":
                continue
            order = mi.get("order", i)
            score = mi.get("scoreLead", 0)
            loss = player_sign * (best_score - score)  # 正値 = 現在プレイヤーにとって損

            if loss > score_filter:
                continue  # スコアフィルタ: 損失過大な手を除外

            try:
                m = Move.from_gtp(gtp, player=self.cn.next_player)
            except Exception:
                continue
            if m.coords is None:
                continue
            x, y = m.coords
            idx = (by - y - 1) * bx + x
            if idx < 0 or idx >= len(human_policy):
                continue

            hp = human_policy[idx]
            div_score = hp * ((order + 1) ** divergence_power)
            candidates.append((m, div_score, hp, order, loss))

        self.game.katrain.log(
            f"[DivergenceStrategy] {len(candidates)} candidates after score filter "
            f"(filter={score_filter})",
            OUTPUT_DEBUG,
        )

        # フォールバック: スコアフィルタ後に候補が0の場合、フィルタを解除して再構築
        if not candidates:
            self.game.katrain.log(
                f"[DivergenceStrategy] No candidates after filter, relaxing to all moveInfos",
                OUTPUT_DEBUG,
            )
            for i, mi in enumerate(move_infos):
                gtp = mi.get("move", "")
                if not gtp or gtp == "pass":
                    continue
                try:
                    m = Move.from_gtp(gtp, player=self.cn.next_player)
                except Exception:
                    continue
                if m.coords is None:
                    continue
                x, y = m.coords
                idx = (by - y - 1) * bx + x
                if idx < 0 or idx >= len(human_policy):
                    continue
                hp = human_policy[idx]
                candidates.append((m, hp, hp, mi.get("order", i), 999.0))

        # それでも候補が無ければ AI 最善手を返す
        if not candidates:
            best_gtp = move_infos[0].get("move", "pass")
            if best_gtp == "pass":
                return Move(None, player=self.cn.next_player), "Fallback: pass."
            return Move.from_gtp(best_gtp, player=self.cn.next_player), "Fallback: best AI move."

        # 候補が ≤3 手の場合は divergence を無効化（humanPolicy のみで選択）
        # → 「ほぼ1択」局面でも自然な手を打てる
        if len(candidates) <= 3:
            self.game.katrain.log(
                f"[DivergenceStrategy] ≤3 candidates, disabling divergence (humanPolicy only)",
                OUTPUT_DEBUG,
            )
            weighted_moves = [(m, hp) for m, _, hp, _, _ in candidates]
        else:
            weighted_moves = [(m, div_score) for m, div_score, _, _, _ in candidates]

        # 重み付き確率選択（utils.weighted_selection_without_replacement はitem[1]を重みとして使用）
        selected = weighted_selection_without_replacement(weighted_moves, 1)[0]
        move = selected[0]

        top5_sorted = sorted(candidates, key=lambda c: -c[1])[:5]
        top5_str = "\n".join(
            f"#{j+1}: {m.gtp()} (div={ds:.4f}, hp={hp:.3f}, order={ord_}, loss={ls:.2f})"
            for j, (m, ds, hp, ord_, ls) in enumerate(top5_sorted)
        )
        chosen_order = next(
            (ord_ for m2, _, _, ord_, _ in candidates if m2.gtp() == move.gtp()), "?"
        )
        ai_thoughts = (
            f"\n{top5_str}\n\n"
            f"DivergenceStrategy: played {move.gtp()} "
            f"(power={divergence_power}, filter={score_filter}, AI_order={chosen_order})"
        )

        self.game.katrain.log(
            f"[DivergenceStrategy] Selected {move.gtp()} (AI order={chosen_order})",
            OUTPUT_DEBUG,
        )
        return move, ai_thoughts
```

- [ ] **Step 4: コミット**

```bash
git add katrain/core/ai.py
git commit -m "feat: DivergenceStrategyクラスをai.pyに追加"
```

---

## Task 3: config.json にデフォルト設定を追加

**Files:**
- Modify: `katrain/config.json`
- Modify: `C:\Users\iwaki\.katrain\config.json`

- [ ] **Step 1: パッケージ版 `katrain/config.json` に追加**

`"ai:pro": { "pro_year": 1914 }` の直後（`}` の前、`"ui_state":` セクションの前）に追加：

```json
        "ai:diverge_move": {
            "human_kyu_rank": -8,
            "divergence_power": 0.5,
            "diverge_score_filter": 2.5
        }
```

（末尾カンマに注意: `"ai:pro"` ブロックの閉じ `}` の後にカンマが必要）

- [ ] **Step 2: ユーザー版 `C:\Users\iwaki\.katrain\config.json` に追加**

同じ内容を同じ位置（`"ai:pro"` の直後）に追加する。

> **注意**: このファイルへの追加を忘れると GUI に設定スライダーが表示されない（CLAUDE.md の「やってはいけないこと」参照）。

- [ ] **Step 3: JSON 構文チェック**

```bash
python -c "import json; json.load(open('katrain/config.json'))" && echo OK
python -c "import json; json.load(open(r'C:\Users\iwaki\.katrain\config.json'))" && echo OK
```

期待出力: 両方とも `OK`

- [ ] **Step 4: コミット**

```bash
git add katrain/config.json
git commit -m "feat: ai:diverge_moveのデフォルト設定をconfig.jsonに追加"
```

---

## Task 4: CLAUDE.md を更新

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: 「AI一致率低減モード（DivergenceStrategy）」セクションを追加**

CLAUDE.md の「力戦派モード（FightingStrategy）」テーブルの直後に以下を追加：

```markdown
### AI一致率低減モード（DivergenceStrategy）

評価レポートの AI 最善手一致率≤30%・上位5手一致率≤40%・平均損失<1.00 を目標とする新戦略モード。

**目標値**: `ai_top_move ≤ 30%`, `ai_top5_move ≤ 40%`, `mean_ptloss < 1.00`

**アルゴリズム**: `divergence_score = humanPolicy × (order+1)^divergence_power`
（order: KataGo の探索順位、0=最善手。大きいほど AI 下位手をブースト）

| パラメータ | デフォルト値 | 備考 |
|---|---|---|
| human_kyu_rank | -8（9段） | humanSLプロファイルのベース段位 |
| divergence_power | 0.5 | AI一致率低減強度（0.3〜1.5）。大きいほど AI 下位手をブースト |
| diverge_score_filter | 2.5 | 許容する最大損失（目数）（1.0〜5.0） |

**注意**: `divergence_power` のデフォルト値は実戦テストで調整が必要。目標値に届かない場合は 0.3 刻みで引き上げる。
```

- [ ] **Step 2: コミット**

```bash
git add CLAUDE.md
git commit -m "docs: AI一致率低減モードのパラメータをCLAUDE.mdに追記"
```

---

## Task 5: 動作確認テスト

- [ ] **Step 1: 起動前に debug_level を有効化**

`C:\Users\iwaki\.katrain\config.json` の `"debug_level": 0` を `1` に変更。

- [ ] **Step 2: アプリを起動して AI モードを選択**

```bash
cd "C:\Users\iwaki\Documents\katrain-1.17.1.1\katrain-1.17.1.1"
python -m katrain
```

KaTrain GUI で:
1. AI設定 → 「ai:diverge_move」が選択肢に存在することを確認
2. パラメータスライダー（divergence_power, diverge_score_filter, human_kyu_rank）が表示されることを確認
3. 数手対局して着手が生成されることを確認

- [ ] **Step 3: ログで動作確認**

ログファイルをGrepで確認（`C:\Users\iwaki\.katrain\` 以下の `.log` ファイル）:

```bash
# DivergenceStrategy の初期化確認
grep -i "DivergenceStrategy" C:\Users\iwaki\.katrain\katrain.log | tail -20

# Stage1/Stage2 クエリの確認
grep "Stage[12]" C:\Users\iwaki\.katrain\katrain.log | tail -10

# 着手選択の確認（AI_order が 0 以外が多ければ成功）
grep "DivergenceStrategy.*AI_order" C:\Users\iwaki\.katrain\katrain.log | tail -10
```

期待出力例:
```
[DivergenceStrategy] Initializing with settings: {...}
[DivergenceStrategy] Using clean moveInfos (20 moves)
[DivergenceStrategy] Selected R16 (AI order=3)
```

- [ ] **Step 4: debug_level を 0 に戻す**

`C:\Users\iwaki\.katrain\config.json` の `"debug_level": 1` を `0` に戻す。

- [ ] **Step 5: 評価レポートで目標値確認（任意）**

19路盤で約30手の対局後、分析オプション → 評価レポートを開き:
- `ai_top_move`（最善手一致率）≤ 30%
- `ai_top5_move`（上位5手一致率）≤ 40%
- `mean_ptloss`（平均損失）< 1.00

目標値に届かない場合は `divergence_power` を 0.3 刻みで引き上げて再テスト。

---

## Self-Review メモ

**Spec coverage チェック:**
- ✅ `DivergenceStrategy` クラス追加（Task 2）
- ✅ `AI_DIVERGE` 定数（Task 1）
- ✅ 2段階クエリ・divergence_score計算・フィルタ・フォールバック（Task 2 Step 3）
- ✅ 候補≤3でdivergence無効化フォールバック（Task 2 Step 3）
- ✅ config.json 両方の更新（Task 3）
- ✅ CLAUDE.md 更新（Task 4）
- ✅ `ai_rank_estimation()` への分岐追加（Task 2 Step 2）
- ✅ `AI_STRATEGIES_RECOMMENDED_ORDER` への追加（Task 1 Step 2）
- ⚠️ **調整注意**: `divergence_power=0.5` のデフォルト値は推定値。実戦テストで目標値未達なら引き上げが必要（Task 5 Step 5 参照）

**型一貫性チェック:**
- `weighted_moves = [(Move, float), ...]` → `weighted_selection_without_replacement(weighted_moves, 1)[0]` → `(Move, float)` ✅
- `Move.from_gtp(gtp, player=self.cn.next_player)` → `Move` オブジェクト ✅
- `player_sign * (best_score - score)` → loss は常に正値（損失方向）✅
