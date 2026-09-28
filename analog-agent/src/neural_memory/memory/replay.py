from __future__ import annotations

import hashlib
import random
from collections import defaultdict
from collections.abc import Sequence

from ..contracts import SampleRecord


class ReplayBuffer:
    """Deterministic per-topology reservoir; raw samples retain the frozen target scaler contract."""

    def __init__(self, capacity_per_topology: int = 256, seed: int = 0) -> None:
        if capacity_per_topology <= 0:
            raise ValueError("capacity_per_topology 必须为正数")
        self.capacity = capacity_per_topology
        self.seed = seed
        self._records: dict[str, list[SampleRecord]] = defaultdict(list)
        self._seen: dict[str, int] = defaultdict(int)

    def add(self, records: Sequence[SampleRecord]) -> None:
        for record in records:
            topology = record.topology_id
            self._seen[topology] += 1
            bucket = self._records[topology]
            if len(bucket) < self.capacity:
                bucket.append(record)
                continue
            digest = hashlib.sha256(
                f"{self.seed}:{topology}:{self._seen[topology]}:{record.sample_id}".encode()
            ).digest()
            rng = random.Random(int.from_bytes(digest[:8], "big"))
            replacement = rng.randrange(self._seen[topology])
            if replacement < self.capacity:
                bucket[replacement] = record

    def records(self) -> tuple[SampleRecord, ...]:
        return tuple(
            record
            for topology in sorted(self._records)
            for record in sorted(self._records[topology], key=lambda item: item.sample_id)
        )

    def by_topology(self) -> dict[str, tuple[SampleRecord, ...]]:
        return {topology: tuple(records) for topology, records in self._records.items()}
