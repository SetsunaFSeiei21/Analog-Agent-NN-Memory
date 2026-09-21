#!/usr/bin/env bash
#SBATCH --job-name=analog-sampling
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=2
#SBATCH --mem=8G
#SBATCH --time=00:30:00

set -euo pipefail

PROJECT_ROOT="${ANALOG_AGENT_ROOT:-${SLURM_SUBMIT_DIR:-}}"
if [[ -z "$PROJECT_ROOT" ]]; then
    PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
fi
[[ -f "$PROJECT_ROOT/src/sample_optimize/sample_only.py" ]] || {
    echo "[ERROR] Analog-Agent 项目目录无效：$PROJECT_ROOT" >&2
    exit 1
}
cd "$PROJECT_ROOT"
export PYTHONPATH="$PROJECT_ROOT${PYTHONPATH:+:$PYTHONPATH}"

# 已激活的 Python 环境可以直接继承；需要在计算节点激活 Conda 时设置 ANALOG_CONDA_ENV。
if [[ -n "${ANALOG_CONDA_ENV:-}" ]]; then
    CONDA_BASE="${ANALOG_CONDA_HOME:-/share/software/anaconda3}"
    if [[ ! -f "$CONDA_BASE/etc/profile.d/conda.sh" ]] && command -v conda >/dev/null 2>&1; then
        CONDA_BASE="$(conda info --base)"
    fi
    [[ -f "$CONDA_BASE/etc/profile.d/conda.sh" ]] || {
        echo "[ERROR] 找不到 conda.sh，请设置 ANALOG_CONDA_HOME" >&2
        exit 1
    }
    source "$CONDA_BASE/etc/profile.d/conda.sh"
    conda activate "$ANALOG_CONDA_ENV"
fi

echo "Job ID: ${SLURM_JOB_ID:-local} | Node: ${SLURM_NODELIST:-local}"
echo "Project: $PROJECT_ROOT | Python: $(command -v "${ANALOG_PYTHON:-python}" || true)"
printf 'Command:'
printf ' %q' "$@"
printf '\n'
exec "$@"
