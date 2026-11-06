# 輪の難易度の色分け Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 盤面監視モードの AI 着手の輪を、AI が打つ前の局面の「人間にとっての難しさ」で 明らか（緑）／普通（設定色）／難解（赤）に塗り分ける。輪の表示は一切遅らせない。

**Architecture:** 相手の手が `Game.play` に入った瞬間に humanSL 9段 8visits を1本先回りで撃ち、結果をそのノードに保存する（`Game._maybe_ring_hp_prefetch`）。輪を出すとき、Kivy 非依存の純関数（`katrain/core/move_difficulty.py`）が親局面の KataGo 通常解析と保存済み humanPolicy から種別を決め、着手ノードに1回だけ記憶する。色は `screen_marker.difficulty_ring_color` が設定色から選ぶ。

**Tech Stack:** Python 3.12・Kivy（GUI のみ）・KataGo analysis engine（humanSL モデル）・pytest

**Spec:** `docs/superpowers/specs/2026-08-18-board-watch-design.md` の「追記11（2026-11-06）」（判定ルール・色・設定・速度ゲートの一次記録）。実装前に必ず読むこと。

## Global Constraints

- 判定の閾値（コード定数・GUI に出さない）: `RING_HARD_MIN_E = 1.5`（9段の期待損失・目）、`RING_OBVIOUS_MIN_HP = 0.8`、`RING_OBVIOUS_MIN_GAP = 1.0`（目）、次善手として数える候補は `visits >= 10`（`RING_GAP_MIN_VISITS`）。優先は 難解 > 明らか。
- 先回りクエリの条件: `humanSLProfile="rank_9d"`・`visits=8`・`include_policy=True`・`ownership=False`・`extra_settings={"humanSLProfile": "rank_9d", "ignorePreRootHistory": False}`・`priority=PRIORITY_EXTRA_AI_QUERY`。難解の `ENIGMA9_HUMAN_PROFILE` / `ENIGMA9_HP_CHILD_VISITS` と同値であること（テストで固定）。
- 発火条件: 色分け ON（`highlight_difficulty` true かつ `highlight_color` が `"off"` でない）× 監視中（`board_watch_active`）× 次番が AI（`players_info[...].player_type == PLAYER_AI`）× リージョンなし。**どれかが偽ならクエリも判定も走らない＝従来とビット同一**。
- 色: 明らか＝`lime`、難解＝`red`、普通＝`highlight_color`。普通の色が lime なら明らか＝`cyan`、red なら難解＝`magenta`。
- **輪は待たない**: 判定は保存済みデータを読むだけ。humanPolicy が無ければ判定なし（普通の色）。判定は着手ノードに最初の1回だけ記憶し、後から humanPolicy が届いても変えない。
- 設定キー `board_watch.highlight_difficulty`（bool・パッケージ既定 `false`）。パッケージ `katrain/config.json` とローカル `C:\Users\iwaki\.katrain\config.json` の**両方**に入れる。**ローカルはメインセッションが直接 Edit する（サブエージェントに任せない）・KaTrain を終了した状態で**。
- 既存ファイルの書き換え: `katrain/` の `.py`・`.kv`・`.po`・`config.json`、`tests/test_board_watch_prefetch.py`、`docs/manual/src/*.html`、`CLAUDE.md` は **CRLF かつ black 未整形**（`screen_marker.py` は LF だが未整形）。**Edit/Write ツールで触らない**（PostToolUse フックが black で全体を再整形する）。下の「パッチ用ヘルパー」を使う python スクリプトで書き換える。新規ファイルは Write でよい。各コミット前に `git diff --stat` で削除行が意図どおりか確かめる。
- `tests/test_screen_marker.py` は LF・black 済み＝Edit ツールでよい。
- i18n: `.po` を変えたら `python tools/compile_mo.py`。
- コミットは日本語の Conventional Commits、末尾に `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`。
- KataGo を使う計測（Task 6）と `tools/manual_screenshots.py`（Task 5）は、**ユーザーが KaTrain で対局していないとき**に走らせる。

### パッチ用ヘルパー（最初に1回作る）

`C:/Users/iwaki/AppData/Local/Temp/claude/C--Users-iwaki-Documents-katrain-1-17-1-1-katrain-1-17-1-1/b27542d2-bd0e-420b-b906-b7b483c50bf9/scratchpad/kpatch.py`（以下 `SCRATCH/kpatch.py`。無ければ Write で作る）:

```python
"""CRLF・black 未整形のファイルを、改行種別を保ったまま書き換える（Edit ツールの black フックを避ける）。"""


def _load(path):
    raw = open(path, "rb").read().decode("utf-8")
    return raw.replace("\r\n", "\n"), "\r\n" in raw


def _save(path, text, crlf):
    if crlf:
        text = text.replace("\n", "\r\n")
    open(path, "wb").write(text.encode("utf-8"))


def patch(path, pairs):
    """pairs = [(old, new), ...]。old は LF で書く。各 old がちょうど1回現れなければ何も書かずに止まる。"""
    text, crlf = _load(path)
    for old, new in pairs:
        n = text.count(old)
        assert n == 1, f"{path}: expected 1 match, got {n}: {old[:80]!r}"
        text = text.replace(old, new)
    _save(path, text, crlf)


def append(path, block):
    """末尾に block を足す（ファイルの改行種別に合わせる）。"""
    text, crlf = _load(path)
    if not text.endswith("\n"):
        text += "\n"
    _save(path, text + block, crlf)
```

各タスクのパッチは `SCRATCH/` に `taskN_patch.py` として Write し（スクラッチのファイルはフックが整形しても無害）、リポジトリ直下から `python SCRATCH/taskN_patch.py` で実行する。スクリプトの先頭は必ず:

```python
import sys
sys.path.insert(0, r"C:/Users/iwaki/AppData/Local/Temp/claude/C--Users-iwaki-Documents-katrain-1-17-1-1-katrain-1-17-1-1/b27542d2-bd0e-420b-b906-b7b483c50bf9/scratchpad")
from kpatch import append, patch
```

## Review Focus

- humanPolicy の配列が壊れている（盤サイズと長さが合わない）・応答に `humanPolicy` が無い・humanSL がエラー → 例外を出さず「判定なし」＝普通の色（Task 1 の `bad_hp` テスト、Task 3 のコールバックのテスト）。
- 同じ手について着手直後・監視スレッドの毎周・設定変更の3経路から呼ばれ、その間に humanPolicy が届く → 色は最初の判定のまま（Task 1 の記憶テストと複数スレッドのテスト）。
- `apply_game_watch_flags` が監視開始・新規対局・設定変更で何度も呼ばれる → 同じノードに先回りクエリは1本だけ（Task 3 の冪等テスト）。
- 輪が指す交点が今の局面の最後の着手ではない（相手の手が入った・新規対局・取り消し）→ 判定せず普通の色、そのノードに記憶も残さない（Task 1 の `current_move_ring_kind` の不一致テスト）。
- 詰碁の監視（リージョンあり）や、次番が人間の局面 → 先回りを撃たない（Task 3 の発火条件テスト）。

---

### Task 1: 判定の純関数（`move_difficulty.py`）

**Files:**
- Create: `katrain/core/move_difficulty.py`
- Test: `tests/test_move_difficulty.py`

**Interfaces:**
- Consumes: `katrain.core.ai` の `enigma9_expected_punish(replies, hp_of)` → `(E, coverage)`、`enigma9_hp_lookup(human_policy, board_size)` → `gtp -> hp`、`enigma9_human_top(human_policy, board_size)` → `(top_gtp, top_hp, pass_hp)` または `None`、`enigma9_reply_table(move_infos, player)` → `(replies, best_gtp)`。`katrain.core.board_watch.move_to_grid(coords, size)` → `(i, j)`。
- Produces:
  - 定数 `RING_OBVIOUS = "obvious"`, `RING_NORMAL = "normal"`, `RING_HARD = "hard"`, `RING_HP_PROFILE = "rank_9d"`, `RING_HP_VISITS = 8`, `RING_HARD_MIN_E`, `RING_OBVIOUS_MIN_HP`, `RING_OBVIOUS_MIN_GAP`, `RING_GAP_MIN_VISITS`
  - `classify_ring_difficulty(move_infos, candidate_moves, human_policy, chosen_gtp, player, board_size) -> (kind | None, info: dict)`
  - `ring_difficulty_of(node, log=None) -> (kind | None, info)`（`node.ring_difficulty` に記憶。親の `ring_human_policy` を読む）
  - `current_move_ring_kind(game, move, log=None) -> kind | None`（`move` は `(i, j)`）
  - `format_ring_difficulty(gtp, kind, info) -> str`

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_move_difficulty.py`:

```python
"""盤面監視の輪の難易度（board-watch spec 追記11）。判定は親局面の解析と humanSL 9段の humanPolicy だけで
決まる純関数で、手ごとに1回だけ記憶する（3経路から呼ばれても色が変わらない）。"""

import threading
from types import SimpleNamespace

import pytest

from katrain.core.move_difficulty import (
    RING_HARD,
    RING_HP_PROFILE,
    RING_HP_VISITS,
    RING_NORMAL,
    RING_OBVIOUS,
    classify_ring_difficulty,
    current_move_ring_kind,
    format_ring_difficulty,
    ring_difficulty_of,
)
from katrain.core.sgf_parser import Move

SIZE = 9
# (gtp, 手番側から見たスコア, visits)。先頭が KataGo の最善手。次善 D4 は 2目・F6 は 2.5目悪い
ROWS = [("E5", 3.0, 1500), ("D4", 1.0, 200), ("F6", 0.5, 100)]
OBVIOUS_HP = {"E5": 0.9, "D4": 0.05, "F6": 0.05}


def hp_array(values, size=SIZE):
    """{gtp: hp} → humanPolicy のフラット配列（盤点数 + 1・末尾 pass・KataGo と同じ並び）"""
    arr = [0.0] * (size * size + 1)
    for gtp, v in values.items():
        x, y = Move.from_gtp(gtp).coords
        arr[(size - 1 - y) * size + x] = v
    return arr


def analysis(rows, player="B"):
    """rows → (生 moveInfos〈scoreLead は黒視点〉, candidate_moves〈relativePointsLost は手番側視点〉)"""
    sign = 1 if player == "B" else -1
    move_infos = [{"move": g, "order": i, "scoreLead": sign * s, "visits": v} for i, (g, s, v) in enumerate(rows)]
    best = rows[0][1]
    cands = [{"move": g, "order": i, "visits": v, "relativePointsLost": best - s} for i, (g, s, v) in enumerate(rows)]
    return move_infos, cands


def classify(rows=ROWS, hp=OBVIOUS_HP, chosen="E5", player="B"):
    infos, cands = analysis(rows, player)
    policy = hp_array(hp) if isinstance(hp, dict) else hp
    return classify_ring_difficulty(infos, cands, policy, chosen, player, (SIZE, SIZE))


