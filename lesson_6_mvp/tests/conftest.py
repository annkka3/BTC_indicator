"""
Конфигурация pytest для тестов.
"""

import pytest
import tempfile
import os
from pathlib import Path

from app.infrastructure.db import DB
from app.config import settings


@pytest.fixture
def temp_db():
    """Создает временную базу данных для тестов."""
    with tempfile.NamedTemporaryFile(delete=False, suffix='.db') as f:
        db_path = f.name
    
    db = DB(db_path)
    
    # Добавляем тестовые данные
    yield db
    
    # Очистка
    db.close()
    if os.path.exists(db_path):
        os.unlink(db_path)


@pytest.fixture
def sample_bars():
    """Возвращает примеры баров для тестов."""
    import time
    now_ms = int(time.time() * 1000)
    
    return [
        ("BTC", "1h", now_ms - 3600000 * 2, 42000.0, 42500.0, 41800.0, 42300.0, 1000000.0),
        ("BTC", "1h", now_ms - 3600000, 42300.0, 42800.0, 42100.0, 42600.0, 1100000.0),
        ("BTC", "1h", now_ms, 42600.0, 43000.0, 42400.0, 42900.0, 1200000.0),
    ]


@pytest.fixture
def api_client():
    """Создает тестовый клиент для FastAPI."""
    from fastapi.testclient import TestClient
    from app.infrastructure.webhook import app
    
    # Переопределяем БД на временную для тестов
    import tempfile
    with tempfile.NamedTemporaryFile(delete=False, suffix='.db') as f:
        test_db_path = f.name
    
    # Инициализируем тестовую БД
    test_db = DB(test_db_path)
    
    # Переопределяем глобальную переменную _db в модуле
    import app.infrastructure.webhook as webhook_module
    original_db = getattr(webhook_module, '_db', None)
    webhook_module._db = test_db
    
    client = TestClient(app)
    
    yield client
    
    # Восстанавливаем
    test_db.close()
    if os.path.exists(test_db_path):
        os.unlink(test_db_path)
    if original_db is not None:
        webhook_module._db = original_db






