# app/presentation/handlers/market_doctor_callback_commands.py
"""
Callback commands для Market Doctor меню.
"""

from telegram import Update
from telegram.ext import ContextTypes
from .callback_commands import CallbackCommand
from ...infrastructure.ui_keyboards import build_kb, kb_md_symbol_menu
import logging

logger = logging.getLogger("alt_forecast.handlers.md_callbacks")


class MarketDoctorTfSelectCommand(CallbackCommand):
    """Команда для выбора таймфрейма в Market Doctor."""
    
    async def execute(self, update: Update, context: ContextTypes.DEFAULT_TYPE, bot) -> None:
        q = update.callback_query
        await q.answer()
        
        # Извлекаем формат и таймфрейм из callback data: 
        # ui:md:tf:brief:1h, ui:md:tf:full:1h, ui:md:tf:1h (старый формат)
        parts = q.data.split(":")
        brief = False
        if len(parts) >= 5 and parts[3] in ["brief", "full"]:
            # Новый формат: ui:md:tf:brief:1h или ui:md:tf:full:1h
            format_type = parts[3]
            brief = format_type == "brief"
            tf = parts[4]
        elif len(parts) >= 4:
            # Старый формат: ui:md:tf:1h (для обратной совместимости)
            tf = parts[3]
            # Проверяем сохранённый формат
            ud = context.user_data
            brief = ud.get("md_brief", False)
        else:
            logger.error(f"Invalid callback data format: {q.data}")
            return
        
        # Сохраняем формат и таймфрейм
        ud = context.user_data
        ud["md_brief"] = brief
        ud["md_format"] = "brief" if brief else "full"
        
        # Обработка multi-TF анализа
        if tf == "multi":
            # Показываем меню выбора символов для multi-TF
            ud["md_tf"] = "multi"
            ud["ui_prev"] = "md_symbol:multi"
            
            # Проверяем, является ли сообщение медиа
            is_media = q.message and (q.message.photo or q.message.video or q.message.document)
            
            if is_media:
                await q.message.reply_text(
                    "Выберите монету для multi-TF анализа:",
                    reply_markup=kb_md_symbol_menu("multi", brief=brief)
                )
            else:
                try:
                    await q.edit_message_reply_markup(
                        reply_markup=kb_md_symbol_menu("multi", brief=brief)
                    )
                except Exception as e:
                    logger.exception("Error editing message for MD multi-TF symbol menu: %s", e)
                    await q.message.reply_text(
                        "Выберите монету для multi-TF анализа:",
                        reply_markup=kb_md_symbol_menu("multi", brief=brief)
                    )
            return
        
        # Нормализуем таймфрейм (1w -> 1d для недели, так как в БД может не быть недельного)
        if tf == "1w":
            tf = "1d"  # Используем дневной как недельный
        # Сохраняем оригинальный таймфрейм для отображения
        ud["md_tf_original"] = parts[-1] if len(parts) >= 4 else tf  # Сохраняем "1w" если был выбран
        ud["md_tf"] = tf
        ud["ui_prev"] = f"md_symbol:{tf}"
        
        # Проверяем, является ли сообщение медиа
        is_media = q.message and (q.message.photo or q.message.video or q.message.document)
        
        if is_media:
            await q.message.reply_text(
                "Выберите монету:",
                reply_markup=kb_md_symbol_menu(tf, brief=brief)
            )
        else:
            try:
                await q.edit_message_reply_markup(
                    reply_markup=kb_md_symbol_menu(tf, brief=brief)
                )
            except Exception as e:
                logger.exception("Error editing message for MD symbol menu: %s", e)
                await q.message.reply_text(
                    "Выберите монету:",
                    reply_markup=kb_md_symbol_menu(tf, brief=brief)
                )


