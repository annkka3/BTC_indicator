# app/presentation/handlers/chart_settings_handler.py
"""
Обработчик настроек графика.
"""

from telegram import Update
from telegram.ext import ContextTypes
from telegram.error import BadRequest
from ...infrastructure.ui_keyboards import kb_chart_symbols, kb_chart_settings
import logging

logger = logging.getLogger("alt_forecast.handlers.chart_settings")


def _save_chart_settings_to_db(chart_settings: dict, user_id: int, bot, ud: dict) -> None:
    """Вспомогательная функция для сохранения настроек в БД через to_dict."""
    if bot.db:
        try:
            from ...domain.chart_settings import ChartSettings
            settings_obj = ChartSettings.from_params(chart_settings)
            settings_dict = settings_obj.to_dict()
            bot.db.save_chart_settings(user_id, settings_dict)
            # Обновляем user_data с полными настройками
            ud["chart_settings"] = settings_dict
        except Exception:
            logger.exception("Error saving chart settings to DB")


async def handle_chart_settings_callback(update: Update, context: ContextTypes.DEFAULT_TYPE, bot) -> None:
    """Обработать callback для настроек графика."""
    q = update.callback_query
    if not q:
        return
    
    await q.answer()
    ud = context.user_data
    user_id = update.effective_user.id
    
    # Получаем текущие настройки: сначала из user_data, если нет - из БД
    chart_settings = ud.get("chart_settings")
    if chart_settings is None and bot.db:
        # Загружаем настройки из БД
        chart_settings = bot.db.get_chart_settings(user_id) or {}
        ud["chart_settings"] = chart_settings
    
    # Если все еще нет настроек, используем пустой словарь
    if chart_settings is None:
        chart_settings = {}
    
    # Извлекаем действие из callback data: ui:chart:settings:mode, ui:chart:settings:back и т.д.
    data = q.data
    parts = data.split(":")
    
    if len(parts) < 4:
        return
    
    action = parts[3]
    
    # Обработка действий
    if action == "preview":
        # Рендерим предпросмотр графика
        try:
            # Получаем ТФ и символ
            tf = ud.get("chart_tf", ud.get("tf", "1h"))
            symbol = ud.get("chart_symbol", "BTC")  # По умолчанию BTC
            
            # Создаем настройки из сохраненных параметров
            from ...domain.chart_settings import ChartSettings
            settings = ChartSettings.from_params(chart_settings)
            settings.timeframe = tf
            
            # Рендерим график
            from ...visual.chart_renderer import render_chart
            from telegram import InputFile
            from telegram.constants import ParseMode
            
            png = render_chart(bot.db, symbol, settings, n_bars=500)
            
            # Формируем подпись
            caption = f"<b>Preview: {symbol}</b> • {tf}"
            if settings.currency:
                caption += f" • {settings.currency.upper()}"
            caption += f"\n<i>Mode: {settings.mode.value}</i>"
            
            # Отправляем график
            await context.bot.send_photo(
                chat_id=update.effective_chat.id,
                photo=InputFile(png, filename=f"preview_{symbol}_{tf}.png"),
                caption=caption,
                parse_mode=ParseMode.HTML
            )
        except Exception as e:
            logger.exception("Error rendering preview: %s", e)
            await q.message.reply_text(
                "❌ Не удалось построить предпросмотр графика. Проверьте настройки."
            )
        return
    
    if action == "back":
        # Возврат к меню символов
        tf = ud.get("chart_tf", ud.get("tf", "1h"))
        try:
            await q.edit_message_reply_markup(kb_chart_symbols(tf))
        except BadRequest:
            await q.message.reply_text(f"📈 Графики • {tf}", reply_markup=kb_chart_symbols(tf))
        return
    
    elif action == "reset":
        # Сброс настроек
        chart_settings = {}
        ud["chart_settings"] = chart_settings
        # Сохраняем пустые настройки в БД через to_dict для консистентности
        _save_chart_settings_to_db(chart_settings, user_id, bot, ud)
        try:
            await q.edit_message_reply_markup(kb_chart_settings(ud.get("chart_settings", chart_settings)))
        except BadRequest:
            await q.message.reply_text("⚙️ Настройки графика (сброшены)", reply_markup=kb_chart_settings(ud.get("chart_settings", chart_settings)))
        return
    
    elif action == "mode":
        # Переключение режима отображения
        current_mode = chart_settings.get("mode", "candle")
        modes = ["line", "candle", "candle+heikin"]
        try:
            current_idx = modes.index(current_mode)
            next_idx = (current_idx + 1) % len(modes)
            chart_settings["mode"] = modes[next_idx]
        except ValueError:
            chart_settings["mode"] = "candle"
        ud["chart_settings"] = chart_settings
        _save_chart_settings_to_db(chart_settings, user_id, bot, ud)
        try:
            await q.edit_message_reply_markup(kb_chart_settings(ud.get("chart_settings", chart_settings)))
        except BadRequest:
            await q.message.reply_text("⚙️ Настройки графика", reply_markup=kb_chart_settings(ud.get("chart_settings", chart_settings)))
        return
    
    elif action == "legend":
        # Переключение позиции легенды
        current_legend = chart_settings.get("legend", "top")
        legends = ["top", "bottom", "off"]
        try:
            current_idx = legends.index(current_legend)
            next_idx = (current_idx + 1) % len(legends)
            chart_settings["legend"] = legends[next_idx]
        except ValueError:
            chart_settings["legend"] = "top"
        ud["chart_settings"] = chart_settings
        _save_chart_settings_to_db(chart_settings, user_id, bot, ud)
        try:
            await q.edit_message_reply_markup(kb_chart_settings(ud.get("chart_settings", chart_settings)))
        except BadRequest:
            await q.message.reply_text("⚙️ Настройки графика", reply_markup=kb_chart_settings(ud.get("chart_settings", chart_settings)))
        return
    
    elif action == "sma":
        # Переключение SMA
        sma_periods = chart_settings.get("sma_periods", [])
        if sma_periods:
            # Выключаем SMA - сохраняем пустой список
            chart_settings["sma_periods"] = []
        else:
            # Включаем SMA - используем дефолтные значения
            chart_settings["sma_periods"] = [20, 50]
        ud["chart_settings"] = chart_settings
        # Сохраняем настройки в БД через to_dict для консистентности
        _save_chart_settings_to_db(chart_settings, user_id, bot, ud)
        try:
            await q.edit_message_reply_markup(kb_chart_settings(ud.get("chart_settings", chart_settings)))
        except BadRequest:
            await q.message.reply_text("⚙️ Настройки графика", reply_markup=kb_chart_settings(ud.get("chart_settings", chart_settings)))
        return
    
    elif action == "ema":
        # Переключение EMA
        ema_periods = chart_settings.get("ema_periods", [])
        if ema_periods:
            chart_settings["ema_periods"] = []
        else:
            chart_settings["ema_periods"] = [12, 50, 200]
        ud["chart_settings"] = chart_settings
        _save_chart_settings_to_db(chart_settings, user_id, bot, ud)
        try:
            await q.edit_message_reply_markup(kb_chart_settings(ud.get("chart_settings", chart_settings)))
        except BadRequest:
            await q.message.reply_text("⚙️ Настройки графика", reply_markup=kb_chart_settings(ud.get("chart_settings", chart_settings)))
        return
    
    elif action == "bb":
        # Переключение Bollinger Bands
        if chart_settings.get("bb_period") is not None:
            chart_settings["bb_period"] = None
            chart_settings["bb_std"] = 2.0  # Сохраняем стандартное значение даже при отключении
        else:
            chart_settings["bb_period"] = 20
            chart_settings["bb_std"] = 2.0
        ud["chart_settings"] = chart_settings
        _save_chart_settings_to_db(chart_settings, user_id, bot, ud)
        try:
            await q.edit_message_reply_markup(kb_chart_settings(ud.get("chart_settings", chart_settings)))
        except BadRequest:
            await q.message.reply_text("⚙️ Настройки графика", reply_markup=kb_chart_settings(ud.get("chart_settings", chart_settings)))
        return
    
    elif action == "ribbon":
        # Переключение Ribbon
        chart_settings["ribbon"] = not chart_settings.get("ribbon", False)
        ud["chart_settings"] = chart_settings
        _save_chart_settings_to_db(chart_settings, user_id, bot, ud)
        try:
            await q.edit_message_reply_markup(kb_chart_settings(ud.get("chart_settings", chart_settings)))
        except BadRequest:
            await q.message.reply_text("⚙️ Настройки графика", reply_markup=kb_chart_settings(ud.get("chart_settings", chart_settings)))
        return
    
    elif action == "separator":
        # Переключение Separator
        if chart_settings.get("separator") is not None:
            chart_settings["separator"] = None
        else:
            chart_settings["separator"] = "day"
        ud["chart_settings"] = chart_settings
        _save_chart_settings_to_db(chart_settings, user_id, bot, ud)
        try:
            await q.edit_message_reply_markup(kb_chart_settings(ud.get("chart_settings", chart_settings)))
        except BadRequest:
            await q.message.reply_text("⚙️ Настройки графика", reply_markup=kb_chart_settings(ud.get("chart_settings", chart_settings)))
        return
    
    elif action == "pivots":
        # Переключение Pivots
        chart_settings["pivots"] = not chart_settings.get("pivots", False)
        ud["chart_settings"] = chart_settings
        _save_chart_settings_to_db(chart_settings, user_id, bot, ud)
        try:
            await q.edit_message_reply_markup(kb_chart_settings(ud.get("chart_settings", chart_settings)))
        except BadRequest:
            await q.message.reply_text("⚙️ Настройки графика", reply_markup=kb_chart_settings(ud.get("chart_settings", chart_settings)))
        return
    
    elif action == "lastline":
        # Переключение Lastline
        chart_settings["lastline"] = not chart_settings.get("lastline", False)
        ud["chart_settings"] = chart_settings
        _save_chart_settings_to_db(chart_settings, user_id, bot, ud)
        try:
            await q.edit_message_reply_markup(kb_chart_settings(ud.get("chart_settings", chart_settings)))
        except BadRequest:
            await q.message.reply_text("⚙️ Настройки графика", reply_markup=kb_chart_settings(ud.get("chart_settings", chart_settings)))
        return
    
    elif action == "ichimoku":
        # Переключение Ichimoku
        chart_settings["ichimoku_enabled"] = not chart_settings.get("ichimoku_enabled", False)
        if chart_settings["ichimoku_enabled"]:
            # Инициализируем параметры по умолчанию
            chart_settings["ichimoku_tenkan"] = 9
            chart_settings["ichimoku_kijun"] = 26
            chart_settings["ichimoku_senkou_b"] = 52
            chart_settings["ichimoku_chikou"] = 26
        ud["chart_settings"] = chart_settings
        _save_chart_settings_to_db(chart_settings, user_id, bot, ud)
        try:
            await q.edit_message_reply_markup(kb_chart_settings(ud.get("chart_settings", chart_settings)))
        except BadRequest:
            await q.message.reply_text("⚙️ Настройки графика", reply_markup=kb_chart_settings(ud.get("chart_settings", chart_settings)))
        return
    
    elif action == "last_badge":
        # Переключение Last Badge
        chart_settings["last_badge"] = not chart_settings.get("last_badge", False)
        ud["chart_settings"] = chart_settings
        _save_chart_settings_to_db(chart_settings, user_id, bot, ud)
        try:
            await q.edit_message_reply_markup(kb_chart_settings(ud.get("chart_settings", chart_settings)))
        except BadRequest:
            await q.message.reply_text("⚙️ Настройки графика", reply_markup=kb_chart_settings(ud.get("chart_settings", chart_settings)))
        return
    
    elif action == "last_ind":
        # Переключение Last Ind (подписи последних значений индикаторов)
        chart_settings["last_ind"] = not chart_settings.get("last_ind", True)  # По умолчанию True
        ud["chart_settings"] = chart_settings
        _save_chart_settings_to_db(chart_settings, user_id, bot, ud)
        try:
            await q.edit_message_reply_markup(kb_chart_settings(ud.get("chart_settings", chart_settings)))
        except BadRequest:
            await q.message.reply_text("⚙️ Настройки графика", reply_markup=kb_chart_settings(ud.get("chart_settings", chart_settings)))
        return
    
    elif action == "vol":
        # Переключение Volume
        chart_settings["show_volume"] = not chart_settings.get("show_volume", False)
        ud["chart_settings"] = chart_settings
        _save_chart_settings_to_db(chart_settings, user_id, bot, ud)
        try:
            await q.edit_message_reply_markup(kb_chart_settings(ud.get("chart_settings", chart_settings)))
        except BadRequest:
            await q.message.reply_text("⚙️ Настройки графика", reply_markup=kb_chart_settings(ud.get("chart_settings", chart_settings)))
        return
    
    elif action == "rsi":
        # Переключение RSI
        chart_settings["show_rsi"] = not chart_settings.get("show_rsi", False)
        if chart_settings["show_rsi"]:
            chart_settings["rsi_period"] = 14
        ud["chart_settings"] = chart_settings
        _save_chart_settings_to_db(chart_settings, user_id, bot, ud)
        try:
            await q.edit_message_reply_markup(kb_chart_settings(ud.get("chart_settings", chart_settings)))
        except BadRequest:
            await q.message.reply_text("⚙️ Настройки графика", reply_markup=kb_chart_settings(ud.get("chart_settings", chart_settings)))
        return
    
    elif action == "macd":
        # Переключение MACD
        chart_settings["show_macd"] = not chart_settings.get("show_macd", False)
        if chart_settings["show_macd"]:
            chart_settings["macd_fast"] = 12
            chart_settings["macd_slow"] = 26
            chart_settings["macd_signal"] = 9
        ud["chart_settings"] = chart_settings
        _save_chart_settings_to_db(chart_settings, user_id, bot, ud)
        try:
            await q.edit_message_reply_markup(kb_chart_settings(ud.get("chart_settings", chart_settings)))
        except BadRequest:
            await q.message.reply_text("⚙️ Настройки графика", reply_markup=kb_chart_settings(ud.get("chart_settings", chart_settings)))
        return
    
    elif action == "atr":
        # Переключение ATR
        chart_settings["show_atr"] = not chart_settings.get("show_atr", False)
        if chart_settings["show_atr"]:
            chart_settings["atr_period"] = 14
        ud["chart_settings"] = chart_settings
        _save_chart_settings_to_db(chart_settings, user_id, bot, ud)
        try:
            await q.edit_message_reply_markup(kb_chart_settings(ud.get("chart_settings", chart_settings)))
        except BadRequest:
            await q.message.reply_text("⚙️ Настройки графика", reply_markup=kb_chart_settings(ud.get("chart_settings", chart_settings)))
        return
    
    elif action == "divergences":
        # Переключение отображения дивергенций
        chart_settings["show_divergences"] = not chart_settings.get("show_divergences", False)
        # Если включаем, инициализируем словарь индикаторов если его нет
        if chart_settings["show_divergences"] and "divergence_indicators" not in chart_settings:
            chart_settings["divergence_indicators"] = {
                "RSI": True,
                "MACD": True,
                "STOCH": False,
                "CCI": False,
                "MFI": False,
                "OBV": False,
                "VOLUME": False,
            }
        ud["chart_settings"] = chart_settings
        _save_chart_settings_to_db(chart_settings, user_id, bot, ud)
        try:
            await q.edit_message_reply_markup(kb_chart_settings(ud.get("chart_settings", chart_settings)))
        except BadRequest:
            await q.message.reply_text("⚙️ Настройки графика", reply_markup=kb_chart_settings(ud.get("chart_settings", chart_settings)))
        return
    
    elif action == "div_ind":
        # Переключение конкретного индикатора для дивергенций
        # Формат: ui:chart:settings:div_ind:RSI
        if len(parts) >= 5:
            ind_name = parts[4].upper()
            if "divergence_indicators" not in chart_settings:
                chart_settings["divergence_indicators"] = {
                    "RSI": True,
                    "MACD": True,
                    "STOCH": False,
                    "CCI": False,
                    "MFI": False,
                    "OBV": False,
                    "VOLUME": False,
                }
            current = chart_settings["divergence_indicators"].get(ind_name, False)
            chart_settings["divergence_indicators"][ind_name] = not current
            ud["chart_settings"] = chart_settings
            _save_chart_settings_to_db(chart_settings, user_id, bot, ud)
            try:
                await q.edit_message_reply_markup(kb_chart_settings(ud.get("chart_settings", chart_settings)))
            except BadRequest:
                await q.message.reply_text("⚙️ Настройки графика", reply_markup=kb_chart_settings(ud.get("chart_settings", chart_settings)))
        return

