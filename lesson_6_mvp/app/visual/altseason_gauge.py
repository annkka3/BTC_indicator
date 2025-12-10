# app/visual/altseason_gauge.py
"""
Горизонтальный gauge-график для Altcoin Season Index в стиле blockchaincenter.net
"""
from __future__ import annotations
import io
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.patches import Rectangle, FancyBboxPatch
import numpy as np


def render_altseason_gauge(value: float, label: str, historical: list = None) -> bytes:
    """
    Рисует горизонтальный gauge-график для Altcoin Season Index.
    
    Args:
        value: Значение индекса (0-100) - БЕЗ процентов, просто число
        label: Метка ("Altcoin Season" или "Bitcoin Season")
        historical: Список исторических значений [{"value": float, "label": str}]
    
    Returns:
        PNG bytes
    """
    # Ограничиваем значение
    v = max(0.0, min(100.0, float(value)))
    
    # Создаем фигуру (широкий прямоугольник для горизонтального gauge)
    fig = plt.figure(figsize=(12, 6), dpi=200, facecolor='white')
    ax = fig.add_subplot(111)
    ax.set_xlim(0, 12)
    ax.set_ylim(0, 6)
    ax.axis('off')
    
    # Заголовок вверху слева
    ax.text(
        0.5, 5.5,
        "Altcoin Season Index",
        ha='left', va='center',
        fontsize=24, weight='bold',
        color='#1a1a2e',  # Темно-синий
        zorder=10
    )
    
    # Значение индекса вверху справа (БЕЗ процентов)
    ax.text(
        11.5, 5.5,
        f"{int(round(v))}",
        ha='right', va='center',
        fontsize=32, weight='bold',
        color='#1a1a2e',  # Темно-синий
        zorder=10
    )
    
    # Параметры горизонтальной полосы
    bar_x = 0.5
    bar_y = 3.5
    bar_width = 11.0
    bar_height = 0.8
    
    # Создаем градиентную полосу используя imshow для плавного градиента
    # Градиент от оранжевого/коричневого (Bitcoin Season) к синему/фиолетовому (Altcoin Season)
    # Цвета из изображения: оранжевый/коричневый -> красновато-фиолетовый -> синий/фиолетовый
    
    # Создаем массив для градиента
    gradient_width = 1000
    gradient = np.zeros((1, gradient_width, 3))
    
    for i in range(gradient_width):
        pos = i / gradient_width
        
        # Градиент: оранжевый/коричневый -> красновато-фиолетовый -> синий/фиолетовый
        # Более точные цвета из изображения
        if pos < 0.33:
            # От оранжевого/коричневого к красновато-фиолетовому
            t = pos / 0.33
            r = 0.85 + (0.55 - 0.85) * t  # 0.85 -> 0.55
            g = 0.50 + (0.30 - 0.50) * t  # 0.50 -> 0.30
            b = 0.25 + (0.45 - 0.25) * t  # 0.25 -> 0.45
        elif pos < 0.67:
            # От красновато-фиолетового к фиолетовому
            t = (pos - 0.33) / 0.34
            r = 0.55 + (0.40 - 0.55) * t  # 0.55 -> 0.40
            g = 0.30 + (0.25 - 0.30) * t  # 0.30 -> 0.25
            b = 0.45 + (0.60 - 0.45) * t  # 0.45 -> 0.60
        else:
            # От фиолетового к синему/фиолетовому
            t = (pos - 0.67) / 0.33
            r = 0.40 + (0.20 - 0.40) * t  # 0.40 -> 0.20
            g = 0.25 + (0.50 - 0.25) * t  # 0.25 -> 0.50
            b = 0.60 + (0.80 - 0.60) * t  # 0.60 -> 0.80
        
        gradient[0, i] = [r, g, b]
    
    # Рисуем градиент с закругленными краями
    # Используем imshow для плавного градиента
    im = ax.imshow(gradient, aspect='auto', extent=[bar_x, bar_x + bar_width, bar_y, bar_y + bar_height], 
                   origin='lower', zorder=1, interpolation='bilinear')
    
    # Добавляем закругленную рамку поверх градиента для закругленных краев
    rounded_bar = FancyBboxPatch(
        (bar_x, bar_y), bar_width, bar_height,
        boxstyle="round,pad=0.02", mutation_aspect=bar_height/bar_width,
        facecolor='none', edgecolor='white', linewidth=0, zorder=2
    )
    # Создаем маску для закругленных краев
    # Рисуем белые закругленные прямоугольники по краям для маскировки
    corner_radius = bar_height * 0.5
    # Левый край
    left_mask = FancyBboxPatch(
        (bar_x - corner_radius, bar_y - 0.1), corner_radius, bar_height + 0.2,
        boxstyle="round,pad=0", mutation_aspect=1.0,
        facecolor='white', edgecolor='none', linewidth=0, zorder=3
    )
    ax.add_patch(left_mask)
    # Правый край
    right_mask = FancyBboxPatch(
        (bar_x + bar_width, bar_y - 0.1), corner_radius, bar_height + 0.2,
        boxstyle="round,pad=0", mutation_aspect=1.0,
        facecolor='white', edgecolor='none', linewidth=0, zorder=3
    )
    ax.add_patch(right_mask)
    
    # Метки под полосой
    ax.text(
        bar_x, bar_y - 0.8,
        "Bitcoin Season",
        ha='left', va='top',
        fontsize=14, weight='normal',
        color='#1a1a2e',
        zorder=10
    )
    
    ax.text(
        bar_x + bar_width, bar_y - 0.8,
        "Altcoin Season",
        ha='right', va='top',
        fontsize=14, weight='normal',
        color='#1a1a2e',
        zorder=10
    )
    
    # Вертикальный индикатор (слайдер) - тонкая вертикальная линия
    indicator_x = bar_x + (v / 100.0) * bar_width
    indicator_color = '#90EE90'  # Светло-зеленый из изображения
    
    # Рисуем вертикальную линию-индикатор (тонкая прямоугольная рамка)
    indicator_width = 0.08
    indicator_rect = Rectangle(
        (indicator_x - indicator_width/2, bar_y - 0.15),
        indicator_width,
        bar_height + 0.3,
        facecolor='none',
        edgecolor=indicator_color,
        linewidth=2.5,
        zorder=5
    )
    ax.add_patch(indicator_rect)
    
    # Добавляем небольшой прямоугольник внутри для лучшей видимости
    indicator_fill = Rectangle(
        (indicator_x - indicator_width/2 + 0.01, bar_y - 0.14),
        indicator_width - 0.02,
        bar_height + 0.28,
        facecolor=indicator_color,
        edgecolor='none',
        alpha=0.2,
        zorder=4
    )
    ax.add_patch(indicator_fill)
    
    # Добавляем надпись в зависимости от значения индекса
    if v >= 70:
        season_text = "Altcoin season"
        season_color = '#1a1a2e'  # Темно-синий
    else:
        season_text = "It's not altcoin season"
        season_color = '#666666'  # Серый
    
    # Размещаем надпись под индикатором
    ax.text(
        indicator_x, bar_y - 1.5,
        season_text,
        ha='center', va='top',
        fontsize=16, weight='bold',
        color=season_color,
        zorder=10
    )
    
    plt.tight_layout()
    
    # Сохраняем в bytes с высоким качеством
    buf = io.BytesIO()
    fig.savefig(buf, format='png', bbox_inches='tight', facecolor='white', dpi=200, pad_inches=0.3)
    plt.close(fig)
    buf.seek(0)
    return buf.getvalue()
