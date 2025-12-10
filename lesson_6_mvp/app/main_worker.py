# app/main_worker.py
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from .infrastructure.telegram_bot import TeleBot
from .utils.logging_config import setup_basic_logging

# Telegram-PTB job callbacks используют context
from telegram.ext import CallbackContext
from telegram.constants import ParseMode


# ---------- фоновые задачи (JobQueue) ----------

async def warm_market(context: CallbackContext) -> None:
    """
    Прогреваем кэш CoinGecko (markets_snapshot) — чтобы кнопки работали без лишних запросов.
    Стоимость: 1 запрос / запуск (только если кэш пуст).
    """
    log = logging.getLogger("alt_forecast.worker")
    try:
        from .infrastructure.coingecko import markets_snapshot
        result = markets_snapshot("usd")  # кэш внутри функции
        
        # Проверяем, что данные получены или есть в кэше
        if result and len(result) > 0:
            log.info(f"warm_market: OK (получено {len(result)} монет)")
        else:
            # Кэш пуст и API недоступен - это не критично, но логируем
            log.warning("warm_market: кэш пуст, API недоступен - данные будут недоступны до восстановления API")
    except Exception as e:
        log.exception("warm_market: FAIL: %s", e)


async def run_daily(context: CallbackContext) -> None:
    """
    Раз в час проверяем, кому отправить «ежедневку» в их локальный час (из user_settings.daily_hour).
    Формат: глобалка + топ/флоп 24h (из снапшота, не бьём API сверх плана).
    """
    log = logging.getLogger("alt_forecast.worker")
    try:
        app = context.application
        bot = app.bot
        telebot: TeleBot = app.bot_data["telebot"]  # положим в main()

        # Час в заданной таймзоне (берём из ENV TZ, по умолчанию Europe/Berlin)
        tz_name = os.getenv("TZ", "Europe/Berlin")
        now = datetime.now(ZoneInfo(tz_name))
        cur_hour = now.hour

        # Кого слать
        users = telebot.db.list_daily_users(cur_hour)
        if not users:
            return

        from .infrastructure.coingecko import global_stats, top_movers

        # один вызов top_movers (использует кэш снапшота)
        coins, gainers, losers, _ = top_movers("usd", "24h", 5)

        g = global_stats().get("data", {})
        mcap = g.get("total_market_cap", {}).get("usd")
        vol = g.get("total_volume", {}).get("usd")
        btc_d = g.get("market_cap_percentage", {}).get("btc")

        def sym_list(arr):  # короткий список тикеров
            return ", ".join([str(c.get("symbol", "")).upper() for c in arr])

        text = (
            "🌅 *Дайджест*\n"
            f"• Капа: ${float(mcap or 0):,.0f}\n"
            f"• 24h объём: ${float(vol or 0):,.0f}\n"
            f"• BTC доминация: {float(btc_d or 0):.1f}%\n\n"
            f"*Топ-5 24h*: {sym_list(gainers)}\n"
            f"*Флоп-5 24h*: {sym_list(losers)}"
        ).replace(",", " ")

        for uid in users:
            try:
                await bot.send_message(chat_id=uid, text=text, parse_mode=ParseMode.MARKDOWN, disable_web_page_preview=True)
            except Exception:
                log.exception("run_daily: send_message FAIL user=%s", uid)
        log.info("run_daily: sent to %d users at %02d:00 %s", len(users), cur_hour, tz_name)

    except Exception as e:
        log.exception("run_daily: FAIL: %s", e)


async def update_twap_detector(context: CallbackContext) -> None:
    """
    Периодическое обновление данных TWAP-детектора.
    Обновляет данные для BTC, ETH, SOL, XRP каждые 10 минут.
    """
    log = logging.getLogger("alt_forecast.worker.twap_detector")
    try:
        from .application.services.twap_detector_service import TWAPDetectorService
        
        detector_service = TWAPDetectorService()
        symbols = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT"]
        
        log.info("Starting TWAP detector update")
        for symbol in symbols:
            try:
                report = detector_service.get_twap_report(symbol, window_minutes=15, force_refresh=True)
                if report:
                    log.debug(
                        f"TWAP {symbol}: {report.dominant_direction}, "
                        f"algo_volume=${report.total_algo_volume_usd/1_000_000:.2f}M, "
                        f"sync={report.synchronization_score:.2f}"
                    )
            except Exception as e:
                log.exception(f"Error updating TWAP for {symbol}: {e}")
        
        log.info("Completed TWAP detector update")
    except Exception as e:
        log.exception(f"TWAP detector update failed: {e}")


