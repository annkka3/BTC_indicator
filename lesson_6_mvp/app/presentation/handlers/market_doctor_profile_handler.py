# app/presentation/handlers/market_doctor_profile_handler.py
"""
Handler для управления профилями риска Market Doctor.
"""

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from telegram.constants import ParseMode
from .base_handler import BaseHandler
import logging

from ...domain.market_diagnostics.profile_provider import ProfileProvider, RiskProfile

logger = logging.getLogger("alt_forecast.handlers.market_doctor_profile")


class MarketDoctorProfileHandler(BaseHandler):
    """Обработчик команд для управления профилями риска Market Doctor."""
    
    def __init__(self, db, services: dict = None):
        """
        Инициализация handler.
        
        Args:
            db: Экземпляр базы данных
            services: Словарь сервисов
        """
        super().__init__(db, services)
        self.profile_provider = ProfileProvider(db)
    
    async def handle_profile_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработать команду /md_profile."""
        try:
            user_id = update.effective_user.id if update.effective_user else None
            if not user_id:
                await self._safe_reply_text(
                    update,
                    "❌ Не удалось определить пользователя.",
                    parse_mode=ParseMode.HTML
                )
                return
            
            # Получаем текущий профиль
            current_profile = self.profile_provider.get_profile(user_id)
            
            # Формируем клавиатуру с профилями
            keyboard = [
                [
                    InlineKeyboardButton(
                        f"{'✅' if current_profile == RiskProfile.CONSERVATIVE else '🛡'} Консервативный",
                        callback_data=f"ui:md:profile:{RiskProfile.CONSERVATIVE}"
                    )
                ],
                [
                    InlineKeyboardButton(
                        f"{'✅' if current_profile == RiskProfile.BALANCED else '⚖️'} Сбалансированный",
                        callback_data=f"ui:md:profile:{RiskProfile.BALANCED}"
                    )
                ],
                [
                    InlineKeyboardButton(
                        f"{'✅' if current_profile == RiskProfile.AGGRESSIVE else '🔥'} Агрессивный",
                        callback_data=f"ui:md:profile:{RiskProfile.AGGRESSIVE}"
                    )
                ],
            ]
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            # Формируем описание профилей
            profile_descriptions = {
                RiskProfile.CONSERVATIVE: (
                    "🛡 <b>Консервативный профиль</b>\n\n"
                    "• Более строгие пороги для входа\n"
                    "• Приоритет накопления и низкого риска\n"
                    "• Размер позиции: ~0.5R от базового\n"
                    "• Стратегия: accumulation_play"
                ),
                RiskProfile.BALANCED: (
                    "⚖️ <b>Сбалансированный профиль</b>\n\n"
                    "• Стандартные пороги и веса\n"
                    "• Баланс между риском и потенциалом\n"
                    "• Размер позиции: ~1.0R от базового\n"
                    "• Стратегия: автоматический выбор"
                ),
                RiskProfile.AGGRESSIVE: (
                    "🔥 <b>Агрессивный профиль</b>\n\n"
                    "• Более мягкие пороги для входа\n"
                    "• Приоритет тренд-фолловинга\n"
                    "• Размер позиции: до 1.5R от базового\n"
                    "• Стратегия: trend_follow"
                )
            }
            
            current_desc = profile_descriptions.get(current_profile, "")
            
            message = (
                f"⚙️ <b>Профиль риска Market Doctor</b>\n\n"
                f"Текущий профиль:\n{current_desc}\n\n"
                "Выберите новый профиль:"
            )
            
            await self._safe_reply_text(
                update,
                message,
                parse_mode=ParseMode.HTML,
                reply_markup=reply_markup
            )
        except Exception as e:
            logger.exception("handle_profile_command failed")
            await self._safe_reply_text(
                update,
                f"❌ Ошибка при загрузке профилей: {str(e)}",
                parse_mode=ParseMode.HTML
            )
    
    async def handle_profile_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработать callback выбора профиля."""
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
            
            # Извлекаем профиль из callback_data: ui:md:profile:conservative
            callback_data = query.data
            parts = callback_data.split(":")
            if len(parts) < 4:
                await query.edit_message_text(
                    "❌ Неверный формат команды.",
                    parse_mode=ParseMode.HTML
                )
                return
            
            profile = parts[3]
            
            if profile not in [RiskProfile.CONSERVATIVE, RiskProfile.BALANCED, RiskProfile.AGGRESSIVE]:
                await query.edit_message_text(
                    "❌ Неверный профиль.",
                    parse_mode=ParseMode.HTML
                )
                return
            
            # Устанавливаем профиль
            self.profile_provider.set_profile(user_id, profile)
            
            # Формируем сообщение подтверждения
            profile_names = {
                RiskProfile.CONSERVATIVE: "🛡 Консервативный",
                RiskProfile.BALANCED: "⚖️ Сбалансированный",
                RiskProfile.AGGRESSIVE: "🔥 Агрессивный"
            }
            
            profile_name = profile_names.get(profile, profile)
            
            await query.edit_message_text(
                f"✅ Профиль риска изменен на: <b>{profile_name}</b>\n\n"
                "Новые анализы Market Doctor будут использовать этот профиль.",
                parse_mode=ParseMode.HTML
            )
        except Exception as e:
            logger.exception("handle_profile_callback failed")
            if query:
                await query.answer(f"❌ Ошибка: {str(e)}", show_alert=True)


