# app/domain/models.py
from __future__ import annotations
from dataclasses import dataclass
from typing import Literal, Tuple, Iterable

# --- Типы и алиасы ---

Metric = Literal["BTC", "USDT.D", "BTC.D", "TOTAL2", "TOTAL3", "ETHBTC"]
Timeframe = Literal["15m", "1h", "4h", "1d"]
Implication = Literal["bullish_alts", "bearish_alts", "neutral"]
DIRECTION = Literal["up", "down", "flat"]

# --- Константы (оставлены как были для совместимости) ---

METRICS: Tuple[Metric, ...] = ("BTC", "USDT.D", "BTC.D", "TOTAL2", "TOTAL3", "ETHBTC")
TIMEFRAMES: Tuple[Timeframe, ...] = ("15m", "1h", "4h", "1d")

METRICS_SET = set(METRICS)
TIMEFRAMES_SET = set(TIMEFRAMES)

# --- Модели данных ---

@dataclass(frozen=True, slots=True)
class Bar:
    """OHLCV-бар. ts — unix ms close time."""
    metric: Metric
    timeframe: Timeframe
    ts: int
    o: float
    h: float
    l: float
    c: float
    v: float | None = None

@dataclass(frozen=True, slots=True)
class Divergence:
    """Сигнал дивергенции для отчётов и логики risk-score."""
    timeframe: Timeframe
    metric: Metric | None
    indicator: str  # "RSI", "MACD", "VOLUME", "PAIR"
    text: str
    implication: Implication

# --- Маппинги импликаций для альтов ---

# Как изменение метрики трактуется для альткоинов:
# up → bullish_alts / bearish_alts / neutral
IMPLICATION_BY_METRIC_AND_DIR: dict[Metric, dict[DIRECTION, Implication]] = {
    "USDT.D": {"up": "bearish_alts", "down": "bullish_alts", "flat": "neutral"},
    "BTC.D":  {"up": "bearish_alts", "down": "bullish_alts", "flat": "neutral"},
    "TOTAL2": {"up": "bullish_alts", "down": "bearish_alts", "flat": "neutral"},
    "TOTAL3": {"up": "bullish_alts", "down": "bearish_alts", "flat": "neutral"},
    "ETHBTC": {"up": "bullish_alts", "down": "bearish_alts", "flat": "neutral"},  # ETH (часто и альты) опережают BTC
    "BTC":    {"up": "neutral",      "down": "neutral",       "flat": "neutral"},
}

def implication_for_alts(metric: Metric, direction: DIRECTION) -> Implication:
    """Единая точка правды для текстов и визуала по влиянию на альты."""
    return IMPLICATION_BY_METRIC_AND_DIR.get(metric, {}).get(direction, "neutral")

def direction_from_delta(delta: float, eps: float = 1e-6) -> DIRECTION:
    """Нормализуем знак изменения к up/down/flat с небольшим порогом eps."""
    if delta > eps:
        return "up"
    if delta < -eps:
        return "down"
    return "flat"

__all__ = [
    "Metric", "Timeframe", "Implication", "DIRECTION",
    "METRICS", "TIMEFRAMES", "METRICS_SET", "TIMEFRAMES_SET",
    "Bar", "Divergence",
    "IMPLICATION_BY_METRIC_AND_DIR",
    "implication_for_alts", "direction_from_delta",
]
