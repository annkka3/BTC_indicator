# app/domain/market_diagnostics/fibonacci.py
"""
Модуль для расчета уровней Фибоначчи (Fibonacci Retracement и Extension).
"""

from typing import List, Optional, Tuple
from dataclasses import dataclass
import pandas as pd
import numpy as np


@dataclass
class FibonacciLevel:
    """Уровень Фибоначчи."""
    level: float  # Цена уровня
    ratio: float  # Коэффициент Фибоначчи (0.236, 0.382, 0.5, 0.618, 0.786, 1.0, 1.272, 1.618)
    name: str  # Название уровня (например, "23.6%", "38.2%", "61.8%")
    type: str  # "retracement" или "extension"


@dataclass
class FibonacciAnalysis:
    """Анализ уровней Фибоначчи."""
    swing_high: float  # Максимальная точка свинга
    swing_low: float  # Минимальная точка свинга
    swing_high_idx: int  # Индекс максимума
    swing_low_idx: int  # Индекс минимума
    retracement_levels: List[FibonacciLevel]  # Уровни коррекции
    extension_levels: List[FibonacciLevel]  # Уровни расширения
    current_price: float  # Текущая цена
    nearest_level: Optional[FibonacciLevel] = None  # Ближайший уровень к текущей цене


# Стандартные коэффициенты Фибоначчи
FIBONACCI_RETRACEMENT_RATIOS = [0.0, 0.236, 0.382, 0.5, 0.618, 0.786, 1.0]
FIBONACCI_EXTENSION_RATIOS = [1.0, 1.272, 1.618, 2.0, 2.618]


def find_swing_points(highs: List[float], lows: List[float], 
                      lookback: int = 5) -> Tuple[Optional[Tuple[int, float]], Optional[Tuple[int, float]]]:
    """
    Найти точки свинга (swing high и swing low).
    
    Args:
        highs: Список максимумов
        lows: Список минимумов
        lookback: Количество баров для определения свинга
    
    Returns:
        Tuple[Optional[Tuple[int, float]], Optional[Tuple[int, float]]]:
        ((индекс_high, цена_high), (индекс_low, цена_low))
    """
    if len(highs) < lookback * 2 + 1 or len(lows) < lookback * 2 + 1:
        return None, None
    
    # Ищем последний swing high
    swing_high = None
    swing_high_idx = None
    
    for i in range(lookback, len(highs) - lookback):
        is_swing_high = True
        current_high = highs[i]
        
        # Проверяем, что это максимум среди соседних баров
        for j in range(i - lookback, i + lookback + 1):
            if j != i and highs[j] >= current_high:
                is_swing_high = False
                break
        
        if is_swing_high:
            swing_high = current_high
            swing_high_idx = i
    
    # Ищем последний swing low
    swing_low = None
    swing_low_idx = None
    
    for i in range(lookback, len(lows) - lookback):
        is_swing_low = True
        current_low = lows[i]
        
        # Проверяем, что это минимум среди соседних баров
        for j in range(i - lookback, i + lookback + 1):
            if j != i and lows[j] <= current_low:
                is_swing_low = False
                break
        
        if is_swing_low:
            swing_low = current_low
            swing_low_idx = i
    
    if swing_high_idx is not None and swing_low_idx is not None:
        return (swing_high_idx, swing_high), (swing_low_idx, swing_low)
    
    return None, None


