# app/ml/momentum_features.py
"""
Модуль для добавления Momentum Intelligence фичей в ML-модели.
"""

import pandas as pd
import numpy as np
import logging
from typing import Optional, Dict

logger = logging.getLogger("alt_forecast.ml.momentum_features")


def add_momentum_features(
    df_feat: pd.DataFrame,
    indicators: Optional[Dict] = None
) -> pd.DataFrame:
    """
    Добавить Momentum Intelligence фичи к DataFrame с features.
    
    Args:
        df_feat: DataFrame с features (индекс = ts)
        indicators: Словарь индикаторов (RSI, MACD, StochRSI, WT, STC, ADX, +DI, -DI)
    
    Returns:
        DataFrame с добавленными momentum фичами
    """
    df_result = df_feat.copy()
    
    # Если indicators не передан, вычисляем из df_feat
    if indicators is None:
        indicators = {}
        
        # RSI уже должен быть в df_feat
        if "rsi_14" in df_result.columns:
            indicators["rsi"] = df_result["rsi_14"]
        
        # MACD уже должен быть в df_feat
        if "macd" in df_result.columns:
            indicators["macd"] = df_result["macd"]
            if "macd_sig" in df_result.columns:
                indicators["macd_signal"] = df_result["macd_sig"]
                indicators["macd_hist"] = df_result["macd"] - df_result["macd_sig"]
    
    # === 1. MOMENTUM STATE (one-hot encoding) ===
    # Определяем состояние импульса на основе RSI, MACD, StochRSI
    
    # Continuation (продолжение тренда)
    momentum_continuation = 0.0
    if "rsi" in indicators:
        rsi = indicators["rsi"]
        if hasattr(rsi, "iloc") and len(rsi) > 0:
            rsi_last = float(rsi.iloc[-1]) if hasattr(rsi, "iloc") else float(rsi)
            # Continuation: RSI в зоне 50-70 (бычий) или 30-50 (медвежий)
            if 50 < rsi_last < 70:
                momentum_continuation = 1.0
            elif 30 < rsi_last < 50:
                momentum_continuation = -1.0
    
    # Exhaustion (истощение)
    momentum_exhaustion = 0.0
    if "rsi" in indicators:
        rsi = indicators["rsi"]
        if hasattr(rsi, "iloc") and len(rsi) > 0:
            rsi_last = float(rsi.iloc[-1]) if hasattr(rsi, "iloc") else float(rsi)
            # Exhaustion: RSI > 70 (перекупленность) или < 30 (перепроданность)
            if rsi_last > 70:
                momentum_exhaustion = 1.0  # Бычье истощение
            elif rsi_last < 30:
                momentum_exhaustion = -1.0  # Медвежье истощение
    
    # Reversal risk (риск разворота)
    momentum_reversal_risk = 0.0
    if "macd_hist" in indicators:
        macd_hist = indicators["macd_hist"]
        if hasattr(macd_hist, "iloc") and len(macd_hist) > 0:
            # Если MACD histogram меняет знак или близок к нулю
            if len(macd_hist) >= 2:
                hist_last = float(macd_hist.iloc[-1])
                hist_prev = float(macd_hist.iloc[-2])
                if (hist_last > 0 and hist_prev < 0) or (hist_last < 0 and hist_prev > 0):
                    momentum_reversal_risk = 1.0  # Смена знака
                elif abs(hist_last) < abs(hist_prev) * 0.5:
                    momentum_reversal_risk = 0.5  # Ослабление импульса
    
    # Добавляем фичи
    df_result["momentum_state_continuation"] = momentum_continuation
    df_result["momentum_state_exhaustion"] = momentum_exhaustion
    df_result["momentum_state_reversal_risk"] = momentum_reversal_risk
    
    # === 2. MOMENTUM BIAS (направление) ===
    momentum_bias = 0.0  # -1 (bearish), 0 (neutral), 1 (bullish)
    
    bullish_signals = 0
    bearish_signals = 0
    
    if "rsi" in indicators:
        rsi = indicators["rsi"]
        if hasattr(rsi, "iloc") and len(rsi) > 0:
            rsi_last = float(rsi.iloc[-1]) if hasattr(rsi, "iloc") else float(rsi)
            if rsi_last > 50:
                bullish_signals += 1
            elif rsi_last < 50:
                bearish_signals += 1
    
    if "macd" in indicators and "macd_signal" in indicators:
        macd = indicators["macd"]
        macd_sig = indicators["macd_signal"]
        if hasattr(macd, "iloc") and hasattr(macd_sig, "iloc"):
            if len(macd) > 0 and len(macd_sig) > 0:
                macd_last = float(macd.iloc[-1])
                sig_last = float(macd_sig.iloc[-1])
                if macd_last > sig_last:
                    bullish_signals += 1
                elif macd_last < sig_last:
                    bearish_signals += 1
    
    # Определяем bias
    if bullish_signals > bearish_signals:
        momentum_bias = 1.0
    elif bearish_signals > bullish_signals:
        momentum_bias = -1.0
    
    df_result["momentum_bias"] = momentum_bias
    
    # === 3. MOMENTUM STRENGTH (0..1) ===
    momentum_strength = 0.5  # По умолчанию нейтрально
    
    if "rsi" in indicators:
        rsi = indicators["rsi"]
        if hasattr(rsi, "iloc") and len(rsi) > 0:
            rsi_last = float(rsi.iloc[-1]) if hasattr(rsi, "iloc") else float(rsi)
            # Strength: расстояние от 50 (нейтральной зоны)
            if rsi_last > 50:
                momentum_strength = min(1.0, (rsi_last - 50) / 50.0)  # 0.5 -> 1.0 для 50-100
            else:
                momentum_strength = min(1.0, (50 - rsi_last) / 50.0)  # 0.5 -> 1.0 для 0-50
    
    df_result["momentum_strength"] = momentum_strength
    
    # === 4. MOMENTUM CONFIDENCE (0..1) ===
    # Уверенность в анализе импульса (на основе согласованности индикаторов)
    momentum_confidence = 0.5
    
    signals_count = 0
    agreement_count = 0
    
    if "rsi" in indicators and "macd" in indicators:
        rsi = indicators["rsi"]
        macd = indicators["macd"]
        if hasattr(rsi, "iloc") and hasattr(macd, "iloc"):
            if len(rsi) > 0 and len(macd) > 0:
                rsi_last = float(rsi.iloc[-1])
                macd_last = float(macd.iloc[-1])
                signals_count += 2
                # Согласованность: оба в одном направлении
                if (rsi_last > 50 and macd_last > 0) or (rsi_last < 50 and macd_last < 0):
                    agreement_count += 2
    
    if signals_count > 0:
        momentum_confidence = agreement_count / signals_count
    
    df_result["momentum_confidence"] = momentum_confidence
    
    # Очистка
    momentum_feature_cols = [c for c in df_result.columns if "momentum" in c]
    df_result[momentum_feature_cols] = df_result[momentum_feature_cols].replace([np.inf, -np.inf], np.nan)
    df_result[momentum_feature_cols] = df_result[momentum_feature_cols].fillna(0.0)
    
    logger.info(f"Added {len(momentum_feature_cols)} momentum features")
    
    return df_result


















