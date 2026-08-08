# 9路専用 新戦略 `ai:parity9`（GUI表示「一致率追随（9路）」）設計

- 日付: 2026-08-06
- 対象: `katrain/core/ai.py`（新クラス + 純関数群）、`katrain/core/constants.py`、`katrain/config.json`（パッケージ + ユーザーローカル）、`i18n/*.po`、`katrain_debug/runner.py`、`tests/test_ai_parity9.py`（新規）
- 関連: [2026-05-31-fighting-complex-humble-design.md](2026-05-31-fighting-complex-humble-design.md)（リード比例予算で一致率を下げる前例）、[2026-06-04-jigo-9x9-dedicated-mode-design.md](2026-06-04-jigo-9x9-dedicated-mode-design.md)（9路専用戦略の器）、[2026-08-05-jigo-endgame-humanstyle-design.md](2026-08-05-jigo-endgame-humanstyle-design.md)（ヨセ以降の切り替え）、`.claude/rules/ai-parameters.md`

## 1. 背景と目的

9路盤で人間相手に打つとき、KataGo 最善手を打ち続けると終局レポートの AI 最善手一致率が相手より大きく上回り、対局として不自然になる。一方で 9路は 1手の価値が大きく、既存の一致率低減モード（`ai:diverge_move`）のように**常に確率的に外す**と勝ちを落とす。

**目的**: 9路で確実に勝ちながら、終局時の AI 最善手一致率が相手を大きく上回らないようにする。ただし相手が最善手を打ち続けている局面ではこちらも外さない。

**ユーザー要件（原文）**:
- 勝利する
- 最善手ばかりを打たない（ただし終盤以降のヨセなどは間違えない）
- 相手が最善手ばかり打ってきている場合はこちらも最善手のみ打つ
- 相手より最善手が一致した手数が多い場合に限り、最善手から外せる
- 外す場合は損失が小さい手、もしくは絶対に逆転されない程度の損失手。かつ humanPolicy が一番高い手（手抜きとバレないため）

## 2. 設計方針（ブレインストーミングでの決定事項）

| 論点 | 決定 |
|---|---|
| 一致の定義 | **KataGo 最善手と完全一致**（`game_report` の `ai_top_move` と同一式）。ユーザーが終局レポートで見る数字と内部判断を一致させる |
| 一致数の比較 | **同手数に切り揃えた累計差**。`mine - opp >= match_margin` で解禁。白番の構造的不利（相手が常に1手多い）を切り揃えで消す |
| 損失予算 | **リード連動のみ** `budget = max(0, lead - keep_margin)`。互角・劣勢では予算0＝一切外さない |
| 序盤 | 上記の帰結として**序盤は最善手固定**（開始時リード≒0 のため予算が立たない）。これを承知のうえで採用 |
| 選択規則 | 予算と1手キャップの両方を満たす非最善手から **humanPolicy 最大** |
| ヨセ | **KataGo 最善手のみ**。境界は **手数閾値 AND 盤上の未確定度** |
| 実装構造 | **完全新規 Strategy クラス**（既存戦略に非依存） |

### 却下した案

- **`Jigo9Strategy` への相乗り**: Jigo は「目差を target に合わせる」戦略で、勝勢時にわざと損して目差を縮める。本モードは勝勢を保ったまま一致率だけ下げるので**目的が逆向き**。deception の phase/eff_target と予算計算が二重に効いてデバッグ不能になる。`complex_humble` が `_generate_human` に相乗りできたのは目的が同方向だったから。
- **`DivergenceStrategy` の拡張**: Divergence は `humanPolicy × (order+1)^power` で**常に**確率的に外す設計。本モードは「ゲートが開いた時だけハードに外す」で選択メカニズムが別物。19路兼用クラスに9路専用ゲートを埋め込むことになり、既存利用者の挙動を変えるリスクがある。
- **損失予算の二段構え** `max(固定底値, lead - margin)`: 互角局面でも微小に損する。ユーザーは勝ちを最優先し、互角では外さない方を選択。
- **ヨセの HumanStyle 9段委譲**（`jigo_endgame_humanstyle` 流用）: 9段でも厳密には最善手を外すため、微小な損を拾う可能性がある。「間違えない」を最も確実にするため KataGo 最善手固定を採用。

## 3. 前提となる実測事実

1. **ユーザーのローカル config は `_enable_ownership: false`**（`~/.katrain/config.json:12`。パッケージ側 `katrain/config.json:12` は true）。したがって `cn.ownership` は None になり、ヨセ判定の未確定度は**クエリで明示的に `ownership=True` を要求**しないと取れない。`engine.request_analysis` に `ownership=True` を渡すと `_enable_ownership` をバイパスできる（`engine.py:429`）。同時に `includeMovesOwnership` も立つ（`engine.py:466-467`、両方が同じフラグ）が、9路なら候補約40手 × 81点で無視できる量。
2. **対局中の全ノードは自動解析される**（`game.py:589` `played_node.analyze(...)`）。したがって履歴ノードの `n.parent.candidate_moves` / `n.parent.analysis_complete` は原則そろっている。
3. **Stage1（humanSLProfile 付き）の `scoreLead` はバイアスされる**ので損失判定に使えない（CLAUDE.md）。損失は Stage2 のクリーンクエリの値を使う。
4. **9路の SGF 校正データは既存にない**（`calibration-data/` は13路・19路と詰碁のみ）。検証には新規収録が要る。

