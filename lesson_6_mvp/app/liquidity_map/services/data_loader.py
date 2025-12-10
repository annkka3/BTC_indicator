# app/liquidity_map/services/data_loader.py
"""
Загрузка OHLCV данных из базы данных.
"""
from typing import List
import pandas as pd
from ..domain.models import Candle
from ...infrastructure.db import DB


def load_ohlcv(symbol: str, tf: str, db: DB, n_bars: int = 500) -> List[Candle]:
    """
    Загрузить OHLCV данные для символа и таймфрейма.
    
    Args:
        symbol: Символ (например, "BTC")
        tf: Таймфрейм (например, "5m", "15m", "1h", "4h", "1d")
        db: Экземпляр базы данных
        n_bars: Количество последних баров
    
    Returns:
        Список свечей
    """
    try:
        rows = db.last_n(symbol, tf, n_bars)
        if not rows:
            return []
        
        candles = []
        for row in rows:
            candle = Candle(
                timestamp=row[0],
                open=float(row[1]),
                high=float(row[2]),
                low=float(row[3]),
                close=float(row[4]),
                volume=float(row[5]) if len(row) > 5 and row[5] is not None else 0.0
            )
            candles.append(candle)
        
        return candles
    except Exception as e:
        import logging
        logger = logging.getLogger("liquidity_map.data_loader")
        logger.exception("Error loading OHLCV for %s %s: %s", symbol, tf, e)
        return []


def load_ohlcv_as_dataframe(symbol: str, tf: str, db: DB, n_bars: int = 500) -> pd.DataFrame:
    """
    Загрузить OHLCV данные как pandas DataFrame.
    
    Args:
        symbol: Символ
        tf: Таймфрейм
        db: Экземпляр базы данных
        n_bars: Количество последних баров
    
    Returns:
        DataFrame с колонками: timestamp, open, high, low, close, volume
    """
    candles = load_ohlcv(symbol, tf, db, n_bars)
    if not candles:
        return pd.DataFrame()
    
    data = {
        'timestamp': [c.timestamp for c in candles],
        'open': [c.open for c in candles],
        'high': [c.high for c in candles],
        'low': [c.low for c in candles],
        'close': [c.close for c in candles],
        'volume': [c.volume for c in candles],
    }
    return pd.DataFrame(data)





