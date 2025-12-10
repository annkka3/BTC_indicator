# app/application/services/diagnostics_logging_service.py
"""
Сервис для периодического логирования диагностик Market Doctor.

Выполняет:
1. Периодический вызов Market Doctor для BTC и ETH
2. Логирование диагностик
3. Вычисление результатов через X баров/часов
"""

import asyncio
import logging
from typing import Dict, Optional
from datetime import datetime, timezone, timedelta
import pandas as pd

from ...infrastructure.db import DB
from ...infrastructure.market_data_service import MarketDataService
from ...domain.market_diagnostics.diagnostics_logger import DiagnosticsLogger
from ...domain.market_diagnostics.report_builder import ReportBuilder
from ...domain.market_diagnostics.analyzer import MarketAnalyzer
from ...domain.market_diagnostics.scoring_engine import ScoringEngine
from ...domain.market_diagnostics.trade_planner import TradePlanner
from ...domain.market_diagnostics.indicators import IndicatorCalculator
from ...domain.market_diagnostics.features import FeatureExtractor
from ...domain.market_regime.global_regime_analyzer import GlobalRegimeAnalyzer

logger = logging.getLogger(__name__)


class DiagnosticsLoggingService:
    """Сервис для логирования диагностик."""
    
    def __init__(self, db: DB, market_data_service: MarketDataService):
        """
        Args:
            db: Database instance
            market_data_service: Market data service
        """
        self.db = db
        self.market_data_service = market_data_service
        self.diagnostics_logger = DiagnosticsLogger(db)
        self.report_builder = ReportBuilder()
        self.market_analyzer = MarketAnalyzer()
        self.scoring_engine = ScoringEngine()
        self.trade_planner = TradePlanner()
        self.indicator_calculator = IndicatorCalculator()
        self.feature_extractor = FeatureExtractor()
        self.global_regime_analyzer = GlobalRegimeAnalyzer(db)
    
    async def log_diagnostics_for_symbol(
        self,
        symbol: str,
        timeframes: list[str] = ["1h", "4h", "1d"]
    ) -> Dict[str, int]:
        """
        Записать диагностики для символа по указанным таймфреймам.
        
        Args:
            symbol: Символ (например, "BTCUSDT")
            timeframes: Список таймфреймов
        
        Returns:
            Словарь {timeframe: snapshot_id}
        """
        snapshot_ids = {}
        
        try:
            # Получаем текущую цену
            current_price = await self._get_current_price(symbol)
            if not current_price:
                logger.warning(f"Could not get current price for {symbol}")
                return snapshot_ids
            
            # Получаем глобальный режим
            global_regime = self.global_regime_analyzer.analyze_current_regime()
            
            # Собираем диагностики для всех таймфреймов
            diagnostics: Dict[str, any] = {}
            indicators_dict: Dict[str, Dict] = {}
            features_dict: Dict[str, Dict] = {}
            derivatives_dict: Dict[str, Dict] = {}
            df_dict: Dict[str, any] = {}  # Сохраняем df для каждого TF
            
            for tf in timeframes:
                try:
                    # Получаем данные
                    df = await self._get_ohlcv_data(symbol, tf)
                    if df is None or len(df) < 100:
                        logger.warning(f"Not enough data for {symbol} {tf}")
                        continue
                    
                    df_dict[tf] = df  # Сохраняем df для использования в trade planner
                    
                    # Вычисляем индикаторы
                    indicators = self.indicator_calculator.calculate_all(df)
                    indicators_dict[tf] = indicators
                    
                    # Получаем деривативы (упрощённо)
                    derivatives = await self._get_derivatives(symbol)
                    derivatives_dict[tf] = derivatives
                    
                    # Извлекаем признаки (нужны indicators и derivatives)
                    features = self.feature_extractor.extract_features(df, indicators, derivatives)
                    features_dict[tf] = features
                    
                    # Анализируем рынок
                    diag = self.market_analyzer.analyze(
                        symbol=symbol,
                        timeframe=tf,
                        df=df,
                        indicators=indicators,
                        features=features,
                        derivatives=derivatives
                    )
                    diagnostics[tf] = diag
                    
                except Exception as e:
                    logger.error(f"Error processing {symbol} {tf}: {e}", exc_info=True)
                    continue
            
            if not diagnostics:
                return snapshot_ids
            
            # Для каждого таймфрейма создаём отчёт и логируем
            for tf in timeframes:
                if tf not in diagnostics:
                    continue
                
                try:
                    # Строим multi-TF score
                    per_tf_scores = {}
                    for diag_tf, diag in diagnostics.items():
                        score = self.scoring_engine.score_timeframe(
                            diag,
                            indicators_dict.get(diag_tf, {}),
                            features_dict.get(diag_tf, {}),
                            derivatives_dict.get(diag_tf, {}),
                            tf,
                            target_tf=tf
                        )
                        per_tf_scores[diag_tf] = score
                    
                    multi_tf_score = self.scoring_engine.aggregate_multi_tf(per_tf_scores, tf)
                    
                    # Строим trade plan
                    target_diag = diagnostics[tf]
                    target_df = df_dict[tf]  # Используем уже полученный df
                    target_indicators = indicators_dict[tf]
                    trade_plan = self.trade_planner.build_plan(
                        diag=target_diag,
                        df=target_df,
                        indicators=target_indicators,
                        mode="auto",
                        regime=global_regime
                    )
                    
                    # Строим compact report
                    compact_report = self.report_builder.build_compact_report(
                        symbol=symbol,
                        target_tf=tf,
                        diagnostics=diagnostics,
                        indicators=indicators_dict,
                        features=features_dict,
                        derivatives=derivatives_dict,
                        current_price=current_price,
                        trade_plan=trade_plan
                    )
                    
                    # Логируем снимок
                    snapshot_id = self.diagnostics_logger.log_snapshot(
                        symbol=symbol,
                        timeframe=tf,
                        multi_tf_score=multi_tf_score,
                        diagnostics=diagnostics,
                        compact_report=compact_report,
                        current_price=current_price
                    )
                    
                    snapshot_ids[tf] = snapshot_id
                    logger.info(f"Logged snapshot {snapshot_id} for {symbol} {tf}")
                    
                except Exception as e:
                    logger.error(f"Error logging snapshot for {symbol} {tf}: {e}", exc_info=True)
                    continue
        
        except Exception as e:
            logger.error(f"Error in log_diagnostics_for_symbol for {symbol}: {e}", exc_info=True)
        
        return snapshot_ids
    
    async def compute_results_for_snapshots(
        self,
        symbol: str,
        timeframe: str,
        horizon_bars: int = 4,
        horizon_hours: float = 24.0
    ):
        """
        Вычислить результаты для снимков, которые ещё не имеют результатов.
        
        Args:
            symbol: Символ
            timeframe: Таймфрейм
            horizon_bars: Горизонт в барах
            horizon_hours: Горизонт в часах
        """
        try:
            # Получаем снимки без результатов
            snapshots = self.diagnostics_logger.get_snapshots(
                symbol=symbol,
                timeframe=timeframe
            )
            
            for snapshot in snapshots:
                # Проверяем, есть ли уже результат
                existing_results = self.diagnostics_logger.get_results_for_snapshot(snapshot['id'])
                has_result = any(
                    r['horizon_bars'] == horizon_bars and abs(r['horizon_hours'] - horizon_hours) < 0.1
                    for r in existing_results
                )
                
                if has_result:
                    continue
                
                # Вычисляем результат
                result = await self._compute_result(
                    snapshot,
                    symbol,
                    timeframe,
                    horizon_bars,
                    horizon_hours
                )
                
                if result:
                    self.diagnostics_logger.log_result(
                        snapshot_id=snapshot['id'],
                        horizon_bars=horizon_bars,
                        horizon_hours=horizon_hours,
                        **result
                    )
                    logger.info(f"Computed result for snapshot {snapshot['id']}")
        
        except Exception as e:
            logger.error(f"Error computing results: {e}", exc_info=True)
    
    async def _compute_result(
        self,
        snapshot: Dict,
        symbol: str,
        timeframe: str,
        horizon_bars: int,
        horizon_hours: float
    ) -> Optional[Dict]:
        """
        Вычислить результат для снимка.
        
        Args:
            snapshot: Снимок диагностики
            symbol: Символ
            timeframe: Таймфрейм
            horizon_bars: Горизонт в барах
            horizon_hours: Горизонт в часах
        
        Returns:
            Словарь с результатами или None
        """
        try:
            entry_price = snapshot.get('current_price')
            if not entry_price:
                return None
            
            # Получаем исторические данные
            df = await self._get_ohlcv_data(symbol, timeframe)
            if df is None or len(df) == 0:
                return None
            
            # Находим индекс входа по snapshot timestamp
            snapshot_ts = snapshot['timestamp_ms']
            entry_idx = None
            
            # Нормализуем DataFrame: убеждаемся, что есть колонка ts или индекс ts
            df_normalized = df.copy()
            
            # Если ts в индексе (DatetimeIndex)
            if isinstance(df_normalized.index, pd.DatetimeIndex):
                # Конвертируем индекс в миллисекунды
                df_normalized['ts_ms'] = df_normalized.index.astype('int64') // 1_000_000
            # Если ts в колонке
            elif 'ts' in df_normalized.columns:
                ts_col = df_normalized['ts']
                # Конвертируем в миллисекунды в зависимости от типа
                if pd.api.types.is_datetime64_any_dtype(ts_col):
                    df_normalized['ts_ms'] = ts_col.astype('int64') // 1_000_000
                elif pd.api.types.is_integer_dtype(ts_col):
                    # Если уже в миллисекундах
                    df_normalized['ts_ms'] = ts_col
                else:
                    # Пытаемся преобразовать
                    try:
                        ts_dt = pd.to_datetime(ts_col, utc=True)
                        df_normalized['ts_ms'] = ts_dt.astype('int64') // 1_000_000
                    except Exception:
                        logger.warning(f"Could not parse ts column in df for {symbol} {timeframe}")
                        # Fallback: используем последний бар
                        entry_idx = len(df_normalized) - 1
            else:
                # Нет ts ни в индексе, ни в колонках - используем последний бар как fallback
                logger.warning(f"No timestamp found in df for {symbol} {timeframe}, using last bar")
                entry_idx = len(df_normalized) - 1
            
            # Если entry_idx ещё не найден, ищем по ts_ms
            if entry_idx is None:
                # Сортируем по времени (если ещё не отсортировано)
                df_normalized = df_normalized.sort_values('ts_ms').reset_index(drop=True)
                
                # Находим первый бар с ts_ms >= snapshot_ts
                candidates = df_normalized.index[df_normalized['ts_ms'] >= snapshot_ts]
                if len(candidates) > 0:
                    entry_idx = int(candidates[0])
                else:
                    # Если snapshot_ts больше всех timestamp в df, используем последний бар
                    logger.warning(f"Snapshot timestamp {snapshot_ts} is after all bars in df, using last bar")
                    entry_idx = len(df_normalized) - 1
            
            # Проверяем, что есть достаточно данных для горизонта
            if entry_idx is None or entry_idx + horizon_bars >= len(df_normalized):
                logger.warning(f"Not enough data for horizon: entry_idx={entry_idx}, df_len={len(df_normalized)}, horizon_bars={horizon_bars}")
                return None
            
            # Получаем цены на горизонте (используем нормализованный df)
            horizon_df = df_normalized.iloc[entry_idx:entry_idx + horizon_bars + 1]
            
            highest_price = horizon_df['high'].max()
            lowest_price = horizon_df['low'].min()
            price_at_horizon = horizon_df.iloc[-1]['close']
            
            # Вычисляем R
            bias = snapshot.get('bias')
            bullish_trigger = snapshot.get('bullish_trigger_level')
            bearish_trigger = snapshot.get('bearish_trigger_level')
            invalidation_level = snapshot.get('invalidation_level')
            
            # Определяем направление и уровни
            if bias == 'LONG':
                # Для лонга: TP выше, SL ниже
                tp_level = bullish_trigger or invalidation_level or entry_price * 1.02
                sl_level = invalidation_level or entry_price * 0.98
                
                max_r_up = (highest_price - entry_price) / (entry_price - sl_level) if entry_price > sl_level else None
                max_r_down = (entry_price - lowest_price) / (entry_price - sl_level) if entry_price > sl_level else None
                r_at_horizon = (price_at_horizon - entry_price) / (entry_price - sl_level) if entry_price > sl_level else None
                
                hit_tp = highest_price >= tp_level if tp_level else False
                hit_sl = lowest_price <= sl_level if sl_level else False
            
            elif bias == 'SHORT':
                # Для шорта: TP ниже, SL выше
                tp_level = bearish_trigger or invalidation_level or entry_price * 0.98
                sl_level = invalidation_level or entry_price * 1.02
                
                max_r_up = (sl_level - lowest_price) / (sl_level - entry_price) if sl_level > entry_price else None
                max_r_down = (highest_price - sl_level) / (sl_level - entry_price) if sl_level > entry_price else None
                r_at_horizon = (entry_price - price_at_horizon) / (sl_level - entry_price) if sl_level > entry_price else None
                
                hit_tp = lowest_price <= tp_level if tp_level else False
                hit_sl = highest_price >= sl_level if sl_level else False
            
            else:
                # NO_TRADE - не вычисляем R
                return None
            
            return {
                'max_r_up': max_r_up,
                'max_r_down': max_r_down,
                'hit_tp': hit_tp,
                'hit_sl': hit_sl,
                'r_at_horizon': r_at_horizon,
                'entry_price': entry_price,
                'price_at_horizon': price_at_horizon,
                'highest_price': highest_price,
                'lowest_price': lowest_price
            }
        
        except Exception as e:
            logger.error(f"Error computing result: {e}", exc_info=True)
            return None
    
    async def _get_current_price(self, symbol: str) -> Optional[float]:
        """Получить текущую цену с биржи."""
        try:
            # Получаем актуальную текущую цену с Binance API
            from ...infrastructure.market_data import binance_spot_price
            symbol_usdt = f"{symbol}USDT" if not symbol.endswith("USDT") else symbol
            return binance_spot_price(symbol_usdt)
        except Exception as e:
            logger.debug(f"Failed to get current price from Binance API for {symbol}: {e}, falling back to last candle close")
            try:
                # Fallback: получаем последний бар из БД
                df = await self._get_ohlcv_data(symbol, "1h")
                if df is not None and len(df) > 0:
                    return float(df.iloc[-1]['close'])
            except Exception as fallback_error:
                logger.error(f"Error getting current price for {symbol} (both API and DB failed): {fallback_error}")
            return None
    
    async def _get_ohlcv_data(self, symbol: str, timeframe: str):
        """Получить OHLCV данные."""
        try:
            # Используем market_data_service
            metric = symbol.replace("USDT", "").replace("BTC", "BTC")
            df = await self.market_data_service.get_ohlcv(metric, timeframe, limit=500)
            # Конвертируем в формат, ожидаемый анализатором (с колонками high, low, close, volume)
            if df is not None and len(df) > 0:
                # Убеждаемся, что колонки названы правильно
                if 'h' in df.columns:
                    df = df.rename(columns={'h': 'high', 'l': 'low', 'c': 'close', 'v': 'volume', 'o': 'open'})
                return df
            return None
        except Exception as e:
            logger.error(f"Error getting OHLCV data for {symbol} {timeframe}: {e}")
            return None
    
    async def _get_derivatives(self, symbol: str) -> Dict:
        """Получить данные деривативов."""
        # Упрощённо возвращаем пустой словарь
        # В реальности нужно получать funding rate, OI и т.д.
        return {}


