# 力戦派 新モード `complex_humble`（GUI表示「力戦派（調整）」）設計

- 日付: 2026-05-31
- 対象: `katrain/core/ai.py` `FightingStrategy`、`katrain/core/constants.py`、`config.json`（パッケージ + ユーザーローカル）、i18n
- 関連: [2026-05-30-fighting-complexity-design.md](2026-05-30-fighting-complexity-design.md)（complex モード本体）、`.claude/rules/ai-parameters.md`

## 1. 背景と目的

現行の力戦派 `complex` モードは「接近・絡み合い・切り」で複雑な碁を実現できているが、**終局時に確認すると AI 最善手一致率が相手よりはるかに高く、50% を超える対局がほとんど**。複雑な碁を打ちながら一致率 5 割超は世界トッププロか AI でしかありえず、相手との実力差が出すぎる。

根本原因は、complex モードに**最善手を意図的に避ける機構が無い**こと。complex は「強い人間らしい着手（humanSL 9段）＋力戦重み」であり、

- 選択重み `humanPolicy × complexity_weight` は、複雑な局面では AI 最善手（＝強い接触・切りの手で humanPolicy も高い）でピークを取りやすい
- タイブレーク（`ai.py:2748`）が拮抗時に高スコア手を**強制**する
- 安全弁v2（`ai.py:2618`）が高損失時に最善手を**強制**する

の 3 機構がすべて最善手側へ引っ張る。

**目的**: 力戦派の「複雑な碁」という特徴を維持したまま、終局時の AI 最善手一致率を相手並みまで下げる。現行 `complex` を含む既存モードは一切変更せず、新モードとして追加する。

## 2. 設計方針（決定事項）

ブレインストーミングで以下を確定:

- **ゴール = リード比例予算（オプションC）**。ただしユーザーの指摘「互角の局面なら一致率を下げる必要はない（互角＝その時点で相手とも一致率が互角）」を反映し、**予算は互角でゼロ、リードに比例して増える**カーブにする。終局時の全局平均が下がっていればよい。
- **選択メカニズム = ハードな最善手回避（案1忠実）**。勝勢かつ予算内に「複雑さゲートを通った非・最善手」があれば、AI 最善手をプールから除外し、残りを `humanPolicy × complexity` で確率選択する。最善手は他に候補が無いときだけ打つ。
- **実装構造 = 新 `fighting_mode` 値**。`_generate_human(complex_mode=True)` のパイプライン・`complexity_*` パラメータ・安全弁・タイブレークをそっくり再利用し、最終選択直前に「謙虚ブロック」を一段挿入する。

却下した案:
- ソフト格下げ（`(order+1)^power`）単独 = 互角局面でも最善手が残りがちで、勝勢局面でも最善手が選ばれてしまい、狙った所で divergence が効かない。
- 全局で常に最善手回避 = 互角・劣勢で勝ちを落とすリスク。ユーザーの「互角では下げなくてよい」と矛盾。

## 3. 挙動仕様

### 3.1 モードのディスパッチ

`FightingStrategy.generate_move()`（`ai.py:2146`）に分岐を追加:

```python
elif mode == "complex":
    return self._generate_human(complex_mode=True)
elif mode == "complex_humble":
    return self._generate_human(complex_mode=True, humble=True)   # ← 追加
```

`_generate_human` のシグネチャに `humble: bool = False` を追加。`humble=True` は `complex_mode=True` を**包含**する（complex の全処理を通したうえで謙虚ブロックを足す）。`humble=False` のときは現行 complex と**バイト単位で同一の挙動**でなければならない（既存モードへの無影響を保証）。

### 3.2 謙虚ブロック（核心）

complex の候補プール構築・複雑さ損失フィルタ・鋭さ/複雑さゲート・humanPolicy フロア・sacrifice floor（`ai.py:2715`）まで**完了した状態**（＝`moves` リストと `good_moves` が確定した状態）で、最終選択の直前に挿入する。

擬似コード:

