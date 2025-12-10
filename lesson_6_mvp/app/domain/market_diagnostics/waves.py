# app/domain/market_diagnostics/waves.py
"""
Упрощённый волновой анализ: legs (ноги) движения цены.

Не полный Эллиотт, а простой анализ последовательности импульсов и коррекций.
"""

from dataclasses import dataclass
from typing import List, Optional
import pandas as pd
import numpy as np

from .structure_levels import find_swings


@dataclass
class PriceLeg:
    """Нога движения цены (импульс или коррекция)."""
    direction: str   # "up" / "down"
    start_idx: int
    end_idx: int
    start_price: float
    end_price: float
    length_pct: float  # Амплитуда в процентах
    duration_bars: int  # Длительность в барах
    volume_avg: float  # Средний объём на ноге
    is_impulse: bool = False  # Является ли импульсом (длинная, сильная)


def analyze_legs(
    df: pd.DataFrame,
    swing_highs: List[int],
    swing_lows: List[int],
    min_leg_pct: float = 2.0
) -> List[PriceLeg]:
    """
    Проанализировать ноги движения цены из swing-ов.
    
    Args:
        df: DataFrame с OHLCV данными
        swing_highs: Индексы swing highs
        swing_lows: Индексы swing lows
        min_leg_pct: Минимальная амплитуда ноги в процентах
    
    Returns:
        Список PriceLeg объектов
    """
    if len(swing_highs) < 2 or len(swing_lows) < 2:
        return []
    
    legs = []
    
    # Объединяем все swing-и в хронологическом порядке
    all_swings = []
    for idx in swing_highs:
        all_swings.append(('high', idx, df['high'].iloc[idx]))
    for idx in swing_lows:
        all_swings.append(('low', idx, df['low'].iloc[idx]))
    
    all_swings.sort(key=lambda x: x[1])  # Сортируем по индексу
    
    if len(all_swings) < 2:
        return []
    
    # Строим ноги между соседними swing-ами
    for i in range(len(all_swings) - 1):
        swing1_type, swing1_idx, swing1_price = all_swings[i]
        swing2_type, swing2_idx, swing2_price = all_swings[i + 1]
        
        # Определяем направление ноги
        if swing1_type == 'low' and swing2_type == 'high':
            direction = "up"
            start_price = swing1_price
            end_price = swing2_price
        elif swing1_type == 'high' and swing2_type == 'low':
            direction = "down"
            start_price = swing1_price
            end_price = swing2_price
        else:
            continue  # Пропускаем ноги между однотипными swing-ами
        
        # Рассчитываем амплитуду
        length_pct = abs((end_price - start_price) / start_price * 100)
        
        if length_pct < min_leg_pct:
            continue  # Пропускаем слишком маленькие ноги
        
        duration = swing2_idx - swing1_idx
        
        # Средний объём на ноге
        if 'volume' in df.columns:
            volume_avg = df['volume'].iloc[swing1_idx:swing2_idx + 1].mean()
        else:
            volume_avg = 0.0
        
        leg = PriceLeg(
            direction=direction,
            start_idx=swing1_idx,
            end_idx=swing2_idx,
            start_price=start_price,
            end_price=end_price,
            length_pct=length_pct,
            duration_bars=duration,
            volume_avg=volume_avg,
            is_impulse=False
        )
        
        legs.append(leg)
    
    # Определяем импульсы (длинные, сильные ноги)
    if legs:
        avg_length = np.mean([l.length_pct for l in legs])
        avg_volume = np.mean([l.volume_avg for l in legs if l.volume_avg > 0])
        
        for leg in legs:
            # Импульс: длина выше среднего и объём выше среднего
            if leg.length_pct > avg_length * 1.2:
                if avg_volume > 0 and leg.volume_avg > avg_volume * 1.1:
                    leg.is_impulse = True
                elif avg_volume == 0:
                    leg.is_impulse = True
    
    return legs


def generate_legs_summary(legs: List[PriceLeg], current_price: float) -> str:
    """
    Сгенерировать текстовое описание структуры движений.
    
    Args:
        legs: Список ног движения
        current_price: Текущая цена
    
    Returns:
        Текстовое описание
    """
    if not legs:
        return "Недостаточно данных для анализа структуры"
    
    # Берем последние 3 ноги
    recent_legs = legs[-3:]
    
    parts = []
    
    for i, leg in enumerate(recent_legs):
        direction_emoji = "↑" if leg.direction == "up" else "↓"
        impulse_marker = " (импульс)" if leg.is_impulse else " (коррекция)"
        
        parts.append(
            f"{direction_emoji} {leg.direction}: {leg.length_pct:.1f}% за {leg.duration_bars} баров{impulse_marker}"
        )
    
    # Определяем текущую фазу
    if recent_legs:
        last_leg = recent_legs[-1]
        
        if last_leg.direction == "up" and last_leg.is_impulse:
            phase_desc = "активный рост"
        elif last_leg.direction == "down" and last_leg.is_impulse:
            phase_desc = "активное падение"
        elif last_leg.direction == "up" and not last_leg.is_impulse:
            phase_desc = "коррекция вверх после падения"
        elif last_leg.direction == "down" and not last_leg.is_impulse:
            phase_desc = "коррекция вниз после роста"
        else:
            phase_desc = "неопределённая фаза"
        
        parts.append(f"Текущая фаза: {phase_desc}")
    
    return " | ".join(parts)







