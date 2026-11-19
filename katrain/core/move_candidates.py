"""盤面監視の複数候補表示（board-watch spec 追記15・Kivy 非依存）。

AI の決定手の輪に加えて、同じ局面（着手ノードの親）の参考の手を輪＋字で示すための判定:
- 最（最善手）  = 親局面の KataGo 通常解析の先頭（`candidate_moves[0]`）
- 感（第一感）  = humanSL 9段の humanPolicy が最大の盤上の手（悪手でもそのまま。パスが最大なら無し）
- 人（人間らしい手）= 悪手でない手の中で humanPolicy が最大の手。第一感が悪手と言えなければ（損失 <= max_loss）
  第一感そのもの＝**字は第一感と違うときだけ出す**。第一感が悪手（損失 > max_loss）か KataGo が読んでいない手
  なら、最善手か visits >= CANDIDATE_MIN_VISITS で損失 <= max_loss の手の中の humanPolicy 最大
- 全           = 最善手と第一感が同じ点（＝3つとも同じ）
- 罠           = 決定手が罠（戦略が着手ノードに残す `ai_decision["trap"]`。難解 / 難解＋が記録する）

材料は move_difficulty と同じ2つ（親局面の通常解析・`Game._maybe_ring_hp_prefetch` が先回りで取る humanPolicy）
＝追加クエリは無い。humanPolicy がまだ届いていなければ「最」だけ返して記憶しない（届いた周から全部出る）。
届いていれば着手ノードに1回だけ記憶する（`ring_roles_of`）。**罠かどうかは記憶しない**＝着手ノードは
`game.play` の中で現局面になり、戦略の記録が付くのはその後（`generate_ai_move`）なので、すき間で監視スレッドが
先に計算すると「罠でない」が固定されてしまう。毎回ノードから読む。

損失は通常解析の `relativePointsLost`（打つ側視点に符号済み）。浅い候補の損失は打つ側に楽観的なので
visits の下限を掛ける（CLAUDE.md「wideRootNoise=0 の moveInfos を損失の判定に使わない」と同じ理由）。
"""

import threading

MARK_TRAP = "罠"
MARK_BEST = "最"
MARK_INSTINCT = "感"
MARK_HUMAN = "人"
MARK_ALL = "全"

CANDIDATE_MAX_LOSS = 2.0  # 「悪手でない」の上限（目）。設定 board_watch.candidates_max_loss で変えられる
CANDIDATE_MIN_VISITS = 10  # 損失を信用する visits（= move_difficulty.RING_GAP_MIN_VISITS）
TRAP_MIN_DELTA_E = 0.5  # 通常の外しを罠とみなす E の上積み（目）＝難解の賭け罠・劣勢演出の罠の資格と同じ値

_LOCK = threading.Lock()


def candidate_roles(candidate_moves, human_policy, board_size, max_loss=CANDIDATE_MAX_LOSS):
    """親局面の {"best", "instinct", "human"}（gtp か None）を返す（純関数）。

    candidate_moves: `GameNode.candidate_moves`（先頭が最善手・relativePointsLost は打つ側視点）。
    human_policy が無い・盤と形が合わないときは instinct / human が None。
    """
    from katrain.core.ai import enigma9_hp_lookup, enigma9_human_top

    roles = {"best": None, "instinct": None, "human": None}
    cands = [c for c in (candidate_moves or []) if c.get("move")]
    if cands and cands[0]["move"] != "pass":
        roles["best"] = cands[0]["move"]
    top = enigma9_human_top(human_policy, board_size) if human_policy is not None else None
    if top is None:
        return roles
    top_gtp, top_hp, pass_hp = top
    if top_gtp is not None and top_hp > pass_hp:
        roles["instinct"] = top_gtp
    hp_of = enigma9_hp_lookup(human_policy, board_size)
    by_gtp = {c["move"]: c for c in cands}
    instinct = roles["instinct"]
    if instinct is not None and instinct in by_gtp and by_gtp[instinct].get("relativePointsLost", 0.0) <= max_loss:
        # 第一感が悪手と言えない＝人間らしい手は第一感そのもの。visits の下限はここでは掛けない: 通常解析は
        # visits を数手に集中させる（13路で 98 候補中 trusted 7 手）ので、掛けると「第一感が浅くしか読まれて
        # いないだけ」の手番で人が別の点へ飛び、「第一感は悪手」と読めてしまう。浅い候補の損失は打つ側に
        # 楽観的なので「損失 > 上限」は visits によらず悪手と言えるが、「損失 <= 上限」は悪手の証明にならない
        roles["human"] = instinct
        return roles
    # 第一感が悪手（損失が上限超）か、KataGo が1回も読んでいない（HumanStyle の悪手フィルタと同じく除外）。
    # 代わりの手は損失を信用できる候補（最善手か visits >= CANDIDATE_MIN_VISITS）から選ぶ
    best_hp = -1.0
    for index, cand in enumerate(cands):
        gtp = cand["move"]
        if gtp == "pass":
            continue
        sound = index == 0 or (
            cand.get("visits", 0) >= CANDIDATE_MIN_VISITS and cand.get("relativePointsLost", 0.0) <= max_loss
        )
        if sound and hp_of(gtp) > best_hp:  # 同値は先（＝KataGo の順位が上）を残す
            roles["human"], best_hp = gtp, hp_of(gtp)
    return roles


