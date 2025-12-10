# app/visual/vol_panel.py
from __future__ import annotations
import io
import math
from typing import Optional
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter, MaxNLocator


def _fmt_pct(x: float, _pos=None) -> str:
    return f"{x:.1f}%"


def _fmt_plain(x: float, _pos=None) -> str:
    # аккуратный формат для ATR: без лишних нулей
    ax = abs(x)
    if ax >= 1000:
        return f"{x:,.0f}"
    if ax >= 1:
        return f"{x:,.2f}"
    return f"{x:.4f}"


def _is_num(x) -> bool:
    return x is not None and not (isinstance(x, float) and math.isnan(x))


def _safe_pct(x) -> float:
    return float(x) * 100.0 if _is_num(x) else float("nan")


def render_vol_panel(
    rv7: float,
    rv30: float,
    atr14: float,
    regime: str,
    pctl: float,
    title: Optional[str] = None
) -> bytes:
    """
    Рисует компактный чарт волатильности:
      • RV7 и RV30 (в %) — слева
      • ATR14 (абс.) — справа столбцом
    Возвращает PNG bytes.
    """
    # подготовка данных (надёжная к None/NaN)
    rv7_pct = _safe_pct(rv7)
    rv30_pct = _safe_pct(rv30)
    atr_val = max(0.0, float(atr14)) if _is_num(atr14) else float("nan")

    # нормализуем подписи
    regime_str = (regime or "n/a")
    try:
        pctl_val = float(pctl)
        if math.isnan(pctl_val):
            raise ValueError
        pctl_val = max(0.0, min(100.0, pctl_val))
    except Exception:
        pctl_val = float("nan")

    # если совсем нет данных — покажем плейсхолдер
    if all(math.isnan(v) for v in (rv7_pct, rv30_pct, atr_val)):
        fig, ax = plt.subplots(figsize=(6.8, 3.6), dpi=170)
        ax.axis("off")
        t = title or "Volatility"
        ax.text(0.5, 0.5, f"{t}\n(no data)", ha="center", va="center", fontsize=14)
        buf = io.BytesIO()
        fig.savefig(buf, format="png", bbox_inches="tight")
        plt.close(fig); buf.seek(0)
        return buf.getvalue()

    fig, ax1 = plt.subplots(figsize=(6.8, 3.6), dpi=170)
    ax2 = ax1.twinx()

    # линии RV: рисуем только если значение валидно
    xs = [0, 1]
    if _is_num(rv30_pct):
        ax1.plot(xs, [rv30_pct, rv30_pct], linewidth=2.2, marker="o", label="RV30")
    if _is_num(rv7_pct):
        ax1.plot(xs, [rv7_pct, rv7_pct], linewidth=2.2, marker="o", label="RV7")

    # столбик ATR14 (одна колонка в x=0.5), только если валиден
    if _is_num(atr_val):
        ax2.bar([0.5], [atr_val], width=0.15, alpha=0.35, label="ATR14")

    # оси и подписи
    ax1.set_xlim(-0.2, 1.2)
    ax1.set_ylabel("Realized Vol (%)")
    ax2.set_ylabel("ATR14 (abs)")

    ax1.yaxis.set_major_formatter(FuncFormatter(_fmt_pct))
    ax1.yaxis.set_major_locator(MaxNLocator(nbins=5))
    ax2.yaxis.set_major_formatter(FuncFormatter(_fmt_plain))
    ax2.yaxis.set_major_locator(MaxNLocator(nbins=5))
    ax1.grid(True, axis="y", linestyle="--", alpha=0.25)

    # объединённая легенда (если есть что легендировать)
    h1, l1 = ax1.get_legend_handles_labels()
    h2, l2 = ax2.get_legend_handles_labels()
    if h1 or h2:
        ax1.legend(h1 + h2, l1 + l2, loc="upper left", frameon=False)

    # заголовок
    t = title or "Volatility"
    # если pctl NaN — не показываем число
    pctl_note = (f" ({pctl_val:.1f}pctl)" if _is_num(pctl_val) else "")
    ax1.set_title(f"{t} — {regime_str}{pctl_note}")

    # убираем x-тики как лишние
    ax1.set_xticks([])
    fig.tight_layout()

    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight")
    plt.close(fig)
    buf.seek(0)
    return buf.getvalue()
