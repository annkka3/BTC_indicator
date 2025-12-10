# app/domain/market_diagnostics/bias_engine_v2.py
"""
Bias Engine v2 - расширенная система определения bias с учетом структурных и ликвидностных факторов.
"""

from typing import Dict, Optional, Tuple, List
from dataclasses import dataclass
from enum import Enum


class StructuralBias(Enum):
    """Структурный bias на основе HTF структуры."""
    BULLISH_STRUCTURE = "bullish_structure"
    BEARISH_STRUCTURE = "bearish_structure"
    NEUTRAL_STRUCTURE = "neutral_structure"
    BEARISH_IMBALANCE = "bearish_imbalance"
    BULLISH_IMBALANCE = "bullish_imbalance"
    ABOVE_EQH = "above_eqh"
    BELOW_EQL = "below_eql"


class LiquidityBias(Enum):
    """Bias на основе потока ликвидности."""
    LIQUIDITY_BELOW = "liquidity_below"
    LIQUIDITY_ABOVE = "liquidity_above"
    SFP_RISK_HIGH = "sfp_risk_high"
    LIQUIDITY_NEUTRAL = "liquidity_neutral"
    ACCUMULATION = "accumulation"


@dataclass
class BiasAnalysis:
    """Расширенный анализ bias."""
    tactical: str  # Тактический bias (LONG/SHORT/NEUTRAL)
    strategic: str  # Стратегический bias (LONG/SHORT)
    structural: Optional[StructuralBias] = None
    structural_description: str = ""
    liquidity: Optional[LiquidityBias] = None
    liquidity_description: str = ""


