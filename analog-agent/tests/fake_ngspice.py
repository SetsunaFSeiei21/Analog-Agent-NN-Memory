#!/usr/bin/env python3

from pathlib import Path
import sys


def main() -> int:
    arguments = sys.argv[1:]
    log_name = arguments[arguments.index("-o") + 1]
    testbench_name = Path(arguments[-1]).stem
    values = {
        "tb_ac": "dc_gain_db = 60\ngbw_hz = 1.2e7\n",
        "tb_stability": "phase_margin_deg = 68\n",
        "tb_cmrr": "cmrr_ref_db = 92\n",
        "tb_psrr": "psrr_plus_ref_db = 80\npsrr_minus_ref_db = 76\n",
        "tb_slew": "slew_rise_v_us = 12\nslew_fall_v_us = 10\n",
        "tb_power": "power_uw = 150\n",
    }
    Path(log_name).write_text(values[testbench_name], encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
