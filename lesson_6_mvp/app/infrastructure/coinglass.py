# app/infrastructure/coinglass.py
from __future__ import annotations

import os
import time
import logging
from dataclasses import dataclass
from typing import Any, Dict, List
import re

import requests
from requests import Response, HTTPError, RequestException

log = logging.getLogger("alt_forecast.coinglass")

COINGLASS_API = os.getenv("COINGLASS_API_BASE", "https://open-api.coinglass.com/api/pro/v1")
DEFAULT_TIMEOUT = float(os.getenv("COINGLASS_TIMEOUT_SEC", "20"))

__all__ = [
    "MaxPainPoint", "MaxPainResult", "fetch_max_pain",
    "LiquidationLevel", "LiquidationLevelsResult", "fetch_liquidation_levels",
    "WhaleOrder", "WhaleOrdersResult", "fetch_whale_orders",
    "WhalePosition", "WhaleActivityResult", "fetch_whale_activity"
]


@dataclass(frozen=True, slots=True)
class MaxPainPoint:
    date: str       # normalized "YYYY-MM-DD"
    notional: float # USD notional (>=0)
    max_pain: float # price level (USD, >=0)


@dataclass(frozen=True, slots=True)
class MaxPainResult:
    symbol: str          # "BTC" | "ETH" | ...
    points: List[MaxPainPoint]
    as_of: float         # unix ts (seconds)


def _hdr() -> Dict[str, str]:
    """
    Build request headers. CoinGlass expects 'coinglassSecret'.
    """
    secret = (os.getenv("COINGLASS_API_KEY") or os.getenv("COINGLASS_SECRET") or "").strip()
    if not secret:
        raise RuntimeError("COINGLASS_API_KEY env var is required")
    return {
        "coinglassSecret": secret,
        "accept": "application/json",
        "user-agent": "alt-forecast-bot/1.0 (+telebot)"
    }


_DATE_RE_YYYYMMDD = re.compile(r"^\d{8}$")
_DATE_RE_ISO = re.compile(r"^\d{4}-\d{2}-\d{2}")


def _norm_date(raw: Any) -> str:
    """
    Normalize various date representations to 'YYYY-MM-DD'.
    Understands 'YYYYMMDD', 'YYYY-MM-DD', ISO datetime, and unix (sec/ms).
    """
    if raw is None:
        return time.strftime("%Y-%m-%d", time.gmtime())

    s = str(raw).strip()
    if not s:
        return time.strftime("%Y-%m-%d", time.gmtime())

    # unix timestamps (sec/ms)
    try:
        val = float(s)
        if val > 1e12:  # ms
            t = time.gmtime(val / 1000.0)
            return time.strftime("%Y-%m-%d", t)
        if val > 1e9:   # sec
            t = time.gmtime(val)
            return time.strftime("%Y-%m-%d", t)
    except Exception:
        pass

    # YYYYMMDD
    if _DATE_RE_YYYYMMDD.match(s):
        return f"{s[0:4]}-{s[4:6]}-{s[6:8]}"

    # YYYY-MM-DD...
    if _DATE_RE_ISO.match(s):
        return s[:10]

    # several popular human formats
    for fmt in ("%Y/%m/%d", "%d.%m.%Y", "%m/%d/%Y"):
        try:
            t = time.strptime(s, fmt)
            return time.strftime("%Y-%m-%d", t)
        except Exception:
            continue

    # fallback: today (UTC)
    return time.strftime("%Y-%m-%d", time.gmtime())


def _to_float(v: Any, default: float = 0.0) -> float:
    try:
        f = float(v)
        if f != f:  # NaN
            return default
        return f
    except Exception:
        return default


def _request_with_retries(url: str, params: Dict[str, Any], max_retries: int = 3) -> Response:
    """
    Simple exponential backoff + honor Retry-After on 429.
    """
    backoff = 1.0
    for attempt in range(1, max_retries + 1):
        try:
            resp = requests.get(url, headers=_hdr(), params=params, timeout=DEFAULT_TIMEOUT)
            if resp.status_code == 429:
                retry_after = resp.headers.get("Retry-After")
                sleep_for = _to_float(retry_after, backoff)
                log.warning(
                    "CoinGlass 429 Retry-After=%s; sleeping %.1fs (attempt %d/%d)",
                    retry_after, sleep_for, attempt, max_retries
                )
                time.sleep(sleep_for)
                backoff = min(backoff * 2, 8.0)
                continue
            resp.raise_for_status()
            return resp

        except HTTPError as e:
            code = getattr(e.response, "status_code", 0)
            if 500 <= code < 600 and attempt < max_retries:
                log.warning("CoinGlass %s, retrying in %.1fs (attempt %d/%d)",
                            code, backoff, attempt, max_retries)
                time.sleep(backoff)
                backoff = min(backoff * 2, 8.0)
                continue
            log.exception("CoinGlass HTTP error: %s", code)
            raise

        except RequestException:
            if attempt < max_retries:
                log.warning("CoinGlass network error, retrying in %.1fs (attempt %d/%d)",
                            backoff, attempt, max_retries)
                time.sleep(backoff)
                backoff = min(backoff * 2, 8.0)
                continue
            log.exception("CoinGlass network error, giving up")
            raise

    # should be unreachable
    raise RuntimeError("unreachable")


