# app/domain/market_diagnostics/elliott_waves.py
"""
Модуль для определения волн Эллиотта (Elliott Wave Theory).
"""

from typing import List, Optional, Tuple, Dict
from dataclasses import dataclass
from enum import Enum
import pandas as pd
import numpy as np


class WaveType(Enum):
    """Тип волны Эллиотта."""
    IMPULSE = "impulse"  # Импульсная волна (1, 3, 5)
    CORRECTIVE = "corrective"  # Коррекционная волна (2, 4)
    UNKNOWN = "unknown"


@dataclass
class ElliottWave:
    """Волна Эллиотта."""
    wave_number: int  # Номер волны (1-5 для импульса, A-B-C для коррекции)
    start_idx: int  # Индекс начала волны
    end_idx: int  # Индекс конца волны
    start_price: float  # Цена начала волны
    end_price: float  # Цена конца волны
    wave_type: WaveType  # Тип волны
    length_pct: float  # Длина волны в процентах от предыдущей
    confidence: float  # Уверенность в определении волны (0-1)


@dataclass
class ElliottWavePattern:
    """Паттерн волн Эллиотта."""
    pattern_type: str  # "impulse_5" (1-2-3-4-5), "corrective_abc" (A-B-C), "unknown"
    waves: List[ElliottWave]  # Список волн
    current_wave: Optional[int] = None  # Текущая волна (1-5 или A-C)
    trend_direction: str = "unknown"  # "up" или "down"
    confidence: float = 0.0  # Общая уверенность в паттерне (0-1)
    target_levels: Optional[List[float]] = None  # Целевые уровни для завершения паттерна


def find_pivots(highs: List[float], lows: List[float], 
                lookback: int = 3) -> Tuple[List[Tuple[int, float]], List[Tuple[int, float]]]:
    """
    Найти все пивоты (локальные максимумы и минимумы).
    
    Args:
        highs: Список максимумов
        lows: Список минимумов
        lookback: Количество баров для определения пивота
    
    Returns:
        Tuple[List[Tuple[int, float]], List[Tuple[int, float]]]:
        (список_highs, список_lows) где каждый элемент это (индекс, цена)
    """
    pivot_highs = []
    pivot_lows = []
    
    if len(highs) < lookback * 2 + 1 or len(lows) < lookback * 2 + 1:
        return pivot_highs, pivot_lows
    
    # Находим все пивоты high
    for i in range(lookback, len(highs) - lookback):
        is_pivot = True
        current_high = highs[i]
        
        for j in range(i - lookback, i + lookback + 1):
            if j != i and highs[j] >= current_high:
                is_pivot = False
                break
        
        if is_pivot:
            pivot_highs.append((i, current_high))
    
    # Находим все пивоты low
    for i in range(lookback, len(lows) - lookback):
        is_pivot = True
        current_low = lows[i]
        
        for j in range(i - lookback, i + lookback + 1):
            if j != i and lows[j] <= current_low:
                is_pivot = False
                break
        
        if is_pivot:
            pivot_lows.append((i, current_low))
    
    return pivot_highs, pivot_lows


def identify_wave_type(wave_start: float, wave_end: float, 
                      prev_wave_start: Optional[float] = None,
                      prev_wave_end: Optional[float] = None) -> Tuple[WaveType, float]:
    """
    Определить тип волны на основе её характеристик.
    
    Args:
        wave_start: Цена начала волны
        wave_end: Цена конца волны
        prev_wave_start: Цена начала предыдущей волны
        prev_wave_end: Цена конца предыдущей волны
    
    Returns:
        Tuple[WaveType, float]: (тип волны, уверенность)
    """
    wave_direction = "up" if wave_end > wave_start else "down"
    wave_length = abs(wave_end - wave_start)
    
    # Базовые правила для определения типа волны
    # Импульсные волны обычно длиннее коррекционных
    # Волна 3 обычно самая длинная в импульсе
    # Волна 2 обычно коррекция 50-61.8% от волны 1
    
    confidence = 0.5  # Базовая уверенность
    
    if prev_wave_start is not None and prev_wave_end is not None:
        prev_wave_length = abs(prev_wave_end - prev_wave_start)
        if prev_wave_length > 0:
            ratio = wave_length / prev_wave_length
            
            # Если волна значительно длиннее предыдущей, это может быть импульсная волна 3
            if ratio > 1.618:
                return WaveType.IMPULSE, 0.7
            # Если волна значительно короче (30-70% от предыдущей), это может быть коррекция
            elif 0.3 <= ratio <= 0.7:
                return WaveType.CORRECTIVE, 0.6
    
    return WaveType.UNKNOWN, confidence


