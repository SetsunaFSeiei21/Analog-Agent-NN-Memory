#!/usr/bin/env bash
set -euo pipefail

# 只修改这里：烟测参数和集群配置。
CIRCUIT_NAME="two_stage_opamp_otaf"
CIRCUIT_TYPE="single_ended_opamp"
SOURCE_DIR="Sample_Optimizer_Circuit/two_stage_opamp_otaf"
N_POINTS=6
N_WORKERS=8
METRICS=(DC_GAIN UGF PM CMRR P_PSRR N_PSRR P_SR N_SR POWER)
SEED=42
CONDA_ENV="newbase"
CONDA_HOME=""                       # 默认尝试 /share/software/anaconda3 或当前 conda。
NGSPICE_COMMAND="ngspice"
SIMULATION_CONDITION_PATH=""         # 留空使用项目内默认 JSON。
SLURM_ACCOUNT="b_phzhwu"
SLURM_PARTITION="ex01A800"
SLURM_GPUS=1
SLURM_MEM="80G"
SLURM_TIME="10-00:00:00"
SLURM_MAIL_USER="934104070@qq.com"
SLURM_MAIL_TYPE="BEGIN,END,FAIL"
DRY_RUN=0                             # 改成 1 只打印 sbatch 命令。

if (( $# != 0 )); then
    echo "[ERROR] 请修改脚本顶部的参数，再无参数运行本脚本" >&2
    exit 2
fi
[[ "$N_POINTS" =~ ^[1-9][0-9]*$ ]] && (( N_POINTS >= 3 )) || { echo "[ERROR] 采样点数至少为 3" >&2; exit 2; }
[[ "$N_WORKERS" =~ ^[1-9][0-9]*$ ]] || { echo "[ERROR] worker 数必须为正整数" >&2; exit 2; }
(( ${#METRICS[@]} > 0 )) || { echo "[ERROR] 至少选择一个指标" >&2; exit 2; }

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$PROJECT_ROOT"
export ANALOG_AGENT_ROOT="$PROJECT_ROOT"
export ANALOG_INPUT_ROOT="$PROJECT_ROOT/smoke_test_circuits"
export ANALOG_SMOKE_TEST=0
export ANALOG_KEEP_WORKSPACE=1
export ANALOG_CONTINUE_ON_ERROR=1
export ANALOG_CONDA_ENV="$CONDA_ENV"
export ANALOG_CONDA_HOME="$CONDA_HOME"
export ANALOG_NGSPICE_COMMAND="$NGSPICE_COMMAND"
export ANALOG_SEED="$SEED"
export ANALOG_SIMULATION_CONDITION_PATH="$SIMULATION_CONDITION_PATH"

RUN_TAG="$(date -u +%Y%m%dT%H%M%SZ)-$$-$RANDOM"
SOURCE="$SOURCE_DIR"
if [[ "$SOURCE" != /* ]]; then SOURCE="$PROJECT_ROOT/$SOURCE"; fi
TARGET="$PROJECT_ROOT/smoke_test_results/$RUN_TAG"
LOG_DIR="$PROJECT_ROOT/hpc_logs/smoke_test/$RUN_TAG"
mkdir -p "$LOG_DIR"

OPTIONS=(
    --parsable --job-name="smoke-${CIRCUIT_NAME//_/-}"
    --output="$LOG_DIR/%j.out" --error="$LOG_DIR/%j.err"
    --nodes=1 --ntasks=1 --ntasks-per-node=1
    --cpus-per-task="$N_WORKERS" --gres="gpu:$SLURM_GPUS"
    --mem="$SLURM_MEM" --time="$SLURM_TIME"
    --mail-user="$SLURM_MAIL_USER" --mail-type="$SLURM_MAIL_TYPE"
    --export=ALL
)
if [[ -n "$SLURM_ACCOUNT" ]]; then OPTIONS+=(--account="$SLURM_ACCOUNT"); fi
if [[ -n "$SLURM_PARTITION" ]]; then OPTIONS+=(--partition="$SLURM_PARTITION"); fi

COMMAND=(
    sbatch "${OPTIONS[@]}" scripts/run/slurm_run.sh
    bash scripts/run/run_sampling.sh
    "$SOURCE" "$CIRCUIT_NAME" "$CIRCUIT_TYPE" "$TARGET" "$N_POINTS" "$N_WORKERS"
    "${METRICS[@]}"
)
if [[ "$DRY_RUN" == 1 ]]; then
    printf '%q ' "${COMMAND[@]}"
    printf '\n'
    exit 0
fi
[[ -d "$SOURCE" ]] || { echo "[ERROR] 示例电路目录不存在：$SOURCE" >&2; exit 1; }
JOB_ID="$("${COMMAND[@]}")"
echo "Smoke test 已提交：job=$JOB_ID"
echo "Slurm 日志：$LOG_DIR"
echo "数据目录：$TARGET/$CIRCUIT_NAME"
