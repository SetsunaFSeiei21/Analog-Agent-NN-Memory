from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

import torch

from ..data.transforms import TargetScaler
from ..model import ZeroSimConfig, ZeroSimModel
from .trainer import TrainingConfig


CHECKPOINT_VERSION = 1


def save_checkpoint(
    path: Path | str,
    *,
    model: ZeroSimModel,
    target_scaler: TargetScaler,
    training_config: TrainingConfig,
    metadata: Mapping[str, Any] | None = None,
) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    torch.save({
        "checkpoint_version": CHECKPOINT_VERSION,
        "model_config": model.config.to_dict(),
        "model_state": model.state_dict(),
        "target_scaler": target_scaler.to_dict(),
        "training_config": training_config.to_dict(),
        "metadata": dict(metadata or {}),
    }, path)


def load_checkpoint(
    path: Path | str,
    *,
    map_location: str | torch.device = "cpu",
) -> tuple[ZeroSimModel, TargetScaler, dict[str, Any]]:
    payload = torch.load(Path(path), map_location=map_location, weights_only=False)
    if payload.get("checkpoint_version") != CHECKPOINT_VERSION:
        raise ValueError(f"不支持的 checkpoint_version：{payload.get('checkpoint_version')}")
    model = ZeroSimModel(ZeroSimConfig(**payload["model_config"]))
    model.load_state_dict(payload["model_state"], strict=True)
    return model, TargetScaler.from_dict(payload["target_scaler"]), dict(payload.get("metadata", {}))
