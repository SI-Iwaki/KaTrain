# Lambdago 由来のチート検出メトリックを `--batch` に追加する設計

- 作成日: 2026-04-14
- ステータス: 設計
- 関連リポジトリ: lambdago (https://github.com/egri-nagy/lambdago)
- 関連論文: Egri-Nagy & Törmänen (2020) "Derived metrics for the game of Go - intrinsic network strength assessment and cheat-detection" (arXiv:2009.01606)
- 関連実装: `katrain_debug/batch_eval.py`, `katrain_debug/cli.py`

## 背景

jigo モードは「相手と同じくらいの損失手」を打つ設計で、人間らしさを重視している。これがどれだけ
人間プレイに近いかを定量評価する手段として lambdago の利用を検討した。

論文を精読した結果、以下が判明した:

- lambdago は **チート判定器ではなく可視化補助ツール**。論文は「fully automated cheat detection
  is not possible」と明記している
- 「lambdago で AI 判定されない＝人間らしい」というロジックは成立しない
- 一方、論文の派生メトリック（特に「choice vs candidate median」「勝率 98% 到達後の slack」）は
  既存 `--batch` 集計が持っていない有意義な情報を与える

したがって本設計は **lambdago 全体の組み込みではなく、論文由来の 2 メトリックを既存 `--batch`
集計に追加する診断指標の拡張** とする。

## 目的

lambdago 論文のチート検出指標のうち以下 2 つを `katrain_debug --batch` に追加する:

- **(b) Choice-vs-Median Gap**: 選択手の損失と候補手損失中央値の差
- **(d) Post-98% Slack**: 勝率 98% 到達前後の平均損失差

jigo モードのパラメータ調整時に「人間らしさの方向に動いているか」を定量比較するための
**開発者向け CLI 指標** として用いる。

## 非目的

- KaTrain GUI への表示はしない（KaTrain 本体に変更なし）
- 単一ゲームでの「AI 判定」スコアは出さない（論文も否定）
- グラフ可視化はしない（数値出力のみ）
- 平均 effect 単独表示は追加しない（既存「Avg Loss」と概念重複）
- lambdago 本体（Clojure/JVM）の同梱・サブプロセス呼び出しはしない

## 対象戦略

全戦略。`--batch` を呼べる戦略は全て同じ集計を表示する。
`jigo_metrics` のような戦略固有ブロックではなく、共通の `lambdago_metrics` キーとして配置する。

## 成功基準

1. `--batch` 出力 (`text` / `json` 両形式) に Choice-vs-Median と Post-98% Slack の集計値が表示される
2. 既存の Aggregate Stats / Notable Divergences / `jigo_metrics` の数値は一切変わらない（リグレッションなし）
3. 1 局あたり追加処理コストが 5% 未満（候補リストの median 計算と勝率追跡のみ）
4. ユニットテスト全パス、常識チェック (KataGo 自己対局 SGF と弱い人間棋譜の比較) パス

## アーキテクチャ

### ファイル変更マップ

| ファイル | 変更内容 | 行数目安 |
|---|---|---|
| `katrain_debug/batch_eval.py` | per-move ループに candidate median と winrate を記録、`_aggregate_lambdago_metrics()` を新規追加、`stats["lambdago_metrics"]` として集計結果を返す | +60 行 |
| `katrain_debug/cli.py` | text モード出力に新セクション「Lambdago Metrics」を追加、json モードは自動で含む | +25 行 |
| `tests/test_lambdago_metrics.py` | 新規テスト（KataGo 不要のピュア単体テスト） | +120 行 |
| `katrain/core/ai.py` | 変更なし | 0 |

### 設計判断

- **新規モジュールを作らない**: 計算は KataGo 候補リストの統計処理のみで、独立モジュール化するほど
  のロジック量がない。既存 `_aggregate_jigo_metrics()` と並列の `_aggregate_lambdago_metrics()` として
  同居させる方が一貫する
- **戦略コードに干渉しない**: `katrain/core/ai.py` は触らない。すべて `katrain_debug/` 内で完結
- **CLI フラグを追加しない**: `--batch` 時は常に集計・表示。計算コストが無視できるため

## メトリック定義

### 共通の入力

`batch_evaluate()` の per-move ループ内で取得済みの `cands`（KataGo 候補手リスト）と選択手情報。
各 `cand` には `pointsLost`, `winrate`, `scoreLead`, `order`, `move`, `visits` が含まれる。

### 重要な前提: winrate の視点

KataGo エンジンは `engine.py:108` で `reportAnalysisWinratesAs = "BLACK"` を強制設定している。
**すべての winrate は黒視点で固定** されており、打つ側 (next_player) の勝率を得るには変換が必要:

```python
# parent_node.winrate は手を打つ前の root winrate（手を打った後ではない）
# game_node.py:299-302 で analysis["root"]["winrate"] を返す
wr_black = parent_node.winrate
wr_player = wr_black if player == "B" else (1.0 - wr_black)
```

`parent_node.candidate_moves[0]["winrate"]` ではなく `parent_node.winrate` を使う理由:
前者は「最善手を打った後の winrate」で、Post-98% Slack 検出の本来の関心事である
「現在の局面の勝率（手を打つ前）」と意味的にずれる。差は通常極小だが、勝率 0.98
境界付近で `first_98_move` が 1 手ずれる可能性がある。

### (b) Choice-vs-Median Gap

#### per-move 計算

```python
considered_cands = [c for c in cands if c["order"] < ADDITIONAL_MOVE_ORDER and "prior" in c]
cand_losses = [c["pointsLost"] for c in considered_cands]  # クランプしない（生の pointsLost）
median_loss = statistics.median(cand_losses)  # 候補数 0 の場合は per-move 結果も None
selected_loss = selected_info["pointsLost"]   # クランプしない
choice_vs_median = selected_loss - median_loss
```

フィルタ条件:

- `order < ADDITIONAL_MOVE_ORDER`: それ以降は KataGo が visit していない raw policy 由来の候補で、
  論文の「考慮された候補」の定義から外れる
- `"prior" in c`: policy prior が割り当てられた合法手のみ。既存 `batch_eval.py:121` の
  `filtered_cands` と同じ条件で一貫性を保つ

クランプを行わない理由: 既存 `point_loss` (`max(0.0, pointsLost)`) はユーザー向けの「失った点数」
として 0 下限が自然だが、論文の effect ε(a) は **score mean の差** で負値（思いがけず良い手）も
保持する。Choice-vs-Median は両方を同じ生スケールで引き算する必要があるため、選択手・候補手とも
クランプしない `pointsLost` を使う。これにより既存 `stats[*].mean_ptloss` とは別の数値経路となる
（既存値は不変）。

#### 値の解釈

- **負**: 中央値より良い手を選んでいる（AI 寄り）
- **0 付近**: 中央値あたりを選んでいる（人間寄り）
- **正**: 中央値より悪い手（弱い人間 / 事故）

#### per-aggregate 集計

`overall` / `B` / `W` 別に以下を計算:

- `count`: 集計対象の手数
- `mean`: `choice_vs_median` の算術平均
- `negative_ratio`: `choice_vs_median < -0.5` の比率（明確に AI 寄りの選択をした手の割合）

### (d) Post-98% Slack 検出

#### 勝率到達検出

per-move で各色の親ノード時点の勝率（打つ側視点）を計算し、**初めて 0.98 以上に到達した
move_num** を `first_98_move[player]` として記録する。

```python
wr_black = parent_node.candidate_moves[0]["winrate"]
wr_player = wr_black if player == "B" else (1.0 - wr_black)
if wr_player >= 0.98 and first_98_move.get(player) is None:
    first_98_move[player] = move_num
```

#### per-color 集計

`first_98_move[player]` が存在する場合のみ:

- `pre_98_avg_loss`: 98% 到達前 (move_num < first_98_move) の平均 `point_loss`
- `post_98_avg_loss`: 98% 到達後 (move_num >= first_98_move) の平均 `point_loss`
- `slack_delta = post_98_avg_loss - pre_98_avg_loss`

ここでは既存の **クランプ済み `point_loss`**（`max(0.0, pointsLost)`）を使う。slack 検出は
「勝勢で手が緩むか」というスカラー比較で、負の pointsLost (思わぬ良手) を 0 扱いにしても
50 手以上の平均では実害が小さく、既存 `mean_ptloss` 系の数値スケールと揃う方が解釈しやすい。
choice_vs_median が生の `pointsLost` を使うのと意図的に分ける。

#### 値の解釈

- **0.0 ± 0.3**: 勝率到達後も精度を維持（人間的）
- **+0.5 以上**: 圧勝後に明確に手を緩めている（AI-slack シグネチャ）

98% 未到達の場合は当該プレイヤーの slack 集計はスキップ（`null` 表示）。

### 参照値（出力時の補助表示）

論文記載の経験値を text 出力に併記:

- 強アマ（4 dan+）平均 effect ≈ -0.65 → mean_loss ≈ 0.65
- AI 疑い ≈ -0.25 → mean_loss ≈ 0.25

`choice_vs_median` の典型値域は論文に数値記載がないため、当面は数値のみ表示してユーザー判断に委ねる。

### サンプル数の扱い

- 各メトリックに `count` フィールドを持たせる
- text 出力で `count < 30` の場合は警告マーカー `(low N)` を併記
- 強制エラーや評価拒否はしない

## 出力形式

### text モード

既存 Aggregate Stats の直後に追加:

```
Lambdago Metrics (lambdago paper-derived)
  Reference: human amateur ≈ -0.65 mean loss; AI suspect ≈ -0.25

  Choice-vs-Median Gap (lower = more AI-like):
    Overall: -0.42  (n=180, neg_ratio=58%)
    B:       -0.51  (n=90,  neg_ratio=63%)
    W:       -0.33  (n=90,  neg_ratio=53%)

  Post-98% Slack (positive = sloppy after winning):
    B: not reached
    W: pre=0.31  post=0.84  delta=+0.53  (AI-slack signature)
       reached at move 142 (n_pre=70, n_post=20 (low N))
```

### json モード

既存 `stats` キー配下に `lambdago_metrics` を追加:

```json
{
  "stats": {
    "overall": { "...既存..." },
    "B": { "...既存..." },
    "lambdago_metrics": {
      "reference": { "human_amateur_loss": 0.65, "ai_suspect_loss": 0.25 },
      "choice_vs_median": {
        "overall": { "count": 180, "mean": -0.42, "negative_ratio": 0.58 },
        "B":       { "count": 90,  "mean": -0.51, "negative_ratio": 0.63 },
        "W":       { "count": 90,  "mean": -0.33, "negative_ratio": 0.53 }
      },
      "post_98_slack": {
        "B": null,
        "W": {
          "first_98_move": 142,
          "n_pre": 70,
          "n_post": 20,
          "low_sample": true,
          "pre_98_avg_loss": 0.31,
          "post_98_avg_loss": 0.84,
          "slack_delta": 0.53
        }
      }
    }
  },
  "moves": [
    {
      "move_num": 1,
      "...既存フィールド...": "...",
      "choice_vs_median": -0.45
    }
  ]
}
```

設計上の判断:

- `lambdago_metrics` を `stats` の入れ子キーとして配置（既存 `jigo_metrics` と同階層）。
  既存パスを壊さない
- per-move には `choice_vs_median` のみ追加。winrate は集計用の中間値で per-move 出力には不要
- `low_sample`: bool フラグで JSON 消費側の判定を容易に
- `not reached` / `null`: 98% 未到達は両形式で明示

## テストと検証

### ユニットテスト

`tests/test_lambdago_metrics.py` を新規作成（KataGo 不要のピュア単体テスト）:

| テストケース | 検証内容 |
|---|---|
| `test_choice_vs_median_basic` | 候補3手 (loss=0.0, 1.0, 3.0)、選択=loss 0.0 → median=1.0、gap=-1.0 |
| `test_choice_vs_median_single_candidate` | 候補1手のみ → median = selected → gap=0.0 |
| `test_choice_vs_median_excludes_raw_policy` | `order >= ADDITIONAL_MOVE_ORDER` の候補は除外される |
| `test_choice_vs_median_excludes_no_prior` | `"prior"` キーがない候補は除外される |
| `test_choice_vs_median_no_clamping` | 負の pointsLost (思わぬ良手) もそのまま median に算入される |
| `test_post_98_slack_detection` | 勝率 [0.5, 0.7, 0.99, 0.99] → first_98_move=3、pre=2手、post=2手の平均差 |
| `test_post_98_slack_not_reached` | 勝率全て 0.5 → result=None |
| `test_post_98_slack_winrate_perspective` | 黒視点 winrate=0.02 (白の勝率 0.98) で白の first_98 を検出 |
| `test_aggregate_low_sample_flag` | post の手数<30 → `low_sample=True` |
| `test_b_w_player_split` | 黒白で勝率挙動が違う場合の per-color 集計 |

### 統合テスト（手動実施）

```bash
# 1. 既存 batch 出力に変化なし（リグレッションチェック）
python -m katrain_debug --sgf tests/data/panda1.sgf --strategy hunt --batch --player W \
  --output json > /tmp/before.json
# 実装後
python -m katrain_debug --sgf tests/data/panda1.sgf --strategy hunt --batch --player W \
  --output json > /tmp/after.json
# diff /tmp/before.json /tmp/after.json で差分が lambdago_metrics 追加のみであることを確認

# 2. jigo モードで Post-98% Slack が検出されること
python -m katrain_debug --sgf docs/superpowers/specs/calibration-data/<圧勝SGF> \
  --strategy jigo --batch --output json
# 期待: 勝率 98% 到達後の slack_delta が正の値（圧勝 max_loss 緩和の影響可視化）

# 3. 強い人間棋譜（プロ実戦）vs AI 棋譜の choice_vs_median 比較
# 期待: プロ実戦 → 0付近 / AI 自己対局 → 大きく負
```

### 数値の妥当性検証

論文と数値が合うかは lambdago 本体との突合をしない（B 案の trade-off として承知）。代わりに常識チェック:

- 既知の AI 棋譜（KataGo 自己対局 SGF を 1 局生成）で `choice_vs_median` が大きく負（例: -1.0 以下）
- 既知の弱い人間棋譜（OGS 5kyu 程度）で `choice_vs_median` が 0 付近
- 両方が満たされなければ、median 計算の対象範囲（`order` フィルタ等）を見直す

### Validation の合格条件

1. ユニットテスト全パス
2. リグレッションテスト（既存 json 出力との diff で `lambdago_metrics` 追加分のみ）
3. 常識チェック2件パス
4. CLAUDE.md の `--batch` セクションに lambdago_metrics の説明を 2-3 行追記

## オープン課題

- **強アマ baseline の自前計測**: 論文記載の「-0.65」を信用するか、自前で人間棋譜を集計するかは
  本設計のスコープ外。当面は論文値を参照値として表示するに留める
- **per-move winrate キャッシュ**: 同じ親ノードを複数戦略で評価する場合、winrate 計算が重複する
  可能性がある。現状の `--batch` は 1 戦略 1 ラン前提なので不要だが、将来複数戦略一括評価を
  実装する際に検討
