# ZeroSim neural memory implementation

This package implements the frozen Sky130 single-ended-op-amp protocol. Version 1 accepts a top-level
`.subckt DUT VINP VINN VOUT VDD VSS`, Sky130 `M`/primitive `X` MOS devices, native `R`, `C`, and DC current
sources. User-defined nested subcircuits are intentionally rejected.

## Repository layout

```text
src/
├── circuit_ir/                 strict netlist, expressions, resolved devices, pin graph
├── sample_optimize/
│   ├── history_store.py        versioned SQLite data/access contract
│   └── point_simulation.py     one-point cache and real-SPICE-call accounting
└── neural_memory/
    ├── contracts.py            canonical nine-metric DTOs
    ├── data/                   manifest, read-only history adapter, transforms, batching
    ├── model/                  ZeroSim encoder/decoder, heads, low-rank adapters
    ├── training/               loss, physical-space evaluation, trainer, checkpoint
    ├── memory/                 R² selector, registry, adaptation, replay, consolidation
    ├── inference.py            checkpoint-backed prediction
    └── service.py              Analog Agent integration facade
```

The neural package reads `sampling_history.sqlite3`; CSV files remain compatibility exports and are not a
training source.

## Frozen data contract

The metric order is exact:

1. `DC_Gain_dB`
2. `UGF_Hz`
3. `Phase_Margin_deg`
4. `CMRR_dB`
5. `PSRR_Plus_dB`
6. `PSRR_Minus_dB`
7. `Slew_Rise_V_us`
8. `Slew_Fall_V_us`
9. `Power_Quiescent_uW`

Slew rate is stored as a non-negative magnitude. UGF, both slew rates, and quiescent power are transformed
with `log10`; other metrics remain linear. Mean and standard deviation are fitted once from only the
initial-topology training split and are frozen for validation, sequential tasks, final blind tasks, and
consolidation.

Two missing-target variants are supported:

- `masked`: missing values are ignored by masked Huber loss;
- `sentinel`: after standardization, missing values become exactly `-20.0` and the loss mask is disabled.

SQLite rows carry an access level:

- `train_visible`: may be used for training and K-shot probes;
- `hidden_eval`: evaluation controller only;
- `final_blind`: readable only after the final-blind gate is explicitly opened.

Cached point requests do not increment the real SPICE budget. A design collision with an inaccessible
partition is rejected instead of revealing or rerunning that point.

## Circuit representation and model

Every device pin becomes a graph token. Physical edges join pins on the same net; virtual edges join pins of
the same device. Index zero is a learned graph token. Token features contain device type, pin role, and fixed
DUT port role; there is no learned absolute node-index embedding.

Encoder layers interleave local graph attention with global attention. From the configured layer onward, a
pin attends only to the six parameter slots (`W`, `L`, `M`, `R`, `C`, `I`) of its own device. Nine learned
metric queries decode the graph. The output head can be:

- one shared MLP;
- nine metric-specific MLPs;
- four MLP experts with top-2 routing.

The checked-in presets are:

| preset | width | encoder layers | local layers | heads | FFN | first parameter layer |
|---|---:|---:|---:|---:|---:|---:|
| `dev` | 128 | 4 | 1 | 4 | 512 | 3 |
| `p0` | 256 | 6 | 2 | 8 | 1024 | 4 |
| `paper` | 512 | 6 | 2 | 8 | 2048 | 4 |

`p0` is the primary A800 80 GB run. `dev` is for contract checks; `paper` is the capacity-matched run.

## Dataset manifest

The manifest has exactly 8 initial, 10 sequential, and 2 final-blind topologies. Sequential
`arrival_index` values must be `0..9`. Each entry points to one circuit directory and defaults to 20,000
usable real-SPICE points.

```json
{
  "schema_version": 1,
  "root": "../sampling_database",
  "topologies": [
    {
      "topology_id": "initial_00",
      "role": "initial_train",
      "directory": "initial_00",
      "circuit_name": "initial_00",
      "expected_usable_points": 20000
    },
    {
      "topology_id": "sequential_00",
      "role": "sequential",
      "arrival_index": 0,
      "directory": "sequential_00"
    }
  ]
}
```

List all 20 entries in the real manifest. Validate counts, canonical topology uniqueness, schema, usable rows,
and real-call budget before training:

```bash
cd analog-agent
python scripts/neural_memory/validate_manifest.py --manifest configs/experiment_manifest.json
```

`--allow-incomplete-data` exists only for development fixtures.

## Training

Install neural dependencies in the target environment (use the CUDA build of PyTorch on A800):

```bash
python -m pip install -r requirements-neural-memory.txt
```

Primary masked training:

```bash
python scripts/neural_memory/train_zerosim.py \
  --manifest configs/experiment_manifest.json \
  --model-config configs/zerosim/p0.json \
  --training-config configs/zerosim/training_masked.json \
  --checkpoint checkpoints/zerosim-p0-seed0.pt \
  --missing-policy masked \
  --batch-size 64 --topologies-per-batch 4 --num-workers 8
```

Sentinel ablation:

```bash
python scripts/neural_memory/train_zerosim.py \
  --manifest configs/experiment_manifest.json \
  --model-config configs/zerosim/p0.json \
  --training-config configs/zerosim/training_sentinel.json \
  --checkpoint checkpoints/zerosim-p0-sentinel-seed0.pt \
  --missing-policy sentinel --z-missing -20.0
```

The training pipeline uses topology-balanced batches, per-topology deterministic train/validation splitting,
bf16 autocast on CUDA, AdamW, gradient clipping, early stopping on physical-space macro R², and a versioned
checkpoint containing the frozen scaler.

## Sequential memory experiment

For every incoming topology, select K probes using only the order seed. Candidate memories predict those
same probes. Selection ranks physical-space macro R² first, macro NRMSE only when R² is undefined or tied,
and finally the registry's stable insertion order. Supported K values are `5, 10, 15, 20, 25`; K=20 is the
primary setting.

```bash
python scripts/neural_memory/run_sequential.py \
  --manifest configs/experiment_manifest.json \
  --checkpoint checkpoints/zerosim-p0-seed0.pt \
  --registry runs/seed0-order0/memory \
  --output runs/seed0-order0/sequential.json \
  --probe-k 20 --model-seed 0 --order-seed 0 \
  --consolidation-interval 5
```

Use `--full-finetune` for the baseline. Set `--consolidation-interval 0` for no consolidation; ablations use
`1, 3, 5, 10`. Replay consolidation updates only the shared backbone and then rebases each stored memory from
its saved probe loader. The scaler never changes.

The two final topologies are skipped unless `--open-final-blind` is provided. Opening that flag should be a
one-time protocol decision after all model, seed, K, selection, and consolidation choices are frozen.

## Agent-facing interfaces

`NeuralMemoryService` exposes four operations:

- `select_memory(probe_loader)` — physical-space R² selection;
- `adapt(...)` — create and persist a topology adapter;
- `predict(topology, parameters, memory_id=...)` — nine physical-unit metrics plus embedding;
- `observe(point_simulator, parameters, ...)` — strict simulation/cache/access-level path.

The service deliberately does not expose hidden labels or final-blind rows. Controller code should pass only
`train_visible` probe loaders and use the evaluation runner for hidden metrics.

## Verification

```bash
cd analog-agent
PYTHONPATH=. python -m pytest -q
```

Tests cover the three repository circuits, topology hashing, SQLite migration, cache/access isolation, both
missing-target contracts, all three output heads, R²/NRMSE selection, deterministic probes, and the legacy
Phase 1 simulator integration.
