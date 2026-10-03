from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import torch

from ..model import reset_adapters
from ..training.loss import MaskedHuberLoss


@dataclass(frozen=True)
class ConsolidationConfig:
    interval: int = 5
    steps: int = 500
    learning_rate: float = 1e-4
    weight_decay: float = 1e-4
    use_loss_mask: bool = True
    huber_delta: float = 1.0
    max_gradient_norm: float = 1.0

    def should_run(self, completed_tasks: int) -> bool:
        return self.interval > 0 and completed_tasks > 0 and completed_tasks % self.interval == 0


class Consolidator:
    """Replay-based shared-backbone update; task adapters are explicitly excluded."""

    def __init__(self, config: ConsolidationConfig) -> None:
        self.config = config

    def consolidate(self, model: torch.nn.Module, loader: Any, *, device: torch.device | str) -> None:
        device = torch.device(device)
        model.to(device)
        for name, parameter in model.named_parameters():
            parameter.requires_grad = ".adapter." not in name and not name.startswith("calibration.")
        trainable = [parameter for parameter in model.parameters() if parameter.requires_grad]
        optimizer = torch.optim.AdamW(
            trainable, lr=self.config.learning_rate, weight_decay=self.config.weight_decay
        )
        loss_function = MaskedHuberLoss(
            delta=self.config.huber_delta, use_loss_mask=self.config.use_loss_mask
        ).to(device)
        iterator = iter(loader)
        model.train()
        for _ in range(self.config.steps):
            try:
                batch = next(iterator)
            except StopIteration:
                iterator = iter(loader)
                batch = next(iterator)
            batch = {
                key: value.to(device) if isinstance(value, torch.Tensor) else value
                for key, value in batch.items()
            }
            optimizer.zero_grad(set_to_none=True)
            output = model(batch)
            loss = loss_function(output["prediction"], batch["target"], batch["target_mask"])
            loss.backward()
            torch.nn.utils.clip_grad_norm_(trainable, self.config.max_gradient_norm)
            optimizer.step()
        reset_adapters(model)
