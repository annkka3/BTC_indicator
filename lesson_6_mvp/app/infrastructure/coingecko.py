#app/infrastructure/coingecko.py
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from typing import List, Dict, Tuple, Optional
from .cache import cached
from .quota import budget_guard
from ..config import settings


_SESSION = requests.Session()
_RETRY = Retry(
    total=3, connect=3, read=3,
    backoff_factor=1.0,
    status_forcelist=(429, 500, 502, 503, 504),
    allowed_methods=frozenset(["GET"])
)
_SESSION.mount("https://", HTTPAdapter(max_retries=_RETRY))
_SESSION.mount("http://",  HTTPAdapter(max_retries=_RETRY))

# Список стейблкоинов для фильтрации
STABLE_TICKERS = {"usdt", "usdc", "busd", "dai", "tusd", "usdp", "usdd", "frax", "lusd", "susd"}

def markets_page(vs: str = "usd", page: int = 1, per_page: int = 250):
    """Одна страница рынка. Берём сразу 250, чтобы не листать."""
    url = f"{settings.coingecko_api_base}/coins/markets"
    params = {
        "vs_currency": vs,
        "order": "market_cap_desc",
        "per_page": per_page,   # 250 — максимум у CoinGecko
        "page": page,
        "sparkline": "false",
        "price_change_percentage": "1h,24h,7d",
        "locale": "en",
    }
    r = _SESSION.get(url, params=params, headers=_headers(), timeout=20)
    r.raise_for_status()
    return r.json()

@budget_guard(units=1)  # Квота списывается только при реальном запросе
def _markets_snapshot_with_quota(vs: str = "usd"):
    """Внутренняя функция для запроса с учётом квоты."""
    return markets_page(vs=vs, page=1, per_page=250)

@cached(ttl=60*60, key_fn=lambda vs: f"markets-snapshot:{vs}", stale_ok=True)  # Увеличено до 60 минут
def markets_snapshot(vs: str = "usd"):
    """Получить снапшот рынка с обработкой ошибок и fallback на кэш.
    
    Декоратор @cached автоматически вернёт stale данные, если API недоступен.
    Если кэш пуст, функция вернёт пустой список вместо исключения.
    
    ВАЖНО: budget_guard вызывается только при реальном запросе к API (внутри markets_page),
    а не при использовании кэша.
    """
    try:
        # budget_guard вызывается только здесь, когда реально делается запрос
        return _markets_snapshot_with_quota(vs=vs)
    except (requests.exceptions.RetryError, requests.exceptions.RequestException) as e:
        # Если API недоступен и декоратор не смог вернуть stale данные (кэш пуст),
        # возвращаем пустой список вместо исключения
        import logging
        logger = logging.getLogger("alt_forecast.coingecko")
        # Используем WARNING вместо ERROR, так как это ожидаемое поведение при недоступности API
        logger.warning(
            f"CoinGecko API недоступен и кэш пуст, возвращаем пустой список: {type(e).__name__}"
        )
        return []

# --- категории (раз в сутки) ---
@budget_guard(units=1)
def _categories_with_quota():
    url = f"{settings.coingecko_api_base}/coins/categories"
    r = _SESSION.get(url, headers=_headers(), timeout=20)
    r.raise_for_status()
    return r.json()

@cached(ttl=24*60*60, key_fn=lambda : "categories", stale_ok=True)
def categories():
    return _categories_with_quota()

@budget_guard(units=1)
def _markets_by_category_with_quota(category: str, vs: str="usd"):
    url = f"{settings.coingecko_api_base}/coins/markets"
    params = {"vs_currency": vs, "category": category, "order": "market_cap_desc",
              "per_page": 250, "page": 1, "sparkline": "false",
              "price_change_percentage": "1h,24h,7d", "locale": "en"}
    r = _SESSION.get(url, params=params, headers=_headers(), timeout=20)
    r.raise_for_status()
    return r.json()

@cached(ttl=60*60, key_fn=lambda cat,vs: f"cat-{cat}-{vs}", stale_ok=True)  # Увеличено до 60 минут
def markets_by_category(category: str, vs: str="usd"):
    return _markets_by_category_with_quota(category, vs)

# --- trending (каждые 30 мин) ---
@budget_guard(units=1)
def _trending_with_quota():
    url = f"{settings.coingecko_api_base}/search/trending"
    r = _SESSION.get(url, headers=_headers(), timeout=20)
    r.raise_for_status()
    return r.json()

@cached(ttl=30*60, key_fn=lambda : "trending", stale_ok=True)  # Увеличено до 30 минут
def trending():
    return _trending_with_quota()

# --- global (каждые 60 мин) ---
@budget_guard(units=1)
def _global_stats_with_quota():
    url = f"{settings.coingecko_api_base}/global"
    r = _SESSION.get(url, headers=_headers(), timeout=20)
    r.raise_for_status()
    return r.json()

@cached(ttl=60*60, key_fn=lambda : "global", stale_ok=True)  # Увеличено до 60 минут
def global_stats():
    return _global_stats_with_quota()

@budget_guard(units=1)
def _defi_global_with_quota():
    url = f"{settings.coingecko_api_base}/global/decentralized_finance_defi"
    r = _SESSION.get(url, headers=_headers(), timeout=20)
    r.raise_for_status()
    return r.json()

