from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

import numpy as np

from ..contracts import METRIC_NAMES
from ..training.evaluator import evaluate_predictions


@dataclass(frozen=True)
class CandidateScore:
    memory_id: str
    stable_index: int
    macro_r2: float | None
    macro_nrmse: float | None
    per_metric_r2: Mapping[str, float | None]
    per_metric_nrmse: Mapping[str, float | None]
    per_metric_variance: Mapping[str, float | None]
    per_metric_count: Mapping[str, int]
    used_nrmse_fallback: bool


@dataclass(frozen=True)
class SelectionResult:
    selected_memory_id: str
    selected_score: CandidateScore
    scores: tuple[CandidateScore, ...]


class R2MemorySelector:
    """Select memory by physical-space K-shot R², then NRMSE, then stable order."""

    def score(
        self,
        memory_id: str,
        stable_index: int,
        prediction: np.ndarray,
        target: np.ndarray,
        valid_mask: np.ndarray,
    ) -> CandidateScore:
        metrics = evaluate_predictions(prediction, target, valid_mask)
        variances: dict[str, float | None] = {}
        for index, name in enumerate(METRIC_NAMES):
            mask = np.asarray(valid_mask, dtype=bool)[..., index]
            values = np.asarray(target, dtype=float)[..., index][mask]
            variances[name] = float(np.var(values)) if len(values) >= 2 else None
        return CandidateScore(
            memory_id=memory_id,
            stable_index=stable_index,
            macro_r2=metrics.macro_r2,
            macro_nrmse=metrics.macro_nrmse,
            per_metric_r2=metrics.per_metric_r2,
            per_metric_nrmse=metrics.per_metric_nrmse,
            per_metric_variance=variances,
            per_metric_count=metrics.per_metric_count,
            used_nrmse_fallback=metrics.macro_r2 is None,
        )

    @staticmethod
    def _rank(score: CandidateScore) -> tuple[float, float, float, int]:
        has_r2 = score.macro_r2 is not None and np.isfinite(score.macro_r2)
        r2 = float(score.macro_r2) if has_r2 else -float("inf")
        nrmse = (
            float(score.macro_nrmse)
            if score.macro_nrmse is not None and np.isfinite(score.macro_nrmse)
            else float("inf")
        )
        return (float(has_r2), r2, -nrmse, -score.stable_index)

    def select(
        self,
        predictions: Mapping[str, np.ndarray],
        target: np.ndarray,
        valid_mask: np.ndarray,
        stable_indices: Mapping[str, int],
    ) -> SelectionResult:
        if not predictions:
            raise ValueError("至少需要一个候选 memory")
        if set(predictions) != set(stable_indices):
            raise ValueError("predictions 与 stable_indices 的候选集合不一致")
        scores = tuple(
            self.score(memory_id, stable_indices[memory_id], prediction, target, valid_mask)
            for memory_id, prediction in predictions.items()
        )
        selected = max(scores, key=self._rank)
        return SelectionResult(selected.memory_id, selected, tuple(sorted(scores, key=lambda item: item.stable_index)))
