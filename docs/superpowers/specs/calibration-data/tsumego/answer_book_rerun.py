"""rerun_keys.py の --config 版: usage: rerun_keys_cfg.py <out.jsonl> <repeats> <config.json> <keysfile>"""
import subprocess, sys, os
out, reps, cfg, keysfile = sys.argv[1], int(sys.argv[2]), sys.argv[3], sys.argv[4]
keys = open(keysfile).read().strip().split(",")
here = "docs/superpowers/specs/calibration-data/tsumego/answer_book_replay.py"
for k in keys:
    for r in range(reps):
        tmp = out + f".{k}.{r}.tmp"
        subprocess.run([sys.executable, here, "--out", tmp, "--keys", k, "--config", cfg], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if os.path.exists(tmp):
            with open(tmp, encoding="utf-8") as f, open(out, "a", encoding="utf-8") as g:
                for line in f:
                    if line.strip(): g.write(line.rstrip("\n") + "\n")
            os.remove(tmp)
        print(f"{k} run{r+1} done", flush=True)
