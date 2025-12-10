from telegram import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton

DEFAULT_TF = "1h"  # подпись ТФ там, где она нужна

def _b(text: str, data: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text, callback_data=data)

# === Подменю с ТФ (payload "1d" как канон для суточного) ===

def kb_vol_menu() -> InlineKeyboardMarkup:
    rows = [
        [_b("15m", "ui:vol:15m"), _b("1h", "ui:vol:1h"),
         _b("4h", "ui:vol:4h"),   _b("1d", "ui:vol:1d")],
        [_b("‹ Назад", "ui:more")],
    ]
    return InlineKeyboardMarkup(rows)

def kb_corr_menu() -> InlineKeyboardMarkup:
    rows = [
        [_b("15m", "ui:corr:15m"), _b("1h", "ui:corr:1h"),
         _b("4h", "ui:corr:4h"),   _b("1d", "ui:corr:1d")],
        [_b("‹ Назад", "ui:more")],
    ]
    return InlineKeyboardMarkup(rows)

def kb_beta_menu() -> InlineKeyboardMarkup:
    rows = [
        [_b("15m", "ui:beta:15m"), _b("1h", "ui:beta:1h"),
         _b("4h", "ui:beta:4h"),   _b("1d", "ui:beta:1d")],
        [_b("‹ Назад", "ui:more")],
    ]
    return InlineKeyboardMarkup(rows)

def kb_funding_menu() -> InlineKeyboardMarkup:
    rows = [
        [_b("BTC", "ui:funding:BTC"), _b("ETH", "ui:funding:ETH"),
         _b("XRP", "ui:funding:XRP"), _b("SOL", "ui:funding:SOL")],
        [_b("‹ Назад", "ui:more")],
    ]
    return InlineKeyboardMarkup(rows)

def kb_basis_menu() -> InlineKeyboardMarkup:
    rows = [
        [_b("BTC", "ui:basis:BTC"), _b("ETH", "ui:basis:ETH"),
         _b("XRP", "ui:basis:XRP"), _b("SOL", "ui:basis:SOL")],
        [_b("‹ Назад", "ui:more")],
    ]
    return InlineKeyboardMarkup(rows)

def kb_scan_divs_menu() -> InlineKeyboardMarkup:
    rows = [
        [_b("15m", "ui:scan_divs:15m"), _b("1h", "ui:scan_divs:1h"),
         _b("4h", "ui:scan_divs:4h"),   _b("1d", "ui:scan_divs:1d")],
        [_b("‹ Назад", "ui:more")],
    ]
    return InlineKeyboardMarkup(rows)

def kb_levels_menu() -> InlineKeyboardMarkup:
    rows = [
        [_b("15m", "ui:levels:15m"), _b("1h", "ui:levels:1h"),
         _b("4h", "ui:levels:4h"),   _b("1d", "ui:levels:1d")],
        [_b("‹ Назад", "ui:more")],
    ]
    return InlineKeyboardMarkup(rows)

def kb_bt_rsi_menu() -> InlineKeyboardMarkup:
    rows = [
        [_b("15m", "ui:bt_rsi:15m"), _b("1h", "ui:bt_rsi:1h"),
         _b("4h", "ui:bt_rsi:4h"),   _b("1d", "ui:bt_rsi:1d")],
        [_b("‹ Назад", "ui:more")],
    ]
    return InlineKeyboardMarkup(rows)

def kb_breadth_menu() -> InlineKeyboardMarkup:
    rows = [
        [_b("15m", "ui:breadth:15m"), _b("1h", "ui:breadth:1h"),
         _b("4h", "ui:breadth:4h"),   _b("1d", "ui:breadth:1d")],
        [_b("‹ Назад", "ui:more")],
    ]
    return InlineKeyboardMarkup(rows)

def kb_whale_orders_menu() -> InlineKeyboardMarkup:
    """Меню выбора символа для карты крупных ордеров китов."""
    rows = [
        [_b("BTC", "ui:whale_orders:BTC"),
         _b("ETH", "ui:whale_orders:ETH")],
        [_b("‹ Назад", "ui:more")],
    ]
    return InlineKeyboardMarkup(rows)

