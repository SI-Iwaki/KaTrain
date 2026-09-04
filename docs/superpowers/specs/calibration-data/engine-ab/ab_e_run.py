"""難解 E 尺度比較の駆動: g0823 の白番全手を A / B / B2 で（エンジンは腕ごとに 1 回）。ログ: ab/e.log"""

import os
import subprocess
import sys
import time

REPO = r"c:/Users/iwaki/Documents/katrain-1.17.1.1/katrain-1.17.1.1"
HOME = r"C:/Users/iwaki/.katrain"
AB = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(AB, "out")
LOG = os.path.join(AB, "e.log")
SGF = REPO + "/docs/superpowers/specs/calibration-data/enigma9/enigma13-vs-human-20260823-white.sgf"
CFG = {
    "A": HOME + "/config.json",
    "B": HOME + "/config_ab_v1181_b10c384.json",
    "B2": HOME + "/config_ab_v1181_b18.json",
}
log_f = open(LOG, "a", encoding="utf-8", buffering=1)


def log(msg):
    log_f.write(f"{time.strftime('%H:%M:%S')} {msg}\n")
    log_f.flush()


for arm in ("A", "B", "B2"):
    step = f"e_{arm}_g0823"
    log(f"STEP {step} start")
    t0 = time.time()
    try:
        p = subprocess.run(
            [sys.executable, os.path.join(AB, "ab_enigma_e.py"), SGF, CFG[arm], os.path.join(OUT, f"{step}.json")],
            cwd=REPO,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=2400,
        )
        with open(os.path.join(OUT, f"{step}.txt"), "w", encoding="utf-8") as f:
            f.write((p.stdout or "") + "\n--- stderr ---\n" + (p.stderr or ""))
        tail = [ln for ln in (p.stdout or "").splitlines() if ln.startswith("wrote")]
        log(f"STEP {step} done rc={p.returncode} in {time.time() - t0:.0f}s {tail[-1] if tail else ''}")
    except Exception as e:
        log(f"STEP {step} FAIL {e!r}")
log("DONE e")
