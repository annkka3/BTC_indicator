# app/visual/whale_orders_map.py
"""
Визуализация карты крупных ордеров китов - график с горизонтальными линиями и таблицей.
"""
from __future__ import annotations

import io
from typing import List, Tuple, Optional, Dict
from datetime import datetime
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle
import matplotlib.dates as mdates

# Используем тип из free_market_data (совместим с coinglass)
try:
    from ..infrastructure.free_market_data import WhaleOrder
except ImportError:
    # Fallback на coinglass если free_market_data недоступен
    from ..infrastructure.coinglass import WhaleOrder


def render_whale_orders_map(
    symbol: str,
    orders: List[WhaleOrder],
    ohlcv_data: Optional[List[Tuple[int, float, float, float, float, Optional[float]]]] = None,
    timeframe: str = "15m"
) -> bytes:
    """
    Создать график с крупными ордерами китов на фоне свечного графика.
    
    Args:
        symbol: Символ (например, "BTC", "ETH")
        orders: Список крупных ордеров
        ohlcv_data: OHLCV данные для свечного графика (опционально)
        timeframe: Таймфрейм для графика
    
    Returns:
        PNG bytes
    """
    if not orders:
        fig, ax = plt.subplots(figsize=(12, 8), dpi=150, facecolor="white")
        ax.text(0.5, 0.5, f"No whale orders data for {symbol}", 
                ha="center", va="center", fontsize=14)
        ax.axis("off")
        buf = io.BytesIO()
        fig.savefig(buf, format="png", bbox_inches="tight")
        plt.close(fig)
        buf.seek(0)
        return buf.read()
    
    # Ограничиваем количество ордеров для отображения (избегаем слишком больших изображений)
    # Берем топ-50 ордеров по размеру для каждого типа
    sorted_orders = sorted(orders, key=lambda x: x.amount, reverse=True)
    buy_orders_all = [o for o in sorted_orders if o.side == "buy"]
    sell_orders_all = [o for o in sorted_orders if o.side == "sell"]
    
    # Ограничиваем до 50 ордеров каждого типа для визуализации
    buy_orders = buy_orders_all[:50]
    sell_orders = sell_orders_all[:50]
    
    # Определяем диапазон цен
    all_prices = [o.price for o in orders]
    if ohlcv_data:
        for _, _, h, l, _, _ in ohlcv_data:
            all_prices.extend([h, l])
    
    if not all_prices:
        fig, ax = plt.subplots(figsize=(12, 8), dpi=150, facecolor="white")
        ax.text(0.5, 0.5, f"No price data for {symbol}", 
                ha="center", va="center", fontsize=14)
        ax.axis("off")
        buf = io.BytesIO()
        fig.savefig(buf, format="png", bbox_inches="tight")
        plt.close(fig)
        buf.seek(0)
        return buf.read()
    
    min_price = min(all_prices)
    max_price = max(all_prices)
    price_range = max_price - min_price
    if price_range == 0:
        price_range = max_price * 0.1
    
    # Создаем фигуру с двумя subplot: график и таблица
    # Ограничиваем размер для избежания ошибок matplotlib (максимум 65535 пикселей)
    # Используем фиксированный размер и DPI для контроля
    fig = plt.figure(figsize=(14, 10), dpi=100, facecolor="white")  # Снизили DPI со 150 до 100
    gs = fig.add_gridspec(2, 1, height_ratios=[3, 1], hspace=0.3)
    ax_chart = fig.add_subplot(gs[0])
    ax_table = fig.add_subplot(gs[1])
    ax_table.axis("off")
    
    # Рисуем свечной график если есть данные
    # Ограничиваем количество свечей для избежания слишком больших изображений
    if ohlcv_data:
        from datetime import datetime, timezone
        # Ограничиваем до последних 200 свечей для визуализации
        limited_ohlcv = ohlcv_data[-200:] if len(ohlcv_data) > 200 else ohlcv_data
        dates = [datetime.fromtimestamp(ts / 1000.0, tz=timezone.utc) for ts, _, _, _, _, _ in limited_ohlcv]
        
        for i, (ts, o, h, l, c, _) in enumerate(limited_ohlcv):
            color = "#2ecc71" if c >= o else "#e74c3c"
            ax_chart.plot([dates[i], dates[i]], [l, h], color="black", linewidth=0.5)
            ax_chart.plot([dates[i], dates[i]], [o, c], color=color, linewidth=2)
    
    # Рисуем горизонтальные линии для ордеров
    # Buy ордера (зеленые) - ниже текущей цены
    for order in buy_orders:
        ax_chart.axhline(y=order.price, color="#2ecc71", linestyle="-", linewidth=1.5, alpha=0.6)
        # Подпись размера ордера
        ax_chart.text(ax_chart.get_xlim()[1] * 0.98, order.price, 
                     f"${order.amount/1_000_000:.2f}M", 
                     ha="right", va="center", fontsize=7, 
                     bbox=dict(boxstyle="round,pad=0.3", facecolor="#2ecc71", alpha=0.3))
    
    # Sell ордера (красные) - выше текущей цены
    for order in sell_orders:
        ax_chart.axhline(y=order.price, color="#e74c3c", linestyle="-", linewidth=1.5, alpha=0.6)
        # Подпись размера ордера
        ax_chart.text(ax_chart.get_xlim()[1] * 0.98, order.price, 
                     f"${order.amount/1_000_000:.2f}M", 
                     ha="right", va="center", fontsize=7,
                     bbox=dict(boxstyle="round,pad=0.3", facecolor="#e74c3c", alpha=0.3))
    
    # Настройка графика
    ax_chart.set_ylabel("Price (USDT)", fontsize=10, fontweight="bold")
    ax_chart.set_title(f"Whale Orders & Large Trades - {symbol}USDT Perpetual ({timeframe})", 
                      fontsize=12, fontweight="bold", pad=10)
    ax_chart.grid(True, alpha=0.3)
    ax_chart.set_axisbelow(True)
    
    # Легенда
    from matplotlib.patches import Patch
    legend_elements = [
        plt.Line2D([0], [0], color="#2ecc71", linewidth=2, label="Buy Orders (Support)"),
        plt.Line2D([0], [0], color="#e74c3c", linewidth=2, label="Sell Orders (Resistance)")
    ]
    ax_chart.legend(handles=legend_elements, loc="upper left", fontsize=9)
    
    # Таблица с топ ордерами
    top_orders = sorted(orders, key=lambda x: x.amount, reverse=True)[:15]
    
    if top_orders:
        table_data = []
        headers = ["Price", "Amount (USD)", "Side", "Age"]
        
        for order in top_orders:
            # Используем символы вместо эмодзи для совместимости с matplotlib
            side_symbol = "▲" if order.side == "buy" else "▼"
            table_data.append([
                f"${order.price:,.2f}",
                f"${order.amount/1_000_000:.2f}M",
                f"{side_symbol} {order.side.upper()}",
                order.age
            ])
        
        table = ax_table.table(cellText=table_data, colLabels=headers,
                               cellLoc="center", loc="center",
                               bbox=[0, 0, 1, 1])
        table.auto_set_font_size(False)
        table.set_fontsize(8)
        table.scale(1, 1.5)
        
        # Стилизация таблицы
        for i in range(len(headers)):
            table[(0, i)].set_facecolor("#34495e")
            table[(0, i)].set_text_props(weight="bold", color="white")
        
        for i in range(1, len(table_data) + 1):
            for j in range(len(headers)):
                if j == 2:  # Side column
                    if "BUY" in table_data[i-1][j]:
                        table[(i, j)].set_facecolor("#d5f4e6")
                    else:
                        table[(i, j)].set_facecolor("#fadbd8")
                else:
                    table[(i, j)].set_facecolor("#ecf0f1")
    
    plt.tight_layout()
    
    buf = io.BytesIO()
    # Сохраняем с ограничением размера
    # Используем dpi=100 и bbox_inches="tight" для контроля размера
    try:
        fig.savefig(buf, format="png", bbox_inches="tight", facecolor="white", dpi=100)
    except ValueError as e:
        # Если все еще слишком большой, пробуем без tight_layout
        plt.tight_layout(rect=[0, 0, 1, 0.95])  # Оставляем небольшой отступ сверху
        fig.savefig(buf, format="png", facecolor="white", dpi=80)  # Еще больше снижаем DPI
    
    plt.close(fig)
    buf.seek(0)
    return buf.read()


