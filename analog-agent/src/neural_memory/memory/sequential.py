from __future__ import annotations

import hashlib
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass
from typing import Any

import numpy as np
import torch

from ..contracts import SampleRecord
from ..data.transforms import TargetScaler
from ..model import adapter_state_dict, load_adapter_state_dict, reset_adapters
from ..training.evaluator import evaluate_predictions
from .adaptation import AdaptationConfig, AdapterTrainer
from .consolidation import ConsolidationConfig, Consolidator
from .registry import MemoryEntry, MemoryRegistry
from .replay import ReplayBuffer
from .selection import R2MemorySelector


ALLOWED_PROBE_K = frozenset({5, 10, 15, 20, 25})


def select_probe_indices(
    records: Sequence[SampleRecord], *, k: int, order_seed: int, topology_id: str
) -> tuple[int, ...]:
    """Probe choice intentionally depends on order seed, never on model seed."""
    if k not in ALLOWED_PROBE_K:
        raise ValueError(f"K 必须是 {sorted(ALLOWED_PROBE_K)}")
    if len(records) < k:
        raise ValueError(f"拓扑 {topology_id} 只有 {len(records)} 个可见样本，无法选择 K={k}")
    digest = hashlib.sha256(f"{order_seed}:{topology_id}".encode()).digest()
    generator = np.random.default_rng(int.from_bytes(digest[:8], "big"))
    return tuple(sorted(generator.choice(len(records), size=k, replace=False).tolist()))


@dataclass(frozen=True)
class SequentialConfig:
    probe_k: int = 20
    order_seed: int = 0
    model_seed: int = 0
    open_final_blind: bool = False

    def __post_init__(self) -> None:
        if self.probe_k not in ALLOWED_PROBE_K:
            raise ValueError(f"probe_k 必须是 {sorted(ALLOWED_PROBE_K)}")


@dataclass(frozen=True)
class SequentialTask:
    topology_id: str
    probe_loader: Any
    hidden_loader: Any
    replay_records: tuple[SampleRecord, ...]
    is_final_blind: bool = False


@dataclass(frozen=True)
class SequentialOutcome:
    topology_id: str
    selected_memory_id: str
    created_memory_id: str | None
    probe_scores: tuple[dict[str, Any], ...]
    hidden_macro_r2: float | None
    hidden_macro_nrmse: float | None
    consolidation_ran: bool


