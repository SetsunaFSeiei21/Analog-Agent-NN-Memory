from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Mapping, Tuple


class DeviceType(str, Enum):
    NMOS = "NMOS"
    PMOS = "PMOS"
    RESISTOR = "RESISTOR"
    CAPACITOR = "CAPACITOR"
    CURRENT_SOURCE = "CURRENT_SOURCE"


@dataclass(frozen=True)
class PortIR:
    name: str
    ordinal: int


@dataclass(frozen=True)
class ParameterExpression:
    text: str
    value: float | None = None


@dataclass(frozen=True)
class DeviceIR:
    name: str
    device_type: DeviceType
    pins: Tuple[str, ...]
    pin_roles: Tuple[str, ...]
    model: str | None
    parameters: Mapping[str, ParameterExpression]
    source_line: int


@dataclass(frozen=True)
class CircuitIR:
    name: str
    ports: Tuple[PortIR, ...]
    devices: Tuple[DeviceIR, ...]
    parameter_defaults: Mapping[str, float]
    source_path: Path
    pdk: str = "sky130"


@dataclass(frozen=True)
class GraphNode:
    index: int
    device_index: int
    pin_index: int
    device_type: DeviceType
    pin_role: str
    net: str
    is_port: bool
    port_ordinal: int = -1


@dataclass(frozen=True)
class PinGraph:
    """Pin-level graph. Index 0 is reserved for the graph token."""

    nodes: Tuple[GraphNode, ...]
    physical_edges: Tuple[Tuple[int, int], ...]
    virtual_edges: Tuple[Tuple[int, int], ...]
    local_attention: Tuple[Tuple[bool, ...], ...]
    device_parameters: Tuple[Mapping[str, float], ...] = field(default_factory=tuple)

    @property
    def num_tokens(self) -> int:
        return len(self.nodes) + 1
