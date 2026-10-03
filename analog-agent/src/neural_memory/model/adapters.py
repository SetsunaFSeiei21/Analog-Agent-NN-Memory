from __future__ import annotations

from collections.abc import Mapping

import torch
from torch import nn


class LowRankAdapter(nn.Module):
    def __init__(self, d_model: int, rank: int, dropout: float = 0.0) -> None:
        super().__init__()
        self.norm = nn.LayerNorm(d_model)
        self.down = nn.Linear(d_model, rank, bias=False)
        self.up = nn.Linear(rank, d_model, bias=False)
        self.dropout = nn.Dropout(dropout)
        nn.init.normal_(self.down.weight, std=0.02)
        nn.init.zeros_(self.up.weight)

    def forward(self, inputs: torch.Tensor) -> torch.Tensor:
        return self.up(self.dropout(torch.nn.functional.gelu(self.down(self.norm(inputs)))))


class OutputCalibration(nn.Module):
    def __init__(self, metrics: int) -> None:
        super().__init__()
        self.scale_delta = nn.Parameter(torch.zeros(metrics))
        self.bias = nn.Parameter(torch.zeros(metrics))

    def forward(self, prediction: torch.Tensor) -> torch.Tensor:
        return prediction * (1.0 + self.scale_delta) + self.bias


def set_adaptation_mode(model: nn.Module, *, full_finetune: bool = False) -> None:
    for parameter in model.parameters():
        parameter.requires_grad = bool(full_finetune)
    if not full_finetune:
        for name, parameter in model.named_parameters():
            if ".adapter." in name or name.startswith("calibration."):
                parameter.requires_grad = True


def reset_adapters(model: nn.Module) -> None:
    for module in model.modules():
        if isinstance(module, LowRankAdapter):
            nn.init.zeros_(module.up.weight)
        elif isinstance(module, OutputCalibration):
            nn.init.zeros_(module.scale_delta)
            nn.init.zeros_(module.bias)


def adapter_state_dict(model: nn.Module) -> dict[str, torch.Tensor]:
    return {
        name: value.detach().cpu().clone()
        for name, value in model.state_dict().items()
        if ".adapter." in name or name.startswith("calibration.")
    }


def load_adapter_state_dict(model: nn.Module, state: Mapping[str, torch.Tensor]) -> None:
    expected = set(adapter_state_dict(model))
    if set(state) != expected:
        raise ValueError(f"adapter state 不匹配：missing={sorted(expected-set(state))}, extra={sorted(set(state)-expected)}")
    current = model.state_dict()
    current.update(state)
    model.load_state_dict(current, strict=True)
