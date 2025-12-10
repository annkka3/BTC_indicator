# app/infrastructure/deribit_options.py
from __future__ import annotations

import os
import re
import time
import logging
from dataclasses import dataclass
from typing import List, Dict, Optional, Any, Iterable

import requests
from requests import Response, HTTPError, RequestException
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

__all__ = ["OptionOI", "fetch_chain", "get_index_price", "build_series"]

log = logging.getLogger("alt_forecast.deribit")

DERIBIT_BASE = os.getenv("DERIBIT_API_BASE", "https://www.deribit.com/api/v2")
DEFAULT_TIMEOUT = float(os.getenv("DERIBIT_TIMEOUT_SEC", "20"))
MAX_RETRIES = int(os.getenv("DERIBIT_MAX_RETRIES", "3"))

@dataclass
class OptionOI:
    expiry: str     # 'YYYY-MM-DD'
    strike: float
    kind: str       # 'C' or 'P'
    oi: float       # contracts (1 contract = 1 BTC/ETH on Deribit inverse options)

# Примеры имён: BTC-27SEP24-60000-C
_NAME_RE = re.compile(r"^(BTC|ETH)-(\d{1,2}[A-Z]{3}\d{2})-(\d+(?:\.\d+)*)-([CP])$")
_MONTHS = {
    'JAN':'01','FEB':'02','MAR':'03','APR':'04','MAY':'05','JUN':'06',
    'JUL':'07','AUG':'08','SEP':'09','OCT':'10','NOV':'11','DEC':'12'
}

def _session_with_retries(total: int = MAX_RETRIES, backoff: float = 0.4) -> requests.Session:
    s = requests.Session()
    retry = Retry(
        total=total,
        backoff_factor=backoff,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset(["GET"])
    )
    adapter = HTTPAdapter(max_retries=retry, pool_connections=10, pool_maxsize=10)
    s.mount("https://", adapter)
    s.mount("http://", adapter)
    s.headers.update({"User-Agent": "alt-forecast-bot/1.0 (+deribit)"})
    return s

_http = _session_with_retries()

def _json(resp: Response) -> Any:
    try:
        return resp.json()
    except Exception as e:
        log.exception("Deribit JSON parse failed")
        raise RuntimeError("Deribit JSON parse failed") from e

def _dmmmYY_to_iso(token: str) -> Optional[str]:
    """
    '27SEP24' -> '2024-09-27'
    """
    m = re.match(r"(\d{1,2})([A-Z]{3})(\d{2})", token or "")
    if not m:
        return None
    day, mon, yy = m.group(1), m.group(2).upper(), m.group(3)
    mm = _MONTHS.get(mon)
    if not mm:
        return None
    return f"20{yy}-{mm}-{int(day):02d}"

def _get(path: str, params: Dict[str, Any]) -> Any:
    url = f"{DERIBIT_BASE.rstrip('/')}/{path.lstrip('/')}"
    resp = _http.get(url, params=params, timeout=DEFAULT_TIMEOUT)
    resp.raise_for_status()
    return _json(resp)

def _validate_ccy(currency: str) -> str:
    c = (currency or "").upper().strip()
    if c not in ("BTC", "ETH"):
        raise ValueError(f"Unsupported currency: {currency!r}")
    return c

def fetch_chain(currency: str) -> List[OptionOI]:
    """
    Вся сводка опционных инструментов Deribit для BTC/ETH (public).
    Возвращает список OptionOI. Пропускает инструменты, имя которых не парсится.
    """
    ccy = _validate_ccy(currency)
    j = _get("public/get_book_summary_by_currency", {"currency": ccy, "kind": "option"})

    result = j.get("result")
    if not isinstance(result, list):
        raise RuntimeError("Deribit: unexpected payload (no result list)")

    out: List[OptionOI] = []
    for it in result:
        name = it.get("instrument_name") or ""
        m = _NAME_RE.match(name)
        if not m:
            continue
        _, dmmmYY, strike, kind = m.groups()
        expiry = _dmmmYY_to_iso(dmmmYY)
        if not expiry:
            continue
        try:
            oi_raw = it.get("open_interest", 0.0)
            oi = float(oi_raw) if oi_raw is not None else 0.0
            out.append(OptionOI(expiry=expiry, strike=float(strike), kind=kind, oi=oi))
        except Exception:
            # пропустим странные строки
            continue
    return out

def get_index_price(currency: str) -> float:
    """USD-цена базового актива (для перевода контрактов в USD-нотационал)."""
    ccy = _validate_ccy(currency)
    idx = "btc_usd" if ccy == "BTC" else "eth_usd"
    j = _get("public/get_index_price", {"index_name": idx})
    try:
        return float(j["result"]["index_price"])
    except Exception as e:
        raise RuntimeError("Deribit: missing index_price") from e

def _max_pain_for_expiry(rows: List[OptionOI]) -> float:
    """
    Максимальная боль по одной дате: перебираем страйки и считаем суммарные выплаты.
    Сложность O(N^2) приемлема (N по страйкам в рамках одной экспирации).
    """
    strikes = sorted({x.strike for x in rows})
    if not strikes:
        return float("nan")
    by: Dict[float, Dict[str, float]] = {s: {"C": 0.0, "P": 0.0} for s in strikes}
    for x in rows:
        # защитимся от неожиданных kind
        k = "C" if x.kind == "C" else ("P" if x.kind == "P" else None)
        if not k:
            continue
        by[x.strike][k] += max(0.0, float(x.oi))

    def pain(price: float) -> float:
        total = 0.0
        for k, v in by.items():
            total += v["C"] * max(price - k, 0.0) + v["P"] * max(k - price, 0.0)
        return total

    # минимизируем «боль» по дискретному множеству страйков
    best = min(strikes, key=pain)
    return float(best)

def build_series(currency: str, max_expiries: int = 10) -> List[Dict]:
    """
    Серия по ближайшим экспирациям:
    [{'date':'YYYY-MM-DD','max_pain':112000.0,'deribit_notional_usd':7.8e9}, ...]
    """
    chain = fetch_chain(currency)
    if not chain:
        return []

    expiries = sorted({x.expiry for x in chain})[:max(1, int(max_expiries))]
    px = get_index_price(currency)

    points: List[Dict] = []
    for exp in expiries:
        rows = [x for x in chain if x.expiry == exp]
        if not rows:
            continue
        mp = _max_pain_for_expiry(rows)
        if mp != mp:  # NaN check
            continue
        calls = sum(max(0.0, x.oi) for x in rows if x.kind == "C")
        puts  = sum(max(0.0, x.oi) for x in rows if x.kind == "P")
        # 1 контракт = 1 BTC/ETH -> в USD по индексу
        deribit_usd = (calls + puts) * float(px)
        points.append({
            "date": exp,
            "max_pain": float(mp),
            "deribit_notional_usd": float(deribit_usd),
        })
    return points
