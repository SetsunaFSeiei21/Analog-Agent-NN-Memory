"""LVT model selection, length domains and default bias regressions (no PDK)."""
import json
import logging
import re
import shutil
import subprocess
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
import pytest

from src.circuit_ir import parse_circuit
from src.sample_optimize.advanced.config import DesignDomain, load_config
from src.sample_optimize.advanced.context import resolve_mos_primitives, simulation_context
from src.sample_optimize.advanced.lut import MosLUT
from src.sample_optimize.advanced.operating_point import primitive
from src.sample_optimize.advanced.profiles import Group
from src.sample_optimize.sampling_controller import Sampling_Controller
from test_advanced_sampling import store

PROJECT = Path(__file__).resolve().parents[1]
N = "sky130_fd_pr__nfet_01v8"
NL = N + "_lvt"
PL = "sky130_fd_pr__pfet_01v8_lvt"


def test_context_resolves_only_actual_lvt_wrappers(tmp_path):
    pdk = tmp_path / "lvt.lib"
    pdk.write_text("\n".join(
        f".subckt {model} D G S B\nm_{i} D G S B core\n.ends {model}"
        for i, model in enumerate((NL, PL))))
    (tmp_path / "power_condition.json").write_text(json.dumps({
        "PDK_PATH": str(pdk), "CORNER": "tt", "TEMP": 27, "VDD": 1.8, "VSS": 0, "VCM": .72}))
    (tmp_path / "tb_power.cir").write_text("* context-only fixture\n")
    simulator = SimpleNamespace(simulate_condition_path=tmp_path, circuit_testbench_path=tmp_path,
                                ngspice_command="unused", _get_testbench_name_lst=lambda: ["power"])
    source = PROJECT / "Sample_Optimizer_Circuit/Opamp0"
    with patch("src.sample_optimize.advanced.context.subprocess.run",
               return_value=subprocess.CompletedProcess([], 0, "fixture-version", "")):
        context = simulation_context(source, "Opamp0", simulator)
    assert context["mos_primitives"] == {NL: "m_0", PL: "m_1"}
    circuit = parse_circuit(source / "Opamp0.sp")
    for device in circuit.devices:
        if device.model:
            assert primitive(device, context["mos_primitives"]) == (
                f"m.xdut.{device.name.lower()}." + ("m_0" if device.model == NL else "m_1"))
    with pytest.raises(ValueError, match=N + "$"):
        resolve_mos_primitives([pdk], [N])