async def run_periodic_logging(
    db: DB,
    market_data_service: MarketDataService,
    interval_minutes: int = 30
):
    """
    Запустить периодическое логирование диагностик.
    
    Args:
        db: Database instance
        market_data_service: Market data service
        interval_minutes: Интервал в минутах
    """
    service = DiagnosticsLoggingService(db, market_data_service)
    
    symbols = ["BTCUSDT", "ETHUSDT"]
    timeframes = ["1h", "4h", "1d"]
    
    while True:
        try:
            logger.info("Starting periodic diagnostics logging")
            
            for symbol in symbols:
                try:
                    snapshot_ids = await service.log_diagnostics_for_symbol(symbol, timeframes)
                    logger.info(f"Logged diagnostics for {symbol}: {snapshot_ids}")
                    
                    # Вычисляем результаты для старых снимков
                    for tf in timeframes:
                        await service.compute_results_for_snapshots(
                            symbol=symbol,
                            timeframe=tf,
                            horizon_bars=4,
                            horizon_hours=24.0
                        )
                
                except Exception as e:
                    logger.error(f"Error logging diagnostics for {symbol}: {e}", exc_info=True)
            
            logger.info(f"Waiting {interval_minutes} minutes until next logging cycle")
            await asyncio.sleep(interval_minutes * 60)
        
        except Exception as e:
            logger.error(f"Error in periodic logging: {e}", exc_info=True)
            await asyncio.sleep(60)  # Короткая пауза при ошибке

