# -*- coding: utf-8 -*-
"""余裕外し（relax）の資格判定と選択の純関数（2026-11-16 に実装 → 同日見送り）。

katrain/core/ai.py に入れていた `enigma9_relax_pick` と定数の写し。実装は本体から外したので、
反実仮想のスクリプト（relax_cf.py・relax_branch_cf.py）はこのモジュールを使う。
本体へ戻すときの差分は relax-implementation-20261116.patch。
"""

ENIGMA9_RELAX_MIN_WR = 0.97        # 外した後の検証済み勝率の床（VEIL_DECIDED_WR と同値）
ENIGMA9_RELAX_SLACK = 0.3          # 最安帯の幅（目）。帯の中は humanPolicy 最大
ENIGMA9_RELAX_HP_RATIO = 0.25      # 最善手の humanPolicy に対する比の床（明らかな一手を珍しい手に替えない）


def enigma9_relax_pick(scored, best_gtp, best_lead_after, min_lead, max_loss, min_hp, max_e_drop,
                       min_wr=ENIGMA9_RELAX_MIN_WR, slack=ENIGMA9_RELAX_SLACK, hp_ratio=ENIGMA9_RELAX_HP_RATIO):
    """余裕外し: 大差の勝勢で最善手の代わりに打つ「9段らしく・ほぼ損のない手」を返す。返り値 (pick or None, 資格のある手)。

    scored は子局面プローブで検証済みのエントリ（ΔE 床を通す前・最善手込み）。資格は全部 AND:
      - 検証済み損失 max(0, loss) <= max_loss（気にならない損）
      - own_hp >= max(min_hp, hp_ratio × 最善手の own_hp)（人間らしさ。明らかな一手を珍しい手に替えない）
      - 着手後の検証済み勝率 >= min_wr、着手後のリード best_lead_after − loss >= min_lead（勝敗に響かない。
        min_lead は呼び出し側が target + large_lead_max_loss 以上にする＝次の手番の罠探索の上限を縮めない）
      - E >= 最善手の E − max_e_drop（最善手そのものが罠になっている手番は罠を残す）
    選ぶのは最安の資格手から slack 目以内の帯の中で own_hp 最大（同点は損の小さい方）。
    min_lead <= 0（OFF）・最善手のエントリ無し・着手後リード不明は (None, [])＝最善手のまま。

    実測（2026-11-16・calibration-data/enigma-relax/）: 実戦ログ 13路 14 局の反実仮想で、リード 12 目以上で
    最善手を打った 153 手番のうち 74 手番は cap 内に代替なし（盤面監視の難易度も「明らか」）、残り 79 手番の
    うち資格あり（1.0 目・hp 10%・E 低下 0.5 まで）は 15 手番＝1.07 回/局・払う損 0.32 目/局・E の変化 −0.02 目/局。
    **外した直後の数手番は罠が減る**（同じ局面の 2 分岐 36 対: 罠の回数は 2 手番先まで −0.39±0.17、4 手番先まで
    −0.28±0.22・ΣE −0.34±0.64。実際に発動した 14 局面だけだと 4 手番先まで ΣE −1.63±1.08＝その後に取り戻すかは
    未確定、原因も未確定）＝一致の減りは 1 発動あたり約 0.7 手ぶん。既定 OFF のままにしてある理由。
    """
    if min_lead is None or min_lead <= 0 or best_lead_after is None:
        return None, []
    best = next((c for c in scored if c["gtp"] == best_gtp), None)
    if best is None:
        return None, []
    eps = 1e-9
    hp_floor = max(min_hp, hp_ratio * (best.get("own_hp") or 0.0))
    quals = []
    for c in scored:
        if c["gtp"] == best_gtp or c["gtp"] == "pass":
            continue
        cost = max(0.0, c["loss"])
        if cost > max_loss + eps:
            continue
        if (c.get("own_hp") or 0.0) < hp_floor - eps:
            continue
        if c.get("wr_after") is None or c["wr_after"] < min_wr:
            continue
        if best_lead_after - c["loss"] < min_lead:
            continue
        if c["e"] < best["e"] - max_e_drop - eps:
            continue
        quals.append(c)
    if not quals:
        return None, []
    cheapest = min(max(0.0, c["loss"]) for c in quals)
    band = [c for c in quals if max(0.0, c["loss"]) <= cheapest + slack + eps]
    pick = max(band, key=lambda c: (c.get("own_hp") or 0.0, -c["loss"]))
    return pick, quals
