# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## プロジェクト概要

KaTrain v1.17.1.1 の修正版ソースコード。囲碁AI学習ツール。Python 3.12環境。

- 上流リポジトリ: https://github.com/sanderland/katrain
- ランタイム設定・データディレクトリ: `C:\Users\iwaki\.katrain\`

## 起動方法

```
cd C:\Users\iwaki\Documents\katrain-1.17.1.1\katrain-1.17.1.1
python -m katrain
```

## GPU環境

NVIDIA GeForce RTX 3080。KataGoエンジン（v1.16.4 TensorRT版）を使用。

## 主な改修箇所

### Human-like AIの悪手フィルタ（`katrain/core/ai.py`）

**課題**: Human-like（9段）モードで、9段が絶対にしないような大悪手（6目以上の損失）を打つ。原因はオリジナルのKaTrainがhumanPolicyの重みでランダム選択するだけで、手の良し悪しをフィルタしていないため。

**修正内容**: `HumanStyleStrategy.generate_move()` にフィルタを追加。

- KataGoの`moveInfos`（探索結果）で各手のスコアを取得
- 現在の手番プレイヤーの視点で最善手スコアを計算（`player_sign`で黒白を正しく処理）
- 最善手から`BAD_MOVE_THRESHOLD`以上損する手を除外
- `moveInfos`に含まれない手（探索されなかった手）も除外
- 残った手の中からhumanPolicyの重みでランダム選択

**重要な実装メモ**:
- KataGoの`scoreLead`は**常にBlackの視点**（正 = Black有利）。Whiteの場合は符号反転が必要。
- 参照点は`move_infos[0]`（最多探索手）ではなく、現在プレイヤーにとっての**真の最善スコア**を使う。
  - `move_infos[0]`はhumanSLProfileの影響で最善手≠最多探索手になることがある。
- `player_sign = 1 if Black else -1` を使い `loss = player_sign * (best_score - score)` で計算。

**重要なパラメータ**:

- フェーズ別閾値（序盤と中盤・終盤で異なる閾値を使用）
  - **19路・13路（デフォルト）**
    - `OPENING_THRESHOLD`: 現在 **2.8**（序盤の閾値）
    - `NORMAL_THRESHOLD`: 現在 **5.0**（中盤・終盤の閾値）
  - **9路盤専用**
    - `OPENING_THRESHOLD`: 現在 **0.5**（序盤: 0.5目以上の損失手は打たない）
    - `NORMAL_THRESHOLD`: 現在 **3.3**（中盤・終盤: 3.3目以上の損失手は打たない）
  - 序盤境界: `math.ceil(0.14 × 盤面マス数)` — 評価レポートの「序盤」と一致（19路: 1〜50手目、9路: 1〜11手目）
  - 小さいほど強い（悪手が減る）が、人間らしさも減る
  - 3.5〜4.0が6目以上の損失をほぼゼロにする安定域（19路・黒白両方でフィルタ正常化後）
- **大差フィルター（9路盤・13路盤）**: `analysis["rootInfo"]["winrate"]` を使用。`rootInfo.winrate` は常にBlack視点のため、White番は `1.0 - winrate` で変換。
  - **大差勝ち（勝率95%+）**: 最善手（`best_gtp_by_score`）を除外し、`GREEN_MOVE_THRESHOLD`以内の緑手のみからhumanPolicy重みで選択。緑手がない場合・推奨手が最善手のみの場合は最善手を打つ（`return`で確実に実行）。`WIN_RATE_THRESHOLD = 0.95`
  - **大差負け（勝率25%未満）**: humanPolicyを無視して最善手のみを打つ。勝率が50%を超えるまで継続（ヒステリシス）。状態は `self.game._human_ai_big_loss_mode` で管理。`BIG_LOSS_ENTER = 0.25` / `BIG_LOSS_EXIT = 0.50`
  - **`GREEN_MOVE_THRESHOLD`**: 9路盤=**1.0目**、13路盤=**1.5目**。最善手から1.5目以内の手のみ「緑手」と判定して選択対象にする。これより大きい損失の手（黄・オレンジ）は大差勝ち時に選ばれない。

- `maxVisits`: 現在 **600**（`override_settings`内）
  - 事後分析の探索数と一致させることが重要（不一致だとフィルタが不安定になる）
  - `C:\Users\iwaki\.katrain\analysis_config.cfg` の最大探索手数と合わせる（現在600で統一）
  - 400に下げるとフィルタ精度が落ち、6目以上の悪手がすり抜ける可能性あり

## パラメータ調整時の変更箇所チェックリスト

> **ルール**: パラメータを変更したら、必ず CLAUDE.md の現在値も同時に更新すること。

### `OPENING_THRESHOLD` / `NORMAL_THRESHOLD` を変更する場合

- [ ] `katrain/core/ai.py` の `HumanStyleStrategy.generate_move()` 内（盤面サイズ別の条件分岐）
- [ ] CLAUDE.md の「重要なパラメータ」欄の現在値を更新

### `maxVisits` を変更する場合
**3箇所を必ず同じ値に揃える**（不一致だとフィルタが不安定になる）

| 場所 | 設定項目 | 役割 |
|------|----------|------|
| `katrain/core/ai.py` 約1325行目 | `override_settings["maxVisits"]` | HumanSL着手選択クエリ |
| KaTrain GUI「分析時の最大探索手数」→ `C:\Users\iwaki\.katrain\config.json` | `max_visits` | 事後分析クエリ |
| `C:\Users\iwaki\.katrain\analysis_config.cfg` 51行目 | `maxVisits` | リクエスト未指定時のデフォルト |

- [ ] `katrain/core/ai.py` — `override_settings` の `"maxVisits": XXX`（約1325行目）
- [ ] KaTrain GUI「エンジン設定 → 分析時の最大探索手数」で変更 → 「設定を更新」
- [ ] `C:\Users\iwaki\.katrain\analysis_config.cfg` — `maxVisits = XXX`（51行目）

> **注意**: GUIから変更すると `config.json` に保存される。`analysis_config.cfg` はデフォルト値のため優先度低いが、揃えておくと安全。

## HumanStyleStrategyに新しいAI設定を追加する手順

### 必須変更ファイル（3箇所）

| ファイル | 変更内容 | 理由 |
|------|----------|------|
| `katrain/core/constants.py` | `AI_OPTION_VALUES` に新キーを追加 | GUIのウィジェット種別を決定する |
| `katrain/config.json`（パッケージ） | `"ai:human"` にデフォルト値を追加 | 初回起動時のデフォルト設定 |
| `C:\Users\iwaki\.katrain\config.json`（ユーザー） | `"ai:human"` に同じキーを追加 | **GUIは保存済みキーのみ表示する**。ここにないと設定画面に出ない |

> **落とし穴**: `constants.py` だけ更新してもGUIに表示されない。両方の `config.json` にキーを追加しないとチェックボックス/スライダーが現れない。

### 設定の型とウィジェット対応

| `AI_OPTION_VALUES` の値 | GUIウィジェット |
| --- | --- |
| `"bool"` | チェックボックス |
| `range(...)` or `[...]` | スライダー |
| `[(value, label), ...]` | スライダー（ラベル付き） |

### `ai.py` での設定読み取り

```python
self.settings.get("your_new_setting", default_value)
```

### humanPolicyの罠（重要）

`modern_style=true` の高段者プロファイルは現代布石（3-3等）を好むため、星点（4-4）などの手に `humanPolicy=0` を返すことがある。
フィルタで `moves` リストに入らない手を**強制したい場合**は、`human_policy[idx]`が0でもMoveを直接生成するフォールバックが必要：

```python
star_moves = [(m, w) for m, w in moves if m.coords in target_stars]
if not star_moves:
    for (sx, sy) in target_stars:
        if self.game.board[sy][sx] == -1:
            idx = (board_size[1] - sy - 1) * board_size[0] + sx
            weight = human_policy[idx] if idx < len(human_policy) and human_policy[idx] > 0 else 1.0
            star_moves.append((Move((sx, sy), player=self.cn.next_player), weight))