def kb_whale_activity_menu() -> InlineKeyboardMarkup:
    """Меню выбора символа для активности китов."""
    rows = [
        [_b("BTC", "ui:whale_activity_symbol:BTC"),
         _b("ETH", "ui:whale_activity_symbol:ETH")],
        [_b("‹ Назад", "ui:more")],
    ]
    return InlineKeyboardMarkup(rows)

def kb_whale_activity_tf_menu(symbol: str) -> InlineKeyboardMarkup:
    """Меню выбора таймфрейма для активности китов по символу."""
    rows = [
        [_b("1 час", f"ui:whale_activity:{symbol}:1h"),
         _b("4 часа", f"ui:whale_activity:{symbol}:4h")],
        [_b("24 часа", f"ui:whale_activity:{symbol}:24h")],
        [_b("‹ Назад", "ui:whale_activity")],
    ]
    return InlineKeyboardMarkup(rows)

def kb_heatmap_menu() -> InlineKeyboardMarkup:
    """Меню выбора символа для тепловой карты."""
    rows = [
        [_b("BTC", "ui:heatmap:BTC"),
         _b("ETH", "ui:heatmap:ETH")],
        [_b("‹ Назад", "ui:more")],
    ]
    return InlineKeyboardMarkup(rows)

# === Справка / Отчёт ===

def kb_help() -> InlineKeyboardMarkup:
    rows = [
        [_b("ℹ️ Краткая справка", "ui:help:short"),
         _b("📘 Полная справка", "ui:help:full")],
        [_b("‹ Назад", "ui:main")],
    ]
    return InlineKeyboardMarkup(rows)

def kb_report() -> InlineKeyboardMarkup:
    rows = [
        [_b("📊 Краткий", "ui:report:short"),
         _b("🧾 Полный", "ui:report:full")],
        [_b("‹ Назад", "ui:main")],
    ]
    return InlineKeyboardMarkup(rows)

# === Меню TF (если используешь) ===

def kb_tf() -> InlineKeyboardMarkup:
    rows = [
        [_b("15m", "ui:tf:set:15m"),
         _b("1h",  "ui:tf:set:1h"),
         _b("4h",  "ui:tf:set:4h"),
         _b("24h", "ui:tf:set:1d")],   # подпись 24h, payload = 1d
        [_b("‹ Назад", "ui:back")],
    ]
    return InlineKeyboardMarkup(rows)

# === Чарты / Альбом ===

def kb_charts() -> InlineKeyboardMarkup:
    """Меню выбора таймфрейма для графиков."""
    rows = [
        [_b("15 мин", "ui:chart:tf:15m"),
         _b("1ч", "ui:chart:tf:1h")],
        [_b("4ч", "ui:chart:tf:4h"),
         _b("1д", "ui:chart:tf:1d")],
        [_b("‹ Назад", "ui:main")],
    ]
    return InlineKeyboardMarkup(rows)

def kb_chart_symbols(tf: str) -> InlineKeyboardMarkup:
    """Меню выбора символа для графика по выбранному ТФ."""
    rows = [
        [_b("📊 Сводная", f"ui:chart:summary:{tf}")],
        [_b("BTC", f"ui:chart:symbol:BTC:{tf}"),
         _b("ETH", f"ui:chart:symbol:ETH:{tf}"),
         _b("SOL", f"ui:chart:symbol:SOL:{tf}")],
        [_b("XRP", f"ui:chart:symbol:XRP:{tf}"),
         _b("ENA", f"ui:chart:symbol:ENA:{tf}"),
         _b("BNB", f"ui:chart:symbol:BNB:{tf}")],
        [_b("WIF", f"ui:chart:symbol:WIF:{tf}"),
         _b("PENGU", f"ui:chart:symbol:PENGU:{tf}"),
         _b("FART", f"ui:chart:symbol:FART:{tf}")],
        [_b("✏️ Введите свой тикер", f"ui:chart:custom:{tf}")],
        [_b("⚙️ Настройки", "ui:chart:settings")],
        [_b("‹ Назад", "ui:charts")],
    ]
    return InlineKeyboardMarkup(rows)

