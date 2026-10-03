from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

import numpy as np
import torch
from torch.utils.data import Dataset

from ...circuit_ir import CircuitIR, build_pin_graph, parse_circuit, resolve_circuit
from ...circuit_ir.schema import DeviceType
from ..contracts import SampleRecord
from .manifest import TopologyEntry
from .transforms import DEVICE_PARAMETER_ORDER, TargetScaler, transform_device_parameters


DEVICE_TYPE_ID = {device_type: index + 1 for index, device_type in enumerate(DeviceType)}
PIN_ROLE_ID = {name: index + 1 for index, name in enumerate(("D", "G", "S", "B", "P", "N"))}


@dataclass(frozen=True)
class CompiledTopology:
    topology_id: str
    circuit: CircuitIR
    device_type: np.ndarray
    pin_role: np.ndarray
    port_role: np.ndarray
    device_index: np.ndarray
    local_attention: np.ndarray
    device_types: np.ndarray

    @classmethod
    def from_entry(cls, entry: TopologyEntry) -> "CompiledTopology":
        circuit = parse_circuit(entry.circuit_path, entry.parameter_path)
        graph = build_pin_graph(circuit)
        token_count = graph.num_tokens
        device_type = np.zeros(token_count, dtype=np.int64)
        pin_role = np.zeros(token_count, dtype=np.int64)
        port_role = np.zeros(token_count, dtype=np.int64)
        device_index = np.full(token_count, -1, dtype=np.int64)
        for node in graph.nodes:
            device_type[node.index] = DEVICE_TYPE_ID[node.device_type]
            pin_role[node.index] = PIN_ROLE_ID[node.pin_role]
            port_role[node.index] = node.port_ordinal + 1 if node.is_port else 0
            device_index[node.index] = node.device_index
        return cls(
            topology_id=entry.topology_id,
            circuit=circuit,
            device_type=device_type,
            pin_role=pin_role,
            port_role=port_role,
            device_index=device_index,
            local_attention=np.asarray(graph.local_attention, dtype=bool),
            device_types=np.asarray([DEVICE_TYPE_ID[d.device_type] for d in circuit.devices], dtype=np.int64),
        )

    def parameters_for(self, record: SampleRecord) -> tuple[np.ndarray, np.ndarray]:
        values = dict(zip(record.parameter_names, record.design_values))
        resolved = resolve_circuit(self.circuit, values)
        parameters = np.zeros((len(resolved.devices), len(DEVICE_PARAMETER_ORDER)), dtype=np.float32)
        mask = np.zeros_like(parameters, dtype=bool)
        for index, device in enumerate(resolved.devices):
            device_parameters = {
                name: expression.value
                for name, expression in device.parameters.items()
                if expression.value is not None
            }
            parameters[index], mask[index] = transform_device_parameters(device_parameters)
        return parameters, mask


class CircuitDataset(Dataset[dict[str, object]]):
    def __init__(
        self,
        records: Sequence[SampleRecord],
        topologies: Mapping[str, CompiledTopology],
        target_scaler: TargetScaler,
        *,
        precompute_device_parameters: bool = True,
    ) -> None:
        self.records = tuple(records)
        self.topologies = dict(topologies)
        self.target_scaler = target_scaler
        missing = sorted({record.topology_id for record in records} - set(topologies))
        if missing:
            raise KeyError(f"缺少已编译拓扑：{missing}")
        self.topology_to_index = {
            topology_id: index for index, topology_id in enumerate(sorted(self.topologies))
        }
        self._parameters: list[tuple[np.ndarray, np.ndarray]] | None = None
        if precompute_device_parameters:
            self._parameters = [self.topologies[row.topology_id].parameters_for(row) for row in self.records]

    def __len__(self) -> int:
        return len(self.records)

    def __getitem__(self, index: int) -> dict[str, object]:
        record = self.records[index]
        topology = self.topologies[record.topology_id]
        parameters, parameter_mask = (
            self._parameters[index] if self._parameters is not None else topology.parameters_for(record)
        )
        target, target_mask = self.target_scaler.transform(record.metric_values)
        return {
            "topology_id": record.topology_id,
            "topology_index": self.topology_to_index[record.topology_id],
            "sample_id": record.sample_id,
            "device_type": topology.device_type,
            "pin_role": topology.pin_role,
            "port_role": topology.port_role,
            "device_index": topology.device_index,
            "local_attention": topology.local_attention,
            "device_parameters": parameters,
            "device_parameter_mask": parameter_mask,
            "device_types": topology.device_types,
            "target": target,
            "target_mask": target_mask,
        }


def collate_circuit_samples(samples: Sequence[dict[str, object]]) -> dict[str, object]:
    if not samples:
        raise ValueError("batch 不能为空")
    batch_size = len(samples)
    max_tokens = max(len(sample["device_type"]) for sample in samples)  # type: ignore[arg-type]
    max_devices = max(len(sample["device_types"]) for sample in samples)  # type: ignore[arg-type]
    device_type = torch.zeros((batch_size, max_tokens), dtype=torch.long)
    pin_role = torch.zeros_like(device_type)
    port_role = torch.zeros_like(device_type)
    device_index = torch.full_like(device_type, -1)
    token_mask = torch.zeros((batch_size, max_tokens), dtype=torch.bool)
    local_attention = torch.zeros((batch_size, max_tokens, max_tokens), dtype=torch.bool)
    device_parameters = torch.zeros((batch_size, max_devices, len(DEVICE_PARAMETER_ORDER)), dtype=torch.float32)
    device_parameter_mask = torch.zeros_like(device_parameters, dtype=torch.bool)
    device_types = torch.zeros((batch_size, max_devices), dtype=torch.long)
    device_mask = torch.zeros((batch_size, max_devices), dtype=torch.bool)
    targets, target_masks = [], []
    for batch_index, sample in enumerate(samples):
        tokens = len(sample["device_type"])  # type: ignore[arg-type]
        devices = len(sample["device_types"])  # type: ignore[arg-type]
        device_type[batch_index, :tokens] = torch.as_tensor(sample["device_type"])
        pin_role[batch_index, :tokens] = torch.as_tensor(sample["pin_role"])
        port_role[batch_index, :tokens] = torch.as_tensor(sample["port_role"])
        device_index[batch_index, :tokens] = torch.as_tensor(sample["device_index"])
        token_mask[batch_index, :tokens] = True
        local_attention[batch_index, :tokens, :tokens] = torch.as_tensor(sample["local_attention"])
        device_parameters[batch_index, :devices] = torch.as_tensor(sample["device_parameters"])
        device_parameter_mask[batch_index, :devices] = torch.as_tensor(sample["device_parameter_mask"])
        device_types[batch_index, :devices] = torch.as_tensor(sample["device_types"])
        device_mask[batch_index, :devices] = True
        targets.append(torch.as_tensor(sample["target"]))
        target_masks.append(torch.as_tensor(sample["target_mask"]))
    return {
        "topology_id": [sample["topology_id"] for sample in samples],
        "topology_index": torch.tensor([int(sample["topology_index"]) for sample in samples]),
        "sample_id": torch.tensor([int(sample["sample_id"]) for sample in samples]),
        "device_type": device_type,
        "pin_role": pin_role,
        "port_role": port_role,
        "device_index": device_index,
        "token_mask": token_mask,
        "local_attention": local_attention,
        "device_parameters": device_parameters,
        "device_parameter_mask": device_parameter_mask,
        "device_types": device_types,
        "device_mask": device_mask,
        "target": torch.stack(targets),
        "target_mask": torch.stack(target_masks),
    }
