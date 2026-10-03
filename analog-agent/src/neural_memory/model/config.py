from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True)
class ZeroSimConfig:
    d_model: int = 256
    num_encoder_layers: int = 6
    local_attention_layers: int = 2
    num_heads: int = 8
    dim_feedforward: int = 1024
    parameter_injection_layer: int = 4
    decoder_layers: int = 2
    dropout: float = 0.1
    head_type: str = "shared"
    moe_experts: int = 4
    moe_top_k: int = 2
    adapter_rank: int = 8
    num_metrics: int = 9
    num_device_parameters: int = 6

    def __post_init__(self) -> None:
        if self.d_model % self.num_heads:
            raise ValueError("d_model 必须能被 num_heads 整除")
        if not 0 <= self.local_attention_layers <= self.num_encoder_layers:
            raise ValueError("local_attention_layers 超出范围")
        if not 1 <= self.parameter_injection_layer <= self.num_encoder_layers:
            raise ValueError("parameter_injection_layer 使用 1-based 编号且必须落在 encoder 内")
        if self.head_type not in {"shared", "metric_specific", "moe"}:
            raise ValueError("head_type 必须为 shared/metric_specific/moe")
        if self.head_type == "moe" and not 1 <= self.moe_top_k <= self.moe_experts:
            raise ValueError("moe_top_k 必须在 [1, moe_experts] 内")
        if self.num_metrics != 9 or self.num_device_parameters != 6:
            raise ValueError("冻结协议要求 9 个指标与 6 类器件参数")

    @classmethod
    def load(cls, path: Path | str) -> "ZeroSimConfig":
        return cls(**json.loads(Path(path).read_text(encoding="utf-8")))

    def to_dict(self) -> dict[str, object]:
        return asdict(self)
