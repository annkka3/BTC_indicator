# app/presentation/handlers/report_handler.py
"""
Handler for report commands (status, full).
"""

from telegram import Update
from telegram.ext import ContextTypes
from telegram.constants import ParseMode
from .base_handler import BaseHandler
from ...infrastructure.ui_keyboards import build_kb
import logging

logger = logging.getLogger("alt_forecast.handlers.reports")


class ReportHandler(BaseHandler):
    """Обработчик команд отчетов."""
    
    async def handle_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработать команду /status (краткий отчет)."""
        try:
            from ...usecases.generate_report import build_status_report
            
            chat_id = update.effective_chat.id
            report_html = build_status_report(self.db)
            
            await context.bot.send_message(
                chat_id=chat_id,
                text=report_html,
                parse_mode=ParseMode.HTML,
                reply_markup=build_kb('main'),
                disable_web_page_preview=True,
            )
        except Exception:
            logger.exception("handle_status failed")
    
    async def handle_full(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработать команду /full (полный отчет)."""
        try:
            from ...usecases.generate_report import build_full_report
            
            chat_id = update.effective_chat.id
            report_html = build_full_report(self.db)
            
            await context.bot.send_message(
                chat_id=chat_id,
                text=report_html,
                parse_mode=ParseMode.HTML,
                reply_markup=build_kb('main'),
                disable_web_page_preview=True,
            )
        except Exception:
            logger.exception("handle_full failed")

