# app/visual/altseason_card.py
from __future__ import annotations
import io, datetime as dt
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

def render_altseason_card(value: float, ts_utc: str | dt.datetime | None = None) -> io.BytesIO:
    """value: 0..100"""
    v = float(max(0.0, min(100.0, value)))
    if isinstance(ts_utc, str):
        ts_txt = ts_utc
    elif isinstance(ts_utc, dt.datetime):
        ts_txt = ts_utc.strftime("%Y-%m-%d %H:%M UTC")
    else:
        ts_txt = dt.datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")

    fig = plt.figure(figsize=(3.2, 4.8), dpi=200)
    ax = plt.gca()
    bg = "#111418"
    fig.patch.set_facecolor(bg); ax.set_facecolor(bg)
    ax.set_axis_off()

    # Заголовок
    ax.text(0.5, 0.88, "Altcoin Season Index", ha="center", va="center",
            color="#E6E9EE", fontsize=11, weight="bold", transform=ax.transAxes)

    # Большое число
    ax.text(0.5, 0.70, f"{int(round(v))}", ha="center", va="center",
            color="white", fontsize=48, weight="bold", transform=ax.transAxes)

    # Градиентная шкала 0..100
    # создаём полоску 1x100 с градиентом от красного к зелёному
    grad = np.linspace(0, 1, 400).reshape(1, -1, 1)
    red  = np.array([0xC4,0x3C,0x35])/255.0
    green= np.array([0x1E,0x8E,0x3E])/255.0
    ramp = (1-grad)*red + grad*green
    ax2 = fig.add_axes([0.13, 0.46, 0.74, 0.06])  # x, y, w, h в figure coords
    ax2.imshow(ramp, aspect="auto")
    ax2.set_axis_off()

    # метка текущего значения
    x = 0.13 + 0.74 * (v/100.0)
    ax.plot([x, x], [0.46, 0.52], color="white", linewidth=2, transform=fig.transFigure)

    # подписи BTC / ALTS и ориентиры
    ax.text(0.13, 0.43, "BTC", ha="left", va="top", color="#A8B0BD", fontsize=9, transform=fig.transFigure)
    ax.text(0.87, 0.43, "ALTS", ha="right", va="top", color="#A8B0BD", fontsize=9, transform=fig.transFigure)
    for p in (0, 30, 50, 70, 100):
        xx = 0.13 + 0.74 * (p/100.0)
        ax.plot([xx, xx], [0.54, 0.56], color="#2A2F36", linewidth=1, transform=fig.transFigure)

    # время
    ax.text(0.5, 0.10, ts_txt, ha="center", va="center", color="#A8B0BD", fontsize=9, transform=ax.transAxes)

    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight")
    plt.close(fig); buf.seek(0)
    return buf