def test_obvious_when_best_is_the_9d_first_instinct_and_no_close_alternative():
    kind, info = classify()
    assert kind == RING_OBVIOUS
    assert info["top"] == "E5" and info["top_hp"] == pytest.approx(0.9)
    assert info["gap"] == pytest.approx(2.0)


def test_deviation_from_the_obvious_move_is_not_obvious():
    kind, _info = classify(chosen="D4")  # AI が意図して最善手を外した手には「明らか」の色を付けない
    assert kind == RING_NORMAL


def test_close_alternative_blocks_obvious():
    kind, info = classify(rows=[("E5", 3.0, 1500), ("D4", 2.5, 200), ("F6", 0.5, 100)])
    assert info["gap"] == pytest.approx(0.5)
    assert kind == RING_NORMAL


def test_no_alternative_with_enough_visits_counts_as_no_competitor():
    kind, info = classify(rows=[("E5", 3.0, 1500), ("D4", 1.0, 5), ("F6", 0.5, 3)])
    assert info["gap"] is None
    assert kind == RING_OBVIOUS


def test_hard_when_the_9d_expected_loss_is_large():
    kind, info = classify(hp={"E5": 0.3, "D4": 0.35, "F6": 0.35})
    assert info["E"] == pytest.approx(0.35 * 2.0 + 0.35 * 2.5)
    assert kind == RING_HARD


def test_hard_takes_precedence_over_obvious():
    # 9段の第一感は最善手 80%・次善とも 2目差＝明らかの条件を満たすが、残り 20% が 8目損する
    kind, info = classify(rows=[("E5", 3.0, 1500), ("D4", 1.0, 200), ("F6", -5.0, 100)], hp={"E5": 0.8, "F6": 0.2})
    assert info["E"] == pytest.approx(1.6)
    assert kind == RING_HARD


def test_normal_in_between():
    kind, info = classify(hp={"E5": 0.6, "D4": 0.2, "F6": 0.2})
    assert info["E"] == pytest.approx(0.2 * 2.0 + 0.2 * 2.5)
    assert kind == RING_NORMAL


def test_white_to_move_uses_the_white_perspective():
    kind, info = classify(player="W")
    assert kind == RING_OBVIOUS and info["gap"] == pytest.approx(2.0)


def test_missing_or_malformed_human_policy_is_no_judgement():
    assert classify(hp=None) == (None, {"why": "no_hp"})
    assert classify(hp=[0.1] * 10) == (None, {"why": "bad_hp"})  # 盤サイズと長さが合わない


def test_no_analysis_or_pass_is_no_judgement():
    assert classify_ring_difficulty([], [], hp_array(OBVIOUS_HP), "E5", "B", (SIZE, SIZE)) == (
        None,
        {"why": "no_analysis"},
    )
    assert classify(chosen="pass") == (None, {"why": "pass"})
    assert classify(chosen=None) == (None, {"why": "pass"})


def test_ring_hp_query_matches_the_strategies_parent_query():
    """難解・一致率ひかえめの親局面クエリと同条件＝NN キャッシュを共有するだけで判定の分布を変えない"""
    from katrain.core.ai import ENIGMA9_HP_CHILD_VISITS, ENIGMA9_HUMAN_PROFILE

    assert (RING_HP_PROFILE, RING_HP_VISITS) == (ENIGMA9_HUMAN_PROFILE, ENIGMA9_HP_CHILD_VISITS)


def node_pair(hp, gtp="E5"):
    infos, cands = analysis(ROWS)
    parent = SimpleNamespace(
        analysis={"moves": {d["move"]: d for d in infos}},
        candidate_moves=cands,
        ring_human_policy=hp,
        next_player="B",
        board_size=(SIZE, SIZE),
    )
    node = SimpleNamespace(move=Move.from_gtp(gtp, player="B"), parent=parent)
    return parent, node


def test_judgement_is_computed_once_per_move_and_logged_once():
    parent, node = node_pair(hp=None)
    logs = []
    assert ring_difficulty_of(node, log=logs.append)[0] is None  # humanPolicy がまだ無い＝判定なし
    parent.ring_human_policy = hp_array(OBVIOUS_HP)  # 後から届いても
    assert ring_difficulty_of(node, log=logs.append)[0] is None  # 最初の判定のまま＝色が変わらない
    assert len(logs) == 1 and "判定なし" in logs[0]


