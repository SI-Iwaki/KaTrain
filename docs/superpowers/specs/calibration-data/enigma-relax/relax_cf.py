# -*- coding: utf-8 -*-
"""余裕外しのログ反実仮想（2026-11-16）: 実戦ログ（難解＋13路）の「最善手に倒れた手番」に実関数 enigma9_relax_pick を当てる。

    python log_turns.py turns.json          # ~/.katrain/logs の対局ログ → 手番ごとの記録
    python relax_cf.py turns.json           # 設定の格子ごとの発動回数・損・E の変化、既定値での局ごとの一致率

リポジトリのルートから PYTHONPATH=. で実行（KataGo 不要）。一致率は「罠・終局パス以外の手番の割合」の代理値
（序盤の 9 段委譲を全部一致と数えるので実際より高い）。標準出力は ASCII のみ。
"""
import json, os, sys
os.environ["KIVY_NO_ARGS"] = "1"
from relax_pick import enigma9_relax_pick

G = [g for g in json.load(open(sys.argv[1], encoding="utf-8")) if g["board"] == 13]
TARGET, LARGE = 2.0, 10.0
NONDEV = ("deviate", "gamble", "overdraft", "terminal_pass")

def run(min_lead, max_loss, min_hp, e_drop, ratio):
    floor = max(min_lead, TARGET + LARGE)
    rows = []
    for g in G:
        T = g["turns"]; n = len(T)
        nd = sum(1 for t in T if t["branch"] not in NONDEV)
        sw = []
        for t in T:
            if t["branch"] != "best_race" or not t["scores"] or t["lead"] is None or t["lead"] < floor:
                continue
            scored = [dict(gtp=s["gtp"], loss=s["vloss"], own_hp=s["own_hp"], wr_after=s["wr"], e=s["e"]) for s in t["scores"]]
            pick, _ = enigma9_relax_pick(scored, scored[0]["gtp"], t["lead"], floor, max_loss, min_hp, e_drop, hp_ratio=ratio)
            if pick:
                sw.append((t, scored[0], pick))
        rows.append((g["log"], n, nd, sw))
    return rows

def summ(rows):
    n = sum(len(sw) for *_, sw in rows)
    loss = sum(max(0, p["loss"]) for *_, sw in rows for _, _, p in sw)
    dE = sum(p["e"] - b["e"] for *_, sw in rows for _, b, p in sw)
    hp = sum(p["own_hp"] for *_, sw in rows for _, _, p in sw) / max(1, n)
    return n, loss, dE, hp

print("games", len(G))
for ratio in (0.25,):
    for e_drop in (0.0, 0.5, 1.0, 99):
        for max_loss in (0.5, 1.0, 1.5):
            for min_hp in (0.05, 0.10, 0.20):
                n, loss, dE, hp = summ(run(12, max_loss, min_hp, e_drop, ratio))
                print(f"ratio {ratio:.2f} e_drop {e_drop:<4} max_loss {max_loss} min_hp {min_hp:.2f}: swaps {n:2d} ({n/len(G):.2f}/g) loss {loss/len(G):.2f}/g dE {dE/len(G):+.2f}/g hp~{hp:.2f}")
print()
rows = run(12, 1.0, 0.10, 0.5, 0.25)
for log, n, nd, sw in rows:
    big = "".join(f" [{b['gtp']}({b['own_hp']:.2f})->{p['gtp']}({p['own_hp']:.2f}) -{max(0,p['loss']):.2f}]" for _, b, p in sw)
    print(f"{log[5:20]} turns {n:2d} match~{100*nd/n:.0f}% -> {100*(nd-len(sw))/n:.0f}%{big}")
