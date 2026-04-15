# Jigo 応答速度改善 フェーズ2（既定解析を Jigo 専用に scoped クリーン化）設計書

> **判定: REJECT（2026-04-15）** — 実装後の校正で Jigo の手一致率が 75.5%（KataGo 固有ノイズ ~80% すら下回る）、不一致手の 33% が \|Δloss\|>1.0 目の顕著な損失増加。原因は既定解析 (800 visits, top-move 集中) と Stage 2 (600 visits, 候補均等) の visit 分布差が Jigo の候補プールを変え選択パターンを崩すこと。wideRootNoise は両者とも 0.0 で同等だったにもかかわらず発生。commit `114b654` で revert 済。memory `project_jigo_widerootnoise_impact.md` の「scoreLead 依存戦略の Stage 2 削減は困難」を再確認。校正データと結果サマリは `docs/superpowers/specs/calibration-data/jigo-speedup/phase2-*` に歴史資産として保持。

## 概要

持碁モード（JigoStrategy）の「相手が打ってから AI が打つまで」の応答時間を、精度を落とさずにさらに短縮する第2段階。

- **現状（案A 適用済）**: 19路・13路で約 0.5s（Stage 1 maxVisits 800→1 で 50% 短縮達成）
- **目標**: 約 0.15〜0.2s（追加で 40% 程度短縮）
- **方針**: 次に打つ AI が Jigo のときだけ、既定解析 (`self.cn.analysis`) の `wideRootNoise` を 0.0 に上書きし、Jigo 側で Stage 2 クエリを廃止して既定解析の結果を直接読む

## 背景

### 現状の二段階クエリ

`JigoStrategy.generate_move()` は1手ごとに2回の逐次 KataGo クエリを投げる:

1. **Stage 1**（humanSLProfile 付き, `maxVisits: 1`）: `humanPolicy` のみ取得（`ai.py:876-899`）
2. **Stage 2**（クリーン, `maxVisits: 600`, `wideRootNoise: 0.0`）: `moveInfos` と `scoreLead` 取得（`ai.py:921-946`）

案A 適用後は Stage 1 は実質ゼロ時間まで縮んでいるため、残る応答時間の大部分は Stage 2（600 visits クリーン）に由来する。

### 既定解析との関係

KaTrain は対局中常に auto 走行の既定解析 (`self.cn.analysis`) を持っており、これは `maxVisits=800` で完了する。ただし以下の差があり Jigo はこれを使えていなかった:

- 既定解析の `wideRootNoise` は `engine.config["wide_root_noise"]` 由来（デフォルト 0.04）
- Jigo Stage 2 は `wideRootNoise=0.0` を明示上書きしてクリーンな `scoreLead` を要求

### 案C（過去の REJECT）の経緯

2026-04-14 の校正で「Stage 2 を既定解析 (0.04) で全面代替する案C」は `mean_ptloss` が +0.22〜+0.47 目悪化して REJECT（`docs/superpowers/specs/2026-04-14-jigo-stage2-default-analysis-design.md`、memory `project_jigo_widerootnoise_impact.md`）。

**真因**: wideRootNoise=0.04 由来の scoreLead noise が Jigo の `loss = best_score - score` フィルタ（`max_loss=5.6`）判定をぶれさせる。visits 600→800 の増加では相殺できなかった。

### 本 spec のアプローチ

`wideRootNoise` の上書きを **「次の打ち手が Jigo のときだけ」にスコープ限定** する。これにより:

- Jigo が読む既定解析は `wideRootNoise=0.0`（現 Stage 2 と同等のクリーン）になる
- Jigo 以外の AI モード・対局の既定解析は `0.04` 据え置き → 他戦略への影響ゼロ、GUI レビュー UX 影響ゼロ
- Jigo 側は Stage 2 クエリを削除し、既定解析 (`self.cn.analysis`) を直接読む → 追加 40% 短縮

### Smoke test による事前確認（2026-04-15 実施）

`tests/data/ogs.sgf` 手番30（19路中盤）で `katrain_debug --strategy jigo` + 診断ログで確認:

| 項目 | 結果 |
|---|---|
| `self.cn.analysis["root"]["scoreLead"]` 存在 | ✓ `scoreLead=-1.30`, `winrate=0.383`, `visits=807` |
| `self.cn.analysis["moves"]` 構造 | ✓ gtp→dict の辞書、各要素に `scoreLead`/`order`/`visits` |
| `self.cn.candidate_moves` | ✓ sorted list、`pointsLost` 計算済 |
| `engine.override_settings` の `ignorePreRootHistory` | 未設定（KataGo 内部 default=False）。Stage 2 も明示 False なので両者一致 |
| `engine.config["wide_root_noise"]` | 0.04（想定どおり） |
| `wait_for_analysis()` 所要時間（CLI） | 0ms（runner が事前 wait 済） |

