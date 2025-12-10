# app/visual/risk_card.py
from __future__ import annotations
import io
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt


def _emoji(label: str) -> str:
    s = (label or "").lower()
    if "сильный" in s and "risk-off" in s:
        return "🔴🔴"
    if "risk-off" in s:
        return "🔴"
    if "нейтрал" in s:
        return "⚪️"
    if "сильный" in s and "risk-on" in s:
        return "🟢🟢"
    if "risk-on" in s:
        return "🟢"
    return "⚪️"


def render_risk_card(tf: str, score: float, label: str) -> bytes:
    """
    Рисует карточку общего риска с линейной шкалой [-8..+8] и маркером score.
    Возвращает PNG bytes.
    """
    # ограничим маркер разумными границами
    x = float(max(-8, min(8, score)))

    fig, ax = plt.subplots(figsize=(7.0, 3.2), dpi=170)
    ax.axis("off")

    # заголовок
    ax.text(0.02, 0.85, f"Risk Now ({tf}) {_emoji(label)}", fontsize=12, weight="bold")
    ax.text(0.02, 0.60, f"{label}", fontsize=11)
    ax.text(0.98, 0.60, f"score {score:+.1f}", fontsize=11, ha="right")

    # шкала: координаты в Axes (0..1)
    left, right, y = 0.06, 0.94, 0.32
    ax.hlines(y, left, right, linewidth=4, alpha=0.25)

    # деления: -8..+8
    for i in range(-8, 9, 2):
        t = (i + 8) / 16.0
        xi = left + (right - left) * t
        ax.vlines(xi, y - 0.06, y + 0.06, linewidth=1.0, alpha=0.35)
        ax.text(xi, y - 0.12, f"{i:+d}", ha="center", va="top", fontsize=9)

    # подписи краёв
    ax.text(left,  y + 0.12, "Risk-OFF", ha="left",  va="bottom", fontsize=9)
    ax.text(right, y + 0.12, "Risk-ON",  ha="right", va="bottom", fontsize=9)

    # маркер текущего score
    t = (x + 8.0) / 16.0
    cx = left + (right - left) * t
    ax.plot([cx], [y], marker="o", markersize=10)

    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight")
    plt.close(fig)
    buf.seek(0)
    return buf.getvalue()
