# app/presentation/handlers/callback_commands.py
"""
Callback commands for handling different types of UI interactions.
Uses Command pattern for clean separation of concerns.
"""

from abc import ABC, abstractmethod
from typing import Optional
from telegram import Update
from telegram.ext import ContextTypes
import logging

logger = logging.getLogger("alt_forecast.handlers.callback_commands")


def _norm_tf(tf: str) -> str:
    """Нормализовать таймфрейм."""
    tf = (tf or "").lower()
    # Нормализуем различные варианты суточного таймфрейма
    if tf in ("1d", "24h", "d1", "1day", "day"):
        return "1d"
    # Оставляем остальные как есть (1h, 4h, 15m)
    return tf


class CallbackCommand(ABC):
    """Базовый класс для команд callback'ов."""
    
    @abstractmethod
    async def execute(self, update: Update, context: ContextTypes.DEFAULT_TYPE, bot) -> None:
        """Выполнить команду."""
        pass


class NavigationCommand(CallbackCommand):
    """Команда для навигации по меню."""
    
    def __init__(self, state: str):
        self.state = state
    
    async def execute(self, update: Update, context: ContextTypes.DEFAULT_TYPE, bot) -> None:
        from ...infrastructure.ui_keyboards import build_kb, DEFAULT_TF
        from telegram.error import BadRequest
        q = update.callback_query
        await q.answer()
        ud = context.user_data
        ud["ui_prev"] = self.state
        
        # Проверяем, является ли сообщение фото или медиа
        is_media = q.message and (q.message.photo or q.message.video or q.message.document)
        
        # Если сообщение - медиа, всегда отправляем новое текстовое сообщение
        if is_media:
            menu_text = {
                "bubbles": "🫧 Пузырьки",
                "main": "Главное меню",
                "more": "➡️ Ещё",
                "help": "ℹ️ Справка",
                "report": "🧾 Отчёт",
                "charts": "📈 Чарты",
                "album": "🖼 Альбом",
                "top": "🏆 Топ",
                "options": "🧩 Опционы",
                "vol": "📉 Волатильность",
                "levels": "📐 Уровни",
                "corr": "🔗 Корреляция",
                "beta": "β Бета",
                "funding": "💵 Фандинг",
                "basis": "⚖️ Базис",
                "bt_rsi": "🧠 BT RSI",
                "breadth": "🌡 Ширина рынка",
                "whale_orders": "🐋 Ордера китов",
                "whale_activity": "🐋 Активность китов",
                "heatmap": "🌡 Тепловая карта",
                "md": "🏥 Market Doctor",
            }.get(self.state, f"Меню: {self.state}")
            await q.message.reply_text(menu_text, reply_markup=build_kb(self.state, ud.get("tf", DEFAULT_TF), user_data=ud))
            return
        
        # Для текстовых сообщений пытаемся редактировать клавиатуру
        try:
            await q.edit_message_reply_markup(build_kb(self.state, ud.get("tf", DEFAULT_TF), user_data=ud))
        except BadRequest as e:
            # Игнорируем ошибку "Message is not modified"
            if "not modified" in str(e).lower():
                pass  # Клавиатура уже такая же, ничего не делаем
            else:
                # Если не можем редактировать (например, сообщение - медиа), отправляем новое сообщение
                await q.message.reply_text(menu_text, reply_markup=build_kb(self.state, ud.get("tf", DEFAULT_TF)))


