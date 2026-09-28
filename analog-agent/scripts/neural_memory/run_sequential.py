from __future__ import annotations

import argparse
import json
import sys

from dataclasses import asdict
from pathlib import Path

import torch
from torch.utils.data import DataLoader


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.neural_memory.data import (  # noqa: E402
    CircuitDataset, CompiledTopology, ExperimentManifest, HistoryReader, collate_circuit_samples,
)
from src.neural_memory.memory import (  # noqa: E402
    AdaptationConfig, ConsolidationConfig, MemoryRegistry, ReplayBuffer,
    SequentialConfig, SequentialExperiment, SequentialTask,
)
from src.neural_memory.memory.sequential import select_probe_indices  # noqa: E402
from src.neural_memory.training import load_checkpoint  # noqa: E402


def loader(records, topologies, scaler, batch_size: int, *, shuffle: bool = False):
    dataset = CircuitDataset(records, topologies, scaler)
    return DataLoader(dataset, batch_size=batch_size, shuffle=shuffle, collate_fn=collate_circuit_samples)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run R²-selected sequential neural-memory evaluation")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--registry", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--probe-k", type=int, choices=[5, 10, 15, 20, 25], default=20)
    parser.add_argument("--order-seed", type=int, default=0)
    parser.add_argument("--model-seed", type=int, default=0)
    parser.add_argument("--adaptation-steps", type=int, default=100)
    parser.add_argument("--adaptation-lr", type=float, default=1e-3)
    parser.add_argument("--full-finetune", action="store_true")
    parser.add_argument("--consolidation-interval", type=int, choices=[0, 1, 3, 5, 10], default=5)
    parser.add_argument("--consolidation-steps", type=int, default=500)
    parser.add_argument("--replay-per-topology", type=int, default=256)
    parser.add_argument("--batch-size", type=int, default=128)
    parser.add_argument("--device", default=None)
    parser.add_argument("--open-final-blind", action="store_true")
    args = parser.parse_args()

    model, scaler, metadata = load_checkpoint(args.checkpoint, map_location="cpu")
    manifest = ExperimentManifest.load(args.manifest)
    all_entries = manifest.by_role("sequential") + manifest.by_role("final_blind")
    topologies = {entry.topology_id: CompiledTopology.from_entry(entry) for entry in all_entries}
    registry = MemoryRegistry(
        args.registry,
        backbone_version=str(metadata.get("backbone_version", "backbone-v0")),
    )
    use_mask = scaler.missing_policy == "masked"
    experiment = SequentialExperiment(
        model=model,
        target_scaler=scaler,
        registry=registry,
        replay_buffer=ReplayBuffer(args.replay_per_topology, args.order_seed),
        adaptation_config=AdaptationConfig(
            steps=args.adaptation_steps,
            learning_rate=args.adaptation_lr,
            full_finetune=args.full_finetune,
            use_loss_mask=use_mask,
        ),
        consolidation_config=ConsolidationConfig(
            interval=args.consolidation_interval,
            steps=args.consolidation_steps,
            use_loss_mask=use_mask,
        ),
        config=SequentialConfig(
            probe_k=args.probe_k,
            order_seed=args.order_seed,
            model_seed=args.model_seed,
            open_final_blind=args.open_final_blind,
        ),
        replay_loader_factory=lambda records: loader(
            records, topologies, scaler, args.batch_size, shuffle=True
        ),
        device=args.device,
    )

    sequential_tasks = []
    for entry in manifest.by_role("sequential"):
        reader = HistoryReader(entry.database_path, entry.topology_id)
        visible = reader.read(access_levels=("train_visible",))
        indices = set(select_probe_indices(
            visible, k=args.probe_k, order_seed=args.order_seed, topology_id=entry.topology_id
        ))
        probe = [record for index, record in enumerate(visible) if index in indices]
        hidden = reader.read(access_levels=("hidden_eval",))
        if not hidden:
            raise ValueError(f"{entry.topology_id} 缺少 hidden_eval 分区")
        sequential_tasks.append(SequentialTask(
            topology_id=entry.topology_id,
            probe_loader=loader(probe, topologies, scaler, args.probe_k),
            hidden_loader=loader(hidden, topologies, scaler, args.batch_size),
            replay_records=tuple(probe),
        ))
    outcomes = list(experiment.run(sequential_tasks))

    if args.open_final_blind:
        final_tasks = []
        for entry in manifest.by_role("final_blind"):
            records = HistoryReader(entry.database_path, entry.topology_id).read(
                access_levels=("final_blind",)
            )
            indices = set(select_probe_indices(
                records, k=args.probe_k, order_seed=args.order_seed, topology_id=entry.topology_id
            ))
            probe = [record for index, record in enumerate(records) if index in indices]
            hidden = [record for index, record in enumerate(records) if index not in indices]
            final_tasks.append(SequentialTask(
                topology_id=entry.topology_id,
                probe_loader=loader(probe, topologies, scaler, args.probe_k),
                hidden_loader=loader(hidden, topologies, scaler, args.batch_size),
                replay_records=(),
                is_final_blind=True,
            ))
        outcomes.extend(experiment.run(final_tasks))

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps([asdict(outcome) for outcome in outcomes], indent=2), encoding="utf-8")
    print(json.dumps({"tasks": len(outcomes), "output": str(args.output), "registry": str(args.registry)}))


if __name__ == "__main__":
    main()
