# app/visual/candles_panel.py
from __future__ import annotations
import io, numpy as np, datetime as dt
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.dates import DateFormatter, AutoDateLocator
from .style import apply_light

def _draw_candles(ax, t, o, h, l, c):
    t = np.asarray(t); o=np.asarray(o); h=np.asarray(h); l=np.asarray(l); c=np.asarray(c)
    up = c>=o; dn = ~up
    # тени
    for mask, col in ((up, "#1E8E3E"), (dn, "#C43C35")):
        ax.vlines(t[mask], l[mask], h[mask], color=col, linewidth=0.9, alpha=0.9)
    # тела
    w = max(0.3, min(0.9, 0.6))  # относительная ширина
    ax.bar(t[up],  c[up]-o[up], bottom=o[up], width=w, color="#B9E6C9", edgecolor="#1E8E3E", linewidth=0.8)
    ax.bar(t[dn],  o[dn]-c[dn], bottom=c[dn], width=w, color="#F3C7C4", edgecolor="#C43C35", linewidth=0.8)
    ax.margins(x=0.01, y=0.1)
    ax.grid(True)

def render_market_dashboard(panels: list[dict], title_suffix: str="") -> io.BytesIO:
    """
    panels: [{ 'title': 'BTCUSDT • 1h', 't': [...datetime], 'o':[], 'h':[], 'l':[], 'c':[] }, ...]
    Рисует 2x3 сетку с аккуратным светлым стилем.
    """
    apply_light()
    n = len(panels)
    rows, cols = 2, 3
    fig, axes = plt.subplots(rows, cols, figsize=(12, 7.6), dpi=160)
    axes = axes.ravel()

    for i, p in enumerate(panels[:rows*cols]):
        ax = axes[i]
        _draw_candles(ax, p["t"], p["o"], p["h"], p["l"], p["c"])
        ax.set_title(f"{p['title']}{(' • '+title_suffix) if title_suffix else ''}")
        ax.xaxis.set_major_locator(AutoDateLocator())
        ax.xaxis.set_major_formatter(DateFormatter("%Y-%b-%d"))
        ax.tick_params(axis="x", rotation=0)

        # вспомогательные пунктирные уровни S/R (по квантилям)
        arr = np.asarray(p["c"], dtype=float)
        if arr.size >= 16:
            q1, q2, q3 = np.quantile(arr, [0.2, 0.5, 0.8])
            for q, a in ((q1,0.35),(q2,0.25),(q3,0.35)):
                ax.axhline(q, color="#8FA3B6", linestyle="--", linewidth=0.7, alpha=a)

    # прячем пустые оси если панелей < 6
    for j in range(i+1, rows*cols):
        axes[j].set_visible(False)

    fig.tight_layout(pad=1.0)
    buf = io.BytesIO()
    fig.savefig(buf, format="png")
    plt.close(fig); buf.seek(0)
    return buf