class BackCommand(CallbackCommand):
    """Команда для возврата в предыдущее меню."""
    
    async def execute(self, update: Update, context: ContextTypes.DEFAULT_TYPE, bot) -> None:
        from ...infrastructure.ui_keyboards import build_kb, DEFAULT_TF
        from telegram.error import BadRequest
        q = update.callback_query
        await q.answer()
        ud = context.user_data
        prev = ud.get("ui_prev", "main")
        ud["ui_prev"] = prev
        
        # Проверяем, является ли сообщение медиа
        is_media = q.message and (q.message.photo or q.message.video or q.message.document)
        if is_media:
            await q.message.reply_text("Назад", reply_markup=build_kb(prev, ud.get("tf", DEFAULT_TF)))
            return
        
        try:
            await q.edit_message_reply_markup(build_kb(prev, ud.get("tf", DEFAULT_TF)))
        except BadRequest as e:
            # Игнорируем ошибку "Message is not modified"
            if "not modified" in str(e).lower():
                pass  # Клавиатура уже такая же, ничего не делаем
            else:
                # Если не можем редактировать, отправляем новое сообщение
                await q.message.reply_text("Назад", reply_markup=build_kb(prev, ud.get("tf", DEFAULT_TF)))


class TimeframeSelectCommand(CallbackCommand):
    """Команда для выбора таймфрейма."""
    
    async def execute(self, update: Update, context: ContextTypes.DEFAULT_TYPE, bot) -> None:
        from ...infrastructure.ui_keyboards import build_kb, DEFAULT_TF
        from telegram.error import BadRequest
        q = update.callback_query
        await q.answer()
        ud = context.user_data
        prev = ud.get("ui_prev", "main")
        ud["ui_prev"] = prev
        
        # Проверяем, является ли сообщение медиа
        is_media = q.message and (q.message.photo or q.message.video or q.message.document)
        if is_media:
            await q.message.reply_text("Выберите таймфрейм:", reply_markup=build_kb("tf", ud.get("tf", DEFAULT_TF)))
            return
        
        try:
            await q.edit_message_reply_markup(build_kb("tf", ud.get("tf", DEFAULT_TF)))
        except BadRequest as e:
            # Игнорируем ошибку "Message is not modified"
            if "not modified" in str(e).lower():
                pass  # Клавиатура уже такая же, ничего не делаем
            else:
                # Если не можем редактировать, отправляем новое сообщение
                await q.message.reply_text("Выберите таймфрейм:", reply_markup=build_kb("tf", ud.get("tf", DEFAULT_TF)))


class TimeframeSetCommand(CallbackCommand):
    """Команда для установки таймфрейма."""
    
    async def execute(self, update: Update, context: ContextTypes.DEFAULT_TYPE, bot) -> None:
        from ...infrastructure.ui_keyboards import build_kb, DEFAULT_TF
        q = update.callback_query
        await q.answer()
        ud = context.user_data
        
        # Извлекаем TF из callback data
        data = q.data
        if ":" in data:
            parts = data.split(":", 2)
            if len(parts) >= 3:
                tf = _norm_tf(parts[2])
                ud["tf"] = tf
        
        prev = ud.get("ui_prev", "main")
        ud["ui_prev"] = prev
        
        # Проверяем, является ли сообщение медиа
        is_media = q.message and (q.message.photo or q.message.video or q.message.document)
        if is_media:
            await q.message.reply_text("Таймфрейм установлен", reply_markup=build_kb(prev, ud.get("tf", DEFAULT_TF)))
            return
        
        from telegram.error import BadRequest
        try:
            await q.edit_message_reply_markup(build_kb(prev, ud.get("tf", DEFAULT_TF)))
        except BadRequest as e:
            # Игнорируем ошибку "Message is not modified"
            if "not modified" in str(e).lower():
                pass  # Клавиатура уже такая же, ничего не делаем
            else:
                # Если не можем редактировать, отправляем новое сообщение
                await q.message.reply_text("Таймфрейм установлен", reply_markup=build_kb(prev, ud.get("tf", DEFAULT_TF)))


