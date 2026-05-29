# Jigo 三連星強制オプション 設計書

- 日付: 2026-05-30
- 対象戦略: `JigoStrategy`（`katrain/core/ai.py`）
- 関連: `HumanStyleStrategy.force_star_opening`（2連星）を共有ヘルパー化して流用

## 1. 背景・目的

jigo モード（持碁戦略）に、序盤の星打ちを強制するオプション `jigo_force_sanrensei` を追加する。設定画面（jigo 設定 UI）のチェックボックスでオン・オフできる。

- **黒番**: 序盤に一辺へ沿った三連星（隅星2つ＋中辺の星1つ）を強制する
- **白番**: 既存の2連星と同一挙動（同辺の隅星2つ。相手が星にいれば対角隅へ）

### 現状認識の訂正

実装着手前の調査で判明した重要点：

- 「序盤に必ず2連星を作る」オプション `force_star_opening` は **`JigoStrategy` ではなく `HumanStyleStrategy`（Human-like AI モード）に実装済み**（`ai.py:2975-3021`）。JigoStrategy には序盤布石を強制する仕組みは存在しない。
- 既存2連星は隅の4星（4-4点）のみを対象とする（`_get_corner_star_points`）。三連星は **中辺の星**を含むため、対象座標を側辺ライン単位へ拡張する必要がある。中辺の星が存在するのは実質 **19路盤のみ**。

## 2. スコープ（確定した要件）

| 項目 | 決定 |
|------|------|
| 対象盤面 | **19路盤のみ**。13路・9路では何もしない（オプション無効） |
| 黒番の挙動 | 三連星（一辺の3星点を占める） |
| 白番の挙動 | 2連星（既存 `force_star_opening` と同一）。説明文で白番挙動を明記 |
| コード構成 | 星打ち布石ロジックを共有ヘルパー関数へ抽出（アプローチ A） |
| UI | jigo 設定画面のチェックボックス。デフォルト OFF |

非スコープ（YAGNI）:
- 13路・9路向けの三連星近似（中辺星が無いため対象外）
- 三連星のライン選択をユーザーが指定する機能（humanPolicy 重みで自動選択）
- 手数による打ち切り設定（既存2連星同様、ステートレスに「完成 or 塞がれ」で自然停止）

## 3. アーキテクチャ

### 3.1 共有ヘルパー（アプローチ A）

`ai.py` にモジュール関数を追加し、HumanStyle と Jigo の両方から呼ぶ。

```
_compute_star_opening_targets(board_size, stones, ai_player, n) -> set[tuple[int,int]]
```

- 引数:
  - `board_size`: `(bx, by)`
  - `stones`: `self.game.stones`（座標・色を持つ石のリスト）
  - `ai_player`: `"B"` / `"W"`
  - `n`: 一辺に揃える星石数。`2`=2連星、`3`=三連星
- 返り値: 次に打つべき星点座標の集合。強制不要・完成済み・盤面非対応なら **空集合**。

補助関数:
- `_get_corner_star_points(board_size)` — 既存。隅4星を返す。
- `_get_star_lines(board_size)` — 新設。4辺それぞれの星点列（隅2＋中辺星の3点コリニア集合）を返す。19路では各辺3点。`n=3` 用。

#### `n=2`（既存2連星ロジックの移植・挙動不変）

`HumanStyleStrategy` の現行インライン処理（`ai.py:2986-3001`）を関数化したもの。隅4星のみを使う。

- AI 星石 0 個:
  - 相手が星にいる → その対角隅星（空きなら）。無ければ空き隅星全体
  - 相手が星にいない → 空き隅星全体
- AI 星石 1 個 → その星と同辺（同じ行 or 列）の空き隅星
- AI 星石 2 個以上 → 空集合（停止）

#### `n=3`（新規・三連星）

`_get_star_lines` の各辺（3点コリニア）に対し評価する。相手石が1つでも乗っているラインは「塞がれ」として除外。

- AI 星石 0 個 → 任意の空き隅星（= 全隅星のうち空き。三連星はどの隅からでも開始可能）
- 有効ライン（AI 石 ≥1 かつ相手石 0）が存在する場合:
  - AI 石数が最大の有効ライン群を選び、その上の空き星点を target とする
  - AI 石 1 個のライン → 残り2点が候補（同辺隅・中辺星）
  - AI 石 2 個のライン → 残り1点（中辺星 or 残隅）で三連星完成
- AI 石 3 個が一直線に揃ったライン → そのラインは完成。他に未完ラインが無ければ空集合（停止）
- 有効ラインが存在しない（全て塞がれ／AI 石が孤立しコリニア化不能）→ 空集合（通常 jigo へフォールバック）

> 補足: 隅星は2つの辺ラインに属する。AI 石1個が隅星のとき、その隅を通る2ラインの空き点が候補になり、humanPolicy で実際の伸長方向が決まる。AI 石が同辺2点に揃った時点でラインが一意化し、残り点へ収束する。

### 3.2 呼び出し側

#### `HumanStyleStrategy`（回帰なし）

`ai.py:2975-3021` の `force_star_opening` ブロックを次へ置換:

```python
if self.settings.get("force_star_opening", False) and moves:
    target_stars = _compute_star_opening_targets(board_size, self.game.stones, self.cn.next_player, n=2)
    if target_stars:
        # 既存の moves 制限 + humanPolicy=0 フォールバック生成（現行コード維持）
        ...
```

返り値適用部（moves を星点候補へ絞り込み、候補が無ければ `human_policy[idx]` から直接 Move 生成）は現行ロジックをそのまま維持する。**挙動不変**を回帰テストで担保する。