def candidate_marks(roles, chosen_gtp, trap=False):
    """輪の一覧 [(gtp, 字, 決定手か)] を返す（純関数）。先頭が決定手、同じ点の役割は1つの輪にまとめる。

    決定手がパス・無しなら空（輪そのものを出さない局面）。字は 罠 → 最／全 → 人 → 感 の順。
    """
    if not chosen_gtp or chosen_gtp == "pass":
        return []
    best, instinct, human = roles.get("best"), roles.get("instinct"), roles.get("human")
    texts = {chosen_gtp: MARK_TRAP if trap else ""}
    order = [chosen_gtp]

    def add(gtp, mark):
        if gtp is None:
            return
        if gtp not in texts:
            texts[gtp] = ""
            order.append(gtp)
        texts[gtp] += mark

    if best is not None and best == instinct:
        add(best, MARK_ALL)  # 最善手＝第一感なら人間らしい手も同じ点（最善手は必ず「悪手でない」に入る）
    else:
        add(best, MARK_BEST)
        if human is not None and human != instinct:
            add(human, MARK_HUMAN)
        add(instinct, MARK_INSTINCT)
    return [(gtp, texts[gtp], gtp == chosen_gtp) for gtp in order]


def decision_is_trap(info):
    """戦略が着手ノードに残した記録（`ai_decision`）から、決定手を罠と表示するかを返す（純関数）。

    難解 / 難解＋は "trap" を直接入れる（賭け罠・捨て身の罠・劣勢演出の罠、または通常の外しで E の上積みが
    TRAP_MIN_DELTA_E 以上）。一致率ひかえめは kind "trap"（罠の上乗せ層）。記録が無い戦略は罠としない。
    """
    if not isinstance(info, dict):
        return False
    return bool(info.get("trap")) or info.get("kind") == "trap"


def ring_roles_of(node, max_loss=CANDIDATE_MAX_LOSS, log=None):
    """着手ノードの役割 dict を返す。humanPolicy が揃っていれば最初の1回だけ計算して `node.ring_roles` に記憶する。

    親局面の解析が無ければ全部 None。log を渡すと、記憶したその1回だけ1行流す（対局ログに残る）。
    """
    with _LOCK:
        cached = getattr(node, "ring_roles", None)
        if cached is not None:
            return cached
        parent = getattr(node, "parent", None)
        analysis = (getattr(parent, "analysis", None) or {}) if parent is not None else {}
        if not analysis.get("moves"):
            return {"best": None, "instinct": None, "human": None}
        human_policy = getattr(parent, "ring_human_policy", None)
        try:
            roles = candidate_roles(parent.candidate_moves, human_policy, parent.board_size, max_loss)
        except Exception as e:  # 判定の不具合で輪そのもの（既存の機能）を止めない
            if log is not None:
                log(f"盤面監視: 候補の判定中にエラー: {e!r}")
            roles = {"best": None, "instinct": None, "human": None}
            human_policy = True  # 同じエラーを毎周繰り返さない＝この結果を記憶する
        if human_policy is None:
            return roles  # 第一感はまだ届いていない＝最善手だけ。記憶しない
        node.ring_roles = roles
    if log is not None:
        move = getattr(node, "move", None)
        log(format_ring_roles(move.gtp() if move is not None else None, roles))
    return roles


def current_move_marks(game, move, max_loss=CANDIDATE_MAX_LOSS, log=None):
    """輪が指す交点 move=(i, j) が今の局面の最後の着手なら、候補の輪 [((i, j), 字, 決定手か)] を返す。

    違う（局面が動いた）・パスなら None＝呼び出し側は決定手の輪だけを出す。決定手以外の点は
    `node.watch_swap_auto`（gtp の集合）にも書く＝監視が「アプリで別の候補が打たれた」を見分ける材料。
    """
    from katrain.core.board_watch import move_to_grid
    from katrain.core.sgf_parser import Move

    if game is None or move is None:
        return None
    node = getattr(game, "current_node", None)
    last = getattr(node, "move", None)
    if last is None or last.coords is None or getattr(node, "parent", None) is None:
        return None
    size = game.board_size[0]
    if move_to_grid(last.coords, size) != tuple(move):
        return None
    roles = ring_roles_of(node, max_loss=max_loss, log=log)
    marks = candidate_marks(roles, last.gtp(), decision_is_trap(getattr(node, "ai_decision", None)))
    node.watch_swap_auto = frozenset(gtp for gtp, _text, decision in marks if not decision)
    return [(move_to_grid(Move.from_gtp(gtp).coords, size), text, decision) for gtp, text, decision in marks]


def swap_targets(node):
    """アプリで打たれたら差し替えを受け付ける手（gtp の集合）＝表示した候補＋差し替えで引き継いだ手。自手は除く"""
    move = getattr(node, "move", None)
    own = move.gtp() if move is not None else None
    targets = set(getattr(node, "watch_swap_auto", None) or ()) | set(getattr(node, "watch_swap_carry", None) or ())
    targets.discard(own)
    targets.discard("pass")
    return targets


def format_ring_roles(gtp, roles):
    """対局ログの1行（例: `盤面監視: G9 の候補 最善 F6・第一感 D4・人間らしい手 D4`）"""
    parts = [
        f"{label} {roles.get(key) or 'なし'}"
        for key, label in (("best", "最善"), ("instinct", "第一感"), ("human", "人間らしい手"))
    ]
    return f"盤面監視: {gtp} の候補 " + "・".join(parts)
