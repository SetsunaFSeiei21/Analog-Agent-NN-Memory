from __future__ import annotations

import re
import subprocess
from pathlib import Path

import numpy as np

from ...circuit_ir.schema import DeviceType
from .context import record_invocation

NUMBER = r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?"


def primitive(device, primitives, instance="xdut"):
    # Original Sky130 and open_pdks use different internal primitive names.
    if device.name.lower().startswith("x"):
        return f"m.{instance}.{device.name.lower()}.{primitives[device.model.lower()]}"
    return f"m.{instance}.{device.name.lower()}"


def run_operating_point(workspace, circuit, condition, constraints, signal_devices,
                        command, timeout, ledger=None):
    workspace = Path(workspace)
    mos = [d for d in circuit.devices if d.device_type in (DeviceType.NMOS, DeviceType.PMOS)]
    nodes = sorted({p.lower() for d in mos for p in d.pins})
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
        for field in ("gm", "id", "vdsat", "gds"):
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
        return {"converged": False, "feasible": False, "reasons": [f"op_execution:{type(exc).__name__}"], "devices": {}}
    log = log_path.read_text(errors="replace") if log_path.exists() else process.stdout
    values = {k.lower(): float(v) for k, v in re.findall(rf"(?m)^\s*(\w+)\s*=\s*({NUMBER})", log)}
    converged = process.returncode == 0 and all(f"n{i}" in values for i in range(len(nodes)))
    if not converged:
        return {"converged": False, "feasible": False, "reasons": ["dc_not_converged"], "devices": {}}
    voltage = {p: values[f"n{i}"] for i, p in enumerate(nodes)}
    error = abs(voltage["vout"] - float(condition["VCM"]))
    reasons = [] if error <= constraints["follower_error_max_v"] else ["follower_error"]
    data = {}
    for i, device in enumerate(mos):
        sign = 1 if device.device_type == DeviceType.NMOS else -1
        vd, vg, vs, vb = (voltage[p.lower()] for p in device.pins)
        fields = {f: values.get(f"d{i}_{f}") for f in ("gm", "id", "vdsat", "gds")}
        current, gm, sat = fields["id"], fields["gm"], fields["vdsat"]
        fields.update({"vds_v": sign * (vd - vs), "vgs_v": sign * (vg - vs),
                       "w_um": device.parameters["W"].value, "l_um": device.parameters["L"].value,
                       "multiplicity": device.parameters["M"].value,
                       "reverse_body_bias_v": sign * (vs - vb),
                       "gmid_v_inv": None if current is None or gm is None or abs(current) <= 1e-30 else abs(gm / current),
                       "saturation_margin_v": None if sat is None else sign * (vd - vs) - abs(sat)})
        data[device.name.upper()] = fields
        if device.name.upper() in signal_devices:
            if current is None or abs(current) < constraints["min_signal_current_a"]:
                reasons.append(f"{device.name}:off_or_missing_current")
            if fields["saturation_margin_v"] is None or fields["saturation_margin_v"] < constraints["saturation_margin_min_v"]:
                reasons.append(f"{device.name}:saturation")
    return {"converged": True, "feasible": not reasons, "reasons": reasons,
            "follower_error_v": error, "vout_v": voltage["vout"], "node_voltages_v": voltage,
            "devices": data}
