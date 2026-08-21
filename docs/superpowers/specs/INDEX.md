# spec 索引

設計と実測の一次記録。全53本。**サイズが大きいものは Read で全読みせず、Grep で該当節だけ引くこと**。

凡例: 🟢 実装済み ／ ⛔ 棚上げ・未実装（コードに存在しない） ／ 📄 調査・解析のみ（実装を伴わない）

---

## AI 戦略（`katrain/core/ai.py`）

作業前に `.claude/rules/ai-strategies.md` と `.claude/rules/ai-parameters.md` を読むこと。

### 力戦派（FightingStrategy）
| spec | |
|---|---|
| `2026-04-06-fighting-human-failsafe-design.md` | 🟢 human モードのフェイルセーフ |
| `2026-05-30-fighting-complexity-design.md` | 🟢 複雑化モード `complex`（切りボーナス＋損失予算ゲート） |
| `2026-05-31-fighting-complex-humble-design.md` | 🟢 `complex_humble`（GUI「力戦派（調整）」） |
| `2026-08-06-fighting-loss-threshold-gui-design.md` | 🟢 悪手フィルタ閾値の GUI 化（盤面サイズ別・フェーズ別） |

### 攻城（SiegeStrategy）・狩猟（HuntStrategy）・一致率低減（Divergence）
| spec | |
|---|---|
| `2026-04-06-ai-diverge-mode-design.md` | 🟢 AI一致率低減モード |
| `2026-04-09-siege-strategy-design.md` | 🟢 攻城戦略 |
| `2026-04-10-siege-humanpolicy-design.md` | 🟢 攻城への humanPolicy 導入 |
| `2026-04-10-fighting-hunt-mode-design.md` | 🟢 狩猟モード |
| `2026-04-10-hunt-invasion-design.md` | 🟢 侵入フェーズ |
| `2026-04-10-hunt-invade-deviation-design.md` | 🟢 侵入フェーズの第一感ぶれ |
| `2026-04-11-hunt-attention-focus-design.md` | 🟢 注意フォーカス（2アンカーmax方式） |
| `2026-04-11-hunt-divergence-strategy-design.md` | 🟢 狩猟＋一致率低減 |
| `2026-04-12-hunt-semeai-pursuit-design.md` | 🟢 攻め合い追撃 |
| `2026-04-12-hunt-score-adaptive-design.md` | 🟢 スコア適応型の損失制御 |
| `2026-04-12-hunt-dead-stone-avoidance-design.md` | 🟢 死石回避 |

### 持碁（JigoStrategy / Jigo9Strategy）
| spec | |
|---|---|
| `2026-04-12-jigo-humanlike-design.md` | 🟢 人間らしさ改修 |
| `2026-04-13-jigo-weak-opponent-design.md` | 🟢 弱相手対応 |
| `2026-04-13-jigo-dynamic-rank-calibration-design.md` | 🟢 動的 rank 閾値校正 |
| `2026-04-13-jigo-large-lead-max-loss-design.md` | 🟢 圧勝時の `max_loss_per_move` 動的緩和 |
| `2026-04-19-jigo-epsilon-tiebreak-design.md` | 🟢 ε バンド tiebreak |
| `2026-05-16-jigo-deception-phase-design.md` | 🟢 油断誘発（deception）フェーズ |
| `2026-05-17-jigo-deception-13path-sliders-design.md` | 🟢 deception の13路スライダー化 |
| `2026-05-30-jigo-force-sanrensei-design.md` | 🟢 三連星強制オプション |
| `2026-06-04-jigo-9x9-dedicated-mode-design.md` | 🟢 持碁（9路）専用モード `ai:jigo9` |
| `2026-08-05-jigo-endgame-humanstyle-design.md` | 🟢 ヨセ段階の HumanStyle 9段委譲 |
| `2026-04-14-jigo-response-speedup-design.md` | 🟢 応答速度改善（案A） |
| `2026-04-14-jigo-stage2-default-analysis-design.md` | ⛔ **REJECT**（案C: Stage2 を既定解析で代替） |
| `2026-04-15-jigo-stage2-per-mode-clean-analysis-design.md` | ⛔ **REJECT**（フェーズ2 scoped・commit 114b654 で revert） |

### 9路・盤面サイズ専用
| spec | |
|---|---|
| `2026-08-06-parity9-strategy-design.md` | 🟢 一致率追随（9路）`ai:parity9` |
| `2026-08-10-enigma9-strategy-design.md` | 🟢 難解 `ai:enigma9` / `enigma13` / `enigma19`（追記2=13路・追記4=19路・追記5=持碁狙い） |
| `2026-05-23-maze-strategy-9x9-design.md` | ⛔ **未実装**（`MazeStrategy` はコードに無い） |
| `2026-05-24-ko-strategy-design.md` | ⛔ **未実装**（`KoStrategy` はコードに無い） |

⛔ の2本が棚上げになった理由は memory `project_per_move_planning_wall.md`（多手先計画が要る結果は
1手ごとの重み付けでは強要できない、という構造的な壁）。

