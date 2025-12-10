# app/domain/market_diagnostics/smc.py
"""
Smart Money Concepts (SMC) анализ:
- BOS/CHOCH (Break of Structure / Change of Character)
- Liquidity pools (equal highs/lows)
- Order blocks (demand/supply zones)
- Fair Value Gaps (FVG)
- Premium/Discount zones
"""

from dataclasses import dataclass
from typing import List, Optional, Tuple
import pandas as pd
import numpy as np

from .structure_levels import Level, LevelKind, LevelOrigin, find_swings


@dataclass
class StructureEvent:
    """Событие изменения структуры."""
    kind: str   # "BOS" или "CHOCH"
    direction: str  # "up" / "down"
    price: float
    time: pd.Timestamp
    strength: float = 1.0  # Сила события (0-1)


@dataclass
class OrderBlock:
    """Order block (зона спроса/предложения)."""
    kind: LevelKind  # DEMAND / SUPPLY
    price_low: float
    price_high: float
    time: pd.Timestamp
    strength: float
    volume_ratio: float  # Отношение объёма к среднему


@dataclass
class FairValueGap:
    """Fair Value Gap (имбаланс)."""
    direction: str  # "bullish" / "bearish"
    price_low: float
    price_high: float
    time_start: pd.Timestamp
    time_end: pd.Timestamp
    filled: bool = False  # Заполнен ли FVG


@dataclass
class SMCContext:
    """Контекст Smart Money Concepts."""
    last_bos: Optional[StructureEvent] = None
    last_choch: Optional[StructureEvent] = None
    liquidity_above: List[float] = None  # Equal highs выше цены
    liquidity_below: List[float] = None  # Equal lows ниже цены
    main_liquidity_above: Optional[float] = None  # Главная ликвидность сверху
    main_liquidity_below: Optional[float] = None  # Главная ликвидность снизу
    order_blocks_demand: List[OrderBlock] = None  # Demand order blocks
    order_blocks_supply: List[OrderBlock] = None  # Supply order blocks
    fvgs: List[FairValueGap] = None  # Fair Value Gaps
    premium_zone_start: Optional[float] = None  # Начало premium зоны
    discount_zone_end: Optional[float] = None  # Конец discount зоны
    current_position: Optional[str] = None  # "premium" / "discount" / "neutral"
    
    def __post_init__(self):
        if self.liquidity_above is None:
            self.liquidity_above = []
        if self.liquidity_below is None:
            self.liquidity_below = []
        if self.order_blocks_demand is None:
            self.order_blocks_demand = []
        if self.order_blocks_supply is None:
            self.order_blocks_supply = []
        if self.fvgs is None:
            self.fvgs = []


