# app/presentation/handlers/analytics_handler.py
"""
Handler for analytics commands (corr, beta, vol, funding, basis).
"""

from telegram import Update, InputFile, InputMediaPhoto
from telegram.ext import ContextTypes
from telegram.constants import ParseMode
from .base_handler import BaseHandler
from ...infrastructure.ui_keyboards import DEFAULT_TF, build_kb
import logging
import time

logger = logging.getLogger("alt_forecast.handlers.analytics")


class AnalyticsHandler(BaseHandler):
    """Обработчик команд аналитики."""
    
    def _resolve_tf(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> str:
        """Определить таймфрейм из контекста."""
        args = context.args or []
        if args and args[0] in ("15m", "1h", "4h", "1d", "24h"):
            return args[0] if args[0] != "24h" else "1d"
        return context.user_data.get('tf', DEFAULT_TF)
    
    def _resolve_symbol(self, update: Update, context: ContextTypes.DEFAULT_TYPE, default: str = "BTC") -> str:
        """Определить символ из контекста."""
        args = context.args or []
        if args and len(args) > 0:
            return args[0].upper()
        return context.user_data.get('symbol', default)
    
    async def handle_corr(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработать команду /corr."""
        try:
            tf = self._resolve_tf(update, context)
            chat_id = update.effective_chat.id
            # Делегируем старому методу пока
            # TODO: Вынести логику в сервис
            await self._send_corr(chat_id, tf, context)
        except Exception:
            logger.exception("handle_corr failed")
    
    async def handle_beta(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработать команду /beta."""
        try:
            tf = self._resolve_tf(update, context)
            chat_id = update.effective_chat.id
            # Делегируем старому методу пока
            await self._send_beta(chat_id, tf, context)
        except Exception:
            logger.exception("handle_beta failed")
    
    async def handle_vol(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработать команду /vol."""
        try:
            tf = self._resolve_tf(update, context)
            symbol = self._resolve_symbol(update, context, "BTC")
            chat_id = update.effective_chat.id
            await self._send_vol(chat_id, tf, symbol, context)
        except Exception:
            logger.exception("handle_vol failed")
    
    async def handle_funding(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработать команду /funding."""
        try:
            symbol = self._resolve_symbol(update, context, "BTC")
            chat_id = update.effective_chat.id
            await self._send_funding(chat_id, symbol)
        except Exception:
            logger.exception("handle_funding failed")
    
    async def handle_basis(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработать команду /basis."""
        try:
            symbol = self._resolve_symbol(update, context, "BTC")
            chat_id = update.effective_chat.id
            await self._send_basis(chat_id, symbol)
        except Exception:
            logger.exception("handle_basis failed")
    
    # Временные методы-заглушки, которые будут делегировать старому коду
    # TODO: Вынести логику в сервисы
    async def _send_corr(self, chat_id: int, tf: str, context):
        """Временная заглушка."""
        pass
    
    async def _send_beta(self, chat_id: int, tf: str, context):
        """Временная заглушка."""
        pass
    
    async def _send_vol(self, chat_id: int, tf: str, symbol: str, context):
        """Временная заглушка."""
        pass
    
    async def _send_funding(self, chat_id: int, symbol: str):
        """Временная заглушка."""
        pass
    
    async def _send_basis(self, chat_id: int, symbol: str):
        """Временная заглушка."""
        pass
    
    async def handle_liqs(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработать команду /liqs или кнопку из меню."""
        try:
            q = update.callback_query
            if q:
                await q.answer()
                # из меню всегда по умолчанию BTC, потом можно добавить выбор
                base = "BTC"
            else:
                text = (update.effective_message.text or "").strip()
                parts = text.split()
                base = parts[1].upper() if len(parts) > 1 else "BTC"
            
            chat_id = update.effective_chat.id
            await self._send_liqs(chat_id, base, context)
        except Exception:
            logger.exception("handle_liqs failed")
    
    async def handle_levels(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработать команду /levels."""
        try:
            tf = self._resolve_tf(update, context)
            symbol = self._resolve_symbol(update, context, "BTC")
            chat_id = update.effective_chat.id
            await self._send_levels(chat_id, symbol, tf, context)
        except Exception:
            logger.exception("handle_levels failed")
    
    async def handle_risk_now(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработать команду /risk_now."""
        try:
            # Обрабатываем callback query если есть
            q = update.callback_query
            if q:
                await q.answer()
            
            chat_id = update.effective_chat.id
            await self._send_risk_now(chat_id, update, context)
        except Exception:
            logger.exception("handle_risk_now failed")
    
    async def handle_backtest(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработать команду /bt (backtest)."""
        try:
            parts = update.effective_message.text.split()
            tf = self._resolve_tf(update, context)
            symbol = self._resolve_symbol(update, context, "BTC")
            
            # Определяем стратегию
            strat = "rsi"
            if len(parts) > 1:
                strat = parts[1].lower()
            
            if strat.lower() != "rsi":
                await update.effective_message.reply_text("Сейчас доступно: /bt rsi SYMBOL [tf]")
                return
            
            chat_id = update.effective_chat.id
            await self._send_bt_rsi(chat_id, symbol, tf, context)
        except Exception:
            logger.exception("handle_backtest failed")
    
    async def handle_breadth(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработать команду /breadth."""
        try:
            tf = self._resolve_tf(update, context)
            chat_id = update.effective_chat.id
            await self._send_breadth(chat_id, tf, context)
        except Exception:
            logger.exception("handle_breadth failed")
    
    async def handle_scan_divs(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработать команду /scan_divs."""
        try:
            q = update.callback_query
            ud = context.user_data
            
            # Определяем ТФ из callback query или используем сохраненный
            tf = ud.get("tf") or "1h"
            page = 0
            
            # Если это callback query, извлекаем параметры
            if q and q.data:
                parts = q.data.split(":")
                if len(parts) >= 3:
                    if parts[2] == "list" and len(parts) >= 5:
                        tf = parts[3] or tf
                        try:
                            page = max(0, int(parts[4]))
                        except (ValueError, TypeError):
                            page = 0
                    else:
                        tf = parts[2] if len(parts) > 2 else tf
            
            ud["tf"] = tf
            text, kb = self._render_scan_divs_text(tf, page)
            
            # Если это callback query, отвечаем на него и редактируем сообщение
            if q:
                await q.answer()
                try:
                    from telegram.constants import ParseMode
                    await q.edit_message_text(
                        text=text,
                        reply_markup=kb,
                        parse_mode=ParseMode.HTML,
                        disable_web_page_preview=True
                    )
                except Exception:
                    # Если не удалось отредактировать, отправляем новое сообщение
                    await q.message.reply_text(
                        text=text,
                        reply_markup=kb,
                        parse_mode=ParseMode.HTML,
                        disable_web_page_preview=True
                    )
            else:
                # Обычное сообщение
                from telegram.constants import ParseMode
                await update.effective_message.reply_text(
                    text=text,
                    reply_markup=kb,
                    parse_mode=ParseMode.HTML,
                    disable_web_page_preview=True
                )
        except Exception:
            logger.exception("handle_scan_divs failed")
    
    # Методы, которые делегируют старому коду
    async def _send_liqs(self, chat_id: int, base: str, context: ContextTypes.DEFAULT_TYPE):
        """Отправить данные по ликвидациям с картой ликвидаций."""
        try:
            from ...infrastructure.free_market_data import (
                get_liquidation_levels_aggregated,
                aggregate_liquidation_levels,
                estimate_liquidation_levels_from_positions
            )
            from ...visual.liquidation_map import render_liquidation_map, analyze_liquidation_zones
            from telegram import InputFile
            
            # Получаем текущую цену из БД
            current_price = None
            try:
                rows = self.db.last_n(base, "1h", 1)
                if rows:
                    current_price = float(rows[0][4])  # close
            except Exception:
                # Fallback на получение цены из API
                try:
                    from ...infrastructure.market_data import binance_spot_price
                    symbol_usdt = f"{base}USDT"
                    current_price = binance_spot_price(symbol_usdt)
                except Exception:
                    pass
            
            # Получаем уровни ликвидации с нескольких бирж и агрегируем
            levels_by_exchange = get_liquidation_levels_aggregated(base, exchanges=["bybit", "okx"], hours=48)
            levels = aggregate_liquidation_levels(levels_by_exchange)
            
            # Если данных все еще мало, добавляем оценку на основе позиций
            if len(levels) < 5 and current_price:
                estimated_levels = estimate_liquidation_levels_from_positions(base, current_price)
                levels.extend(estimated_levels)
            
            # Если данных совсем нет, создаем базовую карту на основе текущей цены
            if not levels and current_price:
                # Создаем примерные уровни вокруг текущей цены
                price_step = current_price * 0.01  # 1% шаг
                for i in range(-10, 11):
                    if i == 0:
                        continue
                    price = current_price + (price_step * i)
                    side = "long" if i < 0 else "short"
                    # Примерная оценка объема на основе расстояния от цены
                    estimated_value = abs(i) * 10000  # Чем дальше, тем больше потенциальный объем
                    from ...infrastructure.free_market_data import LiquidationLevel
                    levels.append(LiquidationLevel(
                        price=price,
                        usd_value=estimated_value,
                        side=side,
                        exchange="estimated"
                    ))
            
            # Создаем визуализацию
            if levels:
                png = render_liquidation_map(base, levels, current_price)
                
                # Создаем текстовое описание
                description = analyze_liquidation_zones(levels, current_price)
                
                # Отправляем график с описанием
                photo = InputFile(png, filename=f"liquidation_map_{base}.png")
                await context.bot.send_photo(
                    chat_id=chat_id,
                    photo=photo,
                    caption=description,
                    parse_mode=ParseMode.HTML
                )
            
            # Также отправляем краткую статистику из старого метода
            from ...infrastructure.liquidations import bybit_liqs_any
            long_usd, short_usd, cnt, sym, ok = bybit_liqs_any(base, minutes=120, limit=200)
            if ok and (long_usd + short_usd) > 0:
                text = (
                    f"<b>Последние ликвидации {sym}</b>\n"
                    f"• Long: ${long_usd:,.0f}\n"
                    f"• Short: ${short_usd:,.0f}\n"
                    f"• Сделок: {cnt:,}"
                ).replace(",", " ")
                await context.bot.send_message(chat_id=chat_id, text=text, parse_mode=ParseMode.HTML)
            elif not levels:
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=f"По <b>{base}</b> недостаточно данных для построения карты ликвидаций.",
                    parse_mode=ParseMode.HTML
                )
        except Exception as e:
            logger.exception("_send_liqs failed: %s", e)
            # Fallback на старый метод
            try:
                from ...infrastructure.liquidations import bybit_liqs_any
                long_usd, short_usd, cnt, sym, ok = bybit_liqs_any(base, minutes=120, limit=200)
                if ok and (long_usd + short_usd) > 0:
                    text = (
                        f"<b>Ликвидации {sym}</b>\n"
                        f"• Long: ${long_usd:,.0f}\n"
                        f"• Short: ${short_usd:,.0f}\n"
                        f"• Сделок: {cnt:,}"
                    ).replace(",", " ")
                    await context.bot.send_message(chat_id=chat_id, text=text, parse_mode=ParseMode.HTML)
                else:
                    await context.bot.send_message(
                        chat_id=chat_id,
                        text=f"По <b>{base}</b> нет данных о ликвидациях.",
                        parse_mode=ParseMode.HTML
                    )
            except Exception as e2:
                logger.exception("_send_liqs fallback also failed: %s", e2)
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=f"Ошибка получения ликвидаций для <b>{base}</b>: {type(e).__name__}",
                    parse_mode=ParseMode.HTML
                )
    
    async def _send_levels(self, chat_id: int, symbol: str, tf: str, context):
        """Отправить данные по уровням."""
        try:
            from ...usecases.analytics import _ohlcv_df, nearest_sr, recent_breakouts
            from telegram.constants import ParseMode
            
            df = _ohlcv_df(self.db, symbol, tf, 800)
            if df.empty:
                await context.bot.send_message(chat_id=chat_id, text="Нет данных.")
                return
            
            last, above, below = nearest_sr(df, k=3)
            bo_up, bo_dn = recent_breakouts(df, lookback=50)
            text = (f"*Levels {symbol} ({tf})*\n"
                    f"Last close: {last:.2f}\n"
                    f"Above: {', '.join(f'{x:.2f}' for x in above) if above else '—'}\n"
                    f"Below: {', '.join(f'{x:.2f}' for x in below) if below else '—'}\n"
                    f"Breakout: {'↑' if bo_up else '—'} {'↓' if bo_dn else '—'}")
            from ...visual.levels_card import render_levels_card
            png = render_levels_card(symbol, tf, last, above, below, bo_up, bo_dn)
            await context.bot.send_photo(chat_id=chat_id, photo=png, caption=text, parse_mode=ParseMode.MARKDOWN)
        except Exception:
            logger.exception("_send_levels failed")
    
    async def _send_risk_now(self, chat_id: int, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Отправить данные по risk_now."""
        try:
            from ...usecases.generate_report import METRICS
            from ...lib.series import get_closes
            from ...domain.services import trend_arrow_metric, indicator_divergences, risk_score
            
            tf = "1h"
            arrows = {}
            for m in METRICS:
                closes = get_closes(self.db, m, tf, 80)
                arrows[m] = trend_arrow_metric(m, tf, closes)
            
            all_divs = []
            for m in METRICS:
                rows = self.db.last_n(m, tf, 320)
                if not rows:
                    continue
                closes = [r[4] for r in rows]
                vols = [r[5] for r in rows] if len(rows[0]) > 5 else None
                all_divs.extend(indicator_divergences(m, tf, closes, vols))
            
            # TODO: Добавить pair_divergences когда будет доступ к _pair_series_sec
            # series = self._pair_series_sec(tf, 320)
            # all_divs.extend(pair_divergences(tf, series))
            
            score, label = risk_score(tf, arrows, all_divs)
            from ...visual.risk_card import render_risk_card
            
            png = render_risk_card(tf, score, label)
            cap = f"<b>🧭 Risk Now ({tf})</b>\n\n{label} (score {score})\n\n<i>Сводный индикатор risk-on/off на основе тренда и дивергенций</i>"
            
            photo = InputFile(png, filename=f"risk_{tf}.png")
            
            # Если это callback query, пытаемся отредактировать сообщение
            q = update.callback_query
            if q:
                try:
                    await q.edit_message_media(
                        media=InputMediaPhoto(photo, caption=cap, parse_mode=ParseMode.HTML),
                        reply_markup=build_kb("main")
                    )
                    return
                except Exception as e:
                    logger.debug("Could not edit message for risk_now, sending new: %s", e)
            
            await context.bot.send_photo(
                chat_id=chat_id,
                photo=photo,
                caption=cap,
                parse_mode=ParseMode.HTML,
                reply_markup=build_kb("main")
            )
        except Exception:
            logger.exception("_send_risk_now failed")
    
    async def _send_bt_rsi(self, chat_id: int, symbol: str, tf: str, context: ContextTypes.DEFAULT_TYPE):
        """Отправить данные по backtest RSI."""
        try:
            from ...usecases.analytics import backtest_rsi
            from telegram.constants import ParseMode
            
            res = backtest_rsi(self.db, symbol, tf)
            text = (f"*BT rsi {symbol} {tf}*\n"
                   f"Win rate: {res.get('win_rate', 0):.2%}\n"
                   f"Total trades: {res.get('total_trades', 0)}\n"
                   f"Avg return: {res.get('avg_return', 0):.2%}\n"
                   f"Sharpe: {res.get('sharpe', 0):.2f}\n\n"
                   "_Зачем_: быстрая прикидка работоспособности простого правила входа/выхода (не финсовет).")
            await context.bot.send_message(
                chat_id=chat_id,
                text=text,
                parse_mode=ParseMode.MARKDOWN
            )
        except Exception:
            logger.exception("_send_bt_rsi failed")
    
    async def _send_breadth(self, chat_id: int, tf: str, context: ContextTypes.DEFAULT_TYPE):
        """Отправить данные по breadth."""
        try:
            from ...usecases.generate_report import METRICS
            from ...usecases.analytics import breadth
            from ...visual.breadth_bar import render_breadth_bar
            from telegram.constants import ParseMode
            
            b = breadth(self.db, METRICS, tf)
            png = render_breadth_bar(b["above_ma50"], b["above_ma200"], b["total"], title=f"Breadth ({tf})")
            cap = (f"*Breadth ({tf})*\n"
                   f">MA50: {b['above_ma50']}/{b['total']} ({b['pct_ma50']}%)\n"
                   f">MA200: {b['above_ma200']}/{b['total']} ({b['pct_ma200']}%)\n"
                   "_Зачем_: оценивает ширину рынка — долю метрик в ап-тренде; полезно для понимания общего фона.")
            await context.bot.send_photo(chat_id=chat_id, photo=png, caption=cap, parse_mode=ParseMode.MARKDOWN)
        except Exception:
            logger.exception("_send_breadth failed")
    
    def _render_scan_divs_text(self, tf: str, page: int = 0, page_size: int = 12):
        """Рендер текста дивергенций."""
        try:
            from ...infrastructure.ui_keyboards import build_kb
            
            rows_all = []
            for m in ("BTC", "ETHBTC", "USDT.D", "BTC.D", "TOTAL2", "TOTAL3"):
                try:
                    rows = self.db.list_open_divs(m, tf)
                except Exception:
                    try:
                        tmp = self.db.list_active_divs(m, tf)
                        rows = [(*r, "active", None) for r in tmp]
                    except Exception:
                        rows = []
                for (_id, ind, side, _impl, rts, rval, status, grade) in rows:
                    rows_all.append((int(rts or 0), m, ind, side, status, grade, rts, rval))
            
            rows_all.sort(key=lambda x: x[0], reverse=True)
            total = len(rows_all)
            start = max(0, page * page_size)
            page_rows = rows_all[start:start + page_size]
            
            head = f"<b>Дивергенции • {tf}</b>\nПоказано {start + 1 if total else 0}–{start + len(page_rows)} из {total}"
            lines = [head]
            for (_key, m, ind, side, status, grade, rts, rval) in page_rows:
                lines.append("• " + self._fmt_div_row(m, ind, side, status, grade, rts, rval))
            
            text = "\n".join(lines) if page_rows else f"<b>Дивергенции • {tf}</b>\nПока сигналов нет."
            kb = self._kb_scan_divs_list(tf, page)
            return text, kb
        except Exception:
            logger.exception("_render_scan_divs_text failed")
            return "", None
    
    def _fmt_div_row(self, m: str, ind: str, side: str, status: str, grade, rts, rval):
        """Форматирование строки дивергенции."""
        try:
            status_emoji = {"active": "🟢", "closed": "⚪"}.get(status, "⚪")
            grade_str = f" ({grade})" if grade else ""
            return f"{status_emoji} {m} {ind} {side}{grade_str}"
        except Exception:
            return f"{m} {ind} {side}"
    
    def _kb_scan_divs_list(self, tf: str, page: int):
        """Клавиатура для списка дивергенций."""
        from ...infrastructure.ui_keyboards import build_kb
        # TODO: Реализовать правильную клавиатуру с пагинацией
        return build_kb("more")
    
    async def handle_whale_orders(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработать команду /whale_orders или callback ui:whale_orders:SYMBOL."""
        try:
            # Проверяем, это callback query или команда
            q = update.callback_query
            if q:
                await q.answer()
                # Извлекаем символ из callback data (ui:whale_orders:BTC)
                parts = q.data.split(":")
                symbol = parts[2].upper() if len(parts) > 2 else "BTC"
            else:
                parts = update.effective_message.text.split() if update.effective_message else []
                symbol = parts[1].upper() if len(parts) > 1 else "BTC"
            
            if symbol not in ("BTC", "ETH"):
                symbol = "BTC"  # По умолчанию BTC
            
            chat_id = update.effective_chat.id
            await self._send_whale_orders(chat_id, symbol, context)
        except Exception:
            logger.exception("handle_whale_orders failed")
    
    async def _send_whale_orders(self, chat_id: int, symbol: str, context: ContextTypes.DEFAULT_TYPE):
        """Отправить карту крупных ордеров китов."""
        try:
            from ...infrastructure.free_market_data import (
                get_whale_orders_aggregated,
                analyze_whale_order_distribution
            )
            from ...visual.whale_orders_map import render_whale_orders_map, format_whale_orders_description
            from ...visual.chart_renderer import get_ohlcv_data
            from telegram import InputFile
            
            # Получаем текущую цену для фильтрации ордеров
            current_price = None
            try:
                rows = self.db.last_n(symbol, "1h", 1)
                if rows:
                    current_price = float(rows[0][4])  # close
            except Exception:
                pass
            
            # Получаем данные о крупных ордерах с нескольких бирж
            # Используем все доступные биржи: Binance, Bybit, OKX, Coinbase
            orders_by_exchange = get_whale_orders_aggregated(
                symbol,
                exchanges=["binance", "bybit", "okx", "coinbase"],  # Все доступные биржи
                min_amount_usd=None,
                current_price=current_price
            )
            
            # Объединяем все ордера в один список
            all_orders = []
            for exchange_orders in orders_by_exchange.values():
                all_orders.extend(exchange_orders)
            
            # Сортируем по размеру
            orders = sorted(all_orders, key=lambda x: x.amount, reverse=True)
            
            # Получаем OHLCV данные для графика
            ohlcv_data = None
            try:
                ohlcv_data = get_ohlcv_data(self.db, symbol, "15m", n_bars=200)
            except Exception:
                pass
            
            # Создаем визуализацию
            if orders:
                png = render_whale_orders_map(symbol, orders, ohlcv_data, timeframe="15m")
                
                # Создаем текстовое описание
                description = format_whale_orders_description(orders, symbol)
                
                # Отправляем график с описанием
                photo = InputFile(png, filename=f"whale_orders_{symbol}.png")
                await context.bot.send_photo(
                    chat_id=chat_id,
                    photo=photo,
                    caption=description,
                    parse_mode=ParseMode.HTML
                )
            else:
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=f"Не найдено крупных ордеров для <b>{symbol}</b> (минимум $5M).",
                    parse_mode=ParseMode.HTML
                )
        except Exception as e:
            logger.exception("_send_whale_orders failed: %s", e)
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"Ошибка получения данных о крупных ордерах для <b>{symbol}</b>: {type(e).__name__}",
                parse_mode=ParseMode.HTML
            )
    
    async def handle_whale_activity(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработать команду /whale_activity или callback ui:whale_activity:SYMBOL:TF."""
        try:
            # Проверяем, это callback query или команда
            q = update.callback_query
            if q:
                await q.answer()
                # Извлекаем символ и таймфрейм из callback data
                # Формат: ui:whale_activity:BTC:1h
                parts = q.data.split(":")
                
                if len(parts) >= 4 and parts[1] == "whale_activity":
                    # ui:whale_activity:BTC:1h
                    symbol = parts[2].upper() if len(parts) > 2 else "BTC"
                    timeframe = parts[3] if len(parts) > 3 else "1h"
                else:
                    # Старый формат ui:whale_activity:1h (для обратной совместимости)
                    symbol = "BTC"
                    timeframe = parts[2] if len(parts) > 2 else "1h"
            else:
                parts = update.effective_message.text.split() if update.effective_message else []
                symbol = parts[1].upper() if len(parts) > 1 else "BTC"
                timeframe = parts[2] if len(parts) > 2 else "1h"
            
            if timeframe not in ("1h", "4h", "24h"):
                timeframe = "1h"
            
            if symbol not in ("BTC", "ETH"):
                symbol = "BTC"
            
            chat_id = update.effective_chat.id
            await self._send_whale_activity(chat_id, symbol, timeframe, context)
        except Exception:
            logger.exception("handle_whale_activity failed")
    
    async def _send_whale_activity(self, chat_id: int, symbol: str, timeframe: str, context: ContextTypes.DEFAULT_TYPE):
        """Отправить активность китов на основе крупных сделок."""
        try:
            from ...infrastructure.free_market_data import get_large_trades_aggregated
            from datetime import datetime, timezone, timedelta
            from telegram import InputFile
            
            # Получаем крупные сделки с нескольких бирж (используем кэш из БД если доступен)
            trades_by_exchange = get_large_trades_aggregated(
                symbol,
                exchanges=["binance", "okx", "bybit", "gate"],  # Все доступные биржи
                timeframe=timeframe,
                min_usd=100_000.0,
                db=self.db  # Передаем БД для использования кэша
            )
            
            # Объединяем все сделки
            all_trades = []
            for exchange_trades in trades_by_exchange.values():
                all_trades.extend(exchange_trades)
            
            if not all_trades:
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=f"Не найдено крупных сделок для <b>{symbol}</b> за {timeframe}.",
                    parse_mode=ParseMode.HTML
                )
                return
            
            # Сортируем по размеру
            recent_trades = sorted(all_trades, key=lambda x: x.usd_value, reverse=True)
            
            if not recent_trades:
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=f"Не найдено крупных сделок для <b>{symbol}</b> за последние {timeframe}.",
                    parse_mode=ParseMode.HTML
                )
                return
            
            # Группируем сделки и создаем текстовое описание
            buy_trades = [t for t in recent_trades if t.side == "buy"]
            sell_trades = [t for t in recent_trades if t.side == "sell"]
            
            total_buy = sum(t.usd_value for t in buy_trades)
            total_sell = sum(t.usd_value for t in sell_trades)
            
            # Статистика по биржам
            exchange_stats: Dict[str, Dict[str, float]] = {}
            for trade in recent_trades:
                ex = trade.exchange
                if ex not in exchange_stats:
                    exchange_stats[ex] = {"count": 0, "volume": 0.0, "buy": 0.0, "sell": 0.0}
                exchange_stats[ex]["count"] += 1
                exchange_stats[ex]["volume"] += trade.usd_value
                if trade.side == "buy":
                    exchange_stats[ex]["buy"] += trade.usd_value
                else:
                    exchange_stats[ex]["sell"] += trade.usd_value
            
            # Топ сделки
            top_trades = recent_trades[:10]
            
            lines = []
            lines.append(f"🐋 <b>Активность китов - {symbol} ({timeframe})</b>\n")
            lines.append(f"📊 <b>Статистика:</b>")
            lines.append(f"   Всего крупных сделок: {len(recent_trades)}")
            lines.append(f"   Buy сделок: {len(buy_trades)} (${total_buy/1_000_000:.2f}M)")
            lines.append(f"   Sell сделок: {len(sell_trades)} (${total_sell/1_000_000:.2f}M)")
            lines.append(f"   Общий объем: ${(total_buy + total_sell)/1_000_000:.2f}M")
            
            # Статистика по биржам
            if exchange_stats:
                lines.append(f"\n🏦 <b>По биржам:</b>")
                for ex, stats in sorted(exchange_stats.items(), key=lambda x: x[1]["volume"], reverse=True):
                    ex_name = ex.upper()
                    lines.append(
                        f"   {ex_name}: {int(stats['count'])} сделок "
                        f"(${stats['volume']/1_000_000:.2f}M) - "
                        f"Buy: ${stats['buy']/1_000_000:.2f}M, "
                        f"Sell: ${stats['sell']/1_000_000:.2f}M"
                    )
            
            if top_trades:
                lines.append(f"\n🏆 <b>Топ сделки:</b>")
                for i, trade in enumerate(top_trades[:10], 1):
                    side_emoji = "🟢" if trade.side == "buy" else "🔴"
                    trade_time = datetime.fromtimestamp(trade.timestamp / 1000, tz=timezone.utc)
                    time_str = trade_time.strftime("%H:%M:%S")
                    ex_name = trade.exchange.upper()
                    lines.append(
                        f"   {i}. {side_emoji} ${trade.usd_value/1_000_000:.2f}M @ ${trade.price:,.2f} "
                        f"({ex_name}, {time_str})"
                    )
            
            description = "\n".join(lines)
            
            await context.bot.send_message(
                chat_id=chat_id,
                text=description,
                parse_mode=ParseMode.HTML
            )
        except Exception as e:
            logger.exception("_send_whale_activity failed: %s", e)
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"Ошибка получения данных об активности китов для <b>{symbol}</b> ({timeframe}): {type(e).__name__}",
                parse_mode=ParseMode.HTML
            )
    
    async def handle_heatmap(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработать команду /heatmap или callback ui:heatmap:SYMBOL."""
        try:
            # Проверяем, это callback query или команда
            q = update.callback_query
            if q:
                await q.answer()
                # Извлекаем символ из callback data (ui:heatmap:BTC)
                parts = q.data.split(":")
                symbol = parts[2].upper() if len(parts) > 2 else "BTC"
            else:
                parts = update.effective_message.text.split() if update.effective_message else []
                symbol = parts[1].upper() if len(parts) > 1 else "BTC"
            
            if symbol not in ("BTC", "ETH", "SOL", "BNB", "XRP"):
                symbol = "BTC"  # По умолчанию BTC
            
            chat_id = update.effective_chat.id
            await self._send_liquidity_intelligence(chat_id, symbol, context)
        except Exception:
            logger.exception("handle_heatmap failed")
    
    async def _send_liquidity_intelligence(self, chat_id: int, symbol: str, context: ContextTypes.DEFAULT_TYPE):
        """Отправить Liquidity Intelligence (изображение + отчет)."""
        try:
            from ...liquidity_map.application.generate_liquidity_map import generate_liquidity_map
            from ...liquidity_map.application.generate_liquidity_report import generate_liquidity_report
            from ...liquidity_map.application.generate_liquidity_report_compact import generate_liquidity_report_compact
            from ...liquidity_map.services.report_builder import build_short_caption
            from ...liquidity_map.services.snapshot_builder import build_tf_snapshot
            from telegram import InputFile
            
            # Генерируем изображение
            png = generate_liquidity_map(symbol, self.db)
            
            # Создаем короткий caption для изображения
            timeframes = ["5m", "15m", "1h", "4h", "1d"]
            snapshots = [build_tf_snapshot(symbol, tf, self.db) for tf in timeframes]
            short_caption = build_short_caption(snapshots, symbol)
            
            # Отправляем изображение с коротким caption
            photo = InputFile(png, filename=f"liquidity_map_{symbol}.png")
            
            await context.bot.send_photo(
                chat_id=chat_id,
                photo=photo,
                caption=short_caption,
                parse_mode=ParseMode.HTML
            )
            
            # Отправляем компактный отчет (1-2 экрана)
            compact_report = generate_liquidity_report_compact(symbol, self.db)
            await context.bot.send_message(
                chat_id=chat_id,
                text=compact_report,
                parse_mode=ParseMode.HTML
            )
            
            # Опционально: отправляем полный отчет отдельным сообщением
            # (можно закомментировать, если компактного достаточно)
            # report_text = generate_liquidity_report(symbol, self.db)
            # max_length = 4000
            # if len(report_text) > max_length:
            #     parts = [report_text[i:i+max_length] for i in range(0, len(report_text), max_length)]
            #     for part in parts:
            #         await context.bot.send_message(
            #             chat_id=chat_id,
            #             text=part,
            #             parse_mode=ParseMode.HTML
            #         )
            # else:
            #     await context.bot.send_message(
            #         chat_id=chat_id,
            #         text=report_text,
            #         parse_mode=ParseMode.HTML
            #     )
        except Exception as e:
            logger.exception("_send_liquidity_intelligence failed: %s", e)
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"Ошибка создания Liquidity Intelligence для <b>{symbol}</b>: {type(e).__name__}\n\n{str(e)}",
                parse_mode=ParseMode.HTML
            )

