from __future__ import annotations

import logging

from pathlib import Path
from typing import (
    Optional,
    Sequence,
    Tuple,
)

import numpy as np

from ..base import (
    Sampler_Optimizer as _Sampler_Optimizer,
)


__all__ = ["LHS_Sampler"]


class LHS_Sampler(_Sampler_Optimizer):

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
        self.seed_sequence = np.random.SeedSequence(seed)

    def generate_sample_point(
        self,
        n_points: int,
        n_workers: Optional[int] = None,
    ) -> np.ndarray:
        """
        LHS 必须一次性生成完整设计。

        n_workers 仅用于保持采样器接口一致，
        实际仿真并行由 Simulator 负责。
        """

        del n_workers

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

        self.logger.info("开始 LHS 采样：points=%d", n_points)
        generator = np.random.default_rng(self.seed_sequence.spawn(1)[0])

        dimension = len(
            self.bounds
        )

        # 每个维度分别生成 0 到 n_points-1 的排列
        stratum_indices = np.column_stack(
            [
                generator.permutation(
                    n_points
                )

                for _ in range(
                    dimension
                )
            ]
        )

        # 在每个分层区间中随机取点
        unit_samples = (
            stratum_indices
            + generator.random(
                size=(
                    n_points,
                    dimension,
                )
            )
        ) / n_points

        bound_array = np.asarray(
            self.bounds,
            dtype=float,
        )

        lower_array = (
            bound_array[:, 0]
            .reshape(1, -1)
        )

        upper_array = (
            bound_array[:, 1]
            .reshape(1, -1)
        )

        continuous_samples = (
            lower_array
            + unit_samples
            * (
                upper_array
                - lower_array
            )
        )

        result = self._project_to_legal_grid(continuous_samples)
        self.logger.info("LHS 采样完成：shape=%s", result.shape)
        return result
