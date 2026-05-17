# JigoStrategy 油断誘発 13路スライダー化 設計書

- 作成日: 2026-05-17
- 対象: `katrain/core/ai.py` の `JigoStrategy.generate_move()` および `_jigo_resolve_phase`
- 方針: 13路盤限定で Phase 1/2/3 開始手数と Phase 1/2 の `eff_target` をユーザが GUI スライダーで調整可能にする
- 前提: `2026-05-16-jigo-deception-phase-design.md`（Phase 機構本体）

## 背景と狙い

既存の `jigo_deception` 機構では Phase 境界手数と `eff_target` がモジュール定数 `JIGO_DECEPTION_PHASE_TABLE` / `JIGO_DECEPTION_TARGETS` にハードコードされている。元 spec で「Phase 境界手数・控え目標値はコード固定。将来 GUI 拡張するなら別 spec で追加」と明示的に deferred されていた拡張。

13路盤プレイヤーから「自分の対局相手の棋力に合わせて控え量や復帰タイミングを微調整したい」というニーズがあるため、まず 13路だけにスライダーを追加する。19/9路は引き続きコード固定（必要になれば後続 spec で同様の拡張）。

## 目標

- 13路盤での Phase 1/2/3 開始手数を 4 段階のスライダーで選択可能にする
- 13路盤での Phase 1/2 の `eff_target` を 4 段階のスライダーで選択可能にする
- `eff_target_max` は `eff_target + 1.0` で自動算出（既存 1.0 目幅の仕様を維持）
- GUI 既存レイアウトを崩さない（`max_options = 15` を厳守）
- スライダー値の順序矛盾（例: Phase 1 開始 > Phase 2 開始）でも例外を出さず、既存ロジックの「最後にマッチする境界が勝つ」挙動に従う
- `jigo_deception=false` または 13路以外の盤面では新スライダーは完全無視（既存挙動と一致）

## 非目標

- 19路・9路でのスライダー化（必要になれば別 spec）
- Phase 0 開始手数の調整（常に手数 1）
- 安全弁閾値（`JIGO_DECEPTION_SAFETY_OVERSHOOT = 5.0`）の調整
- `eff_target_max` を `eff_target` と独立に調整（1.0 目幅は維持）
- スライダー値の順序バリデーション・警告表示

## アーキテクチャ

### 設定キー（5個追加）

`katrain/core/constants.py` の `AI_OPTION_VALUES[AI_JIGO]` および `AI_OPTION_ORDER` に追加。

| キー | デフォルト | 値リスト | 備考 |
|---|---|---|---|
| `jigo_deception_13_phase1_start` | 17 | [10, 17, 25, 35] | Phase 0→1 境界手数 |
| `jigo_deception_13_phase2_start` | 44 | [30, 44, 55, 70] | Phase 1→2 境界手数 |
| `jigo_deception_13_phase3_start` | 83 | [70, 83, 95, 110] | Phase 2→3 境界手数 |
| `jigo_deception_13_phase1_target` | -2.0 | [-1.0, -2.0, -3.0, -4.0] | Phase 1 の eff_target（target_max は +1.0 自動） |
| `jigo_deception_13_phase2_target` | -1.0 | [-0.5, -1.0, -1.5, -2.0] | Phase 2 の eff_target（target_max は +1.0 自動） |

デフォルト値は既存 `JIGO_DECEPTION_PHASE_TABLE[13]` / `JIGO_DECEPTION_TARGETS[(13, …)]` と完全一致させ、未編集ユーザの挙動を変えない。

### `JigoStrategy.generate_move()` への組み込み

既存 Phase 解決ブロック（`katrain/core/ai.py:954-981`）の直後に、13路かつ deception 有効時のみスライダー値で上書きするロジックを挿入。

```python
# 既存の Phase 解決後
if deception_enabled and board_size_for_phase == 13:
    eff_target, eff_target_max = _jigo_resolve_13path_overrides(
        phase, eff_target, eff_target_max, self.settings
    )
    # eff_mode / eff_large_lead_delta は既存ロジックが phase に応じて上書き済み
```

`_jigo_resolve_13path_overrides` は 13路スライダー値で `eff_target` / `eff_target_max` を上書きする小関数:

```python
def _jigo_resolve_13path_overrides(phase, default_target, default_target_max, settings):
    """13路盤の deception 有効時、Phase 1/2 で eff_target/max をスライダー値に置換。

    Phase 0/3 は default をそのまま返す（既存挙動）。
    target_max は target + 1.0 で自動算出。
    """
    if phase == "phase1":
        t = settings.get("jigo_deception_13_phase1_target", -2.0)
        return t, t + 1.0
    if phase == "phase2":
        t = settings.get("jigo_deception_13_phase2_target", -1.0)
        return t, t + 1.0
    return default_target, default_target_max
```

### `_jigo_resolve_phase` への組み込み

`_jigo_resolve_phase(board_size, move_num, current_lead)` 呼び出し時に、13路かつ deception 有効ならスライダーの境界手数を使うようシグネチャを拡張。後方互換のため `phase_table_override` 引数を追加（デフォルト None で既存挙動）:

```python
def _jigo_resolve_phase(board_size, move_num, current_lead, phase_table_override=None):
    table = phase_table_override or JIGO_DECEPTION_PHASE_TABLE.get(
        board_size, JIGO_DECEPTION_PHASE_TABLE[19]
    )
    # 以降は既存ロジック（boundary を走査して base_phase を決定 + 安全弁）
    ...
```

`generate_move()` 呼び出し側:

```python
if deception_enabled:
    board_size_for_phase = max(self.game.board_size)
    move_num = self.cn.depth
    last_lead = getattr(self.game, "_jigo_last_current_lead", None)
    table_override = None
    if board_size_for_phase == 13:
        table_override = [
            (self.settings.get("jigo_deception_13_phase1_start", 17), "phase1"),
            (self.settings.get("jigo_deception_13_phase2_start", 44), "phase2"),
            (self.settings.get("jigo_deception_13_phase3_start", 83), "phase3"),
        ]
    phase = _jigo_resolve_phase(
        board_size_for_phase, move_num, last_lead, phase_table_override=table_override
    )
    ...
```

**安全弁の挙動**: `_jigo_resolve_phase` 内の安全弁は `JIGO_DECEPTION_TARGETS` から `base_target_max` を引いて判定する。13路でスライダー値を使う場合、安全弁にもスライダー由来の `target_max` を渡したい。シグネチャをさらに拡張するか、安全弁判定を `generate_move` 側へ移すか選ぶ必要がある。

**設計判断**: 安全弁判定を `_jigo_resolve_phase` 内に残すが、`target_overrides` 引数を追加して 13路の場合だけ渡す。簡素化:

```python
def _jigo_resolve_phase(
    board_size, move_num, current_lead,
    phase_table_override=None, target_overrides=None,
):
    """target_overrides: {"phase1": (t, tmax), "phase2": (t, tmax)} の dict。
    None なら既存 JIGO_DECEPTION_TARGETS を使う。
    """
    ...
    # 安全弁判定で target_overrides が指定されていればそれを優先
    if base_phase in ("phase1", "phase2") and current_lead is not None:
        if target_overrides and base_phase in target_overrides:
            _, base_target_max = target_overrides[base_phase]
        else:
            targets = JIGO_DECEPTION_TARGETS.get((board_size, base_phase))
            if targets is None:
                return base_phase  # フォールバックで安全弁スキップ
            _, base_target_max = targets
        if current_lead > base_target_max + JIGO_DECEPTION_SAFETY_OVERSHOOT:
            return "phase3"
        if current_lead < base_target_max - JIGO_DECEPTION_SAFETY_OVERSHOOT:
            return "phase3"
    return base_phase
```

`generate_move` から渡す `target_overrides`:

```python
if board_size_for_phase == 13:
    p1_target = self.settings.get("jigo_deception_13_phase1_target", -2.0)
    p2_target = self.settings.get("jigo_deception_13_phase2_target", -1.0)
    target_overrides = {
        "phase1": (p1_target, p1_target + 1.0),
        "phase2": (p2_target, p2_target + 1.0),
    }
```

これで Phase 解決と上書きが一貫する。

### 順序矛盾の許容