def test_judgement_is_stable_across_threads():
    _parent, node = node_pair(hp=hp_array(OBVIOUS_HP))
    logs, kinds = [], []
    threads = [threading.Thread(target=lambda: kinds.append(ring_difficulty_of(node, log=logs.append)[0])) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert kinds == [RING_OBVIOUS] * 8
    assert len(logs) == 1


def fake_game(node):
    return SimpleNamespace(current_node=node, board_size=(SIZE, SIZE))


def test_current_move_ring_kind_judges_only_the_last_move():
    _parent, node = node_pair(hp=hp_array(OBVIOUS_HP))  # E5 = coords (4, 4) = グリッド (4, 4)
    assert current_move_ring_kind(fake_game(node), (4, 4)) == RING_OBVIOUS


def test_current_move_ring_kind_mismatch_is_no_judgement_and_leaves_no_memo():
    _parent, node = node_pair(hp=hp_array(OBVIOUS_HP))
    assert current_move_ring_kind(fake_game(node), (4, 5)) is None  # 輪が別の交点＝今の着手ではない
    assert not hasattr(node, "ring_difficulty")
    assert current_move_ring_kind(fake_game(node), None) is None
    assert current_move_ring_kind(None, (4, 4)) is None
    root_like = SimpleNamespace(move=None, parent=None)
    assert current_move_ring_kind(fake_game(root_like), (4, 4)) is None


def test_format_ring_difficulty():
    kind, info = classify()
    text = format_ring_difficulty("E5", kind, info)
    assert "E5" in text and "明らか" in text and "90%" in text and "-2.0目" in text
    kind, info = classify(hp={"E5": 0.3, "D4": 0.35, "F6": 0.35})
    assert "難解" in format_ring_difficulty("E5", kind, info) and "期待損失 1.6目" in format_ring_difficulty("E5", kind, info)
    kind, info = classify(rows=[("E5", 3.0, 1500), ("D4", 1.0, 5)])
    assert "他に候補なし" in format_ring_difficulty("E5", kind, info)
    assert "判定なし" in format_ring_difficulty("E5", None, {"why": "no_hp"})
    assert "humanPolicy" in format_ring_difficulty("E5", None, {"why": "no_hp"})
```

- [ ] **Step 2: テストが落ちることを確かめる**

Run: `python -m pytest tests/test_move_difficulty.py -q`
Expected: FAIL（`ModuleNotFoundError: No module named 'katrain.core.move_difficulty'`）

- [ ] **Step 3: 実装を書く**

`katrain/core/move_difficulty.py`（新規・Write でよい）:

```python
"""盤面監視の輪を「人間にとっての局面の難しさ」で塗り分ける判定（board-watch spec 追記11・Kivy 非依存）。

判定するのは **AI が打つ前の局面（着手ノードの親）**。材料は2つだけ:
- 親局面の KataGo 通常解析（`strategy.cn` そのもの。監視モードでも親局面はフル解析）
- 親局面の humanSL 9段の humanPolicy（`Game._maybe_ring_hp_prefetch` が相手の着手と同時に 8visits で先回り取得）

難解 = 9段がこの局面で打った場合の期待損失 E（難解戦略と同じ関数）>= RING_HARD_MIN_E。
明らか = AI の手が KataGo の最善手 かつ 9段の第一感が同じ手で hp >= RING_OBVIOUS_MIN_HP かつ
visits >= RING_GAP_MIN_VISITS の他候補が RING_OBVIOUS_MIN_GAP 目以上悪い（または居ない）。
優先は 難解 > 明らか（第一感が 8割でも残りが大損する局面は明らかではない）。それ以外が普通。
humanPolicy が無い・解析が無い・パスは判定なし（None）＝輪は普通の色。

判定は着手ノードに**最初の1回だけ**記憶する（`ring_difficulty_of`）。輪の色は着手直後・監視スレッドの毎周・
設定変更の3か所から付け直されるので、毎回計算し直すと後から届いた humanPolicy で色が変わってちらつく。

ai.py は game.py を import し、game.py はこのモジュールの定数を import する。ai.py の関数は関数の中で
import する（モジュールの読み込みで循環させない）。
"""

import threading

RING_OBVIOUS = "obvious"
RING_NORMAL = "normal"
RING_HARD = "hard"

# 先回りクエリの条件。ai.ENIGMA9_HUMAN_PROFILE / ENIGMA9_HP_CHILD_VISITS と同値（難解・一致率ひかえめの親局面
# クエリと同条件＝NN キャッシュを共有するだけ。humanPolicy は root の NN 出力なので visits を増やしても変わらない）
RING_HP_PROFILE = "rank_9d"
RING_HP_VISITS = 8

RING_HARD_MIN_E = 1.5  # 実戦 307 局面（難解＋13路の子局面プローブの最善手の行）で >= 1.5目が 23%
RING_OBVIOUS_MIN_HP = 0.8  # 実戦の最善手の hp >= 0.8 は 20〜26%
RING_OBVIOUS_MIN_GAP = 1.0  # 次善手との差（目）
RING_GAP_MIN_VISITS = 10  # 次善手として数える候補の visits（= ENIGMA9_REPLY_REF_MIN_VISITS）

_KIND_TEXT = {RING_OBVIOUS: "明らか", RING_NORMAL: "普通", RING_HARD: "難解"}
_NO_JUDGEMENT_TEXT = {
    "no_hp": "humanPolicy が間に合わず",
    "bad_hp": "humanPolicy の形が盤と合わない",
    "no_analysis": "親局面の解析なし",
    "pass": "パス",
}

_LOCK = threading.Lock()  # 着手直後（メッセージループ）と監視スレッドが同時に初回の判定をしても1回にする


def classify_ring_difficulty(move_infos, candidate_moves, human_policy, chosen_gtp, player, board_size):
    """親局面の難しさを (種別 or None, 根拠の dict) で返す（純関数）。

    move_infos: 親局面の生 moveInfos（scoreLead は黒視点）。candidate_moves: `GameNode.candidate_moves`
    （先頭が KataGo の最善手・relativePointsLost は手番側視点）。player: 親局面の手番（＝AI の色）。
    """
    from katrain.core.ai import enigma9_expected_punish, enigma9_hp_lookup, enigma9_human_top, enigma9_reply_table

    if chosen_gtp is None or chosen_gtp == "pass":
        return None, {"why": "pass"}
    if not move_infos or not candidate_moves:
        return None, {"why": "no_analysis"}
    if human_policy is None:
        return None, {"why": "no_hp"}
    top = enigma9_human_top(human_policy, board_size)
    if top is None:
        return None, {"why": "bad_hp"}
    top_gtp, top_hp, _pass_hp = top
    hp_of = enigma9_hp_lookup(human_policy, board_size)
    replies, _best_reply = enigma9_reply_table(move_infos, player)
    e, coverage = enigma9_expected_punish(replies, hp_of)
    best = candidate_moves[0].get("move")
    alternatives = [
        c.get("relativePointsLost", 0.0)
        for c in candidate_moves[1:]
        if c.get("visits", 0) >= RING_GAP_MIN_VISITS and c.get("move") not in (best, None)
    ]
    gap = min(alternatives) if alternatives else None
    info = {"E": e, "coverage": coverage, "top": top_gtp, "top_hp": top_hp, "best": best, "gap": gap, "chosen": chosen_gtp}
    if e >= RING_HARD_MIN_E:
        return RING_HARD, info
    if (
        chosen_gtp == best
        and top_gtp == best
        and top_hp >= RING_OBVIOUS_MIN_HP
        and (gap is None or gap >= RING_OBVIOUS_MIN_GAP)
    ):
        return RING_OBVIOUS, info
    return RING_NORMAL, info


def ring_difficulty_of(node, log=None):
    """着手ノードの難易度 (種別 or None, 根拠) を返す。最初の1回だけ計算して `node.ring_difficulty` に記憶する。

    log を渡すと、計算したその1回だけ `format_ring_difficulty` の1行を流す（対局ログに残る）。
    """
    with _LOCK:
        cached = getattr(node, "ring_difficulty", None)
        if cached is not None:
            return cached
        move = getattr(node, "move", None)
        gtp = move.gtp() if move is not None else None
        parent = getattr(node, "parent", None)
        if parent is None:
            result = (None, {"why": "no_analysis"})
        else:
            analysis = getattr(parent, "analysis", None) or {}
            move_infos = list((analysis.get("moves") or {}).values())
            result = classify_ring_difficulty(
                move_infos,
                parent.candidate_moves if move_infos else [],
                getattr(parent, "ring_human_policy", None),
                gtp,
                parent.next_player,
                parent.board_size,
            )
        node.ring_difficulty = result
    if log is not None:
        log(format_ring_difficulty(gtp, *result))
    return result


def current_move_ring_kind(game, move, log=None):
    """輪が指す交点 move=(i, j) が今の局面の最後の着手なら、その手の難易度の種別を返す（違えば None＝普通の色）。"""
    from katrain.core.board_watch import move_to_grid

    if game is None or move is None:
        return None
    node = getattr(game, "current_node", None)
    last = getattr(node, "move", None)
    if last is None or last.coords is None or getattr(node, "parent", None) is None:
        return None
    if move_to_grid(last.coords, game.board_size[0]) != tuple(move):
        return None
    return ring_difficulty_of(node, log=log)[0]


def format_ring_difficulty(gtp, kind, info):
    """対局ログの1行（例: `盤面監視: R10 の難易度 明らか（第一感 R10 92%・次善 -2.1目）`）"""
    head = f"盤面監視: {gtp} の難易度"
    if kind is None:
        why = info.get("why")
        return f"{head} 判定なし（{_NO_JUDGEMENT_TEXT.get(why, why)}）"
    first = f"第一感 {info['top']} {info['top_hp']:.0%}"
    if kind == RING_OBVIOUS:
        rest = "他に候補なし" if info["gap"] is None else f"次善 -{info['gap']:.1f}目"
        return f"{head} 明らか（{first}・{rest}）"
    return f"{head} {_KIND_TEXT[kind]}（9段の期待損失 {info['E']:.1f}目・{first}）"
```

- [ ] **Step 4: テストが通ることを確かめる**

Run: `python -m pytest tests/test_move_difficulty.py -q`
Expected: 全件 PASS

- [ ] **Step 5: コミット**

```bash
git add katrain/core/move_difficulty.py tests/test_move_difficulty.py
git commit -m "$(cat <<'EOF'
feat(board-watch): 輪の難易度を親局面の解析と humanPolicy から決める純関数を追加

明らか／普通／難解の判定と、着手ノードへの1回だけの記憶（3経路から呼ばれても色が変わらない）。
spec 追記11。

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: 種別から輪の色を選ぶ（`screen_marker.difficulty_ring_color`）

**Files:**
- Modify: `katrain/core/screen_marker.py`（LF・black 未整形 → パッチ）
- Test: `tests/test_screen_marker.py`（LF・black 済み → Edit ツール可）

**Interfaces:**
- Consumes: `move_difficulty.RING_OBVIOUS` / `RING_HARD`（Task 1）、既存の `ring_color(name)` / `RING_COLORS`
- Produces: `difficulty_ring_color(base_name, kind) -> (r, g, b) | None`（`base_name` が `"off"` なら None。kind が None / `"normal"` なら設定色）、`DIFFICULTY_COLORS = {RING_OBVIOUS: ("lime", "cyan"), RING_HARD: ("red", "magenta")}`

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_screen_marker.py` の import に `difficulty_ring_color,` を足し（`HIGHLIGHT_OFF,` の次）、`test_ring_color_presets_fall_back_to_the_default_for_unknown_names` の直後に追加（Edit ツール）:

```python
def test_difficulty_ring_color_keeps_the_three_classes_distinct():
    """難易度の塗り分け（board-watch spec 追記11）: 明らか＝緑・難解＝赤・普通＝設定色。設定色と重なったら
    明らか＝水色・難解＝マゼンタに替えて、どの設定色でも3色が別になる。「表示しない」なら輪を出さない"""
    from katrain.core.move_difficulty import RING_HARD, RING_NORMAL, RING_OBVIOUS

    assert difficulty_ring_color("magenta", RING_OBVIOUS) == RING_COLORS["lime"]
    assert difficulty_ring_color("magenta", RING_HARD) == RING_COLORS["red"]
    assert difficulty_ring_color("magenta", RING_NORMAL) == RING_COLORS["magenta"]
    assert difficulty_ring_color("magenta", None) == RING_COLORS["magenta"]  # 判定なし＝普通の色
    assert difficulty_ring_color("lime", RING_OBVIOUS) == RING_COLORS["cyan"]
    assert difficulty_ring_color("red", RING_HARD) == RING_COLORS["magenta"]
    assert difficulty_ring_color(HIGHLIGHT_OFF, RING_HARD) is None
    for base in [*RING_COLORS, "no-such-color"]:
        colors = {difficulty_ring_color(base, kind) for kind in (RING_OBVIOUS, RING_NORMAL, RING_HARD)}
        assert len(colors) == 3, base
```

- [ ] **Step 2: テストが落ちることを確かめる**

Run: `python -m pytest tests/test_screen_marker.py -q`
Expected: FAIL（`ImportError: cannot import name 'difficulty_ring_color'`）

- [ ] **Step 3: 実装（パッチ）**

`SCRATCH/task2_patch.py`（先頭はヘルパーの3行）:

```python
patch(
    "katrain/core/screen_marker.py",
    [
        (
            "import sys\nimport threading\n\n",
            "import sys\nimport threading\n\nfrom katrain.core.move_difficulty import RING_HARD, RING_OBVIOUS\n\n",
        ),
        (
            '    return [HIGHLIGHT_OFF, *RING_COLORS]\n',
            '    return [HIGHLIGHT_OFF, *RING_COLORS]\n'
            "\n"
            "\n"
            "# 難易度の塗り分け（board-watch spec 追記11）: 種別 -> (既定の色, 普通の色と同じだったときの代わり)。\n"
            "# 緑・赤・水色・マゼンタは黄盤と木目盤のどちらでも見える（橙は黄盤で、白は白石と木目盤で弱い）\n"
            'DIFFICULTY_COLORS = {RING_OBVIOUS: ("lime", "cyan"), RING_HARD: ("red", "magenta")}\n'
            "\n"
            "\n"
            "def difficulty_ring_color(base_name, kind):\n"
            '    """難易度の種別 → 輪の RGB。普通（kind が None / "normal"）は設定色、設定が「表示しない」なら None。\n'
            "\n"
            "    明らか＝緑・難解＝赤。設定色がそれと同じなら代わりの色にして、3種類が必ず別の色になるようにする。\n"
            '    """\n'
            "    base = ring_color(base_name)\n"
            "    if base is None:\n"
            "        return None\n"
            "    pair = DIFFICULTY_COLORS.get(kind)\n"
            "    if pair is None:\n"
            "        return base\n"
            "    primary, alternate = (RING_COLORS[name] for name in pair)\n"
            "    return alternate if primary == base else primary\n",
        ),
    ],
)
```

Run: `python SCRATCH/task2_patch.py`

- [ ] **Step 4: テストが通ることを確かめる**

Run: `python -m pytest tests/test_screen_marker.py tests/test_move_difficulty.py -q`
Expected: 全件 PASS（Win32 の窓テストは Windows で実行される）

- [ ] **Step 5: コミット**

`git diff --stat` で `screen_marker.py` が追加のみ（削除 0〜1 行）であることを確かめてから:

```bash
git add katrain/core/screen_marker.py tests/test_screen_marker.py
git commit -m "$(cat <<'EOF'
feat(board-watch): 輪の難易度の色（明らか＝緑・難解＝赤・普通＝設定色）を選ぶ関数を追加

設定色と重なるときは明らか＝水色・難解＝マゼンタに替え、どの設定色でも3色を別にする。spec 追記11。

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: humanSL の先回り（`Game._maybe_ring_hp_prefetch`）と監視フラグ

**Files:**
- Modify: `katrain/core/game.py`（CRLF・未整形 → パッチ）
- Modify: `katrain/core/board_watch.py`（CRLF・未整形 → パッチ）
- Test: `tests/test_ring_difficulty_prefetch.py`（新規）

**Interfaces:**
- Consumes: `move_difficulty.RING_HP_PROFILE` / `RING_HP_VISITS`（Task 1）、`screen_marker.ring_color`
- Produces:
  - `Game.ring_difficulty_active: bool`（既定 False）
  - `Game._maybe_ring_hp_prefetch(node) -> None`（条件を満たせば1本撃ち、結果を `node.ring_human_policy` に代入。`node.ring_hp_requested = True` で冪等）
  - `Game.play` の非リージョン分岐が通常解析の直後に `_maybe_ring_hp_prefetch(played_node)` を呼ぶ
  - `board_watch.ring_difficulty_enabled(cfg) -> bool`
  - `apply_game_watch_flags(game, cfg)` が `game.ring_difficulty_active` を張り、`game._maybe_ring_hp_prefetch(game.current_node)` を呼ぶ（属性が無い偽物の game では呼ばない）
  - `clear_game_watch_flags(game)` が `game.ring_difficulty_active = False`

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_ring_difficulty_prefetch.py`:

```python
"""輪の難易度（board-watch spec 追記11）のための humanSL 先回り。守っているのは:
1. 条件が難解の親局面クエリと同一（9段・8visits・ownership なし）＝NN キャッシュを共有するだけ
2. 色分け ON × 監視中 × 次番が AI × リージョンなし のときだけ撃つ（どれかが偽ならクエリ 0 本＝従来とビット同一）
3. 同じノードには1本だけ（監視開始・新規対局・設定変更で何度呼ばれても）
4. 失敗・humanPolicy の無い応答でも例外を出さず、判定なし（普通の色）に倒れる
"""

import types

import pytest

from katrain.core.board_watch import apply_game_watch_flags, clear_game_watch_flags, ring_difficulty_enabled
from katrain.core.constants import PLAYER_AI, PLAYER_HUMAN, PRIORITY_EXTRA_AI_QUERY
from katrain.core.game import BaseGame, Game, GameNode
from katrain.core.move_difficulty import RING_HP_PROFILE, RING_HP_VISITS
from katrain.core.sgf_parser import Move


class FakeEngine:
    def __init__(self):
        self.requests = []
        self.terminated = []

    def request_analysis(self, node, **kwargs):
        self.requests.append((node, kwargs))

    def terminate_queries(self, only_for_node=None, lock=True):
        self.terminated.append(only_for_node)


class FakeKatrain:
    def __init__(self, ai):
        human = "W" if ai == "B" else "B"
        self.players_info = {
            ai: types.SimpleNamespace(player_type=PLAYER_AI),
            human: types.SimpleNamespace(player_type=PLAYER_HUMAN),
        }

    def log(self, *args, **kwargs):
        pass


def _game(ai="W", ring=True, watch=True):
    """Game.play() を通せる素の Game（エンジン起動・解析スレッドなし）。ai は KaTrain の AI の色"""
    katrain = FakeKatrain(ai)
    base = BaseGame(katrain, move_tree=GameNode(properties={"SZ": 9, "RU": "chinese", "KM": 7.0}))
    engine = FakeEngine()
    game = Game.__new__(Game)
    game.__dict__.update(base.__dict__)
    game.engines = {"B": engine, "W": engine}
    game.region_of_interest = None
    game.board_watch_active = watch
    game.ring_difficulty_active = ring
    game.board_watch_prefetch_replies = 0
    game.board_watch_probe_warm = False
    game._board_watch_prefetch_nodes = []
    game._region_prefetch_nodes = []
    game._early_speculation_nodes = []
    game._enigma_ponder_owner = None
    return game, engine


def ring_requests(engine):
    return [(n, kw) for n, kw in engine.requests if (kw.get("extra_settings") or {}).get("humanSLProfile")]


def test_opponent_move_fires_one_9d_humansl_query_for_the_ai_position():
    game, engine = _game(ai="W")
    node = game.play(Move.from_gtp("E5", player="B"))  # 相手（黒＝アプリ）の手 → 次番は AI（白）
    rings = ring_requests(engine)
    assert len(rings) == 1 and rings[0][0] is node
    kwargs = rings[0][1]
    assert kwargs["visits"] == RING_HP_VISITS and kwargs["include_policy"] is True and kwargs["ownership"] is False
    assert kwargs["extra_settings"] == {"humanSLProfile": RING_HP_PROFILE, "ignorePreRootHistory": False}
    assert kwargs["priority"] == PRIORITY_EXTRA_AI_QUERY
    assert len(engine.requests) == 2  # 通常解析はそのまま1本


def test_callback_stores_the_human_policy_and_tolerates_errors():
    game, engine = _game(ai="W")
    node = game.play(Move.from_gtp("E5", player="B"))
    kwargs = ring_requests(engine)[0][1]
    kwargs["error_callback"]({"error": "humanSL model missing"})  # 失敗しても例外にしない
    kwargs["callback"]({"rootInfo": {}}, False)  # humanPolicy の無い応答
    assert getattr(node, "ring_human_policy", None) is None
    kwargs["callback"]({"humanPolicy": [0.5] * 82}, True)  # 途中経過は使わない
    assert getattr(node, "ring_human_policy", None) is None
    kwargs["callback"]({"humanPolicy": [0.5] * 82}, False)
    assert node.ring_human_policy == [0.5] * 82


@pytest.mark.parametrize(
    "kwargs",
    [
        {"ai": "W", "ring": False},  # 色分け OFF
        {"ai": "W", "watch": False},  # 監視していない
        {"ai": "B"},  # 次番（白）は人間＝AI の手番ではない
    ],
)
def test_no_query_unless_ring_on_and_watching_and_ai_to_move(kwargs):
    game, engine = _game(**kwargs)
    game.play(Move.from_gtp("E5", player="B"))
    assert ring_requests(engine) == []
    assert len(engine.requests) == 1  # 通常解析だけ＝従来どおり


def test_no_query_on_the_tsumego_region_path():
    game, engine = _game(ai="B")  # root は黒番＝AI の手番。止める理由がリージョンだけになるようにする
    game.region_of_interest = [0, 4, 0, 4]
    game._maybe_ring_hp_prefetch(game.current_node)
    assert ring_requests(engine) == []


def test_prefetch_is_idempotent_per_node():
    game, engine = _game(ai="B")  # root は黒番＝AI の手番
    game._maybe_ring_hp_prefetch(game.current_node)
    game._maybe_ring_hp_prefetch(game.current_node)
    assert len(ring_requests(engine)) == 1
    game2, engine2 = _game(ai="B")
    game2.current_node.ring_human_policy = [0.0] * 82  # 既に持っている
    game2._maybe_ring_hp_prefetch(game2.current_node)
    assert ring_requests(engine2) == []


def test_apply_game_watch_flags_turns_the_ring_on_and_fires_for_the_current_position_once():
    game, engine = _game(ai="B", ring=False)
    cfg = {"highlight_difficulty": True, "highlight_color": "magenta"}
    apply_game_watch_flags(game, cfg)
    apply_game_watch_flags(game, cfg)  # 監視開始のあと設定変更でも呼ばれる
    assert game.ring_difficulty_active is True
    assert len(ring_requests(engine)) == 1  # AI 黒番の初手（root）を拾う・同じノードに2本目は撃たない
    clear_game_watch_flags(game)
    assert game.ring_difficulty_active is False


def test_apply_game_watch_flags_keeps_the_ring_off_when_the_ring_is_hidden():
    game, engine = _game(ai="B", ring=False)
    apply_game_watch_flags(game, {"highlight_difficulty": True, "highlight_color": "off"})
    assert game.ring_difficulty_active is False and ring_requests(engine) == []


def test_ring_difficulty_enabled():
    assert ring_difficulty_enabled({"highlight_difficulty": True, "highlight_color": "cyan"}) is True
    assert ring_difficulty_enabled({"highlight_difficulty": True}) is True  # 色が無い＝既定の色で輪は出る
    assert ring_difficulty_enabled({"highlight_difficulty": True, "highlight_color": "off"}) is False
    assert ring_difficulty_enabled({"highlight_color": "cyan"}) is False
    assert ring_difficulty_enabled(None) is False
```

- [ ] **Step 2: テストが落ちることを確かめる**

Run: `python -m pytest tests/test_ring_difficulty_prefetch.py -q`
Expected: FAIL（`ImportError: cannot import name 'ring_difficulty_enabled'`）

- [ ] **Step 3: 実装（パッチ）**

`SCRATCH/task3_patch.py`（先頭はヘルパーの3行）:

```python
patch(
    "katrain/core/game.py",
    [
        (
            "    PRIORITY_TSUMEGO_SPECULATION,\n)\n",
            "    PRIORITY_TSUMEGO_SPECULATION,\n    PRIORITY_EXTRA_AI_QUERY,\n)\n",
        ),
        (
            "        self.board_watch_active = False  # 対局監視スレッドが走っているか（__main__ が ON/OFF で設定）\n",
            "        self.board_watch_active = False  # 対局監視スレッドが走っているか（__main__ が ON/OFF で設定）\n"
            "        # 輪の難易度の色分け（board-watch spec 追記11）。ON の間だけ AI の手番の局面に humanSL を先回りで撃つ\n"
            "        self.ring_difficulty_active = False\n",
        ),
        (
            "                    analyze_fast=self._enigma_ponder_defers_own_analysis(move),\n"
            "                )\n"
            "                self._maybe_board_watch_prefetch(played_node)\n",
            "                    analyze_fast=self._enigma_ponder_defers_own_analysis(move),\n"
            "                )\n"
            "                self._maybe_ring_hp_prefetch(played_node)\n"
            "                self._maybe_board_watch_prefetch(played_node)\n",
        ),
        (
            "    def _enigma_ponder_defers_own_analysis(self, move):\n",
            '    def _maybe_ring_hp_prefetch(self, node):\n'
            '        """盤面監視の輪の難易度（board-watch spec 追記11）用に、AI が打つ局面の humanSL 9段を先回りで1本撃つ。\n'
            "\n"
            "        相手の着手が入った直後（通常解析の発行と同時）に撃つ。AI の着手生成は通常解析の完了を待ってから\n"
            "        始まる（`__main__._do_update_state`）ので、8visits のこのクエリはその間に終わる＝輪を出すときには\n"
            "        揃っていて、輪は待たない。結果は `node.ring_human_policy` に1回代入するだけ（読むのは\n"
            "        `move_difficulty.ring_difficulty_of`）。条件は難解・一致率ひかえめの親局面クエリと同一（9段・8visits・\n"
            "        ownership なし）＝それらの戦略とは NN キャッシュを共有するだけ。発火は 色分け ON × 監視中 ×\n"
            "        次番が AI × リージョンなし のときだけ（どれかが偽ならクエリ 0 本）。同じノードには1本だけ。\n"
            '        """\n'
            '        if not getattr(self, "ring_difficulty_active", False) or not getattr(self, "board_watch_active", False):\n'
            "            return\n"
            "        if node is None or self.region_of_interest:\n"
            "            return\n"
            '        if getattr(node, "ring_hp_requested", False) or getattr(node, "ring_human_policy", None) is not None:\n'
            "            return\n"
            '        players_info = getattr(self.katrain, "players_info", None)\n'
            "        try:\n"
            "            if not players_info or players_info[node.next_player].player_type != PLAYER_AI:\n"
            "                return\n"
            "        except (KeyError, AttributeError):\n"
            "            return\n"
            "        node.ring_hp_requested = True\n"
            "\n"
            "        def on_result(analysis, partial_result):\n"
            '            if not partial_result and analysis and analysis.get("humanPolicy") is not None:\n'
            '                node.ring_human_policy = analysis["humanPolicy"]\n'
            "\n"
            "        self.engines[node.next_player].request_analysis(\n"
            "            node,\n"
            "            callback=on_result,\n"
            "            error_callback=lambda *_args, **_kwargs: None,  # 失敗＝判定なし（輪は普通の色）\n"
            "            visits=RING_HP_VISITS,\n"
            "            include_policy=True,\n"
            "            ownership=False,\n"
            '            extra_settings={"humanSLProfile": RING_HP_PROFILE, "ignorePreRootHistory": False},\n'
            "            priority=PRIORITY_EXTRA_AI_QUERY,\n"
            "        )\n"
            "\n"
            "    def _enigma_ponder_defers_own_analysis(self, move):\n",
        ),
        (
            "from katrain.core.lang import i18n, rank_label\n",
            "from katrain.core.lang import i18n, rank_label\n"
            "from katrain.core.move_difficulty import RING_HP_PROFILE, RING_HP_VISITS\n",
        ),
    ],
)
patch(
    "katrain/core/board_watch.py",
    [
        (
            "def apply_game_watch_flags(game, cfg):\n",
            "def ring_difficulty_enabled(cfg):\n"
            '    """輪を局面の難しさで塗り分けるか（設定 highlight_difficulty が ON かつ輪が「表示しない」でない・追記11）"""\n'
            "    from katrain.core.screen_marker import ring_color\n"
            "\n"
            "    cfg = cfg or {}\n"
            '    return bool(cfg.get("highlight_difficulty", False)) and ring_color(cfg.get("highlight_color")) is not None\n'
            "\n"
            "\n"
            "def apply_game_watch_flags(game, cfg):\n",
        ),
        (
            "    game.board_watch_active = True\n"
            "    game.board_watch_prefetch_replies = prefetch\n"
            "    return prefetch\n",
            "    game.board_watch_active = True\n"
            "    game.board_watch_prefetch_replies = prefetch\n"
            "    # 輪の難易度の色分け（追記11）。監視開始・新規対局・設定変更のどれでも、今の局面が AI の手番なら先回りを撃つ\n"
            "    # （AI 黒番の初手＝root と、対局の途中で ON にした場合を拾う。同じノードには2本撃たない）\n"
            "    game.ring_difficulty_active = ring_difficulty_enabled(cfg)\n"
            '    prefetch_hp = getattr(game, "_maybe_ring_hp_prefetch", None)\n'
            "    if prefetch_hp is not None:\n"
            '        prefetch_hp(getattr(game, "current_node", None))\n'
            "    return prefetch\n",
        ),
        (
            "    game.board_watch_probe_warm = False\n    game._cancel_board_watch_prefetch()\n",
            "    game.board_watch_probe_warm = False\n"
            "    game.ring_difficulty_active = False\n"
            "    game._cancel_board_watch_prefetch()\n",
        ),
    ],
)
```

Run: `python SCRATCH/task3_patch.py`

- [ ] **Step 4: テストが通ることを確かめる**

Run: `python -m pytest tests/test_ring_difficulty_prefetch.py tests/test_board_watch_prefetch.py tests/test_board_watch.py tests/test_move_difficulty.py -q`
Expected: 全件 PASS（既存の `test_play_*` は `ring_difficulty_active` を持たない Game でもクエリ1本のまま）

- [ ] **Step 5: コミット**

`git diff --stat` で `game.py`・`board_watch.py` が追加中心（削除は置換した 1〜3 行）であることを確かめてから:

```bash
git add katrain/core/game.py katrain/core/board_watch.py tests/test_ring_difficulty_prefetch.py
git commit -m "$(cat <<'EOF'
feat(board-watch): 相手の着手と同時に AI の局面の humanSL 9段を先回りで1本撃つ

輪の難易度用。色分け ON × 監視中 × 次番が AI × リージョンなし のときだけ発火し、
結果はノードに保存するだけ（輪は待たない）。OFF ならクエリ 0 本。spec 追記11。

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 4: 輪の色を選ぶ配線（`__main__._board_watch_ahead` と設定変更の当て直し）

**Files:**
- Modify: `katrain/__main__.py`（CRLF・未整形 → パッチ）
- Test: `tests/test_board_watch_prefetch.py`（CRLF・未整形 → `append`）

**Interfaces:**
- Consumes: `move_difficulty.current_move_ring_kind(game, move, log)`（Task 1）、`screen_marker.difficulty_ring_color(base_name, kind)`（Task 2）、`apply_game_watch_flags`（Task 3・`__main__.py:67` で import 済み）
- Produces: `_board_watch_ahead(move)` が `highlight_difficulty` ON のとき種別の色で輪を出す。`_board_watch_highlight_refresh()` がフラグを張り直す。

- [ ] **Step 1: 失敗する静的テストを書く**

足すテスト本体を `SCRATCH/task4_test_block.txt` に Write する（そのまま書く＝エスケープ不要。`.txt` なのでフックは整形しない）:

```python
def test_ring_difficulty_is_wired_through_main():
    """静的検査（追記11）: `_board_watch_ahead` は色分け ON（設定 highlight_difficulty を毎回読む）のとき
    `current_move_ring_kind` と `difficulty_ring_color` で色を選び、設定変更の当て直し
    `_board_watch_highlight_refresh` は `apply_game_watch_flags` でフラグを張り直す（途中で ON にしたら今の局面から効く）"""
    main_path = os.path.join(os.path.dirname(__file__), "..", "katrain", "__main__.py")
    src = open(main_path, encoding="utf-8").read()
    ahead = src.split("def _board_watch_ahead(")[1].split("\n    def ")[0]
    assert '"highlight_difficulty"' in ahead and '"highlight_color"' in ahead
    assert "current_move_ring_kind" in ahead and "difficulty_ring_color" in ahead
    tree = ast.parse(src)
    funcs = {n.name: n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
    called = [
        getattr(c.func, "id", None) or getattr(c.func, "attr", None)
        for c in ast.walk(funcs["_board_watch_highlight_refresh"])
        if isinstance(c, ast.Call)
    ]
    assert "apply_game_watch_flags" in called
```

`SCRATCH/task4_test.py`（先頭はヘルパーの3行）:

```python
append("tests/test_board_watch_prefetch.py", "\n\n" + open(r"SCRATCH_DIR/task4_test_block.txt", encoding="utf-8").read())
```

（`SCRATCH_DIR` はスクラッチの絶対パスに置き換える。`ast` と `os` はテストファイルの中ほどで既に import 済み。）

Run: `python SCRATCH/task4_test.py && python -m pytest tests/test_board_watch_prefetch.py -q -k ring_difficulty`
Expected: FAIL（`assert '"highlight_difficulty"' in ahead`）

- [ ] **Step 2: 実装（パッチ）**

`SCRATCH/task4_patch.py`:

```python
patch(
    "katrain/__main__.py",
    [
        (
            "        from katrain.core.screen_marker import ring_color\n"
            "\n"
            '        cfg = self._config.get("board_watch") or {}\n',
            "        from katrain.core.move_difficulty import current_move_ring_kind\n"
            "        from katrain.core.screen_marker import difficulty_ring_color, ring_color\n"
            "\n"
            '        cfg = self._config.get("board_watch") or {}\n',
        ),
        (
            '            color = ring_color(cfg.get("highlight_color"))  # None ＝設定「表示しない」\n'
            "            if point is None or color is None:\n",
            '            color = ring_color(cfg.get("highlight_color"))  # None ＝設定「表示しない」\n'
            '            if color is not None and cfg.get("highlight_difficulty"):\n'
            "                # 局面の難しさで塗り分ける（spec 追記11）。判定は着手ノードに1回だけ記憶されるので、\n"
            "                # 着手直後・監視スレッドの毎周・設定変更のどこから呼んでも同じ色（ちらつかない）\n"
            "                kind = current_move_ring_kind(self.game, move, log=lambda message: self.log(message, OUTPUT_INFO))\n"
            '                color = difficulty_ring_color(cfg.get("highlight_color"), kind)\n'
            "            if point is None or color is None:\n",
        ),
        (
            '        if watcher is None or getattr(self, "_board_watch_kind", None) != "game":\n'
            "            return\n"
            "        self._board_watch_ahead(watcher.ahead_move)\n",
            '        if watcher is None or getattr(self, "_board_watch_kind", None) != "game":\n'
            "            return\n"
            "        # 難易度の色分けを途中で ON/OFF したら、フラグを張り直して今の局面から効かせる（spec 追記11）\n"
            '        apply_game_watch_flags(self.game, self._config.get("board_watch"))\n'
            "        self._board_watch_ahead(watcher.ahead_move)\n",
        ),
    ],
)
```

Run: `python SCRATCH/task4_patch.py`

- [ ] **Step 3: テストが通ることを確かめる**

Run: `python -m pytest tests/test_board_watch_prefetch.py tests/test_board_watch.py tests/test_ring_difficulty_prefetch.py tests/test_move_difficulty.py tests/test_screen_marker.py -q`
Expected: 全件 PASS（既存の `test_highlight_settings_are_exposed_in_the_config_popup` も `"highlight_color"` リテラルが残るので PASS）

Run: `python -c "import os; os.environ['KIVY_NO_ARGS']='1'; import ast; ast.parse(open('katrain/__main__.py', encoding='utf-8').read()); print('ok')"`
Expected: `ok`

- [ ] **Step 4: コミット**

```bash
git add katrain/__main__.py tests/test_board_watch_prefetch.py
git commit -m "$(cat <<'EOF'
feat(board-watch): 輪を出すときに局面の難しさで色を選ぶ

highlight_difficulty が ON なら、着手ノードに記憶した判定で 明らか／普通／難解 の色にする。
設定変更の当て直しでフラグも張り直す。spec 追記11。

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 5: 設定（両方の config・設定画面のチェック・i18n）

**Files:**
- Modify: `katrain/config.json`（CRLF → パッチ）
- Modify: `C:\Users\iwaki\.katrain\config.json`（**メインセッションが Edit ツールで直接**・KaTrain 終了中）
- Modify: `katrain/popups.kv`（CRLF → パッチ）
- Modify: `katrain/i18n/locales/jp/LC_MESSAGES/katrain.po`, `katrain/i18n/locales/en/LC_MESSAGES/katrain.po`（CRLF → パッチ）→ `.mo` を再生成
- Test: `tests/test_board_watch_prefetch.py`（`append`）

**Interfaces:**
- Consumes: Task 4 の `_board_watch_ahead` が読む `board_watch/highlight_difficulty`
- Produces: 設定画面の一般設定の輪の色の行に「難易度」チェック（`input_property: "board_watch/highlight_difficulty"`）

- [ ] **Step 1: 失敗する静的テストを書く**

足すテスト本体を `SCRATCH/task5_test_block.txt` に Write する:

```python
def test_ring_difficulty_setting_is_exposed_in_the_config_popup():
    """静的検査（追記11）: 難易度の色分けは輪の色と**同じ行**のチェック（一般設定欄の行を増やさない）。
    パッケージ config の既定は OFF、表示名は en/jp の両方にある"""
    import json

    root = os.path.join(os.path.dirname(__file__), "..", "katrain")
    lines = open(os.path.join(root, "popups.kv"), encoding="utf-8").read().split("\n")
    start = next(i for i, line in enumerate(lines) if 'input_property: "board_watch/highlight_color"' in line)
    # 輪の色の行（MDBoxLayout の子＝インデント 16 以上）が終わるのは、インデント 12 以下の次の行
    end = next(
        i for i in range(start + 1, len(lines)) if lines[i].strip() and len(lines[i]) - len(lines[i].lstrip()) <= 12
    )
    row = "\n".join(lines[start:end])
    assert 'input_property: "board_watch/highlight_difficulty"' in row
    for locale in ("en", "jp"):
        po = open(os.path.join(root, "i18n", "locales", locale, "LC_MESSAGES", "katrain.po"), encoding="utf-8").read()
        assert 'msgid "board_watch:highlight_difficulty"' in po, locale
    pkg = json.load(open(os.path.join(root, "config.json"), encoding="utf-8"))
    assert pkg["board_watch"]["highlight_difficulty"] is False
```

`SCRATCH/task5_test.py`（先頭はヘルパーの3行）:

```python
append("tests/test_board_watch_prefetch.py", "\n\n" + open(r"SCRATCH_DIR/task5_test_block.txt", encoding="utf-8").read())
```

Run: `python SCRATCH/task5_test.py && python -m pytest tests/test_board_watch_prefetch.py -q -k ring_difficulty_setting`
Expected: FAIL

- [ ] **Step 2: パッケージ config・kv・po のパッチ**

`SCRATCH/task5_patch.py`:

```python
patch(
    "katrain/config.json",
    [
        (
            '        "move_cursor": false\n    },\n',
            '        "move_cursor": false,\n        "highlight_difficulty": false\n    },\n',
        )
    ],
)
patch(
    "katrain/popups.kv",
    [
        (
            "                    size_hint: 0.5, 0.8\n"
            "                    pos_hint: {'center_y': 0.5}\n"
            "                    font_size: sp(Theme.DESC_FONT_SIZE)\n"
            "                SmallDescriptionLabel:\n"
            '                    text: i18n._("board_watch:move_cursor")\n'
            "                    size_hint_x: 0.36\n"
            "                LabelledCheckBox:\n"
            '                    input_property: "board_watch/move_cursor"\n'
            "                    pos_hint: {'center_y': 0.5}\n",
            "                    size_hint: 0.42, 0.8\n"
            "                    pos_hint: {'center_y': 0.5}\n"
            "                    font_size: sp(Theme.DESC_FONT_SIZE)\n"
            "                SmallDescriptionLabel:\n"
            '                    text: i18n._("board_watch:move_cursor")\n'
            "                    size_hint_x: 0.26\n"
            "                LabelledCheckBox:\n"
            '                    input_property: "board_watch/move_cursor"\n'
            "                    pos_hint: {'center_y': 0.5}\n"
            "                # 輪の色を局面の難しさで塗り分ける（明らか＝緑・難解＝赤・普通＝左の色。spec 追記11）\n"
            "                SmallDescriptionLabel:\n"
            '                    text: i18n._("board_watch:highlight_difficulty")\n'
            "                    size_hint_x: 0.26\n"
            "                LabelledCheckBox:\n"
            '                    input_property: "board_watch/highlight_difficulty"\n'
            "                    pos_hint: {'center_y': 0.5}\n",
        )
    ],
)
for locale, text in (("jp", "難易度"), ("en", "difficulty")):
    cursor = "カーソル" if locale == "jp" else "cursor"
    patch(
        f"katrain/i18n/locales/{locale}/LC_MESSAGES/katrain.po",
        [
            (
                f'msgid "board_watch:move_cursor"\nmsgstr "{cursor}"\n',
                f'msgid "board_watch:move_cursor"\nmsgstr "{cursor}"\n'
                f'\nmsgid "board_watch:highlight_difficulty"\nmsgstr "{text}"\n',
            )
        ],
    )
```

Run: `python SCRATCH/task5_patch.py && python tools/compile_mo.py`
Expected: エラーなし。`git status` に `.mo` 2本の変更が出る

- [ ] **Step 3: ローカル config（メインセッションが直接）**

1. KaTrain が起動していないことを確かめる（起動中の編集は終了時の全体書き戻しで消える）:
   PowerShell: `Get-Process | Where-Object { $_.MainWindowTitle -like '*KaTrain*' } | Select-Object Id, MainWindowTitle`
   Expected: 何も出ない（出たらユーザーに KaTrain を閉じてもらう）
2. Edit ツールで `C:\Users\iwaki\.katrain\config.json` の `"move_cursor": true` を `"move_cursor": true,\n        "highlight_difficulty": true` に変える（ユーザーはこの機能を使う＝ローカルは ON。インデントは周囲と同じ 8 スペース）。
3. 確かめる: `python -c "import json; print(json.load(open(r'C:\Users\iwaki\.katrain\config.json', encoding='utf-8'))['board_watch'])"`
   Expected: `'highlight_difficulty': True` が入っている

- [ ] **Step 4: テストと画面の確認**

Run: `python -m pytest tests/test_board_watch_prefetch.py tests/test_screen_marker.py -q`
Expected: 全件 PASS

画面（ユーザーが対局していないとき）: `python tools/manual_screenshots.py --groups settings` を実行し、`docs/manual/img/popup_settings.png` を Read ツールで開いて、一般設定の「AI 着手の強調表示（監視）」の行でスピナー・「カーソル」・「難易度」とチェック2つが重ならず収まっていることを確かめる。はみ出すなら `popups.kv` の `size_hint_x` を 0.24 / スピナー 0.4 に詰めて撮り直す（パッチで書き換え）。

- [ ] **Step 5: コミット**

```bash
git add katrain/config.json katrain/popups.kv katrain/i18n/locales/jp/LC_MESSAGES/katrain.po katrain/i18n/locales/jp/LC_MESSAGES/katrain.mo katrain/i18n/locales/en/LC_MESSAGES/katrain.po katrain/i18n/locales/en/LC_MESSAGES/katrain.mo tests/test_board_watch_prefetch.py docs/manual/img/popup_settings.png
git commit -m "$(cat <<'EOF'
feat(board-watch): 設定画面の輪の色の行に「難易度」の色分けチェックを追加

board_watch.highlight_difficulty（パッケージ既定 OFF）。一般設定欄の行は増やさない。spec 追記11。

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
)"
```

（`.mo` のパスは `tools/compile_mo.py` の出力先に合わせる。`git status` で確認してから add する。ローカル config はリポジトリ外なのでコミットしない。）

---

### Task 6: 速度ゲート（先回り ON/OFF の別プロセス ABBA）

**メインセッションで実行する**（KataGo を長く走らせる。ユーザーが対局していないことを先に確かめる）。

**Files:**
- Create: `docs/superpowers/specs/calibration-data/board-watch/ring_difficulty_latency_probe.py`
- Create: `docs/superpowers/specs/calibration-data/board-watch/ring_latency_compare.py`
- Create: `docs/superpowers/specs/calibration-data/board-watch/ring-difficulty-latency-results-20261106.md`（日付は実行日）

**Interfaces:**
- Consumes: `Game.ring_difficulty_active` / `Game._maybe_ring_hp_prefetch`（Task 3）、`move_difficulty.classify_ring_difficulty`（Task 1）、`katrain_debug.katrain_stub.KaTrainStub`
- Produces: ゲートの判定（PASS なら Task 8 へ、FAIL なら Task 7）と、Task 7 が使う `E_kata p77` の値

- [ ] **Step 1: プローブを書く**

`ring_difficulty_latency_probe.py`:

```python
"""輪の難易度（board-watch spec 追記11）の速度ゲート。

相手の手を `Game.play` に入れてから、親局面（AI が打つ局面）の通常解析が終わるまでの秒数を、humanSL の先回り
ON/OFF で比べる。AI の着手生成は解析の完了を待ってから始まる（`__main__._do_update_state` は
`cn.analysis_complete` で `_do_ai_move` を呼ぶ）ので、先回りが着手を遅らせうるのはこの区間の GPU の取り合いだけ。
先回りは解析中に終わる（8visits）ので戦略の区間には残らない（ここで ready 率を数える）。

1 プロセス 1 アーム（同じ局面を同じプロセスで2回測ると NN キャッシュで2回目が速くなる）。ABBA で4回走らせ、
ring_latency_compare.py で局面ごとに対にして比べる。KaTrain で対局していないときに走らせる。

    python ring_difficulty_latency_probe.py --arm off --sgf "experiments/selfplay/20260926_0843_veil9-p1/sgf/*.sgf" --out runs/ring9-off-1.jsonl
"""

