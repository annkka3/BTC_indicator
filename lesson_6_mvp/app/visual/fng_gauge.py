# app/visual/fng_gauge.py
"""
Красивый gauge-график для Fear & Greed Index в стиле альтернативных.me
"""
from __future__ import annotations
import io
import math
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.patches import Arc, Circle, FancyBboxPatch
import numpy as np


def render_fng_gauge(value: int, classification: str, historical: list = None) -> bytes:
    """
    Рисует красивый gauge-график для Fear & Greed Index.
    
    Args:
        value: Значение индекса (0-100)
        classification: Классификация ("Extreme Fear", "Fear", "Neutral", "Greed", "Extreme Greed")
        historical: Список исторических значений [{"value": int, "classification": str, "label": str}]
    
    Returns:
        PNG bytes
    """
    # Ограничиваем значение
    v = max(0, min(100, int(value)))
    
    # Цвета для зон
    colors = {
        "Extreme Fear": "#FF0000",      # Красный
        "Fear": "#FF6B35",              # Оранжево-красный
        "Neutral": "#F7931A",           # Оранжевый/желтый
        "Greed": "#00D9FF",             # Голубой
        "Extreme Greed": "#00FF00",     # Зеленый
    }
    
    # Определяем цвет текущего значения
    current_color = colors.get(classification, "#F7931A")
    
    # Создаем фигуру
    fig = plt.figure(figsize=(10, 6), dpi=150, facecolor='white')
    ax = fig.add_subplot(111)
    ax.set_xlim(0, 10)
    ax.set_ylim(0, 6)
    ax.axis('off')
    
    # Центр gauge
    center_x, center_y = 3.5, 3.5
    radius = 2.5
    
    # Рисуем полукруг gauge (180 градусов)
    start_angle = 180
    end_angle = 0
    
    # Рисуем зоны gauge
    # Значение 0 = 180 градусов (слева), значение 100 = 0 градусов (справа)
    zones = [
        (0, 25, "#FF0000", "EXTREME\nFEAR"),
        (25, 50, "#FF6B35", "FEAR"),
        (50, 75, "#F7931A", "NEUTRAL"),
        (75, 100, "#00D9FF", "GREED"),
    ]
    
    # Рисуем зоны
    for start_val, end_val, color, label in zones:
        # Преобразуем значения в углы: 0 -> 180°, 100 -> 0°
        start_ang = 180 - (start_val / 100) * 180
        end_ang = 180 - (end_val / 100) * 180
        
        # Создаем дугу для зоны (theta1 - начальный угол, theta2 - конечный угол)
        # Углы идут против часовой стрелки, поэтому start_ang > end_ang
        arc = Arc(
            (center_x, center_y), 
            radius * 2, 
            radius * 2,
            angle=0,
            theta1=end_ang,  # Конечный угол (меньше)
            theta2=start_ang,  # Начальный угол (больше)
            linewidth=40,
            color=color,
            alpha=0.4,
            zorder=1
        )
        ax.add_patch(arc)
        
        # Подписи зон
        mid_val = (start_val + end_val) / 2
        mid_ang = 180 - (mid_val / 100) * 180
        mid_rad = math.radians(mid_ang)
        label_x = center_x + (radius + 0.4) * math.cos(mid_rad)
        label_y = center_y + (radius + 0.4) * math.sin(mid_rad)
        
        # Вычисляем угол поворота текста
        rotation = mid_ang - 90
        
        ax.text(
            label_x, label_y, label,
            ha='center', va='center',
            fontsize=8, weight='bold',
            color='#333333',
            rotation=rotation,
            zorder=3
        )
    
    # Рисуем деления
    for i in range(0, 101, 25):
        angle = 180 - (i / 100) * 180
        rad = math.radians(angle)
        
        # Внешняя точка
        x1 = center_x + radius * math.cos(rad)
        y1 = center_y + radius * math.sin(rad)
        
        # Внутренняя точка
        x2 = center_x + (radius - 0.15) * math.cos(rad)
        y2 = center_y + (radius - 0.15) * math.sin(rad)
        
        ax.plot([x1, x2], [y1, y2], 'k-', linewidth=1.5, alpha=0.5, zorder=2)
        
        # Подписи значений
        x_label = center_x + (radius + 0.5) * math.cos(rad)
        y_label = center_y + (radius + 0.5) * math.sin(rad)
        ax.text(x_label, y_label, str(i), ha='center', va='center', fontsize=9, color='#666666', zorder=3)
    
    # Рисуем стрелку (needle)
    angle = 180 - (v / 100) * 180
    rad = math.radians(angle)
    
    # Длина стрелки
    needle_length = radius * 0.85
    
    # Конец стрелки
    needle_x = center_x + needle_length * math.cos(rad)
    needle_y = center_y + needle_length * math.sin(rad)
    
    # Рисуем стрелку
    ax.plot([center_x, needle_x], [center_y, needle_y], 'k-', linewidth=4, zorder=4)
    
    # Круг в центре
    circle = Circle((center_x, center_y), 0.15, color='white', edgecolor='black', linewidth=2, zorder=5)
    ax.add_patch(circle)
    
    # Текущее значение в центре
    ax.text(
        center_x, center_y - 0.5,
        str(v),
        ha='center', va='center',
        fontsize=48, weight='bold',
        color='black',
        zorder=6
    )
    
    # Заголовок
    ax.text(
        3.5, 5.5,
        "Fear & Greed Index",
        ha='center', va='center',
        fontsize=20, weight='bold',
        color='black',
        zorder=7
    )
    
    # Классификация
    ax.text(
        3.5, 0.8,
        classification,
        ha='center', va='center',
        fontsize=14, weight='bold',
        color=current_color,
        zorder=7
    )
    
    # Исторические значения справа
    if historical:
        x_start = 6.5
        y_start = 5.0
        
        ax.text(
            x_start, y_start,
            "Historical Values",
            ha='left', va='top',
            fontsize=12, weight='bold',
            color='black',
            zorder=7
        )
        
        y_pos = y_start - 0.5
        for hist in historical[:4]:  # Показываем до 4 значений
            hist_val = hist.get("value", 0)
            hist_label = hist.get("label", "")
            hist_class = hist.get("classification", "")
            
            # Цвет кружка
            hist_color = colors.get(hist_class, "#F7931A")
            
            # Кружок с значением
            circle_hist = Circle((x_start, y_pos), 0.2, color=hist_color, alpha=0.7, zorder=6)
            ax.add_patch(circle_hist)
            ax.text(
                x_start, y_pos,
                str(hist_val),
                ha='center', va='center',
                fontsize=10, weight='bold',
                color='white',
                zorder=7
            )
            
            # Текст
            ax.text(
                x_start + 0.5, y_pos,
                f"{hist_label}: {hist_class}",
                ha='left', va='center',
                fontsize=10,
                color='#333333',
                zorder=7
            )
            
            y_pos -= 0.6
    
    plt.tight_layout()
    
    # Сохраняем в bytes
    buf = io.BytesIO()
    fig.savefig(buf, format='png', bbox_inches='tight', facecolor='white', dpi=150)
    plt.close(fig)
    buf.seek(0)
    return buf.getvalue()

