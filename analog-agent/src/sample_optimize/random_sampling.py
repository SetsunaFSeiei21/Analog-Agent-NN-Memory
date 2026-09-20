from __future__ import annotations

import logging

from multiprocessing import Pool
from pathlib import Path
from typing import (
    List,
    Optional,
    Sequence,
    Tuple,
)

import numpy as np

from ..base import (
    Sampler_Optimizer as _Sampler_Optimizer,
)


__all__ = ["Random_Sampler"]


class Random_Sampler(_Sampler_Optimizer):

    def __init__(
        self,
        circuit_param_path: Path,
        parameter_name_lst: Sequence[str],
        bounds: Sequence[
            Tuple[float, float, float]
        ],
        seed: int = 42,
        logger: Optional[logging.Logger] = None,
    ) -> None:

        super().__init__(
            circuit_param_path,
            parameter_name_lst,
            bounds,
            seed,
            logger,
        )

        self.seed_sequence = (
            np.random.SeedSequence(seed)
        )

    def generate_chunk(
        self,
        args: Tuple[
            np.random.SeedSequence,
            int,
        ],
    ) -> np.ndarray:

        seed_sequence, chunk_size = args

        rng = np.random.Generator(
            np.random.PCG64(
                seed_sequence
            )
        )

        columns: List[np.ndarray] = []

        for (
            lower_bound,
            upper_bound,
            step,
        ) in self.bounds:

            step_ratio = (
                upper_bound - lower_bound
            ) / step

            tolerance = (
                max(
                    1.0,
                    abs(step_ratio),
                )
                * 1e-12
            )

            max_step_index = int(
                np.floor(
                    step_ratio + tolerance
                )
            )

            step_indices = rng.integers(0, max_step_index + 1, size=chunk_size)
            column = lower_bound + step_indices * step

            columns.append(column)

        return np.column_stack(
            columns
        )

    def generate_sample_point(
        self,
        n_points: int,
        n_workers: Optional[int] = None,
    ) -> np.ndarray:

        if (
            isinstance(n_points, bool)
            or not isinstance(n_points, int)
        ):
            raise TypeError(
                "n_points must be an integer."
            )

        if n_points <= 0:
            raise ValueError(
                "n_points must be greater than 0."
            )

        if n_workers is None:
            n_workers = 1

        if (
            isinstance(n_workers, bool)
            or not isinstance(n_workers, int)
        ):
            raise TypeError(
                "n_workers must be an integer."
            )

        if n_workers <= 0:
            raise ValueError(
                "n_workers must be greater than 0."
            )

        worker_count = min(
            n_points,
            n_workers,
        )
        self.logger.info("开始 Random 采样：points=%d, workers=%d", n_points, worker_count)

        (
            base_chunk_size,
            remainder,
        ) = divmod(
            n_points,
            worker_count,
        )

        chunk_sizes = [
            (
                base_chunk_size
                + int(
                    worker_index
                    < remainder
                )
            )

            for worker_index
            in range(worker_count)
        ]

        child_seed_sequences = (
            self.seed_sequence.spawn(
                worker_count
            )
        )

        tasks = list(
            zip(
                child_seed_sequences,
                chunk_sizes,
            )
        )

        if worker_count == 1:

            chunks = [
                self.generate_chunk(
                    tasks[0]
                )
            ]

        else:

            with Pool(
                processes=worker_count
            ) as pool:

                chunks = pool.map(
                    self.generate_chunk,
                    tasks,
                )

        result = np.concatenate(
            chunks,
            axis=0,
        )
        self.logger.info("Random 采样完成：shape=%s", result.shape)
        return result
