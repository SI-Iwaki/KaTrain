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
    info = {
        "E": e,
        "coverage": coverage,
        "top": top_gtp,
        "top_hp": top_hp,
        "best": best,
        "gap": gap,
        "chosen": chosen_gtp,
    }
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
