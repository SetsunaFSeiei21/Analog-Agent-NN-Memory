from __future__ import annotations

from collections.abc import Sequence

import torch
from torch import nn


class MaskedHuberLoss(nn.Module):
    def __init__(
        self,
        *,
        delta: float = 1.0,
        use_loss_mask: bool = True,
        metric_weights: Sequence[float] | None = None,
    ) -> None:
        super().__init__()
        if delta <= 0:
            raise ValueError("delta 必须为正数")
        self.delta = float(delta)
        self.use_loss_mask = use_loss_mask
        weights = torch.ones(9) if metric_weights is None else torch.tensor(metric_weights, dtype=torch.float32)
        if weights.shape != (9,) or torch.any(weights <= 0):
            raise ValueError("metric_weights 必须是 9 个正数")
        self.register_buffer("metric_weights", weights)

    def forward(self, prediction: torch.Tensor, target: torch.Tensor, valid_mask: torch.Tensor) -> torch.Tensor:
        if prediction.shape != target.shape or prediction.shape != valid_mask.shape:
            raise ValueError("prediction/target/valid_mask 形状必须一致")
        error = prediction - target
        absolute = error.abs()
        loss = torch.where(
            absolute <= self.delta,
            0.5 * error.square(),
            self.delta * (absolute - 0.5 * self.delta),
        )
        loss = loss * self.metric_weights
        if self.use_loss_mask:
            weights = valid_mask.to(loss.dtype) * self.metric_weights
            return (loss * valid_mask).sum() / weights.sum().clamp_min(1.0)
        return loss.mean()