スライダー値の順序矛盾（例: Phase 1 開始=35, Phase 2 開始=30）は既存 `_jigo_resolve_phase` の以下のループに依存して安全に処理する:

```python
base_phase = "phase0"
for boundary, phase in table:
    if move_num >= boundary:
        base_phase = phase
```

順序が崩れていても「最後に手数条件を満たす境界が勝つ」だけで例外は出ない。バリデーションロジックは追加しない（YAGNI）。

ユーザが `Phase 1=35, Phase 2=30, Phase 3=110` を選んだ場合の挙動例（手数 31 時点）:
- `31 >= 10`? いいえ、boundaries[0]=35 なので False。
- 順次評価で `31 >= 30 (phase2)` → True → base_phase=phase2
- `31 >= 110 (phase3)` → False
- 結果: phase2 が採用される

これは「Phase 1 をスキップして直接 Phase 2 に入る」挙動として解釈でき、有害ではない。

## GUI レイアウト安全性

`ConfigAIPopup.max_options = 15`（`katrain/gui/popups.py:398`）が GridLayout の行数上限。超過で `GridLayoutException: Too many children in GridLayout` が発生する（`.claude/rules/ai-settings-gui.md`）。

現在の JIGO 設定項目（9個）:
1. `max_loss_per_move`
2. `min_human_policy`
3. `jigo_mode`
4. `human_profile`
5. `jigo_dynamic_rank`
6. `jigo_large_lead_delta`
7. `jigo_large_lead_max_loss`
8. `jigo_equivalent_epsilon`
9. `jigo_deception`

本 spec で追加する 5項目を加えて 14/15。**1 項目分の余裕あり**。

将来さらに JIGO 設定を追加する場合は `max_options` の引き上げか別戦略への分離が必要。本 spec では追加を 5項目で打ち止めとする。

## i18n 説明文

`.claude/rules/ai-settings-gui.md` のチェックリストに従い、**短ラベル msgid** と **`aihelp:jigo` 本文追記** の両方を `jp` と `en` に追加し、`python tools/compile_mo.py` で `.mo` を再コンパイルする。

### `jp` 短ラベル（5個追加）

```
msgid "jigo_deception_13_phase1_start"
msgstr "[13路] Phase1開始手数 (中盤入口で控えめに打ち始める)"

msgid "jigo_deception_13_phase2_start"
msgstr "[13路] Phase2開始手数 (徐々に target に戻し始める)"

msgid "jigo_deception_13_phase3_start"
msgstr "[13路] Phase3開始手数 (通常 Jigo に復帰、勝ちに行く)"

msgid "jigo_deception_13_phase1_target"
msgstr "[13路] Phase1 目標スコア差 (例: -2.0=2目劣勢を維持)"

msgid "jigo_deception_13_phase2_target"
msgstr "[13路] Phase2 目標スコア差 (Phase3 復帰前の中間値)"
```

### `en` 短ラベル（5個追加）

```
msgid "jigo_deception_13_phase1_start"
msgstr "[13x13] Phase 1 start move (begin holding back)"

msgid "jigo_deception_13_phase2_start"
msgstr "[13x13] Phase 2 start move (begin returning to target)"

msgid "jigo_deception_13_phase3_start"
msgstr "[13x13] Phase 3 start move (resume normal Jigo)"

msgid "jigo_deception_13_phase1_target"
msgstr "[13x13] Phase 1 target score diff (e.g. -2.0 = stay 2 pts behind)"

msgid "jigo_deception_13_phase2_target"
msgstr "[13x13] Phase 2 target score diff (intermediate before Phase 3)"
```

### `aihelp:jigo` 本文への追記（末尾、`jp`）

> jigo_deception: ON で序中盤に意図的に劣勢を演出 → 終盤で逆転する人間らしい棋風。13路盤では Phase1/2/3 の開始手数と Phase1/2 の目標スコア差をスライダーで調整可能（19/9路はコード固定）。各 Phase 中は target_max = target+1.0 で自動設定、過剰優勢/劣勢(±5目)で安全弁が Phase3 に強制ジャンプ。Phase1 開始 < Phase2 開始 < Phase3 開始 となるように設定するのが推奨だが、逆転値でもエラーにはならず「最後に手数条件を満たす Phase」が採用される。