## 4. 挙動仕様

### 4.1 全体フロー

新クラス `Parity9Strategy`（`AI_PARITY_9 = "ai:parity9"`）。`generate_move()` は安いゲートから順に落とす直列で、**すべてのゲートの外し方が「KataGo 最善手を打つ」に倒れる**（フェイルセーフ = 外さない）。

```
0. wait_for_analysis()
   best_gtp = cn.candidate_moves[0]["move"]
1. 盤サイズ != 9        → best（警告ログ）
2. ヨセ sticky が立済み → best                        ← クエリ0本
3. 一致数ゲート: mine - opp < match_margin → best     ← クエリ0本（履歴のみ）
4. Stage2（clean + ownership=True）を発行
5. ヨセ判定: depth >= endgame_move AND unsettled <= unsettled_max
             → game._parity9_endgame = True して best
6. budget = max(0, lead - keep_margin); budget <= 0 → best
7. Stage1（humanSL rank_9d）を発行 → humanPolicy
8. 候補 = 非best かつ pass以外 かつ loss <= min(budget, cap) かつ hp >= min_hp
   空 → best / それ以外 → humanPolicy 最大を採用
```

**順序の理由**: 一致数ゲート（3）は履歴だけで判定でき、大半の手番をここで落とすので、その手前にクエリを置かない。humanSL クエリ（7）は実際に外すと決まってから初めて撃つ。

**一致数ゲート（3）がヨセ判定（5）より手前にあるのは意図的**。ゲートが閉じている手番ではヨセ判定に到達せず sticky も立たないが、どちらの経路でも打つ手は best なので挙動に差は出ない。ゲートは毎手評価し直すので、後からゲートが開いた手番でヨセ判定が走れば sticky はそこで立つ。「sticky が立たないのはバグ」と見て順序を入れ替えないこと（入れ替えると全手番で Stage2 を撃つことになる）。

**最善手の同一性は通常解析から取る**。一致数カウントが `game_report` と同じ通常解析（`cn.candidate_moves[0]`）を見る以上、外す/外さないの基準も通常解析に合わせないと「外したつもりが一致していた」というズレが出る。Stage2 は損失と lead の精度のためだけに使い、Stage2 の最善手が通常解析と食い違っても**手の同一性判定には使わない**。

### 4.2 一致数カウント

```python
def parity9_match_tally(nodes, ai_player):
    """(mine, opp, counted) を返す純関数。

    nodes:     root を除く着手ノードの列（時系列）。呼び出し側は
               [n for n in self.cn.nodes_from_root if n.move and not n.is_root]
               で作る（`game_report` の nodes 構築と同じ絞り込み）
    ai_player: "B" | "W"
    戻り値:    mine = 自分の一致数, opp = 切り揃え後の相手の一致数,
               counted = 自分の判定済み手数（ログ用）
    """
```

判定式は `game_report`（`ai.py:379`）と同一:

```python
n.parent.analysis_complete and n.parent.candidate_moves[0]["move"] == n.move.gtp()
```

**同手数への切り揃え**: プレイヤーごとに一致/不一致の bool 列を時系列で作り、`opp` は `mine` と同じ長さの先頭部分だけを合計する。

- AI が黒番: 着手直前の完了手数は 自分 k / 相手 k → 切り揃えは no-op
- AI が白番: 自分 k / 相手 k+1 → 相手の最後の1手を除外し、白番の構造的不利を消す
- `len(opp列) < len(mine列)` の場合は opp 列を全部使う

**扱えない手**: `n.parent.analysis_complete` が False のノード（解析が間に合わなかった／SGF 読み込み直後）は**両者とも列に入れない**。切り揃えが列の長さ基準なので、片側だけ欠けても比較の公平性は保たれる。パスは `"pass"` として通常どおり比較し、root の置き石は `n.move` が無いので自然に除外される。

**なぜ「差 >= 1」で自己安定するか**: 外すと自分の一致数は増えず、相手が一致するたび差が1縮む。差が0になった時点でゲートが閉じて最善手に戻る。結果として自分の一致率は相手の真上に張り付き、終局レポートで相手を大きく上回らない。

**毎手やり直しで再計算する**（インクリメンタルに持たない）。9路なら最大60ノードで安く、後から解析が精緻化されて `candidate_moves[0]` が変わっても自動で追随する。`game_report` と同じ値を見ている保証にもなる。

### 4.3 損失予算

```python
def parity9_budget(lead, keep_margin):
    """自分視点のリードから外し予算（目）を返す純関数。"""
    return max(0.0, lead - keep_margin)
```

呼び出し側:

```python
sign   = 1 if player == "B" else -1
lead   = stage2["rootInfo"]["scoreLead"] * sign        # 自分視点
budget = parity9_budget(lead, parity9_keep_margin)
cap    = min(budget, parity9_max_loss_per_move)        # 予算と1手キャップの厳しいほう
```

各候補の損失は**最善手基準**で測る:

```python
scores     = [mi["scoreLead"] * sign for mi in stage2["moveInfos"]]
best_score = max(scores)
loss_i     = best_score - scores[i]
```

「最善手の代わりに X を打つと何目損か」が予算の意味なので、`candidate_moves` の `pointsLost`（root 基準）ではなく最善手基準（`relativePointsLost` 相当）を使う。`JigoStrategy`（`ai.py:1353`）と同じ流儀。