def test_model_specific_lut_axes_decks_and_cache(tmp_path):
    (tmp_path / "demo_params.sp").write_text(".param W=1 LN=.15 LNL=.35 LP=.35\n")
    circuit_file = tmp_path / "demo.sp"
    circuit_file.write_text(f""".include "demo_params.sp"
.subckt DUT VINP VINN VOUT VDD VSS
XN VOUT VINP VSS VSS {N} W={{W}} L={{LN}}
XNL VOUT VINP VSS VSS {NL} W={{W}} L={{LNL}}
XP VOUT VINN VDD VDD {PL} W={{W}} L={{LP}}
.ends DUT
""")
    circuit = parse_circuit(circuit_file)
    domain = DesignDomain(["LN", "LNL", "LP"], [[.15, .20, .05], [.35, .35, .01], [.35, .55, .1]])
    groups = [Group("W", length, name, (name,)) for name, length in
              (("XN", "LN"), ("XNL", "LNL"), ("XP", "LP"))]
    config = load_config()["gmid"]["lut"]
    config.update(vgs=[0, 1.8, .9], vds=[0, 1.8, .9], reverse_body_bias=[0, 1.8, 1.8], max_lengths=3)
    context = {"conditions": {"power": {"PDK_PATH": "unused.lib", "CORNER": "tt", "TEMP": 27, "VDD": 1.8, "VSS": 0}},
               "models": {}, "ngspice_version": "oracle", "initialization": "", "global_initialization": {},
               "spice_scripts": None, "mos_primitives": {N: "m0", NL: "mn_lvt", PL: "mp_lvt"}}
    history = store(tmp_path / "history")
    run = history.create_run(1, 1, {"gmid": 1}, {})
    cache = tmp_path / "cache"
    args = (cache, context, domain, groups, config, "unused", 1, history.database_path, run, logging.getLogger("test-lvt"))
    decks = []
    allowed = {N: [.15, .20], NL: [.35], PL: [.35, .45, .55]}
    density = {N: 1., NL: 2., PL: 3.}

    def characterize(args, *, cwd, **kwargs):
        deck = (Path(cwd) / "lut.cir").read_text()
        model, length = re.search(r"XREF D G 0 B (\S+) W=\S+ L=(\S+)", deck).groups()
        assert any(np.isclose(float(length), v) for v in allowed[model])
        assert f"@m.xref.{context['mos_primitives'][model]}[gm]" in deck
        sweep = re.search(r"(?m)^dc VD (\S+) (\S+) (\S+)", deck)
        assert [float(v) for v in sweep.groups()] == ([0., -1.8, -.9] if model == PL else [0., 1.8, .9])
        decks.append((model, float(length)))
        current = np.full(9, density[model] * config["reference_width_um"] * 1e-6)
        np.savetxt(Path(cwd) / "table.txt", np.column_stack([np.arange(9), current, 10*current, np.full(9, .2)]))
        return subprocess.CompletedProcess(args, 0, "", "")

    with patch("src.sample_optimize.advanced.lut.subprocess.run", characterize):
        table, key = MosLUT.ensure(*args, circuit=circuit, workers=3)
    assert len(decks) == 12
    for model, lengths in allowed.items():
        assert table.metadata["model_tables"][model]["length_m"] == pytest.approx(np.array(lengths)*1e-6)
        assert table.lookup(model, lengths[0], 0, .9, .9)[0, 0] == pytest.approx(density[model])
    assert np.isnan(table.lookup(PL, .15, 0, .9, .9)).all()
    assert np.isnan(table.lookup(NL, .40, 0, .9, .9)).all()
    with patch("src.sample_optimize.advanced.lut.subprocess.run", side_effect=AssertionError("cache miss")):
        cached, cached_key = MosLUT.ensure(*args, circuit=circuit)
    assert cached_key == key
    assert np.array_equal(cached.functions[PL].values, table.functions[PL].values)

    # A model swap must rebuild even when PDK hashes and voltage axes are unchanged.
    changed = replace(circuit, devices=tuple(replace(d, model=NL) if d.name == "XN" else d for d in circuit.devices))
    allowed[NL] = [.15, .20, .35]  # NMOS LVT can have its own shorter length domain.
    with patch("src.sample_optimize.advanced.lut.subprocess.run", characterize):
        other, other_key = MosLUT.ensure(*args, circuit=changed)
    assert other_key != key and set(other.functions) == {NL, PL}


def test_opamp0_controller_uses_global_lvt_lengths(tmp_path):
    # The legacy controller moves its source into history on first use.
    source = tmp_path / "source"
    shutil.copytree(PROJECT / "Sample_Optimizer_Circuit/Opamp0", source)
    with Sampling_Controller(
        src_path=source, target_path=tmp_path / "history",
        circuit_name="Opamp0", circuit_type="single_ended_opamp", metrics=["POWER"], console_log=False) as controller:
        bounds = dict(zip(controller.parameter_name_lst, controller.bounds))
    assert len(bounds) == 18
    assert all(bounds[f"DESVAR_L{i}"] == (.35, 1., .01) for i in range(1, 8))
    assert bounds["DESVAR_M0"] == (1, 10, 1)


def test_all_shipped_simulation_common_modes_are_072():
    directories = [PROJECT / "src/sample_optimize/testbench/single_ended_opamp/default_simulate_condition",
                   PROJECT / "configs/testbench/acdc_reference"]
    for directory in directories:
        conditions = list(directory.glob("*_condition.json"))
        assert len(conditions) == 6
        assert all(json.loads(p.read_text())["VCM"] == .72 for p in conditions)
    for relative in ("test/opamp0_open_loop/Opamp0_open_loop.cir", "test/opamp0_excel/Opamp0_all_metrics.cir",
                     "test/ota5/sim_params.sp"):
        assert float(re.search(r"(?:INPUT_VCM|VCM_VAL)\s*=\s*([\d.]+)",
                               (PROJECT.parent / relative).read_text())[1]) == .72
