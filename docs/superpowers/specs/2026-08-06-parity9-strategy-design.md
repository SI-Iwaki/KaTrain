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

**Stage2（clean、先に撃つ）** — `DivergenceStrategy` の Stage2 と同形 + ownership:

```python
engine.request_analysis(
    self.cn, callback=..., error_callback=...,
    priority=PRIORITY_EXTRA_AI_QUERY,
    include_policy=False,
    ownership=True,                       # _enable_ownership=false をバイパス
    extra_settings={"ignorePreRootHistory": False, "maxVisits": 600, "wideRootNoise": 0.0},
)
```

**Stage1（humanSL、外すと決まってから撃つ）**:

```python
engine.request_analysis(
    self.cn, callback=..., error_callback=...,
    priority=PRIORITY_EXTRA_AI_QUERY,
    include_policy=True,
    extra_settings={"humanSLProfile": "rank_9d", "ignorePreRootHistory": False, "maxVisits": 800},
)
```

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

`parity9_max_loss_per_move` は 1.5→3.0 に緩和した。同じ実戦で AI の19回の判断のうち発火（一致数ゲート開・予算内で外した）4回の損失はいずれも旧上限 1.5 のすぐ下（B5: 1.41 / E9: 0.61 / G9: 1.19 / J3: 1.48）に張り付き、さらに6回は「予算内に非最善候補が無い」として外せずに終わった。予算（`lead - keep_margin`）自体は 5.9〜23.7目と十分に余裕があったため、1手キャップ 1.5 がボトルネックだったと判断し 3.0 へ引き上げた。バッチ再生（`--batch`、固定SGFのため軌跡再現はできない）でも1.5→3.0で `ai_top_move` 84.2%→78.9%・`mean_ptloss` 0.09→0.19 と、外す頻度が増える向きに動くことを確認した。

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