def kb_album_menu() -> InlineKeyboardMarkup:
    rows = [
        [_b("15m", "ui:album:15m"),
         _b("1h",  "ui:album:1h"),
         _b("4h",  "ui:album:4h"),
         _b("1d",  "ui:album:1d")],
        [_b("‹ Назад", "ui:main")],
    ]
    return InlineKeyboardMarkup(rows)

def kb_chart_settings(current_settings: dict = None) -> InlineKeyboardMarkup:
    """Меню настроек графика."""
    if current_settings is None:
        current_settings = {}
    
    # Режим отображения
    mode = current_settings.get("mode", "candle")
    mode_text = {
        "line": "📈 Линия",
        "candle": "🕯 Свечи",
        "candle+heikin": "🕯 Heikin-Ashi"
    }.get(mode, "🕯 Свечи")
    
    # Оверлеи
    has_sma = bool(current_settings.get("sma_periods"))
    has_ema = bool(current_settings.get("ema_periods"))
    has_bb = current_settings.get("bb_period") is not None
    has_ichimoku = current_settings.get("ichimoku_enabled", False)
    
    # Подложки
    has_ribbon = current_settings.get("ribbon", False)
    has_separator = current_settings.get("separator") is not None
    has_pivots = current_settings.get("pivots", False)
    has_lastline = current_settings.get("lastline", False)
    has_last_badge = current_settings.get("last_badge", False)
    has_last_ind = current_settings.get("last_ind", True)  # По умолчанию включено
    
    # Индикаторы
    has_vol = current_settings.get("show_volume", False)
    has_rsi = current_settings.get("show_rsi", False)
    has_macd = current_settings.get("show_macd", False)
    has_atr = current_settings.get("show_atr", False)
    
    # Легенда
    legend = current_settings.get("legend", "top")
    legend_text = {
        "top": "⬆️ Вверху",
        "bottom": "⬇️ Внизу",
        "off": "❌ Выкл"
    }.get(legend, "⬆️ Вверху")
    
    rows = [
        [_b(f"Режим: {mode_text}", "ui:chart:settings:mode")],
        [_b("📊 Оверлеи", "ui:chart:settings:overlays")],
        [_b(f"{'✅' if has_sma else '☐'} SMA", "ui:chart:settings:sma"),
         _b(f"{'✅' if has_ema else '☐'} EMA", "ui:chart:settings:ema"),
         _b(f"{'✅' if has_bb else '☐'} BB", "ui:chart:settings:bb")],
        [_b(f"{'✅' if has_ichimoku else '☐'} Ichimoku", "ui:chart:settings:ichimoku")],
        [_b("🎨 Подложки", "ui:chart:settings:annotations")],
        [_b(f"{'✅' if has_ribbon else '☐'} Ribbon", "ui:chart:settings:ribbon"),
         _b(f"{'✅' if has_separator else '☐'} Sep", "ui:chart:settings:separator")],
        [_b(f"{'✅' if has_pivots else '☐'} Pivots", "ui:chart:settings:pivots"),
         _b(f"{'✅' if has_lastline else '☐'} LastLine", "ui:chart:settings:lastline")],
        [_b(f"{'✅' if has_last_badge else '☐'} Last Badge", "ui:chart:settings:last_badge"),
         _b(f"{'✅' if has_last_ind else '☐'} Last Ind", "ui:chart:settings:last_ind")],
        [_b(f"{'✅' if current_settings.get('show_divergences', False) else '☐'} Дивергенции", "ui:chart:settings:divergences")],
        [_b("📉 Нижние панели", "ui:chart:settings:indicators")],
        [_b(f"{'✅' if has_vol else '☐'} Volume", "ui:chart:settings:vol"),
         _b(f"{'✅' if has_rsi else '☐'} RSI 14", "ui:chart:settings:rsi")],
        [_b(f"{'✅' if has_macd else '☐'} MACD", "ui:chart:settings:macd"),
         _b(f"{'✅' if has_atr else '☐'} ATR 14", "ui:chart:settings:atr")],
        [_b(f"Легенда: {legend_text}", "ui:chart:settings:legend")],
        [_b("🖼 Render Preview", "ui:chart:settings:preview")],
        [_b("🔄 Сбросить", "ui:chart:settings:reset")],
        [_b("‹ Назад", "ui:chart:settings:back")],
    ]
    return InlineKeyboardMarkup(rows)

