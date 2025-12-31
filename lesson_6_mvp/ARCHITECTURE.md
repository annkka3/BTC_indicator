# Архитектура Alt Forecast Bot

Проект — сервис крипто-аналитики с двумя каналами выдачи:

- **Telegram-бот** (интерактивные команды, кнопки, отчёты, изображения)
- **HTTP API** (REST + простой веб-дашборд)

Входные данные поступают из:
- **TradingView webhook** (OHLC по выбранным метрикам и таймфреймам)
- внешних API (CoinGecko / CoinGlass и др., если включены)

Хранилище данных — **SQLite** в режиме WAL, используемое всеми сервисами через общий volume.

---

## Общая схема

                TradingView
                   |
                   |  (webhook)
                   v
             +--------------+
             |   FastAPI    |
             |     API      |
             |              |
             |  /webhook    |
             |  /api/*      |
             |  / (UI)      |
             +------+-------+
                    |
                    |  write / read
                    v
             +--------------+
             |   SQLite     |
             |   (WAL)      |
             +------+-------+
                    ^
                    |  read
                    |
             +------+-------+
             |   Worker     |
             |  Telegram    |
             |     Bot      |
             +------+-------+
                    |
                    |  async jobs (optional)
                    v
             +--------------+
             |  RabbitMQ    |
             | (task queue) |
             +--------------+



```
app/
├── domain/              # Domain Layer
│   ├── models.py
│   ├── services.py
│   ├── divergence_detector.py
│   └── chart_settings.py
│
├── application/         # Application Layer
│   ├── services/       # Бизнес-логика
│   │   ├── market_data_service.py
│   │   ├── bubbles_service.py
│   │   ├── forecast_service.py
│   │   ├── twap_service.py
│   │   └── traditional_markets_service.py
│   ├── dto/           # Data Transfer Objects
│   │   └── bubbles_dto.py
│   └── usecases/      # Use Cases
│       ├── analytics.py
│       ├── generate_report.py
│       └── ingest_bar.py
│
├── presentation/        # Presentation Layer
│   ├── handlers/      # Обработчики команд
│   │   ├── base_handler.py
│   │   ├── command_handler.py
│   │   ├── bubbles_handler.py
│   │   ├── chart_handler.py
│   │   ├── forecast_handler.py
│   │   ├── indices_handler.py
│   │   ├── analytics_handler.py
│   │   └── handler_factory.py
│   ├── formatters/    # Форматирование
│   │   └── message_formatter.py
│   └── integration/   # Интеграция
│       └── command_integrator.py
│
├── infrastructure/      # Infrastructure Layer
│   ├── repositories/  # Репозитории
│   │   ├── base_repository.py
│   │   ├── user_repository.py
│   │   └── subscription_repository.py
│   ├── db.py          # База данных
│   ├── telegram_bot.py # Telegram Bot
│   ├── coingecko.py   # CoinGecko API
│   ├── coinglass.py   # Coinglass API
│   ├── cache.py       # Кэширование
│   ├── ui_keyboards.py # Клавиатуры
│   └── ui_router.py   # Роутер
│
├── ml/                 # Machine Learning
│   ├── model.py
│   ├── forecaster.py
│   ├── features.py
│   └── data_adapter.py
│
├── visual/             # Визуализация
│   ├── bubbles.py
│   ├── chart_renderer.py
│   ├── altseason_gauge.py
│   └── ...
│
├── main_worker.py      # Точка входа (Worker)
└── main_api.py         # Точка входа (API)
```


---

## Слои и ответственность

### Domain (`app/domain/`)
Содержит предметную модель и чистую бизнес-логику.

Здесь находятся:
- доменные сущности и типы (Bar, Metric, Timeframe, Divergence, MarketRegime и т.п.)
- доменные сервисы и расчёты (например, детекторы дивергенций, логика режимов рынка)

Здесь **нет**:
- SQL
- HTTP / Telegram
- внешних API
- логики запуска приложения

---

### Application (`app/application/`)
Оркестрирует сценарии использования системы.

Содержит:
- use cases (`usecases/*`): ingest баров, генерация отчётов, аналитика
- сервисы приложения (`services/*`): прогнозы, TWAP, пузырьковые диаграммы
- DTO для передачи данных между слоями

Зависит от Domain, но не содержит инфраструктурных деталей.

---

### ML Layer (Bitcoin Forecast)

ML-логика выделена логически и используется Application Layer.

**Назначение**
- прогноз курса Bitcoin (BTC),
- поддержка аналитических отчётов и сигналов.

**Реализация**
- алгоритм: `CatBoostRegressor`
- тип задачи: регрессия
- горизонты: 1h / 4h / 24h

**Важно**
- ML не влияет на доменные правила,
- модель используется только для аналитики,
- автотрейдинг отсутствует.

Код размещён в:
```
app/ml/
```
---

### Presentation (`app/presentation/`)
Telegram-интерфейс.

Отвечает за:
- обработку команд и callback-кнопок
- вызов соответствующих use cases
- форматирование ответа пользователю

Handlers не реализуют бизнес-логику — только маршрутизацию и UI.

---

### Infrastructure (`app/infrastructure/`)
Реализация внешних зависимостей и технических деталей.

Содержит:
- работу с SQLite и репозитории
- Telegram Bot API
- HTTP API (FastAPI), webhook, статический UI
- клиенты внешних API
- кеширование

Infrastructure может зависеть от всех слоёв, остальные слои от него — нет.

---

## Точки входа

- `app/main_api.py`  
  Запуск FastAPI: webhook, REST API, веб-интерфейс.

- `app/main_worker.py`  
  Запуск Telegram-бота.

- `worker-forecast` (опционально)  
  Отдельный воркер для тяжёлых задач (через очередь).

---

## Потоки данных

### TradingView → база данных
1. TradingView отправляет JSON на `POST /webhook`
2. Webhook валидирует payload
3. Use case `ingest_bar` преобразует данные в доменную модель Bar
4. Бар сохраняется в SQLite

Инвариант: бар уникален по `(metric, timeframe, ts)`.

## Поток данных (MVP)

```
TradingView
    |
    v
FastAPI /webhook
    |
    v
SQLite (WAL)
    |
    +--> Application Services
            |
            +--> ML (CatBoost, BTC forecast)
            |
            +--> Reports / API / Telegram
```

---


### Telegram → аналитика → ответ
1. Пользователь отправляет команду или нажимает кнопку
2. Handler выбирает сценарий
3. Use case обращается к доменной логике и БД
4. Форматтер собирает текст или изображение
5. Ответ отправляется пользователю

---

### REST / UI → чтение данных
- Веб-интерфейс (`GET /`) обращается к `/api/*`
- API читает данные из SQLite и сервисов аналитики
- API не содержит бизнес-логики, только обёртки

---

### Очереди и масштабирование (опционально)
RabbitMQ используется для:
- асинхронной обработки тяжёлых задач
- запуска нескольких `worker-forecast` параллельно

Базовый MVP не требует очередей и работает с одним воркером.

---

## Используемые паттерны

- **Repository** — изоляция доступа к SQLite
- **Factory** — централизованная сборка handlers и services
- **Use Case** — отдельные сценарии работы системы
- **DTO** — передача данных между слоями без протекания инфраструктуры

---

## Архитектурные компромиссы

1. **SQLite вместо Postgres**  
   Выбран ради простоты запуска и минимальной инфраструктуры.  
   Подходит для MVP и умеренной нагрузки.

2. **Два канала выдачи (Telegram + Web UI)**  
   Удобно для демонстрации и отладки, требует строгого разделения логики.

3. **Очереди как опция, а не обязательное условие**  
   RabbitMQ подключается только при росте нагрузки.

---

## Рекомендуемый порядок изучения кода

1. `main_api.py`, `infrastructure/webhook.py`
2. `main_worker.py`
3. `presentation/handlers/*`
4. `application/usecases/*`
5. `domain/*`
6. `infrastructure/db.py`












