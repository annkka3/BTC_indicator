# app/infrastructure/telegram_bot.py

from __future__ import annotations
import re
from datetime import datetime, time as dtime, timedelta
try:
    from zoneinfo import ZoneInfo
    from ..config import settings
    _TZ = getattr(settings, "tz", None)  # если в settings.tz уже ZoneInfo — ок
except Exception:
    _TZ = None
import os
import asyncio
import logging
import time
import inspect
import io
import html
import httpx
import aiohttp
import numpy as np
import pandas as pd
from io import BytesIO

from telegram import Update, InputFile, InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto, BotCommand
from telegram.constants import ParseMode
from telegram.error import TimedOut, NetworkError, RetryAfter, Forbidden, BadRequest
from telegram.ext import Application, CommandHandler, ContextTypes, CallbackQueryHandler, MessageHandler, filters
from telegram.request import HTTPXRequest

from .indices_service import IndicesService
from .instructions import INSTRUCTION_HTML, HELP_SHORT_HTML, HELP_FULL_HTML
from .ui_keyboards import build_kb, DEFAULT_TF, get_main_reply_keyboard
from .ui_router import UIRouter
from ..config import settings
from ..infrastructure.db import DB
from ..usecases.generate_report import (
    build_full_report,           # полный отчёт (часовой и по /full)
    build_status_report,         # краткий отчёт (каждые N минут и по /status)
    METRICS,
)
from ..domain.services import (
    trend_arrow_metric,          # метрико-специфичный порог
    indicator_divergences,
    pair_divergences,
    risk_score,
)

from ..lib.series import get_closes        # единый источник клоузов (oldest→newest)
from .widgets import gen_altseason_png


logger = logging.getLogger("alt_forecast.bot")

MAX_TG_LEN = 4096
SEND_DELAY_SEC = 0.05


# Храним активный TF в user_data
TF_KEY = "ui_tf"
DEFAULT_TF = "1h"

def _have_coinglass() -> bool:
    return bool(
        os.getenv("COINGLASS_API_KEY")
        or os.getenv("COINGLASS_SECRET")
        or getattr(settings, "coinglass_api_key", "")
    )


def _ts_sec(ts) -> int:
    """Нормализуем таймстемп к секундам (sec / ms / ns → sec)."""
    t = float(ts)
    if t > 1e14:      # ns
        t /= 1e9
    elif t > 1e12:    # ms
        t /= 1e3
    return int(t)

# ==== utils for /fng, /ticker, /global ====

# компактное форматирование больших сумм (с суффиксами)
def _fmt_money(v: float, cur: str = "USD") -> str:
    try:
        v = float(v or 0)
    except Exception:
        return f"— {cur}"
    # префикс-символы для популярных валют
    SIGNS = {
        "USD": "$", "EUR": "€", "GBP": "£", "RUB": "₽", "UAH": "₴", "KZT": "₸",
        "TRY": "₺", "JPY": "¥", "CNY": "¥", "KRW": "₩", "AUD": "A$", "CAD": "C$",
    }
    sign = SIGNS.get(cur.upper(), f"{cur.upper()} ")
    for s, p in (("T", 1e12), ("B", 1e9), ("M", 1e6)):
        if v >= p:
            return f"{sign}{v/p:,.2f}{s}".replace(",", " ")
    return f"{sign}{v:,.0f}".replace(",", " ")

# мини-спарклайн по значениям (0..100 ок, но работает с любыми)
_SPARK = "▁▂▃▄▅▆▇█"
def _sparkline(values):
    try:
        vals = [float(x) for x in values if x is not None]
    except Exception:
        vals = []
    if not vals:
        return ""
    lo, hi = min(vals), max(vals)
    if lo == hi:
        return _SPARK[0] * len(vals)
    out = []
    rng = (hi - lo) or 1.0
    for x in vals:
        i = int((x - lo) / rng * (len(_SPARK) - 1))
        out.append(_SPARK[max(0, min(i, len(_SPARK) - 1))])
    return "".join(out)

def _ago_or_in(seconds: int | float | None) -> str:
    try:
        s = int(seconds or 0)
    except Exception:
        s = 0
    if s >= 0:
        m, s = divmod(s, 60)
        h, m = divmod(m, 60)
        return f"обновится через {h:d}ч {m:02d}м"
    s = -s
    m, s = divmod(s, 60)
    h, m = divmod(m, 60)
    return f"обновлено {h:d}ч {m:02d}м назад"


