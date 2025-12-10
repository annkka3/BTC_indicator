# app/liquidity_map/services/pressure_analyzer.py
"""
Анализатор давления покупок/продаж на основе зон ликвидности.
"""
from typing import List
import numpy as np
from ..domain.models import HeatZone, PressureStat
from ..domain.enums import ZoneType


def compute_pressure(zones: List[HeatZone], price_series: List[float]) -> PressureStat:
    """
    Вычислить давление покупок/продаж на основе зон.
    
    Новая формула: weight = width_price * strength_factor * reactions_factor
    где:
    - width_price = размер зоны по цене
    - strength_factor = zone.strength (0-1)
    - reactions_factor = 1 + 0.1 * zone.reactions
    
    Args:
        zones: Список зон ликвидности
        price_series: Серия цен (не используется в новой формуле, но оставлен для совместимости)
    
    Returns:
        Статистика давления
    """
    if not zones:
        return PressureStat(buy_pressure=50.0, sell_pressure=50.0)
    
    total_weight = 0.0
    buy_weight = 0.0
    
    for zone in zones:
        if not zone.is_active:
            continue
        
        # Ширина зоны по цене
        width_price = zone.price_high - zone.price_low
        if width_price <= 0:
            continue
        
        # Фактор силы зоны
        strength_factor = zone.strength  # 0-1
        
        # Фактор реакций (логарифмический рост)
        reactions_factor = 1.0 + 0.1 * zone.reactions
        
        # Общий вес зоны
        weight = width_price * strength_factor * reactions_factor
        
        total_weight += weight
        
        if zone.zone_type == ZoneType.BUY:
            buy_weight += weight
    
    # Нормализуем до процентов
    if total_weight > 0:
        buy_pressure = (buy_weight / total_weight) * 100.0
        sell_pressure = 100.0 - buy_pressure
    else:
        # Если нет активных зон, возвращаем нейтральное значение
        buy_pressure = 50.0
        sell_pressure = 50.0
    
    return PressureStat(
        buy_pressure=round(buy_pressure, 1),
        sell_pressure=round(sell_pressure, 1)
    )

