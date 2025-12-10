# app/domain/interfaces/imarket_data_service.py
"""
Интерфейс для сервиса рыночных данных.

Определяет контракт для получения рыночных данных без привязки к конкретной реализации.
"""

from typing import Protocol, Optional, Dict, Any
import pandas as pd


class IMarketDataService(Protocol):
    """
    Интерфейс для сервиса рыночных данных.
    
    Использует Protocol для утиной типизации - любой объект с этими методами
    будет считаться реализацией интерфейса.
    """
    
    async def get_ohlcv(
        self,
        symbol: str,
        timeframe: str,
        limit: int = 500
    ) -> Optional[pd.DataFrame]:
        """
        Получить OHLCV данные.
        
        Args:
            symbol: Символ монеты
            timeframe: Таймфрейм (1h, 4h, 1d)
            limit: Количество баров
        
        Returns:
            DataFrame с OHLCV данными или None
        """
        ...
    
    async def get_derivatives(
        self,
        symbol: str
    ) -> Optional[Dict[str, Any]]:
        """
        Получить данные деривативов (funding, OI, CVD).
        
        Args:
            symbol: Символ монеты
        
        Returns:
            Словарь с данными деривативов или None
        """
        ...

