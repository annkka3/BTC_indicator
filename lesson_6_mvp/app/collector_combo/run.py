# app/collector_combo/run.py
from __future__ import annotations
import os, time, math, threading, logging
from collections import defaultdict, deque
from typing import Dict, Deque, Tuple, List, Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# опционально: tvdatafeed (если нет — fallback будет всегда)
try:
    import pandas as pd
    try:
        from tvDatafeed import TvDatafeed, Interval
    except ImportError:
        from tvdatafeed import TvDatafeed, Interval
    HAS_TV = True
except Exception:
    HAS_TV = False
    pd = None  # type: ignore

from app.infrastructure.db import DB

# -------- конфиг --------

DB_PATH = os.getenv("DATABASE_PATH", "/data/data.db")

BINANCE = os.getenv("BINANCE_API_BASE", "https://api.binance.com")
COINGECKO = os.getenv("COINGECKO_API_BASE", "https://api.coingecko.com/api/v3")
COINGECKO_API_KEY = os.getenv("COINGECKO_API_KEY", "").strip()  # опционально

ENABLE_TV = os.getenv("ENABLE_TV", "1") not in ("0", "false", "False")
TV_POLL_MIN = int(os.getenv("TV_POLL_MIN", "10"))

# Ограничения частоты (перестраховка, чтобы не ловить 429)
BINANCE_MIN_PERIOD_SEC = int(os.getenv("BINANCE_MIN_PERIOD_SEC", "5"))
GECKO_MIN_PERIOD_SEC   = int(os.getenv("GECKO_MIN_PERIOD_SEC", "60"))

# метрики/символы
CRYPTOCAP = [
    ("CRYPTOCAP", "USDT.D", "USDT.D"),
    ("CRYPTOCAP", "BTC.D",  "BTC.D"),
    ("CRYPTOCAP", "TOTAL2", "TOTAL2"),
    ("CRYPTOCAP", "TOTAL3", "TOTAL3"),
]
EXTRA = [
    ("BINANCE", "BTCUSDT", "BTC"),
    ("BINANCE", "ETHBTC",  "ETHBTC"),
    ("BINANCE", "ETHUSDT", "ETH"),
    ("BINANCE", "SOLUSDT", "SOL"),
    ("BINANCE", "XRPUSDT", "XRP"),
    ("BINANCE", "ENAUSDT", "ENA"),
    ("BINANCE", "BNBUSDT", "BNB"),
    ("BINANCE", "WIFUSDT", "WIF"),
    ("BINANCE", "PENGUUSDT", "PENGU"),
    ("BINANCE", "FARTCOINUSDT", "FART"),  # FART -> FARTCOINUSDT на Binance
]

INTERVALS = {
    "15m": ("15m", 15 * 60_000),
    "1h":  ("1h",  60 * 60_000),
    "4h":  ("4h",  4 * 60 * 60_000),
    "1d":  ("1d",  24 * 60 * 60_000),
}

BINANCE_INTERVAL = {"15m": "15m", "1h": "1h", "4h": "4h", "1d": "1d"}

# -------- логгер и HTTP-сессии с ретраями --------

log = logging.getLogger("alt_forecast.collector")
logging.basicConfig(level=logging.INFO)

def _session_with_retries(total=5, backoff=0.3) -> requests.Session:
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
    s.headers.update({"User-Agent": "alt-forecast-bot/1.0 (+collector)"})
    return s

http = _session_with_retries()

# -------- состояние --------

values_lock = threading.Lock()
# держим минутные точки (ts_ms, value) для агрегации в OHLC
values: Dict[str, Deque[Tuple[int, float]]] = defaultdict(lambda: deque(maxlen=24 * 60 + 10))  # ~сутки минуток

db = DB(DB_PATH)

def now_ms() -> int:
    return int(time.time() * 1000)

def floor_ts(ts_ms: int, tf_ms: int) -> int:
    return ts_ms - (ts_ms % tf_ms)

# -------- вставка OHLC из точек --------

def upsert_bar_from_points(metric: str, tf: str, points: List[Tuple[int, float]]) -> Optional[Tuple[str, str, int, float, float, float, float, None]]:
    if not points:
        return None
    ts_close = floor_ts(points[-1][0], INTERVALS[tf][1])
    o = points[0][1]
    h = max(v for _, v in points)
    l = min(v for _, v in points)
    c = points[-1][1]
    return (metric, tf, ts_close, o, h, l, c, None)

# -------- источники --------

def binance_klines(symbol: str, interval: str, limit=2):
    r = http.get(
        f"{BINANCE}/api/v3/klines",
        params={"symbol": symbol, "interval": interval, "limit": limit},
        timeout=15,
    )
    r.raise_for_status()
    return r.json()

