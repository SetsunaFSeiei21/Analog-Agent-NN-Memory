from __future__ import annotations

import argparse
import json
import sys

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.neural_memory.inference import ZeroSimPredictor  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Run one ZeroSim prediction")
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--topology-id", required=True)
    parser.add_argument("--circuit", type=Path, required=True)
    parser.add_argument("--parameters-file", type=Path, required=True)
    parser.add_argument("--design-json", type=Path, required=True)
    parser.add_argument("--device", default=None)
    args = parser.parse_args()
    predictor = ZeroSimPredictor.from_checkpoint(args.checkpoint, device=args.device)
    topology = predictor.compile_topology(args.topology_id, args.circuit, args.parameters_file)
    design = json.loads(args.design_json.read_text(encoding="utf-8"))
    prediction = predictor.predict(topology, design)
    print(json.dumps({
        "topology_id": prediction.topology_id,
        "metrics": prediction.metrics,
        "embedding": prediction.embedding,
        "backbone_version": prediction.backbone_version,
        "adapter_version": prediction.adapter_version,
    }, indent=2))


if __name__ == "__main__":
    main()