# === Подменю: Пузырьки ===

def kb_bubbles_menu() -> InlineKeyboardMarkup:
    rows = [
        [_b("15мин", "ui:bubbles:15m"),
         _b("1 час", "ui:bubbles:1h"),
         _b("1 день", "ui:bubbles:1d")],
        [_b("⚙️ Настройки", "ui:bubbles:settings")],
        [_b("◀ Назад", "ui:main")],
    ]
    return InlineKeyboardMarkup(rows)

# === Подменю: Топ ===

def kb_top_menu() -> InlineKeyboardMarkup:
    rows = [
        [_b("Топ 24", "ui:cmd:/top_24h"),
         _b("Флоп 24", "ui:cmd:/flop_24h")],
        [_b("Топ 1ч", "ui:cmd:/top_1h"),
         _b("Флоп 1ч", "ui:cmd:/flop_1h")],
        [_b("🗂 Категории", "ui:cmd:/categories")],
        [_b("‹ Назад", "ui:main")],
    ]
    return InlineKeyboardMarkup(rows)

# === Подменю: Опционы ===

def kb_options_menu() -> InlineKeyboardMarkup:
    rows = [
        [_b("Опционы BTC", "ui:cmd:/btc_options"),
         _b("Опционы ETH", "ui:cmd:/eth_options")],
        [_b("‹ Назад", "ui:main")],
    ]
    return InlineKeyboardMarkup(rows)

# === Подменю: Прогноз ===

def kb_forecast_menu() -> InlineKeyboardMarkup:
    rows = [
        [_b("1 час", "ui:forecast:1h"),
         _b("4 часа", "ui:forecast:4h"),
         _b("1 день", "ui:forecast:1d")],
        [_b("‹ Назад", "ui:main")],
    ]
    return InlineKeyboardMarkup(rows)

# === Подменю: Market Doctor ===

def kb_md_format_menu(use_v2: bool = False) -> InlineKeyboardMarkup:
    """Меню выбора формата отчёта (краткий/полный) для Market Doctor."""
    v2_status = "✅" if use_v2 else "☐"
    rows = [
        [_b("📄 Краткий", "ui:md:format:brief"),
         _b("📋 Полный", "ui:md:format:full")],
        [_b(f"{v2_status} Генератор v2 (без дубликатов)", "ui:md:format:toggle_v2")],
        [_b("‹ Назад", "ui:main")],
    ]
    return InlineKeyboardMarkup(rows)

def kb_md_tf_menu(brief: bool = False) -> InlineKeyboardMarkup:
    """Меню выбора таймфрейма для Market Doctor."""
    format_prefix = "brief:" if brief else "full:"
    rows = [
        [_b("1 час", f"ui:md:tf:{format_prefix}1h"),
         _b("4 часа", f"ui:md:tf:{format_prefix}4h")],
        [_b("1 день", f"ui:md:tf:{format_prefix}1d"),
         _b("1 неделя", f"ui:md:tf:{format_prefix}1w")],
        [_b("🔄 Multi-TF (1h+4h+1d)", f"ui:md:tf:{format_prefix}multi")],
        [_b("‹ Назад", "ui:md:format")],
    ]
    return InlineKeyboardMarkup(rows)

