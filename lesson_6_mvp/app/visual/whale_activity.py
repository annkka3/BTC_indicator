# app/visual/whale_activity.py
"""
Визуализация активности китов - карточки с крупными позициями.
"""
from __future__ import annotations

import io
from typing import List
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle, FancyBboxPatch

from ..infrastructure.coinglass import WhalePosition


def render_whale_activity_card(
    symbol: str,
    positions: List[WhalePosition],
    timeframe: str = "1h"
) -> bytes:
    """
    Создать карточку с активностью китов.
    
    Args:
        symbol: Символ (например, "BTC", "ETH")
        positions: Список позиций китов
        timeframe: Таймфрейм
    
    Returns:
        PNG bytes
    """
    if not positions:
        fig, ax = plt.subplots(figsize=(10, 6), dpi=150, facecolor="white")
        ax.text(0.5, 0.5, f"No whale activity data for {symbol} ({timeframe})", 
                ha="center", va="center", fontsize=14)
        ax.axis("off")
        buf = io.BytesIO()
        fig.savefig(buf, format="png", bbox_inches="tight")
        plt.close(fig)
        buf.seek(0)
        return buf.read()
    
    # Ограничиваем количество позиций для отображения
    display_positions = positions[:10]
    n_positions = len(display_positions)
    
    # Создаем фигуру
    fig, ax = plt.subplots(figsize=(14, max(8, n_positions * 1.2)), dpi=150, facecolor="white")
    ax.axis("off")
    
    # Заголовок
    title = f"WHALE ACTION WITH {symbol}"
    ax.text(0.5, 0.98, title, ha="center", va="top", fontsize=16, fontweight="bold",
            transform=ax.transAxes)
    
    # Рисуем карточки для каждой позиции
    y_start = 0.90
    card_height = 0.08
    spacing = 0.01
    
    for i, pos in enumerate(display_positions):
        y_pos = y_start - i * (card_height + spacing)
        
        # Определяем цвет карточки в зависимости от типа позиции
        if "LONG" in pos.activity:
            bg_color = "#d5f4e6"  # Светло-зеленый
            border_color = "#2ecc71"
        elif "SHORT" in pos.activity:
            bg_color = "#fadbd8"  # Светло-красный
            border_color = "#e74c3c"
        else:
            bg_color = "#ecf0f1"  # Серый
            border_color = "#95a5a6"
        
        # Рисуем карточку
        card = FancyBboxPatch(
            (0.05, y_pos - card_height), 0.9, card_height,
            boxstyle="round,pad=0.01", 
            facecolor=bg_color,
            edgecolor=border_color,
            linewidth=2,
            transform=ax.transAxes
        )
        ax.add_patch(card)
        
        # Адрес (сокращенный)
        address_short = pos.address[:6] + "..." + pos.address[-4:] if len(pos.address) > 10 else pos.address
        ax.text(0.08, y_pos - card_height/2, f"👤 Address: {address_short}", 
               ha="left", va="center", fontsize=9, fontweight="bold", transform=ax.transAxes)
        
        # PnL
        pnl_color = "#2ecc71" if pos.total_pnl >= 0 else "#e74c3c"
        pnl_str = f"${pos.total_pnl/1000:.1f}K" if abs(pos.total_pnl) >= 1000 else f"${pos.total_pnl:.0f}"
        ax.text(0.35, y_pos - card_height/2, f"💰 Total PnL: {pnl_str}", 
               ha="left", va="center", fontsize=9, color=pnl_color, transform=ax.transAxes)
        
        # Размер позиции
        pos_str = f"${pos.position_size/1_000_000:.2f}M"
        if pos.position_eth > 0:
            pos_str += f" ({pos.position_eth:.1f} {symbol})"
        ax.text(0.08, y_pos - card_height/2 - 0.025, f"💵 Position: {pos_str}", 
               ha="left", va="center", fontsize=8, transform=ax.transAxes)
        
        # Активность
        activity_emoji = "🟢" if "LONG" in pos.activity else "🔴" if "SHORT" in pos.activity else "⚪"
        ax.text(0.35, y_pos - card_height/2 - 0.025, f"{activity_emoji} Activity: {pos.activity}", 
               ha="left", va="center", fontsize=8, transform=ax.transAxes)
        
        # Плечо и цены
        ax.text(0.08, y_pos - card_height/2 - 0.045, f"⚖️ Leverage: {pos.leverage}", 
               ha="left", va="center", fontsize=8, transform=ax.transAxes)
        ax.text(0.35, y_pos - card_height/2 - 0.045, f"📊 Entry: ${pos.entry_price:.2f} | Liq: ${pos.liquidation_price:.2f}", 
               ha="left", va="center", fontsize=8, transform=ax.transAxes)
    
    # Подвал с информацией о таймфрейме
    ax.text(0.5, 0.02, f"Timeframe: {timeframe} | Total positions: {len(positions)}", 
           ha="center", va="bottom", fontsize=8, style="italic", transform=ax.transAxes)
    
    plt.tight_layout()
    
    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight", facecolor="white")
    plt.close(fig)
    buf.seek(0)
    return buf.read()


def format_whale_activity_description(positions: List[WhalePosition], symbol: str, timeframe: str) -> str:
    """
    Создать текстовое описание активности китов.
    
    Args:
        positions: Список позиций
        symbol: Символ
        timeframe: Таймфрейм
    
    Returns:
        Текстовое описание
    """
    if not positions:
        return f"Нет данных об активности китов для {symbol} за {timeframe}."
    
    long_positions = [p for p in positions if "LONG" in p.activity]
    short_positions = [p for p in positions if "SHORT" in p.activity]
    
    lines = []
    lines.append(f"🐋 <b>Активность китов - {symbol} ({timeframe})</b>\n")
    
    # Статистика по позициям
    total_long_size = sum(p.position_size for p in long_positions)
    total_short_size = sum(p.position_size for p in short_positions)
    total_pnl = sum(p.total_pnl for p in positions)
    
    lines.append(f"📊 <b>Статистика:</b>")
    lines.append(f"   Всего позиций: {len(positions)}")
    lines.append(f"   Long позиций: {len(long_positions)} (${total_long_size/1_000_000:.2f}M)")
    lines.append(f"   Short позиций: {len(short_positions)} (${total_short_size/1_000_000:.2f}M)")
    lines.append(f"   Общий PnL: ${total_pnl/1000:.1f}K")
    
    # Топ позиции
    if positions:
        top_positions = sorted(positions, key=lambda x: abs(x.position_size), reverse=True)[:5]
        lines.append(f"\n🏆 <b>Топ позиции:</b>")
        for i, pos in enumerate(top_positions, 1):
            activity_emoji = "🟢" if "LONG" in pos.activity else "🔴"
            lines.append(f"   {i}. {activity_emoji} ${pos.position_size/1_000_000:.2f}M | PnL: ${pos.total_pnl/1000:.1f}K | {pos.leverage}")
    
    return "\n".join(lines)

