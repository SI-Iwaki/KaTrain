# 詰碁キャプチャ: ownership を目的関数にした着手選択（ai:tsumego）設計書

日付: 2026-07-29
ステータス: 承認済み

## 目的

詰碁キャプチャの黒番AIが「盤全体の目数が最良の手」ではなく「**対象石群の死活を最も自分に有利に動かす手**」を
選ぶようにする。詰碁の正解判定は対象石群の死活で決まるのに、KataGo の目的関数は盤全体の目数であり、
この不一致が誤答の主因である。

## 背景: 目数ベースでは解けないことの実測

先行する2ブランチ（枠の配線バグ修正 `ee0376c`、枠なしモード `2049937`）で盤面とリージョンの
問題は解消したが、誤答は残った。原因は目的関数の不一致で、**盤面や枠をどう調整しても解けない**
構造的ジレンマとして現れる。

| ケース | 状態 | root scoreLead / 勝率 | 1位 | 正解手 |
|---|---|---|---|---|
| case B | 枠なし | +37.72 / **1.000** | A5 | B4 +1.84 |
| case B | 枠なし + komi 44.5 | +0.98 / 0.712 | A5 | B4 +1.23 |
| case C | 枠なし | −53.29 / **0.000** | J1 | H1 +2.24 |
| case C | 枠なし + komi −46.5 | +0.34 / 0.464 | **G7（空き地）** | H1 +4.22 (2 visits) |

- **飽和させる**と詰碁の成否が勝敗に影響せず、KataGo は死活を読む動機を持たない
- **バランスを取る**と今度はリージョン内の空き地の手が価値を持つ

枠はこの両方を「盤を埋める＋バランスを取る」で同時に解こうとしていた設計であり、
枠なし＋リージョンだけではジレンマを解けない。**目的関数を変えるのが本筋**。

## ownership が信号になることの実測

候補手ごとの ownership（`includeMovesOwnership`）で、目数が取り逃す差が出る。

### case C（正解 H1 はコウ、AI は J1 を選び黒が死んだ）

```
move   ptLost  visits   B_own（黒石群のownership平均）
J1     +1.85     897   -0.515   ← AIの選択
H1     +2.03     882   -0.129   ← 正解
```

目数では J1 が上、**ownership では H1 が明確に上**。しかも H1 の値は 0 付近で、
**コウ＝どちらのものとも決まっていない状態が中間値として現れる**。

### case B（正解 B4、AI は A5 を選び白が生きた）

連ごとに見ると、攻撃対象の白 G7 は ROOT / A5 / B4 いずれも −0.76 で動かない。
しかし**全連の変化を合計すると B4 が勝つ**（サイズ加重・黒視点）:

```
連                ROOT    A5      B4      B4の寄与
G0(B,1) B8       +0.95   +0.95   +0.92    -0.03
G3(B,1) D4       +0.44   +0.44   +0.01    -0.43
G4(B,1) B3       -0.61   -0.61   -0.12    +0.49
G5(B,1) A2       -0.65   -0.65   -0.43    +0.22
G6(B,1) B1       -0.70   -0.70   -0.54    +0.16
G7(W,2) B5 C5    -0.76   -0.76   -0.76     0
G8(W,6)          -0.77   -0.78   -0.66    +0.66
G9(W,1) F1       -0.42   -0.42   -0.39    +0.03
                        合計:   A5 = -0.06   B4 = +1.10
```

なお同じ局面で D5 は gain +3.49 と最大だが pointsLost が +4.87 と大きい。
**目数のガードが必要**なことを示している。

## アプローチ

採用: **目数ガードで大損の手を弾き、残りを ownership gain で順位付ける**。

不採用:

- **対象石群を事前に同定して、その連だけを見る** — case B の実測では ROOT で最も
  中間値なのは無関係な単独の黒石 D4(+0.44) で、攻撃対象の白 G7(−0.76) ではなかった。
  同定を誤ると完全に外れるため、全連の変化を合計するほうが頑健
- **ownership gain だけで選ぶ（目数ガードなし）** — case B で 4.87目損の D5 が選ばれる
- **目数と ownership の加重和** — 重みの意味づけが恣意的で調整が難しい。
  ガード（ハード制約）＋ gain（目的関数）のほうが各パラメータの役割が明確

## 設計

### 1. 着手選択

リージョン限定解析が完了した候補手 `cn.candidate_moves` に対して:

```
1. 目数ガード
   best = min(pointsLost)
   候補 = { m | m.pointsLost <= best + max_points_behind }   （既定 max_points_behind = 2.0）

2. ownership gain（手番側から見て有利な向きを正とする）
   sign = +1 if 手番 == B else -1
   gain(m) = Σ_{盤上の全石 s} sign × ( own_after(m, s) − own_root(s) )

3. gain 最大の手を選ぶ。同点は pointsLost が小さい方
```

石ごとに合計するので、大きい連の死活ほど重く効く（連の平均ではなくサイズ加重）。
空き地の手はどの石の ownership も動かさないので gain ≈ 0 となり自動的に沈む。

実測での検算:

