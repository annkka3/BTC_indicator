# app/presentation/integration/command_integrator.py
"""
Интеграционный слой для постепенной миграции команд на новую архитектуру.
"""

from telegram import Update
from telegram.ext import ContextTypes
from typing import Dict, Callable, Optional
from ..handlers.handler_factory import HandlerFactory
import logging

logger = logging.getLogger("alt_forecast.integration")


class CommandIntegrator:
    """Интегратор для маршрутизации команд между старой и новой архитектурой."""
    
    def __init__(self, db):
        """
        Args:
            db: Database instance
        """
        self.db = db
        try:
            self.factory = HandlerFactory(db)
            self.handlers = self.factory.get_handlers()
            logger.info(f"CommandIntegrator initialized with {len(self.handlers)} handlers")
            # Проверяем наличие market_doctor handler
            if "market_doctor" in self.handlers:
                logger.info("Market Doctor handler found")
            else:
                logger.warning("Market Doctor handler NOT found in handlers dict")
        except Exception as e:
            logger.exception(f"Failed to initialize CommandIntegrator: {e}")
            raise
        
        # Маппинг команд на handlers
        self.command_map: Dict[str, Callable] = {
            # Команды
            "start": self._handle_start,
            "help": self._handle_help,
            "help_full": self._handle_help_full,
            "instruction": self._handle_instruction,
            
            # Отчеты
            "status": self._handle_status,
            "full": self._handle_full,
            
            # Пузырьки
            "bubbles": self._handle_bubbles,
            
            # Топ/Флоп
            "top_24h": self._handle_top_24h,
            "flop_24h": self._handle_flop_24h,
            "top_1h": self._handle_top_1h,
            "flop_1h": self._handle_flop_1h,
            "categories": self._handle_categories,
            
            # Графики
            "chart": self._handle_chart,
            "chart_15m": self._handle_chart_tf,
            "chart_1h": self._handle_chart_tf,
            "chart_4h": self._handle_chart_tf,
            "chart_1d": self._handle_chart_tf,
            "chart_album": self._handle_chart_album,
            "chart_album_15m": self._handle_chart_album_tf,
            "chart_album_1h": self._handle_chart_album_tf,
            "chart_album_4h": self._handle_chart_album_tf,
            "chart_album_1d": self._handle_chart_album_tf,
            
            # TWAP
            "twap": self._handle_twap,
            
            # Индексы
            "fng": self._handle_fng,
            "fng_history": self._handle_fng_history,
            "altseason": self._handle_altseason,
            
            # Опционы
            "btc_options": self._handle_btc_options,
            "eth_options": self._handle_eth_options,
            
            # Прогнозы
            "forecast": self._handle_forecast,
            "forecast_full": self._handle_forecast_full,
            "forecast_alts": self._handle_forecast_alts,
            "forecast_stats": self._handle_forecast_stats,
            
            # Дополнительные команды
            "instruction": self._handle_instruction,
            "trending": self._handle_trending,
            "global": self._handle_global,
            "daily": self._handle_daily,
            
            # Аналитика
            "corr": self._handle_corr,
            "beta": self._handle_beta,
            "vol": self._handle_vol,
            "funding": self._handle_funding,
            "basis": self._handle_basis,
            "liqs": self._handle_liqs,
            "levels": self._handle_levels,
            "risk_now": self._handle_risk_now,
            "backtest": self._handle_backtest,
            "breadth": self._handle_breadth,
            "scan_divs": self._handle_scan_divs,
            "ticker": self._handle_ticker,
            "events_add": self._handle_events_add,
            "events_list": self._handle_events_list,
            "events_del": self._handle_events_del,
            "subscribe": self._handle_subscribe,
            "unsubscribe": self._handle_unsubscribe,
            "categories": self._handle_categories,
            "options_btc_free": self._handle_options_btc_free,
            "options_eth_free": self._handle_options_eth_free,
            "cg_test": self._handle_cg_test,
            "bubbles_debug": self._handle_bubbles_debug,
            
            # Диагностика
            "diag": self._handle_diag,
            
            # Квота CoinGecko
            "quota": self._handle_quota,
            
            # Market Doctor
            "market_doctor": self._handle_market_doctor,
            "md": self._handle_market_doctor,
            "md_profile": self._handle_md_profile,
            "mdh": self._handle_mdh,
            "mdt": self._handle_mdt,
            "mdtop": self._handle_mdtop,
            "md_watch_add": self._handle_md_watch_add,
            "md_watch_remove": self._handle_md_watch_remove,
            "md_watch_list": self._handle_md_watch_list,
            "md_backtest": self._handle_md_backtest,
            "md_calibrate": self._handle_md_calibrate,
            "md_apply_weights": self._handle_md_apply_weights,
            "md_weights_list": self._handle_md_weights_list,
            "md_weights_reset": self._handle_md_weights_reset,
            "md_tag": self._handle_md_tag,
            "md_tags": self._handle_md_tags,
            "md_tag_remove": self._handle_md_tag_remove,
            
            # Новые функции: киты и тепловые карты
            "whale_orders": self._handle_whale_orders,
            "whale_activity": self._handle_whale_activity,
            "heatmap": self._handle_heatmap,
        }
    
    def get_handler(self, handler_name: str):
        """
        Получить handler по имени.
        
        Args:
            handler_name: Имя handler (например, "market_doctor")
        
        Returns:
            Handler instance или None
        """
        return self.handlers.get(handler_name)
    
    async def handle_command(self, command: str, update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
        """
        Обработать команду через новую архитектуру.
        
        Returns:
            True если команда обработана, False если нужно использовать старый код
        """
        handler = self.command_map.get(command)
        if handler:
            try:
                result = await handler(update, context)
                # Если handler вернул False, используем fallback
                if result is False:
                    return False
                return True
            except Exception as e:
                logger.exception("Error handling command %s: %s", command, e)
                return False
        return False
    
    # Команды
    async def _handle_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await self.handlers["command"].handle_start(update, context)
    
    async def _handle_help(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await self.handlers["command"].handle_help(update, context, short=True)
    
    async def _handle_help_full(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await self.handlers["command"].handle_help(update, context, short=False)
    
    async def _handle_instruction(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await self.handlers["command"].handle_instruction(update, context)
    
    # Отчеты
    async def _handle_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await self.handlers["report"].handle_status(update, context)
    
    async def _handle_full(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await self.handlers["report"].handle_full(update, context)
    
    # Пузырьки
    async def _handle_bubbles(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        # Определяем таймфрейм из аргументов или контекста
        args = context.args or []
        tf = args[0] if args and args[0] in ("15m", "1h", "1d") else context.user_data.get("tf_bubbles", "1d")
        await self.handlers["bubbles"].handle_bubbles_command(update, context, tf=tf)
    
    # Топ/Флоп
    async def _handle_top_24h(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await self.handlers["top_flop"].handle_top_24h(update, context)
    
    async def _handle_flop_24h(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await self.handlers["top_flop"].handle_flop_24h(update, context)
    
    async def _handle_top_1h(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await self.handlers["top_flop"].handle_top_1h(update, context)
    
    async def _handle_flop_1h(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await self.handlers["top_flop"].handle_flop_1h(update, context)
    
    async def _handle_categories(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await self.handlers["top_flop"].handle_categories(update, context)
    
    # Графики
    async def _handle_chart(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await self.handlers["chart"].handle_chart(update, context)
    
    async def _handle_chart_tf(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        # Извлекаем таймфрейм из команды
        command = update.effective_message.text.split()[0].replace("/", "")
        tf_map = {"chart_15m": "15m", "chart_1h": "1h", "chart_4h": "4h", "chart_1d": "1d"}
        tf = tf_map.get(command, "4h")
        context.user_data["tf"] = tf
        await self.handlers["chart"].handle_chart(update, context)
    
    async def _handle_chart_album(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await self.handlers["chart"].handle_chart_album(update, context)
    
    async def _handle_chart_album_tf(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        command = update.effective_message.text.split()[0].replace("/", "")
        tf_map = {"chart_album_15m": "15m", "chart_album_1h": "1h", "chart_album_4h": "4h", "chart_album_1d": "1d"}
        tf = tf_map.get(command, "4h")
        context.user_data["tf"] = tf
        await self.handlers["chart"].handle_chart_album(update, context)
    
    # TWAP
    async def _handle_twap(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await self.handlers["twap"].handle_twap(update, context)
    
    # Индексы
    async def _handle_fng(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await self.handlers["indices"].handle_fng(update, context)
    
    async def _handle_fng_history(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await self.handlers["indices"].handle_fng_history(update, context)
    
    async def _handle_altseason(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await self.handlers["indices"].handle_altseason(update, context)
    
    # Опционы
    async def _handle_btc_options(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await self.handlers["options"].handle_btc_options(update, context)
    
    async def _handle_eth_options(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await self.handlers["options"].handle_eth_options(update, context)
    
    # Прогнозы
    async def _handle_forecast(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await self.handlers["forecast"].handle_forecast(update, context)
    
    async def _handle_forecast_full(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await self.handlers["forecast"].handle_forecast_full(update, context)
    
    async def _handle_forecast_alts(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await self.handlers["forecast"].handle_forecast_alts(update, context)
    
    async def _handle_forecast_stats(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await self.handlers["forecast"].handle_forecast_stats(update, context)
    
    # Дополнительные команды
    async def _handle_instruction(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await self.handlers["command"].handle_instruction(update, context)
    
    async def _handle_trending(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await self.handlers["command"].handle_trending(update, context)
    
    async def _handle_global(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        # handle_global пока использует fallback, так как логика сложная
        # Пробуем вызвать handler, но он вернет False для fallback
        result = await self.handlers["command"].handle_global(update, context)
        if result is False:
            return False
        return True
    
    async def _handle_daily(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await self.handlers["command"].handle_daily(update, context)
    
    # Аналитика
    async def _handle_corr(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await self.handlers["analytics"].handle_corr(update, context)
    
    async def _handle_beta(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await self.handlers["analytics"].handle_beta(update, context)
    
    async def _handle_vol(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await self.handlers["analytics"].handle_vol(update, context)
    
    async def _handle_funding(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await self.handlers["analytics"].handle_funding(update, context)
    
    async def _handle_basis(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await self.handlers["analytics"].handle_basis(update, context)
    
    async def _handle_liqs(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await self.handlers["analytics"].handle_liqs(update, context)
    
    async def _handle_levels(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await self.handlers["analytics"].handle_levels(update, context)
    
    async def _handle_risk_now(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await self.handlers["analytics"].handle_risk_now(update, context)
    
    async def _handle_backtest(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await self.handlers["analytics"].handle_backtest(update, context)
    
    async def _handle_breadth(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await self.handlers["analytics"].handle_breadth(update, context)
    
    async def _handle_scan_divs(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await self.handlers["analytics"].handle_scan_divs(update, context)
    
    async def _handle_ticker(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await self.handlers["command"].handle_ticker(update, context)
    
    async def _handle_events_add(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await self.handlers["events"].handle_events_add(update, context)
    
    async def _handle_events_list(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await self.handlers["events"].handle_events_list(update, context)
    
    async def _handle_events_del(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await self.handlers["events"].handle_events_del(update, context)
    
    async def _handle_subscribe(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await self.handlers["command"].handle_subscribe(update, context)
    
    async def _handle_unsubscribe(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await self.handlers["command"].handle_unsubscribe(update, context)
    
    async def _handle_categories(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await self.handlers["top_flop"].handle_categories(update, context)
    
    async def _handle_options_btc_free(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await self.handlers["options"].handle_options_free(update, context, "BTC")
    
    async def _handle_options_eth_free(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await self.handlers["options"].handle_options_free(update, context, "ETH")
    
    async def _handle_cg_test(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await self.handlers["command"].handle_cg_test(update, context)
    
    async def _handle_bubbles_debug(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await self.handlers["bubbles"].handle_bubbles_debug(update, context)
    
    async def _handle_markets(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await self.handlers["command"].handle_traditional_markets(update, context)
    
    # Диагностика
    async def _handle_diag(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await self.handlers["diag"].handle_diag(update, context)
    
    # Квота CoinGecko
    async def _handle_quota(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        from ..handlers.quota_handler import QuotaHandler
        handler = QuotaHandler(self.db, self.services)
        await handler.handle_quota_status(update, context)
    
    # Market Doctor
    async def _handle_market_doctor(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        logger.info(f"_handle_market_doctor called via CommandIntegrator, args: {context.args}")
        if "market_doctor" not in self.handlers:
            logger.error("Market Doctor handler not found in handlers dict!")
            logger.error(f"Available handlers: {list(self.handlers.keys())}")
            raise KeyError("Market Doctor handler not found")
        await self.handlers["market_doctor"].handle_market_doctor(update, context)
    
    async def _handle_md_profile(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await self.handlers["market_doctor_profile"].handle_profile_command(update, context)
    
    async def _handle_mdh(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await self.handlers["market_doctor"].handle_market_doctor_brief(update, context)
    
    async def _handle_mdt(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await self.handlers["market_doctor"].handle_market_doctor_trade_only(update, context)
    
    async def _handle_mdtop(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await self.handlers["market_doctor"].handle_market_doctor_top(update, context)
    
    async def _handle_md_watch_add(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await self.handlers["market_doctor_watchlist"].handle_watchlist_add(update, context)
    
    async def _handle_md_watch_remove(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await self.handlers["market_doctor_watchlist"].handle_watchlist_remove(update, context)
    
    async def _handle_md_watch_list(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await self.handlers["market_doctor_watchlist"].handle_watchlist_list(update, context)
    
    async def _handle_md_backtest(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await self.handlers["market_doctor_backtest"].handle_backtest_command(update, context)
    
    async def _handle_md_tag(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await self.handlers["market_doctor_tag"].handle_md_tag(update, context)
    
    async def _handle_md_tags(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await self.handlers["market_doctor_tag"].handle_md_tags_list(update, context)
    
    async def _handle_md_tag_remove(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await self.handlers["market_doctor_tag"].handle_md_tag_remove(update, context)
    
    async def _handle_md_calibrate(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await self.handlers["market_doctor"].handle_market_doctor_calibrate(update, context)
    
    async def _handle_md_apply_weights(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await self.handlers["market_doctor"].handle_market_doctor_apply_weights(update, context)
    
    async def _handle_md_weights_list(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await self.handlers["market_doctor"].handle_market_doctor_weights_list(update, context)
    
    async def _handle_md_weights_reset(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await self.handlers["market_doctor"].handle_market_doctor_weights_reset(update, context)
    
    # Новые функции: киты и тепловые карты
    async def _handle_whale_orders(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await self.handlers["analytics"].handle_whale_orders(update, context)
    
    async def _handle_whale_activity(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await self.handlers["analytics"].handle_whale_activity(update, context)
    
    async def _handle_heatmap(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await self.handlers["analytics"].handle_heatmap(update, context)