### 4.4 ヨセ判定

```python
PARITY9_UNSETTLED_ABS = 0.5   # モジュール定数（スライダーにしない）

def parity9_is_endgame(depth, ownership, endgame_move, unsettled_max):
    if depth < endgame_move:
        return False
    if ownership is None:                    # 取れなければ手数だけで入る（安全側）
        return True
    unsettled = sum(1 for o in ownership if abs(o) < PARITY9_UNSETTLED_ABS)
    return unsettled <= unsettled_max
```

- `depth` は `self.cn.depth`（`JigoStrategy` の `_jigo_endgame_handoff` と同じ規約）。`self.cn` は相手が打ったばかりのノードなので、これから打つ手は `depth + 1` 手目にあたる。閾値は `cn.depth` に対して比較する（既存実装と揃える）
- `ownership` は Stage2 のレスポンスの `analysis["ownership"]`（盤面全点のフラット配列）。`cn.ownership` は `_enable_ownership: false` のため使えない（3節）
- **sticky**: 一度ヨセに入ったら `game._parity9_endgame = True` で戻らない（`game._jigo_endgame_handoff` と同じ流儀）。未確定度は手番ごとに揺れるので、ヨセ突入後にコウや競り合いで一時的に未確定点が増えるとロックが外れて再び外し始めてしまうため
- **ownership が None のとき手数だけでヨセ入りに倒す理由**: AND のままだと「測れない＝永遠にヨセに入らない＝外し続ける」という危険側に倒れる

### 4.5 着手選択

```python
def parity9_select(candidates, best_gtp, cap, min_hp):
    """candidates: [{"gtp","loss","hp"}] → 採用する dict または None"""
    pool = [c for c in candidates
            if c["gtp"] != best_gtp and c["gtp"] != "pass"
            and c["loss"] <= cap and c["hp"] >= min_hp]
    if not pool:
        return None
    return max(pool, key=lambda c: (c["hp"], -c["loss"]))
```

- **温度サンプリングなし**（Jigo と同じ argmax）。手選択が決定的になるので `--batch` の run 間分散が KataGo 側の並列探索非決定性だけになり、パラメータ比較が読める
- **hp 同着は損失が小さいほうを採る**（第2キー `-loss`）。要件の「極力損失が小さい」をタイブレークとして残す
- **pass を外し候補から除外**。パスは対局終了に直結し、area scoring のダメ問題（CLAUDE.md「中国ルールのパス判定を目数だけで決めない」）と絡む。最善手が pass なら常に pass を打つ。基準行動が KataGo 最善手そのままなので `_area_scoring_should_pass` 系の誤爆はこのモードでは構造的に起きない
- **`parity9_min_human_policy` を置く理由**: 予算内でも humanPolicy がほぼ0の手しか無い局面で外すと「人間なら打たない手」を選んで**かえって手抜きがバレる**。下限を割ったら外さず最善手へ戻す

### 4.6 クエリ仕様

**visits は `extra_settings["maxVisits"]` では変えられない**（2026-08-06 訂正）。
`engine.request_analysis` は `maxVisits` を**クエリのトップレベル**に `visits` 引数
（既定 `config["max_visits"]`）から入れ、`extra_settings` は `overrideSettings` に
しか入らない。KataGo はトップレベルを優先するので override 側は無視される（実測
`~/.katrain/logs/game_20260806_100831.log`: トップレベル 1000 / override 600 の
クエリが 1006 visits を返した。Stage1 が要求した 800 も同様に 1007 visits で
返っている）。したがって以下の両クエリとも**実際の visits は `config["max_visits"]`
に依存する**（この環境では 1000）。`extra_settings` の `maxVisits` キーは実装から
削除済み（無効なだけでなく読み手を誤誘導するため）。

**Stage2（clean、先に撃つ）** — `DivergenceStrategy` の Stage2 と同形 + ownership:

```python
engine.request_analysis(
    self.cn, callback=..., error_callback=...,
    priority=PRIORITY_EXTRA_AI_QUERY,
    include_policy=False,
    ownership=True,                       # _enable_ownership=false をバイパス
    extra_settings={"ignorePreRootHistory": False, "wideRootNoise": 0.0},
)
```

**Stage1（humanSL、外すと決まってから撃つ）**:

```python
engine.request_analysis(
    self.cn, callback=..., error_callback=...,
    priority=PRIORITY_EXTRA_AI_QUERY,
    include_policy=True,
    extra_settings={"humanSLProfile": "rank_9d", "ignorePreRootHistory": False},
)
```

visits を実際に変えたい場合は `request_analysis(..., visits=N)` で明示的に渡す
必要がある（`extra_settings` ではなく引数）。これは今回のスコープ外（校正データが
現行 visits 数を前提にしているため、visits を変える判断は別途行う）。

`humanPolicy` はフラット配列なので gtp → 値のルックアップに変換する（`JigoStrategy` の `_hp_for_gtp`、`ai.py:1358` と同じ変換。9路は 81+1 要素で末尾が pass）。

## 5. パラメータ

すべて GUI スライダー。`AI_OPTION_VALUES` / `AI_OPTION_ORDER` / `katrain/config.json` / `~/.katrain/config.json` の4箇所に登録する。

