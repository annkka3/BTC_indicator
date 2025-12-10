# app/infrastructure/free_market_data.py
"""
Бесплатные источники данных для функций китов и ликвидаций.
Использует публичные API бирж без необходимости платной подписки.
"""
from __future__ import annotations

import time
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from dataclasses import dataclass
from typing import List, Dict, Optional, Tuple
import logging
from functools import lru_cache
from threading import Lock

log = logging.getLogger("alt_forecast.free_market_data")

BINANCE_FUT = "https://fapi.binance.com"
BINANCE_SPOT = "https://api.binance.com"
BYBIT = "https://api.bybit.com"
OKX = "https://www.okx.com"
BITGET = "https://api.bitget.com"
GATEIO = "https://api.gateio.ws"

# Общий Session с retry логикой
_sess = requests.Session()
_sess.mount("https://", HTTPAdapter(max_retries=Retry(
    total=2,
    backoff_factor=0.3,
    status_forcelist=(429, 500, 502, 503, 504),
    allowed_methods=frozenset(["GET"])
)))

# Простой кеш с TTL (в секундах)
_cache: Dict[str, Tuple[float, any]] = {}
_cache_lock = Lock()
CACHE_TTL = 60  # 60 секунд кеш


@dataclass(frozen=True, slots=True)
class LiquidationLevel:
    """Уровень ликвидации."""
    price: float
    usd_value: float
    side: str  # "long" | "short"
    exchange: str = "unknown"  # биржа источника данных


@dataclass(frozen=True, slots=True)
class WhaleOrder:
    """Ордер кита."""
    price: float
    amount: float  # USD значение
    side: str  # "buy" | "sell"
    age: str  # примерное время
    exchange: str = "unknown"  # биржа источника данных


@dataclass(frozen=True, slots=True)
class LargeTrade:
    """Крупная сделка."""
    price: float
    quantity: float
    side: str  # "buy" | "sell"
    timestamp: int
    usd_value: float
    exchange: str = "unknown"  # биржа источника данных


def _get_cached(key: str, ttl: float = CACHE_TTL):
    """Получить значение из кеша если оно еще актуально."""
    with _cache_lock:
        if key in _cache:
            cached_time, value = _cache[key]
            if time.time() - cached_time < ttl:
                return value
            del _cache[key]
    return None


def _set_cached(key: str, value: any):
    """Сохранить значение в кеш."""
    with _cache_lock:
        _cache[key] = (time.time(), value)


