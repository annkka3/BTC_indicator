from __future__ import annotations
import io
from typing import Iterable
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter


def _to_clean_returns(returns: Iterable[float]) -> np.ndarray:
    """Приводим к float и чистим NaN/inf. Неизвестные значения -> 0 (нейтрально)."""
    arr = np.array(list(returns), dtype=float) if returns is not None else np.array([], dtype=float)
    if arr.size == 0:
        return arr
    arr = np.nan_to_num(arr, nan=0.0, posinf=0.0, neginf=0.0)
    return arr


def _max_drawdown(equity: np.ndarray) -> float:
    """Максимальная просадка, например -0.35 = -35%."""
    if equity.size == 0:
        return float("nan")
    peak = np.maximum.accumulate(equity)
    dd = equity / np.where(peak == 0, 1.0, peak) - 1.0
    return float(np.min(dd))


def _pct_fmt(x, _pos=None) -> str:
    return f"{x*100:.0f}%"


def render_equity_curve(returns: list[float]) -> bytes:
    """
    Рисует PNG кривой эквити по ряду доходностей (простые, не лог-реты).
    returns: список r_t, где эквити = cumprod(1+r_t), старт = 1.0.
    Возвращает PNG как bytes.
    """
    r = _to_clean_returns(returns)

    # Пусто — отрисуем понятную заглушку
    if r.size == 0:
        fig, ax = plt.subplots(figsize=(8, 3.5), dpi=160, facecolor="white")
        ax.text(0.5, 0.5, "No backtest returns", ha="center", va="center", fontsize=13)
        ax.axis("off")
        buf = io.BytesIO()
        fig.savefig(buf, format="png", bbox_inches="tight")
        plt.close(fig); buf.seek(0)
        return buf.getvalue()

    # Эквити
    eq = np.cumprod(np.concatenate([[1.0], 1.0 + r]))
    # Защита от нулей/отрицательных (на графике это ломает масштаб)
    eq = np.where(eq <= 0, np.nan, eq)
    # если всё пропало, хотя бы рисуем единицу
    if np.all(~np.isfinite(eq)):
        eq = np.ones_like(eq)

    # Метрики
    total_return = float(eq[-1] - 1.0)
    mdd = _max_drawdown(eq)
    trades = int(r.size)

    # График
    fig, ax = plt.subplots(figsize=(8, 3.5), dpi=160, facecolor="white")
    ax.set_facecolor("white")

    x = np.arange(eq.size)
    ax.plot(x, eq, linewidth=1.5, label="Equity")

    # Просадки (fill под кривой до локального пика)
    peak = np.maximum.accumulate(eq)
    drawdown = eq / np.where(peak == 0, 1.0, peak) - 1.0
    ax2 = ax.twinx()
    ax2.fill_between(x, drawdown, 0, where=drawdown < 0, alpha=0.25, step=None, label="Drawdown")
    ax2.yaxis.set_major_formatter(FuncFormatter(_pct_fmt))

    # Оси/сетка/подписи
    ax.set_title("Backtest Equity", fontsize=12)
    sub = f"Total: {total_return*100:.1f}%   |   Max DD: {mdd*100:.1f}%   |   Trades: {trades}"
    ax.set_xlabel(sub, fontsize=9)
    ax.set_ylabel("Equity (normalized)")
    ax.grid(True, linestyle="--", alpha=0.3)

    # Легенда (из обоих осей)
    lines, labels = ax.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    if lines or lines2:
        ax.legend(lines + lines2, labels + labels2, loc="upper left", fontsize=9, frameon=False)

    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight")
    plt.close(fig); buf.seek(0)
    return buf.getvalue()

