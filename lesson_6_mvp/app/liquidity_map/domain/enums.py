# app/liquidity_map/domain/enums.py
"""
Перечисления для модуля Liquidity Intelligence.
"""
from enum import Enum


class ZoneType(Enum):
    """Тип зоны ликвидности."""
    BUY = "BUY"
    SELL = "SELL"


class ZoneStrength(Enum):
    """Сила зоны ликвидности."""
    WEAK = "WEAK"
    STRONG = "STRONG"


class ZoneRole(Enum):
    """Роль зоны в принятии решений."""
    EXECUTION = "EXECUTION"  # Зона, где можно действовать
    CONTEXT = "CONTEXT"  # Контекстная зона (фон)
    INVALIDATION = "INVALIDATION"  # Зона, которая инвалидирует сделку


class MarketRegime(Enum):
    """Режим рынка."""
    PULLBACK_IN_UPTREND = "Pullback in Uptrend"
    COUNTER_TREND_BOUNCE = "Counter-trend Bounce"
    TREND_CONTINUATION = "Trend Continuation"
    RANGE_NO_EDGE = "Range / No Edge"