import argparse
import glob
import json
import os
import sys
import time

os.environ["KIVY_NO_ARGS"] = "1"
REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", ".."))
sys.path.insert(0, REPO)

from katrain.core.constants import PLAYER_AI, PLAYER_HUMAN  # noqa: E402
from katrain.core.engine import KataGoEngine  # noqa: E402
from katrain.core.game import Game, KaTrainSGF  # noqa: E402
from katrain.core.move_difficulty import classify_ring_difficulty  # noqa: E402
from katrain.core.sgf_parser import Move  # noqa: E402
from katrain_debug.katrain_stub import KaTrainStub  # noqa: E402


def longest_line(root):
    best, stack = [root], [[root]]
    while stack:
        path = stack.pop()
        if not path[-1].children and len(path) > len(best):
            best = path
        stack.extend(path + [child] for child in path[-1].children)
    return best


def positions(paths, every, start, per_file):
    out = []
    for path in paths:
        root = KaTrainSGF.parse_file(path)
        moves = [n.move for n in longest_line(root)[1:] if n.move is not None]
        size = root.board_size[0]
        komi = float(root.get_property("KM", 7.0))
        rules = root.get_property("RU", "chinese")
        picks = [d for d in range(start, len(moves) - 1, every) if not moves[d - 1].is_pass][:per_file]
        for d in picks:
            out.append(
                {
                    "sgf": os.path.basename(path),
                    "depth": d,
                    "size": size,
                    "komi": komi,
                    "rules": rules,
                    "moves": [(m.gtp(), m.player) for m in moves[:d]],
                }
            )
    return out