def kb_md_symbol_menu(tf: str, brief: bool = False) -> InlineKeyboardMarkup:
    """Меню выбора символа для Market Doctor по выбранному ТФ."""
    # Используем полные тикеры для лучшей совместимости с биржами
    format_prefix = "brief:" if brief else "full:"
    rows = [
        [_b("BTC", f"ui:md:symbol:BTC:{format_prefix}{tf}"),
         _b("SOL", f"ui:md:symbol:SOL:{format_prefix}{tf}"),
         _b("BNB", f"ui:md:symbol:BNB:{format_prefix}{tf}")],
        [_b("ETH", f"ui:md:symbol:ETH:{format_prefix}{tf}"),
         _b("XRP", f"ui:md:symbol:XRP:{format_prefix}{tf}"),
         _b("ENA", f"ui:md:symbol:ENA:{format_prefix}{tf}")],
        [_b("WIF", f"ui:md:symbol:WIF:{format_prefix}{tf}"),
         _b("OP", f"ui:md:symbol:OP:{format_prefix}{tf}"),
         _b("TIA", f"ui:md:symbol:TIA:{format_prefix}{tf}")],
        [_b("✏️ Введите свой тикер", f"ui:md:custom:{format_prefix}{tf}")],
        [_b("‹ Назад", f"ui:md:tf:{format_prefix}")],
    ]
    return InlineKeyboardMarkup(rows)

# === Экраны: Главное / Более ===

def kb_more(tf: str = DEFAULT_TF) -> InlineKeyboardMarkup:
    rows = [
        [_b("🔥 Тренды",   "ui:cmd:/trending"),
         _b("🌍 Метрики",  "ui:cmd:/global")],
        [_b("🗞 Дайджест", "ui:cmd:/daily"),
         _b("🧭 Риск сейчас", "ui:cmd:/risk_now")],
        [_b("🗓 События", "ui:cmd:/events_list"),
         _b("📉 Вола", "ui:vol")],
        [_b("💥 Ликвидации", "ui:cmd:/liqs"),
         _b("🐋 Ордера китов", "ui:whale_orders")],
        [_b("🔗 Корр", "ui:corr"),
         _b("🌡 Тепловая карта", "ui:heatmap")],
        [_b("β Бета", "ui:beta"),
         _b("💵 Фандинг", "ui:funding")],
        [_b("⚖️ Базис", "ui:basis"),
         _b("🔎 Дивергенции", "ui:scan_divs")],
        [_b("📐 Уровни", "ui:cmd:/levels"),
         _b("🧠 BT RSI", "ui:bt_rsi")],
        [_b("🌡 Ширина", "ui:breadth"),
         _b("🧮 F&G история", "ui:cmd:/fng_history")],
        [_b("📊 Ticker", "ui:cmd:/ticker"),
         _b("🐋 Активность китов", "ui:whale_activity")],
        [_b("‹ Назад", "ui:main")],
    ]
    return InlineKeyboardMarkup(rows)

def kb_main(tf: str = DEFAULT_TF) -> InlineKeyboardMarkup:
    rows = [
        [_b("ℹ️ Справка", "ui:help"),
         _b("🧾 Отчёт", "ui:report")],
        [_b("🫧 Bubbles", "ui:bubbles"),
         _b("🏆 Топ", "ui:top")],
        [_b("📈 Чарты", "ui:charts"),
         _b("🖼 Альбом", "ui:album")],
        [_b("🔮 Прогноз", "ui:forecast"),
         _b("🏥 Market Doctor", "ui:md")],
        [_b("🧩 Опционы", "ui:options"),
         _b("📈 TWAP сейчас", "ui:cmd:/twap")],
        [_b("🪙 Altseason", "ui:cmd:/altseason"),
         _b("🧭 F&G", "ui:cmd:/fng")],
        [_b("📘 Инструкция", "ui:cmd:/instruction"),
         _b("➡️ Ещё", "ui:more")],
    ]
    return InlineKeyboardMarkup(rows)


def get_main_reply_keyboard() -> ReplyKeyboardMarkup:
    """Создать постоянную клавиатуру внизу экрана с основными командами."""
    keyboard = [
        [KeyboardButton("ℹ️ Справка"), KeyboardButton("🧾 Отчёт")],
        [KeyboardButton("🫧 Bubbles"), KeyboardButton("🏆 Топ")],
        [KeyboardButton("📈 Чарты"), KeyboardButton("🖼 Альбом")],
        [KeyboardButton("🔮 Прогноз"), KeyboardButton("🧩 Опционы")],
        [KeyboardButton("📈 TWAP"), KeyboardButton("🪙 Altseason")],
        [KeyboardButton("🧭 F&G"), KeyboardButton("➡️ Ещё")],
        [KeyboardButton("📋 Меню")],  # Кнопка для раскрытия полного меню
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)


