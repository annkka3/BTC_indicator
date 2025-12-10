"""
Тесты для доменных моделей.
"""

import pytest
from app.domain.models import (
    Bar, Metric, Timeframe, Divergence, Implication, DIRECTION,
    implication_for_alts, direction_from_delta,
    METRICS, TIMEFRAMES
)


def test_bar_creation():
    """Тест создания бара."""
    bar = Bar(
        metric="BTC",
        timeframe="1h",
        ts=1704067200000,
        o=42000.0,
        h=42500.0,
        l=41800.0,
        c=42300.0,
        v=1000000.0
    )
    
    assert bar.metric == "BTC"
    assert bar.timeframe == "1h"
    assert bar.ts == 1704067200000
    assert bar.o == 42000.0
    assert bar.h == 42500.0
    assert bar.l == 41800.0
    assert bar.c == 42300.0
    assert bar.v == 1000000.0


def test_implication_for_alts():
    """Тест вычисления импликаций для альткоинов."""
    # USDT.D вверх → bearish для альтов
    assert implication_for_alts("USDT.D", "up") == "bearish_alts"
    
    # USDT.D вниз → bullish для альтов
    assert implication_for_alts("USDT.D", "down") == "bullish_alts"
    
    # TOTAL2 вверх → bullish для альтов
    assert implication_for_alts("TOTAL2", "up") == "bullish_alts"
    
    # BTC нейтрально
    assert implication_for_alts("BTC", "up") == "neutral"


def test_direction_from_delta():
    """Тест определения направления изменения."""
    assert direction_from_delta(0.01) == "up"
    assert direction_from_delta(-0.01) == "down"
    assert direction_from_delta(0.0) == "flat"
    assert direction_from_delta(1e-7) == "flat"  # Меньше eps


def test_metrics_constants():
    """Тест констант метрик."""
    assert "BTC" in METRICS
    assert "USDT.D" in METRICS
    assert "TOTAL2" in METRICS
    assert len(METRICS) == 6


def test_timeframes_constants():
    """Тест констант таймфреймов."""
    assert "15m" in TIMEFRAMES
    assert "1h" in TIMEFRAMES
    assert "4h" in TIMEFRAMES
    assert "1d" in TIMEFRAMES
    assert len(TIMEFRAMES) == 4


def test_divergence_creation():
    """Тест создания дивергенции."""
    div = Divergence(
        timeframe="1h",
        metric="BTC",
        indicator="RSI",
        text="Bullish RSI divergence",
        implication="bullish_alts"
    )
    
    assert div.timeframe == "1h"
    assert div.metric == "BTC"
    assert div.indicator == "RSI"
    assert div.implication == "bullish_alts"