英語版も同等の内容を追記（既存 `aihelp:jigo` の英文末尾に append）。

## 設定値の配置（CLAUDE.md の 3 箇所ルール）

1. `katrain/core/constants.py` — `AI_OPTION_VALUES[AI_JIGO]` に 5 キー追加、`AI_OPTION_ORDER` に 5 キー追加（既存 jigo_deception=10 の後、11〜15）
2. `katrain/config.json` — `ai:jigo` セクションに 5 キーのデフォルト値追加
3. `C:\Users\iwaki\.katrain\config.json` — 同じ 5 キーをユーザーローカル設定に追加（**メインセッションで直接 Edit**、サブエージェント委任禁止）
4. `katrain/i18n/locales/jp/LC_MESSAGES/katrain.po` — 短ラベル 5 個 + `aihelp:jigo` 本文末尾追記
5. `katrain/i18n/locales/en/LC_MESSAGES/katrain.po` — 同上（英語）
6. `python tools/compile_mo.py` — `.mo` 再コンパイル
7. `.claude/rules/ai-parameters.md` — JigoStrategy パラメータテーブルに 5 行追加

## エッジケース処理

| ケース | 動作 |
|---|---|
| `jigo_deception=false` | 新キーは完全無視、既存挙動と完全一致 |
| 19路盤 + deception=true | 既存 `JIGO_DECEPTION_TARGETS[(19, …)]` を使用、新キーは無視 |
| 9路盤 + deception=true | 既存 `JIGO_DECEPTION_TARGETS[(9, …)]` を使用、新キーは無視 |
| 13路盤 + deception=true + 新キー未編集 | デフォルト値 (17/44/83/-2.0/-1.0) = 既存定数と完全一致、挙動不変 |
| 13路盤 + Phase 1 開始 > Phase 2 開始 | 例外なし。`for boundary, phase in table` ループで「最後にマッチした境界」が勝つ |
| 13路盤 + Phase 1 target > Phase 2 target | 例外なし。Phase 1 が控えめでなく Phase 2 がより劣勢、という運用上奇妙な挙動になるだけ |
| 設定キー欠落（古い user config） | `settings.get(key, default)` でデフォルト値にフォールバック |
| 13路盤 + 過剰優勢/劣勢 | 安全弁が `target_overrides` 由来の `target_max ± 5.0` で判定、Phase 3 ジャンプ |

## テスト計画

### ユニットテスト（`tests/test_jigo_deception.py` に追加）

1. `_jigo_resolve_13path_overrides("phase0", -3.0, -2.0, settings)` → `(-3.0, -2.0)` を返す（既存値素通し）
2. `_jigo_resolve_13path_overrides("phase1", _, _, {"jigo_deception_13_phase1_target": -3.0})` → `(-3.0, -2.0)` を返す
3. `_jigo_resolve_13path_overrides("phase2", _, _, {"jigo_deception_13_phase2_target": -0.5})` → `(-0.5, 0.5)` を返す
4. `_jigo_resolve_13path_overrides("phase3", -3.0, -2.0, settings)` → `(-3.0, -2.0)` を返す
5. `_jigo_resolve_phase(13, 50, None, phase_table_override=[(10, "phase1"), (40, "phase2"), (80, "phase3")])` → `"phase2"` を返す
6. 順序矛盾テスト: `_jigo_resolve_phase(13, 31, None, phase_table_override=[(35, "phase1"), (30, "phase2"), (110, "phase3")])` → `"phase2"` を返す（例外なし）
7. 13路スライダー値での安全弁: `_jigo_resolve_phase(13, 50, +5.0, table_override=[…], target_overrides={"phase1": (-2.0, -1.0)})` → `"phase3"`（過剰優勢で安全弁発動）

### CLI 検証