```python
# 既存変数:
#   current_lead         … 自分視点のリード（ai.py:2456/2463 で算出済み）
#   best_gtp_by_score    … KataGo 最善手の gtp（自分視点 best_score を取る手）
#   moves                … [(Move, humanPolicy×complexity_weight), ...]（complex の選択プール）
#   loss_by_gtp          … {gtp: 自分視点 loss}（sacrifice floor 内で算出。humble でも算出する）
#   endgame_threshold    … 32 if 9x9 else ceil(bx*by*0.5)（ai.py:2696）

keep_margin = self.settings.get("complexity_humble_margin", 5.0)
humble_budget = max(0.0, current_lead - keep_margin)        # 互角=0、勝勢ほど増える
is_endgame = current_move >= endgame_threshold

humble_active = False
if humble and humble_budget > 0.0 and not is_endgame and best_gtp_by_score:
    # ゲート通過済み（= moves 内）の「非・最善手」で loss <= humble_budget の候補
    alternatives = [
        (m, w) for (m, w) in moves
        if m.gtp() != best_gtp_by_score
        and loss_by_gtp.get(m.gtp(), 0.0) <= humble_budget
    ]
    if alternatives:
        # 予算内の非・最善手だけを選択プールにする（reserve 厳守＝選ぶ手の loss <= budget）
        # 通常パラメータでは budget >= relaxed_cap なので alternatives = 全非最善手と一致するが、
        # 極端な keep_margin では budget 超の手を確実に除外できる。
        moves = alternatives
        humble_active = True
        self.game.katrain.log(
            f"[FightingStrategy:humble] active: lead={current_lead:.1f} "
            f"keep_margin={keep_margin} budget={humble_budget:.1f} "
            f"dropped best={best_gtp_by_score} ({len(alternatives)} alternatives)",
            OUTPUT_DEBUG,
        )
# 以降、moves を humanPolicy×complexity の重み付き確率選択（既存 weighted_selection）
```

**性質:**

- **互角（`current_lead ≤ keep_margin`）→ `humble_budget = 0` → ブロック不発 → 現行 complex と完全に同一。** ユーザーの「互角では下げない」を厳密に満たす。
- **勝勢ほど `humble_budget` が増え、より大胆に最善手を外す。** ただし `humble_budget = current_lead − keep_margin < current_lead` なので、**1 手で勝ちを手放すことは構造的に起きない**（除外後に選ぶ手の loss は humble_budget 以下＝リード未満）。
- 除外後の選択は argmax ではなく `humanPolicy × complexity` の**確率選択**。「常に一番尖った点」というロボット感を避け、人間のばらつきを残す。
- 候補は complex の複雑さゲート（鋭さ `scoreStdev ≥ complexity_sharpness_min` ＋ 複雑さ重み `≥ _COMPLEXITY_WEIGHT_FRAC × max`）を通った手のみ。**「ただの悪手」は混ざらない**。
- 予算内に非・最善の合格手が無ければ `humble_active=False` のまま＝現行 complex（最善手も残る）にフォールバック。

### 3.3 force-best 系の無効化

`humble_active` が真のときだけ、最善手へ引き戻す 2 機構をバイパスする（divergence と正面衝突するため）:

- **タイブレーク（`ai.py:2748`〜2782）**: `if not humble_active and len(top5) >= 2 and move_infos:` でブロック全体をスキップ。
- **安全弁v2（`ai.py:2618`〜2644）**: これは `moves` 構築直後（謙虚ブロックより前）に走るため、`humble_active` がまだ確定していない。**事前ゲート**で対応する: 安全弁v2 の発火条件に「humble モードかつ謙虚予算が開いている（`humble and humble_budget > 0 and not is_endgame`）」ときは**スキップ**する条件を足す。`humble_budget`・`is_endgame` はプール無しで算出できるため、安全弁v2 の直前で先に計算しておく。

  - 補足: `humble_budget > 0` でも実際に alternatives が無ければ謙虚ブロックは不発になり最善手がプールに残るが、その場合でも安全弁v2 はスキップされる。複雑さゲート＋予算上限（`_complexity_relaxed_cap`）が悪手ガードを兼ねるため、安全弁v2 不在でも「ただの悪手」は出ない（complex の予算設計と同じ品質保証）。

互角時・ヨセ時・`humble=False` 時は両機構とも従来通り有効。

### 3.4 ヨセ除外（判断2）

ヨセ（`current_move ≥ endgame_threshold`、19路=181手目〜）では謙虚ブロックを**不発**にし、現行 complex のヨセ処理（`ai.py:2695`、力戦重み無視の humanPolicy 最上位手）をそのまま使う。

理由: ヨセの最善手外しは複雑化の余地がほぼ無く「ただの損」になりやすい。終盤の一致率は無理に下げない。

将来の余地: 全局平均が下がりきらない場合、ここを部分開放するチューニング余地として残す（v1 では実装しない＝YAGNI）。

## 4. 新規 GUI パラメータ（1個のみ）

校正ダイヤルは `complexity_humble_margin` 一個に集約する。

| パラメータ | デフォルト | 選択肢 | 意味 |
|---|---|---|---|
| `complexity_humble_margin` | 5.0 | 2.0 / 3.0 / 5.0 / 8.0 / 10.0 / 15.0 | この目数を残して打つ＝この差以上リードしたら最善手回避を解禁。**小さい→接戦でも早めに最善手を外す→全局平均一致率がより下がる**。大きい→大勝時のみ外す（案1の10目に近い）。 |

これが「相手と一致率を揃える」ための**主ダイヤル**。実測してこの一個を動かすだけで調整できる。`complexity_lead_threshold` / `complexity_max_loss` / `complexity_base_max_loss` / `complexity_sharpness_min` / `complexity_cut_boost` など既存の complex パラメータは複雑さ品質の担保として**そのまま流用**する。

