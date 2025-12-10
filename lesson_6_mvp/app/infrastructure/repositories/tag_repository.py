# app/infrastructure/repositories/tag_repository.py
"""
Repository for Market Doctor tags/labels.
"""

from typing import List, Optional
from datetime import datetime
from .base_repository import BaseRepository


class TagRepository(BaseRepository):
    """Репозиторий для работы с тегами Market Doctor."""
    
    def _ensure_table(self):
        """Создать таблицу тегов, если её нет."""
        cur = self.db.conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS md_tags (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                symbol TEXT NOT NULL,
                timeframe TEXT,
                tag TEXT NOT NULL,
                comment TEXT,
                created_at INTEGER DEFAULT (strftime('%s', 'now') * 1000),
                snapshot_id INTEGER,
                FOREIGN KEY (snapshot_id) REFERENCES market_diagnostics(id)
            )
        """)
        
        # Индексы
        cur.execute("CREATE INDEX IF NOT EXISTS idx_md_tags_user_symbol ON md_tags(user_id, symbol)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_md_tags_symbol ON md_tags(symbol)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_md_tags_tag ON md_tags(tag)")
        
        self.db.conn.commit()
    
    def add_tag(
        self,
        user_id: int,
        symbol: str,
        tag: str,
        timeframe: Optional[str] = None,
        comment: Optional[str] = None,
        snapshot_id: Optional[int] = None
    ) -> int:
        """
        Добавить тег к символу.
        
        Args:
            user_id: ID пользователя
            symbol: Символ монеты
            tag: Тег (good_entry, fakeout, overhyped и т.д.)
            timeframe: Таймфрейм (опционально)
            comment: Комментарий (опционально)
            snapshot_id: ID снимка диагностики (опционально)
        
        Returns:
            ID созданной записи
        """
        self._ensure_table()
        cur = self.db.conn.cursor()
        
        cur.execute("""
            INSERT INTO md_tags (user_id, symbol, timeframe, tag, comment, snapshot_id)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (user_id, symbol.upper(), timeframe, tag.lower(), comment, snapshot_id))
        
        self.db.conn.commit()
        return cur.lastrowid
    
    def get_tags(
        self,
        symbol: Optional[str] = None,
        user_id: Optional[int] = None,
        tag: Optional[str] = None
    ) -> List[dict]:
        """
        Получить теги.
        
        Args:
            symbol: Фильтр по символу (опционально)
            user_id: Фильтр по пользователю (опционально)
            tag: Фильтр по тегу (опционально)
        
        Returns:
            Список тегов
        """
        self._ensure_table()
        cur = self.db.conn.cursor()
        
        conditions = []
        params = []
        
        if symbol:
            conditions.append("symbol = ?")
            params.append(symbol.upper())
        
        if user_id:
            conditions.append("user_id = ?")
            params.append(user_id)
        
        if tag:
            conditions.append("tag = ?")
            params.append(tag.lower())
        
        where_clause = " AND ".join(conditions) if conditions else "1=1"
        
        cur.execute(f"""
            SELECT id, user_id, symbol, timeframe, tag, comment, created_at, snapshot_id
            FROM md_tags
            WHERE {where_clause}
            ORDER BY created_at DESC
        """, params)
        
        rows = cur.fetchall()
        return [
            {
                "id": row[0],
                "user_id": row[1],
                "symbol": row[2],
                "timeframe": row[3],
                "tag": row[4],
                "comment": row[5],
                "created_at": row[6],
                "snapshot_id": row[7]
            }
            for row in rows
        ]
    
    def remove_tag(self, tag_id: int, user_id: int) -> bool:
        """
        Удалить тег.
        
        Args:
            tag_id: ID тега
            user_id: ID пользователя (для проверки прав)
        
        Returns:
            True если удалено, False если не найдено
        """
        self._ensure_table()
        cur = self.db.conn.cursor()
        
        cur.execute("""
            DELETE FROM md_tags
            WHERE id = ? AND user_id = ?
        """, (tag_id, user_id))
        
        self.db.conn.commit()
        return cur.rowcount > 0






