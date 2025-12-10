# app/liquidity_map/application/generate_liquidity_report.py
"""
Генерация текстового отчета Liquidity Intelligence.
"""
from typing import List
from ..services.snapshot_builder import build_tf_snapshot
from ..services.report_builder import build_text_report
from ...infrastructure.db import DB


def generate_liquidity_report(symbol: str, db: DB) -> str:
    """
    Сгенерировать текстовый отчет Liquidity Intelligence для символа.
    
    Args:
        symbol: Символ (например, "BTC")
        db: Экземпляр базы данных
    
    Returns:
        Текстовый отчет в формате HTML
    """
    # Таймфреймы согласно спецификации
    timeframes = ["5m", "15m", "1h", "4h", "1d"]
    
    # Строим снимки для каждого таймфрейма
    snapshots = []
    for tf in timeframes:
        snapshot = build_tf_snapshot(symbol, tf, db)
        snapshots.append(snapshot)
    
    # Классифицируем роли зон (нужна текущая цена)
    current_price = 0.0
    for snapshot in snapshots:
        if snapshot.current_price > 0:
            current_price = snapshot.current_price
            break
    
    if current_price > 0:
        from ..services.zone_classifier import classify_zone_roles
        classify_zone_roles(snapshots, current_price)
    
    # Строим отчет
    return build_text_report(snapshots, symbol)


