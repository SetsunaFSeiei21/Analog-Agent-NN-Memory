import GPy
import numpy as np

from typing import Sequence, List, Tuple
from __future__ import annotations
from dataclasses import dataclass
from sklearn.preprocessing import StandardScaler

@dataclass
class AdditiveGPConfig: 
    
    kernel_variance: float = 1.0
    kernel_lengthscale: float = 1.0
    noise_variance: float = 1e-6
    optimize_messages: bool = False

class AdditiveGP:
    
    def __init__(self, X: np.ndarray, Y: np.ndarray, groups: Sequence[Sequence[int]], config: AdditiveGPConfig) -> None:
        
        self.config = config or AdditiveGPConfig()
        self.groups = self._normalized_group(groups, np.asarray(X).shape[1])
        self.x_scaler = StandardScaler()
        self.y_scaler = StandardScaler()
        
        self.X_raw = self._as_2d(X, "X")
        self.Y_raw = self._as_2d(Y, "Y")
        if self.X_raw.shape[0] != self.Y_raw.shape[0]:
            raise ValueError("X and Y must have the same number of samples.")
        
        self.X = self.x_scaler.fit_transform(self.X_raw)
        self.Y = self.y_scaler.fit_transform(self.Y_raw)
        self.output_dim = self.Y_raw.shape[1]
        self.models: List[GPy.models.GPRegression] = []
        self._fit_models()
        
    def _kernel(self, input_dim: int) -> GPy.kern.RBF:
        
        return GPy.kern.RBF(
            input_dim = input_dim,
            variance = self.config.kernel_variance,
            lengthscale = self.config.kernel_lengthscale,
            ARD = True
        )
        
    def _fit_models(self) -> None:
        
        self.models.clear()
        target_share = self.Y / max(len(self.groups), 1) # 这里在读了 MOSTAR 的论文后再考虑优化
        for group in self.groups:
            x_group = self.X[:, group]
            model = GPy.models.GPRegression(x_group, target_share, self._kernel(x_group.shape[1]))
            model.Gaussian_noise.variance = self.config.noise_variance
            model.Gaussian_noise.variance.constrain_bounded(1e-10, 1e-2, warning=False)
            self.models.append(model)
            
    def optimize(self, max_iters: int = 1000) -> None:
        
        for model in self.models:
            model.optimize(
                messages = self.config.optimize_messages,
                optimizer = "lbfgs",
                max_iter = max_iters
            )
            
    def predicted_scaled(self, X_new: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
        
        X_new_2d = self._as_2d(X_new, "X_new")
        X_scale = self.x_scaler.transform(X_new_2d)
        mean = np.zeros((X_scale.shape[0], self.output_dim), dtype=float)
        variance = np.zeros_like(mean)
        
        for group, model in zip(self.groups, self.models):
            sub_mean, sub_var = model.predict(X_scale[:, group])
            mean += sub_mean
            variance += np.maximum(sub_var, 0.0)
        
        return mean, variance
    
    def forward(self, X_new: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
        
        scale_mean, scale_var = self.predicted_scaled(X_new)
        mean = self.y_scaler.inverse_transform(scale_mean)
        variance = scale_var * np.square(self.y_scaler.scale_)
        
        return mean, variance
        
    @staticmethod
    def _as_2d(input: np.ndarray, name: str) -> np.ndarray:
        
        array = np.asarray(input, dtype=float)
        if array.ndim == 1:
            array = array.reshape(1,-1)
        if array.ndim != 2:
            raise ValueError(f"{name} must be a 2-D array.")
        
        return array
        
    @staticmethod
    def _normalized_group(groups: Sequence[Sequence[int]], dim: int) -> List[List[int]]:
        
        if not groups:
            return [list(range(dim))]
        normalize = [list(group) for group in groups]
        flat = [index for group in normalize for index in group]
        if sorted(flat) != list(range(dim)):
            raise ValueError(
                "groups must cover every input dimension exactly once. "
                f"Expected 0..{dim - 1}, got {sorted(flat)}."
            )
            
        return normalize