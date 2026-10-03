from __future__ import annotations

import argparse
import json
import sys

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.circuit_ir import circuit_topology_hash, parse_circuit  # noqa: E402
from src.neural_memory.data import ExperimentManifest, HistoryReader  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate the frozen 8/10/2 ZeroSim dataset contract")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--allow-incomplete-data", action="store_true")
    args = parser.parse_args()
    manifest = ExperimentManifest.load(args.manifest)
    hashes: dict[str, str] = {}
    report = []
    for entry in manifest.entries:
        topology_hash = circuit_topology_hash(parse_circuit(entry.circuit_path, entry.parameter_path))
        if topology_hash in hashes:
            raise ValueError(
                f"拓扑重复：{entry.topology_id} 与 {hashes[topology_hash]} 的 canonical hash 相同"
            )
        hashes[topology_hash] = entry.topology_id
        levels = {
            "initial_train": ("train_visible",),
            "sequential": ("train_visible", "hidden_eval"),
            "final_blind": ("final_blind",),
        }[entry.role]
        reader = HistoryReader(entry.database_path, entry.topology_id)
        stats = reader.statistics(access_levels=levels)
        if not args.allow_incomplete_data:
            reader.assert_ready(entry.expected_usable_points, access_levels=levels)
        report.append({
            "topology_id": entry.topology_id,
            "role": entry.role,
            "topology_hash": topology_hash,
            **stats,
            "expected_usable_points": entry.expected_usable_points,
        })
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
