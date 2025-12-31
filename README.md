# Alt Forecast Bot (TradingView Webhooks → Telegram)

Учебный проект: сервис крипто-аналитики с двумя каналами выдачи — **Telegram-бот** и **HTTP API (FastAPI + Web UI)**.  
Проект предназначен для **прогнозирования курса Bitcoin (BTC)** и рыночной аналитики.

Данные поступают через **TradingView webhook**, сохраняются в **SQLite (WAL)** и используются для:
- генерации отчётов,
- визуализации,
- **ML‑прогнозов BTC на основе CatBoost**.

---

## MVP scope

**Реализовано и работает:**
- Приём OHLC‑баров через `POST /webhook` (TradingView alerts)
- Хранение данных в SQLite (WAL), общий volume в Docker
- **ML‑прогноз курса Bitcoin (BTC) с использованием CatBoost**
- REST API для чтения баров, дивергенций, статистики и прогноза BTC
- Web UI (`GET /`) как дашборд для ручной проверки данных и прогнозов
- Telegram worker: команды/кнопки + отчёты и графики
- Тесты: домен, БД, REST API
- Docker + docker‑compose
- Опционально: RabbitMQ + несколько `worker‑forecast`

**Не входит в MVP:**
- торговый автотрейдинг (исполнение ордеров)
- полноценная авторизация и роли
- сложный frontend (SPA)
- production‑мониторинг / SLA
- распределённая БД

---

## ML details (Bitcoin forecast)

**Модель**
- Алгоритм: `CatBoostRegressor`
- Тип задачи: supervised regression

**Target**
- Прогнозируемая величина: `close_price` BTC
- Формат: абсолютная цена или log‑return (в зависимости от конфигурации)

**Horizon**
- Поддерживаемые горизонты: `1h`, `4h`, `24h`
- Горизонт выбирается параметром запроса API

**Features**
- OHLC‑признаки BTC
- Returns и momentum‑фичи
- Волатильность (rolling std, ATR‑подобные метрики)
- Контекст рынка (BTC.D, USDT.D, TOTAL2/TOTAL3 — опционально)
- Календарные признаки (время, сессии — при включении)

**Назначение**
Модель используется **только для аналитики и сигналов**,  
решения об открытии сделок остаются за пользователем.

ML‑логика изолирована в:
```
app/ml/
```

---

## Архитектура (кратко)

- **Domain** — модели и бизнес‑правила
- **Application** — use cases и сервисы
- **Presentation** — Telegram handlers и форматирование
- **Infrastructure** — FastAPI, SQLite, внешние API, очередь
- **ML layer** — CatBoost‑модель прогнозирования BTC

Документация:
- `ARCHITECTURE.md`
- `DOMAIN_MODEL.md`
- `MVP_IMPLEMENTATION.md`

---

## REST API (примеры)

```bash
# Исторические бары BTC
curl "http://localhost:8000/api/bars/BTC/1h?limit=100"

# ML‑прогноз BTC (CatBoost)
curl "http://localhost:8000/api/forecasts/btc?timeframe=1h"
```