def wait_until(cond, timeout):
    deadline = time.perf_counter() + timeout
    while not cond():
        if time.perf_counter() > deadline:
            return False
        time.sleep(0.002)
    return True


def measure(stub, engine, pos, arm):
    game = Game(stub, engine, game_properties={"SZ": pos["size"], "KM": pos["komi"], "RU": pos["rules"]})
    stub.game = game
    wait_until(lambda: game.root.analysis_complete, 60.0)
    for gtp, player in pos["moves"][:-1]:
        game.play(Move.from_gtp(gtp, player=player), analyze=False)
    last_gtp, last_player = pos["moves"][-1]
    ai = "W" if last_player == "B" else "B"
    stub.players_info[ai].player_type = PLAYER_AI
    stub.players_info[last_player].player_type = PLAYER_HUMAN
    game.board_watch_active = True
    game.ring_difficulty_active = arm == "on"
    t0 = time.perf_counter()
    node = game.play(Move.from_gtp(last_gtp, player=last_player))  # 通常解析＋（on なら）先回り
    done = wait_until(lambda: node.analysis_complete, 120.0)
    t_analysis = time.perf_counter() - t0
    hp_ready = getattr(node, "ring_human_policy", None) is not None
    row = {
        "sgf": pos["sgf"],
        "depth": pos["depth"],
        "size": pos["size"],
        "arm": arm,
        "t_analysis": t_analysis,
        "complete": done,
        "root_visits": (node.analysis.get("root") or {}).get("visits"),
        "hp_ready": hp_ready,
    }
    if arm == "on":
        wait_until(lambda: getattr(node, "ring_human_policy", None) is not None, 5.0)
        infos = list((node.analysis.get("moves") or {}).values())
        cands = node.candidate_moves if infos else []
        best = cands[0]["move"] if cands else None
        size = (pos["size"], pos["size"])
        kind_hp, info_hp = classify_ring_difficulty(infos, cands, getattr(node, "ring_human_policy", None), best, ai, size)
        kind_kata, info_kata = classify_ring_difficulty(infos, cands, node.analysis.get("policy"), best, ai, size)
        row.update(
            {
                "kind_hp": kind_hp,
                "E_hp": info_hp.get("E"),
                "top_hp": info_hp.get("top_hp"),
                "gap": info_hp.get("gap"),
                "kind_kata": kind_kata,
                "E_kata": info_kata.get("E"),
                "top_kata": info_kata.get("top_hp"),
            }
        )
    return row


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--arm", choices=["on", "off"], required=True)
    ap.add_argument("--sgf", required=True, help="glob（リポジトリ直下からの相対でよい）")
    ap.add_argument("--out", required=True)
    ap.add_argument("--files", type=int, default=6)
    ap.add_argument("--every", type=int, default=8)
    ap.add_argument("--start", type=int, default=9)
    ap.add_argument("--per-file", type=int, default=6)
    ap.add_argument("--warmup", type=int, default=2)
    ap.add_argument("--config", default=os.path.expanduser("~/.katrain/config.json"))
    args = ap.parse_args()
    paths = sorted(glob.glob(os.path.join(REPO, args.sgf)))[: args.files]
    pos = positions(paths, args.every, args.start, args.per_file)
    if not pos:
        raise SystemExit(f"no positions from {args.sgf}")
    warm = [{**pos[i % len(pos)], "depth": 3 + i, "moves": pos[i % len(pos)]["moves"][: 3 + i]} for i in range(args.warmup)]
    stub = KaTrainStub(args.config, debug_level=0, quiet=True)
    engine = KataGoEngine(stub, {**stub.config("engine"), "allow_recovery": False})
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    try:
        with open(args.out, "w", encoding="utf-8") as f:
            for k, p in enumerate(warm + pos):
                row = measure(stub, engine, p, args.arm)
                row["warmup"] = k < len(warm)
                f.write(json.dumps(row) + "\n")
                f.flush()
                print(f"{k + 1}/{len(warm) + len(pos)} {row['sgf']}@{row['depth']} {row['t_analysis']:.3f}s hp_ready={row['hp_ready']}")
    finally:
        engine.shutdown(finish=False)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: 比較スクリプトを書く**