```bash
# 13路 SGF + デフォルトスライダー → 既存挙動と一致確認
python -m katrain_debug --sgf <13x13.sgf> --strategy jigo \
  --settings jigo_deception=true --move 20 --output json

# 13路 SGF + Phase 1 開始を早める (10手)
python -m katrain_debug --sgf <13x13.sgf> --strategy jigo \
  --settings jigo_deception=true jigo_deception_13_phase1_start=10 --move 15 --output json

# 13路 SGF + Phase 1 target をきつくする (-4.0)
python -m katrain_debug --sgf <13x13.sgf> --strategy jigo \
  --settings jigo_deception=true jigo_deception_13_phase1_target=-4.0 --move 25 --output json
```

各実行で debug ログ `[JigoStrategy] Deception: move=…, phase=…, eff_target=…` を確認、スライダー値が反映されていること。

### GUI 検証

1. `python -m katrain` 起動
2. AI 設定ポップアップで「Kata持碁」選択、`jigo_deception` を ON
3. 新スライダー 5 個が表示され、レイアウト崩れがないことを確認
4. 各スライダーをデフォルト以外の値に変更 → 保存 → 13路盤で AI 対局開始
5. ログで Phase 遷移とスライダー値反映を確認
6. AI 設定ポップアップを再オープン → 設定値が永続化されていることを確認

### batch_eval 校正

13路 SGF（既存 `docs/superpowers/specs/calibration-data/` から流用、なければ撮り直し）を使用:

- 条件: スライダー全デフォルト vs カスタム値（例: phase1_target=-3.0, phase2_target=-1.5）× 3-run 平均
- 測定: `ai_top_move`, `mean_ptloss`, accuracy
- 合格基準:
  - デフォルト値での `ai_top_move` / `mean_ptloss` が既存 13路 baseline（spec 校正前の値）と stdev 0.05 以内
  - カスタム値で `mean_ptloss` 劣化が +1.0 目以内

**校正の限界**: 元 spec と同じく、score_lead 軌跡は SGF 固定のため両条件で同一。実際の Phase 切替による劣勢演出の有無は GUI 対局でしか検証不可。

## 実装順序

1. `katrain/core/ai.py` に `_jigo_resolve_13path_overrides` 関数追加
2. `_jigo_resolve_phase` シグネチャ拡張（`phase_table_override`, `target_overrides` 引数追加、デフォルト None で後方互換）
3. `JigoStrategy.generate_move()` に 13路スライダー読み込みと `_jigo_resolve_phase` 呼び出しの組み込み
4. `tests/test_jigo_deception.py` に新規ユニットテスト 7 個追加
5. `katrain/core/constants.py` の `AI_OPTION_VALUES[AI_JIGO]` と `AI_OPTION_ORDER` に 5 キー追加
6. `katrain/config.json` の `ai:jigo` セクションに 5 キーのデフォルト値追加
7. `C:\Users\iwaki\.katrain\config.json` の `ai:jigo` に 5 キー追加（メインセッション直接 Edit）
8. `katrain/i18n/locales/jp/LC_MESSAGES/katrain.po` に短ラベル 5 個 + `aihelp:jigo` 末尾追記
9. `katrain/i18n/locales/en/LC_MESSAGES/katrain.po` に同上（英語）
10. `python tools/compile_mo.py` で `.mo` 再コンパイル
11. `.claude/rules/ai-parameters.md` の JigoStrategy パラメータテーブルに 5 行追加（サブエージェント経由）
12. CLI 検証（デフォルト・カスタム値で挙動確認）
13. GUI 検証（レイアウト・永続化・対局時 Phase 遷移）
14. batch_eval 校正（3-run 平均 × デフォルト/カスタム × 13路 SGF）
15. 校正結果を本 spec の付録に追記

## 参考

- 関連 spec: `docs/superpowers/specs/2026-05-16-jigo-deception-phase-design.md`（Phase 機構本体）
- 関連 spec: `docs/superpowers/specs/2026-04-12-jigo-humanlike-design.md`（JigoStrategy 本体）
- `.claude/rules/ai-settings-gui.md`: GUI 追加手順、`max_options=15` 制約、i18n コンパイル手順
- `.claude/rules/ai-parameters.md`: JigoStrategy パラメータ一覧（更新対象）
- CLAUDE.md の「やってはいけないこと」: ユーザーローカル config の編集は必ずメインセッション、`.claude/rules/` 編集はサブエージェント経由、i18n `.po` 編集後は `.mo` コンパイル必須
