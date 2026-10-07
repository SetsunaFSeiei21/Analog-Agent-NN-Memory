from __future__ import annotations

import re
import subprocess
from pathlib import Path

import numpy as np

from ...circuit_ir.schema import DeviceType
from ...circuit_ir import resolve_circuit
from ..operating_point_contract import NATIVE_FIELDS, OP_SCHEMA_VERSION
from .context import record_invocation

NUMBER = r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?"


def primitive(device, primitives, instance="xdut"):
    # Original Sky130 and open_pdks use different internal primitive names.
    if device.name.lower().startswith("x"):
        return f"m.{instance}.{device.name.lower()}.{primitives[device.model.lower()]}"
    return f"m.{instance}.{device.name.lower()}"


def empty_observation(circuit, condition, reason):
    """Retain every MOS and its resolved sizing even when OP cannot run."""
    devices = {}
    if circuit is not None and any(expression.value is None for device in circuit.devices for expression in device.parameters.values()):
        circuit = resolve_circuit(circuit)
    for device in (() if circuit is None else circuit.devices):
        if device.device_type not in (DeviceType.NMOS, DeviceType.PMOS):
            continue
        devices[device.name.upper()] = {
            "device_type": device.device_type.value, "model_name": device.model,
            "w_um": device.parameters["W"].value, "l_um": device.parameters["L"].value,
            "multiplicity": device.parameters["M"].value,
        }
    return {"schema_version": OP_SCHEMA_VERSION, "status": "failed", "converged": False,
            "feasible": False, "reasons": [reason], "missing_fields": {},
            "condition": {key: value for key, value in condition.items() if key != "MOS_PRIMITIVES"},
            "bias_topology": "unity_gain_follower", "devices": devices, "node_voltages_v": {}}


def run_operating_point(workspace, circuit, condition, constraints, signal_devices,
                        command, timeout, ledger=None):
    workspace = Path(workspace)
    observation = empty_observation(circuit, condition, "dc_not_converged")
    mos = [d for d in circuit.devices if d.device_type in (DeviceType.NMOS, DeviceType.PMOS)]
    nodes = sorted({p.lower() for d in mos for p in d.pins} | {"vinp", "vinn", "vout", "vdd", "vss"})
    # VINN follows VOUT, exactly as the reference unity follower used for power.
    def node(p):
        p = p.lower()
        if p in {"vinn", "vout"}:
            return "out"
        if p == "vinp":
            return "inp"
        return p if p in {"vdd", "vss", "0"} else "xdut." + p
    statements = [f"let n{i} = v({node(p)})\nprint n{i}" for i, p in enumerate(nodes)]
    for i, device in enumerate(mos):
        for field in NATIVE_FIELDS:
            statements.append(f"let d{i}_{field} = @{primitive(device, condition['MOS_PRIMITIVES'])}[{field}]\nprint d{i}_{field}")
    deck = f'''* Dataset feasibility operating point
.lib "{condition['PDK_PATH']}" {condition['CORNER']}
.include "{circuit.source_path.name}"
.temp {condition['TEMP']}
VDD_SRC vdd 0 {condition['VDD']}
VSS_SRC vss 0 {condition['VSS']}
VINP_SRC inp 0 {condition['VCM']}
XDUT inp out out vdd vss DUT
.control
option numdgt=15
op
{chr(10).join(statements)}
quit
.endc
.end
'''
    (workspace / "tb_operating_point.cir").write_text(deck)
    log_path = workspace / "operating_point.log"
    log_path.unlink(missing_ok=True)
    def launch():
        return subprocess.run([command, "-b", "-o", log_path.name, "tb_operating_point.cir"],
                              cwd=workspace, capture_output=True, text=True, timeout=timeout)
    try:
        process = launch() if ledger is None else record_invocation(*ledger, "design", "operating_point", launch)
    except (subprocess.TimeoutExpired, OSError) as exc:
        observation["reasons"] = [f"op_execution:{type(exc).__name__}"]
        return observation
    log = log_path.read_text(errors="replace") if log_path.exists() else process.stdout
    values = {k.lower(): float(v) for k, v in re.findall(rf"(?m)^\s*(\w+)\s*=\s*({NUMBER})[ \t]*$", log or "")
              if np.isfinite(float(v))}
    converged = process.returncode == 0 and all(f"n{i}" in values for i in range(len(nodes)))
    if not converged:
        return observation
    voltage = {p: values[f"n{i}"] for i, p in enumerate(nodes)}
    error = abs(voltage["vout"] - float(condition["VCM"]))
    reasons = [] if error <= constraints.get("follower_error_max_v", 0.05) else ["follower_error"]
    data = {}
    missing = {}
    for i, device in enumerate(mos):
        sign = 1 if device.device_type == DeviceType.NMOS else -1
        vd, vg, vs, vb = (voltage[p.lower()] for p in device.pins)
        fields = {f: values.get(f"d{i}_{f}") for f in NATIVE_FIELDS if f not in {"vgs", "vds", "vbs"}}
        for field in ("vgs", "vds", "vbs"):
            fields[f"model_{field}_v"] = values.get(f"d{i}_{field}")
        current, gm, sat = fields["id"], fields["gm"], fields["vdsat"]
        fields.update({**observation["devices"][device.name.upper()],
                       "primitive_path": primitive(device, condition["MOS_PRIMITIVES"]),
                       "vd_v": vd, "vg_v": vg, "vs_v": vs, "vb_v": vb,
                       "vds_raw_v": vd - vs, "vgs_raw_v": vg - vs, "vbs_raw_v": vb - vs,
                       "vds_v": sign * (vd - vs), "vgs_v": sign * (vg - vs),
                       "vbs_normalized_v": sign * (vb - vs),
                       "reverse_body_bias_v": sign * (vs - vb),
                       "gmid_v_inv": None if current is None or gm is None or abs(current) <= 1e-30 else abs(gm / current),
                       "intrinsic_gain_v_v": None if gm is None or fields["gds"] is None or abs(fields["gds"]) <= 1e-30 else abs(gm / fields["gds"]),
                       "saturation_margin_v": None if sat is None else sign * (vd - vs) - abs(sat)})
        data[device.name.upper()] = fields
        unavailable = [f for f in NATIVE_FIELDS if f"d{i}_{f}" not in values]
        if unavailable:
            missing[device.name.upper()] = unavailable
        if device.name.upper() in signal_devices:
            if current is None or abs(current) < constraints.get("min_signal_current_a", 1e-12):
                reasons.append(f"{device.name}:off_or_missing_current")
            if fields["saturation_margin_v"] is None or fields["saturation_margin_v"] < constraints.get("saturation_margin_min_v", 0.0):
                reasons.append(f"{device.name}:saturation")
    return {**observation, "status": "partial" if missing else "complete",
            "converged": True, "feasible": not reasons, "reasons": reasons, "missing_fields": missing,
            "follower_error_v": error, "vout_v": voltage["vout"], "node_voltages_v": voltage,
            "devices": data}