def fetch_max_pain(symbol: str) -> MaxPainResult:
    """
    Fetch and normalize CoinGlass options Max Pain by expiries.
    Output points contain:
      - date: 'YYYY-MM-DD'
      - notional: float (USD, >=0)
      - max_pain: float (USD, >=0)
    """
    url = f"{COINGLASS_API}/option/max_pain"
    params = {"symbol": (symbol or "").upper()}

    resp = _request_with_retries(url, params)
    try:
        j = resp.json()
    except Exception as e:
        log.exception("CoinGlass JSON parse failed")
        raise RuntimeError("CoinGlass JSON parse failed") from e

    data = j.get("data", j)
    if isinstance(data, dict):
        data = [data]
    if not isinstance(data, list):
        raise RuntimeError("CoinGlass: unexpected payload shape")

    points: List[MaxPainPoint] = []
    for item in data:
        raw_date = item.get("date") or item.get("expiry") or item.get("endTime")
        date = _norm_date(raw_date)

        # normalize numeric fields and clamp to >= 0
        notional = max(0.0, _to_float(item.get("notionalValue") or item.get("notional") or item.get("value") or 0.0, 0.0))
        maxp = max(0.0, _to_float(item.get("maxPainPrice") or item.get("maxPain") or item.get("price") or 0.0, 0.0))

        points.append(MaxPainPoint(date=date, notional=notional, max_pain=maxp))

    # stable sort by date
    try:
        points.sort(key=lambda p: p.date)
    except Exception:
        pass

    return MaxPainResult(symbol=params["symbol"], points=points, as_of=time.time())


@dataclass(frozen=True, slots=True)
class LiquidationLevel:
    """Уровень ликвидации."""
    price: float      # цена уровня
    usd_value: float  # USD значение ликвидации
    side: str         # "long" | "short"


@dataclass(frozen=True, slots=True)
class LiquidationLevelsResult:
    """Результат запроса уровней ликвидации."""
    symbol: str
    levels: List[LiquidationLevel]
    as_of: float


def fetch_liquidation_levels(symbol: str) -> LiquidationLevelsResult:
    """
    Получить предсказанные уровни ликвидации для символа.
    Использует CoinGlass API или альтернативные источники.
    """
    symbol_upper = (symbol or "").upper().strip()
    
    # Пробуем CoinGlass API
    try:
        url = f"{COINGLASS_API}/futures/liquidation_levels"
        params = {"symbol": symbol_upper}
        resp = _request_with_retries(url, params)
        j = resp.json()
        
        data = j.get("data", j)
        if isinstance(data, dict):
            data = [data]
        if not isinstance(data, list):
            data = []
        
        levels: List[LiquidationLevel] = []
        for item in data:
            price = max(0.0, _to_float(item.get("price") or item.get("liquidationPrice") or 0.0, 0.0))
            usd_value = max(0.0, _to_float(item.get("usdValue") or item.get("value") or item.get("notional") or 0.0, 0.0))
            side = str(item.get("side") or item.get("type") or "long").lower()
            if price > 0 and usd_value > 0:
                levels.append(LiquidationLevel(price=price, usd_value=usd_value, side=side))
        
        return LiquidationLevelsResult(symbol=symbol_upper, levels=levels, as_of=time.time())
    except Exception as e:
        log.warning("CoinGlass liquidation levels API failed for %s: %s", symbol_upper, e)
        # Fallback: возвращаем пустой результат
        return LiquidationLevelsResult(symbol=symbol_upper, levels=[], as_of=time.time())


@dataclass(frozen=True, slots=True)
class WhaleOrder:
    """Ордер кита."""
    price: float      # цена ордера
    amount: float     # USD значение ордера
    side: str         # "buy" | "sell"
    age: str          # возраст ордера (например, "5D 4H")


@dataclass(frozen=True, slots=True)
class WhaleOrdersResult:
    """Результат запроса крупных ордеров."""
    symbol: str
    exchange: str     # биржа (например, "Binance")
    orders: List[WhaleOrder]
    as_of: float


