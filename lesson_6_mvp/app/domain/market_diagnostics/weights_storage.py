# app/domain/market_diagnostics/weights_storage.py
"""
Хранилище весов групп индикаторов для Market Doctor.

Позволяет сохранять и загружать кастомные веса групп из БД.
"""

from typing import Dict, Optional, TYPE_CHECKING
import json

if TYPE_CHECKING:
    from ...domain.interfaces.idb import IDatabase
else:
    IDatabase = object  # Для runtime

from .scoring_engine import IndicatorGroup, GROUP_WEIGHTS


class WeightsStorage:
    """Хранилище весов групп индикаторов."""
    
    def __init__(self, db: IDatabase):
        """
        Args:
            db: Database instance (реализует IDatabase интерфейс)
        """
        self.db = db
        self._init_table()
    
    def _init_table(self):
        """Инициализировать таблицу для хранения весов."""
        cur = self.db.conn.cursor()
        cur.executescript("""
            CREATE TABLE IF NOT EXISTS scoring_weights (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,  -- Имя конфигурации (например, "default", "calibrated")
                weights TEXT NOT NULL,      -- JSON с весами групп
                description TEXT,           -- Описание конфигурации
                created_at_ms INTEGER NOT NULL,
                is_active INTEGER DEFAULT 0, -- Только одна конфигурация может быть активной
                UNIQUE(name)
            );
            
            CREATE INDEX IF NOT EXISTS idx_scoring_weights_active 
                ON scoring_weights(is_active);
        """)
        
        # Создаём дефолтную конфигурацию, если её нет
        cur.execute("SELECT COUNT(*) FROM scoring_weights WHERE name = 'default'")
        if cur.fetchone()[0] == 0:
            default_weights = {
                group.value: weight for group, weight in GROUP_WEIGHTS.items()
            }
            import time
            cur.execute("""
                INSERT INTO scoring_weights (name, weights, description, created_at_ms, is_active)
                VALUES (?, ?, ?, ?, ?)
            """, (
                "default",
                json.dumps(default_weights),
                "Дефолтные веса групп индикаторов",
                int(time.time() * 1000),
                1
            ))
        
        self.db.conn.commit()
    
    def save_weights(
        self,
        name: str,
        weights: Dict[IndicatorGroup, float],
        description: Optional[str] = None,
        set_active: bool = False
    ) -> int:
        """
        Сохранить веса групп.
        
        Args:
            name: Имя конфигурации
            weights: Словарь {IndicatorGroup: weight}
            description: Описание конфигурации
            set_active: Установить как активную конфигурацию
        
        Returns:
            ID сохранённой конфигурации
        """
        cur = self.db.conn.cursor()
        
        # Если устанавливаем как активную, деактивируем остальные
        if set_active:
            cur.execute("UPDATE scoring_weights SET is_active = 0")
        
        # Преобразуем IndicatorGroup в строки для JSON
        weights_dict = {
            group.value if isinstance(group, IndicatorGroup) else str(group): weight
            for group, weight in weights.items()
        }
        
        import time
        cur.execute("""
            INSERT OR REPLACE INTO scoring_weights (name, weights, description, created_at_ms, is_active)
            VALUES (?, ?, ?, ?, ?)
        """, (
            name,
            json.dumps(weights_dict),
            description or f"Конфигурация весов {name}",
            int(time.time() * 1000),
            1 if set_active else 0
        ))
        
        self.db.conn.commit()
        return cur.lastrowid
    
    def load_weights(self, name: Optional[str] = None) -> Optional[Dict[IndicatorGroup, float]]:
        """
        Загрузить веса групп.
        
        Args:
            name: Имя конфигурации (если None, загружает активную)
        
        Returns:
            Словарь {IndicatorGroup: weight} или None
        """
        cur = self.db.conn.cursor()
        
        if name:
            cur.execute("SELECT weights FROM scoring_weights WHERE name = ?", (name,))
        else:
            cur.execute("SELECT weights FROM scoring_weights WHERE is_active = 1 LIMIT 1")
        
        row = cur.fetchone()
        if not row:
            return None
        
        weights_dict = json.loads(row[0])
        
        # Преобразуем строки обратно в IndicatorGroup
        result = {}
        for group_str, weight in weights_dict.items():
            try:
                group = IndicatorGroup(group_str)
                result[group] = weight
            except ValueError:
                # Если не удалось распарсить, пропускаем
                continue
        
        return result
    
    def get_active_weights(self) -> Dict[IndicatorGroup, float]:
        """
        Получить активные веса (или дефолтные, если активных нет).
        
        Returns:
            Словарь {IndicatorGroup: weight}
        """
        weights = self.load_weights()
        if weights:
            return weights
        
        # Возвращаем дефолтные веса
        return GROUP_WEIGHTS.copy()
    
    def list_configurations(self) -> list[Dict]:
        """
        Получить список всех конфигураций.
        
        Returns:
            Список словарей с информацией о конфигурациях
        """
        cur = self.db.conn.cursor()
        cur.execute("""
            SELECT id, name, description, created_at_ms, is_active
            FROM scoring_weights
            ORDER BY created_at_ms DESC
        """)
        
        rows = cur.fetchall()
        return [
            {
                'id': row[0],
                'name': row[1],
                'description': row[2],
                'created_at_ms': row[3],
                'is_active': bool(row[4])
            }
            for row in rows
        ]
    
    def set_active(self, name: str) -> bool:
        """
        Установить конфигурацию как активную.
        
        Args:
            name: Имя конфигурации
        
        Returns:
            True если успешно, False если конфигурация не найдена
        """
        cur = self.db.conn.cursor()
        
        # Деактивируем все
        cur.execute("UPDATE scoring_weights SET is_active = 0")
        
        # Активируем указанную
        cur.execute("UPDATE scoring_weights SET is_active = 1 WHERE name = ?", (name,))
        self.db.conn.commit()
        
        return cur.rowcount > 0