```

### チェックリスト（新機能追加時）

- [ ] `katrain/core/constants.py` — `AI_OPTION_VALUES` に追加
- [ ] `katrain/core/ai.py` — `HumanStyleStrategy.generate_move()` にロジック追加
- [ ] `katrain/config.json` — `"ai:human"` にデフォルト値追加
- [ ] `C:\Users\iwaki\.katrain\config.json` — `"ai:human"` に同じキー追加
- [ ] CLAUDE.md を更新（新機能の説明、パラメータ等）

## ランタイム設定ファイル（`C:\Users\iwaki\.katrain\`）

- `config.json` — KaTrain全体の設定（エンジンパス、モデルパス、AI設定等）
- `analysis_config.cfg` — KataGo解析エンジン用設定
- `katago.exe` — KataGoエンジン本体

## 未完了の検証タスク（`feature/13x13-big-diff-filter` ブランチ）

> 確認完了後に master にマージし、このセクションを削除すること。

### 大差フィルター（13路盤）の動作確認

**現在のブランチ**: `feature/13x13-big-diff-filter`（コミット済み、未マージ）

**確認済み**:
- [x] 大差勝ち（95%+）時に最善手以外が打たれること（13x13 big win ログ）
- [x] 大差負け（25%-）時に最善手のみ打たれること（13x13 big loss ログ）
- [x] 黄色以上の損失手（1.5目超）が大差勝ち時に選ばれないこと

**未確認・調査中**:
- [ ] 大差勝ち（緑手なし）のとき確実に最善手が打たれるか
  - 症状: 勝率100%・緑手がH11のみ（-0.0）のはずが、B6（-2.8）が打たれた（画像で確認）
  - 修正済みコード（commit 79050c8）で `return` を追加したが、再起動後の再確認中
  - **デバッグ方法**: `config.json` の `debug_level: 1` にして `python -m katrain` 起動、ターミナルに `13x13 big win` ログが出るか確認
  - 問題が続く場合: `best_gtp_by_score` が何になっているかをデバッグログで確認

**デバッグ有効化手順**:
```
C:\Users\iwaki\.katrain\config.json の "debug_level": 0 → 1 に変更
python -m katrain で起動
確認後 debug_level を 0 に戻す
```