@cached(ttl=60*60, key_fn=lambda : "global_defi", stale_ok=True)  # Увеличено до 60 минут
def defi_global():
    return _defi_global_with_quota()

def top_movers(vs: str = "usd", tf: str = "24h", limit_each: int = 5, top: int = 500):
    """Берём из кэшированного снапшота, чтобы не бить API на каждой кнопке.
    
    Args:
        vs: валюта (usd, eur, etc.)
        tf: таймфрейм (1h, 24h, 7d)
        limit_each: количество топ/флоп для возврата
        top: ограничение по топу (100, 200, 300, 400, 500) - берем топ-N монет по капитализации
    
    Returns:
        Tuple[List[Dict], List[Dict], List[Dict], str]: (coins_for_bubbles, gainers, losers, tf)
        Если API недоступен и кэш пуст, возвращает пустые списки.
    """
    try:
        data = markets_snapshot(vs=vs)
    except Exception as e:
        import logging
        logging.getLogger("alt_forecast.coingecko").error(
            f"Ошибка при получении markets_snapshot: {e}"
        )
        # Возвращаем пустые списки
        return [], [], [], tf
    
    if not data:
        # Если данные пустые, возвращаем пустые списки
        return [], [], [], tf

    # Ограничиваем по топу (universe)
    # markets_snapshot уже возвращает отсортированные по market_cap_desc, так что просто берем первые top
    coins_universe = data[:min(top, len(data))]

    # отфильтруй стейблы, если у тебя есть _is_stable
    try:
        coins = [c for c in coins_universe if not _is_stable(c)]
    except NameError:
        coins = coins_universe

    coins_for_bubbles = coins  # используем все монеты из universe (до count будет ограничено в render)

    def change(c):
        if tf == "1h":
            return float(c.get("price_change_percentage_1h_in_currency") or c.get("price_change_percentage_1h") or 0.0)
        elif tf == "7d":
            return float(c.get("price_change_percentage_7d_in_currency") or c.get("price_change_percentage_7d") or 0.0)
        else:
            return float(c.get("price_change_percentage_24h_in_currency") or c.get("price_change_percentage_24h") or 0.0)

    sorted_by = sorted(coins, key=change, reverse=True)
    gainers = sorted_by[:limit_each]
    losers  = list(reversed(sorted_by))[:limit_each]
    return coins_for_bubbles, gainers, losers, tf


def _headers() -> dict:
    h = {"Accept": "application/json"}
    if settings.coingecko_api_key:
        # На текущих тарифах CoinGecko ключ желателен даже для Demo
        h["x-cg-pro-api-key"] = settings.coingecko_api_key
    return h

def markets_page(vs: str = "usd", page: int = 1, per_page: int = 250) -> List[Dict]:
    """Страница рынка от CoinGecko (по капе). Забираем 1h и 24h изменения."""
    url = f"{settings.coingecko_api_base}/coins/markets"
    params = {
        "vs_currency": vs,
        "order": "market_cap_desc",
        "per_page": per_page,   # 250 — максимум, чтобы сделать один запрос
        "page": page,
        "sparkline": "false",
        "price_change_percentage": "1h,24h",
        "locale": "en",
    }
    r = _SESSION.get(url, params=params, headers=_headers(), timeout=20)
    r.raise_for_status()  # если всё же 429 — уйдём в except наверху
    return r.json()

def _is_stable(c: Dict) -> bool:
    sym = str(c.get("symbol", "")).lower()
    name = str(c.get("name", "")).lower()
    return (sym in STABLE_TICKERS) or ("stable" in name)

def _change(c: Dict, tf: str) -> float:
    if tf == "1h":
        key = "price_change_percentage_1h_in_currency"
        alt = "price_change_percentage_1h"
    else:
        key = "price_change_percentage_24h_in_currency"
        alt = "price_change_percentage_24h"
    val = c.get(key, c.get(alt, 0.0))
    try:
        return float(val)
    except Exception:
        return 0.0

# def top_movers(vs: str = "usd", tf: str = "24h", limit_each: int = 5) -> Tuple[List[Dict], List[Dict], List[Dict], str]:
#     """
#     Возвращает (coins_for_bubbles, top_gainers, top_losers, tf), где tf in {"1h","24h"}.
#     Кэшируем весь набор монет на 60 сек, чтобы не ловить 429 при частых запросах.
#     """
#     key = (vs, "all")  # кэшируем общий список, т.к. из него считаем и 1h и 24h
#     now = time.time()
#     data: List[Dict]
#
#     if key in _CACHE and (now - _CACHE[key][0] < _TTL_SECONDS):
#         data = _CACHE[key][1]
#     else:
#         # один запрос на 250 монет достаточно для витрины/топов
#         data = markets_page(vs=vs, page=1, per_page=250)
#         _CACHE[key] = (now, data)
#
#     # исключаем стейблы
#     coins = [c for c in data if not _is_stable(c)]
#
#     # на схему берём ~50, чтобы было читаемо
#     coins_for_bubbles = coins[:50]
#
#     # сортировка по выбранному таймфрейму
#     sorted_by = sorted(coins, key=lambda c: _change(c, tf), reverse=True)
#     gainers = sorted_by[:limit_each]
#     losers = list(reversed(sorted_by))[:limit_each]
#     return coins_for_bubbles, gainers, losers, tf
