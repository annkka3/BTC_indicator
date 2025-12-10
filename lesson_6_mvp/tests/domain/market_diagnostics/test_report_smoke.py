# tests/domain/market_diagnostics/test_report_smoke.py
"""
Смоук-тесты для отчётов Market Doctor.
Проверяют, что отчёты не падают и выглядят корректно при различных сценариях.
"""

import pytest
from unittest.mock import Mock, MagicMock
from app.domain.market_diagnostics.report_builder import ReportBuilder
from app.domain.market_diagnostics.compact_report import CompactReportRenderer
from app.domain.market_diagnostics.analyzer import MarketDiagnostics, MarketPhase
from app.domain.market_diagnostics.features import TrendState, VolatilityState, LiquidityState
from app.domain.market_diagnostics.smc import SMCContext
from app.domain.market_diagnostics.trade_planner import TradePlan


@pytest.fixture
def report_builder():
    """Фикстура для ReportBuilder."""
    return ReportBuilder()


@pytest.fixture
def report_renderer():
    """Фикстура для CompactReportRenderer."""
    return CompactReportRenderer(language="ru")


@pytest.fixture
def minimal_diagnostics():
    """Минимальная диагностика с обязательными полями."""
    diag = Mock(spec=MarketDiagnostics)
    diag.symbol = "BTCUSDT"
    diag.timeframe = "1h"
    diag.phase = MarketPhase.ACCUMULATION
    diag.trend = TrendState.NEUTRAL
    diag.volatility = VolatilityState.MEDIUM
    diag.liquidity = LiquidityState.MEDIUM
    diag.risk_score = 0.5
    diag.pump_score = 0.5
    diag.confidence = 0.5
    diag.key_levels = []
    diag.smc_context = None
    diag.extra_metrics = {'indicators': {}}
    return diag


@pytest.fixture
def empty_smc_diagnostics():
    """Диагностика с пустым SMC контекстом."""
    diag = Mock(spec=MarketDiagnostics)
    diag.symbol = "ETHUSDT"
    diag.timeframe = "1h"
    diag.phase = MarketPhase.DISTRIBUTION
    diag.trend = TrendState.BEARISH
    diag.volatility = VolatilityState.HIGH
    diag.liquidity = LiquidityState.LOW
    diag.risk_score = 0.7
    diag.pump_score = 0.3
    diag.confidence = 0.4
    diag.key_levels = []
    
    # Пустой SMC контекст
    smc = Mock(spec=SMCContext)
    smc.last_bos = None
    smc.last_choch = None
    smc.liquidity_above = []
    smc.liquidity_below = []
    smc.order_blocks_demand = []
    smc.order_blocks_supply = []
    smc.fvgs = []
    smc.premium_zone_start = None
    smc.discount_zone_end = None
    smc.current_position = None
    
    diag.smc_context = smc
    diag.extra_metrics = {'indicators': {}}
    return diag


def test_single_tf_report_minimal(report_builder, minimal_diagnostics):
    """Тест: single-TF отчёт с минимальными данными не должен падать."""
    diagnostics = {"1h": minimal_diagnostics}
    
    try:
        report = report_builder.build_compact_report(
            symbol="BTCUSDT",
            target_tf="1h",
            diagnostics=diagnostics,
            indicators={},
            features={},
            derivatives={},
            current_price=50000.0
        )
        
        assert report is not None
        assert report.symbol == "BTCUSDT"
        assert report.target_tf == "1h"
        assert report.direction in ["LONG", "SHORT"]
        assert 0 <= report.score_long <= 10
        assert 0 <= report.score_short <= 10
        assert 0 <= report.confidence <= 1
        assert report.tl_dr is not None
        assert len(report.tl_dr) > 0
    except Exception as e:
        pytest.fail(f"Report building failed with minimal data: {e}")


def test_single_tf_report_empty_smc(report_builder, empty_smc_diagnostics):
    """Тест: single-TF отчёт с пустым SMC не должен падать."""
    diagnostics = {"1h": empty_smc_diagnostics}
    
    try:
        report = report_builder.build_compact_report(
            symbol="ETHUSDT",
            target_tf="1h",
            diagnostics=diagnostics,
            indicators={},
            features={},
            derivatives={},
            current_price=3000.0
        )
        
        assert report is not None
        assert report.smc is not None
        # SMC данные должны быть пустыми, но структура должна существовать
        assert "levels" in report.smc
    except Exception as e:
        pytest.fail(f"Report building failed with empty SMC: {e}")


