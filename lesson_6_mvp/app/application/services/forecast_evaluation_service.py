# app/application/services/forecast_evaluation_service.py
"""
Сервис для автоматической оценки качества прогнозов и их калибровки.

Выполняет:
1. Автоматическую оценку старых прогнозов (сравнение с реальными результатами)
2. Вычисление метрик качества (hit rate, MAE, bias, calibration curves)
3. Обновление калибровочных параметров на основе исторических данных
4. Генерацию отчетов о качестве прогнозов
"""

import logging
import time
import json
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timezone, timedelta
import numpy as np
import pandas as pd

from ...infrastructure.db import DB

logger = logging.getLogger("alt_forecast.services.forecast_evaluation")


class ForecastEvaluationService:
    """Сервис для оценки качества прогнозов."""
    
    def __init__(self, db: DB):
        """
        Args:
            db: Database instance для доступа к forecast_history и bars
        """
        self.db = db
    
    def evaluate_pending_forecasts(self, min_age_hours: float = 1.0) -> Dict[str, int]:
        """
        Оценить прогнозы, которые уже должны были "сбыться".
        
        Находит прогнозы, для которых прошло достаточно времени (min_age_hours)
        после timestamp + horizon, и сравнивает предсказания с реальными результатами.
        
        Args:
            min_age_hours: Минимальное время ожидания после окончания горизонта (в часах)
        
        Returns:
            Dict с количеством оцененных прогнозов: {"evaluated": N, "errors": M}
        """
        results = {"evaluated": 0, "errors": 0, "updated": 0}
        
        try:
            cur = self.db.conn.cursor()
            
            # Получаем все прогнозы, которые еще не оценены
            # и для которых прошло достаточно времени после горизонта
            now_ms = int(time.time() * 1000)
            
            # Получаем все неоцененные прогнозы
            cur.execute("""
                SELECT id, symbol, timeframe, horizon, predicted_return, probability_up,
                       target_price, timestamp_ms, metadata
                FROM forecast_history
                WHERE (actual_return IS NULL OR evaluation_status IS NULL)
                ORDER BY timestamp_ms DESC
                LIMIT 1000
            """)
            
            forecasts = cur.fetchall()
            
            for forecast_row in forecasts:
                try:
                    forecast_id = forecast_row["id"]
                    symbol = forecast_row["symbol"]
                    timeframe = forecast_row["timeframe"]
                    horizon = forecast_row["horizon"]
                    predicted_return = forecast_row["predicted_return"]
                    timestamp_ms = forecast_row["timestamp_ms"]
                    
                    # Вычисляем ожидаемое время окончания горизонта
                    # Конвертируем horizon (бары) в миллисекунды
                    tf_to_ms = {
                        "5m": 5 * 60 * 1000,
                        "15m": 15 * 60 * 1000,
                        "1h": 60 * 60 * 1000,
                        "4h": 4 * 60 * 60 * 1000,
                        "1d": 24 * 60 * 60 * 1000,
                        "24h": 24 * 60 * 60 * 1000,
                    }
                    
                    tf_ms = tf_to_ms.get(timeframe, 60 * 60 * 1000)  # Default: 1h
                    horizon_end_ms = timestamp_ms + (horizon * tf_ms)
                    
                    # Проверяем, прошло ли достаточно времени после окончания горизонта
                    min_age_ms = min_age_hours * 60 * 60 * 1000
                    if now_ms < horizon_end_ms + min_age_ms:
                        # Еще не прошло достаточно времени
                        continue
                    
                    # Получаем реальную цену через horizon баров от timestamp
                    actual_return, actual_price = self._calculate_actual_return(
                        symbol, timeframe, timestamp_ms, horizon
                    )
                    
                    if actual_return is None:
                        # Недостаточно данных для оценки
                        continue
                    
                    # Вычисляем метрики качества
                    error = actual_return - predicted_return
                    hit = 1 if (actual_return > 0) == (predicted_return > 0) else 0
                    p_up_hit = 1 if (actual_return > 0) and (forecast_row["probability_up"] > 0.5) else 0
                    
                    # Обновляем запись в БД
                    cur.execute("""
                        UPDATE forecast_history
                        SET actual_return = ?,
                            actual_price = ?,
                            prediction_error = ?,
                            hit = ?,
                            p_up_hit = ?,
                            evaluation_status = 'evaluated',
                            evaluated_at_ms = ?
                        WHERE id = ?
                    """, (
                        float(actual_return),
                        float(actual_price) if actual_price else None,
                        float(error),
                        int(hit),
                        int(p_up_hit),
                        now_ms,
                        forecast_id
                    ))
                    
                    results["evaluated"] += 1
                    results["updated"] += 1
                    
                except Exception as e:
                    logger.warning(f"Failed to evaluate forecast {forecast_row.get('id')}: {e}")
                    results["errors"] += 1
                    continue
            
            self.db.conn.commit()
            
        except Exception as e:
            logger.error(f"Failed to evaluate pending forecasts: {e}", exc_info=True)
            results["errors"] += 1
        
        return results
    
    def _calculate_actual_return(
        self,
        symbol: str,
        timeframe: str,
        start_timestamp_ms: int,
        horizon: int
    ) -> Tuple[Optional[float], Optional[float]]:
        """
        Вычислить реальный return через horizon баров от start_timestamp_ms.
        
        Args:
            symbol: Символ (BTC, ETH, etc.)
            timeframe: Таймфрейм (1h, 4h, 1d)
            start_timestamp_ms: Время начала прогноза (в миллисекундах)
            horizon: Количество баров вперед
        
        Returns:
            Tuple (actual_return, actual_price) или (None, None) если недостаточно данных
        """
        try:
            # Получаем бары вокруг start_timestamp_ms
            # Нам нужен бар с timestamp >= start_timestamp_ms и horizon баров после него
            
            # Получаем последние бары для нахождения нужного диапазона
            bars = self.db.last_n(symbol, timeframe, limit=horizon + 100)
            
            if not bars or len(bars) < horizon + 1:
                return None, None
            
            # Находим индекс бара, который соответствует start_timestamp_ms
            # Ищем ближайший бар с timestamp >= start_timestamp_ms
            start_idx = None
            for i, (ts, o, h, l, c, v) in enumerate(bars):
                if ts >= start_timestamp_ms:
                    start_idx = i
                    break
            
            if start_idx is None:
                # Используем последний бар как отправную точку
                start_idx = len(bars) - horizon - 1
                if start_idx < 0:
                    return None, None
            
            # Получаем цену начала и цену через horizon баров
            start_price = float(bars[start_idx][4])  # close
            
            end_idx = start_idx + horizon
            if end_idx >= len(bars):
                return None, None
            
            end_price = float(bars[end_idx][4])  # close
            
            # Вычисляем реальный return
            actual_return = (end_price - start_price) / start_price
            
            return actual_return, end_price
            
        except Exception as e:
            logger.warning(f"Failed to calculate actual return for {symbol} {timeframe}: {e}")
            return None, None
    
    def get_forecast_quality_metrics(
        self,
        symbol: Optional[str] = None,
        timeframe: Optional[str] = None,
        min_samples: int = 10
    ) -> Optional[Dict]:
        """
        Получить метрики качества прогнозов на основе исторических данных.
        
        Args:
            symbol: Фильтр по символу (None = все символы)
            timeframe: Фильтр по таймфрейму (None = все таймфреймы)
            min_samples: Минимальное количество образцов для вычисления метрик
        
        Returns:
            Dict с метриками качества или None
        """
        try:
            cur = self.db.conn.cursor()
            
            # Строим запрос с фильтрами
            query = """
                SELECT predicted_return, actual_return, probability_up, hit, p_up_hit,
                       prediction_error, symbol, timeframe, horizon
                FROM forecast_history
                WHERE evaluation_status = 'evaluated'
                  AND actual_return IS NOT NULL
            """
            params = []
            
            if symbol:
                query += " AND symbol = ?"
                params.append(symbol)
            
            if timeframe:
                query += " AND timeframe = ?"
                params.append(timeframe)
            
            cur.execute(query, params)
            rows = cur.fetchall()
            
            if len(rows) < min_samples:
                logger.debug(f"Not enough evaluated forecasts: {len(rows)} < {min_samples}")
                return None
            
            # Преобразуем в numpy массивы
            predicted_returns = np.array([float(r["predicted_return"]) for r in rows])
            actual_returns = np.array([float(r["actual_return"]) for r in rows])
            probabilities_up = np.array([float(r["probability_up"]) for r in rows])
            hits = np.array([int(r["hit"]) for r in rows])
            p_up_hits = np.array([int(r["p_up_hit"]) if r["p_up_hit"] is not None else 0 for r in rows])
            errors = np.array([float(r["prediction_error"]) for r in rows])
            
            # Вычисляем метрики
            hit_rate = float(np.mean(hits))
            p_up_hit_rate = float(np.mean(p_up_hits[probabilities_up > 0.5])) if np.any(probabilities_up > 0.5) else 0.0
            
            mae = float(np.mean(np.abs(errors)))
            mse = float(np.mean(errors ** 2))
            rmse = float(np.sqrt(mse))
            
            bias = float(np.mean(errors))  # Положительное = завышение, отрицательное = занижение
            
            # Калибровка вероятностей (калибровочные кривые)
            # Разбиваем на бины по probability_up
            bins = np.linspace(0, 1, 11)  # 10 бинов
            bin_indices = np.digitize(probabilities_up, bins) - 1
            bin_indices = np.clip(bin_indices, 0, len(bins) - 2)
            
            calibration_data = []
            for i in range(len(bins) - 1):
                mask = bin_indices == i
                if np.any(mask):
                    avg_pred_prob = float(np.mean(probabilities_up[mask]))
                    actual_up_rate = float(np.mean(actual_returns[mask] > 0))
                    count = int(np.sum(mask))
                    calibration_data.append({
                        "predicted_prob": avg_pred_prob,
                        "actual_up_rate": actual_up_rate,
                        "count": count
                    })
            
            # Корреляция между предсказанным и реальным return
            if len(predicted_returns) > 1:
                correlation = float(np.corrcoef(predicted_returns, actual_returns)[0, 1])
            else:
                correlation = 0.0
            
            return {
                "n_samples": len(rows),
                "hit_rate": hit_rate,
                "p_up_hit_rate": p_up_hit_rate,
                "mae": mae,
                "mse": mse,
                "rmse": rmse,
                "bias": bias,
                "correlation": correlation,
                "calibration_curve": calibration_data
            }
            
        except Exception as e:
            logger.error(f"Failed to get forecast quality metrics: {e}", exc_info=True)
            return None
    
    def update_forecast_history_schema(self):
        """
        Обновить схему таблицы forecast_history, добавив поля для оценки.
        Выполняется автоматически при первом вызове.
        """
        try:
            cur = self.db.conn.cursor()
            
            # Проверяем, какие колонки уже есть
            cur.execute("PRAGMA table_info(forecast_history)")
            existing_columns = {row[1] for row in cur.fetchall()}
            
            # Добавляем недостающие колонки
            columns_to_add = {
                "actual_return": "REAL",
                "actual_price": "REAL",
                "prediction_error": "REAL",
                "hit": "INTEGER",
                "p_up_hit": "INTEGER",
                "evaluation_status": "TEXT",
                "evaluated_at_ms": "INTEGER",
                "current_price": "REAL",  # Цена на момент прогноза
            }
            
            for col_name, col_type in columns_to_add.items():
                if col_name not in existing_columns:
                    try:
                        cur.execute(f"ALTER TABLE forecast_history ADD COLUMN {col_name} {col_type}")
                        logger.info(f"Added column {col_name} to forecast_history table")
                    except Exception as e:
                        logger.warning(f"Failed to add column {col_name}: {e}")
            
            self.db.conn.commit()
            
        except Exception as e:
            logger.error(f"Failed to update forecast_history schema: {e}", exc_info=True)

















