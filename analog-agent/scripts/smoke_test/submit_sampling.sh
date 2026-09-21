#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$PROJECT_ROOT"
export ANALOG_AGENT_ROOT="$PROJECT_ROOT"
export ANALOG_INPUT_ROOT="$PROJECT_ROOT/smoke_test_circuits"
export ANALOG_SMOKE_TEST=1
export ANALOG_KEEP_WORKSPACE=1
export ANALOG_CONTINUE_ON_ERROR=0

RUN_TAG="$(date -u +%Y%m%dT%H%M%SZ)-$$-$RANDOM"
SOURCE="$PROJECT_ROOT/Sample_Optimizer_Circuit/5t_ota"
TARGET="$PROJECT_ROOT/smoke_test_results/$RUN_TAG"
LOG_DIR="$PROJECT_ROOT/hpc_logs/smoke_test/$RUN_TAG"
mkdir -p "$LOG_DIR"

OPTIONS=(
    --parsable --job-name="smoke-5t-ota"
    --output="$LOG_DIR/%j.out" --error="$LOG_DIR/%j.err"
    --cpus-per-task=2 --mem="${ANALOG_SLURM_MEM:-8G}"
    --time="${ANALOG_SLURM_TIME:-00:30:00}" --export=ALL
)
if [[ -n "${ANALOG_SLURM_ACCOUNT:-}" ]]; then OPTIONS+=(--account="$ANALOG_SLURM_ACCOUNT"); fi
if [[ -n "${ANALOG_SLURM_PARTITION:-}" ]]; then OPTIONS+=(--partition="$ANALOG_SLURM_PARTITION"); fi

COMMAND=(
    sbatch "${OPTIONS[@]}" scripts/run/slurm_run.sh
    bash scripts/run/run_sampling.sh
    "$SOURCE" 5t_ota single_ended_opamp "$TARGET" 6 2
    DC_GAIN UGF PM POWER
)
if [[ "${ANALOG_DRY_RUN:-0}" == 1 ]]; then
    printf '%q ' "${COMMAND[@]}"
    printf '\n'
    exit 0
fi
[[ -d "$SOURCE" ]] || { echo "[ERROR] 示例电路目录不存在：$SOURCE" >&2; exit 1; }
JOB_ID="$("${COMMAND[@]}")"
echo "Smoke test 已提交：job=$JOB_ID"
echo "Slurm 日志：$LOG_DIR"
echo "数据目录：$TARGET/5t_ota"
