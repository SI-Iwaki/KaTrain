# 詰碁モード解析の高速化（精度不変）設計

日付: 2026-07-31
対象: `katrain/core/ai.py`（TsumegoOwnershipStrategy）、`katrain/core/game.py`、`katrain/__main__.py`、`katrain/core/tsumego_frame.py`

## 背景と目標

F4 キャプチャから全着手完了までの体感時間が長い。内訳は
(1) キャプチャ直後の枠採否判定（実測 健全1.1秒 / 救済2.9秒 / 全枠死5.5〜5.7秒）、
(2) 黒番AIの1手ごとの解析（リージョン root 1800visits ≈ 2秒 ＋ 選択則の追加解析 0〜10本 × 0.5〜2秒）。

**制約: 正答精度を落とさない。** 詰碁の選択則・枠判定は実測誤答ケース（case D〜V2）で校正されて
おり、visits・スクリーン・閾値のどれを削っても校正を壊す。よって高速化は
**「同じクエリを、同じ判定順序で、待ち方だけ変えて」** 行う。

## 高速化の原理（なぜ精度に影響しないか）

1. **KataGo は既に4クエリ並列**（`analysis_config.cfg` の `numAnalysisThreads = 4`）なのに、
   Python 側が1本ずつ発行→完了待ちしている。独立なクエリを全部発行してから全部待てば、
   クエリ内容は1バイトも変わらず wall time だけ縮む。並列実行がクエリ結果に与える影響は
   「他クエリと GPU を分け合う＝遅くなる」だけで、探索木・NN 評価値は変わらない
   （run 間非決定性は numSearchThreads=16 由来で従来から存在。E2E 回帰で確認する）。
2. **NN キャッシュ温め（prefetch）**: 同一プロセスの再クエリは NN キャッシュが効いて
   0.2 秒級で返る（case N の実測で確認済みの性質）。ユーザー（白番）の考慮時間中は
   エンジンが遊んでいるので、白の有力応手 top-K の子局面を低優先度で先読みしておけば、
   実際にその手が打たれたときの 1800visits 解析がキャッシュヒットで数倍速くなる。
   **先読みの結果は使わず捨てる**（本物のクエリが従来どおり走る）ので判定影響はゼロ。
   外れてもコストは遊んでいた GPU 時間だけ。

## 変更1: 選択則の子局面解析を並列ファンアウト（ai.py）

「候補ごとに1本ずつ撃って待つ」ループを「全員分を発行 → 全員待ち → **従来と同じ順序で評価**」に
書き換える。対象と意味論保存の根拠:

| 箇所 | 現行 | 並列化 | 意味論保存 |
|---|---|---|---|
| `_verified_choice` | incumbent+挑戦者を直列解析 | 全員同時発行 | values dict を埋めてから評価する構造は同じ。採用判定は従来と同じ挑戦者順 |
| `_ko_route_screen`（pool複数） | 候補ごとに sim構築→解析→PV歩き | sim構築は従来順で直列（break条件保存）、解析だけ同時発行、PV歩きは従来順 | 構造ショートカット（候補自身の1子取り）・sim失敗時のbreakは構築フェーズで同一に再現 |
| `_ko_promotion_choice` | incumbent→shortlist直列（無条件が出たらbreak） | incumbentは先に単独で測る（succeeds なら shortlist を撃たない従来動作を保存）。shortlist は同時発行 | 選択は「クラス最良・同クラスなら先順位」で、breakは計算量最適化にすぎず結果不変（strict `<` 比較のため後続の同クラスは採用されない） |
| `_ko_escape_choice` | incumbent→shortlist直列 | 同上（incumbent None なら中断、の従来動作保存）。shortlist 同時発行 | best は accepted の最大検証値＝全結果が必要で break なし。評価順も従来どおり |
| `_pick_ko_win_move` | コウ形候補ごとに直列解析（最大3） | ko_node 構築は従来順（checked カウント保存）、lead 解析を同時発行 | best は最大値選択で順序不変 |

実装: `_analyze_region_root` を「発行だけ行い待たない」`_start_region_root` と
「複数の結果を待つ」`_wait_region_roots` に分割し、既存 `_analyze_region_root` は
start+wait の合成として残す（他呼び出し箇所は不変）。

### マイクロ最適化: chosen 子局面解析の共用

