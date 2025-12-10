# app/domain/twap_detector/__init__.py
"""
Модуль для детекции TWAP-алгоритмов на нескольких биржах.
"""

from .exchange_client import (
    ExchangeClient,
    BinanceClient,
    BybitClient,
    OKXClient,
    GateClient,
    get_exchange_clients,
)
from .pattern_analyzer import (
    TWAPPatternAnalyzer,
    ExchangeAnalysis,
)
from .aggregator import (
    TWAPDetector,
    TWAPReport,
)

__all__ = [
    "ExchangeClient",
    "BinanceClient",
    "BybitClient",
    "OKXClient",
    "GateClient",
    "get_exchange_clients",
    "TWAPPatternAnalyzer",
    "ExchangeAnalysis",
    "TWAPDetector",
    "TWAPReport",
]


