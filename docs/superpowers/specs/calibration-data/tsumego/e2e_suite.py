"""詰碁 E2E 回帰スイート: 全ケースの `generate_move_e2e.py` を順に回して PASS/FAIL 表を出す。

選択則・枠判定・解析まわりを触ったら必ずこれを回す。ケースごとに**別プロセスで KataGo を
起動する**ので、CLAUDE.md の「run 間分散を同一プロセスの再クエリで測らない」を自動的に守る。

usage:
  python docs/superpowers/specs/calibration-data/tsumego/e2e_suite.py [case...] [--repeats N] [--full] [--all]
  例: ... e2e_suite.py                # 既定（回帰点だけ・既知限界を除く）
      ... e2e_suite.py V V2 W         # ケースを絞る
      ... e2e_suite.py --full         # 正解手順の**全黒番**を回す（初手から正解まで）
      ... e2e_suite.py --all          # 既知限界（I/Q）も含める

## `line`（正解手順）と `expect`（回帰点）の違い

`line` は**正解手順**（SGF root から交互に打つ GTP 列）。SGF の本譜（`children[0]` 連鎖）は
「実際に打たれた手順」＝誤答を含む線であることが多く、正解が分岐側にしか無いケースがある
（実測: D/F/L/O/T/U は分岐が正解）。局面はこの `line` から組む（`--line`）ので、
本譜の誤答を経由せずに「初手から正解まで」を1手ずつ再現できる。

`expect` は**そのケースが回帰対象として実測で確定している手**（README / spec の追記に記録が
ある手番だけ）。既定モードはここだけを PASS/FAIL する。`--full` を付けると `line` の全黒番を
回し、`expect` に無い手番の不一致は **DIFF**（＝「記録された手順と違う」であって即バグでは
ない。アプリの解答樹に別解があるかを GUI で確かめる）として報告する。
"""
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
E2E = os.path.join(HERE, "generate_move_e2e.py")