`ring_latency_compare.py`:

```python
"""ring_difficulty_latency_probe.py の ABBA を局面ごとに対にして比べる（board-watch spec 追記11 の採用ゲート）。

    python ring_latency_compare.py runs/ring9-off-1.jsonl runs/ring9-on-1.jsonl runs/ring9-on-2.jsonl runs/ring9-off-2.jsonl

ゲート: 局面ごとの比 ON/OFF の平均の 95% 区間（局面のブートストラップ）の上限 < 1.03 かつ ON の ready 率 >= 0.95。
出力は ASCII のみ（cp932 の端末で落ちない）。
"""

import json
import random
import statistics
import sys

GATE_RATIO = 1.03
GATE_READY = 0.95


def quantile(xs, p):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(p * len(xs)))] if xs else float("nan")


def main(paths):
    rows = [json.loads(line) for p in paths for line in open(p, encoding="utf-8") if line.strip()]
    rows = [r for r in rows if not r.get("warmup") and r.get("complete", True)]
    by = {}
    for r in rows:
        by.setdefault((r["sgf"], r["depth"]), {"on": [], "off": []})[r["arm"]].append(r["t_analysis"])
    ratios = [statistics.mean(v["on"]) / statistics.mean(v["off"]) for v in by.values() if v["on"] and v["off"]]
    rng = random.Random(20261106)
    boots = sorted(statistics.mean(rng.choices(ratios, k=len(ratios))) for _ in range(10000))
    lo, hi = boots[249], boots[9749]
    on = [r for r in rows if r["arm"] == "on"]
    off = [r for r in rows if r["arm"] == "off"]
    ready = sum(r["hp_ready"] for r in on) / len(on)
    print(f"positions={len(ratios)} off_median={statistics.median(r['t_analysis'] for r in off):.3f}s "
          f"on_median={statistics.median(r['t_analysis'] for r in on):.3f}s")
    print(f"ratio on/off mean={statistics.mean(ratios):.4f} median={statistics.median(ratios):.4f} 95%CI=[{lo:.4f},{hi:.4f}]")
    print(f"hp_ready={ready:.3f} ({sum(r['hp_ready'] for r in on)}/{len(on)})")
    for key in ("kind_hp", "kind_kata"):
        counts = {}
        for r in on:
            counts[str(r.get(key))] = counts.get(str(r.get(key)), 0) + 1
        print(f"{key} (chosen=best): " + " ".join(f"{k}={v / len(on):.0%}" for k, v in sorted(counts.items())))
    for key in ("E_hp", "E_kata"):
        xs = [r[key] for r in on if r.get(key) is not None]
        print(f"{key} p50={quantile(xs, 0.5):.2f} p77={quantile(xs, 0.77):.2f} p80={quantile(xs, 0.8):.2f} "
              f">=1.5:{sum(x >= 1.5 for x in xs) / max(1, len(xs)):.0%}")
    gate = hi < GATE_RATIO and ready >= GATE_READY
    print("GATE", "PASS" if gate else "FAIL")
    return 0 if gate else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
```

