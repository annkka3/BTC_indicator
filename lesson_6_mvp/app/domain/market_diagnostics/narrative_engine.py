# app/domain/market_diagnostics/narrative_engine.py
"""
Narrative Engine - объяснение рынка человеческим языком на основе микро-аналитики.
"""

from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from enum import Enum


class MarketProfile(Enum):
    """Профиль поведения рынка."""
    BUYER_AGGRESSION = "buyer_aggression"
    SELLER_AGGRESSION = "seller_aggression"
    BUYER_EXHAUSTION = "buyer_exhaustion"
    SELLER_EXHAUSTION = "seller_exhaustion"
    NEUTRAL = "neutral"
    MOMENTUM_LOSS = "momentum_loss"


@dataclass
class NarrativeSummary:
    """Сводка нарратива рынка."""
    profile: MarketProfile
    narrative_text: str
    micro_analysis: str
    behavior_profile: str


class NarrativeEngine:
    """Движок генерации нарративов рынка."""
    
    def __init__(self):
        """Инициализация."""
        pass
    
    def analyze_candle_microstructure(
        self,
        candles: List[Dict],  # [{open, high, low, close, volume}]
        lookback: int = 10
    ) -> Dict[str, any]:
        """
        Микро-аналитика свечей: wick pressure, body dominance.
        
        Args:
            candles: Последние свечи
            lookback: Количество свечей для анализа
        
        Returns:
            Dict с анализом микроструктуры
        """
        if len(candles) < lookback:
            lookback = len(candles)
        
        recent = candles[-lookback:]
        
        # Анализ wick pressure
        upper_wicks = []
        lower_wicks = []
        bodies = []
        
        for candle in recent:
            body = abs(candle['close'] - candle['open'])
            upper_wick = candle['high'] - max(candle['open'], candle['close'])
            lower_wick = min(candle['open'], candle['close']) - candle['low']
            total_range = candle['high'] - candle['low']
            
            if total_range > 0:
                upper_wicks.append(upper_wick / total_range)
                lower_wicks.append(lower_wick / total_range)
                bodies.append(body / total_range)
        
        avg_upper_wick = sum(upper_wicks) / len(upper_wicks) if upper_wicks else 0
        avg_lower_wick = sum(lower_wicks) / len(lower_wicks) if lower_wicks else 0
        avg_body = sum(bodies) / len(bodies) if bodies else 0
        
        # Определяем доминирование
        if avg_upper_wick > 0.4:
            wick_pressure = "верхнее давление (верхние фитили)"
        elif avg_lower_wick > 0.4:
            wick_pressure = "нижнее давление (нижние фитили)"
        else:
            wick_pressure = "нейтральное"
        
        # Body dominance
        if avg_body > 0.6:
            body_dominance = "сильное доминирование тела"
        elif avg_body < 0.3:
            body_dominance = "слабое тело, много фитилей"
        else:
            body_dominance = "умеренное тело"
        
        return {
            "wick_pressure": wick_pressure,
            "body_dominance": body_dominance,
            "avg_upper_wick": avg_upper_wick,
            "avg_lower_wick": avg_lower_wick,
            "avg_body": avg_body
        }
    
    def analyze_buyer_seller_profile(
        self,
        candles: List[Dict],
        volumes: List[float],
        lookback: int = 10
    ) -> Tuple[str, MarketProfile]:
        """
        Профиль поведения покупателей/продавцов.
        
        Returns:
            Tuple[description, MarketProfile]
        """
        if len(candles) < lookback or len(volumes) < lookback:
            lookback = min(len(candles), len(volumes))
        
        recent_candles = candles[-lookback:]
        recent_volumes = volumes[-lookback:]
        
        # Анализ агрессии
        buying_volume = 0
        selling_volume = 0
        up_candles = 0
        down_candles = 0
        
        for i, candle in enumerate(recent_candles):
            volume = recent_volumes[i] if i < len(recent_volumes) else 0
            
            if candle['close'] > candle['open']:
                buying_volume += volume
                up_candles += 1
            else:
                selling_volume += volume
                down_candles += 1
        
        total_volume = buying_volume + selling_volume
        
        if total_volume == 0:
            return "Нейтральное поведение", MarketProfile.NEUTRAL
        
        buying_ratio = buying_volume / total_volume
        
        # Определяем профиль
        if buying_ratio > 0.65 and up_candles > down_candles * 1.5:
            return f"Агрессия покупателей ({buying_ratio*100:.0f}% объёма вверх)", MarketProfile.BUYER_AGGRESSION
        elif buying_ratio < 0.35 and down_candles > up_candles * 1.5:
            return f"Агрессия продавцов ({(1-buying_ratio)*100:.0f}% объёма вниз)", MarketProfile.SELLER_AGGRESSION
        elif buying_ratio > 0.6 and up_candles < down_candles:
            return "Усталость покупателей — движение без подтверждения", MarketProfile.BUYER_EXHAUSTION
        elif buying_ratio < 0.4 and down_candles < up_candles:
            return "Усталость продавцов — движение без подтверждения", MarketProfile.SELLER_EXHAUSTION
        else:
            return "Нейтральное поведение", MarketProfile.NEUTRAL
    
    def generate_narrative(
        self,
        candles: List[Dict],
        volumes: List[float],
        momentum_score: float,
        volume_score: float,
        trend_direction: str,
        lookback: int = 10
    ) -> NarrativeSummary:
        """
        Сгенерировать полный нарратив рынка.
        
        Returns:
            NarrativeSummary
        """
        # Микро-аналитика
        micro = self.analyze_candle_microstructure(candles, lookback)
        
        # Профиль поведения
        behavior_desc, profile = self.analyze_buyer_seller_profile(candles, volumes, lookback)
        
        # Формируем нарратив
        narrative_parts = []
        
        # Анализ импульса
        if momentum_score < -0.3:
            narrative_parts.append("Рынок показывает усталость покупателей.")
            if volume_score < 0:
                narrative_parts.append("Последний импульс был без подтверждения объёма, что типично перед ломкой тренда.")
        
        # Анализ поведения
        if profile == MarketProfile.BUYER_EXHAUSTION:
            narrative_parts.append("Рынок движется вверх без агрессии покупателей — это увеличение риска коррекции.")
        elif profile == MarketProfile.SELLER_EXHAUSTION:
            narrative_parts.append("Рынок движется вниз без агрессии продавцов — возможен разворот.")
        
        # Микроструктура
        if micro['wick_pressure'] == "верхнее давление (верхние фитили)":
            narrative_parts.append("Верхние фитили указывают на давление продавцов на локальных максимумах.")
        elif micro['wick_pressure'] == "нижнее давление (нижние фитили)":
            narrative_parts.append("Нижние фитили указывают на поддержку покупателей на локальных минимумах.")
        
        narrative_text = " ".join(narrative_parts) if narrative_parts else "Рынок в нейтральном состоянии."
        
        return NarrativeSummary(
            profile=profile,
            narrative_text=narrative_text,
            micro_analysis=f"{micro['wick_pressure']}, {micro['body_dominance']}",
            behavior_profile=behavior_desc
        )

