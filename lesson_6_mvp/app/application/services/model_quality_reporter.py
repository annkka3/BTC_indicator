# app/application/services/model_quality_reporter.py
"""
Автоматические отчёты о качестве моделей.

Анализирует:
- Hit-rate по Grade A/B/C/D
- E[R] по каждому типу сетапа
- Смещения в калибровке
- Алерты при деградации качества
"""

import logging
from typing import Dict, List, Optional
from dataclasses import dataclass
from datetime import datetime, timedelta
import json

logger = logging.getLogger("alt_forecast.services.quality_reporter")


@dataclass
class GradeStats:
    """Статистика по Grade."""
    grade: str
    count: int
    hit_rate: float
    avg_return: float
    expected_shortfall: float
    alert: Optional[str] = None  # Алерт, если качество деградировало


@dataclass
class SetupTypeStats:
    """Статистика по типу сетапа."""
    setup_type: str
    count: int
    hit_rate: float
    avg_return: float
    expected_shortfall: float


@dataclass
class QualityReport:
    """Отчёт о качестве моделей."""
    symbol: str
    timeframe: str
    horizon: int
    period_days: int
    total_forecasts: int
    grade_stats: List[GradeStats]
    setup_type_stats: List[SetupTypeStats]
    alerts: List[str]
    timestamp: str


