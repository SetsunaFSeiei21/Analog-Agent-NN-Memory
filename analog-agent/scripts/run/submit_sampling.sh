#!/usr/bin/env bash
set -euo pipefail

if (( $# < 6 )); then
    echo "用法: $0 源电路目录 电路名 电路类型 采样点数 worker数 指标..." >&2
    echo "示例: $0 Sample_Optimizer_Circuit/5t_ota 5t_ota single_ended_opamp 300 8 DC_GAIN UGF PM POWER" >&2
    exit 2
fi

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$PROJECT_ROOT"
export ANALOG_AGENT_ROOT="$PROJECT_ROOT"
export ANALOG_CONTINUE_ON_ERROR="${ANALOG_CONTINUE_ON_ERROR:-1}"
SOURCE="$1"
CIRCUIT_NAME="$2"
CIRCUIT_TYPE="$3"
N_POINTS="$4"
N_WORKERS="$5"
shift 5
METRICS=("$@")

[[ "$CIRCUIT_NAME" =~ ^[A-Za-z0-9_-]+$ ]] || { echo "[ERROR] 电路名不合法" >&2; exit 2; }
[[ "$N_POINTS" =~ ^[1-9][0-9]*$ ]] && (( N_POINTS >= 3 )) || { echo "[ERROR] 采样点数至少为 3" >&2; exit 2; }
[[ "$N_WORKERS" =~ ^[1-9][0-9]*$ ]] || { echo "[ERROR] worker 数必须为正整数" >&2; exit 2; }
if [[ -d "$SOURCE" ]]; then SOURCE="$(cd "$SOURCE" && pwd)"; fi
TARGET="${ANALOG_TARGET_ROOT:-$PROJECT_ROOT/sampling_database}"
LOG_DIR="$PROJECT_ROOT/hpc_logs/run/$(date -u +%Y%m%d)"
mkdir -p "$LOG_DIR"

OPTIONS=(
    --parsable --job-name="sample-$CIRCUIT_NAME"
    --output="$LOG_DIR/$CIRCUIT_NAME-%j.out"
    --error="$LOG_DIR/$CIRCUIT_NAME-%j.err"
    --cpus-per-task="$N_WORKERS" --mem="${ANALOG_SLURM_MEM:-16G}"
    --time="${ANALOG_SLURM_TIME:-1-00:00:00}" --export=ALL
)
if [[ -n "${ANALOG_SLURM_ACCOUNT:-}" ]]; then OPTIONS+=(--account="$ANALOG_SLURM_ACCOUNT"); fi
if [[ -n "${ANALOG_SLURM_PARTITION:-}" ]]; then OPTIONS+=(--partition="$ANALOG_SLURM_PARTITION"); fi

COMMAND=(
    sbatch "${OPTIONS[@]}" scripts/run/slurm_run.sh
    bash scripts/run/run_sampling.sh
    "$SOURCE" "$CIRCUIT_NAME" "$CIRCUIT_TYPE" "$TARGET" "$N_POINTS" "$N_WORKERS"
    "${METRICS[@]}"
)
if [[ "${ANALOG_DRY_RUN:-0}" == 1 ]]; then
    printf '%q ' "${COMMAND[@]}"
    printf '\n'
    exit 0
fi
[[ -d "$SOURCE" || -d "$TARGET/$CIRCUIT_NAME" ]] || {
    echo "[ERROR] 源目录和已有历史目录都不存在：$SOURCE" >&2
    exit 1
}
JOB_ID="$("${COMMAND[@]}")"
echo "正式采样已提交：job=$JOB_ID，circuit=$CIRCUIT_NAME"
echo "Slurm 日志：$LOG_DIR/$CIRCUIT_NAME-$JOB_ID.out"
echo "数据目录：$TARGET/$CIRCUIT_NAME"