class SequentialExperiment:
    def __init__(
        self,
        *,
        model: torch.nn.Module,
        target_scaler: TargetScaler,
        registry: MemoryRegistry,
        replay_buffer: ReplayBuffer,
        adaptation_config: AdaptationConfig,
        consolidation_config: ConsolidationConfig,
        config: SequentialConfig,
        replay_loader_factory: Callable[[Sequence[SampleRecord]], Any],
        device: str | torch.device | None = None,
    ) -> None:
        if target_scaler.missing_policy == "masked" and not adaptation_config.use_loss_mask:
            raise ValueError("masked scaler 必须在 adaptation 中启用 loss mask")
        if target_scaler.missing_policy == "sentinel" and adaptation_config.use_loss_mask:
            raise ValueError("sentinel ablation 必须在 adaptation 中禁用 loss mask")
        self.model = model
        self.scaler = target_scaler
        self.registry = registry
        self.replay = replay_buffer
        self.adaptation_config = adaptation_config
        self.adapter_trainer = AdapterTrainer(adaptation_config)
        self.consolidation_config = consolidation_config
        self.consolidator = Consolidator(consolidation_config)
        self.config = config
        self.replay_loader_factory = replay_loader_factory
        self.device = torch.device(device or ("cuda" if torch.cuda.is_available() else "cpu"))
        self.selector = R2MemorySelector()
        self.support_loaders: dict[str, Any] = {}
        torch.manual_seed(config.model_seed)

    def _snapshot(self) -> dict[str, torch.Tensor]:
        if self.adaptation_config.full_finetune:
            return {name: value.detach().cpu().clone() for name, value in self.model.state_dict().items()}
        return adapter_state_dict(self.model)

    def _load(self, state: dict[str, torch.Tensor]) -> None:
        if self.adaptation_config.full_finetune:
            self.model.load_state_dict(state, strict=True)
        else:
            load_adapter_state_dict(self.model, state)

    @torch.no_grad()
    def _collect(self, loader: Any) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        self.model.to(self.device).eval()
        prediction, target, masks, embeddings = [], [], [], []
        for raw_batch in loader:
            batch = {
                key: value.to(self.device) if isinstance(value, torch.Tensor) else value
                for key, value in raw_batch.items()
            }
            output = self.model(batch)
            prediction.append(output["prediction"].float().cpu().numpy())
            target.append(batch["target"].float().cpu().numpy())
            masks.append(batch["target_mask"].cpu().numpy())
            embeddings.append(output["embedding"].float().cpu().numpy())
        standardized_prediction = np.concatenate(prediction)
        standardized_target = np.concatenate(target)
        return (
            self.scaler.inverse(standardized_prediction),
            self.scaler.inverse(standardized_target),
            np.concatenate(masks),
            np.concatenate(embeddings),
        )

    def _rebase_memories(self, old_entries: Sequence[MemoryEntry]) -> None:
        reset_adapters(self.model)
        shared_state = {name: value.detach().cpu().clone() for name, value in self.model.state_dict().items()}
        for entry in old_entries:
            loader = self.support_loaders.get(entry.memory_id)
            if loader is None:
                continue
            self.model.load_state_dict(shared_state, strict=True)
            adapted = self.adapter_trainer.adapt(self.model, loader, device=self.device)
            self.registry.register(
                topology_id=entry.topology_id,
                adapter_state=adapted,
                created_step=entry.created_step,
                embedding_centroid=entry.embedding_centroid,
                metadata={**dict(entry.metadata), "rebased_from": entry.backbone_version},
                memory_id=entry.memory_id,
            )
        self.model.load_state_dict(shared_state, strict=True)

    def run(self, tasks: Sequence[SequentialTask]) -> tuple[SequentialOutcome, ...]:
        outcomes: list[SequentialOutcome] = []
        completed_nonblind = 0
        for step, task in enumerate(tasks):
            if task.is_final_blind and not self.config.open_final_blind:
                raise PermissionError("final_blind 尚未显式打开；冻结协议禁止提前评估")
            if hasattr(task.probe_loader, "dataset") and len(task.probe_loader.dataset) != self.config.probe_k:
                raise ValueError(
                    f"{task.topology_id} 的 probe loader 必须精确包含 K={self.config.probe_k} 个样本"
                )
            reset_adapters(self.model)
            global_state = self._snapshot()
            candidate_states: dict[str, dict[str, torch.Tensor]] = {"global": global_state}
            stable_indices = {"global": 0}
            for entry in self.registry.entries():
                candidate_states[entry.memory_id] = self.registry.load_state(entry.memory_id)
                stable_indices[entry.memory_id] = entry.stable_index
            predictions: dict[str, np.ndarray] = {}
            probe_target = probe_mask = None
            for memory_id, state in candidate_states.items():
                self._load(state)
                prediction, target, mask, _ = self._collect(task.probe_loader)
                predictions[memory_id] = prediction
                if probe_target is None:
                    probe_target, probe_mask = target, mask
            assert probe_target is not None and probe_mask is not None
            selection = self.selector.select(predictions, probe_target, probe_mask, stable_indices)
            self._load(candidate_states[selection.selected_memory_id])
            adapted_state = self.adapter_trainer.adapt(self.model, task.probe_loader, device=self.device)
            _, _, _, probe_embedding = self._collect(task.probe_loader)
            hidden_prediction, hidden_target, hidden_mask, _ = self._collect(task.hidden_loader)
            hidden_metrics = evaluate_predictions(hidden_prediction, hidden_target, hidden_mask)
            created_memory_id: str | None = None
            if not task.is_final_blind:
                entry = self.registry.register(
                    topology_id=task.topology_id,
                    adapter_state=adapted_state,
                    created_step=step,
                    embedding_centroid=tuple(np.mean(probe_embedding, axis=0).tolist()),
                    metadata={
                        "selected_parent": selection.selected_memory_id,
                        "probe_k": self.config.probe_k,
                        "order_seed": self.config.order_seed,
                        "model_seed": self.config.model_seed,
                        "state_kind": "full_model" if self.adaptation_config.full_finetune else "adapter",
                    },
                )
                created_memory_id = entry.memory_id
                self.support_loaders[entry.memory_id] = task.probe_loader
                self.replay.add(task.replay_records)
                completed_nonblind += 1
            self._load(global_state)
            consolidation_ran = False
            if not task.is_final_blind and self.consolidation_config.should_run(completed_nonblind):
                old_entries = self.registry.entries()
                replay_loader = self.replay_loader_factory(self.replay.records())
                self.consolidator.consolidate(self.model, replay_loader, device=self.device)
                self.registry.bump_backbone_version(
                    f"{self.registry.backbone_version}.c{completed_nonblind}"
                )
                self._rebase_memories(old_entries)
                consolidation_ran = True
            outcomes.append(SequentialOutcome(
                topology_id=task.topology_id,
                selected_memory_id=selection.selected_memory_id,
                created_memory_id=created_memory_id,
                probe_scores=tuple(asdict(score) for score in selection.scores),
                hidden_macro_r2=hidden_metrics.macro_r2,
                hidden_macro_nrmse=hidden_metrics.macro_nrmse,
                consolidation_ran=consolidation_ran,
            ))
        return tuple(outcomes)