class BiasEngineV2:
    """Расширенный движок определения bias."""
    
    def __init__(self):
        """Инициализация."""
        pass
    
    def analyze_structural_bias(
        self,
        current_price: float,
        htf_levels: Dict[str, List[float]],  # {timeframe: [levels]}
        imbalances: List[Dict],  # [{price_low, price_high, direction}]
        eqh_levels: List[float],  # Equal highs
        eql_levels: List[float]  # Equal lows
    ) -> Tuple[Optional[StructuralBias], str]:
        """
        Определить структурный bias на основе HTF структуры.
        
        Args:
            current_price: Текущая цена
            htf_levels: Уровни на старших таймфреймах
            imbalances: Имбалансы (FVG)
            eqh_levels: Уровни равных максимумов
            eql_levels: Уровни равных минимумов
        
        Returns:
            Tuple[StructuralBias, description]
        """
        # Проверяем положение относительно EQH/EQL
        if eqh_levels:
            nearest_eqh = min([eqh for eqh in eqh_levels if eqh > current_price], default=None)
            if nearest_eqh and abs(current_price - nearest_eqh) / current_price < 0.01:  # В пределах 1%
                return StructuralBias.ABOVE_EQH, f"Выше дневного EQH ({nearest_eqh:.0f}), риск выноса стопов"
        
        if eql_levels:
            nearest_eql = max([eql for eql in eql_levels if eql < current_price], default=None)
            if nearest_eql and abs(current_price - nearest_eql) / current_price < 0.01:
                return StructuralBias.BELOW_EQL, f"Ниже дневного EQL ({nearest_eql:.0f}), поддержка"
        
        # Проверяем имбалансы
        for imb in imbalances:
            if imb.get('filled', False):
                continue
            imb_low = imb.get('price_low', 0)
            imb_high = imb.get('price_high', 0)
            direction = imb.get('direction', 'bullish')
            
            if imb_low <= current_price <= imb_high:
                if direction == 'bearish':
                    return StructuralBias.BEARISH_IMBALANCE, f"Внутри дневного bearish imbalance ({imb_low:.0f}–{imb_high:.0f})"
                else:
                    return StructuralBias.BULLISH_IMBALANCE, f"Внутри дневного bullish imbalance ({imb_low:.0f}–{imb_high:.0f})"
        
        # Проверяем HTF уровни
        if htf_levels:
            # Анализируем структуру на старших ТФ
            for tf, levels in htf_levels.items():
                if not levels:
                    continue
                
                # Если цена выше большинства уровней на HTF - бычья структура
                above_count = sum(1 for level in levels if current_price > level)
                if above_count > len(levels) * 0.7:
                    return StructuralBias.BULLISH_STRUCTURE, f"Бычья структура на {tf}"
                elif above_count < len(levels) * 0.3:
                    return StructuralBias.BEARISH_STRUCTURE, f"Медвежья структура на {tf}"
        
        return StructuralBias.NEUTRAL_STRUCTURE, "Нейтральная структура"
    
    def analyze_liquidity_bias(
        self,
        current_price: float,
        liquidity_above: List[float],
        liquidity_below: List[float],
        recent_volume: float,
        avg_volume: float,
        oi_delta: Optional[float] = None,
        funding_rate: Optional[float] = None
    ) -> Tuple[Optional[LiquidityBias], str]:
        """
        Определить bias на основе потока ликвидности.
        
        Args:
            current_price: Текущая цена
            liquidity_above: Ликвидность выше цены
            liquidity_below: Ликвидность ниже цены
            recent_volume: Недавний объём
            avg_volume: Средний объём
            oi_delta: Изменение Open Interest
            funding_rate: Текущий funding rate
        
        Returns:
            Tuple[LiquidityBias, description]
        """
        # Анализируем распределение ликвидности
        liq_above_sum = sum(liquidity_above) if liquidity_above else 0
        liq_below_sum = sum(liquidity_below) if liquidity_below else 0
        
        # Если ликвидность ниже - риск SFP
        if liq_below_sum > liq_above_sum * 1.5:
            return LiquidityBias.LIQUIDITY_BELOW, f"Ликвидность ниже ({liq_below_sum:.0f} vs {liq_above_sum:.0f}), SFP-риск высок"
        
        # Если ликвидность выше - возможен вынос
        if liq_above_sum > liq_below_sum * 1.5:
            return LiquidityBias.LIQUIDITY_ABOVE, f"Ликвидность выше ({liq_above_sum:.0f} vs {liq_below_sum:.0f}), возможен вынос вверх перед разворотом"
        
        # Проверяем объём на накопление
        if recent_volume < avg_volume * 0.7:
            if oi_delta and oi_delta > 0:
                return LiquidityBias.ACCUMULATION, "Накопление ликвидности над локальными хайями"
        
        # Проверяем SFP риск на основе funding
        if funding_rate and funding_rate > 0.01:  # Слишком высокий funding
            return LiquidityBias.SFP_RISK_HIGH, f"Funding {funding_rate*100:.3f}% — слишком горячо, вероятна контрреакция"
        
        return LiquidityBias.LIQUIDITY_NEUTRAL, "Нейтральный → накопление ликвидности над локальными хайями"
    
    def get_full_bias_analysis(
        self,
        tactical_bias: str,
        strategic_bias: str,
        current_price: float,
        htf_levels: Optional[Dict[str, List[float]]] = None,
        imbalances: Optional[List[Dict]] = None,
        eqh_levels: Optional[List[float]] = None,
        eql_levels: Optional[List[float]] = None,
        liquidity_above: Optional[List[float]] = None,
        liquidity_below: Optional[List[float]] = None,
        recent_volume: Optional[float] = None,
        avg_volume: Optional[float] = None,
        oi_delta: Optional[float] = None,
        funding_rate: Optional[float] = None
    ) -> BiasAnalysis:
        """
        Получить полный анализ bias.
        
        Returns:
            BiasAnalysis с всеми типами bias
        """
        structural_bias = None
        structural_desc = ""
        liquidity_bias = None
        liquidity_desc = ""
        
        # Анализируем структурный bias
        if htf_levels or imbalances or eqh_levels or eql_levels:
            structural_bias, structural_desc = self.analyze_structural_bias(
                current_price,
                htf_levels or {},
                imbalances or [],
                eqh_levels or [],
                eql_levels or []
            )
        
        # Анализируем ликвидностный bias
        if liquidity_above is not None or liquidity_below is not None:
            liquidity_bias, liquidity_desc = self.analyze_liquidity_bias(
                current_price,
                liquidity_above or [],
                liquidity_below or [],
                recent_volume or 0,
                avg_volume or 0,
                oi_delta,
                funding_rate
            )
        
        return BiasAnalysis(
            tactical=tactical_bias,
            strategic=strategic_bias,
            structural=structural_bias,
            structural_description=structural_desc,
            liquidity=liquidity_bias,
            liquidity_description=liquidity_desc
        )