class TeleBot:
    def __init__(self):
        token = getattr(settings, "telegram_bot_token", None)
        if not token:
            raise RuntimeError("TELEGRAM_BOT_TOKEN is required for worker")

        self.db = DB()
        self._global_last = None
        
        # Инициализируем систему квот CoinGecko
        from .quota import init_quota_db
        init_quota_db(self.db)
        
        # Инициализируем CommandIntegrator для новой архитектуры
        try:
            from ..presentation.integration.command_integrator import CommandIntegrator
            self.integrator = CommandIntegrator(self.db)
            logger.info("CommandIntegrator initialized successfully")
        except Exception as e:
            logger.warning("Failed to initialize CommandIntegrator: %s", e)
            self.integrator = None
        
        # Инициализируем UIRouter с интегратором и БД
        self.ui = UIRouter(integrator=self.integrator, db=self.db)
        self.http_session = None
        self.indices = IndicesService(self.http_session)
        self._forecast_cache = {}  # key -> (ts, result)
        self._forecast_cache_ttl = 20 * 60  # 20 минут

        # каждые 15 минут обновляем кэш для базового набора
        try:
            self.scheduler.add_job(self._refresh_forecast_cache, "interval", minutes=15, id="forecast_cache",
                                   replace_existing=True)
        except Exception:
            pass

        # ── HTTPX/HTTPXRequest совместимость по версиям PTB ─────────────────────
        connect_to = float(os.getenv("TG_CONNECT_TIMEOUT", "10"))   # сек
        read_to    = float(os.getenv("TG_READ_TIMEOUT", "45"))      # сек
        write_to   = float(os.getenv("TG_WRITE_TIMEOUT", "45"))     # сек
        pool_to    = float(os.getenv("TG_POOL_TIMEOUT", "45"))      # сек
        proxy_url  = os.getenv("HTTPS_PROXY") or os.getenv("HTTP_PROXY")  # http/https/socks5://...

        timeout = httpx.Timeout(connect=connect_to, read=read_to, write=write_to, pool=pool_to)

        request = None
        try:
            sig = inspect.signature(HTTPXRequest.__init__)
            params = set(sig.parameters.keys())

            # Вариант 1: старая сигнатура с индивидуальными таймаутами + proxy_url
            if {"connect_timeout", "read_timeout", "write_timeout", "pool_timeout"}.issubset(params):
                kwargs = dict(
                    connect_timeout=connect_to,
                    read_timeout=read_to,
                    write_timeout=write_to,
                    pool_timeout=pool_to,
                )
                if "proxy_url" in params and proxy_url:
                    kwargs["proxy_url"] = proxy_url
                request = HTTPXRequest(**kwargs)

            # Вариант 2: более новая сигнатура с единым 'timeout'
            elif "timeout" in params:
                kwargs = dict(timeout=timeout)
                if "proxy_url" in params and proxy_url:
                    kwargs["proxy_url"] = proxy_url
                request = HTTPXRequest(**kwargs)

            # Вариант 3: совсем новая сигнатура с 'client'
            elif "client" in params:
                client = httpx.AsyncClient(timeout=timeout, proxies=proxy_url) if proxy_url else httpx.AsyncClient(timeout=timeout)
                request = HTTPXRequest(client=client)

            # Вариант 4: только proxy_url или вообще без параметров
            elif "proxy_url" in params and proxy_url:
                request = HTTPXRequest(proxy_url=proxy_url)
            else:
                request = HTTPXRequest()
        except Exception:
            # На всякий случай — если даже это не сработало, используем дефолт
            logger.exception("HTTPXRequest compatibility init failed; falling back to default")
            request = None

        builder = Application.builder().token(token)
        if request is not None:
            builder = builder.request(request)
        self.app = builder.build()
        
        # Настройка меню-кнопки с быстрыми командами при старте
        self.app.post_init = self._setup_menu_commands_async

        # --- Commands
        self.app.add_handler(CommandHandler("start", self.on_start))
        self.app.add_handler(CommandHandler("help", self.on_help))
        self.app.add_handler(CommandHandler(["help_full", "helpfull"], self.on_help_full))
        self.app.add_handler(CommandHandler("info", self.on_info))
        self.app.add_handler(CallbackQueryHandler(self.on_ui_btn, pattern=r"^ui:"))

        # Краткий/полный отчёты
        self.app.add_handler(CommandHandler(["status", "report"], self.on_status))  # КРАТКИЙ
        self.app.add_handler(CommandHandler(["full", "full_report"], self.on_full))  # ПОЛНЫЙ

        self.app.add_handler(CommandHandler(["subscribe", "sub"], self.on_sub))
        self.app.add_handler(CommandHandler(["unsubscribe", "unsub", "stop"], self.on_unsub))
        self.app.add_handler(CommandHandler("chart", self.on_chart))
        self.app.add_handler(CommandHandler("chart_album", self.on_chart_album))
        self.app.add_handler(CommandHandler("diag", self.on_diag))
        # Команды через CommandIntegrator
        if self.integrator:
            async def _cmd_quota(u, c):
                await self.integrator.handle_command("quota", u, c)
            self.app.add_handler(CommandHandler("quota", _cmd_quota))
        else:
            logger.warning("CommandIntegrator not available, quota command disabled")
        self.app.add_handler(CommandHandler(["market_doctor", "md"], self.on_market_doctor))
        self.app.add_handler(CommandHandler("md_profile", self.on_md_profile))
        self.app.add_handler(CommandHandler("mdh", self.on_mdh))
        self.app.add_handler(CommandHandler("mdt", self.on_mdt))
        self.app.add_handler(CommandHandler("mdtop", self.on_mdtop))
        self.app.add_handler(CommandHandler("md_watch_add", self.on_md_watch_add))
        self.app.add_handler(CommandHandler("md_watch_remove", self.on_md_watch_remove))
        self.app.add_handler(CommandHandler("md_watch_list", self.on_md_watch_list))
        self.app.add_handler(CommandHandler("md_backtest", self.on_md_backtest))
        self.app.add_handler(CommandHandler("md_calibrate", self.on_md_calibrate))
        self.app.add_handler(CommandHandler("md_apply_weights", self.on_md_apply_weights))
        self.app.add_handler(CommandHandler("md_weights_list", self.on_md_weights_list))
        self.app.add_handler(CommandHandler("md_weights_reset", self.on_md_weights_reset))

        # Options
        self.app.add_handler(CommandHandler("options_btc", self.on_options_btc))
        self.app.add_handler(CommandHandler("options_eth", self.on_options_eth))
        self.app.add_handler(CommandHandler("options_btc_free", lambda u, c: self.cmd_options_free(u, c, "BTC")))
        self.app.add_handler(CommandHandler("options_eth_free", lambda u, c: self.cmd_options_free(u, c, "ETH")))

        # Analytics
        self.app.add_handler(CommandHandler("corr", self.on_corr))
        self.app.add_handler(CommandHandler("beta", self.on_beta))
        self.app.add_handler(CommandHandler("vol", self.on_vol))
        self.app.add_handler(CommandHandler("funding", self.on_funding))
        self.app.add_handler(CommandHandler("basis", self.on_basis))
        self.app.add_handler(CommandHandler("liqs", self.on_liqs))
        self.app.add_handler(CommandHandler("scan_divs", self.cmd_scan_divs))
        self.app.add_handler(CallbackQueryHandler(self.cb_scan_divs, pattern=r"^ui:scan_divs(?::|$)"))
        self.app.add_handler(CommandHandler("levels", self.on_levels))
        self.app.add_handler(CommandHandler("risk_now", self.on_risk_now))
        self.app.add_handler(CommandHandler("bt", self.on_backtest))
        self.app.add_handler(CommandHandler("breadth", self.on_breadth))
        
        # Новые команды через CommandIntegrator
        if self.integrator:
            async def _cmd_whale_orders(u, c):
                await self.integrator.handle_command("whale_orders", u, c)
            
            async def _cmd_whale_activity(u, c):
                await self.integrator.handle_command("whale_activity", u, c)
            
            async def _cmd_heatmap(u, c):
                await self.integrator.handle_command("heatmap", u, c)
            
            self.app.add_handler(CommandHandler("whale_orders", _cmd_whale_orders))
            self.app.add_handler(CommandHandler("whale_activity", _cmd_whale_activity))
            self.app.add_handler(CommandHandler("heatmap", _cmd_heatmap))
        else:
            logger.warning("CommandIntegrator not available, whale/heatmap commands disabled")
        self.app.add_handler(CommandHandler(["bubbles1h", "bubbles_1h"], lambda u, c: self.on_bubbles(u, c, "1h")))
        self.app.add_handler(CommandHandler(["bubbles24h", "bubbles_24h", "bubbles"], lambda u, c: self.on_bubbles(u, c, "24h")))
        self.app.add_handler(MessageHandler(filters.Regex(r'^Bubbles 1h$'), lambda u, c: self.on_bubbles(u, c, "1h")))
        self.app.add_handler(MessageHandler(filters.Regex(r'^Bubbles 24h$'), lambda u, c: self.on_bubbles(u, c, "24h")))

        # Events
        self.app.add_handler(CommandHandler("events_add", self.on_events_add))
        self.app.add_handler(CommandHandler("events_list", self.on_events_list))
        self.app.add_handler(CommandHandler("events_del", self.on_events_del))

        # --- Callback buttons (inline)
        self.app.add_handler(CallbackQueryHandler(self.on_help_btn, pattern=r"^help:"))
        self.app.add_handler(CallbackQueryHandler(self.on_main_btn, pattern=r"^(report|subscribe|unsubscribe)$"))
        self.app.add_handler(CallbackQueryHandler(self.on_events_btn, pattern=r"^events:list$"))
        self.app.add_handler(CommandHandler("cg_test", self.on_cg_test))
        self.app.add_handler(CommandHandler("bubbles_debug", self.cmd_bubbles_debug))

        # --- команды ---
        self.app.add_handler(CommandHandler("global", self.on_global))
        self.app.add_handler(CommandHandler("trending", self.on_trending))
        self.app.add_handler(CommandHandler("top", self.on_top))
        self.app.add_handler(CommandHandler("flop", self.on_flop))
        self.app.add_handler(CommandHandler("daily", self.on_daily_cmd))

        # --- callback-кнопки ---
        self.app.add_handler(CallbackQueryHandler(self.on_categories_btn, pattern=r"^categories(:|$)"))
        self.app.add_handler(CallbackQueryHandler(self.on_category_pick, pattern=r"^cat:select:"))
        self.app.add_handler(CallbackQueryHandler(self.on_pager, pattern=r"^pager:(top|flop):"))
        self.app.add_handler(CallbackQueryHandler(self.on_bubbles_settings_handler, pattern=r"^bubbles:set:"))
        self.app.add_handler(CallbackQueryHandler(self.on_bubbles_shuffle, pattern=r"^bubbles:shuffle$"))
        self.app.add_handler(CallbackQueryHandler(self.on_bubbles_refresh, pattern=r"^bubbles:refresh$"))
        self.app.add_handler(CallbackQueryHandler(self.on_main_btn, pattern=r"^bubbles:"))
        # TWAP callbacks
        self.app.add_handler(CallbackQueryHandler(self.on_twap_callback, pattern=r"^twap:"))

        self.app.add_handler(MessageHandler(filters.Regex(r'(?i)^\s*b[uy]?bble?s?\s*1h\s*$'),lambda u, c: self.on_bubbles(u, c, "1h")))
        self.app.add_handler(MessageHandler(filters.Regex(r'(?i)^\s*b[uy]?bble?s?\s*24h\s*$'),lambda u, c: self.on_bubbles(u, c, "24h")))
        
        # Обработка ввода тикера для графиков (должен быть после других MessageHandler)
        self.app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.on_text_message))

        self.app.add_handler(CommandHandler("forecast", self.cmd_forecast))
        self.app.add_handler(CommandHandler("forecast3", self.cmd_forecast3))
        self.app.add_handler(CommandHandler("forecast_full", self.cmd_forecast_full))
        self.app.add_handler(CommandHandler("forecast_alts", self.cmd_forecast_alts))
        self.app.add_handler(CommandHandler("forecast_stats", self.cmd_forecast_stats))
        self.app.add_handler(CommandHandler("twap", self.on_twap))
        self.app.add_handler(CommandHandler("markets", self.on_markets))

        # --- Jobs
        async def _send_daily(context: ContextTypes.DEFAULT_TYPE):
            subs = list(self.db.list_subs())
            if not subs:
                return

            if _have_coinglass():
                try:
                    from ..infrastructure.coinglass import fetch_max_pain
                    from ..visual.options_chart import render_max_pain_chart

                    def build(symbol: str):
                        res = fetch_max_pain(symbol)
                        png = render_max_pain_chart(res)
                        text = (
                            f"*{symbol} options max pain*\n" +
                            "\n".join([f"• `{p.date}`  *{p.max_pain:,.0f}*  (${p.notional:,.0f})"
                                       for p in res.points[:10]])
                        )
                        return png, text

                    png_btc, txt_btc = build("BTC")
                    png_eth, txt_eth = build("ETH")
                except Exception:
                    logger.exception("daily CoinGlass failed, fallback to free")
                    png_btc, txt_btc = await self._build_free_payload("BTC", context)
                    png_eth, txt_eth = await self._build_free_payload("ETH", context)
            else:
                png_btc, txt_btc = await self._build_free_payload("BTC", context)
                png_eth, txt_eth = await self._build_free_payload("ETH", context)

            for chat_id in subs:
                try:
                    if png_btc:
                        await context.bot.send_photo(chat_id=chat_id, photo=png_btc, caption=txt_btc, parse_mode=ParseMode.MARKDOWN)
                    else:
                        await context.bot.send_message(chat_id=chat_id, text=txt_btc, parse_mode=ParseMode.MARKDOWN)

                    if png_eth:
                        await context.bot.send_photo(chat_id=chat_id, photo=png_eth, caption=txt_eth, parse_mode=ParseMode.MARKDOWN)
                    else:
                        await context.bot.send_message(chat_id=chat_id, text=txt_eth, parse_mode=ParseMode.MARKDOWN)
                except Exception:
                    logger.exception("daily send failed chat_id=%s", chat_id)
                    await asyncio.sleep(0.1)

        # Используем единый источник TZ из конфига
        tz = settings.tz

        def _sec_to_next(minute: int) -> int:
            now = datetime.now(tz)
            base = now.replace(second=0, microsecond=0)
            if base.minute >= minute:
                base = (base.replace(minute=0) + timedelta(hours=1))
            return int(((base.replace(minute=minute)) - now).total_seconds())

        # Доп. помощники на будущее (12h/4h слоты)
        def _sec_to_next_12h(minute: int = 10) -> int:
            now = datetime.now(tz)
            cand = []
            for h in (0, 12):
                t = now.replace(hour=h, minute=minute, second=0, microsecond=0)
                if t <= now:
                    t = t + timedelta(hours=12)
                cand.append(t)
            target = min(cand)
            return int((target - now).total_seconds())

        def _sec_to_next_4h(minute: int = 20) -> int:
            now = datetime.now(tz)
            hours = [0, 4, 8, 12, 16, 20]
            cand = []
            for h in hours:
                t = now.replace(hour=h, minute=minute, second=0, microsecond=0)
                if t <= now:
                    t = t + timedelta(hours=4)
                cand.append(t)
            target = min(cand)
            return int((target - now).total_seconds())

        # Планировщик
        self.app.job_queue.run_daily(_send_daily, time=dtime(hour=9, minute=0, tzinfo=tz), name="daily_max_pain")

        # Периодические рассылки:
        # 1) Краткий отчёт — ежечасно в :30
        self.app.job_queue.run_repeating(
            self.job_broadcast_compact, interval=60 * 60, first=_sec_to_next(30), name="broadcast_compact_30m"
        )
        # 2) Полный отчёт — ежечасно в :00
        self.app.job_queue.run_repeating(
            self.job_broadcast_full, interval=60 * 60, first=_sec_to_next(0), name="broadcast_full_hh00"
        )
        # 3) PNG-дайджест — раз в час
        self.app.job_queue.run_repeating(
            self.job_broadcast_chart, interval=60 * 60, first=60, name="broadcast_chart_hourly"
        )

        # Напоминания о событиях (каждую минуту)
        async def _events_job(context: ContextTypes.DEFAULT_TYPE):
            from ..infrastructure.events import due_events, mark_notified
            now_ms = int(time.time() * 1000)
            for ev_id, chat_id, ts, title, kind in due_events(now_ms):
                when = "через ~24 часа" if kind == "24h" else "через ~1 час"
                try:
                    dt = pd.to_datetime(ts, unit="ms")
                    await context.bot.send_message(
                        chat_id=chat_id,
                        text=f"🔔 Напоминание: {title}\nКогда: <code>{dt}</code> ({when})",
                        parse_mode=ParseMode.HTML,
                    )
                except Exception:
                    logger.exception("failed to send event reminder")
                mark_notified(ev_id, kind)

        self.app.job_queue.run_repeating(_events_job, interval=60, first=10, name="events_reminders")
        
        # Автоматические отчёты о качестве моделей (раз в сутки в 8:00 UTC)
        async def _quality_reports_job(context: CallbackContext):
            from ..main_worker import generate_quality_reports
            await generate_quality_reports(context)
        
        # Используем уже импортированные dtime и ZoneInfo из начала файла
        # dtime уже импортирован глобально в строке 5
        # ZoneInfo уже импортирован глобально в строке 7 (в try-except блоке)
        # Если ZoneInfo не доступен (старый Python), используем UTC через datetime
        # Используем глобальный ZoneInfo напрямую - он уже импортирован
        try:
            # ZoneInfo уже импортирован глобально в начале файла (строка 7)
            tz_utc = ZoneInfo("UTC")
        except NameError:
            # Если ZoneInfo не доступен (старый Python), используем UTC через datetime
            from datetime import timezone
            tz_utc = timezone.utc
        self.app.job_queue.run_daily(
            _quality_reports_job,
            time=dtime(hour=8, minute=0, tzinfo=tz_utc),
            name="quality_reports_daily"
        )
        
        # Автоматическая оценка прогнозов (каждые 2 часа)
        async def _evaluate_forecasts_job(context: ContextTypes.DEFAULT_TYPE):
            from ..main_worker import evaluate_forecasts
            await evaluate_forecasts(context)
        self.app.job_queue.run_repeating(
            _evaluate_forecasts_job,
            interval=7200,  # 2 часа в секундах
            first=300,  # Первый запуск через 5 минут после старта
            name="evaluate_forecasts_periodic"
        )

        # error handler
        self.app.add_error_handler(self.on_error)

    def _fc_key(self, sym: str, tf: str, horizon: int) -> str:
        return f"{sym}:{tf}:{horizon}"

    def _fc_get(self, key: str):
        import time
        v = self._forecast_cache.get(key)
        if not v:
            return None
        ts, res = v
        if time.time() - ts > self._forecast_cache_ttl:
            return None
        return res

    def _fc_set(self, key: str, res):
        import time
        self._forecast_cache[key] = (time.time(), res)

    async def _refresh_forecast_cache(self):
        from ..ml.data_adapter import make_loader
        from ..ml.forecaster import forecast_symbol

        loader = make_loader()
        watch = [
            ("BTCUSDT", "1h", 24),
            ("BTCUSDT", "4h", 6),
            ("BTCUSDT", "24h", 1),
        ]
        for sym, tf, horizon in watch:
            try:
                key = self._fc_key(sym, tf, horizon)
                res = forecast_symbol(loader, sym, tf, horizon=horizon)
                self._fc_set(key, res)
            except Exception:
                continue

    def _kb(self, state: str = "main") -> InlineKeyboardMarkup:
        # ЕДИНАЯ клавиатура под /start, справки и отчёты
        return build_kb(state, DEFAULT_TF)

    async def on_ui_btn(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        return await self.ui.handle(update, context, self)

    async def shutdown(self):
        if self.http_session:
            await self.http_session.close()

    METRICS = ("BTC", "ETHBTC", "USDT.D", "BTC.D", "TOTAL2", "TOTAL3")  # если у тебя уже есть — убери дубли

    def _kb_scan_divs_list(self, tf: str, page: int) -> InlineKeyboardMarkup:
        rows = [
            [
                InlineKeyboardButton("◀️", callback_data=f"ui:scan_divs:list:{tf}:{max(page - 1, 0)}"),
                InlineKeyboardButton(f"{tf}", callback_data="noop"),
                InlineKeyboardButton("▶️", callback_data=f"ui:scan_divs:list:{tf}:{page + 1}"),
            ],
            [
                InlineKeyboardButton("15m", callback_data="ui:scan_divs:15m"),
                InlineKeyboardButton("1h", callback_data="ui:scan_divs:1h"),
                InlineKeyboardButton("4h", callback_data="ui:scan_divs:4h"),
                InlineKeyboardButton("1d", callback_data="ui:scan_divs:1d"),
            ],
            [InlineKeyboardButton("🔄 Обновить", callback_data=f"ui:scan_divs:list:{tf}:{page}")]
        ]
        return InlineKeyboardMarkup(rows)

    def _fmt_ts(self, ms: int | None) -> str:
        if not ms:
            return "-"
        try:
            dt = datetime.fromtimestamp(ms / 1000, _TZ) if _TZ else datetime.utcfromtimestamp(ms / 1000)
            return dt.strftime("%d.%m %H:%M")
        except Exception:
            return "-"

    def _fmt_div_row(self, metric: str, indicator: str, side: str,
                     status: str, grade: str | None,
                     detected_ts: int | None, pivot_r_val: float | None) -> str:
        tag = "🟢 Bull" if side == "bullish" else "🔴 Bear"
        t = self._fmt_ts(detected_ts)
        thr = "" if pivot_r_val is None else f" | порог <code>{pivot_r_val:.4g}</code>"
        if status == "confirmed":
            gtxt = "hard" if grade == "hard" else ("soft" if grade == "soft" else "")
            return f"{tag} (<code>{indicator}</code>, {gtxt}) • <code>{metric}</code> — <b>подтв.</b> с {t}{thr}"
        return f"{tag} (<code>{indicator}</code>) • <code>{metric}</code> — активна с {t}{thr}"

    def _render_scan_divs_text(self, tf: str, page: int = 0, page_size: int = 12):
        rows_all = []
        for m in ("BTC", "ETHBTC", "USDT.D", "BTC.D", "TOTAL2", "TOTAL3"):
            try:
                rows = self.db.list_open_divs(m, tf)
            except Exception:
                try:
                    tmp = self.db.list_active_divs(m, tf)
                    rows = [(*r, "active", None) for r in tmp]
                except Exception:
                    rows = []
            for (_id, ind, side, _impl, rts, rval, status, grade) in rows:
                rows_all.append((int(rts or 0), m, ind, side, status, grade, rts, rval))

        rows_all.sort(key=lambda x: x[0], reverse=True)
        total = len(rows_all)
        start = max(0, page * page_size)
        page_rows = rows_all[start:start + page_size]

        head = f"<b>Дивергенции • {tf}</b>\nПоказано {start + 1 if total else 0}–{start + len(page_rows)} из {total}"
        lines = [head]
        for (_key, m, ind, side, status, grade, rts, rval) in page_rows:
            lines.append("• " + self._fmt_div_row(m, ind, side, status, grade, rts, rval))

        text = "\n".join(lines) if page_rows else f"<b>Дивергенции • {tf}</b>\nПока сигналов нет."
        kb = self._kb_scan_divs_list(tf, page)
        return text, kb

    from telegram.constants import ParseMode
    from telegram.error import BadRequest

    async def _smart_show_text(self, update, q, text, reply_markup):
        """Надёжно показывает text с клавиатурой:
        - если исходное сообщение текстовое — редактируем его;
        - если это фото/медиа — убираем у него клавиатуру и отправляем новое текстовое сообщение;
        - если сообщение не изменилось — молча закрываем «часики» (без падения).
        """
        kwargs = dict(parse_mode=ParseMode.HTML,
                      disable_web_page_preview=True,
                      reply_markup=reply_markup)

        # 1) Текстовое сообщение
        if q and getattr(q, "message", None) and getattr(q.message, "text", None):
            try:
                return await q.edit_message_text(text, **kwargs)
            except BadRequest as e:
                msg = (getattr(e, "message", "") or str(e)).lower()
                if "message is not modified" in msg:
                    # попробуем обновить только клавиатуру
                    try:
                        return await q.edit_message_reply_markup(reply_markup=reply_markup)
                    except BadRequest:
                        pass
                    await q.answer("Обновлено", cache_time=1)
                    return None
                if "there is no text" in msg:
                    # упадём дальше в ветку медиа
                    pass
                else:
                    raise

        # 2) Фото/медиа — снимаем старую клавиатуру и шлём новый текст
        if q and getattr(q, "message", None):
            try:
                await q.edit_message_reply_markup(reply_markup=None)
            except BadRequest:
                pass
            sent = await q.message.reply_text(text, **kwargs)
            await q.answer()
            return sent

        # 3) Фолбэк
        sent = await update.effective_message.reply_text(text, **kwargs)
        if q:
            await q.answer()
        return sent

    async def _safe_edit_text(self, q, text, reply_markup=None,
                              parse_mode=None, disable_web_page_preview=None):
        """Безопасная замена edit_message_text по всему боту:
        - Если «Message is not modified» → обновляем только клавиатуру (если она есть) или молча закрываем «часики».
        - Если исходное сообщение было медиа (нет .text) → снимаем клавиатуру и отправляем НОВОЕ текстовое сообщение.
        """
        from telegram.error import BadRequest

        kwargs = {}
        if reply_markup is not None:
            kwargs["reply_markup"] = reply_markup
        if parse_mode is not None:
            kwargs["parse_mode"] = parse_mode
        if disable_web_page_preview is not None:
            kwargs["disable_web_page_preview"] = disable_web_page_preview

        try:
            return await q.edit_message_text(text, **kwargs)

        except BadRequest as e:
            msg = (getattr(e, "message", "") or str(e)).lower()
            if "message is not modified" in msg:
                # обновим только клавиатуру, если она менялась
                try:
                    if reply_markup is not None:
                        return await q.edit_message_reply_markup(reply_markup=reply_markup)
                except BadRequest:
                    pass
                await q.answer("Обновлено", cache_time=1)
                return None
            if "there is no text" in msg:
                # исходное сообщение было фото/медиа
                try:
                    await q.edit_message_reply_markup(reply_markup=None)
                except BadRequest:
                    pass
                return await q.message.reply_text(text, **kwargs)
            raise

    async def on_scan_divs(self, update, context):
        q = update.callback_query
        ud = context.user_data

        tf = (ud.get("tf") or "1h")
        page = 0

        # payload: ui:scan_divs | ui:scan_divs:TF | ui:scan_divs:list:TF:PAGE
        if q and q.data:
            parts = q.data.split(":")
            if len(parts) >= 3:
                if parts[2] == "list" and len(parts) >= 5:
                    tf = parts[3] or tf
                    try:
                        page = max(0, int(parts[4]))
                    except (ValueError, TypeError):
                        page = 0
                else:
                    tf = parts[2] or tf

        ud["tf"] = tf
        text, kb = self._render_scan_divs_text(tf, page)

        if q:
            # ВАЖНО: _smart_show_text сам вызывает q.answer()
            await self._smart_show_text(update, q, text, kb)
            return

        await update.effective_message.reply_text(
            text, reply_markup=kb, disable_web_page_preview=True, parse_mode=ParseMode.HTML
        )

    async def cmd_scan_divs(self, update, context):
        """Обработчик команды /scan_divs с поддержкой новой архитектуры."""
        try:
            if self.integrator:
                handled = await self.integrator.handle_command("scan_divs", update, context)
                if handled:
                    return
            await self._cmd_scan_divs_legacy(update, context)
        except Exception:
            logger.exception("cmd_scan_divs failed")
            try:
                await self._cmd_scan_divs_legacy(update, context)
            except Exception:
                logger.exception("cmd_scan_divs legacy also failed")
    
    async def _cmd_scan_divs_legacy(self, update, context):
        """Старая реализация команды /scan_divs."""
        tf = "1h"
        text, kb = self._render_scan_divs_text(tf, page=0)
        await update.message.reply_text(text, reply_markup=kb, disable_web_page_preview=True)

    async def cb_scan_divs(self, update, context):
        q = update.callback_query
        data = q.data.split(":")  # варианты: ui:scan_divs, ui:scan_divs:1h, ui:scan_divs:list:1h:2
        try:
            if len(data) == 2:
                # просто открыли подменю TF — покажем список для дефолтного TF
                tf = "1h"
                text, kb = self._render_scan_divs_text(tf, page=0)
                await self._smart_show_text(update, q, text, kb)
            elif len(data) == 3:
                # выбрали TF
                tf = data[2]
                text, kb = self._render_scan_divs_text(tf, page=0)
                await self._smart_show_text(update, q, text, kb)
            elif len(data) == 5 and data[2] == "list":
                tf = data[3]
                page = int(data[4])
                text, kb = self._render_scan_divs_text(tf, page=page)
                await self._smart_show_text(update, q, text, kb)
            await q.answer()
        except Exception:
            await q.answer("Ошибка рендера дивергенций", show_alert=True)

    async def on_fng(self, update, context):
        """Обработчик команды /fng с поддержкой новой архитектуры."""
        try:
            if self.integrator:
                handled = await self.integrator.handle_command("fng", update, context)
                if handled:
                    return
            await self._on_fng_legacy(update, context)
        except Exception:
            logger.exception("on_fng failed")
            try:
                await self._on_fng_legacy(update, context)
            except Exception:
                logger.exception("on_fng legacy also failed")
    
    async def _on_fng_legacy(self, update, context):
        """Старая реализация команды /fng."""
        d = await self.indices.get_fng_history(limit=1)
        cur = d["values"][0] if d["values"] else {"value": None, "classification": ""}
        val = cur["value"]
        cls = cur["classification"]
        try:
            ttu = int(d.get("time_until_update") or 0)
        except Exception:
            ttu = 0

        caption = (
            f"<b>Fear & Greed</b>\n"
            f"Значение: <b>{val if val is not None else '—'}</b> — {cls or ''}\n"
            f"{_ago_or_in(ttu)}"
        )

        # cache-buster: меняем URL хотя бы раз в час (или чаще, если хотите)
        png_url = self.indices.get_fng_widget_url()

        await self.app.bot.send_photo(
            chat_id=update.effective_chat.id,
            photo=png_url,
            caption=caption,
            parse_mode="HTML",
            reply_markup=build_kb("more"),
        )

    async def on_fng_history(self, update, context):
        """Обработчик команды /fng_history с поддержкой новой архитектуры."""
        try:
            if self.integrator:
                handled = await self.integrator.handle_command("fng_history", update, context)
                if handled:
                    return
            await self._on_fng_history_legacy(update, context)
        except Exception:
            logger.exception("on_fng_history failed")
            try:
                await self._on_fng_history_legacy(update, context)
            except Exception:
                logger.exception("on_fng_history legacy also failed")
    
    async def _on_fng_history_legacy(self, update, context):
        """Старая реализация команды /fng_history."""
        try:
            parts = (getattr(update.effective_message, "text", "") or "").split()
            limit = int(parts[1]) if len(parts) > 1 else 7
            limit = max(3, min(limit, 60))
        except Exception:
            limit = 7

        d = await self.indices.get_fng_history(limit=limit)
        vals = [v["value"] for v in reversed(d["values"])]
        if not vals:
            return await self._send_html(update.effective_chat.id, "Нет данных F&G.", reply_markup=build_kb("more"))

        spark = _sparkline(vals)
        now = vals[-1]
        prev = vals[-2] if len(vals) > 1 else None
        wk = vals[-8] if len(vals) > 7 else None
        mo = vals[-31] if len(vals) > 30 else None
        try:
            ttu = int(d.get("time_until_update") or 0)
        except Exception:
            ttu = 0

        lines = [
            "<b>Fear & Greed — история</b>",
            f"Последние {len(vals)}: <code>{spark}</code>",
            f"Текущее: <b>{now}</b>" + (f" (вчера: {prev})" if prev is not None else ""),
            (f"Неделю назад: {wk}" if wk is not None else ""),
            (f"Месяц назад: {mo}" if mo is not None else ""),
            _ago_or_in(ttu),
        ]
        text = "\n".join([ln for ln in lines if ln])
        await self._send_html(update.effective_chat.id, text, reply_markup=build_kb("more"))

    async def on_altseason(self, update, context):
        """Обработчик команды /altseason с поддержкой новой архитектуры."""
        try:
            if self.integrator:
                handled = await self.integrator.handle_command("altseason", update, context)
                if handled:
                    return
            await self._on_altseason_legacy(update, context)
        except Exception:
            logger.exception("on_altseason failed")
            try:
                await self._on_altseason_legacy(update, context)
            except Exception:
                logger.exception("on_altseason legacy also failed")
    
    async def _on_altseason_legacy(self, update, context):
        """Старая реализация команды /altseason."""
        d = await self.indices.get_altseason()  # {"value": int|None, "label": str}
        val = d.get("value")
        label = d.get("label") or ""

        # генерим PNG
        from ..visual.altseason_card import render_altseason_card

        png_bytes = render_altseason_card(value=val)
        photo = InputFile(BytesIO(png_bytes), filename="altseason.png")

        caption = (
            "<b>Altcoin Season Index</b>\n"
            f"Значение: <b>{'—' if val is None else val}</b>"
            f"{' — ' + label if label else ''}"
        )
        await self.app.bot.send_photo(
            chat_id=update.effective_chat.id,
            photo=photo,
            caption=caption,
            parse_mode="HTML",
            reply_markup=build_kb("main"),
        )

    async def on_twap(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик команды /twap с поддержкой новой архитектуры."""
        try:
            if self.integrator:
                handled = await self.integrator.handle_command("twap", update, context)
                if handled:
                    return
            await self._on_twap_legacy(update, context)
        except Exception:
            logger.exception("on_twap failed")
            try:
                await self._on_twap_legacy(update, context)
            except Exception:
                logger.exception("on_twap legacy also failed")
    
    async def on_twap_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик callback'ов для кнопок TWAP."""
        try:
            if self.integrator:
                handler = self.integrator.get_handler("twap")
                if handler:
                    await handler.handle_twap_callback(update, context)
                    return
        except Exception:
            logger.exception("on_twap_callback failed")
    
    async def _on_twap_legacy(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Старая реализация команды /twap."""
        text = (
            "<b>TWAP сейчас</b>\n\n"
            "Функция находится в разработке.\n"
            "Скоро здесь будет отображаться TWAP (Time-Weighted Average Price) для основных активов."
        )
        await update.effective_message.reply_text(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=build_kb("main"),
        )
    
    async def on_markets(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик команды /markets с поддержкой новой архитектуры."""
        try:
            if self.integrator:
                handled = await self.integrator.handle_command("markets", update, context)
                if handled:
                    return
            await self._on_markets_legacy(update, context)
        except Exception:
            logger.exception("on_markets failed")
            try:
                await self._on_markets_legacy(update, context)
            except Exception:
                logger.exception("on_markets legacy also failed")
    
    async def _on_markets_legacy(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Старая реализация команды /markets."""
        try:
            from ..application.services.traditional_markets_service import TraditionalMarketsService
            traditional_markets = TraditionalMarketsService()
            markets = traditional_markets.get_all_traditional_markets()
            
            lines = ["<b>📊 Традиционные рынки</b>\n"]
            
            # S&P500
            sp500 = markets.get("sp500")
            if sp500:
                emoji = "🟢" if sp500["change_percent_24h"] > 0 else "🔴" if sp500["change_percent_24h"] < 0 else "⚪"
                lines.append(
                    f"{emoji} <b>{sp500['name']}</b>: {sp500['price']:,.2f} "
                    f"({sp500['change_percent_24h']:+.2f}%)"
                )
            else:
                lines.append("❌ S&P 500: данные недоступны")
            
            # Золото
            gold = markets.get("gold")
            if gold:
                emoji = "🟢" if gold["change_percent_24h"] > 0 else "🔴" if gold["change_percent_24h"] < 0 else "⚪"
                lines.append(
                    f"{emoji} <b>{gold['name']}</b>: ${gold['price_usd']:,.2f}/oz "
                    f"({gold['change_percent_24h']:+.2f}%)"
                )
            else:
                lines.append("❌ Gold: данные недоступны")
            
            # Нефть
            oil = markets.get("oil")
            if oil:
                emoji = "🟢" if oil["change_percent_24h"] > 0 else "🔴" if oil["change_percent_24h"] < 0 else "⚪"
                lines.append(
                    f"{emoji} <b>{oil['name']}</b>: ${oil['price_usd']:,.2f}/bbl "
                    f"({oil['change_percent_24h']:+.2f}%)"
                )
            else:
                lines.append("❌ Oil: данные недоступны")
            
            lines.append("\n<i>Данные обновляются в реальном времени</i>")
            
            # Если все данные недоступны, добавляем подсказку
            if not sp500 and not gold and not oil:
                lines.append("\n⚠️ <i>Для работы требуется установить yfinance: pip install yfinance</i>")
            
            text = "\n".join(lines)
            
            await update.effective_message.reply_text(
                text,
                parse_mode=ParseMode.HTML,
                reply_markup=build_kb("main")
            )
        except Exception:
            logger.exception("_on_markets_legacy failed")
            await update.effective_message.reply_text(
                "❌ Ошибка при получении данных о традиционных рынках.\n\n"
                "⚠️ Для работы требуется установить yfinance:\n"
                "<code>pip install yfinance</code>",
                parse_mode=ParseMode.HTML,
                reply_markup=build_kb("main")
        )

    def _resolve_tf(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> str:
        tf = context.user_data.get("tf")
        if not tf:
            text = getattr(getattr(update, "effective_message", None), "text", "") or ""
            try:
                tf = self._parse_tf(text)
            except Exception:
                tf = None
        return tf or DEFAULT_TF

    def _resolve_symbol(self, update: Update, context: ContextTypes.DEFAULT_TYPE, default: str = "BTC") -> str:
        symbol = context.user_data.get("symbol")
        if not symbol:
            # если в тексте иногда передаёшь тикер
            text = getattr(getattr(update, "effective_message", None), "text", "") or ""
            # при желании можно добавить парсер тикера из текста
        return symbol or default

    def _resolve_pair(self, update: Update, context: ContextTypes.DEFAULT_TYPE, default: str = "ETHBTC") -> str:
        pair = context.user_data.get("pair")
        if not pair:
            text = getattr(getattr(update, "effective_message", None), "text", "") or ""
            # при желании можно добавить парсер пары
        return pair or default

    def _resolve_study(self, update: Update, context: ContextTypes.DEFAULT_TYPE, default: str = "rsi") -> str:
        return context.user_data.get("study") or default

    async def _send_html_safe(self, bot, chat_id: int, text: str, reply_markup=None, disable_web_page_preview=True):
        try:
            return await bot.send_message(
                chat_id=chat_id,
                text=text,
                parse_mode=ParseMode.HTML,
                reply_markup=reply_markup,
                disable_web_page_preview=disable_web_page_preview,
            )
        except BadRequest as e:
            logger.warning("send_html_safe: fallback to plain text: %s", e)
            return await bot.send_message(
                chat_id=chat_id,
                text=text,
                reply_markup=reply_markup,
                disable_web_page_preview=disable_web_page_preview,
            )

    async def on_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик команды /start с поддержкой новой архитектуры."""
        try:
            # Пытаемся использовать новую архитектуру
            if self.integrator:
                handled = await self.integrator.handle_command("start", update, context)
                if handled:
                    return
            # Fallback на старый код
            await self._on_start_legacy(update, context)
        except Exception:
            logger.exception("on_start failed")
            # Если новая архитектура упала, пробуем старую
            try:
                await self._on_start_legacy(update, context)
            except Exception:
                logger.exception("on_start legacy also failed")
    
    async def _on_start_legacy(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Старая реализация команды /start."""
        msg = (
            "Привет!\n"
            "Я ALT Forecast — твой крипто-навигатор:\n"
            "рынок одним взглядом, пузыри как CryptoBubbles, топы/флопы, корреляции,\n"
            "волатильность, риск-режим, опционы и куча других\n"
            "полезных штук.\n"
            "Нажимай кнопки ниже — поехали!\n"
            "Хочешь подписаться на отчёты бота нажми /subscribe"
        )
        await update.effective_message.reply_text(
            msg,
            parse_mode=ParseMode.HTML,
            reply_markup=get_main_reply_keyboard(),
        )

    def _pair_series_sec(self, tf: str, n: int = 320) -> dict[str, list[tuple[int, float]]]:
        series: dict[str, list[tuple[int, float]]] = {}
        for m in METRICS:
            rows = self.db.last_n_closes(m, tf, n)
            series[m] = [(_ts_sec(ts), c) for ts, c in rows]
        return series

    def _vol_hint(self, *, sym: str, tf: str, rv7: float, rv30: float, atr: float, regime: str, pctl: float) -> str:
        reg = (regime or "").lower()
        base = "Зачем: понять режим волатильности для выбора стопов/размера позиции и ожидания сжатия/разжатия. "
        atr_tip = f"ATR≈{atr:.0f} → стопы ближе ~1×ATR шумом выбивает; ориентир 1.5–2×ATR."
        if reg == "low":
            extra = "Рынок сжат → вероятно расширение волатильности; не злоупотребляй плечом."
        elif reg == "high":
            extra = "Рынок разжат → высокая амплитуда; уменьшай плечо, стопы шире; возможна нормализация."
        else:
            extra = "Режим средний; подстраивай стопы к ATR, возможны как всплеск, так и спад волы."
        return f"{base}{atr_tip} {extra}"

    async def _send_html(self, chat_id: int, text: str, reply_markup=None):
        if not text:
            return
        parts, cur, cur_len = [], [], 0
        for line in text.splitlines(keepends=True):
            if cur_len + len(line) > MAX_TG_LEN - 32:
                parts.append("".join(cur))
                cur, cur_len = [line], len(line)
            else:
                cur.append(line)
                cur_len += len(line)
        if cur:
            parts.append("".join(cur))
        for i, chunk in enumerate(parts, 1):
            await self.app.bot.send_message(
                chat_id=chat_id,
                text=chunk,
                parse_mode=ParseMode.HTML,
                reply_markup=reply_markup,
                disable_web_page_preview=True,
            )
            if i < len(parts):
                await asyncio.sleep(0.2)

    def _build_full_safe(self) -> str:
        try:
            return build_full_report(self.db)
        except Exception:
            logger.exception("build_full_report failed")
            return "<b>Ошибка формирования полного отчёта</b>. Попробуйте позже."

    def _build_compact_safe(self) -> str:
        try:
            return build_status_report(self.db)
        except Exception:
            logger.exception("build_status_report failed")
            return "<b>Ошибка формирования краткого отчёта</b>. Попробуйте позже."

    def _parse_tf(self, text: str | None) -> str:
        if not text:
            return "1h"
        for p in text.strip().split()[1:]:
            if p in ("15m", "1h", "4h", "1d"):
                return p
        return "1h"

    async def _build_free_payload(self, symbol: str, context: ContextTypes.DEFAULT_TYPE):
        from ..infrastructure.deribit import build_series
        from ..visual.options_chart_free import render_free_series

        pts = build_series(symbol, max_expiries=8)

        bmap: dict[str, float] = {}
        try:
            from ..infrastructure.binance_options import notional_by_expiry
            for p in pts:
                y, m, d = p["date"].split("-")
                yymmdd = f"{y[2:]}{m}{d}"
                v = notional_by_expiry(symbol, yymmdd)
                if v:
                    bmap[yymmdd] = float(v)
        except Exception:
            bmap = {}

        png = render_free_series(pts, bmap if bmap else None)

        lines, total_sum = [], 0.0
        for p in pts[:10]:
            yymmdd = p["date"].replace("-", "")[2:]
            d_usd = float(p.get("deribit_notional_usd", 0.0))
            b_usd = float(bmap.get(yymmdd, 0.0))
            s_usd = d_usd + b_usd
            total_sum += s_usd
            lines.append(f"• `{p['date']}`  MP=*{p['max_pain']:,.0f}*  Σ≈${s_usd:,.0f}")

        text = f"*{symbol} options (free)*\nΣ total≈${total_sum:,.0f}\n" + "\n".join(lines)
        return png, text

    # ---------------- /help + callbacks ----------------

    def _resolve_tf(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> str:
        # 1) из user_data — приоритет
        tf = context.user_data.get("tf")

        # 2) если нет — пробуем из текста (/chart 15m)
        if not tf:
            text = getattr(getattr(update, "effective_message", None), "text", "") or ""
            try:
                tf = self._parse_tf(text)
            except Exception:
                tf = None

        # 3) нормализация: любые суточные → 1d
        tf = (tf or "").lower()
        if tf in ("1d", "24h", "d1", "1day", "day"):
            tf = "1d"

        # 4) дефолт
        return tf or DEFAULT_TF

    def _resolve_symbol(self, update, context, default="BTC"):
        return context.user_data.get("symbol") or default


    async def on_help(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик команды /help с поддержкой новой архитектуры."""
        try:
            if self.integrator:
                handled = await self.integrator.handle_command("help", update, context)
                if handled:
                    return
            await self._on_help_legacy(update, context)
        except Exception:
            logger.exception("on_help failed")
            try:
                await self._on_help_legacy(update, context)
            except Exception:
                logger.exception("on_help legacy also failed")
    
    async def _on_help_legacy(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Старая реализация команды /help."""
        text = (
            "<b>ALT Forecast — что умею</b> 👉\n\n"
            "<b>Отчёты</b>\n"
            "• /status — краткий срез\n"
            "• /full — полный обзор\n\n"
            "<b>Рынок</b>\n"
            "• /top, /flop, /top_1h, /flop_1h\n"
            "• /trending\n"
            "• /categories\n\n"
            "<b>Визуал</b>\n"
            "• /bubbles 1h|1d\n"
            "• /chart_*\n"
            "• /chart_album_*\n\n"
            "<b>Индексы</b>\n"
            "• /fng\n"
            "• /altseason\n\n"
            "<b>Ещё</b>\n"
            "жми кнопку «➡️ Ещё» внизу — там вола, корреляции, фандинг/базис и т.д.\n\n"
            "<i>Подсказка:</i> настройки пузырьков (размер/кол-во/стейблы) — через «🫧 Bubbles → ⚙️ Настройки»."
        )
        await update.effective_message.reply_text(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=self._kb('help'),
        )

    async def on_help_full(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик команды /help_full с поддержкой новой архитектуры."""
        try:
            if self.integrator:
                handled = await self.integrator.handle_command("help_full", update, context)
                if handled:
                    return
            await self._on_help_full_legacy(update, context)
        except Exception:
            logger.exception("on_help_full failed")
            try:
                await self._on_help_full_legacy(update, context)
            except Exception:
                logger.exception("on_help_full legacy also failed")
    
    async def _on_help_full_legacy(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Старая реализация команды /help_full."""
        text = (
            "<b>ALT Forecast — полная справка</b>\n\n"
            "<b>Навигация</b>\n\n"
            "• Вызови /start — увидишь главное меню.\n\n"
            "• Все разделы доступны через кнопки. Подразделы открываются в один клик.\n\n"
            "• Любую команду можно ввести текстом (например, /bubbles 1h).\n\n"
            "<b>Главное меню</b>\n\n"
            "• ℹ️ Справка — краткая (/help) и полная (/help_full) инструкции.\n\n"
            "• 🧾 Отчёт — /status (краткий), /full (полный) — быстрый обзор рынка.\n\n"
            "• 🫧 Bubbles — /bubbles 1h | /bubbles 1d. Есть «⚙️ Настройки»: размер пузырей по капе/росту, количество, включать/исключать стейблы.\n\n"
            "• 🏆 Топ — /top_24h (= /top), /flop_24h (= /flop), /top_1h, /flop_1h, а также /categories (срез по секторам).\n\n"
            "• 📈 Чарты — /chart_15m /chart_1h /chart_4h /chart_1d (ключевые графики по ТФ).\n\n"
            "• 🖼 Альбом — /chart_album_15m /chart_album_1h /chart_album_4h /chart_album_1d (набор графиков одним сообщением).\n\n"
            "• 🧩 Опционы — /btc_options, /eth_options (сводки по опционам BTC/ETH).\n\n"
            "• 🧭 F&G — /fng (индекс страха/жадности).\n\n"
            "• 🪙 Altseason — /altseason.\n\n"
            "• 📘 Инструкция — /instruction (этот документ и навигация).\n\n"
            "<b>Экран «Ещё»</b>\n\n"
            "• 🔥 Тренды — /trending (ускорение интереса/движения).\n\n"
            "• 🌍 Метрики — /global (агрегаты: доминирование, капитализация и т.п.).\n\n"
            "• 🗞 Дайджест — /daily (утренний обзор ключевых пунктов).\n\n"
            "• 🧭 Риск сейчас — /risk_now (оценка режима: risk-on/off, перегрев).\n\n"
            "• 🗓 События — /events_list (релизы/ивенты/драйверы волатильности).\n\n"
            "• 📉 Волатильность — /vol + выбор ТФ 15m/1h/4h/1d.\n\n"
            "• 💥 Ликвидации — /liqs.\n\n"
            "• 🔗 Корреляция — /corr + ТФ.\n\n"
            "• β Бета — /beta + ТФ (сила альтов к BTC).\n\n"
            "• 💵 Фандинг — /funding symbol.\n\n"
            "• ⚖️ Базис — /basis symbol.\n\n"
            "• 🔎 Дивергенции — /scan_divs + ТФ.\n\n"
            "• 📐 Уровни — /levels + ТФ (SR/ключевые зоны).\n\n"
            "• 🧠 BT RSI — /bt rsi + ТФ.\n\n"
            "• 🌡 Ширина рынка — /breadth + ТФ.\n\n"
            "• 🧮 F&G история — /fng_history [N].\n\n"
            "• 📈 Ticker — /ticker [sort] [limit] [convert] — сортировки: rank | percent_change_1h | percent_change_24h | percent_change_7d | volume_24h | market_cap.\n\n"
            "<b>Подсказки</b>\n\n"
            "• ТФ обозначения: 15m, 1h, 4h, 1d.\n\n"
            "• Некоторые команды могут занять пару секунд из-за внешних API.\n\n"
            "• Источники данных: CoinGecko (рынок/категории), позже — деривативы бирж; все источники будут указаны на карточках.\n\n"
            "<b>Важно</b>\n\n"
            "Этот бот — инструмент для анализа. Это не финансовая рекомендация. Проверяй данные, управляй рисками и соблюдай свой план."
        )
        await update.effective_message.reply_text(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=self._kb('help'),
        )

    async def on_help_btn(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        q = update.callback_query
        await q.answer()
        chat_id = update.effective_chat.id
        parts = q.data.split(":")
        try:
            if parts[:2] == ["help", "show"]:
                mode = parts[2]
                if mode == "full":
                    await self.on_help_full(update, context)
                else:
                    await self.on_help(update, context)
                return
            if parts[:2] == ["help", "options"]:
                sym = parts[2]
                await self.cmd_options(update, context, sym); return
            if parts[:2] == ["help", "options_free"]:
                sym = parts[2]
                png, text = await self._build_free_payload(sym, context)
                if png:
                    await context.bot.send_photo(chat_id=chat_id, photo=png, caption=text, parse_mode=ParseMode.MARKDOWN)
                else:
                    await context.bot.send_message(chat_id=chat_id, text=text, parse_mode=ParseMode.MARKDOWN)
                return
            if parts[:2] == ["help", "chart"]:
                await self._send_chart_tf(chat_id, tf=parts[2] if len(parts) > 2 else "1h"); return
            if parts[:2] == ["help", "chart_album"]:
                await self._send_chart_album_tf(chat_id, tf=parts[2] if len(parts) > 2 else "1h"); return
            if parts[:2] == ["help", "corr"]:
                await self._send_corr(chat_id, tf=parts[2], context=context); return
            if parts[:2] == ["help", "beta"]:
                await self._send_beta(chat_id, sym=parts[2], tf=parts[3]); return
            if parts[:2] == ["help", "vol"]:
                await self._send_vol(chat_id, sym=parts[2], tf=parts[3]); return
            if parts[:2] == ["help", "funding"]:
                await self._send_funding(chat_id, base=parts[2]); return
            if parts[:2] == ["help", "basis"]:
                await self._send_basis(chat_id, base=parts[2]); return
            if parts[:2] == ["help", "liqs"]:
                await self._send_liqs(chat_id, base=parts[2]); return
            if parts[:2] == ["help", "levels"]:
                await self._send_levels(chat_id, sym=parts[2], tf=parts[3], context=context); return
            if parts[:2] == ["help", "scan_divs"]:
                await self._send_scan_divs(chat_id, tf=parts[2]); return
            if parts[:2] == ["help", "risk_now"]:
                await self._send_risk_now(chat_id); return
            if parts[:2] == ["help", "breadth"]:
                await self._send_breadth(chat_id, tf=parts[2]); return
            if parts[:2] == ["help", "bt"]:
                await self._send_bt_rsi(chat_id, sym=parts[3], tf=parts[4]); return
            if parts[:2] == ["help", "info"]:
                await self.on_info(chat_id); return
        except Exception:
            logger.exception("on_help_btn failed")

    # ------- helpers for callbacks -------

    async def on_bubbles_settings(self, update, context):
        q = update.callback_query
        await q.answer()
        uid = q.from_user.id
        vs, count, hide, seed, daily, hour, size_mode, top, tf_setting = self.db.get_user_settings(uid)
        
        # Определяем текущий режим размера
        size_mode_labels = {
            "percent": "%",
            "cap": "Капа",
            "volume_share": "Доля объёма",
            "volume_24h": "Объём 24ч"
        }
        size_mode_label = size_mode_labels.get(size_mode, "%")
        
        rows = [
            # Размер пузыря
            [InlineKeyboardButton(f"Размер: {size_mode_label}", callback_data="noop")],
            [InlineKeyboardButton("Размер: %", callback_data="bubbles:set:size_mode=percent"),
             InlineKeyboardButton("Размер: Капа", callback_data="bubbles:set:size_mode=cap")],
            [InlineKeyboardButton("Размер: Доля объёма", callback_data="bubbles:set:size_mode=volume_share"),
             InlineKeyboardButton("Размер: Объём 24ч", callback_data="bubbles:set:size_mode=volume_24h")],
            
            # Количество (n)
            [InlineKeyboardButton("n ◀", callback_data="bubbles:set:count_dec"),
             InlineKeyboardButton(f"n = {count}", callback_data="noop"),
             InlineKeyboardButton("▶", callback_data="bubbles:set:count_inc")],
            
            # Топ (universe)
            [InlineKeyboardButton("Top ◀", callback_data="bubbles:set:top_dec"),
             InlineKeyboardButton(f"Top = {top}", callback_data="noop"),
             InlineKeyboardButton("▶", callback_data="bubbles:set:top_inc")],
            
            # Переключатели
            [InlineKeyboardButton(f"Стейблы: {'OFF' if hide else 'ON'}", 
                                  callback_data=f"bubbles:set:hide={0 if hide else 1}")],
            [InlineKeyboardButton(f"Cap-filter: OFF", callback_data="noop")],
            
            # Действия
            [InlineKeyboardButton("Обновить /bubbles", callback_data="bubbles:refresh")],
            [InlineKeyboardButton("◀ Назад", callback_data="ui:bubbles")],
        ]
        await self._safe_edit_text(q, "Настройки пузырей:", reply_markup=InlineKeyboardMarkup(rows))

    async def on_bubbles_settings_handler(self, update, context):
        """Обработчик всех callback'ов bubbles:set:*"""
        q = update.callback_query
        await q.answer()
        uid = q.from_user.id
        data = q.data
        
        # Получаем текущие настройки
        vs, count, hide, seed, daily, hour, size_mode, top, tf_setting = self.db.get_user_settings(uid)
        
        # Обрабатываем разные типы настроек
        if data.startswith("bubbles:set:size_mode="):
            new_mode = data.split("=", 1)[1]
            self.db.set_user_settings(uid, bubbles_size_mode=new_mode)
            await self.on_bubbles_settings(update, context)
        elif data == "bubbles:set:count_dec":
            new_count = max(10, count - 10)
            self.db.set_user_settings(uid, bubbles_count=new_count)
            await self.on_bubbles_settings(update, context)
        elif data == "bubbles:set:count_inc":
            new_count = min(200, count + 10)
            self.db.set_user_settings(uid, bubbles_count=new_count)
            await self.on_bubbles_settings(update, context)
        elif data == "bubbles:set:top_dec":
            top_options = [100, 200, 300, 400, 500]
            current_idx = next((i for i, v in enumerate(top_options) if v >= top), len(top_options) - 1)
            new_top = top_options[max(0, current_idx - 1)]
            self.db.set_user_settings(uid, bubbles_top=new_top)
            await self.on_bubbles_settings(update, context)
        elif data == "bubbles:set:top_inc":
            top_options = [100, 200, 300, 400, 500]
            current_idx = next((i for i, v in enumerate(top_options) if v >= top), 0)
            new_top = top_options[min(len(top_options) - 1, current_idx + 1)]
            self.db.set_user_settings(uid, bubbles_top=new_top)
            await self.on_bubbles_settings(update, context)
        elif data.startswith("bubbles:set:hide="):
            new_hide = int(data.split("=", 1)[1])
            self.db.set_user_settings(uid, bubbles_hide_stables=new_hide)
            await self.on_bubbles_settings(update, context)
        elif data.startswith("bubbles:set:count="):
            new_count = int(data.split("=", 1)[1])
            self.db.set_user_settings(uid, bubbles_count=new_count)
            await self.on_bubbles_settings(update, context)
        else:
            # Если не распознано, просто обновляем меню
            await self.on_bubbles_settings(update, context)

    async def on_bubbles_refresh(self, update, context):
        """Обновить пузырьки с текущими настройками"""
        q = update.callback_query
        await q.answer()
        uid = q.from_user.id
        vs, count, hide, seed, daily, hour, size_mode, top, tf_setting = self.db.get_user_settings(uid)
        # Используем сохраненный TF из настроек
        await self.on_bubbles(update, context, tf_setting)

    async def on_bubbles_shuffle(self, update, context):
        q = update.callback_query
        await q.answer()
        uid = q.from_user.id
        vs, count, hide, seed, daily, hour, size_mode, top, tf_setting = self.db.get_user_settings(uid)
        self.db.set_user_settings(uid, bubbles_seed=(seed + 1))
        await self._safe_edit_text(q, "⏳ Перемешал. Нажми «Bubbles 1h/24h».")

    async def _send_bubbles(self, chat_id: int, context: ContextTypes.DEFAULT_TYPE, tf: str = "24h"):
        import requests
        try:
            from telegram import InputFile
            from telegram.constants import ParseMode
            from ..infrastructure.coingecko import top_movers
            from ..visual.bubbles import render_bubbles
            import html, math

            logger.warning("BUBBLES_V=rank_override_v4")  # <- новый маркер

            # --- настройки пользователя
            vs_currency, bub_count, bub_hide, bub_seed, _, _, bub_size_mode, bub_top, bub_tf = self.db.get_user_settings(chat_id)

            # --- данные рынка
            try:
                coins, gainers, losers, tf = top_movers(vs=vs_currency, tf=tf, limit_each=5, top=bub_top)
            except requests.exceptions.HTTPError as he:
                if getattr(he.response, "status_code", None) == 429:
                    retry_after = he.response.headers.get("Retry-After")
                    hint = f" Подожди ~{retry_after} сек." if retry_after else " Попробуй через минуту."
                    await context.bot.send_message(chat_id=chat_id,
                                                   text="CoinGecko вернул 429 (лимит запросов)." + hint)
                    return
                raise
            except (requests.exceptions.RetryError, requests.exceptions.RequestException) as e:
                # Если API недоступен, пробуем использовать пустые данные или показать сообщение
                logger.warning(f"CoinGecko API недоступен при получении bubbles: {e}")
                coins, gainers, losers, tf = [], [], [], tf
                # Можно показать сообщение пользователю, но лучше просто показать пустые пузырьки
                # await context.bot.send_message(chat_id=chat_id,
                #                                text="⚠️ CoinGecko API временно недоступен. Показываю последние доступные данные.")
            except Exception as e:
                logger.exception(f"Неожиданная ошибка при получении bubbles: {e}")
                coins, gainers, losers, tf = [], [], [], tf

            logger.info(
                "bubbles: tf=%s vs=%s coins=%d gainers=%d losers=%d settings(count=%s, hide=%s, seed=%s)",
                tf, vs_currency, len(coins), len(gainers), len(losers), bub_count, bub_hide, bub_seed
            )
            if not coins:
                await context.bot.send_message(chat_id=chat_id, text="CoinGecko вернул пустые данные.")
                return

            # Подготовка данных для рендеринга с учетом настроек размера
            def _looks_stable(sym: str) -> bool:
                s = (sym or "").upper()
                if s in {
                    "USDT", "USDC", "DAI", "TUSD", "USDD", "FDUSD", "USDE", "USDS", "USDJ", "BUSD", "PYUSD",
                    "GUSD", "LUSD", "SUSD", "EURS", "BSC-USD", "USD0", "WBTC", "WETH", "STETH", "WSTETH"
                }:
                    return True
                return s.endswith("USD") or s.startswith("USD") or s in {"USDT.E", "USDC.E", "USDT0"}

            # Фильтруем стейблы если нужно
            coins_filtered = []
            for c in coins:
                sym = (c.get("symbol") or c.get("ticker") or "").upper()
                if bool(bub_hide) and _looks_stable(sym):
                    continue
                coins_filtered.append(c)
            
            # Фильтруем стейблы из gainers и losers
            gainers_filtered = []
            for c in gainers:
                sym = (c.get("symbol") or c.get("ticker") or "").upper()
                if bool(bub_hide) and _looks_stable(sym):
                    continue
                gainers_filtered.append(c)
            
            losers_filtered = []
            for c in losers:
                sym = (c.get("symbol") or c.get("ticker") or "").upper()
                if bool(bub_hide) and _looks_stable(sym):
                    continue
                losers_filtered.append(c)
            
            # Гарантируем включение топ 5 растущих и топ 5 падающих монет
            # Создаем словарь для быстрого поиска по символу
            coins_by_sym = {str(c.get("symbol", "")).upper(): c for c in coins_filtered}
            
            # Добавляем топ 5 растущих, если их еще нет в списке
            for gainer in gainers_filtered[:5]:
                sym = str(gainer.get("symbol", "")).upper()
                if sym and sym not in coins_by_sym:
                    coins_by_sym[sym] = gainer
                    coins_filtered.append(gainer)
                    logger.info(f"Added top gainer to bubbles: {sym}")
            
            # Добавляем топ 5 падающих, если их еще нет в списке
            for loser in losers_filtered[:5]:
                sym = str(loser.get("symbol", "")).upper()
                if sym and sym not in coins_by_sym:
                    coins_by_sym[sym] = loser
                    coins_filtered.append(loser)
                    logger.info(f"Added top loser to bubbles: {sym}")

            # Ограничиваем по количеству
            coins_for_render = coins_filtered[:int(bub_count or 50)]
            
            # Вычисляем общий объем для режимов volume_share и volume_24h
            total_volume_24h = sum(float(c.get("total_volume", 0) or 0) for c in coins_filtered)
            
            # Подготавливаем данные для рендеринга в зависимости от режима размера
            if bub_size_mode == "percent":
                # Размер по проценту изменения - передаем как есть, render_bubbles обработает
                pass
            elif bub_size_mode == "cap":
                # Размер по капитализации - уже есть в market_cap
                pass
            elif bub_size_mode in ("volume_share", "volume_24h"):
                # Размер по объему - нужно нормализовать
                for c in coins_for_render:
                    vol = float(c.get("total_volume", 0) or 0)
                    if total_volume_24h > 0:
                        c["volume_share"] = vol / total_volume_24h
                else:
                        c["volume_share"] = 0.0
            # ----------------------------------------------

            # --- картинка
            img_err, png = "", None
            try:
                # Маппинг режима размера для render_bubbles
                size_mode_map = {
                    "percent": "percent",  # новый режим - по проценту изменения
                    "cap": "rank",         # по капитализации (используем rank как было)
                    "volume_share": "volume_share",  # новый режим
                    "volume_24h": "volume_24h"       # новый режим
                }
                render_size_mode = size_mode_map.get(bub_size_mode, "percent")
                
                try:
                    png = render_bubbles(
                        coins_for_render, tf=tf,
                        count=int(bub_count or 50),
                        hide_stables=bool(bub_hide),
                        seed=int(bub_seed or 42),
                        color_mode="quantile",
                        size_mode=render_size_mode,
                    )
                except TypeError:
                    # Fallback для старой версии render_bubbles
                    png = render_bubbles(coins_for_render, tf=tf)
                logger.info("bubbles: render OK (size_mode=%s)", render_size_mode)
            except Exception as e_img:
                img_err = f"(картинку построить не удалось: {type(e_img).__name__})"
                logger.exception("bubbles: render FAIL")

            # --- тексты
            def _fmt_plain(c, vs_currency, tf_):
                sym = str(c.get("symbol", "")).upper()
                px = float(c.get("current_price") or 0.0)
                ch = (c.get("price_change_percentage_1h_in_currency") if tf_ == "1h"
                      else c.get("price_change_percentage_24h_in_currency")) \
                     or c.get("price_change_percentage_1h") \
                     or c.get("price_change_percentage_24h") \
                     or 0.0
                # Формат: FLUX: 0.288413 USD  +12.79%
                return f"{sym}: {px:.6f} {vs_currency.upper()}  {float(ch):+.2f}%"

            # Формируем caption для фото
            size_mode_label = {"percent": "%", "cap": "Капа", "volume_share": "Доля объёма", "volume_24h": "Объём 24ч"}.get(bub_size_mode, "%")
            cap_photo = f"Crypto bubbles — {tf} · n={int(bub_count or 50)} · top{bub_top}"

            # Получаем universe (общее количество монет в выборке)
            universe = len(coins)  # общее количество монет до фильтрации стейблов

            # ВАЖНО: никаких <br> в HTML — используем \n
            gainers_text = "\n".join(_fmt_plain(x, vs_currency, tf) for x in gainers) or "—"
            losers_text = "\n".join(_fmt_plain(x, vs_currency, tf) for x in losers) or "—"

            # Описание размера пузырей
            size_desc_map = {
                "percent": "размер ~ |%|",
                "cap": "размер ~ капа",
                "volume_share": "размер ~ доля объёма",
                "volume_24h": "размер ~ объём 24ч"
            }
            size_desc = size_desc_map.get(bub_size_mode, "размер ~ |%|")

            cap_text_html = (
                f"<b>Crypto movers ({tf})</b>\n\n"
                f"Пузыри: {size_desc}, цвет — изменение (динамическая яркость).\n\n"
                f"(n={int(bub_count or 50)}, universe={universe}, stables={'off' if bub_hide else 'on'})\n\n"
                f"<b>Топ-5 растущих</b>\n\n{gainers_text}\n\n"
                f"<b>Топ-5 падающих</b>\n\n{losers_text}"
            )

            # --- отправка
            if png:
                photo = InputFile(png, filename=f"bubbles_{tf}.png")
                await self.app.bot.send_photo(chat_id=chat_id, photo=photo, caption=cap_photo, parse_mode=None)
                logger.info("bubbles: send_photo OK (short caption)")
                # добавляем развернутый текст отдельным сообщением
                try:
                    await context.bot.send_message(
                        chat_id=chat_id, text=cap_text_html, parse_mode=ParseMode.HTML, disable_web_page_preview=True
                    )
                except Exception:
                    # На всякий случай fallback без HTML
                    logger.exception("bubbles: send_message HTML failed -> retry plain")
                    await context.bot.send_message(chat_id=chat_id, text=cap_text_html)
                return

            # fallback, если не смогли сгенерить/отправить фото
            try:
                await context.bot.send_message(
                    chat_id=chat_id, text=cap_text_html, parse_mode=ParseMode.HTML, disable_web_page_preview=True
                )
            except Exception:
                logger.exception("bubbles: text fallback HTML failed -> retry plain")
                await context.bot.send_message(chat_id=chat_id, text=cap_text_html)
            logger.info("bubbles: sent text fallback")

        except Exception:
            logger.exception("bubbles: general FAIL")
            import traceback
            tb = traceback.format_exc(limit=2)
            await context.bot.send_message(chat_id=chat_id,
                                           text=("Не получилось получить рынок из CoinGecko.\n\n" + tb)[:3500])

    async def on_bubbles(self, update: Update, context: ContextTypes.DEFAULT_TYPE, tf: str = "24h"):
        """Обработчик команды /bubbles с поддержкой новой архитектуры."""
        try:
            # Нормализуем tf: 24h -> 1d
            if tf == "24h":
                tf = "1d"
            # Пытаемся использовать новую архитектуру
            if self.integrator:
                # Сохраняем tf в контекст для интегратора
                context.user_data["tf_bubbles"] = tf
                handled = await self.integrator.handle_command("bubbles", update, context)
                if handled:
                    return
            # Fallback на старый код
            await self._send_bubbles(update.effective_chat.id, context, tf=tf)
        except Exception:
            logger.exception("on_bubbles failed")
            try:
                await self._send_bubbles(update.effective_chat.id, context, tf=tf)
            except Exception:
                logger.exception("on_bubbles legacy also failed")

    # --- SAFE helpers for commands triggered by both text and buttons ---
    def _get_sym_tf_from_update(self, update, context, default_sym="BTC", default_tf="1h"):
        ud = context.user_data
        txt = (getattr(update.effective_message, "text", "") or "").strip()
        parts = txt.split()
        sym = (parts[1] if len(parts) > 1 else ud.get("symbol", default_sym)).upper()
        tf = (parts[2] if len(parts) > 2 else ud.get("tf", default_tf)).lower()
        return sym, tf

    # ==================== FORECAST HANDLERS (callback-safe) ====================

    # --- helpers inside TeleBot -------------------------------------------------

    from telegram.constants import ParseMode
    from telegram.error import BadRequest
    import re

    def _strip_html(text: str) -> str:
        return re.sub(r"<[^>]+>", "", text or "")

    def _fmt_html(text: str) -> str:
        # мелкая нормализация, чтобы не раздувать «жирные» теги и т.п.
        return text.replace("\r", "").strip()

    def _is_callback(update) -> bool:
        return getattr(update, "callback_query", None) is not None

    # === ВСТАВИТЬ ВНУТРИ class TeleBot: =========================================

    def _get_message_obj(self, update):
        """
        Возвращает объект Message, к которому можно «reply_text».
        Работает и для callback_query, и для обычных сообщений.
        """
        q = getattr(update, "callback_query", None)
        if q and q.message:
            return q.message
        msg = getattr(update, "effective_message", None)
        if msg:
            return msg
        return None  # крайне редкий случай: отправим через bot.send_message в _reply_text_safe

    def _parse_cmd_args(self, update, default_sym: str = "BTC", default_tf: str = "1h"):
        """
        Единый парсер аргументов для слэш-команд И нажатий на кнопки.
        Сигнатура ВАЖНА: (self, update, default_sym=..., default_tf=...)
        """
        msg = getattr(update, "effective_message", None)
        text = (getattr(msg, "text", "") or "").strip()
        if text.startswith("/"):
            parts = text.split()
            sym = (parts[1] if len(parts) > 1 else default_sym).upper()
            tf = (parts[2] if len(parts) > 2 else default_tf).lower()
        else:
            sym, tf = default_sym, default_tf
        return sym, tf

    async def _reply_text_safe(self, update, text_html: str):
        """
        Безопасная отправка текста: пробуем HTML, при BadRequest падаем в plain.
        Работает и для сообщений, и для callback-кнопок.
        """
        from telegram.constants import ParseMode
        from telegram.error import BadRequest
        import re

        def _strip_html(t: str) -> str:
            return re.sub(r"<[^>]+>", "", t or "")

        def _fmt_html(t: str) -> str:
            return (t or "").replace("\r", "").strip()

        msg_obj = self._get_message_obj(update)
        if msg_obj is not None:
            try:
                return await msg_obj.reply_text(
                    _fmt_html(text_html),
                    parse_mode=ParseMode.HTML,
                    disable_web_page_preview=True
                )
            except BadRequest:
                # телега не смогла распарсить HTML — шлём плэйн
                return await msg_obj.reply_text(
                    _strip_html(text_html),
                    disable_web_page_preview=True
                )

        # Фолбэк, если вдруг Message нет (редко встречается)
        chat = getattr(update, "effective_chat", None)
        chat_id = getattr(chat, "id", None)
        if chat_id is not None:
            try:
                return await self.app.bot.send_message(
                    chat_id=chat_id,
                    text=_fmt_html(text_html),
                    parse_mode=ParseMode.HTML,
                    disable_web_page_preview=True
                )
            except BadRequest:
                return await self.app.bot.send_message(
                    chat_id=chat_id,
                    text=_strip_html(text_html),
                    disable_web_page_preview=True
                )
        return None

    # --- forecasts --------------------------------------------------------------

    async def cmd_forecast(self, update, context):
        """Обработчик команды /forecast с поддержкой новой архитектуры."""
        try:
            if self.integrator:
                handled = await self.integrator.handle_command("forecast", update, context)
                if handled:
                    return
            await self._cmd_forecast_legacy(update, context)
        except Exception:
            logger.exception("cmd_forecast failed")
            try:
                await self._cmd_forecast_legacy(update, context)
            except Exception:
                logger.exception("cmd_forecast legacy also failed")
    
    async def _cmd_forecast_legacy(self, update, context):
        """Старая реализация команды /forecast."""
        from ..ml.data_adapter import make_loader, load_bars_from_project
        from ..ml.forecaster import forecast_symbol

        sym, tf = self._parse_cmd_args(update)
        horizon = 24 if tf == "1h" else (6 if tf == "4h" else 1)

        try:
            loader = make_loader()
            res = forecast_symbol(loader, sym, tf, horizon=horizon)

            df = load_bars_from_project(sym, tf, limit=500)
            last_close = float(df["close"].iloc[-1])
            target_price = last_close * (1.0 + float(res["ret_pred"]))

            text = (
                f"<b>Прогноз {sym} ({tf}, +{horizon} бар)</b>\n"
                f"Ожидание: <b>{res['ret_pred'] * 100:+.2f}%</b>\n"
                f"P(up): <b>{res['p_up']:.2f}</b>\n"
                f"Цель: <b>{target_price:.6g}</b> (текущая {last_close:.6g})\n"
                f"<i>MAE(walk): {res['meta'].get('MAE_walk', float('nan')):.4f}, "
                f"AUC(walk): {res['meta'].get('AUC_walk', float('nan')):.3f}</i>"
            )
        except Exception as e:
            text = f"Не удалось посчитать прогноз: {type(e).__name__}: {e}"

        await self._reply_text_safe(update, text)

    async def cmd_forecast3(self, update, context):
        """Обработчик команды /forecast3 с поддержкой новой архитектуры."""
        try:
            if self.integrator:
                # forecast3 пока используем старый код
                handled = False
                if handled:
                    return
            await self._cmd_forecast3_legacy(update, context)
        except Exception:
            logger.exception("cmd_forecast3 failed")
            try:
                await self._cmd_forecast3_legacy(update, context)
            except Exception:
                logger.exception("cmd_forecast3 legacy also failed")
    
    async def _cmd_forecast3_legacy(self, update, context):
        """
        Старая реализация команды /forecast3.
        Прогноз BTC: 1h / 4h / 24h + мини-чарт по 24h с оранжевым прогнозным участком.
        Работает и по слэш-команде, и с кнопки.
        """
        from io import BytesIO
        import numpy as np
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        from telegram import InputFile

        from ..ml.data_adapter import make_loader, load_bars_from_project
        from ..ml.forecaster import forecast_symbol

        # ---- входные аргументы (унифицированно для слэшей и кнопок)
        sym, _ = self._parse_cmd_args(update, default_sym="BTC", default_tf="1h")

        tfs = [("1h", 24), ("4h", 6), ("24h", 1)]
        loader = make_loader()

        # ---- текстовая часть (как у тебя было)
        lines = [f"<b>Прогноз {sym}: 1h / 4h / 24h</b>"]
        results = {}  # сохраним, пригодится для подписи к графику
        for tf, horizon in tfs:
            try:
                res = forecast_symbol(loader, sym, tf, horizon=horizon)
                df = load_bars_from_project(sym, tf, limit=400)
                last_close = float(df["close"].iloc[-1])
                tgt = last_close * (1.0 + float(res["ret_pred"]))
                results[tf] = (res, last_close, tgt, horizon)
                lines.append(
                    f"<b>{tf}</b>: {res['ret_pred'] * 100:+.2f}% | "
                    f"P(up)={res['p_up']:.2f} | цель: <b>{tgt:.6g}</b> "
                    f"(текущая {last_close:.6g})"
                )
            except Exception as e:
                lines.append(f"<b>{tf}</b>: ошибка {type(e).__name__}: {e}")

        # ---- график по 24h с прогнозом на сутки (+1 бар)
        try:
            # если 24h уже посчитали выше — используем; иначе посчитаем тут
            if "24h" not in results:
                res24 = forecast_symbol(loader, sym, "24h", horizon=1)
                df24 = load_bars_from_project(sym, "24h", limit=1200)
                last_close24 = float(df24["close"].iloc[-1])
                tgt24 = last_close24 * (1.0 + float(res24["ret_pred"]))
                results["24h"] = (res24, last_close24, tgt24, 1)
            else:
                res24, last_close24, tgt24, _ = results["24h"]
                df24 = load_bars_from_project(sym, "24h", limit=1200)

            df24 = df24.tail(300).copy()
            last_ts = df24["ts"].iloc[-1]
            # шаг по времени (между последними двумя барами)
            step = (df24["ts"].iloc[-1] - df24["ts"].iloc[-2])

            # оценим «баровую» волу и доверительный интервал ~68% (для справки в caption)
            ret_bar = df24["close"].pct_change().dropna()
            sigma = float(ret_bar.tail(200).std())
            ci68 = (res24["ret_pred"] - sigma, res24["ret_pred"] + sigma)
            lo68_price = last_close24 * (1.0 + ci68[0])
            hi68_price = last_close24 * (1.0 + ci68[1])

            # --- рисуем
            fig, ax = plt.subplots(figsize=(9.6, 4.8), dpi=150)
            ax.plot(df24["ts"], df24["close"], lw=1.6)

            # последний известный бар и целевая точка прогноза
            ax.scatter([last_ts], [last_close24], s=28)
            ax.scatter([last_ts + step], [tgt24], s=46)

            # прогнозный участок (оранжевый)
            ax.axvspan(last_ts, last_ts + step, color="#ff9900", alpha=0.15)

            # горизонтальные линии цели и 68%-ДИ
            ax.axhline(tgt24, ls="--", lw=1.1, alpha=0.7)
            ax.axhline(lo68_price, ls=":", lw=1.0, alpha=0.5)
            ax.axhline(hi68_price, ls=":", lw=1.0, alpha=0.5)

            ax.set_title(
                f"{sym} — 24h (+1 бар) · цель ≈ {tgt24:.4g} ({res24['ret_pred'] * 100:+.2f}%) · P(up)={res24['p_up']:.2f}")
            ax.grid(alpha=0.25)
            fig.tight_layout()

            buf = BytesIO()
            fig.savefig(buf, format="png")
            plt.close(fig)
            buf.seek(0)

            # короткий caption без parse_mode, чтобы не словить HTML-ошибок
            caption = (
                f"{sym} — 24h (+1 бар)\n"
                f"Текущая: {last_close24:.4g}\n"
                f"Цель: ~{tgt24:.4g} ({res24['ret_pred'] * 100:+.2f}%)\n"
                f"P(up): {res24['p_up']:.2f}"
            )

            chat_id = update.effective_chat.id
            await context.bot.send_photo(
                chat_id=chat_id,
                photo=InputFile(buf, filename=f"{sym}_forecast_24h.png"),
                caption=caption,
                parse_mode=None  # ВАЖНО: не парсить caption
            )
        except Exception:
            # не роняем команду из-за графика — просто залогируем
            logger.exception("forecast3: chart build/send failed")

        # ---- отправляем текст (HTML через безопасный хелпер)
        await self._reply_text_safe(update, "\n".join(lines))

    async def cmd_forecast_full(self, update, context):
        """Обработчик команды /forecast_full с поддержкой новой архитектуры."""
        try:
            if self.integrator:
                handled = await self.integrator.handle_command("forecast_full", update, context)
                if handled:
                    return
            await self._cmd_forecast_full_legacy(update, context)
        except Exception:
            logger.exception("cmd_forecast_full failed")
            try:
                await self._cmd_forecast_full_legacy(update, context)
            except Exception:
                logger.exception("cmd_forecast_full legacy also failed")
    
    async def _cmd_forecast_full_legacy(self, update, context):
        """Старая реализация команды /forecast_full."""
        from io import BytesIO
        import numpy as np
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from telegram import InputFile

        from ..ml.data_adapter import make_loader, load_bars_from_project
        from ..ml.forecaster import forecast_symbol

        sym, tf = self._parse_cmd_args(update, default_sym="BTC", default_tf="1h")
        horizon = 24 if tf == "1h" else (6 if tf == "4h" else 1)

        try:
            loader = make_loader()
            res = forecast_symbol(loader, sym, tf, horizon=horizon)

            df = load_bars_from_project(sym, tf, limit=1200).tail(400)
            last_ts = df["ts"].iloc[-1]
            last_close = float(df["close"].iloc[-1])

            # доверительные интервалы по исторической волатильности
            ret_bar = df["close"].pct_change().dropna()
            sigma = float(ret_bar.tail(500).std())
            rh = np.sqrt(max(1, horizon)) * sigma
            ci68 = (res["ret_pred"] - rh, res["ret_pred"] + rh)
            ci95 = (res["ret_pred"] - 2 * rh, res["ret_pred"] + 2 * rh)

            target_price = last_close * (1.0 + float(res["ret_pred"]))
            lo68_price = last_close * (1.0 + ci68[0])
            hi68_price = last_close * (1.0 + ci68[1])

            # график
            fig, ax = plt.subplots(figsize=(9.5, 5.0), dpi=160)
            ax.plot(df["ts"], df["close"], lw=1.6)
            ax.scatter([last_ts], [last_close], s=36)
            ax.scatter([last_ts], [target_price], s=60, color="orange")
            step = (df["ts"].iloc[-1] - df["ts"].iloc[-2])
            ax.axvspan(last_ts, last_ts + step * horizon, color="orange", alpha=0.10)
            ax.axhline(target_price, ls="--", lw=1.2, alpha=0.6, color="orange")
            ax.axhline(lo68_price, ls=":", lw=1.0, alpha=0.5)
            ax.axhline(hi68_price, ls=":", lw=1.0, alpha=0.5)
            ax.set_title(f"{sym} forecast — {tf} (+{horizon} bar)")
            ax.grid(alpha=0.25)
            fig.tight_layout()

            buf = BytesIO()
            fig.savefig(buf, format="png")
            plt.close(fig)
            buf.seek(0)

            caption = (
                f"{sym} — {tf}  +{horizon} бар\n"
                f"Текущая: {last_close:.4g}\n"
                f"Цель: ~{target_price:.4g} ({res['ret_pred'] * 100:+.2f}%)\n"
                f"P(up): {res['p_up']:.2f}"
            )
            await context.bot.send_photo(
                chat_id=update.effective_chat.id,
                photo=InputFile(buf, filename=f"{sym}_{tf}_forecast.png"),
                caption=caption,
                parse_mode=None
            )

            regime = (
                "🟢 бычий" if (res["p_up"] >= 0.6 and res["ret_pred"] > 0)
                else "🔴 медвежий" if (res["p_up"] <= 0.4 and res["ret_pred"] < 0)
                else "⚪ нейтральный"
            )
            long_msg = (
                f"<b>Полный прогноз {sym} ({tf}, +{horizon} бар)</b>\n"
                f"Ожидание: <b>{res['ret_pred'] * 100:+.2f}%</b>   "
                f"P(up): <b>{res['p_up']:.2f}</b>   Режим: <b>{regime}</b>\n"
                f"Текущая цена: <b>{last_close:.6g}</b>\n"
                f"Целевой уровень: <b>{target_price:.6g}</b>\n"
                f"ДИ 68%: <b>{ci68[0] * 100:+.2f}% … {ci68[1] * 100:+.2f}%</b>\n"
                f"ДИ 95%: <b>{ci95[0] * 100:+.2f}% … {ci95[1] * 100:+.2f}%</b>\n"
                f"<i>MAE(walk): {res['meta'].get('MAE_walk', float('nan')):.4f}, "
                f"AUC(walk): {res['meta'].get('AUC_walk', float('nan')):.3f}, "
                f"N(train): {res['meta'].get('n_train', '—')}</i>"
            )
            await self._reply_text_safe(update, long_msg)

        except Exception as e:
            await self._reply_text_safe(update, f"Не удалось собрать полный прогноз: {type(e).__name__}: {e}")

    async def cmd_forecast_alts(self, update, context):
        """Обработчик команды /forecast_alts с поддержкой новой архитектуры."""
        try:
            if self.integrator:
                handled = await self.integrator.handle_command("forecast_alts", update, context)
                if handled:
                    return
            await self._cmd_forecast_alts_legacy(update, context)
        except Exception:
            logger.exception("cmd_forecast_alts failed")
            try:
                await self._cmd_forecast_alts_legacy(update, context)
            except Exception:
                logger.exception("cmd_forecast_alts legacy also failed")
    
    async def cmd_forecast_stats(self, update, context):
        """Обработчик команды /forecast_stats с поддержкой новой архитектуры."""
        try:
            if self.integrator:
                handled = await self.integrator.handle_command("forecast_stats", update, context)
                if handled:
                    return
            # Fallback сообщение, если интегратор недоступен
            await update.effective_message.reply_text(
                "❌ Команда /forecast_stats временно недоступна. Попробуйте позже.",
                parse_mode=ParseMode.HTML
            )
        except Exception:
            logger.exception("cmd_forecast_stats failed")
            try:
                await update.effective_message.reply_text(
                    "❌ Ошибка при получении статистики прогнозов.",
                    parse_mode=ParseMode.HTML
                )
            except Exception:
                pass
    
    async def _cmd_forecast_alts_legacy(self, update, context):
        """Старая реализация команды /forecast_alts."""
        from telegram.constants import ParseMode
        from ..infrastructure.coingecko import top_movers
        from ..ml.data_adapter import make_loader, _symbol_norm
        from ..ml.forecaster import forecast_symbol

        loader = make_loader()
        vs = "usd"
        try:
            coins, gainers, losers, _ = top_movers(vs=vs, tf="24h", limit_each=24)
        except Exception as e:
            await update.effective_message.reply_text(f"Не удалось получить список альтов: {e}")
            return

        def _is_ok(sym):
            s = (sym or "").upper()
            return s not in {"BTC", "WBTC", "USDT", "USDC", "DAI", "BUSD", "TUSD", "FDUSD", "PYUSD", "EURS",
                             "SUSD", "LUSD", "USDD", "USDJ", "USDE", "USDS", "GUSD", "USD0", "BSC-USD",
                             "STETH", "WSTETH", "WETH"}

        top10 = [c for c in sorted(coins, key=lambda x: float(x.get("market_cap") or 0), reverse=True) if
                 _is_ok(c.get("symbol"))][:10]
        movers24 = [c for c in (gainers[:12] + losers[:12]) if _is_ok(c.get("symbol"))]

        async def _do_batch(title, arr, tf_for_model="1h", horizon=24):
            lines = [f"<b>{title}</b>  ({tf_for_model}, +{horizon} бар)"]
            for c in arr:
                sym = _symbol_norm(c.get("symbol") or "")
                try:
                    res = forecast_symbol(loader, sym, tf_for_model, horizon=horizon)
                    lines.append(f"{sym}: {res['ret_pred'] * 100:+.2f}% · P(up)={res['p_up']:.2f}")
                except Exception as e:
                    lines.append(f"{sym}: ошибка {type(e).__name__}")
            await update.effective_message.reply_text(
                "\n".join(lines), parse_mode=ParseMode.HTML, disable_web_page_preview=True
            )

        await _do_batch("Топ-10 по капитализации (альты)", top10, tf_for_model="1h", horizon=24)
        await _do_batch("Топ-24 суточных муверов (12↑/12↓)", movers24, tf_for_model="1h", horizon=24)

    async def cmd_forecast_from_btn(self, update, context):
        return await self.cmd_forecast(update, context)

    async def cmd_forecast3_from_btn(self, update, context):
        return await self.cmd_forecast3(update, context)

    async def cmd_forecast_full_from_btn(self, update, context):
        return await self.cmd_forecast_full(update, context)

    async def cmd_forecast_alts_from_btn(self, update, context):
        return await self.cmd_forecast_alts(update, context)

    async def on_main_btn(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        logger.info("on_main_btn: got callback data=%r chat_id=%s", update.callback_query.data,
                    update.effective_chat.id)
        q = update.callback_query
        await q.answer()
        chat_id = update.effective_chat.id
        data = q.data
        try:
            if data == "report":
                await self._send_html(chat_id, self._build_compact_safe(), reply_markup=self._kb('main'))
            elif data == "subscribe":
                self.db.add_sub(chat_id)
                await context.bot.send_message(chat_id=chat_id, text="Подписал на авто-обновления. /unsubscribe — отписка.")
            elif data == "unsubscribe":
                self.db.remove_sub(chat_id)
                await context.bot.send_message(chat_id=chat_id, text="Подписка отключена.")
            elif data.startswith("bubbles:"):
                tf = data.split(":", 1)[1]
                logger.info("on_main_btn: bubbles tf=%s", tf)
                await self._send_bubbles(chat_id, context, tf=tf)
        except Exception:
            logger.exception("on_main_btn failed")

    async def on_categories_btn(self, update, context):
        """Обработчик callback для категорий с поддержкой новой архитектуры."""
        try:
            q = update.callback_query
            if not q:
                return
            
            data = q.data
            
            # Обрабатываем кнопки "Тренды" и "Глобалка" из меню категорий
            if data == "categories:trending":
                if self.integrator:
                    handled = await self.integrator.handle_command("trending", update, context)
                    if handled:
                        return
                await self.on_trending(update, context)
                return
            elif data == "categories:global":
                if self.integrator:
                    handled = await self.integrator.handle_command("global", update, context)
                    if handled:
                        return
                await self.on_global(update, context)
                return
            
            # Обычное меню категорий
            if self.integrator and hasattr(self.integrator.handlers.get("top_flop"), "handle_categories"):
                await self.integrator.handlers["top_flop"].handle_categories(update, context)
                return
            await self._on_categories_btn_legacy(update, context)
        except Exception:
            logger.exception("on_categories_btn failed")
            try:
                await self._on_categories_btn_legacy(update, context)
            except Exception:
                logger.exception("on_categories_btn legacy also failed")
    
    async def _on_categories_btn_legacy(self, update, context):
        """Старая реализация callback для категорий."""
        from ..infrastructure.coingecko import categories
        q = update.callback_query;
        await q.answer()
        cats = categories()
        # берём популярные
        names = [c.get("id") for c in cats if c.get("market_cap")][:12]  # 12 кнопок
        rows = []
        for i in range(0, len(names), 3):
            chunk = names[i:i + 3]
            rows.append([InlineKeyboardButton(n[:20], callback_data=f"cat:select:{n}") for n in chunk])
        rows.append([InlineKeyboardButton("🔥 Тренды", callback_data="categories:trending"),
                     InlineKeyboardButton("🌍 Глобалка", callback_data="categories:global")])
        kb = InlineKeyboardMarkup(rows)
        await self._safe_edit_text(q, "Выбери категорию:", reply_markup=kb)

    async def on_category_pick(self, update, context):
        """Обработчик выбора категории с поддержкой новой архитектуры."""
        try:
            if self.integrator and hasattr(self.integrator.handlers.get("top_flop"), "handle_category_pick"):
                await self.integrator.handlers["top_flop"].handle_category_pick(update, context)
                return
            await self._on_category_pick_legacy(update, context)
        except Exception:
            logger.exception("on_category_pick failed")
            try:
                await self._on_category_pick_legacy(update, context)
            except Exception:
                logger.exception("on_category_pick legacy also failed")
    
    async def _on_category_pick_legacy(self, update, context):
        """Старая реализация выбора категории."""
        from ..infrastructure.coingecko import markets_by_category
        q = update.callback_query;
        await q.answer()
        cat = q.data.split(":", 2)[2]
        data = markets_by_category(cat, vs="usd")
        if not data:
            await self._safe_edit_text(q, f"Нет данных для категории {cat}")
            return

        def chg(c, key):
            return float(c.get(key) or 0.0)

        # топ/флоп за 24ч
        sorted24 = sorted(data, key=lambda c: chg(c, "price_change_percentage_24h_in_currency"), reverse=True)
        gain = sorted24[:5];
        loss = list(reversed(sorted24))[:5]

        def fmt(c):
            return f"{c['symbol'].upper():<6} {c['current_price']:.4g} USD ({(c.get('price_change_percentage_24h_in_currency') or 0):+,.2f}%)"

        text = f"*Категория*: `{cat}`\n\n*Топ-5 24h*\n" + "\n".join(map(fmt, gain)) + "\n\n*Флоп-5 24h*\n" + "\n".join(
            map(fmt, loss))
        await self._safe_edit_text(q, text, parse_mode=ParseMode.MARKDOWN, disable_web_page_preview=True)

    async def on_trending(self, update, context):
        """Обработчик команды /trending с поддержкой новой архитектуры."""
        try:
            if self.integrator:
                handled = await self.integrator.handle_command("trending", update, context)
                if handled:
                    return
            await self._on_trending_legacy(update, context)
        except Exception:
            logger.exception("on_trending failed")
            try:
                await self._on_trending_legacy(update, context)
            except Exception:
                logger.exception("on_trending legacy also failed")
    
    async def _on_trending_legacy(self, update, context):
        """Старая реализация команды /trending."""
        from ..infrastructure.coingecko import trending
        chat_id = update.effective_chat.id
        tr = trending()
        coins = tr.get("coins", [])
        if not coins:
            await context.bot.send_message(chat_id=chat_id, text="Тренды: пусто")
            return
        lines = []
        for item in coins[:10]:
            c = item.get("item", {})
            lines.append(f"{c.get('symbol', '').upper():<6} rank{c.get('market_cap_rank')}  score {c.get('score')}")
        await context.bot.send_message(chat_id=chat_id, text="🔥 *Trending*\n" + "\n".join(lines),
                                       parse_mode=ParseMode.MARKDOWN)

    async def on_global(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик команды /global с поддержкой новой архитектуры."""
        try:
            if self.integrator:
                handled = await self.integrator.handle_command("global", update, context)
                if handled:
                    return
            await self._on_global_legacy(update, context)
        except Exception:
            logger.exception("on_global failed")
            try:
                await self._on_global_legacy(update, context)
            except Exception:
                logger.exception("on_global legacy also failed")
    
    async def _on_global_legacy(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        Старая реализация команды /global.
        Глобальные метрики рынка:
        - total market cap (в выбранной валюте), + % за 24ч (из CG)
        - total 24h volume (в выбранной валюте), + дельта к прошлому вызову
        - BTC dominance, + дельта
        - active cryptocurrencies, + дельта
        - DeFi market cap (в USD у CG), + дельта
        Поддержка: /global [CURRENCY], напр. /global EUR
        """
        # ------ 1) Разбор аргумента валюты ------
        parts = (getattr(update.effective_message, "text", "") or "").split()
        cur_code = (parts[1] if len(parts) > 1 else "USD").upper()

        # ------ 2) Источники CoinGecko ------
        from ..infrastructure.coingecko import global_stats, defi_global
        chat_id = update.effective_chat.id

        g = (global_stats() or {}).get("data", {}) or {}
        d = (defi_global() or {}).get("data", {}) or {}

        # total_market_cap / total_volume у CG — это мапы по валютам
        mcap_map = g.get("total_market_cap", {}) or {}
        vol_map = g.get("total_volume", {}) or {}
        btc_d = g.get("market_cap_percentage", {}).get("btc")
        actv = g.get("active_cryptocurrencies")
        defi_usd = d.get("defi_market_cap")  # у CG для DeFi в USD

        # Берём значения в нужной валюте (если нет — попробуем USD)
        def pick(map_obj, code, fallback="USD"):
            if not isinstance(map_obj, dict):
                return None
            return map_obj.get(code.lower()) or map_obj.get(code.upper()) or map_obj.get(fallback.lower())

        mcap = pick(mcap_map, cur_code)
        vol = pick(vol_map, cur_code)
        # % изменения капы CG отдаёт только в USD
        mcap_ch_pct = g.get("market_cap_change_percentage_24h_usd")

        # ------ 3) Fallback (не обязателен): Alternative.me ------
        # Если что-то не пришло с CG и есть self.indices — подставим оттуда
        alt = None
        if (mcap is None or vol is None or btc_d in (None, 0)) and hasattr(self, "indices"):
            try:
                alt = await self.indices.get_global(convert=cur_code)
            except Exception:
                alt = None

        if mcap is None and alt:
            mcap = alt.get("total_market_cap")
        if vol is None and alt:
            vol = alt.get("total_volume_24h")
        if (btc_d is None or btc_d == 0) and alt:
            btc_d = alt.get("btc_dominance")

        cur = {
            "code": cur_code,
            "mcap": mcap,
            "vol": vol,
            "btc_d": btc_d,
            "actv": actv,
            "defi": defi_usd,  # остаётся в USD — это особенность CG эндпоинта
        }

        # ------ 4) Вычисление дельт к прошлому вызову (на валюту) ------
        def pct(cur_v, prev_v):
            try:
                cur_v = float(cur_v);
                prev_v = float(prev_v)
                if prev_v == 0:
                    return None
                return (cur_v / prev_v - 1.0) * 100.0
            except Exception:
                return None

        # Храним последние значения по каждой валюте: self._global_last = {"USD": {...}, "EUR": {...}}
        if not hasattr(self, "_global_last") or not isinstance(self._global_last, dict):
            self._global_last = {}

        prev = self._global_last.get(cur_code, {}) or {}
        vol_ch = pct(cur["vol"], prev.get("vol"))
        btc_ch = pct(cur["btc_d"], prev.get("btc_d"))
        actv_ch = pct(cur["actv"], prev.get("actv"))
        defi_ch = pct(cur["defi"], prev.get("defi"))

        # Обновим «последние» по этой валюте
        self._global_last[cur_code] = cur

        # ------ 5) Форматирование ------
        CURRENCY_SIGNS = {
            "USD": "$", "EUR": "€", "GBP": "£", "RUB": "₽", "UAH": "₴", "KZT": "₸",
            "TRY": "₺", "JPY": "¥", "CNY": "¥", "KRW": "₩", "AUD": "A$", "CAD": "C$",
        }
        sign = CURRENCY_SIGNS.get(cur_code, f"{cur_code} ")

        def fmt_money(x):
            try:
                v = float(x)
                # укороченная запись: T/B/M
                for suffix, p in (("T", 1e12), ("B", 1e9), ("M", 1e6)):
                    if v >= p:
                        return f"{sign}{v / p:,.2f}{suffix}".replace(",", " ")
                return f"{sign}{v:,.0f}".replace(",", " ")
            except Exception:
                return "—"

        def fmt_pct(x):
            return (f"{float(x):+,.2f}%".replace(",", " ")) if x is not None else "—"

        def fmt_num(x):
            try:
                return f"{int(x):,}".replace(",", " ")
            except Exception:
                return "—"

        # ------ 6) Сообщение ------
        # DeFi капу явно помечаем валютой (USD), чтобы не вводить в заблуждение.
        text = (
            "🌍 <b>Глобальные метрики</b>\n"
            f"• Капа: {fmt_money(cur['mcap'])}  ({fmt_pct(mcap_ch_pct) if mcap_ch_pct is not None else '—'})\n"
            f"• 24ч объём: {fmt_money(cur['vol'])}  ({fmt_pct(vol_ch)})\n"
            f"• BTC доминация: {float(cur['btc_d'] or 0):.2f}%  ({fmt_pct(btc_ch)})\n"
            f"• Активных монет: {fmt_num(cur['actv'])}  ({fmt_pct(actv_ch)})\n"
            f"• DeFi market cap (USD): {fmt_money(cur['defi'])}  ({fmt_pct(defi_ch)})"
        )

        await self._send_html(chat_id, text, reply_markup=build_kb("more"))

    async def on_ticker(self, update, context):
        """Обработчик команды /ticker с поддержкой новой архитектуры."""
        try:
            if self.integrator:
                handled = await self.integrator.handle_command("ticker", update, context)
                if handled:
                    return
            await self._on_ticker_legacy(update, context)
        except Exception:
            logger.exception("on_ticker failed")
            try:
                await self._on_ticker_legacy(update, context)
            except Exception:
                logger.exception("on_ticker legacy also failed")
    
    async def _on_ticker_legacy(self, update, context):
        """Старая реализация команды /ticker."""
        parts = (getattr(update.effective_message, "text", "") or "").split()

        # sort
        allowed_sorts = {"rank", "percent_change_1h", "percent_change_24h", "percent_change_7d", "volume_24h",
                         "market_cap"}
        sort = parts[1].lower() if len(parts) > 1 and parts[1].lower() in allowed_sorts else "rank"

        # limit
        limit = 20
        if len(parts) > 2:
            try:
                limit = int(parts[2])
            except Exception:
                limit = 20
        limit = max(5, min(limit, 50))

        # convert
        convert = parts[3].upper() if len(parts) > 3 and len(parts[3]) in (3, 4) else "USD"

        rows = await self.indices.get_ticker(limit=limit, sort=sort, convert=convert, structure="array")
        if not rows:
            return await self._send_html(update.effective_chat.id, "Нет данных тикера.", reply_markup=build_kb("more"))

        head = f"<b>/ticker</b> — sort: <code>{sort}</code>, limit: <code>{limit}</code>, convert: <code>{convert}</code>\n"
        lines = [head]
        for r in rows:
            price = f'{r["price"]:.4f} {convert}'
            p1h = f'{r["percent_change_1h"]:+.2f}%'
            p24h = f'{r["percent_change_24h"]:+.2f}%'
            p7d = f'{r["percent_change_7d"]:+.2f}%'
            vol = _fmt_money(r["volume_24h"], convert)
            mc = _fmt_money(r["market_cap"], convert)
            lines.append(
                f"<b>{r['rank'] or '—'}. {r['symbol']}</b> — {r['name']}\n"
                f"Цена: {price}; 1h: {p1h}; 24h: {p24h}; 7d: {p7d}\n"
                f"Vol24h: {vol}; MC: {mc}\n"
            )
        text = "\n".join(lines)
        if len(text) > 4000:
            text = text[:4000] + "\n…"
        await self._send_html(update.effective_chat.id, text, reply_markup=build_kb("more"))

    async def on_top(self, update, context):
        """Обработчик команды /top с поддержкой новой архитектуры."""
        try:
            if self.integrator:
                handled = await self.integrator.handle_command("top_24h", update, context)
                if handled:
                    return
            await self._on_top_legacy(update, context)
        except Exception:
            logger.exception("on_top failed")
            try:
                await self._on_top_legacy(update, context)
            except Exception:
                logger.exception("on_top legacy also failed")
    
    async def _on_top_legacy(self, update, context):
        """Старая реализация команды /top."""
        # /top 24h|1h|7d (по умолчанию 24h)
        tf = (context.args[0] if context.args else "24h").lower()
        from ..infrastructure.coingecko import markets_snapshot
        data = markets_snapshot("usd")

        def change(c):
            if tf == "1h":
                k = ("price_change_percentage_1h_in_currency", "price_change_percentage_1h")
            elif tf == "7d":
                k = ("price_change_percentage_7d_in_currency", "price_change_percentage_7d")
            else:
                k = ("price_change_percentage_24h_in_currency", "price_change_percentage_24h")
            v = c.get(k[0], c.get(k[1], 0.0));
            return float(v or 0.0)

        rows = sorted([c for c in data if c.get("symbol")], key=change, reverse=True)
        await self._send_rank_page(update.effective_chat.id, context, rows, tf, kind="top", page=1)

    async def on_flop(self, update, context):
        """Обработчик команды /flop с поддержкой новой архитектуры."""
        try:
            if self.integrator:
                handled = await self.integrator.handle_command("flop_24h", update, context)
                if handled:
                    return
            await self._on_flop_legacy(update, context)
        except Exception:
            logger.exception("on_flop failed")
            try:
                await self._on_flop_legacy(update, context)
            except Exception:
                logger.exception("on_flop legacy also failed")
    
    async def _on_flop_legacy(self, update, context):
        """Старая реализация команды /flop."""
        tf = (context.args[0] if context.args else "24h").lower()
        from ..infrastructure.coingecko import markets_snapshot
        data = markets_snapshot("usd")

        def change(c):
            if tf == "1h":
                k = ("price_change_percentage_1h_in_currency", "price_change_percentage_1h")
            elif tf == "7d":
                k = ("price_change_percentage_7d_in_currency", "price_change_percentage_7d")
            else:
                k = ("price_change_percentage_24h_in_currency", "price_change_percentage_24h")
            v = c.get(k[0], c.get(k[1], 0.0));
            return float(v or 0.0)

        rows = sorted([c for c in data if c.get("symbol")], key=change, reverse=False)
        await self._send_rank_page(update.effective_chat.id, context, rows, tf, kind="flop", page=1)

    def _rank_page(self, rows, page: int, per: int = 20):
        """Пагинация списка. Возвращает (page_rows, page, total)."""
        total = max(1, (len(rows) + per - 1) // per)
        page = max(1, min(int(page), total))
        s = (page - 1) * per
        e = min(len(rows), s + per)
        return rows[s:e], page, total

    async def _send_rank_page(self, chat_id: int, context: ContextTypes.DEFAULT_TYPE, rows, tf: str, kind: str,
                              page: int = 1):
        # rows — список словарей CoinGecko (из snapshot), уже отсортирован
        per = 20
        page_rows, page, total = self._rank_page(rows, page, per)

        def fmt(c):
            sym = html.escape(str(c.get("symbol", "")).upper())
            name = html.escape(str(c.get("name", "")))
            px = float(c.get("current_price") or 0.0)
            if tf == "1h":
                ch = c.get("price_change_percentage_1h_in_currency") or c.get("price_change_percentage_1h") or 0.0
            elif tf == "7d":
                ch = c.get("price_change_percentage_7d_in_currency") or c.get("price_change_percentage_7d") or 0.0
            else:
                ch = c.get("price_change_percentage_24h_in_currency") or c.get("price_change_percentage_24h") or 0.0
            return f"{sym} — {name}: {px:.4g} USD  ({float(ch):+,.2f}%)"

        title = "🏆 ТОП" if kind == "top" else "🔻 ФЛОП"
        body = "\n".join(fmt(x) for x in page_rows) or "—"
        text = (
            f"<b>{title} {html.escape(tf)}</b>  ·  стр. {page}/{total}\n"
            f"{body}"
        )

        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("◀️", callback_data=f"pager:{kind}:{tf}:{max(1, page - 1)}"),
            InlineKeyboardButton(f"{page}/{total}", callback_data="noop"),
            InlineKeyboardButton("▶️", callback_data=f"pager:{kind}:{tf}:{min(total, page + 1)}"),
        ]])

        await self._send_html_safe(context.bot, chat_id, text, reply_markup=kb)

    async def on_pager(self, update, context):
        q = update.callback_query;
        await q.answer()
        _, kind, tf, page = q.data.split(":", 3)
        page = max(1, int(page))
        from ..infrastructure.coingecko import markets_snapshot
        data = markets_snapshot("usd")

        def change(c):
            if tf == "1h":
                k = ("price_change_percentage_1h_in_currency", "price_change_percentage_1h")
            elif tf == "7d":
                k = ("price_change_percentage_7d_in_currency", "price_change_percentage_7d")
            else:
                k = ("price_change_percentage_24h_in_currency", "price_change_percentage_24h")
            v = c.get(k[0], c.get(k[1], 0.0));
            return float(v or 0.0)

        rows = sorted([c for c in data if c.get("symbol")], key=change, reverse=(kind == "top"))
        page_rows, page, total = self._rank_page(rows, page, 20)

        def fmt(c):
            sym = c['symbol'].upper();
            px = float(c.get('current_price') or 0.0)
            if tf == "1h":
                ch = c.get("price_change_percentage_1h_in_currency") or c.get("price_change_percentage_1h") or 0.0
            elif tf == "7d":
                ch = c.get("price_change_percentage_7d_in_currency") or c.get("price_change_percentage_7d") or 0.0
            else:
                ch = c.get("price_change_percentage_24h_in_currency") or c.get("price_change_percentage_24h") or 0.0
            return f"{sym:<6} {px:.4g} USD  ({float(ch):+,.2f}%)"

        text = (f"*{('TOP' if kind == 'top' else 'FLOP')} {tf}*  p{page}/{total}\n" +
                "\n".join(map(fmt, page_rows))).replace(",", " ")
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("◀️", callback_data=f"pager:{kind}:{tf}:{page - 1}"),
             InlineKeyboardButton(f"{page}/{total}", callback_data="noop"),
             InlineKeyboardButton("▶️", callback_data=f"pager:{kind}:{tf}:{page + 1}")],
        ])
        await self._safe_edit_text(q, text, parse_mode=ParseMode.MARKDOWN, reply_markup=kb)

    async def on_daily_cmd(self, update, context):
        """Обработчик команды /daily с поддержкой новой архитектуры."""
        try:
            if self.integrator:
                handled = await self.integrator.handle_command("daily", update, context)
                if handled:
                    return
            await self._on_daily_cmd_legacy(update, context)
        except Exception:
            logger.exception("on_daily_cmd failed")
            try:
                await self._on_daily_cmd_legacy(update, context)
            except Exception:
                logger.exception("on_daily_cmd legacy also failed")
    
    async def _on_daily_cmd_legacy(self, update, context):
        """Старая реализация команды /daily."""
        chat_id = update.effective_chat.id
        uid = update.effective_user.id
        args = [a.lower() for a in (context.args or [])]
        if not args:
            vs, count, hide, seed, daily, hour, size_mode, top, tf_setting = self.db.get_user_settings(uid)
            await context.bot.send_message(chat_id=chat_id, text=f"Daily: {'ON' if daily else 'OFF'}, время: {hour}:00")
            return
        if args[0] == "on":
            h = int(args[1]) if len(args) > 1 and args[1].isdigit() else 9
            self.db.set_user_settings(uid, daily_digest=1, daily_hour=h)
            await context.bot.send_message(chat_id=chat_id, text=f"✅ Daily включён на {h}:00")
        elif args[0] == "off":
            self.db.set_user_settings(uid, daily_digest=0)
            await context.bot.send_message(chat_id=chat_id, text="⛔️ Daily выключен")
        else:
            await context.bot.send_message(chat_id=chat_id, text="Используй: /daily on [час] | /daily off")

    async def _send_chart_tf(self, chat_id: int, tf: str):
        from ..visual.digest import render_digest
        try:
            png = render_digest(self.db, tf)
        except Exception as e:
            await self.app.bot.send_message(chat_id=chat_id, text=f"Ошибка рендера графика {tf}: {e}")
            return
        await self.app.bot.send_photo(chat_id=chat_id, photo=png, caption=f"График • {tf}")

    async def _send_chart_album_tf(self, chat_id: int, tf: str):
        from ..visual.digest import render_digest_panels
        try:
            panels = render_digest_panels(self.db, tf)
        except Exception as e:
            await self.app.bot.send_message(chat_id=chat_id, text=f"Ошибка рендера альбома {tf}: {e}")
            return

        # Собираем подпись (как в /chart_album)
        try:
            arrows = {}
            for m in METRICS:
                closes = get_closes(self.db, m, tf, 80)
                arrows[m] = trend_arrow_metric(m, tf, closes)

            all_divs = []
            series = self._pair_series_sec(tf, 320)
            for m in METRICS:
                rows = self.db.last_n(m, tf, 320)
                highs = [r[2] for r in rows]
                lows = [r[3] for r in rows]
                closes = [r[4] for r in rows]
                vols = [r[5] for r in rows]
                all_divs.extend(indicator_divergences(m, tf, closes, vols))
            all_divs.extend(pair_divergences(tf, series))
            score, label = risk_score(tf, arrows, all_divs)
            caption = f"<b>{tf}</b>: {label} (счёт {score})\n<i>/chart_album 15m|1h|4h|1d</i>"
        except Exception:
            logger.exception("risk label failed in _send_chart_album_tf")
            caption = f"<b>{tf}</b> альбом"

        if not panels:
            await self.app.bot.send_message(chat_id=chat_id, text="Нет панелей для отправки.")
            return

        # Telegram требует 2–10 элементов для media group; если одна — отправим как обычное фото.
        if len(panels) == 1:
            item = panels[0]
            if isinstance(item, (bytes, bytearray)):
                metric, png = "panel1", item
            else:
                metric, png = item  # ожидаем (metric, bytes)
            bio = io.BytesIO(png)
            bio.name = f"{metric}_{tf}.png"
            await self.app.bot.send_photo(chat_id=chat_id, photo=bio, caption=caption, parse_mode=ParseMode.HTML)
            return

        media_group = []
        for i, item in enumerate(panels):
            if isinstance(item, (bytes, bytearray)):
                metric, png = (METRICS[i] if i < len(METRICS) else f"panel{i + 1}"), item
            else:
                metric, png = item  # (metric, bytes)
            bio = io.BytesIO(png)
            bio.name = f"{metric}_{tf}.png"
            media_group.append(
                InputMediaPhoto(media=bio, caption=caption if i == 0 else None, parse_mode=ParseMode.HTML))

        await self.app.bot.send_media_group(chat_id=chat_id, media=media_group)


    async def cmd_bubbles_debug(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик команды /bubbles_debug с поддержкой новой архитектуры."""
        try:
            if self.integrator:
                handled = await self.integrator.handle_command("bubbles_debug", update, context)
                if handled:
                    return
            await self._cmd_bubbles_debug_legacy(update, context)
        except Exception:
            logger.exception("cmd_bubbles_debug failed")
            try:
                await self._cmd_bubbles_debug_legacy(update, context)
            except Exception:
                logger.exception("cmd_bubbles_debug legacy also failed")
    
    async def _cmd_bubbles_debug_legacy(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Старая реализация команды /bubbles_debug."""
        chat_id = update.effective_chat.id
        await update.message.reply_text("[dbg] backend=Agg, coins=?")
        await self._send_bubbles(chat_id=chat_id, context=context, tf="24h")
        await update.message.reply_text("[dbg] photo OK v=rank")


    async def on_cg_test(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик команды /cg_test с поддержкой новой архитектуры."""
        try:
            if self.integrator:
                handled = await self.integrator.handle_command("cg_test", update, context)
                if handled:
                    return
            await self._on_cg_test_legacy(update, context)
        except Exception:
            logger.exception("on_cg_test failed")
            try:
                await self._on_cg_test_legacy(update, context)
            except Exception:
                logger.exception("on_cg_test legacy also failed")
    
    async def _on_cg_test_legacy(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Старая реализация команды /cg_test."""
        try:
            from ..infrastructure.coingecko import markets_page
            rows = markets_page(vs="usd", page=1, per_page=5)
            syms = ", ".join([str(r.get("symbol", "")).upper() for r in rows])
            await context.bot.send_message(chat_id=update.effective_chat.id,
                                           text=f"CoinGecko OK: {len(rows)} монет. Примеры: {syms}")
        except Exception as e:
            await context.bot.send_message(chat_id=update.effective_chat.id,
                                           text=f"CoinGecko ERROR: {type(e).__name__}: {e}")

    async def _send_corr(self, chat_id: int, tf: str, context: ContextTypes.DEFAULT_TYPE):
        from ..usecases.analytics import corr_matrix_and_beta
        from ..visual.corr_heatmap import render_corr_heatmap
        df, betas = corr_matrix_and_beta(self.db, METRICS, base="BTC", timeframe=tf, n=600)
        if df.empty or "BTC" not in df.columns:
            await context.bot.send_message(chat_id=chat_id, text="Нет данных для корреляции.")
            return

        png = render_corr_heatmap(df)

        corr_with_btc = df["BTC"].drop(index="BTC").dropna().clip(-1.0, 1.0)
        corr_lines = [f"{k}: {v:+.2f}" for k, v in corr_with_btc.items()]
        beta_lines = [f"{k}: {v:+.2f}" for k, v in betas.items() if k != "BTC" and not np.isnan(v)]

        cap = (
            "*Корреляции с BTC* (" + tf + ")\n" +
            ("\n".join(corr_lines[:12]) if corr_lines else "—") +
            "\n\n*Бета к BTC*\n" +
            ("\n".join(beta_lines[:12]) if beta_lines else "—") +
            "\n\n_Зачем_: понять синхронность активов (хедж/диверсификация) и общий фон рынка. |corr|→1 — ходят вместе/вразн.; β>1 — движения сильнее BTC."
        )
        await self.app.bot.send_photo(chat_id=chat_id, photo=png, caption=cap, parse_mode=ParseMode.MARKDOWN)

    async def _send_beta(self, chat_id: int, sym: str, tf: str):
        from ..usecases.analytics import corr_matrix_and_beta
        _, betas = corr_matrix_and_beta(self.db, METRICS, base="BTC", timeframe=tf, n=600)
        b = betas.get(sym)
        if b is None or np.isnan(b):
            await self.app.bot.send_message(chat_id=chat_id, text=f"Не получилось посчитать бета для {sym} ({tf}).")
        else:
            await self.app.bot.send_message(
                chat_id=chat_id,
                text=(f"*Бета {sym} к BTC* ({tf}): {b:+.2f}\n"
                      "_Зачем_: чувствительность к BTC; β>1 — усиливает движение BTC, β<1 — слабее, β<0 — чаще в противофазе."),
                parse_mode=ParseMode.MARKDOWN
            )

    async def _send_vol(self, chat_id: int, sym: str, tf: str):
        from ..usecases.analytics import vol_regime
        from ..visual.vol_panel import render_vol_panel
        vs = vol_regime(self.db, sym, tf, n=1200)

        hint = self._vol_hint(sym=sym, tf=tf, rv7=vs.rv_7, rv30=vs.rv_30, atr=vs.atr_14, regime=vs.regime, pctl=vs.pctl)

        png = render_vol_panel(vs.rv_7, vs.rv_30, vs.atr_14, vs.regime, vs.pctl, title=f"Volatility {sym} ({tf})")
        caption = (f"*Volatility {sym} ({tf})*\n"
                   f"RV7: {vs.rv_7:.4f}\nRV30: {vs.rv_30:.4f}\nATR14: {vs.atr_14:.2f}\n"
                   f"Regime: *{vs.regime}* ({vs.pctl:.1f}pctl)\n\n"
                   f"_{hint}_")
        await self.app.bot.send_photo(chat_id=chat_id, photo=png, caption=caption, parse_mode=ParseMode.MARKDOWN)

    async def _send_funding(self, chat_id: int, base: str):
        from ..infrastructure.market_data import binance_funding_and_mark
        from ..visual.market_misc import render_funding_card

        sym = f"{base.upper()}USDT"
        x = binance_funding_and_mark(sym)
        png = render_funding_card(sym, x["markPrice"], x["fundingRate"])
        cap = (f"*Funding (Binance) {sym}*\n"
               f"mark: {x['markPrice']:.2f}\nlastFundingRate: {x['fundingRate']:.6f}\n"
               "_Зачем_: показывает перекос перп-позиций — высокий + перегретые лонги, отрицательный — перегретые шорты.")
        await self.app.bot.send_photo(chat_id=chat_id, photo=png, caption=cap, parse_mode=ParseMode.MARKDOWN)

    async def _send_basis(self, chat_id: int, base: str):
        from ..infrastructure.market_data import basis_pct
        from ..visual.market_misc import render_basis_card
        sym = f"{base.upper()}USDT"
        b = basis_pct(sym)
        png = render_basis_card(sym, b["spot"], b["mark"], b["basis_pct"])
        cap = (f"*Basis {sym}*\nspot: {b['spot']:.2f}\nmark: {b['mark']:.2f}\n"
               f"basis: {b['basis_pct']:.3f}%\n"
               "_Зачем_: отражает премию/дисконт перпетуала к споту — индикатор аппетита к риску.")
        await self.app.bot.send_photo(chat_id=chat_id, photo=png, caption=cap, parse_mode=ParseMode.MARKDOWN)



    async def _send_liqs(self, chat_id: int, base: str):
        from ..infrastructure.liquidations import bybit_liqs_any
        try:
            long_usd, short_usd, cnt, sym, ok = bybit_liqs_any(base, minutes=120, limit=200)
            long_usd = float(long_usd or 0.0)
            short_usd = float(short_usd or 0.0)
            cnt = int(cnt or 0)
            sym = str(sym or base)

            if not ok or ((long_usd + short_usd) <= 0 and cnt <= 0):
                await self._send_html_safe(self.app.bot, chat_id,
                                           f"По <b>{sym}</b> нет свежих ликвидаций за последнее окно.")
                return

            text = (
                f"<b>Ликвидации {sym}</b>\n"
                f"• Long: ${long_usd:,.0f}\n"
                f"• Short: ${short_usd:,.0f}\n"
                f"• Сделок: {cnt:,}"
            ).replace(",", " ")

            await self._send_html_safe(self.app.bot, chat_id, text)

        except Exception as e:
            import traceback
            tb = traceback.format_exc(limit=2)
            await self._send_html_safe(self.app.bot, chat_id,
                                       f"Ошибка получения ликвидаций для <b>{base}</b>:\n<i>{type(e).__name__}: {e}</i>\n{tb}")


    async def _send_levels(self, chat_id: int, sym: str, tf: str, context: ContextTypes.DEFAULT_TYPE):
        from ..usecases.analytics import _ohlcv_df, nearest_sr, recent_breakouts
        df = _ohlcv_df(self.db, sym, tf, 800)
        if df.empty:
            await context.bot.send_message(chat_id=chat_id, text="Нет данных.")
            return
        last, above, below = nearest_sr(df, k=3)
        bo_up, bo_dn = recent_breakouts(df, lookback=50)
        text = (f"*Levels {sym} ({tf})*\n"
                f"Last close: {last:.2f}\n"
                f"Above: {', '.join(f'{x:.2f}' for x in above) if above else '—'}\n"
                f"Below: {', '.join(f'{x:.2f}' for x in below) if below else '—'}\n"
                f"Breakout: {'↑' if bo_up else '—'} {'↓' if bo_dn else '—'}")
        from ..visual.levels_card import render_levels_card
        png = render_levels_card(sym, tf, last, above, below, bo_up, bo_dn)
        await self.app.bot.send_photo(chat_id=chat_id, photo=png, caption=text, parse_mode=ParseMode.MARKDOWN)

    async def _send_scan_divs(self, chat_id: int, tf: str):
        out = []
        for m in METRICS:
            rows = self.db.last_n(m, tf, 320)
            if not rows:
                continue
            highs  = [r[2] for r in rows]
            lows   = [r[3] for r in rows]
            closes = [r[4] for r in rows]
            vols   = [r[5] for r in rows]
            divs = indicator_divergences(m, tf, closes, vols)
            if not divs:
                continue
            bulls = [d.indicator for d in divs if "bullish" in d.implication]
            bears = [d.indicator for d in divs if "bearish" in d.implication]
            parts = []
            if bulls:
                parts.append("🟢 bullish: " + ", ".join(bulls))
            if bears:
                parts.append("🔴 bearish: " + ", ".join(bears))
            out.append(f"• {m}: " + " | ".join(parts))
        txt = "*Дивергенции сейчас*\n" + ("\n".join(out) if out else "—") + "\n\n_Зачем_: дивергенции часто предвосхищают развороты/ослабление импульса."
        await self.app.bot.send_message(chat_id=chat_id, text=txt, parse_mode=ParseMode.MARKDOWN)

    async def _send_risk_now(self, chat_id: int):
        tf = "1h"
        arrows = {}
        for m in METRICS:
            closes = get_closes(self.db, m, tf, 80)
            arrows[m] = trend_arrow_metric(m, tf, closes)

        all_divs = []
        for m in METRICS:
            rows = self.db.last_n(m, tf, 320)
            if not rows:
                continue
            highs  = [r[2] for r in rows]
            lows   = [r[3] for r in rows]
            closes = [r[4] for r in rows]
            vols   = [r[5] for r in rows]
            all_divs.extend(indicator_divergences(m, tf, closes, vols))

        series = self._pair_series_sec(tf, 320)
        all_divs.extend(pair_divergences(tf, series))

        score, label = risk_score(tf, arrows, all_divs)
        from ..visual.risk_card import render_risk_card

        png = render_risk_card(tf, score, label)
        cap = f"*Risk Now ({tf})*: {label} (score {score})"
        await self.app.bot.send_photo(chat_id=chat_id, photo=png, caption=cap, parse_mode=ParseMode.MARKDOWN)
        await self.app.bot.send_message(
            chat_id=chat_id,
            text=f"*Risk Now ({tf})*: {label} (score {score})\n_Зачем_: сводный индикатор risk-on/off на основе тренда и дивергенций.",
            parse_mode=ParseMode.MARKDOWN
        )

    async def _send_breadth(self, chat_id: int, tf: str):
        from ..usecases.analytics import breadth
        from ..visual.breadth_bar import render_breadth_bar
        b = breadth(self.db, METRICS, tf)
        png = render_breadth_bar(b["above_ma50"], b["above_ma200"], b["total"], title=f"Breadth ({tf})")
        cap = (f"*Breadth ({tf})*\n"
               f">MA50: {b['above_ma50']}/{b['total']} ({b['pct_ma50']}%)\n"
               f">MA200: {b['above_ma200']}/{b['total']} ({b['pct_ma200']}%)\n"
               "_Зачем_: оценивает ширину рынка — долю метрик в ап-тренде; полезно для понимания общего фона.")
        await self.app.bot.send_photo(chat_id=chat_id, photo=png, caption=cap, parse_mode=ParseMode.MARKDOWN)

    async def _send_bt_rsi(self, chat_id: int, sym: str, tf: str):
        from ..usecases.analytics import backtest_rsi
        res = backtest_rsi(self.db, sym, tf)
        await self.app.bot.send_message(
            chat_id=chat_id,
            text=(f"*BT rsi {sym} {tf}*\n"
                  f"Trades: {res.trades}\nWinrate: {res.winrate:.1f}%\n"
                  f"Total: {res.total_ret:.2f}%\nSharpe~: {res.sharpe:.2f}\n"
                  "_Зачем_: быстрая прикидка работоспособности простого правила входа/выхода (не финсовет)."),
            parse_mode=ParseMode.MARKDOWN)

    # ---------------- commands ----------------

    async def on_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик команды /status с поддержкой новой архитектуры."""
        try:
            if self.integrator:
                handled = await self.integrator.handle_command("status", update, context)
                if handled:
                    return
            await self._on_status_legacy(update, context)
        except Exception:
            logger.exception("on_status failed")
            try:
                await self._on_status_legacy(update, context)
            except Exception:
                logger.exception("on_status legacy also failed")
    
    async def _on_status_legacy(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Старая реализация команды /status."""
        text = self._build_compact_safe()
        await self._send_html(update.effective_chat.id, text, reply_markup=self._kb('main'))

    async def on_full(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик команды /full с поддержкой новой архитектуры."""
        try:
            if self.integrator:
                handled = await self.integrator.handle_command("full", update, context)
                if handled:
                    return
            await self._on_full_legacy(update, context)
        except Exception:
            logger.exception("on_full failed")
            try:
                await self._on_full_legacy(update, context)
            except Exception:
                logger.exception("on_full legacy also failed")
    
    async def _on_full_legacy(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Старая реализация команды /full."""
        text = self._build_full_safe()
        await self._send_html(update.effective_chat.id, text, reply_markup=self._kb('main'))

    async def on_sub(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик команды /subscribe с поддержкой новой архитектуры."""
        try:
            if self.integrator:
                handled = await self.integrator.handle_command("subscribe", update, context)
                if handled:
                    return
            await self._on_sub_legacy(update, context)
        except Exception:
            logger.exception("on_sub failed")
            try:
                await self._on_sub_legacy(update, context)
            except Exception:
                logger.exception("on_sub legacy also failed")
    
    async def _on_sub_legacy(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Старая реализация команды /subscribe."""
        try:
            self.db.add_sub(update.effective_chat.id)
            await update.effective_message.reply_text("Подписал на авто-обновления. /unsubscribe — отписка.")
        except Exception:
            logger.exception("on_sub failed")

    async def on_unsub(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик команды /unsubscribe с поддержкой новой архитектуры."""
        try:
            if self.integrator:
                handled = await self.integrator.handle_command("unsubscribe", update, context)
                if handled:
                    return
            await self._on_unsub_legacy(update, context)
        except Exception:
            logger.exception("on_unsub failed")
            try:
                await self._on_unsub_legacy(update, context)
            except Exception:
                logger.exception("on_unsub legacy also failed")
    
    async def _on_unsub_legacy(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Старая реализация команды /unsubscribe."""
        try:
            self.db.remove_sub(update.effective_chat.id)
            await update.effective_message.reply_text("Подписка отключена.")
        except Exception:
            logger.exception("on_unsub failed")

    async def on_chart(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик команды /chart с поддержкой новой архитектуры."""
        try:
            if self.integrator:
                handled = await self.integrator.handle_command("chart", update, context)
                if handled:
                    return
            await self._on_chart_legacy(update, context)
        except Exception:
            logger.exception("on_chart failed")
            try:
                await self._on_chart_legacy(update, context)
            except Exception:
                logger.exception("on_chart legacy also failed")
    
    async def _on_chart_legacy(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Старая реализация команды /chart."""
        tf = self._resolve_tf(update, context)
        if not tf:
            tf = context.user_data.get('tf', DEFAULT_TF)
        from ..visual.digest import render_digest
        try:
            png = render_digest(self.db, tf)
        except Exception:
            logger.exception("render_digest failed")
            await update.effective_message.reply_text("Не удалось построить график, попробуйте позже.")
            return

        arrows = {}
        for m in METRICS:
            closes = get_closes(self.db, m, tf, 80)
            arrows[m] = trend_arrow_metric(m, tf, closes)

        all_divs = []
        for m in METRICS:
            rows = self.db.last_n(m, tf, 320)
            if not rows:
                continue
            highs  = [r[2] for r in rows]
            lows   = [r[3] for r in rows]
            closes = [r[4] for r in rows]
            vols   = [r[5] for r in rows]
            all_divs.extend(indicator_divergences(m, tf, closes, vols))

        series = self._pair_series_sec(tf, 320)
        all_divs.extend(pair_divergences(tf, series))

        score, label = risk_score(tf, arrows, all_divs)
        caption = f"<b>{tf}</b>: {label} (счёт {score})\n<i>/chart 15m|1h|4h|1d</i>"

        await self.app.bot.send_photo(
            chat_id=update.effective_chat.id,
            photo=png,
            caption=caption,
            parse_mode=ParseMode.HTML,
        )

    async def on_chart_album(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик команды /chart_album с поддержкой новой архитектуры."""
        try:
            if self.integrator:
                handled = await self.integrator.handle_command("chart_album", update, context)
                if handled:
                    return
            await self._on_chart_album_legacy(update, context)
        except Exception:
            logger.exception("on_chart_album failed")
            try:
                await self._on_chart_album_legacy(update, context)
            except Exception:
                logger.exception("on_chart_album legacy also failed")
    
    async def on_diag(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик команды /diag с поддержкой новой архитектуры."""
        try:
            if self.integrator:
                handled = await self.integrator.handle_command("diag", update, context)
                if handled:
                    return
            # Fallback: отправляем сообщение об ошибке
            await update.effective_message.reply_text(
                "Команда /diag недоступна. Используйте: /diag [metric] [timeframe]"
            )
        except Exception:
            logger.exception("on_diag failed")
    
    async def on_market_doctor(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик команды /market_doctor или /md с поддержкой новой архитектуры."""
        try:
            # Логируем аргументы для отладки
            args = context.args or []
            logger.info(f"on_market_doctor called with args: {args}, message text: {update.effective_message.text if update.effective_message else 'N/A'}")
            
            # Пробуем использовать CommandIntegrator если он доступен
            if self.integrator:
                try:
                    # Пробуем получить handler напрямую
                    handler = self.integrator.get_handler("market_doctor")
                    if handler:
                        logger.debug(f"Calling handler.handle_market_doctor directly with args: {args}")
                        await handler.handle_market_doctor(update, context)
                        return
                    
                    logger.debug("Handler 'market_doctor' not found, trying via command_map")
                    # Если handler не найден, пробуем через command_map
                    handled = await self.integrator.handle_command("md", update, context)
                    if handled:
                        logger.debug("Command 'md' handled via command_map")
                        return
                    
                    handled = await self.integrator.handle_command("market_doctor", update, context)
                    if handled:
                        logger.debug("Command 'market_doctor' handled via command_map")
                        return
                except Exception as e:
                    logger.warning(f"Error using CommandIntegrator, trying re-initialization: {e}")
            
            # Fallback: если CommandIntegrator не инициализирован или произошла ошибка,
            # пробуем инициализировать его заново
            if not self.integrator:
                logger.warning("CommandIntegrator not initialized, attempting re-initialization")
                try:
                    from ..presentation.integration.command_integrator import CommandIntegrator
                    self.integrator = CommandIntegrator(self.db)
                    logger.info("CommandIntegrator re-initialized successfully")
                    
                    # Пробуем обработать команду снова
                    handled = await self.integrator.handle_command("md", update, context)
                    if handled:
                        logger.debug("Command 'md' handled after re-initialization")
                        return
                except Exception as e:
                    logger.exception(f"Failed to re-initialize CommandIntegrator: {e}")
            
            # Если всё ещё не обработано, отправляем сообщение об ошибке
            logger.warning(f"Command /md not handled, args were: {args}")
            await update.effective_message.reply_text(
                "Команда /md временно недоступна. Используйте: /md <символ> [таймфрейм]\n"
                "Пример: /md BTC 1h"
            )
            return
        except Exception as e:
            logger.exception("on_market_doctor failed: %s", e)
            # В случае ошибки тоже показываем инструкцию
            try:
                await update.effective_message.reply_text(
                    f"❌ Ошибка при выполнении команды: {str(e)}\n\n"
                    "Использование: /md <символ> [таймфрейм]\n"
                    "Пример: /md BTC 1h\n"
                    "Пример: /md ETHUSDT 4h\n"
                    "Таймфреймы: 1h, 4h, 1d (по умолчанию 1h)"
                )
            except Exception:
                pass
    
    async def on_md_profile(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик команды /md_profile для управления профилями риска."""
        try:
            if self.integrator:
                # Используем новый handler через integrator
                handler = self.integrator.get_handler("market_doctor_profile")
                if handler:
                    await handler.handle_profile_command(update, context)
                    return
            
            # Fallback: используем прямой доступ к handler через factory
            if hasattr(self, "factory"):
                handlers = self.factory.get_handlers()
                profile_handler = handlers.get("market_doctor_profile")
                if profile_handler:
                    await profile_handler.handle_profile_command(update, context)
                    return
            
            await update.effective_message.reply_text(
                "Команда /md_profile временно недоступна."
            )
        except Exception:
            logger.exception("on_md_profile failed")
    
    async def on_mdh(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик команды /mdh - краткий отчет multi-TF."""
        try:
            if self.integrator:
                handler = self.integrator.get_handler("market_doctor")
                if handler:
                    await handler.handle_market_doctor_brief(update, context)
                    return
            await update.effective_message.reply_text(
                "Команда /mdh временно недоступна. Используйте: /mdh <символ>"
            )
        except Exception:
            logger.exception("on_mdh failed")
    
    async def on_mdt(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик команды /mdt - только торговый план."""
        try:
            if self.integrator:
                handler = self.integrator.get_handler("market_doctor")
                if handler:
                    await handler.handle_market_doctor_trade_only(update, context)
                    return
            await update.effective_message.reply_text(
                "Команда /mdt временно недоступна. Используйте: /mdt <символ> [таймфрейм]"
            )
        except Exception:
            logger.exception("on_mdt failed")
    
    async def on_mdtop(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик команды /mdtop - топ сетапы."""
        try:
            if self.integrator:
                handler = self.integrator.get_handler("market_doctor")
                if handler:
                    await handler.handle_market_doctor_top(update, context)
                    return
            await update.effective_message.reply_text(
                "Команда /mdtop временно недоступна."
            )
        except Exception:
            logger.exception("on_mdtop failed")
    
    async def on_md_watch_add(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик команды /md_watch_add."""
        try:
            if self.integrator:
                handler = self.integrator.get_handler("market_doctor_watchlist")
                if handler:
                    await handler.handle_watchlist_add(update, context)
                    return
            await update.effective_message.reply_text(
                "Команда /md_watch_add временно недоступна."
            )
        except Exception:
            logger.exception("on_md_watch_add failed")
    
    async def on_md_watch_remove(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик команды /md_watch_remove."""
        try:
            if self.integrator:
                handler = self.integrator.get_handler("market_doctor_watchlist")
                if handler:
                    await handler.handle_watchlist_remove(update, context)
                    return
            await update.effective_message.reply_text(
                "Команда /md_watch_remove временно недоступна."
            )
        except Exception:
            logger.exception("on_md_watch_remove failed")
    
    async def on_md_watch_list(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик команды /md_watch_list."""
        try:
            if self.integrator:
                handler = self.integrator.get_handler("market_doctor_watchlist")
                if handler:
                    await handler.handle_watchlist_list(update, context)
                    return
            await update.effective_message.reply_text(
                "Команда /md_watch_list временно недоступна."
            )
        except Exception:
            logger.exception("on_md_watch_list failed")
    
    async def on_md_backtest(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик команды /md_backtest."""
        try:
            if self.integrator:
                handler = self.integrator.get_handler("market_doctor_backtest")
                if handler:
                    await handler.handle_backtest_command(update, context)
                    return
            await update.effective_message.reply_text(
                "Команда /md_backtest временно недоступна."
            )
        except Exception:
            logger.exception("on_md_backtest failed")
    
    async def on_md_calibrate(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик команды /md_calibrate - отчёт о калибровке."""
        try:
            if self.integrator:
                await self.integrator.handle_command("md_calibrate", update, context)
            else:
                await update.effective_message.reply_text(
                    "Команда /md_calibrate временно недоступна."
                )
        except Exception:
            logger.exception("on_md_calibrate failed")
    
    async def on_md_apply_weights(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик команды /md_apply_weights."""
        try:
            if self.integrator:
                await self.integrator.handle_command("md_apply_weights", update, context)
            else:
                await update.effective_message.reply_text(
                    "Команда /md_apply_weights временно недоступна."
                )
        except Exception:
            logger.exception("on_md_apply_weights failed")
    
    async def on_md_weights_list(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик команды /md_weights_list."""
        try:
            if self.integrator:
                await self.integrator.handle_command("md_weights_list", update, context)
            else:
                await update.effective_message.reply_text(
                    "Команда /md_weights_list временно недоступна."
                )
        except Exception:
            logger.exception("on_md_weights_list failed")
    
    async def on_md_weights_reset(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик команды /md_weights_reset."""
        try:
            if self.integrator:
                await self.integrator.handle_command("md_weights_reset", update, context)
            else:
                await update.effective_message.reply_text(
                    "Команда /md_weights_reset временно недоступна."
                )
        except Exception:
            logger.exception("on_md_weights_reset failed")
    
    async def on_text_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик текстовых сообщений для ввода тикера графика и Market Doctor."""
        try:
            text = update.effective_message.text or ""
            ud = context.user_data
            
            # Обработка кнопок из ReplyKeyboardMarkup
            if text == "ℹ️ Справка":
                await self.on_help(update, context)
                return
            elif text == "🧾 Отчёт":
                await self.on_status(update, context)
                return
            elif text == "🫧 Bubbles":
                await self.on_bubbles(update, context, "1h")
                return
            elif text == "🏆 Топ":
                await self._handle_top_button(update, context)
                return
            elif text == "📈 Чарты":
                await self.on_chart(update, context)
                return
            elif text == "🖼 Альбом":
                await self.on_chart_album(update, context)
                return
            elif text == "🔮 Прогноз":
                await self._handle_forecast_button(update, context)
                return
            elif text == "🧩 Опционы":
                await self.on_options_btc(update, context)
                return
            elif text == "📈 TWAP":
                await self.on_twap(update, context)
                return
            elif text == "🪙 Altseason":
                await self.on_altseason(update, context)
                return
            elif text == "🧭 F&G":
                await self.on_fng(update, context)
                return
            elif text == "➡️ Ещё":
                await self._send_more_menu(update, context)
                return
            elif text == "📋 Меню":
                await self._send_full_menu(update, context)
                return
            
            # Проверяем, ожидаем ли мы ввод символа для Market Doctor
            if ud.get("waiting_for_md_symbol", False):
                # Получаем текст сообщения
                text = update.effective_message.text or ""
                symbol = text.strip().upper()
                
                # Валидация символа
                if not symbol or len(symbol) > 20 or not symbol.replace("-", "").replace(".", "").isalnum():
                    await update.effective_message.reply_text(
                        "❌ Неверный формат символа. Введите корректный тикер (например: BTC, ETH, SOL)."
                    )
                    return
                
                # Сбрасываем флаг ожидания
                ud["waiting_for_md_symbol"] = False
                
                # Получаем сохраненный таймфрейм
                tf = ud.get("md_tf", "1h")
                
                # Проверяем, нужен ли multi-TF анализ
                if tf == "multi":
                    # Устанавливаем аргументы для multi-TF
                    context.args = [symbol, "multi"]
                else:
                    # Устанавливаем аргументы команды
                    context.args = [symbol, tf]
                
                # Выполняем команду Market Doctor через handler напрямую
                if self.integrator:
                    try:
                        handler = self.integrator.get_handler("market_doctor")
                        if handler:
                            await handler.handle_market_doctor(update, context)
                            return
                    except Exception:
                        logger.exception("Error executing MD command via integrator")
                
                # Fallback через handle_command
                if self.integrator:
                    try:
                        handled = await self.integrator.handle_command("md", update, context)
                        if handled:
                            return
                    except Exception:
                        logger.exception("Error executing MD command via handle_command")
                
                # Последний fallback
                if hasattr(self, "on_market_doctor"):
                    await self.on_market_doctor(update, context)
                else:
                    await update.effective_message.reply_text(
                        f"Анализ {symbol} на таймфрейме {tf}...\n"
                        "Команда временно недоступна."
                    )
                return
            
            # Проверяем, ожидаем ли мы ввод тикера для графика
            if not ud.get("waiting_for_chart_ticker", False):
                return  # Не обрабатываем, если не ожидаем ввод
            
            # Получаем текст сообщения
            text = update.effective_message.text or ""
            symbol = text.strip().upper()
            
            # Валидация символа (должен быть буквенно-цифровым, не слишком длинным)
            if not symbol or len(symbol) > 20 or not symbol.replace("-", "").replace(".", "").isalnum():
                await update.effective_message.reply_text(
                    "❌ Неверный формат тикера. Введите корректный тикер (например: BTC, ETH, SOL)."
                )
                return
            
            # Сбрасываем флаг ожидания
            ud["waiting_for_chart_ticker"] = False
            
            # Получаем сохраненный ТФ
            tf = ud.get("chart_tf", ud.get("tf", "1h"))
            
            # Получаем настройки графика: сначала из user_data, если нет - из БД
            chart_settings = ud.get("chart_settings")
            if chart_settings is None and self.db:
                user_id = update.effective_user.id
                chart_settings = self.db.get_chart_settings(user_id) or {}
                ud["chart_settings"] = chart_settings
            
            # Если все еще нет настроек, используем пустой словарь
            if chart_settings is None:
                chart_settings = {}
            
            # Создаем настройки
            from ..domain.chart_settings import ChartSettings
            settings = ChartSettings.from_params(chart_settings)
            settings.timeframe = tf
            
            # Рендерим график
            try:
                from ..visual.chart_renderer import render_chart
                png = render_chart(self.db, symbol, settings, n_bars=500)
                
                # Отправляем график
                from telegram import InputFile
                from telegram.constants import ParseMode
                
                caption = f"<b>{symbol}</b> • {tf}"
                if settings.currency:
                    caption += f" • {settings.currency.upper()}"
                
                await context.bot.send_photo(
                    chat_id=update.effective_chat.id,
                    photo=InputFile(png, filename=f"chart_{symbol}_{tf}.png"),
                    caption=caption,
                    parse_mode=ParseMode.HTML
                )
            except Exception as e:
                logger.exception("Error rendering chart for custom ticker %s %s", symbol, tf)
                await update.effective_message.reply_text(
                    f"Не удалось построить график для {symbol} {tf}. Проверьте, что тикер корректен и данные доступны."
                )
        except Exception:
            logger.exception("on_text_message failed")
    
    async def _on_chart_album_legacy(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Старая реализация команды /chart_album."""
        tf = self._resolve_tf(update, context)
        if not tf:
            tf = context.user_data.get('tf', DEFAULT_TF)
        from ..visual.digest import render_digest_panels
        panels = render_digest_panels(self.db, tf)

        arrows = {}
        for m in METRICS:
            closes = get_closes(self.db, m, tf, 80)
            arrows[m] = trend_arrow_metric(m, tf, closes)

        all_divs = []
        series = self._pair_series_sec(tf, 320)
        for m in METRICS:
            rows = self.db.last_n(m, tf, 320)
            if not rows:
                continue
            highs = [r[2] for r in rows]
            lows = [r[3] for r in rows]
            closes = [r[4] for r in rows]
            vols = [r[5] for r in rows]
            all_divs.extend(indicator_divergences(m, tf, closes, vols))
        all_divs.extend(pair_divergences(tf, series))
        score, label = risk_score(tf, arrows, all_divs)
        caption = f"<b>{tf}</b>: {label} (счёт {score})\n<i>/chart_album 15m|1h|4h|1d</i>"

        media_group = []
        for i, item in enumerate(panels):
            if isinstance(item, (bytes, bytearray)):
                metric = METRICS[i] if i < len(METRICS) else f"panel{i+1}"
                png = item
            else:
                metric, png = item
            bio = io.BytesIO(png)
            bio.name = f"{metric}_{tf}.png"
            media_group.append(InputMediaPhoto(media=bio, caption=caption if i == 0 else None, parse_mode=ParseMode.HTML))
        await self.app.bot.send_media_group(chat_id=update.effective_chat.id, media=media_group)

    # -------- options --------

    async def cmd_options(self, update: Update, context: ContextTypes.DEFAULT_TYPE, symbol: str):
        chat_id = update.effective_chat.id
        if _have_coinglass():
            try:
                from ..infrastructure.coinglass import fetch_max_pain
                from ..visual.options_chart import render_max_pain_chart
                res = fetch_max_pain(symbol)
                head = f"*{symbol} options max pain*\n"
                lines = [f"• `{p.date}`  max pain: *{p.max_pain:,.0f}*  notional: ${p.notional:,.0f}" for p in res.points[:10]]
                text = head + "\n".join(lines) if lines else head + "_no data_"
                png = render_max_pain_chart(res)
                await context.bot.send_photo(chat_id=chat_id, photo=png, caption=text, parse_mode=ParseMode.MARKDOWN)
                return
            except Exception:
                logger.exception("CoinGlass failed, fallback to free")
        png, text = await self._build_free_payload(symbol, context)
        if png:
            await context.bot.send_photo(chat_id=chat_id, photo=png, caption=text, parse_mode=ParseMode.MARKDOWN)
        else:
            await context.bot.send_message(chat_id=chat_id, text=text, parse_mode=ParseMode.MARKDOWN)

    async def cmd_options_free(self, update: Update, context: ContextTypes.DEFAULT_TYPE, symbol: str):
        """Обработчик команды /options_*_free с поддержкой новой архитектуры."""
        try:
            if self.integrator:
                command = f"options_{symbol.lower()}_free"
                handled = await self.integrator.handle_command(command, update, context)
                if handled:
                    return
            await self._cmd_options_free_legacy(update, context, symbol)
        except Exception:
            logger.exception("cmd_options_free failed")
            try:
                await self._cmd_options_free_legacy(update, context, symbol)
            except Exception:
                logger.exception("cmd_options_free legacy also failed")
    
    async def _cmd_options_free_legacy(self, update: Update, context: ContextTypes.DEFAULT_TYPE, symbol: str):
        """Старая реализация команды /options_*_free."""
        png, text = await self._build_free_payload(symbol, context)
        chat_id = update.effective_chat.id
        if png:
            await context.bot.send_photo(chat_id=chat_id, photo=png, caption=text, parse_mode=ParseMode.MARKDOWN)
        else:
            await context.bot.send_message(chat_id=chat_id, text=text, parse_mode=ParseMode.MARKDOWN)

    async def on_options_btc(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик команды /options_btc с поддержкой новой архитектуры."""
        try:
            if self.integrator:
                handled = await self.integrator.handle_command("btc_options", update, context)
                if handled:
                    return
            await self._on_options_btc_legacy(update, context)
        except Exception:
            logger.exception("on_options_btc failed")
            try:
                await self._on_options_btc_legacy(update, context)
            except Exception:
                logger.exception("on_options_btc legacy also failed")
    
    async def _on_options_btc_legacy(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Старая реализация команды /options_btc."""
        await self.cmd_options(update, context, "BTC")

    async def on_options_eth(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик команды /options_eth с поддержкой новой архитектуры."""
        try:
            if self.integrator:
                handled = await self.integrator.handle_command("eth_options", update, context)
                if handled:
                    return
            await self._on_options_eth_legacy(update, context)
        except Exception:
            logger.exception("on_options_eth failed")
            try:
                await self._on_options_eth_legacy(update, context)
            except Exception:
                logger.exception("on_options_eth legacy also failed")
    
    async def _on_options_eth_legacy(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Старая реализация команды /options_eth."""
        await self.cmd_options(update, context, "ETH")

    # -------- analytics (parse message text) --------

    async def on_corr(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик команды /corr с поддержкой новой архитектуры."""
        try:
            if self.integrator:
                handled = await self.integrator.handle_command("corr", update, context)
                if handled:
                    return
            await self._on_corr_legacy(update, context)
        except Exception:
            logger.exception("on_corr failed")
            try:
                await self._on_corr_legacy(update, context)
            except Exception:
                logger.exception("on_corr legacy also failed")
    
    async def _on_corr_legacy(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Старая реализация команды /corr."""
        parts = update.effective_message.text.split()
        tf = self._resolve_tf(update, context)
        await self._send_corr(update.effective_chat.id, tf, context)

    async def on_beta(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик команды /beta с поддержкой новой архитектуры."""
        try:
            if self.integrator:
                handled = await self.integrator.handle_command("beta", update, context)
                if handled:
                    return
            await self._on_beta_legacy(update, context)
        except Exception:
            logger.exception("on_beta failed")
            try:
                await self._on_beta_legacy(update, context)
            except Exception:
                logger.exception("on_beta legacy also failed")
    
    async def _on_beta_legacy(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Старая реализация команды /beta."""
        parts = update.effective_message.text.split()
        tf = self._resolve_tf(update, context)
        sym = self._resolve_pair(update, context, "ETHBTC")
        await self._send_beta(update.effective_chat.id, sym, tf)

    async def on_vol(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик команды /vol с поддержкой новой архитектуры."""
        try:
            if self.integrator:
                handled = await self.integrator.handle_command("vol", update, context)
                if handled:
                    return
            await self._on_vol_legacy(update, context)
        except Exception:
            logger.exception("on_vol failed")
            try:
                await self._on_vol_legacy(update, context)
            except Exception:
                logger.exception("on_vol legacy also failed")
    
    async def _on_vol_legacy(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Старая реализация команды /vol."""
        parts = update.effective_message.text.split()
        tf = self._resolve_tf(update, context)
        sym = self._resolve_symbol(update, context, "BTC")  # если внутри нужен тикер
        await self._send_vol(update.effective_chat.id, sym, tf)

    async def on_funding(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик команды /funding с поддержкой новой архитектуры."""
        try:
            if self.integrator:
                handled = await self.integrator.handle_command("funding", update, context)
                if handled:
                    return
            await self._on_funding_legacy(update, context)
        except Exception:
            logger.exception("on_funding failed")
            try:
                await self._on_funding_legacy(update, context)
            except Exception:
                logger.exception("on_funding legacy also failed")
    
    async def _on_funding_legacy(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Старая реализация команды /funding."""
        parts = update.effective_message.text.split()
        base = parts[1] if len(parts) > 1 else "BTC"
        base = self._resolve_symbol(update, context)
        await self._send_funding(update.effective_chat.id, base)

    async def on_basis(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик команды /basis с поддержкой новой архитектуры."""
        try:
            if self.integrator:
                handled = await self.integrator.handle_command("basis", update, context)
                if handled:
                    return
            await self._on_basis_legacy(update, context)
        except Exception:
            logger.exception("on_basis failed")
            try:
                await self._on_basis_legacy(update, context)
            except Exception:
                logger.exception("on_basis legacy also failed")
    
    async def _on_basis_legacy(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Старая реализация команды /basis."""
        parts = update.effective_message.text.split()
        base = parts[1] if len(parts) > 1 else "BTC"
        base = self._resolve_symbol(update, context)
        await self._send_basis(update.effective_chat.id, base)

    async def on_liqs(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик команды /liqs с поддержкой новой архитектуры."""
        try:
            if self.integrator:
                handled = await self.integrator.handle_command("liqs", update, context)
                if handled:
                    return
            await self._on_liqs_legacy(update, context)
        except Exception:
            logger.exception("on_liqs failed")
            try:
                await self._on_liqs_legacy(update, context)
            except Exception:
                logger.exception("on_liqs legacy also failed")
    
    async def _on_liqs_legacy(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Старая реализация команды /liqs."""
        parts = update.effective_message.text.split()
        base = parts[1] if len(parts) > 1 else "BTC"
        await self._send_liqs(update.effective_chat.id, base)

    async def on_levels(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик команды /levels с поддержкой новой архитектуры."""
        try:
            if self.integrator:
                handled = await self.integrator.handle_command("levels", update, context)
                if handled:
                    return
            await self._on_levels_legacy(update, context)
        except Exception:
            logger.exception("on_levels failed")
            try:
                await self._on_levels_legacy(update, context)
            except Exception:
                logger.exception("on_levels legacy also failed")
    
    async def _on_levels_legacy(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Старая реализация команды /levels."""
        parts = update.effective_message.text.split()
        tf = self._resolve_tf(update, context)
        m = self._resolve_symbol(update, context, "BTC")
        await self._send_levels(update.effective_chat.id, m, tf, context)

    async def on_risk_now(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик команды /risk_now с поддержкой новой архитектуры."""
        try:
            if self.integrator:
                handled = await self.integrator.handle_command("risk_now", update, context)
                if handled:
                    return
            await self._on_risk_now_legacy(update, context)
        except Exception:
            logger.exception("on_risk_now failed")
            try:
                await self._on_risk_now_legacy(update, context)
            except Exception:
                logger.exception("on_risk_now legacy also failed")
    
    async def _on_risk_now_legacy(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Старая реализация команды /risk_now."""
        await self._send_risk_now(update.effective_chat.id)

    async def on_backtest(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик команды /bt с поддержкой новой архитектуры."""
        try:
            if self.integrator:
                handled = await self.integrator.handle_command("backtest", update, context)
                if handled:
                    return
            await self._on_backtest_legacy(update, context)
        except Exception:
            logger.exception("on_backtest failed")
            try:
                await self._on_backtest_legacy(update, context)
            except Exception:
                logger.exception("on_backtest legacy also failed")
    
    async def _on_backtest_legacy(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Старая реализация команды /bt."""
        parts = update.effective_message.text.split()
        tf = self._resolve_tf(update, context)
        sym = self._resolve_symbol(update, context, "BTC")
        strat = self._resolve_study(update, context, "rsi")
        if strat.lower() != "rsi":
            await update.effective_message.reply_text("Сейчас доступно: /bt rsi SYMBOL [tf]")
            return
        await self._send_bt_rsi(update.effective_chat.id, sym=sym, tf=tf)

    async def on_breadth(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик команды /breadth с поддержкой новой архитектуры."""
        try:
            if self.integrator:
                handled = await self.integrator.handle_command("breadth", update, context)
                if handled:
                    return
            await self._on_breadth_legacy(update, context)
        except Exception:
            logger.exception("on_breadth failed")
            try:
                await self._on_breadth_legacy(update, context)
            except Exception:
                logger.exception("on_breadth legacy also failed")
    
    async def _on_breadth_legacy(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Старая реализация команды /breadth."""
        tf = self._resolve_tf(update, context)
        await self._send_breadth(update.effective_chat.id, tf)

    async def on_events_add(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик команды /events_add с поддержкой новой архитектуры."""
        try:
            if self.integrator:
                handled = await self.integrator.handle_command("events_add", update, context)
                if handled:
                    return
            await self._on_events_add_legacy(update, context)
        except Exception:
            logger.exception("on_events_add failed")
            try:
                await self._on_events_add_legacy(update, context)
            except Exception:
                logger.exception("on_events_add legacy also failed")
    
    async def _on_events_add_legacy(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Старая реализация команды /events_add."""
        import re
        from ..infrastructure.events import add_event
        from zoneinfo import ZoneInfo
        from datetime import datetime

        def _parse_date_to_ms(date_str: str, tz) -> int:
            """
            Преобразует 'YYYY-MM-DD' (или 'YYYY-MM-DD HH:MM') в unix ms локальной TZ.
            Если время не указано — берём полночь.
            """
            date_str = date_str.strip()
            # поддержим оба формата
            fmt = "%Y-%m-%d %H:%M" if " " in date_str else "%Y-%m-%d"
            dt = datetime.strptime(date_str, fmt)
            # если времени нет — полночь по локальной TZ
            if fmt == "%Y-%m-%d":
                dt = dt.replace(hour=0, minute=0, second=0, microsecond=0)
            if tz:
                dt = dt.replace(tzinfo=tz)
            return int(dt.timestamp() * 1000)
        text = (update.effective_message.text or "").strip()

        # Разрешим оба формата: с временем и без
        m = re.match(r"^/events_add\s+(\d{4}-\d{2}-\d{2}(?:\s+\d{2}:\d{2})?)\s+(.+)$", text)
        if not m:
            await update.effective_message.reply_text(
                "Формат: /events_add YYYY-MM-DD [HH:MM] Текст события\n"
                "Пример: /events_add 2025-10-05 19:00 FOMC"
            )
            return

        date_str, title = m.group(1), m.group(2)

        try:
            tz = getattr(settings, "tz", None)
        except Exception:
            tz = None

        try:
            ts_ms = _parse_date_to_ms(date_str, tz)
        except Exception as e:
            await update.effective_message.reply_text(f"Ошибка в дате: {e}")
            return

        eid = add_event(ts_ms, title, author_chat_id=(update.effective_user.id if update.effective_user else None))
        await update.effective_message.reply_text(f"✅ Событие добавлено (id={eid}). Видно всем.")

    async def on_events_list(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик команды /events_list с поддержкой новой архитектуры."""
        try:
            if self.integrator:
                handled = await self.integrator.handle_command("events_list", update, context)
                if handled:
                    return
            await self._on_events_list_legacy(update, context)
        except Exception:
            logger.exception("on_events_list failed")
            try:
                await self._on_events_list_legacy(update, context)
            except Exception:
                logger.exception("on_events_list legacy also failed")
    
    async def _on_events_list_legacy(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Старая реализация команды /events_list."""
        from datetime import datetime, timezone
        from ..infrastructure.events import list_all_events, purge_past_events

        try:
            purge_past_events()  # мягкая гигиена
        except Exception:
            logger.exception("purge_past_events failed silently")

        rows = list_all_events()
        if not rows:
            await update.effective_message.reply_text("Сейчас нет предстоящих событий.")
            return

        try:
            tz = getattr(settings, "tz", None)
        except Exception:
            tz = None

        lines = ["<b>Предстоящие события</b>"]
        for eid, ts, title in rows[:100]:
            dt = datetime.fromtimestamp(ts / 1000.0, tz=tz or timezone.utc)
            lines.append(f"• <b>{dt.strftime('%Y-%m-%d')}</b> — {title}")

        await update.effective_message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)

    async def on_events_del(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик команды /events_del с поддержкой новой архитектуры."""
        try:
            if self.integrator:
                handled = await self.integrator.handle_command("events_del", update, context)
                if handled:
                    return
            await self._on_events_del_legacy(update, context)
        except Exception:
            logger.exception("on_events_del failed")
            try:
                await self._on_events_del_legacy(update, context)
            except Exception:
                logger.exception("on_events_del legacy also failed")
    
    async def _on_events_del_legacy(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Старая реализация команды /events_del."""
        from ..infrastructure.events import del_event
        parts = update.effective_message.text.split()
        if len(parts) < 2 or not parts[1].isdigit():
            await update.effective_message.reply_text("Формат: /events_del 12")
            return
        del_event(update.effective_chat.id, int(parts[1]))
        await update.effective_message.reply_text("Удалено.")

    async def on_info(self, update, context):
        """Обработчик команды /info с поддержкой новой архитектуры."""
        try:
            if self.integrator:
                handled = await self.integrator.handle_command("instruction", update, context)
                if handled:
                    return
            await self._on_info_legacy(update, context)
        except Exception:
            logger.exception("on_info failed")
            try:
                await self._on_info_legacy(update, context)
            except Exception:
                logger.exception("on_info legacy also failed")
    
    async def _on_info_legacy(self, update, context):
        """Старая реализация команды /info."""
        await self._send_html(update.effective_chat.id, INSTRUCTION_HTML, reply_markup=self._kb("main"))

    # ---------------- jobs ----------------

    async def job_broadcast_compact(self, context: ContextTypes.DEFAULT_TYPE):
        """Рассылка краткого отчёта (каждый час в :30)."""
        text = self._build_compact_safe()
        subs = list(self.db.list_subs())
        if not subs:
            return
        delay = SEND_DELAY_SEC
        for chat_id in subs:
            try:
                await self._send_html(chat_id, text, reply_markup=self._kb('main'))
                await asyncio.sleep(delay)
            except RetryAfter as e:
                wait_for = int(getattr(e, "retry_after", 2))
                logger.warning("429 RetryAfter chat_id=%s, sleeping %ss", chat_id, wait_for)
                await asyncio.sleep(wait_for)
            except Forbidden:
                logger.info("Forbidden chat_id=%s; removing from subs", chat_id)
                try:
                    self.db.remove_sub(chat_id)
                except Exception:
                    logger.exception("failed to remove sub after Forbidden")
            except (TimedOut, NetworkError):
                delay = min(delay * 1.5 + 0.05, 1.0)
                logger.warning("network issue on send to chat_id=%s; new delay=%.2fs", chat_id, delay)
                await asyncio.sleep(delay)
            except Exception:
                logger.exception("send failed chat_id=%s, delay=%.2f", chat_id, delay)
                await asyncio.sleep(delay)

    async def job_broadcast_full(self, context: ContextTypes.DEFAULT_TYPE):
        """Рассылка полного текста (раз в час в :00)."""
        text = self._build_full_safe()
        subs = list(self.db.list_subs())
        if not subs:
            return
        delay = SEND_DELAY_SEC
        for chat_id in subs:
            try:
                await self._send_html(chat_id, text, reply_markup=self._kb('main'))
                await asyncio.sleep(delay)
            except RetryAfter as e:
                wait_for = int(getattr(e, "retry_after", 2))
                logger.warning("429 RetryAfter (full) chat_id=%s, sleeping %ss", chat_id, wait_for)
                await asyncio.sleep(wait_for)
            except Forbidden:
                logger.info("Forbidden chat_id=%s; removing from subs", chat_id)
                try:
                    self.db.remove_sub(chat_id)
                except Exception:
                    logger.exception("failed to remove sub after Forbidden")
            except (TimedOut, NetworkError):
                delay = min(delay * 1.5 + 0.05, 1.0)
                logger.warning("network issue on send full to chat_id=%s; new delay=%.2fs", chat_id, delay)
                await asyncio.sleep(delay)
            except Exception:
                logger.exception("send full failed chat_id=%s", chat_id)
                await asyncio.sleep(delay)

    async def job_broadcast_chart(self, context: ContextTypes.DEFAULT_TYPE):
        tf = "1h"
        from ..visual.digest import render_digest
        try:
            png = render_digest(self.db, tf)
        except Exception:
            logger.exception("render_digest failed in job")
            return

        try:
            arrows = {}
            for m in METRICS:
                closes = get_closes(self.db, m, tf, 80)
                arrows[m] = trend_arrow_metric(m, tf, closes)

            all_divs = []
            for m in METRICS:
                rows = self.db.last_n(m, tf, 320)
                if not rows:
                    continue
                highs  = [r[2] for r in rows]
                lows   = [r[3] for r in rows]
                closes = [r[4] for r in rows]
                vols   = [r[5] for r in rows]
                all_divs.extend(indicator_divergences(m, tf, closes, vols))

            series = self._pair_series_sec(tf, 320)
            all_divs.extend(pair_divergences(tf, series))

            score, label = risk_score(tf, arrows, all_divs)
            caption = f"<b>{tf}</b>: {label} (счёт {score})\n<i>/chart 15m|1h|4h|1d</i>"
        except Exception:
            logger.exception("risk label failed in job")
            caption = f"<b>{tf}</b> дайджест"

        subs = list(self.db.list_subs())
        if not subs:
            return

        delay = SEND_DELAY_SEC
        for chat_id in subs:
            try:
                await self.app.bot.send_photo(
                    chat_id=chat_id, photo=png, caption=caption, parse_mode=ParseMode.HTML,
                    reply_markup=self._kb('main')
                )
                await asyncio.sleep(delay)
            except RetryAfter as e:
                wait_for = int(getattr(e, "retry_after", 2))
                logger.warning("429 on photo chat_id=%s, sleep=%ss", chat_id, wait_for)
                await asyncio.sleep(wait_for)
            except Forbidden:
                logger.info("Forbidden chat_id=%s; removing from subs", chat_id)
                try:
                    self.db.remove_sub(chat_id)
                except Exception:
                    logger.exception("failed to remove sub after Forbidden")
            except (TimedOut, NetworkError):
                delay = min(delay * 1.5 + 0.05, 1.0)
                logger.warning("network issue on photo to chat_id=%s; delay=%.2fs", chat_id, delay)
                await asyncio.sleep(delay)
            except Exception:
                logger.exception("send_photo failed chat_id=%s", chat_id)
                await asyncio.sleep(delay)

    async def on_events_btn(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        q = update.callback_query
        await q.answer()

        await self.on_events_list(update, context)

    async def _purge_events_job(context: ContextTypes.DEFAULT_TYPE):
        try:
            from ..infrastructure.events import purge_past_events
            n = purge_past_events()
            if n:
                logger.info("purged %d past events", n)
        except Exception:
            logger.exception("purge_past_events job failed")

    # ---------------- error & run ----------------

    async def on_error(self, update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
        logger.exception("Unhandled error in handler", exc_info=context.error)

    async def _send_more_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Отправить меню 'Ещё' через callback."""
        # Создаем фейковый callback query для обработки через существующий роутер
        class FakeCallbackQuery:
            def __init__(self, update):
                self.data = "ui:more"
                self.message = update.effective_message
                self.from_user = update.effective_user
                self.id = "fake"
        fake_query = FakeCallbackQuery(update)
        update.callback_query = fake_query
        await self.on_ui_btn(update, context)
    
    async def _send_full_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Отправить полное меню со всеми командами и подкомандами."""
        tf = context.user_data.get("tf", DEFAULT_TF)
        menu_text = "📋 <b>Главное меню</b>\n\nВыберите команду:"
        await update.effective_message.reply_text(
            menu_text,
            parse_mode=ParseMode.HTML,
            reply_markup=build_kb("main", tf, force_show=True),
        )
    
    async def _handle_top_button(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработка кнопки 'Топ'."""
        if self.integrator:
            await self.integrator.handle_command("top", update, context)
        else:
            await update.effective_message.reply_text("Команда /top временно недоступна")
    
    async def _handle_forecast_button(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработка кнопки 'Прогноз'."""
        if self.integrator:
            await self.integrator.handle_command("forecast", update, context)
        else:
            await update.effective_message.reply_text("Команда /forecast временно недоступна")

    async def _setup_menu_commands_async(self, application: Application):
        """Настройка меню-кнопки с быстрыми командами (вызывается при старте бота)."""
        commands = [
            BotCommand("start", "Запуск и приветствие"),
            BotCommand("help", "Справка"),
            BotCommand("status", "Отчёт"),
            BotCommand("bubbles", "Bubbles"),
            BotCommand("top", "Топ"),
            BotCommand("chart", "Чарты"),
            BotCommand("chart_album", "Альбом"),
            BotCommand("forecast", "Прогноз"),
            BotCommand("btc_options", "Опционы BTC"),
            BotCommand("twap", "TWAP сейчас"),
            BotCommand("altseason", "Altseason"),
            BotCommand("fng", "F&G"),
            BotCommand("instruction", "Инструкция"),
            BotCommand("full", "Полный отчёт"),
            BotCommand("help_full", "Полная справка"),
            BotCommand("eth_options", "Опционы ETH"),
        ]
        try:
            await application.bot.set_my_commands(commands)
            logger.info("Menu commands set successfully")
        except Exception as e:
            logger.warning("Failed to set menu commands: %s", e)
            # Не критично, продолжаем работу

    def run(self):
        try:
            admin = getattr(settings, "admin_chat_id", None)
            if admin:
                self.db.add_sub(int(admin))
        except Exception:
            logger.exception("add_sub admin failed")

        for attempt in range(1, 4):
            try:
                logger.info("Starting Telegram polling (attempt %d/3)...", attempt)
                self.app.run_polling(close_loop=False, drop_pending_updates=True)
                return
            except (TimedOut, NetworkError) as e:
                logger.warning("Telegram startup network issue: %s (attempt %d). Retrying...", e, attempt)
                asyncio.get_event_loop().run_until_complete(asyncio.sleep(2 * attempt))

        # если не взлетело 3 раза:
        raise RuntimeError("Telegram startup failed after retries due to repeated timeouts")


