# app/domain/market_diagnostics/calibration_service.py
"""
Сервис для адаптивной калибровки порогов Market Doctor.

Использует исторические данные для определения оптимальных порогов pump_score
в зависимости от символа и режима рынка.
"""

from typing import Dict, Optional, TYPE_CHECKING
import logging
import numpy as np

if TYPE_CHECKING:
    from ...domain.interfaces.idb import IDatabase
    from ...domain.interfaces.idiagnostics_repository import IDiagnosticsRepository
else:
    IDatabase = object
    IDiagnosticsRepository = object

from .backtest_analyzer import BacktestAnalyzer
from ..market_regime import GlobalRegime, GlobalRegimeAnalyzer

logger = logging.getLogger("alt_forecast.calibration")


class CalibrationService:
    """Сервис для адаптивной калибровки порогов."""
    
    def __init__(self, db: IDatabase, diagnostics_repo: IDiagnosticsRepository):
        """
        Args:
            db: Database instance (реализует IDatabase интерфейс)
            diagnostics_repo: Репозиторий диагностик (реализует IDiagnosticsRepository интерфейс)
        """
        self.db = db
        self.diagnostics_repo = diagnostics_repo
        # BacktestAnalyzer и GlobalRegimeAnalyzer создаются лениво при первом использовании
        # Это временное решение для обратной совместимости
        # В будущем они должны передаваться через DI
        self._backtest_analyzer = None
        self._regime_analyzer = None
    
    @property
    def backtest_analyzer(self) -> BacktestAnalyzer:
        """Ленивая инициализация BacktestAnalyzer."""
        if self._backtest_analyzer is None:
            # Временное решение: создаем через условный импорт
            # В будущем это должно передаваться через DI
            try:
                from ...infrastructure.db import DB as ConcreteDB
                from ...infrastructure.repositories.diagnostics_repository import DiagnosticsRepository as ConcreteRepo
                from ...infrastructure.market_data_service import MarketDataService as ConcreteMarketData
                
                if isinstance(self.db, ConcreteDB) and isinstance(self.diagnostics_repo, ConcreteRepo):
                    concrete_db = self.db
                    concrete_repo = self.diagnostics_repo
                    market_data = ConcreteMarketData(concrete_db)
                    regime_analyzer = GlobalRegimeAnalyzer(concrete_db, market_data)
                    self._backtest_analyzer = BacktestAnalyzer(concrete_db, concrete_repo, regime_analyzer)
                else:
                    raise ValueError("BacktestAnalyzer requires concrete DB and DiagnosticsRepository implementations")
            except (ImportError, ValueError) as e:
                logger.error(f"Failed to create BacktestAnalyzer: {e}")
                raise
        return self._backtest_analyzer
    
    @property
    def regime_analyzer(self) -> GlobalRegimeAnalyzer:
        """Ленивая инициализация GlobalRegimeAnalyzer."""
        if self._regime_analyzer is None:
            # Временное решение: создаем через условный импорт
            # В будущем это должно передаваться через DI
            try:
                from ...infrastructure.db import DB as ConcreteDB
                from ...infrastructure.market_data_service import MarketDataService as ConcreteMarketData
                
                if isinstance(self.db, ConcreteDB):
                    concrete_db = self.db
                    market_data = ConcreteMarketData(concrete_db)
                    self._regime_analyzer = GlobalRegimeAnalyzer(concrete_db, market_data)
                else:
                    raise ValueError("GlobalRegimeAnalyzer requires concrete DB implementation")
            except (ImportError, ValueError) as e:
                logger.error(f"Failed to create GlobalRegimeAnalyzer: {e}")
                raise
        return self._regime_analyzer
        
        # Кэш для калибровок (чтобы не пересчитывать каждый раз)
        self._calibration_cache: Dict[str, float] = {}
        self._cache_ttl = 3600  # 1 час
    
    def get_effective_pump_threshold(
        self,
        symbol: str,
        regime: Optional[GlobalRegime] = None,
        min_hit_rate: float = 0.55,
        min_avg_return: float = 2.0
    ) -> float:
        """
        Получить эффективный порог pump_score для символа и режима.
        
        Args:
            symbol: Символ монеты
            regime: Режим рынка (если None, используется текущий)
            min_hit_rate: Минимальный hit rate для приемлемого порога (по умолчанию 55%)
            min_avg_return: Минимальная средняя доходность для приемлемого порога (по умолчанию 2%)
        
        Returns:
            Порог pump_score (0.0 - 1.0)
        """
        # Определяем режим если не указан
        if regime is None:
            regime_snapshot = self.regime_analyzer.analyze_current_regime()
            regime = regime_snapshot.regime
        
        # Проверяем кэш
        cache_key = f"{symbol}_{regime.value}"
        if cache_key in self._calibration_cache:
            return self._calibration_cache[cache_key]
        
        # Получаем статистику по символу и режиму
        stats = self.backtest_analyzer.analyze_per_asset_regime(
            symbol=symbol,
            regime=regime,
            hours=24
        )
        
        # Пробуем найти порог по комбинации symbol + regime
        threshold = self._find_threshold_from_stats(
            stats,
            symbol,
            regime,
            min_hit_rate,
            min_avg_return
        )
        
        # Если не нашли по symbol+regime, пробуем по regime
        if threshold is None:
            threshold = self._find_threshold_from_regime_stats(
                stats,
                regime,
                min_hit_rate,
                min_avg_return
            )
        
        # Если все еще не нашли, используем дефолтный порог
        if threshold is None:
            threshold = self._get_default_threshold(regime)
        
        # Кэшируем результат
        self._calibration_cache[cache_key] = threshold
        
        return threshold
    
    def _find_threshold_from_stats(
        self,
        stats: Dict,
        symbol: str,
        regime: GlobalRegime,
        min_hit_rate: float,
        min_avg_return: float
    ) -> Optional[float]:
        """Найти порог из статистики по symbol+regime."""
        symbol_regime_stats = stats.get('by_symbol_regime', {})
        
        # Ищем статистику для конкретной комбинации
        key = (symbol, regime.value)
        if key in symbol_regime_stats:
            stat = symbol_regime_stats[key]
            if stat['count'] >= 10:  # Минимум 10 снимков для статистической значимости
                if stat['hit_rate'] >= min_hit_rate and stat['avg_return'] >= min_avg_return:
                    # Используем бины pump_score для определения точного порога
                    return self._find_threshold_from_bins(symbol, regime, min_hit_rate, min_avg_return)
        
        return None
    
    def _find_threshold_from_regime_stats(
        self,
        stats: Dict,
        regime: GlobalRegime,
        min_hit_rate: float,
        min_avg_return: float
    ) -> Optional[float]:
        """Найти порог из статистики по regime."""
        regime_stats = stats.get('by_regime', {})
        
        if regime.value in regime_stats:
            stat = regime_stats[regime.value]
            if stat['count'] >= 20:  # Больше данных для режима в целом
                if stat['hit_rate'] >= min_hit_rate and stat['avg_return'] >= min_avg_return:
                    return self._find_threshold_from_bins(None, regime, min_hit_rate, min_avg_return)
        
        return None
    
    def _find_threshold_from_bins(
        self,
        symbol: Optional[str],
        regime: GlobalRegime,
        min_hit_rate: float,
        min_avg_return: float
    ) -> float:
        """Найти порог из бинов pump_score."""
        bins_stats = self.backtest_analyzer.analyze_pump_score_bins_by_regime(
            symbol=symbol,
            regime=regime,
            bins=20  # Более детальное разбиение
        )
        
        # Ищем самый низкий bin, который удовлетворяет критериям
        best_threshold = 0.7  # Дефолтный порог
        
        for bin_name, bin_stat in sorted(bins_stats.items(), key=lambda x: x[1]['pump_score_range'][0]):
            if bin_stat['count'] >= 5:  # Минимум данных
                if bin_stat['hit_rate'] >= min_hit_rate and bin_stat['avg_return'] >= min_avg_return:
                    # Используем нижнюю границу бина как порог
                    best_threshold = bin_stat['pump_score_range'][0]
                    break
        
        return best_threshold
    
    def _get_default_threshold(self, regime: GlobalRegime) -> float:
        """Получить дефолтный порог в зависимости от режима."""
        # Адаптируем порог в зависимости от режима
        base_threshold = 0.7
        
        if regime == GlobalRegime.RISK_OFF:
            # В RISK_OFF повышаем требования
            return min(base_threshold + 0.1, 0.9)
        elif regime == GlobalRegime.PANIC:
            # В панике еще выше требования
            return min(base_threshold + 0.15, 0.95)
        elif regime == GlobalRegime.RISK_ON:
            # В RISK_ON можно немного снизить
            return max(base_threshold - 0.05, 0.6)
        elif regime == GlobalRegime.ALT_SEASON:
            # В сезон альтов можно снизить для альтов
            return max(base_threshold - 0.08, 0.6)
        else:
            return base_threshold
    
    def calibrate_p_up_by_setup_type(
        self,
        raw_p_up: float,
        symbol: str,
        timeframe: str,
        horizon: int,
        setup_type: Optional[str] = None,
        grade: Optional[str] = None
    ) -> float:
        """
        Калибровать p_up с учетом типа сетапа и Grade.
        
        Калибровка раздельно по:
        - setup_type: SOFT, IMPULSE, NEEDS_CONFIRMATION, NEUTRAL
        - grade: A, B, C, D
        
        Args:
            raw_p_up: Сырое значение p_up
            symbol: Символ
            timeframe: Таймфрейм
            horizon: Горизонт прогноза
            setup_type: Тип сетапа (опционально)
            grade: Grade сетапа (опционально)
        
        Returns:
            Откалиброванное значение p_up
        """
        try:
            # Получаем исторические данные с фильтрацией по setup_type и grade
            cur = self.db.conn.cursor()
            
            # Пробуем получить данные из forecast_history с метаданными
            # Если в БД есть колонки setup_type и grade, используем их
            query = """
                SELECT probability_up, predicted_return, timestamp_ms
                FROM forecast_history
                WHERE symbol = ? AND timeframe = ? AND horizon = ?
            """
            params = [symbol, timeframe, horizon]
            
            # Добавляем фильтры, если есть setup_type или grade
            # (предполагаем, что эти данные могут быть в JSON метаданных или отдельных колонках)
            # Пока используем простую версию без фильтров, но структура готова для расширения
            
            cur.execute(query + " ORDER BY timestamp_ms DESC LIMIT 1000", params)
            rows = cur.fetchall()
            
            if len(rows) < 50:
                # Fallback на обычную калибровку
                return self.calibrate_p_up(raw_p_up, symbol, timeframe, horizon)
            
            # Определяем бинки
            bins = {
                "0.5-0.6": (0.5, 0.6),
                "0.6-0.7": (0.6, 0.7),
                "0.7-0.8": (0.7, 0.8),
                "0.8-0.9": (0.8, 0.9),
                "0.9-1.0": (0.9, 1.0),
            }
            
            # Вычисляем статистику для каждого бина
            bin_stats = {}
            for bin_name, (bin_min, bin_max) in bins.items():
                bin_rows = [
                    r for r in rows
                    if bin_min <= r[0] < bin_max  # probability_up в диапазоне бина
                ]
                
                if len(bin_rows) < 10:
                    continue
                
                # Вычисляем hit-rate и E[R]
                hits = sum(1 for r in bin_rows if r[1] > 0)  # predicted_return > 0
                hit_rate = hits / len(bin_rows) if bin_rows else 0.5
                avg_return = sum(r[1] for r in bin_rows) / len(bin_rows) if bin_rows else 0.0
                
                # Вычисляем Expected Shortfall (ES) - средний убыток в худших 10%
                returns = [r[1] for r in bin_rows]
                returns_sorted = sorted(returns)
                worst_10_pct = int(len(returns_sorted) * 0.1)
                if worst_10_pct > 0:
                    es = sum(returns_sorted[:worst_10_pct]) / worst_10_pct
                else:
                    es = 0.0
                
                bin_stats[bin_name] = {
                    "count": len(bin_rows),
                    "hit_rate": hit_rate,
                    "avg_return": avg_return,
                    "expected_shortfall": es,
                }
            
            # Определяем целевой бин
            target_bin = None
            for bin_name, (bin_min, bin_max) in bins.items():
                if bin_min <= raw_p_up < bin_max:
                    target_bin = bin_name
                    break
            
            if target_bin is None:
                if raw_p_up < 0.5:
                    target_bin = "0.5-0.6"
                else:
                    target_bin = "0.9-1.0"
            
            # Применяем калибровку
            if target_bin in bin_stats:
                bin_stat = bin_stats[target_bin]
                actual_hit_rate = bin_stat["hit_rate"]
                expected_hit_rate = (bins[target_bin][0] + bins[target_bin][1]) / 2.0
                calibration_factor = actual_hit_rate / expected_hit_rate if expected_hit_rate > 0 else 1.0
                
                # Дополнительная корректировка на основе E[R] и ES
                # Если E[R] низкий или ES очень негативный, снижаем confidence
                if bin_stat["avg_return"] < 0:
                    calibration_factor *= 0.9  # Снижаем на 10% если средний return отрицательный
                if bin_stat["expected_shortfall"] < -0.05:  # ES хуже -5%
                    calibration_factor *= 0.85  # Снижаем еще на 15%
                
                calibrated_p_up = max(0.0, min(1.0, raw_p_up * calibration_factor))
                
                logger.debug(
                    f"Calibrated p_up by setup: {raw_p_up:.3f} -> {calibrated_p_up:.3f} "
                    f"(bin: {target_bin}, hit_rate: {actual_hit_rate:.3f}, E[R]: {bin_stat['avg_return']:.4f}, ES: {bin_stat['expected_shortfall']:.4f})"
                )
                return calibrated_p_up
            
            return raw_p_up
        except Exception as e:
            logger.warning(f"Failed to calibrate p_up by setup type: {e}", exc_info=True)
            return self.calibrate_p_up(raw_p_up, symbol, timeframe, horizon)
    
    def get_setup_type_stats(
        self,
        symbol: str,
        timeframe: str,
        horizon: int,
        setup_type: Optional[str] = None,
        grade: Optional[str] = None,
        min_samples: int = 20
    ) -> Optional[Dict]:
        """
        Получить статистику по типу сетапа: E[R], ES, hit-rate.
        
        Args:
            symbol: Символ
            timeframe: Таймфрейм
            horizon: Горизонт прогноза
            setup_type: Тип сетапа (опционально)
            grade: Grade сетапа (опционально)
            min_samples: Минимальное количество образцов
        
        Returns:
            Dict с статистикой или None
        """
        try:
            cur = self.db.conn.cursor()
            query = """
                SELECT probability_up, predicted_return, timestamp_ms
                FROM forecast_history
                WHERE symbol = ? AND timeframe = ? AND horizon = ?
            """
            params = [symbol, timeframe, horizon]
            
            # TODO: Добавить фильтрацию по setup_type и grade, когда эти данные будут в БД
            # Пока используем все данные
            
            cur.execute(query + " ORDER BY timestamp_ms DESC LIMIT 1000", params)
            rows = cur.fetchall()
            
            if len(rows) < min_samples:
                return None
            
            # Вычисляем общую статистику
            returns = [r[1] for r in rows]  # predicted_return
            
            # E[R] - средний return
            avg_return = sum(returns) / len(returns) if returns else 0.0
            
            # std_R - стандартное отклонение
            if len(returns) > 1:
                import numpy as np
                std_return = float(np.std(returns))
            else:
                std_return = 0.0
            
            # Hit-rate
            hits = sum(1 for r in returns if r > 0)
            hit_rate = hits / len(returns) if returns else 0.5
            
            # Expected Shortfall (ES) - средний убыток в худших 10%
            returns_sorted = sorted(returns)
            worst_10_pct = max(1, int(len(returns_sorted) * 0.1))
            es = sum(returns_sorted[:worst_10_pct]) / worst_10_pct if worst_10_pct > 0 else 0.0
            
            # Value at Risk (VaR) - 5-й перцентиль
            if len(returns_sorted) > 0:
                var_5 = returns_sorted[int(len(returns_sorted) * 0.05)] if len(returns_sorted) > 5 else returns_sorted[0]
            else:
                var_5 = 0.0
            
            return {
                "count": len(rows),
                "avg_return": avg_return,
                "std_return": std_return,
                "hit_rate": hit_rate,
                "expected_shortfall": es,
                "var_5": var_5,
                "setup_type": setup_type,
                "grade": grade,
            }
        except Exception as e:
            logger.warning(f"Failed to get setup type stats: {e}", exc_info=True)
            return None
    
    def calibrate_p_up(
        self,
        raw_p_up: float,
        symbol: str,
        timeframe: str,
        horizon: int = 24
    ) -> float:
        """
        Калибровать p_up на основе исторической статистики через бинки.
        
        Бинки: 0.5-0.6, 0.6-0.7, 0.7-0.8, 0.8-0.9, 0.9-1.0
        
        Args:
            raw_p_up: Сырое значение p_up из модели
            symbol: Символ
            timeframe: Таймфрейм
            horizon: Горизонт прогноза
        
        Returns:
            Откалиброванное значение p_up
        """
        try:
            # Получаем исторические данные из forecast_history
            cur = self.db.conn.cursor()
            cur.execute("""
                SELECT probability_up, predicted_return, timestamp_ms
                FROM forecast_history
                WHERE symbol = ? AND timeframe = ? AND horizon = ?
                ORDER BY timestamp_ms DESC
                LIMIT 1000
            """, (symbol, timeframe, horizon))
            
            rows = cur.fetchall()
            if len(rows) < 50:  # Минимум данных для калибровки
                logger.debug(f"Not enough historical data for calibration: {len(rows)} rows")
                return raw_p_up
            
            # Определяем бинки
            bins = {
                "0.5-0.6": (0.5, 0.6),
                "0.6-0.7": (0.6, 0.7),
                "0.7-0.8": (0.7, 0.8),
                "0.8-0.9": (0.8, 0.9),
                "0.9-1.0": (0.9, 1.0),
            }
            
            # Вычисляем фактический hit-rate для каждого бина
            bin_stats = {}
            for bin_name, (bin_min, bin_max) in bins.items():
                bin_rows = [
                    r for r in rows
                    if bin_min <= r[1] < bin_max  # probability_up в диапазоне бина
                ]
                
                if len(bin_rows) < 10:  # Минимум 10 образцов для статистики
                    continue
                
                # Вычисляем hit-rate (правильное направление)
                # Для этого нужно сравнить predicted_return с фактическим результатом
                # Упрощенно: считаем, что если predicted_return > 0, то прогноз был "вверх"
                hits = sum(1 for r in bin_rows if r[2] > 0)  # predicted_return > 0
                hit_rate = hits / len(bin_rows) if bin_rows else 0.5
                
                bin_stats[bin_name] = {
                    "count": len(bin_rows),
                    "hit_rate": hit_rate,
                    "avg_return": sum(r[2] for r in bin_rows) / len(bin_rows) if bin_rows else 0.0,
                }
            
            # Определяем, в какой бин попадает raw_p_up
            target_bin = None
            for bin_name, (bin_min, bin_max) in bins.items():
                if bin_min <= raw_p_up < bin_max:
                    target_bin = bin_name
                    break
            
            if target_bin is None:
                # Если выходит за пределы, используем ближайший бин
                if raw_p_up < 0.5:
                    target_bin = "0.5-0.6"
                else:
                    target_bin = "0.9-1.0"
            
            # Если есть статистика для целевого бина, применяем калибровку
            if target_bin in bin_stats:
                bin_stat = bin_stats[target_bin]
                actual_hit_rate = bin_stat["hit_rate"]
                
                # Простая калибровка: корректируем p_up на основе разницы между ожидаемым и фактическим hit-rate
                # Если фактический hit-rate ниже ожидаемого, снижаем p_up
                expected_hit_rate = (bins[target_bin][0] + bins[target_bin][1]) / 2.0
                calibration_factor = actual_hit_rate / expected_hit_rate if expected_hit_rate > 0 else 1.0
                
                # Применяем калибровку (ограничиваем диапазон 0-1)
                calibrated_p_up = max(0.0, min(1.0, raw_p_up * calibration_factor))
                
                logger.debug(f"Calibrated p_up: {raw_p_up:.3f} -> {calibrated_p_up:.3f} (bin: {target_bin}, factor: {calibration_factor:.3f})")
                return calibrated_p_up
            
            # Если статистики нет, возвращаем исходное значение
            return raw_p_up
        
        except Exception as e:
            logger.warning(f"Failed to calibrate p_up: {e}", exc_info=True)
            return raw_p_up
    
    def get_reliability_score(
        self,
        pattern_id: str,
        min_samples: int = 10
    ) -> Optional[float]:
        """
        Получить reliability score для паттерна.
        
        Args:
            pattern_id: ID паттерна (hash по phase+trend+structure+regime)
            min_samples: Минимальное количество образцов для расчета
        
        Returns:
            Reliability score (0.0 - 1.0) или None если недостаточно данных
        """
        # Получаем все снимки с этим pattern_id
        snapshots = self.diagnostics_repo.get_snapshots(limit=10000)
        
        matching_snapshots = [
            s for s in snapshots
            if s.get('extra_metrics', {}).get('pattern_id') == pattern_id
        ]
        
        if len(matching_snapshots) < min_samples:
            return None
    
    def get_reliability_score_with_samples(
        self,
        pattern_id: str,
        min_samples: int = 10
    ) -> tuple[Optional[float], int]:
        """
        Получить reliability score и количество образцов для паттерна.
        
        Args:
            pattern_id: ID паттерна (hash по phase+trend+structure+regime)
            min_samples: Минимальное количество образцов для расчета
        
        Returns:
            Tuple (reliability_score, num_samples) или (None, num_samples) если недостаточно данных
        """
        # Получаем все снимки с этим pattern_id
        snapshots = self.diagnostics_repo.get_snapshots(limit=10000)
        
        matching_snapshots = [
            s for s in snapshots
            if s.get('extra_metrics', {}).get('pattern_id') == pattern_id
        ]
        
        num_samples = len(matching_snapshots)
        
        if num_samples < min_samples:
            return None, num_samples
        
        # Вычисляем доходность для каждого снимка
        returns = []
        for snapshot in matching_snapshots:
            ret = self.backtest_analyzer.calculate_returns(
                snapshot['symbol'],
                snapshot['timeframe'],
                snapshot['timestamp'],
                hours=24
            )
            if ret is not None:
                returns.append(ret)
        
        if len(returns) < min_samples:
            return None
        
        # Reliability = стабильность результатов
        # Комбинация hit_rate и консистентности доходности
        hit_rate = sum(1 for r in returns if r > 0) / len(returns)
        avg_return = np.mean(returns)
        std_return = np.std(returns)
        
        # Нормализуем std_return (чем меньше разброс, тем выше reliability)
        # Предполагаем, что std_return в диапазоне 0-20%
        normalized_consistency = max(0, 1 - (std_return / 20.0))
        
        # Reliability = взвешенная комбинация hit_rate и консистентности
        reliability = (hit_rate * 0.6) + (normalized_consistency * 0.4)
        
        # Учитываем среднюю доходность (если доходность отрицательная, снижаем reliability)
        if avg_return < 0:
            reliability *= 0.5
        
        return min(max(reliability, 0.0), 1.0)
    
    def get_reliability_score_with_samples(
        self,
        pattern_id: str,
        min_samples: int = 10
    ) -> tuple[Optional[float], int]:
        """
        Получить reliability score и количество образцов для паттерна.
        
        Args:
            pattern_id: ID паттерна (hash по phase+trend+structure+regime)
            min_samples: Минимальное количество образцов для расчета
        
        Returns:
            Tuple (reliability_score, num_samples) или (None, num_samples) если недостаточно данных
        """
        # Получаем все снимки с этим pattern_id
        snapshots = self.diagnostics_repo.get_snapshots(limit=10000)
        
        matching_snapshots = [
            s for s in snapshots
            if s.get('extra_metrics', {}).get('pattern_id') == pattern_id
        ]
        
        num_samples = len(matching_snapshots)
        
        if num_samples < min_samples:
            return None, num_samples
        
        # Вычисляем доходность для каждого снимка
        returns = []
        for snapshot in matching_snapshots:
            ret = self.backtest_analyzer.calculate_returns(
                snapshot['symbol'],
                snapshot['timeframe'],
                snapshot['timestamp'],
                hours=24
            )
            if ret is not None:
                returns.append(ret)
        
        if len(returns) < min_samples:
            return None, num_samples
        
        # Reliability = стабильность результатов
        # Комбинация hit_rate и консистентности доходности
        hit_rate = sum(1 for r in returns if r > 0) / len(returns)
        avg_return = np.mean(returns)
        std_return = np.std(returns)
        
        # Нормализуем std_return (чем меньше разброс, тем выше reliability)
        # Предполагаем, что std_return в диапазоне 0-20%
        normalized_consistency = max(0, 1 - (std_return / 20.0))
        
        # Reliability = взвешенная комбинация hit_rate и консистентности
        reliability = (hit_rate * 0.6) + (normalized_consistency * 0.4)
        
        # Учитываем среднюю доходность (если доходность отрицательная, снижаем reliability)
        if avg_return < 0:
            reliability *= 0.5
        
        reliability_score = min(max(reliability, 0.0), 1.0)
        return reliability_score, num_samples
    
    def clear_cache(self):
        """Очистить кэш калибровок."""
        self._calibration_cache.clear()