def identify_elliott_pattern(pivot_highs: List[Tuple[int, float]], 
                             pivot_lows: List[Tuple[int, float]],
                             current_price: float) -> Optional[ElliottWavePattern]:
    """
    Определить паттерн волн Эллиотта из пивотов.
    
    Args:
        pivot_highs: Список пивотов максимумов [(индекс, цена), ...]
        pivot_lows: Список пивотов минимумов [(индекс, цена), ...]
        current_price: Текущая цена
    
    Returns:
        ElliottWavePattern или None
    """
    if len(pivot_highs) < 3 or len(pivot_lows) < 3:
        return None
    
    # Объединяем все пивоты в хронологическом порядке
    all_pivots = []
    for idx, price in pivot_highs:
        all_pivots.append((idx, price, "high"))
    for idx, price in pivot_lows:
        all_pivots.append((idx, price, "low"))
    
    all_pivots.sort(key=lambda x: x[0])  # Сортируем по индексу
    
    if len(all_pivots) < 5:
        return None
    
    # Берем последние 5-9 пивотов для анализа
    recent_pivots = all_pivots[-9:] if len(all_pivots) >= 9 else all_pivots
    
    waves = []
    trend_direction = "unknown"
    
    # Упрощенный анализ: ищем паттерн 1-2-3-4-5 или A-B-C
    # Для импульсного паттерна (1-2-3-4-5):
    # - Волны 1, 3, 5 в направлении тренда
    # - Волны 2, 4 против тренда (коррекции)
    
    # Определяем общее направление тренда
    if len(recent_pivots) >= 2:
        first_price = recent_pivots[0][1]
        last_price = recent_pivots[-1][1]
        trend_direction = "up" if last_price > first_price else "down"
    
    # Пытаемся идентифицировать волны
    wave_number = 1
    pattern_type = "unknown"
    confidence = 0.3
    
    for i in range(len(recent_pivots) - 1):
        start_idx, start_price, start_type = recent_pivots[i]
        end_idx, end_price, end_type = recent_pivots[i + 1]
        
        # Определяем тип волны
        prev_wave = waves[-1] if waves else None
        wave_type, wave_confidence = identify_wave_type(
            start_price, end_price,
            prev_wave.start_price if prev_wave else None,
            prev_wave.end_price if prev_wave else None
        )
        
        # Вычисляем длину в процентах
        length_pct = 0.0
        if prev_wave and abs(prev_wave.end_price - prev_wave.start_price) > 0:
            length_pct = (abs(end_price - start_price) / 
                         abs(prev_wave.end_price - prev_wave.start_price)) * 100
        
        wave = ElliottWave(
            wave_number=wave_number,
            start_idx=start_idx,
            end_idx=end_idx,
            start_price=start_price,
            end_price=end_price,
            wave_type=wave_type,
            length_pct=length_pct,
            confidence=wave_confidence
        )
        
        waves.append(wave)
        wave_number += 1
        
        if wave_number > 5:
            break
    
    # Определяем тип паттерна
    if len(waves) >= 5:
        # Проверяем, похоже ли на импульсный паттерн 1-2-3-4-5
        impulse_waves = [w for w in waves if w.wave_type == WaveType.IMPULSE]
        if len(impulse_waves) >= 3:
            pattern_type = "impulse_5"
            confidence = 0.6
    elif len(waves) >= 3:
        # Проверяем, похоже ли на коррекционный паттерн A-B-C
        pattern_type = "corrective_abc"
        confidence = 0.4
    
    # Определяем текущую волну
    current_wave = None
    if waves:
        last_wave = waves[-1]
        # Если текущая цена близка к концу последней волны, возможно начинается новая
        if abs(current_price - last_wave.end_price) / last_wave.end_price < 0.02:
            current_wave = len(waves) + 1
        else:
            current_wave = len(waves)
    
    # Рассчитываем целевые уровни (упрощенно)
    target_levels: Optional[List[float]] = None
    if waves and pattern_type == "impulse_5":
        target_levels = []
        last_wave = waves[-1]
        if trend_direction == "up":
            # Для восходящего тренда: цель = последняя волна * 1.618
            target = last_wave.end_price + (last_wave.end_price - last_wave.start_price) * 0.618
            target_levels.append(target)
        else:
            # Для нисходящего тренда
            target = last_wave.end_price - (last_wave.start_price - last_wave.end_price) * 0.618
            target_levels.append(target)
    
    return ElliottWavePattern(
        pattern_type=pattern_type,
        waves=waves,
        current_wave=current_wave,
        trend_direction=trend_direction,
        confidence=confidence,
        target_levels=target_levels
    )


def analyze_elliott_waves(df: pd.DataFrame, current_price: Optional[float] = None) -> Optional[ElliottWavePattern]:
    """
    Проанализировать волны Эллиотта для DataFrame.
    
    Args:
        df: DataFrame с колонками ['high', 'low', 'close']
        current_price: Текущая цена (если None, используется последняя close)
    
    Returns:
        ElliottWavePattern или None, если недостаточно данных
    """
    if df is None or df.empty or len(df) < 30:
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
    
    # Находим все пивоты
    pivot_highs, pivot_lows = find_pivots(highs, lows, lookback=3)
    
    if len(pivot_highs) < 3 or len(pivot_lows) < 3:
        return None
    
    # Определяем паттерн волн Эллиотта
    pattern = identify_elliott_pattern(pivot_highs, pivot_lows, current_price)
    
    return pattern

