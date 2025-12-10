# app/domain/market_diagnostics/calibration_analyzer.py
"""
Анализатор для калибровки скоринга Market Doctor на основе фактических результатов.

Анализирует накопленные данные и предлагает:
- Калибровку границ scores (что реально "сильный шорт")
- Перетюнинг весов групп индикаторов
- Статистику по режимам и таймфреймам
"""

from typing import Dict, List, Optional, Tuple, TYPE_CHECKING
from dataclasses import dataclass
import json
import statistics

if TYPE_CHECKING:
    from ...domain.interfaces.idb import IDatabase
else:
    IDatabase = object

from .diagnostics_logger import DiagnosticsLogger


@dataclass
class ScoreBucketStats:
    """Статистика по корзине scores."""
    score_range: Tuple[float, float]  # (min, max)
    count: int
    avg_r: Optional[float] = None
    win_rate: Optional[float] = None  # Шанс получить хотя бы +1R
    loss_rate: Optional[float] = None  # Шанс словить -1R до +1R
    avg_max_r_up: Optional[float] = None
    avg_max_r_down: Optional[float] = None


@dataclass
class GroupWeightRecommendation:
    """Рекомендация по весу группы индикаторов."""
    group: str
    current_weight: float
    recommended_weight: float
    correlation_with_success: float
    reasoning: str


@dataclass
class CalibrationReport:
    """Отчёт о калибровке."""
    score_thresholds: Dict[str, Dict[str, float]]  # {direction: {strength_level: threshold}}
    group_weights: Dict[str, float]  # {group: weight}
    recommendations: List[GroupWeightRecommendation]
    stats_by_regime: Dict[str, Dict[str, float]]
    stats_by_timeframe: Dict[str, Dict[str, float]]


