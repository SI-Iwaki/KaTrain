# コウ戦略（KoStrategy）設計書 — コウ重視・複雑化戦略

> **【棚上げ】2026-05-24: この設計に基づく実装は完了したが、GUI 13路実機テストの結果、戦略自体を棚上げ。**
> 理由: 実装は正しく動作（コウ検出・KoFight・安全機構は機能）するものの、**勝負を決定づけるコウを作れず、辺のヨセコウ程度しか生まれない**。これは構造的な限界で、(1) 決定的なコウ＝大石の死活が懸かるコウは多手先の計画が必要で、1手ごとの重み付け選択では作れない、(2) humanSL 9段の事前分布は不要なコウを避ける打ち方なのでコウ形が自然発生しにくい、(3) 損失バジェット（人間らしさ・自滅防止に必須）がコウを強要する前のめりな手を弾く——ため。「人間らしさ・手堅さ」と「決定的コウの強要」は原理的にトレードオフで、迷路戦略（`2026-05-23-maze-strategy-9x9-design.md`）が「強い相手を小さい盤でハメるのは原理的に困難」で中止になったのと同じ壁。
> 実装一式は `feature/ko-strategy` ブランチに保留（master 未マージ）。以下は棚上げ時点の設計記録。

## 概要

新AIモード `ai:ko`（GUI表示「コウ」）。**地を作って勝つのではなく、コウで競る碁**を打つ戦略。コウの発生を最大化し、損失バジェット内で最もコウ的な手を選ぶ。コウ争いが盤面を未確定に保つため、**碁の複雑化はその副産物**として生じる。対応盤面: 19路・13路。

### 設計の前提（ブレインストーミングでの決定事項）

| 論点 | 決定 |
|---|---|
| 「複雑化」と「コウ」の関係 | **コウが主・複雑さは副産物** |
| コウ不在時の振る舞い | **緊張を高めてコウを誘発**（力戦派的に不安定な形を作る） |
| 対応盤面 | **19路・13路**（他サイズは穏当にフォールバック） |
| リスク許容 | **損失バジェット内で積極コウ**（`ko_max_loss` フィルタ） |
| 実装アプローチ | **独立戦略 `ai:ko` ＋ 純粋盤面ロジックでコウ検出**（KataGo追加照会なし） |

### 迷路戦略（中止）からの教訓の反映

先行した「迷路戦略（MazeStrategy）」は 9路専用の難解化戦略だったが、GUI実機テストで中止された（`docs/superpowers/specs/2026-05-23-maze-strategy-9x9-design.md` 冒頭注記）。中止理由と本設計での回避策:

| 迷路戦略の失敗 | 本設計での回避 |
|---|---|
| 「相手を誤らせる」前提が、9路の humanSL 9段相手には通用しない | コウは**実際に双方危険な局面を作る**メカニズムで、相手の誤りに依存しない。盤面も 19路・13路に拡大 |
| 「鋭さ」最大化が最善手を犠牲にして悪手連発 | `ko_max_loss` の損失フィルタ ＋ 劣勢時キャップ ＋ 選択後安全弁で歯止め |
| 2手先読み照会（K×2）が逐次実行で遅すぎる | コウ検出を**純粋盤面ロジック**で行い、KataGo追加照会はゼロ |

## アーキテクチャ

新クラス `KoStrategy(AIStrategy)` を `katrain/core/ai.py` に追加。既存の `HuntStrategy` / `SiegeStrategy` と同じ**2段階クエリ方式**を踏襲する。

- **Stage 1（humanSLProfile=rank_9d, maxVisits=800）**: `humanPolicy`（人間らしい手の事前分布）を取得
- **Stage 2（クリーン, maxVisits=600, wideRootNoise=0）**: 正確な `scoreLead` を取得し、悪手フィルタに使用

`scoreLead` は常に黒視点のため、`player_sign = 1 if Black else -1`、`loss = player_sign * (best_score - score)` で打つ側視点に変換する（既存戦略と同一の規約）。

ディスパッチは `generate_ai_move`（`katrain/core/ai.py`）に `AI_KO → KoStrategy(self.game, self.settings).generate_move()` を追加する。

## コウ検出（純粋盤面ロジック・追加照会なし）

KaTrain の盤面表現（`katrain/core/game.py` の石鎖 `chains` と直前捕獲 `last_capture`、`game.py:182-190` の捕獲・コウ判定ロジック）を用い、エンジン照会なしで以下を判定する。

### 候補手の4分類

各候補手（Stage 2 の `moveInfos`）を、盤面のコピー上で着手シミュレートして分類する:

| 分類 | 判定条件 |
|---|---|
| **コウ取り/コウ作り**（ko_capture） | その手が**単石を捕獲**し、捕獲後に打った石が**単独石・呼吸点1**になる（相手が次に単石で取り返せるコウ形） |
| **コウ材**（ko_threat） | コウ進行中で取り返しが禁止されているとき、相手の弱い石群を脅かす手（`find_targets` の不安定度 × 近接で近似） |
| **コウ解消**（ko_resolve） | 現在立っているコウを継ぐ/埋める手 |
| **通常手**（normal） | 上記以外 |

### コウ禁止状態の判定

「今コウ禁止が立っているか（相手が直前に単石を取り、こちらが即座に取り返せない状態か）」は、現局面に至る直前手の `last_capture` が単石でコウ形を成すかで判定する。

### ウッテガエシ（snapback）の除外

単石捕獲でも、捕獲した自石に他の呼吸点があれば真のコウ禁止は立たない（snapback）。**コウ形（取った石が単独・呼吸点1）に限り** ko_capture に分類し、snapback は通常手扱いとする。

### 実装上の注意

- `game.py` の `_validate_move_and_update_chains` は `self` を破壊的に更新するため、候補手シミュレートには **盤面（`board` / `chains`）のコピー**を用いる純粋ヘルパーを用意する。盤面配列のコピーと近傍走査のみで、エンジン照会は発生しない。
- 候補約30手 × 小さな配列操作のみのため、1手あたり 100ms 未満を目標とする。

## フェーズと着手の動き

| 局面 | フェーズ | 動き |
|---|---|---|
| **序盤**（コウ不在・コウ禁止なし） | **Seek（種まき）** | 力戦派的に相手へ絡む。接触・切り・未確定な競り合いで**コウが生まれやすい不安定な形**を作る。人間らしさは `humanPolicy`、悪手は `ko_max_loss` で除外 |
| **中盤**（コウ形出現/コウ進行中） | **KoFight（コウ戦）** | コウ形が現れたら `ko_bonus` で食いつき、コウを取る/作る手を最優先。コウを取られて取り返せないときは、相手の弱石を脅かすコウ材を `ko_threat_bonus` で選択し、相手の受けを強要 |
| **終盤**（手数 ≥ `ko_endgame_move`） | **Endgame** | 既存戦略と同じく `humanPolicy` 最大手でヨセ。ただしヨセコウが盤上にあれば KoFight を継続 |

### フェーズ判定

1. **Endgame**: 手数 ≥ `ko_endgame_move`（19路）/ `ceil(0.5 × 盤面マス数)`（13路）。ただし盤上にコウ形/コウ禁止が存在する場合は KoFight を優先
2. **KoFight**: コウ禁止が立っている、または損失バジェット内に ko_capture 候補が1つ以上ある
3. **Seek**: 上記以外

## 重み計算

```
weight = humanPolicy × phase_multiplier

Seek 相:
  phase_multiplier = 力戦重み = unsettled(o)^ko_seek_unsettled_power
                              × proximity(相手石への最近接, stddev=ko_seek_proximity_stddev)
                              × (接触/切り手なら ko_seek_contact_boost)

KoFight 相:
  ko_capture 手               → phase_multiplier = ko_bonus
  ko_threat 手（取り返し待ち時）→ phase_multiplier = ko_threat_bonus × (不安定度×近接)
  ko_resolve / 通常手          → phase_multiplier = 1.0
```

- `unsettled` と `proximity` は `FightingStrategy._build_fighting_weight_dict`（`ai.py:2160`）と同じ考え方を流用する
- `ko_threat` の重みは `find_targets` の不安定度・近接で近似する（**単一局面解析ではコウ材が本当にセンテかを厳密検証できない**ため近似に留める。これは「コウで勝つ」の保証ではなく棋風の実現が目的）

### 選択と安全機構

1. **損失フィルタ**: `loss ≤ ko_max_loss` の候補のみ残す（悪手連発を防止）
2. **重み付き選択**: 残った候補から `weight` で確率選択
3. **選択後安全弁**: 選んだ手の損失が `ko_max_loss` を超えていたら最善重み手にフォールバック（Hunt と同一）
4. **劣勢時キャップ**: `score_lead < -6.0` のとき `ko_max_loss` を `min(設定値, 4.0)` に縮小し自滅を防止（Hunt と同一のハードコード）
5. **failsafe**: 候補ゼロ時は KataGo 最善手を選択
6. **非対応サイズ**: 9路など 19/13 以外では `humanPolicy` 最大手で穏当にフォールバック（Hunt の「9路で空パス」より安全）

## パラメータ