def gecko_global_and_caps() -> dict[str, float]:
    headers = {}
    if COINGECKO_API_KEY:
        headers["x-cg-pro-api-key"] = COINGECKO_API_KEY
    # TOTAL
    rg = http.get(f"{COINGECKO}/global", headers=headers, timeout=15)
    rg.raise_for_status()
    g = rg.json()["data"]
    total_usd = float(g["total_market_cap"]["usd"])
    # market caps (минимальный набор)
    rm = http.get(
        f"{COINGECKO}/coins/markets",
        params={"vs_currency": "usd", "ids": "bitcoin,ethereum,tether", "per_page": 3, "page": 1},
        headers=headers,
        timeout=15,
    )
    rm.raise_for_status()
    m = rm.json()
    caps = {i["id"]: float(i["market_cap"]) for i in m}
    btc = caps.get("bitcoin", 0.0); eth = caps.get("ethereum", 0.0); usdt = caps.get("tether", 0.0)
    out = {}
    out["TOTAL"]  = total_usd
    out["BTC.D"]  = (btc / total_usd * 100.0) if total_usd > 0 else 0.0
    out["USDT.D"] = (usdt / total_usd * 100.0) if total_usd > 0 else 0.0
    out["TOTAL2"] = max(total_usd - btc, 0.0)
    out["TOTAL3"] = max(total_usd - btc - eth, 0.0)
    return out

# -------- 1) Минутный сборщик (fallback) --------

def sampler_minutely():
    """
    Каждую минуту обновляем минутные значения CRYPTOCAP (CoinGecko) и close BTC/ETHBTC (Binance).
    Для биржи используем closeTime kline — это лучше синхронизирует окна.
    """
    last_binance_fetch = 0.0
    last_gecko_fetch = 0.0

    while True:
        t0 = time.time()

        # Binance — забираем последние 1-2 свечи 1m, чтобы поймать close и не пропустить минуту
        try:
            if t0 - last_binance_fetch >= BINANCE_MIN_PERIOD_SEC:
                # Список пар для сбора данных через Binance API
                binance_pairs = [
                    ("BTCUSDT", "BTC"),
                    ("ETHBTC", "ETHBTC"),
                    ("ETHUSDT", "ETH"),
                    ("SOLUSDT", "SOL"),
                    ("XRPUSDT", "XRP"),
                    ("ENAUSDT", "ENA"),
                    ("BNBUSDT", "BNB"),
                    ("WIFUSDT", "WIF"),
                    ("PENGUUSDT", "PENGU"),
                    ("FARTCOINUSDT", "FART"),  # FART -> FARTCOINUSDT на Binance
                ]
                for sym, metric in binance_pairs:
                    try:
                        kl = binance_klines(sym, "1m", limit=2)
                        if kl:
                            # Каждая kline: [openTime, o, h, l, c, v, closeTime, ...]
                            ot, o, h, l, c, v, ct = kl[-1][0], float(kl[-1][1]), float(kl[-1][2]), float(kl[-1][3]), float(kl[-1][4]), float(kl[-1][5]), kl[-1][6]
                            # используем closeTime как ts точки
                            with values_lock:
                                values[metric].append((int(ct), float(c)))
                    except Exception as e:
                        # Логируем ошибку для конкретной пары, но продолжаем с другими
                        log.debug(f"[sampler] binance error for {sym}: {e}")
                last_binance_fetch = t0
        except Exception as e:
            log.warning("[sampler] binance error: %s", e)

        # CoinGecko — одноминутный опрос
        try:
            if t0 - last_gecko_fetch >= GECKO_MIN_PERIOD_SEC:
                g = gecko_global_and_caps()
                ts = now_ms()
                with values_lock:
                    for metric, val in g.items():
                        values[metric].append((ts, float(val)))
                last_gecko_fetch = t0
        except Exception as e:
            log.warning("[sampler] gecko error: %s", e)

        # доспим аккуратно до ближайшей границы минуты
        sleep_left = 60 - (time.time() % 60)
        time.sleep(max(0.45, min(5.0, sleep_left)))

# -------- 2) Флашер окон в OHLC --------

