# app/infrastructure/webhook.py
from __future__ import annotations

import hmac
import logging
from typing import Iterable

from fastapi import FastAPI, Request, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel, field_validator
import os

from .db import DB                    # не меняю импорты, как у тебя
from ..config import settings         # pydantic-settings или твой конфиг

app = FastAPI(
    title="Alt Forecast Bot API",
    description="REST API для криптовалютной аналитики и прогнозов",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc"
)
log = logging.getLogger("alt_forecast.api")

_db: DB | None = None

# Разрешённые ТФ и маппинг входящих ключей от TV
TF_MAP = {
    "15": "15m", "15m": "15m",
    "60": "1h",  "1h": "1h",
    "240": "4h", "4h": "4h",
    "D": "1d", "1D": "1d", "1d": "1d", "1440": "1d",
}
ALLOWED_TF = {"15m", "1h", "4h", "1d"}

# Разрешённые метрики — можно переопределить через settings.ALLOWED_METRICS (CSV)
DEFAULT_ALLOWED_METRICS = {"BTC", "USDT.D", "BTC.D", "TOTAL2", "TOTAL3", "ETHBTC"}

def _get_allowed_metrics() -> set[str]:
    val = getattr(settings, "ALLOWED_METRICS", None) or getattr(settings, "allowed_metrics", None)
    if not val:
        return set(DEFAULT_ALLOWED_METRICS)
    if isinstance(val, Iterable) and not isinstance(val, (str, bytes)):
        return {str(x).strip() for x in val if str(x).strip()}
    # CSV-строка
    return {s.strip() for s in str(val).split(",") if s.strip()}

def normalize_tf(tf_in: str) -> str:
    tf_in = (tf_in or "").strip()
    return TF_MAP.get(tf_in, tf_in)

def secret_ok(got: str | None) -> bool:
    expected = (
        getattr(settings, "SECRET_WEBHOOK_TOKEN", None)
        or getattr(settings, "secret_webhook_token", None)
        or ""
    )
    if not expected:
        # секрет не задан — пропускаем (но лучше всё же задать)
        return True
    got = (got or "").strip()
    return hmac.compare_digest(got, str(expected).strip())

class BarIn(BaseModel):
    secret: str | None = None
    metric: str
    timeframe: str
    ts: int       # unix ms или s
    o: float; h: float; l: float; c: float
    v: float | None = None

    @field_validator("metric")
    @classmethod
    def _metric_whitelist(cls, v: str):
        allowed = _get_allowed_metrics()
        if v not in allowed:
            raise ValueError(f"metric '{v}' is not allowed")
        return v

    @field_validator("timeframe")
    @classmethod
    def _tf_norm(cls, v: str):
        tf = normalize_tf(v)
        if tf not in ALLOWED_TF:
            raise ValueError(f"unsupported timeframe '{v}'")
        return tf

    @field_validator("ts")
    @classmethod
    def _ts_ms(cls, v: int):
        # приводим к миллисекундам, если пришли секунды
        if v < 10**12:
            v = v * 1000
        return v

    @field_validator("h")
    @classmethod
    def _ohlc_consistency(cls, h: float, info):
        # базовая проверка консистентности OHLC: l <= min(o,c) <= max(o,c) <= h
        o = info.data.get("o"); l = info.data.get("l"); c = info.data.get("c")
        if o is None or l is None or c is None:
            return h
        lo = min(o, c); hi = max(o, c)
        if not (l <= lo <= hi <= h):
            # не блокируем полностью (некоторые источники присылают равные бары),
            # но выбрасываем 422, потому что это почти всегда мусор
            raise ValueError("inconsistent OHLC values")
        return h

@app.on_event("startup")
def _startup():
    global _db
    db_path = (
        getattr(settings, "DATABASE_PATH", None)
        or getattr(settings, "database_path", None)
        or "/data/data.db"
    )
    _db = DB(db_path)
    log.info("DB initialized at %s", db_path)
    
    # Регистрируем REST API роуты
    try:
        from .rest_api import create_rest_api_router
        create_rest_api_router(app, _db)
        log.info("REST API routes registered")
    except Exception as e:
        log.warning("Failed to register REST API routes: %s", e)
    
    # Статические файлы для веб-интерфейса
    static_dir = os.path.join(os.path.dirname(__file__), "static")
    if os.path.exists(static_dir):
        app.mount("/static", StaticFiles(directory=static_dir), name="static")
        
        @app.get("/", response_class=FileResponse)
        async def root():
            index_path = os.path.join(static_dir, "index.html")
            if os.path.exists(index_path):
                return index_path
            raise HTTPException(status_code=404, detail="Index page not found")
        
        log.info("Static files mounted at /static, root endpoint configured")

@app.post("/webhook")
async def webhook(request: Request):
    if _db is None:
        raise HTTPException(500, detail="DB not initialized")

    # Защита от больших тел (сканеры/ошибки). 10 КБ за глаза.
    try:
        clen = int(request.headers.get("content-length", "0"))
        if clen and clen > 10_000:
            raise HTTPException(status_code=413, detail="payload too large")
    except ValueError:
        pass

    try:
        data = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="invalid json")

    # Проверяем секрет константно-временным сравнением
    if not secret_ok(data.get("secret")):
        raise HTTPException(status_code=401, detail="invalid secret")

    # Валидируем/нормализуем через Pydantic-модель
    try:
        bar = BarIn(**data)
    except Exception as e:
        raise HTTPException(status_code=422, detail=str(e))

    try:
        _db.upsert_bar(bar.metric, bar.timeframe, bar.ts, bar.o, bar.h, bar.l, bar.c, bar.v)
    except Exception as e:
        log.exception("db upsert failed")
        raise HTTPException(status_code=500, detail="db error")

    # Сдержанный лог без секрета/сырого payload
    log.info("ingest ok: metric=%s tf=%s ts=%s c=%.8f", bar.metric, bar.timeframe, bar.ts, bar.c)
    return {"ok": True}

@app.get("/healthz")
async def healthz():
    return {"ok": True}
