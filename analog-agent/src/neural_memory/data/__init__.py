"""Data layer with lazy torch-dependent imports."""

from importlib import import_module


_EXPORTS = {
    "CircuitDataset": (".dataset", "CircuitDataset"),
    "CompiledTopology": (".dataset", "CompiledTopology"),
    "collate_circuit_samples": (".dataset", "collate_circuit_samples"),
    "HistoryReader": (".history_reader", "HistoryReader"),
    "ExperimentManifest": (".manifest", "ExperimentManifest"),
    "TopologyEntry": (".manifest", "TopologyEntry"),
    "TopologyBalancedBatchSampler": (".sampler", "TopologyBalancedBatchSampler"),
    "DEVICE_PARAMETER_ORDER": (".transforms", "DEVICE_PARAMETER_ORDER"),
    "TargetScaler": (".transforms", "TargetScaler"),
}

__all__ = list(_EXPORTS)


def __getattr__(name: str):
    if name not in _EXPORTS:
        raise AttributeError(name)
    module_name, attribute = _EXPORTS[name]
    value = getattr(import_module(module_name, __name__), attribute)
    globals()[name] = value
    return value
