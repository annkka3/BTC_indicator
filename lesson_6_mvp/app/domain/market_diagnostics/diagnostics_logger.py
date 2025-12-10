# app/domain/market_diagnostics/diagnostics_logger.py
"""
Модуль логирования диагностик Market Doctor для статистического анализа.

Логирует:
- Scores (aggregated_long/short, per-TF scores, group scores)
- Diagnostics (regime, trend, volatility, liquidity)
- SMC context (уровни, имбалансы)
- Trade recommendations (bias, triggers, position size)
- Фактические результаты через X баров/часов
"""

import json
from typing import Dict, Optional, List, Any, TYPE_CHECKING
from datetime import datetime, timezone
from dataclasses import dataclass, asdict

if TYPE_CHECKING:
    from ...domain.interfaces.idb import IDatabase
else:
    IDatabase = object

from .scoring_engine import MultiTFScore, TimeframeScore
from .analyzer import MarketDiagnostics
from .trade_planner import TradePlan
from .compact_report import CompactReport


@dataclass
class DiagnosticsSnapshot:
    """Снимок диагностики для логирования."""
    symbol: str
    timeframe: str
    timestamp_ms: int
    
    # Scores
    aggregated_long: float
    aggregated_short: float
    direction: str  # "LONG" / "SHORT" / "NEUTRAL"
    confidence: float
    
    # Per-TF scores
    per_tf_scores: Dict[str, Dict]  # {tf: {net_score, normalized_long, normalized_short, group_scores}}
    
    # Diagnostics
    regime: str
    trend: str
    volatility: str
    liquidity: str
    
    # SMC context
    nearest_support: Optional[float] = None
    nearest_resistance: Optional[float] = None
    distance_to_support: Optional[float] = None
    distance_to_resistance: Optional[float] = None
    has_unfilled_imbalance: bool = False
    imbalance_distance: Optional[float] = None
    
    # Trade recommendations
    bias: Optional[str] = None  # "LONG" / "SHORT" / "NO_TRADE"
    position_r: Optional[float] = None
    bullish_trigger_level: Optional[float] = None
    bearish_trigger_level: Optional[float] = None
    invalidation_level: Optional[float] = None
    
    # Setup type
    setup_type: Optional[str] = None
    setup_description: Optional[str] = None
    
    # Current price
    current_price: Optional[float] = None


@dataclass
class DiagnosticsResult:
    """Результат диагностики через X баров/часов."""
    snapshot_id: int  # ID из diagnostics_snapshots
    horizon_bars: int  # Через сколько баров проверяем
    horizon_hours: float  # Через сколько часов проверяем
    
    # Фактические результаты
    max_r_up: Optional[float] = None  # Максимальный R вверх
    max_r_down: Optional[float] = None  # Максимальный R вниз
    hit_tp: bool = False  # Достигнут TP
    hit_sl: bool = False  # Достигнут SL
    r_at_horizon: Optional[float] = None  # R на горизонте
    
    # Цены
    entry_price: Optional[float] = None
    price_at_horizon: Optional[float] = None
    highest_price: Optional[float] = None
    lowest_price: Optional[float] = None


