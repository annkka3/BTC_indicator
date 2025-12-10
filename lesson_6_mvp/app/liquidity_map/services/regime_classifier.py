# app/liquidity_map/services/regime_classifier.py
"""
Классификатор режима рынка (Market Regime).
"""
from typing import List
from ..domain.models import TimeframeSnapshot
from ..domain.enums import MarketRegime


def classify_regime(snapshots: List[TimeframeSnapshot]) -> MarketRegime:
    """
    Классифицировать режим рынка на основе bias старших и младших ТФ.
    
    Args:
        snapshots: Список снимков таймфреймов
    
    Returns:
        MarketRegime
    """
    if not snapshots:
        return MarketRegime.RANGE_NO_EDGE
    
    # Разделяем на старшие (HTF) и младшие (LTF) ТФ
    htf_tfs = ["4h", "1d"]
    ltf_tfs = ["5m", "15m", "1h"]
    
    # Определяем bias старших ТФ (учитываем доминирующий bias и силу давления)
    htf_long_score = 0.0
    htf_short_score = 0.0
    
    for snapshot in snapshots:
        if snapshot.tf in htf_tfs:
            # Приоритет более старшим ТФ (1d важнее 4h)
            weight = 2.0 if snapshot.tf == "1d" else 1.0
            
            if snapshot.buy_pressure > 60:
                # Учитываем силу давления (чем больше, тем сильнее)
                strength = (snapshot.buy_pressure - 50) / 50.0  # 0.0-1.0
                htf_long_score += strength * weight
            elif snapshot.sell_pressure > 60:
                strength = (snapshot.sell_pressure - 50) / 50.0
                htf_short_score += strength * weight
    
    htf_bias = None
    if htf_long_score > htf_short_score and htf_long_score > 0.5:
        htf_bias = "LONG"
    elif htf_short_score > htf_long_score and htf_short_score > 0.5:
        htf_bias = "SHORT"
    
    # Определяем bias младших ТФ (учитываем доминирующий bias и силу давления)
    ltf_long_score = 0.0
    ltf_short_score = 0.0
    
    for snapshot in snapshots:
        if snapshot.tf in ltf_tfs:
            # Приоритет более старшим LTF (1h важнее 15m, 15m важнее 5m)
            weight = 3.0 if snapshot.tf == "1h" else (2.0 if snapshot.tf == "15m" else 1.0)
            
            if snapshot.buy_pressure > 60:
                strength = (snapshot.buy_pressure - 50) / 50.0
                ltf_long_score += strength * weight
            elif snapshot.sell_pressure > 60:
                strength = (snapshot.sell_pressure - 50) / 50.0
                ltf_short_score += strength * weight
    
    ltf_bias = None
    if ltf_long_score > ltf_short_score and ltf_long_score > 0.5:
        ltf_bias = "LONG"
    elif ltf_short_score > ltf_long_score and ltf_short_score > 0.5:
        ltf_bias = "SHORT"
    
    # Проверяем наличие сильного противоположного сигнала на младших ТФ
    # (для определения PULLBACK даже если общий LTF bias совпадает с HTF)
    strong_ltf_opposite = False
    if htf_bias == "LONG":
        # Ищем сильный SHORT на младших ТФ (15m или 5m)
        for snapshot in snapshots:
            if snapshot.tf in ["15m", "5m"] and snapshot.sell_pressure > 80:
                strong_ltf_opposite = True
                break
    elif htf_bias == "SHORT":
        # Ищем сильный LONG на младших ТФ (15m или 5m)
        for snapshot in snapshots:
            if snapshot.tf in ["15m", "5m"] and snapshot.buy_pressure > 80:
                strong_ltf_opposite = True
                break
    
    # Классификация режима
    if htf_bias == "LONG" and (ltf_bias == "SHORT" or strong_ltf_opposite):
        return MarketRegime.PULLBACK_IN_UPTREND
    elif htf_bias == "SHORT" and (ltf_bias == "LONG" or strong_ltf_opposite):
        return MarketRegime.COUNTER_TREND_BOUNCE
    elif htf_bias == "LONG" and ltf_bias == "LONG":
        return MarketRegime.TREND_CONTINUATION
    elif htf_bias == "SHORT" and ltf_bias == "SHORT":
        return MarketRegime.TREND_CONTINUATION
    else:
        return MarketRegime.RANGE_NO_EDGE


def get_regime_description(regime: MarketRegime, symbol: str) -> str:
    """
    Получить описание режима для отчёта.
    
    Args:
        regime: Режим рынка
        symbol: Символ
    
    Returns:
        Строка описания режима
    """
    descriptions = {
        MarketRegime.PULLBACK_IN_UPTREND: f"{symbol}: Higher-TF Uptrend + Lower-TF Pullback",
        MarketRegime.COUNTER_TREND_BOUNCE: f"{symbol}: Counter-trend Bounce + Lower-TF Pullback",
        MarketRegime.TREND_CONTINUATION: f"{symbol}: Trend Continuation",
        MarketRegime.RANGE_NO_EDGE: f"{symbol}: Range / No Edge"
    }
    return descriptions.get(regime, f"{symbol}: Unknown Regime")