| キー | 意味 | 候補値 | 既定 |
|---|---|---|---|
| `parity9_keep_margin` | 安全幅（目）。予算 = リード − これ | 1.0 / 2.0 / 3.0 / 5.0 / 8.0 | 3.0 |
| `parity9_max_loss_per_move` | 1手あたり損失キャップ（目） | 0.5 / 1.0 / 1.5 / 2.0 / 3.0 | 3.0 |
| `parity9_match_margin` | 解禁に必要な一致数差 | 1 / 2 / 3 | 1 |
| `parity9_endgame_move` | ヨセ手数閾値 | 22 / 26 / 30 / 34 / 38 | 30 |
| `parity9_unsettled_max` | ヨセ判定の未確定点上限 | 4 / 6 / 8 / 10 / 12 | 8 |
| `parity9_min_human_policy` | 採用候補の humanPolicy 下限 | 0.0 / 0.005 / 0.01 / 0.02 | 0.01 |

**校正済み（2026-08-06）**: 9路実戦1局（AI=白・人間=黒、komi 7.0・中国ルール・38手・白+26目、`docs/superpowers/specs/calibration-data/parity9/parity9-vs-human-20260806-white.sgf` にログ `~/.katrain/logs/game_20260806_100831.log` から再構成）で計測。

`parity9_unsettled_max=8` と `PARITY9_UNSETTLED_ABS=0.5` は実測で妥当と確認した。手数（depth）ごとの未確定点数は 3→59, 5→64, 7→32, 9→43, 11→29, 13→10, 15→44, 17→41, 19→10, 21→7, 23→3, 25→3, 27→5, 29→7, 31→5 で、実際にヨセ判定が発火したのは depth 31（unsettled=5 <= 8）。中盤は 10 まで下がる瞬間（depth 13, 19）があり、既定を 12 まで緩めると中盤をヨセと誤認する。8 は「まだ戦っている」と「収束した」を正しく分離している。

`parity9_max_loss_per_move` は 1.5→3.0 に緩和した。同じ実戦で AI の19回の判断のうち発火（一致数ゲート開・予算内で外した）4回の損失はいずれも旧上限 1.5 のすぐ下（B5: 1.41 / E9: 0.61 / G9: 1.19 / J3: 1.48）に張り付き、さらに6回は「予算内に非最善候補が無い」として外せずに終わった。予算（`lead - keep_margin`）自体は 5.9〜23.7目と十分に余裕があったため、1手キャップ 1.5 が制約の一つだったと判断し 3.0 へ引き上げた。バッチ再生（`--batch`、固定SGFのため軌跡再現はできない）でも1.5→3.0で `ai_top_move` 84.2%→78.9%・`mean_ptloss` 0.09→0.19 と、外す頻度が増える向きに動くことを確認した。

ただし**修正前のバッチ A/B で実際に動いたのは19手中1手だけ**（`ai_top_move` 84.2%=16/19 → 78.9%=15/19）。固定 SGF の再生なので各局面のリードと候補は同一条件であり、これは「キャップを倍にしても候補なし6手のうち5手は依然として通らない」ことを意味していた。したがって 1.5 は**制約の一つではあったが唯一のボトルネックではない**、というのが修正前の暫定結論だった。

**損失基準修正後の A/B（`0ef0f32`。損失基準を Stage2 argmax ではなく `best_gtp`＝`cn.candidate_moves[0]` に固定し、`PARITY9_MIN_VISITS`(10) 未満の1visit候補を基準・候補プールの両方から除外する修正）**: 同じ校正 SGF・同じ19白番判断をキャップ別に再計測した。

| `parity9_max_loss_per_move` | 修正前 | 修正後 |
|---|---|---|
| 1.5 | `ai_top_move` 84.2%（16/19）、mean_ptloss 0.09 | 89.5%（17/19）、0.09 |
| 3.0 | 78.9%（15/19）、0.19 | 78.9%（15/19）、0.17 |

修正は外す頻度を**増やさなかった**——キャップ1.5では外す率がむしろ1手分下がり（16/19→17/19）、3.0では不変。1手の差は run間ノイズの範囲内（本リポジトリで計測済みの3-run `ai_top_move` stdev ≈0.03、19手換算で約0.6手＝CLAUDE.md）なので、率直に言えば**修正は外す頻度をほぼ動かさなかった**、が正確な結論。ただし修正は §4.3 が定義する損失（「best_gtp の代わりにこの手を打つと何目損か」）の意味を取り戻し、1visit の手（構造上 `best_score - 自分のscoreLead = 0` になり得る＝候補プールの首位を取ってしまう）が選ばれる経路を塞いだので、率が動かなかったことをもって無意味だったとは結論できない（下記参照）。

**`parity9_max_loss_per_move` は 3.0 を維持する**。「1.5 がボトルネックだった」という当初の根拠は否定されたが、1.5 と 3.0 の差は修正前（1手）より修正後（2手）のほうがむしろ広がっており、3.0 という結論自体は最初より良い実測のうえに立っている。なお、キャップ3.0では選ばれた手が1手 KataGo の Top5 の外に出る（Top1 78.9% vs Top5 84.2%）のに対し、キャップ1.5の外し手は全部 Top5 以内に収まっている。

**残りを塞いでいた要因は解決した**（`parity9_min_human_policy` か9路の候補分布かという当初の2択はどちらも誤りだった）。マッチした1局面ペア（depth 23＝発火／depth 25＝ブロック。lead 18.86 vs 18.83・unsettled 3 vs 3）を単発診断すると、depth 25 のログはこう出る:

```
No deviation candidate: cap=3.00 min_hp=0.01 pool=28 searched=1 non_best=0
```

Stage2 の `moveInfos` 28件のうち `PARITY9_MIN_VISITS`（10）以上の visits を持つのはちょうど**1件**——それが最善手自身だったため、非最善の代替候補は文字通りゼロだった。KataGo が実質すべての探索（1000 visits）を1手に集中させ、残り27手をほぼ読んでいなかった。

言い換えると、**ここでブロックするのは正しい挙動であって欠陥ではない**。18.8目リードの局面で誰も読んでいない手を打つことは、まさに visit floor が防ぐべきリスクそのもの。校正局で発生した6回のブロックは、この機構が意図どおり働いている証拠として読む。

これが露わにする構造的な緊張も記録しておく: Stage2 は `scoreLead` をクリーンに保つため意図的に `wideRootNoise: 0.0` で撃っており（4.6節）、これが KataGo の探索を1点に集中させる（通常解析は 0.04 で候補を広げる）。**スコア精度はプール幅を犠牲にして買っている**。visit floor を下げる、または wideRootNoise を広げる代わりに、現状のまま出荷することが決定された。

`parity9_endgame_move` の既定30は既存の 9路ヨセ閾値（力戦派 32、`jigo9_endgame_move` 既定30）に合わせた値（未変更）。

## 6. 登録（漏れると GUI に出ない／巻き戻る）

| ファイル | 追加内容 |
|---|---|
| `katrain/core/constants.py` | `AI_PARITY_9 = "ai:parity9"`、`AI_STRATEGIES_ENGINE`、`AI_STRATEGIES`、`AI_STRATEGIES_RECOMMENDED_ORDER`、`AI_STRENGTH`（`float("nan")`、Jigo と同じ）、`AI_OPTION_VALUES` 6件、`AI_OPTION_ORDER` 6件 |
| `katrain/config.json` | `ai` セクションに `ai:parity9` の既定値6件 |
| `~/.katrain/config.json` | 同じ6件。**メインセッションで直接 Edit**（サブエージェント委任禁止・CLAUDE.md）。KaTrain 起動中は終了時に上書きされるのでウィンドウを閉じてから編集 |
| `katrain/i18n/*.po` | `ai:parity9` のラベル「一致率追随（9路）」→ `python tools/compile_mo.py` で `.mo` を再コンパイル |
| `katrain_debug/runner.py` | `STRATEGY_NAME_MAP["parity9"] = AI_PARITY_9` |
| `.claude/rules/ai-parameters.md` | パラメータ表に本モードの6件を追記 |

GUI 一覧に無い `player_subtype` は往復で `ai:default` に巻き戻る既知の落とし穴があるので、登録後にログで戦略クラス名（`Initializing Parity9Strategy with settings:`）を確認する。

## 7. エラー処理

すべて「KataGo 最善手を打つ」に倒す。

| 事象 | 挙動 |
|---|---|
| Stage1（humanSL）失敗 / `humanPolicy` 欠落 | best |
| Stage2（clean）失敗 / `moveInfos` 空 | best |
| `cn.candidate_moves` が空 | `cn.policy_ranking[0]` → それも無ければ pass |
| 履歴の親解析が全滅（mine=opp=0） | 差0 → ゲート閉 → best |
| `ownership` 欠落 | 手数のみでヨセ入り（外さない側） |
| 盤サイズ != 9 | best + 警告ログ（9路専用モードのため） |

## 8. ログ

`OUTPUT_DEBUG` で `[Parity9Strategy]` プレフィックス。1手ごとに最低限これを出す:

- `Tally: mine=N opp=M (counted=K) → gate open/closed`
- `Endgame: depth=D thr=T unsettled=U max=X → yose/not yet` （sticky 発火時は `sticky`）
- `Budget: lead=L margin=M → budget=B, cap=C`
- `Deviate: played <gtp> (loss=X.XX, hp=Y.YYY) instead of <best_gtp>` / `No deviation: <理由>`

`--batch` は per-move debug ログを抑制するので、ゲートの発火状況を見るときは `--move N` で個別実行する（CLAUDE.md）。

## 9. テスト

### 9.1 pytest（KataGo 不要・純関数）

`tests/test_ai_parity9.py` を新規作成。

- `parity9_match_tally`: 黒番の対等ケース / 白番の切り揃え / 親解析欠損の飛ばし / パスを含む列 / 初手（空列）
- `parity9_budget`: 劣勢 / 互角 / 安全幅ちょうど / 勝勢
- `parity9_is_endgame`: 手数未満 / `ownership=None` / 未確定点が上限超 / 上限ちょうど
- `parity9_select`: pool 空 / hp 下限で全滅 / pass 除外 / hp 同着の損失タイブレーク / 最善手のみ予算内

### 9.2 実測（KataGo 必要）

1. 9路のSGFを新規収録し `docs/superpowers/specs/calibration-data/parity9/` に格納（命名規則 `parity9-vs-<相手>-<YYYYMMDD>-<色>.sgf`）
2. `python -m katrain_debug --sgf <9路SGF> --strategy parity9 --batch` で一致率・平均損失を確認
3. GUI 実戦（`python -m katrain`、`debug_level=1`）で終局レポートを確認 — 自分の一致率が相手を上回っていないか、かつ勝っているか

