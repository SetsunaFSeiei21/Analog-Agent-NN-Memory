#!/usr/bin/env bash
set -euo pipefail

# 只修改这里：正式任务的电路、采样量和集群配置。
SOURCE_DIR="Sample_Optimizer_Circuit/5t_ota"
CIRCUIT_NAME="5t_ota"
CIRCUIT_TYPE="single_ended_opamp"
N_POINTS=300
N_WORKERS=8
METRICS=(DC_GAIN UGF PM POWER)
TARGET_ROOT="sampling_database"
SEED=42
CONDA_ENV="newbase"
CONDA_HOME=""                       # 默认尝试 /share/software/anaconda3 或当前 conda。
NGSPICE_COMMAND="ngspice"
SIMULATION_CONDITION_PATH=""         # 留空使用项目内默认 JSON。
CONTINUE_ON_ERROR=1                  # 单点失败时记录失败数据并继续。
KEEP_WORKSPACE=0                     # 改为 1 保留 ngspice 工作区。
SLURM_ACCOUNT="b_phzhwu"
SLURM_PARTITION="ex01A800"
SLURM_GPUS=1
SLURM_MEM="80G"
SLURM_TIME="10-00:00:00"
SLURM_MAIL_USER="934104070@qq.com"
SLURM_MAIL_TYPE="BEGIN,END,FAIL"
DRY_RUN=0                             # 改成 1 只打印 sbatch 命令。

if (( $# != 0 )); then
    echo "[ERROR] 请直接修改脚本顶部的参数，再无参数运行本脚本" >&2
    exit 2
fi

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$PROJECT_ROOT"
export ANALOG_AGENT_ROOT="$PROJECT_ROOT"
export ANALOG_CONTINUE_ON_ERROR="$CONTINUE_ON_ERROR"
export ANALOG_KEEP_WORKSPACE="$KEEP_WORKSPACE"
export ANALOG_CONDA_ENV="$CONDA_ENV"
export ANALOG_CONDA_HOME="$CONDA_HOME"
export ANALOG_NGSPICE_COMMAND="$NGSPICE_COMMAND"
export ANALOG_SEED="$SEED"
export ANALOG_SIMULATION_CONDITION_PATH="$SIMULATION_CONDITION_PATH"

[[ "$CIRCUIT_NAME" =~ ^[A-Za-z0-9_-]+$ ]] || { echo "[ERROR] 电路名不合法" >&2; exit 2; }
[[ "$N_POINTS" =~ ^[1-9][0-9]*$ ]] && (( N_POINTS >= 3 )) || { echo "[ERROR] 采样点数至少为 3" >&2; exit 2; }
[[ "$N_WORKERS" =~ ^[1-9][0-9]*$ ]] || { echo "[ERROR] worker 数必须为正整数" >&2; exit 2; }
(( ${#METRICS[@]} > 0 )) || { echo "[ERROR] 至少选择一个指标" >&2; exit 2; }
SOURCE="$SOURCE_DIR"
if [[ "$SOURCE" != /* ]]; then SOURCE="$PROJECT_ROOT/$SOURCE"; fi
TARGET="$TARGET_ROOT"
if [[ "$TARGET" != /* ]]; then TARGET="$PROJECT_ROOT/$TARGET"; fi
LOG_DIR="$PROJECT_ROOT/hpc_logs/run/$(date -u +%Y%m%d)"
mkdir -p "$LOG_DIR"

OPTIONS=(
    --parsable --job-name="sample-$CIRCUIT_NAME"
    --output="$LOG_DIR/$CIRCUIT_NAME-%j.out"
    --error="$LOG_DIR/$CIRCUIT_NAME-%j.err"
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
[[ -d "$SOURCE" || -d "$TARGET/$CIRCUIT_NAME" ]] || {
    echo "[ERROR] 源目录和已有历史目录都不存在：$SOURCE" >&2
    exit 1
}
JOB_ID="$("${COMMAND[@]}")"
echo "正式采样已提交：job=$JOB_ID，circuit=$CIRCUIT_NAME"
echo "Slurm 日志：$LOG_DIR/$CIRCUIT_NAME-$JOB_ID.out"
echo "数据目录：$TARGET/$CIRCUIT_NAME"
