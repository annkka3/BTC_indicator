# app/liquidity_map/domain/models.py
"""
Доменные модели для Liquidity Intelligence.
"""
from dataclasses import dataclass
from datetime import datetime
from typing import Optional
from .enums import ZoneType, ZoneStrength, ZoneRole, MarketRegime


@dataclass
class Candle:
    """OHLCV свеча."""
    timestamp: int
    open: float
    high: float
    low: float
    close: float
    volume: float
    
    @property
    def body_mid(self) -> float:
        """Середина тела свечи."""
        return (self.open + self.close) / 2.0
    
    @property
    def range_size(self) -> float:
        """Размер диапазона свечи."""
        return self.high - self.low


@dataclass
class HeatZone:
    """Зона ликвидности (heat zone)."""
    tf: str
    zone_type: ZoneType
    price_low: float
    price_high: float
    strength: float  # 0-1
    reactions: int  # количество реакций цены на зону
    created_at: datetime
    expires_at: datetime
    role: ZoneRole = ZoneRole.CONTEXT  # Роль зоны (по умолчанию контекст)
    
    @property
    def is_active(self) -> bool:
        """Проверка, активна ли зона."""
        return datetime.utcnow() < self.expires_at
    
    @property
    def center_price(self) -> float:
        """Центральная цена зоны."""
        return (self.price_low + self.price_high) / 2.0


@dataclass
class PressureStat:
    """Статистика давления (buy/sell)."""
    buy_pressure: float  # процент
    sell_pressure: float  # процент
    
    @property
    def bias(self) -> str:
        """Определение смещения (LONG/SHORT/NEUTRAL)."""
        diff = self.buy_pressure - self.sell_pressure
        if diff > 10:
            return "LONG"
        elif diff < -10:
            return "SHORT"
        else:
            return "NEUTRAL"
    
    @property
    def state(self) -> str:
        """Вербальное состояние давления."""
        diff = abs(self.buy_pressure - self.sell_pressure)
        dominant = "Buy" if self.buy_pressure > self.sell_pressure else "Sell"
        
        if diff < 10:
            return "Balanced"
        elif diff < 30:
            return f"{dominant} Skew"
        else:
            return f"Dominant {dominant}"


@dataclass
class TimeframeSnapshot:
    """Снимок состояния таймфрейма."""
    tf: str
    zones: list[HeatZone]
    buy_pressure: float  # процент
    sell_pressure: float  # процент
    bias: str  # LONG / SHORT / NEUTRAL
    current_price: float
    timestamp: datetime
    
    @property
    def pressure_stat(self) -> PressureStat:
        """Получить статистику давления."""
        return PressureStat(
            buy_pressure=self.buy_pressure,
            sell_pressure=self.sell_pressure
        )
    
    @property
    def active_zones(self) -> list[HeatZone]:
        """Получить только активные зоны."""
        return [z for z in self.zones if z.is_active]


