from __future__ import annotations

import argparse
import json
import sys

from dataclasses import replace
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.neural_memory.model import ZeroSimConfig  # noqa: E402
from src.neural_memory.training import TrainingConfig, train_from_manifest  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Train the ZeroSim neural-memory backbone")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--model-config", type=Path, required=True)
    parser.add_argument("--training-config", type=Path, required=True)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--missing-policy", choices=["masked", "sentinel"], default="masked")
    parser.add_argument("--z-missing", type=float, default=-20.0)
    parser.add_argument("--head-type", choices=["shared", "metric_specific", "moe"], default=None)
    parser.add_argument("--batch-size", type=int, default=64)
    parser.add_argument("--topologies-per-batch", type=int, default=4)
    parser.add_argument("--num-workers", type=int, default=4)
    parser.add_argument("--device", default=None)
    parser.add_argument("--history-output", type=Path, default=None)
    args = parser.parse_args()

    model_config = ZeroSimConfig.load(args.model_config)
    if args.head_type is not None:
        model_config = replace(model_config, head_type=args.head_type)
    training_config = TrainingConfig(**json.loads(args.training_config.read_text(encoding="utf-8")))
    artifacts = train_from_manifest(
        args.manifest,
        model_config=model_config,
        training_config=training_config,
        checkpoint_path=args.checkpoint,
        missing_policy=args.missing_policy,
        z_missing=args.z_missing,
        batch_size=args.batch_size,
        topologies_per_batch=args.topologies_per_batch,
        num_workers=args.num_workers,
        device=args.device,
    )
    if args.history_output:
        args.history_output.parent.mkdir(parents=True, exist_ok=True)
        args.history_output.write_text(json.dumps(artifacts.history, indent=2), encoding="utf-8")
    print(json.dumps({
        "checkpoint": str(artifacts.checkpoint_path),
        "train_size": artifacts.train_size,
        "validation_size": artifacts.validation_size,
        "epochs_completed": len(artifacts.history),
    }))


if __name__ == "__main__":
    main()
