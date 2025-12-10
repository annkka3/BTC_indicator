# app/visual/price_heatmap.py
"""
Тепловые карты цен для BTC и ETH - визуализация распределения объемов и ценовых уровней.
"""
from __future__ import annotations

import io
from typing import List, Tuple, Optional
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import LinearSegmentedColormap
import matplotlib.dates as mdates
from datetime import datetime, timezone

from ..infrastructure.db import DB


def render_price_heatmap(
    symbol: str,
    db: DB,
    timeframe: str = "1h",
    n_bars: int = 200
) -> bytes:
    """
    Тепловая карта по исполненному объёму с акцентом на
    кластеры, где цена долго торговалась (узлы ликвидности).
    
    В отличие от простого распределения объема по свечам, эта версия:
    - Фокусируется на центре тела свечи (реальная торговая зона)
    - Использует гауссово распределение объема вокруг центра
    - Применяет временное сглаживание для выделения долговременных кластеров
    - Показывает яркие "пояса" там, где цена долго торговалась с объемом
    
    Args:
        symbol: Символ (например, "BTC", "ETH")
        db: База данных
        timeframe: Таймфрейм
        n_bars: Количество баров для анализа
    
    Returns:
        PNG bytes
    """
    try:
        rows = db.last_n(symbol, timeframe, n_bars)
        if not rows:
            fig, ax = plt.subplots(figsize=(10, 6), dpi=150, facecolor="white")
            ax.text(
                0.5, 0.5, f"No data for {symbol} {timeframe}",
                ha="center", va="center", fontsize=14,
            )
            ax.axis("off")
            buf = io.BytesIO()
            fig.savefig(buf, format="png", bbox_inches="tight")
            plt.close(fig)
            buf.seek(0)
            return buf.read()

        # --- подготовка данных ---
        timestamps = [r[0] for r in rows]
        opens = np.array([float(r[1]) for r in rows])
        highs = np.array([float(r[2]) for r in rows])
        lows = np.array([float(r[3]) for r in rows])
        closes = np.array([float(r[4]) for r in rows])
        volumes = np.array(
            [float(r[5]) if len(r) > 5 and r[5] is not None else 0.0 for r in rows]
        )

        dates = [
            datetime.fromtimestamp(ts / 1000.0, tz=timezone.utc) for ts in timestamps
        ]

        all_prices = list(lows) + list(highs) + list(opens) + list(closes)
        min_price = min(all_prices)
        max_price = max(all_prices)

        # небольшой отступ сверху/снизу
        padding = (max_price - min_price) * 0.03
        min_price -= padding
        max_price += padding

        # --- сетка цен ---
        n_price_levels = 80  # увеличено с 50 для лучшего разрешения
        price_levels = np.linspace(min_price, max_price, n_price_levels)
        price_step = price_levels[1] - price_levels[0]

        heatmap_data = np.zeros((n_price_levels, len(dates)), dtype=float)

        # --- распределяем объём по уровням ---
        for i in range(len(dates)):
            bar_low = lows[i]
            bar_high = highs[i]
            bar_vol = volumes[i]
            bar_range = max(bar_high - bar_low, 1e-8)

            if bar_vol <= 0:
                continue

            # центрируем вокруг середины тела (ближе к реальной торговой зоне)
            body_mid = 0.5 * (opens[i] + closes[i])

            # для каждого уровня считаем, попадает ли он в бар,
            # и насколько он близок к body_mid
            for j, level in enumerate(price_levels):
                if bar_low <= level <= bar_high:
                    # расстояние от центра тела в долях диапазона
                    dist = abs(level - body_mid) / bar_range
                    # гауссово затухание — узкий "коридор" вокруг цены
                    sigma = 0.35  # чем меньше, тем уже полоска
                    intensity = np.exp(-0.5 * (dist / sigma) ** 2)

                    heatmap_data[j, i] += bar_vol * intensity

        # --- сглаживание по времени, чтобы подчеркнуть кластеры ---
        if heatmap_data.max() > 0:
            # несколько проходов простым фильтром [1,2,1]/4
            for _ in range(3):
                tmp = heatmap_data.copy()
                tmp[:, 1:-1] = (
                    heatmap_data[:, :-2]
                    + 2.0 * heatmap_data[:, 1:-1]
                    + heatmap_data[:, 2:]
                ) / 4.0
                heatmap_data = tmp

            # теперь нормализуем
            heatmap_data /= heatmap_data.max()

        # --- рисуем ---
        fig, ax = plt.subplots(figsize=(14, 8), dpi=150, facecolor="white")

        colors = ['#000020', '#001050', '#0040a0', '#00a060', '#ffd93d', '#ff6b6b']
        cmap = LinearSegmentedColormap.from_list('liquidity_heatmap', colors, N=200)

        im = ax.imshow(
            heatmap_data,
            aspect='auto',
            cmap=cmap,
            interpolation='bilinear',
            extent=[
                mdates.date2num(dates[0]),
                mdates.date2num(dates[-1]),
                min_price,
                max_price,
            ],
            origin='lower',
            alpha=0.9,  # фон поярче
        )

        # свечи поверх, но чуть прозрачнее, чтобы не забивать карту
        for i, date in enumerate(dates):
            date_num = mdates.date2num(date)
            color = "#2ecc71" if closes[i] >= opens[i] else "#e74c3c"
            body_bottom = min(opens[i], closes[i])
            body_top = max(opens[i], closes[i])
            body_height = body_top - body_bottom
            if body_height == 0:
                body_height = (max_price - min_price) * 0.001

            ax.plot(
                [date_num, date_num],
                [lows[i], highs[i]],
                color="black",
                linewidth=0.4,
                alpha=0.5,
            )
            ax.bar(
                date_num,
                body_height,
                bottom=body_bottom,
                width=0.7,
                color=color,
                edgecolor="black",
                linewidth=0.4,
                alpha=0.6,
            )

        ax.set_xlabel("Time", fontsize=10, fontweight="bold")
        ax.set_ylabel("Price (USDT)", fontsize=10, fontweight="bold")
        ax.set_title(
            f"Price Heatmap - {symbol}USDT ({timeframe})",
            fontsize=12,
            fontweight="bold",
            pad=10,
        )

        ax.xaxis.set_major_formatter(mdates.DateFormatter("%m-%d %H:%M"))
        ax.xaxis.set_major_locator(
            mdates.HourLocator(interval=max(1, len(dates) // 10))
        )
        plt.setp(ax.xaxis.get_majorticklabels(), rotation=45, ha="right")

        cbar = plt.colorbar(im, ax=ax, fraction=0.046, pad=0.04)
        cbar.set_label("Volume intensity (executed)", rotation=90, fontsize=9)

        ax.grid(True, alpha=0.25, linestyle="--")
        ax.set_axisbelow(True)
        plt.tight_layout()

        buf = io.BytesIO()
        fig.savefig(buf, format="png", bbox_inches="tight", facecolor="white")
        plt.close(fig)
        buf.seek(0)
        return buf.read()

    except Exception as e:
        import logging
        logger = logging.getLogger("alt_forecast.visual.price_heatmap")
        logger.exception("Error rendering price heatmap for %s: %s", symbol, e)

        fig, ax = plt.subplots(figsize=(10, 6), dpi=150, facecolor="white")
        ax.text(
            0.5, 0.5,
            f"Error rendering heatmap for {symbol}: {str(e)}",
            ha="center", va="center", fontsize=12, wrap=True,
        )
        ax.axis("off")
        buf = io.BytesIO()
        fig.savefig(buf, format="png", bbox_inches="tight")
        plt.close(fig)
        buf.seek(0)
        return buf.read()

