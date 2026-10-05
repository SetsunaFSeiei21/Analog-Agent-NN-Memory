"""Electrical checks against a known linear op-amp, without a PDK dependency.

Set ANALOG_TEST_NGSPICE to an executable path, or install ngspice on PATH.
The tests exercise the real Simulator rendering, execution, and parsing path.
"""
from __future__ import annotations

import json
import math
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.sample_optimize.simulating import Simulator  # noqa: E402

NGSPICE = shutil.which(os.environ.get("ANALOG_TEST_NGSPICE", "ngspice"))
METRICS = ["DC_GAIN", "UGF", "PM", "CMRR", "P_PSRR", "N_PSRR", "P_SR", "N_SR", "POWER"]


@unittest.skipUnless(NGSPICE, "ngspice is required for electrical testbench checks")
class NgspiceTestbenchTest(unittest.TestCase):
    def run_amplifier(self, gain: float, common_gain: float, metrics=METRICS):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "AnalyticOpamp"
            source.mkdir()
            (source / "AnalyticOpamp_params.sp").write_text(
                f".param AD={gain}\n.param ACM={common_gain}\n", encoding="utf-8"
            )
            # An independent linear model: known differential/common-mode gains,
            # one output pole, supply feedthrough 0.1/0.2, and 100-uA rail draw.
            (source / "AnalyticOpamp.sp").write_text(
                '.include "AnalyticOpamp_params.sp"\n'
                ".subckt DUT VINP VINN VOUT VDD VSS\n"
                "BGAIN DRIVE 0 V={0.72 + AD*(V(VINP)-V(VINN)) "
                "+ ACM*((V(VINP)+V(VINN))/2-0.72) "
                "+ 0.1*(V(VDD)-1.8) + 0.2*V(VSS)}\n"
                "ROUT DRIVE VOUT 1k\nCINT VOUT 0 100n\n"
                "IQ VDD VSS DC 100u\n.ends DUT\n", encoding="utf-8"
            )
            pdk = root / "empty.lib"
            pdk.write_text("* No transistor models needed.\n.lib tt\n.endl tt\n")
            conditions = root / "conditions"
            conditions.mkdir()
            for path in (ROOT / "configs/testbench/acdc_reference").glob("*.json"):
                values = json.loads(path.read_text(encoding="utf-8"))
                values.update(PDK_PATH=pdk.as_posix(), AC_POINTS_PER_DEC=100)
                (conditions / path.name).write_text(json.dumps(values), encoding="utf-8")
            simulator = Simulator(
                metrics, "single_ended_opamp", "AnalyticOpamp",
                simulate_condition_path=conditions, output_path=root / "results",
                ngspice_command=NGSPICE, timeout_seconds=30,
            )
            return simulator.simulate_batch(
                source, 1, np.asarray([[gain, common_gain]]), continue_on_error=True
            )

    def test_single_pole_metrics_match_independent_analytic_solution(self):
        gain, common_gain = 1000.0, 10.0
        result = self.run_amplifier(gain, common_gain)
        self.assertEqual(result.failure_records, ())
        values = dict(zip(METRICS, result.metrics[0]))
        self.assertTrue(np.all(np.isfinite(result.metrics)))
        inverting_gain = gain - common_gain / 2
        pole = 1 / (2 * math.pi * 1000 * (100e-9 + 1e-12))
        expected_ugf = pole * math.sqrt(inverting_gain**2 - 1)
        expected_pm = 180 - math.degrees(math.atan(math.sqrt(inverting_gain**2 - 1)))
        self.assertAlmostEqual(values["DC_GAIN"], 20 * math.log10(inverting_gain), delta=1e-4)
        self.assertAlmostEqual(values["UGF"] / expected_ugf, 1, delta=1e-3)
        self.assertAlmostEqual(values["PM"], expected_pm, delta=0.01)
        self.assertAlmostEqual(values["CMRR"], 20 * math.log10(gain / common_gain), delta=1e-4)
        for metric, feedthrough in (("P_PSRR", 0.1), ("N_PSRR", 0.2)):
            expected = 20 * math.log10((1 + inverting_gain) / feedthrough)
            self.assertAlmostEqual(values[metric], expected, delta=1e-4)
        self.assertAlmostEqual(values["POWER"], 180.0, delta=1e-5)
        output_swing = 0.4 * (gain + common_gain / 2) / (1 + inverting_gain)
        time_constant = 1000 * (100e-9 + 1e-12) / (1 + inverting_gain)
        expected_slew = 0.8 * output_swing / (math.log(9) * time_constant) / 1e6
        for metric in ("P_SR", "N_SR"):
            self.assertAlmostEqual(values[metric] / expected_slew, 1, delta=0.01)

    def test_low_gain_cmrr_keeps_adm_over_acm_definition(self):
        result = self.run_amplifier(2.0, 0.4, ["CMRR"])
        self.assertEqual(result.failure_records, ())
        self.assertAlmostEqual(result.metrics[0, 0], 20 * math.log10(5), delta=1e-4)

    def test_sub_unity_gain_stays_negative_and_ugf_is_missing(self):
        result = self.run_amplifier(0.1, 0.0, ["DC_GAIN", "UGF"])
        self.assertAlmostEqual(result.metrics[0, 0], -20.0, delta=1e-4)
        self.assertTrue(np.isnan(result.metrics[0, 1]))
        self.assertEqual(result.failure_records[0]["failed_metrics"], ["UGF"])


if __name__ == "__main__":
    unittest.main()
