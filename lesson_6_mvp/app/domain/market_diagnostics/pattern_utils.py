# app/domain/market_diagnostics/pattern_utils.py
"""
Утилиты для работы с паттернами Market Doctor.
"""

import hashlib
from typing import Optional
from .analyzer import MarketPhase, MarketDiagnostics
from .features import TrendState
from ..market_regime import GlobalRegime


def generate_pattern_id(
    phase: MarketPhase,
    trend: TrendState,
    structure: str,
    regime: Optional[GlobalRegime] = None
) -> str:
    """
    Сгенерировать pattern_id на основе характеристик паттерна.
    
    Args:
        phase: Фаза рынка
        trend: Тренд
        structure: Структура рынка
        regime: Глобальный режим (опционально)
    
    Returns:
        Hash строку pattern_id
    """
    pattern_string = f"{phase.value}_{trend.value}_{structure}"
    if regime:
        pattern_string += f"_{regime.value}"
    
    # Используем MD5 для создания короткого hash
    pattern_id = hashlib.md5(pattern_string.encode()).hexdigest()[:16]
    return pattern_id


