# app/presentation/handlers/market_doctor_watchlist_handler.py
"""
Handler для управления watchlist Market Doctor.
"""

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from telegram.constants import ParseMode
from .base_handler import BaseHandler
import logging

from ...infrastructure.repositories.watchlist_repository import WatchlistRepository

logger = logging.getLogger("alt_forecast.handlers.market_doctor_watchlist")


class MarketDoctorWatchlistHandler(BaseHandler):
    """Обработчик команд для управления watchlist Market Doctor."""
    
    def __init__(self, db, services: dict = None):
        """
        Инициализация handler.
        
        Args:
            db: Экземпляр базы данных
            services: Словарь сервисов
        """
        super().__init__(db, services)
        self.watchlist_repo = WatchlistRepository(db)
    
    async def handle_watchlist_add(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработать команду /md_watch_add <symbol>."""
        try:
            user_id = update.effective_user.id if update.effective_user else None
            if not user_id:
                await self._safe_reply_text(
                    update,
                    "❌ Не удалось определить пользователя.",
                    parse_mode=ParseMode.HTML
                )
                return
            
            args = context.args or []
            if not args:
                await self._safe_reply_text(
                    update,
                    "Использование: /md_watch_add <символ>\n"
                    "Пример: /md_watch_add BTC\n"
                    "Пример: /md_watch_add ETHUSDT",
                    parse_mode=ParseMode.HTML
                )
                return
            
            symbol = args[0].upper().strip()
            
            # Добавляем символ в watchlist
            added = self.watchlist_repo.add_symbol(user_id, symbol)
            
            if added:
                await self._safe_reply_text(
                    update,
                    f"✅ Символ <b>{symbol}</b> добавлен в ваш watchlist.\n\n"
                    "Теперь Market Doctor будет мониторить этот тикер в фоновом режиме.",
                    parse_mode=ParseMode.HTML
                )
            else:
                await self._safe_reply_text(
                    update,
                    f"ℹ️ Символ <b>{symbol}</b> уже есть в вашем watchlist.",
                    parse_mode=ParseMode.HTML
                )
        except Exception as e:
            logger.exception("handle_watchlist_add failed")
            await self._safe_reply_text(
                update,
                f"❌ Ошибка при добавлении символа: {str(e)}",
                parse_mode=ParseMode.HTML
            )
    
    async def handle_watchlist_remove(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработать команду /md_watch_remove <symbol>."""
        try:
            user_id = update.effective_user.id if update.effective_user else None
            if not user_id:
                await self._safe_reply_text(
                    update,
                    "❌ Не удалось определить пользователя.",
                    parse_mode=ParseMode.HTML
                )
                return
            
            args = context.args or []
            if not args:
                await self._safe_reply_text(
                    update,
                    "Использование: /md_watch_remove <символ>\n"
                    "Пример: /md_watch_remove BTC",
                    parse_mode=ParseMode.HTML
                )
                return
            
            symbol = args[0].upper().strip()
            
            # Удаляем символ из watchlist
            removed = self.watchlist_repo.remove_symbol(user_id, symbol)
            
            if removed:
                await self._safe_reply_text(
                    update,
                    f"✅ Символ <b>{symbol}</b> удален из вашего watchlist.",
                    parse_mode=ParseMode.HTML
                )
            else:
                await self._safe_reply_text(
                    update,
                    f"ℹ️ Символ <b>{symbol}</b> не найден в вашем watchlist.",
                    parse_mode=ParseMode.HTML
                )
        except Exception as e:
            logger.exception("handle_watchlist_remove failed")
            await self._safe_reply_text(
                update,
                f"❌ Ошибка при удалении символа: {str(e)}",
                parse_mode=ParseMode.HTML
            )
    
    async def handle_watchlist_list(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработать команду /md_watch_list."""
        try:
            user_id = update.effective_user.id if update.effective_user else None
            if not user_id:
                await self._safe_reply_text(
                    update,
                    "❌ Не удалось определить пользователя.",
                    parse_mode=ParseMode.HTML
                )
                return
            
            # Получаем список символов в watchlist
            symbols = self.watchlist_repo.get_user_watchlist(user_id)
            
            if not symbols:
                await self._safe_reply_text(
                    update,
                    "📋 Ваш watchlist пуст.\n\n"
                    "Добавьте символы командой: /md_watch_add <символ>",
                    parse_mode=ParseMode.HTML
                )
                return
            
            # Формируем список с кнопками для удаления
            lines = ["📋 <b>Ваш watchlist:</b>\n"]
            
            keyboard = []
            for symbol in symbols:
                lines.append(f"• {symbol}")
                keyboard.append([
                    InlineKeyboardButton(
                        f"❌ Удалить {symbol}",
                        callback_data=f"ui:md:watch:remove:{symbol}"
                    )
                ])
            
            reply_markup = InlineKeyboardMarkup(keyboard) if keyboard else None
            
            await self._safe_reply_text(
                update,
                "\n".join(lines),
                parse_mode=ParseMode.HTML,
                reply_markup=reply_markup
            )
        except Exception as e:
            logger.exception("handle_watchlist_list failed")
            await self._safe_reply_text(
                update,
                f"❌ Ошибка при получении watchlist: {str(e)}",
                parse_mode=ParseMode.HTML
            )
    
    async def handle_watchlist_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработать callback для watchlist."""
        try:
            query = update.callback_query
            if not query:
                return
            
            await query.answer()
            
            user_id = update.effective_user.id if update.effective_user else None
            if not user_id:
                await query.edit_message_text(
                    "❌ Не удалось определить пользователя.",
                    parse_mode=ParseMode.HTML
                )
                return
            
            # Извлекаем действие из callback_data: ui:md:watch:remove:BTC
            callback_data = query.data
            parts = callback_data.split(":")
            if len(parts) < 5:
                await query.edit_message_text(
                    "❌ Неверный формат команды.",
                    parse_mode=ParseMode.HTML
                )
                return
            
            action = parts[3]
            symbol = parts[4]
            
            if action == "remove":
                removed = self.watchlist_repo.remove_symbol(user_id, symbol)
                if removed:
                    await query.edit_message_text(
                        f"✅ Символ <b>{symbol}</b> удален из вашего watchlist.",
                        parse_mode=ParseMode.HTML
                    )
                else:
                    await query.answer("Символ не найден в watchlist", show_alert=True)
        except Exception as e:
            logger.exception("handle_watchlist_callback failed")
            if query:
                await query.answer(f"❌ Ошибка: {str(e)}", show_alert=True)


