"""Generic body-bias sizing checks against an independent analytic MOS LUT.

No PDK or SPICE process is used here. Both polarities have body-dependent
threshold AND mobility, so silently querying body=0 changes the sized width.
"""
from dataclasses import replace
from unittest.mock import patch

import numpy as np
import pytest

from src.circuit_ir import parse_circuit
from src.circuit_ir.schema import DeviceType
from src.sample_optimize.advanced.config import DesignDomain, load_config
from src.sample_optimize.advanced.gmid import GmidSampler
from src.sample_optimize.advanced.lut import MosLUT
from src.sample_optimize.advanced.profiles import Group, NODE_SEEDS, SIGNAL


def make_sampler(tmp_path, monkeypatch, *, pmos=False, vss=0., mode="nominal_lut",
                 conditioned=True, body="rail", multiplicity=1, extra=False,
                 reference_first=True, shared_length=False):
    name = "arbitrary_body_fixture"
    model = "sky130_fd_pr__pfet_01v8_lvt" if pmos else "sky130_fd_pr__nfet_01v8_lvt"
    rail, opposite = ("VDD", "VSS") if pmos else ("VSS", "VDD")
    bulk = {"rail": rail, "source": "SRC", "forward": opposite, "ground": "0"}[body]
    feed = "BIAS VSS" if pmos else "VDD BIAS"
    load_length = "LREF" if shared_length else "LLOAD"
    path = tmp_path / f"{name}.sp"
    path.write_text(f"""* Arbitrary topology; do not depend on a registered opamp name.
.subckt DUT VINP VINN VOUT VDD VSS
IREF {feed} DC {{IBIAS_A}}
MREF BIAS BIAS SRC {bulk} {model} W={{WREF}} L={{LREF}} m={{MREF}}
RSOURCE SRC {rail} {{R_SOURCE}}
RLOAD VOUT {opposite if extra else 'VINP'} {{R_LOAD}}
""" + (f"MLOAD VOUT VINP {rail} {rail} {model} W={{WLOAD}} L={{{load_length}}} m=1\n"
        if extra else "") + ".ends DUT\n")
    (tmp_path / f"{name}_params.sp").write_text(f""".param WREF=1 LREF=.7 MREF={multiplicity}
.param IBIAS_A=1e-6 R_SOURCE=300000 R_LOAD=300000
""" + (".param WLOAD=1\n" if extra else "") +
        (".param LLOAD=.7\n" if extra and not shared_length else ""))
    circuit = parse_circuit(path)
    bounds = {"WREF": [.01, 100., .01], "LREF": [.7, .7, .1],
              "MREF": [multiplicity, multiplicity, 1], "IBIAS_A": [1e-6, 1e-6, 1e-6],
              "R_SOURCE": [300000, 300000, 1], "R_LOAD": [300000, 300000, 1],
              "WLOAD": [.01, 100., .01], "LLOAD": [.4, 1., .3]}
    names = list(circuit.parameter_defaults)
    domain = DesignDomain(names, [bounds[n] for n in names])
    groups = [Group("WREF", "LREF", "MREF", ("MREF",))]
    if extra:
        groups.append(Group("WLOAD", load_length, "MLOAD", ("MLOAD",)))
    if not reference_first:
        groups.reverse()
    targets = {"WREF": np.array([10.]), "WLOAD": np.array([10./3.])}
    metadata = {"model_tables": {model: {"length_m": [.4e-6, .7e-6, 1e-6]}},
                "reverse_body_bias_v": [0., .1, .3, .6, 1.2, 1.8],
                "vgs_v": np.linspace(0, 1.8, 181), "vds_v": np.linspace(0, 1.8, 37)}
    length, reverse, vg, vd = np.meshgrid(metadata["model_tables"][model]["length_m"],
                                         metadata["reverse_body_bias_v"],
                                         metadata["vgs_v"], metadata["vds_v"], indexing="ij")
    threshold = .3 + .25*(np.sqrt(.7+reverse)-np.sqrt(.7))
    overdrive = np.maximum(vg-threshold, 0.)
    beta = 50e-6/length/(1.+.4*reverse)
    current = beta*np.where(vd < overdrive, overdrive*vd-.5*vd**2, .5*overdrive**2)
    gm = beta*np.minimum(overdrive, vd)
    lut = MosLUT(metadata, {model: np.stack([current, gm, overdrive], axis=-1)})
    config = load_config()["gmid"]
    config.update(sizing_mode=mode, condition_lengths_on_width=conditioned,
                  max_solver_evaluations=200, solver_tolerance=1e-5)
    # The seed happens to be close to the analytic OP. Production seeds remain
    # estimates, and the coupled test checks KCL independently of those seeds.
    source = 1.5 if pmos else .3
    bias = source + (-1 if pmos else 1)*(.3+.25*(np.sqrt(1.)-np.sqrt(.7))+.2)
    monkeypatch.setitem(NODE_SEEDS, name, {"SRC": source, "BIAS": bias})
    monkeypatch.setitem(SIGNAL, name, [])
    return GmidSampler(circuit, domain, tuple(groups), targets, lut,
                       {"VDD": vss+1.8, "VSS": vss, "VCM": vss+.9}, config)


