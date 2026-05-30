# 力戦派 複雑化モード（FightingStrategy `complex`）設計

- 作成日: 2026-05-30
- 対象: `katrain/core/ai.py` `FightingStrategy`
- 関連メモリ: `project_per_move_planning_wall`, `feedback_batch_eval_trajectory_limit`, `feedback_fighting_proximity_stddev`

## 目的

現在の戦略群のうち「接触戦の密度（力戦調）」を最も生み出せる **FightingStrategy** を土台に、
盤面をより複雑（紛れの多い乱戦）にする方向へ per-move バイアスをかける新モードを追加する。

ユーザー要件（確定事項）:
- 重視軸は**接触戦の密度（力戦調・定石を外す打ちまわし）**が最優先。理想は「多くの弱い石群／攻め合い・コウ・死活／地が長く決まらない／接触戦密度」の全軸。
- 強さの犠牲は**小**を基本とする。通常は既存の悪手フィルタ（19路 NORMAL=5.6目）を維持し互角以上を狙う。
- **例外**: 大差リード時（例: 15目以上勝ち）は大きめの損（例: 10目）を許容する。ただし
  - 「**さらに複雑な局面にできる手**」に限る
  - 複雑化に寄与しない**ただの明らかな悪手はNG**
  - 逆転されるほどの大損はNG（リードに比例した上限に収める）

## スコープ

- 対象盤面: FightingStrategy 既存と同じ（19路・13路を主対象。9路は力戦重みが意味を持ちにくいが排除はしない）。
- 既存の `classic` / `scoreloss` / `human` モードは**一切変更しない**（回帰リスクゼロ）。
- 新モード `complex` は `human` モードのパイプライン（2段階クエリ・悪手フィルタ・安全弁）を再利用し、2点だけ差し替える。

## アーキテクチャ

`fighting_mode` に4つ目の値 **`"complex"`** を追加する。`generate_move()` のディスパッチに分岐を足す。

`complex` モードは `_generate_human()` のパイプラインを基盤とし、以下2点を差し替える:

1. 重み関数: `_build_fighting_weight_dict()` → **`_build_complexity_weight_dict()`**
2. 悪手フィルタ: 固定閾値 → **`_complexity_loss_filter()`**（リード適応＋鋭さゲート）

実装方針: `_generate_human()` 内で `mode == "complex"` を判定して上記2点を切り替えるか、
あるいは `_generate_complex()` として共通パイプラインを切り出して両者から呼ぶ。
コード重複を避けるため、**共通部分のヘルパー抽出**を優先する（実装計画で詳細化）。

### 新規ユニット（小さく分離）

- `_build_complexity_weight_dict() -> Dict[Tuple[int,int], float]`
  純粋関数的に複雑さスコア辞書を返す。KataGo追加クエリなし。
- `_complexity_loss_filter(move_infos, base_threshold, current_lead, complexity_weights, ...) -> Set[str]`
  リード適応の損失フィルタ。許容手の GTP set を返す。
- `_count_cut_adjacency((x, y)) -> int`
  候補点が接する**異なる相手 chain** の数を返す小ヘルパー（`game.board` / `game.chains` を使用）。

## 複雑さスコア（案A・盤面ヒューリスティック）

現状の力戦重み `unsettled × prox × contact_boost × invasion_bonus` を土台に、複雑さ志向の成分を乗算で追加する。

最終重み（complex時）:
```
weight(x,y) = humanPolicy × unsettled × prox × contact_boost × invasion_bonus × cut_boost
```

### 成分

| 成分 | 狙う軸 | 計算 |
|---|---|---|
| 切りボーナス `cut_boost` | 石群を増やす（乱戦） | `_count_cut_adjacency((x,y)) >= 2` のとき重みに ×`complexity_cut_boost`（デフォルト2.0） |
| 接触強調 | 接触戦密度（最優先） | complex時は `contact_boost` を既定で強める（`complexity_contact_boost` デフォルト2.0） |
| 未確定維持 | settleさせない | `unsettled = (1-|o|)^unsettled_power` を流用。complex時に `unsettled_power` を高め（例3.0）にして確定地を更に冷遇するかは実装時に校正 |

### 切り検出（`_count_cut_adjacency`）

候補の空点 `(x,y)` の4近傍について `game.board` の chain id を見る。
相手 chain id（`game.chains[c][0].player != next_player`）の**異なる id** が2つ以上あれば「切り/楔」とみなす。

- 単純判定。切断の成否（取られる切りか）までは見ない（既知の限界として明記）。
- `game.board` / `game.chains` は現ノードの盤面状態を反映している。

### 最小構成スタート（YAGNI）

初期実装は **切りボーナス＋接触強調** のみとする。
「新戦場ボーナス」（直近N手の重心から遠い未確定点へのボーナス＝同時多発の乱戦を促す）は**後追加**とする。
理由: 「盤の反対側の2点平均が幻影中心になる」罠（メモリ既知）の回避設計が要るため、効果を見てから足す。

## リード適応の損失予算＋鋭さゲート（案B）

ユーザー要件「大差勝ち中だけ、複雑化する鋭い手に限り、大きめの損を許す」を実装する。

### 現在リードの取得

Stage2 クリーン解析の root `scoreLead`（**常に黒視点**）を `player_sign`（B=+1 / W=-1）で打つ側視点に変換し `current_lead` とする。

