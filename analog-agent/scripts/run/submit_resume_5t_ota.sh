#!/usr/bin/env bash
set -euo pipefail

# Resume the interrupted 5t_ota run. Defaults to 32 workers / 32 Slurm CPUs.
# Preview: DRY_RUN=1 bash scripts/run/submit_resume_5t_ota.sh
if (( $# != 0 )); then
    echo "[ERROR] 本脚本固定续跑 5t_ota；使用 ANALOG_RESUME_WORKERS 调整并发" >&2
    exit 2
fi
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec bash "$SCRIPT_DIR/submit_resume_sampling.sh" 5t_ota