# case -> dict(sgf, region, line=正解手順, expect={手数: 期待手...}, note)
CASES = {
    "D": dict(
        sgf="case-d-gain-region-20260730.sgf",
        region="0,8,0,8",
        line=["C2", "B2", "D1", "B1", "A4", "C1", "B3"],  # 本譜4手 + 分岐(alt@4)
        expect={4: ("A4", "B3")},
        note="B3 は README 記載の別解（2026-08-01 の全手順スイープでは 4手目に B3 2/2）",
    ),
    "E": dict(
        sgf="case-e-ko-margin-20260730.sgf",
        region="3,12,0,8",
        line=["M2", "N3", "N1", "N3", "J1", "N5", "K1"],  # 本譜6手 + 分岐(alt@6)
        expect={6: ("K1",)},
        note="",
    ),
    "F": dict(
        sgf="case-f-gain-visit-share-20260730.sgf",
        region="4,12,3,12",
        line=["L12", "K10", "N8"],  # 本譜2手 + 分岐(alt@2)。壊れた枠の盤なので ply4 以降は伸ばさない
        expect={2: ("N8",)},
        note="壊れた枠の盤（脱出の退化再現用・どの手でも解けない）",
    ),
    "F2": dict(
        sgf="case-f2-rescue-shadow-20260730.sgf",
        region="5,12,6,12",
        line=["L12", "K10", "N8", "N7", "N11"],
        expect={4: ("N11", "M12")},
        note="N11/M12 はコイン投げ",
    ),
    "G2": dict(
        sgf="case-g2-frameless-guard-20260730.sgf",
        region="0,7,3,12",
        line=["A11", "A10", "C13", "E13", "A13"],
        expect={2: ("C13", "A10")},
        note="A10 は別解の疑い（GUI 要観察）",
    ),
    "H": dict(
        sgf="case-h-gate-cliff-20260730.sgf",
        region="5,12,0,6",
        line=["N2", "N1", "L2", "L1", "N4"],
        expect={4: ("N4",)},
        note="",
    ),
    "J": dict(
        sgf="case-j-points-tie-20260730.sgf",
        region="6,12,1,12",
        line=["M11", "L11", "M10", "L9", "M12", "N8", "M13", "N9", "N6", "M6", "N10"],
        expect={10: ("N10",)},
        note="",
    ),
    "K": dict(
        sgf="case-k-ko-route-20260730.sgf",
        region="0,8,3,12",
        line=["C13"],  # 正解の継続は未記録
        expect={0: ("C13",)},
        note="A10 が稀に出る別解あり",
    ),
    "L": dict(
        sgf="case-l-immediate-ko-20260730.sgf",
        region="4,12,0,9",
        line=["J6", "H6", "J6"],  # 分岐(alt@0)
        expect={0: ("J6",)},
        note="",
    ),
    "M": dict(
        sgf="case-m-capture-gain-ko-20260730.sgf",
        region="4,12,0,8",
        line=["K2", "L4", "L3", "M3", "K1"],  # 本譜4手 + 正解 K1
        expect={4: ("K1",)},
        note="",
    ),
    "O": dict(
        sgf="case-o-all-ko-band-20260731.sgf",
        region="0,8,3,12",
        line=["A11", "C10", "C13", "B13", "B12", "A10", "A8", "A13", "B12"],  # 分岐(alt@0)
        expect={0: ("A11",)},
        note="",
    ),
    "P": dict(
        sgf="case-p-visits-tie-ko-20260731.sgf",
        region="2,12,0,6",
        line=["K1", "J2", "J1", "H1", "L2", "L1", "M1"],
        expect={2: ("J1",)},
        note="",
    ),
    "R": dict(
        sgf="case-r-declass-nonsolution-20260731.sgf",
        region="0,12,7,12",
        line=["G13", "J12", "J13"],
        expect={0: ("G13",)},
        note="root 解析の分散で稀に J13/C8。3手目 J13 も救済経路で D8 1/4（spec 追記33 の残余）",
    ),
    "T": dict(
        sgf="case-t-defender-seki-20260731.sgf",
        region="2,12,0,6",
        line=["M1", "J1", "L1", "J2", "H2"],  # 本譜2手 + 分岐(alt@2)
        expect={0: ("M1",), 2: ("L1",)},
        note="",
    ),
    "U": dict(
        sgf="case-u-move-order-ko-20260731.sgf",
        region="0,8,0,8",
        line=["C1", "B1", "A3", "A4", "A2", "E1", "D1"],  # 分岐(alt@0)
        expect={0: ("C1",)},
        note="",
    ),
    "V": dict(
        sgf="case-v-declass-no-kill-20260731.sgf",
        region="4,12,4,12",
        line=["L12", "N10", "N13", "N11"],  # 分岐(alt@0) の2手 + case V2 本譜
        expect={0: ("L12",)},
        note="",
    ),
    "V2": dict(
        sgf="case-v2-guard-outside-ko-20260731.sgf",
        region="4,12,4,12",
        line=["L12", "N10", "N13", "N11"],
        expect={2: ("N13",)},
        note="",
    ),
    "W": dict(
        sgf="case-w-frameless-declass-20260801.sgf",
        region="6,12,0,6",
        line=["H1", "G1", "K1"],
        expect={0: ("H1",), 2: ("K1",)},
        note="初手の残り 1/3 は救済が N4 を拾う分散（spec 追記33/35）",
    ),
    "X": dict(
        sgf="case-x-attacker-role-edge-20260801.sgf",
        region="0,6,0,10",
        line=["A4", "A3", "A8", "A7", "A5", "C2", "C1"],
        expect={0: ("A4",)},
        note="役割指定（black_to_attack_p=True）で張り直した枠。実キャプチャは極値票 -68 の役割反転"
        "で壁が白になり C2 で誤答（-inverted.sgf、spec 追記37）",
    ),
}
# 既知限界（エンジン側の value/探索の問題で選択則では救えない。spec 追記13/21）
KNOWN_LIMITS = {
    "I": dict(
        sgf="case-i-defender-ko-20260730.sgf",
        region="6,12,0,8",
        line=["N2", "N3", "J1", "N7", "K1"],
        expect={0: ("N2",)},
        note="KataGo の探索崩壊（未対処）",
    ),
    "Q": dict(
        sgf="case-q-ko-is-answer-20260731.sgf",
        region="4,12,4,12",
        line=["N9", "M13", "N11"],
        expect={0: ("N9",)},
        note="準備手が正解（未対処）",
    ),
}