### 2段階の損失バンド

- `loss < base_threshold`（NORMAL=5.6目）の手 → **常に許容**（通常の力戦human動作）
- `base_threshold ≤ loss < relaxed_cap` の手 → **ゲート通過時のみ許容**

`loss = player_sign × (best_score - score)`（既存 human モードと同じ符号規約。best_score は現プレイヤーの真の最善スコア）。

### ゲート（3条件すべて満たす手だけが緩和バンドに入れる）

1. **リード条件**: `current_lead >= complexity_lead_threshold`（デフォルト15目）。勝っていなければ緩和は一切作動しない＝デフォルトは犠牲小。
2. **鋭さ条件**: その候補手の KataGo `scoreStdev >= complexity_sharpness_min`。スコアのばらつきが大きい＝双方紛れのある手のみ。一方的な悪手を弾く。
3. **複雑さ条件**: その手の複雑さスコア（前節）が候補中の上位／フロア超。盤面的にも紛れを生む手に限定。

### 緩和上限の段階化

Jigo の `jigo_large_lead_max_loss` 動的緩和と同じ発想。一気に全予算を開放せず、リードに比例させる:

```
relaxed_cap = min(
    complexity_max_loss,                                  # 上限（デフォルト10目）
    base_threshold + (current_lead - complexity_lead_threshold) × slope
)
```

`slope` は実装時に決定（例: lead=15で base+α、lead=25で上限近く）。逆転されない範囲に収める。

### 安全装置

- 既存の安全弁（最多探索手の loss ≥ 4.0 で最善スコア手を強制）は温存。
  ただし complex モードで**緩和バンドの手を意図的に選んだ場合は安全弁をスキップ**する（意図的な損を上書きしないため）。実装時にクロスチェックで要注意。
- 大差が縮んで `current_lead < threshold` に戻れば即座に通常フィルタへ復帰（毎手再評価のため自動）。

### `scoreStdev` の入手性（実装時の検証項目）

Stage2 クリーンクエリ（`include_policy=False`）の各 `moveInfo` に `scoreStdev` が含まれるかを実装時に確認する。
含まれない場合は winrate の散らばり等で代替する。

## パラメータ

`constants.py` の `AI_OPTION_VALUES` + パッケージ `config.json` + **ローカル `C:\Users\iwaki\.katrain\config.json`** の3箇所に登録する。
ローカル config はメインセッションで直接 Edit する（サブエージェント委任不可）。

| パラメータ | デフォルト | 選択肢/型 | 役割 |
|---|---|---|---|
| `fighting_mode` | （既存に値追加） | classic / scoreloss / human / **complex** | complexモード選択 |
| `complexity_cut_boost` | 2.0 | 1.0〜5.0 | 切り点の重みブースト |
| `complexity_contact_boost` | 2.0 | 1.0〜5.0 | complex時の接触強調（既存 contact_boost と別保持か共用かは実装時判断） |
| `complexity_lead_threshold` | 15.0 | 目数 | 緩和予算が解禁されるリード差 |
| `complexity_max_loss` | 10.0 | 目数 | 緩和時の損失上限 |
| `complexity_sharpness_min` | （要校正） | scoreStdev値 | 鋭さゲート閾値 |

「新戦場ボーナス」のパラメータは最小構成では未追加（後追加）。

i18n: ラベル・説明文を `.po` に追加 → `python tools/compile_mo.py` で `.mo` 再コンパイル。
`.claude/rules/ai-parameters.md` のテーブルも同時更新。

## 検証方法

- **CLI個別確認**:
  `python -m katrain_debug --sgf FILE --move N --strategy fighting --settings fighting_mode=complex` で、
  どの手に切り/接触/鋭さブーストが乗ったか、緩和バンドが作動したかを確認。
- **GUI実戦**: `debug_level=1` で `[FightingStrategy]` ログを `grep -a` で抽出。
  複雑さ重みの上位手・ゲート通過の発動を確認。
- **リード適応の作動**: 大差局面の SGF を `--move N` で個別実行して確認。

## 既知の限界（明記）

- **batch評価では複雑化を測れない**（メモリ `feedback_batch_eval_trajectory_limit`）。
  複雑さは1局通しの軌跡特性で、SGF固定の batch では両条件が同一になる。
  AI一致率・損失の副作用チェックには使えるが、複雑化そのものの効果は GUI 実戦でしか測れない。
- **多手先計画は強要できない**（メモリ `project_per_move_planning_wall`）。
  本機能は「複雑になりやすい手」を1手ごとに優遇するもので、コウで勝ち切る・難解な攻め合いを最後まで作る、
  といった多手計画は保証しない。あくまで局面を紛れさせる方向への per-move バイアス。
- 複雑さスコアは近似ヒューリスティック。切り検出は「2つ以上の異なる相手 chain に接する点」という単純判定で、
  本当の切断成否（取られる切りか）までは見ない。

## 今後の拡張（本スコープ外）

- 新戦場ボーナス（同時多発の乱戦促進）。
- 案C（1手先の再評価で複雑さを直接測定: 相手応手の policy エントロピー・score stdev・互角応手数）。
  高精度だが K回の追加クエリで重い。精度向上オプションとして温存。
