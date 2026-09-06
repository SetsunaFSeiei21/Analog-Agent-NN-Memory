from __future__ import annotations

import numpy as np

from GP import AdditiveGP
from typing import Callable, Sequence, Tuple, List, Optional, Dict
from scipy.stats import norm
from scipy.optimize import differential_evolution
from dataclasses import dataclass

SimulationFN = Callable[[Sequence[float]], Sequence[float]]

@dataclass
class MetricSpec:
    
    name: str
    target: float
    direction: str
    
DEFAULT_METRICS = (
    MetricSpec("gain_db", 40.0, "gte"),
    MetricSpec("ugbw_hz", 5_000_000.0, "gte"),
    MetricSpec("phase_margin_deg", 60.0, "gte"),
    MetricSpec("current_a", 0.0, "minimize"),
)


def random_sample(
    count: int, 
    bounds: np.ndarray,
    simulator: SimulationFN,
    rng: np.random.Generator
) -> Tuple[np.ndarray, np.ndarray]:
    
    xs: List[np.ndarray] = []
    ys: List[np.ndarray] = []
    for _ in range(count):
        x = rng.uniform(bounds[:, 0], bounds[:, 1])
        y = np.asarray(simulator(x), dtype=float)
        xs.append(x)
        ys.append(y)
    
    return np.vstack(xs), np.vstack(ys)

class BayesianOptimization:
    
    def __init__(self,
        groups: Sequence[Sequence[int]],
        bounds: Sequence[Tuple[float, float]],
        best_x: Sequence[float],
        best_y: Sequence[float],
        simulation_fn: SimulationFN,
        metric_specs: Sequence[MetricSpec] = DEFAULT_METRICS,
        constraints: Optional[Dict[int, int]] = None, # constraints 在数据结构和执行方式上已经假设成了单向映射，所以后续要对constraints进行处理
        random_seed: int = 42
        ):
        self.bounds = np.asarray(bounds, dtype=float)
        self.groups = [list(group) for group in groups]
        self.best_x = np.asarray(best_x, dtype=float)
        self.best_y = np.asarray(best_y, dtype=float)
        self.metric_specs = list(metric_specs)
        self.constraints = constraints or {}
        self.simulation_fn = simulation_fn
        self.rng = np.random.default_rng(random_seed)
        
    def _probability_score(self, mean: np.ndarray, variance: np.ndarray) -> float:
        
        score = 0.0
        for index, spec in enumerate(self.metric_specs):
            sigma = float(np.sqrt(max(variance[index], 1e-18)))
            mu = float(mean[index])
            if spec.direction == "gte":
                score += float(norm.cdf((mu - spec.target) / sigma))
            elif spec.direction == "lte":
                score += float(norm.cdf((spec.target - mu) / sigma))
            elif spec.direction == "minimize":
                best = self.best_y[index] if index < len(self.best_y) else mu
                score += float(norm.cdf((best - mu) / sigma))
            elif spec.direction == "maximize":
                best = self.best_y[index] if index < len(self.best_y) else mu
                score += float(norm.cdf((mu - best) / sigma))
            else:
                raise ValueError(f"Unknown metric direction: {spec.direction}")
            
        return score
        
    def apply_constraints(self, x: np.ndarray, constraints: Dict[int, int]) -> np.ndarray:
        
        constrainted = np.asarray(x, dtype=float).copy()
        if constraints:
            for source, target in constraints.items():
                constrainted[target] = constrainted[source]
                
        return constrainted
        
    def _sub_constraints(self, group: Sequence[int]) -> Dict[int, int]:
        
        local: Dict[int, int] = {}
        for source, target in self.constraints.items():
            if source in group and target in group:
                local[group.index(source)] = group.index(target)
                
        return local
        
    def _optimize_group(self, group: Sequence[int]) -> np.ndarray:
        
        sub_bound = self.bounds[list(group)]
        sub_constraints = self._sub_constraints(group)
        
        def objective(sub_x: np.ndarray) -> float:
            sub_x = self.apply_constraints(sub_x, sub_constraints)
            candidate = self.best_x.copy()
            for index, value in zip(group, sub_x):
                candidate[index] = value
            candidate = self.apply_constraints(candidate, self.constraints)
            mean_2d, variance_2d = self.model.forward(candidate.reshape(1, -1))
            mean = mean_2d[0]
            variance = variance_2d[0]
            
            return -self._probability_score(mean, variance)
        
        result = differential_evolution(
            objective,
            bounds=[tuple(row) for row in sub_bound],
            seed=int(self.rng.integers(0, 2**31 - 1)),
            maxiter=80,
            popsize=12,
            polish=True,
            updating="immediate",
        )
        
        return self.apply_constraints(result.x, sub_constraints)
    
    def _connect_group(self, sub_xs: Sequence[Sequence[float]]) -> np.ndarray:
        
        x = np.zeros(self.bounds.shape[0], dtype=float)
        for group, sub_x in zip(self.groups, sub_xs):
            for index, value in zip(group, sub_x):
                x[index] = value
                
        return self.apply_constraints(x, self.constraints)
    
    def _is_better(self, y: np.ndarray) -> bool:
        
        feasible = True
        for index, spec in enumerate(self.metric_specs):
            if spec.direction == "gte" and y[index] < spec.target:
                feasible = False
            if spec.direction == "lte" and y[index] > spec.target:
                feasible = False
        current_index = next(
            (idx for idx, spec in enumerate(self.metric_specs) if spec.direction == "minimize"),
            len(self.metric_specs) - 1,
        ) 
        return feasible and y[current_index] < self.best_y[current_index]
        
        
    
    def bayesian_optimization(
        self,
        init_x: np.ndarray,
        init_y: np.ndarray,
        n_iters: int = 50,
        gp_max_iters: int = 100,
    ) -> Tuple[np.ndarray, np.ndarray]:
        X_all = np.asarray(init_x, dtype=float)
        Y_all = np.asarray(init_y, dtype=float)
        
        for iteration in range(1, n_iters + 1):
            
            self.model = AdditiveGP(X_all, Y_all, self.groups)
            self.model.optimize(gp_max_iters)
            sub_xs = [self._optimize_group(group) for group in self.groups]
            x_next = self._connect_group(sub_xs)
            y_next = np.asarray(self.simulation_fn(x_next), dtype=float)
            
            X_all = np.vstack([X_all, x_next])
            Y_all = np.vstack([Y_all, y_next])
            
            if self._is_better(y_next):
                self.best_x = x_next
                self.best_y = y_next
                
            print(f"iteration={iteration} y_next={y_next.tolist()} best_y={self.best_y.tolist()}")
        
        return X_all, Y_all