# app/presentation/handlers/twap_handler.py
"""
Handler for TWAP command.
"""

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from telegram.constants import ParseMode
from .base_handler import BaseHandler
from ...infrastructure.ui_keyboards import build_kb
from datetime import datetime
import logging

logger = logging.getLogger("alt_forecast.handlers.twap")


class TWAPHandler(BaseHandler):
    """Обработчик команды /twap."""
    
    def __init__(self, db, services: dict):
        super().__init__(db, services)
        self.twap_service = services.get("twap_service")
        self.twap_detector_service = services.get("twap_detector_service")
        self.supported_symbols = ["BTC", "ETH", "SOL", "XRP"]
    
    def _build_symbol_keyboard(self, current_symbol: str = None, current_period: str = "1h") -> InlineKeyboardMarkup:
        """Построить клавиатуру с кнопками для выбора символа и периода."""
        buttons = []
        row = []
        for symbol in self.supported_symbols:
            label = f"✅ {symbol}" if symbol == current_symbol else symbol
            row.append(InlineKeyboardButton(label, callback_data=f"twap:{symbol}:{current_period}"))
            if len(row) == 2:
                buttons.append(row)
                row = []
        if row:
            buttons.append(row)
        
        # Кнопки периода с отметкой текущего
        period_1h_label = "✅ 1 час" if current_period == "1h" else "⏱ 1 час"
        period_24h_label = "✅ 24 часа" if current_period == "24h" else "📅 24 часа"
        buttons.append([
            InlineKeyboardButton(period_1h_label, callback_data=f"twap:{current_symbol or 'BTC'}:1h"),
            InlineKeyboardButton(period_24h_label, callback_data=f"twap:{current_symbol or 'BTC'}:24h"),
        ])
        
        return InlineKeyboardMarkup(buttons)
    
    async def handle_twap(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработать команду /twap."""
        try:
            # Получаем аргументы команды (символ и период)
            args = context.args or []
            symbol = args[0].upper() if args and args[0].upper() in self.supported_symbols else "BTC"
            period_arg = args[1] if len(args) > 1 else "1h"
            
            # Определяем период (только 1 час или 24 часа)
            if period_arg == "24h" or period_arg == "24":
                window_minutes = 24 * 60
                period_hours = 24
                period_text = "24 часа"
            else:
                window_minutes = 60  # По умолчанию 1 час
                period_hours = 1
                period_text = "1 час"
            
            # Используем новый детектор TWAP-алгоритмов, если доступен
            if self.twap_detector_service:
                symbol_usdt = f"{symbol}USDT"
                report = self.twap_detector_service.get_twap_report(symbol_usdt, window_minutes)
                
                if report:
                    text = self._format_twap_report(report, symbol, period_text)
                    await update.effective_message.reply_text(
                        text,
                        parse_mode=ParseMode.HTML,
                        reply_markup=self._build_symbol_keyboard(symbol, period_arg),
                    )
                    return
            
            # Fallback: используем старый метод анализа
            pattern_data = self.twap_service.analyze_trading_patterns(symbol, period_hours)
            
            if not pattern_data:
                await update.effective_message.reply_text(
                    f"Не удалось получить данные для анализа TWAP по {symbol}.",
                    parse_mode=ParseMode.HTML,
                    reply_markup=self._build_symbol_keyboard(symbol, period_arg),
                )
                return
            
            # Формируем сообщение в стиле Coinact.gg
            lines = []
            
            # Заголовок
            period_text = "последний час" if period_hours == 1 else "последние сутки"
            lines.append(f"<b>📊 TWAP анализ — {symbol}</b>")
            lines.append(f"<i>Период: {period_text}</i>\n")
            
            # Основная информация
            minutes_ago = pattern_data["minutes_ago"]
            lines.append(
                f"Торговые паттерны обнаружены за последние <b>{minutes_ago:.1f} мин</b>.\n"
            )
            
            # Направление (покупка/продажа)
            direction = pattern_data["direction"]
            buy_vol = pattern_data["buy_volume"]
            sell_vol = pattern_data["sell_volume"]
            
            if direction == "buy":
                lines.append("🟢 <b>Доминируют покупки</b>")
                lines.append("   Автоматические ордера направлены на покупку.")
                market_phase = "Накопление / подготовка к росту"
            elif direction == "sell":
                lines.append("🔴 <b>Доминируют продажи</b>")
                lines.append("   Автоматические ордера направлены на продажу.")
                market_phase = "Распределение / фиксация прибыли"
            else:
                lines.append("⚪ <b>Нейтральный баланс</b>")
                lines.append("   Покупки и продажи сбалансированы.")
                market_phase = "Консолидация / флэт"
            
            lines.append("")
            
            # Объемы
            volume_per_hour = pattern_data["volume_per_hour"]
            
            # Форматируем объем
            if volume_per_hour >= 1_000_000:
                vol_text = f"${volume_per_hour / 1_000_000:.2f}M"
                volume_category = "высокий"
            elif volume_per_hour >= 500_000:
                vol_text = f"${volume_per_hour / 1_000_000:.2f}M"
                volume_category = "средний"
            elif volume_per_hour >= 1_000:
                vol_text = f"${volume_per_hour / 1_000:.2f}K"
                volume_category = "низкий"
            else:
                vol_text = f"${volume_per_hour:.2f}"
                volume_category = "очень низкий"
            
            lines.append(f"💵 <b>Объем автоматических ордеров:</b>")
            lines.append(f"   {vol_text} в час ({volume_category})")
            
            if buy_vol > 0 or sell_vol > 0:
                buy_pct = (buy_vol / (buy_vol + sell_vol) * 100) if (buy_vol + sell_vol) > 0 else 0
                sell_pct = (sell_vol / (buy_vol + sell_vol) * 100) if (buy_vol + sell_vol) > 0 else 0
                lines.append(f"   Покупки: {buy_pct:.1f}% | Продажи: {sell_pct:.1f}%")
            
            lines.append("")
            
            # TWAP и текущая цена
            twap = pattern_data["twap"]
            current = pattern_data["current_price"]
            deviation = pattern_data["deviation"]
            
            lines.append(f"💰 <b>Цена:</b> ${current:,.2f}")
            lines.append(f"📊 <b>TWAP:</b> ${twap:,.2f}")
            lines.append(f"📈 <b>Отклонение:</b> {deviation:+.2f}%")
            
            # Сила сигнала
            signal_strength = pattern_data["signal_strength"]
            strength_emoji = "🔥" if signal_strength == "strong" else "⚡" if signal_strength == "moderate" else "💨"
            strength_text = "сильный" if signal_strength == "strong" else "умеренный" if signal_strength == "moderate" else "слабый"
            lines.append(f"{strength_emoji} <b>Сила сигнала:</b> {strength_text}")
            
            lines.append("")
            
            # Интерпретация и рекомендации
            lines.append("🧩 <b>Интерпретация:</b>")
            interpretation = self._get_interpretation(direction, volume_per_hour, deviation, signal_strength, symbol)
            lines.append(interpretation)
            
            lines.append("")
            lines.append(f"📊 <b>Фаза рынка:</b> {market_phase}")
            
            # Рекомендации
            recommendation = self._get_recommendation(direction, volume_per_hour, deviation, signal_strength)
            if recommendation:
                lines.append("")
                lines.append(f"💡 <b>Рекомендация:</b> {recommendation}")
            
            text = "\n".join(lines)
            
            await update.effective_message.reply_text(
                text,
                parse_mode=ParseMode.HTML,
                reply_markup=self._build_symbol_keyboard(symbol, period_arg),
            )
        except Exception:
            logger.exception("handle_twap failed")
            await update.effective_message.reply_text(
                "Произошла ошибка при анализе TWAP.",
                parse_mode=ParseMode.HTML,
            )
    
    async def handle_twap_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработать callback от кнопок TWAP."""
        query = update.callback_query
        if not query:
            return
        
        # Пытаемся ответить на callback, но игнорируем ошибки для устаревших запросов
        try:
            await query.answer()
        except Exception as e:
            # Если запрос устарел, просто логируем и продолжаем
            if "too old" in str(e).lower() or "timeout" in str(e).lower():
                logger.debug(f"Callback query expired: {e}")
            else:
                logger.warning(f"Failed to answer callback query: {e}")
        
        try:
            # Парсим callback_data: twap:SYMBOL или twap:SYMBOL:PERIOD
            data_parts = query.data.split(":")
            symbol = data_parts[1] if len(data_parts) > 1 else "BTC"
            period = data_parts[2] if len(data_parts) > 2 else "1h"
            
            # Определяем период (только 1 час или 24 часа)
            if period == "24h":
                window_minutes = 24 * 60
                period_hours = 24
                period_text = "24 часа"
            else:
                window_minutes = 60  # По умолчанию 1 час
                period_hours = 1
                period_text = "1 час"
            
            # Используем новый детектор TWAP-алгоритмов, если доступен
            if self.twap_detector_service:
                symbol_usdt = f"{symbol}USDT"
                report = self.twap_detector_service.get_twap_report(symbol_usdt, window_minutes)
                
                if report:
                    text = self._format_twap_report(report, symbol, period_text)
                    await query.edit_message_text(
                        text,
                        parse_mode=ParseMode.HTML,
                        reply_markup=self._build_symbol_keyboard(symbol, period),
                    )
                    return
            
            # Fallback: используем старый метод анализа
            pattern_data = self.twap_service.analyze_trading_patterns(symbol, period_hours)
            
            if not pattern_data:
                await query.edit_message_text(
                    f"Не удалось получить данные для анализа TWAP по {symbol}.",
                    parse_mode=ParseMode.HTML,
                    reply_markup=self._build_symbol_keyboard(symbol, period),
                )
                return
            
            # Формируем сообщение (аналогично handle_twap)
            lines = []
            period_text = "последний час" if period_hours == 1 else "последние сутки"
            lines.append(f"<b>📊 TWAP анализ — {symbol}</b>")
            lines.append(f"<i>Период: {period_text}</i>\n")
            
            minutes_ago = pattern_data["minutes_ago"]
            lines.append(f"Торговые паттерны обнаружены за последние <b>{minutes_ago:.1f} мин</b>.\n")
            
            direction = pattern_data["direction"]
            buy_vol = pattern_data["buy_volume"]
            sell_vol = pattern_data["sell_volume"]
            
            if direction == "buy":
                lines.append("🟢 <b>Доминируют покупки</b>")
                lines.append("   Автоматические ордера направлены на покупку.")
                market_phase = "Накопление / подготовка к росту"
            elif direction == "sell":
                lines.append("🔴 <b>Доминируют продажи</b>")
                lines.append("   Автоматические ордера направлены на продажу.")
                market_phase = "Распределение / фиксация прибыли"
            else:
                lines.append("⚪ <b>Нейтральный баланс</b>")
                lines.append("   Покупки и продажи сбалансированы.")
                market_phase = "Консолидация / флэт"
            
            lines.append("")
            
            volume_per_hour = pattern_data["volume_per_hour"]
            
            # Форматируем объем
            if volume_per_hour >= 1_000_000:
                vol_text = f"${volume_per_hour / 1_000_000:.2f}M"
                volume_category = "высокий"
            elif volume_per_hour >= 500_000:
                vol_text = f"${volume_per_hour / 1_000_000:.2f}M"
                volume_category = "средний"
            elif volume_per_hour >= 1_000:
                vol_text = f"${volume_per_hour / 1_000:.2f}K"
                volume_category = "низкий"
            else:
                vol_text = f"${volume_per_hour:.2f}"
                volume_category = "очень низкий"
            
            lines.append(f"💵 <b>Объем автоматических ордеров:</b>")
            lines.append(f"   {vol_text} в час ({volume_category})")
            
            if buy_vol > 0 or sell_vol > 0:
                buy_pct = (buy_vol / (buy_vol + sell_vol) * 100) if (buy_vol + sell_vol) > 0 else 0
                sell_pct = (sell_vol / (buy_vol + sell_vol) * 100) if (buy_vol + sell_vol) > 0 else 0
                lines.append(f"   Покупки: {buy_pct:.1f}% | Продажи: {sell_pct:.1f}%")
            
            lines.append("")
            
            twap = pattern_data["twap"]
            current = pattern_data["current_price"]
            deviation = pattern_data["deviation"]
            
            lines.append(f"💰 <b>Цена:</b> ${current:,.2f}")
            lines.append(f"📊 <b>TWAP:</b> ${twap:,.2f}")
            lines.append(f"📈 <b>Отклонение:</b> {deviation:+.2f}%")
            
            signal_strength = pattern_data["signal_strength"]
            strength_emoji = "🔥" if signal_strength == "strong" else "⚡" if signal_strength == "moderate" else "💨"
            strength_text = "сильный" if signal_strength == "strong" else "умеренный" if signal_strength == "moderate" else "слабый"
            lines.append(f"{strength_emoji} <b>Сила сигнала:</b> {strength_text}")
            
            lines.append("")
            
            # Интерпретация и рекомендации
            lines.append("🧩 <b>Интерпретация:</b>")
            interpretation = self._get_interpretation(direction, volume_per_hour, deviation, signal_strength, symbol)
            lines.append(interpretation)
            
            lines.append("")
            lines.append(f"📊 <b>Фаза рынка:</b> {market_phase}")
            
            # Рекомендации
            recommendation = self._get_recommendation(direction, volume_per_hour, deviation, signal_strength)
            if recommendation:
                lines.append("")
                lines.append(f"💡 <b>Рекомендация:</b> {recommendation}")
            
            text = "\n".join(lines)
            
            await query.edit_message_text(
                text,
                parse_mode=ParseMode.HTML,
                reply_markup=self._build_symbol_keyboard(symbol, period),
            )
        except Exception as e:
            logger.exception("handle_twap_callback failed")
            # Пытаемся показать ошибку только если запрос еще валиден
            try:
                await query.answer("Произошла ошибка при обработке запроса.", show_alert=True)
            except Exception:
                # Игнорируем ошибки для устаревших запросов
                pass
    
    def _format_twap_report(self, report, symbol: str, period_text: str = None) -> str:
        """Форматировать отчёт TWAP-детектора в сообщение."""
        from ...domain.twap_detector import TWAPReport
        
        lines = []
        
        # Определяем текстовое представление периода
        if period_text is None:
            if report.window_minutes >= 1440:
                period_text = "24 часа"
            elif report.window_minutes >= 60:
                period_text = f"{report.window_minutes // 60} час"
            else:
                period_text = f"{report.window_minutes} мин"
        
        # Заголовок
        lines.append(f"<b>📊 TWAP анализ — {symbol}</b>")
        lines.append(f"<i>Период анализа: {period_text}</i>\n")
        
        # Основная информация
        lines.append(f"Торговые паттерны обнаружены за <b>{period_text}</b>.\n")
        
        # Направление и биржи
        if report.dominant_direction == "BUY":
            lines.append("🟢 <b>Доминируют покупки</b>")
            if report.buy_exchanges:
                lines.append(f"   Биржи: {', '.join(report.buy_exchanges)}")
        elif report.dominant_direction == "SELL":
            lines.append("🔴 <b>Доминируют продажи</b>")
            if report.sell_exchanges:
                lines.append(f"   Биржи: {', '.join(report.sell_exchanges)}")
        else:
            lines.append("⚪ <b>Нейтральный баланс</b>")
            if report.buy_exchanges or report.sell_exchanges:
                exchanges_str = ", ".join(report.buy_exchanges + report.sell_exchanges)
                lines.append(f"   Биржи: {exchanges_str}")
        
        lines.append("")
        
        # Объём алго-ордеров
        # Форматируем объём в зависимости от величины
        if report.total_algo_volume_usd >= 1_000_000:
            algo_vol_text = f"${report.total_algo_volume_usd / 1_000_000:.2f}M"
        elif report.total_algo_volume_usd >= 1_000:
            algo_vol_text = f"${report.total_algo_volume_usd / 1_000:.2f}K"
        else:
            algo_vol_text = f"${report.total_algo_volume_usd:.2f}"
        
        # Рассчитываем объём в час (экстраполируем из окна анализа)
        volume_per_hour = report.total_algo_volume_usd * (60 / report.window_minutes) if report.window_minutes > 0 else 0
        if volume_per_hour >= 1_000_000:
            vol_per_hour_text = f"${volume_per_hour / 1_000_000:.2f}M"
        elif volume_per_hour >= 1_000:
            vol_per_hour_text = f"${volume_per_hour / 1_000:.2f}K"
        else:
            vol_per_hour_text = f"${volume_per_hour:.2f}"
        
        # Форматируем чистый поток
        if abs(report.total_net_flow_usd) >= 1_000_000:
            net_flow_text = f"${abs(report.total_net_flow_usd) / 1_000_000:.2f}M"
        elif abs(report.total_net_flow_usd) >= 1_000:
            net_flow_text = f"${abs(report.total_net_flow_usd) / 1_000:.2f}K"
        else:
            net_flow_text = f"${abs(report.total_net_flow_usd):.2f}"
        
        # Рассчитываем общий объём всех сделок (не только алго)
        total_volume_all = sum(
            ex.buy_volume_usd + ex.sell_volume_usd 
            for ex in report.exchanges
        )
        
        if total_volume_all >= 1_000_000:
            total_vol_all_text = f"${total_volume_all / 1_000_000:.2f}M"
        elif total_volume_all >= 1_000:
            total_vol_all_text = f"${total_volume_all / 1_000:.2f}K"
        else:
            total_vol_all_text = f"${total_volume_all:.2f}"
        
        total_vol_per_hour = total_volume_all * (60 / report.window_minutes) if report.window_minutes > 0 else 0
        if total_vol_per_hour >= 1_000_000:
            total_vol_hour_text = f"${total_vol_per_hour / 1_000_000:.2f}M"
        elif total_vol_per_hour >= 1_000:
            total_vol_hour_text = f"${total_vol_per_hour / 1_000:.2f}K"
        else:
            total_vol_hour_text = f"${total_vol_per_hour:.2f}"
        
        # Форматируем период для отображения
        if report.window_minutes >= 1440:
            period_display = "24 часа"
        elif report.window_minutes >= 60:
            hours = report.window_minutes // 60
            period_display = f"{hours} час" if hours == 1 else f"{hours} часа"
        else:
            period_display = f"{report.window_minutes} мин"
        
        lines.append(f"💵 <b>Объём сделок:</b>")
        lines.append(f"   Всего: {total_vol_all_text} за {period_display}")
        if report.window_minutes < 60:
            # Показываем экстраполяцию на час только для периодов меньше часа
            lines.append(f"   (~{total_vol_hour_text}/ч)")
        if report.total_algo_volume_usd > 0:
            lines.append(f"   Алго-ордера: {algo_vol_text} за {period_display}")
            if report.window_minutes < 60:
                lines.append(f"   (~{vol_per_hour_text}/ч)")
        else:
            lines.append(f"   Алго-ордера: не обнаружены (algo_score &lt; 50%)")
        lines.append(f"   Чистый поток: {net_flow_text} ({report.dominant_direction})")
        
        lines.append("")
        
        # Детали по биржам
        if report.exchanges:
            lines.append("<b>📈 Детали по биржам:</b>")
            for exchange_analysis in report.exchanges:
                direction_emoji = "🟢" if exchange_analysis.direction == "BUY" else "🔴" if exchange_analysis.direction == "SELL" else "⚪"
                algo_score_pct = exchange_analysis.algo_score * 100
                
                # Форматируем объём по бирже
                if exchange_analysis.algo_volume_usd >= 1_000_000:
                    algo_vol_text = f"${exchange_analysis.algo_volume_usd / 1_000_000:.2f}M"
                elif exchange_analysis.algo_volume_usd >= 1_000:
                    algo_vol_text = f"${exchange_analysis.algo_volume_usd / 1_000:.2f}K"
                else:
                    algo_vol_text = f"${exchange_analysis.algo_volume_usd:.2f}"
                
                # Также показываем общий объём (не только алго)
                total_vol = exchange_analysis.buy_volume_usd + exchange_analysis.sell_volume_usd
                if total_vol >= 1_000_000:
                    total_vol_text = f"${total_vol / 1_000_000:.2f}M"
                elif total_vol >= 1_000:
                    total_vol_text = f"${total_vol / 1_000:.2f}K"
                else:
                    total_vol_text = f"${total_vol:.2f}"
                
                lines.append(
                    f"{direction_emoji} <b>{exchange_analysis.exchange}</b>: "
                    f"{exchange_analysis.direction} | "
                    f"Algo: {algo_score_pct:.0f}% | "
                    f"AlgoVol: {algo_vol_text} | "
                    f"Total: {total_vol_text}"
                )
        
        lines.append("")
        
        # Синхронность
        sync_pct = report.synchronization_score * 100
        if report.synchronization_score >= 0.7:
            sync_text = "высокая"
            sync_emoji = "✅"
        elif report.synchronization_score >= 0.4:
            sync_text = "средняя"
            sync_emoji = "⚠️"
        else:
            sync_text = "низкая"
            sync_emoji = "❌"
        
        lines.append(f"{sync_emoji} <b>Синхронность паттернов:</b> {sync_text} ({sync_pct:.0f}%)")
        
        # Интерпретация
        lines.append("")
        lines.append("🧩 <b>Интерпретация:</b>")
        interpretation = self._interpret_twap_report(report)
        lines.append(interpretation)
        
        return "\n".join(lines)
    
    def _interpret_twap_report(self, report) -> str:
        """Интерпретировать отчёт TWAP-детектора."""
        if report.dominant_direction == "SELL":
            if report.total_algo_volume_usd >= 1_000_000:
                return (
                    f"Идёт активный сброс через TWAP-алгоритмы. "
                    f"Объём {report.total_algo_volume_usd / 1_000_000:.2f}M в час говорит о сильной активности институциональных ботов. "
                    f"Вероятнее всего, идёт фиксация прибыли после роста."
                )
            else:
                return (
                    f"Наблюдается продажа через TWAP-алгоритмы. "
                    f"Это может быть синхронный выход средств или фиксация прибыли."
                )
        elif report.dominant_direction == "BUY":
            if report.total_algo_volume_usd >= 1_000_000:
                return (
                    f"Активное накопление через TWAP-алгоритмы. "
                    f"Высокий объём покупок ({report.total_algo_volume_usd / 1_000_000:.2f}M/ч) указывает на институциональный интерес. "
                    f"Возможна подготовка к росту."
                )
            else:
                return (
                    f"Умеренное накопление через алгоритмы. "
                    f"Алгоритмы покупают равномерно, что может указывать на подготовку к движению."
                )
        else:
            return (
                f"Баланс между покупками и продажами. "
                f"Рынок в консолидации, ждём пробоя в ту или иную сторону."
            )

