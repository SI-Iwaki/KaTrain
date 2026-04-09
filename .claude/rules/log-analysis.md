---
description: KaTrainゲームログの読み方・分析手順・サブエージェント起動テンプレート（ログ分析時のみ参照）
paths:
  - "**/*.log"
---

# KaTrain ゲームログ分析ガイド

## ログの場所と命名規則

```
C:\Users\iwaki\.katrain\logs\game_YYYYMMDD_HHMMSS.log
```

1局1ファイル。サイズは数百KB〜1MB超になることがある。

---

## 絶対ルール：大ログはReadしない

- **Read（全読み）は禁止**。数百KB = 数万〜十数万トークン = コンテキストを大量消費
- **必ずGrepで必要な行だけ抽出する**
- 複数パターンの横断分析には**Exploreサブエージェント**を使う

---

## ログの行パターン一覧

### 1. KataGoクエリ送受信

```
Sending query QUERY:N: {"rules":..., "analyzeTurns": [T], "maxVisits": 600, ...}
[秒数][QUERY:N][done] KataGo analysis received: X candidate moves, Y visits
[秒数][QUERY:N][....] KataGo analysis received: ...   ← 途中経過
```

- `priority: 10006` = AI着手生成用クエリ（humanSLProfile付き）
- `priority: 1006`  = 通常解析クエリ
- `[done]` = 最終結果、`[....]` = 途中結果

### 2. HumanStyleStrategy初期化（着手ごとに出力）

```
Generate AI move called with mode: ai:human
Initializing HumanStyleStrategy with settings: {'human_kyu_rank': -8.0, 'modern_style': True, 'force_star_opening': True, 'loose_moves_big_win': False, 'policy_temperature': 1.0, 'first_impression_deviation': True}
```

### 3. フェーズ・閾値

```
[HumanStyleStrategy] Move N: phase=opening, threshold=2.8 (boundary=51)
[HumanStyleStrategy] Move N: phase=normal,  threshold=5.9 (boundary=51)
```

- `phase=opening`: 序盤（19路: 1〜50手目）
- `threshold`: 悪手フィルターの閾値（目数）

### 4. スコアフィルター結果

```
[HumanStyleStrategy] Best move score: -0.9 (player=W), filtering moves losing 2.8+ pts
[HumanStyleStrategy] 69 moves pass score filter out of 69 searched
[HumanStyleStrategy] 69 candidate moves (291 filtered out)
```

- `X moves pass score filter out of Y searched`: フィルター通過数/探索数
- `(N filtered out)`: 除外数（探索外の手を含む）

### 5. force_star_opening（序盤限定）

```
[HumanStyleStrategy] force_star_opening: ai_stars=0, opp_stars=1, targets=['(3,3)']
```

### 6. humanPolicy情報

```
[HumanStyleStrategy] Human policy sum: -3.5e-07, max: 0.541110039
[HumanStyleStrategy] Analysis contains humanPolicy: True
```

- `sum ≈ 0`: 手番1（正常）
- `sum ≈ -(N-1)`: 手番NでhumanPolicy=-1の手（探索外）がN-1個累積している正常パターン
- `max`: 最高確率手のhumanPolicy値（0〜1）

### 7. Top5候補手と選択結果

```
[HumanStyleStrategy] Top 5 moves:
#1: D4 - 54.1%
#2: C6 - 17.7%
[HumanStyleStrategy] Selected move D4 (prob=0.5411)
```

### 8. 第一感ぶれ（first_impression_deviation）

```
[HumanStyleStrategy] First-impression deviation: E4 (loss=0.7)
First-impression deviation: played E4 (loss=0.7). (338 bad moves filtered)
```

上位3位のうち損失0.5〜2.0目の手を確定選択したとき出力。

### 9. 着手完了サマリー行（最重要確認行）

```
Played move D4 (54.1%) as the #1 top move. (291 bad moves filtered)
First-impression deviation: played E4 (loss=0.7). (338 bad moves filtered)
```

---

## よく使うGrepパターン

