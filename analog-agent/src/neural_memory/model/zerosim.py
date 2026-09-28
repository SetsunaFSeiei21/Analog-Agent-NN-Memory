from __future__ import annotations

import torch
from torch import nn

from .adapters import OutputCalibration
from .config import ZeroSimConfig
from .layers import DeviceParameterCrossAttention, EncoderBlock, MetricDecoderLayer


class SharedMetricHead(nn.Module):
    def __init__(self, d_model: int) -> None:
        super().__init__()
        self.network = nn.Sequential(nn.LayerNorm(d_model), nn.Linear(d_model, d_model), nn.GELU(), nn.Linear(d_model, 1))

    def forward(self, inputs: torch.Tensor) -> tuple[torch.Tensor, dict[str, torch.Tensor]]:
        return self.network(inputs).squeeze(-1), {}


class MetricSpecificHead(nn.Module):
    def __init__(self, d_model: int, metrics: int) -> None:
        super().__init__()
        self.networks = nn.ModuleList([
            nn.Sequential(nn.LayerNorm(d_model), nn.Linear(d_model, d_model), nn.GELU(), nn.Linear(d_model, 1))
            for _ in range(metrics)
        ])

    def forward(self, inputs: torch.Tensor) -> tuple[torch.Tensor, dict[str, torch.Tensor]]:
        values = [network(inputs[:, index]).squeeze(-1) for index, network in enumerate(self.networks)]
        return torch.stack(values, dim=1), {}


class MoEMetricHead(nn.Module):
    def __init__(self, d_model: int, experts: int, top_k: int) -> None:
        super().__init__()
        self.top_k = top_k
        self.router = nn.Linear(d_model, experts)
        self.experts = nn.ModuleList([
            nn.Sequential(nn.LayerNorm(d_model), nn.Linear(d_model, d_model), nn.GELU(), nn.Linear(d_model, 1))
            for _ in range(experts)
        ])

    def forward(self, inputs: torch.Tensor) -> tuple[torch.Tensor, dict[str, torch.Tensor]]:
        logits = self.router(inputs)
        top_values, top_indices = logits.topk(self.top_k, dim=-1)
        gates = torch.softmax(top_values, dim=-1)
        expert_values = torch.stack([expert(inputs).squeeze(-1) for expert in self.experts], dim=-1)
        selected = torch.gather(expert_values, -1, top_indices)
        prediction = (selected * gates).sum(dim=-1)
        probabilities = torch.softmax(logits, dim=-1)
        importance = probabilities.mean(dim=(0, 1))
        load = torch.nn.functional.one_hot(top_indices, len(self.experts)).float().mean(dim=(0, 1, 2))
        auxiliary = len(self.experts) * torch.sum(importance * load)
        return prediction, {"router_logits": logits, "moe_balance_loss": auxiliary}


class ZeroSimModel(nn.Module):
    """Unified pin-graph transformer for zero-shot analog performance prediction."""

    def __init__(self, config: ZeroSimConfig) -> None:
        super().__init__()
        self.config = config
        width = config.d_model
        self.device_embedding = nn.Embedding(6, width, padding_idx=0)
        self.pin_embedding = nn.Embedding(7, width, padding_idx=0)
        self.port_embedding = nn.Embedding(6, width, padding_idx=0)
        self.graph_token = nn.Parameter(torch.empty(1, 1, width))
        nn.init.normal_(self.graph_token, std=0.02)
        self.input_norm = nn.LayerNorm(width)
        self.encoder = nn.ModuleList([
            EncoderBlock(width, config.num_heads, config.dim_feedforward, config.dropout, config.adapter_rank)
            for _ in range(config.num_encoder_layers)
        ])
        self.parameter_attention = nn.ModuleList([
            DeviceParameterCrossAttention(width, config.num_heads, config.num_device_parameters, config.dropout)
            for _ in range(config.num_encoder_layers - config.parameter_injection_layer + 1)
        ])
        self.metric_queries = nn.Parameter(torch.empty(1, config.num_metrics, width))
        nn.init.normal_(self.metric_queries, std=0.02)
        self.decoder = nn.ModuleList([
            MetricDecoderLayer(width, config.num_heads, config.dim_feedforward, config.dropout)
            for _ in range(config.decoder_layers)
        ])
        if config.head_type == "shared":
            self.head: nn.Module = SharedMetricHead(width)
        elif config.head_type == "metric_specific":
            self.head = MetricSpecificHead(width, config.num_metrics)
        else:
            self.head = MoEMetricHead(width, config.moe_experts, config.moe_top_k)
        self.calibration = OutputCalibration(config.num_metrics)

    def _local_layer_indices(self) -> set[int]:
        # Interleave the requested number of local layers early; all other layers are global.
        return {2 * index for index in range(self.config.local_attention_layers) if 2 * index < self.config.num_encoder_layers}

    def forward(self, batch: dict[str, torch.Tensor]) -> dict[str, torch.Tensor]:
        token_mask = batch["token_mask"]
        encoded = (
            self.device_embedding(batch["device_type"])
            + self.pin_embedding(batch["pin_role"])
            + self.port_embedding(batch["port_role"])
        )
        encoded[:, :1] = encoded[:, :1] + self.graph_token
        encoded = self.input_norm(encoded) * token_mask.unsqueeze(-1)
        local_layers = self._local_layer_indices()
        parameter_index = 0
        for layer_index, layer in enumerate(self.encoder):
            allowed = batch["local_attention"] if layer_index in local_layers else None
            encoded = layer(encoded, token_mask, allowed)
            if layer_index + 1 >= self.config.parameter_injection_layer:
                encoded = self.parameter_attention[parameter_index](
                    encoded,
                    batch["device_index"],
                    batch["device_parameters"],
                    batch["device_parameter_mask"],
                    batch["device_types"],
                    token_mask,
                )
                parameter_index += 1
        queries = self.metric_queries.expand(encoded.shape[0], -1, -1)
        for layer in self.decoder:
            queries = layer(queries, encoded, token_mask)
        prediction, diagnostics = self.head(queries)  # type: ignore[operator]
        prediction = self.calibration(prediction)
        return {
            "prediction": prediction,
            "embedding": encoded[:, 0],
            "metric_embeddings": queries,
            **diagnostics,
        }
