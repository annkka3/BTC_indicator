# app/visual/market_misc.py (v1.3: white bg, safe inputs, adaptive funding gauge)
from __future__ import annotations
import io
import math
from typing import Optional
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter, MaxNLocator


def _fmt_usd(x: float, _pos=None) -> str:
    ax = abs(x)
    if ax >= 1e12: return f"${x/1e12:.2f}T"
    if ax >= 1e9:  return f"${x/1e9:.2f}B"
    if ax >= 1e6:  return f"${x/1e6:.2f}M"
    if ax >= 1e3:  return f"${x/1e3:.0f}K"
    return f"${x:.0f}"


def _fmt_pct(x: float, _pos=None) -> str:
    return f"{x:.3f}%"


def _clean_float(v: float | int | None, fallback: float = 0.0) -> float:
    try:
        x = float(v) if v is not None else float("nan")
    except Exception:
        x = float("nan")
    return x if math.isfinite(x) else fallback


# -------- Funding --------
def render_funding_card(symbol: str, mark_price: float, funding_rate: float) -> bytes:
    """
    Крупным funding в % + подзаголовок — mark price.
    Адаптивная линейка снизу: симметричный диапазон вокруг 0, чтобы не клиповалось.
    """
    rate_pct = _clean_float(funding_rate, 0.0) * 100.0
    mark_price = _clean_float(mark_price, 0.0)

    # адаптивная шкала: минимум ±0.10%, максимум ±0.50%, и с небольшим запасом
    span = max(0.10, min(0.50, abs(rate_pct) * 1.8))
    lo, hi = -span, +span
    # нормированное значение бара в пределах [lo, hi]
    bar_val = max(min(rate_pct, hi), lo)

    fig, ax = plt.subplots(figsize=(6.4, 3.2), dpi=170, facecolor="white")
    ax.set_facecolor("white")
    ax.axis("off")

    ax.text(0.02, 0.82, f"Funding — {symbol}", fontsize=12, weight="bold")
    ax.text(0.02, 0.54, f"{rate_pct:.4f}%", fontsize=28, weight="bold")
    ax.text(0.02, 0.22, f"Mark: {mark_price:,.2f}", fontsize=11)

    # линейка снизу
    ax2 = fig.add_axes([0.02, 0.08, 0.96, 0.08])
    ax2.bar([0], [bar_val], width=0.6,
            color=("tab:red" if rate_pct > 0 else "tab:blue"), alpha=0.65)
    ax2.set_xlim(lo, hi)
    # метки: крайние + ноль
    ax2.set_xticks([lo, 0, hi], [f"{lo:.2f}%", "0", f"{hi:+.2f}%"])
    ax2.set_yticks([])
    for spine in ax2.spines.values():
        spine.set_visible(False)
    ax2.axvline(0, color="#333", linewidth=0.8, alpha=0.6)

    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight")
    plt.close(fig); buf.seek(0)
    return buf.getvalue()


# -------- Basis --------
def render_basis_card(symbol: str, spot: float, mark: float, basis_pct: float) -> bytes:
    """
    Две полосы (Spot vs Mark) и значение Basis в % в заголовке.
    Безопасное форматирование (NaN -> 0).
    """
    spot = _clean_float(spot, 0.0)
    mark = _clean_float(mark, 0.0)
    basis_pct = _clean_float(basis_pct, 0.0)

    fig, ax = plt.subplots(figsize=(6.8, 3.4), dpi=170, facecolor="white")
    ax.set_facecolor("white")

    vals = [spot, mark]
    labels = ["Spot", "Mark"]
    bars = ax.barh(labels, vals, alpha=0.85)

    ax.set_xlabel("Price (USD)")
    ax.xaxis.set_major_formatter(FuncFormatter(_fmt_usd))
    ax.xaxis.set_major_locator(MaxNLocator(nbins=5))
    ax.grid(True, axis="x", linestyle="--", alpha=0.25)

    ax.set_title(f"Basis — {symbol}   ({basis_pct:.3f}%)")

    # подписи значений чуть правее конца полос
    for i, (lab, v, b) in enumerate(zip(labels, vals, bars)):
        x = b.get_width()
        ax.text(x, b.get_y() + b.get_height()/2,
                f"  {v:,.2f}", va="center", ha="left", fontsize=9)

    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight")
    plt.close(fig); buf.seek(0)
    return buf.getvalue()


# -------- Liquidations --------
def render_liqs_card(symbol: str, long_usd: float, short_usd: float, count: int) -> bytes:
    """
    Бар-чарт: Long vs Short liqs (USD), подписи и общее количество.
    Защита от NaN/∞ и аккуратные подписи.
    """
    long_usd = _clean_float(long_usd, 0.0)
    short_usd = _clean_float(short_usd, 0.0)
    count = int(count) if isinstance(count, (int, float)) else 0

    fig, ax = plt.subplots(figsize=(6.8, 3.4), dpi=170, facecolor="white")
    ax.set_facecolor("white")

    labels = ["Long liqs (USD)", "Short liqs (USD)"]
    vals = [long_usd, short_usd]
    bars = ax.bar(labels, vals, alpha=0.85)

    for b in bars:
        h = b.get_height()
        ax.annotate(
            _fmt_usd(h),
            xy=(b.get_x() + b.get_width()/2, h),
            xytext=(0, 3),
            textcoords="offset points",
            ha="center", va="bottom",
            fontsize=9, weight="bold"
        )

    ax.yaxis.set_major_formatter(FuncFormatter(_fmt_usd))
    ax.yaxis.set_major_locator(MaxNLocator(nbins=5))
    ax.grid(True, axis="y", linestyle="--", alpha=0.25)
    ax.set_title(f"Liquidations — {symbol}   (count: {count})")

    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight")
    plt.close(fig); buf.seek(0)
    return buf.getvalue()
