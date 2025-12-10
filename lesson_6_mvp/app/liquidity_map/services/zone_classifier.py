# app/liquidity_map/services/zone_classifier.py
"""
Классификатор ролей зон (EXECUTION/CONTEXT/INVALIDATION).
"""
from typing import List
from ..domain.models import HeatZone, TimeframeSnapshot
from ..domain.enums import ZoneRole, ZoneType


def classify_zone_roles(snapshots: List[TimeframeSnapshot], current_price: float) -> None:
    """
    Классифицировать роли зон для всех таймфреймов.
    
    Правила:
    - EXECUTION: зона, где можно действовать (цена внутри или близко, сильная, много реакций)
    - INVALIDATION: зона, которая инвалидирует сделку (противоположная bias, близко)
    - CONTEXT: всё остальное (фон)
    
    Args:
        snapshots: Список снимков
        current_price: Текущая цена
    """
    # Находим якорный snapshot (1h)
    anchor_snapshot = next((s for s in snapshots if s.tf == "1h"), None)
    if not anchor_snapshot:
        return
    
    anchor_bias = anchor_snapshot.bias
    
    # Классифицируем зоны для каждого snapshot
    for snapshot in snapshots:
        for zone in snapshot.zones:
            # Проверяем, находится ли цена в зоне
            price_in_zone = zone.price_low <= current_price <= zone.price_high
            
            # Расстояние до зоны (в процентах от цены)
            zone_mid = zone.center_price
            distance_pct = abs(current_price - zone_mid) / current_price * 100 if current_price > 0 else 100
            
            # EXECUTION зона: цена внутри или близко, сильная, имеет реакции
            # Важно: для BUY-зон - только если цена внутри или ниже зоны (зона поддержки)
            # Для SELL-зон - только если цена внутри или выше зоны (зона сопротивления)
            
            # Проверяем позицию зоны относительно цены
            zone_is_below_price = zone.price_high < current_price  # Зона ниже цены
            zone_is_above_price = zone.price_low > current_price     # Зона выше цены
            
            # Для BUY-зон: EXECUTION только если цена внутри или ниже зоны
            # Для SELL-зон: EXECUTION только если цена внутри или выше зоны
            can_be_execution = False
            if zone.zone_type == ZoneType.BUY:
                can_be_execution = price_in_zone or zone_is_below_price
            else:  # SELL
                can_be_execution = price_in_zone or zone_is_above_price
            
            if can_be_execution:
                # Цена внутри зоны - более мягкие критерии
                if price_in_zone:
                    if zone.strength >= 0.5 and zone.reactions >= 2:
                        zone.role = ZoneRole.EXECUTION
                    # Если зона очень сильная, даже без реакций может быть EXECUTION
                    elif zone.strength >= 0.8:
                        zone.role = ZoneRole.EXECUTION
                # Цена близко к зоне - более строгие критерии
                elif distance_pct < 1.0:
                    if zone.strength >= 0.6 and zone.reactions >= 3:
                        # Предпочитаем зоны, совпадающие с bias, но не обязательно
                        if ((zone.zone_type == ZoneType.BUY and anchor_bias == "LONG") or
                            (zone.zone_type == ZoneType.SELL and anchor_bias == "SHORT")):
                            zone.role = ZoneRole.EXECUTION
                        # Если зона очень сильная, тоже может быть EXECUTION
                        elif zone.strength >= 0.8 and zone.reactions >= 5:
                            zone.role = ZoneRole.EXECUTION
            
            # Зоны выше цены (для BUY) или ниже цены (для SELL) - CONTEXT
            if zone.role != ZoneRole.EXECUTION and zone.role != ZoneRole.INVALIDATION:
                if (zone.zone_type == ZoneType.BUY and zone_is_above_price) or \
                   (zone.zone_type == ZoneType.SELL and zone_is_below_price):
                    zone.role = ZoneRole.CONTEXT
            
            # INVALIDATION зона: противоположная bias, близко к цене
            elif distance_pct < 2.0 and \
                 ((zone.zone_type == ZoneType.SELL and anchor_bias == "LONG") or
                  (zone.zone_type == ZoneType.BUY and anchor_bias == "SHORT")):
                zone.role = ZoneRole.INVALIDATION
            
            # CONTEXT: всё остальное
            else:
                zone.role = ZoneRole.CONTEXT


def get_execution_zones(snapshots: List[TimeframeSnapshot]) -> List[HeatZone]:
    """
    Получить только EXECUTION зоны (не более 2).
    
    Args:
        snapshots: Список снимков
    
    Returns:
        Список EXECUTION зон (отсортированные по приоритету)
    """
    execution_zones = []
    for snapshot in snapshots:
        for zone in snapshot.zones:
            if zone.role == ZoneRole.EXECUTION:
                execution_zones.append(zone)
    
    # Сортируем по приоритету: сначала по strength, потом по reactions
    execution_zones.sort(key=lambda z: (z.strength, z.reactions), reverse=True)
    
    # Возвращаем максимум 2 зоны
    return execution_zones[:2]


def get_invalidation_zones(snapshots: List[TimeframeSnapshot], current_price: float = 0.0) -> List[HeatZone]:
    """
    Получить INVALIDATION зоны (не более 1).
    
    Args:
        snapshots: Список снимков
        current_price: Текущая цена (для сортировки по близости)
    
    Returns:
        Список INVALIDATION зон
    """
    invalidation_zones = []
    for snapshot in snapshots:
        for zone in snapshot.zones:
            if zone.role == ZoneRole.INVALIDATION:
                invalidation_zones.append(zone)
    
    # Сортируем по близости к цене
    if current_price > 0:
        invalidation_zones.sort(key=lambda z: abs(z.center_price - current_price))
    
    # Возвращаем максимум 1 зону
    return invalidation_zones[:1]