def calculate_fibonacci_levels(
    swing_high: float,
    swing_low: float,
    current_price: float,
    direction: str = "auto"  # "up", "down", "auto"
) -> FibonacciAnalysis:
    """
    Рассчитать уровни Фибоначчи.
    
    Args:
        swing_high: Максимальная точка свинга
        swing_low: Минимальная точка свинга
        current_price: Текущая цена
        direction: Направление тренда ("up" если восходящий, "down" если нисходящий, "auto" для автоматического определения)
    
    Returns:
        FibonacciAnalysis с рассчитанными уровнями
    """
    if swing_high <= swing_low:
        # Если данные некорректны, используем текущую цену
        swing_high = max(swing_high, current_price * 1.1)
        swing_low = min(swing_low, current_price * 0.9)
    
    # Определяем направление тренда
    if direction == "auto":
        # Если текущая цена ближе к high, считаем что тренд был вверх (коррекция вниз)
        # Если ближе к low, считаем что тренд был вниз (коррекция вверх)
        mid = (swing_high + swing_low) / 2
        direction = "up" if current_price > mid else "down"
    
    # Разница между high и low
    diff = swing_high - swing_low
    
    # Рассчитываем уровни коррекции
    retracement_levels = []
    if direction == "up":
        # Восходящий тренд: коррекция от high к low
        base = swing_high
        for ratio in FIBONACCI_RETRACEMENT_RATIOS:
            level_price = swing_high - (diff * ratio)
            name = f"{ratio * 100:.1f}%" if ratio > 0 else "0%"
            retracement_levels.append(
                FibonacciLevel(
                    level=level_price,
                    ratio=ratio,
                    name=name,
                    type="retracement"
                )
            )
    else:
        # Нисходящий тренд: коррекция от low к high
        base = swing_low
        for ratio in FIBONACCI_RETRACEMENT_RATIOS:
            level_price = swing_low + (diff * ratio)
            name = f"{ratio * 100:.1f}%" if ratio < 1.0 else "100%"
            retracement_levels.append(
                FibonacciLevel(
                    level=level_price,
                    ratio=ratio,
                    name=name,
                    type="retracement"
                )
            )
    
    # Рассчитываем уровни расширения
    extension_levels = []
    if direction == "up":
        # Расширение вверх от swing_high
        for ratio in FIBONACCI_EXTENSION_RATIOS:
            if ratio > 1.0:
                level_price = swing_low + (diff * ratio)
                name = f"{ratio * 100:.1f}%"
                extension_levels.append(
                    FibonacciLevel(
                        level=level_price,
                        ratio=ratio,
                        name=name,
                        type="extension"
                    )
                )
    else:
        # Расширение вниз от swing_low
        for ratio in FIBONACCI_EXTENSION_RATIOS:
            if ratio > 1.0:
                level_price = swing_high - (diff * ratio)
                name = f"{ratio * 100:.1f}%"
                extension_levels.append(
                    FibonacciLevel(
                        level=level_price,
                        ratio=ratio,
                        name=name,
                        type="extension"
                    )
                )
    
    # Находим ближайший уровень к текущей цене
    nearest_level = None
    min_distance = float('inf')
    
    all_levels = retracement_levels + extension_levels
    for level in all_levels:
        distance = abs(level.level - current_price)
        if distance < min_distance:
            min_distance = distance
            nearest_level = level
    
    return FibonacciAnalysis(
        swing_high=swing_high,
        swing_low=swing_low,
        swing_high_idx=0,  # Будет установлено при вызове
        swing_low_idx=0,  # Будет установлено при вызове
        retracement_levels=retracement_levels,
        extension_levels=extension_levels,
        current_price=current_price,
        nearest_level=nearest_level
    )


def analyze_fibonacci(df: pd.DataFrame, current_price: Optional[float] = None) -> Optional[FibonacciAnalysis]:
    """
    Проанализировать уровни Фибоначчи для DataFrame.
    
    Args:
        df: DataFrame с колонками ['high', 'low', 'close']
        current_price: Текущая цена (если None, используется последняя close)
    
    Returns:
        FibonacciAnalysis или None, если недостаточно данных
    """
    if df is None or df.empty or len(df) < 20:
        return None
    
    if 'high' not in df.columns or 'low' not in df.columns:
        return None
    
    highs = df['high'].tolist()
    lows = df['low'].tolist()
    closes = df['close'].tolist()
    
    if current_price is None:
        current_price = closes[-1] if closes else None
    
    if current_price is None:
        return None
    
    # Находим точки свинга
    swing_high_data, swing_low_data = find_swing_points(highs, lows, lookback=5)
    
    if swing_high_data is None or swing_low_data is None:
        # Если не нашли свинги, используем максимум и минимум из последних данных
        recent_highs = highs[-50:] if len(highs) >= 50 else highs
        recent_lows = lows[-50:] if len(lows) >= 50 else lows
        
        swing_high = max(recent_highs)
        swing_low = min(recent_lows)
        swing_high_idx = len(highs) - 1 - recent_highs[::-1].index(swing_high)
        swing_low_idx = len(lows) - 1 - recent_lows[::-1].index(swing_low)
    else:
        swing_high_idx, swing_high = swing_high_data
        swing_low_idx, swing_low = swing_low_data
    
    # Рассчитываем уровни Фибоначчи
    fib_analysis = calculate_fibonacci_levels(
        swing_high=swing_high,
        swing_low=swing_low,
        current_price=current_price
    )
    
    # Устанавливаем индексы
    fib_analysis.swing_high_idx = swing_high_idx
    fib_analysis.swing_low_idx = swing_low_idx
    
    return fib_analysis















