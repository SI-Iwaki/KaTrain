"""A/B 準備: 新エンジンの TensorRT プラン温め（katrain_debug 経由）＋ 3 構成のベンチマーク。

ログは ab/prep.log（utf-8）。各ステップは失敗しても次へ進む。
"""

import os
import re
import subprocess
import sys
import time

REPO = r"c:/Users/iwaki/Documents/katrain-1.17.1.1/katrain-1.17.1.1"
HOME = r"C:/Users/iwaki/.katrain"
LOG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "prep.log")
OLD_EXE = HOME + "/katago.exe"
NEW_EXE = HOME + "/katago-v1.18.1-trt/katago.exe"
B18 = REPO + "/katrain/models/kata1-b18c384nbt-s9996604416-d4316597426.bin.gz"
B10 = HOME + "/b10c384h6nbttflrs.bin.gz"
CFG_B = HOME + "/config_ab_v1181_b10c384.json"
CFG_B2 = HOME + "/config_ab_v1181_b18.json"
ANALYSIS_CFG = REPO + "/katrain/KataGo/analysis_config.cfg"
GTP_CFG = HOME + "/katago-v1.18.1-trt/default_gtp.cfg"

log_f = open(LOG, "a", encoding="utf-8", buffering=1)


def log(msg):
    line = f"{time.strftime('%H:%M:%S')} {msg}"
    log_f.write(line + "\n")
    log_f.flush()


def run(step, cmd, timeout, keep=None):
    log(f"STEP {step} start: {' '.join(cmd)}")
    t0 = time.time()
    try:
        p = subprocess.run(
            cmd, cwd=REPO, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout
        )
        out = (p.stdout or "") + (p.stderr or "")
        with open(LOG[:-4] + f".{step}.txt", "w", encoding="utf-8") as f:
            f.write(out)
        if keep:
            for ln in out.splitlines():
                if re.search(keep, ln):
                    log(f"  {step}: {ln.strip()[:200]}")
        log(f"STEP {step} done rc={p.returncode} in {time.time() - t0:.0f}s")
    except subprocess.TimeoutExpired:
        log(f"STEP {step} FAIL timeout after {timeout}s")
    except Exception as e:
        log(f"STEP {step} FAIL {e!r}")


threads = "12"
with open(ANALYSIS_CFG, encoding="utf-8") as f:
    m = re.search(r"^numSearchThreads\s*=\s*(\d+)", f.read(), flags=re.M)
    if m:
        threads = m.group(1)
log(f"benchmark threads={threads}")

KEEP = r"KataGo v|Loaded model|Model name|Initializing|timing cache|Started, ready|Result ---|^Move:|Traceback|rror"
run(
    "warmup_B_v1181_b10c384",
    [
        sys.executable,
        "-m",
        "katrain_debug",
        "--sgf",
        "tests/data/ogs.sgf",
        "--move",
        "30",
        "--strategy",
        "human",
        "--config",
        CFG_B,
    ],
    1800,
    KEEP,
)
run(
    "warmup_B2_v1181_b18",
    [
        sys.executable,
        "-m",
        "katrain_debug",
        "--sgf",
        "tests/data/ogs.sgf",
        "--move",
        "30",
        "--strategy",
        "human",
        "--config",
        CFG_B2,
    ],
    1800,
    KEEP,
)

BENCH_KEEP = r"KataGo v|Model name|numSearchThreads|visits/s|nnEvals|Traceback|rror|Uncaught"
for step, exe, model in [
    ("bench_A_v1164_b18", OLD_EXE, B18),
    ("bench_B2_v1181_b18", NEW_EXE, B18),
    ("bench_B_v1181_b10c384", NEW_EXE, B10),
]:
    for cfg in (ANALYSIS_CFG, GTP_CFG):
        cmd = [
            exe,
            "benchmark",
            "-model",
            model,
            "-config",
            cfg,
            "-t",
            threads,
            "-v",
            "3000",
            "-override-config",
            f"homeDataDir={HOME}",
        ]
        run(step + ("" if cfg == ANALYSIS_CFG else "_gtpcfg"), cmd, 1800, BENCH_KEEP)
        txt = open(LOG[:-4] + f".{step}{'' if cfg == ANALYSIS_CFG else '_gtpcfg'}.txt", encoding="utf-8").read()
        if "visits/s" in txt:
            break
        log(f"  {step}: no visits/s with {os.path.basename(cfg)}, trying next cfg")
log("DONE prep")
