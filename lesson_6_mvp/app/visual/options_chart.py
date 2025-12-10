# app/visual/options_chart.py (v1.4: robust inputs, sorted expiries, adaptive scales, highlights)
from __future__ import annotations
import io
import math
from typing import List, Tuple
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter, MaxNLocator

from ..infrastructure.coinglass import MaxPainResult, MaxPainPoint


def _money_fmt(x: float, _pos=None) -> str:
    ax = abs(x)
    if ax >= 1e12:
        return f"{x/1e12:.2f}T"
    if ax >= 1e9:
        return f"{x/1e9:.2f}B"
    if ax >= 1e6:
        return f"{x/1e6:.2f}M"
    if ax >= 1e3:
        return f"{x/1e3:.0f}K"
    return f"{x:.0f}"


def _clean_float(v, fallback: float = 0.0) -> float:
    try:
        x = float(v)
    except Exception:
        return fallback
    return x if math.isfinite(x) else fallback


def _sort_points(points: List[MaxPainPoint]) -> List[MaxPainPoint]:
    # Безопасная сортировка по дате 'YYYY-MM-DD'
    try:
        return sorted(points, key=lambda p: (p.date or "9999-12-31"))
    except Exception:
        return points


def _nearest_index(points: List[MaxPainPoint]) -> int | None:
    # «Ближайшая» экспирация — первая по времени (после сортировки)
    return 0 if points else None


def render_max_pain_chart(res: MaxPainResult) -> bytes:
    """
    Строит чарт Max Pain для CoinGlass-результата.
    Вход: MaxPainResult(points: List[MaxPainPoint] с полями .date (YYYY-MM-DD), .notional (USD), .max_pain (USD))
    Выход: PNG bytes.
    """
    points: List[MaxPainPoint] = list(res.points or [])
    points = _sort_points(points)

    if not points:
        fig, ax = plt.subplots(figsize=(10.5, 4.2), dpi=170, facecolor="white")
        ax.set_facecolor("white")
        ax.text(0.5, 0.5, "No CoinGlass options data", ha="center", va="center", fontsize=14)
        ax.axis("off")
        buf = io.BytesIO()
        fig.savefig(buf, format="png", bbox_inches="tight")
        plt.close(fig); buf.seek(0)
        return buf.getvalue()

    xs = [p.date for p in points]                           # 'YYYY-MM-DD'
    mp = [_clean_float(p.max_pain, 0.0) for p in points]    # цена (USD)
    notional = [_clean_float(p.notional, 0.0) for p in points]  # USD

    x = np.arange(len(xs))
    width = 0.45

    fig, ax1 = plt.subplots(figsize=(10.5, 4.2), dpi=170, facecolor="white")
    ax1.set_facecolor("white")
    ax2 = ax1.twinx()

    # Столбцы: ноушналы по экспирациям
    bars = ax2.bar(x, notional, width=width, alpha=0.35, label="Notional (USD)", zorder=2)

    # Линия: Max Pain
    # Если точек одна — всё равно рисуем маркер
    ax1.plot(x, mp, linewidth=2.2, marker="o", ms=4.5, label="Max Pain (USD)", zorder=3)

    # Оси, сетка, форматирование
    ax1.set_xticks(x, xs, rotation=25, ha="right")
    sym = getattr(res, "symbol", "").strip() or "—"
    ax1.set_title(f"Options — Max Pain & Notional ({sym})")

    ax1.set_ylabel("Max Pain (USD)")
    ax2.set_ylabel("Notional (USD)")

    ax1.yaxis.set_major_formatter(FuncFormatter(_money_fmt))
    ax2.yaxis.set_major_formatter(FuncFormatter(_money_fmt))
    ax1.yaxis.set_major_locator(MaxNLocator(nbins=6))
    ax2.yaxis.set_major_locator(MaxNLocator(nbins=6))
    ax1.grid(True, axis="y", linestyle="--", alpha=0.3, zorder=1)

    # Адаптивные границы по левой оси (цены MP) — небольшой паддинг
    if mp:
        mp_arr = np.array(mp, dtype=float)
        lo = float(np.nanmin(mp_arr))
        hi = float(np.nanmax(mp_arr))
        if not math.isfinite(lo) or not math.isfinite(hi):
            lo, hi = 0.0, 1.0
        pad = (hi - lo) * 0.08 or max(1.0, hi * 0.02)
        ax1.set_ylim(lo - pad, hi + pad)

    # Правая ось снизу всегда от 0
    ax2.set_ylim(bottom=0)

    # Аннотации: компактная подпись крупнейшего notional и ближайшей экспы
    if len(bars) > 0:
        # крупнейший notional
        k = int(np.argmax(notional))
        try:
            b = bars[k]
            h = b.get_height()
            if h > 0:
                ax2.annotate(
                    _money_fmt(h),
                    xy=(b.get_x() + b.get_width() / 2, h),
                    xytext=(0, 3),
                    textcoords="offset points",
                    ha="center", va="bottom", fontsize=8.5, weight="bold", alpha=0.9,
                    zorder=4,
                )
        except Exception:
            pass

        # подсветка ближайшей экспирации (первая по времени)
        ni = _nearest_index(points)
        if ni is not None and 0 <= ni < len(bars):
            try:
                bars[ni].set_alpha(0.55)
                bars[ni].set_linewidth(1.4)
                bars[ni].set_edgecolor("#444")
                ax1.annotate(
                    "nearest",
                    xy=(x[ni], mp[ni]),
                    xytext=(0, 10),
                    textcoords="offset points",
                    ha="center", va="bottom", fontsize=8.5, alpha=0.9,
                )
            except Exception:
                pass

    # Объединённая легенда
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
