# app/domain/interfaces/idiagnostics_repository.py
"""
Интерфейс для репозитория диагностик Market Doctor.

Определяет контракт для работы с диагностиками без привязки к конкретной реализации.
"""

from typing import Protocol, List, Optional, Dict, Any
from dataclasses import dataclass


@dataclass
class DiagnosticsSnapshot:
    """Снимок диагностики для сохранения."""
    timestamp: int  # Unix timestamp в миллисекундах
    symbol: str
    timeframe: str
    phase: str
    trend: str
    volatility: str
    liquidity: str
    structure: str
    pump_score: float
    risk_score: float
    close_price: float
    strategy_mode: str
    # Дополнительные метрики (опционально)
    extra_metrics: Optional[Dict[str, Any]] = None
    # Pattern ID для reliability analysis
    pattern_id: Optional[str] = None
    # Reliability score паттерна (0.0 - 1.0)
    reliability_score: Optional[float] = None


class IDiagnosticsRepository(Protocol):
    """
    Интерфейс для репозитория диагностик.
    
    Использует Protocol для утиной типизации - любой объект с этими методами
    будет считаться реализацией интерфейса.
    """
    
    def get_snapshots(
        self,
        symbol: Optional[str] = None,
        timeframe: Optional[str] = None,
        limit: Optional[int] = None,
        since_ms: Optional[int] = None,
        until_ms: Optional[int] = None
    ) -> List[DiagnosticsSnapshot]:
        """
        Получить снимки диагностик.
        
        Args:
            symbol: Фильтр по символу (если None, все символы)
            timeframe: Фильтр по таймфрейму (если None, все таймфреймы)
            limit: Максимальное количество записей
            since_ms: Начало временного диапазона (Unix timestamp в миллисекундах)
            until_ms: Конец временного диапазона (Unix timestamp в миллисекундах)
        
        Returns:
            Список снимков диагностик
        """
        ...
    
    def save_snapshot(self, snapshot: DiagnosticsSnapshot) -> int:
        """
        Сохранить снимок диагностики.
        
        Args:
            snapshot: Снимок диагностики
        
        Returns:
            ID сохраненной записи
        """
        ...

