# 中国ルールのパス判定 実測結果（2026-08-06）

対象: `_AREA_PASS_MARGIN` の目数ゲートが、ダメが残っているのに強制パスしていた不具合。

- 局面: `pass_pos.sgf`（13路・中国ルール・コミ7.0・手数119・白番）。実戦ログ `~/.katrain/logs/game_20260806_011214.log` の QUERY:454 から復元
- 再現スクリプト: `pass_probe.py`（humanPolicy 実測）/ `terminate_probe.py`（終局収束の自己対局）

## 1. 失敗局面の実測（`pass_probe.py`）

Stage1 = humanSL `rank_9d` 800visits / Stage2 = クリーン 600visits・wRN=0。

```
pass: humanPolicy=0.0000  loss=0.28  visits=6

top 8 by humanPolicy (score-filter survivors):
  N3    hp=0.4090  loss=-0.00  visits=170
  C1    hp=0.3287  loss=+0.01  visits=104
  C3    hp=0.1119  loss=+0.06  visits=82
  J1    hp=0.0732  loss=+0.17  visits=12
  J10   hp=0.0278  loss=+0.04  visits=119
  M11   hp=0.0152  loss=+0.20  visits=62
  G6    hp=0.0129  loss=+0.08  visits=84
  F6    hp=0.0100  loss=+0.06  visits=85

ARGMAX_HUMANPOLICY: N3   PASS_IS_ARGMAX: False
```

**目数はパスと最善手を分離できない**（実戦ログの当該手番では `loss=0.10`）が、
**humanPolicy は 0.0000 と 0.4090 で決定的に分離する**。

## 2. 終局に収束するか（`terminate_probe.py`）

「`best_gtp_by_score == "pass"` なら強制パス、それ以外は候補＋pass の humanPolicy argmax」
を両者 AI で自己対局。

| 局面 | 挙動 | hp(pass) |
|---|---|---|
| ply 0〜12 | ダメを13個すべて詰める（N3 J1 C1 C3 N1 J10 G6 F6 M11 A11 M13 G12 N12） | 0.0000〜0.0018 |
| ply 13 以降 | 黒がパスを選び始める | 0.3256 → 0.5371 |
| ply 28 | 白もパス → **両者連続パスで正常終局** | 0.7491 |

`RESULT: TERMINATED after 29 plies (two consecutive passes)`

**humanPolicy に委ねても無限対局にならない**ことの実測。ダメが残る間は hp(pass) がほぼ 0、
詰め切ると 0.37〜0.75 に立ち上がる。

## 3. 修正後の E2E 確認

```
python -m katrain_debug --sgf pass_pos.sgf --move 119 --strategy human --output text
→ [HumanStyleStrategy] Area scoring: pass removed from candidates (better non-pass moves exist, best=A9)
→ [HumanStyleStrategy] Endgame (move 119 >= 85): playing top humanPolicy move
→ Move: C1
```

修正前は同じ局面で `Area scoring: pass within 0.5pt of best (loss=0.10), forcing pass` だった。

## 結論

目数条件（`pass_loss < _AREA_PASS_MARGIN`）に **humanPolicy がパスを最上位に置いているか**を
AND する（`_area_scoring_should_pass`）。目数条件を残すのは、パスが明確に損な局面
（実測 ply14 の白 `loss(pass)=+20.65`）で人間モデルが誤ってパスを推した場合の保険。
