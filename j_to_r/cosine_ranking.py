# cosine_ranking.py
# ----------------------------------------------------------------------
# Pure-cosine scoring utilities shared by both apps.
# - safe_cosine on [0,1]
# - top-k mean similarity & coverage
# - weighted raw score -> percent
# ----------------------------------------------------------------------

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, List, Tuple, Dict
import math
import os

import numpy as np


def _clamp01(x: float) -> float:
    return 0.0 if x < 0.0 else 1.0 if x > 1.0 else x


def _to_percent(x: float, ndigits: int = 1) -> float:
    return round(100.0 * _clamp01(x), ndigits)


def safe_cosine(a: np.ndarray, b: np.ndarray, *, eps: float = 1e-12) -> float:
    """
    Cosine similarity mapped to [0,1].
    Returns 0.0 if any vector is near-zero.
    """
    a = np.asarray(a, dtype=float)
    b = np.asarray(b, dtype=float)
    na = float(np.linalg.norm(a))
    nb = float(np.linalg.norm(b))
    if na < eps or nb < eps:
        return 0.0
    cos = float(np.dot(a, b) / (na * nb))
    cos = max(-1.0, min(1.0, cos))
    return 0.5 * (cos + 1.0)  # map [-1,1] -> [0,1]


@dataclass
class CosineConfig:
    """
    All-cosine scoring knobs.
    - w_mean: weight for top-k mean similarity
    - w_cov:  weight for coverage (share of chunks above threshold)
    We enforce w_mean + w_cov == 1.0.
    """
    topk: int = int(os.getenv("COS_TOPK", "5"))
    threshold: float = float(os.getenv("COS_THRESHOLD", "0.50"))
    w_mean: float = float(os.getenv("COS_W_MEAN", "0.80"))
    w_cov: float = float(os.getenv("COS_W_COV", "0.20"))

    def validate(self) -> None:
        s = self.w_mean + self.w_cov
        if not math.isclose(s, 1.0, rel_tol=1e-6, abs_tol=1e-6):
            raise ValueError(f"w_mean + w_cov must sum to 1.0 (got {s:.6f}).")
        if not (0.0 <= self.threshold <= 1.0):
            raise ValueError("threshold must be in [0,1].")
        if self.topk < 1:
            raise ValueError("topk must be >= 1.")


def topk_mean_and_coverage(
    query_vec: np.ndarray,
    candidate_chunk_vecs: Iterable[np.ndarray],
    *,
    topk: int,
    threshold: float,
) -> Tuple[float, float]:
    """
    Compute:
      - mean of the top-k cosine similarities across a candidate's chunks
      - coverage: fraction of chunks >= threshold
    All similarities on [0,1].
    """
    sims: List[float] = [safe_cosine(query_vec, v) for v in candidate_chunk_vecs]
    if not sims:
        return 0.0, 0.0
    sims_sorted = sorted(sims, reverse=True)
    k = max(1, min(topk, len(sims_sorted)))
    mean_topk = float(np.mean(sims_sorted[:k]))
    coverage = float(np.mean([1.0 if s >= threshold else 0.0 for s in sims]))
    return mean_topk, coverage


def compute_cosine_match_percent(
    *,
    query_vec: np.ndarray,
    candidate_chunk_vecs: Iterable[np.ndarray],
    config: CosineConfig | None = None,
) -> Dict[str, float]:
    """
    Weighted score strictly from cosine-derived signals.
    Returns a dict with mean_topk, coverage, raw (0..1), and percent (0..100).
    """
    cfg = config or CosineConfig()
    cfg.validate()

    mean_topk, coverage = topk_mean_and_coverage(
        query_vec=query_vec,
        candidate_chunk_vecs=candidate_chunk_vecs,
        topk=cfg.topk,
        threshold=cfg.threshold,
    )

    raw = _clamp01(cfg.w_mean * mean_topk + cfg.w_cov * coverage)
    return {
        "mean_topk": float(mean_topk),
        "coverage": float(coverage),
        "raw": float(raw),
        "percent": _to_percent(raw),
    }


def calibrate_within_resultset(raw_scores: List[float]) -> List[float]:
    """
    Relative calibration within the current result set: min->0%, max->100%.
    If all equal, return the direct percent mapping of each raw score.
    """
    if not raw_scores:
        return []
    xs = [float(_clamp01(x)) for x in raw_scores]
    lo, hi = min(xs), max(xs)
    if math.isclose(lo, hi, abs_tol=1e-12):
        return [_to_percent(x) for x in xs]
    span = hi - lo
    return [_to_percent((x - lo) / span) for x in xs]
