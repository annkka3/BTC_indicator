# app/domain/divergence_detector.py
"""
Расширенный детектор дивергенций для различных индикаторов.
Аналог "Divergence for Many Indicator v4" из TradingView.
"""

from typing import List, Optional, Tuple, Dict, Any
from dataclasses import dataclass
from .models import Metric, Timeframe, Divergence
from .services import rsi, macd, ema, pivots_high, pivots_low, _last_two_indices, _strength_tag, _alts_implication
import math


@dataclass
class DivergenceSignal:
    """Сигнал дивергенции с координатами для отображения на графике."""
    indicator: str  # "RSI", "MACD", "STOCH", "CCI", "MFI", "OBV", "VOLUME"
    side: str  # "bullish" или "bearish"
    price_idx_left: int  # Индекс левого пивота цены
    price_idx_right: int  # Индекс правого пивота цены
    price_val_left: float  # Значение цены в левом пивоте
    price_val_right: float  # Значение цены в правом пивоте
    indicator_val_left: float  # Значение индикатора в левом пивоте
    indicator_val_right: float  # Значение индикатора в правом пивоте
    strength: str  # "strong", "medium", "weak"
    text: str  # Текстовое описание


def stochastic(highs: List[float], lows: List[float], closes: List[float], 
               k_period: int = 14, d_period: int = 3) -> Tuple[List[Optional[float]], List[Optional[float]]]:
    """Вычислить Stochastic Oscillator (%K и %D)."""
    n = len(closes)
    if n < k_period:
        return [None] * n, [None] * n
    
    k_values: List[Optional[float]] = [None] * n
    d_values: List[Optional[float]] = [None] * n
    
    for i in range(k_period - 1, n):
        period_high = max(highs[i - k_period + 1:i + 1])
        period_low = min(lows[i - k_period + 1:i + 1])
        
        if period_high != period_low:
            k = 100 * (closes[i] - period_low) / (period_high - period_low)
            k_values[i] = k
        else:
            k_values[i] = 50.0
    
    # %D - сглаженная %K
    for i in range(k_period + d_period - 2, n):
        k_sum = sum(k_values[i - d_period + 1:i + 1])
        if k_sum is not None:
            d_values[i] = k_sum / d_period
    
    return k_values, d_values


def cci(highs: List[float], lows: List[float], closes: List[float], period: int = 20) -> List[Optional[float]]:
    """Вычислить Commodity Channel Index (CCI)."""
    n = len(closes)
    if n < period:
        return [None] * n
    
    tp = [(h + l + c) / 3.0 for h, l, c in zip(highs, lows, closes)]  # Typical Price
    cci_values: List[Optional[float]] = [None] * n
    
    for i in range(period - 1, n):
        tp_sma = sum(tp[i - period + 1:i + 1]) / period
        mean_dev = sum(abs(tp[j] - tp_sma) for j in range(i - period + 1, i + 1)) / period
        
        if mean_dev != 0:
            cci_values[i] = (tp[i] - tp_sma) / (0.015 * mean_dev)
        else:
            cci_values[i] = 0.0
    
    return cci_values


def mfi(highs: List[float], lows: List[float], closes: List[float], 
        volumes: List[Optional[float]], period: int = 14) -> List[Optional[float]]:
    """Вычислить Money Flow Index (MFI)."""
    n = len(closes)
    if n < period + 1:
        return [None] * n
    
    tp = [(h + l + c) / 3.0 for h, l, c in zip(highs, lows, closes)]  # Typical Price
    mfi_values: List[Optional[float]] = [None] * n
    
    raw_money_flow: List[Optional[float]] = [None] * n
    for i in range(1, n):
        if volumes[i] is not None and volumes[i] > 0:
            raw_money_flow[i] = tp[i] * volumes[i]
        else:
            raw_money_flow[i] = None
    
    for i in range(period, n):
        positive_flow = 0.0
        negative_flow = 0.0
        
        for j in range(i - period + 1, i + 1):
            if raw_money_flow[j] is not None and j > 0:
                if tp[j] > tp[j - 1]:
                    positive_flow += raw_money_flow[j] or 0.0
                elif tp[j] < tp[j - 1]:
                    negative_flow += raw_money_flow[j] or 0.0
        
        if negative_flow != 0:
            mfi_values[i] = 100 - (100 / (1 + positive_flow / negative_flow))
        else:
            mfi_values[i] = 100.0 if positive_flow > 0 else 50.0
    
    return mfi_values