class MarketDoctorSymbolCommand(CallbackCommand):
    """Команда для выполнения Market Doctor с выбранным символом и таймфреймом."""
    
    def __init__(self, integrator=None):
        self.integrator = integrator
    
    async def execute(self, update: Update, context: ContextTypes.DEFAULT_TYPE, bot) -> None:
        q = update.callback_query
        await q.answer()
        
        # Извлекаем символ, формат и таймфрейм: 
        # ui:md:symbol:BTC:brief:1h, ui:md:symbol:BTC:full:1h, ui:md:symbol:BTC:1h (старый формат)
        parts = q.data.split(":")
        brief = False
        if len(parts) >= 6 and parts[4] in ["brief", "full"]:
            # Новый формат: ui:md:symbol:BTC:brief:1h
            symbol = parts[3]
            format_type = parts[4]
            brief = format_type == "brief"
            tf = parts[5]
        elif len(parts) >= 5:
            # Старый формат: ui:md:symbol:BTC:1h (для обратной совместимости)
            symbol = parts[3]
            tf = parts[4]
            # Проверяем сохранённый формат
            ud = context.user_data
            brief = ud.get("md_brief", False)
        else:
            logger.error(f"Invalid callback data format: {q.data}")
            await q.message.reply_text("❌ Ошибка: неверный формат данных.")
            return
        
        logger.debug(f"MarketDoctorSymbolCommand: symbol={symbol}, tf={tf}, brief={brief}")
        
        # Сохраняем формат в user_data для передачи в генератор отчёта
        ud = context.user_data
        ud["md_brief"] = brief
        
        # Устанавливаем аргументы команды
        # Для multi-TF используем "multi" как таймфрейм
        context.args = [symbol, tf]
        
        # Выполняем команду через integrator - получаем handler напрямую
        if self.integrator:
            try:
                handler = self.integrator.get_handler("market_doctor")
                if handler:
                    logger.debug(f"Calling handler.handle_market_doctor with args: {context.args}")
                    await handler.handle_market_doctor(update, context)
                    return
                else:
                    logger.warning("Handler 'market_doctor' not found via get_handler")
            except Exception as e:
                logger.exception(f"Error executing MD command via integrator: {e}")
        
        # Fallback: пробуем через handle_command
        if self.integrator:
            try:
                logger.debug("Trying handle_command('md')")
                handled = await self.integrator.handle_command("md", update, context)
                if handled:
                    logger.debug("Command handled via handle_command")
                    return
            except Exception as e:
                logger.exception(f"Error executing MD command via handle_command: {e}")
        
        # Последний fallback на прямой вызов через bot
        if hasattr(bot, "on_market_doctor"):
            try:
                logger.debug("Trying bot.on_market_doctor")
                await bot.on_market_doctor(update, context)
                return
            except Exception as e:
                logger.exception(f"Error executing MD command via bot.on_market_doctor: {e}")
        
        # Если ничего не сработало
        logger.error(f"All fallbacks failed for symbol={symbol}, tf={tf}")
        await q.message.reply_text(
            f"❌ Ошибка при выполнении анализа для {symbol} {tf}.\n"
            f"Попробуйте использовать команду: /md {symbol} {tf}"
        )


class MarketDoctorCustomSymbolCommand(CallbackCommand):
    """Команда для запроса ввода символа от пользователя."""
    
    async def execute(self, update: Update, context: ContextTypes.DEFAULT_TYPE, bot) -> None:
        q = update.callback_query
        await q.answer()
        
        # Извлекаем формат и таймфрейм: 
        # ui:md:custom:brief:1h, ui:md:custom:full:1h, ui:md:custom:1h (старый формат)
        parts = q.data.split(":")
        brief = False
        if len(parts) >= 5 and parts[3] in ["brief", "full"]:
            # Новый формат: ui:md:custom:brief:1h
            format_type = parts[3]
            brief = format_type == "brief"
            tf = parts[4]
        elif len(parts) >= 4:
            # Старый формат: ui:md:custom:1h (для обратной совместимости)
            tf = parts[3]
            # Проверяем сохранённый формат
            ud = context.user_data
            brief = ud.get("md_brief", False)
        else:
            logger.error(f"Invalid callback data format: {q.data}")
            return
        
        # Сохраняем состояние ожидания ввода символа
        ud = context.user_data
        ud["waiting_for_md_symbol"] = True
        ud["md_tf"] = tf
        ud["md_brief"] = brief
        
        # Формируем текст запроса в зависимости от таймфрейма
        if tf == "multi":
            text = (
                "Введите символ монеты для multi-TF анализа (1h + 4h + 1d):\n"
                "Например: BTC, ETH, SOL, или полный тикер типа ETHUSDT"
            )
        else:
            text = (
                f"Введите символ монеты для анализа на таймфрейме {tf}:\n"
                "Например: BTC, ETH, SOL, или полный тикер типа ETHUSDT"
            )
        
        # Отправляем сообщение с запросом символа
        await q.message.reply_text(
            text,
            reply_markup=build_kb("main")
        )

