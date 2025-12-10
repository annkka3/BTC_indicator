# app/infrastructure/queue.py
"""
Интеграция с RabbitMQ для масштабирования воркеров.
"""

from __future__ import annotations

import logging
import json
from typing import Optional, Dict, Any
from enum import Enum

try:
    import pika
    from pika import BlockingConnection, ConnectionParameters, BasicProperties
    RABBITMQ_AVAILABLE = True
except ImportError:
    RABBITMQ_AVAILABLE = False
    logging.warning("pika not installed. RabbitMQ integration disabled.")

log = logging.getLogger("alt_forecast.queue")


class TaskType(str, Enum):
    """Типы задач для очереди."""
    FORECAST_BTC = "forecast_btc"
    GENERATE_REPORT = "generate_report"
    UPDATE_CACHE = "update_cache"
    PROCESS_DIVERGENCE = "process_divergence"


class MessageQueue:
    """Класс для работы с RabbitMQ."""
    
    def __init__(
        self,
        host: str = "rabbitmq",
        port: int = 5672,
        username: str = "guest",
        password: str = "guest",
        virtual_host: str = "/"
    ):
        if not RABBITMQ_AVAILABLE:
            raise RuntimeError("pika is not installed. Install it with: pip install pika")
        
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.virtual_host = virtual_host
        self.connection: Optional[BlockingConnection] = None
        self.channel = None
        self.exchange = "alt_forecast"
        self._connect()
    
    def _connect(self):
        """Устанавливает соединение с RabbitMQ."""
        try:
            credentials = pika.PlainCredentials(self.username, self.password)
            parameters = ConnectionParameters(
                host=self.host,
                port=self.port,
                virtual_host=self.virtual_host,
                credentials=credentials,
                heartbeat=600,
                blocked_connection_timeout=300
            )
            self.connection = BlockingConnection(parameters)
            self.channel = self.connection.channel()
            
            # Объявляем exchange
            self.channel.exchange_declare(
                exchange=self.exchange,
                exchange_type="direct",
                durable=True
            )
            
            log.info(f"Connected to RabbitMQ at {self.host}:{self.port}")
        except Exception as e:
            log.error(f"Failed to connect to RabbitMQ: {e}")
            raise
    
    def ensure_queue(self, queue_name: str, routing_key: Optional[str] = None):
        """Создает очередь, если она не существует."""
        if routing_key is None:
            routing_key = queue_name
        
        self.channel.queue_declare(queue=queue_name, durable=True)
        self.channel.queue_bind(
            exchange=self.exchange,
            queue=queue_name,
            routing_key=routing_key
        )
    
    def publish_task(
        self,
        task_type: TaskType,
        payload: Dict[str, Any],
        queue_name: Optional[str] = None,
        priority: int = 0
    ):
        """
        Публикует задачу в очередь.
        
        Args:
            task_type: Тип задачи
            payload: Данные задачи
            queue_name: Имя очереди (если не указано, используется task_type)
            priority: Приоритет задачи (0-255)
        """
        if queue_name is None:
            queue_name = task_type.value
        
        self.ensure_queue(queue_name, routing_key=task_type.value)
        
        message = {
            "task_type": task_type.value,
            "payload": payload
        }
        
        properties = BasicProperties(
            delivery_mode=2,  # Persistent message
            priority=priority
        )
        
        self.channel.basic_publish(
            exchange=self.exchange,
            routing_key=task_type.value,
            body=json.dumps(message),
            properties=properties
        )
        
        log.info(f"Published task {task_type.value} to queue {queue_name}")
    
    def consume_tasks(
        self,
        queue_name: str,
        callback,
        auto_ack: bool = False
    ):
        """
        Начинает потребление задач из очереди.
        
        Args:
            queue_name: Имя очереди
            callback: Функция обработки задачи (message) -> None
            auto_ack: Автоматическое подтверждение обработки
        """
        self.ensure_queue(queue_name)
        
        def _callback(ch, method, properties, body):
            try:
                message = json.loads(body)
                callback(message)
                if not auto_ack:
                    ch.basic_ack(delivery_tag=method.delivery_tag)
            except Exception as e:
                log.exception(f"Error processing message: {e}")
                if not auto_ack:
                    ch.basic_nack(delivery_tag=method.delivery_tag, requeue=True)
        
        self.channel.basic_qos(prefetch_count=1)  # Обрабатываем по одной задаче на воркер
        self.channel.basic_consume(
            queue=queue_name,
            on_message_callback=_callback,
            auto_ack=auto_ack
        )
        
        log.info(f"Started consuming from queue {queue_name}")
        self.channel.start_consuming()
    
    def stop_consuming(self):
        """Останавливает потребление задач."""
        if self.channel and self.channel.is_consuming:
            self.channel.stop_consuming()
    
    def close(self):
        """Закрывает соединение."""
        if self.connection and not self.connection.is_closed:
            self.connection.close()
            log.info("RabbitMQ connection closed")


class QueueWorker:
    """Базовый класс для воркеров очереди."""
    
    def __init__(self, queue: MessageQueue, queue_name: str):
        self.queue = queue
        self.queue_name = queue_name
    
    def process_message(self, message: Dict[str, Any]):
        """Обрабатывает сообщение. Должен быть переопределен в подклассах."""
        raise NotImplementedError
    
    def start(self):
        """Запускает воркер."""
        log.info(f"Starting worker for queue {self.queue_name}")
        try:
            self.queue.consume_tasks(
                queue_name=self.queue_name,
                callback=self.process_message,
                auto_ack=False
            )
        except KeyboardInterrupt:
            log.info("Worker stopped by user")
        finally:
            self.queue.close()