def fetch_whale_orders(symbol: str, exchange: str = "Binance", min_amount: float = 5_000_000.0) -> WhaleOrdersResult:
    """
    Получить крупные ордера китов для символа.
    """
    symbol_upper = (symbol or "").upper().strip()
    exchange_upper = (exchange or "Binance").strip()
    
    try:
        url = f"{COINGLASS_API}/futures/whale_orders"
        params = {
            "symbol": symbol_upper,
            "exchange": exchange_upper,
            "minAmount": min_amount
        }
        resp = _request_with_retries(url, params)
        j = resp.json()
        
        data = j.get("data", j)
        if isinstance(data, dict):
            data = [data]
        if not isinstance(data, list):
            data = []
        
        orders: List[WhaleOrder] = []
        for item in data:
            price = max(0.0, _to_float(item.get("price") or 0.0, 0.0))
            amount = max(0.0, _to_float(item.get("amount") or item.get("usdValue") or item.get("value") or 0.0, 0.0))
            side = str(item.get("side") or item.get("type") or "buy").lower()
            age = str(item.get("age") or item.get("time") or "unknown")
            
            if price > 0 and amount >= min_amount:
                orders.append(WhaleOrder(price=price, amount=amount, side=side, age=age))
        
        # Сортируем по цене
        orders.sort(key=lambda x: x.price, reverse=True)
        
        return WhaleOrdersResult(symbol=symbol_upper, exchange=exchange_upper, orders=orders, as_of=time.time())
    except Exception as e:
        log.warning("CoinGlass whale orders API failed for %s: %s", symbol_upper, e)
        return WhaleOrdersResult(symbol=symbol_upper, exchange=exchange_upper, orders=[], as_of=time.time())


@dataclass(frozen=True, slots=True)
class WhalePosition:
    """Позиция кита."""
    address: str      # адрес (сокращенный)
    total_pnl: float  # общий PnL в USD
    perp_pnl: float   # PnL по перпетуалам
    position_size: float  # размер позиции в USD
    position_eth: float  # размер позиции в ETH (для ETH) или BTC
    leverage: str     # кредитное плечо
    entry_price: float
    liquidation_price: float
    margin_used: float
    activity: str     # "OPEN LONG" | "OPEN SHORT" | "CLOSE LONG" | "CLOSE SHORT"


@dataclass(frozen=True, slots=True)
class WhaleActivityResult:
    """Результат запроса активности китов."""
    symbol: str
    timeframe: str    # "1h" | "4h" | "24h"
    positions: List[WhalePosition]
    as_of: float


def fetch_whale_activity(symbol: str, timeframe: str = "1h", limit: int = 20) -> WhaleActivityResult:
    """
    Получить активность крупных китов для символа за указанный таймфрейм.
    """
    symbol_upper = (symbol or "").upper().strip()
    tf_map = {"1h": "1h", "4h": "4h", "24h": "24h", "1d": "24h"}
    tf = tf_map.get(timeframe.lower(), "1h")
    
    try:
        url = f"{COINGLASS_API}/futures/whale_activity"
        params = {
            "symbol": symbol_upper,
            "timeframe": tf,
            "limit": limit
        }
        resp = _request_with_retries(url, params)
        j = resp.json()
        
        data = j.get("data", j)
        if isinstance(data, dict):
            data = [data]
        if not isinstance(data, list):
            data = []
        
        positions: List[WhalePosition] = []
        for item in data[:limit]:
            address = str(item.get("address") or item.get("wallet") or "unknown")
            total_pnl = _to_float(item.get("totalPnl") or item.get("totalPnL") or item.get("pnl") or 0.0, 0.0)
            perp_pnl = _to_float(item.get("perpPnl") or item.get("perpPnL") or total_pnl, 0.0)
            position_size = _to_float(item.get("positionSize") or item.get("position") or item.get("size") or 0.0, 0.0)
            position_eth = _to_float(item.get("positionEth") or item.get("positionBtc") or item.get("positionAmount") or 0.0, 0.0)
            leverage = str(item.get("leverage") or item.get("leverageType") or "unknown")
            entry_price = max(0.0, _to_float(item.get("entryPrice") or item.get("entry") or 0.0, 0.0))
            liquidation_price = max(0.0, _to_float(item.get("liquidationPrice") or item.get("liquidation") or 0.0, 0.0))
            margin_used = max(0.0, _to_float(item.get("marginUsed") or item.get("margin") or 0.0, 0.0))
            activity = str(item.get("activity") or item.get("action") or "unknown").upper()
            
            positions.append(WhalePosition(
                address=address,
                total_pnl=total_pnl,
                perp_pnl=perp_pnl,
                position_size=position_size,
                position_eth=position_eth,
                leverage=leverage,
                entry_price=entry_price,
                liquidation_price=liquidation_price,
                margin_used=margin_used,
                activity=activity
            ))
        
        return WhaleActivityResult(symbol=symbol_upper, timeframe=tf, positions=positions, as_of=time.time())
    except Exception as e:
        log.warning("CoinGlass whale activity API failed for %s: %s", symbol_upper, e)
        return WhaleActivityResult(symbol=symbol_upper, timeframe=tf, positions=[], as_of=time.time())
