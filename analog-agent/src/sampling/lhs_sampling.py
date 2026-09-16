import numpy as np

from ..base import Sampler_Optimizer
from pathlib import Path
from typing import Sequence, Tuple

class LHS_Sampler(Sampler_Optimizer):
    
    def __init__(
        self,
        circuit_param_path: Path,
        parameter_name_lst: Sequence[str],
        bounds: Sequence[Tuple[float, float, float]],
        seed: int = 42,
    ) -> None:
        
        super().__init__(circuit_param_path, parameter_name_lst, bounds, seed)
    
    def generate_sample_point(
        self,
        n_points: int,
        n_workers: int,
    ) -> np.ndarray:

        if n_points <= 0:
            raise ValueError("n_points must be greater than 0.")

        generator: np.random.Generator = np.random.default_rng(self.seed)

        # 参数维度数
        size = len(self.bounds)

        design_result = []

        # 每个维度分别生成 0 ~ n_points-1 的随机排列
        for _ in range(size):
            dim_result = generator.permutation(n_points)
            design_result.append(dim_result)

        # shape: (n_points, size)
        design_result_array = np.vstack(design_result).T

        # 将 [0, 1) 划分为 n_points 个区间
        sample_step = 1.0 / n_points

        lower_bound_array = (
            sample_step * design_result_array
        )

        upper_bound_array = (
            sample_step * (design_result_array + 1)
        )

        # 每个对应区间内随机取值
        uniform_result_array = generator.uniform(
            low=lower_bound_array,
            high=upper_bound_array,
        )

        # 真实参数范围
        real_bound_array = np.asarray(
            self.bounds,
            dtype=float,
        )

        real_lower_bound_array = (
            real_bound_array[:, 0].reshape(1, -1)
        )

        real_upper_bound_array = (
            real_bound_array[:, 1].reshape(1, -1)
        )

        # [0, 1) -> 真实参数空间
        real_result_array = (
            uniform_result_array
            * (
                real_upper_bound_array
                - real_lower_bound_array
            )
            + real_lower_bound_array
        )

        # 回代 step，寻找最近的合法离散值
        step_array = (
            real_bound_array[:, 2].reshape(1, -1)
        )

        real_step_num = np.rint(
            (
                real_result_array
                - real_lower_bound_array
            )
            / step_array
        ).astype(np.int64)

        sample_result = (
            real_lower_bound_array
            + real_step_num * step_array
        )

        # 防止越界
        sample_result = np.clip(
            sample_result,
            real_lower_bound_array,
            real_upper_bound_array,
        )

        return sample_result