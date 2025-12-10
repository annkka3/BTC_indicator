# app/infrastructure/repositories/diagnostics_repository.py
"""
Репозиторий для сохранения и анализа диагностик Market Doctor.
"""

from datetime import datetime
from typing import Optional, List, Dict, Any
from dataclasses import dataclass
from ..db import DB
from .base_repository import BaseRepository


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
    # Pattern ID для reliability analysis (hash по phase+trend+structure+regime)
    pattern_id: Optional[str] = None
    # Reliability score паттерна (0.0 - 1.0)
    reliability_score: Optional[float] = None


class DiagnosticsRepository(BaseRepository):
    """Репозиторий для работы с диагностиками Market Doctor."""
    
    def __init__(self, db: DB):
        super().__init__(db)
        self._ensure_table()
    
    def _ensure_table(self):
        """Создать таблицу для диагностик, если её нет."""
        cur = self.db.conn.cursor()
        
        # Создаем таблицу
        cur.execute("""
            CREATE TABLE IF NOT EXISTS market_diagnostics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp INTEGER NOT NULL,
                symbol TEXT NOT NULL,
                timeframe TEXT NOT NULL,
                phase TEXT NOT NULL,
                trend TEXT NOT NULL,
                volatility TEXT NOT NULL,
                liquidity TEXT NOT NULL,
                structure TEXT NOT NULL,
                pump_score REAL NOT NULL,
                risk_score REAL NOT NULL,
                close_price REAL NOT NULL,
                strategy_mode TEXT NOT NULL,
                extra_metrics TEXT,  -- JSON строка с дополнительными метриками
                pattern_id TEXT,     -- ID паттерна для reliability analysis
                reliability_score REAL,  -- Reliability score паттерна (0.0 - 1.0)
                created_at INTEGER DEFAULT (strftime('%s', 'now') * 1000)
            )
        """)
        
        # Проверяем существование столбцов и добавляем их, если нужно (миграция)
        cur.execute("PRAGMA table_info(market_diagnostics)")
        columns = {row[1]: row[2] for row in cur.fetchall()}
        
        if 'pattern_id' not in columns:
            cur.execute("ALTER TABLE market_diagnostics ADD COLUMN pattern_id TEXT")
        
        if 'reliability_score' not in columns:
            cur.execute("ALTER TABLE market_diagnostics ADD COLUMN reliability_score REAL")
        
        # Создаем индексы отдельными запросами
        cur.execute("CREATE INDEX IF NOT EXISTS idx_md_symbol_tf ON market_diagnostics(symbol, timeframe)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_md_timestamp ON market_diagnostics(timestamp)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_md_pump_score ON market_diagnostics(pump_score)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_md_risk_score ON market_diagnostics(risk_score)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_md_phase ON market_diagnostics(phase)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_md_pattern_id ON market_diagnostics(pattern_id)")
        
        self.db.conn.commit()
    
    def save_snapshot(self, snapshot: DiagnosticsSnapshot) -> int:
        """
        Сохранить снимок диагностики.
        
        Args:
            snapshot: Снимок диагностики
        
        Returns:
            ID сохраненной записи
        """

        import json
        
        cur = self.db.conn.cursor()
        extra_metrics_json = json.dumps(snapshot.extra_metrics) if snapshot.extra_metrics else None
        
        cur.execute("""
            INSERT INTO market_diagnostics (
                timestamp, symbol, timeframe, phase, trend, volatility, liquidity,
                structure, pump_score, risk_score, close_price, strategy_mode, extra_metrics,
                pattern_id, reliability_score
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            snapshot.timestamp,
            snapshot.symbol,
            snapshot.timeframe,
            snapshot.phase,
            snapshot.trend,
            snapshot.volatility,
            snapshot.liquidity,
            snapshot.structure,
            snapshot.pump_score,
            snapshot.risk_score,
            snapshot.close_price,
            snapshot.strategy_mode,
            extra_metrics_json,
            snapshot.pattern_id,
            snapshot.reliability_score
        ))
        self.db.conn.commit()
        return cur.lastrowid
    
    def get_snapshots(
        self,
        symbol: Optional[str] = None,
        timeframe: Optional[str] = None,
        phase: Optional[str] = None,
        min_pump_score: Optional[float] = None,
        max_risk_score: Optional[float] = None,
        limit: int = 1000
    ) -> List[Dict[str, Any]]:
        """
        Получить снимки диагностик с фильтрацией.
        
        Args:
            symbol: Фильтр по символу
            timeframe: Фильтр по таймфрейму
            phase: Фильтр по фазе
            min_pump_score: Минимальный pump_score
            max_risk_score: Максимальный risk_score
            limit: Максимальное количество записей
        
        Returns:
            Список словарей с данными диагностик
        """
        import json
        
        conditions = []
        params = []
        
        if symbol:
            conditions.append("symbol = ?")
            params.append(symbol)
        
        if timeframe:
            conditions.append("timeframe = ?")
            params.append(timeframe)
        
        if phase:
            conditions.append("phase = ?")
            params.append(phase)
        
        if min_pump_score is not None:
            conditions.append("pump_score >= ?")
            params.append(min_pump_score)
        
        if max_risk_score is not None:
            conditions.append("risk_score <= ?")
            params.append(max_risk_score)
        
        where_clause = "WHERE " + " AND ".join(conditions) if conditions else ""
        
        cur = self.db.conn.cursor()
        cur.execute(f"""
            SELECT * FROM market_diagnostics
            {where_clause}
            ORDER BY timestamp DESC
            LIMIT ?
        """, params + [limit])
        
        rows = cur.fetchall()
        results = []
        for row in rows:
            result = dict(row)
            if result.get('extra_metrics'):
                try:
                    result['extra_metrics'] = json.loads(result['extra_metrics'])
                except:
                    result['extra_metrics'] = {}
            results.append(result)
        
        return results
    
    def get_statistics(
        self,
        symbol: Optional[str] = None,
        timeframe: Optional[str] = None,
        phase: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Получить статистику по диагностикам.
        
        Args:
            symbol: Фильтр по символу
            timeframe: Фильтр по таймфрейму
            phase: Фильтр по фазе
        
        Returns:
            Словарь со статистикой
        """
        conditions = []
        params = []
        
        if symbol:
            conditions.append("symbol = ?")
            params.append(symbol)
        
        if timeframe:
            conditions.append("timeframe = ?")
            params.append(timeframe)
        
        if phase:
            conditions.append("phase = ?")
            params.append(phase)
        
        where_clause = "WHERE " + " AND ".join(conditions) if conditions else ""
        
        cur = self.db.conn.cursor()
        cur.execute(f"""
            SELECT 
                COUNT(*) as total_count,
                AVG(pump_score) as avg_pump_score,
                AVG(risk_score) as avg_risk_score,
                MIN(pump_score) as min_pump_score,
                MAX(pump_score) as max_pump_score,
                MIN(risk_score) as min_risk_score,
                MAX(risk_score) as max_risk_score,
                COUNT(DISTINCT symbol) as unique_symbols,
                COUNT(DISTINCT timeframe) as unique_timeframes
            FROM market_diagnostics
            {where_clause}
        """, params)
        
        row = cur.fetchone()
        if row:
            return dict(row)
        return {}
    
    def get_phase_distribution(
        self,
        symbol: Optional[str] = None,
        timeframe: Optional[str] = None
    ) -> Dict[str, int]:
        """
        Получить распределение по фазам.
        
        Args:
            symbol: Фильтр по символу
            timeframe: Фильтр по таймфрейму
        
        Returns:
            Словарь {phase: count}
        """
        conditions = []
        params = []
        
        if symbol:
            conditions.append("symbol = ?")
            params.append(symbol)
        
        if timeframe:
            conditions.append("timeframe = ?")
            params.append(timeframe)
        
        where_clause = "WHERE " + " AND ".join(conditions) if conditions else ""
        
        cur = self.db.conn.cursor()
        cur.execute(f"""
            SELECT phase, COUNT(*) as count
            FROM market_diagnostics
            {where_clause}
            GROUP BY phase
            ORDER BY count DESC
        """, params)
        
        return {row['phase']: row['count'] for row in cur.fetchall()}