## 設計

### 1. `engine.py` の変更

`KataGoEngine.request_analysis` 内、`settings` 構築直後に Jigo 判定を追加する。

#### 変更前（`engine.py:444-445` 近辺）

```python
settings = copy.copy(self.override_settings)
settings["wideRootNoise"] = self.config["wide_root_noise"]
```

#### 変更後

```python
settings = copy.copy(self.override_settings)
settings["wideRootNoise"] = self.config["wide_root_noise"]
# Jigo 戦略は wideRootNoise=0.0 のクリーンな scoreLead を必要とする。
# 次に打つ側が Jigo の場合のみ既定解析を 0.0 に上書きする（他 AI モード・他戦略への影響は無い）。
try:
    next_player = analysis_node.next_player
    player_info = self.katrain.players_info.get(next_player)
    if player_info is not None and player_info.ai and player_info.strategy == AI_JIGO:
        settings["wideRootNoise"] = 0.0
except Exception:
    pass  # 判定不能時は default 挙動（wide_root_noise 維持）
```

`AI_JIGO` は `katrain.core.constants` からインポートする（既存 import に追記）。

### 2. `ai.py` JigoStrategy の変更

`generate_move()` の Stage 2 ブロック（`ai.py:920-946` 付近）を削除し、既定解析を直接読む形に置き換える。

#### 変更前（概略）

```python
# Stage 2: クリーンクエリ
stage2_override = {"ignorePreRootHistory": False, "maxVisits": 600, "wideRootNoise": 0.0}
stage2_analysis = None
stage2_error = False
# ... コールバック定義 ...
engine.request_analysis(..., extra_settings=stage2_override)
while not (stage2_error or stage2_analysis):
    time.sleep(0.01)
    engine.check_alive(exception_if_dead=True)

if stage2_error or not stage2_analysis:
    self.last_decision_info["score_lead_biased"] = True
    score_analysis = stage1_analysis
else:
    score_analysis = stage2_analysis
move_infos = score_analysis.get("moveInfos", [])
current_lead = score_analysis.get("rootInfo", {}).get("scoreLead", 0) * sign
```

#### 変更後

```python
# Stage 2 削除。既定解析は engine.py 側で wideRootNoise=0.0 が保証されている（Jigo 用 scoped 上書き）
# self.cn.analysis["root"] == 旧 rootInfo / self.cn.candidate_moves == 旧 moveInfos 相当
default_analysis = self.cn.analysis
if not default_analysis or not default_analysis.get("root"):
    # フォールバック: Stage 1 moveInfos を使用（Stage 2 失敗経路相当）
    self.last_decision_info["score_lead_biased"] = True
    self.game.katrain.log(
        "[JigoStrategy] Default analysis unavailable, using Stage1 moveInfos (biased)",
        OUTPUT_DEBUG,
    )
    move_infos = stage1_analysis.get("moveInfos", [])
    current_lead = stage1_analysis.get("rootInfo", {}).get("scoreLead", 0) * sign
else:
    # 既定解析の candidate_moves (sorted) から scoreLead 付き候補を取得
    move_infos = [
        {"move": c["move"], "scoreLead": c.get("scoreLead", 0)}
        for c in self.cn.candidate_moves
    ]
    current_lead = default_analysis["root"].get("scoreLead", 0) * sign
```

`self.cn.candidate_moves` は既定解析が空のとき `policy_ranking` ベースのフォールバックリストを返すため、追加のエラー分岐は不要。

### 3. 参照キー名の差分吸収

| 現 Stage 2（raw KataGo JSON） | 既定解析（`self.cn.analysis`） |
|---|---|
| `score_analysis["moveInfos"]`（list） | `self.cn.analysis["moves"]`（dict, gtp→info）または `self.cn.candidate_moves`（sorted list） |
| `score_analysis["rootInfo"]["scoreLead"]` | `self.cn.analysis["root"]["scoreLead"]` |

候補手を list 形式で扱いたい Jigo の現ロジック（`scores_player = [mi.get("scoreLead", 0) * sign for mi in move_infos]`）は、`self.cn.candidate_moves` を使えば最小差分で置換可能。

### 4. 想定効果

- Stage 1 はすでに maxVisits=1（ほぼゼロ時間）
- Stage 2 の 600 visits 相当の追加クエリが**完全消滅**
- 既定解析は対局中 auto 走行 = Jigo.generate_move() 到達時点で多くの場合は完了済
- 合計で案A (50%) + 今回 (40%) で現行 0.5s → **約 0.15〜0.2s**