def flusher():
    """
    Каждые 5 сек пытаемся закрывать окна 15m/1h/4h/1d и писать OHLC в БД.
    Пишем батчами и идемпотентно.
    """
    last_written: dict[tuple[str, str], int] = {}
    tfs = list(INTERVALS.items())
    while True:
        try:
            ts = now_ms()
            batch: List[Tuple[str, str, int, float, float, float, float, None]] = []
            with values_lock:
                # копия ссылок, чтобы минимизировать время локов
                for metric, dq in list(values.items()):
                    if not dq:
                        continue
                    for tf, (_, tf_ms) in tfs:
                        ts_close = floor_ts(ts, tf_ms)
                        key = (metric, tf)
                        if last_written.get(key) == ts_close:
                            continue
                        # окно (ts_close - tf, ts_close]
                        win = [(t, v) for (t, v) in dq if (ts_close - tf_ms) < t <= ts_close]
                        item = upsert_bar_from_points(metric, tf, win)
                        if item:
                            batch.append(item)
                            last_written[key] = ts_close
            if batch:
                # быстрее одной транзакцией
                with db.atomic():
                    db.upsert_many_bars(batch)
                log.info("[flush] wrote %d bars", len(batch))
        except Exception:
            log.exception("[flush] error")
        time.sleep(5)

# -------- 3) TradingView fetcher (если доступен) --------

def tv_fetcher():
    if not (HAS_TV and ENABLE_TV):
        log.info("[tv] tvdatafeed disabled (HAS_TV=%s, ENABLE_TV=%s)", HAS_TV, ENABLE_TV)
        return

    user = os.getenv("TV_USER") or None
    pwd  = os.getenv("TV_PASS") or None
    tv = TvDatafeed(user, pwd)  # без логина часто работает

    def _interval_for(tf: str):
        return {
            "15m": Interval.in_15_minute,
            "1h":  Interval.in_1_hour,
            "4h":  Interval.in_4_hour,
            "1d":  Interval.in_daily,
        }[tf]

    # для отсеивания дублей
    seen: set[tuple[str, str, int]] = set()

    while True:
        try:
            batch: List[Tuple[str, str, int, float, float, float, float, Optional[float]]] = []

            # CRYPTOCAP
            for exch, symbol, metric in CRYPTOCAP:
                for tf in ("15m", "1h", "4h", "1d"):
                    try:
                        df = tv.get_hist(symbol=symbol, exchange=exch, interval=_interval_for(tf), n_bars=300)
                        if df is None or df.empty:
                            continue
                        # батчим вставки
                        rows = []
                        for ts, row in df.iterrows():
                            ts_ms = int(ts.value // 1_000_000)
                            key = (metric, tf, ts_ms)
                            if key in seen:
                                continue
                            seen.add(key)
                            o = float(row["open"]); h = float(row["high"]); l = float(row["low"]); c = float(row["close"])
                            v = float(row["volume"]) if "volume" in row and pd is not None and pd.notna(row["volume"]) else None
                            rows.append((metric, tf, ts_ms, o, h, l, c, v))
                        if rows:
                            batch.extend(rows)
                            log.info("[tv] %s %s: +%d", metric, tf, len(rows))
                    except Exception as e:
                        log.warning("[tv] error %s %s: %s", metric, tf, e)

            # Пары (дублирует Binance, но может быть полезно)
            for exch, symbol, metric in EXTRA:
                for tf in ("15m", "1h", "4h", "1d"):
                    try:
                        df = tv.get_hist(symbol=symbol, exchange=exch, interval=_interval_for(tf), n_bars=300)
                        if df is None or df.empty:
                            continue
                        rows = []
                        for ts, row in df.iterrows():
                            ts_ms = int(ts.value // 1_000_000)
                            key = (metric, tf, ts_ms)
                            if key in seen:
                                continue
                            seen.add(key)
                            o = float(row["open"]); h = float(row["high"]); l = float(row["low"]); c = float(row["close"])
                            v = float(row["volume"]) if "volume" in row and pd is not None and pd.notna(row["volume"]) else None
                            rows.append((metric, tf, ts_ms, o, h, l, c, v))
                        if rows:
                            batch.extend(rows)
                            log.info("[tv] %s %s: +%d", metric, tf, len(rows))
                    except Exception as e:
                        log.warning("[tv] error %s %s: %s", metric, tf, e)

            if batch:
                with db.atomic():
                    db.upsert_many_bars(batch)
                log.info("[tv] wrote %d bars total", len(batch))

        except Exception:
            log.exception("[tv] outer loop error")

        # спим и пробуем ещё
        time.sleep(max(60, TV_POLL_MIN * 60))

# -------- main --------

def main():
    t1 = threading.Thread(target=sampler_minutely, daemon=True, name="sampler_minutely")
    t2 = threading.Thread(target=flusher, daemon=True, name="flusher")
    t1.start(); t2.start()

    # поток TV отдельно (если доступен)
    if HAS_TV and ENABLE_TV:
        t3 = threading.Thread(target=tv_fetcher, daemon=True, name="tv_fetcher")
        t3.start()

    # держим процесс
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        log.info("collector stopped")

if __name__ == "__main__":
    main()
