from __future__ import annotations

import copy
from dataclasses import asdict, dataclass
from typing import Any

import numpy as np
import torch
from torch import nn

from ..data.transforms import TargetScaler
from .evaluator import RegressionMetrics, evaluate_predictions
from .loss import MaskedHuberLoss


@dataclass(frozen=True)
class TrainingConfig:
    epochs: int = 100
    learning_rate: float = 3e-4
    weight_decay: float = 1e-4
    gradient_accumulation_steps: int = 1
    max_gradient_norm: float = 1.0
    amp_dtype: str = "bfloat16"
    early_stopping_patience: int = 15
    huber_delta: float = 1.0
    use_loss_mask: bool = True
    moe_balance_weight: float = 0.01
    seed: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class Trainer:
    def __init__(
        self,
        model: nn.Module,
        target_scaler: TargetScaler,
        config: TrainingConfig,
        *,
        device: torch.device | str | None = None,
    ) -> None:
        self.model = model
        self.target_scaler = target_scaler
        self.config = config
        self.device = torch.device(device or ("cuda" if torch.cuda.is_available() else "cpu"))
        self.model.to(self.device)
        self.loss = MaskedHuberLoss(delta=config.huber_delta, use_loss_mask=config.use_loss_mask).to(self.device)
        self.optimizer = torch.optim.AdamW(
            [parameter for parameter in model.parameters() if parameter.requires_grad],
            lr=config.learning_rate,
            weight_decay=config.weight_decay,
        )
        enabled = self.device.type == "cuda" and config.amp_dtype in {"float16", "bfloat16"}
        self.autocast_enabled = enabled
        self.autocast_dtype = torch.bfloat16 if config.amp_dtype == "bfloat16" else torch.float16
        scaler_enabled = enabled and self.autocast_dtype == torch.float16
        try:
            self.scaler = torch.amp.GradScaler("cuda", enabled=scaler_enabled)
        except (AttributeError, TypeError):  # torch 2.2 compatibility
            self.scaler = torch.cuda.amp.GradScaler(enabled=scaler_enabled)

    def _device_batch(self, batch: dict[str, object]) -> dict[str, object]:
        return {
            key: value.to(self.device, non_blocking=True) if isinstance(value, torch.Tensor) else value
            for key, value in batch.items()
        }

    def train_epoch(self, loader: Any) -> float:
        self.model.train()
        self.optimizer.zero_grad(set_to_none=True)
        total_loss, steps = 0.0, 0
        for step, raw_batch in enumerate(loader):
            batch = self._device_batch(raw_batch)
            with torch.autocast(self.device.type, dtype=self.autocast_dtype, enabled=self.autocast_enabled):
                output = self.model(batch)  # type: ignore[arg-type]
                loss = self.loss(output["prediction"], batch["target"], batch["target_mask"])  # type: ignore[arg-type]
                if "moe_balance_loss" in output:
                    loss = loss + self.config.moe_balance_weight * output["moe_balance_loss"]
                scaled_loss = loss / self.config.gradient_accumulation_steps
            self.scaler.scale(scaled_loss).backward()
            if (step + 1) % self.config.gradient_accumulation_steps == 0:
                self.scaler.unscale_(self.optimizer)
                torch.nn.utils.clip_grad_norm_(self.model.parameters(), self.config.max_gradient_norm)
                self.scaler.step(self.optimizer)
                self.scaler.update()
                self.optimizer.zero_grad(set_to_none=True)
            total_loss += float(loss.detach())
            steps += 1
        if steps and steps % self.config.gradient_accumulation_steps:
            self.scaler.unscale_(self.optimizer)
            torch.nn.utils.clip_grad_norm_(self.model.parameters(), self.config.max_gradient_norm)
            self.scaler.step(self.optimizer)
            self.scaler.update()
            self.optimizer.zero_grad(set_to_none=True)
        return total_loss / max(steps, 1)

    @torch.no_grad()
    def evaluate(self, loader: Any) -> tuple[float, RegressionMetrics]:
        self.model.eval()
        losses, prediction, target, masks = [], [], [], []
        for raw_batch in loader:
            batch = self._device_batch(raw_batch)
            output = self.model(batch)  # type: ignore[arg-type]
            losses.append(float(self.loss(output["prediction"], batch["target"], batch["target_mask"])))  # type: ignore[arg-type]
            prediction.append(output["prediction"].float().cpu().numpy())
            target.append(batch["target"].float().cpu().numpy())  # type: ignore[union-attr]
            masks.append(batch["target_mask"].cpu().numpy())  # type: ignore[union-attr]
        standardized_prediction = np.concatenate(prediction)
        standardized_target = np.concatenate(target)
        valid_mask = np.concatenate(masks)
        physical_prediction = self.target_scaler.inverse(standardized_prediction)
        physical_target = self.target_scaler.inverse(standardized_target)
        return float(np.mean(losses)), evaluate_predictions(physical_prediction, physical_target, valid_mask)

    def fit(self, train_loader: Any, validation_loader: Any) -> list[dict[str, Any]]:
        torch.manual_seed(self.config.seed)
        np.random.seed(self.config.seed)
        best_score = -float("inf")
        best_state: dict[str, torch.Tensor] | None = None
        patience = 0
        history: list[dict[str, Any]] = []
        for epoch in range(self.config.epochs):
            if hasattr(train_loader.batch_sampler, "set_epoch"):
                train_loader.batch_sampler.set_epoch(epoch)
            training_loss = self.train_epoch(train_loader)
            validation_loss, metrics = self.evaluate(validation_loader)
            score = metrics.macro_r2 if metrics.macro_r2 is not None else -validation_loss
            history.append({
                "epoch": epoch, "training_loss": training_loss, "validation_loss": validation_loss,
                "macro_r2": metrics.macro_r2, "macro_nrmse": metrics.macro_nrmse,
            })
            if score > best_score:
                best_score = score
                best_state = copy.deepcopy({name: value.detach().cpu() for name, value in self.model.state_dict().items()})
                patience = 0
            else:
                patience += 1
                if patience >= self.config.early_stopping_patience:
                    break
        if best_state is not None:
            self.model.load_state_dict(best_state)
        return history
