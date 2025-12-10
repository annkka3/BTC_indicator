# app/visual/corr_heatmap.py
from __future__ import annotations
import io
from typing import Iterable, Sequence

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import TwoSlopeNorm
from matplotlib.ticker import MaxNLocator


def _order_labels(labels: Sequence[str], preferred: Iterable[str] | None = None) -> list[str]:
    """
    Возвращает список меток в «умном» порядке:
    - сначала пересечение с preferred (если передан),
    - затем остальные по алфавиту (стабильно).
    """
    uniq = list(dict.fromkeys(labels))
    if not preferred:
        return sorted(uniq)
    pref = [x for x in preferred if x in uniq]
    rest = sorted([x for x in uniq if x not in pref])
    return pref + rest


def _safe_numeric(df):
    """Приводим к float, выбрасываем полностью пустые ряды/столбцы, чистим inf→nan."""
    try:
        dfn = df.copy()
        dfn = dfn.apply(pd.to_numeric, errors="coerce")  # type: ignore
    except Exception:
        # без pandas-помощников: через values
        dfn = df.astype(float)
    dfn = dfn.replace([np.inf, -np.inf], np.nan).dropna(axis=0, how="all").dropna(axis=1, how="all")
    return dfn


def render_corr_heatmap(df) -> bytes:
    """
    Строит PNG с тепловой картой корреляций.
    Ожидается квадратный DataFrame (pandas) с метками строк/столбцов.
    Допустимы:
    - не квадратная форма (возьмём пересечение индексов/колонок),
    - NaN/inf (будут очищены),
    - случай «пусто» — вернём заглушку PNG.
    """
    # Ленивая импортирующая защита (если файл дергать вне окружения pandas)
    try:
        import pandas as pd  # noqa: F401
    except Exception:
        pd = None  # type: ignore

    # Пусто → заглушка
    if df is None or getattr(df, "empty", True):
        fig, ax = plt.subplots(figsize=(7, 3.5), dpi=170)
        ax.text(0.5, 0.5, "No correlation data", ha="center", va="center", fontsize=14)
        ax.axis("off")
        buf = io.BytesIO()
        fig.savefig(buf, format="png", bbox_inches="tight")
        plt.close(fig)
        buf.seek(0)
        return buf.getvalue()

    # Приведение к числам и удаление полностью пустых рядов/колонок
    try:
        dfn = _safe_numeric(df)
    except Exception:
        dfn = df  # в крайнем случае попробуем как есть

    # Делаем матрицу строго квадратной по пересечению меток
    rows = list(map(str, getattr(dfn, "index", [])))
    cols = list(map(str, getattr(dfn, "columns", [])))
    common = [x for x in rows if x in cols]
    if not common:
        # Ничего общего — показать заглушку
        fig, ax = plt.subplots(figsize=(7, 3.5), dpi=170)
        ax.text(0.5, 0.5, "No common labels for correlation matrix", ha="center", va="center", fontsize=12)
        ax.axis("off")
        buf = io.BytesIO()
        fig.savefig(buf, format="png", bbox_inches="tight")
        plt.close(fig)
        buf.seek(0)
        return buf.getvalue()

    # Умное упорядочивание
    preferred = ("BTC", "ETHBTC", "USDT.D", "BTC.D", "TOTAL2", "TOTAL3")
    order = _order_labels(common, preferred=preferred)

    dfn = dfn.reindex(index=order, columns=order)

    # Если после реиндекса всё NaN — выходим заглушкой
    if dfn.isna().all().all():
        fig, ax = plt.subplots(figsize=(7, 3.5), dpi=170)
        ax.text(0.5, 0.5, "Correlation matrix is empty", ha="center", va="center", fontsize=12)
        ax.axis("off")
        buf = io.BytesIO()
        fig.savefig(buf, format="png", bbox_inches="tight")
        plt.close(fig)
        buf.seek(0)
        return buf.getvalue()

    mat = np.array(dfn.values, dtype=float)
    # NaN → 0 для визуализации, зажмём значения в [-1, 1]
    mat = np.nan_to_num(mat, nan=0.0, posinf=0.0, neginf=0.0)
    mat = np.clip(mat, -1.0, 1.0)

    n = mat.shape[0]
    if n <= 0:
        # на всякий случай
        fig, ax = plt.subplots(figsize=(7, 3.5), dpi=170)
        ax.text(0.5, 0.5, "No correlation data", ha="center", va="center", fontsize=14)
        ax.axis("off")
        buf = io.BytesIO()
        fig.savefig(buf, format="png", bbox_inches="tight")
        plt.close(fig)
        buf.seek(0)
        return buf.getvalue()

    # Адаптивный размер полотна
    side = min(max(0.6 * n, 5.5), 12.0)
    fig, ax = plt.subplots(figsize=(side, side * 0.85), dpi=170)

    # Центр палитры в 0 для симметрии
    norm = TwoSlopeNorm(vmin=-1.0, vcenter=0.0, vmax=1.0)
    im = ax.imshow(mat, cmap="RdBu_r", norm=norm, interpolation="nearest", zorder=2)

    # Тики и подписи
    ax.set_xticks(np.arange(n))
    ax.set_yticks(np.arange(n))
    ax.set_xticklabels(order, rotation=35, ha="right")
    ax.set_yticklabels(order)

    # Сетка ячеек
    ax.set_xlim(-0.5, n - 0.5)
    ax.set_ylim(n - 0.5, -0.5)
    for i in range(n + 1):
        ax.axhline(i - 0.5, color="k", linewidth=0.3, alpha=0.25, zorder=3)
        ax.axvline(i - 0.5, color="k", linewidth=0.3, alpha=0.25, zorder=3)

    # Аннотации только для небольших матриц
    if n <= 14:
        for i in range(n):
            for j in range(n):
                val = float(mat[i, j])
                txt_color = "#111" if abs(val) < 0.6 else "#f2f2f2"
                ax.text(j, i, f"{val:.2f}", ha="center", va="center", fontsize=8.5, color=txt_color, zorder=4)

    # Цветовая шкала
    cbar = fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04)
    cbar.set_label("Correlation", rotation=90)
    cbar.ax.yaxis.set_major_locator(MaxNLocator(nbins=6))

    ax.set_title("Correlation Heatmap (centered at 0)")
    fig.tight_layout()

    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight")
    plt.close(fig)
    buf.seek(0)
    return buf.getvalue()
