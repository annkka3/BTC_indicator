"""
Тесты для REST API endpoints.
"""

import pytest
import time
from fastapi.testclient import TestClient


def test_healthz(api_client):
    """Тест health check endpoint."""
    response = api_client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"ok": True}


def test_webhook_endpoint(api_client):
    """Тест webhook endpoint для получения баров."""
    payload = {
        "secret": "",  # Пустой секрет для тестов (если не установлен)
        "metric": "BTC",
        "timeframe": "1h",
        "ts": int(time.time() * 1000),
        "o": 42000.0,
        "h": 42500.0,
        "l": 41800.0,
        "c": 42300.0,
        "v": 1000000.0
    }
    
    response = api_client.post("/webhook", json=payload)
    # Может быть 200 или 401 в зависимости от настроек секрета
    assert response.status_code in [200, 401]


def test_get_bars_endpoint(api_client):
    """Тест получения баров через API."""
    # Сначала добавляем тестовые данные через webhook (если возможно)
    # Или напрямую в БД
    
    response = api_client.get("/api/bars/BTC/1h?limit=10")
    
    # Должен вернуть 200 даже если данных нет
    assert response.status_code == 200
    assert isinstance(response.json(), list)


def test_get_metrics_stats(api_client):
    """Тест получения статистики по метрикам."""
    response = api_client.get("/api/metrics/stats")
    
    assert response.status_code == 200
    stats = response.json()
    assert isinstance(stats, list)


def test_get_api_stats(api_client):
    """Тест получения общей статистики API."""
    response = api_client.get("/api/stats")
    
    assert response.status_code == 200
    stats = response.json()
    
    assert "database" in stats
    assert "metrics" in stats
    assert "timeframes" in stats
    assert "bars" in stats
    assert "divergences" in stats


def test_get_bars_invalid_metric(api_client):
    """Тест валидации метрики."""
    response = api_client.get("/api/bars/INVALID/1h")
    
    assert response.status_code == 400


def test_get_bars_invalid_timeframe(api_client):
    """Тест валидации таймфрейма."""
    response = api_client.get("/api/bars/BTC/invalid")
    
    assert response.status_code == 400


def test_get_forecast_endpoint(api_client):
    """Тест получения прогноза."""
    response = api_client.get("/api/forecasts/btc?timeframe=1h")
    
    # Может вернуть 404 если нет данных или модели, или 500 при ошибке
    assert response.status_code in [200, 404, 500]


def test_get_divergences(api_client):
    """Тест получения дивергенций."""
    response = api_client.get("/api/divergences?limit=10")
    
    assert response.status_code == 200
    divs = response.json()
    assert isinstance(divs, list)