### 評価・デバッグ基盤
| spec | |
|---|---|
| `2026-04-11-strategy-debug-cli-design.md` | 🟢 戦略デバッグCLI（`katrain_debug`） |
| `2026-04-14-lambdago-cheat-metrics-design.md` | 🟢 `--batch` のチート検出メトリック |

---

## 詰碁

作業前に `.claude/rules/tsumego.md`（設計と落とし穴）と `.claude/rules/tsumego-parameters.md`（パラメータ値）を読むこと。

### キャプチャ・盤面認識・出題
| spec | |
|---|---|
| `2026-07-28-tsumego-capture-design.md` | 🟢 画面キャプチャ→KaTrain自動反映 |
| `2026-07-29-tsumego-auto-ai-black-design.md` | 🟢 黒番AI自動着手 |
| `2026-07-29-tsumego-core-region-design.md` | 🟢 コアクラスタ検出とリージョン保証 |
| `2026-07-29-tsumego-frameless-design.md` | 🟢 枠なしモード |
| `2026-08-13-tsumego-web-capture-design.md` | 🟢 Web詰碁（格子線＋座標ラベルOCR） |

### 着手選択・死活ソルバ・回答帳
| spec | |
|---|---|
| `2026-07-29-tsumego-ownership-design.md` | 🟢 **199KB**・`ai:tsumego` の着手選択。case A〜AG の一次記録 |
| `2026-08-01-tsumego-solver-design.md` | 🟢 **150KB**・死活ソルバ（Rust df-pn） |
| `2026-08-02-tsumego-answer-book-design.md` | 🟢 回答帳（誤答問題の手動記録と対称一致再生） |

### 速度（いずれも精度不変）
| spec | |
|---|---|
| `2026-07-31-tsumego-analysis-speedup-design.md` | 🟢 並列発行・先読み |
| `2026-08-03-tsumego-latency-overlap-design.md` | 🟢 手番内投機（段階1+2） |
| `2026-08-03-tsumego-stage3-early-speculation-design.md` | 🟢 root 部分結果からの前倒し投機（段階3） |

### 誤答の調査・修正
| spec | |
|---|---|
| `2026-08-09-tsumego-answer-book-replay-design.md` | 🟢 回答帳リプレイ検証基盤 |
| `2026-08-13-tsumego-answer-book-fixes.md` | 🟢 フルリプレイ（501手順）による外科的修正4件 |
| `2026-08-10-tsumego-ambiguity-analysis.md` | 📄 「候補の曖昧さ」による誤答トリアージ（494件）。**却下した施策も数値つきで記録** |
| `2026-08-15-tsumego-followup-hypothesis.md` | 📄 リプレイ 20260815（538手順）と follow-up 収束仮説の検証 |
| `2026-08-15-tsumego-extraction-expansion-design.md` | 📄 **53KB**・抽出器拡張。§0/§0.7 が結論（A も B も net≈0 で打ち止め） |
| `2026-08-15-tsumego-extraction-expansion-handoff.md` | 📄 同上の引き継ぎ文書 |

---

## 盤面監視

| spec | |
|---|---|
| `2026-08-18-board-watch-design.md` | 🟢 **44KB**・`board_watch.py`。対局アプリの着手を検出して人間側の手として片方向注入（トグル `ctrl+alt+d`） |
| `2026-08-22-tsumego-white-auto-apply-design.md` | 🟢 `board_watch.py` + `__main__.py`。詰碁モードでアプリの白の応手を自動反映（影グリッド方式・`reconcile` は無変更） |

---

## 開発環境

| spec | |
|---|---|
| `2026-04-19-ccmux-introduction-design.md` | 📄 ccmux 導入検討（KaTrain のコードには無関係） |

---

---

## 実装プラン（`docs/superpowers/plans/`）

45本。上の各 spec と**1対1で対応する実装チェックリスト**（ファイル名は spec から `-design` を
除いたもの、例 `2026-08-18-board-watch.md` ↔ `2026-08-18-board-watch-design.md`）。
実装済みの機能では履歴的な資料で、**現在の挙動を知りたいなら spec か rules を見ること**
（プランは着手前に書かれるので、実装中に変わった判断が反映されていない）。

---

## 校正・ベースラインデータ

`calibration-data/<機能名>/` に機能別で格納。命名規則は `<モード>-vs-<相手>-<YYYYMMDD>[-<色>].sgf`、
結果は `<機能>-results-<YYYYMMDD>.md`。既存 SGF は `clean_sgf_main_line.py` で main-line 化してから使う。

- `tsumego/` — E2E スイート（`e2e_suite.py` / `generate_move_e2e.py` / `solver_p1_suite.py`）とケース表
- `tsumego-web/` — Web キャプチャの実スクショ回帰（`validate_web_capture.py`）
- `jigo-speedup/` `jigo-endgame/` `parity9/` `enigma9/` `board-watch/` `runs/` — 各機能の校正結果
