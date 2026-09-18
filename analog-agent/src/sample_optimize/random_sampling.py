import numpy as np

from multiprocessing import Pool
from pathlib import Path
from typing import List, Sequence, Tuple

from ..base import Sampler_Optimizer as _Sampler_Optimizer

__all__ = ["Random_Sampler"]

class Random_Sampler(_Sampler_Optimizer):

    def __init__(
        self,
        circuit_param_path: Path,
        parameter_name_lst: Sequence[str],
        bounds: Sequence[Tuple[float, float, float]],
        seed: int = 42,
    ) -> None:

        super().__init__(
            circuit_param_path,
            parameter_name_lst,
            bounds,
            seed,
        )

        self.seed_sequence = np.random.SeedSequence(seed)

    def generate_chunk(
        self,
        args: Tuple[np.random.SeedSequence, int],
    ) -> np.ndarray:

        seed_sequence, chunk_size = args

        rng = np.random.Generator(
            np.random.PCG64(seed_sequence)
        )

        columns: List[np.ndarray] = []

        for lower_bound, upper_bound, step in self.bounds:
            grid = np.arange(
                lower_bound,
                upper_bound + step * 0.1,
                step,
            )

            tolerance = (
                max(
                    1.0,
                    abs(lower_bound),
                    abs(upper_bound),
                )
                * 1e-12
            )

            grid = grid[
                grid <= upper_bound + tolerance
            ]

            column = rng.choice(
                grid,
                size=chunk_size,
                replace=True,
            )

            columns.append(column)

        return np.column_stack(columns)

    def generate_sample_point(
        self,
        n_points: int,
        n_workers: int,
    ) -> np.ndarray:

        if (
            isinstance(n_points, bool)
            or not isinstance(n_points, int)
        ):
            raise TypeError("n_points must be an integer.")

        if (
            isinstance(n_workers, bool)
            or not isinstance(n_workers, int)
        ):
            raise TypeError("n_workers must be an integer.")

        if n_points <= 0:
            raise ValueError(
                "n_points must be greater than 0."
            )

        if n_workers <= 0:
            raise ValueError(
                "n_workers must be greater than 0."
            )

        worker_count = min(
            n_points,
            n_workers,
        )

        base_chunk_size, remainder = divmod(
            n_points,
            worker_count,
        )

        chunk_sizes = [
            base_chunk_size
            + int(worker_index < remainder)
            for worker_index in range(worker_count)
        ]

        child_seed_sequences = (
            self.seed_sequence.spawn(worker_count)
        )

        tasks = [
            (
                seed_sequence,
                chunk_size,
            )
            for seed_sequence, chunk_size in zip(
                child_seed_sequences,
                chunk_sizes,
            )
        ]

        if worker_count == 1:
            chunks = [
                self.generate_chunk(tasks[0])
            ]
        else:
            with Pool(
                processes=worker_count,
            ) as pool:
                chunks = pool.map(
                    self.generate_chunk,
                    tasks,
                )

        result = np.concatenate(
            chunks,
            axis=0,
        )

        return result