def get_reply_markup_with_menu(inline_keyboard: InlineKeyboardMarkup | None = None) -> ReplyKeyboardMarkup | InlineKeyboardMarkup:
    """
    Получить клавиатуру для ответа. Всегда включает постоянную клавиатуру с кнопкой меню.
    Если передан inline_keyboard, возвращает его (inline-кнопки имеют приоритет).
    Иначе возвращает постоянную клавиатуру.
    """
    if inline_keyboard is not None:
        return inline_keyboard
    return get_main_reply_keyboard()


# Флаг для использования меню бота вместо inline-кнопок главного меню
USE_BOT_MENU = True  # Установите False, чтобы вернуть inline-кнопки главного меню

def build_kb(state: str = "main", tf: str = DEFAULT_TF, force_show: bool = False, context=None, user_data: dict = None) -> InlineKeyboardMarkup | None:
    """
    Создать клавиатуру. Если USE_BOT_MENU=True и state="main", возвращает None
    (кнопки будут в меню бота, а не под сообщением).
    Но если force_show=True, всегда показывает меню.
    """
    # Если используем меню бота, не показываем главное меню как inline-кнопки по умолчанию
    # Но если явно запрашивается (force_show=True), показываем
    if USE_BOT_MENU and state == "main" and not force_show:
        return None
    
    if state == "help":       return kb_help()
    if state == "report":     return kb_report()
    if state == "tf":         return kb_tf()
    if state == "more":       return kb_more(tf)
    if state == "charts":     return kb_charts()
    if state == "album":      return kb_album_menu()
    if state == "bubbles":    return kb_bubbles_menu()
    if state == "top":        return kb_top_menu()
    if state == "options":    return kb_options_menu()
    if state == "vol":        return kb_vol_menu()
    if state == "corr":       return kb_corr_menu()
    if state == "beta":       return kb_beta_menu()
    if state == "funding":    return kb_funding_menu()
    if state == "basis":      return kb_basis_menu()
    if state == "scan_divs":  return kb_scan_divs_menu()
    if state == "levels":     return kb_levels_menu()
    if state == "bt_rsi":     return kb_bt_rsi_menu()
    if state == "breadth":    return kb_breadth_menu()
    if state == "forecast":   return kb_forecast_menu()
    if state == "md":         
        # По умолчанию генератор v2 включён
        use_v2 = True
        if user_data:
            use_v2 = user_data.get('md_use_v2', True)
        elif context and hasattr(context, 'user_data') and context.user_data:
            use_v2 = context.user_data.get('md_use_v2', True)
        return kb_md_format_menu(use_v2=use_v2)
    if state == "md:format":  
        # По умолчанию генератор v2 включён
        use_v2 = True
        if user_data:
            use_v2 = user_data.get('md_use_v2', True)
        elif context and hasattr(context, 'user_data') and context.user_data:
            use_v2 = context.user_data.get('md_use_v2', True)
        return kb_md_format_menu(use_v2=use_v2)
    if state == "whale_orders": return kb_whale_orders_menu()
    if state == "whale_activity": return kb_whale_activity_menu()
    if state.startswith("whale_activity_symbol:"):  # whale_activity_symbol:BTC, whale_activity_symbol:ETH
        symbol_part = state.split(":", 1)[1] if ":" in state else "BTC"
        return kb_whale_activity_tf_menu(symbol_part)
    if state == "heatmap": return kb_heatmap_menu()
    if state.startswith("md_symbol:"):  # md_symbol:1h, md_symbol:4h, etc.
        tf_part = state.split(":", 1)[1] if ":" in state else DEFAULT_TF
        return kb_md_symbol_menu(tf_part)
    return kb_main(tf)