class ModelQualityReporter:
    """Репортер качества моделей."""
    
    def __init__(self, db):
        """
        Args:
            db: Database instance
        """
        self.db = db
    
    def generate_report(
        self,
        symbol: str = "BTC",
        timeframe: str = "1h",
        horizon: int = 24,
        period_days: int = 30,
        min_samples_per_grade: int = 20
    ) -> Optional[QualityReport]:
        """
        Сгенерировать отчёт о качестве моделей.
        
        Args:
            symbol: Символ
            timeframe: Таймфрейм
            horizon: Горизонт прогноза
            period_days: Период анализа в днях
            min_samples_per_grade: Минимальное количество образцов для Grade
        
        Returns:
            QualityReport или None
        """
        try:
            cur = self.db.conn.cursor()
            
            # Получаем данные за период
            cutoff_ts = int((datetime.utcnow() - timedelta(days=period_days)).timestamp() * 1000)
            
            query = """
                SELECT 
                    probability_up,
                    predicted_return,
                    timestamp_ms,
                    metadata
                FROM forecast_history
                WHERE symbol = ? AND timeframe = ? AND horizon = ?
                AND timestamp_ms >= ?
                ORDER BY timestamp_ms DESC
            """
            
            cur.execute(query, (symbol, timeframe, horizon, cutoff_ts))
            rows = cur.fetchall()
            
            if len(rows) < min_samples_per_grade:
                logger.warning(f"Insufficient data for report: {len(rows)} < {min_samples_per_grade}")
                return None
            
            # Анализируем по Grade
            grade_stats = self._analyze_by_grade(rows, min_samples_per_grade)
            
            # Анализируем по типу сетапа
            setup_type_stats = self._analyze_by_setup_type(rows)
            
            # Генерируем алерты
            alerts = self._generate_alerts(grade_stats, min_samples_per_grade)
            
            return QualityReport(
                symbol=symbol,
                timeframe=timeframe,
                horizon=horizon,
                period_days=period_days,
                total_forecasts=len(rows),
                grade_stats=grade_stats,
                setup_type_stats=setup_type_stats,
                alerts=alerts,
                timestamp=datetime.utcnow().isoformat()
            )
        except Exception as e:
            logger.exception(f"Failed to generate quality report: {e}")
            return None
    
    def _analyze_by_grade(self, rows: List, min_samples: int) -> List[GradeStats]:
        """Анализировать статистику по Grade."""
        # Группируем по Grade (извлекаем из metadata или вычисляем)
        grade_groups = {"A": [], "B": [], "C": [], "D": []}
        
        for row in rows:
            # Пытаемся извлечь grade из metadata
            grade = None
            try:
                metadata_str = row[3] if len(row) > 3 else None
                if metadata_str:
                    if isinstance(metadata_str, str):
                        metadata = json.loads(metadata_str)
                    else:
                        metadata = metadata_str
                    grade = metadata.get("grade")
            except Exception:
                pass
            
            # Если grade нет в metadata, вычисляем приблизительно
            if not grade:
                # Упрощенная логика: на основе probability_up и predicted_return
                p_up = row[0]
                ret = row[1]
                if p_up > 0.7 and abs(ret) > 0.02:
                    grade = "A"
                elif p_up > 0.6 and abs(ret) > 0.01:
                    grade = "B"
                elif p_up > 0.5:
                    grade = "C"
                else:
                    grade = "D"
            
            if grade in grade_groups:
                grade_groups[grade].append(row)
        
        # Вычисляем статистику для каждого Grade
        grade_stats = []
        for grade, group_rows in grade_groups.items():
            if len(group_rows) < min_samples:
                continue
            
            returns = [r[1] for r in group_rows]  # predicted_return
            
            # Hit-rate
            hits = sum(1 for r in returns if r > 0)
            hit_rate = hits / len(returns) if returns else 0.5
            
            # E[R]
            avg_return = sum(returns) / len(returns) if returns else 0.0
            
            # Expected Shortfall
            returns_sorted = sorted(returns)
            worst_10_pct = max(1, int(len(returns_sorted) * 0.1))
            es = sum(returns_sorted[:worst_10_pct]) / worst_10_pct if worst_10_pct > 0 else 0.0
            
            # Алерт, если hit-rate слишком низкий для Grade
            alert = None
            if grade == "A" and hit_rate < 0.5:
                alert = f"Grade A hit-rate {hit_rate:.1%} < 50% - требуется снижение агрессивности"
            elif grade == "B" and hit_rate < 0.45:
                alert = f"Grade B hit-rate {hit_rate:.1%} < 45% - требуется пересмотр порогов"
            
            grade_stats.append(GradeStats(
                grade=grade,
                count=len(group_rows),
                hit_rate=hit_rate,
                avg_return=avg_return,
                expected_shortfall=es,
                alert=alert
            ))
        
        return grade_stats
    
    def _analyze_by_setup_type(self, rows: List) -> List[SetupTypeStats]:
        """Анализировать статистику по типу сетапа."""
        # Группируем по setup_type
        setup_groups = {"SOFT": [], "IMPULSE": [], "NEEDS_CONFIRMATION": [], "NEUTRAL": []}
        
        for row in rows:
            setup_type = None
            try:
                metadata_str = row[3] if len(row) > 3 else None
                if metadata_str:
                    if isinstance(metadata_str, str):
                        metadata = json.loads(metadata_str)
                    else:
                        metadata = metadata_str
                    setup_type = metadata.get("setup_type")
            except Exception:
                pass
            
            if setup_type and setup_type in setup_groups:
                setup_groups[setup_type].append(row)
        
        # Вычисляем статистику
        setup_stats = []
        for setup_type, group_rows in setup_groups.items():
            if len(group_rows) < 10:
                continue
            
            returns = [r[1] for r in group_rows]
            
            hits = sum(1 for r in returns if r > 0)
            hit_rate = hits / len(returns) if returns else 0.5
            avg_return = sum(returns) / len(returns) if returns else 0.0
            
            returns_sorted = sorted(returns)
            worst_10_pct = max(1, int(len(returns_sorted) * 0.1))
            es = sum(returns_sorted[:worst_10_pct]) / worst_10_pct if worst_10_pct > 0 else 0.0
            
            setup_stats.append(SetupTypeStats(
                setup_type=setup_type,
                count=len(group_rows),
                hit_rate=hit_rate,
                avg_return=avg_return,
                expected_shortfall=es
            ))
        
        return setup_stats
    
    def _generate_alerts(self, grade_stats: List[GradeStats], min_samples: int) -> List[str]:
        """Генерировать алерты на основе статистики."""
        alerts = []
        
        for stat in grade_stats:
            if stat.alert:
                alerts.append(stat.alert)
            
            # Дополнительные проверки
            if stat.grade == "A" and stat.avg_return < 0:
                alerts.append(f"Grade A имеет отрицательный E[R]: {stat.avg_return:.4f}")
            
            if stat.grade in ["A", "B"] and stat.expected_shortfall < -0.1:
                alerts.append(f"Grade {stat.grade} имеет высокий ES: {stat.expected_shortfall:.4f}")
        
        return alerts
    
    def format_report(self, report: QualityReport) -> str:
        """Форматировать отчёт для отображения."""
        lines = [
            f"📊 <b>Отчёт о качестве модели</b>",
            f"Символ: {report.symbol} | ТФ: {report.timeframe} | H: {report.horizon}",
            f"Период: {report.period_days} дней | Всего прогнозов: {report.total_forecasts}",
            f"Дата: {report.timestamp}",
            "",
            "<b>Статистика по Grade:</b>"
        ]
        
        for stat in report.grade_stats:
            alert_mark = "⚠️" if stat.alert else ""
            lines.append(
                f"Grade {stat.grade}: {stat.count} образцов | "
                f"Hit-rate: {stat.hit_rate:.1%} | "
                f"E[R]: {stat.avg_return*100:+.2f}% | "
                f"ES: {stat.expected_shortfall*100:+.2f}% {alert_mark}"
            )
            if stat.alert:
                lines.append(f"  ⚠️ {stat.alert}")
        
        lines.append("")
        lines.append("<b>Статистика по типам сетапов:</b>")
        
        for stat in report.setup_type_stats:
            lines.append(
                f"{stat.setup_type}: {stat.count} образцов | "
                f"Hit-rate: {stat.hit_rate:.1%} | "
                f"E[R]: {stat.avg_return*100:+.2f}% | "
                f"ES: {stat.expected_shortfall*100:+.2f}%"
            )
        
        if report.alerts:
            lines.append("")
            lines.append("<b>⚠️ Алерты:</b>")
            for alert in report.alerts:
                lines.append(f"• {alert}")
        
        return "\n".join(lines)


















