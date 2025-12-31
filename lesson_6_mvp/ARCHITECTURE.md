# Архитектура проекта Alt Forecast Bot

## Оглавление
1. [Обзор архитектуры](#обзор-архитектуры)
2. [Clean Architecture - слои](#clean-architecture---слои)
3. [Структура проекта](#структура-проекта)
4. [Паттерны проектирования](#паттерны-проектирования)
5. [Потоки данных](#потоки-данных)
6. [Компоненты системы](#компоненты-системы)

---

## Обзор архитектуры

Проект построен на принципах **Clean Architecture** (Чистой архитектуры), что обеспечивает:
- Разделение ответственности между слоями
- Независимость бизнес-логики от инфраструктуры
- Легкость тестирования
- Расширяемость и поддерживаемость

### Основные принципы

1. **Dependency Rule**: Внутренние слои не зависят от внешних
2. **Single Responsibility**: Каждый класс отвечает за одну задачу
3. **Dependency Injection**: Зависимости передаются через конструктор
4. **Factory Pattern**: Использование фабрик для создания объектов

---

## Clean Architecture - слои

### Domain Layer (Доменный слой)
**Расположение**: `app/domain/`

Содержит бизнес-логику и модели данных, не зависящие от внешних библиотек.

**Компоненты**:
- `models.py` - доменные модели
- `services.py` - доменные сервисы
- `divergence_detector.py` - логика определения дивергенций
- `chart_settings.py` - настройки графиков

**Характеристики**:
- Не зависит от других слоев
- Содержит чистую бизнес-логику
- Легко тестируется

### Application Layer (Слой приложения)
**Расположение**: `app/application/`

Содержит бизнес-логику приложения и use cases.

**Компоненты**:
- `services/` - сервисы приложения:
  - `market_data_service.py` - работа с рыночными данными
  - `bubbles_service.py` - генерация пузырьковых диаграмм
  - `forecast_service.py` - ML прогнозы
  - `twap_service.py` - расчет TWAP
  - `traditional_markets_service.py` - традиционные рынки
- `dto/` - Data Transfer Objects:
  - `bubbles_dto.py` - DTO для пузырьков
- `usecases/` - use cases:
  - `analytics.py` - аналитика
  - `generate_report.py` - генерация отчетов
  - `ingest_bar.py` - обработка баров

**Характеристики**:
- Зависит только от Domain Layer
- Содержит бизнес-логику приложения
- Использует репозитории через интерфейсы

### Presentation Layer (Слой представления)
**Расположение**: `app/presentation/`

Обрабатывает взаимодействие с пользователем (Telegram Bot).

**Компоненты**:
- `handlers/` - обработчики команд:
  - `base_handler.py` - базовый класс для всех handlers
  - `command_handler.py` - базовые команды (start, help, info)
  - `bubbles_handler.py` - обработка пузырьков
  - `chart_handler.py` - обработка графиков
  - `forecast_handler.py` - обработка прогнозов
  - `indices_handler.py` - обработка индексов (F&G, Altseason)
  - `analytics_handler.py` - аналитика
  - `handler_factory.py` - фабрика для создания handlers
- `formatters/` - форматирование сообщений:
  - `message_formatter.py` - форматирование текстовых сообщений
- `integration/` - интеграция:
  - `command_integrator.py` - интеграция команд

**Характеристики**:
- Зависит от Application Layer
- Обрабатывает пользовательский ввод
- Форматирует вывод для пользователя

### Infrastructure Layer (Слой инфраструктуры)
**Расположение**: `app/infrastructure/`

Содержит реализацию внешних зависимостей.

**Компоненты**:
- `repositories/` - репозитории:
  - `base_repository.py` - базовый класс
  - `user_repository.py` - работа с пользователями
  - `subscription_repository.py` - работа с подписками
- `db.py` - работа с базой данных (SQLite)
- `telegram_bot.py` - интеграция с Telegram Bot API
- `coingecko.py` - работа с CoinGecko API
- `coinglass.py` - работа с Coinglass API
- `binance_options.py` - работа с Binance Options API
- `cache.py` - кэширование
- `ui_keyboards.py` - клавиатуры Telegram
- `ui_router.py` - роутер для callback'ов

**Характеристики**:
- Зависит от всех других слоев
- Реализует внешние интеграции
- Содержит детали реализации

---

## Структура проекта

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

## Паттерны проектирования

### 1. Factory Pattern (Паттерн Фабрика)
**Использование**: `HandlerFactory`

Создает handlers и services с правильными зависимостями.

```python
factory = HandlerFactory(db)
handlers = factory.get_handlers()
services = factory.get_services()
```

### 2. Repository Pattern (Паттерн Репозиторий)
**Использование**: `BaseRepository`, `UserRepository`, `SubscriptionRepository`

Абстрагирует работу с базой данных.

```python
class UserRepository(BaseRepository):
    def get_user_settings(self, user_id: int):
        # Логика работы с БД
        pass
```

### 3. Handler Pattern (Паттерн Обработчик)
**Использование**: `BaseHandler`, все handlers

Обрабатывает команды и callback'и от Telegram.

```python
class BubblesHandler(BaseHandler):
    async def handle_bubbles_command(self, update, context, tf="1h"):
        # Обработка команды
        pass
```

### 4. Service Pattern (Паттерн Сервис)
**Использование**: Все services в `application/services/`

Содержит бизнес-логику приложения.

```python
class BubblesService:
    def generate_bubbles(self, timeframe: str) -> bytes:
        # Генерация пузырьков
        pass
```

### 5. DTO Pattern (Паттерн Data Transfer Object)
**Использование**: `BubblesDTO`, `BubblesSettingsDTO`

Переносит данные между слоями.

```python
@dataclass
class BubblesSettingsDTO:
    timeframe: str
    min_mcap: float
    max_mcap: float
```

### 6. Command Pattern (Паттерн Команда)
**Использование**: `CallbackRouter`, `CallbackCommand`

Инкапсулирует запросы как объекты.

```python
class CallbackCommand(ABC):
    async def execute(self, update, context):
        pass
```

---

## Потоки данных

### 1. Обработка команды от пользователя

```
User → Telegram Bot → CommandHandler → Service → Repository → Database
                                      ↓
                                   Response ← Formatter ← Service
```

**Пример**: Команда `/bubbles`

1. Пользователь отправляет `/bubbles 1h`
2. `TelegramBot` получает команду
3. `CommandIntegrator` направляет в `BubblesHandler`
4. `BubblesHandler` вызывает `BubblesService`
5. `BubblesService` получает данные через `MarketDataService`
6. `BubblesService` генерирует изображение
7. `BubblesHandler` отправляет изображение пользователю

### 2. Обработка webhook от TradingView

```
TradingView → Webhook → API Handler → UseCase → Repository → Database
```

**Пример**: Получение данных OHLC

1. TradingView отправляет webhook
2. `main_api.py` получает запрос
3. `ingest_bar` use case обрабатывает данные
4. Данные сохраняются в БД через Repository

### 3. Фоновые задачи (Job Queue)

```
Scheduler → Job → Service → Repository → Database
                    ↓
                 Telegram Bot → User
```

**Пример**: Ежечасная рассылка пузырьков

1. `JobQueue` запускает задачу каждые 60 минут
2. `hourly_bubbles` получает список подписчиков
3. Для каждого подписчика вызывается `BubblesService`
4. Изображение отправляется пользователю

---

## Компоненты системы

### 1. Telegram Bot (`infrastructure/telegram_bot.py`)

Основной класс для работы с Telegram Bot API.

**Ответственность**:
- Инициализация бота
- Регистрация handlers
- Обработка команд и callback'ов
- Интеграция с новой архитектурой

**Ключевые методы**:
- `__init__()` - инициализация
- `run()` - запуск бота
- `on_start()` - обработка команды /start
- `on_ui_btn()` - обработка callback'ов

### 2. Handler Factory (`presentation/handlers/handler_factory.py`)

Создает и инициализирует все handlers и services.

**Ответственность**:
- Создание services
- Создание handlers
- Управление зависимостями

**Ключевые методы**:
- `get_services()` - получение всех services
- `get_handlers()` - получение всех handlers

### 3. Command Integrator (`presentation/integration/command_integrator.py`)

Интегрирует новую архитектуру со старым кодом.

**Ответственность**:
- Маршрутизация команд
- Fallback на старый код
- Постепенная миграция

### 4. Database (`infrastructure/db.py`)

Работа с SQLite базой данных.

**Ответственность**:
- Подключение к БД
- Выполнение SQL запросов
- Управление транзакциями

### 5. Market Data Service (`application/services/market_data_service.py`)

Работа с рыночными данными (CoinGecko).

**Ответственность**:
- Получение данных о криптовалютах
- Кэширование данных
- Форматирование данных

### 6. Bubbles Service (`application/services/bubbles_service.py`)

Генерация пузырьковых диаграмм.

**Ответственность**:
- Получение данных о криптовалютах
- Генерация изображений
- Фильтрация по параметрам

### 7. Forecast Service (`application/services/forecast_service.py`)

ML прогнозы для криптовалют.

**Ответственность**:
- Загрузка ML модели
- Генерация прогнозов
- Кэширование результатов

---

## Зависимости между слоями

```
Presentation Layer
    ↓ зависит от
Application Layer
    ↓ зависит от
Domain Layer
    ↑ зависит от
Infrastructure Layer
```

**Правило**: Зависимости направлены внутрь. Внешние слои зависят от внутренних, но не наоборот.

---

## Расширение проекта

### Добавление новой команды

1. Создать handler в `presentation/handlers/`
2. Добавить метод в handler
3. Зарегистрировать в `HandlerFactory`
4. Добавить маршрутизацию в `CommandIntegrator`
5. Зарегистрировать в `TelegramBot`

### Добавление нового сервиса

1. Создать service в `application/services/`
2. Добавить в `HandlerFactory.get_services()`
3. Использовать в handlers через dependency injection

### Добавление нового репозитория

1. Создать repository в `infrastructure/repositories/`
2. Наследоваться от `BaseRepository`
3. Использовать в services

---

## Тестирование

### Unit тесты

Тестирование отдельных компонентов без зависимостей.

**Примеры**:
- Тестирование services без БД
- Тестирование handlers с mock services
- Тестирование domain логики

### Integration тесты

Тестирование взаимодействия между компонентами.

**Примеры**:
- Тестирование handlers с реальными services
- Тестирование repositories с БД
- Тестирование всего потока команды

---

## Заключение

Архитектура проекта следует принципам Clean Architecture, что обеспечивает:
- Чистый и понятный код
- Легкость тестирования
- Расширяемость
- Поддерживаемость

Для изучения проекта рекомендуется:
1. Начать с `main_worker.py` - точка входа
2. Изучить `HandlerFactory` - создание компонентов
3. Изучить handlers - обработка команд
4. Изучить services - бизнес-логика
5. Изучить repositories - работа с БД













