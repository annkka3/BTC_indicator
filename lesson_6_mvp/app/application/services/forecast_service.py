# app/application/services/forecast_service.py
from ...utils.performance import measure_time_async
"""
Service for ML-based price forecasts.
"""

from typing import Dict, List, Optional
import logging
import numpy as np
from ...utils.performance import measure_time

logger = logging.getLogger("alt_forecast.services.forecast")


class ForecastService:
    """Сервис для генерации прогнозов с использованием ML."""
    
    def __init__(self, db):
        """
        Args:
            db: Database instance for accessing historical data
        """
        self.db = db
        self._forecast_cache = {}
        self._cache_ttl = 20 * 60  # 20 минут
        # Кэш моделей: (symbol, tf, horizon, model_type) -> model_data
        self._model_cache = {}
        self._model_cache_max_size = 10  # Максимум 10 моделей в кэше
    
    @measure_time
    def forecast_btc(
        self,
        timeframe: str = "1h",
        horizon: int = 24,
    ) -> Optional[Dict]:
        """
        Сгенерировать прогноз для BTC с использованием CatBoost модели.
        
        Args:
            timeframe: Таймфрейм (1h, 4h, 1d) - если передан "24h", нормализуется в "1d"
            horizon: Горизонт прогноза в барах
        
        Returns:
            Dict с прогнозом или None
        """
        # Нормализуем "24h" -> "1d" для совместимости с data_adapter
        if timeframe == "24h":
            timeframe = "1d"
        try:
            # Пробуем использовать CatBoost модель (из ноутбука)
            try:
                from ...ml.catboost_forecaster import forecast_with_catboost, HORIZON_MAP
                from ...ml.data_adapter import load_bars_from_project
                from ...ml.data_healthcheck import check_data_quality, filter_invalid_data
                
                # Маппинг таймфрейма на горизонт (для 5-минутных данных)
                # Если данные в боте 5-минутные, используем HORIZON_MAP
                # Если данные часовые, используем horizon напрямую
                horizon_for_model = HORIZON_MAP.get(timeframe, horizon)
                
                # Определяем тип модели (Extended для H=48)
                use_extended = (horizon_for_model == 48)
                model_type = "catboost_extended" if use_extended else "catboost"
                
                # Проверяем кэш моделей
                model_cache_key = ("BTC", "5m", horizon_for_model, model_type)
                cached_model = self._model_cache.get(model_cache_key)
                
                # Загружаем данные
                # Пробуем загрузить 5-минутные данные (как в ноутбуке)
                try:
                    df = load_bars_from_project("BTC", "5m", limit=5000)
                    
                    # Проверяем качество данных перед прогнозом
                    data_quality = check_data_quality(df, min_samples=100)
                    if not data_quality.is_valid:
                        logger.warning(f"Data quality issues: {data_quality.issues}")
                        if data_quality.warnings:
                            logger.warning(f"Data quality warnings: {data_quality.warnings}")
                        
                        # Фильтруем невалидные данные
                        df = filter_invalid_data(df, data_quality)
                        
                        # Если после фильтрации недостаточно данных, возвращаем None
                        if len(df) < 100:
                            logger.error(f"Insufficient valid data after filtering: {len(df)} rows")
                            return None
                    
                    # Используем 5-минутные данные с правильным горизонтом
                    # Передаём кэшированную модель, если есть
                    result = forecast_with_catboost(
                        df, "BTC", "5m", horizon_for_model, 
                        cached_model_data=cached_model
                    )
                    
                    # Если модель была загружена и её нет в кэше, сохраняем её
                    if result and "model_data" in result:
                        self._cache_model(model_cache_key, result["model_data"])
                except Exception:
                    # Если 5-минутных данных нет, используем данные текущего таймфрейма
                    df = load_bars_from_project("BTC", timeframe, limit=5000)
                    # Для часовых данных используем horizon напрямую
                    result = forecast_with_catboost(df, "BTC", timeframe, horizon)
                
                if result:
                    # Получаем текущую цену для расчета целевой цены
                    # Используем последний 5-минутный бар для более актуальной цены
                    # Получаем текущую цену - ВСЕГДА используем 5m бар для актуальности
                    current_price = None
                    try:
                        # Пробуем получить последний 5-минутный бар (более актуальный)
                        rows_5m = self.db.last_n("BTC", "5m", 1)
                        if rows_5m:
                            current_price = float(rows_5m[0][4])  # close из последнего 5m бара
                        else:
                            # Fallback: пытаемся получить из других источников, но всё равно актуальную
                            # Пробуем API напрямую
                            try:
                                from ...infrastructure.market_data import binance_spot_price
                                current_price = binance_spot_price("BTCUSDT")
                            except Exception:
                                # Последний fallback: используем последний бар для таймфрейма
                                rows = self.db.last_n("BTC", timeframe, 1)
                                current_price = float(rows[0][4]) if rows else None
                        
                        if current_price:
                            # Преобразуем residual в return
                            # residual = log(P_{t+H}) - log(MA(t))
                            # return ≈ residual для малых значений
                            predicted_return = result.get("ret_pred", 0.0)
                            target_price = current_price * np.exp(predicted_return)  # Более точная формула
                        else:
                            target_price = 0.0
                    except Exception as e:
                        logger.warning(f"Failed to get current price: {e}")
                        current_price = None
                        target_price = 0.0
                    
                    # Калибруем p_up на основе исторической статистики
                    raw_p_up = result.get("p_up", 0.5)
                    calibrated_p_up = raw_p_up
                    try:
                        from ...domain.market_diagnostics.calibration_service import CalibrationService
                        from ...domain.market_diagnostics.setup_type import classify_setup
                        
                        calibration_service = CalibrationService(self.db)
                        
                        # Получаем setup_type и grade для расширенной калибровки
                        setup_class = classify_setup(
                            predicted_return=result.get("ret_pred", 0.0),
                            probability_up=raw_p_up,
                            confidence_interval_68=result.get("confidence_interval_68"),
                            confidence_interval_95=result.get("confidence_interval_95"),
                            global_regime=None,  # Можно получить из GlobalRegimeAnalyzer
                            momentum_grade=None,
                            momentum_strength=None
                        )
                        
                        # Используем расширенную калибровку с учетом типа сетапа
                        calibrated_p_up = calibration_service.calibrate_p_up_by_setup_type(
                            raw_p_up=raw_p_up,
                            symbol="BTC",
                            timeframe=timeframe,
                            horizon=horizon_for_model,
                            setup_type=setup_class.setup_type.value,
                            grade=setup_class.grade
                        )
                    except Exception as e:
                        logger.debug(f"Failed to calibrate p_up: {e}")
                        # Fallback на простую калибровку
                        try:
                            calibrated_p_up = calibration_service.calibrate_p_up(
                                raw_p_up=raw_p_up,
                                symbol="BTC",
                                timeframe=timeframe,
                                horizon=horizon_for_model
                            )
                        except Exception:
                            # Используем raw_p_up если калибровка не удалась
                            pass
                    
                    forecast_data = {
                        "symbol": "BTC",
                        "timeframe": timeframe,
                        "horizon": horizon,
                        "predicted_return": result.get("ret_pred", 0.0),
                        "probability_up": calibrated_p_up,  # Используем откалиброванное значение
                        "probability_up_raw": raw_p_up,  # Сохраняем сырое значение для отладки
                        "target_price": target_price,
                        "current_price": current_price,  # Сохраняем текущую цену из 5m бара
                        "confidence_interval_68": result.get("confidence_interval_68", (0.0, 0.0)),
                        "confidence_interval_95": result.get("confidence_interval_95", (0.0, 0.0)),
                        "metadata": result.get("meta", {}),
                        "model_type": "CatBoost",  # Индикатор новой модели
                        "model_version": "1.0",
                    }
                    
                    # Кэшируем результат
                    cache_key = f"btc_{timeframe}_{horizon}"
                    import time
                    self._forecast_cache[cache_key] = (forecast_data, time.time())
                    
                    # Сохраняем в историю для обучения
                    self.save_forecast_history(forecast_data)
                    
                    return forecast_data
            except ImportError as e:
                logger.warning(f"CatBoost forecaster not available (ImportError: {e}), falling back to default model")
            except FileNotFoundError as e:
                logger.warning(f"CatBoost forecast failed: {e}, falling back to default model")
            except Exception as e:
                logger.warning(f"CatBoost forecast failed: {e}, falling back to default model", exc_info=True)
            
            # Используем обновленную модель из forecaster.py (с улучшениями из lesson_05)
            from ...ml.forecaster import forecast_symbol
            from ...ml.data_adapter import make_loader
            
            # Проверяем кэш
            cache_key = f"btc_{timeframe}_{horizon}"
            if cache_key in self._forecast_cache:
                cached_data, cached_ts = self._forecast_cache[cache_key]
                import time
                if time.time() - cached_ts < self._cache_ttl:
                    return cached_data
            
            loader = make_loader(self.db)
            result = forecast_symbol(loader, "BTC", timeframe, horizon)
            
            if result:
                # Получаем текущую цену для расчета целевой цены
                # Используем последний 5-минутный бар для более актуальной цены
                try:
                    # Пробуем получить последний 5-минутный бар (более актуальный)
                    rows_5m = self.db.last_n("BTC", "5m", 1)
                    if rows_5m:
                        current_price = float(rows_5m[0][4])  # close из последнего 5m бара
                    else:
                        # Fallback: используем последний бар для таймфрейма
                        rows = self.db.last_n("BTC", timeframe, 1)
                        current_price = float(rows[0][4]) if rows else None
                    
                    if current_price:
                        # Обновленная модель уже конвертирует log-отклонение в доходность
                        # ret_pred уже содержит правильную доходность
                        predicted_return = result.get("ret_pred", 0.0)
                        # Используем правильную формулу для целевой цены
                        target_price = current_price * (1.0 + predicted_return)
                    else:
                        target_price = 0.0
                except Exception:
                    target_price = 0.0
                
                # Проверяем метаданные модели для определения типа таргета
                meta = result.get("meta", {})
                target_type = meta.get("target_type", "unknown")
                model_type_name = meta.get("model_type", "Unknown")
                
                forecast_data = {
                    "symbol": "BTC",
                    "timeframe": timeframe,
                    "horizon": horizon,
                    "predicted_return": result.get("ret_pred", 0.0),
                    "probability_up": result.get("p_up", 0.5),
                    "target_price": target_price,
                    "current_price": current_price,  # Сохраняем текущую цену
                    "confidence_interval_68": result.get("ci68", (0.0, 0.0)),
                    "confidence_interval_95": result.get("ci95", (0.0, 0.0)),
                    "metadata": meta,
                    "model_type": model_type_name,  # CatBoost, LightGBM или RandomForest
                    "model_version": "2.0",  # Обновленная версия с улучшениями из lesson_05
                    "target_type": target_type,  # log_residual_from_ema или unknown
                }
                
                # Кэшируем результат
                import time
                self._forecast_cache[cache_key] = (forecast_data, time.time())
                
                # Сохраняем в историю для обучения
                self.save_forecast_history(forecast_data)
                
                return forecast_data
            return None
        except Exception as e:
            logger.exception("Failed to forecast BTC: %s", e)
            return None
    
    def _cache_model(self, cache_key: tuple, model_data: Dict):
        """
        Кэшировать модель с ограничением размера кэша.
        
        Args:
            cache_key: Ключ кэша (symbol, tf, horizon, model_type)
            model_data: Данные модели для кэширования
        """
        # Если кэш переполнен, удаляем самый старый элемент (FIFO)
        if len(self._model_cache) >= self._model_cache_max_size:
            # Удаляем первый элемент (самый старый)
            oldest_key = next(iter(self._model_cache))
            del self._model_cache[oldest_key]
            logger.debug(f"Model cache full, removed {oldest_key}")
        
        # Добавляем новую модель в кэш
        self._model_cache[cache_key] = model_data
        logger.debug(f"Cached model: {cache_key}")
    
    def forecast_altcoins(
        self,
        symbols: List[str],
        timeframe: str = "1h",
        horizon: int = 24,
    ) -> List[Dict]:
        """
        Сгенерировать прогнозы для списка альткоинов.
        
        Args:
            symbols: Список символов
            timeframe: Таймфрейм
            horizon: Горизонт прогноза
        
        Returns:
            List[Dict]: Список прогнозов
        """
        results = []
        from ...ml.forecaster import forecast_symbol
        from ...ml.data_adapter import make_loader
        
        loader = make_loader(self.db)
        
        for symbol in symbols:
            try:
                result = forecast_symbol(loader, symbol, timeframe, horizon)
                
                if result:
                    # Получаем текущую цену для расчета целевой цены
                    # Используем последний 5-минутный бар для более актуальной цены
                    try:
                        # Пробуем получить последний 5-минутный бар (более актуальный)
                        rows_5m = self.db.last_n(symbol, "5m", 1)
                        if rows_5m:
                            current_price = float(rows_5m[0][4])  # close из последнего 5m бара
                        else:
                            # Fallback: используем последний бар для таймфрейма
                            rows = self.db.last_n(symbol, timeframe, 1)
                            current_price = float(rows[0][4]) if rows else None
                        
                        if current_price:
                            # Обновленная модель уже конвертирует log-отклонение в доходность
                            predicted_return = result.get("ret_pred", 0.0)
                            target_price = current_price * (1.0 + predicted_return)
                        else:
                            target_price = 0.0
                    except Exception:
                        target_price = 0.0
                    
                    # Получаем метаданные модели
                    meta = result.get("meta", {})
                    model_type_name = meta.get("model_type", "Unknown")
                    target_type = meta.get("target_type", "unknown")
                    
                    forecast_data = {
                        "symbol": symbol,
                        "timeframe": timeframe,
                        "horizon": horizon,
                        "predicted_return": result.get("ret_pred", 0.0),
                        "probability_up": result.get("p_up", 0.5),
                        "target_price": target_price,
                        "current_price": current_price,
                        "metadata": meta,
                        "model_type": model_type_name,
                        "model_version": "2.0",  # Обновленная версия
                        "target_type": target_type,
                    }
                    
                    results.append(forecast_data)
                    
                    # Сохраняем в историю
                    self.save_forecast_history(forecast_data)
            except Exception as e:
                logger.warning("Failed to forecast %s: %s", symbol, e)
                continue
        
        return results
    
    def save_forecast_history(self, forecast_data: Dict):
        """
        Сохранить прогноз в историю для последующего обучения модели.
        
        Args:
            forecast_data: Данные прогноза
        """
        try:
            # Создаем таблицу для истории прогнозов, если её нет
            cur = self.db.conn.cursor()
            cur.execute("""
                CREATE TABLE IF NOT EXISTS forecast_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT NOT NULL,
                    timeframe TEXT NOT NULL,
                    horizon INTEGER NOT NULL,
                    predicted_return REAL NOT NULL,
                    probability_up REAL NOT NULL,
                    target_price REAL,
                    timestamp_ms INTEGER NOT NULL,
                    metadata TEXT,
                    current_price REAL,
                    actual_return REAL,
                    actual_price REAL,
                    prediction_error REAL,
                    hit INTEGER,
                    p_up_hit INTEGER,
                    evaluation_status TEXT,
                    evaluated_at_ms INTEGER
                )
            """)
            
            # Сохраняем прогноз
            import time
            import json
            timestamp_ms = int(time.time() * 1000)
            metadata_json = json.dumps(forecast_data.get("metadata", {}))
            
            # Получаем текущую цену для сохранения
            current_price = forecast_data.get("current_price", 0.0)
            if not current_price:
                # Пробуем получить текущую цену из последнего 5-минутного бара
                try:
                    rows_5m = self.db.last_n(forecast_data.get("symbol", "BTC"), "5m", 1)
                    if rows_5m:
                        current_price = float(rows_5m[0][4])  # close
                except Exception:
                    pass
            
            cur.execute("""
                INSERT INTO forecast_history 
                (symbol, timeframe, horizon, predicted_return, probability_up, target_price, 
                 timestamp_ms, metadata, current_price)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                forecast_data.get("symbol", ""),
                forecast_data.get("timeframe", ""),
                forecast_data.get("horizon", 24),
                forecast_data.get("predicted_return", 0.0),
                forecast_data.get("probability_up", 0.5),
                forecast_data.get("target_price", 0.0),
                timestamp_ms,
                metadata_json,
                current_price if current_price > 0 else None
            ))
            
            self.db.conn.commit()
            
            # Очищаем старые записи (оставляем последние 10000)
            cur.execute("""
                DELETE FROM forecast_history 
                WHERE id NOT IN (
                    SELECT id FROM forecast_history 
                    ORDER BY timestamp_ms DESC 
                    LIMIT 10000
                )
            """)
            self.db.conn.commit()
            
        except Exception as e:
            logger.warning("Failed to save forecast history: %s", e)