@pytest.mark.parametrize("pmos", [False, True])
@pytest.mark.parametrize("mode", ["nominal_lut", "coupled_lut"])
@pytest.mark.parametrize("conditioned", [False, True])
@pytest.mark.parametrize("vss", [0., -.4, .4])
def test_floating_source_rail_bulk_uses_actual_body_polarity(
        tmp_path, monkeypatch, pmos, mode, conditioned, vss):
    sampler = make_sampler(tmp_path, monkeypatch, pmos=pmos, vss=vss,
                           mode=mode, conditioned=conditioned)
    assert sampler._is_bias_reference(sampler.mos[0])
    with patch.object(sampler.lut, "lookup", wraps=sampler.lut.lookup) as lookup:
        point, info = sampler.propose(np.random.default_rng(12))
    assert point is not None, info
    assert all(np.isclose(value, axis).any() for value, axis in zip(point, sampler.domain.axes))
    # The first query already uses the nonzero reverse bias, including PMOS.
    assert lookup.call_args_list[0].args[2] == pytest.approx(.3)
    assert info["sizing_mode"] == mode
    if mode == "coupled_lut":
        source = info["lut_predicted_nodes_v"]["SRC"]
        assert source == pytest.approx(vss+(1.5 if pmos else .3), abs=2e-5)
        assert info["lut_solver_error"] < 1e-5
    # An independent saturation equation predicts W ~ 0.784 um at body=.3V.
    assert point[sampler.domain.names.index("WREF")] == pytest.approx(.784, abs=.02)


@pytest.mark.parametrize("pmos", [False, True])
@pytest.mark.parametrize("mode", ["nominal_lut", "coupled_lut"])
def test_reverse_body_changes_width_and_multiplicity_preserves_total_current(
        tmp_path, monkeypatch, pmos, mode):
    points = []
    for body, multiplicity in [("source", 1), ("rail", 1), ("rail", 4)]:
        sampler = make_sampler(tmp_path, monkeypatch, pmos=pmos, mode=mode,
                               body=body, multiplicity=multiplicity)
        point, info = sampler.propose(np.random.default_rng(12))
        assert point is not None, info
        assert point[sampler.domain.names.index("IBIAS_A")] == 1e-6
        points.append(point[sampler.domain.names.index("WREF")])
    assert points[1] > points[0]*1.08  # Body-dependent mobility, not just a Vt shift.
    assert points[2]*4 == pytest.approx(points[1], abs=.03)


@pytest.mark.parametrize("pmos", [False, True])
@pytest.mark.parametrize("shared_length", [False, True])
def test_conditioning_finds_reference_after_a_nonreference_group(
        tmp_path, monkeypatch, pmos, shared_length):
    sampler = make_sampler(tmp_path, monkeypatch, pmos=pmos, extra=True,
                           reference_first=False, shared_length=shared_length)
    assert not sampler._is_bias_reference(sampler.mos[1])
    assert sampler.groups[1].reference == "MREF"
    with patch.object(sampler.lut, "lookup", wraps=sampler.lut.lookup) as lookup:
        point, info = sampler.propose(np.random.default_rng(3))
    assert point is not None, info
    length_queries = [call for call in lookup.call_args_list if np.ndim(call.args[1]) == 2]
    assert length_queries
    if shared_length:
        assert point[sampler.domain.names.index("LREF")] == .7