| 目的 | pattern |
|---|---|
| 全着手の選択結果 | `Played move\|First-impression deviation: played` |
| フィルター通過率の確認 | `moves pass score filter out of` |
| first_impression_deviation発動手 | `First-impression deviation: [A-Z]` |
| フェーズ・閾値の確認 | `Move [0-9]+: phase=` |
| 異常検出 | `error=True\|humanPolicy: False` |
| AI設定値の確認 | `Initializing HumanStyleStrategy with settings` |

---

## サブエージェント起動テンプレート

### テンプレートA: 1局の全体サマリー

```
subagent_type: Explore

prompt:
C:\Users\iwaki\.katrain\logs\game_YYYYMMDD_HHMMSS.log を分析し、
以下をコンパクトに返せ。生ログ行は貼らないこと。

1. 対局設定（盤面サイズ・AI設定値）
   Grep: "Initializing HumanStyleStrategy with settings"（最初の1件）

2. 全着手サマリー表（手番|座標|選択理由|Top確率|通過数/除外数）
   Grep: "Played move|First-impression deviation: played"
   Grep: "moves pass score filter out of"（手番順に対応付け）

3. first_impression_deviation発動一覧（手番・座標・損失目数）
   Grep: "First-impression deviation: [A-Z]"

4. フェーズ切り替え（openingからnormalへの移行手番）
   Grep: "phase=normal"（最初の1件）

5. 異常検出
   Grep: "error=True|humanPolicy: False"
```

### テンプレートB: フィルター効果の統計

```
subagent_type: Explore

prompt:
C:\Users\iwaki\.katrain\logs\game_YYYYMMDD_HHMMSS.log から
以下の統計を算出して返せ。計算過程は省略すること。

1. 序盤(opening)・中盤(normal)別のフィルター通過率（平均）
   Grep: "Move [0-9]+: phase=" と "moves pass score filter out of" を対応付け

2. first_impression_deviation発動回数・該当手番・損失目数一覧
   Grep: "First-impression deviation: [A-Z]"

3. humanPolicy最大値の分布（0.9以上 / 0.5〜0.9 / 0.5未満の件数）
   Grep: "Human policy sum:.*max:" で全行取得しmax値を集計
```

### テンプレートC: 特定手番の詳細トレース

```
subagent_type: Explore

prompt:
C:\Users\iwaki\.katrain\logs\game_YYYYMMDD_HHMMSS.log の
手番N の処理を調べ、以下を返せ。

1. 使用QUERYのID・応答時間・候補手数
2. フェーズ・閾値・Best move score
3. フィルター通過数・除外数
4. Top5候補手と確率
5. 選択手と選択理由（通常選択 or first_impression_deviation）

Grep: "Move N:|Selected move|First-impression deviation"
```

### テンプレートD: 複数ログの比較（general-purposeサブエージェント）

```
subagent_type: general-purpose

prompt:
C:\Users\iwaki\.katrain\logs\ 内の直近Nファイルについて、
以下を比較した表を返せ。ファイル内容を直接貼らないこと。

- ファイル名（対局日時）
- first_impression_deviation発動回数
- 平均フィルター除外数
- 異常（humanPolicy未取得など）の有無
```

---

## FightingStrategy（humanモード）のログパターン

HumanStyleStrategyとはプレフィックスと一部の行フォーマットが異なる。

### 初期化

```
Initializing FightingStrategy with settings: {'fighting_mode': 'human', 'fighting_max_loss': 2.5, ...}
Generating move using FightingStrategy
[FightingStrategy] Mode: human
[FightingStrategy:human] Starting move generation
```

### フェーズ・閾値・ベストスコア

```
[FightingStrategy:human] Move N: threshold=2.8, best_score=-1.0
[FightingStrategy:human] Move N: threshold=6.0, best_score=-5.2
```

- 序盤（19路: Move 0〜50手目未満）: threshold=2.8
- 中盤以降: threshold=5.6（※コードは FightingStrategy と HumanStyleStrategy で共通値）
- `best_score`: Stage 2 クリーンクエリでの最善手スコア（現プレイヤー視点）

### フィルター通過

```
[FightingStrategy:human] 56 moves pass score filter
[FightingStrategy:human] 56 candidate moves (305 filtered)
```

### 安全弁

