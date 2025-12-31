# Alt Forecast Bot (TradingView Webhooks → Telegram)

> **Учебный проект** - Телеграм-бот для криптовалютной аналитики на основе Clean Architecture

## Доменная модель → DOMAIN_MODEL.md, app/domain/*

1. Доменная модель сервиса 

DOMAIN_MODEL.md — текстовое описание доменной модели (Bar, Metric, Timeframe, Divergence, MarketRegime и т.д.)

app/domain/models.py — типы и dataclass’ы (Metric, Timeframe, Implication, константы METRICS, TIMEFRAMES, маппинги импликаций и т.п.)

app/domain/services.py, app/domain/market_regime/*, app/domain/divergence_detector.py — доменные сервисы поверх этих моделей.

Плюс архитектурный контекст в ARCHITECTURE.md.

## СУБД → SQLite, app/infrastructure/db.py

app/infrastructure/db.py — класс DB, создаёт и инициализирует SQLite:

таблица bars (метрика, таймфрейм, ts, o,h,l,c,v),

subs, user_settings,

divs (дивергенции),

trades (для TWAP / крупных сделок) и т.д.

Путь к БД через конфиг: DATABASE_PATH из app/config.py / окружения.

В Docker Compose база живёт в volume:

DATABASE_PATH=/data/data.db

volume dbdata монтируется в /data.

Тесты:

tests/test_database.py — проверка базовых операций с DB.


## REST → FastAPI, app/infrastructure/rest_api.py, app/main_api.py

Основные файлы:

app/infrastructure/rest_api.py

FastAPI роуты: /api/bars, /api/bars/{metric}/{timeframe}, /api/forecasts/btc, /api/metrics/stats, /api/divergences, /api/stats и т.п.

Ответы описаны через pydantic-модели: BarResponse, ForecastResponse, DivergenceResponse, MetricsStatsResponse.

Функция create_rest_api_router(app: FastAPI, db: DB) навешивает все эти endpoints на приложение.

app/infrastructure/webhook.py

Создаёт app = FastAPI(...)

Вызывает create_rest_api_router(app, _db) — REST привинчен к основному приложению.

app/main_api.py — просто реэкспорт app для запуска через Uvicorn:
from .infrastructure.webhook import app.

Тесты:

tests/test_rest_api.py — проверка ключевых REST маршрутов через TestClient.

Swagger/Redoc у FastAPI включается автоматически — при запуске API у тебя будут /docs и /redoc.

## UI → app/infrastructure/static/index.html, GET /

Фронтенд:

app/infrastructure/static/index.html

Адаптивный dashboard (метрики, таймфреймы, количество баров, активные дивергенции).

Управляющие элементы (селекты метрики/таймфрейма/лимита).

JS ходит в твой REST:

/api/stats

/api/forecasts/btc

/api/bars/{metric}/{timeframe}

/api/divergences

В app/infrastructure/webhook.py:

app.mount("/static", StaticFiles(...))

@app.get("/") → отдаёт index.html.

То есть пользователь может открыть http://localhost:8000/ и реально «потыкать» сервис.

Плюс:

Telegram-бот как отдельный UI-канал реализован в слоях app/presentation/*, app/usecases, и воркер (app/main_worker.py).

## Тесты → tests/*,

Что есть:

Папка tests/:

test_database.py — операции с БД.

test_domain_models.py — доменные модели/логика.

test_rest_api.py — REST эндпоинты.

test_report_generation.py

test_market_doctor_report.py

test_direct_report_generation.py

test_bot_report_generation.py

test_large_trades.py

test_v2_generator.py

test_render_report.py

Настройки pytest: pytest.ini, tests/conftest.py (фикстуры временной базы, TestClient и т.д.).

## Docker → Dockerfile.api, Dockerfile.worker, docker-compose.yml

Файлы:

Dockerfile.api

python:3.11-slim

установка зависимостей из requirements.api.txt

копирование app/

HEALTHCHECK через HTTP /healthz

запуск: uvicorn app.main_api:app ...

Dockerfile.worker

python:3.11-slim, MPLBACKEND=Agg для headless-графиков

системные зависимости (git, curl)

установка requirements.worker.txt

установка tradingview-datafeed

HEALTHCHECK через pgrep

запуск: python -m app.main_worker

docker-compose.yml:

сервис api (образ alt-forecast-api:latest, порт 8000)

сервис worker

сервис worker-forecast

сервис rabbitmq + rabbitmq-management

volume dbdata для базы.

## Масштабирование → rabbitmq + сервис worker-forecast, docker compose --scale.

В docker-compose.yml есть отдельный сервис worker-forecast:

использует тот же код (образ alt-forecast-worker:latest), общую БД и RabbitMQ.

через RabbitMQ можно запускать несколько воркеров параллельно.


## Документация

### Техническая документация
- **[ARCHITECTURE.md](./ARCHITECTURE.md)** - Подробное описание архитектуры проекта
- **[DOMAIN_MODEL.md](./DOMAIN_MODEL.md)** - Доменная модель сервиса
- **[MVP_IMPLEMENTATION.md](./MVP_IMPLEMENTATION.md)** - Текущая реализация MVP

##  MVP Реализация

Проект реализует полноценный MVP со следующими компонентами:

1. **Доменная модель** 
   - Документирована в [DOMAIN_MODEL.md](./DOMAIN_MODEL.md)
   - Определены основные сущности: Bar, Metric, Timeframe, Divergence, Implication
   - Реализованы доменные сервисы

2. **База данных** 
   - SQLite с WAL mode для конкурентного доступа
   - Оптимизированные индексы
   - Миграции схемы

3. **REST API** 
   - Полноценный REST интерфейс с FastAPI
   - Интерактивная документация (Swagger/ReDoc)
   - Валидация данных через Pydantic
   - Endpoints для баров, прогнозов, метрик, дивергенций

4. **Веб-интерфейс** 
   - Современный HTML/JS фронтенд
   - Dashboard с визуализацией данных
   - Интеграция с REST API

5. **Тестирование** 
   - Unit тесты для доменных моделей
   - Интеграционные тесты для БД
   - Тесты для REST API
   - Настроен pytest с покрытием

6. **Docker** 
   - Оптимизированные Dockerfiles
   - Docker Compose для оркестрации
   - Health checks для всех сервисов
   - Горячая перезагрузка в разработке

7. **Масштабирование** 
   - RabbitMQ для очередей сообщений
   - Отдельные воркеры для прогнозирования
   - Возможность масштабирования через `docker compose scale`
   - Поддержка нескольких воркеров для параллельной обработки

## Описание проекта

Alt Forecast Bot - это телеграм-бот для криптовалютной аналитики, построенный на принципах **Clean Architecture**. Бот предоставляет:

- Анализ криптовалютных рынков
- Графики и визуализация данных
- ML прогнозы цен
- Индексы (Fear & Greed, Altseason)
- Опционы и деривативы
- Уведомления и алерты

## Архитектура

Проект использует **Clean Architecture** с разделением на слои:

- **Domain Layer** - бизнес-логика и модели
- **Application Layer** - сервисы и use cases
- **Presentation Layer** - handlers для Telegram Bot
- **Infrastructure Layer** - репозитории, БД, внешние API

Подробнее в [ARCHITECTURE.md](./ARCHITECTURE.md)

## ✨ Основные функции

- **Docker** + чистая архитектура (API / Worker)
- **TradingView Webhooks** (Once Per Bar Close) на ТФ 15m/1h/4h/1D
- **Метрики**: BTC, USDT.D, BTC.D, TOTAL2, TOTAL3, ETHBTC
- **SQLite (WAL)** - хранение OHLC данных
- **Дивергенции**: Price↔RSI, Price↔MACD и Volume
- **Ключевые уровни S/R** на основе свингов
- **Отчёты** вида: `TOTAL3: ⬆ 15m ⬇ 1h → 4h ⬆ 24h` + оценка режима (Risk-ON/OFF)
- **Визуализация**: пузырьковые диаграммы, графики, gauge-индикаторы
- **ML прогнозы** для BTC и альткоинов
- **Традиционные рынки**: S&P500, золото, нефть
- **TWAP** (Time-Weighted Average Price)

### 1. Установка зависимостей

```bash
# Клонирование репозитория
git clone <repository-url>
cd alt-forecast-bot

# Создание виртуального окружения
python -m venv venv
source venv/bin/activate  # Linux/Mac
# или
venv\Scripts\activate  # Windows

# Установка зависимостей
pip install -r requirements.worker.txt
pip install -r requirements.api.txt
pip install -r requirements.test.txt  # Для тестов
```

### 2. Настройка окружения

Создайте файл `.env`:

```env
TELEGRAM_BOT_TOKEN=123:ABC...
ADMIN_CHAT_ID=123456789
SECRET_WEBHOOK_TOKEN=long_random_secret
TV_BTC_SYMBOL=BINANCE:BTCUSDT
TZ=Europe/Amsterdam
DATABASE_PATH=./data/data.db

# Опционально
COINGECKO_API_KEY=your_api_key
COINGLASS_API_KEY=your_api_key
LOG_LEVEL=INFO
```

### 3. Запуск проекта

#### Вариант 1: Docker (рекомендуется)

```bash
# Запуск всех сервисов
docker compose up -d --build

# Масштабирование воркеров прогнозирования (пример: 3 воркера)
docker compose up -d --scale worker-forecast=3

# Просмотр логов
docker compose logs -f api worker worker-forecast

# Остановка
docker compose down
```

**Сервисы:**
- **API** (порт 8000) - REST API и веб-интерфейс
- **Worker** - Telegram бот
- **Worker-forecast** - Воркеры для обработки задач прогнозирования (масштабируемые)
- **RabbitMQ** (порт 5672) - Очередь сообщений для масштабирования
- **RabbitMQ Management UI** (порт 15672) - Веб-интерфейс для управления очередями

#### Вариант 2: Локальный запуск

```bash
# Worker (Telegram Bot)
python -m app.main_worker

# API (Webhook)
python -m app.main_api
```

### 4. Настройка TradingView (опционально)

В TradingView создайте по 4 алерта (15/60/240/1D, Once Per Bar Close) на символы:
- CRYPTOCAP:USDT.D
- CRYPTOCAP:BTC.D
- CRYPTOCAP:TOTAL2
- CRYPTOCAP:TOTAL3
- BINANCE:BTCUSDT (или свой через TV_BTC_SYMBOL)
- BINANCE:ETHBTC

URL вебхука: `http://<ip>:8000/webhook`
Message — JSON из `pine/tv_alerts_template.pine` (см. комментарий внутри)


## Технологии

- **Python 3.11** - основной язык
- **FastAPI** - REST API фреймворк
- **python-telegram-bot** - работа с Telegram Bot API
- **SQLite** - база данных (WAL mode)
- **Docker & Docker Compose** - контейнеризация
- **RabbitMQ** - очередь сообщений для масштабирования
- **Clean Architecture** - архитектура проекта
- **Machine Learning (CatBoost, LightGBM)** - прогнозы цен
- **Matplotlib/Pillow** - визуализация
- **Pytest** - тестирование

## REST API

Проект предоставляет REST API для доступа к данным и прогнозам:

### Endpoints

- `GET /` - Веб-интерфейс (Dashboard)
- `GET /docs` - Интерактивная документация API (Swagger)
- `GET /redoc` - Альтернативная документация API (ReDoc)
- `GET /healthz` - Health check
- `POST /webhook` - Webhook для получения данных от TradingView

### API Endpoints

- `GET /api/bars` - Список баров с фильтрацией
- `GET /api/bars/{metric}/{timeframe}` - Бары для конкретной метрики и таймфрейма
- `GET /api/metrics/stats` - Статистика по метрикам
- `GET /api/forecasts/btc` - Прогноз для BTC
- `GET /api/divergences` - Список дивергенций
- `GET /api/stats` - Общая статистика API

### Примеры использования

```bash
# Получить последние 100 баров BTC за 1 час
curl http://localhost:8000/api/bars/BTC/1h?limit=100

# Получить прогноз BTC
curl http://localhost:8000/api/forecasts/btc?timeframe=1h

# Получить активные дивергенции
curl http://localhost:8000/api/divergences?status=active&limit=50
```

## Тестирование

```bash
# Запуск всех тестов
pytest

# Запуск с покрытием
pytest --cov=app --cov-report=html

# Запуск конкретных тестов
pytest tests/test_database.py
pytest tests/test_rest_api.py
pytest tests/test_domain_models.py
```

## Структура проекта

```
app/
├── domain/              # Domain Layer - бизнес-логика
├── application/         # Application Layer - сервисы и use cases
├── presentation/        # Presentation Layer - handlers для Telegram
├── infrastructure/      # Infrastructure Layer - репозитории, БД, API
├── ml/                 # Machine Learning - модели и прогнозы
├── visual/             # Визуализация - графики и диаграммы
├── main_worker.py      # Точка входа (Worker)
└── main_api.py         # Точка входа (API)
```

Подробнее в [ARCHITECTURE.md](./ARCHITECTURE.md)

## Учебные материалы

### Паттерны проектирования

- **Factory Pattern** - создание handlers и services
- **Repository Pattern** - работа с базой данных
- **Handler Pattern** - обработка команд
- **Service Pattern** - бизнес-логика
- **DTO Pattern** - передача данных
- **Command Pattern** - обработка callback'ов

### Принципы

- **Clean Architecture** - разделение слоёв
- **Dependency Injection** - инъекция зависимостей
- **Single Responsibility** - единственная ответственность
- **Dependency Rule** - правило зависимостей


## Полезные ссылки

- [Clean Architecture](https://blog.cleancoder.com/uncle-bob/2012/08/13/the-clean-architecture.html)
- [Telegram Bot API](https://core.telegram.org/bots/api)
- [python-telegram-bot](https://python-telegram-bot.org/)
- [CoinGecko API](https://www.coingecko.com/en/api)


