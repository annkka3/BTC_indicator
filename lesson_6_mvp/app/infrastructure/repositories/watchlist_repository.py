# app/infrastructure/repositories/watchlist_repository.py
"""
Репозиторий для работы с watchlist пользователей Market Doctor.
"""

from typing import List, Optional
from .base_repository import BaseRepository


class WatchlistRepository(BaseRepository):
    """Репозиторий для работы с watchlist тикеров."""
    
    def __init__(self, db):
        super().__init__(db)
        self._ensure_table()
    
    def _ensure_table(self):
        """Создать таблицу для watchlist, если её нет."""
        cur = self.db.conn.cursor()
        # Создаем таблицу
        cur.execute("""
            CREATE TABLE IF NOT EXISTS md_watchlist (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                symbol TEXT NOT NULL,
                added_at INTEGER DEFAULT (strftime('%s', 'now') * 1000),
                UNIQUE(user_id, symbol)
            )
        """)
        # Создаем индексы отдельно
        cur.execute("CREATE INDEX IF NOT EXISTS idx_md_watchlist_user ON md_watchlist(user_id)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_md_watchlist_symbol ON md_watchlist(symbol)")
        self.db.conn.commit()
    
    def add_symbol(self, user_id: int, symbol: str) -> bool:
        """
        Добавить символ в watchlist пользователя.
        
        Args:
            user_id: ID пользователя
            symbol: Символ для добавления
        
        Returns:
            True если добавлен, False если уже существует
        """
        cur = self.db.conn.cursor()
        try:
            cur.execute("""
                INSERT INTO md_watchlist (user_id, symbol)
                VALUES (?, ?)
            """, (user_id, symbol.upper()))
            self.db.conn.commit()
            return True
        except Exception:
            # Символ уже существует
            self.db.conn.rollback()
            return False
    
    def remove_symbol(self, user_id: int, symbol: str) -> bool:
        """
        Удалить символ из watchlist пользователя.
        
        Args:
            user_id: ID пользователя
            symbol: Символ для удаления
        
        Returns:
            True если удален, False если не найден
        """
        cur = self.db.conn.cursor()
        cur.execute("""
            DELETE FROM md_watchlist
            WHERE user_id = ? AND symbol = ?
        """, (user_id, symbol.upper()))
        self.db.conn.commit()
        return cur.rowcount > 0
    
    def get_user_watchlist(self, user_id: int) -> List[str]:
        """
        Получить список символов в watchlist пользователя.
        
        Args:
            user_id: ID пользователя
        
        Returns:
            Список символов
        """
        cur = self.db.conn.cursor()
        cur.execute("""
            SELECT symbol FROM md_watchlist
            WHERE user_id = ?
            ORDER BY added_at DESC
        """, (user_id,))
        return [row['symbol'] for row in cur.fetchall()]
    
    def is_in_watchlist(self, user_id: int, symbol: str) -> bool:
        """
        Проверить, есть ли символ в watchlist пользователя.
        
        Args:
            user_id: ID пользователя
            symbol: Символ для проверки
        
        Returns:
            True если есть, False если нет
        """
        cur = self.db.conn.cursor()
        cur.execute("""
            SELECT 1 FROM md_watchlist
            WHERE user_id = ? AND symbol = ?
            LIMIT 1
        """, (user_id, symbol.upper()))
        return cur.fetchone() is not None
    
    def get_all_watched_symbols(self) -> List[str]:
        """
        Получить список всех уникальных символов из всех watchlist.
        
        Returns:
            Список уникальных символов
        """
        cur = self.db.conn.cursor()
        cur.execute("""
            SELECT DISTINCT symbol FROM md_watchlist
            ORDER BY symbol
        """)
        return [row['symbol'] for row in cur.fetchall()]
    
    def get_users_watching_symbol(self, symbol: str) -> List[int]:
        """
        Получить список пользователей, которые следят за символом.
        
        Args:
            symbol: Символ
        
        Returns:
            Список user_id
        """
        cur = self.db.conn.cursor()
        cur.execute("""
            SELECT DISTINCT user_id FROM md_watchlist
            WHERE symbol = ?
        """, (symbol.upper(),))
        return [row['user_id'] for row in cur.fetchall()]