async def collect_trades(context: CallbackContext) -> None:
    """
    Сбор сделок с бирж каждый час для кэширования в БД.
    Собирает данные за последний час и сохраняет их для быстрого доступа.
    """
    log = logging.getLogger("alt_forecast.worker.trades_collector")
    try:
        telebot: TeleBot = context.application.bot_data.get("telebot")
        if not telebot or not hasattr(telebot, 'db'):
            log.warning("Telebot or DB not available for trades collection")
            return
        
        from .application.services.trades_collector_service import TradesCollectorService
        
        collector = TradesCollectorService(telebot.db)
        
        log.info("Starting trades collection")
        results = collector.collect_all_symbols(window_minutes=60)
        
        total_trades = sum(results.values())
        log.info(f"Collected {total_trades} trades total: {results}")
        
        # Очищаем старые данные (старше 24 часов)
        deleted = collector.cleanup_old_trades(max_age_hours=24)
        if deleted > 0:
            log.info(f"Cleaned up {deleted} old trades")
        
    except Exception as e:
        log.exception(f"Trades collection failed: {e}")


async def evaluate_forecasts(context: CallbackContext) -> None:
    """
    Автоматически оценить качество старых прогнозов.
    Сравнивает предсказания с реальными результатами и обновляет метрики.
    Запускается каждые 2 часа.
    """
    log = logging.getLogger("alt_forecast.worker.forecast_evaluation")
    try:
        from .application.services.forecast_evaluation_service import ForecastEvaluationService
        
        telebot = context.bot_data.get("telebot")
        if not telebot or not hasattr(telebot, 'db'):
            log.warning("Telebot or DB not available for forecast evaluation")
            return
        
        db = telebot.db
        evaluation_service = ForecastEvaluationService(db)
        
        # Обновляем схему таблицы при первом запуске
        evaluation_service.update_forecast_history_schema()
        
        # Оцениваем прогнозы, которые должны были "сбыться"
        # min_age_hours = 1.0 означает, что мы оцениваем прогнозы, для которых
        # прошло хотя бы 1 час после окончания горизонта прогноза
        results = evaluation_service.evaluate_pending_forecasts(min_age_hours=1.0)
        
        log.info(
            f"Forecast evaluation completed: "
            f"evaluated={results['evaluated']}, "
            f"updated={results['updated']}, "
            f"errors={results['errors']}"
        )
        
        # Получаем метрики качества для логирования
        metrics = evaluation_service.get_forecast_quality_metrics(symbol="BTC")
        if metrics:
            log.info(
                f"Forecast quality metrics (BTC): "
                f"n_samples={metrics['n_samples']}, "
                f"hit_rate={metrics['hit_rate']:.2%}, "
                f"MAE={metrics['mae']:.4f}, "
                f"bias={metrics['bias']:.4f}"
            )
        
    except Exception as e:
        log.exception(f"Forecast evaluation failed: {e}")


async def generate_quality_reports(context: CallbackContext) -> None:
    """
    Генерировать автоматические отчёты о качестве моделей.
    Запускается раз в сутки.
    """
    log = logging.getLogger("alt_forecast.worker.quality_reports")
    try:
        from .application.services.model_quality_reporter import ModelQualityReporter
        
        telebot = context.bot_data.get("telebot")
        if not telebot or not hasattr(telebot, 'db'):
            log.warning("Telebot or DB not available for quality reports")
            return
        
        db = telebot.db
        reporter = ModelQualityReporter(db)
        
        # Генерируем отчёты для основных конфигураций
        configs = [
            ("BTC", "1h", 24),
            ("BTC", "4h", 24),
            ("BTC", "1d", 24),
        ]
        
        for symbol, timeframe, horizon in configs:
            try:
                report = reporter.generate_report(
                    symbol=symbol,
                    timeframe=timeframe,
                    horizon=horizon,
                    period_days=30
                )
                
                if report and report.alerts:
                    # Отправляем алерты админу
                    admin_chat_id = os.getenv("ADMIN_CHAT_ID")
                    if admin_chat_id:
                        try:
                            formatted = reporter.format_report(report)
                            await context.bot.send_message(
                                chat_id=int(admin_chat_id),
                                text=formatted,
                                parse_mode=ParseMode.HTML
                            )
                            log.info(f"Sent quality report alert for {symbol} {timeframe} H={horizon}")
                        except Exception as e:
                            log.exception(f"Failed to send quality report: {e}")
            except Exception as e:
                log.exception(f"Failed to generate report for {symbol} {timeframe} H={horizon}: {e}")
        
        log.info("Completed quality reports generation")
    except Exception as e:
        log.exception(f"Quality reports generation failed: {e}")


async def log_diagnostics_periodically(context: CallbackContext) -> None:
    """
    Периодическое логирование диагностик Market Doctor для статистического анализа.
    Логирует BTCUSDT и ETHUSDT по таймфреймам 1h, 4h, 1d каждые 30 минут.
    """
    log = logging.getLogger("alt_forecast.worker.diagnostics_logging")
    try:
        from .application.services.diagnostics_logging_service import DiagnosticsLoggingService
        from .infrastructure.market_data_service import MarketDataService
        
        telebot = context.bot_data.get("telebot")
        if not telebot or not hasattr(telebot, 'db'):
            log.warning("Telebot or DB not available for diagnostics logging")
            return
        
        db = telebot.db
        market_data_service = MarketDataService(db=db)
        service = DiagnosticsLoggingService(db, market_data_service)
        
        symbols = ["BTCUSDT", "ETHUSDT"]
        timeframes = ["1h", "4h", "1d"]
        
        log.info("Starting periodic diagnostics logging")
        
        for symbol in symbols:
            try:
                snapshot_ids = await service.log_diagnostics_for_symbol(symbol, timeframes)
                log.info(f"Logged diagnostics for {symbol}: {snapshot_ids}")
                
                # Вычисляем результаты для старых снимков
                for tf in timeframes:
                    await service.compute_results_for_snapshots(
                        symbol=symbol,
                        timeframe=tf,
                        horizon_bars=4,
                        horizon_hours=24.0
                    )
            
            except Exception as e:
                log.exception(f"Error logging diagnostics for {symbol}: {e}")
        
        log.info("Completed periodic diagnostics logging")
    
    except Exception as e:
        log.exception(f"log_diagnostics_periodically: FAIL: {e}")