def format_whale_orders_description(orders: List[WhaleOrder], symbol: str) -> str:
    """
    Создать текстовое описание крупных ордеров китов.
    
    Args:
        orders: Список ордеров
        symbol: Символ
    
    Returns:
        Текстовое описание
    """
    if not orders:
        return f"Нет данных о крупных ордерах для {symbol}."
    
    buy_orders = [o for o in orders if o.side == "buy"]
    sell_orders = [o for o in orders if o.side == "sell"]
    
    lines = []
    lines.append(f"🐋 <b>Крупные ордера китов - {symbol}USDT</b>\n")
    
    # Статистика по биржам
    exchange_stats: Dict[str, Dict[str, any]] = {}
    for order in orders:
        ex = getattr(order, 'exchange', 'unknown')
        if ex not in exchange_stats:
            exchange_stats[ex] = {"count": 0, "total": 0.0, "buy": 0.0, "sell": 0.0}
        exchange_stats[ex]["count"] += 1
        exchange_stats[ex]["total"] += order.amount
        if order.side == "buy":
            exchange_stats[ex]["buy"] += order.amount
        else:
            exchange_stats[ex]["sell"] += order.amount
    
    # Анализ buy ордеров (поддержка)
    if buy_orders:
        buy_orders.sort(key=lambda x: x.amount, reverse=True)
        total_buy = sum(o.amount for o in buy_orders)
        
        lines.append(f"🟢 <b>Buy ордера (поддержка):</b>")
        lines.append(f"   Всего: ${total_buy/1_000_000:.2f}M ({len(buy_orders)} ордеров)")
        
        if buy_orders:
            lines.append("   Топ уровни поддержки:")
            for i, order in enumerate(buy_orders[:5], 1):
                ex_name = getattr(order, 'exchange', 'unknown').upper()
                lines.append(f"   {i}. ${order.price:,.2f} - ${order.amount/1_000_000:.2f}M ({ex_name}, {order.age})")
    
    # Анализ sell ордеров (сопротивление)
    if sell_orders:
        sell_orders.sort(key=lambda x: x.amount, reverse=True)
        total_sell = sum(o.amount for o in sell_orders)
        
        lines.append(f"\n🔴 <b>Sell ордера (сопротивление):</b>")
        lines.append(f"   Всего: ${total_sell/1_000_000:.2f}M ({len(sell_orders)} ордеров)")
        
        if sell_orders:
            lines.append("   Топ уровни сопротивления:")
            for i, order in enumerate(sell_orders[:5], 1):
                ex_name = getattr(order, 'exchange', 'unknown').upper()
                lines.append(f"   {i}. ${order.price:,.2f} - ${order.amount/1_000_000:.2f}M ({ex_name}, {order.age})")
    
    # Общая статистика
    total_orders_value = sum(o.amount for o in orders)
    lines.append(f"\n📊 <b>Общая статистика:</b>")
    lines.append(f"   Всего ордеров: {len(orders)}")
    lines.append(f"   Общая стоимость: ${total_orders_value/1_000_000:.2f}M")
    
    # Статистика по биржам если есть данные с нескольких бирж
    if len(exchange_stats) > 1:
        lines.append(f"\n🏦 <b>По биржам:</b>")
        for ex, stats in sorted(exchange_stats.items(), key=lambda x: x[1]["total"], reverse=True):
            ex_name = ex.upper()
            lines.append(
                f"   • {ex_name}: {int(stats['count'])} ордеров "
                f"(${stats['total']/1_000_000:.2f}M) - "
                f"Buy: ${stats['buy']/1_000_000:.2f}M, "
                f"Sell: ${stats['sell']/1_000_000:.2f}M"
            )
    
    return "\n".join(lines)

