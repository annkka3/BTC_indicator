# app/presentation/handlers/market_doctor_format_command.py
"""
Callback command для выбора формата отчёта Market Doctor (краткий/полный).
"""

from telegram import Update
from telegram.ext import ContextTypes
from .callback_commands import CallbackCommand
from ...infrastructure.ui_keyboards import kb_md_tf_menu, kb_md_format_menu
import logging

logger = logging.getLogger("alt_forecast.handlers.md_format")


class MarketDoctorFormatCommand(CallbackCommand):
    """Команда для выбора формата отчёта (краткий/полный) в Market Doctor."""
    
    async def execute(self, update: Update, context: ContextTypes.DEFAULT_TYPE, bot) -> None:
        q = update.callback_query
        await q.answer()
        
        ud = context.user_data
        
        # Извлекаем действие из callback data
        parts = q.data.split(":")
        if len(parts) >= 4:
            action = parts[3]  # "brief", "full" или "toggle_v2"
            
            if action == "toggle_v2":
                # Переключаем генератор v2
                current_v2 = ud.get("md_use_v2", False)
                ud["md_use_v2"] = not current_v2
                
                # Обновляем меню с новым статусом
                use_v2 = ud.get("md_use_v2", False)
                try:
                    await q.edit_message_reply_markup(
                        reply_markup=kb_md_format_menu(use_v2=use_v2)
                    )
                except Exception as e:
                    logger.exception("Error editing message for MD format menu: %s", e)
                return
            
            # Обработка выбора формата (brief/full)
            format_type = action
            brief = format_type == "brief"
            
            # Сохраняем выбор формата
            ud["md_format"] = format_type
            ud["md_brief"] = brief
            
            # Показываем меню выбора таймфрейма
            is_media = q.message and (q.message.photo or q.message.video or q.message.document)
            
            if is_media:
                await q.message.reply_text(
                    "Выберите таймфрейм:",
                    reply_markup=kb_md_tf_menu(brief=brief)
                )
            else:
                try:
                    await q.edit_message_reply_markup(
                        reply_markup=kb_md_tf_menu(brief=brief)
                    )
                except Exception as e:
                    logger.exception("Error editing message for MD TF menu: %s", e)
                    await q.message.reply_text(
                        "Выберите таймфрейм:",
                        reply_markup=kb_md_tf_menu(brief=brief)
                    )


