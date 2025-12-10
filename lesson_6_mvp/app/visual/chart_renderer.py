# app/visual/chart_renderer.py
"""
Настраиваемый рендерер графиков с поддержкой различных режимов, оверлеев и индикаторов.
"""

from __future__ import annotations
import io
import math
from typing import List, Tuple, Optional, Dict, Any
from datetime import datetime, timezone, timedelta

import numpy as np
# Ленивая загрузка matplotlib для ускорения старта приложения
# matplotlib будет загружен только при вызове render_chart

from ..domain.chart_settings import ChartSettings, PriceMode, LegendPosition, SeparatorType
from ..domain.services import ema, rsi, macd, atr
from ..domain.divergence_detector import detect_divergences, DivergenceSignal
from ..infrastructure.db import DB
from ..infrastructure.ohlcv_cache import get_ohlcv_cache
from typing import Union


def sma(values: List[float], period: int) -> List[Optional[float]]:
    """Вычислить Simple Moving Average."""
    if period <= 0 or not values:
        return []
    n = len(values)
    out: List[Optional[float]] = [None] * n
    if n < period:
        return out
    
    # Первое значение - простое среднее
    sma_val = sum(values[:period]) / period
    out[period - 1] = sma_val
    
    # Остальные значения - скользящее среднее
    for i in range(period, n):
        sma_val = sma_val - (values[i - period] / period) + (values[i] / period)
        out[i] = sma_val
    
    return out


def bollinger_bands(values: List[float], period: int, std_dev: float = 2.0) -> Tuple[List[Optional[float]], List[Optional[float]], List[Optional[float]]]:
    """Вычислить Bollinger Bands (middle, upper, lower)."""
    if period <= 0 or not values:
        return ([None] * len(values), [None] * len(values), [None] * len(values))
    
    n = len(values)
    middle = sma(values, period)
    upper: List[Optional[float]] = [None] * n
    lower: List[Optional[float]] = [None] * n
    
    for i in range(period - 1, n):
        if middle[i] is not None:
            # Вычисляем стандартное отклонение для периода
            period_values = values[i - period + 1:i + 1]
            mean = middle[i]
            variance = sum((v - mean) ** 2 for v in period_values) / period
            std = math.sqrt(variance)
            
            upper[i] = mean + (std_dev * std)
            lower[i] = mean - (std_dev * std)
    
    return middle, upper, lower


def heikin_ashi(opens: List[float], highs: List[float], lows: List[float], closes: List[float]) -> Tuple[List[float], List[float], List[float], List[float]]:
    """Вычислить Heikin-Ashi свечи."""
    n = len(closes)
    ha_open = [0.0] * n
    ha_high = [0.0] * n
    ha_low = [0.0] * n
    ha_close = [0.0] * n
    
    # Первая свеча
    ha_open[0] = (opens[0] + closes[0]) / 2.0
    ha_close[0] = (opens[0] + highs[0] + lows[0] + closes[0]) / 4.0
    ha_high[0] = max(highs[0], ha_open[0], ha_close[0])
    ha_low[0] = min(lows[0], ha_open[0], ha_close[0])
    
    # Остальные свечи
    for i in range(1, n):
        ha_close[i] = (opens[i] + highs[i] + lows[i] + closes[i]) / 4.0
        ha_open[i] = (ha_open[i - 1] + ha_close[i - 1]) / 2.0
        ha_high[i] = max(highs[i], ha_open[i], ha_close[i])
        ha_low[i] = min(lows[i], ha_open[i], ha_close[i])
    
    return ha_open, ha_high, ha_low, ha_close