@pytest.mark.parametrize("pmos", [False, True])
@pytest.mark.parametrize("body", ["forward", "ground"])
def test_unsupported_body_is_rejected_instead_of_clipped(tmp_path, monkeypatch, pmos, body):
    # Ground differs from VSS here. Choose its offset so the body junction is
    # forward biased for either device polarity, despite all nodes being valid.
    vss = -1. if not pmos else 1.
    sampler = make_sampler(tmp_path, monkeypatch, pmos=pmos, body=body, vss=vss)
    point, info = sampler.propose(np.random.default_rng(12))
    assert point is None
    assert info["rejection"] == "lut_out_of_domain"


@pytest.mark.parametrize("pmos", [False, True])
def test_absolute_ground_bulk_differs_from_the_vss_terminal(tmp_path, monkeypatch, pmos):
    # Keep the junction reverse biased, with body different from the rail case.
    sampler = make_sampler(tmp_path, monkeypatch, pmos=pmos, body="ground",
                           vss=-1.6 if pmos else .4)
    with patch.object(sampler.lut, "lookup", wraps=sampler.lut.lookup) as lookup:
        point, info = sampler.propose(np.random.default_rng(12))
    assert point is not None, info
    assert lookup.call_args_list[0].args[2] == pytest.approx(.1 if pmos else .7)


@pytest.mark.parametrize("pmos", [False, True])
def test_length_conditioning_queries_nonzero_body(tmp_path, monkeypatch, pmos):
    sampler = make_sampler(tmp_path, monkeypatch, pmos=pmos, extra=True, reference_first=False)
    sampler.circuit = replace(sampler.circuit, devices=tuple(
        replace(d, pins=(d.pins[0], d.pins[1], "SRC", d.pins[3])) if d.name == "MLOAD" else d
        for d in sampler.circuit.devices))
    sampler.mos = [d for d in sampler.circuit.devices if d.device_type in (DeviceType.NMOS, DeviceType.PMOS)]
    sampler.targets["WLOAD"] = np.array([7.5])
    with patch.object(sampler.lut, "lookup", wraps=sampler.lut.lookup) as lookup:
        point, info = sampler.propose(np.random.default_rng(3))
    assert point is not None, info
    length_queries = [call for call in lookup.call_args_list if np.ndim(call.args[1]) == 2]
    assert len(length_queries) == 1
    assert length_queries[0].args[2] == pytest.approx(.3)


@pytest.mark.parametrize("pmos", [False, True])
def test_coupled_solver_does_not_clip_a_forward_body_after_drain_source_reversal(
        tmp_path, monkeypatch, pmos):
    from src.sample_optimize.advanced import gmid
    sampler = make_sampler(tmp_path, monkeypatch, pmos=pmos, body="source", mode="coupled_lut")
    solve = gmid.least_squares

    def inspect_residual(fun, initial, **kwargs):
        reversed_bias = initial.copy()
        reversed_bias[sampler.nets.index("SRC")] = 1.5 if pmos else .3
        reversed_bias[sampler.nets.index("BIAS")] = 1.6 if pmos else .2
        # The effective source is now the original drain. Its body junction is
        # forward biased; evaluating a zero-body slice would hide that fact.
        assert np.all(fun(reversed_bias) == 1e6)
        return solve(fun, initial, **kwargs)

    with patch.object(gmid, "least_squares", inspect_residual):
        point, info = sampler.propose(np.random.default_rng(12))
    assert point is not None, info


