"""A/B 後段: 交差評価（両腕の選択手を審判エンジン固定で測り直す）＋ B の E2E 破損 2 件の --debug 診断。

ログ: ab/cross.log。出力: ab/out/cross_*.txt|json, ab/out/diag_*.txt
"""

import os
import re
import subprocess
import sys
import time

REPO = r"c:/Users/iwaki/Documents/katrain-1.17.1.1/katrain-1.17.1.1"
HOME = r"C:/Users/iwaki/.katrain"
AB = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(AB, "out")
LOG = os.path.join(AB, "cross.log")
TSU = REPO + "/docs/superpowers/specs/calibration-data/tsumego"
CFG = {
    "A": HOME + "/config.json",
    "B": HOME + "/config_ab_v1181_b10c384.json",
    "B2": HOME + "/config_ab_v1181_b18.json",
}
SGF = {
    "g0823": REPO + "/docs/superpowers/specs/calibration-data/enigma9/enigma13-vs-human-20260823-white.sgf",
    "g0901": REPO + "/docs/superpowers/specs/calibration-data/enigma13/enigma13-vs-human-20260901-white.sgf",
}
log_f = open(LOG, "a", encoding="utf-8", buffering=1)


def log(msg):
    log_f.write(f"{time.strftime('%H:%M:%S')} {msg}\n")
    log_f.flush()


def run(step, cmd, timeout, keep=None):
    log(f"STEP {step} start")
    t0 = time.time()
    try:
        p = subprocess.run(
            cmd, cwd=REPO, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout
        )
        with open(os.path.join(OUT, f"{step}.txt"), "w", encoding="utf-8") as f:
            f.write((p.stdout or "") + "\n--- stderr ---\n" + (p.stderr or ""))
        if keep:
            for ln in (p.stdout or "").splitlines():
                if re.search(keep, ln):
                    log(f"  {step}: {ln.strip()[:200]}")
        log(f"STEP {step} done rc={p.returncode} in {time.time() - t0:.0f}s")
    except subprocess.TimeoutExpired:
        log(f"STEP {step} FAIL timeout")
    except Exception as e:
        log(f"STEP {step} FAIL {e!r}")


# 交差評価: X=A vs Y=B（r1 同士）を審判 A / 審判 B で。エンジンだけ替えた B2 は審判 A で A と比較
for g in SGF:
    for judge in ("A", "B"):
        run(
            f"cross_{g}_AvsB_judge{judge}",
            [
                sys.executable,
                os.path.join(AB, "ab_cross_eval.py"),
                SGF[g],
                os.path.join(OUT, f"enigma_A_{g}_r1.json"),
                os.path.join(OUT, f"enigma_B_{g}_r1.json"),
                "--config",
                CFG[judge],
                "--out",
                os.path.join(OUT, f"cross_{g}_AvsB_judge{judge}.json"),
            ],
            1200,
            keep=r"^moves=|^  (all|differing)",
        )
    run(
        f"cross_{g}_AvsB2_judgeA",
        [
            sys.executable,
            os.path.join(AB, "ab_cross_eval.py"),
            SGF[g],
            os.path.join(OUT, f"enigma_A_{g}_r1.json"),
            os.path.join(OUT, f"enigma_B2_{g}_r1.json"),
            "--config",
            CFG["A"],
            "--out",
            os.path.join(OUT, f"cross_{g}_AvsB2_judgeA.json"),
        ],
        1200,
        keep=r"^moves=|^  (all|differing)",
    )

# B の E2E 破損 2 件の診断（--debug で判定経路を残す）
run(
    "diag_B_F2at4",
    [
        sys.executable,
        TSU + "/generate_move_e2e.py",
        TSU + "/case-f2-rescue-shadow-20260730.sgf",
        "4",
        "5,12,6,12",
        "1",
        "--line=L12,K10,N8,N7,N11",
        "--debug",
        f"--config={CFG['B']}",
    ],
    900,
    keep=r"after 4 moves",
)
run(
    "diag_B_AAat6",
    [
        sys.executable,
        TSU + "/generate_move_e2e.py",
        TSU + "/case-aa-wall-is-target-20260802.sgf",
        "6",
        "5,12,0,8",
        "1",
        "--line=L1,J4,N3,K5,K6,N2,N5",
        "--debug",
        f"--config={CFG['B']}",
    ],
    900,
    keep=r"after 6 moves",
)
log("DONE cross")
