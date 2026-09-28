from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import torch
from torch.utils.data import DataLoader

from ..contracts import SampleRecord
from ..data import (
    CircuitDataset, CompiledTopology, ExperimentManifest, HistoryReader, TargetScaler,
    TopologyBalancedBatchSampler, collate_circuit_samples,
)
from ..model import ZeroSimConfig, ZeroSimModel
from .checkpoint import save_checkpoint
from .trainer import Trainer, TrainingConfig


@dataclass(frozen=True)
class TrainingArtifacts:
    checkpoint_path: Path
    scaler: TargetScaler
    history: tuple[dict[str, object], ...]
    train_size: int
    validation_size: int


def _split_by_topology(
    records: list[SampleRecord], validation_fraction: float, seed: int
) -> tuple[list[SampleRecord], list[SampleRecord]]:
    generator = np.random.default_rng(seed)
    train: list[SampleRecord] = []
    validation: list[SampleRecord] = []
    for topology_id in sorted({record.topology_id for record in records}):
        group = [record for record in records if record.topology_id == topology_id]
        order = generator.permutation(len(group))
        validation_count = max(1, int(round(len(group) * validation_fraction)))
        validation_indices = set(order[:validation_count].tolist())
        validation.extend(record for index, record in enumerate(group) if index in validation_indices)
        train.extend(record for index, record in enumerate(group) if index not in validation_indices)
    return train, validation


def train_from_manifest(
    manifest_path: Path | str,
    *,
    model_config: ZeroSimConfig,
    training_config: TrainingConfig,
    checkpoint_path: Path | str,
    missing_policy: str = "masked",
    z_missing: float = -20.0,
    validation_fraction: float = 0.1,
    batch_size: int = 64,
    topologies_per_batch: int = 4,
    num_workers: int = 0,
    device: str | torch.device | None = None,
    enforce_expected_points: bool = True,
) -> TrainingArtifacts:
    if missing_policy == "masked" and not training_config.use_loss_mask:
        raise ValueError("masked 目标必须启用 loss mask")
    if missing_policy == "sentinel" and training_config.use_loss_mask:
        raise ValueError("sentinel ablation 必须禁用 loss mask")
    manifest = ExperimentManifest.load(manifest_path, enforce_frozen_protocol=True)
    entries = manifest.by_role("initial_train")
    records: list[SampleRecord] = []
    for entry in entries:
        reader = HistoryReader(entry.database_path, entry.topology_id)
        if enforce_expected_points:
            reader.assert_ready(entry.expected_usable_points, access_levels=("train_visible",))
        records.extend(reader.read(access_levels=("train_visible",)))
    train_records, validation_records = _split_by_topology(records, validation_fraction, training_config.seed)
    # Frozen once, strictly from the initial-topology training split.
    scaler = TargetScaler.fit(
        (record.metric_values for record in train_records),
        missing_policy=missing_policy,
        z_missing=z_missing,
    )
    topologies = {entry.topology_id: CompiledTopology.from_entry(entry) for entry in entries}
    train_dataset = CircuitDataset(train_records, topologies, scaler)
    validation_dataset = CircuitDataset(validation_records, topologies, scaler)
    batch_sampler = TopologyBalancedBatchSampler(
        train_records,
        batch_size=batch_size,
        topologies_per_batch=topologies_per_batch,
        seed=training_config.seed,
    )
    train_loader = DataLoader(
        train_dataset, batch_sampler=batch_sampler, collate_fn=collate_circuit_samples,
        num_workers=num_workers, pin_memory=torch.cuda.is_available(),
    )
    validation_loader = DataLoader(
        validation_dataset, batch_size=batch_size, shuffle=False, collate_fn=collate_circuit_samples,
        num_workers=num_workers, pin_memory=torch.cuda.is_available(),
    )
    torch.manual_seed(training_config.seed)
    np.random.seed(training_config.seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(training_config.seed)
    model = ZeroSimModel(model_config)
    trainer = Trainer(model, scaler, training_config, device=device)
    history = trainer.fit(train_loader, validation_loader)
    checkpoint_path = Path(checkpoint_path)
    save_checkpoint(
        checkpoint_path,
        model=model,
        target_scaler=scaler,
        training_config=training_config,
        metadata={
            "manifest": str(Path(manifest_path).resolve()),
            "train_topologies": [entry.topology_id for entry in entries],
            "train_size": len(train_records),
            "validation_size": len(validation_records),
            "scaler_fitted_on": "initial_train_split_only",
        },
    )
    return TrainingArtifacts(checkpoint_path, scaler, tuple(history), len(train_records), len(validation_records))
