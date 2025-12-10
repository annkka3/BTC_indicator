# app/visual/liquidation_map.py
"""
Визуализация карты ликвидаций - горизонтальный бар-чарт с уровнями ликвидации.
"""
from __future__ import annotations

import io
from typing import List, Tuple, Dict
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle

# Используем тип из free_market_data (совместим с coinglass)
try:
    from ..infrastructure.free_market_data import LiquidationLevel
except ImportError:
    # Fallback на coinglass если free_market_data недоступен
    from ..infrastructure.coinglass import LiquidationLevel


def render_liquidation_map(
    symbol: str,
    levels: List[LiquidationLevel],
    current_price: float = None
) -> bytes:
    """
    Создать горизонтальный бар-чарт с уровнями ликвидации.
    
    Args:
        symbol: Символ (например, "BTC", "ETH")
        levels: Список уровней ликвидации
        current_price: Текущая цена (опционально)
    
    Returns:
        PNG bytes
    """
    if not levels:
        # Пустой график
        fig, ax = plt.subplots(figsize=(10, 6), dpi=150, facecolor="white")
        ax.text(0.5, 0.5, f"No liquidation data for {symbol}", 
                ha="center", va="center", fontsize=14)
        ax.axis("off")
        buf = io.BytesIO()
        fig.savefig(buf, format="png", bbox_inches="tight")
        plt.close(fig)
        buf.seek(0)
        return buf.read()
    
    # Разделяем на long и short
    long_levels = [l for l in levels if l.side == "long"]
    short_levels = [l for l in levels if l.side == "short"]
    
    # Сортируем по цене
    long_levels.sort(key=lambda x: x.price, reverse=True)
    short_levels.sort(key=lambda x: x.price, reverse=True)
    
    # Объединяем все уровни для определения диапазона
    all_levels = long_levels + short_levels
    if not all_levels:
        all_levels = levels
    
    if not all_levels:
        fig, ax = plt.subplots(figsize=(10, 6), dpi=150, facecolor="white")
        ax.text(0.5, 0.5, f"No valid liquidation data for {symbol}", 
                ha="center", va="center", fontsize=14)
        ax.axis("off")
        buf = io.BytesIO()
        fig.savefig(buf, format="png", bbox_inches="tight")
        plt.close(fig)
        buf.seek(0)
        return buf.read()
    
    prices = [l.price for l in all_levels]
    max_usd = max([l.usd_value for l in all_levels], default=1.0)
    
    min_price = min(prices)
    max_price = max(prices)
    price_range = max_price - min_price
    if price_range == 0:
        price_range = max_price * 0.1  # 10% от цены
    
    # Фильтруем и группируем уровни для лучшей визуализации
    # Убираем дубликаты по цене (оставляем максимальный объем)
    price_dict = {}
    for level in all_levels:
        price_key = round(level.price, 2)  # Округляем для группировки
        if price_key not in price_dict or level.usd_value > price_dict[price_key].usd_value:
            price_dict[price_key] = level
    
    # Сортируем по цене и берем топ уровни
    sorted_levels = sorted(price_dict.values(), key=lambda x: x.usd_value, reverse=True)
    
    # Определяем количество уровней для отображения (максимум 30 для читаемости)
    display_levels = sorted_levels[:30]
    n_levels = len(display_levels)
    
    if n_levels == 0:
        fig, ax = plt.subplots(figsize=(10, 6), dpi=150, facecolor="white")
        ax.text(0.5, 0.5, f"No liquidation levels to display for {symbol}", 
                ha="center", va="center", fontsize=14)
        ax.axis("off")
        buf = io.BytesIO()
        fig.savefig(buf, format="png", bbox_inches="tight")
        plt.close(fig)
        buf.seek(0)
        return buf.read()
    
    # Создаем фигуру с фиксированной высотой для лучшей читаемости
    fig_height = max(8, min(12, n_levels * 0.4))  # Ограничиваем высоту
    fig, ax = plt.subplots(figsize=(12, fig_height), dpi=150, facecolor="white")
    
    if n_levels == 0:
        ax.text(0.5, 0.5, f"No liquidation levels to display for {symbol}", 
                ha="center", va="center", fontsize=14)
        ax.axis("off")
        buf = io.BytesIO()
        fig.savefig(buf, format="png", bbox_inches="tight")
        plt.close(fig)
        buf.seek(0)
        return buf.read()
    
    # Сортируем для отображения (сверху вниз - от высокой цены к низкой)
    display_levels.sort(key=lambda x: x.price, reverse=True)
    
    # Создаем горизонтальные бары
    y_positions = np.arange(n_levels)
    bar_height = 0.6
    
    # Определяем максимальную ширину для нормализации (в USD)
    # Используем разумный масштаб - максимальное значение USD
    max_width_usd = max_usd
    
    for i, level in enumerate(display_levels):
        y_pos = y_positions[i]
        # Нормализуем ширину бара относительно максимального значения
        # Используем прямое значение USD, но ограничиваем масштаб для читаемости
        width = level.usd_value
        
        # Цвет в зависимости от типа
        color = "#2ecc71" if level.side == "long" else "#e74c3c"
        
        # Рисуем бар
        ax.barh(y_pos, width, height=bar_height, color=color, alpha=0.7, edgecolor="black", linewidth=0.5)
        
        # Подпись цены слева (форматируем цену правильно)
        if level.price >= 1000:
            price_str = f"${level.price/1000:.2f}K"
        elif level.price >= 1:
            price_str = f"${level.price:.2f}"
        else:
            price_str = f"${level.price:.4f}"
        
        ax.text(-max_width_usd * 0.05, y_pos, price_str, 
                ha="right", va="center", fontsize=8, fontweight="bold")
        
        # Подпись значения справа
        if level.usd_value >= 1_000_000:
            usd_str = f"${level.usd_value/1_000_000:.2f}M"
        elif level.usd_value >= 1000:
            usd_str = f"${level.usd_value/1000:.1f}K"
        else:
            usd_str = f"${level.usd_value:.0f}"
        ax.text(width + max_width_usd * 0.02, y_pos, usd_str,
                ha="left", va="center", fontsize=8)
    
    # Настройка осей
    ax.set_yticks(y_positions)
    # Форматируем цены для оси Y правильно
    y_labels = []
    for l in display_levels:
        if l.price >= 1000:
            y_labels.append(f"${l.price/1000:.2f}K")
        elif l.price >= 1:
            y_labels.append(f"${l.price:.2f}")
        else:
            y_labels.append(f"${l.price:.4f}")
    ax.set_yticklabels(y_labels, fontsize=7)
    ax.set_xlabel("USD Value", fontsize=10, fontweight="bold")
    ax.set_ylabel("Price", fontsize=10, fontweight="bold")
    
    # Устанавливаем разумные пределы для оси X
    ax.set_xlim(left=-max_width_usd * 0.1, right=max_width_usd * 1.15)
    
    # Заголовок
    title = f"Predicted Liquidation Levels - {symbol}USDT"
    ax.set_title(title, fontsize=12, fontweight="bold", pad=10)
    
    # Легенда
    from matplotlib.patches import Patch
    legend_elements = [
        Patch(facecolor="#2ecc71", alpha=0.7, label="Long Liquidations"),
        Patch(facecolor="#e74c3c", alpha=0.7, label="Short Liquidations")
    ]
    ax.legend(handles=legend_elements, loc="upper right", fontsize=9)
    
    # Линия текущей цены (если указана)
    if current_price and min_price <= current_price <= max_price:
        # Находим позицию текущей цены
        price_pos = None
        for i, level in enumerate(display_levels):
            if abs(level.price - current_price) < price_range * 0.01:
                price_pos = y_positions[i]
                break
        
        if price_pos is not None:
            ax.axhline(y=price_pos, color="blue", linestyle="--", linewidth=2, alpha=0.7, label="Current Price")
    
    # Сетка
    ax.grid(True, alpha=0.3, axis="x")
    ax.set_axisbelow(True)
    
    # Инвертируем ось Y для отображения сверху вниз (высокие цены вверху)
    ax.invert_yaxis()
    
    plt.tight_layout()
    
    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight", facecolor="white")
    plt.close(fig)
    buf.seek(0)
    return buf.read()