def ichimoku_cloud(
    highs: List[float], 
    lows: List[float], 
    closes: List[float],
    tenkan_period: int = 9,
    kijun_period: int = 26,
    senkou_b_period: int = 52,
    chikou_period: int = 26
) -> Tuple[List[Optional[float]], List[Optional[float]], List[Optional[float]], List[Optional[float]], List[Optional[float]], List[Optional[float]], List[Optional[float]]]:
    """
    Вычислить Ichimoku Cloud компоненты.
    
    Returns:
        (tenkan_sen, kijun_sen, senkou_span_a, senkou_span_b, chikou_span, cloud_top, cloud_bottom)
        Все списки имеют длину n, где None означает отсутствие данных для этого индекса.
    """
    n = len(closes)
    tenkan_sen: List[Optional[float]] = [None] * n
    kijun_sen: List[Optional[float]] = [None] * n
    senkou_span_a: List[Optional[float]] = [None] * n
    senkou_span_b: List[Optional[float]] = [None] * n
    chikou_span: List[Optional[float]] = [None] * n
    
    # Tenkan-sen (Conversion Line): (Highest High + Lowest Low) / 2 за последние 9 периодов
    for i in range(tenkan_period - 1, n):
        period_highs = highs[i - tenkan_period + 1:i + 1]
        period_lows = lows[i - tenkan_period + 1:i + 1]
        if period_highs and period_lows:
            tenkan_sen[i] = (max(period_highs) + min(period_lows)) / 2.0
    
    # Kijun-sen (Base Line): (Highest High + Lowest Low) / 2 за последние 26 периодов
    for i in range(kijun_period - 1, n):
        period_highs = highs[i - kijun_period + 1:i + 1]
        period_lows = lows[i - kijun_period + 1:i + 1]
        if period_highs and period_lows:
            kijun_sen[i] = (max(period_highs) + min(period_lows)) / 2.0
    
    # Senkou Span A (Leading Span A): (Tenkan-sen + Kijun-sen) / 2, сдвинуто на 26 периодов вперед
    for i in range(n):
        if i >= kijun_period - 1 and tenkan_sen[i] is not None and kijun_sen[i] is not None:
            # Сдвигаем на kijun_period периодов вперед
            future_idx = i + kijun_period
            if future_idx < n:
                senkou_span_a[future_idx] = (tenkan_sen[i] + kijun_sen[i]) / 2.0
    
    # Senkou Span B (Leading Span B): (Highest High + Lowest Low) / 2 за последние 52 периода, сдвинуто на 26 периодов вперед
    for i in range(senkou_b_period - 1, n):
        period_highs = highs[i - senkou_b_period + 1:i + 1]
        period_lows = lows[i - senkou_b_period + 1:i + 1]
        if period_highs and period_lows:
            senkou_b_val = (max(period_highs) + min(period_lows)) / 2.0
            # Сдвигаем на kijun_period периодов вперед
            future_idx = i + kijun_period
            if future_idx < n:
                senkou_span_b[future_idx] = senkou_b_val
    
    # Chikou Span (Lagging Span): Close, сдвинуто на 26 периодов назад
    for i in range(n):
        past_idx = i - chikou_period
        if past_idx >= 0:
            chikou_span[i] = closes[past_idx]
    
    # Cloud Top и Cloud Bottom для заливки облака
    cloud_top: List[Optional[float]] = [None] * n
    cloud_bottom: List[Optional[float]] = [None] * n
    for i in range(n):
        if senkou_span_a[i] is not None and senkou_span_b[i] is not None:
            cloud_top[i] = max(senkou_span_a[i], senkou_span_b[i])
            cloud_bottom[i] = min(senkou_span_a[i], senkou_span_b[i])
        elif senkou_span_a[i] is not None:
            cloud_top[i] = senkou_span_a[i]
            cloud_bottom[i] = senkou_span_a[i]
        elif senkou_span_b[i] is not None:
            cloud_top[i] = senkou_span_b[i]
            cloud_bottom[i] = senkou_span_b[i]
    
    return tenkan_sen, kijun_sen, senkou_span_a, senkou_span_b, chikou_span, cloud_top, cloud_bottom


