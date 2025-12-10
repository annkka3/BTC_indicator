# app/infrastructure/forecast_worker.py
"""
Воркер для обработки задач прогнозирования из очереди RabbitMQ.
"""

from __future__ import annotations

import logging
import os
from typing import Dict, Any
from .queue import MessageQueue, QueueWorker, TaskType
from .db import DB
from ..config import settings

log = logging.getLogger("alt_forecast.forecast_worker")


class ForecastWorker(QueueWorker):
    """Воркер для обработки задач прогнозирования."""
    
    def __init__(self):
        db_path = (
            getattr(settings, "DATABASE_PATH", None)
            or getattr(settings, "database_path", None)
            or "/data/data.db"
        )
        self.db = DB(db_path)
        
        # Инициализируем очередь
        queue = MessageQueue(
            host=os.getenv("RABBITMQ_HOST", "rabbitmq"),
            port=int(os.getenv("RABBITMQ_PORT", "5672")),
            username=os.getenv("RABBITMQ_USER", "guest"),
            password=os.getenv("RABBITMQ_PASS", "guest")
        )
        
        super().__init__(queue, "forecast_btc")
    
    def process_message(self, message: Dict[str, Any]):
        """Обрабатывает сообщение о задаче прогнозирования."""
        task_type = message.get("task_type")
        payload = message.get("payload", {})
        
        log.info(f"Processing task: {task_type}, payload: {payload}")
        
        if task_type == TaskType.FORECAST_BTC.value:
            self._process_forecast_btc(payload)
        else:
            log.warning(f"Unknown task type: {task_type}")
    
    def _process_forecast_btc(self, payload: Dict[str, Any]):
        """Обрабатывает задачу прогнозирования BTC."""
        timeframe = payload.get("timeframe", "1h")
        horizon = payload.get("horizon", 24)
        
        try:
            from ..application.services.forecast_service import ForecastService
            forecast_service = ForecastService(self.db)
            forecast = forecast_service.forecast_btc(timeframe, horizon)
            
            if forecast:
                log.info(f"Forecast generated: {forecast}")
            else:
                log.warning("Failed to generate forecast")
        except Exception as e:
            log.exception(f"Error processing forecast: {e}")


def main():
    """Точка входа для воркера."""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    worker = ForecastWorker()
    try:
        worker.start()
    except KeyboardInterrupt:
        log.info("Worker stopped")
    finally:
        worker.queue.close()
        worker.db.close()


if __name__ == "__main__":
    main()

