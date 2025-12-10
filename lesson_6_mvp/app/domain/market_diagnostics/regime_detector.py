# app/domain/market_diagnostics/regime_detector.py
"""
Regime Detector - определение мета-режимов рынка.
"""

from typing import Dict, List, Optional
from dataclasses import dataclass
from enum import Enum


class MarketRegime(Enum):
    """Мета-режимы рынка."""
    TREND = "trend"
    EXHAUSTION = "exhaustion"
    LIQUIDITY_HUNT = "liquidity_hunt"
    CHOP = "chop"


@dataclass
class RegimeAnalysis:
    """Анализ режима рынка."""
    primary_regime: MarketRegime
    secondary_regime: Optional[MarketRegime] = None
    confidence: float = 0.5
    description: str = ""


class RegimeDetector:
    """Детектор мета-режимов рынка."""
    
    def __init__(self):
        """Инициализация."""
        pass
    
    def detect_regime(
        self,
        price_changes: List[float],  # Последние изменения цены
        volumes: List[float],
        volatility: float,
        momentum_score: float,
        liquidity_above: List[float],
        liquidity_below: List[float],
        recent_wicks: List[float],  # Размеры фитилей
        lookback: int = 20
    ) -> RegimeAnalysis:
        """
        Определить мета-режим рынка.
        
        Returns:
            RegimeAnalysis
        """
        if len(price_changes) < lookback:
            lookback = len(price_changes)
        
        recent_changes = price_changes[-lookback:]
        recent_volumes = volumes[-lookback:] if len(volumes) >= lookback else volumes
        
        # 1. Trend regime
        # Последовательные движения в одном направлении
        up_moves = sum(1 for chg in recent_changes if chg > 0)
        down_moves = sum(1 for chg in recent_changes if chg < 0)
        trend_strength = abs(up_moves - down_moves) / len(recent_changes) if recent_changes else 0
        
        if trend_strength > 0.4 and abs(momentum_score) > 0.3:
            return RegimeAnalysis(
                primary_regime=MarketRegime.TREND,
                confidence=min(trend_strength, 0.9),
                description="Рынок в трендовом режиме"
            )
        
        # 2. Exhaustion regime
        # Снижение импульса, уменьшение объёмов
        if len(recent_volumes) >= 5:
            recent_vol_avg = sum(recent_volumes[-5:]) / 5
            earlier_vol_avg = sum(recent_volumes[-10:-5]) / 5 if len(recent_volumes) >= 10 else recent_vol_avg
            
            if recent_vol_avg < earlier_vol_avg * 0.7 and abs(momentum_score) < 0.2:
                return RegimeAnalysis(
                    primary_regime=MarketRegime.EXHAUSTION,
                    confidence=0.7,
                    description="Рынок в режиме истощения — импульс ослабевает"
                )
        
        # 3. Liquidity hunt regime
        # Большие фитили, движение к ликвидности
        if recent_wicks:
            avg_wick = sum(recent_wicks) / len(recent_wicks)
            large_wicks = sum(1 for w in recent_wicks if w > avg_wick * 1.5)
            
            liq_above_sum = sum(liquidity_above) if liquidity_above else 0
            liq_below_sum = sum(liquidity_below) if liquidity_below else 0
            
            if large_wicks > len(recent_wicks) * 0.3 and (liq_above_sum > 0 or liq_below_sum > 0):
                direction = "вверх" if liq_above_sum > liq_below_sum else "вниз"
                return RegimeAnalysis(
                    primary_regime=MarketRegime.LIQUIDITY_HUNT,
                    confidence=0.75,
                    description=f"Рынок в liquidity-hunt режиме: высокая вероятность выноса {direction} перед разворотом"
                )
        
        # 4. Chop regime
        # Высокая волатильность, но без направления
        if volatility > 0.02 and trend_strength < 0.2:
            return RegimeAnalysis(
                primary_regime=MarketRegime.CHOP,
                confidence=0.7,
                description="Рынок в режиме раскачки (chop) — высокая волатильность без направления"
            )
        
        # По умолчанию - тренд с низкой уверенностью
        return RegimeAnalysis(
            primary_regime=MarketRegime.TREND,
            confidence=0.5,
            description="Рынок в трендовом режиме"
        )












