# app/liquidity_map/services/zone_detector.py
"""
Детектор зон ликвидности на основе объемов и поведения цены.
"""
from typing import List
from datetime import datetime, timedelta
import pandas as pd
import numpy as np
from ..domain.models import Candle, HeatZone
from ..domain.enums import ZoneType, ZoneStrength


def detect_volume_zones(df: pd.DataFrame, min_volume_percentile: float = 0.7) -> List[HeatZone]:
    """
    Обнаружить зоны ликвидности на основе объемов.
    
    Args:
        df: DataFrame с колонками: timestamp, open, high, low, close, volume
        min_volume_percentile: Минимальный перцентиль объема для зоны
    
    Returns:
        Список зон ликвидности
    """
    if df.empty or len(df) < 10:
        return []
    
    zones = []
    
    # Вычисляем порог объема
    volume_threshold = df['volume'].quantile(min_volume_percentile)
    
    # Группируем по ценовым уровням
    price_range = df['high'].max() - df['low'].min()
    n_levels = 50
    price_levels = np.linspace(df['low'].min(), df['high'].max(), n_levels)
    
    # Создаем матрицу объемов по уровням
    volume_matrix = np.zeros(n_levels)
    
    for _, row in df.iterrows():
        low = row['low']
        high = row['high']
        volume = row['volume']
        
        # Распределяем объем по уровням
        for i, level in enumerate(price_levels):
            if low <= level <= high:
                # Чем ближе к центру тела, тем больше вес
                body_mid = (row['open'] + row['close']) / 2.0
                dist = abs(level - body_mid) / (high - low + 1e-8)
                weight = np.exp(-2 * dist)  # Гауссово затухание
                volume_matrix[i] += volume * weight
    
    # Находим кластеры (зоны с высокой концентрацией объема)
    threshold = np.percentile(volume_matrix[volume_matrix > 0], 70)
    
    # Группируем смежные уровни в зоны
    in_zone = volume_matrix >= threshold
    zone_start = None
    
    for i in range(len(in_zone)):
        if in_zone[i] and zone_start is None:
            zone_start = i
        elif not in_zone[i] and zone_start is not None:
            # Завершаем зону
            zone_low = price_levels[zone_start]
            zone_high = price_levels[i - 1]
            zone_volume = volume_matrix[zone_start:i].sum()
            
            # Определяем тип зоны на основе поведения цены
            zone_type = _classify_zone_type(df, zone_low, zone_high)
            strength = min(1.0, zone_volume / volume_threshold)
            
            # Создаем зону
            zone = HeatZone(
                tf=df.iloc[0].get('tf', '1h'),
                zone_type=zone_type,
                price_low=zone_low,
                price_high=zone_high,
                strength=strength,
                reactions=0,  # Будет обновлено в enrich_zones_with_reactions
                created_at=datetime.utcnow(),
                expires_at=datetime.utcnow() + timedelta(days=7)  # Зона живет 7 дней
            )
            zones.append(zone)
            zone_start = None
    
    # Обрабатываем зону, если она доходит до конца
    if zone_start is not None:
        zone_low = price_levels[zone_start]
        zone_high = price_levels[-1]
        zone_volume = volume_matrix[zone_start:].sum()
        zone_type = _classify_zone_type(df, zone_low, zone_high)
        strength = min(1.0, zone_volume / volume_threshold)
        
        zone = HeatZone(
            tf=df.iloc[0].get('tf', '1h'),
            zone_type=zone_type,
            price_low=zone_low,
            price_high=zone_high,
            strength=strength,
            reactions=0,
            created_at=datetime.utcnow(),
            expires_at=datetime.utcnow() + timedelta(days=7)
        )
        zones.append(zone)
    
    return zones


def _classify_zone_type(df: pd.DataFrame, zone_low: float, zone_high: float) -> ZoneType:
    """
    Классифицировать тип зоны (BUY/SELL) на основе поведения цены.
    """
    # Смотрим, что происходит после того, как цена покидает зону
    zone_center = (zone_low + zone_high) / 2.0
    
    # Находим моменты, когда цена входит/выходит из зоны
    touches = []
    for idx in range(len(df)):
        row = df.iloc[idx]
        if zone_low <= row['low'] <= zone_high or zone_low <= row['high'] <= zone_high:
            touches.append(idx)
    
    if len(touches) < 2:
        # По умолчанию - BUY зона
        return ZoneType.BUY
    
    # Анализируем движение после зоны
    buy_count = 0
    sell_count = 0
    
    for touch_idx in touches:
        if touch_idx < len(df) - 1:
            row = df.iloc[touch_idx]
            next_row = df.iloc[touch_idx + 1]
            
            if next_row['close'] > zone_center:
                buy_count += 1
            elif next_row['close'] < zone_center:
                sell_count += 1
    
    return ZoneType.BUY if buy_count >= sell_count else ZoneType.SELL


def enrich_zones_with_reactions(zones: List[HeatZone], df: pd.DataFrame) -> List[HeatZone]:
    """
    Обогатить зоны информацией о реакциях цены.
    
    Args:
        zones: Список зон
        df: DataFrame с данными
    
    Returns:
        Обновленный список зон с заполненным полем reactions
    """
    for zone in zones:
        reactions = 0
        
        for i in range(len(df) - 1):
            row = df.iloc[i]
            next_row = df.iloc[i + 1]
            
            # Проверяем, коснулась ли цена зоны
            touched = (zone.price_low <= row['low'] <= zone.price_high or
                      zone.price_low <= row['high'] <= zone.price_high or
                      zone.price_low <= row['close'] <= zone.price_high)
            
            if touched:
                # Проверяем реакцию (отскок или пробой)
                price_before = row['close']
                price_after = next_row['close']
                
                if zone.zone_type == ZoneType.BUY:
                    # Для BUY зоны реакция - отскок вверх
                    if price_after > price_before:
                        reactions += 1
                else:  # SELL зона
                    # Для SELL зоны реакция - отскок вниз
                    if price_after < price_before:
                        reactions += 1
        
        zone.reactions = reactions
    
    return zones


def classify_zones(zones: List[HeatZone]) -> List[HeatZone]:
    """
    Классифицировать зоны по силе (WEAK/STRONG).
    Обновляет strength на основе reactions и других факторов.
    """
    if not zones:
        return zones
    
    # Нормализуем strength на основе reactions
    max_reactions = max((z.reactions for z in zones), default=1)
    
    for zone in zones:
        # Комбинируем volume-based strength и reaction-based strength
        reaction_strength = min(1.0, zone.reactions / max(max_reactions, 1))
        zone.strength = (zone.strength * 0.6 + reaction_strength * 0.4)
    
    return zones

