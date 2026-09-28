from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Iterator, Sequence

import torch
from torch.utils.data import Sampler

from ..contracts import SampleRecord


class TopologyBalancedBatchSampler(Sampler[list[int]]):
    """Equal examples per selected topology, with deterministic epoch shuffling."""

    def __init__(
        self,
        records: Sequence[SampleRecord],
        *,
        batch_size: int,
        topologies_per_batch: int,
        seed: int = 0,
        drop_last: bool = False,
        rank: int = 0,
        world_size: int = 1,
    ) -> None:
        if batch_size <= 0 or topologies_per_batch <= 0:
            raise ValueError("batch_size 与 topologies_per_batch 必须为正数")
        if batch_size % topologies_per_batch:
            raise ValueError("batch_size 必须能被 topologies_per_batch 整除")
        grouped: dict[str, list[int]] = defaultdict(list)
        for index, record in enumerate(records):
            grouped[record.topology_id].append(index)
        if topologies_per_batch > len(grouped):
            raise ValueError("topologies_per_batch 超过数据集拓扑数")
        self.groups = dict(grouped)
        self.batch_size = batch_size
        self.topologies_per_batch = topologies_per_batch
        self.per_topology = batch_size // topologies_per_batch
        self.seed = seed
        self.drop_last = drop_last
        self.rank = rank
        self.world_size = world_size
        self.epoch = 0

    def set_epoch(self, epoch: int) -> None:
        self.epoch = int(epoch)

    def __len__(self) -> int:
        batches = len([index for indices in self.groups.values() for index in indices]) / self.batch_size
        count = math.floor(batches) if self.drop_last else math.ceil(batches)
        return math.ceil(count / self.world_size)

    def __iter__(self) -> Iterator[list[int]]:
        generator = torch.Generator().manual_seed(self.seed + self.epoch)
        topology_ids = sorted(self.groups)
        shuffled = {
            topology: torch.tensor(indices)[torch.randperm(len(indices), generator=generator)].tolist()
            for topology, indices in self.groups.items()
        }
        cursors = {topology: 0 for topology in topology_ids}
        total_batches = math.floor(sum(map(len, self.groups.values())) / self.batch_size) if self.drop_last else math.ceil(sum(map(len, self.groups.values())) / self.batch_size)
        for batch_index in range(total_batches):
            permutation = torch.randperm(len(topology_ids), generator=generator).tolist()
            chosen = [topology_ids[index] for index in permutation[: self.topologies_per_batch]]
            batch: list[int] = []
            for topology in chosen:
                for _ in range(self.per_topology):
                    if cursors[topology] >= len(shuffled[topology]):
                        shuffled[topology] = torch.tensor(self.groups[topology])[
                            torch.randperm(len(self.groups[topology]), generator=generator)
                        ].tolist()
                        cursors[topology] = 0
                    batch.append(shuffled[topology][cursors[topology]])
                    cursors[topology] += 1
            if batch_index % self.world_size == self.rank:
                yield batch
