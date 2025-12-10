# app/presentation/handlers/quota_handler.py
"""
Handler для мониторинга использования квоты CoinGecko API.
"""

from telegram import Update
from telegram.ext import ContextTypes
from telegram.constants import ParseMode
from .base_handler import BaseHandler
import logging

from ...infrastructure.quota import get_budget

logger = logging.getLogger("alt_forecast.handlers.quota")


class QuotaHandler(BaseHandler):
    """Обработчик команды для мониторинга квоты CoinGecko."""
    
    async def handle_quota_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработать команду /quota - статус использования квоты CoinGecko."""
        try:
            budget_info, limit = get_budget()
            
            used = budget_info["used"]
            remaining = budget_info["remaining"]
            percentage = budget_info["percentage"]
            month = budget_info["month"]
            
            # Определяем статус
            if percentage < 50:
                status_emoji = "🟢"
                status_text = "Норма"
            elif percentage < 80:
                status_emoji = "🟡"
                status_text = "Внимание"
            elif percentage < 95:
                status_emoji = "🟠"
                status_text = "Высокое использование"
            else:
                status_emoji = "🔴"
                status_text = "Критично"
            
            # Прогресс-бар
            bar_length = 20
            filled = int(bar_length * percentage / 100)
            bar = "█" * filled + "░" * (bar_length - filled)
            
            message = (
                f"📊 <b>Использование квоты CoinGecko API</b>\n"
                f"━━━━━━━━━━━━━━━━━━\n\n"
                f"📅 Месяц: <code>{month}</code>\n"
                f"📈 Использовано: <b>{used:,}</b> / {limit:,} запросов\n"
                f"📉 Осталось: <b>{remaining:,}</b> запросов\n"
                f"📊 Процент: <b>{percentage:.1f}%</b>\n\n"
                f"{status_emoji} Статус: <b>{status_text}</b>\n\n"
                f"<code>{bar}</code> {percentage:.1f}%\n\n"
                f"💡 <i>Кэширование активно для минимизации запросов.</i>\n"
                f"<i>Лимит: {limit:,} запросов в месяц (бесплатный план CoinGecko).</i>"
            )
            
            await update.message.reply_text(message, parse_mode=ParseMode.HTML)
        
        except Exception as e:
            logger.exception(f"Error in handle_quota_status: {e}")
            await update.message.reply_text(
                f"❌ Ошибка при получении статуса квоты: {str(e)}",
                parse_mode=ParseMode.MARKDOWN
            )