def get_liquidation_levels_from_bybit(symbol: str, hours: int = 48) -> List[LiquidationLevel]:
    """
    Получить уровни ликвидации из исторических данных Bybit.
    Группирует ликвидации по ценовым уровням для создания карты.
    Использует несколько запросов для получения большего количества данных.
    """
    symbol_usdt = f"{symbol}USDT" if not symbol.endswith("USDT") else symbol
    
    try:
        end_ms = int(time.time() * 1000) - 2000
        all_liqs = []
        
        # Делаем несколько запросов с разными временными окнами для получения больше данных
        window_hours = 6  # Каждое окно 6 часов
        num_windows = max(1, hours // window_hours)
        
        for i in range(num_windows):
            window_end = end_ms - (i * window_hours * 3600 * 1000)
            window_start = window_end - (window_hours * 3600 * 1000)
            
            try:
                url = f"{BYBIT}/v5/market/liquidation"
                params = {
                    "category": "linear",
                    "symbol": symbol_usdt,
                    "startTime": int(window_start),
                    "endTime": int(window_end),
                    "limit": 200
                }
                
                r = _sess.get(url, params=params, timeout=15)
                if r.status_code == 404:
                    continue
                r.raise_for_status()
                data = r.json()
                
                liqs = data.get("result", {}).get("list", [])
                if liqs:
                    all_liqs.extend(liqs)
                    
            except Exception as e:
                log.debug("Failed to get liquidations for window %d: %s", i, e)
                continue
        
        # Если данных все еще мало, пробуем inverse контракт
        if len(all_liqs) < 10:
            symbol_usd = symbol_usdt.replace("USDT", "USD")
            try:
                url = f"{BYBIT}/v5/market/liquidation"
                params = {
                    "category": "inverse",
                    "symbol": symbol_usd,
                    "startTime": end_ms - (hours * 3600 * 1000),
                    "endTime": end_ms,
                    "limit": 200
                }
                r = _sess.get(url, params=params, timeout=15)
                if r.status_code != 404:
                    r.raise_for_status()
                    data = r.json()
                    liqs = data.get("result", {}).get("list", [])
                    if liqs:
                        all_liqs.extend(liqs)
            except Exception:
                pass
        
        if not all_liqs:
            return []
        
        # Группируем ликвидации по ценовым уровням
        price_groups: Dict[Tuple[str, float], float] = {}
        
        for liq in all_liqs:
            side = str(liq.get("side", "")).lower()
            if side not in ("buy", "sell", "long", "short"):
                continue
            
            price = float(liq.get("price", 0))
            value = float(liq.get("value", 0) or liq.get("qty", 0))
            
            if price <= 0 or value <= 0:
                continue
            
            # Нормализуем side
            side_normalized = "long" if side in ("buy", "long") else "short"
            
            # Округляем цену для группировки (более агрессивное округление для лучшей группировки)
            # Для BTC округляем до $100, для ETH до $10
            if symbol.upper() == "BTC":
                price_rounded = round(price / 100) * 100
            elif symbol.upper() == "ETH":
                price_rounded = round(price / 10) * 10
            else:
                price_rounded = round(price * 100) / 100  # Округление до 0.01
            
            key = (side_normalized, price_rounded)
            price_groups[key] = price_groups.get(key, 0) + value
        
        # Создаем список уровней
        levels = []
        for (side, price), total_value in price_groups.items():
            # Снижаем минимальный порог для отображения
            if total_value >= 500:  # Минимум $500 для отображения
                levels.append(LiquidationLevel(
                    price=price,
                    usd_value=total_value,
                    side=side,
                    exchange="bybit"
                ))
        
        result = sorted(levels, key=lambda x: x.price, reverse=True)
        _set_cached(cache_key, result)
        return result
        
    except Exception as e:
        log.warning("Failed to get liquidation levels from Bybit for %s: %s", symbol, e)
        return []


def get_whale_orders_from_binance(symbol: str, min_amount_usd: Optional[float] = None, current_price: Optional[float] = None) -> List[WhaleOrder]:
    """
    Получить крупные ордера из orderbook Binance.
    Анализирует стакан заявок и находит крупные ордера.
    """
    symbol_usdt = f"{symbol}USDT" if not symbol.endswith("USDT") else symbol
    
    # Проверяем кеш
    cache_key = f"whale_orders_{symbol_usdt}"
    cached = _get_cached(cache_key, ttl=60)  # 1 минута кеш для ордеров
    if cached is not None:
        return cached
    
    try:
        # Получаем orderbook с глубиной 500
        url = f"{BINANCE_FUT}/fapi/v1/depth"
        params = {"symbol": symbol_usdt, "limit": 500}
        
        r = _sess.get(url, params=params, timeout=10)
        r.raise_for_status()
        data = r.json()
        
        # Получаем текущую цену для расчета USD значения
        if current_price is None:
            ticker_url = f"{BINANCE_FUT}/fapi/v1/ticker/price"
            ticker_r = _sess.get(ticker_url, params={"symbol": symbol_usdt}, timeout=10)
            ticker_r.raise_for_status()
            current_price = float(ticker_r.json()["price"])
        
        # Умный порог если не указан
        if min_amount_usd is None:
            bids = data.get("bids", [])
            asks = data.get("asks", [])
            total_notional = sum(float(p) * float(q) for p, q in bids + asks)
            min_amount_usd = max(2_000_000.0, total_notional * 0.0005)  # 0.05% от общего объема стакана
        
        orders = []
        
        # Обрабатываем bids (buy orders)
        bids = data.get("bids", [])
        for bid in bids:
            price = float(bid[0])
            quantity = float(bid[1])
            amount_usd = price * quantity
            
            # Фильтр по размеру
            if amount_usd < min_amount_usd:
                continue
            
            # Фильтр по расстоянию от текущей цены (не дальше 10%)
            if abs(price - current_price) / current_price > 0.1:
                continue
            
            orders.append(WhaleOrder(
                price=price,
                amount=amount_usd,
                side="buy",
                age="Live"
            ))
        
        # Обрабатываем asks (sell orders)
        asks = data.get("asks", [])
        for ask in asks:
            price = float(ask[0])
            quantity = float(ask[1])
            amount_usd = price * quantity
            
            # Фильтр по размеру
            if amount_usd < min_amount_usd:
                continue
            
            # Фильтр по расстоянию от текущей цены (не дальше 10%)
            if abs(price - current_price) / current_price > 0.1:
                continue
            
            orders.append(WhaleOrder(
                price=price,
                amount=amount_usd,
                side="sell",
                age="Live",
                exchange="binance"
            ))
        
        result = sorted(orders, key=lambda x: x.amount, reverse=True)
        _set_cached(cache_key, result)
        return result
        
    except Exception as e:
        log.warning("Failed to get whale orders from Binance for %s: %s", symbol, e)
        return []


def get_whale_orders_from_bybit(symbol: str, min_amount_usd: Optional[float] = None, current_price: Optional[float] = None) -> List[WhaleOrder]:
    """
    Получить крупные ордера из Bybit orderbook.
    """
    symbol_usdt = f"{symbol}USDT"
    
    cache_key = f"whale_orders_bybit_{symbol_usdt}"
    cached = _get_cached(cache_key, ttl=60)
    if cached is not None:
        return cached
    
    try:
        url = f"{BYBIT}/v5/market/orderbook"
        params = {
            "category": "linear",
            "symbol": symbol_usdt,
            "limit": "200"  # максимальная глубина для Bybit
        }
        
        r = _sess.get(url, params=params, timeout=10)
        r.raise_for_status()
        data = r.json()
        
        if data.get("retCode") != 0:
            return []
        
        result_data = data.get("result", {})
        if not result_data:
            return []
        
        # Получаем текущую цену если не указана
        if current_price is None:
            ticker_url = f"{BYBIT}/v5/market/tickers"
            ticker_params = {"category": "linear", "symbol": symbol_usdt}
            ticker_r = _sess.get(ticker_url, params=ticker_params, timeout=10)
            ticker_r.raise_for_status()
            ticker_data = ticker_r.json()
            if ticker_data.get("retCode") == 0 and ticker_data.get("result", {}).get("list"):
                current_price = float(ticker_data["result"]["list"][0].get("lastPrice", 0))
            else:
                return []
        
        bids = result_data.get("b", [])  # bids в формате [["price", "size"], ...]
        asks = result_data.get("a", [])  # asks в формате [["price", "size"], ...]
        
        # Умный порог
        if min_amount_usd is None:
            try:
                total_notional = sum(float(p) * float(q) for p, q in bids + asks)
                min_amount_usd = max(2_000_000.0, total_notional * 0.0005)
            except Exception:
                min_amount_usd = 2_000_000.0
        
        orders = []
        
        # Bids (buy)
        for bid in bids:
            if not isinstance(bid, (list, tuple)) or len(bid) < 2:
                continue
            price = float(bid[0])
            quantity = float(bid[1])
            amount_usd = price * quantity
            
            if amount_usd < min_amount_usd:
                continue
            if abs(price - current_price) / current_price > 0.1:
                continue
            
            orders.append(WhaleOrder(
                price=price,
                amount=amount_usd,
                side="buy",
                age="Live",
                exchange="bybit"
            ))
        
        # Asks (sell)
        for ask in asks:
            if not isinstance(ask, (list, tuple)) or len(ask) < 2:
                continue
            price = float(ask[0])
            quantity = float(ask[1])
            amount_usd = price * quantity
            
            if amount_usd < min_amount_usd:
                continue
            if abs(price - current_price) / current_price > 0.1:
                continue
            
            orders.append(WhaleOrder(
                price=price,
                amount=amount_usd,
                side="sell",
                age="Live",
                exchange="bybit"
            ))
        
        result = sorted(orders, key=lambda x: x.amount, reverse=True)
        _set_cached(cache_key, result)
        return result
        
    except Exception as e:
        log.warning("Failed to get whale orders from Bybit for %s: %s", symbol, e)
        return []


def get_whale_orders_from_coinbase(symbol: str, min_amount_usd: Optional[float] = None, current_price: Optional[float] = None) -> List[WhaleOrder]:
    """
    Получить крупные ордера из Coinbase Pro/Advanced Trade orderbook.
    Note: Coinbase использует другой формат символов (BTC-USD вместо BTCUSDT).
    """
    # Coinbase использует формат BTC-USD для спотовых пар
    symbol_coinbase = f"{symbol}-USD"
    
    cache_key = f"whale_orders_coinbase_{symbol_coinbase}"
    cached = _get_cached(cache_key, ttl=60)
    if cached is not None:
        return cached
    
    try:
        # Coinbase Pro/Advanced Trade API endpoint для orderbook
        url = f"https://api.exchange.coinbase.com/products/{symbol_coinbase}/book"
        params = {"level": "2"}  # level 2 дает лучший баланс между данными и скоростью
        
        r = _sess.get(url, params=params, timeout=10)
        r.raise_for_status()
        data = r.json()
        
        # Получаем текущую цену если не указана
        if current_price is None:
            ticker_url = f"https://api.exchange.coinbase.com/products/{symbol_coinbase}/ticker"
            ticker_r = _sess.get(ticker_url, timeout=10)
            ticker_r.raise_for_status()
            ticker_data = ticker_r.json()
            current_price = float(ticker_data.get("price", 0))
            if current_price == 0:
                return []
        
        bids = data.get("bids", [])
        asks = data.get("asks", [])
        
        # Умный порог
        if min_amount_usd is None:
            try:
                total_notional = sum(float(p) * float(q) for p, q in bids + asks)
                min_amount_usd = max(2_000_000.0, total_notional * 0.0005)
            except Exception:
                min_amount_usd = 2_000_000.0
        
        orders = []
        
        # Bids (buy) - формат Coinbase: [price, size]
        for bid in bids:
            if not isinstance(bid, (list, tuple)) or len(bid) < 2:
                continue
            price = float(bid[0])
            quantity = float(bid[1])
            amount_usd = price * quantity
            
            if amount_usd < min_amount_usd:
                continue
            if abs(price - current_price) / current_price > 0.1:
                continue
            
            orders.append(WhaleOrder(
                price=price,
                amount=amount_usd,
                side="buy",
                age="Live",
                exchange="coinbase"
            ))
        
        # Asks (sell)
        for ask in asks:
            if not isinstance(ask, (list, tuple)) or len(ask) < 2:
                continue
            price = float(ask[0])
            quantity = float(ask[1])
            amount_usd = price * quantity
            
            if amount_usd < min_amount_usd:
                continue
            if abs(price - current_price) / current_price > 0.1:
                continue
            
            orders.append(WhaleOrder(
                price=price,
                amount=amount_usd,
                side="sell",
                age="Live",
                exchange="coinbase"
            ))
        
        result = sorted(orders, key=lambda x: x.amount, reverse=True)
        _set_cached(cache_key, result)
        return result
        
    except Exception as e:
        log.warning("Failed to get whale orders from Coinbase for %s: %s", symbol, e)
        return []


def get_large_trades_from_binance(symbol: str, limit: int = 500, min_usd: float = 100_000.0, since_ms: Optional[int] = None) -> List[LargeTrade]:
    """
    Получить крупные сделки из Binance aggTrades.
    """
    symbol_usdt = f"{symbol}USDT" if not symbol.endswith("USDT") else symbol
    
    # Проверяем кеш (только если since_ms не указан, иначе данные зависят от времени)
    if since_ms is None:
        cache_key = f"large_trades_{symbol_usdt}_{limit}"
        cached = _get_cached(cache_key, ttl=60)  # 1 минута кеш
        if cached is not None:
            return cached
    
    try:
        url = f"{BINANCE_FUT}/fapi/v1/aggTrades"
        params = {"symbol": symbol_usdt, "limit": limit}
        
        # Добавляем startTime если указан
        if since_ms is not None:
            params["startTime"] = since_ms
        
        r = _sess.get(url, params=params, timeout=10)
        r.raise_for_status()
        trades = r.json()
        
        large_trades = []
        for trade in trades:
            price = float(trade["p"])
            quantity = float(trade["q"])
            usd_value = price * quantity
            
            if usd_value >= min_usd:
                # Определяем сторону по isBuyerMaker
                side = "sell" if trade.get("m", False) else "buy"
                
                large_trades.append(LargeTrade(
                    price=price,
                    quantity=quantity,
                    side=side,
                    timestamp=int(trade["T"]),
                    usd_value=usd_value,
                    exchange="binance"
                ))
        
        result = sorted(large_trades, key=lambda x: x.usd_value, reverse=True)
        
        # Сохраняем в кеш только если since_ms не указан
        if since_ms is None:
            cache_key = f"large_trades_{symbol_usdt}_{limit}"
            _set_cached(cache_key, result)
        
        return result
        
    except Exception as e:
        log.warning("Failed to get large trades from Binance for %s: %s", symbol, e)
        return []


def estimate_liquidation_levels_from_positions(
    symbol: str,
    current_price: float,
    leverage_range: Tuple[float, float] = (10.0, 50.0)
) -> List[LiquidationLevel]:
    """
    Оценить потенциальные уровни ликвидации на основе анализа orderbook и позиций.
    Это упрощенная оценка, основанная на предположениях о среднем плече.
    """
    try:
        # Получаем orderbook для анализа концентрации позиций
        symbol_usdt = f"{symbol}USDT" if not symbol.endswith("USDT") else symbol
        url = f"{BINANCE_FUT}/fapi/v1/depth"
        params = {"symbol": symbol_usdt, "limit": 100}
        
        r = _sess.get(url, params=params, timeout=10)
        r.raise_for_status()
        data = r.json()
        
        levels = []
        
        # Анализируем bids (длинные позиции) - ликвидация ниже текущей цены
        bids = data.get("bids", [])
        total_long_value = 0.0
        for bid in bids[:20]:  # Топ 20 уровней
            price = float(bid[0])
            quantity = float(bid[1])
            if price < current_price:
                total_long_value += price * quantity
        
        # Оцениваем уровни ликвидации для long позиций
        # Предполагаем среднее плечо 20x
        avg_leverage = 20.0
        if total_long_value > 0:
            # Примерный уровень ликвидации для long позиций
            # При плече 20x ликвидация происходит примерно при падении на 5%
            liquidation_price_long = current_price * (1 - 1/avg_leverage)
            if liquidation_price_long > 0:
                levels.append(LiquidationLevel(
                    price=liquidation_price_long,
                    usd_value=total_long_value * 0.1,  # Примерная оценка
                    side="long"
                ))
        
        # Анализируем asks (короткие позиции) - ликвидация выше текущей цены
        asks = data.get("asks", [])
        total_short_value = 0.0
        for ask in asks[:20]:
            price = float(ask[0])
            quantity = float(ask[1])
            if price > current_price:
                total_short_value += price * quantity
        
        # Оцениваем уровни ликвидации для short позиций
        if total_short_value > 0:
            liquidation_price_short = current_price * (1 + 1/avg_leverage)
            if liquidation_price_short > 0:
                levels.append(LiquidationLevel(
                    price=liquidation_price_short,
                    usd_value=total_short_value * 0.1,
                    side="short",
                    exchange="binance_estimated"
                ))
        
        return levels
        
    except Exception as e:
        log.warning("Failed to estimate liquidation levels for %s: %s", symbol, e)
        return []


# ==================== Поддержка других бирж ====================

def get_liquidation_levels_from_okx(symbol: str, hours: int = 48) -> List[LiquidationLevel]:
    """
    Получить уровни ликвидации из OKX API.
    """
    symbol_usdt = f"{symbol}-USDT-SWAP" if not symbol.endswith("-USDT-SWAP") else symbol
    
    cache_key = f"liqs_okx_{symbol}_{hours}"
    cached = _get_cached(cache_key, ttl=120)
    if cached is not None:
        return cached
    
    try:
        # OKX API требует временные метки в миллисекундах
        # Но для публичного API ликвидаций может быть ограничение по времени
        # Используем более короткий период и правильный формат
        end_ms = int(time.time() * 1000)
        # Ограничиваем до 24 часов максимум для публичного API
        hours_limited = min(hours, 24)
        start_ms = end_ms - (hours_limited * 3600 * 1000)
        
        url = f"{OKX}/api/v5/public/liquidation-orders"
        # OKX API может требовать параметры без instId для получения всех или использовать другой формат
        # Попробуем упрощенный запрос без временных ограничений сначала
        params = {
            "instType": "SWAP",
            "limit": "100"
        }
        
        # Если есть конкретный символ, добавляем его
        if symbol_usdt:
            params["instId"] = symbol_usdt
        
        r = _sess.get(url, params=params, timeout=15)
        
        # Если 400 ошибка, пробуем без временных параметров
        if r.status_code == 400:
            # Пробуем без begin/end - возможно API не поддерживает эти параметры для публичного endpoint
            params_no_time = {
                "instType": "SWAP",
                "limit": "100"
            }
            if symbol_usdt:
                params_no_time["instId"] = symbol_usdt
            r = _sess.get(url, params=params_no_time, timeout=15)
        
        r.raise_for_status()
        data = r.json()
        
        if data.get("code") != "0":
            log.debug("OKX API returned code: %s, msg: %s", data.get("code"), data.get("msg"))
            return []
        
        liqs = data.get("data", [])
        if not liqs:
            return []
        
        # Группируем по ценам
        price_groups: Dict[Tuple[str, float], float] = {}
        
        for liq in liqs:
            side = str(liq.get("side", "")).lower()
            if side not in ("long", "short"):
                continue
            
            price = float(liq.get("price", 0) or liq.get("px", 0))
            value = float(liq.get("sz", 0)) * price  # размер * цена
            
            if price <= 0 or value <= 0:
                continue
            
            # Округление как в Bybit функции
            if symbol.upper() == "BTC":
                price_rounded = round(price / 100) * 100
            elif symbol.upper() == "ETH":
                price_rounded = round(price / 10) * 10
            else:
                price_rounded = round(price * 100) / 100
            
            key = (side, price_rounded)
            price_groups[key] = price_groups.get(key, 0) + value
        
        levels = []
        for (side, price), total_value in price_groups.items():
            if total_value >= 500:
                levels.append(LiquidationLevel(
                    price=price,
                    usd_value=total_value,
                    side=side,
                    exchange="okx"
                ))
        
        result = sorted(levels, key=lambda x: x.price, reverse=True)
        _set_cached(cache_key, result)
        return result
        
    except Exception as e:
        log.warning("Failed to get liquidation levels from OKX for %s: %s", symbol, e)
        return []


def get_whale_orders_from_okx(symbol: str, min_amount_usd: Optional[float] = None, current_price: Optional[float] = None) -> List[WhaleOrder]:
    """
    Получить крупные ордера из OKX orderbook.
    """
    symbol_usdt = f"{symbol}-USDT-SWAP" if not symbol.endswith("-USDT-SWAP") else symbol
    
    cache_key = f"whale_orders_okx_{symbol_usdt}"
    cached = _get_cached(cache_key, ttl=60)
    if cached is not None:
        return cached
    
    try:
        url = f"{OKX}/api/v5/market/books"
        params = {"instId": symbol_usdt, "sz": "400"}  # глубина 400
        
        r = _sess.get(url, params=params, timeout=10)
        r.raise_for_status()
        data = r.json()
        
        if data.get("code") != "0":
            return []
        
        book_data = data.get("data", [{}])[0]
        if not book_data:
            return []
        
        if current_price is None:
            # Получаем текущую цену
            ticker_url = f"{OKX}/api/v5/market/ticker"
            ticker_r = _sess.get(ticker_url, params={"instId": symbol_usdt}, timeout=10)
            ticker_r.raise_for_status()
            ticker_data = ticker_r.json()
            if ticker_data.get("code") == "0" and ticker_data.get("data"):
                current_price = float(ticker_data["data"][0].get("last", 0))
            else:
                return []
        
        bids = book_data.get("bids", [])
        asks = book_data.get("asks", [])
        
        # Умный порог
        if min_amount_usd is None:
            # OKX может возвращать данные в формате [price, size, ...] или [price, size]
            try:
                total_notional = 0.0
                for item in bids + asks:
                    if isinstance(item, (list, tuple)) and len(item) >= 2:
                        total_notional += float(item[0]) * float(item[1])
                min_amount_usd = max(2_000_000.0, total_notional * 0.0005)
            except Exception:
                min_amount_usd = 2_000_000.0
        
        orders = []
        
        # Bids (buy)
        for bid in bids:
            # OKX формат: [price, size, ...] - берем первые два элемента
            if not isinstance(bid, (list, tuple)) or len(bid) < 2:
                continue
            price = float(bid[0])
            quantity = float(bid[1])
            amount_usd = price * quantity
            
            if amount_usd < min_amount_usd:
                continue
            if abs(price - current_price) / current_price > 0.1:
                continue
            
            orders.append(WhaleOrder(
                price=price,
                amount=amount_usd,
                side="buy",
                age="Live",
                exchange="okx"
            ))
        
        # Asks (sell)
        for ask in asks:
            # OKX формат: [price, size, ...] - берем первые два элемента
            if not isinstance(ask, (list, tuple)) or len(ask) < 2:
                continue
            price = float(ask[0])
            quantity = float(ask[1])
            amount_usd = price * quantity
            
            if amount_usd < min_amount_usd:
                continue
            if abs(price - current_price) / current_price > 0.1:
                continue
            
            orders.append(WhaleOrder(
                price=price,
                amount=amount_usd,
                side="sell",
                age="Live",
                exchange="okx"
            ))
        
        result = sorted(orders, key=lambda x: x.amount, reverse=True)
        _set_cached(cache_key, result)
        return result
        
    except Exception as e:
        log.warning("Failed to get whale orders from OKX for %s: %s", symbol, e)
        return []


def get_large_trades_from_okx(symbol: str, limit: int = 500, min_usd: float = 100_000.0, since_ms: Optional[int] = None) -> List[LargeTrade]:
    """
    Получить крупные сделки из OKX API.
    """
    symbol_usdt = f"{symbol}-USDT-SWAP" if not symbol.endswith("-USDT-SWAP") else symbol
    
    if since_ms is None:
        cache_key = f"large_trades_okx_{symbol_usdt}_{limit}"
        cached = _get_cached(cache_key, ttl=60)
        if cached is not None:
            return cached
    
    try:
        url = f"{OKX}/api/v5/market/trades"
        params = {"instId": symbol_usdt, "limit": str(limit)}
        
        if since_ms is not None:
            params["before"] = str(since_ms)
        
        r = _sess.get(url, params=params, timeout=10)
        r.raise_for_status()
        data = r.json()
        
        if data.get("code") != "0":
            return []
        
        trades = data.get("data", [])
        large_trades = []
        
        for trade in trades:
            price = float(trade.get("px", 0))
            quantity = float(trade.get("sz", 0))
            usd_value = price * quantity
            
            if usd_value >= min_usd:
                side = "buy" if trade.get("side") == "buy" else "sell"
                timestamp = int(trade.get("ts", 0))
                
                large_trades.append(LargeTrade(
                    price=price,
                    quantity=quantity,
                    side=side,
                    timestamp=timestamp,
                    usd_value=usd_value,
                    exchange="okx"
                ))
        
        result = sorted(large_trades, key=lambda x: x.usd_value, reverse=True)
        
        if since_ms is None:
            _set_cached(cache_key, result)
        
        return result
        
    except Exception as e:
        log.warning("Failed to get large trades from OKX for %s: %s", symbol, e)
        return []


# ==================== Агрегирующие функции ====================

def get_liquidation_levels_aggregated(
    symbol: str,
    exchanges: Optional[List[str]] = None,
    hours: int = 48
) -> Dict[str, List[LiquidationLevel]]:
    """
    Получить уровни ликвидации с нескольких бирж и агрегировать их.
    
    Args:
        symbol: Символ (BTC, ETH)
        exchanges: Список бирж для запроса (по умолчанию все доступные)
        hours: Период в часах
    
    Returns:
        Словарь {exchange: [levels]}
    """
    if exchanges is None:
        exchanges = ["bybit", "okx"]  # По умолчанию используем эти биржи
    
    results: Dict[str, List[LiquidationLevel]] = {}
    
    # Bybit
    if "bybit" in exchanges:
        try:
            levels = get_liquidation_levels_from_bybit(symbol, hours)
            if levels:
                results["bybit"] = levels
        except Exception as e:
            log.warning("Failed to get Bybit liquidations: %s", e)
    
    # OKX
    if "okx" in exchanges:
        try:
            levels = get_liquidation_levels_from_okx(symbol, hours)
            if levels:
                results["okx"] = levels
        except Exception as e:
            log.warning("Failed to get OKX liquidations: %s", e)
    
    return results


def aggregate_liquidation_levels(
    levels_by_exchange: Dict[str, List[LiquidationLevel]],
    price_tolerance: float = 0.001
) -> List[LiquidationLevel]:
    """
    Агрегировать уровни ликвидации с разных бирж, объединяя близкие по цене.
    
    Args:
        levels_by_exchange: Словарь {exchange: [levels]}
        price_tolerance: Допустимое отклонение цены для объединения (0.1% по умолчанию)
    
    Returns:
        Агрегированный список уровней
    """
    # Собираем все уровни с указанием биржи
    all_levels: List[Tuple[LiquidationLevel, str]] = []
    for exchange, levels in levels_by_exchange.items():
        for level in levels:
            all_levels.append((level, exchange))
    
    if not all_levels:
        return []
    
    # Группируем по близким ценам и стороне
    aggregated: Dict[Tuple[str, float], Tuple[float, float, List[str]]] = {}
    # key: (side, rounded_price) -> (total_value, avg_price, exchanges)
    
    for level, exchange in all_levels:
        # Округление для группировки
        if level.price > 1000:  # BTC
            rounded = round(level.price / 100) * 100
        elif level.price > 100:  # ETH
            rounded = round(level.price / 10) * 10
        else:
            rounded = round(level.price * 100) / 100
        
        key = (level.side, rounded)
        
        if key in aggregated:
            total_val, avg_price, exchanges_list = aggregated[key]
            total_val += level.usd_value
            # Взвешенное среднее
            avg_price = (avg_price * (len(exchanges_list) - 1) + level.price) / len(exchanges_list)
            exchanges_list.append(exchange)
            aggregated[key] = (total_val, avg_price, exchanges_list)
        else:
            aggregated[key] = (level.usd_value, level.price, [exchange])
    
    # Создаем финальный список
    result = []
    for (side, _), (total_value, avg_price, exchanges_list) in aggregated.items():
        # Объединяем биржи в строку
        exchanges_str = "+".join(sorted(set(exchanges_list)))
        
        result.append(LiquidationLevel(
            price=avg_price,
            usd_value=total_value,
            side=side,
            exchange=exchanges_str
        ))
    
    return sorted(result, key=lambda x: x.price, reverse=True)


def get_whale_orders_aggregated(
    symbol: str,
    exchanges: Optional[List[str]] = None,
    min_amount_usd: Optional[float] = None,
    current_price: Optional[float] = None
) -> Dict[str, List[WhaleOrder]]:
    """
    Получить крупные ордера с нескольких бирж.
    
    Args:
        symbol: Символ (BTC, ETH)
        exchanges: Список бирж для запроса (по умолчанию все доступные)
        min_amount_usd: Минимальный размер ордера в USD
        current_price: Текущая цена (опционально, будет получена автоматически)
    
    Returns:
        Словарь {exchange: [orders]}
    """
    if exchanges is None:
        # По умолчанию используем все доступные биржи
        exchanges = ["binance", "bybit", "okx", "coinbase"]
    
    results: Dict[str, List[WhaleOrder]] = {}
    
    # Получаем текущую цену один раз для всех бирж (если не указана)
    if current_price is None:
        try:
            from ...infrastructure.market_data import binance_spot_price
            symbol_usdt = f"{symbol}USDT"
            current_price = binance_spot_price(symbol_usdt)
        except Exception:
            pass  # Будет получена индивидуально для каждой биржи
    
    # Binance
    if "binance" in exchanges:
        try:
            orders = get_whale_orders_from_binance(symbol, min_amount_usd, current_price)
            if orders:
                results["binance"] = orders
        except Exception as e:
            log.warning("Failed to get Binance whale orders: %s", e)
    
    # Bybit
    if "bybit" in exchanges:
        try:
            orders = get_whale_orders_from_bybit(symbol, min_amount_usd, current_price)
            if orders:
                results["bybit"] = orders
        except Exception as e:
            log.warning("Failed to get Bybit whale orders: %s", e)
    
    # OKX
    if "okx" in exchanges:
        try:
            orders = get_whale_orders_from_okx(symbol, min_amount_usd, current_price)
            if orders:
                results["okx"] = orders
        except Exception as e:
            log.warning("Failed to get OKX whale orders: %s", e)
    
    # Coinbase
    if "coinbase" in exchanges:
        try:
            orders = get_whale_orders_from_coinbase(symbol, min_amount_usd, current_price)
            if orders:
                results["coinbase"] = orders
        except Exception as e:
            log.warning("Failed to get Coinbase whale orders: %s", e)
    
    return results


def get_large_trades_aggregated(
    symbol: str,
    exchanges: Optional[List[str]] = None,
    timeframe: str = "1h",
    min_usd: float = 100_000.0,
    db=None
) -> Dict[str, List[LargeTrade]]:
    """
    Получить крупные сделки с нескольких бирж.
    
    Args:
        symbol: Символ торговли (например, "BTC")
        exchanges: Список бирж для запроса (по умолчанию все доступные)
        timeframe: Период анализа ("1h", "4h", "24h")
        min_usd: Минимальный размер сделки в USD
        db: Экземпляр DB для использования кэшированных данных (опционально)
    
    Returns:
        Словарь {exchange: [trades]}
    """
    if exchanges is None:
        exchanges = ["binance", "okx", "bybit", "gate"]
    
    tf_hours = {"1h": 1, "4h": 4, "24h": 24}.get(timeframe, 1)
    now_ms = int(time.time() * 1000)
    since_ms = now_ms - (tf_hours * 3600 * 1000)
    
    results: Dict[str, List[LargeTrade]] = {}
    
    # Если есть БД, сначала пытаемся получить данные из кэша
    if db:
        try:
            symbol_usdt = f"{symbol}USDT" if not symbol.endswith("USDT") else symbol
            all_trades = db.get_trades_by_period(symbol_usdt, since_ms, now_ms)
            
            if all_trades:
                log.debug(f"Found {len(all_trades)} trades in DB for {symbol}")
                # Фильтруем крупные сделки и группируем по биржам
                trades_by_exchange = {}
                for trade in all_trades:
                    volume_usd = trade["price"] * trade["qty"]
                    if volume_usd >= min_usd:
                        # Нормализуем имя биржи: "Binance" -> "binance", "OKX" -> "okx", etc.
                        exchange_raw = trade["exchange"]
                        exchange = exchange_raw.lower()
                        # Маппинг имен бирж для совместимости
                        exchange_map = {
                            "binance": "binance",
                            "okx": "okx",
                            "bybit": "bybit",
                            "gate": "gate",
                        }
                        exchange = exchange_map.get(exchange, exchange)
                        
                        if exchange not in trades_by_exchange:
                            trades_by_exchange[exchange] = []
                        
                        trades_by_exchange[exchange].append(LargeTrade(
                            price=trade["price"],
                            quantity=trade["qty"],
                            side="buy" if trade["is_buyer"] else "sell",
                            timestamp=trade["time"],
                            usd_value=volume_usd,
                            exchange=exchange
                        ))
                
                log.debug(f"Large trades by exchange from DB: {list(trades_by_exchange.keys())}")
                
                # Сортируем по размеру для каждой биржи
                for exchange, trades in trades_by_exchange.items():
                    if exchange in exchanges:
                        results[exchange] = sorted(trades, key=lambda x: x.usd_value, reverse=True)
                        log.debug(f"Added {len(trades)} large trades from DB for {exchange}")
                
                # Если получили данные из БД, используем их (но дополняем API если нужно)
                if results:
                    log.info(f"Using cached trades from DB for {symbol}: {list(results.keys())} exchanges")
                    # Дополняем API данными для бирж, которых нет в кэше
                    missing_exchanges = [ex for ex in exchanges if ex not in results]
                    if missing_exchanges:
                        log.info(f"Fetching from API for missing exchanges: {missing_exchanges}")
                        # Продолжаем выполнение, чтобы получить данные для недостающих бирж
                    else:
                        # Все биржи есть в кэше - возвращаем результат
                        log.info(f"All exchanges found in cache for {symbol}")
                        return results
                else:
                    log.debug(f"No large trades found in DB for {symbol}, fetching from API")
        except Exception as e:
            log.warning(f"Error getting trades from DB for {symbol}, falling back to API: {e}")
    
    # Fallback: получаем данные напрямую с бирж через API
    # Для длительных периодов используем пагинацию через exchange clients
    try:
        from ..domain.twap_detector.exchange_client import get_exchange_clients
        
        exchange_clients_map = {
            "binance": None,
            "okx": None,
            "bybit": None,
            "gate": None,
        }
        
        for client in get_exchange_clients():
            client_name_lower = client.name.lower()
            if client_name_lower in exchange_clients_map:
                exchange_clients_map[client_name_lower] = client
        
        # Binance - запрашиваем только если нет в results или явно запрошено
        if "binance" in exchanges and "binance" not in results:
            try:
                if exchange_clients_map["binance"]:
                    # Используем пагинацию через exchange client
                    all_trades = exchange_clients_map["binance"].get_all_trades(
                        f"{symbol}USDT" if not symbol.endswith("USDT") else symbol,
                        since_ms,
                        now_ms
                    )
                    log.debug(f"Got {len(all_trades)} trades from Binance API for {symbol}")
                    
                    # Проверяем временной диапазон
                    trades_in_range = [t for t in all_trades if since_ms <= t["time"] <= now_ms]
                    log.debug(f"Binance: {len(trades_in_range)} trades in time range [{since_ms}, {now_ms}]")
                    
                    # Фильтруем крупные сделки с проверкой временного диапазона
                    large_trades = [
                        LargeTrade(
                            price=t["price"],
                            quantity=t["qty"],
                            side="buy" if t["is_buyer"] else "sell",
                            timestamp=t["time"],
                            usd_value=t["price"] * t["qty"],
                            exchange="binance"
                        )
                        for t in all_trades
                        if since_ms <= t["time"] <= now_ms and t["price"] * t["qty"] >= min_usd
                    ]
                    if large_trades:
                        results["binance"] = sorted(large_trades, key=lambda x: x.usd_value, reverse=True)
                        log.info(f"Added {len(large_trades)} large trades from Binance API")
                else:
                    # Fallback на старый метод
                    limit = 1000  # Увеличиваем лимит для пагинации
                    trades = get_large_trades_from_binance(symbol, limit, min_usd, since_ms)
                    if trades:
                        results["binance"] = trades
                        log.info(f"Added {len(trades)} large trades from Binance (fallback)")
            except Exception as e:
                log.warning("Failed to get Binance large trades: %s", e)
    
        # OKX - запрашиваем только если нет в results
        # ВАЖНО: Используем старый метод, который запрашивает SWAP (фьючерсы), где сделки крупнее
        # Exchange client запрашивает SPOT, где сделки меньше
        if "okx" in exchanges and "okx" not in results:
            try:
                # Используем старый метод для OKX, который запрашивает SWAP (фьючерсы)
                # Это дает более крупные сделки, чем SPOT
                limit = 500
                trades = get_large_trades_from_okx(symbol, limit, min_usd, since_ms)
                if trades:
                    # Фильтруем по времени, так как старый метод может не учитывать since_ms правильно
                    filtered_trades = [
                        t for t in trades
                        if since_ms <= t.timestamp <= now_ms
                    ]
                    if filtered_trades:
                        results["okx"] = sorted(filtered_trades, key=lambda x: x.usd_value, reverse=True)
                        log.info(f"Added {len(filtered_trades)} large trades from OKX (SWAP/futures)")
                    else:
                        log.debug(f"OKX: {len(trades)} trades found, but none in time range [{since_ms}, {now_ms}]")
            except Exception as e:
                log.warning("Failed to get OKX large trades: %s", e)
        
        # Bybit - запрашиваем только если нет в results
        if "bybit" in exchanges and "bybit" not in results:
            try:
                if exchange_clients_map["bybit"]:
                    all_trades = exchange_clients_map["bybit"].get_all_trades(
                        f"{symbol}USDT" if not symbol.endswith("USDT") else symbol,
                        since_ms,
                        now_ms
                    )
                    log.debug(f"Got {len(all_trades)} trades from Bybit API for {symbol}")
                    
                    # Проверяем временной диапазон и размер сделок
                    trades_in_range = [t for t in all_trades if since_ms <= t["time"] <= now_ms]
                    log.debug(f"Bybit: {len(trades_in_range)} trades in time range [{since_ms}, {now_ms}]")
                    
                    # Проверяем максимальный размер сделки
                    if all_trades:
                        max_volume = max(t["price"] * t["qty"] for t in all_trades)
                        log.debug(f"Bybit: Max trade volume = ${max_volume:,.2f}, min_usd = ${min_usd:,.2f}")
                    
                    large_trades = [
                        LargeTrade(
                            price=t["price"],
                            quantity=t["qty"],
                            side="buy" if t["is_buyer"] else "sell",
                            timestamp=t["time"],
                            usd_value=t["price"] * t["qty"],
                            exchange="bybit"
                        )
                        for t in all_trades
                        if since_ms <= t["time"] <= now_ms and t["price"] * t["qty"] >= min_usd
                    ]
                    if large_trades:
                        results["bybit"] = sorted(large_trades, key=lambda x: x.usd_value, reverse=True)
                        log.info(f"Added {len(large_trades)} large trades from Bybit API")
                    else:
                        log.debug(f"Bybit: No large trades found (>= ${min_usd:,.2f}) after filtering")
            except Exception as e:
                log.warning("Failed to get Bybit large trades: %s", e)
        
        # Gate.io - запрашиваем только если нет в results
        if "gate" in exchanges and "gate" not in results:
            try:
                if exchange_clients_map["gate"]:
                    all_trades = exchange_clients_map["gate"].get_all_trades(
                        f"{symbol}USDT" if not symbol.endswith("USDT") else symbol,
                        since_ms,
                        now_ms
                    )
                    log.debug(f"Got {len(all_trades)} trades from Gate.io API for {symbol}")
                    
                    # Проверяем временной диапазон и размер сделок
                    trades_in_range = [t for t in all_trades if since_ms <= t["time"] <= now_ms]
                    log.debug(f"Gate: {len(trades_in_range)} trades in time range [{since_ms}, {now_ms}]")
                    
                    # Проверяем максимальный размер сделки
                    if all_trades:
                        max_volume = max(t["price"] * t["qty"] for t in all_trades)
                        log.debug(f"Gate: Max trade volume = ${max_volume:,.2f}, min_usd = ${min_usd:,.2f}")
                    
                    large_trades = [
                        LargeTrade(
                            price=t["price"],
                            quantity=t["qty"],
                            side="buy" if t["is_buyer"] else "sell",
                            timestamp=t["time"],
                            usd_value=t["price"] * t["qty"],
                            exchange="gate"
                        )
                        for t in all_trades
                        if since_ms <= t["time"] <= now_ms and t["price"] * t["qty"] >= min_usd
                    ]
                    if large_trades:
                        results["gate"] = sorted(large_trades, key=lambda x: x.usd_value, reverse=True)
                        log.info(f"Added {len(large_trades)} large trades from Gate.io API")
                    else:
                        log.debug(f"Gate: No large trades found (>= ${min_usd:,.2f}) after filtering")
            except Exception as e:
                log.warning("Failed to get Gate.io large trades: %s", e)
    
    except Exception as e:
        log.warning(f"Error using exchange clients for large trades: {e}")
        # Fallback на старые методы
        if "binance" in exchanges and "binance" not in results:
            try:
                trades = get_large_trades_from_binance(symbol, 500, min_usd, since_ms)
                if trades:
                    results["binance"] = trades
            except Exception:
                pass
        
        if "okx" in exchanges and "okx" not in results:
            try:
                trades = get_large_trades_from_okx(symbol, 500, min_usd, since_ms)
                if trades:
                    results["okx"] = trades
            except Exception:
                pass
    
    # Финальное логирование результата
    total_trades = sum(len(trades) for trades in results.values())
    log.info(
        f"get_large_trades_aggregated for {symbol} ({timeframe}): "
        f"found {len(results)} exchanges with {total_trades} total large trades. "
        f"Exchanges: {list(results.keys())}"
    )
    
    return results


# ==================== Дополнительные метрики ====================

def calculate_liquidation_velocity(levels: List[LiquidationLevel], hours: int) -> float:
    """
    Рассчитать скорость ликвидаций (USD в час).
    """
    if not levels or hours <= 0:
        return 0.0
    total_usd = sum(l.usd_value for l in levels)
    return total_usd / hours


def calculate_liquidity_concentration(levels: List[LiquidationLevel]) -> float:
    """
    Рассчитать индекс концентрации ликвидности (индекс Герфиндаля).
    Возвращает значение от 0 до 1, где 1 = максимальная концентрация.
    """
    if not levels:
        return 0.0
    
    total_usd = sum(l.usd_value for l in levels)
    if total_usd <= 0:
        return 0.0
    
    # Сумма квадратов долей
    hhi = sum((l.usd_value / total_usd) ** 2 for l in levels)
    return hhi


def calculate_long_short_ratio(levels: List[LiquidationLevel]) -> float:
    """
    Рассчитать соотношение long/short ликвидаций.
    """
    long_usd = sum(l.usd_value for l in levels if l.side == "long")
    short_usd = sum(l.usd_value for l in levels if l.side == "short")
    
    if short_usd == 0:
        return float('inf') if long_usd > 0 else 0.0
    
    return long_usd / short_usd


def analyze_whale_order_distribution(orders: List[WhaleOrder]) -> Dict[str, float]:
    """
    Анализ распределения ордеров китов.
    
    Returns:
        Словарь с метриками: total_count, avg_size, median_size, max_size, etc.
    """
    if not orders:
        return {}
    
    amounts = [o.amount for o in orders]
    total_count = len(orders)
    total_value = sum(amounts)
    avg_size = total_value / total_count if total_count > 0 else 0
    
    sorted_amounts = sorted(amounts)
    median_size = sorted_amounts[len(sorted_amounts) // 2] if sorted_amounts else 0
    max_size = max(amounts) if amounts else 0
    min_size = min(amounts) if amounts else 0
    
    # Распределение по биржам
    exchange_counts: Dict[str, int] = {}
    exchange_values: Dict[str, float] = {}
    for order in orders:
        ex = order.exchange
        exchange_counts[ex] = exchange_counts.get(ex, 0) + 1
        exchange_values[ex] = exchange_values.get(ex, 0) + order.amount
    
    return {
        "total_count": total_count,
        "total_value": total_value,
        "avg_size": avg_size,
        "median_size": median_size,
        "max_size": max_size,
        "min_size": min_size,
        "exchange_counts": exchange_counts,
        "exchange_values": exchange_values
    }

