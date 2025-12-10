# app/presentation/handlers/market_doctor_tag_handler.py
"""
Handler for Market Doctor tagging commands.
"""

from telegram import Update
from telegram.ext import ContextTypes
from telegram.constants import ParseMode
from .base_handler import BaseHandler
import logging

from ...infrastructure.repositories.tag_repository import TagRepository

logger = logging.getLogger("alt_forecast.handlers.market_doctor_tag")


class MarketDoctorTagHandler(BaseHandler):
    """Обработчик команд для тегирования Market Doctor."""
    
    def __init__(self, db, services: dict = None):
        """
        Инициализация handler.
        
        Args:
            db: Экземпляр базы данных
            services: Словарь сервисов
        """
        super().__init__(db, services)
        self.tag_repo = TagRepository(db)
    
    async def handle_md_tag(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        Обработать команду /md_tag - добавить тег к символу.
        
        Формат: /md_tag <symbol> <tag> [timeframe] [comment]
        Пример: /md_tag BTC good_entry 1h Отличный вход
        """
        try:
            user_id = update.effective_user.id if update.effective_user else None
            if not user_id:
                await update.effective_message.reply_text("❌ Не удалось определить пользователя.")
                return
            
            args = context.args or []
            
            if len(args) < 2:
                await update.effective_message.reply_text(
                    "❌ Неверный формат команды.\n\n"
                    "Использование: /md_tag <symbol> <tag> [timeframe] [comment]\n"
                    "Пример: /md_tag BTC good_entry 1h Отличный вход\n\n"
                    "Доступные теги: good_entry, fakeout, overhyped, weak_setup, strong_setup"
                )
                return
            
            symbol = args[0].upper()
            tag = args[1].lower()
            timeframe = args[2] if len(args) > 2 else None
            comment = " ".join(args[3:]) if len(args) > 3 else None
            
            # Валидация тега
            valid_tags = [
                "good_entry", "fakeout", "overhyped", "weak_setup", "strong_setup",
                "breakout_failed", "breakout_confirmed", "reversal", "continuation"
            ]
            if tag not in valid_tags:
                await update.effective_message.reply_text(
                    f"❌ Неверный тег: {tag}\n\n"
                    f"Доступные теги: {', '.join(valid_tags)}"
                )
                return
            
            # Добавляем тег
            tag_id = self.tag_repo.add_tag(
                user_id=user_id,
                symbol=symbol,
                tag=tag,
                timeframe=timeframe,
                comment=comment
            )
            
            response = f"✅ Тег добавлен: {symbol} → {tag}"
            if timeframe:
                response += f" ({timeframe})"
            if comment:
                response += f"\nКомментарий: {comment}"
            
            await update.effective_message.reply_text(response)
        except Exception as e:
            logger.exception(f"Error in handle_md_tag: {e}")
            await update.effective_message.reply_text(
                f"❌ Ошибка при добавлении тега: {e}"
            )
    
    async def handle_md_tags_list(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        Обработать команду /md_tags - показать теги для символа или пользователя.
        
        Формат: /md_tags [symbol]
        Пример: /md_tags BTC
        """
        try:
            user_id = update.effective_user.id if update.effective_user else None
            if not user_id:
                await update.effective_message.reply_text("❌ Не удалось определить пользователя.")
                return
            
            args = context.args or []
            symbol = args[0].upper() if args else None
            
            # Получаем теги
            tags = self.tag_repo.get_tags(symbol=symbol, user_id=user_id)
            
            if not tags:
                if symbol:
                    response = f"📋 Теги для {symbol} не найдены."
                else:
                    response = "📋 У вас нет тегов."
            else:
                response = f"📋 Теги{' для ' + symbol if symbol else ''}:\n\n"
                for tag in tags[:20]:  # Ограничиваем 20 тегами
                    tag_line = f"• {tag['symbol']} → {tag['tag']}"
                    if tag['timeframe']:
                        tag_line += f" ({tag['timeframe']})"
                    if tag['comment']:
                        tag_line += f" - {tag['comment']}"
                    response += tag_line + "\n"
                
                if len(tags) > 20:
                    response += f"\n... и еще {len(tags) - 20} тегов"
            
            await update.effective_message.reply_text(response)
        except Exception as e:
            logger.exception(f"Error in handle_md_tags_list: {e}")
            await update.effective_message.reply_text(
                f"❌ Ошибка при получении тегов: {e}"
            )
    
    async def handle_md_tag_remove(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        Обработать команду /md_tag_remove - удалить тег.
        
        Формат: /md_tag_remove <tag_id>
        Пример: /md_tag_remove 123
        """
        try:
            user_id = update.effective_user.id if update.effective_user else None
            if not user_id:
                await update.effective_message.reply_text("❌ Не удалось определить пользователя.")
                return
            
            args = context.args or []
            if not args:
                await update.effective_message.reply_text(
                    "❌ Неверный формат команды.\n\n"
                    "Использование: /md_tag_remove <tag_id>\n"
                    "Пример: /md_tag_remove 123\n\n"
                    "ID тега можно найти в /md_tags"
                )
                return
            
            try:
                tag_id = int(args[0])
            except ValueError:
                await update.effective_message.reply_text("❌ ID тега должен быть числом.")
                return
            
            # Удаляем тег
            removed = self.tag_repo.remove_tag(tag_id, user_id)
            
            if removed:
                await update.effective_message.reply_text(f"✅ Тег #{tag_id} удален.")
            else:
                await update.effective_message.reply_text(
                    f"❌ Тег #{tag_id} не найден или вы не имеете прав на его удаление."
                )
        except Exception as e:
            logger.exception(f"Error in handle_md_tag_remove: {e}")
            await update.effective_message.reply_text(
                f"❌ Ошибка при удалении тега: {e}"
            )