def analyze_liquidation_zones(levels: List[LiquidationLevel], current_price: float | None = None) -> str:
    """
    Анализировать основные зоны ликвидности и создать текстовое описание.
    
    Args:
        levels: Список уровней ликвидации
        current_price: Текущая цена (опционально)
    
    Returns:
        Текстовое описание зон ликвидности
    """
    if not levels:
        return "По инструменту нет значимых уровней ликвидностей за выбранный период."
    
    total_usd = sum(l.usd_value for l in levels)
    long_usd = sum(l.usd_value for l in levels if l.side == "long")
    short_usd = sum(l.usd_value for l in levels if l.side == "short")
    
    # Статистика по биржам
    exchange_stats: Dict[str, float] = {}
    for lvl in levels:
        ex = getattr(lvl, 'exchange', 'unknown')
        exchange_stats[ex] = exchange_stats.get(ex, 0) + lvl.usd_value
    
    lines: list[str] = []
    lines.append("💥 <b>Карта ликвидаций</b>")
    lines.append(f"Всего ликвидаций: ${total_usd/1_000_000:.2f}M")
    lines.append(f"• Long:  ${long_usd/1_000_000:.2f}M")
    lines.append(f"• Short: ${short_usd/1_000_000:.2f}M")
    
    # Статистика по биржам если есть данные с нескольких бирж
    if len(exchange_stats) > 1:
        lines.append(f"\n🏦 <b>По биржам:</b>")
        total_for_percent = sum(exchange_stats.values())
        for ex, volume in sorted(exchange_stats.items(), key=lambda x: x[1], reverse=True):
            ex_name = ex.upper().replace("_", " ")
            percent = (volume / total_for_percent * 100) if total_for_percent > 0 else 0
            lines.append(f"   • {ex_name}: ${volume/1_000_000:.2f}M ({percent:.0f}%)")
    
    # Топ-уровни по каждой стороне
    top_long = sorted(
        [l for l in levels if l.side == "long"],
        key=lambda x: x.usd_value,
        reverse=True
    )[:5]
    top_short = sorted(
        [l for l in levels if l.side == "short"],
        key=lambda x: x.usd_value,
        reverse=True
    )[:5]
    
    if top_long:
        lines.append("\n🟢 <b>Ключевые уровни для ликвидации long-ов:</b>")
        for i, lvl in enumerate(top_long, 1):
            lines.append(f"   {i}. ${lvl.price:,.0f} — ${lvl.usd_value/1_000_000:.2f}M")
    
    if top_short:
        lines.append("\n🔴 <b>Ключевые уровни для ликвидации short-ов:</b>")
        for i, lvl in enumerate(top_short, 1):
            lines.append(f"   {i}. ${lvl.price:,.0f} — ${lvl.usd_value/1_000_000:.2f}M")
    
    # Привязка к текущей цене
    if current_price:
        lines.append(f"\n💰 <b>Текущая цена:</b> ${current_price:,.2f}")
        
        above = [l for l in levels if l.price > current_price]
        below = [l for l in levels if l.price < current_price]
        
        if above:
            nearest_above = min(above, key=lambda x: x.price)
            lines.append(
                f"   Ближайший уровень выше: ${nearest_above.price:,.0f} "
                f"({nearest_above.side}, ${nearest_above.usd_value/1_000_000:.2f}M)"
            )
        
        if below:
            nearest_below = max(below, key=lambda x: x.price)
            lines.append(
                f"   Ближайший уровень ниже: ${nearest_below.price:,.0f} "
                f"({nearest_below.side}, ${nearest_below.usd_value/1_000_000:.2f}M)"
            )
    
    return "\n".join(lines)