class CalibrationAnalyzer:
    """Анализатор для калибровки скоринга."""
    
    def __init__(self, db: IDatabase):
        """
        Args:
            db: Database instance
        """
        self.db = db
        self.logger = DiagnosticsLogger(db)
    
    def analyze_score_buckets(
        self,
        symbol: Optional[str] = None,
        timeframe: Optional[str] = None,
        direction: Optional[str] = None,
        horizon_bars: int = 4,
        horizon_hours: float = 24.0
    ) -> Dict[str, ScoreBucketStats]:
        """
        Проанализировать корзины scores и их фактическую эффективность.
        
        Args:
            symbol: Фильтр по символу
            timeframe: Фильтр по таймфрейму
            direction: Фильтр по направлению ("LONG" / "SHORT")
            horizon_bars: Горизонт в барах для проверки результатов
            horizon_hours: Горизонт в часах для проверки результатов
        
        Returns:
            Словарь {bucket_name: ScoreBucketStats}
        """
        # Получаем снимки с результатами
        snapshots = self.logger.get_snapshots(symbol=symbol, timeframe=timeframe)
        
        # Группируем по корзинам scores
        buckets = {
            "weak_long": (0.0, 4.0),
            "moderate_long": (4.0, 6.0),
            "strong_long": (6.0, 8.0),
            "extreme_long": (8.0, 10.0),
            "weak_short": (0.0, 4.0),
            "moderate_short": (4.0, 6.0),
            "strong_short": (6.0, 8.0),
            "extreme_short": (8.0, 10.0),
        }
        
        bucket_data: Dict[str, List[Dict]] = {name: [] for name in buckets.keys()}
        
        for snapshot in snapshots:
            # Фильтруем по направлению
            if direction and snapshot['direction'] != direction:
                continue
            
            # Получаем результаты
            results = self.logger.get_results_for_snapshot(snapshot['id'])
            result = None
            for r in results:
                if r['horizon_bars'] == horizon_bars and abs(r['horizon_hours'] - horizon_hours) < 0.1:
                    result = r
                    break
            
            if not result or result['r_at_horizon'] is None:
                continue
            
            # Определяем корзину
            if snapshot['direction'] == 'LONG':
                score = snapshot['aggregated_long']
                if 0.0 <= score < 4.0:
                    bucket_name = "weak_long"
                elif 4.0 <= score < 6.0:
                    bucket_name = "moderate_long"
                elif 6.0 <= score < 8.0:
                    bucket_name = "strong_long"
                else:
                    bucket_name = "extreme_long"
            elif snapshot['direction'] == 'SHORT':
                score = snapshot['aggregated_short']
                if 0.0 <= score < 4.0:
                    bucket_name = "weak_short"
                elif 4.0 <= score < 6.0:
                    bucket_name = "moderate_short"
                elif 6.0 <= score < 8.0:
                    bucket_name = "strong_short"
                else:
                    bucket_name = "extreme_short"
            else:
                continue
            
            bucket_data[bucket_name].append({
                'snapshot': snapshot,
                'result': result
            })
        
        # Вычисляем статистику для каждой корзины
        bucket_stats: Dict[str, ScoreBucketStats] = {}
        
        for bucket_name, data_list in bucket_data.items():
            if not data_list:
                continue
            
            r_values = [d['result']['r_at_horizon'] for d in data_list if d['result']['r_at_horizon'] is not None]
            max_r_up_values = [d['result']['max_r_up'] for d in data_list if d['result']['max_r_up'] is not None]
            max_r_down_values = [d['result']['max_r_down'] for d in data_list if d['result']['max_r_down'] is not None]
            
            wins = sum(1 for r in r_values if r >= 1.0)
            losses = sum(1 for r in r_values if r <= -1.0)
            
            bucket_stats[bucket_name] = ScoreBucketStats(
                score_range=buckets[bucket_name],
                count=len(data_list),
                avg_r=statistics.mean(r_values) if r_values else None,
                win_rate=wins / len(data_list) if data_list else None,
                loss_rate=losses / len(data_list) if data_list else None,
                avg_max_r_up=statistics.mean(max_r_up_values) if max_r_up_values else None,
                avg_max_r_down=statistics.mean(max_r_down_values) if max_r_down_values else None
            )
        
        return bucket_stats
    
    def analyze_group_correlations(
        self,
        symbol: Optional[str] = None,
        timeframe: Optional[str] = None,
        horizon_bars: int = 4,
        horizon_hours: float = 24.0
    ) -> Dict[str, float]:
        """
        Проанализировать корреляции групп индикаторов с успешными сделками.
        
        Args:
            symbol: Фильтр по символу
            timeframe: Фильтр по таймфрейму
            horizon_bars: Горизонт в барах
            horizon_hours: Горизонт в часах
        
        Returns:
            Словарь {group_name: correlation_score}
        """
        snapshots = self.logger.get_snapshots(symbol=symbol, timeframe=timeframe)
        
        group_correlations: Dict[str, List[Tuple[float, float]]] = {}  # {group: [(raw_score, r_at_horizon)]}
        
        for snapshot in snapshots:
            results = self.logger.get_results_for_snapshot(snapshot['id'])
            result = None
            for r in results:
                if r['horizon_bars'] == horizon_bars and abs(r['horizon_hours'] - horizon_hours) < 0.1:
                    result = r
                    break
            
            if not result or result['r_at_horizon'] is None:
                continue
            
            # Парсим per_tf_scores
            per_tf_scores = json.loads(snapshot['per_tf_scores'])
            target_tf = snapshot['timeframe']
            
            if target_tf in per_tf_scores:
                group_scores = per_tf_scores[target_tf].get('group_scores', {})
                
                for group_name, group_data in group_scores.items():
                    raw_score = group_data.get('raw_score', 0)
                    r_at_horizon = result['r_at_horizon']
                    
                    if group_name not in group_correlations:
                        group_correlations[group_name] = []
                    
                    # Учитываем направление
                    if snapshot['direction'] == 'LONG' and raw_score > 0:
                        group_correlations[group_name].append((raw_score, r_at_horizon))
                    elif snapshot['direction'] == 'SHORT' and raw_score < 0:
                        group_correlations[group_name].append((abs(raw_score), abs(r_at_horizon)))
        
        # Вычисляем корреляции
        correlations: Dict[str, float] = {}
        
        for group_name, pairs in group_correlations.items():
            if len(pairs) < 10:  # Минимум данных для статистики
                continue
            
            scores = [p[0] for p in pairs]
            results = [p[1] for p in pairs]
            
            # Простая корреляция Пирсона
            if len(scores) > 1:
                mean_score = statistics.mean(scores)
                mean_result = statistics.mean(results)
                
                numerator = sum((s - mean_score) * (r - mean_result) for s, r in zip(scores, results))
                denom_score = sum((s - mean_score) ** 2 for s in scores)
                denom_result = sum((r - mean_result) ** 2 for r in results)
                
                if denom_score > 0 and denom_result > 0:
                    correlation = numerator / (denom_score * denom_result) ** 0.5
                    correlations[group_name] = correlation
        
        return correlations
    
    def generate_calibration_report(
        self,
        symbol: Optional[str] = None,
        timeframe: Optional[str] = None,
        horizon_bars: int = 4,
        horizon_hours: float = 24.0
    ) -> CalibrationReport:
        """
        Сгенерировать отчёт о калибровке.
        
        Args:
            symbol: Фильтр по символу
            timeframe: Фильтр по таймфрейму
            horizon_bars: Горизонт в барах
            horizon_hours: Горизонт в часах
        
        Returns:
            CalibrationReport
        """
        # Анализируем корзины scores
        bucket_stats = self.analyze_score_buckets(
            symbol=symbol,
            timeframe=timeframe,
            horizon_bars=horizon_bars,
            horizon_hours=horizon_hours
        )
        
        # Определяем пороги на основе статистики
        score_thresholds = {
            "LONG": {},
            "SHORT": {}
        }
        
        # Для LONG
        if "strong_long" in bucket_stats:
            strong_stats = bucket_stats["strong_long"]
            if strong_stats.win_rate and strong_stats.win_rate >= 0.6:
                score_thresholds["LONG"]["strong"] = 6.0
            elif "extreme_long" in bucket_stats:
                extreme_stats = bucket_stats["extreme_long"]
                if extreme_stats.win_rate and extreme_stats.win_rate >= 0.6:
                    score_thresholds["LONG"]["strong"] = 7.5
        
        # Для SHORT
        if "strong_short" in bucket_stats:
            strong_stats = bucket_stats["strong_short"]
            if strong_stats.win_rate and strong_stats.win_rate >= 0.6:
                score_thresholds["SHORT"]["strong"] = 6.0
            elif "extreme_short" in bucket_stats:
                extreme_stats = bucket_stats["extreme_short"]
                if extreme_stats.win_rate and extreme_stats.win_rate >= 0.6:
                    score_thresholds["SHORT"]["strong"] = 7.5
        
        # Анализируем корреляции групп
        group_correlations = self.analyze_group_correlations(
            symbol=symbol,
            timeframe=timeframe,
            horizon_bars=horizon_bars,
            horizon_hours=horizon_hours
        )
        
        # Текущие веса (из scoring_engine.py)
        current_weights = {
            "trend": 0.25,
            "momentum": 0.20,
            "volume": 0.15,
            "volatility": 0.10,
            "structure": 0.20,
            "derivatives": 0.10
        }
        
        # Генерируем рекомендации
        recommendations: List[GroupWeightRecommendation] = []
        
        for group_name, correlation in group_correlations.items():
            current_weight = current_weights.get(group_name, 0.1)
            
            # Если корреляция высокая, увеличиваем вес
            if correlation > 0.3:
                recommended_weight = min(0.35, current_weight * 1.2)
            elif correlation < -0.1:
                recommended_weight = max(0.05, current_weight * 0.8)
            else:
                recommended_weight = current_weight
            
            if abs(recommended_weight - current_weight) > 0.01:
                recommendations.append(GroupWeightRecommendation(
                    group=group_name,
                    current_weight=current_weight,
                    recommended_weight=recommended_weight,
                    correlation_with_success=correlation,
                    reasoning=f"Корреляция с успехом: {correlation:.2f}"
                ))
        
        # Статистика по режимам и таймфреймам
        stats_by_regime = self._analyze_by_regime(symbol, timeframe, horizon_bars, horizon_hours)
        stats_by_timeframe = self._analyze_by_timeframe(symbol, horizon_bars, horizon_hours)
        
        return CalibrationReport(
            score_thresholds=score_thresholds,
            group_weights=current_weights,
            recommendations=recommendations,
            stats_by_regime=stats_by_regime,
            stats_by_timeframe=stats_by_timeframe
        )
    
    def _analyze_by_regime(
        self,
        symbol: Optional[str],
        timeframe: Optional[str],
        horizon_bars: int,
        horizon_hours: float
    ) -> Dict[str, Dict[str, float]]:
        """Анализ статистики по режимам."""
        snapshots = self.logger.get_snapshots(symbol=symbol, timeframe=timeframe)
        
        regime_stats: Dict[str, List[float]] = {}
        
        for snapshot in snapshots:
            regime = snapshot['regime']
            if regime not in regime_stats:
                regime_stats[regime] = []
            
            results = self.logger.get_results_for_snapshot(snapshot['id'])
            result = None
            for r in results:
                if r['horizon_bars'] == horizon_bars and abs(r['horizon_hours'] - horizon_hours) < 0.1:
                    result = r
                    break
            
            if result and result['r_at_horizon'] is not None:
                regime_stats[regime].append(result['r_at_horizon'])
        
        stats_dict: Dict[str, Dict[str, float]] = {}
        for regime, r_values in regime_stats.items():
            if r_values:
                stats_dict[regime] = {
                    'avg_r': statistics.mean(r_values),
                    'win_rate': sum(1 for r in r_values if r >= 1.0) / len(r_values),
                    'count': len(r_values)
                }
        
        return stats_dict
    
    def _analyze_by_timeframe(
        self,
        symbol: Optional[str],
        horizon_bars: int,
        horizon_hours: float
    ) -> Dict[str, Dict[str, float]]:
        """Анализ статистики по таймфреймам."""
        snapshots = self.logger.get_snapshots(symbol=symbol)
        
        tf_stats: Dict[str, List[float]] = {}
        
        for snapshot in snapshots:
            tf = snapshot['timeframe']
            if tf not in tf_stats:
                tf_stats[tf] = []
            
            results = self.logger.get_results_for_snapshot(snapshot['id'])
            result = None
            for r in results:
                if r['horizon_bars'] == horizon_bars and abs(r['horizon_hours'] - horizon_hours) < 0.1:
                    result = r
                    break
            
            if result and result['r_at_horizon'] is not None:
                tf_stats[tf].append(result['r_at_horizon'])
        
        stats_dict: Dict[str, Dict[str, float]] = {}
        for tf, r_values in tf_stats.items():
            if r_values:
                stats_dict[tf] = {
                    'avg_r': statistics.mean(r_values),
                    'win_rate': sum(1 for r in r_values if r >= 1.0) / len(r_values),
                    'count': len(r_values)
                }
        
        return stats_dict




