# app/presentation/handlers/top_flop_handler.py
"""
Handler for top/flop commands.
"""

from telegram import Update
from telegram.ext import ContextTypes
from telegram.constants import ParseMode
from .base_handler import BaseHandler
from ...infrastructure.ui_keyboards import build_kb
import logging

logger = logging.getLogger("alt_forecast.handlers.top_flop")


class TopFlopHandler(BaseHandler):
    """Обработчик команд топ/флоп."""
    
    def __init__(self, db, services: dict):
        super().__init__(db, services)
        self.market_data_service = services.get("market_data_service")
    
    async def handle_top(self, update: Update, context: ContextTypes.DEFAULT_TYPE, tf: str = "24h"):
        """Обработать команду /top."""
        try:
            chat_id = update.effective_chat.id
            args = context.args or []
            
            # Определяем TF из аргументов или используем переданный
            if args and args[0] in ("1h", "24h", "7d"):
                tf = args[0]
            
            # Получаем данные
            coins, gainers, losers, _ = self.market_data_service.get_top_movers(
                vs="usd", tf=tf, limit_each=20, top=500
            )
            
            # Формируем сообщение
            lines = [f"<b>Топ-20 растущих ({tf})</b>\n"]
            for i, coin in enumerate(gainers[:20], 1):
                sym = coin.get("symbol", "").upper()
                chg = coin.get(f"price_change_percentage_{tf}_in_currency") or coin.get(f"price_change_percentage_{tf}") or 0.0
                price = coin.get("current_price", 0.0)
                lines.append(f"{i}. {sym}: {float(chg):+.2f}% (${float(price):,.2f})")
            
            text = "\n".join(lines)
            await context.bot.send_message(
                chat_id=chat_id,
                text=text,
                parse_mode=ParseMode.HTML,
                reply_markup=build_kb('main'),
            )
        except Exception:
            logger.exception("handle_top failed")
    
    async def handle_flop(self, update: Update, context: ContextTypes.DEFAULT_TYPE, tf: str = "24h"):
        """Обработать команду /flop."""
        try:
            chat_id = update.effective_chat.id
            args = context.args or []
            
            # Определяем TF из аргументов или используем переданный
            if args and args[0] in ("1h", "24h", "7d"):
                tf = args[0]
            
            # Получаем данные
            coins, gainers, losers, _ = self.market_data_service.get_top_movers(
                vs="usd", tf=tf, limit_each=20, top=500
            )
            
            # Формируем сообщение
            lines = [f"<b>Топ-20 падающих ({tf})</b>\n"]
            for i, coin in enumerate(losers[:20], 1):
                sym = coin.get("symbol", "").upper()
                chg = coin.get(f"price_change_percentage_{tf}_in_currency") or coin.get(f"price_change_percentage_{tf}") or 0.0
                price = coin.get("current_price", 0.0)
                lines.append(f"{i}. {sym}: {float(chg):+.2f}% (${float(price):,.2f})")
            
            text = "\n".join(lines)
            await context.bot.send_message(
                chat_id=chat_id,
                text=text,
                parse_mode=ParseMode.HTML,
                reply_markup=build_kb('main'),
            )
        except Exception:
            logger.exception("handle_flop failed")
    
    async def handle_categories(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработать команду /categories."""
        try:
            from telegram import InlineKeyboardButton, InlineKeyboardMarkup
            from ...infrastructure.coingecko import categories
            
            q = update.callback_query
            if q:
                await q.answer()
                cats = categories()
                # берём популярные
                names = [c.get("id") for c in cats if c.get("market_cap")][:12]  # 12 кнопок
                rows = []
                for i in range(0, len(names), 3):
                    chunk = names[i:i + 3]
                    rows.append([InlineKeyboardButton(n[:20], callback_data=f"cat:select:{n}") for n in chunk])
                rows.append([InlineKeyboardButton("🔥 Тренды", callback_data="categories:trending"),
                             InlineKeyboardButton("🌍 Глобалка", callback_data="categories:global")])
                kb = InlineKeyboardMarkup(rows)
                await q.edit_message_text("Выбери категорию:", reply_markup=kb)
            else:
                # Если команда вызвана напрямую, показываем список категорий
                cats = categories()
                names = [c.get("id") for c in cats if c.get("market_cap")][:12]
                rows = []
                for i in range(0, len(names), 3):
                    chunk = names[i:i + 3]
                    rows.append([InlineKeyboardButton(n[:20], callback_data=f"cat:select:{n}") for n in chunk])
                rows.append([InlineKeyboardButton("🔥 Тренды", callback_data="categories:trending"),
                             InlineKeyboardButton("🌍 Глобалка", callback_data="categories:global")])
                kb = InlineKeyboardMarkup(rows)
                await update.effective_message.reply_text("Выбери категорию:", reply_markup=kb)
        except Exception:
            logger.exception("handle_categories failed")
    
    async def handle_category_pick(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработать выбор категории."""
        try:
            from ...infrastructure.coingecko import markets_by_category
            
            q = update.callback_query
            if not q:
                return
            
            await q.answer()
            cat = q.data.split(":", 2)[2]
            data = markets_by_category(cat, vs="usd")
            if not data:
                await q.edit_message_text(f"Нет данных для категории {cat}")
                return
            
            def chg(c, key):
                return float(c.get(key) or 0.0)
            
            # топ/флоп за 24ч
            sorted24 = sorted(data, key=lambda c: chg(c, "price_change_percentage_24h_in_currency"), reverse=True)
            gain = sorted24[:5]
            loss = list(reversed(sorted24))[:5]
            
            def fmt(c):
                return f"{c['symbol'].upper():<6} {c['current_price']:.4g} USD ({(c.get('price_change_percentage_24h_in_currency') or 0):+,.2f}%)"
            
            text = f"*Категория*: `{cat}`\n\n*Топ-5 24h*\n" + "\n".join(map(fmt, gain)) + "\n\n*Флоп-5 24h*\n" + "\n".join(map(fmt, loss))
            await q.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, disable_web_page_preview=True)
        except Exception:
            logger.exception("handle_category_pick failed")

