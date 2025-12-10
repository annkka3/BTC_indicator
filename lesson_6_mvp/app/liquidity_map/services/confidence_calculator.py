# app/liquidity_map/services/confidence_calculator.py
"""
Калькулятор Confidence Score (0-100).
"""
from typing import List
from ..domain.models import TimeframeSnapshot
from ..domain.enums import MarketRegime, ZoneRole
from .zone_classifier import get_execution_zones


def calculate_confidence_score(snapshots: List[TimeframeSnapshot], regime: MarketRegime, 
                               current_price: float) -> tuple[int, str]:
    """
    Вычислить Confidence Score (0-100) и интерпретацию.
    
    Формула:
    - regime_score: 0-30
    - zone_quality_score: 0-30
    - pressure_alignment: 0-20
    - distance_to_zone: 0-10
    - HTF_confirmation: 0-10
    
    Args:
        snapshots: Список снимков
        regime: Режим рынка
        current_price: Текущая цена
    
    Returns:
        Tuple (score, interpretation)
    """
    score = 0
    
    # 1. Regime Score (0-30)
    regime_score = _calculate_regime_score(regime)
    score += regime_score
    
    # 2. Zone Quality Score (0-30)
    execution_zones = get_execution_zones(snapshots)
    # Если нет EXECUTION зон, используем все активные зоны для оценки
    if not execution_zones:
        all_active_zones = []
        for snapshot in snapshots:
            all_active_zones.extend(snapshot.active_zones)
        # Берем лучшие зоны по strength и reactions
        if all_active_zones:
            all_active_zones.sort(key=lambda z: (z.strength, z.reactions), reverse=True)
            zone_score = _calculate_zone_quality_score(all_active_zones[:2], current_price)
            # Снижаем score, если нет EXECUTION зон
            zone_score = int(zone_score * 0.7)
        else:
            zone_score = 0
    else:
        zone_score = _calculate_zone_quality_score(execution_zones, current_price)
    score += zone_score
    
    # 3. Pressure Alignment (0-20)
    pressure_score = _calculate_pressure_alignment(snapshots)
    score += pressure_score
    
    # 4. Distance to Zone (0-10)
    distance_score = _calculate_distance_score(execution_zones, current_price)
    score += distance_score
    
    # 5. HTF Confirmation (0-10)
    htf_score = _calculate_htf_confirmation(snapshots)
    score += htf_score
    
    # Интерпретация
    interpretation = _get_confidence_interpretation(score)
    
    return score, interpretation


def _calculate_regime_score(regime: MarketRegime) -> int:
    """Вычислить score режима (0-30)."""
    scores = {
        MarketRegime.TREND_CONTINUATION: 30,
        MarketRegime.PULLBACK_IN_UPTREND: 20,
        MarketRegime.COUNTER_TREND_BOUNCE: 10,
        MarketRegime.RANGE_NO_EDGE: 0
    }
    return scores.get(regime, 0)


def _calculate_zone_quality_score(zones: List, current_price: float) -> int:
    """Вычислить score качества зон (0-30)."""
    if not zones:
        return 0
    
    # Берем лучшую зону
    best_zone = zones[0]
    
    # Score на основе strength и reactions
    strength_score = int(best_zone.strength * 15)  # 0-15
    reactions_score = min(15, best_zone.reactions * 2)  # 0-15 (макс 15)
    
    # Бонус, если цена внутри зоны
    if best_zone.price_low <= current_price <= best_zone.price_high:
        return min(30, strength_score + reactions_score + 5)
    
    return strength_score + reactions_score


def _calculate_pressure_alignment(snapshots: List[TimeframeSnapshot]) -> int:
    """Вычислить score выравнивания давления (0-20)."""
    # Проверяем согласованность между ТФ
    htf_snapshots = [s for s in snapshots if s.tf in ["4h", "1d"]]
    ltf_snapshots = [s for s in snapshots if s.tf in ["1h", "15m"]]
    
    if not htf_snapshots or not ltf_snapshots:
        return 0
    
    # Проверяем, совпадают ли bias
    htf_bias = htf_snapshots[0].bias
    ltf_bias = ltf_snapshots[0].bias
    
    if htf_bias == ltf_bias and htf_bias != "NEUTRAL":
        return 20
    elif htf_bias != "NEUTRAL" and ltf_bias != "NEUTRAL":
        return 10
    else:
        return 0


def _calculate_distance_score(execution_zones: List, current_price: float) -> int:
    """Вычислить score расстояния до зоны (0-10)."""
    if not execution_zones:
        return 0
    
    best_zone = execution_zones[0]
    
    # Проверяем, находится ли цена в зоне
    if best_zone.price_low <= current_price <= best_zone.price_high:
        return 10
    
    # Расстояние в процентах
    zone_mid = best_zone.center_price
    distance_pct = abs(current_price - zone_mid) / current_price * 100 if current_price > 0 else 100
    
    if distance_pct < 0.5:
        return 8
    elif distance_pct < 1.0:
        return 5
    elif distance_pct < 2.0:
        return 2
    else:
        return 0


def _calculate_htf_confirmation(snapshots: List[TimeframeSnapshot]) -> int:
    """Вычислить score подтверждения старших ТФ (0-10)."""
    htf_snapshots = [s for s in snapshots if s.tf in ["4h", "1d"]]
    
    if not htf_snapshots:
        return 0
    
    # Проверяем силу bias на старших ТФ
    strong_confirmation = any(s.buy_pressure > 70 or s.sell_pressure > 70 for s in htf_snapshots)
    
    if strong_confirmation:
        return 10
    elif any(s.bias != "NEUTRAL" for s in htf_snapshots):
        return 5
    else:
        return 0


def _get_confidence_interpretation(score: int) -> str:
    """Получить интерпретацию confidence score."""
    if score >= 80:
        return "High confidence, strong setups available."
    elif score >= 60:
        return "Medium confidence, selective setups only."
    elif score >= 40:
        return "Low confidence, wait for better conditions."
    else:
        return "Very low confidence, no edge. Avoid trading."

