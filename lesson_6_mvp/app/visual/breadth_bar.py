# app/visual/breadth_bar.py
from __future__ import annotations
import io
from typing import Optional
import math

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter, MaxNLocator


def _as_int(x, default=0) -> int:
    try:
        if x is None:
            return default
        xi = int(x)
        # защищаемся от отрицательных значений
        return max(0, xi)
    except Exception:
        return default


def _pct(n: int, total: int) -> float:
    if total <= 0:
        return 0.0
    try:
        p = (float(n) / float(total)) * 100.0
    except Exception:
        return 0.0
    # жёстко ограничим 0..100 на случай округлительных аномалий
    return max(0.0, min(100.0, p))


def _fmt_pct(x: float, _pos=None) -> str:
    return f"{x:.0f}%"


def render_breadth_bar(
    above_ma50: int,
    above_ma200: int,
    total: int,
    title: Optional[str] = None
) -> bytes:
    """
    PNG с двумя столбцами ширины рынка:
      • доля инструментов >MA50
      • доля инструментов >MA200

    Пример:
        png = render_breadth_bar(23, 10, 50, title="Breadth (1h)")
    """
    # Нормализуем вход
    total_i = _as_int(total)
    a50 = min(_as_int(above_ma50), total_i)
    a200 = min(_as_int(above_ma200), total_i)

    p50 = _pct(a50, total_i)
    p200 = _pct(a200, total_i)

    labels = [">MA50", ">MA200"]
    values = [p50, p200]
    abs_vals = [f"{a50}/{total_i}" if total_i > 0 else "0/0",
                f"{a200}/{total_i}" if total_i > 0 else "0/0"]

    # холст
    fig, ax = plt.subplots(figsize=(6.2, 3.6), dpi=170, facecolor="white")
    ax.set_facecolor("white")

    # столбцы (дефолтные цвета Matplotlib)
    x = range(len(labels))
    bars = ax.bar(x, values, alpha=0.9)

    # подписи над столбцами
    for i, b in enumerate(bars):
        h = float(b.get_height())
        ax.annotate(
            f"{h:.1f}%",
            xy=(b.get_x() + b.get_width() / 2, h),
            xytext=(0, 4),
            textcoords="offset points",
            ha="center",
            va="bottom",
            fontsize=10,
            fontweight="bold",
        )
        ax.annotate(
            abs_vals[i],
            xy=(b.get_x() + b.get_width() / 2, max(h, 0.0)),
            xytext=(0, -14),
            textcoords="offset points",
            ha="center",
            va="top",
            fontsize=9,
            alpha=0.85,
        )

    # оси/сетка/форматирование
    ax.set_xticks(list(x), labels)
    ax.set_ylim(0, 100)
    ax.yaxis.set_major_formatter(FuncFormatter(_fmt_pct))
    ax.yaxis.set_major_locator(MaxNLocator(nbins=5))
    ax.grid(True, axis="y", linestyle="--", alpha=0.25)
    ax.set_ylabel("Share of assets")
    if title:
        ax.set_title(title)

    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight")
    plt.close(fig)
    buf.seek(0)
    return buf.getvalue()
