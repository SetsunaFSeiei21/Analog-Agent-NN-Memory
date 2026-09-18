from __future__ import annotations

from pathlib import Path
from typing import (
    Optional,
    Sequence,
    Tuple,
)

import numpy as np
from scipy.stats import qmc

from ..base import (
    Sampler_Optimizer as _Sampler_Optimizer,
)


__all__ = ["Sobol_Sampler"]


class Sobol_Sampler(_Sampler_Optimizer):

    def __init__(
        self,
        circuit_param_path: Path,
        parameter_name_lst: Sequence[str],
        bounds: Sequence[
            Tuple[float, float, float]
        ],
        seed: int = 42,
    ) -> None:

        super().__init__(
            circuit_param_path,
            parameter_name_lst,
            bounds,
            seed,
        )

    def generate_sample_point(
        self,
        n_points: int,
        n_workers: Optional[int] = None,
    ) -> np.ndarray:
        """
        Sobol 必须使用一个采样引擎生成完整序列。

        n_workers 仅用于保持统一接口，
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

        # 正整数 n 是 2 的幂，当且仅当：
        #
        # n & (n - 1) == 0
        if n_points & (n_points - 1):

            raise ValueError(
                "n_points 必须为 2 的幂，"
                f"现在为 {n_points}"
            )

        m = (
            n_points.bit_length()
            - 1
        )

        sampler = qmc.Sobol(
            d=len(self.bounds),
            scramble=True,
            seed=self.seed,
        )

        unit_samples = (
            sampler.random_base2(
                m=m
            )
        )

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

        return self._project_to_legal_grid(
            continuous_samples
        )