from .history_store import SamplingHistoryStore
from .lhs_sampling import LHS_Sampler
from .random_sampling import Random_Sampler
from .sampling_controller import Sampling_Controller, SamplingResult
from .simulating import SimulationBatchResult, Simulator
from .sobol_sampling import Sobol_Sampler


__all__ = [
    "LHS_Sampler",
    "Random_Sampler",
    "SamplingHistoryStore",
    "SamplingResult",
    "Sampling_Controller",
    "SimulationBatchResult",
    "Simulator",
    "Sobol_Sampler",
]
from .point_simulation import OBSERVATION_SOURCES, PointSimulationResult, PointSimulator

__all__ += ["OBSERVATION_SOURCES", "PointSimulationResult", "PointSimulator"]

__all__ += ["DatasetSamplingController", "DatasetSamplingResult"]


def __getattr__(name):
    if name in {"DatasetSamplingController", "DatasetSamplingResult"}:
        from .advanced.controller import DatasetSamplingController, DatasetSamplingResult
        return {"DatasetSamplingController": DatasetSamplingController,
                "DatasetSamplingResult": DatasetSamplingResult}[name]
    raise AttributeError(name)