### 9.3 検証の限界（明記）

**`--batch` は固定 SGF の再生なので「自分が外した結果リードが変わる」軌跡を再現できない**（memory `feedback_batch_eval_trajectory_limit`）。本モードは予算がリード依存なので、batch で観測できるのは「一致数ゲートがいつ開くか」までで、予算の妥当性は評価できない。**最終的な検証は GUI 実戦の終局レポート**になる。

また 9路は総手数が短く（40〜60手）、序盤が予算0で固定される設計上、**実際に外せる窓は中盤の10手前後しかない可能性がある**。ゲートが一度も開かない場合は `parity9_keep_margin` を下げる方向で校正する。

## 10. スコープ外（YAGNI）

- 13路・19路への展開（9路専用として作る。他サイズは最善手固定にフォールバック）
- 序盤の布石強制（`force_star_opening` 相当）
- 温度サンプリング / 確率的選択
- 一致率のウィンドウ方式（直近N手）— 累計方式で終局レポートが揃うことを優先
- 累積損失予算の別枠管理 — 一致数ゲートが外す頻度を上限づけるため不要と判断

---

## 追記1（2026-08-08）: 一致率を絶対目標へ — 設計の入れ替え

### 動機

GUI 実戦でユーザーから「9路の持碁（`ai:jigo9`）より `ai:parity9` のほうが一致率が高い」と
報告があった。校正局（`parity9-vs-human-20260806-white.sgf`・白19判断）で切り分けた結果、
本モードは§2の設計方針そのものが目標に届かないことが分かった。

**`ai:jigo9` のほうが一致率が低い理由は2つあり、どちらも褒められたものではない**:
(a) jigo は候補構築に visit floor を持たない（`ai.py` の Jigo 候補構築ループ）ので、wRN=0 の
Stage2 が返す 1visit エントリ（生NN評価＝打つ側に楽観的）を「損失の小さい手」として掴む。
(b) jigo は**目差を target に寄せるのが目的**なので、`lead < target_score` では target 最接近手＝
わざと縮める手を打つ。**一致率をリードで買っている**。本モードはリードを守るのが前提なので、
同じ手段は使えない。

### 判明した構造（校正局19判断の全数計測）

`docs/.../calibration-data/parity9/`（プローブは使い捨て）で、各局面の「hp>=0.01 かつ
visits>=10 の非最善候補」を全数数えた:

| 分類 | 手数 | 内容 |
|---|---|---|
| 強制（最善手の humanPolicy >= 0.97） | 5 | 代替手ゼロ。9段も同じ手を打つ |
| 高価（3目以内に人間らしい代替なし） | 4 | 最安 +3.25〜+8.85目 |
| hp 下限でブロック | 1 | loss +1.96 だが hp=0.005 |
| 外せる | 9 | 3目以内に代替あり |

- **「損失0の同値手を拾う」案は在庫ゼロ**: 19局面すべてで `loss <= 0.05` の代替手が **0手**。
  9路 1000visits に厳密な同値手は存在しない。
- **ヨセ（32/34/36/38）の最安代替は +8.85 / なし / +3.25 / なし**。ヨセロックは何も損して
  いない＝「ヨセに無料の在庫がある」という見立ては誤り。
- **相手（人間）は全手番 `opp=0`**。§4.2 の「相手を上回らない」追随目標は、相手が最善手に
  一度も一致しない対局では**100%外さないと達成できない**＝原理的に到達不能だった。

### 変更（4点）

| # | 変更 | 根拠（実測） |
|---|---|---|
| 1 | 候補プールを Stage2 `moveInfos` → **通常解析 `cn.candidate_moves`** | Stage2(wRN=0) は非最善手を 69〜86visits でしか読まず損失が **1.3〜1.8目楽観的**。move 14 F3 は Stage2 +2.54目 / 実際 +4.03目 |
| 2 | 一致数差ゲート → **レートゲート** `parity9_rate_gate` | 旧ゲートは 0-0 で必ず閉じ、**盤面最安の白初手**（0.5目以内に代替7手・最善手 hp 0.194 < D4 hp 0.485）を落としていた |
| 3 | スコア予算 → **着手後の勝率フロア** `parity9_min_winrate`、`keep_margin` 既定 0.0 | 互角局面で予算が必ず 0（move 2: 勝率82% なのにリード 0.99 < margin 1.0） |
| 4 | 選択を「予算内で hp 最大」→ **最安バンド内で hp 最大**（`parity9_cost_slack`） | 旧規則は毎回予算を使い切る（12手で21.2目）。高価な外しほど hp も低い（4〜5目→hp 1.5〜7.9% / 1目未満→hp 37〜60%） |

`parity9_match_margin` は削除し `parity9_target_rate` が置き換える。実効目標は
`max(parity9_target_rate, 相手の一致率)`＝相手が強くて目標まで下げると勝てない対局では
相手と同率程度で止まる（ユーザー要件）。

### 段階別の実測（同一 SGF・白19判断）

| 段階 | Top1 | Top5 | 実損失合計 | mean_ptloss |
|---|---|---|---|---|
| 改修前 | 52.6% | 73.7% | 11.04目 | 0.58 |
| +1 通常解析プール | 57.9% | 73.7% | **5.82目** | 0.31 |
| +2 レートゲート・cap5.0・hp0.5% | 52.6% | 63.2% | 11.07目 | 0.58 |
| +3 勝率フロア・keep 0.0 | 36.8% | 52.6% | 21.23目 | 1.12 |
| +4 コスト最安バンド（確定） | **42.1%** | 68.4% | **13.52目** | 0.71 |