- [ ] **Step 3: プローブの動作確認（短く）**

Run: `python docs/superpowers/specs/calibration-data/board-watch/ring_difficulty_latency_probe.py --arm on --sgf "experiments/selfplay/20260926_0843_veil9-p1/sgf/*.sgf" --files 1 --per-file 2 --warmup 1 --out C:/Users/iwaki/AppData/Local/Temp/claude/C--Users-iwaki-Documents-katrain-1-17-1-1-katrain-1-17-1-1/b27542d2-bd0e-420b-b906-b7b483c50bf9/scratchpad/ring-smoke.jsonl`
Expected: 3 行出て `hp_ready=True`、jsonl に `kind_hp` と `E_hp` が入る。`hp_ready=False` なら humanSL モデル（config の `humanlike_model`）とクエリのエラーを `stub.logs` で調べる（プローブに `print(stub.logs[-5:])` を一時的に足して見る）

- [ ] **Step 4: ABBA を走らせる（バックグラウンド・約15〜20分）**

`SCRATCH/ring_abba.sh`:

```bash
set -e
cd "C:/Users/iwaki/Documents/katrain-1.17.1.1/katrain-1.17.1.1"
P=docs/superpowers/specs/calibration-data/board-watch/ring_difficulty_latency_probe.py
OUT=docs/superpowers/specs/calibration-data/board-watch/ring-latency-runs
mkdir -p "$OUT"
for spec in "9:experiments/selfplay/20260926_0843_veil9-p1/sgf/*.sgf" "13:experiments/selfplay/20260924_0951_veil13-p1/sgf/*.sgf"; do
  size="${spec%%:*}"; glob="${spec#*:}"
  python "$P" --arm off --sgf "$glob" --out "$OUT/ring$size-off-1.jsonl"
  python "$P" --arm on  --sgf "$glob" --out "$OUT/ring$size-on-1.jsonl"
  python "$P" --arm on  --sgf "$glob" --out "$OUT/ring$size-on-2.jsonl"
  python "$P" --arm off --sgf "$glob" --out "$OUT/ring$size-off-2.jsonl"
done
echo ABBA_DONE
```

Bash ツールの `run_in_background: true` で `bash SCRATCH/ring_abba.sh > SCRATCH/ring_abba.log 2>&1` を起動し、完了通知を待つ（その間は KaTrain で対局しないようユーザーに伝える）。

- [ ] **Step 5: 比べてゲートを判定する**

Run（9路・13路それぞれ）:
`python docs/superpowers/specs/calibration-data/board-watch/ring_latency_compare.py docs/superpowers/specs/calibration-data/board-watch/ring-latency-runs/ring9-off-1.jsonl docs/superpowers/specs/calibration-data/board-watch/ring-latency-runs/ring9-on-1.jsonl docs/superpowers/specs/calibration-data/board-watch/ring-latency-runs/ring9-on-2.jsonl docs/superpowers/specs/calibration-data/board-watch/ring-latency-runs/ring9-off-2.jsonl`
（13路は `ring13-*` に置き換え）
Expected: 両方 `GATE PASS`。出力全体を results の md に貼る。

判定:
- 両方 PASS → Task 7 は飛ばして Task 8 へ。`kind_hp` の分布（obvious / hard の割合）が spec の想定（それぞれ約2割）から大きく外れていたら（どちらかが 10% 未満 or 40% 超）、数字をユーザーに見せて閾値を直すか確認する（直すなら `move_difficulty.py` の定数をパッチし、Task 1 のテストの期待値も合わせる）。
- どちらか FAIL → 数字をユーザーに見せ、Task 7（案B）に進むことを確認する。

- [ ] **Step 6: 結果を記録してコミット**

`ring-difficulty-latency-results-20261106.md` に、実行日時・SGF・局面数・ABBA の順・Step 5 の出力（両サイズ）・判定を書く。

```bash
git add docs/superpowers/specs/calibration-data/board-watch/ring_difficulty_latency_probe.py docs/superpowers/specs/calibration-data/board-watch/ring_latency_compare.py docs/superpowers/specs/calibration-data/board-watch/ring-latency-runs docs/superpowers/specs/calibration-data/board-watch/ring-difficulty-latency-results-20261106.md
git commit -m "$(cat <<'EOF'
docs(board-watch): 輪の難易度の先回りの速度ゲートを測った（別プロセス ABBA）

相手の手から親局面の解析完了までを先回り ON/OFF で局面ごとに対にして比べた。spec 追記11。

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 7（Task 6 が FAIL のときだけ）: 案B へ切り替える（KataGo の policy で代用・先回りなし）

**Files:**
- Modify: `katrain/core/move_difficulty.py`（Task 1 で新規作成＝LF・black 済み → Edit ツール可）
- Modify: `katrain/core/game.py`（パッチ）
- Test: `tests/test_move_difficulty.py`, `tests/test_ring_difficulty_prefetch.py`

**Interfaces:**
- Produces: `RING_HP_PREFETCH = False`、`RING_HARD_MIN_E_KATAGO = <Task 6 の 13路の出力 E_kata p77 の値>`、`ring_difficulty_of` は `ring_human_policy` の代わりに `parent.analysis["policy"]` を使い、難解の閾値に `RING_HARD_MIN_E_KATAGO` を使う

- [ ] **Step 1: テストを先に直す**

`tests/test_ring_difficulty_prefetch.py` の先頭に `pytestmark = pytest.mark.skip(reason="案B: 先回りなし（spec 追記11 の速度ゲート FAIL）")` を足し、`tests/test_move_difficulty.py` に追加:

```python
def test_plan_b_uses_the_katago_policy_without_prefetch():
    from katrain.core import move_difficulty as md

    assert md.RING_HP_PREFETCH is False
    infos, cands = analysis(ROWS)
    parent = SimpleNamespace(
        analysis={"moves": {d["move"]: d for d in infos}, "policy": hp_array(OBVIOUS_HP)},
        candidate_moves=cands,
        next_player="B",
        board_size=(SIZE, SIZE),
    )
    node = SimpleNamespace(move=Move.from_gtp("E5", player="B"), parent=parent)
    assert ring_difficulty_of(node)[0] == RING_OBVIOUS