def get_ohlcv_data(db: DB, metric: Union[str, Metric], timeframe: Union[str, Timeframe], n_bars: int = 500, use_cache: bool = True) -> List[Tuple[int, float, float, float, float, Optional[float]]]:
    """Получить OHLCV данные с использованием кэша и fallback на TradingView/Binance."""
    import logging
    logger = logging.getLogger("alt_forecast.chart_renderer")
    
    cache = get_ohlcv_cache() if use_cache else None
    
    # Пытаемся получить из кэша
    if cache:
        cached_data = cache.get(metric, timeframe)
        if cached_data is not None:
            return cached_data[:n_bars] if len(cached_data) > n_bars else cached_data
    
    # Получаем из БД
    rows = db.last_n(metric, timeframe, n_bars)
    rows = sorted(rows, key=lambda r: r[0])
    
    # Дедупликация
    dedup: Dict[int, Tuple[int, float, float, float, float, Optional[float]]] = {}
    for ts, o, h, l, c, v in rows:
        if not (math.isfinite(o) and math.isfinite(h) and math.isfinite(l) and math.isfinite(c)):
            continue
        vv = float(v) if v is not None and math.isfinite(v) else None
        dedup[int(ts)] = (int(ts), float(o), float(h), float(l), float(c), vv)
    
    result = [dedup[k] for k in sorted(dedup.keys())]
    
    # Если данных нет в БД, пытаемся получить из TradingView/Binance (fallback)
    if not result:
        logger.info(f"No data in DB for {metric} {timeframe}, trying TradingView/Binance fallback")
        try:
            # Нормализуем символ для TradingView/Binance
            symbol = str(metric).upper().strip()
            
            # Известные метрики, которые не нужно обрабатывать через TradingView
            known_metrics = ["BTC", "ETHBTC", "USDT.D", "BTC.D", "TOTAL2", "TOTAL3"]
            
            # Если это не известная метрика, пытаемся получить через TradingView
            if symbol not in known_metrics:
                # Функция для нормализации символа для TradingView
                def normalize_symbol_for_tv(sym: str) -> List[str]:
                    """
                    Нормализует символ для TradingView и возвращает список возможных вариантов.
                    Пробуем разные варианты, так как символы на биржах могут отличаться.
                    """
                    sym = sym.upper().strip()
                    variants = []
                    
                    # Если уже есть формат EXCHANGE:SYMBOL, используем как есть
                    if ":" in sym:
                        variants.append(sym)
                        return variants
                    
                    # Специальные случаи для известных символов
                    special_cases = {
                        "FART": "FARTCOINUSDT",  # FART -> FARTCOINUSDT на Binance
                    }
                    
                    if sym in special_cases:
                        # Добавляем специальный вариант (без BINANCE:, так как _load_from_tv добавит его)
                        variants.append(special_cases[sym])
                        # Также попробуем стандартные варианты с очищенным символом
                        sym_original = sym
                        sym = special_cases[sym]  # Используем полный символ для дальнейшей обработки
                    
                    # Убираем возможные суффиксы и префиксы
                    sym_clean = sym.replace("USDT", "").replace("USD", "").replace("BTC", "").strip()
                    
                    # Вариант 1: Символ как есть + USDT (для Binance) - самый распространенный случай
                    if not sym.endswith("USDT") and not sym.endswith("USD") and not sym.endswith("BTC"):
                        variants.append(f"{sym}USDT")
                    
                    # Вариант 2: Если символ уже содержит USDT/USD/BTC, используем как есть
                    if "USDT" in sym or "USD" in sym or "BTC" in sym:
                        variants.append(sym)
                    
                    # Вариант 3: Очищенный символ + USDT (если была очистка)
                    if sym_clean and sym_clean != sym and not sym_clean.endswith("USDT"):
                        variants.append(f"{sym_clean}USDT")
                    
                    # Вариант 4: Символ как есть (на случай, если он уже в правильном формате)
                    variants.append(sym)
                    
                    # Убираем дубликаты, сохраняя порядок
                    seen = set()
                    unique_variants = []
                    for v in variants:
                        if v and v not in seen:
                            seen.add(v)
                            unique_variants.append(v)
                    
                    return unique_variants
                
                # Получаем список вариантов символов для попытки
                symbol_variants = normalize_symbol_for_tv(symbol)
                logger.info(f"Trying {len(symbol_variants)} symbol variants for {symbol}: {symbol_variants}")
                
                # Импортируем TradingView адаптер
                try:
                    from ..ml.data_adapter import _load_from_tv, _tv_interval
                    import pandas as pd
                    
                    # Пытаемся загрузить из TradingView для каждого варианта символа
                    df = None
                    successful_symbol = None
                    for tv_symbol in symbol_variants:
                        try:
                            # Извлекаем символ без биржи для _load_from_tv (она сама добавит BINANCE:)
                            sym_for_tv = tv_symbol.replace("BINANCE:", "") if "BINANCE:" in tv_symbol else tv_symbol
                            df = _load_from_tv(sym_for_tv, timeframe, n_bars)
                            if df is not None and not df.empty:
                                successful_symbol = tv_symbol
                                logger.info(f"Successfully loaded data from TradingView using symbol: {tv_symbol}")
                                break
                        except Exception as e:
                            logger.debug(f"Failed to load from TradingView with symbol {tv_symbol}: {e}")
                            continue
                    
                    if df is not None and not df.empty:
                        logger.info(f"Loaded {len(df)} bars from TradingView for {symbol} {timeframe} (used: {successful_symbol})")
                        # Конвертируем DataFrame в список кортежей
                        # _normalize_df возвращает DataFrame с ts в формате pandas Timestamp (datetime)
                        result = []
                        for idx, row in df.iterrows():
                            # ts после _normalize_df должен быть pandas Timestamp (datetime)
                            ts = row['ts']
                            try:
                                if isinstance(ts, pd.Timestamp):
                                    # pandas Timestamp в наносекундах, преобразуем в миллисекунды
                                    ts_ms = int(ts.value // 1_000_000)
                                elif hasattr(ts, 'timestamp'):
                                    # datetime объект
                                    ts_ms = int(ts.timestamp() * 1000)
                                elif isinstance(ts, (int, float)):
                                    # Если это число, проверяем масштаб (ms или s)
                                    ts_ms = int(ts) if ts > 1e12 else int(ts * 1000)
                                else:
                                    # Пытаемся преобразовать в pandas Timestamp
                                    ts_dt = pd.Timestamp(ts)
                                    ts_ms = int(ts_dt.value // 1_000_000)
                            except Exception as e:
                                logger.warning(f"Could not parse timestamp {ts}: {e}")
                                continue
                            
                            try:
                                o = float(row['open'])
                                h = float(row['high'])
                                l = float(row['low'])
                                c = float(row['close'])
                                v = float(row['volume']) if 'volume' in row and pd.notna(row.get('volume')) and math.isfinite(row.get('volume')) else None
                                
                                if math.isfinite(o) and math.isfinite(h) and math.isfinite(l) and math.isfinite(c):
                                    result.append((ts_ms, o, h, l, c, v))
                            except (ValueError, TypeError) as e:
                                logger.warning(f"Could not parse OHLCV values: {e}")
                                continue
                        
                        # Сортируем по времени
                        result = sorted(result, key=lambda r: r[0])
                        
                        # Сохраняем в БД для будущего использования
                        # Важно: сохраняем с оригинальным символом (metric), который ввел пользователь
                        if result:
                            try:
                                # Сохраняем батчем
                                batch = []
                                for ts_ms, o, h, l, c, v in result:
                                    batch.append((metric, timeframe, ts_ms, o, h, l, c, v))
                                if batch:
                                    with db.atomic():
                                        db.upsert_many_bars(batch)
                                    logger.info(f"Saved {len(batch)} bars to DB for {metric} {timeframe}")
                            except Exception as e:
                                logger.warning(f"Failed to save bars to DB: {e}")
                    else:
                        logger.warning(f"Could not load data from TradingView for {symbol} {timeframe} with any of the variants: {symbol_variants}")
                except ImportError:
                    logger.debug("TradingView data adapter not available")
                except Exception as e:
                    logger.warning(f"Failed to load from TradingView: {e}")
        except Exception as e:
            logger.warning(f"Fallback failed for {metric} {timeframe}: {e}")
    
    # Сохраняем в кэш
    if cache and result:
        cache.set(metric, timeframe, result)
    
    return result


def render_chart(
    db: DB,
    metric: Union[str, Metric],
    settings: ChartSettings,
    n_bars: int = 500,
) -> bytes:
    """
    Рендерить настраиваемый график.
    Использует кэширование и ленивую загрузку matplotlib для оптимизации производительности.
    
    Args:
        db: База данных
        metric: Метрика (BTC, ETH и т.д.)
        settings: Настройки графика
        n_bars: Количество баров для отображения
    
    Returns:
        PNG bytes
    """
    # Ленивая загрузка matplotlib
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates
    from mplfinance.original_flavor import candlestick_ohlc
    
    # Кэширование графиков и мониторинг производительности
    from ..infrastructure.cache import get_cache, set_cache
    from ..utils.performance import PerformanceMonitor
    
    with PerformanceMonitor("render_chart"):
        # Создаем ключ кэша на основе параметров
        cache_key = f"{metric}_{settings.timeframe}_{n_bars}_{hash(str(settings))}"
        cached_result = get_cache("render_chart", cache_key, ttl=60)
        if cached_result is not None:
            return cached_result
        
        # Логируем настройки для отладки
        import logging
        logger = logging.getLogger("alt_forecast.chart_renderer")
        logger.debug(f"render_chart: SMA={settings.sma_periods}, EMA={settings.ema_periods}, BB={settings.bb_period}, "
                    f"Ichimoku={settings.ichimoku_enabled}, Ribbon={settings.ribbon}, Separator={settings.separator}, "
                    f"Pivots={settings.pivots}, LastBadge={settings.last_badge}, LastInd={settings.last_ind}")
        
        # Получаем данные
        rows = get_ohlcv_data(db, metric, settings.timeframe, n_bars)
        
        if not rows:
            # Возвращаем пустой график
            fig, ax = plt.subplots(figsize=(12, 8), dpi=150, facecolor="white")
            ax.text(0.5, 0.5, f"No data for {metric}", ha="center", va="center", fontsize=14)
            ax.axis("off")
            buf = io.BytesIO()
            fig.savefig(buf, format="png", bbox_inches="tight")
            plt.close(fig)
            buf.seek(0)
            result = buf.read()
            
            # Сохраняем в кэш (даже для пустого графика)
            set_cache("render_chart", cache_key, result)
            return result
        
        # Подготавливаем данные
        timestamps = [r[0] for r in rows]
        opens = [r[1] for r in rows]
        highs = [r[2] for r in rows]
        lows = [r[3] for r in rows]
        closes = [r[4] for r in rows]
        volumes = [r[5] for r in rows]
        
        # Конвертируем timestamps в datetime
        dates = [datetime.fromtimestamp(ts / 1000.0, tz=timezone.utc) for ts in timestamps]
        date_nums = [mdates.date2num(dt) for dt in dates]
        
        # Инициализируем список дивергенций (будет заполнен позже)
        divergence_signals: List[DivergenceSignal] = []
        
        # Определяем количество панелей
        n_panels = 1  # Основная панель с ценой
    if settings.show_volume:
        n_panels += 1
    if settings.show_rsi:
        n_panels += 1
    if settings.show_macd:
        n_panels += 1
    if settings.show_atr:
        n_panels += 1
    
    # Создаем фигуру с панелями
    heights = [3.0] + [1.0] * (n_panels - 1)  # Основная панель больше
    fig, axes = plt.subplots(n_panels, 1, figsize=(14, sum(heights)), dpi=150, facecolor="white", 
                             gridspec_kw={"height_ratios": heights, "hspace": 0.1})
    
    if n_panels == 1:
        axes = [axes]
    
    ax_main = axes[0]
    ax_main.set_facecolor("white")
    
    # Инициализируем список для легенды
    legend_labels = []
    
    # Применяем режим отображения цены
    if settings.mode == PriceMode.LINE:
        # Линия с заливкой
        ax_main.plot(date_nums, closes, color="#1f77b4", linewidth=1.5, label="Close")
        # Заливка под линией до минимального значения или до нуля
        min_price = min(closes) if closes else 0
        ax_main.fill_between(date_nums, closes, min_price, alpha=0.3, color="#1f77b4")
        legend_labels.append("Close")
    elif settings.mode == PriceMode.CANDLE_HEIKIN:
        # Heikin-Ashi свечи
        ha_open, ha_high, ha_low, ha_close = heikin_ashi(opens, highs, lows, closes)
        # Конвертируем в формат для candlestick_ohlc
        ha_ohlc = [(date_nums[i], ha_open[i], ha_high[i], ha_low[i], ha_close[i]) 
                   for i in range(len(date_nums))]
        # Ширина свечи
        if len(date_nums) >= 3:
            steps = np.diff(date_nums)
            steps = steps[steps > 0]
            step = float(np.median(steps)) if steps.size else 0.0
            width = step * 0.6 if step > 0 else 0.4
        else:
            width = 0.4
        candlestick_ohlc(ax_main, ha_ohlc, width=width, colorup="green", colordown="red", alpha=0.9)
    else:  # CANDLE (по умолчанию)
        # Классические свечи
        ohlc = [(date_nums[i], opens[i], highs[i], lows[i], closes[i]) 
                for i in range(len(date_nums))]
        # Ширина свечи
        if len(date_nums) >= 3:
            steps = np.diff(date_nums)
            steps = steps[steps > 0]
            step = float(np.median(steps)) if steps.size else 0.0
            width = step * 0.6 if step > 0 else 0.4
        else:
            width = 0.4
        candlestick_ohlc(ax_main, ohlc, width=width, colorup="green", colordown="red", alpha=0.9)
    
    # Добавляем оверлеи (SMA, EMA, BB)
    
    # SMA (отображаем только если периоды заданы)
    if settings.sma_periods:
        for period in settings.sma_periods:
            sma_values = sma(closes, period)
            sma_plot = [v if v is not None else np.nan for v in sma_values]
            ax_main.plot(date_nums, sma_plot, label=f"SMA{period}", linewidth=1.5, alpha=0.8)
            legend_labels.append(f"SMA{period}")
    
    # EMA (отображаем только если периоды заданы)
    if settings.ema_periods:
        for period in settings.ema_periods:
            ema_values = ema(closes, period)
            ema_plot = [v if v is not None else np.nan for v in ema_values]
            ax_main.plot(date_nums, ema_plot, label=f"EMA{period}", linewidth=1.5, alpha=0.8, linestyle="--")
            legend_labels.append(f"EMA{period}")
    
    # Bollinger Bands
    if settings.bb_period is not None:
        bb_middle, bb_upper, bb_lower = bollinger_bands(closes, settings.bb_period, settings.bb_std)
        bb_middle_plot = [v if v is not None else np.nan for v in bb_middle]
        bb_upper_plot = [v if v is not None else np.nan for v in bb_upper]
        bb_lower_plot = [v if v is not None else np.nan for v in bb_lower]
        
        ax_main.plot(date_nums, bb_middle_plot, label=f"BB{settings.bb_period}", linewidth=1.0, alpha=0.6, color="gray")
        ax_main.plot(date_nums, bb_upper_plot, label=f"BB+{settings.bb_std}", linewidth=1.0, alpha=0.5, color="purple", linestyle=":")
        ax_main.plot(date_nums, bb_lower_plot, label=f"BB-{settings.bb_std}", linewidth=1.0, alpha=0.5, color="purple", linestyle=":")
        ax_main.fill_between(date_nums, bb_upper_plot, bb_lower_plot, alpha=0.1, color="purple")
        
        legend_labels.extend([f"BB{settings.bb_period}", f"BB+{settings.bb_std}", f"BB-{settings.bb_std}"])
    
    # Ichimoku Cloud
    if settings.ichimoku_enabled:
        tenkan, kijun, senkou_a, senkou_b, chikou, cloud_top, cloud_bottom = ichimoku_cloud(
            highs, lows, closes,
            settings.ichimoku_tenkan,
            settings.ichimoku_kijun,
            settings.ichimoku_senkou_b,
            settings.ichimoku_chikou
        )
        
        # Преобразуем в массивы с NaN для пропусков
        tenkan_plot = [v if v is not None else np.nan for v in tenkan]
        kijun_plot = [v if v is not None else np.nan for v in kijun]
        senkou_a_plot = [v if v is not None else np.nan for v in senkou_a]
        senkou_b_plot = [v if v is not None else np.nan for v in senkou_b]
        chikou_plot = [v if v is not None else np.nan for v in chikou]
        cloud_top_plot = [v if v is not None else np.nan for v in cloud_top]
        cloud_bottom_plot = [v if v is not None else np.nan for v in cloud_bottom]
        
        # Облако (Kumo) - заливка между Senkou Span A и B
        # Зеленая заливка когда Senkou A > Senkou B, красная когда наоборот
        where_bullish = np.array([a is not None and b is not None and a > b 
                                  for a, b in zip(senkou_a, senkou_b)])
        where_bearish = np.array([a is not None and b is not None and a <= b 
                                  for a, b in zip(senkou_a, senkou_b)])
        
        ax_main.fill_between(date_nums, cloud_top_plot, cloud_bottom_plot, 
                            where=where_bullish, alpha=0.2, color="green", label="Ichimoku Cloud (Bullish)")
        ax_main.fill_between(date_nums, cloud_top_plot, cloud_bottom_plot, 
                            where=where_bearish, alpha=0.2, color="red", label="Ichimoku Cloud (Bearish)")
        
        # Линии
        ax_main.plot(date_nums, tenkan_plot, color="blue", linewidth=1.0, alpha=0.7, label=f"Tenkan ({settings.ichimoku_tenkan})")
        ax_main.plot(date_nums, kijun_plot, color="red", linewidth=1.0, alpha=0.7, label=f"Kijun ({settings.ichimoku_kijun})")
        ax_main.plot(date_nums, senkou_a_plot, color="green", linewidth=1.0, alpha=0.6, linestyle="--", label="Senkou A")
        ax_main.plot(date_nums, senkou_b_plot, color="red", linewidth=1.0, alpha=0.6, linestyle="--", label="Senkou B")
        ax_main.plot(date_nums, chikou_plot, color="purple", linewidth=1.0, alpha=0.5, label="Chikou")
        
        legend_labels.extend([f"Tenkan", f"Kijun", "Senkou A", "Senkou B", "Chikou"])
    
    # Добавляем подложки и подсветки
    # Ribbon (лента тренда выше/ниже EMA200)
    if settings.ribbon:
        ema200_values = ema(closes, 200)
        if any(v is not None for v in ema200_values):
            ema200_plot = [v if v is not None else np.nan for v in ema200_values]
            # Заливка выше/ниже EMA200
            ax_main.fill_between(date_nums, closes, ema200_plot, where=np.array(closes) >= np.array([v if v is not None else 0 for v in ema200_plot]), 
                                alpha=0.2, color="green", label="Above EMA200")
            ax_main.fill_between(date_nums, closes, ema200_plot, where=np.array(closes) < np.array([v if v is not None else 0 for v in ema200_plot]), 
                                alpha=0.2, color="red", label="Below EMA200")
    
    # Separators (вертикальные разделители)
    if settings.separator:
        if settings.separator == SeparatorType.DAY:
            # Разделители по дням
            current_day = None
            for i, dt in enumerate(dates):
                day = dt.date()
                if current_day is None:
                    current_day = day
                elif day != current_day:
                    ax_main.axvline(date_nums[i], color="gray", linestyle=":", linewidth=0.5, alpha=0.3)
                    current_day = day
        elif settings.separator == SeparatorType.WEEK:
            # Разделители по неделям
            current_week = None
            for i, dt in enumerate(dates):
                week = dt.isocalendar()[1]  # Номер недели
                year = dt.year
                week_key = (year, week)
                if current_week is None:
                    current_week = week_key
                elif week_key != current_week:
                    ax_main.axvline(date_nums[i], color="gray", linestyle=":", linewidth=0.5, alpha=0.3)
                    current_week = week_key
    
    # Pivots (маркеры локальных high/low) - светло-зеленые и светло-красные
    if settings.pivots:
        # Простой алгоритм поиска пивотов (локальные максимумы и минимумы)
        pivot_window = 5
        for i in range(pivot_window, len(closes) - pivot_window):
            # Локальный максимум - светло-красный
            if all(closes[i] >= closes[i - j] for j in range(1, pivot_window + 1)) and \
               all(closes[i] >= closes[i + j] for j in range(1, pivot_window + 1)):
                ax_main.plot(date_nums[i], highs[i], marker="v", color="#ff9999", markersize=6, alpha=0.5)
            # Локальный минимум - светло-зеленый
            if all(closes[i] <= closes[i - j] for j in range(1, pivot_window + 1)) and \
               all(closes[i] <= closes[i + j] for j in range(1, pivot_window + 1)):
                ax_main.plot(date_nums[i], lows[i], marker="^", color="#99ff99", markersize=6, alpha=0.5)
    
    # Lastline (пунктир на последней цене)
    if settings.lastline and closes:
        last_price = closes[-1]
        ax_main.axhline(last_price, color="blue", linestyle="--", linewidth=1.5, alpha=0.7, label=f"Last: {last_price:.2f}")
        legend_labels.append(f"Last: {last_price:.2f}")
    
    # Поиск дивергенций (если включено)
    if settings.show_divergences:
        try:
            import logging
            logger = logging.getLogger("alt_forecast.chart_renderer")
            
            from ..domain.models import Metric, Timeframe
            # Преобразуем metric в Metric тип
            metric_str = str(metric).upper()
            if metric_str in ["BTC", "ETH", "USDT.D", "BTC.D", "TOTAL2", "TOTAL3", "ETHBTC"]:
                metric_enum: Metric = metric_str  # type: ignore
            else:
                metric_enum = "BTC"  # type: ignore
            
            # Преобразуем timeframe в Timeframe тип
            tf_str = settings.timeframe.lower()
            if tf_str in ["15m", "1h", "4h", "1d"]:
                tf_enum: Timeframe = tf_str  # type: ignore
            else:
                tf_enum = "1h"  # type: ignore
            
            # Получаем настройки индикаторов для дивергенций
            div_indicators = settings.divergence_indicators
            # Проверяем, что это словарь и не пустой
            if not div_indicators or not isinstance(div_indicators, dict) or len(div_indicators) == 0:
                # Если настройки не заданы, используем значения по умолчанию
                div_indicators = {
                    "RSI": True,
                    "MACD": True,
                    "STOCH": False,
                    "CCI": False,
                    "MFI": False,
                    "OBV": False,
                    "VOLUME": False,
                }
                # Сохраняем в настройках для следующего использования
                settings.divergence_indicators = div_indicators
            
            logger.info(f"Detecting divergences for {metric_enum} {tf_enum}, show_divergences={settings.show_divergences}, enabled indicators: {div_indicators}, data length: {len(closes)}")
            
            divergence_signals = detect_divergences(
                metric_enum,
                tf_enum,
                closes,
                highs,
                lows,
                volumes,
                enabled_indicators=div_indicators
            )
            
            logger.info(f"Found {len(divergence_signals)} divergences")
            
            # Получаем границы оси Y для размещения меток (нужно до отрисовки дивергенций)
            y_min_ax, y_max_ax = ax_main.get_ylim()
            
            # Отображаем дивергенции на основном графике
            for div in divergence_signals:
                # Проверяем, что индексы в допустимых пределах
                if div.price_idx_left >= len(date_nums) or div.price_idx_right >= len(date_nums):
                    logger.warning(f"Divergence index out of range: left={div.price_idx_left}, right={div.price_idx_right}, data_len={len(date_nums)}")
                    continue
                
                # Рисуем линию между пивотами цены (линия дивергенции)
                x_left = date_nums[div.price_idx_left]
                x_right = date_nums[div.price_idx_right]
                y_left = div.price_val_left
                y_right = div.price_val_right
                
                # Цвет линии: яркий зеленый для bullish, яркий красный для bearish
                color = "#00ff00" if div.side == "bullish" else "#ff0000"  # Яркие цвета для дивергенций
                linestyle = "--" if div.strength == "(слабая)" else "-"
                linewidth = 1.5 if div.strength == "(слабая)" else 2.0
                
                # Линия дивергенции на основном графике (соединяет пивоты цены)
                ax_main.plot([x_left, x_right], [y_left, y_right], 
                           color=color, linestyle=linestyle, linewidth=linewidth, alpha=0.8, zorder=5,
                           label=f"{div.indicator} {'Bull' if div.side == 'bullish' else 'Bear'}")
                
                # Стрелка на правом пивоте - яркая
                marker = "^" if div.side == "bullish" else "v"
                ax_main.plot(x_right, y_right, marker=marker, color=color, 
                           markersize=12, markeredgewidth=2, alpha=0.95, zorder=6,
                           markeredgecolor="white")
        except Exception as e:
            import logging
            logger = logging.getLogger("alt_forecast.chart_renderer")
            logger.exception("Error detecting divergences: %s", e)
    
    # Last badge (бейдж с текущей ценой и % изменения в правом верхнем углу)
    # Должен быть ДО настройки осей, чтобы не перекрываться
    if settings.last_badge and closes and len(closes) >= 2:
        last_price = closes[-1]
        prev_price = closes[-2] if len(closes) >= 2 else closes[-1]
        change_pct = ((last_price - prev_price) / prev_price * 100) if prev_price != 0 else 0.0
        change_color = "green" if change_pct >= 0 else "red"
        change_sign = "+" if change_pct >= 0 else ""
        
        badge_text = f"{last_price:.2f}\n{change_sign}{change_pct:.2f}%"
        ax_main.text(0.98, 0.98, badge_text,
                    transform=ax_main.transAxes,
                    fontsize=11,
                    fontweight='bold',
                    horizontalalignment='right',
                    verticalalignment='top',
                    color=change_color,
                    bbox=dict(boxstyle='round,pad=0.5', facecolor='white', edgecolor=change_color, linewidth=2, alpha=0.9))
    
    # Отображение текущего значения справа (последняя цена закрытия) - если last_ind включено
    if settings.last_ind and closes:
        last_price = closes[-1]
        # Размещаем текст справа от графика
        ax_main.text(1.02, 0.5, f"{last_price:.2f}", 
                    transform=ax_main.transAxes, 
                    fontsize=10, 
                    fontweight='bold',
                    verticalalignment='center',
                    bbox=dict(boxstyle='round,pad=0.3', facecolor='white', edgecolor='gray', alpha=0.8))
    
    # Легенда
    if settings.legend != LegendPosition.OFF:
        if settings.legend == LegendPosition.TOP:
            ax_main.legend(loc="upper left", fontsize=8, framealpha=0.9)
        else:  # BOTTOM
            ax_main.legend(loc="lower left", fontsize=8, framealpha=0.9)
    
    # Нижние панели
    panel_idx = 1
    
    # Volume
    if settings.show_volume:
        ax_vol = axes[panel_idx]
        ax_vol.set_facecolor("white")
        volumes_plot = [v if v is not None and v > 0 else 0 for v in volumes]
        colors_vol = ["green" if closes[i] >= opens[i] else "red" for i in range(len(closes))]
        ax_vol.bar(date_nums, volumes_plot, width=width*0.8, color=colors_vol, alpha=0.6)
        ax_vol.set_ylabel("Volume", fontsize=9)
        ax_vol.grid(True, alpha=0.3)
        ax_vol.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m-%d\n%H:%M"))
        # Отображение текущего значения справа (если last_ind включено)
        if settings.last_ind and volumes_plot:
            last_vol = volumes_plot[-1]
            ax_vol.text(1.02, 0.5, f"{last_vol:.2f}", 
                       transform=ax_vol.transAxes, 
                       fontsize=9, 
                       fontweight='bold',
                       verticalalignment='center',
                       bbox=dict(boxstyle='round,pad=0.3', facecolor='white', edgecolor='gray', alpha=0.8))
        panel_idx += 1
    
    # RSI
    if settings.show_rsi:
        ax_rsi = axes[panel_idx]
        ax_rsi.set_facecolor("white")
        rsi_values = rsi(closes, settings.rsi_period)
        rsi_plot = [v if v is not None else np.nan for v in rsi_values]
        ax_rsi.plot(date_nums, rsi_plot, color="purple", linewidth=1.5, label=f"RSI{settings.rsi_period}")
        ax_rsi.axhline(70, color="red", linestyle="--", linewidth=1, alpha=0.5, label="Overbought")
        ax_rsi.axhline(50, color="gray", linestyle="--", linewidth=1, alpha=0.3, label="Neutral")
        ax_rsi.axhline(30, color="green", linestyle="--", linewidth=1, alpha=0.5, label="Oversold")
        ax_rsi.set_ylabel(f"RSI{settings.rsi_period}", fontsize=9)
        ax_rsi.set_ylim(0, 100)
        ax_rsi.grid(True, alpha=0.3)
        ax_rsi.legend(loc="upper left", fontsize=7)
        ax_rsi.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m-%d\n%H:%M"))
        
        # Отображение дивергенций на панели RSI
        if settings.show_divergences:
            for div in divergence_signals:
                if div.indicator == "RSI":
                    x_left = date_nums[div.price_idx_left]
                    x_right = date_nums[div.price_idx_right]
                    y_left = div.indicator_val_left
                    y_right = div.indicator_val_right
                    # Яркие цвета для дивергенций
                    color = "#00ff00" if div.side == "bullish" else "#ff0000"
                    linestyle = "--" if div.strength == "(слабая)" else "-"
                    linewidth = 1.5 if div.strength == "(слабая)" else 2.0
                    ax_rsi.plot([x_left, x_right], [y_left, y_right], 
                               color=color, linestyle=linestyle, linewidth=linewidth, alpha=0.8, zorder=5)
                    marker = "^" if div.side == "bullish" else "v"
                    ax_rsi.plot(x_right, y_right, marker=marker, color=color, 
                               markersize=8, markeredgewidth=2, alpha=0.9, zorder=6,
                               markeredgecolor="white")
        
        # Отображение текущего значения справа (если last_ind включено)
        if settings.last_ind and rsi_plot and not np.isnan(rsi_plot[-1]):
            last_rsi = rsi_plot[-1]
            ax_rsi.text(1.02, 0.5, f"{last_rsi:.2f}", 
                       transform=ax_rsi.transAxes, 
                       fontsize=9, 
                       fontweight='bold',
                       verticalalignment='center',
                       bbox=dict(boxstyle='round,pad=0.3', facecolor='white', edgecolor='gray', alpha=0.8))
        panel_idx += 1
    
    # MACD
    if settings.show_macd:
        ax_macd = axes[panel_idx]
        ax_macd.set_facecolor("white")
        macd_line, macd_signal, macd_hist = macd(closes, settings.macd_fast, settings.macd_slow, settings.macd_signal)
        macd_line_plot = [v if v is not None else np.nan for v in macd_line]
        macd_signal_plot = [v if v is not None else np.nan for v in macd_signal]
        macd_hist_plot = [v if v is not None else np.nan for v in macd_hist]
        
        ax_macd.plot(date_nums, macd_line_plot, color="blue", linewidth=1.5, label="MACD")
        ax_macd.plot(date_nums, macd_signal_plot, color="orange", linewidth=1.5, label="Signal")
        ax_macd.bar(date_nums, macd_hist_plot, width=width*0.8, color=["green" if v > 0 else "red" for v in macd_hist_plot], 
                   alpha=0.6, label="Histogram")
        ax_macd.axhline(0, color="black", linestyle="--", linewidth=0.5, alpha=0.3)
        ax_macd.set_ylabel("MACD", fontsize=9)
        ax_macd.grid(True, alpha=0.3)
        ax_macd.legend(loc="upper left", fontsize=7)
        ax_macd.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m-%d\n%H:%M"))
        
        # Отображение дивергенций на панели MACD
        if settings.show_divergences:
            for div in divergence_signals:
                if div.indicator == "MACD":
                    x_left = date_nums[div.price_idx_left]
                    x_right = date_nums[div.price_idx_right]
                    y_left = div.indicator_val_left
                    y_right = div.indicator_val_right
                    # Яркие цвета для дивергенций
                    color = "#00ff00" if div.side == "bullish" else "#ff0000"
                    linestyle = "--" if div.strength == "(слабая)" else "-"
                    linewidth = 1.5 if div.strength == "(слабая)" else 2.0
                    ax_macd.plot([x_left, x_right], [y_left, y_right], 
                               color=color, linestyle=linestyle, linewidth=linewidth, alpha=0.8, zorder=5)
                    marker = "^" if div.side == "bullish" else "v"
                    ax_macd.plot(x_right, y_right, marker=marker, color=color, 
                               markersize=8, markeredgewidth=2, alpha=0.9, zorder=6,
                               markeredgecolor="white")
        
        # Отображение текущего значения справа (MACD линия) - если last_ind включено
        if settings.last_ind and macd_line_plot and not np.isnan(macd_line_plot[-1]):
            last_macd = macd_line_plot[-1]
            ax_macd.text(1.02, 0.5, f"{last_macd:.4f}", 
                        transform=ax_macd.transAxes, 
                        fontsize=9, 
                        fontweight='bold',
                        verticalalignment='center',
                        bbox=dict(boxstyle='round,pad=0.3', facecolor='white', edgecolor='gray', alpha=0.8))
        panel_idx += 1
    
    # ATR
    if settings.show_atr:
        ax_atr = axes[panel_idx]
        ax_atr.set_facecolor("white")
        atr_values = atr(highs, lows, closes, settings.atr_period)
        atr_plot = [v if v is not None else np.nan for v in atr_values]
        ax_atr.plot(date_nums, atr_plot, color="brown", linewidth=1.5, label=f"ATR{settings.atr_period}")
        ax_atr.set_ylabel(f"ATR{settings.atr_period}", fontsize=9)
        ax_atr.grid(True, alpha=0.3)
        ax_atr.legend(loc="upper left", fontsize=7)
        ax_atr.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m-%d\n%H:%M"))
        # Отображение текущего значения справа (если last_ind включено)
        if settings.last_ind and atr_plot and not np.isnan(atr_plot[-1]):
            last_atr = atr_plot[-1]
            ax_atr.text(1.02, 0.5, f"{last_atr:.4f}", 
                       transform=ax_atr.transAxes, 
                       fontsize=9, 
                       fontweight='bold',
                       verticalalignment='center',
                       bbox=dict(boxstyle='round,pad=0.3', facecolor='white', edgecolor='gray', alpha=0.8))
        panel_idx += 1
    
        # Заголовок
        title = f"{metric} • {settings.timeframe}"
        if settings.currency:
            title += f" • {settings.currency.upper()}"
        fig.suptitle(title, fontsize=12, fontweight="bold")
        
        # Сохраняем
        buf = io.BytesIO()
        fig.tight_layout()
        fig.savefig(buf, format="png", bbox_inches="tight", dpi=150)
        plt.close(fig)
        buf.seek(0)
        result = buf.read()
        
        # Сохраняем в кэш
        set_cache("render_chart", cache_key, result)
        return result

