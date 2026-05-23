# 迷路戦略（MazeStrategy）設計書 — 9路盤専用・難解化戦略

> **【中止】2026-05-23: この設計は GUI 実機テストの結果、中止しました。**
> 理由: (1) 9路盤では humanSL 9段の相手がほとんど間違えず、期待損失 E に「相手を誤らせる余地」がほぼ無い。(2) E がフラットなため選択が鋭さ項 S と損失バジェットに引っ張られ、最善手を犠牲にした悪手（級段位者でも咎められる手）を連発した。(3) 2手先読み照会（K×2）が逐次実行で遅すぎる。
> 根本的に「完璧に近い相手をハメる」ことは小さい盤では原理的に困難で、トリック戦法は格下相手にしか効かない。実装一式は `feature/maze-strategy-9x9` ブランチに保留（master 未マージ）。以下は中止時点の設計記録。

## 概要

新AIモード `ai:maze`（GUI 表示「迷路」） — **9路盤専用**。相手が最善応手を見つけるのに最も深い読みを要する手を選び、対局を意図的に難解化する戦略。相手が読み切れずに誤れば敗北につながる「双方向に危険」な局面を作り続ける。

上流の既存戦略（Hunt/Siege）が 9路非対応なのに対し、本戦略は 9路盤の空白を埋める。

## コンセプト

- **最優先は難解さ（勝敗は二の次）**: AI は毎回最善手を打つのではなく、相手が長考・誤りやすい手を選ぶ。
- **難解さの測り方は humanSL 期待損失 + 局面の鋭さの組み合わせ（指標 C）**:
  - 「人間（humanSL 9段）が実際に何目損するか」（期待損失 E）
  - 「もっともらしい手ほど大損する＝客観的な読みの深さ」（鋭さ S）
- **損失バジェットはネット評価で自動調整**: 「相手の期待損失 − λ×自分の損失」を最大化し、ワナのリターンが大きい時だけ大きく損を許容する。破綻防止のハード上限を併用。
- **相手モデルは humanSL 9段固定**: 「強豪でも引っかかる難手」だけを選ぶ。弱い相手にはより一層効く。
- 対応盤面: **9路盤のみ**（他サイズは KataGo 最善手にフォールバック）。

## クラス構造

- **クラス名**: `MazeStrategy(AIStrategy)`
- **登録名**: `AI_MAZE = "ai:maze"`
- **配置**: `katrain/core/ai.py`
- **継承**: `AIStrategy`（`JigoStrategy` と同じパターン）
- **選択方式**: 決定的 argmax（温度サンプリングなし。将来オプションとして温度を追加可能）

## アルゴリズム（generate_move）

### 全体の流れ

```
1. wait_for_analysis() で現局面のクリーン解析を取得
   （MazeStrategy は root に humanSLProfile を付けないため moveInfos は clean）
2. 自分の候補手集合を決定:
     own_loss <= maze_hard_cap の手を、KataGo 上位から最大 K=maze_candidates_k 個
3. 各候補 M について 2手先読み照会（並列ディスパッチ）:
     子 Stage 1（humanSL 9段・maxVisits=1）→ 相手の humanPolicy 分布
     子 Stage 2（クリーン・maxVisits=maze_child_visits・wideRootNoise=0）→ 相手応手の clean ptloss
4. 各候補の難解さスコア D(M) を計算
5. ネットスコア N(M) = D(M) − maze_risk_lambda × own_loss(M)
6. N(M) 最大の手を選択
```

### 視点とスコアの扱い（プロジェクト規約準拠）

- KataGo の `scoreLead` は常に Black 視点。`sign = player_sign(next_player)` を掛けて手番視点へ変換。
- `own_loss(M)` = 現局面のクリーン moveInfos から `sign × (best_score − score(M))`。負値（最善超え）は 0 にクランプ。
- 子 Stage 2 の相手応手の `ptloss_opp(r)` も同様に**相手視点**で計算し、`max(0, ptloss_opp(r))` でクランプ。