**段階1で一致率が悪化しているのは正しい**。消えた外し1手は「2.54目のつもりで 4.03目
払っていた」偽の外しで、実損失は半減している。**一致率だけで施策を評価してはいけない**
（一致率は損失を過小評価するほど下がる）。

### 既定値の選択

ユーザーが「42% / 約13目」のラングを選択したため、`max_loss_per_move=5.0` /
`min_human_policy=0.005` の緩い側を既定にした。この既定では hp 2.3%（4.90目）と hp 0.7%
（2.02目）の外しが各1手残る。`max_loss_per_move=4.0` / `min_human_policy=0.01` にすると
**52.6% / 約6.6目** になる（どちらもスライダー）。

### 9路の構造的な床

19判断のうち **5手は最善手の humanPolicy が 0.97 以上**で代替手が存在しない。ここで一致
するのは不自然どころか 9段の挙動そのものなので、**一致率を 20%台まで下げることは
「人間らしくない手は打たない」と両立しない**。実測ベースの現実的な下限は 35〜45%。

### 検証の限界

- **n=1**（校正局1局・白番のみ）。相手が強い対局（`opp_rate > target`）で実効目標が上がる
  経路は**実データで踏んでいない**（ユニットテストのみ）。
- §9.3 のとおり `--batch` は固定 SGF の再生なので、外した結果リードが変わる軌跡は再現でき
  ない。予算・勝率フロアの妥当性の最終判断は GUI 実戦の終局レポート。

---

## 追記2（2026-08-08）: スコア予算の撤去 — 安全ゲートを勝率フロアに一本化

### 動機（GUI 実戦 `~/.katrain/logs/game_20260808_221839.log`）

追記1 の設計で **AI 黒番**の実戦を1局打った。26判断の内訳は
外し7 / 予算ゼロ5 / 候補なし4 / ヨセロック10 で、最終一致率は約 73%。
追記1 のバッチ（白番・42.1%）と大きく違う。切り分けた結果、原因は2つとも構造的だった。

**1. `keep_margin` によるスコア予算が黒番の序盤を全滅させていた。**
`scoreLead` は komi 込みなので「lead > 0」は「勝率 > 50%」と同義。9路 komi 7 では
白は序盤からわずかに正だが**黒は負**（実測 depth 0〜8 で lead −0.22〜−0.04）。
`budget = max(0, lead − 0.0) = 0` で早期 return するため序盤5手が問答無用で最善手に
固定され、しかも**追記1 で入れた勝率フロアが一度も評価されないまま**ログには
`no budget` と出ていた。白番（校正局 move 2 は lead +0.99）では通っていた経路で、
**手番の色で挙動が変わる**のが本質的な誤り。

**2. この対局は黒 +2.8〜+4.6 の接戦だった。** 校正局は白 +26 の圧勝。
一致率が高いのは原資が無いからで、**設計どおりの正しい挙動**。

### 変更

- `parity9_keep_margin` と純関数 `parity9_budget` を**削除**。
- 安全判定は**着手後の勝率フロア `parity9_min_winrate` ただ1つ**。`cap = parity9_max_loss_per_move`。
- 新純関数 `parity9_has_admissible(candidates, best_gtp, cap, min_winrate)`。
  `loss` / `wr` / `visits` は通常解析だけで揃うので、**hp を載せる前**に候補の有無を
  判定できる＝§4.1 の「外すと決まるまで humanSL を撃たない」順序を維持する。
  `parity9_build_candidates` から `hp_for_gtp` を外し、hp は Stage1 後に呼び出し側が載せる。
- ログを是正: `no budget (lead=…)` → `Safety: lead=… root_wr=… min_wr=… cap=…` ＋
  落ちた場合 `No admissible candidate (pre-hp): non_best=N min_loss=… max_wr=…`。
  **なぜ外せなかったのかがログで判別できる**。

### 実測

| SGF | | Top1 | Top5 | 実損失 | mean | acc |
|---|---|---|---|---|---|---|
| 校正局（白+26・19判断） | 撤去前 | 42.1% | 68.4% | 13.52目 | 0.71 | 81.5 |
| 校正局（白+26・19判断） | 撤去後 | 42.1% | **73.7%** | **12.35目** | **0.65** | **82.9** |
| 実戦（黒+3〜4・25判断） | 撤去後 | 76.0% | 96.0% | 0.90目 | 0.04 | 99.0 |

外し手数は校正局で 11 のまま**同数**＝一致率は動かない。目的は非対称の除去とログの
是正であって、一致率のレバーではない。実戦 SGF はログから復元して
`calibration-data/parity9/parity9-vs-human-20260808-black.sgf` に保存した。

### 分かったこと（重要）

**序盤を塞いでいたのは予算ではなく勝率フロアだった。** 予算ゲートを**撤去した状態でも**
黒番実戦の move 1〜9 は落ちる（同じログの lead +2.07 → wr 80.3% の対応から逆算すると
序盤の勝率は約48%で、フロア 0.7 はおろか 0.5 でも通らない）。**9路 komi 7 の黒は
開始時点が 50% ちょうどなので、勝率を1%も下げたくないなら序盤は原理的に外せない。**
ここを開けるには「序盤に限り 45% 程度まで許す」という別の緩和が要り、それは
勝ちを落とすリスクを取る判断になる。追記1 の「黒白で天井が違う」は仕様として残る。

