# app/presentation/handlers/chart_callback_commands.py
"""
Callback commands для работы с графиками.
"""

from abc import ABC
from telegram import Update
from telegram.ext import ContextTypes
from telegram.error import BadRequest
import logging

logger = logging.getLogger("alt_forecast.handlers.chart_callbacks")


def _norm_tf(tf: str) -> str:
    """Нормализовать таймфрейм."""
    tf = (tf or "").lower()
    if tf in ("1d", "24h", "d1", "1day", "day"):
        return "1d"
    return tf


class ChartTfSelectCommand:
    """Команда для выбора таймфрейма в меню графиков."""
    
    async def execute(self, update: Update, context: ContextTypes.DEFAULT_TYPE, bot) -> None:
        from ...infrastructure.ui_keyboards import kb_chart_symbols
        q = update.callback_query
        await q.answer()
        ud = context.user_data
        
        # Извлекаем ТФ из callback data: ui:chart:tf:15m
        data = q.data
        tf = _norm_tf(data.split(":")[-1])
        ud["tf"] = tf
        ud["chart_tf"] = tf  # Сохраняем для использования в графиках
        
        # Показываем меню выбора символа
        try:
            await q.edit_message_reply_markup(kb_chart_symbols(tf))
        except BadRequest as e:
            if "not modified" not in str(e).lower():
                # Если не можем редактировать, отправляем новое сообщение
                await q.message.reply_text(f"📈 Графики • {tf}", reply_markup=kb_chart_symbols(tf))


class ChartSummaryCommand:
    """Команда для отображения сводного графика (старый формат)."""
    
    async def execute(self, update: Update, context: ContextTypes.DEFAULT_TYPE, bot) -> None:
        q = update.callback_query
        await q.answer()
        ud = context.user_data
        
        # Извлекаем ТФ из callback data: ui:chart:summary:1h
        data = q.data
        tf = _norm_tf(data.split(":")[-1])
        ud["tf"] = tf
        
        # Вызываем старый обработчик графика
        await bot.on_chart(update, context)


class ChartSymbolCommand:
    """Команда для отображения графика конкретного символа."""
    
    def __init__(self, db):
        self.db = db
    
    async def execute(self, update: Update, context: ContextTypes.DEFAULT_TYPE, bot) -> None:
        q = update.callback_query
        await q.answer()
        ud = context.user_data
        
        # Извлекаем символ и ТФ из callback data: ui:chart:symbol:BTC:1h
        data = q.data
        parts = data.split(":")
        if len(parts) >= 5:
            symbol = parts[3].upper()
            tf = _norm_tf(parts[4])
        else:
            symbol = "BTC"
            tf = ud.get("tf", "1h")
        
        ud["tf"] = tf
        ud["chart_symbol"] = symbol
        
        # Получаем настройки графика: сначала из user_data, если нет - из БД
        chart_settings = ud.get("chart_settings")
        if chart_settings is None and self.db:
            # Загружаем настройки из БД
            user_id = update.effective_user.id
            chart_settings = self.db.get_chart_settings(user_id) or {}
            ud["chart_settings"] = chart_settings
        
        # Если все еще нет настроек, используем пустой словарь
        if chart_settings is None:
            chart_settings = {}
        
        # Создаем настройки из сохраненных параметров
        from ...domain.chart_settings import ChartSettings
        settings = ChartSettings.from_params(chart_settings)
        settings.timeframe = tf
        
        # Рендерим график
        try:
            from ...visual.chart_renderer import render_chart
            png = render_chart(self.db, symbol, settings, n_bars=500)
            
            # Отправляем график
            from telegram import InputFile
            from telegram.constants import ParseMode
            
            caption = f"<b>{symbol}</b> • {tf}"
            if settings.currency:
                caption += f" • {settings.currency.upper()}"
            
            await context.bot.send_photo(
                chat_id=update.effective_chat.id,
                photo=InputFile(png, filename=f"chart_{symbol}_{tf}.png"),
                caption=caption,
                parse_mode=ParseMode.HTML
            )
        except Exception as e:
            logger.exception("Error rendering chart for %s %s", symbol, tf)
            await q.message.reply_text(
                f"Не удалось построить график для {symbol} {tf}. Попробуйте позже."
            )


class ChartCustomCommand:
    """Команда для запроса ввода кастомного тикера."""
    
    async def execute(self, update: Update, context: ContextTypes.DEFAULT_TYPE, bot) -> None:
        q = update.callback_query
        await q.answer()
        ud = context.user_data
        user_id = update.effective_user.id
        
        # Извлекаем ТФ из callback data: ui:chart:custom:1h
        data = q.data
        tf = _norm_tf(data.split(":")[-1])
        ud["tf"] = tf
        ud["chart_tf"] = tf
        ud["waiting_for_chart_ticker"] = True  # Флаг ожидания ввода тикера
        
        # Загружаем настройки из БД, если их еще нет в user_data
        if "chart_settings" not in ud and hasattr(bot, 'db') and bot.db:
            chart_settings = bot.db.get_chart_settings(user_id)
            if chart_settings:
                ud["chart_settings"] = chart_settings
        
        # Отправляем сообщение с запросом тикера
        await q.message.reply_text(
            f"Введите тикер для графика ({tf}):\n\n"
            "Например: BTC, ETH, SOL, DOGE и т.д.",
            reply_markup=None  # Убираем клавиатуру для ввода текста
        )


class ChartSettingsCommand:
    """Команда для открытия меню настроек графика."""
    
    async def execute(self, update: Update, context: ContextTypes.DEFAULT_TYPE, bot) -> None:
        from ...infrastructure.ui_keyboards import kb_chart_settings
        q = update.callback_query
        await q.answer()
        ud = context.user_data
        
        # Показываем меню настроек
        try:
            await q.edit_message_reply_markup(kb_chart_settings(ud.get("chart_settings", {})))
        except BadRequest as e:
            if "not modified" not in str(e).lower():
                await q.message.reply_text("⚙️ Настройки графика", reply_markup=kb_chart_settings(ud.get("chart_settings", {})))


class ChartSettingsBackCommand:
    """Команда для возврата из настроек в меню символов."""
    
    async def execute(self, update: Update, context: ContextTypes.DEFAULT_TYPE, bot) -> None:
        from ...infrastructure.ui_keyboards import kb_chart_symbols
        q = update.callback_query
        await q.answer()
        ud = context.user_data
        
        # Возвращаемся к меню символов с сохраненным ТФ
        tf = ud.get("chart_tf", ud.get("tf", "1h"))
        try:
            await q.edit_message_reply_markup(kb_chart_symbols(tf))
        except BadRequest as e:
            if "not modified" not in str(e).lower():
                await q.message.reply_text(f"📈 Графики • {tf}", reply_markup=kb_chart_symbols(tf))

