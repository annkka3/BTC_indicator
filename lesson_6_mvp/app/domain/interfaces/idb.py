# app/domain/interfaces/idb.py
"""
Интерфейс для работы с базой данных.

Определяет контракт для работы с БД без привязки к конкретной реализации.
"""

from abc import ABC, abstractmethod
from typing import Any, Protocol


class IDatabase(Protocol):
    """
    Интерфейс для работы с базой данных.
    
    Использует Protocol для утиной типизации - любой объект с этими атрибутами
    будет считаться реализацией интерфейса.
    """
    
    @property
    @abstractmethod
    def conn(self) -> Any:
        """
        Соединение с базой данных.
        
        Returns:
            Объект соединения (например, sqlite3.Connection)
        """
        pass
    
    @property
    @abstractmethod
    def path(self) -> str:
        """
        Путь к файлу базы данных.
        
        Returns:
            Путь к файлу БД
        """
        pass

