# app/domain/market_diagnostics/micro_patterns.py
"""
Micro-Pattern Engine - авто-распознавание разворотных паттернов.
"""

from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from enum import Enum


class MicroPattern(Enum):
    """Микро-паттерны."""
    THREE_BAR_REVERSAL = "3_bar_reversal"
    STOP_RUN_RECOIL = "stop_run_recoil"
    DELTA_ABSORPTION = "delta_absorption"
    IMBALANCE_REFILL_IMPULSE = "imbalance_refill_impulse"
    VOLUME_CLIMAX_COMPRESSION = "volume_climax_compression"
    NONE = "none"


@dataclass
class PatternDetection:
    """Обнаруженный паттерн."""
    pattern: MicroPattern
    confidence: float  # 0-1
    description: str
    timeframe_hours: int  # Временной горизонт (4-8 баров обычно)
    direction: str  # "bullish", "bearish", "neutral"


class MicroPatternEngine:
    """Движок распознавания микро-паттернов."""
    
    def __init__(self):
        """Инициализация."""
        pass
    
    def detect_3_bar_reversal(
        self,
        candles: List[Dict]  # [{open, high, low, close, volume}]
    ) -> Optional[PatternDetection]:
        """Обнаружить 3-bar reversal паттерн."""
        if len(candles) < 3:
            return None
        
        c1, c2, c3 = candles[-3:]
        
        # Бычий разворот: два падающих бара, затем растущий
        if (c1['close'] < c1['open'] and 
            c2['close'] < c2['open'] and 
            c3['close'] > c3['open'] and
            c3['close'] > c2['high']):
            return PatternDetection(
                pattern=MicroPattern.THREE_BAR_REVERSAL,
                confidence=0.7,
                description="Формируется 3-bar reversal паттерн: вероятен откат в ближайшие 4–8 баров",
                timeframe_hours=4,
                direction="bullish"
            )
        
        # Медвежий разворот: два растущих бара, затем падающий
        if (c1['close'] > c1['open'] and 
            c2['close'] > c2['open'] and 
            c3['close'] < c3['open'] and
            c3['close'] < c2['low']):
            return PatternDetection(
                pattern=MicroPattern.THREE_BAR_REVERSAL,
                confidence=0.7,
                description="Формируется 3-bar reversal паттерн: вероятен откат в ближайшие 4–8 баров",
                timeframe_hours=4,
                direction="bearish"
            )
        
        return None
    
    def detect_stop_run_recoil(
        self,
        candles: List[Dict],
        key_levels: List[float],
        current_price: float
    ) -> Optional[PatternDetection]:
        """Обнаружить stop-run + recoil паттерн."""
        if len(candles) < 2 or not key_levels:
            return None
        
        last_candle = candles[-1]
        prev_candle = candles[-2]
        
        # Ищем пробой уровня с последующим отскоком
        for level in key_levels:
            # Пробой вниз с отскоком
            if (prev_candle['low'] > level and 
                last_candle['low'] < level and 
                last_candle['close'] > level):
                return PatternDetection(
                    pattern=MicroPattern.STOP_RUN_RECOIL,
                    confidence=0.75,
                    description="Stop-run + recoil: вынос стопов ниже уровня с последующим отскоком",
                    timeframe_hours=4,
                    direction="bullish"
                )
            
            # Пробой вверх с отскоком
            if (prev_candle['high'] < level and 
                last_candle['high'] > level and 
                last_candle['close'] < level):
                return PatternDetection(
                    pattern=MicroPattern.STOP_RUN_RECOIL,
                    confidence=0.75,
                    description="Stop-run + recoil: вынос стопов выше уровня с последующим отскоком",
                    timeframe_hours=4,
                    direction="bearish"
                )
        
        return None
    
    def detect_delta_absorption(
        self,
        buy_volume: List[float],
        sell_volume: List[float],
        price_changes: List[float],
        lookback: int = 10
    ) -> Optional[PatternDetection]:
        """Обнаружить delta absorption паттерн."""
        if len(buy_volume) < lookback or len(sell_volume) < lookback:
            return None
        
        recent_buys = sum(buy_volume[-lookback:])
        recent_sells = sum(sell_volume[-lookback:])
        
        # Поглощение: большой объём, но цена не двигается
        if recent_buys > recent_sells * 1.5:
            avg_price_change = sum(price_changes[-lookback:]) / lookback if price_changes else 0
            if abs(avg_price_change) < 0.001:  # Цена почти не двигается
                return PatternDetection(
                    pattern=MicroPattern.DELTA_ABSORPTION,
                    confidence=0.65,
                    description="Delta absorption: большой объём покупок, но цена стоит — накопление",
                    timeframe_hours=8,
                    direction="bullish"
                )
        
        if recent_sells > recent_buys * 1.5:
            avg_price_change = sum(price_changes[-lookback:]) / lookback if price_changes else 0
            if abs(avg_price_change) < 0.001:
                return PatternDetection(
                    pattern=MicroPattern.DELTA_ABSORPTION,
                    confidence=0.65,
                    description="Delta absorption: большой объём продаж, но цена стоит — распределение",
                    timeframe_hours=8,
                    direction="bearish"
                )
        
        return None
    
    def detect_imbalance_refill_impulse(
        self,
        candles: List[Dict],
        imbalances: List[Dict],  # [{price_low, price_high, filled}]
        current_price: float
    ) -> Optional[PatternDetection]:
        """Обнаружить imbalance refill + impulse continuation."""
        if not imbalances:
            return None
        
        # Ищем незаполненный имбаланс
        for imb in imbalances:
            if imb.get('filled', False):
                continue
            
            imb_low = imb.get('price_low', 0)
            imb_high = imb.get('price_high', 0)
            
            # Цена приближается к имбалансу
            if imb_low <= current_price <= imb_high:
                # Проверяем импульс после заполнения
                if len(candles) >= 2:
                    last_candle = candles[-1]
                    if last_candle['close'] > last_candle['open']:
                        return PatternDetection(
                            pattern=MicroPattern.IMBALANCE_REFILL_IMPULSE,
                            confidence=0.7,
                            description="Imbalance refill + impulse: заполнение имбаланса с продолжением импульса",
                            timeframe_hours=6,
                            direction="bullish"
                        )
        
        return None
    
    def detect_volume_climax_compression(
        self,
        candles: List[Dict],
        volumes: List[float],
        lookback: int = 20
    ) -> Optional[PatternDetection]:
        """Обнаружить volume climax → compression → expansion."""
        if len(candles) < lookback or len(volumes) < lookback:
            return None
        
        recent_volumes = volumes[-lookback:]
        recent_candles = candles[-lookback:]
        
        # Ищем climax (пик объёма)
        max_vol_idx = recent_volumes.index(max(recent_volumes))
        
        if max_vol_idx < len(recent_volumes) - 5:
            # После climax идёт compression (сжатие)
            post_climax_volumes = recent_volumes[max_vol_idx + 1:]
            if len(post_climax_volumes) >= 3:
                avg_post_vol = sum(post_climax_volumes[:3]) / 3
                climax_vol = recent_volumes[max_vol_idx]
                
                if avg_post_vol < climax_vol * 0.5:  # Compression
                    # Проверяем expansion (расширение)
                    if len(post_climax_volumes) >= 5:
                        latest_vol = post_climax_volumes[-1]
                        if latest_vol > avg_post_vol * 1.5:
                            return PatternDetection(
                                pattern=MicroPattern.VOLUME_CLIMAX_COMPRESSION,
                                confidence=0.8,
                                description="Volume climax → compression → expansion: вероятен сильный импульс",
                                timeframe_hours=8,
                                direction="bullish" if recent_candles[-1]['close'] > recent_candles[-1]['open'] else "bearish"
                            )
        
        return None
    
    def detect_all_patterns(
        self,
        candles: List[Dict],
        volumes: List[float],
        buy_volume: Optional[List[float]] = None,
        sell_volume: Optional[List[float]] = None,
        price_changes: Optional[List[float]] = None,
        key_levels: Optional[List[float]] = None,
        imbalances: Optional[List[Dict]] = None,
        current_price: Optional[float] = None
    ) -> List[PatternDetection]:
        """
        Обнаружить все возможные паттерны.
        
        Returns:
            Список обнаруженных паттернов
        """
        patterns = []
        
        # 3-bar reversal
        pattern = self.detect_3_bar_reversal(candles)
        if pattern:
            patterns.append(pattern)
        
        # Stop-run + recoil
        if key_levels and current_price:
            pattern = self.detect_stop_run_recoil(candles, key_levels, current_price)
            if pattern:
                patterns.append(pattern)
        
        # Delta absorption
        if buy_volume and sell_volume and price_changes:
            pattern = self.detect_delta_absorption(buy_volume, sell_volume, price_changes)
            if pattern:
                patterns.append(pattern)
        
        # Imbalance refill + impulse
        if imbalances and current_price:
            pattern = self.detect_imbalance_refill_impulse(candles, imbalances, current_price)
            if pattern:
                patterns.append(pattern)
        
        # Volume climax → compression → expansion
        if volumes:
            pattern = self.detect_volume_climax_compression(candles, volumes)
            if pattern:
                patterns.append(pattern)
        
        return patterns












