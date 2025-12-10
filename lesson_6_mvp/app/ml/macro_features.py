# app/ml/macro_features.py
"""
Модуль для добавления макро-фичей (DXY, SP500, GOLD, OIL) в ML-модели.
"""

import pandas as pd
import numpy as np
import logging
from typing import Optional, Dict
from pathlib import Path

logger = logging.getLogger("alt_forecast.ml.macro_features")

try:
    import yfinance as yf
    HAS_YFINANCE = True
except ImportError:
    HAS_YFINANCE = False
    logger.warning("yfinance not available, macro features will be limited")


def load_macro_data_for_timestamps(
    timestamps: pd.DatetimeIndex,
    symbols: list = ["^GSPC", "DX-Y.NYB", "GC=F", "CL=F"]
) -> Optional[pd.DataFrame]:
    """
    Загрузить исторические макро-данные для указанных timestamp.
    
    Args:
        timestamps: DatetimeIndex с временными метками
        symbols: Список символов для загрузки (SP500, DXY, Gold, Oil)
    
    Returns:
        DataFrame с колонками [ts, SP500_close, DXY_close, GOLD_close, OIL_close] или None
    """
    if not HAS_YFINANCE:
        logger.warning("yfinance not available, cannot load macro data")
        return None
    
    try:
        # Определяем период для загрузки
        start_date = timestamps.min() - pd.Timedelta(days=7)  # Запас для интерполяции
        end_date = timestamps.max() + pd.Timedelta(days=1)
        
        macro_data = {}
        
        # Загружаем данные для каждого символа
        symbol_map = {
            "^GSPC": "SP500",
            "DX-Y.NYB": "DXY",
            "GC=F": "GOLD",
            "CL=F": "OIL"
        }
        
        for symbol in symbols:
            try:
                ticker = yf.Ticker(symbol)
                hist = ticker.history(start=start_date, end=end_date, interval="1h")
                
                if hist.empty:
                    logger.warning(f"No data for {symbol}")
                    continue
                
                # Нормализуем индекс (убираем timezone если есть)
                hist.index = hist.index.tz_localize(None) if hist.index.tz else hist.index
                
                # Используем Close цену
                macro_data[symbol_map.get(symbol, symbol)] = hist["Close"]
                
            except Exception as e:
                logger.warning(f"Failed to load {symbol}: {e}")
                continue
        
        if not macro_data:
            return None
        
        # Объединяем все данные
        macro_df = pd.DataFrame(macro_data)
        macro_df.index.name = "ts"
        macro_df = macro_df.reset_index()
        
        # Интерполируем для точных timestamp
        macro_df = macro_df.set_index("ts")
        macro_df = macro_df.reindex(timestamps, method="ffill")
        macro_df = macro_df.fillna(method="bfill")  # Заполняем пропуски в начале
        
        return macro_df.reset_index()
    
    except Exception as e:
        logger.error(f"Failed to load macro data: {e}", exc_info=True)
        return None


def add_macro_features(
    df_feat: pd.DataFrame,
    macro_df: Optional[pd.DataFrame] = None
) -> pd.DataFrame:
    """
    Добавить макро-фичи к DataFrame с features.
    
    Args:
        df_feat: DataFrame с features (индекс = ts)
        macro_df: DataFrame с макро-данными (колонки: ts, SP500_close, DXY_close, GOLD_close, OIL_close)
    
    Returns:
        DataFrame с добавленными макро-фичами
    """
    df_result = df_feat.copy()
    
    # Если macro_df не передан, пытаемся загрузить
    if macro_df is None:
        if isinstance(df_result.index, pd.DatetimeIndex):
            macro_df = load_macro_data_for_timestamps(df_result.index)
        else:
            logger.warning("Cannot load macro data: index is not DatetimeIndex")
            macro_df = None
    
    if macro_df is None or macro_df.empty:
        # Если макро-данные недоступны, добавляем нулевые фичи
        logger.warning("Macro data not available, adding zero features")
        for col in ["SP500_close", "DXY_close", "GOLD_close", "OIL_close"]:
            df_result[f"{col}_ret1"] = 0.0
            df_result[f"{col}_ret4"] = 0.0
        df_result["SP500_above_ma50"] = 0.0
        df_result["risk_on_off"] = 0.0
        return df_result
    
    # Нормализуем macro_df: убеждаемся, что ts в индексе или колонке
    if "ts" in macro_df.columns:
        macro_df = macro_df.set_index("ts")
    
    # Джойним по timestamp (индексу)
    macro_df_aligned = macro_df.reindex(df_result.index, method="ffill")
    
    # Добавляем returns для макро-инструментов
    for col in ["SP500_close", "DXY_close", "GOLD_close", "OIL_close"]:
        if col in macro_df_aligned.columns:
            # Returns (БЕЗ УТЕЧКИ: shift(1))
            df_result[f"{col}_ret1"] = macro_df_aligned[col].pct_change(1).shift(1).fillna(0.0)
            df_result[f"{col}_ret4"] = macro_df_aligned[col].pct_change(4).shift(1).fillna(0.0)
            
            # Спрэды с BTC (если есть close)
            if "close" in df_result.columns:
                btc_ret1 = df_result["close"].pct_change(1).shift(1).fillna(0.0)
                df_result[f"BTC_{col}_spread_ret1"] = (btc_ret1 - df_result[f"{col}_ret1"]).fillna(0.0)
        else:
            # Если колонка отсутствует, добавляем нули
            df_result[f"{col}_ret1"] = 0.0
            df_result[f"{col}_ret4"] = 0.0
    
    # Risk-on / Risk-off индикатор (SP500 выше/ниже своей 50MA)
    if "SP500_close" in macro_df_aligned.columns:
        sp500_ma50 = macro_df_aligned["SP500_close"].rolling(50, min_periods=1).mean().shift(1)
        df_result["SP500_above_ma50"] = (macro_df_aligned["SP500_close"] > sp500_ma50).astype(float).fillna(0.0)
        
        # Risk-on/off: 1 если SP500 выше MA50 и растет, -1 если ниже и падает
        sp500_ret1 = macro_df_aligned["SP500_close"].pct_change(1).shift(1).fillna(0.0)
        df_result["risk_on_off"] = (
            np.where(
                (df_result["SP500_above_ma50"] > 0.5) & (sp500_ret1 > 0),
                1.0,
                np.where(
                    (df_result["SP500_above_ma50"] < 0.5) & (sp500_ret1 < 0),
                    -1.0,
                    0.0
                )
            )
        ).astype(float)
    else:
        df_result["SP500_above_ma50"] = 0.0
        df_result["risk_on_off"] = 0.0
    
    # Очистка
    macro_feature_cols = [c for c in df_result.columns if any(x in c for x in ["SP500", "DXY", "GOLD", "OIL", "risk_on"])]
    df_result[macro_feature_cols] = df_result[macro_feature_cols].replace([np.inf, -np.inf], np.nan)
    df_result[macro_feature_cols] = df_result[macro_feature_cols].fillna(0.0)
    
    logger.info(f"Added {len(macro_feature_cols)} macro features")
    
    return df_result


