```
[FightingStrategy:human] Safety v2: top weighted move A19 loss=4.07
[FightingStrategy:human] Safety valve v2: top weighted A19 loss=4.07 >= 4.0, forcing best-score move L16
AI thoughts: Safety valve v2: top weighted A19 had loss=4.07, forced best-score move L16.
```

- `Safety v2:` = 最高重み候補のloss確認（毎回出力）
- `Safety valve v2:` = loss >= 4.0 で発動、best-score手を強制
- 安全弁発動時は `Human+Fighting: played` 行は**出ない**。`AI thoughts:` 行のみ

v1安全弁（最多visits手が対象）：
```
[FightingStrategy:human] Safety valve: max-visit move C11 loss=4.83 >= 4.0, forcing best-score move B5
AI thoughts: Safety valve: max-visit C11 had loss=4.83, forced best-score move B5.
```

### Score tiebreak

2つの条件のいずれかで発動し、Stage 2スコア差が2目以上あれば高スコア手を確定選択：

```
Score tiebreak(visits_reversal): played Q16 (score diff=2.5pt). (300 filtered)
Score tiebreak(policy): played M5 (score diff=3.1pt). (304 filtered)
Score tiebreak(mcts_nonprefer): played K14 (score diff=2.6pt). (279 filtered)
```

- `visits_reversal`: humanPolicy 2位手の visits が 1位の2倍超
- `policy`: humanPolicy の 1位/2位比が 1.05 未満（拮抗）
- `mcts_nonprefer`: 2位 visits ≥ 1位 visits（MCTSが1位を優遇していない）
- タイブレーク発動時も `Human+Fighting: played` 行は**出ない**

### 通常選択・終局

```
[FightingStrategy:human] Selected: D16
AI thoughts:
Human+Fighting: played D16 (305 bad moves filtered)
```

```
[FightingStrategy:human] Endgame: playing top humanPolicy move C11
AI thoughts: Endgame: played top humanPolicy move C11.
```

- 終局（19路: Move 181手目以降）は力戦重みなしのhumanPolicy最上位を選択
- 終局時も `Human+Fighting: played` 行は**出ない**。`AI thoughts:` 行のみ

### "AI thoughts:" 行の役割まとめ

| 内容 | 対応する選択パターン |
|---|---|
| `Human+Fighting: played X` | 通常選択（重み付きランダム） |
| `Score tiebreak(...): played X` | タイブレーク確定選択 |
| `Safety valve v2: top weighted X had loss=Y, forced Z` | 安全弁v2発動 |
| `Safety valve: max-visit X had loss=Y, forced Z` | 安全弁v1発動 |
| `Endgame: played top humanPolicy move X` | 終局フェーズ選択 |

### FightingStrategy よく使うGrepパターン

| 目的 | pattern |
|---|---|
| 全着手の選択結果 | `Human\+Fighting: played\|Score tiebreak\|Safety valve.*forced\|Endgame: played` |
| フィルター通過率 | `moves pass score filter` |
| 安全弁の発動確認 | `Safety valve.*forced` |
| タイブレーク発動確認 | `Score tiebreak` |
| フェーズ・閾値・ベストスコア | `Move [0-9]+: threshold=` |
| 安全弁v2の候補チェック | `Safety v2: top weighted` |
| 設定値の確認 | `Initializing FightingStrategy with settings` |
| 異常検出 | `error=True` |

### サブエージェントテンプレートE: FightingStrategy 1局サマリー

```
subagent_type: Explore

prompt:
C:\Users\iwaki\.katrain\logs\game_YYYYMMDD_HHMMSS.log を分析し、
以下をコンパクトに返せ。生ログ行は貼らないこと。

1. 対局設定（盤面サイズ・AI設定値）
   Grep: "Initializing FightingStrategy with settings"（最初の1件）

2. 全着手サマリー表（手番|座標|選択パターン|filtered数）
   Grep: "Human\+Fighting: played|Score tiebreak|Safety valve.*forced|Endgame: played"

3. フェーズ・ベストスコア推移（序盤→中盤→逆転の有無）
   Grep: "Move [0-9]+: threshold="（全件）

4. 安全弁発動一覧（手番・発動理由・強制手）
   Grep: "Safety valve.*forced"

5. タイブレーク発動一覧（手番・トリガー種別・打った手・score diff）
   Grep: "Score tiebreak"

6. 安全弁v2の候補チェック（loss値の推移）
   Grep: "Safety v2: top weighted"
```

