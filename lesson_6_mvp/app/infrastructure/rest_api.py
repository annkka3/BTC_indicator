# app/infrastructure/rest_api.py
"""
Расширенный REST API для доступа к данным и прогнозам.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional, List
from fastapi import FastAPI, HTTPException, Query, Path
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from .db import DB
from ..domain.models import Metric, Timeframe, METRICS, TIMEFRAMES
from ..config import settings

log = logging.getLogger("alt_forecast.api.rest")

# Pydantic модели для API

class BarResponse(BaseModel):
    """Ответ с данными бара."""
    metric: str
    timeframe: str
    ts: int
    timestamp_iso: str
    open: float
    high: float
    low: float
    close: float
    volume: Optional[float] = None

    class Config:
        json_schema_extra = {
            "example": {
                "metric": "BTC",
                "timeframe": "1h",
                "ts": 1704067200000,
                "timestamp_iso": "2024-01-01T00:00:00Z",
                "open": 42000.0,
                "high": 42500.0,
                "low": 41800.0,
                "close": 42300.0,
                "volume": 1000000.0
            }
        }


class ForecastResponse(BaseModel):
    """Ответ с прогнозом."""
    symbol: str
    timeframe: str
    horizon: int
    current_price: float
    predicted_price: Optional[float] = None
    predicted_return: Optional[float] = None
    probability_up: Optional[float] = None
    confidence: Optional[float] = None
    timestamp: int

    class Config:
        json_schema_extra = {
            "example": {
                "symbol": "BTC",
                "timeframe": "1h",
                "horizon": 24,
                "current_price": 42000.0,
                "predicted_price": 42500.0,
                "predicted_return": 0.012,
                "probability_up": 0.65,
                "confidence": 0.72,
                "timestamp": 1704067200000
            }
        }


class DivergenceResponse(BaseModel):
    """Ответ с данными дивергенции."""
    id: int
    metric: str
    timeframe: str
    indicator: str
    side: str
    implication: str
    status: str
    detected_ts: int
    score: float

    class Config:
        json_schema_extra = {
            "example": {
                "id": 1,
                "metric": "BTC",
                "timeframe": "1h",
                "indicator": "RSI",
                "side": "bullish",
                "implication": "bullish_alts",
                "status": "active",
                "detected_ts": 1704067200000,
                "score": 0.75
            }
        }


class MetricsStatsResponse(BaseModel):
    """Статистика по метрикам."""
    metric: str
    timeframe: str
    latest_price: float
    latest_ts: int
    bar_count: int
    price_change_24h: Optional[float] = None


def create_rest_api_router(app: FastAPI, db: DB):
    """Создает и регистрирует REST API роуты."""
    
    @app.get("/api/bars", response_model=List[BarResponse], tags=["bars"])
    async def get_bars(
        metric: Optional[str] = Query(None, description="Фильтр по метрике"),
        timeframe: Optional[str] = Query(None, description="Фильтр по таймфрейму"),
        limit: int = Query(100, ge=1, le=1000, description="Максимальное количество записей"),
        offset: int = Query(0, ge=0, description="Смещение для пагинации")
    ):
        """
        Получить список баров с фильтрацией.
        
        - **metric**: Фильтр по метрике (BTC, USDT.D, BTC.D, TOTAL2, TOTAL3, ETHBTC)
        - **timeframe**: Фильтр по таймфрейму (15m, 1h, 4h, 1d)
        - **limit**: Максимальное количество записей (1-1000)
        - **offset**: Смещение для пагинации
        """
        try:
            if metric and metric not in METRICS:
                raise HTTPException(status_code=400, detail=f"Invalid metric. Allowed: {METRICS}")
            if timeframe and timeframe not in TIMEFRAMES:
                raise HTTPException(status_code=400, detail=f"Invalid timeframe. Allowed: {TIMEFRAMES}")
            
            # Получаем бары из БД
            if metric and timeframe:
                bars = db.last_n(metric, timeframe, limit + offset)
                bars = bars[offset:offset + limit]
            elif metric:
                # Если указана только метрика, получаем для всех таймфреймов
                all_bars = []
                for tf in TIMEFRAMES:
                    tf_bars = db.last_n(metric, tf, limit // len(TIMEFRAMES) + 1)
                    # Добавляем таймфрейм и сохраняем исходный формат бара
                    for bar in tf_bars:
                        all_bars.append((tf, bar))  # (tf, (ts, o, h, l, c, v))
                # Сортируем по ts (второй элемент бара, который находится в bar[0])
                all_bars.sort(key=lambda x: x[1][0], reverse=True)  # Сортируем по ts
                bars_with_tf = all_bars[offset:offset + limit]
                # Сохраняем информацию о таймфрейме для каждого бара
                bars = [(tf, bar) for tf, bar in bars_with_tf]
            else:
                raise HTTPException(
                    status_code=400,
                    detail="At least 'metric' or both 'metric' and 'timeframe' must be specified"
                )
            
            result = []
            for item in bars:
                # Если bars содержит пары (tf, bar), обрабатываем соответственно
                if isinstance(item, tuple) and len(item) == 2 and isinstance(item[1], tuple):
                    # Случай когда только metric указан - формат (tf, (ts, o, h, l, c, v))
                    tf, bar = item
                    bar_metric = metric
                else:
                    # Случай когда metric и timeframe указаны - формат (ts, o, h, l, c, v)
                    bar = item
                    tf = timeframe
                    bar_metric = metric
                
                # bar is RowBars = (ts, o, h, l, c, v)
                if len(bar) >= 5:
                    ts, o, h, l, c = bar[0], bar[1], bar[2], bar[3], bar[4]
                    v = bar[5] if len(bar) > 5 else None
                    
                    timestamp_iso = datetime.utcfromtimestamp(ts / 1000).isoformat() + "Z"
                    result.append(BarResponse(
                        metric=bar_metric,
                        timeframe=tf,
                        ts=ts,
                        timestamp_iso=timestamp_iso,
                        open=o,
                        high=h,
                        low=l,
                        close=c,
                        volume=v
                    ))
            
            return result
        except HTTPException:
            raise
        except Exception as e:
            log.exception("Error getting bars")
            raise HTTPException(status_code=500, detail=str(e))

    @app.get("/api/bars/{metric}/{timeframe}", response_model=List[BarResponse], tags=["bars"])
    async def get_bars_by_metric_timeframe(
        metric: str = Path(..., description="Метрика"),
        timeframe: str = Path(..., description="Таймфрейм"),
        limit: int = Query(100, ge=1, le=1000, description="Максимальное количество записей")
    ):
        """
        Получить бары для конкретной метрики и таймфрейма.
        
        - **metric**: Метрика (BTC, USDT.D, BTC.D, TOTAL2, TOTAL3, ETHBTC)
        - **timeframe**: Таймфрейм (15m, 1h, 4h, 1d)
        - **limit**: Максимальное количество записей (1-1000)
        """
        if metric not in METRICS:
            raise HTTPException(status_code=400, detail=f"Invalid metric. Allowed: {METRICS}")
        if timeframe not in TIMEFRAMES:
            raise HTTPException(status_code=400, detail=f"Invalid timeframe. Allowed: {TIMEFRAMES}")
        
        try:
            bars = db.last_n(metric, timeframe, limit)
            result = []
            for bar in bars:
                if len(bar) >= 5:
                    ts = bar[1] if len(bar) >= 2 else 0
                    o, h, l, c = bar[2], bar[3], bar[4], bar[5] if len(bar) > 5 else bar[4]
                    v = bar[6] if len(bar) > 6 else None
                    
                    timestamp_iso = datetime.utcfromtimestamp(ts / 1000).isoformat() + "Z"
                    result.append(BarResponse(
                        metric=metric,
                        timeframe=timeframe,
                        ts=ts,
                        timestamp_iso=timestamp_iso,
                        open=o,
                        high=h,
                        low=l,
                        close=c,
                        volume=v
                    ))
            return result
        except Exception as e:
            log.exception("Error getting bars")
            raise HTTPException(status_code=500, detail=str(e))

    @app.get("/api/metrics/stats", response_model=List[MetricsStatsResponse], tags=["metrics"])
    async def get_metrics_stats():
        """
        Получить статистику по всем метрикам.
        """
        try:
            stats = []
            for metric in METRICS:
                for tf in TIMEFRAMES:
                        bars = db.last_n(metric, tf, 1)
                        if bars:
                            bar = bars[0]
                            # bar is RowBars = (ts, o, h, l, c, v)
                            ts = bar[0]
                            latest_price = bar[4]  # close price
                            
                            # Получаем цену 24 часа назад для расчета изменения
                            price_24h_ago = None
                            bars_24h = db.last_n(metric, tf, 288)  # ~24 часа для 5m или больше для других TF
                            if len(bars_24h) > 0:
                                old_bar = bars_24h[-1]
                                old_price = old_bar[4]  # close price
                                price_change_24h = ((latest_price - old_price) / old_price * 100) if old_price > 0 else None
                            else:
                                price_change_24h = None
                        
                        # Подсчитываем общее количество баров (приблизительно)
                        all_bars = db.last_n(metric, tf, 10000)
                        bar_count = len(all_bars)
                        
                        stats.append(MetricsStatsResponse(
                            metric=metric,
                            timeframe=tf,
                            latest_price=latest_price,
                            latest_ts=ts,
                            bar_count=bar_count,
                            price_change_24h=price_change_24h
                        ))
            return stats
        except Exception as e:
            log.exception("Error getting metrics stats")
            raise HTTPException(status_code=500, detail=str(e))

    @app.get("/api/forecasts/btc", response_model=ForecastResponse, tags=["forecasts"])
    async def get_btc_forecast(
        timeframe: str = Query("1h", description="Таймфрейм (1h, 4h, 1d)"),
        horizon: int = Query(24, ge=1, le=168, description="Горизонт прогноза в барах")
    ):
        """
        Получить прогноз для BTC.
        
        - **timeframe**: Таймфрейм (1h, 4h, 1d)
        - **horizon**: Горизонт прогноза в барах (1-168)
        """
        if timeframe not in ["1h", "4h", "1d"]:
            raise HTTPException(status_code=400, detail="Invalid timeframe. Allowed: 1h, 4h, 1d")
        
        try:
            from ..application.services.forecast_service import ForecastService
            forecast_service = ForecastService(db)
            forecast = forecast_service.forecast_btc(timeframe, horizon)
            
            if not forecast:
                raise HTTPException(status_code=404, detail="Forecast not available")
            
            return ForecastResponse(
                symbol="BTC",
                timeframe=timeframe,
                horizon=horizon,
                current_price=forecast.get("current_price", 0.0),
                predicted_price=forecast.get("predicted_price"),
                predicted_return=forecast.get("predicted_return"),
                probability_up=forecast.get("probability_up"),
                confidence=forecast.get("confidence"),
                timestamp=int(datetime.now().timestamp() * 1000)
            )
        except HTTPException:
            raise
        except Exception as e:
            log.exception("Error getting forecast")
            raise HTTPException(status_code=500, detail=str(e))

    @app.get("/api/divergences", response_model=List[DivergenceResponse], tags=["divergences"])
    async def get_divergences(
        status: Optional[str] = Query(None, description="Фильтр по статусу (active, confirmed, invalid)"),
        metric: Optional[str] = Query(None, description="Фильтр по метрике"),
        timeframe: Optional[str] = Query(None, description="Фильтр по таймфрейму"),
        limit: int = Query(50, ge=1, le=200, description="Максимальное количество записей")
    ):
        """
        Получить список дивергенций.
        
        - **status**: Фильтр по статусу (active, confirmed, invalid)
        - **metric**: Фильтр по метрике
        - **timeframe**: Фильтр по таймфрейму
        - **limit**: Максимальное количество записей
        """
        try:
            query = "SELECT id, metric, timeframe, indicator, side, implication, status, detected_ts, score FROM divs WHERE 1=1"
            params = []
            
            if status:
                query += " AND status = ?"
                params.append(status)
            if metric:
                query += " AND metric = ?"
                params.append(metric)
            if timeframe:
                query += " AND timeframe = ?"
                params.append(timeframe)
            
            query += " ORDER BY detected_ts DESC LIMIT ?"
            params.append(limit)
            
            cur = db.conn.cursor()
            cur.execute(query, params)
            rows = cur.fetchall()
            
            result = []
            for row in rows:
                result.append(DivergenceResponse(
                    id=row["id"],
                    metric=row["metric"],
                    timeframe=row["timeframe"],
                    indicator=row["indicator"],
                    side=row["side"],
                    implication=row["implication"],
                    status=row["status"],
                    detected_ts=row["detected_ts"],
                    score=row["score"] or 0.0
                ))
            
            return result
        except Exception as e:
            log.exception("Error getting divergences")
            raise HTTPException(status_code=500, detail=str(e))

    @app.get("/api/stats", tags=["stats"])
    async def get_api_stats():
        """
        Получить общую статистику API и базы данных.
        """
        try:
            stats = {
                "database": {
                    "path": db.path,
                    "connected": db.conn is not None
                },
                "metrics": {
                    "supported": list(METRICS),
                    "count": len(METRICS)
                },
                "timeframes": {
                    "supported": list(TIMEFRAMES),
                    "count": len(TIMEFRAMES)
                }
            }
            
            # Подсчитываем общее количество баров
            total_bars = 0
            for metric in METRICS:
                for tf in TIMEFRAMES:
                    bars = db.last_n(metric, tf, 10000)
                    total_bars += len(bars)
            
            stats["bars"] = {
                "total_count": total_bars
            }
            
            # Подсчитываем дивергенции
            cur = db.conn.cursor()
            cur.execute("SELECT COUNT(*) as cnt FROM divs")
            div_count = cur.fetchone()["cnt"]
            cur.execute("SELECT COUNT(*) as cnt FROM divs WHERE status='active'")
            active_div_count = cur.fetchone()["cnt"]
            
            stats["divergences"] = {
                "total_count": div_count,
                "active_count": active_div_count
            }
            
            return stats
        except Exception as e:
            log.exception("Error getting stats")
            raise HTTPException(status_code=500, detail=str(e))

