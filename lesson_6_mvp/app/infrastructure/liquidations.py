# app/infrastructure/liquidations.py
import time
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

_sess = requests.Session()
_sess.mount("https://", HTTPAdapter(max_retries=Retry(
    total=2, backoff_factor=0.5, status_forcelist=(429, 500, 502, 503, 504), allowed_methods=frozenset(["GET"])
)))

BYBIT  = "https://api.bybit.com"
BYTICK = "https://api.bytick.com"

def _now_ms() -> int:
    # небольшой отступ от "прямо сейчас", чтобы endTime не попадал в будущее даже при расхождении часов
    return int(time.time() * 1000) - 2000

def _clamp_range_ms(end_ms: int, span_ms: int, max_span_ms: int = 7*24*3600*1000) -> tuple[int,int]:
    end_ms = min(end_ms, _now_ms())
    span_ms = min(span_ms, max_span_ms)
    start_ms = max(0, end_ms - span_ms)
    return start_ms, end_ms

def _req_liqs(host: str, category: str, symbol: str, start_ms: int, end_ms: int, limit: int = 200) -> dict:
    url = f"{host}/v5/market/liquidation"
    params = dict(category=category, symbol=symbol, startTime=start_ms, endTime=end_ms, limit=limit)
    r = _sess.get(url, params=params, timeout=15)
    if r.status_code == 404:
        # у Bybit 404 часто = "пусто" — не бросаем исключение
        return {"retCode": 10000, "result": {"list": []}}
    r.raise_for_status()
    return r.json()

def bybit_liqs_any(base: str = "BTC", *, minutes: int = 120, limit: int = 200) -> tuple[float, float, int, str, bool]:
    """
    Возвращает (long_usd, short_usd, count, symbol_used, ok).
    Порядок попыток: linear (USDT) → inverse (USD), хосты: bybit → byt ick.
    Если окно пустое — идём назад ступенями (по 30 мин) до 12 часов.
    """
    base = (base or "BTC").upper().strip()
    end_ms = _now_ms()
    span_ms = max(1, int(minutes)) * 60 * 1000
    start_ms, end_ms = _clamp_range_ms(end_ms, span_ms)

    # кандидаты по категории/символу
    candidates: list[tuple[str,str]] = []
    if base.endswith("USDT"):
        candidates.append(("linear", base))
        candidates.append(("inverse", base.replace("USDT", "USD")))
    elif base.endswith("USD"):
        candidates.append(("inverse", base))
        candidates.append(("linear", base.replace("USD", "USDT")))
    else:
        candidates.append(("linear", f"{base}USDT"))
        candidates.append(("inverse", f"{base}USD"))

    hosts = (BYBIT, BYTICK)

    # попробуем шагами назад: 0 → -30 → -60 … до -12h
    step_ms = 30 * 60 * 1000
    max_back = 12 * 60 * 60 * 1000
    back = 0

    last_symbol = base
    while back <= max_back:
        s, e = _clamp_range_ms(end_ms - back, span_ms)
        for category, symbol in candidates:
            last_symbol = symbol
            total_long = total_short = 0.0
            count = 0
            for host in hosts:
                try:
                    data = _req_liqs(host, category, symbol, s, e, limit)
                    arr = (((data or {}).get("result") or {}).get("list") or [])
                    for it in arr:
                        side = str(it.get("side") or it.get("position") or "").lower()
                        qty_usd = float(it.get("value", 0) or it.get("qty", 0) or 0)
                        if side.startswith("buy") or side == "long":
                            total_long += qty_usd
                        elif side.startswith("sell") or side == "short":
                            total_short += qty_usd
                        count += 1
                    if count > 0 or (total_long + total_short) > 0:
                        return float(total_long), float(total_short), int(count), symbol, True
                except requests.HTTPError:
                    # помолчать: 4xx/5xx на одном хосте не критичен
                    continue
                except Exception:
                    continue
        back += step_ms

    return 0.0, 0.0, 0, last_symbol, False
