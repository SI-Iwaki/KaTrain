"""指定 key を --debug で回し、標準出力（戦略ログ込み）を key ごとのファイルへ保存。usage: debug_capture.py <outdir> <keysfile> [--config cfg]"""
import subprocess, sys, os
outdir, keysfile = sys.argv[1], sys.argv[2]; cfg = sys.argv[sys.argv.index("--config")+1] if "--config" in sys.argv else None
os.makedirs(outdir, exist_ok=True)
here = "docs/superpowers/specs/calibration-data/tsumego/answer_book_replay.py"
for k in open(keysfile).read().strip().split(","):
    out = os.path.join(outdir, f"{k}.txt")
    if os.path.exists(out) and os.path.getsize(out) > 1000: continue
    cmd = [sys.executable, here, "--out", out + ".jsonl", "--keys", k, "--debug"] + (["--config", cfg] if cfg else [])
    with open(out, "w", encoding="utf-8", errors="replace") as f:
        subprocess.run(cmd, stdout=f, stderr=subprocess.STDOUT, env={**os.environ, "PYTHONIOENCODING": "utf-8"})
    print(k, "done", flush=True)
