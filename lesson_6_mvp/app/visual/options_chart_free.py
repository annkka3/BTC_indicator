# app/visual/options_chart_free.py
from __future__ import annotations
import io
import math
from typing import List, Dict
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter, MaxNLocator


def _money_fmt(x: float, _pos=None) -> str:
    ax = abs(x)
    if ax >= 1e12: return f"{x/1e12:.2f}T"
    if ax >= 1e9:  return f"{x/1e9:.2f}B"
    if ax >= 1e6:  return f"{x/1e6:.2f}M"
    if ax >= 1e3:  return f"{x/1e3:.0f}K"
    return f"{x:.0f}"


def _clean_float(v, fallback: float = 0.0) -> float:
    try:
        x = float(v)
    except Exception:
        return fallback
    return x if math.isfinite(x) else fallback


def _sort_points(points: List[Dict]) -> List[Dict]:
    # Безопасная сортировка по 'YYYY-MM-DD'
    try:
        return sorted(points, key=lambda p: (p.get("date") or "9999-12-31"))
    except Exception:
        return points


def _nearest_index(points: List[Dict]) -> int | None:
    # «Ближайшая» экспирация — первая после сортировки
    return 0 if points else None


def render_free_series(
    points: List[Dict],
    binance_notional: Dict[str, float] | None = None,
    *,
    mobile: bool = False,
    annotate_mp: bool = False,
    annotate_bars: bool = True,
    highlight_nearest: bool = True,
) -> bytes:
    """
    points: [{date:'YYYY-MM-DD', max_pain, deribit_notional_usd}, ...] (из deribit.build_series)
    binance_notional: {'YYMMDD': notionalUSD, ...} (может быть пустым)
    Рисуем ОДИН столбик Total Notional = Deribit + Binance по каждой дате + линию Max Pain.

    Опции:
      mobile            — компактный размер полотна (узкая ширина)
      annotate_mp       — подписывать значения Max Pain над маркерами
      annotate_bars     — подписывать крупнейший столбик notional
      highlight_nearest — визуально выделять «ближайшую» экспирацию
    """
    pts = _sort_points(list(points or []))
    if not pts:
        fig, ax = plt.subplots(figsize=((6.6, 4.0) if mobile else (10.5, 4.2)), dpi=170)
        ax.text(0.5, 0.5, "No free options data", ha="center", va="center", fontsize=14)
        ax.axis("off")
        buf = io.BytesIO(); fig.savefig(buf, format="png", bbox_inches="tight")
        plt.close(fig); buf.seek(0)
        return buf.getvalue()

    xs   = [str(p.get("date", "")) for p in pts]
    mp   = [_clean_float(p.get("max_pain"), 0.0) for p in pts]
    dnot = [_clean_float(p.get("deribit_notional_usd", 0.0), 0.0) for p in pts]

    # Binance по тем же датам в формате YYMMDD
    bnot: List[float] = []
    if binance_notional:
        for d in xs:
            yymmdd = d.replace("-", "")[2:] if d else ""
            bnot.append(_clean_float(binance_notional.get(yymmdd, 0.0), 0.0))
    else:
        bnot = [0.0] * len(xs)

    total_not = [dn + bn for dn, bn in zip(dnot, bnot)]

    x = np.arange(len(xs))
    fig_w = 6.6 if mobile else 10.5
    fig_h = 4.2
    fig, ax1 = plt.subplots(figsize=(fig_w, fig_h), dpi=170)
    ax2 = ax1.twinx()

    # Столбцы: Total Notional
    bars = ax2.bar(x, total_not, alpha=0.35, label="Total Notional (USD)", zorder=2)

    # Линия: Max Pain
    ax1.plot(x, mp, linewidth=2.2, marker="o", ms=4.5, label="Max Pain (USD)", zorder=3)

    # Подписи X
    rot = 18 if mobile else 25
    ax1.set_xticks(x, xs, rotation=rot, ha="right")

    ax1.set_title("Options — Max Pain & Total Notional")
    ax1.set_ylabel("Max Pain (USD)")
    ax2.set_ylabel("Total Notional (USD)")

    ax1.yaxis.set_major_formatter(FuncFormatter(_money_fmt))
    ax2.yaxis.set_major_formatter(FuncFormatter(_money_fmt))
    ax1.yaxis.set_major_locator(MaxNLocator(nbins=6))
    ax2.yaxis.set_major_locator(MaxNLocator(nbins=6))
    ax1.grid(True, axis="y", linestyle="--", alpha=0.3, zorder=1)

    # Адаптивные границы по левой оси
    if mp:
        mp_arr = np.array(mp, dtype=float)
        lo = float(np.nanmin(mp_arr))
        hi = float(np.nanmax(mp_arr))
        if not math.isfinite(lo) or not math.isfinite(hi):
            lo, hi = 0.0, 1.0
        pad = (hi - lo) * 0.08 or max(1.0, hi * 0.02)
        ax1.set_ylim(lo - pad, hi + pad)

    # Правая ось от нуля
    ax2.set_ylim(bottom=0)

    # Аннотации: крупнейший notional
    if annotate_bars and len(bars) > 0:
        k = int(np.argmax(total_not))
        try:
            b = bars[k]
            h = b.get_height()
            if h > 0:
                ax2.annotate(
                    _money_fmt(h),
                    xy=(b.get_x() + b.get_width() / 2, h),
                    xytext=(0, 3),
                    textcoords="offset points",
                    ha="center", va="bottom", fontsize=8.5, weight="bold", alpha=0.95, zorder=4
                )
        except Exception:
            pass

    # Аннотации: Max Pain значения
    if annotate_mp:
        for i, y in enumerate(mp):
            if math.isfinite(y):
                ax1.annotate(
                    _money_fmt(y),
                    xy=(x[i], y),
                    xytext=(0, 8 if mobile else 10),
                    textcoords="offset points",
                    ha="center", va="bottom",
                    fontsize=(8 if mobile else 8.5),
                    alpha=0.9
                )

    # Подсветка ближайшей экспирации
    if highlight_nearest and len(bars) > 0:
        ni = _nearest_index(pts)
        if ni is not None and 0 <= ni < len(bars):
            try:
                bars[ni].set_alpha(0.55)
                bars[ni].set_linewidth(1.4)
                bars[ni].set_edgecolor("#444")
                # маркер рядом с точкой Max Pain на этой дате
                if ni < len(mp) and math.isfinite(mp[ni]):
                    ax1.annotate(
                        "nearest",
                        xy=(x[ni], mp[ni]),
                        xytext=(0, 10 if not mobile else 8),
                        textcoords="offset points",
                        ha="center", va="bottom", fontsize=(8 if mobile else 8.5), alpha=0.9
                    )
            except Exception:
                pass

    # Общая легенда
    h1, l1 = ax1.get_legend_handles_labels()
    h2, l2 = ax2.get_legend_handles_labels()
    if h1 or h2:
        ax1.legend(h1 + h2, l1 + l2, loc="upper left", frameon=False)

    ax1.margins(x=0.02)
    fig.tight_layout()

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=170, bbox_inches="tight")
    plt.close(fig); buf.seek(0)
    return buf.getvalue()
