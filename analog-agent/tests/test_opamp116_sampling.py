from __future__ import annotations

import re
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest

from src.circuit_ir import parse_circuit, resolve_circuit
from src.sample_optimize.advanced.config import DesignDomain, load_config
from src.sample_optimize.advanced.gmid import GmidSampler
from src.sample_optimize.advanced.lut import MosLUT
from src.sample_optimize.advanced.profiles import make_profile
from test_advanced_sampling import synthetic_lut
from test_sampling_performance import Characterizer, lut_inputs


PROJECT = Path(__file__).resolve().parents[1]
CIRCUIT_NAME = "loOpamp116"


def opamp116():
    return parse_circuit(PROJECT / "Sample_Optimizer_Circuit" / CIRCUIT_NAME / f"{CIRCUIT_NAME}.sp")


def analytic_sampler(*, fixed=False, bias_m=1, conditioned=True):
    circuit = opamp116()
    names = list(circuit.parameter_defaults)
    bounds = []
    for name in names:
        if name == "IBIAS_A":
            bounds.append([5e-6, 5e-6, .5e-6] if fixed else [.5e-6, 5e-6, .5e-6])
        elif name.startswith("DESVAR_L"):
            bounds.append([1., 1., .01] if fixed else [.35, 1., .01])
        elif name.startswith("DESVAR_M"):
            value = bias_m if name == "DESVAR_M1" else 1
            bounds.append([value, value, 1] if fixed else [1, 50, 1])
        else:
            bounds.append([.01, 100., .01] if fixed else [.5, 10., .01])
    domain = DesignDomain(names, bounds)
    config = load_config()["gmid"]
    config["condition_lengths_on_width"] = conditioned
    if fixed:
        config["default_range"] = [10., 10., .5]
    groups, _, targets = make_profile(CIRCUIT_NAME, circuit, config)
    metadata = {"length_m": [0.35e-6, 0.5e-6, 0.7e-6, 1e-6],
                "reverse_body_bias_v": [0., 1.8],
                "vgs_v": np.linspace(0., 1.8, 91),
                "vds_v": np.linspace(0., 1.8, 37)}
    length, body, vg, vd = np.meshgrid(*metadata.values(), indexing="ij")
    overdrive = np.maximum(vg-.35-.1*body, 0.)
    current = 50e-6/length*np.where(vd < overdrive, overdrive*vd-.5*vd**2, .5*overdrive**2)
    gm = 50e-6/length*np.minimum(overdrive, vd)
    lut = synthetic_lut(metadata, np.stack([current, gm, overdrive], axis=-1), circuit)
    return GmidSampler(circuit, domain, groups, targets, lut,
                       {"VDD": 1.8, "VSS": 0., "VCM": .72}, config)


