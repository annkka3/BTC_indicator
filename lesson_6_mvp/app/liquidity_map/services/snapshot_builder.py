# app/liquidity_map/services/snapshot_builder.py
"""
Построитель снимков состояния таймфрейма.
"""
from datetime import datetime
from ..domain.models import TimeframeSnapshot
from .data_loader import load_ohlcv_as_dataframe
from .zone_detector import detect_volume_zones, enrich_zones_with_reactions, classify_zones
from .pressure_analyzer import compute_pressure
from .zone_classifier import classify_zone_roles
from ...infrastructure.db import DB


def build_tf_snapshot(symbol: str, tf: str, db: DB) -> TimeframeSnapshot:
    """
    Построить снимок состояния таймфрейма.
    
    Args:
        symbol: Символ (например, "BTC")
        tf: Таймфрейм (например, "5m", "15m", "1h", "4h", "1d")
        db: Экземпляр базы данных
    
    Returns:
        Снимок состояния таймфрейма
    """
    # Загружаем данные (для коротких ТФ берем меньше баров)
    n_bars = 200 if tf in ["5m", "15m"] else 500
    df = load_ohlcv_as_dataframe(symbol, tf, db, n_bars=n_bars)
    
    # Если нет данных, пробуем загрузить с меньшим количеством баров
    if df.empty and n_bars > 50:
        df = load_ohlcv_as_dataframe(symbol, tf, db, n_bars=50)
    
    if df.empty:
        # Возвращаем пустой снимок
        return TimeframeSnapshot(
            tf=tf,
            zones=[],
            buy_pressure=50.0,
            sell_pressure=50.0,
            bias="NEUTRAL",
            current_price=0.0,
            timestamp=datetime.utcnow()
        )
    
    # Добавляем tf в DataFrame для zone_detector
    df['tf'] = tf
    
    # Обнаруживаем зоны
    zones = detect_volume_zones(df)
    
    # Обогащаем зоны реакциями
    zones = enrich_zones_with_reactions(zones, df)
    
    # Классифицируем зоны
    zones = classify_zones(zones)
    
    # Вычисляем давление
    price_series = df['close'].tolist()
    pressure_stat = compute_pressure(zones, price_series)
    
    # Текущая цена
    current_price = float(df['close'].iloc[-1])
    
    snapshot = TimeframeSnapshot(
        tf=tf,
        zones=zones,
        buy_pressure=pressure_stat.buy_pressure,
        sell_pressure=pressure_stat.sell_pressure,
        bias=pressure_stat.bias,
        current_price=current_price,
        timestamp=datetime.utcnow()
    )
    
    return snapshot

