"""Optional real Sky130 checks. Set ANALOG_TEST_NGSPICE and
ANALOG_TEST_SKY130_LIBRARY (a .lib file exposing corner tt)."""
import json
import os
import shutil
from pathlib import Path

import numpy as np
import pytest

from src.circuit_ir import parse_circuit
from src.sample_optimize.advanced.config import load_config
from src.sample_optimize.advanced.context import simulation_context
from src.sample_optimize.advanced.profiles import make_profile, REFERENCES
from src.sample_optimize.simulating import Simulator, SINGLE_OPAMP_METRIC2METRIC
from src.utils.spice_parser import read_parameter_names

PROJECT = Path(__file__).resolve().parents[1]
NGSPICE = shutil.which(os.environ.get("ANALOG_TEST_NGSPICE", "ngspice"))
LIBRARY = os.environ.get("ANALOG_TEST_SKY130_LIBRARY")
pytestmark = pytest.mark.skipif(not NGSPICE or not LIBRARY, reason="real ngspice and Sky130 TT library required")


@pytest.mark.parametrize("name", REFERENCES)
def test_real_sky130_op_hierarchy_partial_metrics_and_bias_regions(tmp_path, name):
    conditions = tmp_path / "conditions"
    conditions.mkdir()
    defaults = PROJECT / "src/sample_optimize/testbench/single_ended_opamp/default_simulate_condition"
    for file in defaults.glob("*.json"):
        values = json.loads(file.read_text())
        values["PDK_PATH"] = str(Path(LIBRARY).resolve())
        (conditions / file.name).write_text(json.dumps(values))
    source = PROJECT / "Sample_Optimizer_Circuit" / name
    ir = parse_circuit(source / f"{name}.sp")
    _, signal, _ = make_profile(name, ir, load_config()["gmid"])
    simulator = Simulator(list(SINGLE_OPAMP_METRIC2METRIC), "single_ended_opamp", name,
                          simulate_condition_path=conditions, output_path=tmp_path,
                          ngspice_command=NGSPICE)
    context = simulation_context(source, name, simulator)
    simulator.operating_point_config = {
        "circuit": ir, "signal_devices": signal, "constraints": load_config()["constraints"],
        "condition": {**context["conditions"]["power"], "MOS_PRIMITIVES": context["mos_primitives"]},
    }
    parameters = dict(ir.parameter_defaults)
    if name == "Opamp0":
        parameters.update({f"DESVAR_W{i}": 10. for i in range(1, 10)})
        parameters.update({f"DESVAR_L{i}": .5 for i in range(1, 10)})
        # Preserve the previous fixture's bias geometry and 2:1 mirror ratios
        # while exercising the new independent sizing parameters.
        parameters.update(DESVAR_W3=1., DESVAR_L3=5., DESVAR_L4=.15, DESVAR_L7=.15,
                          DESVAR_W8=1., DESVAR_L8=5., DESVAR_M1=2., DESVAR_M5=2.,
                          IBIAS_A=2e-7)
    names = read_parameter_names(source / f"{name}_params.sp")
    result = simulator.simulate_batch(source, 1, np.asarray([[parameters[n] for n in names]]), True)
    assert result.metrics.shape == (1, 9)
    observation = result.observations[0]
    assert observation["converged"]
    expected = {d.name.upper() for d in ir.devices if d.model}
    assert set(observation["devices"]) == expected
    assert all(d["gm"] is not None and d["id"] is not None and d["vdsat"] is not None
               for d in observation["devices"].values())
    assert np.isfinite(result.metrics[0, -1])  # Power remains available even if AC metrics fail.
    if name == "Opamp0":
        assert observation["feasible"]
        assert observation["devices"]["XNM6"]["saturation_margin_v"] < 0
        assert observation["devices"]["XPM6"]["id"] / observation["devices"]["XPM7"]["id"] == pytest.approx(2., rel=.1)
