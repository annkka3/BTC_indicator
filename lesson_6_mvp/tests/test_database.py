"""
Тесты для работы с базой данных.
"""

import pytest
import time
from app.infrastructure.db import DB


def test_db_initialization(temp_db):
    """Тест инициализации базы данных."""
    assert temp_db is not None
    assert temp_db.conn is not None


def test_upsert_bar(temp_db):
    """Тест добавления/обновления бара."""
    now_ms = int(time.time() * 1000)
    
    temp_db.upsert_bar("BTC", "1h", now_ms, 42000.0, 42500.0, 41800.0, 42300.0, 1000000.0)
    
    bars = temp_db.last_n("BTC", "1h", 1)
    assert len(bars) == 1
    
    bar = bars[0]
    assert bar[0] == now_ms  # ts
    assert bar[1] == 42000.0  # open
    assert bar[4] == 42300.0  # close
    assert bar[5] == 1000000.0  # volume


def test_last_n(temp_db, sample_bars):
    """Тест получения последних N баров."""
    # Добавляем тестовые бары
    for bar in sample_bars:
        temp_db.upsert_bar(*bar)
    
    bars = temp_db.last_n("BTC", "1h", 2)
    assert len(bars) == 2
    
    # Проверяем, что бары упорядочены по времени (oldest first)
    assert bars[0][0] < bars[1][0]


def test_get_last_ts(temp_db, sample_bars):
    """Тест получения времени последнего бара."""
    # Добавляем тестовые бары
    for bar in sample_bars:
        temp_db.upsert_bar(*bar)
    
    last_ts = temp_db.get_last_ts("BTC", "1h")
    assert last_ts == sample_bars[-1][2]  # ts из последнего бара


def test_user_settings(temp_db):
    """Тест работы с настройками пользователя."""
    user_id = 12345
    
    # Получаем настройки (должны быть дефолтные)
    settings = temp_db.get_user_settings(user_id)
    assert settings[0] == "usd"  # vs_currency
    assert settings[1] == 50  # bubbles_count
    
    # Обновляем настройки
    temp_db.set_user_settings(user_id, bubbles_count=100, vs_currency="eur")
    
    # Проверяем обновление
    settings = temp_db.get_user_settings(user_id)
    assert settings[0] == "eur"
    assert settings[1] == 100


def test_upsert_many_bars(temp_db):
    """Тест батч-вставки баров."""
    now_ms = int(time.time() * 1000)
    
    bars = [
        ("BTC", "1h", now_ms - 3600000, 42000.0, 42500.0, 41800.0, 42300.0, 1000000.0),
        ("BTC", "1h", now_ms, 42300.0, 42800.0, 42100.0, 42600.0, 1100000.0),
        ("ETH", "1h", now_ms, 2500.0, 2550.0, 2480.0, 2530.0, 500000.0),
    ]
    
    with temp_db.atomic():
        temp_db.upsert_many_bars(bars)
    
    btc_bars = temp_db.last_n("BTC", "1h", 10)
    assert len(btc_bars) == 2
    
    eth_bars = temp_db.last_n("ETH", "1h", 10)
    assert len(eth_bars) == 1






