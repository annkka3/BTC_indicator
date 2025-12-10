# app/domain/market_diagnostics/tradability.py
"""
Анализ ликвидности и торговых характеристик инструмента.
"""

from enum import Enum
from dataclasses import dataclass
from typing import Optional, Dict
import logging

logger = logging.getLogger("alt_forecast.tradability")


class TradabilityState(str, Enum):
    """Состояние ликвидности инструмента."""
    ILLIQUID = "illiquid"           # Низкая ликвидность, высокий спред
    NORMAL = "normal"               # Нормальная ликвидность
    HIGH_LIQUIDITY = "high_liquidity"  # Высокая ликвидность, низкий спред


@dataclass
class TradabilitySnapshot:
    """Снимок торговых характеристик инструмента."""
    spread_bps: float  # Спред в базисных пунктах (basis points)
    size_at_10bps: float  # Объем, который можно влить с проскальзыванием ≤10 bps (в USDT)
    state: TradabilityState
    avg_volume_1m: Optional[float] = None  # Средний объем за последние минуты
    depth_bid: Optional[float] = None  # Глубина стакана на биде (в USDT)
    depth_ask: Optional[float] = None  # Глубина стакана на аске (в USDT)
    
    def get_description(self) -> str:
        """Получить текстовое описание ликвидности."""
        if self.state == TradabilityState.ILLIQUID:
            return (
                f"💧 Спред ~{self.spread_bps:.1f} bps, объем тонкий — инструмент подходит только для малых позиций."
            )
        elif self.state == TradabilityState.HIGH_LIQUIDITY:
            return (
                f"💧 Спред ~{self.spread_bps:.1f} bps, доступный объем ~{self.size_at_10bps:.0f} USDT при 10 bps проскальзывании."
            )
        else:
            return (
                f"💧 Спред ~{self.spread_bps:.1f} bps, доступный объем ~{self.size_at_10bps:.0f} USDT при 10 bps проскальзывании."
            )


class TradabilityAnalyzer:
    """Анализатор ликвидности и торговых характеристик."""
    
    def __init__(self, db=None):
        """
        Args:
            db: Database instance (опционально, для получения данных из БД)
        """
        self.db = db
    
    def analyze_tradability(
        self,
        symbol: str,
        current_price: float,
        volume_24h: Optional[float] = None
    ) -> TradabilitySnapshot:
        """
        Проанализировать торговые характеристики инструмента.
        
        Args:
            symbol: Символ монеты
            current_price: Текущая цена
            volume_24h: Объем за 24 часа (опционально)
        
        Returns:
            TradabilitySnapshot с характеристиками ликвидности
        """
        # TODO: Интегрировать с реальными данными orderbook и trades
        # Пока используем упрощенную модель на основе объема
        
        # Оценка спреда на основе объема
        if volume_24h is None:
            # Пробуем получить из БД
            volume_24h = self._get_volume_from_db(symbol)
        
        spread_bps = self._estimate_spread(volume_24h, current_price)
        size_at_10bps = self._estimate_size_at_slippage(volume_24h, current_price, slippage_bps=10)
        state = self._determine_state(spread_bps, size_at_10bps)
        
        return TradabilitySnapshot(
            spread_bps=spread_bps,
            size_at_10bps=size_at_10bps,
            state=state,
            avg_volume_1m=volume_24h / (24 * 60) if volume_24h else None
        )
    
    def _get_volume_from_db(self, symbol: str) -> Optional[float]:
        """Получить объем из БД."""
        if not self.db:
            return None
        
        try:
            # Получаем последние бары для оценки объема
            bars = self.db.last_n(symbol, "1h", 24)
            if bars:
                # Суммируем объем за последние 24 часа
                total_volume = sum(bar[5] for bar in bars)  # volume
                return total_volume
        except Exception as e:
            logger.debug(f"Error getting volume from DB: {e}")
        
        return None
    
    def _estimate_spread(self, volume_24h: Optional[float], price: float) -> float:
        """
        Оценить спред на основе объема.
        
        Чем больше объем, тем меньше спред.
        """
        if volume_24h is None or volume_24h == 0:
            return 50.0  # Высокий спред для неизвестного объема
        
        # Нормализуем объем (предполагаем, что 1M USDT = хороший объем)
        normalized_volume = volume_24h / 1_000_000
        
        # Спред обратно пропорционален объему
        # Для объема 1M спред ~5 bps, для 100k ~20 bps, для 10k ~50 bps
        if normalized_volume > 10:
            spread = 2.0  # Очень высокая ликвидность
        elif normalized_volume > 1:
            spread = 5.0  # Хорошая ликвидность
        elif normalized_volume > 0.1:
            spread = 15.0  # Средняя ликвидность
        elif normalized_volume > 0.01:
            spread = 30.0  # Низкая ликвидность
        else:
            spread = 50.0  # Очень низкая ликвидность
        
        return spread
    
    def _estimate_size_at_slippage(
        self,
        volume_24h: Optional[float],
        price: float,
        slippage_bps: float = 10
    ) -> float:
        """
        Оценить размер позиции при заданном проскальзывании.
        
        Args:
            volume_24h: Объем за 24 часа
            price: Текущая цена
            slippage_bps: Проскальзывание в базисных пунктах
        
        Returns:
            Размер позиции в USDT
        """
        if volume_24h is None or volume_24h == 0:
            return 1000.0  # Консервативная оценка
        
        # Предполагаем, что можно торговать ~1% от дневного объема без значительного проскальзывания
        # Для проскальзывания 10 bps можно взять больше
        available_size = volume_24h * 0.01 * (slippage_bps / 10.0)
        
        # Ограничиваем разумными значениями
        return min(max(available_size, 1000.0), 1_000_000.0)
    
    def _determine_state(self, spread_bps: float, size_at_10bps: float) -> TradabilityState:
        """Определить состояние ликвидности."""
        if spread_bps > 30 or size_at_10bps < 5000:
            return TradabilityState.ILLIQUID
        elif spread_bps < 5 and size_at_10bps > 50000:
            return TradabilityState.HIGH_LIQUIDITY
        else:
            return TradabilityState.NORMAL


