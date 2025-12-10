# Доменная модель сервиса Alt Forecast Bot

## Обзор

Доменная модель представляет бизнес-логику и ключевые сущности системы для анализа криптовалютных рынков и генерации прогнозов.

## Основные сущности

### 1. Bar (OHLCV-бар)
**Описание**: Представляет свечу (candle) с ценовыми данными за определенный период времени.

**Атрибуты**:
- `metric: Metric` - метрика (BTC, USDT.D, BTC.D, TOTAL2, TOTAL3, ETHBTC)
- `timeframe: Timeframe` - таймфрейм (15m, 1h, 4h, 1d)
- `ts: int` - время закрытия бара в unix миллисекундах
- `o: float` - цена открытия (open)
- `h: float` - максимальная цена (high)
- `l: float` - минимальная цена (low)
- `c: float` - цена закрытия (close)
- `v: float | None` - объем торгов (volume), опционально

**Бизнес-правила**:
- Должно выполняться: `l <= min(o, c) <= max(o, c) <= h`
- Бар уникален по комбинации (metric, timeframe, ts)
- ts всегда в миллисекундах

### 2. Metric (Метрика)
**Описание**: Тип рыночной метрики для отслеживания.

**Значения**:
- `BTC` - цена Bitcoin
- `USDT.D` - доминирование USDT
- `BTC.D` - доминирование Bitcoin
- `TOTAL2` - капитализация альткоинов (без BTC)
- `TOTAL3` - капитализация альткоинов (без BTC и ETH)
- `ETHBTC` - отношение ETH к BTC

**Бизнес-логика**:
- Каждая метрика имеет специфические импликации для альткоинов
- Изменение метрик влияет на оценку режима рынка (risk-on/risk-off)

### 3. Timeframe (Таймфрейм)
**Описание**: Временной интервал для анализа.

**Значения**:
- `15m` - 15 минут
- `1h` - 1 час
- `4h` - 4 часа
- `1d` - 1 день

### 4. Divergence (Дивергенция)
**Описание**: Сигнал расхождения между ценой и техническим индикатором.

**Атрибуты**:
- `timeframe: Timeframe` - таймфрейм
- `metric: Metric | None` - метрика (может быть None для парных дивергенций)
- `indicator: str` - тип индикатора (RSI, MACD, VOLUME, PAIR)
- `text: str` - текстовое описание
- `implication: Implication` - влияние на альткоины
- `pivot_l_ts: int | None` - время левого пивота
- `pivot_l_val: float | None` - значение левого пивота
- `pivot_r_ts: int | None` - время правого пивота
- `pivot_r_val: float | None` - значение правого пивота
- `detected_ts: int` - время обнаружения
- `status: str` - статус (active, confirmed, invalid)
- `confirm_ts: int | None` - время подтверждения
- `confirm_grade: str | None` - тип подтверждения (soft, hard)
- `invalid_ts: int | None` - время инвалидации
- `score: float` - качество сигнала (0.0 - 1.0)

**Бизнес-правила**:
- Дивергенция может быть бычьей (bullish) или медвежьей (bearish)
- Влияние на альткоины: bullish_alts, bearish_alts, neutral
- Дивергенция проходит жизненный цикл: active → confirmed/invalid

### 5. Implication (Импликация)
**Описание**: Влияние изменения метрики на альткоины.

**Значения**:
- `bullish_alts` - позитивно для альткоинов
- `bearish_alts` - негативно для альткоинов
- `neutral` - нейтрально

**Маппинг метрик**:
```
USDT.D ↑ → bearish_alts (деньги уходят в стейблкоины)
USDT.D ↓ → bullish_alts (деньги идут в рисковые активы)
BTC.D ↑ → bearish_alts (деньги идут в BTC)
BTC.D ↓ → bullish_alts (деньги уходят из BTC)
TOTAL2/TOTAL3 ↑ → bullish_alts
TOTAL2/TOTAL3 ↓ → bearish_alts
ETHBTC ↑ → bullish_alts (ETH опережает BTC)
```

