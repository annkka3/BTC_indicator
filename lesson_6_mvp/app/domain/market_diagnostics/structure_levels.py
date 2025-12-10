# app/domain/market_diagnostics/structure_levels.py
"""
Анализ структуры рынка: swing-и, кластеры уровней поддержки/сопротивления.

Базовый кирпич для SMC и волнового анализа.
"""

from dataclasses import dataclass
from enum import Enum
from typing import List, Tuple, Optional
import pandas as pd
import numpy as np


class LevelKind(str, Enum):
    """Тип уровня."""
    SUPPORT = "support"
    RESISTANCE = "resistance"
    LIQUIDITY_HIGH = "liquidity_high"   # equal highs
    LIQUIDITY_LOW = "liquidity_low"     # equal lows
    ORDERBLOCK_DEMAND = "orderblock_demand"
    ORDERBLOCK_SUPPLY = "orderblock_supply"
    FVG = "fvg"


class LevelOrigin(str, Enum):
    """Происхождение уровня."""
    SWING_HIGH = "swing_high"
    SWING_LOW = "swing_low"
    VPOC = "vpoc"
    ROUND = "round"
    SMC = "smc"


@dataclass
class Level:
    """Уровень поддержки/сопротивления."""
    price: float
    kind: LevelKind
    strength: float        # 0–1
    touched_times: int
    time_first: pd.Timestamp
    time_last: pd.Timestamp
    origin: LevelOrigin
    price_low: Optional[float] = None  # Для зон (order blocks, FVG)
    price_high: Optional[float] = None  # Для зон


def find_swings(df: pd.DataFrame, left: int = 2, right: int = 2) -> Tuple[List[int], List[int]]:
    """
    Найти локальные экстремумы (swing high/low).
    
    Args:
        df: DataFrame с OHLCV данными
        left: Количество баров слева для сравнения
        right: Количество баров справа для сравнения
    
    Returns:
        (highs, lows) - списки индексов swing high и swing low
    """
    if len(df) < left + right + 1:
        return [], []
    
    highs, lows = [], []
    
    for i in range(left, len(df) - right):
        window = df.iloc[i-left:i+right+1]
        
        # Swing high: текущий high максимальный в окне
        if df['high'].iloc[i] == window['high'].max():
            highs.append(i)
        
        # Swing low: текущий low минимальный в окне
        if df['low'].iloc[i] == window['low'].min():
            lows.append(i)
    
    return highs, lows


def cluster_levels(prices: List[float], tolerance_bps: float = 0.3) -> List[float]:
    """
    Кластеризовать уровни по цене.
    
    Группирует близкие по цене уровни в кластеры и возвращает средние цены кластеров.
    
    Args:
        prices: Список цен уровней
        tolerance_bps: Допуск в процентах (0.3 = 0.3%)
    
    Returns:
        Список средних цен кластеров
    """
    if not prices:
        return []
    
    prices = sorted(prices)
    clusters = []
    current = [prices[0]]
    
    for p in prices[1:]:
        # Проверяем, попадает ли цена в текущий кластер
        if abs(p - current[-1]) / current[-1] * 100 <= tolerance_bps:
            current.append(p)
        else:
            # Сохраняем текущий кластер и начинаем новый
            clusters.append(current)
            current = [p]
    
    clusters.append(current)
    
    # Возвращаем средние цены кластеров
    return [sum(c) / len(c) for c in clusters]