def test_constrained_bindings_preserve_independent_lengths_and_matching():
    circuit = opamp116()
    assert len(circuit.devices) == 16
    expected = {f"DESVAR_{kind}{i}" for kind in ("W", "L") for i in range(1, 9)}
    expected |= {f"DESVAR_M{i}" for i in range(1, 5)} | {"IBIAS_A"}
    assert len(circuit.parameter_defaults) == 21
    assert set(circuit.parameter_defaults) == expected
    used = {name for d in circuit.devices for expr in d.parameters.values()
            for name in re.findall(r"[A-Za-z_][A-Za-z_0-9]*", expr.text)}
    assert used == expected
    resolved = resolve_circuit(circuit, {"DESVAR_L1": 6., "DESVAR_L2": 4.,
                                       "DESVAR_W7": 300., "DESVAR_W3": 120.,
                                       "DESVAR_M1": 2., "DESVAR_M2": 5.,
                                       "DESVAR_M3": 3., "DESVAR_M4": 7.})
    devices = {d.name: d for d in resolved.devices}
    for name in ("XNM0", "XNM6"):
        assert devices[name].parameters["L"].value == 6.
    for name in ("XNM1", "XNM10", "XNM2"):
        assert devices[name].parameters["L"].value == 4.
    for names, multiplicity in ((["XNM0", "XNM10"], 2.),
                                (["XNM1", "XNM6"], 13.),
                                (["XNM2", "XPM0"], 5.),
                                (["XNM3", "XPM3"], 7.),
                                (["XNM8", "XNM9", "XNM7", "XNM5", "XPM1", "XPM4", "XPM2"], 3.)):
        assert all(devices[name].parameters["M"].value == multiplicity for name in names)
    assert devices["XPM0"].parameters["W"].value == 20.
    assert devices["XPM3"].parameters["W"].value == 20.
    for first, second in (("XNM8", "XNM9"), ("XNM5", "XNM7"), ("XPM1", "XPM4")):
        assert devices[first].parameters == devices[second].parameters
    assert devices["XPM1"].parameters["W"].value == 300.
    assert devices["XPM1"].parameters["M"].value == 3.
    assert devices["XNM8"].parameters["W"].value == 120.
    assert devices["XNM8"].parameters["M"].value == 3.
    assert devices["XNM5"].parameters["W"].value == 112.
    for names in (("XNM0", "XNM6"), ("XNM10", "XNM1", "XNM2"), ("XPM0", "XPM3")):
        for key in ("W", "L"):
            assert len({devices[name].parameters[key].value for name in names}) == 1
    assert all(d.pins[3] == "VSS" for d in circuit.devices if d.name.startswith("XNM"))
    assert devices["XPM2"].pins[2:] == ("N8", "N8")
    assert devices["IBIAS_SRC"].pins == ("VDD", "VBIAS")


def test_profile_covers_eight_width_groups_without_duplicate_references():
    groups, signal, _ = make_profile(CIRCUIT_NAME, opamp116(), load_config()["gmid"])
    by_width = {group.width: group for group in groups}
    assert len(groups) == 8
    assert groups[0].reference == "XNM0"
    assert dict(zip(by_width["DESVAR_W1"].members, by_width["DESVAR_W1"].member_lengths)) == {
        "XNM0": "DESVAR_L1", "XNM6": "DESVAR_L1"}
    assert dict(zip(by_width["DESVAR_W2"].members, by_width["DESVAR_W2"].member_lengths)) == {
        "XNM10": "DESVAR_L2", "XNM1": "DESVAR_L2", "XNM2": "DESVAR_L2"}
    assert set(by_width["DESVAR_W3"].members) == {"XNM8", "XNM9"}
    assert set(by_width["DESVAR_W4"].members) == {"XNM3"}
    assert set(by_width["DESVAR_W5"].members) == {"XNM5", "XNM7"}
    assert set(by_width["DESVAR_W6"].members) == {"XPM0", "XPM3"}
    assert set(by_width["DESVAR_W7"].members) == {"XPM1", "XPM4"}
    assert set(by_width["DESVAR_W8"].members) == {"XPM2"}
    assert {g.reference for g in groups}.isdisjoint({"XNM2", "XPM3", "XPM4"})
    members = [name for group in groups for name in group.members]
    assert len(members) == len(set(members)) == 15
    assert {"XNM8", "XNM9", "XNM5", "XNM7", "XPM2"} <= set(signal)
    assert "XPM4" in signal


@pytest.mark.parametrize("mutation", ["none", "extra_channel", "source_bulk", "reversed_source"])
def test_floating_diode_requires_an_isolated_correctly_driven_branch(mutation):
    circuit = opamp116()
    diode = next(d for d in circuit.devices if d.name == "XNM0")
    if mutation == "extra_channel":
        other = next(d for d in circuit.devices if d.name == "XNM2")
        circuit = replace(circuit, devices=circuit.devices + (
            replace(other, name="XEXTRA", pins=("VBIAS", "N1", "VSS", "VSS")),))
    elif mutation == "source_bulk":
        diode = replace(diode, pins=("VBIAS", "VBIAS", "N0", "N0"))
    elif mutation == "reversed_source":
        circuit = replace(circuit, devices=tuple(
            replace(d, pins=tuple(reversed(d.pins))) if d.name == "IBIAS_SRC" else d
            for d in circuit.devices))
    sampler = object.__new__(GmidSampler)
    sampler.circuit = circuit
    assert sampler._is_bias_reference(diode) == (mutation in {"none", "source_bulk"})


