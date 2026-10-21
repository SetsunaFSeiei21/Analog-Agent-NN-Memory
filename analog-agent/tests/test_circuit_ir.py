from __future__ import annotations

from pathlib import Path

import pytest

from src.circuit_ir import CircuitParseError, build_pin_graph, circuit_topology_hash, parse_circuit


ROOT = Path(__file__).parents[1] / "Sample_Optimizer_Circuit"


@pytest.mark.parametrize(
    ("name", "devices", "pins"),
    [("5t_ota", 7, 26), ("two_stage_opamp_otaf", 11, 38), ("two_stage_folded_opamp", 25, 94),
     ("Opamp0", 18, 70)],
)
def test_reference_circuits_parse_to_pin_graph(name: str, devices: int, pins: int) -> None:
    circuit = parse_circuit(ROOT / name / f"{name}.sp")
    graph = build_pin_graph(circuit)
    assert len(circuit.devices) == devices
    assert len(graph.nodes) == pins
    assert graph.num_tokens == pins + 1
    assert len(graph.local_attention) == pins + 1
    assert all(graph.local_attention[0])


def test_resolved_device_parameters_follow_design_override() -> None:
    circuit = parse_circuit(ROOT / "5t_ota" / "5t_ota.sp")
    graph = build_pin_graph(circuit, {"WIN": 33.0, "M_FACTOR": 3})
    input_devices = [
        graph.device_parameters[index]
        for index, device in enumerate(circuit.devices)
        if device.name in {"XMN_INP", "XMN_INN"}
    ]
    assert all(params["W"] == 33.0 and params["M"] == 3 for params in input_devices)


def test_opamp0_shared_sizing_and_multiplicity_expressions() -> None:
    circuit = parse_circuit(ROOT / "Opamp0" / "Opamp0.sp")
    assert len(circuit.parameter_defaults) == 18
    design = {"DESVAR_W3": 6.0, "DESVAR_L3": 0.6,
              "DESVAR_W1": 8.0, "DESVAR_L1": 0.8,
              "DESVAR_M0": 3, "DESVAR_M1": 4, "DESVAR_M2": 5}
    graph = build_pin_graph(circuit, design)
    parameters = {d.name: graph.device_parameters[i] for i, d in enumerate(circuit.devices)}
    for device, group in [("XNM6", 3), ("XNM5", 3), ("XPM6", 1), ("XPM7", 1), ("XPM8", 1), ("XPM9", 1)]:
        assert parameters[device]["W"] == design[f"DESVAR_W{group}"]
        assert parameters[device]["L"] == design[f"DESVAR_L{group}"]
    assert parameters["XNM5"]["M"] == 3
    assert parameters["XPM6"]["M"] == 8
    for members, multiple in [(("XPM4", "XPM5"), 4), (("XPM2", "XPM3"), 5),
                              (("XPM0", "XPM1"), 5), (("XNM2", "XNM3"), 9), (("XNM0", "XNM1"), 5)]:
        assert all(parameters[d]["M"] == multiple for d in members)
        assert all(parameters[d] == parameters[members[0]] for d in members)
    for bias_device in ("XPM7", "XPM8", "XPM9", "XNM4", "XNM6"):
        assert parameters[bias_device]["M"] == 1
    for device in circuit.devices:
        if device.model:
            assert device.model.endswith("_01v8_lvt")
            if device.name.startswith("XPM"):
                assert device.pins[3] == device.pins[2]
            else:
                assert device.pins[3] == "VSS"


def test_topology_hash_ignores_instance_and_internal_net_names(tmp_path: Path) -> None:
    source_dir = ROOT / "5t_ota"
    original = (source_dir / "5t_ota.sp").read_text(encoding="utf-8")
    renamed = original.replace("N_BIAS", "BIAS_RENAMED").replace("NTAIL", "TAIL_RENAMED")
    renamed = renamed.replace("XMN_INP", "X123").replace("XMN_INN", "X456")
    circuit_path = tmp_path / "renamed.sp"
    circuit_path.write_text(renamed, encoding="utf-8")
    params_path = tmp_path / "renamed_params.sp"
    params_path.write_text((source_dir / "5t_ota_params.sp").read_text(encoding="utf-8"), encoding="utf-8")
    assert circuit_topology_hash(parse_circuit(source_dir / "5t_ota.sp")) == circuit_topology_hash(
        parse_circuit(circuit_path, params_path)
    )


def test_user_subcircuit_is_rejected(tmp_path: Path) -> None:
    params = tmp_path / "bad_params.sp"
    params.write_text(".param W=1 L=0.5\n", encoding="utf-8")
    netlist = tmp_path / "bad.sp"
    netlist.write_text(
        ".subckt CHILD A B\nR1 A B 1k\n.ends CHILD\n"
        ".subckt DUT VINP VINN VOUT VDD VSS\nXU1 VINP VOUT CHILD\n.ends DUT\n",
        encoding="utf-8",
    )
    with pytest.raises(CircuitParseError, match="子电路|DUT"):
        parse_circuit(netlist, params)