def test_multi_tf_report(report_builder, minimal_diagnostics):
    """Тест: multi-TF отчёт не должен падать."""
    diagnostics = {
        "1h": minimal_diagnostics,
        "4h": minimal_diagnostics,
        "1d": minimal_diagnostics
    }
    
    try:
        report = report_builder.build_compact_report(
            symbol="BTCUSDT",
            target_tf="1h",
            diagnostics=diagnostics,
            indicators={},
            features={},
            derivatives={},
            current_price=50000.0
        )
        
        assert report is not None
        assert len(report.per_tf) >= 1
        # Multi-TF отчёт должен содержать данные по нескольким ТФ
        assert "1h" in report.per_tf
    except Exception as e:
        pytest.fail(f"Multi-TF report building failed: {e}")


def test_report_rendering_no_placeholders(report_builder, report_renderer, minimal_diagnostics):
    """Тест: отрендеренный отчёт не должен содержать Placeholder/None."""
    diagnostics = {"1h": minimal_diagnostics}
    
    report = report_builder.build_compact_report(
        symbol="BTCUSDT",
        target_tf="1h",
        diagnostics=diagnostics,
        indicators={},
        features={},
        derivatives={},
        current_price=50000.0
    )
    
    try:
        rendered = report_renderer.render(report)
        
        assert rendered is not None
        assert len(rendered) > 0
        
        # Проверяем отсутствие явных заглушек
        assert "None" not in rendered, "Report contains 'None' placeholder"
        assert "Placeholder" not in rendered, "Report contains 'Placeholder' text"
        assert "N/A" not in rendered or rendered.count("N/A") < 3, "Too many 'N/A' placeholders"
    except Exception as e:
        pytest.fail(f"Report rendering failed: {e}")


def test_report_compact_format(report_builder, report_renderer, minimal_diagnostics):
    """Тест: отчёт должен быть компактным и структурированным."""
    diagnostics = {"1h": minimal_diagnostics}
    
    report = report_builder.build_compact_report(
        symbol="BTCUSDT",
        target_tf="1h",
        diagnostics=diagnostics,
        indicators={},
        features={},
        derivatives={},
        current_price=50000.0
    )
    
    rendered = report_renderer.render(report)
    
    # Проверяем наличие ключевых секций
    assert "Market Doctor" in rendered or "🏥" in rendered
    assert "TL;DR" in rendered or "📋" in rendered
    assert "Структура рынка" in rendered or "SMC" in rendered
    
    # Отчёт не должен быть слишком длинным (примерно до 2000 символов для компактного формата)
    assert len(rendered) < 5000, f"Report too long: {len(rendered)} characters"


def test_report_with_missing_trade_plan(report_builder, minimal_diagnostics):
    """Тест: отчёт должен работать без TradePlan."""
    diagnostics = {"1h": minimal_diagnostics}
    
    try:
        report = report_builder.build_compact_report(
            symbol="BTCUSDT",
            target_tf="1h",
            diagnostics=diagnostics,
            indicators={},
            features={},
            derivatives={},
            current_price=50000.0,
            trade_plan=None
        )
        
        assert report is not None
        assert report.trade_map is not None
        # Trade map должен иметь значения по умолчанию
        assert "bias" in report.trade_map
    except Exception as e:
        pytest.fail(f"Report building failed without TradePlan: {e}")


def test_report_setup_type_present(report_builder, minimal_diagnostics):
    """Тест: отчёт должен содержать тип сетапа."""
    diagnostics = {"1h": minimal_diagnostics}
    
    report = report_builder.build_compact_report(
        symbol="BTCUSDT",
        target_tf="1h",
        diagnostics=diagnostics,
        indicators={},
        features={},
        derivatives={},
        current_price=50000.0
    )
    
    assert report.setup_type is not None
    assert report.setup_type != ""
    assert report.setup_description is not None
    assert len(report.setup_description) > 0




