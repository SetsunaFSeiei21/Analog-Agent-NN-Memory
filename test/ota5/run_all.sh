#!/usr/bin/env bash

set -euo pipefail


echo "========================================"
echo "SKY130 5T OTA Simulation"
echo "========================================"


# ============================================================
# Check ngspice
# ============================================================

if ! command -v ngspice >/dev/null 2>&1; then
    echo "[ERROR] ngspice not found in PATH."
    exit 1
fi


mkdir -p logs


# ============================================================
# Operating Point
# ============================================================

echo
echo "[1/6] Operating Point"

ngspice \
    -b \
    -o logs/op.log \
    tb_op.cir


# ============================================================
# AC
#
# DC Gain
# GBW
# Phase Margin
# ============================================================

echo
echo "[2/6] AC Performance"

ngspice \
    -b \
    -o logs/ac.log \
    tb_ac.cir


# ============================================================
# CMRR
# ============================================================

echo
echo "[3/6] CMRR"

ngspice \
    -b \
    -o logs/cmrr.log \
    tb_cmrr.cir


# ============================================================
# PMRR
# ============================================================

echo
echo "[4/6] PMRR"

ngspice \
    -b \
    -o logs/pmrr.log \
    tb_pmrr.cir


# ============================================================
# Slew Rate
# ============================================================

echo
echo "[5/6] Slew Rate"

ngspice \
    -b \
    -o logs/slew.log \
    tb_slew.cir


# ============================================================
# Power
# ============================================================

echo
echo "[6/6] Power"

ngspice \
    -b \
    -o logs/power.log \
    tb_power.cir


echo
echo "========================================"
echo "All simulations completed."
echo "========================================"
echo
echo "Logs:"
echo "  logs/op.log"
echo "  logs/ac.log"
echo "  logs/cmrr.log"
echo "  logs/pmrr.log"
echo "  logs/slew.log"
echo "  logs/power.log"
echo