#### `JigoStrategy`（Stage 1 直後に短絡）

挿入位置: `human_policy = stage1_analysis["humanPolicy"]` の直後（`ai.py:1111` 以降）、Stage 2 クエリの前。

```python
if self.settings.get("jigo_force_sanrensei", False) and max(self.game.board_size) == 19:
    n = 3 if self.cn.next_player == "B" else 2
    target_stars = _compute_star_opening_targets(self.game.board_size, self.game.stones, self.cn.next_player, n=n)
    if target_stars:
        # target のうち humanPolicy 最大の点を選択（同値は座標ソートで決定的）
        # humanPolicy=0 でも空きマスなら強制（HumanStyle と同じフォールバック思想）
        # 即 return（Stage 2・target 選択・deception は通らない）
        return aimove, "Jigo force sanrensei: ..."
```

- `target_stars` 非空 → Stage 2 をスキップして短絡 return
- `target_stars` 空（完成済み・塞がれ・白で2連星完成・非19路）→ 従来フロー継続

### 3.3 データフロー（jigo, 強制発動時）

```
Stage 1 query (humanPolicy, maxVisits=1)
   ↓
_compute_star_opening_targets(n=3 黒 / n=2 白)
   ↓ 非空
target の中で humanPolicy 最大の星点を選択
   ↓
即 return（Stage 2 / target 選択 / deception を経由しない）
```

- 序盤の星打ちは損失 ≒ 0 のため、jigo の目標目差ロジックと干渉しない
- `self.game._jigo_last_current_lead` は更新しない（lead 未計算のため）
- `last_decision_info.score_lead` は `None` のまま

## 4. 変更ファイル一覧

| ファイル | 変更内容 |
|------|----------|
| `katrain/core/ai.py` | `_get_star_lines` 新設、`_compute_star_opening_targets` 新設、HumanStyle の置換、Jigo の短絡挿入 |
| `katrain/core/constants.py` | `AI_OPTION_VALUES["jigo_force_sanrensei"] = "bool"`、`AI_OPTION_ORDER` へ順序追加 |
| `katrain/gui/popups.py` | `max_options` 16 → 17 |
| `katrain/config.json` | `ai:jigo` に `"jigo_force_sanrensei": false` |
| `C:\Users\iwaki\.katrain\config.json`（ユーザーローカル） | 同上（**メインセッションで直接 Edit**。GUI は保存済みキーのみ表示するため必須） |
| `katrain/i18n/locales/jp/.po` / `en/.po` | msgid `jigo_force_sanrensei` 短ラベル ＋ jigo 説明文へ白番挙動を追記 |
| `.claude/rules/ai-parameters.md` / `CLAUDE.md` | パラメータ表へ追記 |

### 4.1 UI 制約（重要）

- `ConfigAIPopup.max_options`（`popups.py:398`）は現在 **16**。jigo は既に 16 項目（上限）を使用しているため、17 個目を追加すると `GridLayoutException: Too many children in GridLayout` が発生する。**`max_options` を 17 に引き上げる**（全戦略共通のグリッド行数。空行が1行増えるのみで他戦略に悪影響なし）。
- `AI_OPTION_ORDER` の jigo 群（4-15）に `jigo_force_sanrensei` を挿入。deception 群の前（例: 11）に入れて以降を繰り下げるか、末尾（16）に置く。実装時に決定。

### 4.2 i18n

- 短ラベル msgid `"jigo_force_sanrensei"`:
  - jp: 例「三連星強制（黒）」
  - en: 例 "Force sanrensei (Black)"
- jigo 戦略説明文（`aihelp:` 相当の長文 msgstr）へ追記:
  - jp: 「jigo_force_sanrensei: ON で 19路盤の序盤に星打ちを強制（黒番=三連星、白番=二連星）。13路・9路では無効。」
  - en: 同義
- `.po` 編集後は **`python tools/compile_mo.py` で `.mo` を再コンパイル**（必須）

## 5. テスト

ヘルパーは Kivy 非依存の純関数として実装し、ユニットテスト可能にする。

- **`n=2` 一致**: 既存2連星と同一の target を返すこと（黒0/1/2石、白の対角ケースの代表局面）
- **`n=3` 各段階**:
  - 黒0石 → 全隅星
  - 黒1石（隅星）→ その隅を通る2ラインの空き星点
  - 黒2石（同辺）→ 残り1点（中辺星）
  - 相手石で塞がれたライン → そのラインを除外
  - 三連星完成 → 空集合
- **盤面ガード**: 13路・9路で `n=3` が空集合（または呼び出し側でガード）
- **HumanStyle 回帰**: `force_star_opening` 既存挙動が不変
- **Jigo 短絡**: 19路黒で序盤に三連星点を返し、完成後は通常フローへ戻る

AI 系テストは humanSL モデルが必要なため、純関数ヘルパーのテストはモデル不要で実行できるよう分離する。

## 6. 設計上の限界・注意

- 三連星は黒の布石概念。白は隅を取られるため三連星を作れず、要件通り2連星に縮退する。
- 相手が序盤からライン上の星点へ侵入してきた場合、塞がれたラインは除外され、有効ラインが無くなれば強制は停止して通常 jigo に戻る（無理な布石を続けない）。
- `modern_style` 系の高段者 humanPolicy は星点に 0 を返すことがあるため、target が humanPolicy=0 でも空きマスなら強制する（HumanStyle 既存フォールバックと同じ思想）。