class DiagnosticsLogger:
    """Логгер для диагностик Market Doctor."""
    
    def __init__(self, db: IDatabase):
        """
        Args:
            db: Database instance
        """
        self.db = db
        self._init_tables()
    
    def _init_tables(self):
        """Инициализировать таблицы для логирования."""
        cur = self.db.conn.cursor()
        cur.executescript("""
            -- Снимки диагностик
            CREATE TABLE IF NOT EXISTS diagnostics_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                timeframe TEXT NOT NULL,
                timestamp_ms INTEGER NOT NULL,
                
                -- Scores
                aggregated_long REAL NOT NULL,
                aggregated_short REAL NOT NULL,
                direction TEXT NOT NULL,
                confidence REAL NOT NULL,
                
                -- Per-TF scores (JSON)
                per_tf_scores TEXT NOT NULL,
                
                -- Diagnostics
                regime TEXT NOT NULL,
                trend TEXT NOT NULL,
                volatility TEXT NOT NULL,
                liquidity TEXT NOT NULL,
                
                -- SMC context
                nearest_support REAL,
                nearest_resistance REAL,
                distance_to_support REAL,
                distance_to_resistance REAL,
                has_unfilled_imbalance INTEGER DEFAULT 0,
                imbalance_distance REAL,
                
                -- Trade recommendations
                bias TEXT,
                position_r REAL,
                bullish_trigger_level REAL,
                bearish_trigger_level REAL,
                invalidation_level REAL,
                
                -- Setup type
                setup_type TEXT,
                setup_description TEXT,
                
                -- Current price
                current_price REAL,
                
                -- Индексы для быстрого поиска
                UNIQUE(symbol, timeframe, timestamp_ms)
            );
            
            CREATE INDEX IF NOT EXISTS idx_diagnostics_snapshots_symbol_tf 
                ON diagnostics_snapshots(symbol, timeframe, timestamp_ms);
            CREATE INDEX IF NOT EXISTS idx_diagnostics_snapshots_timestamp 
                ON diagnostics_snapshots(timestamp_ms);
            
            -- Результаты диагностик через X баров/часов
            CREATE TABLE IF NOT EXISTS diagnostics_results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                snapshot_id INTEGER NOT NULL,
                horizon_bars INTEGER NOT NULL,
                horizon_hours REAL NOT NULL,
                
                -- Фактические результаты
                max_r_up REAL,
                max_r_down REAL,
                hit_tp INTEGER DEFAULT 0,
                hit_sl INTEGER DEFAULT 0,
                r_at_horizon REAL,
                
                -- Цены
                entry_price REAL,
                price_at_horizon REAL,
                highest_price REAL,
                lowest_price REAL,
                
                FOREIGN KEY (snapshot_id) REFERENCES diagnostics_snapshots(id),
                UNIQUE(snapshot_id, horizon_bars, horizon_hours)
            );
            
            CREATE INDEX IF NOT EXISTS idx_diagnostics_results_snapshot 
                ON diagnostics_results(snapshot_id);
        """)
        self.db.conn.commit()
    
    def log_snapshot(
        self,
        symbol: str,
        timeframe: str,
        multi_tf_score: MultiTFScore,
        diagnostics: Dict[str, MarketDiagnostics],
        compact_report: CompactReport,
        current_price: Optional[float] = None
    ) -> int:
        """
        Записать снимок диагностики.
        
        Args:
            symbol: Символ (например, "BTCUSDT")
            timeframe: Таймфрейм (например, "1h")
            multi_tf_score: Multi-TF score
            diagnostics: Словарь диагностик по таймфреймам
            compact_report: Компактный отчёт
            current_price: Текущая цена
        
        Returns:
            ID созданного снимка
        """
        target_diag = diagnostics.get(timeframe)
        if not target_diag:
            raise ValueError(f"No diagnostics for timeframe {timeframe}")
        
        # Извлекаем SMC данные
        smc = compact_report.smc
        levels = smc.get('levels', {})
        support_levels = levels.get('support', [])
        resistance_levels = levels.get('resistance', [])
        
        nearest_support = None
        nearest_resistance = None
        distance_to_support = None
        distance_to_resistance = None
        
        if current_price:
            if support_levels:
                sup = support_levels[0]
                nearest_support = (sup.get('price_low', 0) + sup.get('price_high', 0)) / 2
                distance_to_support = abs(current_price - nearest_support) / current_price if nearest_support else None
            
            if resistance_levels:
                res = resistance_levels[0]
                nearest_resistance = (res.get('price_low', 0) + res.get('price_high', 0)) / 2
                distance_to_resistance = abs(nearest_resistance - current_price) / current_price if nearest_resistance else None
        
        # Проверяем незаполненные имбалансы
        imbalances = smc.get('imbalances', [])
        has_unfilled_imbalance = False
        imbalance_distance = None
        
        if imbalances and current_price:
            for imb in imbalances:
                if not imb.get('filled', False):
                    has_unfilled_imbalance = True
                    mid_price = (imb.get('price_low', 0) + imb.get('price_high', 0)) / 2
                    imbalance_distance = abs(mid_price - current_price) / current_price if mid_price else None
                    break
        
        # Извлекаем trade recommendations
        trade_map = compact_report.trade_map
        bias = trade_map.get('bias')
        position_r = trade_map.get('position_r')
        bullish_trigger = trade_map.get('bullish_trigger')
        bearish_trigger = trade_map.get('bearish_trigger')
        invalidations = trade_map.get('invalidations', [])
        
        bullish_trigger_level = bullish_trigger.get('level') if bullish_trigger else None
        bearish_trigger_level = bearish_trigger.get('level') if bearish_trigger else None
        invalidation_level = None
        if invalidations:
            invalidation_level = invalidations[0].get('level')
        
        # Формируем per_tf_scores для JSON
        per_tf_scores_dict = {}
        for tf, score_data in multi_tf_score.per_tf.items():
            if isinstance(score_data, TimeframeScore):
                per_tf_scores_dict[tf] = {
                    'net_score': score_data.net_score,
                    'normalized_long': score_data.normalized_long,
                    'normalized_short': score_data.normalized_short,
                    'group_scores': {
                        group.value: {
                            'raw_score': group_score.raw_score,
                            'summary': group_score.summary
                        }
                        for group, group_score in score_data.group_scores.items()
                    }
                }
            else:
                per_tf_scores_dict[tf] = score_data
        
        timestamp_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        
        cur = self.db.conn.cursor()
        cur.execute("""
            INSERT OR REPLACE INTO diagnostics_snapshots (
                symbol, timeframe, timestamp_ms,
                aggregated_long, aggregated_short, direction, confidence,
                per_tf_scores,
                regime, trend, volatility, liquidity,
                nearest_support, nearest_resistance,
                distance_to_support, distance_to_resistance,
                has_unfilled_imbalance, imbalance_distance,
                bias, position_r,
                bullish_trigger_level, bearish_trigger_level, invalidation_level,
                setup_type, setup_description,
                current_price
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            symbol,
            timeframe,
            timestamp_ms,
            multi_tf_score.aggregated_long,
            multi_tf_score.aggregated_short,
            multi_tf_score.direction,
            multi_tf_score.confidence,
            json.dumps(per_tf_scores_dict),
            target_diag.phase.value if hasattr(target_diag.phase, 'value') else str(target_diag.phase),
            target_diag.trend.value if hasattr(target_diag.trend, 'value') else str(target_diag.trend),
            target_diag.volatility.value if hasattr(target_diag.volatility, 'value') else str(target_diag.volatility),
            target_diag.liquidity.value if hasattr(target_diag.liquidity, 'value') else str(target_diag.liquidity),
            nearest_support,
            nearest_resistance,
            distance_to_support,
            distance_to_resistance,
            1 if has_unfilled_imbalance else 0,
            imbalance_distance,
            bias,
            position_r,
            bullish_trigger_level,
            bearish_trigger_level,
            invalidation_level,
            compact_report.setup_type,
            compact_report.setup_description,
            current_price
        ))
        self.db.conn.commit()
        
        return cur.lastrowid
    
    def log_result(
        self,
        snapshot_id: int,
        horizon_bars: int,
        horizon_hours: float,
        max_r_up: Optional[float] = None,
        max_r_down: Optional[float] = None,
        hit_tp: bool = False,
        hit_sl: bool = False,
        r_at_horizon: Optional[float] = None,
        entry_price: Optional[float] = None,
        price_at_horizon: Optional[float] = None,
        highest_price: Optional[float] = None,
        lowest_price: Optional[float] = None
    ):
        """
        Записать результат диагностики через X баров/часов.
        
        Args:
            snapshot_id: ID снимка диагностики
            horizon_bars: Через сколько баров проверяем
            horizon_hours: Через сколько часов проверяем
            max_r_up: Максимальный R вверх
            max_r_down: Максимальный R вниз
            hit_tp: Достигнут TP
            hit_sl: Достигнут SL
            r_at_horizon: R на горизонте
            entry_price: Цена входа
            price_at_horizon: Цена на горизонте
            highest_price: Максимальная цена за период
            lowest_price: Минимальная цена за период
        """
        cur = self.db.conn.cursor()
        cur.execute("""
            INSERT OR REPLACE INTO diagnostics_results (
                snapshot_id, horizon_bars, horizon_hours,
                max_r_up, max_r_down, hit_tp, hit_sl, r_at_horizon,
                entry_price, price_at_horizon, highest_price, lowest_price
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            snapshot_id,
            horizon_bars,
            horizon_hours,
            max_r_up,
            max_r_down,
            1 if hit_tp else 0,
            1 if hit_sl else 0,
            r_at_horizon,
            entry_price,
            price_at_horizon,
            highest_price,
            lowest_price
        ))
        self.db.conn.commit()
    
    def get_snapshots(
        self,
        symbol: Optional[str] = None,
        timeframe: Optional[str] = None,
        start_timestamp_ms: Optional[int] = None,
        end_timestamp_ms: Optional[int] = None,
        limit: int = 1000
    ) -> List[Dict[str, Any]]:
        """
        Получить снимки диагностик.
        
        Args:
            symbol: Фильтр по символу
            timeframe: Фильтр по таймфрейму
            start_timestamp_ms: Начало периода (ms)
            end_timestamp_ms: Конец периода (ms)
            limit: Максимальное количество записей
        
        Returns:
            Список снимков
        """
        cur = self.db.conn.cursor()
        query = "SELECT * FROM diagnostics_snapshots WHERE 1=1"
        params = []
        
        if symbol:
            query += " AND symbol = ?"
            params.append(symbol)
        
        if timeframe:
            query += " AND timeframe = ?"
            params.append(timeframe)
        
        if start_timestamp_ms:
            query += " AND timestamp_ms >= ?"
            params.append(start_timestamp_ms)
        
        if end_timestamp_ms:
            query += " AND timestamp_ms <= ?"
            params.append(end_timestamp_ms)
        
        query += " ORDER BY timestamp_ms DESC LIMIT ?"
        params.append(limit)
        
        cur.execute(query, params)
        rows = cur.fetchall()
        
        return [dict(row) for row in rows]
    
    def get_results_for_snapshot(self, snapshot_id: int) -> List[Dict[str, Any]]:
        """
        Получить результаты для снимка диагностики.
        
        Args:
            snapshot_id: ID снимка
        
        Returns:
            Список результатов
        """
        cur = self.db.conn.cursor()
        cur.execute("SELECT * FROM diagnostics_results WHERE snapshot_id = ?", (snapshot_id,))
        rows = cur.fetchall()
        
        return [dict(row) for row in rows]