### 触らなかったもの（判断の記録）

**ヨセ判定の AND を OR にしない。** 実戦では `unsettled=0`（未確定点ゼロ）が depth 18 から
続いていたのにヨセ判定 `depth>=30 AND unsettled<=8` の手数ゲートが効かず、depth 20〜26 で
5手外していた（うち2手は humanPolicy 5.7% / 2.9%）。ユーザー要件「ヨセ以外」に最も近い
違反だが、**`unsettled=0` は「終局」の信号ではない** — その対局は決着と出てから**さらに
30手打たれている**。OR にすると depth 18 でロックされ外しが 7手→2手（一致率 約92%）に
激減する。`endgame_move=30` は 49手の対局の61%地点で、コードベースの慣習
（9路 `ceil(0.5×81)=41`）よりすでに早い。

### 検証の限界（更新）

- n=2（白番の校正局・黒番の実戦、各1局）。
- 相手が強い対局（`opp_rate > parity9_target_rate` で実効目標が上がる経路）は**まだ実データで
  踏んでいない**（ユニットテストのみ）。相手は2局とも一致率 27% 以下だった。

---

## 追記3（2026-08-08）: 相手レートのブレーキ撤去 + ヨセロックの置換

### 動機

実戦2局（`game_20260808_224752` = parity9・**白番** / `game_20260808_225507` = jigo9）を
ユーザーが比較し「jigo9 のほうが理想に近い」と判断した。

**交絡を先に明記する**: parity9 局は AI +0.07〜5.9目の接戦で相手が **43〜54% 一致**してくる
強敵、jigo9 局は AI +12〜15目の快勝。相手の強さが違うので、両者の一致率の差
（約77% vs 約38%）をそのまま戦略の優劣とは読めない。ただし交絡を除いても構造的な差が2つある。

### A. 実効目標のブレーキは追記1 の実装ミス

追記1 で `eff_target = max(parity9_target_rate, opp_rate)` としたが、根拠にしたユーザー要件は
「相手が強すぎて**全体目標以下では勝てない場合**は相手と同率程度であれば超えてよい」であり、
条件は「**勝てない場合**」。それは安全ゲート（着手後の勝率フロア）が既に処理しているので、
相手のレートで目標を引き上げるのは二重適用だった。実測で **30判断中5回**、安全性とは無関係に
ゲートを閉じるブレーキになっていた。`eff_target = target_rate` に修正（`opp` はログ用に残す）。

### B. ヨセのハードロックを撤回（追記1・追記2 の結論を訂正）

追記1 で「ヨセに無料の在庫はない」と結論したが、**根拠は校正局のヨセ4手だけ**だった。
校正局は38手で終わっており、**本当のヨセに入る前に終局していた**。実戦（60手）で測り直すと
ヨセ帯に安い代替手が実在し、jigo9 も同じ帯で損失 0.00〜0.26 の手を打ち続けている。
この局ではヨセロックが **31判断中16手＝52%** を最善手に固定しており、一致率が下がらない
最大の原因だった。

新スライダー `parity9_yose_max_loss`（既定 0.1目、0 で従来の完全固定）。ヨセでは
`cap = min(max_loss, yose_max_loss)` に絞るだけで、勝率フロアと hp 下限はそのまま効く。
**ダメ詰めや1目ヨセは手順が入れ替わっても目数が動かない**ので、0.1目の手を打つことは
ユーザー要件「ヨセなどは間違えない」に反しない。

### 実測（接戦局・白番30判断）

| | Top1 | Top5 | 実損失 | 外し |
|---|---|---|---|---|
| 修正前（実戦・31判断） | 約77% | — | — | 7（ゲート閉5・ヨセロック16） |
| A+B 後 | **63.3%** | 93.3% | 3.29目 | **11**（ゲート閉0・ヨセロック0、うちヨセ3手） |

ヨセの外し3手の損失は −0.03 / −1.27 / +0.02 ＝実質ゼロコスト。

**ヨセ在庫（AI側15判断）**: 代替手が `≤0.1` で4局面 / `≤0.2` で5 / `≤0.3` で6、
**代替手が存在しないのが6局面**（最善手の hp 0.94〜1.00・探索された手が1つだけ）。
0.1 → 0.3 は +2手・約0.5目で接戦では割に合わないため既定 0.1 を維持。

30判断中19が `no safe deviation`。リード 0.07〜5.9目の接戦なので勝率フロア（60%）が
正しく効いている。**接戦で一致率が上がるのは「必ず勝つ」の帰結**で仕様。

### 計測上の落とし穴（2回踏んだ）

**実戦ログから復元した SGF の「最初の着手の色」を AI の手番と読んではいけない。**
AI の手番は戦略ログの `depth` の偶奇で決まる（`Endgame: depth=1,3,5…` の奇数＝1手打たれた
あとに着手＝**白番**）。この局を `--player B` で回して人間側を評価し、さらに在庫プローブも
`range(1,61,2)` で相手側を測ってしまい、「ヨセ15判断のうち13手に0.5目以内の代替」という
**誤った在庫**を一度報告した（正しくは ≤0.1 で4手）。復元時に AI の手番を判定して記録すること。