def calculate_level_strength(
    level_price: float,
    df: pd.DataFrame,
    swing_indexes: List[int],
    tolerance_bps: float = 0.3
) -> Tuple[float, int]:
    """
    Рассчитать силу уровня на основе касаний и возраста.
    
    Args:
        level_price: Цена уровня
        df: DataFrame с OHLCV данными
        swing_indexes: Индексы swing-ов, которые могут касаться уровня
        tolerance_bps: Допуск для определения касания (в процентах)
    
    Returns:
        (strength, touched_times) - сила уровня (0-1) и количество касаний
    """
    if not swing_indexes:
        return 0.0, 0
    
    tolerance = level_price * tolerance_bps / 100.0
    touched_times = 0
    
    # Подсчитываем касания
    for idx in swing_indexes:
        if idx >= len(df):
            continue
        
        high = df['high'].iloc[idx]
        low = df['low'].iloc[idx]
        
        # Проверяем, пересекает ли свеча уровень
        if low <= level_price + tolerance and high >= level_price - tolerance:
            touched_times += 1
    
    # Также проверяем близкие свечи (не только swing-и)
    close_prices = df['close']
    for price in close_prices:
        if abs(price - level_price) / level_price * 100 <= tolerance_bps:
            touched_times += 0.5  # Меньший вес для не-swing касаний
    
    # Рассчитываем силу на основе касаний и возраста
    # Базовый score от касаний (нормализуем до 0-1)
    touch_score = min(touched_times / 5.0, 1.0)  # Максимум при 5+ касаниях
    
    # Возраст уровня (чем старше, тем сильнее, но с убывающей отдачей)
    if swing_indexes:
        first_touch_idx = min(swing_indexes)
        age_bars = len(df) - first_touch_idx
        age_score = min(age_bars / 100.0, 1.0)  # Максимум при 100+ барах
    else:
        age_score = 0.0
    
    # Объём вблизи уровня (если доступен)
    volume_score = 0.0
    if 'volume' in df.columns:
        tolerance_abs = level_price * tolerance_bps / 100.0
        near_level = df[
            (df['low'] <= level_price + tolerance_abs) &
            (df['high'] >= level_price - tolerance_abs)
        ]
        if len(near_level) > 0:
            avg_volume_near = near_level['volume'].mean()
            avg_volume_all = df['volume'].mean()
            if avg_volume_all > 0:
                volume_ratio = avg_volume_near / avg_volume_all
                volume_score = min(volume_ratio / 2.0, 1.0)  # Максимум при 2x среднего объёма
    
    # Взвешенная комбинация
    strength = (
        0.4 * touch_score +
        0.3 * age_score +
        0.3 * volume_score
    )
    
    return strength, int(touched_times)


def build_support_resistance_levels(
    df: pd.DataFrame,
    left: int = 2,
    right: int = 2,
    tolerance_bps: float = 0.3,
    min_strength: float = 0.2
) -> List[Level]:
    """
    Построить уровни поддержки и сопротивления из swing-ов.
    
    Классификация support/resistance основана на текущей цене:
    - Если уровень ниже текущей цены → SUPPORT
    - Если уровень выше текущей цены → RESISTANCE
    
    Args:
        df: DataFrame с OHLCV данными
        left: Количество баров слева для swing detection
        right: Количество баров справа для swing detection
        tolerance_bps: Допуск для кластеризации (в процентах)
        min_strength: Минимальная сила уровня для включения
    
    Returns:
        Список Level объектов
    """
    if len(df) < left + right + 1:
        return []
    
    # Получаем текущую цену
    current_price = float(df['close'].iloc[-1])
    
    # Находим swing-и
    swing_highs, swing_lows = find_swings(df, left, right)
    
    levels = []
    
    # Обрабатываем swing highs и lows
    all_swing_prices = []
    swing_indices_map = {}  # price -> list of indices
    
    if swing_highs:
        high_prices = [df['high'].iloc[i] for i in swing_highs]
        for price, idx in zip(high_prices, swing_highs):
            all_swing_prices.append(price)
            if price not in swing_indices_map:
                swing_indices_map[price] = []
            swing_indices_map[price].append(idx)
    
    if swing_lows:
        low_prices = [df['low'].iloc[i] for i in swing_lows]
        for price, idx in zip(low_prices, swing_lows):
            all_swing_prices.append(price)
            if price not in swing_indices_map:
                swing_indices_map[price] = []
            swing_indices_map[price].append(idx)
    
    # Кластеризуем все уровни вместе
    clustered_prices = cluster_levels(all_swing_prices, tolerance_bps)
    
    for price in clustered_prices:
        # Определяем все индексы, которые попадают в этот кластер
        cluster_indices = []
        for swing_price, indices in swing_indices_map.items():
            if abs(swing_price - price) / price * 100 <= tolerance_bps:
                cluster_indices.extend(indices)
        
        if not cluster_indices:
            continue
        
        # Рассчитываем силу уровня
        strength, touched = calculate_level_strength(
            price, df, cluster_indices, tolerance_bps
        )
        
        if strength >= min_strength:
            # Классифицируем по текущей цене
            if price < current_price:
                kind = LevelKind.SUPPORT
                origin = LevelOrigin.SWING_LOW
            else:
                kind = LevelKind.RESISTANCE
                origin = LevelOrigin.SWING_HIGH
            
            # Находим первое и последнее касание
            first_idx = min(cluster_indices)
            last_idx = max(cluster_indices)
            
            level = Level(
                price=price,
                kind=kind,
                strength=strength,
                touched_times=touched,
                time_first=df.index[first_idx] if hasattr(df.index[first_idx], '__class__') else pd.Timestamp.now(),
                time_last=df.index[last_idx] if hasattr(df.index[last_idx], '__class__') else pd.Timestamp.now(),
                origin=origin
            )
            levels.append(level)
    
    # Сортируем по силе (от большей к меньшей)
    levels.sort(key=lambda l: l.strength, reverse=True)
    
    return levels


