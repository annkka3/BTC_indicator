# app/presentation/handlers/callback_router.py
"""
Router for callback queries using Command pattern.
"""

from typing import Dict, Optional
from telegram import Update
from telegram.ext import ContextTypes
from .callback_commands import (
    CallbackCommand,
    NavigationCommand,
    BackCommand,
    TimeframeSelectCommand,
    TimeframeSetCommand,
    BotCommandExecutionCommand,
    TimeframeCommandExecutionCommand,
    SymbolCommandExecutionCommand,
    BubblesCommand,
    TopFlopCommand,
    DefaultCommand,
    WhaleActivitySymbolCommand,
)
from .market_doctor_callback_commands import (
    MarketDoctorTfSelectCommand,
    MarketDoctorSymbolCommand,
    MarketDoctorCustomSymbolCommand,
)
from .market_doctor_format_command import MarketDoctorFormatCommand
import logging

logger = logging.getLogger("alt_forecast.handlers.router")


class CallbackRouter:
    """Роутер для callback'ов с использованием паттерна Command."""
    
    def __init__(self, handlers: Optional[Dict[str, CallbackCommand]] = None, integrator=None):
        """
        Args:
            handlers: Словарь обработчиков callback'ов {pattern: Command}
            integrator: CommandIntegrator для использования новой архитектуры
        """
        self.handlers = handlers or {}
        self.integrator = integrator
        self.default_handler: Optional[CallbackCommand] = DefaultCommand()
    
    def register(self, pattern: str, command: CallbackCommand):
        """Зарегистрировать обработчик для паттерна."""
        self.handlers[pattern] = command
    
    def set_default(self, command: CallbackCommand):
        """Установить обработчик по умолчанию."""
        self.default_handler = command
    
    async def handle(self, update: Update, context: ContextTypes.DEFAULT_TYPE, bot) -> None:
        """Обработать callback query."""
        q = update.callback_query
        if not q:
            return
        
        data = q.data
        
        # Сортируем паттерны по длине (более специфичные первыми)
        sorted_patterns = sorted(self.handlers.items(), key=lambda x: len(x[0]), reverse=True)
        
        # Ищем подходящий обработчик
        from telegram.error import BadRequest
        for pattern, command in sorted_patterns:
            # Проверяем точное совпадение или начало с паттерном
            # Для паттернов, заканчивающихся на ":", проверяем startswith
            # Для остальных - точное совпадение или startswith с ":"
            matches = False
            if data == pattern:
                matches = True
            elif pattern.endswith(":") and data.startswith(pattern):
                matches = True
            elif not pattern.endswith(":") and data.startswith(pattern + ":"):
                matches = True
            
            if matches:
                try:
                    # Проверяем, является ли command функцией или объектом с методом execute
                    if callable(command) and not hasattr(command, 'execute'):
                        # Это функция, вызываем напрямую
                        await command(update, context, bot)
                    else:
                        # Это объект с методом execute
                        await command.execute(update, context, bot)
                    return
                except BadRequest as e:
                    # Игнорируем ошибку "Message is not modified"
                    error_msg = str(e).lower()
                    if "not modified" in error_msg:
                        logger.debug("Message not modified for pattern %s, ignoring", pattern)
                    else:
                        # Логируем ошибку, но не прерываем выполнение - команда уже вызвана
                        logger.warning("BadRequest for pattern %s: %s (command may have executed)", pattern, e)
                    return
                except Exception as e:
                    logger.exception("Error executing command for pattern %s: %s", pattern, e)
                    return
        
        # Если не нашли, используем обработчик по умолчанию
        if self.default_handler:
            try:
                await self.default_handler.execute(update, context, bot)
            except BadRequest as e:
                # Игнорируем ошибку "Message is not modified"
                if "not modified" in str(e).lower():
                    logger.debug("Message not modified for default handler, ignoring")
                else:
                    logger.exception("Error executing default command: %s", e)
            except Exception as e:
                logger.exception("Error executing default command: %s", e)
        else:
            logger.warning("No handler found for callback data: %s", data)
            await q.answer("Команда не распознана", show_alert=False)
    
    @staticmethod
    def create_default_router(integrator=None, db=None) -> 'CallbackRouter':
        """Создать роутер с дефолтными обработчиками."""
        router = CallbackRouter(integrator=integrator)
        
        # Импортируем команды для графиков
        from .chart_callback_commands import (
            ChartTfSelectCommand,
            ChartSummaryCommand,
            ChartSymbolCommand,
            ChartCustomCommand,
            ChartSettingsCommand,
        )
        
        # Навигация
        router.register("ui:main", NavigationCommand("main"))
        router.register("ui:more", NavigationCommand("more"))
        router.register("ui:help", NavigationCommand("help"))
        router.register("ui:report", NavigationCommand("report"))
        router.register("ui:charts", NavigationCommand("charts"))
        router.register("ui:album", NavigationCommand("album"))
        router.register("ui:bubbles", NavigationCommand("bubbles"))
        router.register("ui:top", NavigationCommand("top"))
        router.register("ui:options", NavigationCommand("options"))
        router.register("ui:vol", NavigationCommand("vol"))
        router.register("ui:levels", NavigationCommand("levels"))
        router.register("ui:corr", NavigationCommand("corr"))
        router.register("ui:beta", NavigationCommand("beta"))
        router.register("ui:funding", NavigationCommand("funding"))
        router.register("ui:basis", NavigationCommand("basis"))
        router.register("ui:bt_rsi", NavigationCommand("bt_rsi"))
        router.register("ui:breadth", NavigationCommand("breadth"))
        router.register("ui:forecast", NavigationCommand("forecast"))
        router.register("ui:md", NavigationCommand("md"))
        router.register("ui:whale_orders", NavigationCommand("whale_orders"))
        router.register("ui:whale_activity", NavigationCommand("whale_activity"))
        router.register("ui:heatmap", NavigationCommand("heatmap"))
        router.register("ui:back", BackCommand())
        router.register("ui:tf", TimeframeSelectCommand())
        
        # Установка таймфрейма
        router.register("ui:tf:set:", TimeframeSetCommand())
        
        # Справка/Отчёт
        router.register("ui:help:short", BotCommandExecutionCommand("help", integrator))
        router.register("ui:help:full", BotCommandExecutionCommand("help_full", integrator))
        router.register("ui:report:short", BotCommandExecutionCommand("status", integrator))
        router.register("ui:report:full", BotCommandExecutionCommand("full", integrator))
        
        # Чарты - новое меню с символами
        if db:
            from .chart_settings_callback_command import ChartSettingsCallbackCommand
            router.register("ui:chart:tf:", ChartTfSelectCommand())
            router.register("ui:chart:summary:", ChartSummaryCommand())
            router.register("ui:chart:symbol:", ChartSymbolCommand(db))
            router.register("ui:chart:custom:", ChartCustomCommand())
            router.register("ui:chart:settings", ChartSettingsCommand())
            # Обработчики настроек графика
            router.register("ui:chart:settings:", ChartSettingsCallbackCommand())
        
        # Старые обработчики для обратной совместимости
        router.register("ui:chart:", TimeframeCommandExecutionCommand("chart", integrator))
        router.register("ui:album:", TimeframeCommandExecutionCommand("chart_album", integrator))
        
        # Волатильность / Уровни
        router.register("ui:vol:", TimeframeCommandExecutionCommand("vol", integrator))
        router.register("ui:levels:", TimeframeCommandExecutionCommand("levels", integrator))
        
        # Корреляция/Бета/Фандинг/Базис/Дивергенции/BT RSI/Ширина
        router.register("ui:corr:", TimeframeCommandExecutionCommand("corr", integrator))
        router.register("ui:beta:", TimeframeCommandExecutionCommand("beta", integrator))
        router.register("ui:funding:", SymbolCommandExecutionCommand("funding", integrator))
        router.register("ui:basis:", SymbolCommandExecutionCommand("basis", integrator))
        router.register("ui:scan_divs:", TimeframeCommandExecutionCommand("scan_divs", integrator))
        router.register("ui:bt_rsi:", TimeframeCommandExecutionCommand("backtest", integrator))
        router.register("ui:breadth:", TimeframeCommandExecutionCommand("breadth", integrator))
        router.register("ui:scan_divs", BotCommandExecutionCommand("scan_divs", integrator))
        
        # Новые функции: киты и тепловые карты
        router.register("ui:whale_orders:", SymbolCommandExecutionCommand("whale_orders", integrator))
        router.register("ui:whale_activity:", BotCommandExecutionCommand("whale_activity", integrator))
        router.register("ui:whale_activity_symbol:", WhaleActivitySymbolCommand())
        router.register("ui:heatmap:", SymbolCommandExecutionCommand("heatmap", integrator))
        
        # Пузырьки
        router.register("ui:bubbles:", BubblesCommand(integrator))
        
        # Прямые команды
        router.register("ui:cmd:/vol", BotCommandExecutionCommand("vol", integrator))
        router.register("ui:cmd:/levels", BotCommandExecutionCommand("levels", integrator))
        router.register("ui:cmd:/trending", BotCommandExecutionCommand("trending", integrator))
        router.register("ui:cmd:/global", BotCommandExecutionCommand("global", integrator))
        router.register("ui:cmd:/daily", BotCommandExecutionCommand("daily", integrator))
        router.register("ui:cmd:/btc_options", BotCommandExecutionCommand("btc_options", integrator))
        router.register("ui:cmd:/eth_options", BotCommandExecutionCommand("eth_options", integrator))
        router.register("ui:cmd:/top_24h", TopFlopCommand("top_24h", "24h", integrator))
        router.register("ui:cmd:/flop_24h", TopFlopCommand("flop_24h", "24h", integrator))
        router.register("ui:cmd:/top_1h", TopFlopCommand("top_1h", "1h", integrator))
        router.register("ui:cmd:/flop_1h", TopFlopCommand("flop_1h", "1h", integrator))
        router.register("ui:cmd:/twap", BotCommandExecutionCommand("twap", integrator))
        router.register("ui:cmd:/instruction", BotCommandExecutionCommand("instruction", integrator))
        router.register("ui:cmd:/beta", BotCommandExecutionCommand("beta", integrator))
        router.register("ui:cmd:/funding", BotCommandExecutionCommand("funding", integrator))
        router.register("ui:cmd:/basis", BotCommandExecutionCommand("basis", integrator))
        router.register("ui:cmd:/scan_divs", BotCommandExecutionCommand("scan_divs", integrator))
        router.register("ui:cmd:/levels", BotCommandExecutionCommand("levels", integrator))
        router.register("ui:cmd:/risk_now", BotCommandExecutionCommand("risk_now", integrator))
        router.register("ui:cmd:/events_list", BotCommandExecutionCommand("events_list", integrator))
        router.register("ui:cmd:/breadth", BotCommandExecutionCommand("breadth", integrator))
        router.register("ui:cmd:/categories", BotCommandExecutionCommand("categories", integrator))
        router.register("ui:cmd:/fng", BotCommandExecutionCommand("fng", integrator))
        router.register("ui:cmd:/altseason", BotCommandExecutionCommand("altseason", integrator))
        router.register("ui:cmd:/fng_history", BotCommandExecutionCommand("fng_history", integrator))
        router.register("ui:cmd:/ticker", BotCommandExecutionCommand("ticker", integrator))
        router.register("ui:cmd:/forecast", BotCommandExecutionCommand("forecast", integrator))
        router.register("ui:cmd:/forecast3", BotCommandExecutionCommand("forecast3", integrator))
        router.register("ui:cmd:/forecast_full", BotCommandExecutionCommand("forecast_full", integrator))
        router.register("ui:cmd:/forecast_alts", BotCommandExecutionCommand("forecast_alts", integrator))
        
        # Прогноз с таймфреймом
        router.register("ui:forecast:", TimeframeCommandExecutionCommand("forecast", integrator))
        
        # Market Doctor
        from .market_doctor_callback_commands import (
            MarketDoctorTfSelectCommand,
            MarketDoctorSymbolCommand,
            MarketDoctorCustomSymbolCommand,
        )
        from .market_doctor_format_command import MarketDoctorFormatCommand
        router.register("ui:md:format:", MarketDoctorFormatCommand())
        router.register("ui:md:tf:", MarketDoctorTfSelectCommand())
        router.register("ui:md:symbol:", MarketDoctorSymbolCommand(integrator))
        router.register("ui:md:custom:", MarketDoctorCustomSymbolCommand())
        
        # Market Doctor Profile callbacks
        if db:
            from .market_doctor_profile_handler import MarketDoctorProfileHandler
            profile_handler = MarketDoctorProfileHandler(db)
            async def handle_profile_callback(u, c, b):
                await profile_handler.handle_profile_callback(u, c)
            router.register("ui:md:profile:", handle_profile_callback)
            
            # Market Doctor Watchlist callbacks
            from .market_doctor_watchlist_handler import MarketDoctorWatchlistHandler
            watchlist_handler = MarketDoctorWatchlistHandler(db)
            async def handle_watchlist_callback(u, c, b):
                await watchlist_handler.handle_watchlist_callback(u, c)
            router.register("ui:md:watch:", handle_watchlist_callback)
        router.register("ui:cmd:/bubbles_1h", BotCommandExecutionCommand("bubbles", integrator))
        router.register("ui:cmd:/bubbles_24h", BotCommandExecutionCommand("bubbles", integrator))
        router.register("ui:cmd:/liqs", BotCommandExecutionCommand("liqs", integrator))
        router.register("ui:cmd:/bt", BotCommandExecutionCommand("backtest", integrator))
        
        # Категории: Тренды и Глобалка
        router.register("categories:trending", BotCommandExecutionCommand("trending", integrator))
        router.register("categories:global", BotCommandExecutionCommand("global", integrator))
        
        # Команды с TF
        router.register("ui:cmdtf:/chart", BotCommandExecutionCommand("chart", integrator))
        router.register("ui:cmdtf:/chart_album", BotCommandExecutionCommand("chart_album", integrator))
        router.register("ui:cmdtf:/corr", BotCommandExecutionCommand("corr", integrator))
        router.register("ui:cmdtf:/vol", BotCommandExecutionCommand("vol", integrator))
        router.register("ui:cmdtf:/levels", BotCommandExecutionCommand("levels", integrator))
        router.register("ui:cmdtf:/forecast", BotCommandExecutionCommand("forecast", integrator))
        router.register("ui:cmdtf:/forecast_full", BotCommandExecutionCommand("forecast_full", integrator))
        router.register("ui:cmdtf:/forecast3", BotCommandExecutionCommand("forecast3", integrator))
        
        return router
