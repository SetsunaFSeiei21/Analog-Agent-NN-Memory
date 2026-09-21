#!/usr/bin/env bash
set -euo pipefail

if (( $# < 7 )); then
    echo "用法: $0 源电路目录 电路名 电路类型 数据库根目录 采样点数 worker数 指标..." >&2
    exit 2
fi

SOURCE_DIR="$1"
CIRCUIT_NAME="$2"
CIRCUIT_TYPE="$3"
TARGET_ROOT="$4"
N_POINTS="$5"
N_WORKERS="$6"
shift 6
METRICS=("$@")

[[ "$CIRCUIT_NAME" =~ ^[A-Za-z0-9_-]+$ ]] || { echo "[ERROR] 电路名不合法" >&2; exit 2; }
[[ "$N_POINTS" =~ ^[1-9][0-9]*$ ]] && (( N_POINTS >= 3 )) || { echo "[ERROR] n_points 至少为 3" >&2; exit 2; }
[[ "$N_WORKERS" =~ ^[1-9][0-9]*$ ]] || { echo "[ERROR] n_workers 必须大于 0" >&2; exit 2; }

PROJECT_ROOT="${ANALOG_AGENT_ROOT:-$(pwd)}"
cd "$PROJECT_ROOT"
export PYTHONPATH="$PROJECT_ROOT${PYTHONPATH:+:$PYTHONPATH}"
PYTHON="${ANALOG_PYTHON:-python}"
NGSPICE="${ANALOG_NGSPICE_COMMAND:-ngspice}"
command -v "$PYTHON" >/dev/null || { echo "[ERROR] 未找到 Python：$PYTHON" >&2; exit 1; }
command -v "$NGSPICE" >/dev/null || { echo "[ERROR] 未找到 ngspice：$NGSPICE" >&2; exit 1; }
command -v flock >/dev/null || { echo "[ERROR] 未找到 flock 命令" >&2; exit 1; }

CONDITIONS="${ANALOG_SIMULATION_CONDITION_PATH:-$PROJECT_ROOT/src/sample_optimize/testbench/$CIRCUIT_TYPE/default_simulate_condition}"
"$PYTHON" - "$CONDITIONS" "${METRICS[@]}" <<'PY'
import json
import sys
from pathlib import Path

from src.sample_optimize.simulating import SINGLE_OPAMP_METRIC2TESTBENCH_NAME

conditions = Path(sys.argv[1])
for metric in sys.argv[2:]:
    bench = SINGLE_OPAMP_METRIC2TESTBENCH_NAME.get(metric)
    if bench is None:
        sys.exit(f"[ERROR] 不支持的指标：{metric}")
    config_file = conditions / f"{bench}_condition.json"
    if not config_file.is_file():
        sys.exit(f"[ERROR] 缺少仿真条件：{config_file}")
    pdk = json.loads(config_file.read_text(encoding="utf-8")).get("PDK_PATH")
    if not pdk or not Path(pdk).is_file():
        sys.exit(f"[ERROR] {config_file} 的 PDK_PATH 不存在：{pdk}")
PY

mkdir -p "$TARGET_ROOT"
TARGET_ROOT="$(cd "$TARGET_ROOT" && pwd)"
exec 9>"$TARGET_ROOT/.${CIRCUIT_NAME}.sampling.lock"
flock -n 9 || { echo "[ERROR] 电路 $CIRCUIT_NAME 已有采样任务在运行" >&2; exit 1; }

HISTORY_DIR="$TARGET_ROOT/$CIRCUIT_NAME"
if [[ -d "$HISTORY_DIR" ]]; then
    echo "复用历史数据：$HISTORY_DIR"
    CIRCUIT_SOURCE="$HISTORY_DIR"
else
    [[ -d "$SOURCE_DIR" ]] || { echo "[ERROR] 源电路目录不存在：$SOURCE_DIR" >&2; exit 1; }
    SOURCE_DIR="$(cd "$SOURCE_DIR" && pwd)"
    [[ -f "$SOURCE_DIR/$CIRCUIT_NAME.sp" && -f "$SOURCE_DIR/${CIRCUIT_NAME}_params.sp" ]] || {
        echo "[ERROR] 缺少 $CIRCUIT_NAME.sp 或 ${CIRCUIT_NAME}_params.sp" >&2
        exit 1
    }
    INPUT_ROOT="${ANALOG_INPUT_ROOT:-$PROJECT_ROOT/sampling_inputs}"
    mkdir -p "$INPUT_ROOT"
    STAGING_DIR="$(mktemp -d "$INPUT_ROOT/${CIRCUIT_NAME}.XXXXXX")"
    CIRCUIT_SOURCE="$STAGING_DIR/$CIRCUIT_NAME"
    cp -a "$SOURCE_DIR" "$CIRCUIT_SOURCE"
    echo "复制输入电路：$SOURCE_DIR -> $CIRCUIT_SOURCE"
    # Controller 会把副本移入数据库；初始化失败时保留副本用于排查。
    trap 'rmdir "$STAGING_DIR" 2>/dev/null || true' EXIT
fi

ARGS=(
    -m src.sample_optimize.sample_only
    --src_path "$CIRCUIT_SOURCE"
    --circuit_type "$CIRCUIT_TYPE"
    --circuit_name "$CIRCUIT_NAME"
    --target_path "$TARGET_ROOT"
    --metrics "${METRICS[@]}"
    --n_points "$N_POINTS"
    --n_workers "$N_WORKERS"
    --ngspice_command "$NGSPICE"
    --simulation_condition_path "$CONDITIONS"
    --seed "${ANALOG_SEED:-42}"
)
if [[ "${ANALOG_KEEP_WORKSPACE:-0}" == 1 ]]; then ARGS+=(--keep_workspace); fi
if [[ "${ANALOG_CONTINUE_ON_ERROR:-0}" == 1 ]]; then
    ARGS+=(--continue_on_error)
else
    ARGS+=(--no-continue_on_error)
fi

"$PYTHON" "${ARGS[@]}"

if [[ "${ANALOG_SMOKE_TEST:-0}" == 1 ]]; then
    "$PYTHON" - "$HISTORY_DIR" "$N_POINTS" <<'PY'
import sqlite3
import sys
from pathlib import Path

history, expected = Path(sys.argv[1]), int(sys.argv[2])
with sqlite3.connect(history / "sampling_history.sqlite3") as connection:
    total, passed = connection.execute(
        "SELECT COUNT(*), COALESCE(SUM(success), 0) FROM samples"
    ).fetchone()
if (total, passed) != (expected, expected):
    sys.exit(f"[ERROR] Smoke test 未完全成功：total={total}, passed={passed}, expected={expected}")
for name in ("design_parameters.csv", "metrics.csv"):
    if not (history / name).is_file():
        sys.exit(f"[ERROR] 缺少输出文件：{history / name}")
print(f"[OK] Smoke test 成功：{passed}/{expected}，数据位于 {history}")
PY
fi
