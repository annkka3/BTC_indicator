# app/infrastructure/repositories/base_repository.py
"""
Base repository class for data access.
"""

from abc import ABC
from typing import Optional
from ..db import DB


class BaseRepository(ABC):
    """Базовый класс для всех репозиториев."""
    
    def __init__(self, db: DB):
        """
        Args:
            db: Database instance
        """
        self.db = db