### 自分の候補手集合（ステップ2）

- 現局面のクリーン moveInfos を own_loss 昇順に並べ、`own_loss <= maze_hard_cap` を満たす上位 K 手を候補とする。
- これにより「破綻手」を最初から除外し、子照会の回数を K に固定する。

### 2手先読み照会（ステップ3）

- `engine.request_analysis(self.cn, ..., next_move=M, extra_settings=...)` で **M を打った後の子局面**を照会する。`next_move` はゲーム木を変更しないため一時ノード生成不要。
- 子局面の手番は相手なので、返る `humanPolicy` は相手の手選択分布、`moveInfos` は相手の応手候補。
- **子 Stage 1**: `{"humanSLProfile": "rank_9d"（Jigo と同じ human_profile 既定値）, "maxVisits": 1}` — humanPolicy 取得のみ（Jigo Stage 1 と同じ軽量クエリ）。
- **子 Stage 2**: `{"maxVisits": maze_child_visits, "wideRootNoise": 0.0}` — クリーンな ptloss 取得用。
- K 個の照会は `PRIORITY_EXTRA_AI_QUERY` で並列ディスパッチし、全完了まで待機（`time.sleep` ポーリング + `engine.check_alive`、Jigo と同じパターン）。

### 難解さスコア D(M)（ステップ4・指標 C）

子 Stage 1 の humanPolicy と子 Stage 2 の ptloss を相手応手 r について突き合わせる:

- **期待損失** `E = Σ_r humanPolicy(r) × max(0, ptloss_opp(r))`
  - 「相手が人間的に打った時に平均何目損するか」。最善応手の humanPolicy が低く、もっともらしい手が大損なほど大きい。
- **鋭さ** `S = Σ_r humanPolicy(r) × max(0, ptloss_opp(r))²`
  - 二乗により大損な応手を強調する重み付き二乗和（分散ではなく二次モーメント）。「双方向に危険な深さ」を表す。安手の小さなワナを抑制し、客観的に難解な局面を優遇する。
- **ブレンド** `D = E + maze_sharpness_weight × S`

humanPolicy の gtp→値ルックアップは Jigo の `_hp_for_gtp` と同じフラット配列インデックス変換を流用する。

### ネット選択（ステップ5・6）

- `N(M) = D(M) − maze_risk_lambda × own_loss(M)`
- argmax で N(M) 最大の手を選択。難解さ優先（λ 小さめ）だが own_loss にペナルティを掛けることで「ワナのリターンに見合わない無駄な損」を避ける。
- ハード上限（maze_hard_cap）が「相手に読み切られても致命傷にならない」範囲を保証 → 「相手が誤れば敗北、読み切れば AI が少し損」という双方向構造を作る。

## パラメータ

| パラメータ | 既定値 | 役割 | GUI |
|---|---|---|---|
| `maze_candidates_k` | 18 | 評価する自分の候補手の数（探索幅） | スライダー（int） |
| `maze_hard_cap` | 8.0 | 自分の1手で許容する最大損失（目）。破綻防止の絶対上限 | スライダー（目） |
| `maze_risk_lambda` | 0.3 | ネットスコアの own_loss 重み（小＝難解さ優先） | スライダー |
| `maze_sharpness_weight` | 0.5 | D の鋭さ項 S のブレンド重み | スライダー |
| `maze_child_visits` | 400 | 子局面 Stage 2 の visits（9路なので軽め） | スライダー（int） |

- humanSL ランクは 9段固定（GUI に露出しない）。
- 既定値は初期推定値であり、self-play 校正後に調整する（特に λ・sharpness_weight）。

## エッジケース・フォールバック

