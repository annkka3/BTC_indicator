# app/liquidity_map/application/generate_liquidity_report_compact.py
"""
Генерация компактного отчета Liquidity Intelligence (1-2 экрана).
"""
from typing import List
from ..services.snapshot_builder import build_tf_snapshot
from ..services.report_builder import build_compact_report
from ...infrastructure.db import DB


def generate_liquidity_report_compact(symbol: str, db: DB) -> str:
    """
    Сгенерировать компактный отчет Liquidity Intelligence для символа.
    
    Args:
        symbol: Символ (например, "BTC")
        db: Экземпляр базы данных
    
    Returns:
        Компактный отчет в формате HTML
    """
    # Таймфреймы согласно спецификации
    timeframes = ["5m", "15m", "1h", "4h", "1d"]
    
    # Строим снимки для каждого таймфрейма
    snapshots = []
    for tf in timeframes:
        snapshot = build_tf_snapshot(symbol, tf, db)
        snapshots.append(snapshot)
    
    # Строим компактный отчет
    return build_compact_report(snapshots, symbol)