def obv(closes: List[float], volumes: List[Optional[float]]) -> List[Optional[float]]:
    """Вычислить On-Balance Volume (OBV)."""
    n = len(closes)
    if n < 2:
        return [None] * n
    
    obv_values: List[Optional[float]] = [None] * n
    obv_values[0] = volumes[0] if volumes[0] is not None else 0.0
    
    for i in range(1, n):
        prev_obv = obv_values[i - 1] or 0.0
        vol = volumes[i] if volumes[i] is not None else 0.0
        
        if closes[i] > closes[i - 1]:
            obv_values[i] = prev_obv + vol
        elif closes[i] < closes[i - 1]:
            obv_values[i] = prev_obv - vol
        else:
            obv_values[i] = prev_obv
    
    return obv_values


def detect_divergences(
    metric: Metric,
    timeframe: Timeframe,
    closes: List[float],
    highs: List[float],
    lows: List[float],
    volumes: List[Optional[float]],
    enabled_indicators: Optional[Dict[str, bool]] = None
) -> List[DivergenceSignal]:
    """
    Обнаружить дивергенции для всех включенных индикаторов.
    
    Args:
        metric: Метрика (BTC, ETH и т.д.)
        timeframe: Таймфрейм
        closes: Список цен закрытия
        highs: Список максимумов
        lows: Список минимумов
        volumes: Список объемов
        enabled_indicators: Словарь {indicator_name: enabled} для фильтрации
    
    Returns:
        Список сигналов дивергенций
    """
    if enabled_indicators is None:
        # По умолчанию все включены
        enabled_indicators = {
            "RSI": True,
            "MACD": True,
            "STOCH": True,
            "CCI": True,
            "MFI": True,
            "OBV": True,
            "VOLUME": True,
        }
    
    n = len(closes)
    if n < 50:
        return []
    
    signals: List[DivergenceSignal] = []
    
    # Находим пивоты цены
    hi_flags = pivots_high(closes, 2, 2)
    lo_flags = pivots_low(closes, 2, 2)
    hi_idx = _last_two_indices(hi_flags)
    lo_idx = _last_two_indices(lo_flags)
    
    # Логирование для отладки
    import logging
    logger = logging.getLogger("alt_forecast.divergence_detector")
    logger.info(f"Pivots found: hi_idx={hi_idx} (count={len(hi_idx)}), lo_idx={lo_idx} (count={len(lo_idx)})")
    
    if len(hi_idx) < 2 and len(lo_idx) < 2:
        logger.info(f"No enough pivots for divergence detection: hi_idx={len(hi_idx)}, lo_idx={len(lo_idx)}")
        return []
    
    # RSI
    if enabled_indicators.get("RSI", True):
        r = rsi(closes, 14)
        # Bearish дивергенция (цена HH, RSI ниже)
        if len(hi_idx) == 2 and r[hi_idx[0]] is not None and r[hi_idx[1]] is not None:
            price_hh = closes[hi_idx[1]] > closes[hi_idx[0]]
            rsi_lower = r[hi_idx[1]] < r[hi_idx[0]]
            logger.info(f"RSI Bearish check: hi_idx={hi_idx}, price_HH={price_hh} ({closes[hi_idx[0]]:.2f} -> {closes[hi_idx[1]]:.2f}), RSI_lower={rsi_lower} ({r[hi_idx[0]]:.2f} -> {r[hi_idx[1]]:.2f})")
            if price_hh and rsi_lower:
                diff = r[hi_idx[1]] - r[hi_idx[0]]
                strength = _strength_tag(diff, r)
                signals.append(DivergenceSignal(
                    indicator="RSI",
                    side="bearish",
                    price_idx_left=hi_idx[0],
                    price_idx_right=hi_idx[1],
                    price_val_left=closes[hi_idx[0]],
                    price_val_right=closes[hi_idx[1]],
                    indicator_val_left=r[hi_idx[0]],
                    indicator_val_right=r[hi_idx[1]],
                    strength=strength,
                    text=f"Bearish дивергенция (RSI) {strength}: цена HH, RSI ниже"
                ))
        # Bullish дивергенция (цена LL, RSI выше)
        if len(lo_idx) == 2 and r[lo_idx[0]] is not None and r[lo_idx[1]] is not None:
            price_ll = closes[lo_idx[1]] < closes[lo_idx[0]]
            rsi_higher = r[lo_idx[1]] > r[lo_idx[0]]
            logger.info(f"RSI Bullish check: lo_idx={lo_idx}, price_LL={price_ll} ({closes[lo_idx[0]]:.2f} -> {closes[lo_idx[1]]:.2f}), RSI_higher={rsi_higher} ({r[lo_idx[0]]:.2f} -> {r[lo_idx[1]]:.2f})")
            if price_ll and rsi_higher:
                diff = r[lo_idx[1]] - r[lo_idx[0]]
                strength = _strength_tag(diff, r)
                signals.append(DivergenceSignal(
                    indicator="RSI",
                    side="bullish",
                    price_idx_left=lo_idx[0],
                    price_idx_right=lo_idx[1],
                    price_val_left=closes[lo_idx[0]],
                    price_val_right=closes[lo_idx[1]],
                    indicator_val_left=r[lo_idx[0]],
                    indicator_val_right=r[lo_idx[1]],
                    strength=strength,
                    text=f"Bullish дивергенция (RSI) {strength}: цена LL, RSI выше"
                ))
    
    # MACD
    if enabled_indicators.get("MACD", True):
        m_line, sig, _ = macd(closes, 12, 26, 9)
        # Bearish дивергенция
        if len(hi_idx) == 2 and m_line[hi_idx[0]] is not None and m_line[hi_idx[1]] is not None:
            if closes[hi_idx[1]] > closes[hi_idx[0]] and m_line[hi_idx[1]] < m_line[hi_idx[0]]:
                diff = m_line[hi_idx[1]] - m_line[hi_idx[0]]
                m_line_clean = [x for x in m_line if x is not None]
                strength = _strength_tag(diff, m_line_clean)
                signals.append(DivergenceSignal(
                    indicator="MACD",
                    side="bearish",
                    price_idx_left=hi_idx[0],
                    price_idx_right=hi_idx[1],
                    price_val_left=closes[hi_idx[0]],
                    price_val_right=closes[hi_idx[1]],
                    indicator_val_left=m_line[hi_idx[0]],
                    indicator_val_right=m_line[hi_idx[1]],
                    strength=strength,
                    text=f"Bearish дивергенция (MACD) {strength}: цена HH, MACD ниже"
                ))
        # Bullish дивергенция
        if len(lo_idx) == 2 and m_line[lo_idx[0]] is not None and m_line[lo_idx[1]] is not None:
            if closes[lo_idx[1]] < closes[lo_idx[0]] and m_line[lo_idx[1]] > m_line[lo_idx[0]]:
                diff = m_line[lo_idx[1]] - m_line[lo_idx[0]]
                m_line_clean = [x for x in m_line if x is not None]
                strength = _strength_tag(diff, m_line_clean)
                signals.append(DivergenceSignal(
                    indicator="MACD",
                    side="bullish",
                    price_idx_left=lo_idx[0],
                    price_idx_right=lo_idx[1],
                    price_val_left=closes[lo_idx[0]],
                    price_val_right=closes[lo_idx[1]],
                    indicator_val_left=m_line[lo_idx[0]],
                    indicator_val_right=m_line[lo_idx[1]],
                    strength=strength,
                    text=f"Bullish дивергенция (MACD) {strength}: цена LL, MACD выше"
                ))
    
    # Stochastic
    if enabled_indicators.get("STOCH", True):
        k_values, d_values = stochastic(highs, lows, closes, 14, 3)
        # Используем %K для поиска дивергенций
        # Bearish дивергенция
        if len(hi_idx) == 2 and k_values[hi_idx[0]] is not None and k_values[hi_idx[1]] is not None:
            if closes[hi_idx[1]] > closes[hi_idx[0]] and k_values[hi_idx[1]] < k_values[hi_idx[0]]:
                diff = k_values[hi_idx[1]] - k_values[hi_idx[0]]
                k_clean = [x for x in k_values if x is not None]
                strength = _strength_tag(diff, k_clean)
                signals.append(DivergenceSignal(
                    indicator="STOCH",
                    side="bearish",
                    price_idx_left=hi_idx[0],
                    price_idx_right=hi_idx[1],
                    price_val_left=closes[hi_idx[0]],
                    price_val_right=closes[hi_idx[1]],
                    indicator_val_left=k_values[hi_idx[0]],
                    indicator_val_right=k_values[hi_idx[1]],
                    strength=strength,
                    text=f"Bearish дивергенция (Stochastic) {strength}: цена HH, Stoch ниже"
                ))
        # Bullish дивергенция
        if len(lo_idx) == 2 and k_values[lo_idx[0]] is not None and k_values[lo_idx[1]] is not None:
            if closes[lo_idx[1]] < closes[lo_idx[0]] and k_values[lo_idx[1]] > k_values[lo_idx[0]]:
                diff = k_values[lo_idx[1]] - k_values[lo_idx[0]]
                k_clean = [x for x in k_values if x is not None]
                strength = _strength_tag(diff, k_clean)
                signals.append(DivergenceSignal(
                    indicator="STOCH",
                    side="bullish",
                    price_idx_left=lo_idx[0],
                    price_idx_right=lo_idx[1],
                    price_val_left=closes[lo_idx[0]],
                    price_val_right=closes[lo_idx[1]],
                    indicator_val_left=k_values[lo_idx[0]],
                    indicator_val_right=k_values[lo_idx[1]],
                    strength=strength,
                    text=f"Bullish дивергенция (Stochastic) {strength}: цена LL, Stoch выше"
                ))
    
    # CCI
    if enabled_indicators.get("CCI", True):
        cci_values = cci(highs, lows, closes, 20)
        # Bearish дивергенция
        if len(hi_idx) == 2 and cci_values[hi_idx[0]] is not None and cci_values[hi_idx[1]] is not None:
            if closes[hi_idx[1]] > closes[hi_idx[0]] and cci_values[hi_idx[1]] < cci_values[hi_idx[0]]:
                diff = cci_values[hi_idx[1]] - cci_values[hi_idx[0]]
                cci_clean = [x for x in cci_values if x is not None]
                strength = _strength_tag(diff, cci_clean)
                signals.append(DivergenceSignal(
                    indicator="CCI",
                    side="bearish",
                    price_idx_left=hi_idx[0],
                    price_idx_right=hi_idx[1],
                    price_val_left=closes[hi_idx[0]],
                    price_val_right=closes[hi_idx[1]],
                    indicator_val_left=cci_values[hi_idx[0]],
                    indicator_val_right=cci_values[hi_idx[1]],
                    strength=strength,
                    text=f"Bearish дивергенция (CCI) {strength}: цена HH, CCI ниже"
                ))
        # Bullish дивергенция
        if len(lo_idx) == 2 and cci_values[lo_idx[0]] is not None and cci_values[lo_idx[1]] is not None:
            if closes[lo_idx[1]] < closes[lo_idx[0]] and cci_values[lo_idx[1]] > cci_values[lo_idx[0]]:
                diff = cci_values[lo_idx[1]] - cci_values[lo_idx[0]]
                cci_clean = [x for x in cci_values if x is not None]
                strength = _strength_tag(diff, cci_clean)
                signals.append(DivergenceSignal(
                    indicator="CCI",
                    side="bullish",
                    price_idx_left=lo_idx[0],
                    price_idx_right=lo_idx[1],
                    price_val_left=closes[lo_idx[0]],
                    price_val_right=closes[lo_idx[1]],
                    indicator_val_left=cci_values[lo_idx[0]],
                    indicator_val_right=cci_values[lo_idx[1]],
                    strength=strength,
                    text=f"Bullish дивергенция (CCI) {strength}: цена LL, CCI выше"
                ))
    
    # MFI
    if enabled_indicators.get("MFI", True) and volumes and any(v is not None for v in volumes):
        mfi_values = mfi(highs, lows, closes, volumes, 14)
        # Bearish дивергенция
        if len(hi_idx) == 2 and mfi_values[hi_idx[0]] is not None and mfi_values[hi_idx[1]] is not None:
            if closes[hi_idx[1]] > closes[hi_idx[0]] and mfi_values[hi_idx[1]] < mfi_values[hi_idx[0]]:
                diff = mfi_values[hi_idx[1]] - mfi_values[hi_idx[0]]
                mfi_clean = [x for x in mfi_values if x is not None]
                strength = _strength_tag(diff, mfi_clean)
                signals.append(DivergenceSignal(
                    indicator="MFI",
                    side="bearish",
                    price_idx_left=hi_idx[0],
                    price_idx_right=hi_idx[1],
                    price_val_left=closes[hi_idx[0]],
                    price_val_right=closes[hi_idx[1]],
                    indicator_val_left=mfi_values[hi_idx[0]],
                    indicator_val_right=mfi_values[hi_idx[1]],
                    strength=strength,
                    text=f"Bearish дивергенция (MFI) {strength}: цена HH, MFI ниже"
                ))
        # Bullish дивергенция
        if len(lo_idx) == 2 and mfi_values[lo_idx[0]] is not None and mfi_values[lo_idx[1]] is not None:
            if closes[lo_idx[1]] < closes[lo_idx[0]] and mfi_values[lo_idx[1]] > mfi_values[lo_idx[0]]:
                diff = mfi_values[lo_idx[1]] - mfi_values[lo_idx[0]]
                mfi_clean = [x for x in mfi_values if x is not None]
                strength = _strength_tag(diff, mfi_clean)
                signals.append(DivergenceSignal(
                    indicator="MFI",
                    side="bullish",
                    price_idx_left=lo_idx[0],
                    price_idx_right=lo_idx[1],
                    price_val_left=closes[lo_idx[0]],
                    price_val_right=closes[lo_idx[1]],
                    indicator_val_left=mfi_values[lo_idx[0]],
                    indicator_val_right=mfi_values[lo_idx[1]],
                    strength=strength,
                    text=f"Bullish дивергенция (MFI) {strength}: цена LL, MFI выше"
                ))
    
    # OBV
    if enabled_indicators.get("OBV", True) and volumes and any(v is not None for v in volumes):
        obv_values = obv(closes, volumes)
        # Bearish дивергенция
        if len(hi_idx) == 2 and obv_values[hi_idx[0]] is not None and obv_values[hi_idx[1]] is not None:
            if closes[hi_idx[1]] > closes[hi_idx[0]] and obv_values[hi_idx[1]] < obv_values[hi_idx[0]]:
                diff = obv_values[hi_idx[1]] - obv_values[hi_idx[0]]
                obv_clean = [x for x in obv_values if x is not None]
                strength = _strength_tag(diff, obv_clean)
                signals.append(DivergenceSignal(
                    indicator="OBV",
                    side="bearish",
                    price_idx_left=hi_idx[0],
                    price_idx_right=hi_idx[1],
                    price_val_left=closes[hi_idx[0]],
                    price_val_right=closes[hi_idx[1]],
                    indicator_val_left=obv_values[hi_idx[0]],
                    indicator_val_right=obv_values[hi_idx[1]],
                    strength=strength,
                    text=f"Bearish дивергенция (OBV) {strength}: цена HH, OBV ниже"
                ))
        # Bullish дивергенция
        if len(lo_idx) == 2 and obv_values[lo_idx[0]] is not None and obv_values[lo_idx[1]] is not None:
            if closes[lo_idx[1]] < closes[lo_idx[0]] and obv_values[lo_idx[1]] > obv_values[lo_idx[0]]:
                diff = obv_values[lo_idx[1]] - obv_values[lo_idx[0]]
                obv_clean = [x for x in obv_values if x is not None]
                strength = _strength_tag(diff, obv_clean)
                signals.append(DivergenceSignal(
                    indicator="OBV",
                    side="bullish",
                    price_idx_left=lo_idx[0],
                    price_idx_right=lo_idx[1],
                    price_val_left=closes[lo_idx[0]],
                    price_val_right=closes[lo_idx[1]],
                    indicator_val_left=obv_values[lo_idx[0]],
                    indicator_val_right=obv_values[lo_idx[1]],
                    strength=strength,
                    text=f"Bullish дивергенция (OBV) {strength}: цена LL, OBV выше"
                ))
    
    # Volume
    if enabled_indicators.get("VOLUME", True) and volumes and any(v is not None for v in volumes):
        vols_pure = volumes
        # Bearish дивергенция (цена HH, объем ниже)
        if len(hi_idx) == 2 and vols_pure[hi_idx[0]] is not None and vols_pure[hi_idx[1]] is not None:
            if closes[hi_idx[1]] > closes[hi_idx[0]] and vols_pure[hi_idx[1]] < vols_pure[hi_idx[0]]:
                signals.append(DivergenceSignal(
                    indicator="VOLUME",
                    side="bearish",
                    price_idx_left=hi_idx[0],
                    price_idx_right=hi_idx[1],
                    price_val_left=closes[hi_idx[0]],
                    price_val_right=closes[hi_idx[1]],
                    indicator_val_left=vols_pure[hi_idx[0]],
                    indicator_val_right=vols_pure[hi_idx[1]],
                    strength="(слабая)",
                    text="Bearish дивергенция (Volume): HH на меньшем объёме"
                ))
        # Bullish дивергенция (цена LL, объем ниже)
        if len(lo_idx) == 2 and vols_pure[lo_idx[0]] is not None and vols_pure[lo_idx[1]] is not None:
            if closes[lo_idx[1]] < closes[lo_idx[0]] and vols_pure[lo_idx[1]] < vols_pure[lo_idx[0]]:
                signals.append(DivergenceSignal(
                    indicator="VOLUME",
                    side="bullish",
                    price_idx_left=lo_idx[0],
                    price_idx_right=lo_idx[1],
                    price_val_left=closes[lo_idx[0]],
                    price_val_right=closes[lo_idx[1]],
                    indicator_val_left=vols_pure[lo_idx[0]],
                    indicator_val_right=vols_pure[lo_idx[1]],
                    strength="(слабая)",
                    text="Bullish дивергенция (Volume): LL на меньшем объёме"
                ))
    
    return signals

