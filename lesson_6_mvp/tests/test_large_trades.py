#!/usr/bin/env python3
"""Быстрый тест для проверки крупных сделок с разных бирж."""

import sys
import logging
from app.infrastructure.free_market_data import get_large_trades_aggregated

logging.basicConfig(
    level=logging.DEBUG,
    format='%(levelname)s: %(name)s: %(message)s'
)

# Устанавливаем уровень логирования только для нужных модулей
logging.getLogger("alt_forecast.free_market_data").setLevel(logging.DEBUG)
logging.getLogger("alt_forecast.twap_detector").setLevel(logging.DEBUG)

print("Тестируем get_large_trades_aggregated для BTC (1h)...")
print("="*80)

results = get_large_trades_aggregated(
    'BTC',
    ['binance', 'okx', 'bybit', 'gate'],
    '1h',
    100_000.0,
    db=None
)

print(f'\n=== РЕЗУЛЬТАТЫ ===')
for exchange, trades in results.items():
    print(f'\n{exchange.upper()}: {len(trades)} крупных сделок')
    if trades:
        total_volume = sum(t.usd_value for t in trades)
        buy_volume = sum(t.usd_value for t in trades if t.side == "buy")
        sell_volume = sum(t.usd_value for t in trades if t.side == "sell")
        print(f'  Общий объем: ${total_volume/1_000_000:.2f}M')
        print(f'  Buy: ${buy_volume/1_000_000:.2f}M, Sell: ${sell_volume/1_000_000:.2f}M')
        print(f'  Топ-3 сделки:')
        for i, t in enumerate(trades[:3], 1):
            print(f'    {i}. ${t.usd_value:,.2f} @ ${t.price:,.2f}')

if not results:
    print("\n⚠ Нет данных ни с одной биржи!")


