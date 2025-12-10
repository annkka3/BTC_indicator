# app/presentation/handlers/chart_settings_callback_command.py
"""
Callback command для обработки настроек графика.
"""

from telegram import Update
from telegram.ext import ContextTypes
from .callback_commands import CallbackCommand
from .chart_settings_handler import handle_chart_settings_callback


class ChartSettingsCallbackCommand(CallbackCommand):
    """Команда для обработки callback'ов настроек графика."""
    
    async def execute(self, update: Update, context: ContextTypes.DEFAULT_TYPE, bot) -> None:
        """Выполнить обработку настроек графика."""
        await handle_chart_settings_callback(update, context, bot)