class BotCommandExecutionCommand(CallbackCommand):
    """Команда для выполнения команды бота через CommandIntegrator."""
    
    def __init__(self, command_name: str, integrator=None):
        self.command_name = command_name
        self.integrator = integrator
    
    async def execute(self, update: Update, context: ContextTypes.DEFAULT_TYPE, bot) -> None:
        q = update.callback_query
        await q.answer()
        
        # Используем новую архитектуру если доступна
        if self.integrator:
            try:
                handled = await self.integrator.handle_command(self.command_name, update, context)
                if handled:
                    return
            except Exception:
                logger.exception("Error executing command %s via integrator", self.command_name)
        
        # Fallback на старый метод
        method = getattr(bot, f"on_{self.command_name}", None)
        if not method:
            method = getattr(bot, f"cmd_{self.command_name}", None)
        
        if method:
            await method(update, context)
        else:
            logger.warning("Command method not found: %s", self.command_name)
            await q.answer("Команда временно недоступна", show_alert=False)


class TimeframeCommandExecutionCommand(CallbackCommand):
    """Команда для выполнения команды с таймфреймом."""
    
    def __init__(self, command_name: str, integrator=None):
        self.command_name = command_name
        self.integrator = integrator
    
    async def execute(self, update: Update, context: ContextTypes.DEFAULT_TYPE, bot) -> None:
        from ...infrastructure.ui_keyboards import DEFAULT_TF
        q = update.callback_query
        if q:
            await q.answer()
        ud = context.user_data
        
        # Устанавливаем TF из callback data
        if q:
            data = q.data
            if ":" in data:
                parts = data.split(":", 2)
                if len(parts) >= 3:
                    ud["tf"] = _norm_tf(parts[2])
        
        # Используем новую архитектуру если доступна
        if self.integrator:
            try:
                handled = await self.integrator.handle_command(self.command_name, update, context)
                if handled:
                    return
            except Exception:
                logger.exception("Error executing command %s via integrator", self.command_name)
        
        # Fallback на старый метод
        method = getattr(bot, f"on_{self.command_name}", None)
        if not method:
            method = getattr(bot, f"cmd_{self.command_name}", None)
        
        if method:
            await method(update, context)
        else:
            logger.warning("Command method not found: %s", self.command_name)
            if q:
                await q.answer("Команда временно недоступна", show_alert=False)


class SymbolCommandExecutionCommand(CallbackCommand):
    """Команда для выполнения команды с символом."""
    
    def __init__(self, command_name: str, integrator=None):
        self.command_name = command_name
        self.integrator = integrator
    
    async def execute(self, update: Update, context: ContextTypes.DEFAULT_TYPE, bot) -> None:
        q = update.callback_query
        if q:
            await q.answer()
        ud = context.user_data
        
        # Устанавливаем символ из callback data
        if q:
            data = q.data
            if ":" in data:
                parts = data.split(":", 2)
                if len(parts) >= 3:
                    ud["symbol"] = parts[2]
        
        # Используем новую архитектуру если доступна
        if self.integrator:
            try:
                handled = await self.integrator.handle_command(self.command_name, update, context)
                if handled:
                    return
            except Exception:
                logger.exception("Error executing command %s via integrator", self.command_name)
        
        # Fallback на старый метод
        method = getattr(bot, f"on_{self.command_name}", None)
        if not method:
            method = getattr(bot, f"cmd_{self.command_name}", None)
        
        if method:
            await method(update, context)
        else:
            logger.warning("Command method not found: %s", self.command_name)
            if q:
                await q.answer("Команда временно недоступна", show_alert=False)