| ケース | 目数ガード通過 | gain 最大 | 結果 |
|---|---|---|---|
| case C | J1(+1.85), H1(+2.03), L1(+2.24), K1(+3.13) 等 | **H1 +1.61**（J1 は −1.59） | 正解 |
| case B | A5(−0.08), B4(+1.70)。D5(+4.87) は除外 | **B4 +1.10**（A5 は −0.06） | 正解 |

### 2. ownership データの取得

`engine.py:457-458` は `includeOwnership` / `includeMovesOwnership` を
`self.config["_enable_ownership"]` で制御している。ユーザーのローカル設定では
現在 `false` なので **`true` にする必要がある**（パッケージ側 `katrain/config.json` は既に `true`）。

候補手ごとの ownership は `cn.analysis["moves"][gtp]["ownership"]` に入る。
`analysis_dumps` が per-move ownership を捨てるのは SGF へ保存する時だけで、
メモリ上の解析結果には残る（`game_node.py:26-28`）。

ROOT の ownership は `cn.analysis["ownership"]`（= `cn.ownership`）。

配列→盤座標の変換は既存の `var_to_grid(array, (size_x, size_y))` を使う。
戻り値は `grid[y][x]` で y は下origin。`Move.coords` が `(x, y)` なので `grid[y][x]` で引ける。

### 3. 実装場所

`ai.py` に既存の `OwnershipBaseStrategy` 系（`AI_SIMPLE_OWNERSHIP` / `AI_SETTLE_STONES`）が
あり、per-move ownership を使う前例になっている。同じパターンで新戦略を追加する:

- `constants.py`: `AI_TSUMEGO = "ai:tsumego"` を追加。どのリスト（`AI_STRATEGIES_ENGINE` /
  `AI_STRATEGIES_RECOMMENDED_ORDER` / `AI_STRENGTH` 等）に登録するかは、既存の
  `AI_SIMPLE_OWNERSHIP` / `AI_SETTLE_STONES` の登録先に倣う（両者で登録先が異なるため、
  実装時に既存コードを確認して合わせる）。手順は `.claude/rules/ai-settings-gui.md` に従う
- `ai.py`: `@register_strategy(AI_TSUMEGO)` を付けた `TsumegoOwnershipStrategy` を追加
- `config.json`（パッケージ側とユーザーローカルの両方）: `ai/ai:tsumego` の設定に
  `max_points_behind` を置く
- `__main__.py`: キャプチャ適用時の黒番を `AI_DEFAULT` から `AI_TSUMEGO` に変更

### 4. フォールバック

ownership が取れない場合（`_enable_ownership` が false、古い KataGo 等）は
`candidate_moves[0]`（= 現行 `ai:default` と同じ挙動）にフォールバックし、
その旨を `OUTPUT_INFO` でログに出す。無言で劣化させない。

## 検証

### ユニットテスト

`ai.py` の戦略は Kivy 非依存で、`katrain_debug` のスタブ経由でテストできる。
ownership 配列を固定値で与えた偽の解析結果に対して:

- gain 計算が手番の符号を正しく扱う（黒番と白番で符号が反転する）
- 目数ガードが `best + max_points_behind` を超える手を除外する
  （case B の D5 相当: gain 最大だが pointsLost 超過 → 選ばれない）
- gain 同点時に pointsLost の小さい方が選ばれる
- ownership が無い場合に `candidate_moves[0]` へフォールバックする
- `var_to_grid` の座標変換が `Move.coords` と一致する（既知の石の ownership を引けること）

### 実機検証

case A / B / C を含む問題群で `ai:default` と比較する。判定は
「アプリが正解と判定したか」で行う（コウ・セキに持ち込む別解も正解）。

## 限界（既知・未解決）

- **`max_points_behind = 2.0` は case B / C の2ケースからの推定値**。問題群で調整が要る。
  小さすぎると正解手を弾き（case C の H1 は +2.03）、大きすぎると大損の手が入る（case B の D5 は +4.87）
- gain は全連の合計なので、詰碁と無関係な連が同時に動く局面では信号が希釈される
- **KataGo の読み自体が誤っている問題は直らない**。case B は gain では正解に転んだが、
  攻撃対象の白 G7 の ownership は動いておらず、KataGo はこの白を「どちらにせよ生きている」と
  読んでいる。正解に転んだのは黒の死に石が蘇る副次効果によるもので、保証ではない
- 飽和時（勝率0/1）は KataGo の探索自体が甘くなり ownership の推定精度も落ちる。
  komi によるバランス調整の併用は有効な可能性があるが、本設計には含めない（別途評価する）

## 影響範囲

- `katrain/core/constants.py` — `AI_TSUMEGO` の定義と各リストへの登録
- `katrain/core/ai.py` — `TsumegoOwnershipStrategy` の追加
- `katrain/__main__.py` — キャプチャ時の黒番プレイヤー種別
- `katrain/config.json` および `C:\Users\iwaki\.katrain\config.json` — 戦略設定と `_enable_ownership`
- `tests/` — 戦略のユニットテスト

既存の戦略・枠ロジック・リージョン算出は変更しない。