TALLY = re.compile(r"^after\s+(\d+) moves: \{(.*?)\}")


def run_case(case, plies, repeats):
    proc = subprocess.run(
        [
            sys.executable,
            E2E,
            os.path.join(HERE, case["sgf"]),
            ",".join(str(m) for m in plies),
            case["region"],
            str(repeats),
            "--line=" + ",".join(case["line"]),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    got = {}
    for raw in (proc.stdout or "").splitlines():
        m = TALLY.match(raw.strip())
        if m:
            got[int(m.group(1))] = dict(
                (k.strip().strip("'"), int(v))
                for k, v in (part.split(":") for part in m.group(2).split(",") if ":" in part)
            )
    if not got:
        return None, (proc.stdout or "")[-1200:] + (proc.stderr or "")[-1200:]
    return got, None


def main():
    argv = list(sys.argv[1:])
    if "--solver" in argv:
        # 死活ソルバモード（スペック §10.2 G6）: 同じケース表を KataGo 不要のソルバで回す。
        # 実装は solver_p1_suite.py（同じ CASES/KNOWN_LIMITS を import している）。
        # ソルバは決定的なので --repeats は落とす
        import runpy

        if "--repeats" in argv:
            i = argv.index("--repeats")
            del argv[i : i + 2]
        sys.argv = (
            [os.path.join(HERE, "solver_p1_suite.py")]
            + [a for a in argv if a not in ("--solver", "--all")]
            + ["--native"]
        )
        runpy.run_path(sys.argv[0], run_name="__main__")
        return
    repeats = 3
    if "--repeats" in argv:
        i = argv.index("--repeats")
        repeats = int(argv[i + 1])
        del argv[i : i + 2]
    full = "--full" in argv
    table = dict(CASES)
    if "--all" in argv:
        table.update(KNOWN_LIMITS)
    names = [a for a in argv if not a.startswith("--")] or list(table)
    rows, failures = [], []
    for name in names:
        case = table.get(name) or KNOWN_LIMITS.get(name)
        if case is None:
            print(f"unknown case: {name}")
            continue
        plies = (
            sorted(range(0, len(case["line"]), 2)) if full else sorted(case["expect"])
        )
        print(f"--- {name} ({case['sgf']}) plies={plies} x{repeats}", flush=True)
        got, err = run_case(case, plies, repeats)
        if got is None:
            rows.append((name, "ERROR", err.splitlines()[-1] if err else ""))
            failures.append(name)
            print(f"    ERROR\n{err}", flush=True)
            continue
        for move_n in plies:
            counts = got.get(move_n, {})
            wanted = case["expect"].get(move_n) or (case["line"][move_n],)
            documented = move_n in case["expect"]
            ok = sum(v for k, v in counts.items() if k in wanted)
            total = sum(counts.values()) or 1
            if ok == total:
                verdict = "PASS"
            elif documented:
                verdict = "PART" if ok else "FAIL"
            else:
                verdict = "DIFF"  # 記録された手順と違う＝別解かもしれない（GUI で要確認）
            if verdict in ("FAIL", "PART"):
                failures.append(f"{name}@{move_n}")
            rows.append(
                (
                    f"{name}@{move_n}",
                    verdict,
                    f"{ok}/{total} expected={'/'.join(wanted)}{'' if documented else '(手順)'} "
                    f"got={counts} {case['note']}".strip(),
                )
            )
            print(f"    move {move_n}: {verdict}  {ok}/{total} expected={'/'.join(wanted)} got={counts}", flush=True)
    print("\n=== E2E suite summary ===")
    for name, verdict, detail in rows:
        print(f"{verdict:<5} {name:<8} {detail}")
    diffs = [r[0] for r in rows if r[1] == "DIFF"]
    print(
        f"\n{sum(1 for r in rows if r[1] == 'PASS')}/{len(rows)} PASS"
        + (f"  回帰失敗: {failures}" if failures else "  回帰失敗なし")
        + (f"  手順差分(要 GUI 確認): {diffs}" if diffs else "")
    )


if __name__ == "__main__":  # import して CASES だけ読む用途（検算スクリプト）で実行しない
    main()
