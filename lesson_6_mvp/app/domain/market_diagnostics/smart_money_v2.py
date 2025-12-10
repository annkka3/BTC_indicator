# app/domain/market_diagnostics/smart_money_v2.py
"""
Smart Money Map v2 - расширенная интерпретация поведения Smart Money.
"""

from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from enum import Enum


class SmartMoneyBehavior(Enum):
    """Поведение Smart Money."""
    ACCUMULATING = "accumulating"
    DISTRIBUTING = "distributing"
    NOT_INTERESTED = "not_interested"
    WAITING = "waiting"
    AGGRESSIVE_BUY = "aggressive_buy"
    AGGRESSIVE_SELL = "aggressive_sell"


@dataclass
class SFPProbability:
    """Вероятность Stop Hunt (SFP)."""
    probability_1h: float
    probability_4h: float
    direction: str  # "up" or "down"
    factors: List[str]


@dataclass
class SmartMoneyAnalysis:
    """Анализ Smart Money."""
    behavior: SmartMoneyBehavior
    behavior_description: str
    narrative_interpretation: str
    sfp_probability: Optional[SFPProbability] = None


class SmartMoneyV2:
    """Расширенный анализ Smart Money."""
    
    def __init__(self):
        """Инициализация."""
        pass
    
    def analyze_smart_money_behavior(
        self,
        current_price: float,
        weekly_ob: Optional[float] = None,  # Weekly Order Block
        weekly_os: Optional[float] = None,  # Weekly Order Block (support)
        daily_fvg: Optional[Dict] = None,  # {price_low, price_high}
        volume_profile: Optional[Dict] = None,  # {price: volume}
        limit_orders: Optional[Dict] = None  # {price: volume}
    ) -> Tuple[SmartMoneyBehavior, str]:
        """
        Определить поведение Smart Money.
        
        Returns:
            Tuple[behavior, description]
        """
        # Цена над недельным OB
        if weekly_ob and current_price > weekly_ob:
            return SmartMoneyBehavior.NOT_INTERESTED, f"Цена над недельным OB ({weekly_ob:.0f}) — Smart Money не желает покупать дорого"
        
        # Цена подошла к daily FVG
        if daily_fvg:
            fvg_low = daily_fvg.get('price_low', 0)
            fvg_high = daily_fvg.get('price_high', 0)
            if fvg_low <= current_price <= fvg_high:
                return SmartMoneyBehavior.DISTRIBUTING, f"Цена подошла к daily FVG ({fvg_low:.0f}–{fvg_high:.0f}) — типичное место для сброса"
        
        # Анализ volume profile
        if volume_profile:
            # Ищем зоны накопления (высокий объём на нижних уровнях)
            high_volume_prices = [p for p, v in volume_profile.items() if v > sum(volume_profile.values()) / len(volume_profile) * 1.5]
            if high_volume_prices:
                support_levels = [p for p in high_volume_prices if p < current_price]
                if support_levels:
                    nearest_support = max(support_levels)
                    if abs(current_price - nearest_support) / current_price < 0.02:  # В пределах 2%
                        return SmartMoneyBehavior.ACCUMULATING, f"Цена у зоны накопления ({nearest_support:.0f}) — Smart Money накапливает"
        
        # Анализ лимитных ордеров
        if limit_orders:
            buy_orders = sum(v for p, v in limit_orders.items() if p < current_price)
            sell_orders = sum(v for p, v in limit_orders.items() if p > current_price)
            
            if buy_orders > sell_orders * 1.5:
                return SmartMoneyBehavior.ACCUMULATING, "Лимитные ордера покупателей преобладают — накопление"
            elif sell_orders > buy_orders * 1.5:
                return SmartMoneyBehavior.DISTRIBUTING, "Лимитные ордера продавцов преобладают — распределение"
        
        return SmartMoneyBehavior.WAITING, "Smart Money в режиме ожидания"
    
    def calculate_sfp_probability(
        self,
        current_price: float,
        liquidity_above: List[float],
        liquidity_below: List[float],
        recent_wicks: List[float],
        volume_absorption: float,  # Поглощение объёма
        oi_delta: Optional[float] = None,
        lookback_1h: int = 20,
        lookback_4h: int = 10
    ) -> SFPProbability:
        """
        Рассчитать вероятность Stop Hunt (SFP).
        
        Returns:
            SFPProbability с вероятностями для 1h и 4h
        """
        factors = []
        prob_1h = 0.0
        prob_4h = 0.0
        direction = "neutral"
        
        # Анализ ликвидности
        liq_above_sum = sum(liquidity_above) if liquidity_above else 0
        liq_below_sum = sum(liquidity_below) if liquidity_below else 0
        
        if liq_above_sum > liq_below_sum * 1.5:
            direction = "up"
            prob_1h += 0.3
            prob_4h += 0.4
            factors.append("ликвидность выше")
        elif liq_below_sum > liq_above_sum * 1.5:
            direction = "down"
            prob_1h += 0.3
            prob_4h += 0.4
            factors.append("ликвидность ниже")
        
        # Анализ фитилей
        if recent_wicks:
            avg_wick = sum(recent_wicks) / len(recent_wicks)
            large_wicks = sum(1 for w in recent_wicks if w > avg_wick * 1.5)
            if large_wicks > len(recent_wicks) * 0.3:
                prob_1h += 0.2
                prob_4h += 0.15
                factors.append("большие фитили")
        
        # Поглощение объёма
        if volume_absorption > 0.7:
            prob_1h += 0.2
            prob_4h += 0.1
            factors.append("поглощение объёма")
        elif volume_absorption < 0.3:
            prob_1h += 0.1
            prob_4h += 0.05
            factors.append("слабое поглощение")
        
        # OI delta
        if oi_delta:
            if oi_delta > 0.03:  # Рост OI
                prob_1h += 0.1
                prob_4h += 0.15
                factors.append("рост OI")
            elif oi_delta < -0.03:  # Падение OI
                prob_1h += 0.1
                prob_4h += 0.15
                factors.append("падение OI")
        
        # Ограничиваем вероятности
        prob_1h = min(prob_1h, 0.95)
        prob_4h = min(prob_4h, 0.95)
        
        return SFPProbability(
            probability_1h=prob_1h,
            probability_4h=prob_4h,
            direction=direction,
            factors=factors
        )
    
    def generate_narrative_interpretation(
        self,
        behavior: SmartMoneyBehavior,
        behavior_desc: str,
        current_price: float,
        key_levels: List[float]
    ) -> str:
        """Сгенерировать narrative интерпретацию."""
        narratives = {
            SmartMoneyBehavior.ACCUMULATING: "Smart Money накапливает позиции — благоприятный сигнал для лонгов",
            SmartMoneyBehavior.DISTRIBUTING: "Smart Money распределяет позиции — осторожность для лонгов",
            SmartMoneyBehavior.NOT_INTERESTED: "Smart Money не заинтересован в покупках на текущих уровнях",
            SmartMoneyBehavior.WAITING: "Smart Money в режиме ожидания — ждёт лучших уровней",
            SmartMoneyBehavior.AGGRESSIVE_BUY: "Smart Money агрессивно покупает — сильный бычий сигнал",
            SmartMoneyBehavior.AGGRESSIVE_SELL: "Smart Money агрессивно продаёт — сильный медвежий сигнал"
        }
        
        base_narrative = narratives.get(behavior, behavior_desc)
        
        # Добавляем контекст по уровням
        if key_levels:
            nearest_level = min(key_levels, key=lambda x: abs(x - current_price))
            if abs(nearest_level - current_price) / current_price < 0.01:
                base_narrative += f" Цена у ключевого уровня {nearest_level:.0f}."
        
        return base_narrative
    
    def analyze_smart_money(
        self,
        current_price: float,
        weekly_ob: Optional[float] = None,
        weekly_os: Optional[float] = None,
        daily_fvg: Optional[Dict] = None,
        volume_profile: Optional[Dict] = None,
        limit_orders: Optional[Dict] = None,
        liquidity_above: Optional[List[float]] = None,
        liquidity_below: Optional[List[float]] = None,
        recent_wicks: Optional[List[float]] = None,
        volume_absorption: float = 0.5,
        oi_delta: Optional[float] = None,
        key_levels: Optional[List[float]] = None
    ) -> SmartMoneyAnalysis:
        """
        Полный анализ Smart Money.
        
        Returns:
            SmartMoneyAnalysis
        """
        # Поведение
        behavior, behavior_desc = self.analyze_smart_money_behavior(
            current_price, weekly_ob, weekly_os, daily_fvg, volume_profile, limit_orders
        )
        
        # Narrative
        narrative = self.generate_narrative_interpretation(
            behavior, behavior_desc, current_price, key_levels or []
        )
        
        # SFP вероятность
        sfp_prob = None
        if liquidity_above is not None or liquidity_below is not None:
            sfp_prob = self.calculate_sfp_probability(
                current_price,
                liquidity_above or [],
                liquidity_below or [],
                recent_wicks or [],
                volume_absorption,
                oi_delta
            )
        
        return SmartMoneyAnalysis(
            behavior=behavior,
            behavior_description=behavior_desc,
            narrative_interpretation=narrative,
            sfp_probability=sfp_prob
        )