- **9路盤ガード**: 盤面が 9×9 でなければ KataGo 最善手にフォールバック（OUTPUT_DEBUG でログ）。
- **候補ゼロ**（全手が hard_cap 超）: own_loss 最小の手を選ぶ（堅実フォールバック）。
- **子照会失敗**: その候補をスキップ。全候補が失敗した場合は KataGo 最善手（failsafe）。
- **humanPolicy=0 問題**（既知の落とし穴）: 子局面の関連 humanPolicy が全ゼロの候補は E が退化するため、その候補は鋭さ項 S のみで評価する（E=0 扱い）。
- **終盤・確定局面**: ワナが無い（全候補で D≈0）場合、N = −λ×own_loss となり自然に最善手近辺を打つ。難解さ優先でも終盤で破綻しない。
- **パス**: KataGo 最善手がパス（終局）ならパス。

## デバッグログ（debug_level=1）

- `[MazeStrategy] Settings: ...`（初期化時の全パラメータ）
- `[MazeStrategy] Candidates: K=N (own_loss filtered M → K)`
- 候補ごと: `[MazeStrategy] M: own_loss=.. E=.. S=.. D=.. N=..`
- 選択結果: `[MazeStrategy] Selected: <gtp> N=.. (own_loss=.., E=..)`
- フォールバック: `[MazeStrategy] Fallback: <reason>`

## CLI 検証（katrain_debug 拡張）

- `katrain_debug/runner.py` / `cli.py` に `--strategy maze` を追加。
- 単一局面（`--move N`）で**候補手ごとに own_loss / E / S / D / N を表形式表示** → ワナ選択の意思決定を確認可能。
- `--output json` で構造化出力（`result.explanation` に候補テーブルを格納）。

```bash
python -m katrain_debug --sgf <9x9.sgf> --move N --strategy maze --output text
```

## 自動検証（self-play 比較）

本戦略は「相手の誤りを誘発する」のが本質で、固定 SGF のバッチ評価では効果を測れない（trajectory 形成型は batch_eval 不可）。代わりに **self-play 比較**で検証する:

1. `MazeStrategy` vs `humanSL 9段` の自己対局を複数回実行。
2. ベースライン `KataGo 最善手` vs `humanSL 9段` の自己対局を同数実行。
3. 各局で **humanSL 側の実現 mean ptloss** を集計し比較。
4. Maze 側の方が相手（humanSL）の mean ptloss を有意に増やせていれば「難解化」が機能している証拠。
5. 結果を `docs/superpowers/specs/calibration-data/maze/maze-results-<YYYYMMDD>.md` に記録。

補助的に GUI 手動テスト（debug_level=1 でログ確認）も行う。

## 影響ファイル

- `katrain/core/ai.py` — `MazeStrategy` 追加（主たる改修）
- `katrain/core/constants.py` — `AI_MAZE` 定義、`AI_STRATEGIES` / `AI_STRATEGIES_RECOMMENDED_ORDER` 登録、`AI_OPTION_VALUES` にパラメータ登録、`AI_KEY_PROPERTIES`（nan）登録
- `katrain/config.json` — `ai:maze` のパラメータ既定値
- `C:\Users\iwaki\.katrain\config.json`（ユーザーローカル）— 同じパラメータ既定値（**両方必須**、メインセッションで直接編集）
- `katrain/i18n/locales/*/LC_MESSAGES/katrain.po` — 戦略名・パラメータラベル・aihelp 追記 → `python tools/compile_mo.py` で `.mo` 再コンパイル
- `katrain_debug/runner.py`, `katrain_debug/cli.py` — `--strategy maze` 対応

## 設計上の限界・留意点

- **照会コスト**: K=18 個 × 子 Stage 2（400 visits）の照会が1手ごとに発生。9路 TensorRT で目安 6〜10 秒/手。GUI 対局では許容範囲だが、CLI バッチ評価には不向き。
- **9段モデルの保守性**: 相手が humanSL 9段より大幅に弱い場合、9段が引っかからない手を「易しい」と誤判定し、実際にはその弱い相手が引っかかるワナを見送る可能性がある（ユーザー選択により許容）。
- **難解さ優先の代償**: λ が小さいと AI が常に hard_cap 近くまで損を許容し、相手が読み切ると AI が不利になりやすい。ハード上限と λ で調整する。
- self-play 検証は humanSL モデル（`humanlike_model` 設定）が必須。
