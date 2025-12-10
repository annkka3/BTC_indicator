# app/visual/levels_card.py (v1.2: white bg, safe ranges, level dedup)
from __future__ import annotations
import io
from typing import Iterable, List, Optional
import math
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter, MaxNLocator


def _fmt_value(metric: str, v: float) -> str:
    if metric in ("TOTAL2", "TOTAL3"):
        return f"{v/1e9:.1f}B"
    if metric.endswith("D"):
        return f"{v:.2f}%"
    if metric == "ETHBTC":
        return f"{v:.6f}"
    return f"{v:.2f}"


def _yfmt(metric: str):
    def money(x: float) -> str:
        ax = abs(x)
        if ax >= 1e12: return f"{x/1e12:.2f}T"
        if ax >= 1e9:  return f"{x/1e9:.2f}B"
        if ax >= 1e6:  return f"{x/1e6:.2f}M"
        if ax >= 1e3:  return f"{x/1e3:.0f}K"
        return f"{x:.2f}"
    def pct(x: float) -> str: return f"{x:.2f}%"
    def ethbtc(x: float) -> str: return f"{x:.6f}"
    def plain(x: float) -> str: return f"{x:.2f}"
    if metric in ("TOTAL2","TOTAL3"): return FuncFormatter(lambda x,_: money(x))
    if metric.endswith("D"):          return FuncFormatter(lambda x,_: pct(x))
    if metric == "ETHBTC":            return FuncFormatter(lambda x,_: ethbtc(x))
    return FuncFormatter(lambda x,_: plain(x))


def _dedup_levels(levels: List[float], *, tol_rel: float = 0.002) -> List[float]:
    """Склеивает близкие уровни по относительному порогу (по медиане списка)."""
    vals = [float(v) for v in levels if v is not None and math.isfinite(v)]
    if not vals:
        return []
    vals = sorted(vals)
    base = np.median(vals)
    tol = abs(base) * tol_rel if base != 0 else tol_rel
    out = [vals[0]]
    for v in vals[1:]:
        if abs(v - out[-1]) > max(tol, tol_rel):
            out.append(v)
    return out


def render_levels_card(symbol: str, tf: str,
                       last: float,
                       above: Iterable[float] | None,
                       below: Iterable[float] | None,
                       breakout_up: bool,
                       breakout_dn: bool) -> bytes:
    """
    Мини-панель S/R:
      • горизонтальные линии уровней выше/ниже
      • маркер текущей цены
      • флажки Breakout ↑/↓
    Возвращает PNG bytes.
    """
    # очистка входов
    last_val = float(last) if last is not None and math.isfinite(last) else float("nan")
    above_raw = [float(v) for v in (above or []) if v is not None and math.isfinite(v)]
    below_raw = [float(v) for v in (below or []) if v is not None and math.isfinite(v)]

    above = _dedup_levels(above_raw)
    below = _dedup_levels(below_raw)

    # холст
    fig, ax = plt.subplots(figsize=(7.0, 3.6), dpi=170, facecolor="white")
    ax.set_facecolor("white")

    # диапазон по Y вокруг last/уровней
    levels_all = ([last_val] if math.isfinite(last_val) else []) + above + below
    if levels_all:
        y_min = float(min(levels_all))
        y_max = float(max(levels_all))
        span = max(y_max - y_min, (abs(last_val) if math.isfinite(last_val) else abs(y_max)) * 0.003 + 1e-9)
        pad = span * 0.25
        ax.set_ylim(y_min - pad, y_max + pad)
    else:
        # запасной диапазон
        ax.set_ylim(0.0, 1.0)

    ax.yaxis.set_major_formatter(_yfmt(symbol))
    ax.yaxis.set_major_locator(MaxNLocator(nbins=6))
    ax.grid(True, axis="y", linestyle="--", alpha=0.25)

    # ось X не используется — это «полка» уровней
    ax.set_xlim(0, 1)
    ax.set_xticks([])

    # линии уровней
    for v in below:
        ax.axhline(v, linestyle="--", linewidth=0.9, alpha=0.6)
        ax.text(0.02, v, f"S {_fmt_value(symbol, v)}", va="center", ha="left", fontsize=9, alpha=0.95)
    for v in above:
        ax.axhline(v, linestyle="--", linewidth=0.9, alpha=0.6)
        ax.text(0.02, v, f"R {_fmt_value(symbol, v)}", va="center", ha="left", fontsize=9, alpha=0.95)

    # текущая цена
    if math.isfinite(last_val):
        ax.axhline(last_val, linewidth=1.5, alpha=0.95)
        ax.text(0.98, last_val, f"last {_fmt_value(symbol, last_val)}",
                va="center", ha="right", fontsize=10, fontweight="bold")
    else:
        ax.text(0.5, 0.5, "No price", transform=ax.transAxes, ha="center", va="center", alpha=0.7)

    # breakout флажки
    note = []
    if breakout_up: note.append("Breakout ↑")
    if breakout_dn: note.append("Breakout ↓")
    subt = (" | ".join(note)) if note else "—"
    ax.set_title(f"Levels {symbol} ({tf}) — {subt}")

    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight")
    plt.close(fig); buf.seek(0)
    return buf.getvalue()
