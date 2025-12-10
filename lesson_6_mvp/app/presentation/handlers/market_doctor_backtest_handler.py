# app/presentation/handlers/market_doctor_backtest_handler.py
"""
Handler для backtest анализа Market Doctor.
"""

from telegram import Update
from telegram.ext import ContextTypes
from telegram.constants import ParseMode
from .base_handler import BaseHandler
import logging

from ...domain.market_diagnostics.backtest_analyzer import BacktestAnalyzer

logger = logging.getLogger("alt_forecast.handlers.market_doctor_backtest")


class MarketDoctorBacktestHandler(BaseHandler):
    """Обработчик команд для backtest анализа Market Doctor."""
    
    def __init__(self, db, services: dict = None):
        """
        Инициализация handler.
        
        Args:
            db: Экземпляр базы данных
            services: Словарь сервисов
        """
        super().__init__(db, services)
        self.backtest_analyzer = BacktestAnalyzer(db)
    
    async def handle_backtest_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработать команду /md_backtest."""
        try:
            args = context.args or []
            
            # Парсим аргументы: /md_backtest [symbol] [timeframe] [hours]
            symbol = args[0].upper().strip() if len(args) > 0 else None
            timeframe = args[1] if len(args) > 1 else None
            hours = int(args[2]) if len(args) > 2 and args[2].isdigit() else 24
            
            # Генерируем отчет
            report = self.backtest_analyzer.generate_backtest_report(
                symbol=symbol,
                timeframe=timeframe,
                hours=hours
            )
            
            await self._safe_reply_text(
                update,
                report,
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True
            )
        except Exception as e:
            logger.exception("handle_backtest_command failed")
            await self._safe_reply_text(
                update,
                f"❌ Ошибка при генерации backtest отчета: {str(e)}\n\n"
                "Использование: /md_backtest [символ] [таймфрейм] [часы]\n"
                "Пример: /md_backtest BTC 1h 24\n"
                "Пример: /md_backtest ETHUSDT 4h 48",
                parse_mode=ParseMode.HTML
            )