---

## SiegeStrategy（攻城戦略）のログパターン

### 初期化

```
Generate AI move called with mode: ai:siege
Initializing SiegeStrategy with settings: {'siege_transition_move': 40, 'siege_min_group_size': 5, ...}
[SiegeStrategy] Stage 1: requesting humanSL analysis (rank_9d)
[SiegeStrategy] Stage 2: requesting clean analysis
[SiegeStrategy] Using clean moveInfos (N moves)
```

### フェーズ・ターゲット

```
[SiegeStrategy] Phase: concede, move=N
[SiegeStrategy] Phase: attack, move=N, targets=M
[SiegeStrategy] Phase: attack (forced), move=N, targets=0
[SiegeStrategy] Primary target: size=N, instability=0.XX, score=X.XX
```

### フィルター通過

```
[SiegeStrategy:concede] N moves pass score filter out of M (threshold=4.5)
[SiegeStrategy:concede] N candidate moves (M filtered)
[SiegeStrategy:attack] N moves pass score filter out of M (threshold=6.0)
[SiegeStrategy:attack] Targets: N, candidates: M (K filtered)
```

### 安全弁・タイブレーク・エンドゲーム

```
[SiegeStrategy:attack] Safety valve: top weighted A19 loss=4.07 >= 4.0, forcing best-score move L16
[SiegeStrategy:concede] Tiebreak(mcts_nonprefer): D4 over Q4 (score diff=2.5pt)
[SiegeStrategy:attack] Endgame: playing top humanPolicy move C11
```

### 通常選択

```
[SiegeStrategy:concede] Selected: Q4
[SiegeStrategy:attack] Selected: D16
```

### Stage 1 失敗時

```
[SiegeStrategy] Stage 1 failed, falling back to standard policy
```

### SiegeStrategy よく使うGrepパターン

| 目的 | pattern |
|---|---|
| 全着手の選択結果 | `SiegeStrategy.*Selected:\|Safety valve.*forced\|Tiebreak.*:\|Endgame: played` |
| フィルター通過率 | `SiegeStrategy.*moves pass score filter` |
| フェーズ遷移 | `SiegeStrategy.*Phase:` |
| ターゲット情報 | `SiegeStrategy.*Primary target` |
| 安全弁の発動確認 | `SiegeStrategy.*Safety valve.*forced` |
| タイブレーク発動確認 | `SiegeStrategy.*Tiebreak` |
| 設定値の確認 | `Initializing SiegeStrategy with settings` |
| 異常検出 | `SiegeStrategy.*Stage 1 failed\|SiegeStrategy.*Error` |

### サブエージェントテンプレートF: SiegeStrategy 1局サマリー

```
subagent_type: Explore

prompt:
C:\Users\iwaki\.katrain\logs\game_YYYYMMDD_HHMMSS.log を分析し、
以下をコンパクトに返せ。生ログ行は貼らないこと。

1. 対局設定（盤面サイズ・AI設定値）
   Grep: "Initializing SiegeStrategy with settings"（最初の1件）

2. フェーズ遷移（concede→attack移行手番、ターゲット数推移）
   Grep: "SiegeStrategy.*Phase:"（全件）

3. 全着手サマリー表（手番|座標|選択パターン|filtered数）
   Grep: "SiegeStrategy.*Selected:|Safety valve.*forced|Tiebreak|Endgame: played"

4. ターゲット一覧（サイズ・不安定度・スコア）
   Grep: "Primary target"

5. 安全弁発動一覧（手番・発動理由・強制手）
   Grep: "SiegeStrategy.*Safety valve.*forced"

6. タイブレーク発動一覧（手番・トリガー種別・打った手・score diff）
   Grep: "SiegeStrategy.*Tiebreak"
```

---

## humanPolicy=0問題の診断

`memory/feedback_humanpolicy_zero.md` も参照。

ログ上の症状：
```
[HumanStyleStrategy] Analysis contains humanPolicy: False
[HumanStyleStrategy] Human policy sum: 0.0, max: 0.0
```

正常時は `humanPolicy: True` かつ `max > 0` であること。
