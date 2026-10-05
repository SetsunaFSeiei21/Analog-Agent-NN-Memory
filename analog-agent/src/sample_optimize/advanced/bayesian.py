from __future__ import annotations

import numpy as np
from scipy.linalg import cho_factor, cho_solve
from scipy.spatial.distance import cdist
from scipy.special import ndtr


class ConstrainedBayesianSampler:
    """Bounded exact-GP active sampling of electrical feasibility.

    A Gaussian surrogate of the binary OP feasibility label supplies uncertainty
    and an approximate probability (not a calibrated GP classifier). Acquisition
    favors feasibility, uncertainty, boundary cases and distance from observations;
    a fixed exploration share preserves broad coverage. No performance target.
    """
    def __init__(self, domain, config):
        self.domain, self.config = domain, config

    def propose(self, rng, designs, feasible, excluded, count):
        from ..history_store import SamplingHistoryStore
        pool = self.domain.random(rng, self.config["candidate_pool_size"])
        kept, seen = [], set(excluded)
        for row in pool:
            key = SamplingHistoryStore.design_key(row)
            if key not in seen:
                seen.add(key)
                kept.append(row)
        if not kept:
            return [], []
        pool = np.asarray(kept)
        count = min(count, len(pool))
        if len(designs) < self.config["warmup_points"]:
            return pool[:count], [{"acquisition": "bayesian_warmup"}] * count
        x = self.domain.normalize(designs)
        y = np.asarray(feasible, dtype=float)
        limit = self.config["max_training_points"]
        # Deterministic, bounded, class-balanced subset; all rows used for coverage.
        selected = []
        for cls in (0., 1.):
            indices = np.flatnonzero(y == cls)
            if len(indices):
                selected.extend(indices[np.unique(np.rint(np.linspace(0, len(indices)-1, min(len(indices), limit//2))).astype(int))])
        if not selected:  # Missing OP observations never arrive as invented labels.
            return pool[:count], [{"acquisition": "bayesian_warmup"}] * count
        indices = np.asarray(sorted(selected), dtype=int)
        train, targets = x[indices], y[indices]
        candidates = self.domain.normalize(pool)
        ell = self.config["length_scale"]
        kernel = lambda a, b: np.exp(-0.5 * cdist(a, b, metric="sqeuclidean") / ell**2)
        prior_mean = (targets.sum()+1.) / (len(targets)+2.)
        matrix = kernel(train, train)
        matrix.flat[::len(matrix)+1] += self.config["noise_variance"] + 1e-8
        factor = cho_factor(matrix, lower=True, check_finite=True)
        cross = kernel(candidates, train)
        mean = prior_mean + cross @ cho_solve(factor, targets-prior_mean)
        variance = np.maximum(1. - np.sum(cross * cho_solve(factor, cross.T).T, axis=1), 1e-10)
        sigma = np.sqrt(variance)
        probability = ndtr((mean-0.5) / np.sqrt(variance+self.config["noise_variance"]))
        distance = np.full(len(pool), np.inf)
        for start in range(0, len(x), 2048):
            distance = np.minimum(distance, cdist(candidates, x[start:start+2048]).min(axis=1))
        coverage = distance / max(float(distance.max()), 1e-12)
        boundary = 4*probability*(1-probability)
        score = probability*sigma + self.config["boundary_weight"]*boundary*sigma + self.config["coverage_weight"]*coverage
        exploration = int(round(count*self.config["exploration_fraction"]))
        # A random subset is reserved independently of the predicted feasibility.
        chosen = rng.choice(len(pool), exploration, replace=False).tolist() if exploration else []
        score[chosen] = -np.inf
        for _ in range(count-len(chosen)):
            i = int(np.argmax(score))
            chosen.append(i)
            # Greedy batch diversity, including within-batch pending points.
            penalty = np.minimum(cdist(candidates, candidates[[i]]).ravel() / max(ell, 1e-9), 1.)
            score *= penalty
            score[chosen] = -np.inf
        metadata = [{"acquisition": "exploration" if j < exploration else "feasibility_uncertainty_coverage",
                     "probability_feasible": float(probability[i]), "posterior_std": float(sigma[i])}
                    for j, i in enumerate(chosen)]
        return pool[chosen], metadata