def detect_bos_choch(
    df: pd.DataFrame,
    swing_highs: List[int],
    swing_lows: List[int],
    lookback: int = 20
) -> Tuple[Optional[StructureEvent], Optional[StructureEvent]]:
    """
    Обнаружить BOS (Break of Structure) и CHOCH (Change of Character).
    
    Args:
        df: DataFrame с OHLCV данными
        swing_highs: Индексы swing highs
        swing_lows: Индексы swing lows
        lookback: Количество баров для анализа
    
    Returns:
        (last_bos, last_choch) - последние события BOS и CHOCH
    """
    if len(df) < lookback or not swing_highs or not swing_lows:
        return None, None
    
    # Берем последние swing-и
    recent_highs = [i for i in swing_highs if i >= len(df) - lookback]
    recent_lows = [i for i in swing_lows if i >= len(df) - lookback]
    
    if len(recent_highs) < 2 or len(recent_lows) < 2:
        return None, None
    
    # Сортируем по индексу
    recent_highs.sort()
    recent_lows.sort()
    
    last_bos = None
    last_choch = None
    
    # BOS UP: новый swing high выше предыдущего значимого high
    if len(recent_highs) >= 2:
        current_high_idx = recent_highs[-1]
        prev_high_idx = recent_highs[-2]
        
        current_high = df['high'].iloc[current_high_idx]
        prev_high = df['high'].iloc[prev_high_idx]
        
        if current_high > prev_high * 1.01:  # Минимум 1% выше
            last_bos = StructureEvent(
                kind="BOS",
                direction="up",
                price=current_high,
                time=df.index[current_high_idx] if hasattr(df.index[current_high_idx], '__class__') else pd.Timestamp.now(),
                strength=min((current_high / prev_high - 1.0) * 10, 1.0)  # Нормализуем
            )
    
    # BOS DOWN: новый swing low ниже предыдущего значимого low
    if len(recent_lows) >= 2:
        current_low_idx = recent_lows[-1]
        prev_low_idx = recent_lows[-2]
        
        current_low = df['low'].iloc[current_low_idx]
        prev_low = df['low'].iloc[prev_low_idx]
        
        if current_low < prev_low * 0.99:  # Минимум 1% ниже
            if last_bos is None or last_bos.direction != "down":
                last_bos = StructureEvent(
                    kind="BOS",
                    direction="down",
                    price=current_low,
                    time=df.index[current_low_idx] if hasattr(df.index[current_low_idx], '__class__') else pd.Timestamp.now(),
                    strength=min((1.0 - current_low / prev_low) * 10, 1.0)
                )
    
    # CHOCH: изменение характера тренда
    # Если был BOS up, но появился lower low - это CHOCH down
    if last_bos and last_bos.direction == "up" and len(recent_lows) >= 2:
        current_low_idx = recent_lows[-1]
        prev_low_idx = recent_lows[-2]
        
        current_low = df['low'].iloc[current_low_idx]
        prev_low = df['low'].iloc[prev_low_idx]
        
        if current_low < prev_low:
            last_choch = StructureEvent(
                kind="CHOCH",
                direction="down",
                price=current_low,
                time=df.index[current_low_idx] if hasattr(df.index[current_low_idx], '__class__') else pd.Timestamp.now(),
                strength=0.7
            )
    
    # Если был BOS down, но появился higher high - это CHOCH up
    if last_bos and last_bos.direction == "down" and len(recent_highs) >= 2:
        current_high_idx = recent_highs[-1]
        prev_high_idx = recent_highs[-2]
        
        current_high = df['high'].iloc[current_high_idx]
        prev_high = df['high'].iloc[prev_high_idx]
        
        if current_high > prev_high:
            last_choch = StructureEvent(
                kind="CHOCH",
                direction="up",
                price=current_high,
                time=df.index[current_high_idx] if hasattr(df.index[current_high_idx], '__class__') else pd.Timestamp.now(),
                strength=0.7
            )
    
    return last_bos, last_choch


def detect_liquidity_pools(
    df: pd.DataFrame,
    swing_indexes: List[int],
    side: str,
    tolerance_bps: float = 0.05
) -> List[float]:
    """
    Обнаружить liquidity pools (equal highs/lows).
    
    Args:
        df: DataFrame с OHLCV данными
        swing_indexes: Индексы swing-ов (high или low)
        side: "high" или "low"
        tolerance_bps: Допуск для определения равенства (в процентах)
    
    Returns:
        Список цен liquidity pools
    """
    if len(swing_indexes) < 2:
        return []
    
    pools = []
    price_col = 'high' if side == 'high' else 'low'
    
    # Группируем близкие по цене swing-и
    swing_prices = [(i, df[price_col].iloc[i]) for i in swing_indexes]
    swing_prices.sort(key=lambda x: x[1])  # Сортируем по цене
    
    current_group = [swing_prices[0]]
    
    for idx, price in swing_prices[1:]:
        last_price = current_group[-1][1]
        
        # Проверяем, попадает ли в текущую группу
        if abs(price - last_price) / last_price * 100 <= tolerance_bps:
            current_group.append((idx, price))
        else:
            # Если группа содержит 2+ элемента - это liquidity pool
            if len(current_group) >= 2:
                avg_price = sum(p for _, p in current_group) / len(current_group)
                pools.append(avg_price)
            
            current_group = [(idx, price)]
    
    # Проверяем последнюю группу
    if len(current_group) >= 2:
        avg_price = sum(p for _, p in current_group) / len(current_group)
        pools.append(avg_price)
    
    return pools


