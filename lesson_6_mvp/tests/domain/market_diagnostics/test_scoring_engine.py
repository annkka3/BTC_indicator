# tests/domain/market_diagnostics/test_scoring_engine.py
"""
Юнит-тесты для ScoringEngine.
"""

import pytest
from unittest.mock import Mock
from app.domain.market_diagnostics.scoring_engine import (
    ScoringEngine,
    IndicatorGroup,
    MultiTFScore
)
from app.domain.market_diagnostics.analyzer import MarketDiagnostics, MarketPhase
from app.domain.market_diagnostics.features import TrendState, VolatilityState, LiquidityState
from app.domain.market_diagnostics.smc import SMCContext


@pytest.fixture
def scoring_engine():
    """Фикстура для ScoringEngine."""
    return ScoringEngine()


@pytest.fixture
def mock_diagnostics_bullish():
    """Мок диагностики с супер бычьими сигналами."""
    diag = Mock(spec=MarketDiagnostics)
    diag.symbol = "BTCUSDT"
    diag.timeframe = "1h"
    diag.phase = MarketPhase.EXPANSION_UP
    diag.trend = TrendState.BULLISH
    diag.volatility = VolatilityState.MEDIUM
    diag.liquidity = LiquidityState.HIGH
    diag.smc_context = Mock(spec=SMCContext)
    diag.smc_context.last_bos = None
    diag.smc_context.premium_zone_start = None
    diag.smc_context.discount_zone_end = None
    diag.smc_context.current_position = None
    diag.smc_context.fvgs = []
    diag.smc_context.liquidity_above = []
    diag.smc_context.liquidity_below = []
    
    # Супер бычьи индикаторы
    indicators = {
        'ema_20': 100,
        'ema_50': 95,
        'ema_200': 90,
        'rsi': 70,
        'macd': 5,
        'macd_signal': 2,
        'macd_histogram': 3,
        'bb_upper': 105,
        'bb_middle': 100,
        'bb_lower': 95,
        'atr': 2,
        'volume': 1000000,
        'obv': 5000000,
        'cmf': 0.3,
        'wt1': 60,
        'wt2': 55,
        'stc': 80,
        'adx': 35,
        'ichimoku_tenkan': 98,
        'ichimoku_kijun': 96,
        'ichimoku_senkou_a': 94,
        'ichimoku_senkou_b': 92,
        'current_price': 100
    }
    
    diag.extra_metrics = {'indicators': indicators}
    return diag


@pytest.fixture
def mock_diagnostics_bearish():
    """Мок диагностики с супер медвежьими сигналами."""
    diag = Mock(spec=MarketDiagnostics)
    diag.symbol = "BTCUSDT"
    diag.timeframe = "4h"
    diag.phase = MarketPhase.EXPANSION_DOWN
    diag.trend = TrendState.BEARISH
    diag.volatility = VolatilityState.MEDIUM
    diag.liquidity = LiquidityState.HIGH
    diag.smc_context = Mock(spec=SMCContext)
    diag.smc_context.last_bos = None
    diag.smc_context.premium_zone_start = None
    diag.smc_context.discount_zone_end = None
    diag.smc_context.current_position = None
    diag.smc_context.fvgs = []
    diag.smc_context.liquidity_above = []
    diag.smc_context.liquidity_below = []
    
    # Супер медвежьи индикаторы
    indicators = {
        'ema_20': 100,
        'ema_50': 105,
        'ema_200': 110,
        'rsi': 30,
        'macd': -5,
        'macd_signal': -2,
        'macd_histogram': -3,
        'bb_upper': 105,
        'bb_middle': 100,
        'bb_lower': 95,
        'atr': 2,
        'volume': 1000000,
        'obv': -5000000,
        'cmf': -0.3,
        'wt1': 40,
        'wt2': 45,
        'stc': 20,
        'adx': 35,
        'ichimoku_tenkan': 102,
        'ichimoku_kijun': 104,
        'ichimoku_senkou_a': 106,
        'ichimoku_senkou_b': 108,
        'current_price': 100
    }
    
    diag.extra_metrics = {'indicators': indicators}
    return diag


@pytest.fixture
def mock_diagnostics_conflicting():
    """Мок диагностики с конфликтующими сигналами."""
    diag = Mock(spec=MarketDiagnostics)
    diag.symbol = "BTCUSDT"
    diag.timeframe = "1h"
    diag.phase = MarketPhase.ACCUMULATION
    diag.trend = TrendState.NEUTRAL
    diag.volatility = VolatilityState.LOW
    diag.liquidity = LiquidityState.MEDIUM
    diag.smc_context = Mock(spec=SMCContext)
    diag.smc_context.last_bos = None
    diag.smc_context.premium_zone_start = None
    diag.smc_context.discount_zone_end = None
    diag.smc_context.current_position = None
    diag.smc_context.fvgs = []
    diag.smc_context.liquidity_above = []
    diag.smc_context.liquidity_below = []
    
    # Смешанные индикаторы
    indicators = {
        'ema_20': 100,
        'ema_50': 100,
        'ema_200': 100,
        'rsi': 50,
        'macd': 0.1,
        'macd_signal': 0,
        'macd_histogram': 0.1,
        'bb_upper': 102,
        'bb_middle': 100,
        'bb_lower': 98,
        'atr': 1,
        'volume': 500000,
        'obv': 0,
        'cmf': 0,
        'wt1': 50,
        'wt2': 50,
        'stc': 50,
        'adx': 15,
        'ichimoku_tenkan': 100,
        'ichimoku_kijun': 100,
        'ichimoku_senkou_a': 100,
        'ichimoku_senkou_b': 100,
        'current_price': 100
    }
    
    diag.extra_metrics = {'indicators': indicators}
    return diag


