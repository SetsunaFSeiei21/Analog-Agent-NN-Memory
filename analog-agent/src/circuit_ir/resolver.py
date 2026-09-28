from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import replace

from .expression import evaluate_expression
from .schema import CircuitIR, DeviceIR, ParameterExpression


def resolve_circuit(circuit: CircuitIR, parameter_values: Mapping[str, float] | None = None) -> CircuitIR:
    values = dict(circuit.parameter_defaults)
    if parameter_values:
        canonical = {name.casefold(): name for name in values}
        for name, value in parameter_values.items():
            key = name.casefold()
            if key not in canonical:
                raise KeyError(f"未知设计参数：{name}")
            values[canonical[key]] = float(value)
    devices: list[DeviceIR] = []
    for device in circuit.devices:
        resolved: dict[str, ParameterExpression] = {}
        for name, expression in device.parameters.items():
            value = evaluate_expression(expression.text, values)
            if not math.isfinite(value) or value <= 0:
                raise ValueError(f"{device.name}.{name} 必须为有限正数，实际为 {value}")
            if name == "M" and not math.isclose(value, round(value), rel_tol=0, abs_tol=1e-9):
                raise ValueError(f"{device.name}.M 必须为整数，实际为 {value}")
            resolved[name] = ParameterExpression(expression.text, float(round(value) if name == "M" else value))
        devices.append(replace(device, parameters=resolved))
    return replace(circuit, devices=tuple(devices), parameter_defaults=values)
