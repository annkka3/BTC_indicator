# app/config.py
from __future__ import annotations
import os
from dataclasses import dataclass, field
from typing import Tuple, Optional
from zoneinfo import ZoneInfo  # stdlib, Py3.9+

def _env_bool(name: str, default: bool = False) -> bool:
    v = os.getenv(name)
    if v is None:
        return default
    return str(v).strip().lower() not in ("0", "false", "no", "off", "")

def _env_int(
    name: str,
    default: int,
    *,
    min_value: Optional[int] = None,
    max_value: Optional[int] = None,
) -> int:
    v = os.getenv(name)
    try:
        x = int(v) if v is not None else default
    except Exception:
        x = default
    if min_value is not None:
        x = max(min_value, x)
    if max_value is not None:
        x = min(max_value, x)
    return x

def _env_csv(name: str, default: Tuple[str, ...]) -> Tuple[str, ...]:
    v = os.getenv(name)
    if not v:
        return default
    return tuple(s.strip() for s in v.split(",") if s.strip())

@dataclass
class Settings:
    # Core
    database_path: str = os.getenv("DATABASE_PATH", "/data/data.db")

    # Храним оригинальную строку TZ из окружения;
    # рабочую зону времени отдаём через свойство `tz` (ZoneInfo)
    tz_str: str = os.getenv("TZ", "Europe/Amsterdam")

    # Security / Webhook
    secret_webhook_token: Optional[str] = os.getenv("SECRET_WEBHOOK_TOKEN")
    # Разрешённые метрики для вебхука
    allowed_metrics: Tuple[str, ...] = field(
        default_factory=lambda: _env_csv(
            "ALLOWED_METRICS",
            ("BTC", "USDT.D", "BTC.D", "TOTAL2", "TOTAL3", "ETHBTC"),
        )
    )
    # Символ BTC в TradingView (если используешь pine-шаблон)
    tv_btc_symbol: str = os.getenv("TV_BTC_SYMBOL", "BINANCE:BTCUSDT")

    # Telegram
    telegram_bot_token: Optional[str] = os.getenv("TELEGRAM_BOT_TOKEN")
    admin_chat_id: Optional[str] = os.getenv("ADMIN_CHAT_ID")  # str; ниже удобное свойство int
    report_interval_min: int = _env_int("REPORT_INTERVAL_MIN", 15, min_value=5, max_value=360)

    # Logging
    log_level: str = os.getenv("LOG_LEVEL", "INFO")

    # Collector: внешние API и частоты
    binance_api_base: str = os.getenv("BINANCE_API_BASE", "https://api.binance.com")
    coingecko_api_base: str = os.getenv("COINGECKO_API_BASE", "https://api.coingecko.com/api/v3")
    coingecko_api_key: Optional[str] = os.getenv("COINGECKO_API_KEY")
    coinglass_api_key: Optional[str] = os.getenv("COINGLASS_API_KEY")

    enable_tv: bool = _env_bool("ENABLE_TV", True)
    tv_user: Optional[str] = os.getenv("TV_USER")
    tv_pass: Optional[str] = os.getenv("TV_PASS")
    tv_poll_min: int = _env_int("TV_POLL_MIN", 10, min_value=1, max_value=360)

    binance_min_period_sec: int = _env_int("BINANCE_MIN_PERIOD_SEC", 5, min_value=1, max_value=60)
    gecko_min_period_sec: int   = _env_int("GECKO_MIN_PERIOD_SEC", 60, min_value=30, max_value=600)

    # Удобные derived-свойства
    @property
    def admin_chat_id_int(self) -> Optional[int]:
        try:
            return int(self.admin_chat_id) if self.admin_chat_id else None
        except Exception:
            return None

    @property
    def tz(self) -> ZoneInfo:
        # Если переменная окружения поменяется в рантайме — можно перечитать self.tz_str и вернуть актуальную зону.
        try:
            return ZoneInfo(self.tz_str)
        except Exception:
            # Фоллбек, если указана неверная зона
            return ZoneInfo("UTC")

# Единый экземпляр
settings = Settings()
