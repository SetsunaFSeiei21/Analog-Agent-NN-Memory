#!/usr/bin/env bash
set -euo pipefail

# Temporary recovery for the two interrupted 60,000-point runs.
# Default: submit both; optional arguments select one or both circuit names.
# Their batch_size is 32, so >32 workers would not increase SPICE concurrency.
N_WORKERS="${ANALOG_RESUME_WORKERS:-8}"
TARGET_ROOT="${ANALOG_RESUME_TARGET_ROOT:-sampling_database}"
CONDA_ENV="${ANALOG_CONDA_ENV:-newbase}"
SLURM_ACCOUNT="${ANALOG_SLURM_ACCOUNT:-b_phzhwu}"
SLURM_PARTITION="${ANALOG_SLURM_PARTITION:-ex01A800}"
SLURM_GPUS="${ANALOG_SLURM_GPUS:-1}"
SLURM_MEM="${ANALOG_SLURM_MEM:-80G}"
SLURM_TIME="${ANALOG_SLURM_TIME:-10-00:00:00}"
SLURM_MAIL_USER="${ANALOG_SLURM_MAIL_USER:-934104070@qq.com}"
DRY_RUN="${DRY_RUN:-0}"
N_POINTS=60000
METRICS=(DC_GAIN UGF PM CMRR P_PSRR N_PSRR P_SR N_SR POWER)

[[ "$N_WORKERS" =~ ^[1-9][0-9]*$ ]] && (( N_WORKERS <= 32 )) || {
    echo "[ERROR] 这两次任务 batch_size=32，ANALOG_RESUME_WORKERS 应为 1..32" >&2; exit 2;
}
[[ "$SLURM_GPUS" =~ ^[0-9]+$ ]] || { echo "[ERROR] GPU 数必须是非负整数" >&2; exit 2; }
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$PROJECT_ROOT"
[[ "$TARGET_ROOT" == /* ]] || TARGET_ROOT="$PROJECT_ROOT/$TARGET_ROOT"

export ANALOG_AGENT_ROOT="$PROJECT_ROOT"
export ANALOG_CONDA_ENV="$CONDA_ENV"
export ANALOG_SAMPLING_MODE=five
export ANALOG_SEED=42
export ANALOG_SMOKE_TEST=0
export ANALOG_CONTINUE_ON_ERROR=1
# Each SPICE worker gets one CPU. Avoid 32 workers each starting a BLAS pool.
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1
export NUMEXPR_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1

if (( $# == 0 )); then set -- 5t_ota two_stage_opamp_otaf; fi
CIRCUITS=("$@")
declare -A RUN_IDS=(
    [5t_ota]=1e9b2d5c2b0a4558824b7437f30305d8
    [two_stage_opamp_otaf]=8459175daab247d5aac6243418564861
)
declare -A SEEN=()
# Validate every request before submitting any job.
for CIRCUIT in "${CIRCUITS[@]}"; do
    case "$CIRCUIT" in
        5t_ota|two_stage_opamp_otaf) ;;
        *) echo "[ERROR] 未知电路：$CIRCUIT" >&2; exit 2 ;;
    esac
    [[ -z "${SEEN[$CIRCUIT]:-}" ]] || {
        echo "[ERROR] 未知或重复电路：$CIRCUIT" >&2; exit 2;
    }
    SEEN[$CIRCUIT]=1
    if [[ "$DRY_RUN" != 1 ]]; then
        "${ANALOG_PYTHON:-python}" - "$TARGET_ROOT/$CIRCUIT" "${RUN_IDS[$CIRCUIT]}" "$N_POINTS" "$N_WORKERS" <<'PY'
import json
import runpy
import sqlite3
import sys
from contextlib import closing
from pathlib import Path

directory, run_id, target, workers = Path(sys.argv[1]), sys.argv[2], int(sys.argv[3]), int(sys.argv[4])
database = directory / "sampling_history.sqlite3"
if not database.is_file():
    sys.exit(f"[ERROR] 未找到已有数据库：{database}")
with closing(sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True)) as con:
    row = con.execute("SELECT r.status,r.requested_points,r.config_json,s.state_json FROM sampling_runs r "
                      "JOIN sampling_state s USING(run_id) WHERE r.run_id=?", (run_id,)).fetchone()
    if row is None or row[0] not in ("RUNNING", "FAILED") or row[1] != target:
        sys.exit(f"[ERROR] 任务不存在、已完成或目标点数不符：{run_id}")
    config, state = json.loads(row[2]), json.loads(row[3])
    if workers > config["sampling"]["batch_size"]:
        sys.exit("[ERROR] worker 数超过原任务 batch_size；请降低 ANALOG_RESUME_WORKERS")
    # Load the stdlib-only check without importing the numerical stack on login nodes.
    validate = runpy.run_path("src/sample_optimize/resume_compat.py")["validate_current_implementation"]
    try:
        validate(config, state["config_fingerprint"])
    except (KeyError, ValueError) as exc:
        sys.exit(f"[ERROR] {directory.name} 的原任务与当前采样实现不兼容：{exc}\n"
                 "本补丁仅兼容 SQLite 修复；若原任务早于 LVT/gm-ID 算法改动，"
                 "须使用原任务的采样版本续跑，或在新数据目录重新采样。")
    print(f"续跑检查：{directory.name}，已完成={sum(state['completed'].values())}/{target}，workers={workers}")
PY
    fi
done

LOG_DIR="$PROJECT_ROOT/hpc_logs/resume/$(date -u +%Y%m%d)"
if [[ "$DRY_RUN" != 1 ]]; then mkdir -p "$LOG_DIR"; fi
for CIRCUIT in "${CIRCUITS[@]}"; do
    OPTIONS=(
        --parsable --job-name="resume-$CIRCUIT"
        --output="$LOG_DIR/$CIRCUIT-%j.out" --error="$LOG_DIR/$CIRCUIT-%j.err"
        --nodes=1 --ntasks=1 --ntasks-per-node=1 --cpus-per-task="$N_WORKERS"
        --mem="$SLURM_MEM" --time="$SLURM_TIME"
        --mail-user="$SLURM_MAIL_USER" --mail-type=BEGIN,END,FAIL --export=ALL
    )
    # Explicitly override slurm_run.sh's GPU default, also for CPU partitions.
    OPTIONS+=(--gres="gpu:$SLURM_GPUS")
    if [[ -n "$SLURM_ACCOUNT" ]]; then OPTIONS+=(--account="$SLURM_ACCOUNT"); fi
    if [[ -n "$SLURM_PARTITION" ]]; then OPTIONS+=(--partition="$SLURM_PARTITION"); fi
    COMMAND=(env ANALOG_RESUME_RUN_ID="${RUN_IDS[$CIRCUIT]}"
        sbatch "${OPTIONS[@]}" scripts/run/slurm_run.sh
        bash scripts/run/run_sampling.sh
        "$TARGET_ROOT/$CIRCUIT" "$CIRCUIT" single_ended_opamp "$TARGET_ROOT"
        "$N_POINTS" "$N_WORKERS" "${METRICS[@]}")
    if [[ "$DRY_RUN" == 1 ]]; then
        printf '%q ' "${COMMAND[@]}"; printf '\n'
    else
        JOB_ID="$("${COMMAND[@]}")"
        echo "续跑已提交：circuit=$CIRCUIT，job=$JOB_ID，workers=$N_WORKERS"
        echo "Slurm 日志：$LOG_DIR/$CIRCUIT-${JOB_ID%%;*}.out"
    fi
done
