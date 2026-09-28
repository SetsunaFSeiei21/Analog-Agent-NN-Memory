from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable

from .expression import ParameterEnvironment, parse_assignments
from .schema import CircuitIR, DeviceIR, DeviceType, ParameterExpression, PortIR


EXPECTED_PORTS = ("VINP", "VINN", "VOUT", "VDD", "VSS")


class CircuitParseError(ValueError):
    pass


def _logical_lines(path: Path) -> list[tuple[int, str]]:
    result: list[tuple[int, str]] = []
    current: tuple[int, str] | None = None
    for number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.split("$", 1)[0].strip()
        if not line or line.startswith("*"):
            continue
        if line.startswith("+"):
            if current is None:
                raise CircuitParseError(f"孤立续行：{path}:{number}")
            current = (current[0], current[1] + " " + line[1:].strip())
        else:
            if current is not None:
                result.append(current)
            current = (number, line)
    if current is not None:
        result.append(current)
    return result


def _tokens(text: str) -> list[str]:
    return re.findall(r"\{[^{}]*\}|\([^()]*\)|[^\s]+", text)


def _parameter_expressions(parameter_path: Path) -> dict[str, str]:
    expressions: dict[str, str] = {}
    for line_no, line in _logical_lines(parameter_path):
        if not line.casefold().startswith(".param"):
            continue
        try:
            pairs = parse_assignments(line[len(".param"):].strip())
        except ValueError as exc:
            raise CircuitParseError(f"{parameter_path}:{line_no}: {exc}") from exc
        for name, value in pairs.items():
            if name.casefold() in {key.casefold() for key in expressions}:
                raise CircuitParseError(f"参数重复定义：{name}")
            expressions[name] = value
    if not expressions:
        raise CircuitParseError(f"参数文件没有 .param：{parameter_path}")
    return expressions


def _named(tokens: Iterable[str]) -> tuple[list[str], dict[str, str]]:
    positional: list[str] = []
    named: dict[str, str] = {}
    for token in tokens:
        if "=" not in token:
            positional.append(token)
            continue
        name, value = token.split("=", 1)
        key = name.upper()
        if key in named:
            raise CircuitParseError(f"器件参数重复：{name}")
        named[key] = value
    return positional, named


def _mos(line_no: int, tokens: list[str]) -> DeviceIR:
    positional, named = _named(tokens[1:])
    if len(positional) != 5:
        raise CircuitParseError(f"第 {line_no} 行 MOS 必须是四个引脚加一个 Sky130 模型")
    pins, model = tuple(positional[:4]), positional[4]
    if not model.casefold().startswith("sky130_fd_pr__"):
        raise CircuitParseError(f"第 {line_no} 行只允许 Sky130 primitive：{model}")
    lowered = model.casefold()
    if "nfet" in lowered:
        kind = DeviceType.NMOS
    elif "pfet" in lowered:
        kind = DeviceType.PMOS
    else:
        raise CircuitParseError(f"第 {line_no} 行无法识别 MOS 极性：{model}")
    unknown = set(named) - {"W", "L", "M"}
    if unknown or "W" not in named or "L" not in named:
        raise CircuitParseError(f"第 {line_no} 行 MOS 只允许 W/L/M，且 W/L 必填：{sorted(unknown)}")
    named.setdefault("M", "1")
    return DeviceIR(
        name=tokens[0], device_type=kind, pins=pins, pin_roles=("D", "G", "S", "B"),
        model=model, parameters={k: ParameterExpression(v) for k, v in named.items()}, source_line=line_no,
    )


def _two_terminal(line_no: int, tokens: list[str], kind: DeviceType, parameter: str) -> DeviceIR:
    if len(tokens) != 4:
        raise CircuitParseError(f"第 {line_no} 行 {kind.value} 必须有两个引脚和一个值")
    return DeviceIR(
        name=tokens[0], device_type=kind, pins=(tokens[1], tokens[2]), pin_roles=("P", "N"),
        model=None, parameters={parameter: ParameterExpression(tokens[3])}, source_line=line_no,
    )


def _current(line_no: int, tokens: list[str]) -> DeviceIR:
    if len(tokens) == 5 and tokens[3].casefold() == "dc":
        value = tokens[4]
    elif len(tokens) == 4:
        value = tokens[3]
    else:
        raise CircuitParseError(f"第 {line_no} 行电流源仅支持 I P N [DC] value")
    return DeviceIR(
        name=tokens[0], device_type=DeviceType.CURRENT_SOURCE,
        pins=(tokens[1], tokens[2]), pin_roles=("P", "N"), model=None,
        parameters={"I": ParameterExpression(value)}, source_line=line_no,
    )


def parse_circuit(
    circuit_path: Path | str,
    parameter_path: Path | str | None = None,
    *,
    pdk: str = "sky130",
    circuit_type: str = "single_ended_opamp",
) -> CircuitIR:
    circuit_path = Path(circuit_path)
    parameter_path = Path(parameter_path) if parameter_path else circuit_path.with_name(circuit_path.stem + "_params.sp")
    if pdk.casefold() != "sky130":
        raise CircuitParseError("ZeroSim v1 只支持 Sky130")
    if circuit_type != "single_ended_opamp":
        raise CircuitParseError("ZeroSim v1 只支持 single_ended_opamp")
    expressions = _parameter_expressions(parameter_path)
    defaults = ParameterEnvironment(expressions).resolve()
    devices: list[DeviceIR] = []
    in_dut = False
    seen_dut = False
    ports: tuple[str, ...] = ()
    for line_no, line in _logical_lines(circuit_path):
        tokens = _tokens(line)
        head = tokens[0].casefold()
        if head == ".subckt":
            if in_dut or seen_dut:
                raise CircuitParseError("ZeroSim v1 不允许用户子电路")
            if len(tokens) < 2 or tokens[1].casefold() != "dut":
                raise CircuitParseError("顶层子电路必须命名为 DUT")
            ports = tuple(token.upper() for token in tokens[2:])
            if ports != EXPECTED_PORTS:
                raise CircuitParseError(f"DUT 端口必须严格为 {EXPECTED_PORTS}，实际为 {ports}")
            in_dut, seen_dut = True, True
            continue
        if head == ".ends":
            if in_dut:
                in_dut = False
            continue
        if not in_dut:
            continue
        if head.startswith("."):
            raise CircuitParseError(f"DUT 内不允许指令：{line}")
        prefix = tokens[0][0].upper()
        if prefix in {"M", "X"}:
            devices.append(_mos(line_no, tokens))
        elif prefix == "R":
            devices.append(_two_terminal(line_no, tokens, DeviceType.RESISTOR, "R"))
        elif prefix == "C":
            devices.append(_two_terminal(line_no, tokens, DeviceType.CAPACITOR, "C"))
        elif prefix == "I":
            devices.append(_current(line_no, tokens))
        else:
            raise CircuitParseError(f"第 {line_no} 行是不允许的器件或用户子电路：{tokens[0]}")
    if in_dut or not seen_dut:
        raise CircuitParseError("缺少完整的 .subckt DUT/.ends")
    if not devices:
        raise CircuitParseError("DUT 中没有器件")
    folded = [device.name.casefold() for device in devices]
    if len(folded) != len(set(folded)):
        raise CircuitParseError("器件名忽略大小写后重复")
    return CircuitIR(
        name=circuit_path.stem,
        ports=tuple(PortIR(name, index) for index, name in enumerate(ports)),
        devices=tuple(devices), parameter_defaults=defaults, source_path=circuit_path.resolve(),
    )