async def hourly_top_setups(context: CallbackContext) -> None:
    """
    Ежечасное сканирование топ-сетапов Market Doctor.
    Отправляет топ-10 сетапов подписчикам (если настроено).
    """
    log = logging.getLogger("alt_forecast.worker.top_setups")
    try:
        from .application.services.market_scanner_service import MarketScannerService
        from .domain.market_diagnostics import DEFAULT_CONFIG
        
        # Получаем bot из context
        bot = context.bot
        telebot = context.bot_data.get("telebot")
        
        if not telebot:
            log.warning("TeleBot not found in bot_data")
            return
        
        db = telebot.db
        
        # Создаем сервис сканера
        scanner = MarketScannerService(db, DEFAULT_CONFIG)
        
        # Сканируем рынок
        timeframes = ["4h", "1d"]
        candidates = await scanner.scan_universe(
            symbols=None,  # Используем DEFAULT_TOP_COINS
            timeframes=timeframes,
            min_pump_score=0.7,
            max_risk_score=0.7,
            limit=10
        )
        
        if not candidates:
            log.info("No top setups found")
            return
        
        # Формируем отчет
        report = scanner.format_top_setups_report(candidates, timeframes)
        
        # Отправляем отчет всем пользователям, которые подписаны на уведомления
        # Пока отправляем только в лог, можно расширить для отправки подписчикам
        log.info(f"Top setups found: {len(candidates)}")
        log.debug(f"Report:\n{report}")
        
        # TODO: Добавить отправку подписчикам через подписки
        # Можно создать таблицу md_subscriptions для пользователей, которые хотят получать топ-сетапы
        
    except Exception as e:
        log.exception("hourly_top_setups: FAIL: %s", e)


async def hourly_bubbles(context: CallbackContext) -> None:
    """
    Ежечасная рассылка пузырей за 1 час.
    Кого слать: можно использовать существующие подписки subs (list_subs),
    либо завести отдельную настройку — здесь используем subs для простоты.
    """
    log = logging.getLogger("alt_forecast.worker")
    try:
        app = context.application
        telebot: TeleBot = app.bot_data["telebot"]

        # список подписчиков (твоя существующая таблица subs)
        chat_ids = telebot.db.list_subs()
        if not chat_ids:
            return

        # отсылаем «пузырь 1h» с реюзом метода бота (он сам использует кэш снапшота)
        for uid in chat_ids:
            try:
                await telebot._send_bubbles(chat_id=uid, context=context, tf="1h")
            except Exception:
                log.exception("hourly_bubbles: send FAIL chat_id=%s", uid)

        log.info("hourly_bubbles: sent to %d subs", len(chat_ids))
    except Exception as e:
        log.exception("hourly_bubbles: FAIL: %s", e)


# ---------- точка входа ----------

def main():
    # Базовый логгер проекта
    setup_basic_logging()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    )

    # Поднимаем телеграм-бота
    bot = TeleBot()

    # Делаем TeleBot доступным в job callbacks
    # (PTB хранит произвольные данные в application.bot_data)
    bot.app.bot_data["telebot"] = bot

    # Планировщик PTB
    jq = bot.app.job_queue

    # 1) Прогрев кэша CoinGecko — каждые 15 минут
    jq.run_repeating(warm_market, interval=15 * 60, first=5)

    # 2) Ежедневка — раз в час проверяем, чьё «окно»
    jq.run_repeating(run_daily, interval=60 * 60, first=30)

    # 3) Ежечасный «пузырь 1h» подписчикам
    jq.run_repeating(hourly_bubbles, interval=60 * 60, first=60)
    
    # 4) Ежечасное сканирование топ-сетапов Market Doctor
    jq.run_repeating(hourly_top_setups, interval=60 * 60, first=120)
    
    # 5) Периодическое логирование диагностик Market Doctor (каждые 30 минут)
    jq.run_repeating(log_diagnostics_periodically, interval=30 * 60, first=180)
    
    # 6) Сбор сделок с бирж каждый час для кэширования в БД
    jq.run_repeating(collect_trades, interval=60 * 60, first=300)  # Первый запуск через 5 минут

    # Запуск long-polling
    bot.run()


if __name__ == "__main__":
    main()