def detect_order_blocks(
    df: pd.DataFrame,
    bos_event: Optional[StructureEvent],
    lookback_bars: int = 10
) -> Tuple[List[OrderBlock], List[OrderBlock]]:
    """
    Обнаружить order blocks (зоны спроса/предложения).
    
    Упрощенный алгоритм:
    - Находим BOS
    - Ищем перед BOS последнюю свечу с большим телом против направления движения
    - Это и есть order block
    
    Args:
        df: DataFrame с OHLCV данными
        bos_event: Событие BOS
        lookback_bars: Количество баров для поиска перед BOS
    
    Returns:
        (demand_blocks, supply_blocks) - списки order blocks
    """
    demand_blocks = []
    supply_blocks = []
    
    if bos_event is None or len(df) < lookback_bars + 1:
        return demand_blocks, supply_blocks
    
    # Находим индекс BOS события
    bos_time = bos_event.time
    try:
        if isinstance(df.index, pd.DatetimeIndex):
            bos_idx = df.index.get_loc(bos_time, method='nearest')
        else:
            # Если индекс не DatetimeIndex, ищем по времени
            bos_idx = len(df) - 1
            for i in range(len(df)):
                if hasattr(df.index[i], '__class__') and df.index[i] >= bos_time:
                    bos_idx = i
                    break
    except (KeyError, TypeError):
        bos_idx = len(df) - 1
    
    if bos_idx < lookback_bars:
        return demand_blocks, supply_blocks
    
    # Определяем направление BOS
    direction = bos_event.direction
    
    # Рассчитываем средний объём
    avg_volume = df['volume'].iloc[max(0, bos_idx - 50):bos_idx].mean()
    if avg_volume == 0:
        avg_volume = 1.0
    
    # Ищем order block перед BOS
    search_start = max(0, bos_idx - lookback_bars)
    
    if direction == "down":
        # BOS down -> ищем supply order block (последняя бычья свеча перед падением)
        for i in range(bos_idx - 1, search_start - 1, -1):
            if i < 0:
                break
            
            candle = df.iloc[i]
            body_size = abs(candle['close'] - candle['open'])
            candle_range = candle['high'] - candle['low']
            
            # Бычья свеча (close > open) с относительно большим телом
            if candle['close'] > candle['open'] and body_size > candle_range * 0.6:
                volume_ratio = candle['volume'] / avg_volume if avg_volume > 0 else 1.0
                
                # Если объём выше среднего - это хороший order block
                if volume_ratio > 1.2:
                    ob = OrderBlock(
                        kind=LevelKind.ORDERBLOCK_SUPPLY,
                        price_low=candle['low'],
                        price_high=candle['high'],
                        time=df.index[i] if hasattr(df.index[i], '__class__') else pd.Timestamp.now(),
                        strength=min(volume_ratio / 2.0, 1.0),
                        volume_ratio=volume_ratio
                    )
                    supply_blocks.append(ob)
                    break  # Берем только последний перед BOS
    
    elif direction == "up":
        # BOS up -> ищем demand order block (последняя медвежья свеча перед ростом)
        for i in range(bos_idx - 1, search_start - 1, -1):
            if i < 0:
                break
            
            candle = df.iloc[i]
            body_size = abs(candle['close'] - candle['open'])
            candle_range = candle['high'] - candle['low']
            
            # Медвежья свеча (close < open) с относительно большим телом
            if candle['close'] < candle['open'] and body_size > candle_range * 0.6:
                volume_ratio = candle['volume'] / avg_volume if avg_volume > 0 else 1.0
                
                if volume_ratio > 1.2:
                    ob = OrderBlock(
                        kind=LevelKind.ORDERBLOCK_DEMAND,
                        price_low=candle['low'],
                        price_high=candle['high'],
                        time=df.index[i] if hasattr(df.index[i], '__class__') else pd.Timestamp.now(),
                        strength=min(volume_ratio / 2.0, 1.0),
                        volume_ratio=volume_ratio
                    )
                    demand_blocks.append(ob)
                    break
    
    return demand_blocks, supply_blocks


def detect_fair_value_gaps(df: pd.DataFrame, lookback: int = 50) -> List[FairValueGap]:
    """
    Обнаружить Fair Value Gaps (имбалансы).
    
    FVG возникает когда:
    - Бычий FVG: low[i+1] > high[i-1]
    - Медвежий FVG: high[i+1] < low[i-1]
    
    Args:
        df: DataFrame с OHLCV данными
        lookback: Количество баров для анализа
    
    Returns:
        Список FairValueGap объектов
    """
    if len(df) < 3:
        return []
    
    fvgs = []
    start_idx = max(0, len(df) - lookback)
    
    for i in range(start_idx + 1, len(df) - 1):
        prev_candle = df.iloc[i - 1]
        current_candle = df.iloc[i]
        next_candle = df.iloc[i + 1]
        
        # Бычий FVG: low следующей свечи выше high предыдущей
        if next_candle['low'] > prev_candle['high']:
            fvg = FairValueGap(
                direction="bullish",
                price_low=prev_candle['high'],
                price_high=next_candle['low'],
                time_start=df.index[i - 1] if hasattr(df.index[i - 1], '__class__') else pd.Timestamp.now(),
                time_end=df.index[i + 1] if hasattr(df.index[i + 1], '__class__') else pd.Timestamp.now(),
                filled=False
            )
            fvgs.append(fvg)
        
        # Медвежий FVG: high следующей свечи ниже low предыдущей
        elif next_candle['high'] < prev_candle['low']:
            fvg = FairValueGap(
                direction="bearish",
                price_low=next_candle['high'],
                price_high=prev_candle['low'],
                time_start=df.index[i - 1] if hasattr(df.index[i - 1], '__class__') else pd.Timestamp.now(),
                time_end=df.index[i + 1] if hasattr(df.index[i + 1], '__class__') else pd.Timestamp.now(),
                filled=False
            )
            fvgs.append(fvg)
    
    return fvgs