@pytest.mark.parametrize("pmos", [False, True])
def test_current_grid_intersects_every_forced_reference(tmp_path, monkeypatch, pmos):
    sampler = make_sampler(tmp_path, monkeypatch, pmos=pmos, extra=True, reference_first=False)
    circuit = sampler.circuit
    diode, feed = sampler.mos[0], circuit.devices[0]
    second = replace(diode, name="MREF2", pins=("BIAS2", "BIAS2", "SRC", diode.pins[3]),
                     parameters={**diode.parameters, "W": replace(diode.parameters["W"], text="WREF2")})
    feed = replace(feed, name="IREF2", pins=tuple("BIAS2" if p == "BIAS" else p for p in feed.pins))
    circuit = replace(circuit, devices=circuit.devices+(second, feed),
                      parameter_defaults={**circuit.parameter_defaults, "WREF2": .05})
    # A second forced branch cannot carry 1uA within this narrow W range.
    domain = DesignDomain([*sampler.domain.names, "WREF2"],
                          [*sampler.domain.bounds.tolist(), [.01, .1, .01]])
    groups = (*sampler.groups, Group("WREF2", "LREF", "MREF2", ("MREF2",)))
    sampler = GmidSampler(circuit, domain, groups, {**sampler.targets, "WREF2": np.array([10.])},
                           sampler.lut, sampler.condition, sampler.config)
    point, info = sampler.propose(np.random.default_rng(3))
    assert point is None and info["rejection"] == "no_bias_grid_for_lut_sizing"


@pytest.mark.parametrize("pmos", [False, True])
def test_curve_caches_separate_body_and_diode_bias(tmp_path, monkeypatch, pmos):
    sampler = make_sampler(tmp_path, monkeypatch, pmos=pmos)
    model = sampler.mos[0].model
    with patch.object(sampler.lut, "lookup", wraps=sampler.lut.lookup) as lookup:
        a, _ = sampler._initial_curve(model, .7, True, 1.8, 0.)
        b, _ = sampler._initial_curve(model, .7, True, 1.8, .3)
        c, _ = sampler._initial_curve(model, .7, False, 1.8, .3)
        assert sampler._initial_curve(model, .7, True, 1.8, .3)[0] is b
        assert lookup.call_count == 3
        assert not np.array_equal(a, b) and not np.array_equal(b, c)
        table, _ = sampler._length_table(model, "LREF", 1.8, .3, True)
        assert sampler._length_table(model, "LREF", 1.8, .3, True)[0] is table
        sampler._length_table(model, "LREF", 1.8, 0., True)
        sampler._length_table(model, "LREF", 1.8, .3, False)
        assert lookup.call_count == 6


@pytest.mark.parametrize("pmos", [False, True])
@pytest.mark.parametrize("mutation,expected", [
    ("none", True), ("gate", True), ("capacitor", True),
    ("channel", False), ("resistor", False), ("second_feed", False),
    ("reversed_feed", False), ("not_diode", False)])
def test_forced_current_recognition_depends_on_dc_paths_not_bulk(
        tmp_path, monkeypatch, pmos, mutation, expected):
    sampler = make_sampler(tmp_path, monkeypatch, pmos=pmos)
    circuit, diode = sampler.circuit, sampler.mos[0]
    extra = None
    if mutation == "gate":
        extra = replace(diode, name="EXTRA", pins=("VDD", "BIAS", "VSS", "VSS"))
    elif mutation == "capacitor":
        extra = replace(circuit.devices[2], name="EXTRA", device_type=DeviceType.CAPACITOR,
                        pins=("BIAS", "VSS"))
    elif mutation == "channel":
        extra = replace(diode, name="EXTRA", pins=("BIAS", "VINP", "VSS", "VSS"))
    elif mutation == "resistor":
        extra = replace(circuit.devices[2], name="EXTRA", pins=("BIAS", "VSS"))
    elif mutation == "second_feed":
        extra = replace(circuit.devices[0], name="EXTRA")
    elif mutation == "reversed_feed":
        circuit = replace(circuit, devices=tuple(
            replace(d, pins=tuple(reversed(d.pins))) if d.name == "IREF" else d
            for d in circuit.devices))
    elif mutation == "not_diode":
        diode = replace(diode, pins=("BIAS", "VINP", "SRC", "VSS"))
    if extra is not None:
        circuit = replace(circuit, devices=circuit.devices+(extra,))
    sampler.circuit = circuit
    assert sampler._is_bias_reference(diode) is expected
