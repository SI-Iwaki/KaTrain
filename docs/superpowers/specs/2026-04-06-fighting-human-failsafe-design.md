# 力戦派humanモード フェイルセーフ設計

## 概要

力戦派（FightingStrategy）humanモードで、極端なパラメータ設定によりフィルタが厳しくなりすぎて候補が0件になると、フィルタ自体がバイパスされ大悪手が出る問題（フェイルオープン）を修正する。

## 問題

現在の実装（`ai.py` 1690行）:
```python
has_filter = len(good_moves) > 0
```

`good_moves` が空の場合 `has_filter = False` となり、全ての手がフィルタなしで通過する。これは安全側ではなく危険側に倒れる設計。

## 解決策: 二重防御

### 1. パラメータ範囲の制限（constants.py）

極端な設定をGUI上で不可能にする。

| パラメータ | 現在の範囲 | 変更後 |
|---|---|---|
| `proximity_stddev` | 1.0〜10.0 (step 0.5) | 2.0〜10.0 (step 0.5) |
| `fighting_invasion_bonus` | [1.0, 1.5, 2.0, 3.0, 5.0, 8.0, 10.0] | [1.0, 1.5, 2.0, 3.0, 5.0] |
| `fighting_contact_boost` | [1.0, 1.5, 2.0, 3.0, 5.0, 8.0, 10.0] | [1.0, 1.5, 2.0, 3.0, 5.0] |
| `fighting_chaos_relax` | 0.0〜5.0 (step 0.5) | 0.0〜3.0 (step 0.5) |

GUIスライダーのインデックス（`AI_OPTION_INITIAL`）も必要に応じて調整。

### 2. 段階的閾値緩和フェイルセーフ（ai.py）

`_generate_human()` の悪手フィルタで `good_moves` が空の場合、閾値を段階的に緩和して再フィルタ。

#### フロー

```
1. 通常フィルタ（元の閾値 BAD_MOVE_THRESHOLD）→ good_moves
2. if good_moves が空:
   a. 閾値 × 1.5 で再フィルタ → good_moves
   b. まだ空なら 閾値 × 2.0 で再フィルタ → good_moves
   c. まだ空なら 閾値 = 9.0（絶対上限）で再フィルタ → good_moves
   d. まだ空なら best_gtp_by_score を確定選択して return
3. 緩和が発動した場合はログ出力
```

#### 設計詳細

- 緩和ステップ: `×1.5, ×2.0, 9.0目` の3段階
- 既存のフィルタロジック（chaos_relax含む）を再利用。閾値のみ差し替え
- 絶対上限 9.0目を超える緩和は行わない
- 9目でも候補0件の場合は `best_gtp_by_score` を確定選択（安全弁と同様の動作）
- ログ出力例: `[FightingStrategy:human] Filter relaxed: threshold 5.6 -> 8.4, found 3 moves`

## 変更対象ファイル

| ファイル | 変更内容 |
|---|---|
| `katrain/core/constants.py` | パラメータ範囲の制限 |
| `katrain/core/ai.py` | `_generate_human()` に段階的緩和ロジック追加 |
| `CLAUDE.md` | パラメータテーブル更新（範囲変更の反映） |