def test_score_timeframe_super_bullish(scoring_engine, mock_diagnostics_bullish):
    """Тест: супер бычьи сигналы должны давать положительный long score."""
    score = scoring_engine.score_timeframe(mock_diagnostics_bullish, {}, {}, {}, "1h", target_tf="1h")
    
    assert score is not None
    # С бычьими сигналами long score должен быть выше short
    assert score.normalized_long > score.normalized_short, f"Expected normalized_long > normalized_short, got long={score.normalized_long}, short={score.normalized_short}"
    assert score.net_score > 0, f"Expected net_score > 0, got {score.net_score}"


def test_score_timeframe_super_bearish(scoring_engine, mock_diagnostics_bearish):
    """Тест: супер медвежьи сигналы должны давать положительный short score."""
    score = scoring_engine.score_timeframe(mock_diagnostics_bearish, {}, {}, {}, "1h", target_tf="1h")
    
    assert score is not None
    # С медвежьими сигналами short score должен быть выше long
    assert score.normalized_short > score.normalized_long, f"Expected normalized_short > normalized_long, got short={score.normalized_short}, long={score.normalized_long}"
    assert score.net_score < 0, f"Expected net_score < 0, got {score.net_score}"


def test_score_timeframe_conflicting_signals(scoring_engine, mock_diagnostics_conflicting):
    """Тест: конфликтующие сигналы должны давать нейтральный score."""
    score = scoring_engine.score_timeframe(mock_diagnostics_conflicting, {}, {}, {}, "1h", target_tf="1h")
    
    assert score is not None
    # Score должен быть близок к нейтральному (5.0)
    assert 4.0 <= score.normalized_long <= 6.0, f"Expected normalized_long between 4.0-6.0, got {score.normalized_long}"
    assert 4.0 <= score.normalized_short <= 6.0, f"Expected normalized_short between 4.0-6.0, got {score.normalized_short}"
    assert abs(score.net_score) < 1.0, f"Expected abs(net_score) < 1.0, got {score.net_score}"


def test_aggregate_multi_tf(scoring_engine, mock_diagnostics_bullish, mock_diagnostics_bearish):
    """Тест: агрегация multi-TF scores."""
    per_tf_scores = {
        "1h": scoring_engine.score_timeframe(mock_diagnostics_bullish, {}, {}, {}, "1h", target_tf="1h"),
        "4h": scoring_engine.score_timeframe(mock_diagnostics_bearish, {}, {}, {}, "4h", target_tf="1h")
    }
    
    multi_score = scoring_engine.aggregate_multi_tf(per_tf_scores, "1h")
    
    assert multi_score is not None
    assert multi_score.target_tf == "1h"
    assert len(multi_score.per_tf) == 2
    assert "1h" in multi_score.per_tf
    assert "4h" in multi_score.per_tf
    # Confidence должен быть понижен из-за конфликта
    assert multi_score.confidence < 0.8, f"Expected confidence < 0.8 due to conflict, got {multi_score.confidence}"


def test_normalization_range(scoring_engine, mock_diagnostics_bullish):
    """Тест: нормализованные scores должны быть в диапазоне [0, 10]."""
    score = scoring_engine.score_timeframe(mock_diagnostics_bullish, {}, {}, {}, "1h", target_tf="1h")
    
    assert 0 <= score.normalized_long <= 10, f"normalized_long out of range: {score.normalized_long}"
    assert 0 <= score.normalized_short <= 10, f"normalized_short out of range: {score.normalized_short}"


def test_group_scores_present(scoring_engine, mock_diagnostics_bullish):
    """Тест: все группы индикаторов должны присутствовать."""
    score = scoring_engine.score_timeframe(mock_diagnostics_bullish, {}, {}, {}, "1h", target_tf="1h")
    
    expected_groups = [
        IndicatorGroup.TREND,
        IndicatorGroup.MOMENTUM,
        IndicatorGroup.VOLUME,
        IndicatorGroup.VOLATILITY,
        IndicatorGroup.STRUCTURE
    ]
    
    for group in expected_groups:
        assert group in score.group_scores, f"Group {group} missing from group_scores"
        assert score.group_scores[group].raw_score is not None
        assert isinstance(score.group_scores[group].raw_score, (int, float))

