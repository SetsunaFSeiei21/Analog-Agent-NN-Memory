from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import torch

from ..model import adapter_state_dict, set_adaptation_mode
from ..training.loss import MaskedHuberLoss


@dataclass(frozen=True)
class AdaptationConfig:
    steps: int = 100
    learning_rate: float = 1e-3
    weight_decay: float = 0.0
    full_finetune: bool = False
    use_loss_mask: bool = True
    huber_delta: float = 1.0
    max_gradient_norm: float = 1.0


class AdapterTrainer:
    def __init__(self, config: AdaptationConfig) -> None:
        self.config = config

    def adapt(self, model: torch.nn.Module, loader: Any, *, device: torch.device | str) -> dict[str, torch.Tensor]:
        device = torch.device(device)
        model.to(device)
        set_adaptation_mode(model, full_finetune=self.config.full_finetune)
        optimizer = torch.optim.AdamW(
            [parameter for parameter in model.parameters() if parameter.requires_grad],
            lr=self.config.learning_rate,
            weight_decay=self.config.weight_decay,
        )
        loss_function = MaskedHuberLoss(
            delta=self.config.huber_delta,
            use_loss_mask=self.config.use_loss_mask,
        ).to(device)
        model.train()
        iterator = iter(loader)
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
            torch.nn.utils.clip_grad_norm_(model.parameters(), self.config.max_gradient_norm)
            optimizer.step()
        if self.config.full_finetune:
            return {name: value.detach().cpu().clone() for name, value in model.state_dict().items()}
        return adapter_state_dict(model)
