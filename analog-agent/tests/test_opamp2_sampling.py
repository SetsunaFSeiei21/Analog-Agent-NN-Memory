"""Opamp2 integration: corrected bindings and generic gm/ID sampling."""
import json
import re
from pathlib import Path

import numpy as np
import pytest

from src.circuit_ir import parse_circuit, resolve_circuit
from src.circuit_ir.schema import DeviceType
from src.sample_optimize.advanced.config import DesignDomain, load_config
from src.sample_optimize.advanced.gmid import GmidSampler
from src.sample_optimize.advanced.profiles import make_profile
from test_advanced_sampling import synthetic_lut


PROJECT = Path(__file__).resolve().parents[1]


def opamp2():
    return parse_circuit(PROJECT / "Sample_Optimizer_Circuit/Opamp2/Opamp2.sp")


def test_all_seventeen_parameters_are_used_with_standard_ports():
    circuit = opamp2()
    expected = {f"DESVAR_{kind}{i}" for kind in ("W", "L") for i in range(1, 8)}
    expected |= {"DESVAR_M1", "DESVAR_M2", "IBIAS_A"}
    assert set(circuit.parameter_defaults) == expected
    used = {name for d in circuit.devices for expr in d.parameters.values()
            for name in re.findall(r"[A-Za-z_][A-Za-z_0-9]*", expr.text)}
    assert used == expected
    assert tuple(p.name for p in circuit.ports) == ("VINP", "VINN", "VOUT", "VDD", "VSS")
    assert len(circuit.devices) == 16
    assert sum(d.device_type == DeviceType.NMOS for d in circuit.devices) == 8
    assert sum(d.device_type == DeviceType.PMOS for d in circuit.devices) == 7


def test_tail_mirror_dimensions_multiplicity_bulk_and_reference_current():
    circuit = resolve_circuit(opamp2(), {"DESVAR_W3": 4., "DESVAR_L3": .75,
                                       "DESVAR_M1": 5., "DESVAR_M2": 3., "IBIAS_A": 2e-6})
    devices = {d.name: d for d in circuit.devices}
    for name in ("XNM4", "XNM5"):
        assert devices[name].parameters["W"].value == 4.
        assert devices[name].parameters["L"].value == .75
    assert devices["XNM4"].parameters["M"].value == 6.
    assert devices["XNM5"].parameters["M"].value == 1.
    assert devices["XNM8"].parameters["M"].value == 5.
    assert devices["XNM7"].parameters["M"].value == 1.
    for first, second in (("XNM0", "XNM1"), ("XNM3", "XNM2"),
                           ("XPM3", "XPM0"), ("XPM1", "XPM2")):
        assert devices[first].parameters == devices[second].parameters
        assert devices[first].parameters["M"].value == 3.
    assert devices["XNM0"].pins[1] == "VINP"
    assert devices["XNM1"].pins[1] == "VINN"
    assert all(d.pins[3] == "VSS" for d in circuit.devices if d.device_type == DeviceType.NMOS)
    assert devices["XPM3"].pins[2:] == ("NET19", "NET19")
    assert devices["XPM0"].pins[2:] == ("NET2", "NET2")
    assert devices["IBIAS_SRC"].pins == ("NET6", "VSS")
    assert devices["IBIAS_SRC"].parameters["I"].value == 2e-6


def test_seven_groups_cover_every_mos_and_allow_triode_bias_generator():
    circuit = opamp2()
    groups, signal, _ = make_profile("Opamp2", circuit, load_config()["gmid"])
    assert [g.width for g in groups] == [f"DESVAR_W{i}" for i in range(1, 8)]
    members = [member for g in groups for member in g.members]
    assert len(members) == len(set(members)) == 15
    assert groups[0].reference == "XPM6"
    assert set(groups[2].members) == {"XNM4", "XNM5"}
    assert {"XNM7", "XNM8"}.isdisjoint(signal)
    assert "XNM4" in signal
    sampler = object.__new__(GmidSampler)
    sampler.circuit = circuit
    assert sampler._is_bias_reference(next(d for d in circuit.devices if d.name == "XPM6"))


@pytest.mark.parametrize("conditioned", [True, False])
def test_gmid_generates_candidates_on_the_shared_physical_grid(conditioned):
    circuit = opamp2()
    physical = json.loads((PROJECT / "src/sample_optimize/parameter_ranges.json").read_text())["control_parameter_ranges"]
    names = list(circuit.parameter_defaults)
    bounds = [physical["I"] if name == "IBIAS_A" else physical[name.removeprefix("DESVAR_")[0]]
              for name in names]
    domain = DesignDomain(names, bounds)
    config = load_config()["gmid"]
    config["condition_lengths_on_width"] = conditioned
    groups, _, targets = make_profile("Opamp2", circuit, config)
    metadata = {"length_m": np.linspace(.35e-6, 1e-6, 7),
                "reverse_body_bias_v": np.linspace(0, 1.8, 7),
                "vgs_v": np.linspace(0, 1.8, 91), "vds_v": np.linspace(0, 1.8, 37)}
    length, body, vg, vd = np.meshgrid(*metadata.values(), indexing="ij")
    overdrive = np.maximum(vg-.35-.1*body, 0.)
    beta = 50e-6/length/(1+.4*body)
    current = beta*np.where(vd < overdrive, overdrive*vd-.5*vd**2, .5*overdrive**2)
    gm = beta*np.minimum(overdrive, vd)
    lut = synthetic_lut(metadata, np.stack([current, gm, overdrive], axis=-1), circuit)
    sampler = GmidSampler(circuit, domain, groups, targets, lut,
                           {"VDD": 1.8, "VSS": 0., "VCM": .72}, config)
    rng = np.random.default_rng(42)
    accepted = 0
    for _ in range(100):
        point, info = sampler.propose(rng)
        if point is None:
            continue
        assert info["sizing_mode"] == "nominal_lut"
        assert all(np.isclose(value, axis, atol=1e-12, rtol=1e-12).any()
                   for value, axis in zip(point, domain.axes))
        accepted += 1
        if accepted == 3:
            break
    assert accepted == 3
