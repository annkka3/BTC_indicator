# app/presentation/handlers/command_handler.py
"""
Handler for basic commands (start, help, info, etc.).
"""

from telegram import Update
from telegram.ext import ContextTypes
from telegram.constants import ParseMode
from .base_handler import BaseHandler
from ...infrastructure.instructions import INSTRUCTION_HTML, HELP_SHORT_HTML, HELP_FULL_HTML
from ...infrastructure.ui_keyboards import build_kb, get_main_reply_keyboard
import logging

logger = logging.getLogger("alt_forecast.handlers.commands")


class CommandHandler(BaseHandler):
    """Обработчик базовых команд бота."""
    
    async def handle_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработать команду /start."""
        try:
            msg = (
                "Привет!\n"
                "Я ALT Forecast — твой крипто-навигатор:\n"
                "рынок одним взглядом, пузыри как CryptoBubbles, топы/флопы, корреляции,\n"
                "волатильность, риск-режим, опционы и куча других\n"
                "полезных штук.\n"
                "Нажимай кнопки ниже — поехали!\n"
                "Хочешь подписаться на отчёты бота нажми /subscribe"
            )
            await update.effective_message.reply_text(
                msg,
                parse_mode=ParseMode.HTML,
                reply_markup=get_main_reply_keyboard(),
            )
        except Exception:
            logger.exception("handle_start failed")
    
    async def handle_help(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработать команду /help (краткая справка)."""
        try:
            text = (
                "<b>ALT Forecast — что умею</b> 👉\n\n"
                "<b>Отчёты</b>\n"
                "• /status — краткий срез\n"
                "• /full — полный обзор\n\n"
                "<b>Рынок</b>\n"
                "• /top, /flop, /top_1h, /flop_1h\n"
                "• /trending\n"
                "• /categories\n\n"
                "<b>Визуал</b>\n"
                "• /bubbles 1h|1d\n"
                "• /chart_*\n"
                "• /chart_album_*\n\n"
                "<b>Индексы</b>\n"
                "• /fng\n"
                "• /altseason\n\n"
                "<b>Ещё</b>\n"
                "жми кнопку «➡️ Ещё» внизу — там вола, корреляции, фандинг/базис и т.д.\n\n"
                "<i>Подсказка:</i> настройки пузырьков (размер/кол-во/стейблы) — через «🫧 Bubbles → ⚙️ Настройки»."
            )
            await update.effective_message.reply_text(
                text,
                parse_mode=ParseMode.HTML,
                reply_markup=build_kb('help'),
            )
        except Exception:
            logger.exception("handle_help failed")
    
    async def handle_help_full(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработать команду /help_full (полная справка)."""
        try:
            await update.effective_message.reply_text(
                HELP_FULL_HTML,
                parse_mode=ParseMode.HTML,
                reply_markup=build_kb('help'),
            )
        except Exception:
            logger.exception("handle_help_full failed")
    
    async def handle_instruction(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработать команду /instruction."""
        try:
            await update.effective_message.reply_text(
                INSTRUCTION_HTML,
                parse_mode=ParseMode.HTML,
                reply_markup=build_kb('main'),
            )
        except Exception:
            logger.exception("handle_instruction failed")
    
    async def handle_info(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработать команду /info."""
        try:
            text = (
                "<b>ALT Forecast Bot</b>\n\n"
                "Версия: 2.0\n"
                "Архитектура: Clean Architecture\n\n"
                "Используемые источники данных:\n"
                "• CoinGecko API\n"
                "• Binance API\n"
                "• Coinglass API\n"
            )
            await update.effective_message.reply_text(
                text,
                parse_mode=ParseMode.HTML,
                reply_markup=build_kb('main'),
            )
        except Exception:
            logger.exception("handle_info failed")
    
    async def handle_trending(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработать команду /trending."""
        try:
            from ...infrastructure.coingecko import trending
            chat_id = update.effective_chat.id
            tr = trending()
            coins = tr.get("coins", [])
            if not coins:
                await context.bot.send_message(chat_id=chat_id, text="Тренды: пусто")
                return
            lines = []
            for item in coins[:10]:
                c = item.get("item", {})
                lines.append(f"{c.get('symbol', '').upper():<6} rank{c.get('market_cap_rank')}  score {c.get('score')}")
            await context.bot.send_message(
                chat_id=chat_id,
                text="🔥 *Trending*\n" + "\n".join(lines),
                parse_mode=ParseMode.MARKDOWN
            )
        except Exception:
            logger.exception("handle_trending failed")
    
    async def handle_global(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработать команду /global."""
        # Обрабатываем callback query если есть
        q = update.callback_query
        if q:
            await q.answer()
        
        # Делегируем старому методу пока (сложная логика с кэшированием)
        # TODO: Вынести логику в сервис
        # Возвращаем False, чтобы использовался fallback на старый код
        return False
    
    async def handle_daily(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработать команду /daily."""
        try:
            chat_id = update.effective_chat.id
            uid = update.effective_user.id
            args = [a.lower() for a in (context.args or [])]
            if not args:
                vs, count, hide, seed, daily, hour, size_mode, top, tf_setting = self.db.get_user_settings(uid)
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=f"Daily: {'ON' if daily else 'OFF'}, время: {hour}:00"
                )
                return
            if args[0] == "on":
                h = int(args[1]) if len(args) > 1 and args[1].isdigit() else 9
                self.db.set_user_settings(uid, daily_digest=1, daily_hour=h)
                await context.bot.send_message(chat_id=chat_id, text=f"✅ Daily включён на {h}:00")
            elif args[0] == "off":
                self.db.set_user_settings(uid, daily_digest=0)
                await context.bot.send_message(chat_id=chat_id, text="⛔️ Daily выключен")
            else:
                await context.bot.send_message(
                    chat_id=chat_id,
                    text="Используй: /daily on [час] | /daily off"
                )
        except Exception:
            logger.exception("handle_daily failed")
    
    async def handle_ticker(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработать команду /ticker."""
        try:
            parts = (getattr(update.effective_message, "text", "") or "").split()
            
            # sort
            allowed_sorts = {"rank", "percent_change_1h", "percent_change_24h", "percent_change_7d", "volume_24h", "market_cap"}
            sort = parts[1].lower() if len(parts) > 1 and parts[1].lower() in allowed_sorts else "rank"
            
            # limit
            limit = 20
            if len(parts) > 2:
                try:
                    limit = int(parts[2])
                except Exception:
                    limit = 20
            limit = max(5, min(limit, 50))
            
            # convert
            convert = parts[3].upper() if len(parts) > 3 and len(parts[3]) in (3, 4) else "USD"
            
            # Получаем данные через IndicesService
            from ...infrastructure.indices_service import IndicesService
            indices = IndicesService(None)
            rows = await indices.get_ticker(limit=limit, sort=sort, convert=convert, structure="array")
            
            if not rows:
                await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text="Нет данных тикера.",
                    reply_markup=build_kb("more")
                )
                return
            
            head = f"<b>/ticker</b> — sort: <code>{sort}</code>, limit: <code>{limit}</code>, convert: <code>{convert}</code>\n"
            lines = [head]
            for r in rows:
                price = f'{r["price"]:.4f} {convert}'
                chg = r.get("percent_change_24h", 0.0)
                lines.append(f"• <b>{r['symbol']}</b>: {price} ({chg:+.2f}%)")
            
            text = "\n".join(lines)
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=text,
                parse_mode=ParseMode.HTML,
                reply_markup=build_kb("more")
            )
        except Exception:
            logger.exception("handle_ticker failed")
    
    async def handle_subscribe(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработать команду /subscribe."""
        try:
            self.db.add_sub(update.effective_chat.id)
            await update.effective_message.reply_text("Подписал на авто-обновления. /unsubscribe — отписка.")
        except Exception:
            logger.exception("handle_subscribe failed")
    
    async def handle_unsubscribe(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработать команду /unsubscribe."""
        try:
            self.db.remove_sub(update.effective_chat.id)
            await update.effective_message.reply_text("Подписка отключена.")
        except Exception:
            logger.exception("handle_unsubscribe failed")
    
    async def handle_cg_test(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработать команду /cg_test (тест CoinGecko API)."""
        try:
            from ...infrastructure.coingecko import markets_page
            rows = markets_page(vs="usd", page=1, per_page=5)
            syms = ", ".join([str(r.get("symbol", "")).upper() for r in rows])
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=f"CoinGecko OK: {len(rows)} монет. Примеры: {syms}"
            )
        except Exception as e:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=f"CoinGecko ERROR: {type(e).__name__}: {e}"
            )
    
    async def handle_traditional_markets(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработать команду /markets (традиционные рынки: S&P500, золото, нефть)."""
        try:
            traditional_markets = self.services.get("traditional_markets_service")
            if not traditional_markets:
                await update.effective_message.reply_text(
                    "Сервис традиционных рынков недоступен.",
                    reply_markup=build_kb("main")
                )
                return
            
            # Получаем данные обо всех рынках
            markets = traditional_markets.get_all_traditional_markets()
            
            lines = ["<b>📊 Традиционные рынки</b>\n"]
            
            # S&P500
            sp500 = markets.get("sp500")
            if sp500:
                emoji = "🟢" if sp500["change_percent_24h"] > 0 else "🔴" if sp500["change_percent_24h"] < 0 else "⚪"
                lines.append(
                    f"{emoji} <b>{sp500['name']}</b>: {sp500['price']:,.2f} "
                    f"({sp500['change_percent_24h']:+.2f}%)"
                )
            else:
                lines.append("❌ S&P 500: данные недоступны")
            
            # Золото
            gold = markets.get("gold")
            if gold:
                emoji = "🟢" if gold["change_percent_24h"] > 0 else "🔴" if gold["change_percent_24h"] < 0 else "⚪"
                lines.append(
                    f"{emoji} <b>{gold['name']}</b>: ${gold['price_usd']:,.2f}/oz "
                    f"({gold['change_percent_24h']:+.2f}%)"
                )
            else:
                lines.append("❌ Gold: данные недоступны")
            
            # Нефть
            oil = markets.get("oil")
            if oil:
                emoji = "🟢" if oil["change_percent_24h"] > 0 else "🔴" if oil["change_percent_24h"] < 0 else "⚪"
                lines.append(
                    f"{emoji} <b>{oil['name']}</b>: ${oil['price_usd']:,.2f}/bbl "
                    f"({oil['change_percent_24h']:+.2f}%)"
                )
            else:
                lines.append("❌ Oil: данные недоступны")
            
            lines.append("\n<i>Данные обновляются в реальном времени</i>")
            
            # Если все данные недоступны, добавляем подсказку
            if not sp500 and not gold and not oil:
                lines.append("\n⚠️ <i>Для работы требуется установить yfinance: pip install yfinance</i>")
            
            text = "\n".join(lines)
            
            await update.effective_message.reply_text(
                text,
                parse_mode=ParseMode.HTML,
                reply_markup=build_kb("main")
            )
        except Exception:
            logger.exception("handle_traditional_markets failed")
            await update.effective_message.reply_text(
                "❌ Ошибка при получении данных о традиционных рынках.\n\n"
                "⚠️ Для работы требуется установить yfinance:\n"
                "<code>pip install yfinance</code>",
                parse_mode=ParseMode.HTML,
                reply_markup=build_kb("main")
            )

