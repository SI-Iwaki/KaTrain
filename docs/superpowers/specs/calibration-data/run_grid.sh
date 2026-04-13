#!/usr/bin/env bash
# Jigo dynamic rank 校正グリッド実行スクリプト
# 使用: bash docs/superpowers/specs/calibration-data/run_grid.sh

set -euo pipefail

SGF="docs/superpowers/specs/calibration-data/jigo-vs-3dan-20260413-white.sgf"
RUNS_DIR="docs/superpowers/specs/calibration-data/runs"
mkdir -p "$RUNS_DIR"

COMMON_SETTINGS="target_score_max=5.0 max_loss_per_move=7.0 human_profile=rank_9d"

run_config() {
    local config_id="$1"
    local extra_settings="$2"
    for i in 1 2 3; do
        local out="$RUNS_DIR/${config_id}_run${i}.json"
        if [ -f "$out" ]; then
            echo "SKIP ${config_id} run ${i} (already exists: $out)"
            continue
        fi
        echo "RUN  ${config_id} run ${i} → $out"
        python -m katrain_debug \
            --sgf "$SGF" \
            --strategy jigo --batch --player W \
            --settings $COMMON_SETTINGS $extra_settings \
            --output json 2>/dev/null > "$out"
    done
}

run_config "off"   "jigo_dynamic_rank=false"
run_config "5-15"  "jigo_dynamic_rank=true jigo_rank_delta_1=5 jigo_rank_delta_2=15"
run_config "3-10"  "jigo_dynamic_rank=true jigo_rank_delta_1=3 jigo_rank_delta_2=10"
run_config "5-10"  "jigo_dynamic_rank=true jigo_rank_delta_1=5 jigo_rank_delta_2=10"
run_config "3-15"  "jigo_dynamic_rank=true jigo_rank_delta_1=3 jigo_rank_delta_2=15"

echo "Done. Runs in $RUNS_DIR"
ls -la "$RUNS_DIR"
