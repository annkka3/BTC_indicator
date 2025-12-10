# app/presentation/handlers/options_handler.py
"""
Handler for options commands.
"""

from telegram import Update
from telegram.ext import ContextTypes
from telegram.constants import ParseMode
from .base_handler import BaseHandler
from ...infrastructure.ui_keyboards import build_kb
import logging

logger = logging.getLogger("alt_forecast.handlers.options")


class OptionsHandler(BaseHandler):
    """Обработчик команд опционов."""
    
    async def handle_btc_options(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработать команду /btc_options."""
        try:
            await self._send_options(update, context, "BTC")
        except Exception:
            logger.exception("handle_btc_options failed")
    
    async def handle_eth_options(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработать команду /eth_options."""
        try:
            await self._send_options(update, context, "ETH")
        except Exception:
            logger.exception("handle_eth_options failed")
    
    async def _send_options(self, update: Update, context: ContextTypes.DEFAULT_TYPE, symbol: str):
        """Отправить данные по опционам."""
        try:
            chat_id = update.effective_chat.id
            
            # Проверяем наличие Coinglass API
            import os
            has_coinglass = bool(os.getenv("COINGLASS_API_KEY") or os.getenv("COINGLASS_SECRET"))
            
            if has_coinglass:
                # Используем Coinglass API если доступен
                try:
                    from ...infrastructure.coinglass import fetch_max_pain
                    from ...visual.options_chart import render_max_pain_chart
                    
                    res = fetch_max_pain(symbol)
                    png = render_max_pain_chart(res)
                    
                    text = (
                        f"*{symbol} options max pain*\n" +
                        "\n".join([f"• `{p.date}`  *{p.max_pain:,.0f}*  (${p.notional:,.0f})"
                                   for p in res.points[:10]])
                    )
                    
                    from telegram import InputFile
                    photo = InputFile(png, filename=f"{symbol}_options.png")
                    await context.bot.send_photo(
                        chat_id=chat_id,
                        photo=photo,
                        caption=text,
                        parse_mode=ParseMode.MARKDOWN,
                        reply_markup=build_kb("main")
                    )
                    return
                except Exception as e:
                    logger.warning("Coinglass API failed, falling back to free sources: %s", e)
                    # Fallback на бесплатные источники
            
            # Используем бесплатные источники (Deribit + Binance Options)
            await self.handle_options_free(update, context, symbol)
            
        except Exception as e:
            logger.exception("_send_options failed for %s: %s", symbol, e)
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=f"Не удалось получить данные опционов {symbol}.",
                reply_markup=build_kb("main")
            )
    
    async def handle_options_free(self, update: Update, context: ContextTypes.DEFAULT_TYPE, symbol: str):
        """Обработать команду /options_*_free (бесплатные опционы)."""
        try:
            from ...infrastructure.deribit import build_series
            from ...visual.options_chart_free import render_free_series
            from telegram import InputFile
            
            pts = build_series(symbol, max_expiries=8)
            
            bmap: dict[str, float] = {}
            try:
                from ...infrastructure.binance_options import notional_by_expiry
                for p in pts:
                    y, m, d = p["date"].split("-")
                    yymmdd = f"{y[2:]}{m}{d}"
                    v = notional_by_expiry(symbol, yymmdd)
                    if v:
                        bmap[yymmdd] = float(v)
            except Exception:
                bmap = {}
            
            png = render_free_series(pts, bmap if bmap else None)
            
            lines, total_sum = [], 0.0
            for p in pts[:10]:
                yymmdd = p["date"].replace("-", "")[2:]
                d_usd = float(p.get("deribit_notional_usd", 0.0))
                b_usd = float(bmap.get(yymmdd, 0.0))
                s_usd = d_usd + b_usd
                total_sum += s_usd
                lines.append(f"• `{p['date']}`  MP=*{p['max_pain']:,.0f}*  Σ≈${s_usd:,.0f}")
            
            text = f"*{symbol} options (free)*\nΣ total≈${total_sum:,.0f}\n" + "\n".join(lines)
            
            chat_id = update.effective_chat.id
            if png:
                photo = InputFile(png, filename=f"{symbol}_options_free.png")
                await context.bot.send_photo(
                    chat_id=chat_id,
                    photo=photo,
                    caption=text,
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=build_kb("main")
                )
            else:
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=text,
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=build_kb("main")
                )
        except Exception:
            logger.exception("handle_options_free failed for %s", symbol)