class BubblesCommand(CallbackCommand):
    """Команда для работы с пузырьками."""
    
    def __init__(self, integrator=None):
        self.integrator = integrator
    
    async def execute(self, update: Update, context: ContextTypes.DEFAULT_TYPE, bot) -> None:
        from ...infrastructure.ui_keyboards import DEFAULT_TF
        q = update.callback_query
        await q.answer()
        ud = context.user_data
        
        data = q.data
        parts = data.split(":", 2)
        
        if len(parts) == 3:
            action = parts[2]
            if action == "settings":
                # Открываем настройки пузырьков
                # Используем безопасный метод, который работает с фото
                if hasattr(bot, '_safe_edit_text'):
                    await bot.on_bubbles_settings(update, context)
                else:
                    # Fallback: если сообщение - фото, отправляем новое
                    if q.message and q.message.photo:
                        await q.message.reply_text("Настройки пузырей:", reply_markup=None)
                        await bot.on_bubbles_settings(update, context)
                    else:
                        await bot.on_bubbles_settings(update, context)
            else:
                # ui:bubbles:15m, ui:bubbles:1h, ui:bubbles:1d
                # Выполняем команду bubbles - не пытаемся редактировать клавиатуру
                tf_bubbles = _norm_tf(action)
                ud["bubbles_tf"] = tf_bubbles
                ud["tf_bubbles"] = tf_bubbles  # для совместимости
                
                # Сохраняем в настройки пользователя
                user_id = update.effective_user.id if update.effective_user else None
                if user_id:
                    bot.db.set_user_settings(user_id, bubbles_tf=tf_bubbles)
                
                # Выполняем команду bubbles - она сама отправит новое сообщение с графиком
                if self.integrator:
                    try:
                        handled = await self.integrator.handle_command("bubbles", update, context)
                        if handled:
                            return
                    except Exception:
                        logger.exception("Error executing bubbles via integrator")
                
                # Вызываем команду bubbles - она отправит новое сообщение с графиком
                await bot.on_bubbles(update, context, tf_bubbles)


class TopFlopCommand(CallbackCommand):
    """Команда для топ/флоп с таймфреймом."""
    
    def __init__(self, command_name: str, tf: str, integrator=None):
        self.command_name = command_name
        self.tf = tf
        self.integrator = integrator
    
    async def execute(self, update: Update, context: ContextTypes.DEFAULT_TYPE, bot) -> None:
        q = update.callback_query
        await q.answer()
        
        # Устанавливаем args для команды
        context.args = [self.tf]
        
        # Используем новую архитектуру если доступна
        command_map = {
            "top_24h": "top",
            "flop_24h": "flop",
            "top_1h": "top",
            "flop_1h": "flop",
        }
        cmd = command_map.get(self.command_name, self.command_name)
        
        if self.integrator:
            try:
                handled = await self.integrator.handle_command(cmd, update, context)
                if handled:
                    return
            except Exception:
                logger.exception("Error executing %s via integrator", cmd)
        
        # Fallback на старый метод
        method = getattr(bot, f"on_{cmd}", None)
        if method:
            await method(update, context)


class WhaleActivitySymbolCommand(CallbackCommand):
    """Команда для обработки выбора символа активности китов."""
    
    async def execute(self, update: Update, context: ContextTypes.DEFAULT_TYPE, bot) -> None:
        from ...infrastructure.ui_keyboards import kb_whale_activity_tf_menu
        q = update.callback_query
        if q:
            await q.answer()
            # Извлекаем символ из callback data (ui:whale_activity_symbol:BTC)
            parts = q.data.split(":")
            symbol = parts[2].upper() if len(parts) > 2 else "BTC"
            
            # Показываем меню выбора таймфрейма
            try:
                await q.edit_message_reply_markup(reply_markup=kb_whale_activity_tf_menu(symbol))
            except Exception:
                # Если не удалось отредактировать, отправляем новое сообщение
                await q.message.reply_text(
                    f"Выберите таймфрейм для {symbol}:",
                    reply_markup=kb_whale_activity_tf_menu(symbol)
                )


class DefaultCommand(CallbackCommand):
    """Обработчик по умолчанию для неизвестных callback'ов."""
    
    async def execute(self, update: Update, context: ContextTypes.DEFAULT_TYPE, bot) -> None:
        q = update.callback_query
        await q.answer("Команда не распознана", show_alert=False)
        logger.warning("Unhandled callback data: %s", q.data)