## 精度維持の根拠

1. **Jigo 判定の scoreLead 精度**: 既定解析を `wideRootNoise=0.0`（現 Stage 2 と同値）でクリーン化する。visits は既定解析 800 > 現 Stage 2 600 なので精度は同等以上
2. **humanPolicy 経路**: Stage 1（humanSLProfile, maxVisits=1）は今回変更なし。humanPolicy の値は完全に同一
3. **`ignorePreRootHistory`**: 既定解析は未設定（KataGo default=False）、Stage 2 も明示 False。両者一致（smoke test で確認済）
4. **フィルタ・選択ロジック**: `_jigo_filter_candidates` / `_jigo_select_move` / `_jigo_exclude_sharp_moves` / `_jigo_compute_effective_max_loss` / `_jigo_relax_filters` は完全据え置き

残る変動要因は KataGo 並列探索の非決定性 (memory `feedback_batch_eval_variance.md`) のみで、これは現行でも同じ。

## リスクとガード

### R1. `wait_for_analysis()` が実対局で遅延する可能性

Smoke test は runner が事前 wait するため 0ms だったが、実対局では Jigo.generate_move() 起動時に既定解析がまだ完了していない可能性がある。

- **影響**: 待ち時間が Stage 2 削減分を相殺する可能性
- **ガード**: 既定解析は相手の手確定とほぼ同時に auto 発行される（KaTrain の analyze_all_nodes）。Jigo 側の総処理時間は「既定解析 visits 800 完了」が上限で、現行の「Stage 1 が maxVisits=1 + Stage 2 600 visits 逐次」より必ず速いか同等
- **検証**: §5.1 で実対局時間を実測

### R2. `self.katrain.players_info` が未初期化の edge case

`engine.request_analysis` は初期化順序により `katrain.players_info` が未整備の状態で呼ばれ得る。

- **ガード**: `try/except Exception: pass` で判定不能時は既存の `wide_root_noise` 値にフォールバック。Jigo 以外では常に影響ゼロ、Jigo でも「たまたま判定できなかった瞬間」は従来の 0.04 挙動になる（Stage 2 失敗と同クラスの稀事象）
- **検証**: §5.3 で判定ミス発生数をログでカウント

### R3. 判定直後に AI モード切替が起きた場合

ユーザが対局途中で Black/White の AI 設定を変更した場合、手番ごとに wideRootNoise の値が切り替わる。

- **影響**: 最悪でも既定解析の候補手表示が一時的に多様/クリーンのどちらかになるだけ。gameplay への悪影響なし
- **ガード**: 不要（現行仕様として許容）

### R4. Stage 2 フォールバック経路の扱い

現行コード（`ai.py:949-954`）は Stage 2 失敗時に Stage 1 の biased `moveInfos` を使う仕組み。本 spec では既定解析が無い／不完全なときに Stage 1 フォールバック相当の経路を残す。

- **ガード**: `self.cn.analysis` または `self.cn.analysis["root"]` が None のとき biased フォールバックを発動。`last_decision_info["score_lead_biased"]=True` もセットし、既存の batch_eval 互換を保つ

### R5. `candidate_moves` のフォールバック経路との整合性

`self.cn.candidate_moves` は既定解析がほぼ無い場合に `policy_ranking` ベースの単一要素リストを返す。この場合 Jigo のフィルタ処理は候補1件 = KataGo top policy 手をそのまま選ぶ挙動になり、既存の「Stage 2 失敗時 Stage 1 fallback」と機能的に同等。

## 検証計画

保存先: `docs/superpowers/specs/calibration-data/jigo-speedup/` (既存ディレクトリに追加)

- `phase2-results-20260415.md`（または実施日付）
- `phase2-{before,after}-{game}-{color}-run{1,2,3}.json`

### 5.1 実対局での応答時間計測

**目的**: R1 の実測確認。

- KaTrain 本体起動 → 19路 Jigo 対局 → 相手手→AI手の経過時間を 5-10 手サンプリング（ストップウォッチ）
- 同じ手順を 13路でも実施
- 目標: **平均 0.2s 以下**

補助として debug level=1 で `[JigoStrategy]` ログの時刻差分を `Starting move generation` と `Selected:` の間で計測。

### 5.2 精度回帰検証（`katrain_debug --batch` で3run平均）

校正 SGF（既存）:

- 19路: `docs/superpowers/specs/calibration-data/jigo-speedup/` 配下の既存 Jigo SGF（案A で使用したものを再利用）
- 13路: `katrain-13ro-20260401-game1.sgf`, `game2.sgf`

比較項目（**案A 適用後の現行** vs **本 spec 適用後**、各 3run 平均）:

| メトリック | 合格基準 |
|---|---|
| Top1 AI一致率 | ±2% 以内 |
| Top5 AI一致率 | ±2% 以内 |
| 平均損失（mean ptloss） | ±0.1 目以内 |
| Choice-vs-Median Gap | ±0.1 目以内 |
| Post-98% Slack | ±0.1 目以内 |

実行コマンド例:

```bash
python -m katrain_debug --sgf <SGF> --strategy jigo --batch --player W
python -m katrain_debug --sgf <SGF> --strategy jigo --batch --player B
```

**重要**: 校正データは **案A 適用済コードの再採取** を before として取り直す。案C REJECT 時の旧 before データ（wideRootNoise noise で汚染された可能性のある基準）は使わない。

### 5.3 フォールバック・判定ミス発生率

19路・13路の batch_eval 出力ログで以下を確認:

- `[JigoStrategy] Default analysis unavailable` の発生数（R4: 想定ゼロ）
- `last_decision_info["score_lead_biased"]=True` の発生数
- engine.py 側の Jigo 判定 try/except 例外ログ（§5.1 実対局時に debug level=1 で観察）

### 5.4 実装直後の動作確認（post-implementation smoke test）

§2 の engine.py 変更が入った状態で、既定解析に `wideRootNoise=0.0` が適用されていることを確認する。

確認手段（どちらかで可）:

(a) 一時診断ログで検証: `engine.py` の `settings["wideRootNoise"] = 0.0` セット直後に `self.katrain.log(f"[JigoScoped] wideRootNoise={settings['wideRootNoise']}", OUTPUT_ERROR)` を入れて `katrain_debug --sgf tests/data/ogs.sgf --move 30 --strategy jigo` を実行。Jigo 判定経路で 0.0 ログが出ることを確認後、診断ログを撤去。

(b) Jigo の既存ログ観察: `[JigoStrategy] Selected:` ログに表示される `score` が現 Stage 2 実行と同等（±0.05 目）であれば事実上クリーン化されている証拠。

実装完了後、`[JigoStrategy] Default analysis unavailable` が出ていないことも同時に確認する（= Stage 2 削除後のフォールバック経路が誤発動していないこと）。

## ロールバック

単一コミットで revert 可能。ロールバック操作:

1. `engine.py` の Jigo 判定 try ブロック削除
2. `ai.py` JigoStrategy の Stage 2 ブロックを復元

両ファイルとも git 履歴から戻せば Stage 2 クエリ方式に即復帰する。

## 影響範囲

| 対象 | 影響 |
|---|---|
| JigoStrategy の手選択 | **なし**（scoreLead 精度は現 Stage 2 同等以上。humanPolicy は変化なし） |
| 他戦略 HumanStyle/Fighting/Siege/Hunt/Divergence 等 | **なし**（`wideRootNoise` 上書きは Jigo 専用） |
| GUI レビュー UX（Jigo 以外のモード） | **なし**（既定 0.04 据え置き） |
| GUI レビュー UX（Jigo 対局中、Jigo の手番） | 候補手リストの下位候補が argmax 寄りに集中（UX 実害は軽微） |
| 他戦略の校正データ | **不要**（再取得しない） |
| Jigo の校正データ | §5.2 で before/after を取り直す（`phase2-*` 命名で既存と区別） |
| i18n | なし |
| 設定ファイル / GUI 設定項目 | なし |
| KataGo エンジン設定 (`analysis_config.cfg`) | なし |

## コーディング規約準拠

- コミットメッセージ: 日本語 Conventional Commits（`perf(jigo): ...` を推奨）
- フォーマット: `black katrain/`（line-length 120）
- 関連ドキュメント更新:
  - `.claude/rules/ai-parameters.md` の Jigo セクション — Stage 2 の記述を「既定解析 (Jigo-scoped clean) 使用」に更新
  - CLAUDE.md の「KataGo 解析結果の扱い」セクション — 必要なら Jigo の既定解析利用を注記

## 変更影響範囲（ファイル単位）

- `katrain/core/engine.py`: 判定ブロック 7-10 行追加（import 含む）
- `katrain/core/ai.py`: `JigoStrategy.generate_move()` の Stage 2 ブロック約 30 行削除＋既定解析読み替え約 15 行追加
- `.claude/rules/ai-parameters.md`: Jigo 関連の表記更新（文字列 5-10 行）
- `docs/superpowers/specs/calibration-data/jigo-speedup/`: 新規 `phase2-*` ファイル群

テスト: 既存 `tests/test_ai.py` は humanSL モデル必要（環境依存）。構文・非 AI 系は `pytest --ignore=tests/test_ai.py` で確認。
