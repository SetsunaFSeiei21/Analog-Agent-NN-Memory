from __future__ import annotations

from typing import Any, Mapping

import numpy as np
import torch

from .data import CompiledTopology, TargetScaler
from .inference import ZeroSimPredictor
from .memory import AdaptationConfig, AdapterTrainer, MemoryRegistry, R2MemorySelector, SelectionResult
from .model import load_adapter_state_dict, reset_adapters


class NeuralMemoryService:
    """Narrow integration facade for an Analog Agent controller."""

    def __init__(
        self,
        *,
        model: torch.nn.Module,
        target_scaler: TargetScaler,
        registry: MemoryRegistry,
        adaptation_config: AdaptationConfig,
        device: str | torch.device | None = None,
        backbone_version: str | None = None,
    ) -> None:
        if adaptation_config.full_finetune:
            raise ValueError("在线服务使用 adapter 主方案；full-finetune 仅作为离线 baseline")
        self.device = torch.device(device or ("cuda" if torch.cuda.is_available() else "cpu"))
        self.model = model.to(self.device)
        self.scaler = target_scaler
        self.registry = registry
        self.adaptation = AdapterTrainer(adaptation_config)
        self.selector = R2MemorySelector()
        self.predictor = ZeroSimPredictor(
            model, target_scaler, device=self.device,
            backbone_version=backbone_version or registry.backbone_version,
        )

    def activate(self, memory_id: str | None) -> None:
        reset_adapters(self.model)
        if memory_id is not None and memory_id != "global":
            load_adapter_state_dict(self.model, self.registry.load_state(memory_id))
        self.predictor.adapter_version = None if memory_id in {None, "global"} else memory_id

    @torch.no_grad()
    def _loader_predictions(self, loader: Any) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        prediction, target, mask = [], [], []
        self.model.eval()
        for raw_batch in loader:
            batch = {
                key: value.to(self.device) if isinstance(value, torch.Tensor) else value
                for key, value in raw_batch.items()
            }
            output = self.model(batch)
            prediction.append(output["prediction"].float().cpu().numpy())
            target.append(batch["target"].float().cpu().numpy())
            mask.append(batch["target_mask"].cpu().numpy())
        return (
            self.scaler.inverse(np.concatenate(prediction)),
            self.scaler.inverse(np.concatenate(target)),
            np.concatenate(mask),
        )

    def select_memory(self, probe_loader: Any) -> SelectionResult:
        predictions: dict[str, np.ndarray] = {}
        stable = {"global": 0}
        self.activate("global")
        global_prediction, target, mask = self._loader_predictions(probe_loader)
        predictions["global"] = global_prediction
        for entry in self.registry.entries():
            self.activate(entry.memory_id)
            predictions[entry.memory_id] = self._loader_predictions(probe_loader)[0]
            stable[entry.memory_id] = entry.stable_index
        return self.selector.select(predictions, target, mask, stable)

    def adapt(
        self,
        *,
        topology_id: str,
        probe_loader: Any,
        parent_memory_id: str,
        created_step: int,
        metadata: Mapping[str, object] | None = None,
    ) -> str:
        self.activate(parent_memory_id)
        state = self.adaptation.adapt(self.model, probe_loader, device=self.device)
        entry = self.registry.register(
            topology_id=topology_id,
            adapter_state=state,
            created_step=created_step,
            metadata={"selected_parent": parent_memory_id, **dict(metadata or {})},
        )
        self.predictor.adapter_version = entry.memory_id
        return entry.memory_id

    def predict(
        self,
        topology: CompiledTopology,
        parameter_values: Mapping[str, float],
        *,
        memory_id: str | None = None,
    ):
        self.activate(memory_id)
        return self.predictor.predict(topology, parameter_values)

    @staticmethod
    def observe(point_simulator: Any, parameter_values: Mapping[str, float], **observation: object):
        """Forward to the strict point-simulation API; returned sample is immediately auditable."""
        return point_simulator.simulate(parameter_values, **observation)
