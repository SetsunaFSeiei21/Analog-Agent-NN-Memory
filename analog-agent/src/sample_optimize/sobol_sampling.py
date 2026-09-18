import math
import numpy as np

from ..base import Sampler_Optimizer as _Sampler_Optimizer
from typing import Sequence, Tuple
from pathlib import Path
from scipy.stats import qmc

__all__ = ["Sobol_Sampler"]

class Sobol_Sampler(_Sampler_Optimizer):
    
    def __init__(
        self,
        circuit_param_path: Path,
        parameter_name_lst: Sequence[str],
        bounds: Sequence[Tuple[float, float, float]],
        seed: int = 42,
    ) -> None:
        
        super().__init__(circuit_param_path, parameter_name_lst, bounds, seed)
    
    def generate_sample_point(self, n_points: int, n_workers: int) -> np.ndarray:
        
        if n_points <= 0:
            raise ValueError("n_points 必须大于 0")
        if not test_result % 1 == 0:
            raise ValueError(f"采样数必须为2的幂数，现在为{n_points}")
        sampler = qmc.Sobol(d = len(self.bounds), scramble=True, seed=self.seed)
        test_result = math.log2(n_points)
        m = int(math.log2(n_points))
        unit_result = sampler.random_base2(m=m)
        bound_array = np.array(self.bounds)
        lower_bound_array = bound_array[:, 0].reshape(1, -1)
        upper_bound_array = bound_array[:, 1].reshape(1, -1)
        step_array = bound_array[:, 2].reshape(1, -1)
        real_result_array = lower_bound_array + unit_result * (upper_bound_array - lower_bound_array)
        real_step_num = np.rint((real_result_array - lower_bound_array) / step_array).astype(np.int64)
        sample_result = lower_bound_array + real_step_num * step_array
        sample_result = np.clip(sample_result, lower_bound_array, upper_bound_array)
        
        return sample_result