### 6. Direction (Направление)
**Описание**: Направление изменения цены.

**Значения**:
- `up` - рост
- `down` - падение
- `flat` - боковое движение

**Определение**:
- Используется порог `eps = 1e-6` для определения flat

### 7. User Settings (Настройки пользователя)
**Описание**: Персонализированные настройки пользователя Telegram бота.

**Атрибуты**:
- `user_id: int` - идентификатор пользователя
- `vs_currency: str` - базовая валюта (по умолчанию 'usd')
- `bubbles_count: int` - количество пузырьков на диаграмме (по умолчанию 50)
- `bubbles_hide_stables: int` - скрывать стейблкоины (0/1)
- `bubbles_seed: int` - seed для генерации пузырьков (по умолчанию 42)
- `bubbles_size_mode: str` - режим размера пузырьков ('percent', 'cap', 'volume_share', 'volume_24h')
- `bubbles_top: int` - топ монет для отображения (100, 200, 300, 400, 500)
- `bubbles_tf: str` - таймфрейм для пузырьков ('15m', '1h', '1d')
- `daily_digest: int` - ежедневный дайджест (0/1)
- `daily_hour: int` - час рассылки дайджеста (0-23)
- `chart_settings: str | None` - настройки графиков (JSON)

### 8. Subscription (Подписка)
**Описание**: Подписка пользователя на периодические отчеты.

**Атрибуты**:
- `chat_id: int` - идентификатор чата Telegram

## Связи между сущностями

```
Bar ──belongs_to──> Metric
Bar ──belongs_to──> Timeframe

Divergence ──detected_on──> Metric (optional)
Divergence ──detected_on──> Timeframe
Divergence ──has──> Implication

User Settings ──belongs_to──> User (Telegram)

Subscription ──belongs_to──> User (Telegram)
```

## Доменные сервисы

### 1. Divergence Detector
**Ответственность**: Обнаружение дивергенций на графиках.

**Методы**:
- `detect_rsi_divergence()` - обнаружение дивергенции RSI
- `detect_macd_divergence()` - обнаружение дивергенции MACD
- `detect_volume_divergence()` - обнаружение дивергенции объема

### 2. Implication Calculator
**Ответственность**: Вычисление импликаций изменения метрик для альткоинов.

**Методы**:
- `implication_for_alts(metric, direction) -> Implication` - вычисление импликации
- `direction_from_delta(delta, eps) -> Direction` - определение направления

### 3. Market State Analyzer
**Ответственность**: Анализ текущего состояния рынка.

**Методы**:
- `get_risk_mode()` - определение режима (risk-on/risk-off)
- `get_market_regime()` - определение режима рынка

## Инварианты и бизнес-правила

1. **Уникальность баров**: Комбинация (metric, timeframe, ts) уникальна
2. **Консистентность OHLC**: `l <= min(o, c) <= max(o, c) <= h`
3. **Временная упорядоченность**: Бары должны быть упорядочены по времени
4. **Импликации**: Изменение каждой метрики имеет предопределенную импликацию
5. **Жизненный цикл дивергенций**: active → confirmed/invalid (нельзя вернуться назад)

## Границы контекста

### Внутренние сущности (Domain Layer)
- Bar
- Metric
- Timeframe
- Divergence
- Implication
- Direction

### Внешние интеграции (Infrastructure Layer)
- Telegram Bot API
- CoinGecko API
- TradingView Webhooks
- База данных (SQLite)

### Границы ответственности
- **Domain Layer**: Чистая бизнес-логика, независимая от инфраструктуры
- **Application Layer**: Оркестрация доменных сервисов
- **Infrastructure Layer**: Внешние интеграции, персистентность

## Расширяемость

Модель спроектирована с учетом будущего расширения:
- Добавление новых метрик через расширение типа `Metric`
- Добавление новых таймфреймов через расширение типа `Timeframe`
- Добавление новых типов индикаторов для дивергенций
- Расширение настроек пользователя через JSON поля






