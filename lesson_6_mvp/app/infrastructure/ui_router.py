from telegram import Update
from telegram.ext import ContextTypes
from .ui_keyboards import build_kb, DEFAULT_TF
from ..presentation.handlers.callback_router import CallbackRouter


def _norm_tf(tf: str) -> str:
    # любой суточный вариант → 1d
    tf = (tf or "").lower()
    if tf in ("1d", "24h", "d1", "1day", "day"):
        return "1d"
    return tf


class UIRouter:
    """Роутер для UI callback'ов. Использует новый CallbackRouter с паттерном Command."""
    
    def __init__(self, integrator=None, db=None):
        """
        Args:
            integrator: CommandIntegrator для использования новой архитектуры
            db: Database instance для доступа к данным
        """
        self.integrator = integrator
        self.db = db
        self.callback_router = CallbackRouter.create_default_router(integrator, db)
        # Сохраняем старый метод для fallback
        self._legacy_handle = self._legacy_handle_impl
    
    async def handle(self, update: Update, context: ContextTypes.DEFAULT_TYPE, bot) -> None:
        """Обработать callback query через новый CallbackRouter."""
        try:
            # Используем новый роутер
            await self.callback_router.handle(update, context, bot)
        except Exception:
            # Fallback на старый код при ошибке
            import logging
            logger = logging.getLogger("alt_forecast.ui_router")
            logger.exception("Error in new callback router, falling back to legacy")
            await self._legacy_handle(update, context, bot)
    
    async def _legacy_handle_impl(self, update: Update, context: ContextTypes.DEFAULT_TYPE, bot) -> None:
        """Старая реализация для fallback."""
        q = update.callback_query
        await q.answer()

        data = q.data
        ud = context.user_data
        tf = ud.get("tf", DEFAULT_TF)
        prev = ud.get("ui_prev", "main")

        def _render(state: str):
            ud["ui_prev"] = state
            return build_kb(state, ud.get("tf", DEFAULT_TF), user_data=ud)

        # ---------- Навигация ----------
        if data == "ui:main":
            await q.edit_message_reply_markup(_render("main")); return
        if data == "ui:more":
            await q.edit_message_reply_markup(_render("more")); return
        if data == "ui:help":
            await q.edit_message_reply_markup(_render("help")); return
        if data == "ui:report":
            await q.edit_message_reply_markup(_render("report")); return
        if data == "ui:charts":
            await q.edit_message_reply_markup(_render("charts")); return
        if data == "ui:album":
            await q.edit_message_reply_markup(_render("album")); return
        if data == "ui:bubbles":
            await q.edit_message_reply_markup(_render("bubbles")); return
        if data == "ui:top":
            await q.edit_message_reply_markup(_render("top")); return
        if data == "ui:options":
            await q.edit_message_reply_markup(_render("options")); return
        if data == "ui:vol":
            await q.edit_message_reply_markup(_render("vol")); return
        if data == "ui:levels":
            await q.edit_message_reply_markup(_render("levels")); return
        if data == "ui:corr":
            await q.edit_message_reply_markup(_render("corr")); return
        if data == "ui:beta":
            await q.edit_message_reply_markup(_render("beta")); return
        if data == "ui:funding":
            await q.edit_message_reply_markup(_render("funding")); return
        if data == "ui:basis":
            await q.edit_message_reply_markup(_render("basis")); return
        if data == "ui:scan_divs":
            return await bot.on_scan_divs(update, context)
        if data == "ui:bt_rsi":
            await q.edit_message_reply_markup(_render("bt_rsi")); return
        if data == "ui:breadth":
            await q.edit_message_reply_markup(_render("breadth")); return
        if data == "ui:md":
            await q.edit_message_reply_markup(_render("md")); return
        if data == "ui:tf":
            ud["ui_prev"] = prev
            await q.edit_message_reply_markup(build_kb("tf", tf)); return
        if data == "ui:back":
            await q.edit_message_reply_markup(_render(prev)); return

        # ---------- Установка TF ----------
        if data.startswith("ui:tf:set:"):
            ud["tf"] = _norm_tf(data.split(":", 2)[2])
            await q.edit_message_reply_markup(_render(prev)); return

        # ---------- Справка/Отчёт ----------
        if data == "ui:help:short":   return await bot.on_help(update, context)
        if data == "ui:help:full":    return await bot.on_help_full(update, context)
        if data == "ui:report:short": return await bot.on_status(update, context)
        if data == "ui:report:full":  return await bot.on_full(update, context)

        # ---------- Чарты/Альбом по ТФ (подменю) ----------
        if data.startswith("ui:chart:"):
            ud["tf"] = _norm_tf(data.split(":", 2)[2])
            return await bot.on_chart(update, context)

        if data.startswith("ui:album:"):
            ud["tf"] = _norm_tf(data.split(":", 2)[2])
            return await bot.on_chart_album(update, context)

        # ---------- Волатильность / Уровни: запуск по выбранному TF (подменю) ----------
        if data.startswith("ui:vol:"):
            ud["tf"] = _norm_tf(data.split(":", 2)[2])
            return await bot.on_vol(update, context)

        if data.startswith("ui:levels:"):
            ud["tf"] = _norm_tf(data.split(":", 2)[2])
            ud.setdefault("symbol", "BTC")
            return await bot.on_levels(update, context)

        # ---------- Подменю: Корреляция/Бета/Фандинг/Базис/Дивергенции/BT RSI/Ширина ----------
        if data.startswith("ui:corr:"):
            ud["tf"] = _norm_tf(data.split(":", 2)[2])
            return await bot.on_corr(update, context)

        if data.startswith("ui:beta:"):
            ud["tf"] = _norm_tf(data.split(":", 2)[2])
            ud["pair"] = "ETHBTC"
            return await bot.on_beta(update, context)

        if data.startswith("ui:funding:"):
            ud["symbol"] = data.split(":", 2)[2]
            return await bot.on_funding(update, context)

        if data.startswith("ui:basis:"):
            ud["symbol"] = data.split(":", 2)[2]
            return await bot.on_basis(update, context)

        if data.startswith("ui:scan_divs:"):
            ud["tf"] = _norm_tf(data.split(":", 2)[2])
            return await bot.on_scan_divs(update, context)

        if data.startswith("ui:bt_rsi:"):
            ud["tf"] = _norm_tf(data.split(":", 2)[2])
            ud["symbol"] = "BTC"
            ud["study"]  = "rsi"
            return await bot.on_backtest(update, context)

        if data.startswith("ui:breadth:"):
            ud["tf"] = _norm_tf(data.split(":", 2)[2])
            return await bot.on_breadth(update, context)

        # ---------- Подменю: Пузырьки ----------
        if data.startswith("ui:bubbles:"):
            parts = data.split(":", 2)
            if len(parts) == 3:
                action = parts[2]
                if action == "settings":
                    return await bot.on_bubbles_settings(update, context)
                else:
                    # ui:bubbles:15m, ui:bubbles:1h, ui:bubbles:1d
                    tf_bubbles = _norm_tf(action)
                    # Сохраняем выбранный TF в настройки пользователя
                    ud["bubbles_tf"] = tf_bubbles
                    user_id = update.effective_user.id if update.effective_user else None
                    if user_id:
                        bot.db.set_user_settings(user_id, bubbles_tf=tf_bubbles)
                    return await bot.on_bubbles(update, context, tf_bubbles)

        # ---------- Прямые команды КНОПОК (без подменю) ----------
        # ВАЖНО: эти ветки стоят ДО общего словаря.
        if data == "ui:cmd:/vol":
            return await bot.on_vol(update, context)

        if data == "ui:cmd:/levels":
            return await bot.on_levels(update, context)

        # ---------- Категории: Тренды и Глобалка ----------
        if data == "categories:trending":
            return await bot.on_trending(update, context)
        if data == "categories:global":
            return await bot.on_global(update, context)

        # ---------- Прочие прямые команды ----------
        if data.startswith("ui:cmd:/"):
            raw = data.split("ui:cmd:", 1)[1]
            cmd = raw.strip().lower()

            mapping = {
                "/trending":    getattr(bot, "on_trending",    None),
                "/global":      getattr(bot, "on_global",      None),
                "/daily":       getattr(bot, "on_daily_cmd",   None),
                "/btc_options": getattr(bot, "on_options_btc", None),
                "/eth_options": getattr(bot, "on_options_eth", None),
                "/top_24h":     (lambda u, c: (setattr(c, 'args', ['24h']) or bot.on_top(u, c))),
                "/flop_24h":    (lambda u, c: (setattr(c, 'args', ['24h']) or bot.on_flop(u, c))),
                "/top_1h":      (lambda u, c: (setattr(c, 'args', ['1h']) or bot.on_top(u, c))),
                "/flop_1h":     (lambda u, c: (setattr(c, 'args', ['1h']) or bot.on_flop(u, c))),
                "/twap":        getattr(bot, "on_twap",        None),
                "/instruction": getattr(bot, "on_info",        None),
                "/beta":        getattr(bot, "on_beta",        None),
                "/funding":     getattr(bot, "on_funding",     None),
                "/basis":       getattr(bot, "on_basis",       None),
                "/scan_divs":   getattr(bot, "on_scan_divs",   None),
                "/levels":      getattr(bot, "on_levels",      None),   # безопасно, если где-то придёт
                "/risk_now":    getattr(bot, "on_risk_now",    None),
                "/events_list": getattr(bot, "on_events_list", None),
                "/breadth":     getattr(bot, "on_breadth",     None),
                "/vol":         getattr(bot, "on_vol",         None),   # безопасно, если где-то придёт
                "/categories":  getattr(bot, "on_categories_btn", None),
                "/fng": getattr(bot, "on_fng", None),
                "/altseason": getattr(bot, "on_altseason", None),
                "/fng_history": getattr(bot, "on_fng_history", None),
                "/ticker": getattr(bot, "on_ticker", None),
                # --- ПРОГНОЗЫ ---
                "/forecast":       getattr(bot, "cmd_forecast_from_btn", None),
                "/forecast3":      getattr(bot, "cmd_forecast3_from_btn", None),
                "/forecast_full":  getattr(bot, "cmd_forecast_full_from_btn", None),
                "/forecast_alts":  getattr(bot, "cmd_forecast_alts_from_btn", None),

                # ----------------
                # Особые кейсы
                "/bubbles_1h":  (lambda u, c: bot.on_bubbles(u, c, "1h")),
                "/bubbles_24h": (lambda u, c: bot.on_bubbles(u, c, "24h")),
                "/liqs":        getattr(bot, "on_liqs",        None),
                "/bt":          getattr(bot, "on_backtest",    None),
            }

            fn = mapping.get(cmd)
            if fn:
                return await fn(update, context)

            await q.answer("Команда временно недоступна", show_alert=False)
            return

        # ---------- Команды, зависящие от TF (через user_data) ----------
        if data.startswith("ui:cmdtf:/"):
            cmd = data.split("ui:cmdtf:", 1)[1]
            # tf уже должен быть в ud["tf"] после выбора, но подстрахуемся:
            ud["tf"] = ud.get("tf", DEFAULT_TF)
            if cmd == "/chart":        return await bot.on_chart(update, context)
            if cmd == "/chart_album":  return await bot.on_chart_album(update, context)
            if cmd == "/corr":         return await bot.on_corr(update, context)
            if cmd == "/vol":          return await bot.on_vol(update, context)      # на всякий случай
            if cmd == "/levels":       return await bot.on_levels(update, context)   # на всякий случай
            if cmd == "/forecast":       return await bot.cmd_forecast(update, context)
            if cmd == "/forecast_full":  return await bot.cmd_forecast_full(update, context)
            if cmd == "/forecast3":      return await bot.cmd_forecast3(update, context)
            return