@pytest.mark.parametrize("conditioned", [False, True])
def test_opamp116_gmid_proposes_on_the_existing_physical_grid(conditioned):
    sampler = analytic_sampler(conditioned=conditioned)
    rng = np.random.default_rng(42)
    accepted = []
    for _ in range(100):
        point, info = sampler.propose(rng)
        if point is None:
            continue
        assert all(np.isclose(value, axis, atol=1e-12, rtol=1e-12).any()
                   for value, axis in zip(point, sampler.domain.axes))
        assert info["sizing_mode"] == "nominal_lut"
        devices = {d.name: d for d in resolve_circuit(
            sampler.circuit, dict(zip(sampler.domain.names, point))).devices}
        assert devices["XNM0"].parameters["W"] == devices["XNM6"].parameters["W"]
        assert devices["XNM10"].parameters["W"] == devices["XNM1"].parameters["W"] == devices["XNM2"].parameters["W"]
        assert devices["XNM0"].parameters["L"] == devices["XNM6"].parameters["L"]
        assert devices["XNM1"].parameters["L"] == devices["XNM2"].parameters["L"]
        values = dict(zip(sampler.domain.names, point))
        total = 2*values["DESVAR_M3"]+values["DESVAR_M4"]
        assert devices["XNM1"].parameters["M"].value == devices["XNM6"].parameters["M"].value == total
        accepted.append(point)
        if len(accepted) == 3:
            break
    assert len(accepted) == 3


def test_forced_reference_multiplicity_scales_width_not_total_bias():
    one = analytic_sampler(fixed=True, bias_m=1)
    four = analytic_sampler(fixed=True, bias_m=4)
    point_one, _ = one.propose(np.random.default_rng(12))
    point_four, _ = four.propose(np.random.default_rng(12))
    assert point_one is not None and point_four is not None
    bias = one.domain.names.index("IBIAS_A")
    width = one.domain.names.index("DESVAR_W1")
    assert point_one[bias] == point_four[bias] == 5e-6
    assert point_four[width]*4 == pytest.approx(point_one[width], abs=.03)


def test_lut_includes_a_length_used_only_by_a_nonreference_member(tmp_path):
    history, run, args, _ = lut_inputs(tmp_path)
    circuit = opamp116()
    groups, _, _ = make_profile(CIRCUIT_NAME, circuit, load_config()["gmid"])
    first = groups[0]
    # Keep generic cross-length coverage after this circuit's own W1 group
    # changed to shared L1. Only this synthetic fixture gives XNM6 another L.
    circuit = replace(circuit, devices=tuple(
        replace(d, parameters={**d.parameters, "L": replace(d.parameters["L"], text="DESVAR_L2")})
        if d.name == "XNM6" else d
        for d in circuit.devices if d.name in first.members))
    first = replace(first, member_lengths=tuple(
        "DESVAR_L2" if member == "XNM6" else "DESVAR_L1" for member in first.members))
    domain = DesignDomain(["DESVAR_L1", "DESVAR_L2"], [[.2, .4, .2], [1.2, 1.4, .2]])
    context, _, _, config, *tail = args
    context = dict(context, mos_primitives={d.model: "m0" for d in circuit.devices})
    config = dict(config, max_lengths=4)
    oracle = Characterizer()
    with patch("src.sample_optimize.advanced.lut.subprocess.run", oracle):
        table, _ = MosLUT.ensure(tmp_path / "lut", context, domain, [first], config,
                                 *tail, circuit=circuit, workers=2)
    model = circuit.devices[0].model
    assert table.metadata["model_tables"][model]["length_m"] == pytest.approx([.2e-6, .4e-6, 1.2e-6, 1.4e-6])
    assert np.isfinite(table.lookup(model, 1.4, 0., .9, .9)).all()
    assert oracle.calls == 8