盤面サイズ別デフォルトは `BOARD_PARAMS`（Hunt/Siege と同じ構造）でコード側に持つ。GUI ウィジェットは `AI_OPTION_VALUES` に登録した一組の離散選択肢を表示し、デフォルト選択は 19路値とする。

| パラメータ | デフォルト(19路) | デフォルト(13路) | GUI | 説明 |
|---|---|---|---|---|
| `ko_max_loss` | 6.0 | 4.0 | ✅ ドロップダウン `3.0/4.0/5.0/6.0/8.0` | 許容最大損失（目）。攻撃性・リスク許容 |
| `ko_bonus` | 6.0 | 6.0 | ✅ ドロップダウン `2.0/4.0/6.0/10.0/15.0` | コウ取り/作り手の重み倍率 |
| `ko_threat_bonus` | 3.0 | 3.0 | ✅ ドロップダウン `1.5/2.0/3.0/5.0` | コウ材手の重み倍率 |
| `ko_seek_contact_boost` | 1.5 | 1.5 | ✅ ドロップダウン `1.0/1.5/2.0/3.0` | Seek相の接触/切り手のブースト |
| `ko_endgame_move` | 200 | `ceil(0.5×マス)` | ✅ ドロップダウン `150/180/200/220/250` | ヨセ切替手数（19路） |
| `ko_seek_unsettled_power` | 2.0 | 2.0 | ❌ config手動 | Seek相の未確定地への重み指数 |
| `ko_seek_proximity_stddev` | 3.0 | 2.5 | ❌ config手動 | Seek相の相手石への近接stddev |
| `ko_min_group_size` | 5 | 4 | ❌ config手動 | コウ材判定の弱石群最小サイズ |
| `ko_instability_min` | 0.3 | 0.3 | ❌ config手動 | コウ材判定の最小不安定度 |

**ハードコード定数**: 劣勢閾値 `-6.0`、劣勢時 `ko_max_loss` キャップ `4.0`。

## 変更ファイル

| ファイル | 変更内容 |
|---|---|
| `katrain/core/constants.py` | `AI_KO="ai:ko"`、`AI_STRATEGIES` / `AI_STRATEGIES_RECOMMENDED_ORDER` / `AI_STRENGTH`(nan) / `AI_KEY_PROPERTIES` / `AI_OPTION_VALUES`（GUI5項目）/ `AI_OPTION_ORDER` |
| `katrain/core/ai.py` | `AI_KO` import、`KoStrategy` クラス、`generate_ai_move` ディスパッチ、コウ検出ヘルパー |
| `katrain/config.json`（パッケージ既定） | `ai/ai:ko` に9パラメータ |
| `C:\Users\iwaki\.katrain\config.json`（ユーザーローカル） | 同9パラメータ（**メインセッションで直接編集**。サブエージェント委任不可） |
| i18n `.po` ＋ `python tools/compile_mo.py` | GUIラベル「コウ」と各パラメータ名 |
| `katrain_debug`（CLI） | `ko` 戦略を登録 |
| `.claude/rules/ai-parameters.md` | パラメータ表を追記（**サブエージェント経由で編集**） |
| `tests/` | コウ検出ユニットテスト追加（モデル不要・決定的） |

## 検証方法

1. **ユニットテスト（モデル不要・決定的・CI向き）**: 既知のコウ形を含む SGF / 盤面を構築し、4分類（ko_capture / ko_threat / ko_resolve / normal）の判定とコウ禁止判定、snapback 除外を assert。純粋盤面ロジックのため humanSL モデル無しで回せる
2. **CLI**: `python -m katrain_debug --sgf FILE --move N --strategy ko --output text` でフェーズ・分類・選択手を確認。`--batch` で AI一致率・損失を計測（`--batch` は per-move ログを抑制するため、分類ログ確認は `--move N` で行う）
3. **GUI実機対局**: 最終確認。デバッグログ（`[KoStrategy] Phase:` / `Ko detected:` / `Selected:`）を `log-analysis.md` のパターンで Grep。迷路戦略は GUI テストで中止判断されたため、本戦略も GUI 対局での挙動確認を必須とする

## 設計上の限界（正直な位置づけ）

- **「必ずコウで勝つ」は保証しない**。本戦略はコウの発生を最大化し損失バジェット内で最もコウ的な手を選ぶもので、コウ材が真にセンテかは単一局面解析では厳密検証できない。棋風として「地より絡み・コウで競る碁」を実現するのが目的
- **コウが最後まで現れない静かな碁**では Seek 相が続き、実質「穏やかな力戦派」に縮退する。これは許容する自然な劣化