def calculate_premium_discount(
    df: pd.DataFrame,
    swing_highs: List[int],
    swing_lows: List[int]
) -> Tuple[Optional[float], Optional[float], Optional[str]]:
    """
    Рассчитать premium/discount зоны на основе swing-ов.
    
    Args:
        df: DataFrame с OHLCV данными
        swing_highs: Индексы swing highs
        swing_lows: Индексы swing lows
    
    Returns:
        (premium_start, discount_end, current_position)
        - premium_start: Начало premium зоны (верхняя половина диапазона)
        - discount_end: Конец discount зоны (нижняя половина диапазона)
        - current_position: "premium" / "discount" / "neutral"
    """
    if not swing_highs or not swing_lows:
        return None, None, None
    
    # Берем последние значимые swing-и
    recent_highs = [df['high'].iloc[i] for i in swing_highs[-5:]]
    recent_lows = [df['low'].iloc[i] for i in swing_lows[-5:]]
    
    if not recent_highs or not recent_lows:
        return None, None, None
    
    range_high = max(recent_highs)
    range_low = min(recent_lows)
    range_mid = (range_high + range_low) / 2.0
    
    # Premium зона: верхняя половина (от mid до high)
    premium_start = range_mid
    
    # Discount зона: нижняя половина (от low до mid)
    discount_end = range_mid
    
    # Определяем текущую позицию
    current_price = df['close'].iloc[-1]
    
    if current_price >= premium_start:
        current_position = "premium"
    elif current_price <= discount_end:
        current_position = "discount"
    else:
        current_position = "neutral"
    
    return premium_start, discount_end, current_position


def analyze_smc_context(
    df: pd.DataFrame,
    left: int = 2,
    right: int = 2,
    lookback: int = 50
) -> SMCContext:
    """
    Полный анализ SMC контекста.
    
    Args:
        df: DataFrame с OHLCV данными
        left: Количество баров слева для swing detection
        right: Количество баров справа для swing detection
        lookback: Количество баров для анализа
    
    Returns:
        SMCContext с полным контекстом
    """
    context = SMCContext()
    
    if len(df) < left + right + 1:
        return context
    
    # Находим swing-и
    swing_highs, swing_lows = find_swings(df, left, right)
    
    if not swing_highs or not swing_lows:
        return context
    
    # BOS/CHOCH
    last_bos, last_choch = detect_bos_choch(df, swing_highs, swing_lows, lookback)
    context.last_bos = last_bos
    context.last_choch = last_choch
    
    # Liquidity pools
    current_price = df['close'].iloc[-1]
    
    # Equal highs выше цены
    liquidity_highs = detect_liquidity_pools(df, swing_highs, "high", tolerance_bps=0.05)
    context.liquidity_above = [p for p in liquidity_highs if p > current_price]
    if context.liquidity_above:
        context.main_liquidity_above = min(context.liquidity_above)  # Ближайшая сверху
    
    # Equal lows ниже цены
    liquidity_lows = detect_liquidity_pools(df, swing_lows, "low", tolerance_bps=0.05)
    context.liquidity_below = [p for p in liquidity_lows if p < current_price]
    if context.liquidity_below:
        context.main_liquidity_below = max(context.liquidity_below)  # Ближайшая снизу
    
    # Order blocks
    demand_blocks, supply_blocks = detect_order_blocks(df, last_bos, lookback_bars=10)
    context.order_blocks_demand = demand_blocks
    context.order_blocks_supply = supply_blocks
    
    # Fair Value Gaps
    context.fvgs = detect_fair_value_gaps(df, lookback)
    
    # Premium/Discount
    premium_start, discount_end, current_position = calculate_premium_discount(
        df, swing_highs, swing_lows
    )
    context.premium_zone_start = premium_start
    context.discount_zone_end = discount_end
    context.current_position = current_position
    
    return context







