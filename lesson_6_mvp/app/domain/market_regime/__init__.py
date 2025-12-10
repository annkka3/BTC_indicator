# app/domain/market_regime/__init__.py
"""
Market Regime domain module.

Анализ глобального режима рынка криптовалют.
"""

from .global_regime_analyzer import GlobalRegimeAnalyzer, GlobalRegime, RegimeSnapshot

__all__ = [
    "GlobalRegimeAnalyzer",
    "GlobalRegime",
    "RegimeSnapshot",
]


