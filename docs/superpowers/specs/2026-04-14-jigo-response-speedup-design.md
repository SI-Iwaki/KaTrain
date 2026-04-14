# Jigo 応答速度改善 設計書

## 概要

持碁モード（JigoStrategy）の「相手が打ってから AI が打つまで」の応答時間を、精度を落とさずに短縮する。

- **現状**: 19路・13路で体感 約1秒
- **目標**: 0.5秒以下（約50%短縮）
- **方針**: Stage 1 クエリの `maxVisits` を 800 → 1 に削減

## 背景

`JigoStrategy.generate_move()` は1手生成ごとに2回の逐次 KataGo クエリを投げる:

1. **Stage 1**（humanSLProfile 付き, `maxVisits: 800`）: `humanPolicy` 取得
2. **Stage 2**（クリーン, `maxVisits: 600`）: `moveInfos` と `scoreLead` 取得

合計 1400 visits が相手の手→AI の手の応答時間にそのまま乗っている。

## 設計

### 1. 変更内容

`katrain/core/ai.py` の `JigoStrategy.generate_move()` 内、Stage 1 override のみを変更:

```python
# 変更前
stage1_override = {
    "humanSLProfile": human_profile,
    "ignorePreRootHistory": False,
    "maxVisits": 800,
}

# 変更後
stage1_override = {
    "humanSLProfile": human_profile,
    "ignorePreRootHistory": False,
    "maxVisits": 1,
}
```

Stage 2（`clean_override_settings`）は**変更しない**。候補手の選択・フィルタに使う情報源は完全に維持する。

### 2. 精度維持の根拠

Stage 1 の唯一の出力消費は `stage1_analysis["humanPolicy"]`（`ai.py:914`）。

- `humanPolicy` は humanSL ニューラルネットの **root policy 出力**（raw neural-net policy distribution）
- `maxVisits=1` で root 評価が1回走れば、`humanPolicy` の値は完全に確定する
- MCTS の探索は `moveInfos`（visits/winrate/scoreLead 等）を refinement するが、`humanPolicy` 自体は refinement 対象ではない

したがって Stage 1 の `maxVisits` を 800 から 1 に下げても `humanPolicy` の値は変化せず、`_jigo_filter_candidates` 以降の処理は完全に同じ結果になる。

### 3. リスクとガード

**前提リスク（最重要）**: 「`maxVisits=1` で KataGo が `humanPolicy` フィールドを populate する」という前提が成立しない場合、Stage 1 の早期 failure パス（`ai.py:904` の `"humanPolicy" not in stage1_analysis`）に入り、KataGo 最善手にフォールバックする。これはサイレント障害ではなく既存のエラー経路であり、**ログで即検知できる**（`Stage1 failed, falling back to KataGo top move`）。実装前に smoke test で確認する（「5.4 実装前 smoke test」参照）。

**残存リスク**: Stage 2 が失敗したとき、フォールバック経路（`ai.py:949-954`）で `stage1_analysis` の `moveInfos` が使われる。`maxVisits=1` だと Stage 1 `moveInfos` のスコア精度が低下する。

**ガードと受容理由**:

- Stage 2 の失敗は KataGo エンジン異常時のみの稀な事象
- 失敗時は既存ログ `[JigoStrategy] Stage2 failed, using Stage1 moveInfos (biased)` が出力され、検知可能
- そもそも Stage 1 の `moveInfos` は humanSLProfile によるバイアスがかかっている（現行コードでも「biased」表記）。`maxVisits=1` でも `maxVisits=800` でもバイアス自体は同じ。違いは探索による score refinement の有無のみ
- 現行の退行経路の「質」を同じオーダーに保つため、visits=1 でもこの経路は「バイアスされた粗いスコアで最善手選択」に等しい。既存挙動の質的退行は発生しない

### 4. 想定効果

- Stage 1 は実質「root NN評価1回」まで短縮（数十ms未満オーダー）
- Stage 2（600 visits クリーン）は現状維持
- 合計で体感約 **50-55% の時間短縮**
- 目標 0.5s 以下は十分射程内

### 5. 検証計画

#### 5.1 速度検証（実対局）

- 19路・13路でそれぞれ対局し、相手手→AI手の体感時間を 5-10 手サンプリング
- 目標: **平均0.5s以下**
- 副次的に debug ログで Stage 1/Stage 2 クエリの所要時間を確認（必要なら `time.perf_counter()` で計測を追加）