```

Run: `python -m pytest tests/test_move_difficulty.py -q`
Expected: FAIL（`RING_HP_PREFETCH` が無い）

- [ ] **Step 2: 実装**

`move_difficulty.py`（Edit ツール）:
- 定数の下に `RING_HP_PREFETCH = False  # 速度ゲート FAIL（results 20261106）＝先回りしない。KataGo の policy で代用` と `RING_HARD_MIN_E_KATAGO = <値>  # KataGo policy で重みづけた E の実戦分布の p77（humanPolicy の 1.5 目と同じ上位 23%）` を足す。
- `classify_ring_difficulty` に引数 `hard_min_e=RING_HARD_MIN_E` を足し、`if e >= RING_HARD_MIN_E:` を `if e >= hard_min_e:` にする。
- `ring_difficulty_of` の `getattr(parent, "ring_human_policy", None)` を `policy` に置き換え、その直前に
  `policy = getattr(parent, "ring_human_policy", None) if RING_HP_PREFETCH else analysis.get("policy")` を置き、`classify_ring_difficulty(..., hard_min_e=RING_HARD_MIN_E if RING_HP_PREFETCH else RING_HARD_MIN_E_KATAGO)` で呼ぶ。
- `format_ring_difficulty` の `第一感` を、`RING_HP_PREFETCH` が False のとき `KataGo の直感` にする。

`game.py`（パッチ）: `_maybe_ring_hp_prefetch` の docstring 直後に `if not RING_HP_PREFETCH:\n            return` を入れ、import を `from katrain.core.move_difficulty import RING_HP_PREFETCH, RING_HP_PROFILE, RING_HP_VISITS` にする。

- [ ] **Step 3: テスト**

Run: `python -m pytest tests/test_move_difficulty.py tests/test_ring_difficulty_prefetch.py tests/test_board_watch_prefetch.py -q`
Expected: PASS（prefetch のテストは skip）

- [ ] **Step 4: spec 追記11 に「案B へ切り替えた」と数字を足してコミット**

spec の末尾（追記11 の最後）に `**実測（YYYY-MM-DD）**: 速度ゲート FAIL（9路 比 … / 13路 比 …）→ 案B（KataGo の policy・先回りなし・難解の閾値 E_kata >= <値>）。` をパッチで追記し、

```bash
git add katrain/core/move_difficulty.py katrain/core/game.py tests/test_move_difficulty.py tests/test_ring_difficulty_prefetch.py docs/superpowers/specs/2026-08-18-board-watch-design.md
git commit -m "$(cat <<'EOF'
fix(board-watch): 速度ゲートの結果を受けて輪の難易度を KataGo の policy で判定する（先回りなし）

spec 追記11 の案B。

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 8: ドキュメントと仕上げ

**Files:**
- Modify: `docs/manual/src/08_watch.html`, `docs/manual/src/10_settings.html`（CRLF → パッチ）→ `python tools/build_manual.py` で `docs/manual/index.html` を再生成
- Modify: `CLAUDE.md`（CRLF → パッチ）
- Modify: `docs/superpowers/specs/2026-08-18-board-watch-design.md`（CRLF → パッチ・追記11 の末尾に実測を追記）
- Create: メモリ `C:\Users\iwaki\.claude\projects\C--Users-iwaki-Documents-katrain-1-17-1-1-katrain-1-17-1-1\memory\project_ring_difficulty.md` と `MEMORY.md` の1行

- [ ] **Step 1: マニュアル・CLAUDE.md・spec のパッチ**

`SCRATCH/task8_patch.py`:

```python
patch(
    "docs/manual/src/08_watch.html",
    [
        (
            "輪は最前面のクリック透過ウィンドウなので、アプリの操作を邪魔しません。",
            "同じ行の「難易度」にチェックを入れると、AI が打つ前の局面が人間にとってどれだけ難しかったかで輪の色が変わります"
            "（<b>緑＝明らか</b>：9段の第一感が KataGo の最善手と一致して 8 割以上・次善手が 1 目以上悪い／"
            "<b>赤＝難解</b>：9段がこの局面で打つと平均 1.5 目以上損しそう／それ以外は選んだ色＝普通。"
            "選んだ色が緑なら明らかは水色、赤なら難解はマゼンタになります）。判定の根拠は対局ログに 1 手 1 行で残ります"
            "（「盤面監視: R10 の難易度 明らか（第一感 R10 92%・次善 -2.1目）」）。"
            "判定に使う 9段の第一感は相手の手が入った瞬間に先回りで取るので、輪の表示は遅れません（間に合わなかった手は選んだ色のままです）。\n"
            "輪は最前面のクリック透過ウィンドウなので、アプリの操作を邪魔しません。",
        ),
        (
            "    <tr><td>highlight_color</td><td>cyan</td><td>輪の色（設定画面のドロップダウンと同じ）</td></tr>\n",
            "    <tr><td>highlight_color</td><td>cyan</td><td>輪の色（設定画面のドロップダウンと同じ）</td></tr>\n"
            "    <tr><td>highlight_difficulty</td><td>false</td><td>輪の色を局面の難しさで塗り分ける（明らか＝緑・難解＝赤・普通＝highlight_color。設定画面の「難易度」チェックと同じ）</td></tr>\n",
        ),
    ],
)
patch(
    "docs/manual/src/10_settings.html",
    [("<td>色のみ一般設定に</td>", "<td>色と難易度の色分けのみ一般設定に</td>")],
)
patch(
    "CLAUDE.md",
    [
        (
            "＝`board_watch.highlight_color`・監視の自前キャプチャからは",
            "＝`board_watch.highlight_color`。同じ行の「難易度」チェック〈`board_watch.highlight_difficulty`〉で"
            "輪を局面の難しさで塗り分ける＝明らか緑／難解赤／普通は設定色・相手の着手と同時に humanSL 9段 8visits を先回り＝"
            "輪は待たない・判定は `katrain/core/move_difficulty.py`・spec 追記11。監視の自前キャプチャからは",
        )
    ],
)
```

（`08_watch.html` の「AI 着手の強調表示（監視モード）」の古い表記はこの機会に「（監視）」へ直してよい＝`patch` に `("「AI 着手の強調表示（監視モード）」", "「AI 着手の強調表示（監視）」")` を足す。）

spec 追記11 の末尾へ、Task 6 の結果の要約を `append` で足す（ファイルは CRLF。`append` が合わせる）:

```python
append(
    "docs/superpowers/specs/2026-08-18-board-watch-design.md",
    "\n**実測（2026-11-06・速度ゲート）**: <9路の比の平均と 95% 区間・ready 率>／<13路の同じ数字>＝PASS。"
    "判定の分布（最善手を打った場合・humanPolicy）: 明らか <x>%・難解 <y>%。記録は "
    "`calibration-data/board-watch/ring-difficulty-latency-results-20261106.md`。\n",
)
```

`<...>` は Task 6 Step 5 の出力の数字で埋めてから実行する（埋めずに実行しない）。

Run: `python SCRATCH/task8_patch.py && python tools/build_manual.py`
Expected: エラーなし。`git diff --stat` に `docs/manual/index.html` が出る

- [ ] **Step 2: メモリ**

`project_ring_difficulty.md`（Write）:

```markdown
---
name: project_ring_difficulty
description: 盤面監視の輪を局面の難しさで塗り分ける機能（2026-11-06・spec board-watch 追記11）。判定は move_difficulty.py、humanSL 9段 8visits を相手の着手と同時に先回り。速度ゲートの結果と閾値の見直し手順
metadata:
  type: project
---

盤面監視の輪を 明らか（緑）／普通（設定色）／難解（赤）に塗り分ける（`board_watch.highlight_difficulty`・ローカルは ON）。
判定は親局面（AI が打つ前）の通常解析＋humanSL 9段の humanPolicy（`Game._maybe_ring_hp_prefetch` が相手の着手と同時に撃つ）。
閾値: 難解 = 9段の期待損失 E >= 1.5目、明らか = 最善手 = 9段の第一感で hp >= 0.8 かつ次善が 1目以上悪い。

**Why:** ユーザーは「どの手が人間にとって難しい局面だったか」を対局中に確認したい（学習用）。**着手表示が遅くなるなら中止**が条件だった。

**How to apply:** 閾値を見直すときは対局ログの `盤面監視: … の難易度` 行を集計する。速度を疑われたら
`calibration-data/board-watch/ring_difficulty_latency_probe.py` の ABBA を回す（結果 `ring-difficulty-latency-results-20261106.md`）。
関連: [[project_enigma_e_calibration]]
```

`MEMORY.md` の末尾に1行: `- [project_ring_difficulty.md](project_ring_difficulty.md) — 盤面監視の輪の難易度の色分け（明らか緑／難解赤）。判定 move_difficulty.py・humanSL 先回り・速度ゲートの手順`

- [ ] **Step 3: 全体のテスト**

Run: `python -m pytest tests -q -p no:cacheprovider`
Expected: 新規・変更したテストは全部 PASS。既知の失敗（`tests/test_ai.py` の strategies / rank_estimation の2件、`tests/test_collapsable_panel.py` の順序依存フレーク）以外に失敗が無い。既知のもの以外が落ちたら `git stash` で master と比べて切り分ける。

- [ ] **Step 4: コミット**

```bash
git add docs/manual/src/08_watch.html docs/manual/src/10_settings.html docs/manual/index.html CLAUDE.md docs/superpowers/specs/2026-08-18-board-watch-design.md
git commit -m "$(cat <<'EOF'
docs(board-watch): 輪の難易度の色分けをマニュアル・CLAUDE.md・spec に記録する

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
)"
```

- [ ] **Step 5: ユーザーへの確認**

実際の監視対局で、輪の色が手ごとに変わること・表示が遅れないこと・対局ログ（`~/.katrain/logs/game_*.log`）に `難易度` 行が出ることを確かめてもらう（Grep: `難易度 (明らか|普通|難解|判定なし)`）。`判定なし（humanPolicy が間に合わず）` が多ければ報告してもらう。
