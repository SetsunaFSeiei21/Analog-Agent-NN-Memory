from __future__ import annotations

import math

import torch
from torch import nn

from .adapters import LowRankAdapter


class MaskedSelfAttention(nn.Module):
    def __init__(self, d_model: int, num_heads: int, dropout: float) -> None:
        super().__init__()
        self.num_heads = num_heads
        self.head_dim = d_model // num_heads
        self.qkv = nn.Linear(d_model, 3 * d_model)
        self.output = nn.Linear(d_model, d_model)
        self.dropout = nn.Dropout(dropout)

    def forward(
        self,
        inputs: torch.Tensor,
        token_mask: torch.Tensor,
        allowed_attention: torch.Tensor | None,
    ) -> torch.Tensor:
        batch, tokens, width = inputs.shape
        qkv = self.qkv(inputs).view(batch, tokens, 3, self.num_heads, self.head_dim)
        query, key, value = qkv.unbind(dim=2)
        query, key, value = (tensor.transpose(1, 2) for tensor in (query, key, value))
        scores = torch.matmul(query, key.transpose(-2, -1)) / math.sqrt(self.head_dim)
        base = token_mask[:, :, None] & token_mask[:, None, :]
        allowed = base if allowed_attention is None else base & allowed_attention
        scores = scores.masked_fill(~allowed[:, None], torch.finfo(scores.dtype).min)
        weights = self.dropout(torch.softmax(scores, dim=-1))
        attended = torch.matmul(weights, value).transpose(1, 2).reshape(batch, tokens, width)
        return self.output(attended) * token_mask.unsqueeze(-1)


class EncoderBlock(nn.Module):
    def __init__(self, d_model: int, num_heads: int, dim_feedforward: int, dropout: float, adapter_rank: int) -> None:
        super().__init__()
        self.norm1 = nn.LayerNorm(d_model)
        self.attention = MaskedSelfAttention(d_model, num_heads, dropout)
        self.norm2 = nn.LayerNorm(d_model)
        self.ff = nn.Sequential(
            nn.Linear(d_model, dim_feedforward), nn.GELU(), nn.Dropout(dropout),
            nn.Linear(dim_feedforward, d_model), nn.Dropout(dropout),
        )
        self.dropout = nn.Dropout(dropout)
        self.adapter = LowRankAdapter(d_model, adapter_rank, dropout)

    def forward(self, inputs: torch.Tensor, token_mask: torch.Tensor, allowed: torch.Tensor | None) -> torch.Tensor:
        output = inputs + self.dropout(self.attention(self.norm1(inputs), token_mask, allowed))
        output = output + self.ff(self.norm2(output))
        output = output + self.adapter(output)
        return output * token_mask.unsqueeze(-1)


class DeviceParameterCrossAttention(nn.Module):
    """Each pin token attends only to the six parameter slots of its own device."""

    def __init__(self, d_model: int, num_heads: int, parameter_count: int, dropout: float) -> None:
        super().__init__()
        self.num_heads = num_heads
        self.head_dim = d_model // num_heads
        self.parameter_count = parameter_count
        self.value_embedding = nn.Sequential(nn.Linear(1, d_model), nn.GELU(), nn.Linear(d_model, d_model))
        self.parameter_embedding = nn.Embedding(parameter_count, d_model)
        self.device_embedding = nn.Embedding(6, d_model, padding_idx=0)
        self.query = nn.Linear(d_model, d_model)
        self.key = nn.Linear(d_model, d_model)
        self.value = nn.Linear(d_model, d_model)
        self.output = nn.Linear(d_model, d_model)
        self.norm = nn.LayerNorm(d_model)
        self.dropout = nn.Dropout(dropout)

    def forward(
        self,
        inputs: torch.Tensor,
        device_index: torch.Tensor,
        device_parameters: torch.Tensor,
        parameter_mask: torch.Tensor,
        device_types: torch.Tensor,
        token_mask: torch.Tensor,
    ) -> torch.Tensor:
        batch, tokens, width = inputs.shape
        devices = device_parameters.shape[1]
        parameter_ids = torch.arange(self.parameter_count, device=inputs.device)
        parameter_tokens = self.value_embedding(device_parameters.unsqueeze(-1))
        parameter_tokens = parameter_tokens + self.parameter_embedding(parameter_ids)[None, None]
        parameter_tokens = parameter_tokens + self.device_embedding(device_types)[:, :, None]
        selected = device_index.clamp(min=0, max=max(devices - 1, 0))
        gather_index = selected[:, :, None, None].expand(-1, -1, self.parameter_count, width)
        selected_tokens = torch.gather(parameter_tokens, 1, gather_index)
        selected_mask = torch.gather(
            parameter_mask, 1, selected[:, :, None].expand(-1, -1, self.parameter_count)
        )
        valid_token = token_mask & (device_index >= 0)
        selected_mask = selected_mask & valid_token.unsqueeze(-1)
        query = self.query(self.norm(inputs)).view(batch, tokens, self.num_heads, self.head_dim)
        key = self.key(selected_tokens).view(batch, tokens, self.parameter_count, self.num_heads, self.head_dim)
        value = self.value(selected_tokens).view(batch, tokens, self.parameter_count, self.num_heads, self.head_dim)
        scores = torch.einsum("bthd,btphd->bthp", query, key) / math.sqrt(self.head_dim)
        scores = scores.masked_fill(~selected_mask[:, :, None], torch.finfo(scores.dtype).min)
        weights = self.dropout(torch.softmax(scores, dim=-1))
        attended = torch.einsum("bthp,btphd->bthd", weights, value).reshape(batch, tokens, width)
        attended = self.output(attended) * valid_token.unsqueeze(-1)
        return inputs + self.dropout(attended)


class MetricDecoderLayer(nn.Module):
    def __init__(self, d_model: int, num_heads: int, dim_feedforward: int, dropout: float) -> None:
        super().__init__()
        self.self_attention = nn.MultiheadAttention(d_model, num_heads, dropout=dropout, batch_first=True)
        self.cross_attention = nn.MultiheadAttention(d_model, num_heads, dropout=dropout, batch_first=True)
        self.norm1 = nn.LayerNorm(d_model)
        self.norm2 = nn.LayerNorm(d_model)
        self.norm3 = nn.LayerNorm(d_model)
        self.ff = nn.Sequential(
            nn.Linear(d_model, dim_feedforward), nn.GELU(), nn.Dropout(dropout), nn.Linear(dim_feedforward, d_model)
        )
        self.dropout = nn.Dropout(dropout)

    def forward(self, queries: torch.Tensor, memory: torch.Tensor, token_mask: torch.Tensor) -> torch.Tensor:
        normalized = self.norm1(queries)
        queries = queries + self.dropout(self.self_attention(normalized, normalized, normalized, need_weights=False)[0])
        normalized = self.norm2(queries)
        queries = queries + self.dropout(self.cross_attention(
            normalized, memory, memory, key_padding_mask=~token_mask, need_weights=False
        )[0])
        return queries + self.dropout(self.ff(self.norm3(queries)))
