"""エンジン A/B 本番: 腕の実効確認 → 詰碁 E2E（A/B）→ 難解13路バッチ（A/B × 2局 × 3run）→ 対照 B2。

腕: A = 現行（v1.16.4 TRT + b18, ~/.katrain/config.json）
    B = v1.18.1 TRT + b10c384 transformer（config_ab_v1181_b10c384.json）
    B2 = v1.18.1 TRT + b18（エンジンだけ替えた対照。config_ab_v1181_b18.json）
ログ: ab/run.log。各ステップの生出力は ab/out/<step>.txt|json。失敗しても次へ進む。
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
os.makedirs(OUT, exist_ok=True)
LOG = os.path.join(AB, "run.log")
TSU = REPO + "/docs/superpowers/specs/calibration-data/tsumego"
ARMS = {
    "A": None,
    "B": HOME + "/config_ab_v1181_b10c384.json",
    "B2": HOME + "/config_ab_v1181_b18.json",
}
ENIGMA_SGFS = {
    "g0823": REPO + "/docs/superpowers/specs/calibration-data/enigma9/enigma13-vs-human-20260823-white.sgf",
    "g0901": REPO + "/docs/superpowers/specs/calibration-data/enigma13/enigma13-vs-human-20260901-white.sgf",
}
log_f = open(LOG, "a", encoding="utf-8", buffering=1)


def log(msg):
    log_f.write(f"{time.strftime('%H:%M:%S')} {msg}\n")
    log_f.flush()


def run(step, cmd, timeout, keep=None, ext="txt"):
    log(f"STEP {step} start: {' '.join(cmd)}")
    t0 = time.time()
    try:
        p = subprocess.run(
            cmd, cwd=REPO, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout
        )
        with open(os.path.join(OUT, f"{step}.{ext}"), "w", encoding="utf-8") as f:
            f.write(p.stdout or "")
        with open(os.path.join(OUT, f"{step}.err"), "w", encoding="utf-8") as f:
            f.write(p.stderr or "")
        if keep:
            for ln in ((p.stdout or "") + (p.stderr or "")).splitlines():
                if re.search(keep, ln):
                    log(f"  {step}: {ln.strip()[:220]}")
        log(f"STEP {step} done rc={p.returncode} in {time.time() - t0:.0f}s")
        return p.returncode
    except subprocess.TimeoutExpired:
        log(f"STEP {step} FAIL timeout after {timeout}s")
    except Exception as e:
        log(f"STEP {step} FAIL {e!r}")
    return -1


def cfg_args(arm, style):
    cfg = ARMS[arm]
    if cfg is None:
        return []
    return [f"--config={cfg}"] if style == "eq" else ["--config", cfg]


# 1. 腕の実効確認: E2E と同じ入口（generate_move_e2e.py）で「Starting KataGo with」の exe/model を記録
for arm in ("A", "B", "B2"):
    run(
        f"verify_{arm}",
        [
            sys.executable,
            TSU + "/generate_move_e2e.py",
            TSU + "/case-d-gain-region-20260730.sgf",
            "4",
            "0,8,0,8",
            "1",
            "--line=C2,B2,D1,B1,A4,C1,B3",
            "--debug",
        ]
        + cfg_args(arm, "eq"),
        900,
        keep=r"Starting KataGo with|after 4 moves",
    )

# 2. 詰碁 E2E（既定＝回帰点だけ・3 repeats）
for arm in ("A", "B"):
    run(
        f"e2e_{arm}",
        [sys.executable, TSU + "/e2e_suite.py"] + cfg_args(arm, "eq"),
        5400,
        keep=r"PASS$|回帰失敗|手順差分|ERROR",
    )

# 3. 難解13路バッチ（AI=白）
for arm in ("A", "B"):
    for tag, sgf in ENIGMA_SGFS.items():
        for rep in (1, 2, 3):
            run(
                f"enigma_{arm}_{tag}_r{rep}",
                [
                    sys.executable,
                    "-m",
                    "katrain_debug",
                    "--sgf",
                    sgf,
                    "--strategy",
                    "enigma13",
                    "--batch",
                    "--player",
                    "W",
                    "--output",
                    "json",
                ]
                + cfg_args(arm, "sp"),
                3600,
                keep=r"Traceback|Error",
                ext="json",
            )

# 4. 対照 B2（エンジンだけ替えた腕）: E2E 1 本 ＋ 難解 1 run × 2 局
run(
    "e2e_B2",
    [sys.executable, TSU + "/e2e_suite.py"] + cfg_args("B2", "eq"),
    5400,
    keep=r"PASS$|回帰失敗|手順差分|ERROR",
)
for tag, sgf in ENIGMA_SGFS.items():
    run(
        f"enigma_B2_{tag}_r1",
        [
            sys.executable,
            "-m",
            "katrain_debug",
            "--sgf",
            sgf,
            "--strategy",
            "enigma13",
            "--batch",
            "--player",
            "W",
            "--output",
            "json",
        ]
        + cfg_args("B2", "sp"),
        3600,
        keep=r"Traceback|Error",
        ext="json",
    )
log("DONE run")
