# app/domain/interfaces/__init__.py
"""
Интерфейсы для работы с внешними зависимостями.

Эти интерфейсы определяют контракты для работы с БД и внешними сервисами,
не нарушая принципы Clean Architecture (Dependency Rule).
"""

from .idb import IDatabase
from .idiagnostics_repository import IDiagnosticsRepository
from .imarket_data_service import IMarketDataService

__all__ = [
    "IDatabase",
    "IDiagnosticsRepository",
    "IMarketDataService",
]

