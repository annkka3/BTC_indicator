# app/lib/filters.py
from __future__ import annotations
from typing import List

def _median(seq: List[float]) -> float:
    if not seq:
        return 0.0
    s = sorted(seq)
    n = len(s)
    mid = n // 2
    if n % 2 == 1:
        return s[mid]
    else:
        return 0.5 * (s[mid - 1] + s[mid])

def _mad(vals: List[float]) -> float:
    if not vals:
        return 0.0
    m = _median(vals)
    dev = [abs(v - m) for v in vals]
    md = _median(dev)
    # avoid division by zero downstream; return small positive if md==0
    return md if md != 0.0 else 1e-12

def denoise_mad(vals: List[float], k: float = 3.5) -> List[float]:
    """Clamp values to median ± k*MAD to suppress outliers/wicks.
    Returns a *new* list; original is not modified.
    """
    if not vals:
        return []
    if len(vals) < 5:
        return vals[:]
    m = _median(vals)
    mad = _mad(vals)
    lo, hi = m - k * mad, m + k * mad
    return [min(max(v, lo), hi) for v in vals]
