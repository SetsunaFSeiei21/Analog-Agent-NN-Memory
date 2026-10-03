from __future__ import annotations

from pathlib import Path

import pytest

from src.circuit_ir import CircuitParseError, build_pin_graph, circuit_topology_hash, parse_circuit


ROOT = Path(__file__).parents[1] / "Sample_Optimizer_Circuit"


@pytest.mark.parametrize(
    ("name", "devices", "pins"),
    [("5t_ota", 7, 26), ("two_stage_opamp_otaf", 11, 38), ("two_stage_folded_opamp", 25, 94)],
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
