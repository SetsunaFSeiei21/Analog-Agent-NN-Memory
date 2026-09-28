from __future__ import annotations

from pathlib import Path
from typing import Mapping, Sequence

import torch

from .contracts import METRIC_NAMES, MetricPrediction, SampleRecord
from .data import CircuitDataset, CompiledTopology, TargetScaler, TopologyEntry, collate_circuit_samples
from .model import ZeroSimModel
from .training.checkpoint import load_checkpoint


class ZeroSimPredictor:
    def __init__(
        self,
        model: ZeroSimModel,
        target_scaler: TargetScaler,
        *,
        device: str | torch.device | None = None,
        backbone_version: str | None = None,
        adapter_version: str | None = None,
    ) -> None:
        self.device = torch.device(device or ("cuda" if torch.cuda.is_available() else "cpu"))
        self.model = model.to(self.device).eval()
        self.scaler = target_scaler
        self.backbone_version = backbone_version
        self.adapter_version = adapter_version

    @classmethod
    def from_checkpoint(
        cls, path: Path | str, *, device: str | torch.device | None = None
    ) -> "ZeroSimPredictor":
        model, scaler, metadata = load_checkpoint(path, map_location="cpu")
        return cls(
            model, scaler, device=device,
            backbone_version=str(metadata.get("backbone_version", Path(path).stem)),
        )

    @staticmethod
    def compile_topology(
        topology_id: str,
        circuit_path: Path | str,
        parameter_path: Path | str,
    ) -> CompiledTopology:
        circuit_path, parameter_path = Path(circuit_path), Path(parameter_path)
        return CompiledTopology.from_entry(TopologyEntry(
            topology_id=topology_id,
            role="sequential",
            circuit_path=circuit_path,
            parameter_path=parameter_path,
            database_path=circuit_path.parent / "sampling_history.sqlite3",
        ))

    @torch.no_grad()
    def predict(
        self,
        topology: CompiledTopology,
        parameter_values: Mapping[str, float],
    ) -> MetricPrediction:
        expected = tuple(topology.circuit.parameter_defaults)
        supplied = {name.casefold(): (name, value) for name, value in parameter_values.items()}
        if set(supplied) != {name.casefold() for name in expected}:
            raise ValueError("parameter_values 必须精确覆盖拓扑的全部设计参数")
        record = SampleRecord(
            topology_id=topology.topology_id,
            sample_id=-1,
            parameter_names=expected,
            design_values=tuple(float(supplied[name.casefold()][1]) for name in expected),
            metric_values=(None,) * len(METRIC_NAMES),
            access_level="inference",
            database_path=Path("<inference>"),
        )
        dataset = CircuitDataset([record], {topology.topology_id: topology}, self.scaler)
        batch = collate_circuit_samples([dataset[0]])
        tensor_batch = {
            key: value.to(self.device) if isinstance(value, torch.Tensor) else value
            for key, value in batch.items()
        }
        output = self.model(tensor_batch)  # type: ignore[arg-type]
        physical = self.scaler.inverse(output["prediction"].float().cpu().numpy())[0]
        embedding: Sequence[float] = output["embedding"][0].float().cpu().tolist()
        return MetricPrediction(
            topology_id=topology.topology_id,
            metrics={name: float(value) for name, value in zip(METRIC_NAMES, physical)},
            embedding=embedding,
            backbone_version=self.backbone_version,
            adapter_version=self.adapter_version,
        )