`_ko_route_screen([chosen])`（毎手1本・wRN=0・untilDepth=6・ownership なし）と
`_ko_promotion_choice` の incumbent 検証（同条件・ownership あり）は同一子局面の再解析。
screen 側を ownership=True で撃って raw 解析結果を generate_move 内で memo し、
promotion の incumbent はそれを再利用する（クエリ設定キー: move/visits/untilDepth/wRN が
一致するときだけ）。includeOwnership は探索に影響しない（ツリー集計のみ）。
declass 確認（wRN=0.04）・脱出 incumbent（wRN=0.04）は条件が違うので memo に当たらず従来どおり。

## 変更2: 白番考慮中の先読み prefetch（game.py + __main__.py）

- 黒（AI）が着手し、その node のリージョン解析（1800visits）が完了した時点で、
  candidate_moves の白応手 top-K（既定3、pass除く）について
  `engine.request_analysis(黒node, next_move=応手, region..., visits=1800, priority=-50)` を発行。
  callback は破棄のみ。次の `Game.play()` 冒頭で
  `engine.terminate_queries(only_for_node=黒node)` により未消化の先読みを打ち切る
  （実クエリが解析スロットを直ちに取れるように）。
- 発火条件: リージョンモード（`region_analysis_visits` あり）かつ次番が人間
  （`katrain.players_info` を getattr ガードで参照。無い環境＝デバッグスタブでは発火しない）。
- 設定: `tsumego_capture/ponder_replies`（int、既定3、0で無効）。キャプチャ適用時に
  `game.region_prefetch_replies` へ伝える（Game 自体は汎用のまま）。
- 効果: 予測的中時、白の応手後の 1800visits 解析が NN キャッシュヒットで大幅短縮。
  外れ時は従来と同一（先読みは terminate 済み）。判定影響ゼロ（結果は捨てる）。

## 変更3: 枠採否判定の並列化（__main__.py + tsumego_frame.py）

- **trial（400visits × 2枠）を同時発行**。独立クエリなので判定不変。
- **読み直しフェーズ**（全枠が浅い読みで死、または閾値近傍の生）:
  現行 `frame_validity_verdicts` は aliveness 順に1本ずつ読み直し、
  「使える枠が確定したら残りの死んだ枠の救済を省略」する動的早期打ち切りを持つ。
  並列版は「読み直しの可能性がある枠（初期 settled_usable でない枠）」を**全部同時発行**し、
  結果の**適用**は従来と同じ aliveness 順・同じ動的スキップ規則で行い、
  従来なら読み直さなかった枠の結果は**破棄**する。→ 採否・採用枠は直列版と完全一致、
  wall time は sum → max。
  実装は `frame_validity_verdicts(..., read_batch=None)` を追加（None なら従来の直列 read）。
- **枠なし比較読み**（全枠死のときだけ使う）: 読み直しフェーズが発生する場合に限り
  投機的に同時発行し、使わなければ破棄。
- 期待効果: 健全 1.1→0.7秒 / 全枠死 5.5→2.5秒前後。

## やらないこと（非目標）

- visits の削減・スクリーンの省略・閾値変更（校正を壊す）
- `analysis_config.cfg` / `katago.exe` の変更（手動管理領域）
- 先読み結果の判定への再利用（データフローを変えない。温めだけ）

## 検証

1. `pytest tests/test_tsumego_*.py`（既存ユニット）＋並列ヘルパーの順序保存ユニットテスト追加
2. E2E 回帰: `generate_move_e2e.py` を README の全ケース・各3run で実行し、期待手
   （D=A4 / E=K1 / F=N8 / G2=A10 / H=N4 / F2=N11orM12 / J=N10 / K=C13 / L=J6 / M=K1 /
   O=A11 / P=J1 / R=G13(残余分散あり) / T=M1,L1 / U=C1 / V=L12 / V2=N13）が不変なこと
3. 時間比較: 改修前に代表ケース（M/O/T/V2）の per-move 所要時間を計測し、改修後と比較
4. GUI 実戦確認はユーザーの次回キャプチャで（`枠の採否判定に X 秒` ログと着手間隔で体感確認）

## 期待効果（概算）

- 通常の1手: root 2秒 + screen 1秒 ≈ 3秒 → 先読み的中時 ≈ 1.3〜1.8秒
- 重い手番（検証・救済・脱出・格上げ発動）: 5〜12秒 → 2.5〜5秒（並列度2〜5）
- キャプチャ: 1.1〜5.7秒 → 0.7〜2.6秒
