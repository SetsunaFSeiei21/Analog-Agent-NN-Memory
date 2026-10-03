from __future__ import annotations

import pytest


torch = pytest.importorskip("torch")

from src.neural_memory.model import ZeroSimConfig, ZeroSimModel  # noqa: E402


@pytest.mark.parametrize("head_type", ["shared", "metric_specific", "moe"])
def test_model_forward_all_heads(head_type: str) -> None:
    config = ZeroSimConfig(
        d_model=32,
        num_encoder_layers=2,
        local_attention_layers=1,
        num_heads=4,
        dim_feedforward=64,
        parameter_injection_layer=2,
        decoder_layers=1,
        head_type=head_type,
        adapter_rank=4,
    )
    model = ZeroSimModel(config)
    batch = {
        "device_type": torch.tensor([[0, 1, 1, 2, 2]]),
        "pin_role": torch.tensor([[0, 1, 2, 1, 2]]),
        "port_role": torch.tensor([[0, 1, 0, 0, 3]]),
        "device_index": torch.tensor([[-1, 0, 0, 1, 1]]),
        "token_mask": torch.ones((1, 5), dtype=torch.bool),
        "local_attention": torch.ones((1, 5, 5), dtype=torch.bool),
        "device_parameters": torch.randn((1, 2, 6)),
        "device_parameter_mask": torch.ones((1, 2, 6), dtype=torch.bool),
        "device_types": torch.tensor([[1, 2]]),
    }
    output = model(batch)
    assert output["prediction"].shape == (1, 9)
    assert output["embedding"].shape == (1, 32)
    if head_type == "moe":
        assert output["router_logits"].shape == (1, 9, 4)