#### 5.2 精度回帰検証（`katrain_debug --batch` で3run平均）

校正対局 SGF は 2 局:

- 19路: 既存の Jigo 校正 SGF（`docs/superpowers/specs/calibration-data/jigo-*/` に既存のもの、ない場合は `tests/data/ogs.sgf` 等の19路SGFを暫定使用）
- 13路: 既存の13路校正 SGF（または `tests/data/panda1.sgf`）

比較項目（現行 800 vs 変更後 1、それぞれ3run平均）:

| メトリック | 合格基準 |
|---|---|
| Top1 AI一致率 | ±2%以内 |
| Top5 AI一致率 | ±2%以内 |
| 平均損失（mean ptloss） | ±0.1目以内 |
| Choice-vs-Median Gap | ±0.1目以内 |
| Post-98% Slack | ±0.1目以内 |

実行コマンド例（白番評価）:

```bash
python -m katrain_debug --sgf <SGF> --strategy jigo --batch --player W
```

**備考**: CLAUDE.md にあるとおり、`jigo` は温度サンプリングなし（argmax）のため3run分散は極小（0.001〜0.005）。ただし複数 SGF・両色で確認するため3run体制を採る。

#### 5.3 フォールバック発生率の確認

19路・13路の batch_eval 出力ログで `[JigoStrategy] Stage2 failed` の発生数をカウント。通常はゼロのはず。発生している場合は別問題の切り分けが必要。

校正結果の保存先: `docs/superpowers/specs/calibration-data/jigo-speedup/`

- `jigo-speedup-results-20260414.md`
- `run1/`, `run2/`, `run3/` の `--batch` JSON 出力

#### 5.4 実装前 smoke test

Section 3 の「前提リスク」を打ち消すため、`maxVisits=1` 変更後まず **1 手だけ** CLI で実行して `humanPolicy` が populate されるか確認:

```bash
python -m katrain_debug --sgf tests/data/ogs.sgf --move 30 --strategy jigo --output json 2>/dev/null | python -c "import sys,json; d=json.loads(sys.stdin.read()); print('OK' if d.get('selected_hp') is not None else 'FAIL: humanPolicy missing')"
```

- `OK` が返れば `humanPolicy` は populate されており前提成立。検証計画 5.1〜5.3 に進む
- `FAIL` または `Stage1 failed, falling back to KataGo top move` がログに出た場合は前提不成立。`maxVisits=2`, `5`, `10` と段階的に上げて最小値を探る

### 6. ロールバック

`maxVisits: 1` を `800` に戻すだけで復旧できる。他のコード変更はない。

### 7. 将来拡張（案C: 保留タスク）

案A 適用後もさらに改善したい場合は、Stage 2 を既定解析 (`self.cn.analysis`) で置き換える案C を検討する（タスク #5）。

案C 検証のチェックリスト（着手前に確認すべき事項）:

- 既定解析の `maxVisits`（GUI `max_visits` = 800）は Stage 2 の 600 以上で問題ない
- 既定解析に `wideRootNoise` が設定されているか（`analysis_config.cfg` 確認）。Stage 2 は `wideRootNoise=0.0` を明示しているため、既定が非ゼロだとスコアにノイズが乗る
- 既定解析の `ignorePreRootHistory` の扱い
- `self.cn.analysis["rootInfo"]["scoreLead"]` が Stage 2 相当のクリーンな値か確認
- 既定解析が別スレッドで常に完了済みとは限らない。`wait_for_analysis()` の待ち時間も測る

案C が実現可能と判明した場合、Stage 2 省略で追加 40% 程度の短縮が期待される。

## コーディング規約準拠

- コミットメッセージ: 日本語 Conventional Commits (`perf: ...` もしくは `refactor: ...`)
- フォーマット: `black katrain/`（line-length 120）
- 関連ドキュメント更新:
  - `.claude/rules/ai-parameters.md` の Jigo セクション（maxVisits の記述があれば更新）

## 変更影響範囲

- 単一ファイル・単一数値の変更（`katrain/core/ai.py` の Stage 1 `maxVisits`）
- テスト: 既存の `tests/test_ai.py` は humanSL モデルが必要なため環境依存。通しては走らないが、構文回帰は `pytest --ignore=tests/test_ai.py` で確認可能
- GUI 変更なし、設定ファイル変更なし、i18n 変更なし
