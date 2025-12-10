
# app/infrastructure/binance_options.py
from __future__ import annotations

import os
import re
import time
import logging
from typing import Any, Dict, Optional

import requests
from requests import Response, HTTPError, RequestException

__all__ = ["notional_by_expiry"]

log = logging.getLogger("alt_forecast.binance_options")

BINANCE_EAPI_BASE = os.getenv("BINANCE_EAPI_BASE", "https://eapi.binance.com")
BINANCE_EAPI_PATH = "/eapi/v1/openInterest"
DEFAULT_TIMEOUT = float(os.getenv("BINANCE_EAPI_TIMEOUT_SEC", "15"))
MAX_RETRIES = int(os.getenv("BINANCE_EAPI_MAX_RETRIES", "3"))

_YM_RE = re.compile(r"^\d{6}$")  # YYMMDD


def _headers() -> Dict[str, str]:
    return {
        "accept": "application/json",
        "user-agent": "alt-forecast-bot/1.0 (+binance-options)"
    }


def _to_float(v: Any) -> Optional[float]:
    try:
        f = float(v)
        if f != f:  # NaN
            return None
        return f
    except Exception:
        return None


def _request_with_retries(url: str, params: Dict[str, Any]) -> Response:
    """
    Простые ретраи с экспоненциальным бэкоффом и уважением Retry-After для 429.
    """
    backoff = 1.0
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = requests.get(url, params=params, headers=_headers(), timeout=DEFAULT_TIMEOUT)
            if resp.status_code == 429:
                ra = resp.headers.get("Retry-After")
                sleep_for = _to_float(ra) or backoff
                log.warning("Binance EAPI 429 Retry-After=%s; sleep %.1fs (attempt %d/%d)",
                            ra, sleep_for, attempt, MAX_RETRIES)
                time.sleep(min(max(0.5, sleep_for), 10.0))
                backoff = min(backoff * 2, 8.0)
                continue
            resp.raise_for_status()
            return resp
        except HTTPError as e:
            code = getattr(e.response, "status_code", 0)
            if 500 <= code < 600 and attempt < MAX_RETRIES:
                log.warning("Binance EAPI %s, retry in %.1fs (attempt %d/%d)",
                            code, backoff, attempt, MAX_RETRIES)
                time.sleep(backoff)
                backoff = min(backoff * 2, 8.0)
                continue
            log.exception("Binance EAPI HTTP error: %s", code)
            raise
        except RequestException:
            if attempt < MAX_RETRIES:
                log.warning("Binance EAPI network error, retry in %.1fs (attempt %d/%d)",
                            backoff, attempt, MAX_RETRIES)
                time.sleep(backoff)
                backoff = min(backoff * 2, 8.0)
                continue
            log.exception("Binance EAPI network error, giving up")
            raise
    raise RuntimeError("unreachable")


def notional_by_expiry(underlying: str, yymmdd: str) -> float | None:
    """
    Возвращает суммарный notional OI (USD) по опционным экспирациям Binance для базового актива.
      underlying: 'BTC' | 'ETH'
      yymmdd: строка вида 'YYMMDD', например '250912'
    При ошибке парсинга/сети — None.
    """
    if not underlying:
        return None
    underlying = underlying.upper().strip()

    if not _YM_RE.match(yymmdd or ""):
        log.warning("Invalid yymmdd format: %r", yymmdd)
        return None

    url = f"{BINANCE_EAPI_BASE.rstrip('/')}{BINANCE_EAPI_PATH}"
    params = {"underlyingAsset": underlying, "expiration": yymmdd}

    try:
        resp = _request_with_retries(url, params)
        j = resp.json()
    except Exception:
        log.exception("Binance EAPI parse/request failure")
        return None

    # возможные поля по разным версиям API
    candidates = (
        j.get("notional"),
        j.get("totalNotional"),
        j.get("sumOpenInterestUsd"),
        # иногда структура приходит как {"data": {...}}
        (j.get("data") or {}).get("notional") if isinstance(j.get("data"), dict) else None,
        (j.get("data") or {}).get("totalNotional") if isinstance(j.get("data"), dict) else None,
        (j.get("data") or {}).get("sumOpenInterestUsd") if isinstance(j.get("data"), dict) else None,
    )

    for val in candidates:
        f = _to_float(val)
        if f is not None:
            return f

    log.warning("Binance EAPI: no usable notional field in response keys=%s", list(j.keys()))
    return None