GUI オプション行数: 力戦派パネルは現状 13 行（上限 17、[[project_gui_max_options_17]]）。本パラメータ追加で 14 行＝余裕あり。新 `fighting_mode` 値はドロップダウン項目の追加であり行数を増やさない。

## 5. 変更ファイル一覧

| ファイル | 変更 |
|---|---|
| `katrain/core/ai.py` | `generate_move` に `complex_humble` 分岐／`_generate_human(humble=False)` 引数追加／謙虚ブロック挿入／安全弁v2・タイブレークの `humble_active` ゲート |
| `katrain/core/constants.py` | `AI_OPTION_VALUES["fighting_mode"]` に `("complex_humble", "[fighting:complex_humble]")` 追加／`complexity_humble_margin` キー追加＋表示順登録 |
| `katrain/config.json`（パッケージ） | `ai:p:fighting` セクション（`AI_FIGHTING = "ai:p:fighting"`）に `complexity_humble_margin: 5.0` 追加 |
| `C:\Users\iwaki\.katrain\config.json`（ユーザーローカル） | 同キー追加（**GUI は保存済みキーのみ表示**。メインセッションで直接 Edit、サブエージェント委任不可） |
| `katrain/i18n/locales/{en,jp}/.../katrain.po` | `[fighting:complex_humble]`（表示「力戦派（調整）」相当）・`complexity_humble_margin` 短ラベル・`aihelp:fighting` 本文に挙動説明を追記 |
| （ビルド） | `python tools/compile_mo.py` で `.mo` 再コンパイル |

GUI 表示名「力戦派（調整）」: 既存 complex がプレイヤー欄に「力戦派 (complex)」と出る仕組み（commit c173b52）に合わせ、`complex_humble` モード時に「力戦派（調整）」と表示されるよう i18n ラベルを設定する。

段位（elo）表示: `constants.py:320` の `AI_FIGHTING` elo 分岐は `fighting_mode == "human"/"scoreloss"` のみ特別扱いし、`complex` はデフォルト経路にフォールスルーしている。`complex_humble` も同じくフォールスルーで complex と同一強度表示になる＝**この分岐は変更不要**。

## 6. テスト

### 6.1 純関数ユニット（KataGo 不要、`tests/test_fighting_complexity.py` に追記）

- `humble_budget = max(0, lead - keep_margin)`: `lead ≤ keep_margin → 0`、`lead > keep_margin → lead - keep_margin`。
- alternatives 抽出: 最善手 gtp が除外される／loss > budget の手が落ちる／budget 内の非最善手だけ残る。
- `humble_budget < current_lead` 不変条件（勝ちを手放さない）。
- `humble=False` で謙虚ブロックが一切作用しない（現行 complex と同一出力）回帰。

謙虚ロジックを純関数（例 `_humble_filter_alternatives(moves, loss_by_gtp, best_gtp, budget)`）に切り出してテスト可能にする。

### 6.2 GUI 実戦検証

- `debug_level=1` で対局し、`grep -a "FightingStrategy:humble"` で発火/不発と除外手を確認。
- **batch_eval はリード軌跡を作れないため謙虚ブロックの検証は不可**（[[feedback_batch_eval_trajectory_limit]]）。これは既知の構造的制約で、検証は GUI 実戦ログのみ。
- 校正手順: 数局打って終局時の全局 AI 一致率（相手 vs 自分）を比較し、自分側が相手並みに下がるまで `complexity_humble_margin` を下げる方向で調整。複雑さ（接触・切りの密度）が損なわれていないことを盤面で目視確認（特徴喪失なら本機能は却下条件）。

## 7. スコープ外（YAGNI）

- ソフト格下げ（order-power）や最善手選択確率の上限キャップ（ハイブリッド案）= v1 では実装しない。`complexity_humble_margin` 一個で不足が判明した場合に再検討。
- ヨセ区間への divergence 拡張 = 将来余地として記載のみ。
- 9路/13路/19路は complex と同じ対応範囲。盤面別の特別扱いは追加しない（複雑さゲート・予算が盤面非依存に機能する）。
- 相手一致率の自動目標値追従 = 行わない。`complexity_humble_margin` 手動チューニングのみ。

## 8. リスクと既知の限界

- **全局平均が下がりきらない可能性**: 接戦が長く続く対局では謙虚ブロックが不発で complex のまま＝一致率が高いまま終わる。ユーザー合意済み（「互角＝相手とも互角なので OK、最終的に下がっていればよい」）。不足時の対処は `complexity_humble_margin` を下げる（接戦寄りでも発火）。
- **力戦特徴の喪失は却下条件**: 最善手回避で複雑さが落ちるなら本機能は破棄する。除外後選択を `humanPolicy × complexity` にし、複雑さゲート通過手限定にすることで特徴維持を狙うが、GUI 実戦の目視確認が最終判定。
