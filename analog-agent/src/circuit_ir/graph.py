from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from itertools import combinations

from .resolver import resolve_circuit
from .schema import CircuitIR, GraphNode, PinGraph


def _undirected_clique(indices: list[int]) -> set[tuple[int, int]]:
    edges: set[tuple[int, int]] = set()
    for left, right in combinations(sorted(indices), 2):
        edges.add((left, right))
        edges.add((right, left))
    return edges


def build_pin_graph(circuit: CircuitIR, parameter_values: dict[str, float] | None = None) -> PinGraph:
    resolved = resolve_circuit(circuit, parameter_values)
    ports = {port.name.casefold(): port.ordinal for port in resolved.ports}
    nodes: list[GraphNode] = []
    by_net: dict[str, list[int]] = defaultdict(list)
    by_device: dict[int, list[int]] = defaultdict(list)
    device_parameters = []
    for device_index, device in enumerate(resolved.devices):
        device_parameters.append({name: expression.value for name, expression in device.parameters.items() if expression.value is not None})
        for pin_index, (net, role) in enumerate(zip(device.pins, device.pin_roles)):
            index = len(nodes) + 1
            port_ordinal = ports.get(net.casefold(), -1)
            nodes.append(GraphNode(
                index=index, device_index=device_index, pin_index=pin_index,
                device_type=device.device_type, pin_role=role, net=net,
                is_port=port_ordinal >= 0, port_ordinal=port_ordinal,
            ))
            by_net[net.casefold()].append(index)
            by_device[device_index].append(index)
    physical: set[tuple[int, int]] = set()
    virtual: set[tuple[int, int]] = set()
    for indices in by_net.values():
        physical.update(_undirected_clique(indices))
    for indices in by_device.values():
        virtual.update(_undirected_clique(indices))
    size = len(nodes) + 1
    attention = [[False] * size for _ in range(size)]
    for index in range(size):
        attention[index][index] = True
        attention[0][index] = attention[index][0] = True
    for left, right in physical | virtual:
        attention[left][right] = True
    return PinGraph(
        nodes=tuple(nodes), physical_edges=tuple(sorted(physical)), virtual_edges=tuple(sorted(virtual)),
        local_attention=tuple(tuple(row) for row in attention), device_parameters=tuple(device_parameters),
    )


def circuit_topology_hash(circuit: CircuitIR) -> str:
    """Canonical WL-style hash independent of instance and internal-net spelling."""
    graph = build_pin_graph(circuit)
    labels = {
        node.index: f"{node.device_type.value}:{node.pin_role}:P{node.port_ordinal if node.is_port else '-'}"
        for node in graph.nodes
    }
    neighbors: dict[int, list[tuple[str, int]]] = defaultdict(list)
    for left, right in graph.physical_edges:
        neighbors[left].append(("p", right))
    for left, right in graph.virtual_edges:
        neighbors[left].append(("v", right))
    for _ in range(4):
        labels = {
            index: hashlib.sha256(json.dumps(
                [labels[index], sorted((kind, labels[other]) for kind, other in neighbors[index])],
                separators=(",", ":"),
            ).encode()).hexdigest()
            for index in labels
        }
    payload = {
        "nodes": sorted(labels.values()),
        "physical": len(graph.physical_edges) // 2,
        "virtual": len(graph.virtual_edges) // 2,
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
