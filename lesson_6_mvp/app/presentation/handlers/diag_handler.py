# app/presentation/handlers/diag_handler.py
"""
Handler for diagnostic commands.
"""

from telegram import Update
from telegram.ext import ContextTypes
from telegram.constants import ParseMode
from .base_handler import BaseHandler
from ...infrastructure.ohlcv_cache import get_ohlcv_cache
from ...domain.models import Metric, Timeframe
import logging
from datetime import datetime, timezone

logger = logging.getLogger("alt_forecast.handlers.diag")


class DiagHandler(BaseHandler):
    """Обработчик диагностических команд."""
    
    async def handle_diag(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработать команду /diag для метаданных последнего OHLCV и детектора подозрительно дёшево."""
        try:
            args = context.args or []
            metric = args[0].upper() if args and args[0] else "BTC"
            timeframe = args[1] if len(args) > 1 else "1h"
            
            # Получаем последние данные
            rows = self.db.last_n(metric, timeframe, 100)
            if not rows:
                await update.effective_message.reply_text(
                    f"Нет данных для {metric} {timeframe}",
                    parse_mode=ParseMode.HTML
                )
                return
            
            # Последний бар
            last_bar = rows[-1]
            ts, o, h, l, c, v = last_bar
            
            # Метаданные последнего OHLCV
            last_dt = datetime.fromtimestamp(ts / 1000.0, tz=timezone.utc)
            age_seconds = (datetime.now(timezone.utc) - last_dt).total_seconds()
            
            # Статистика кэша
            cache = get_ohlcv_cache()
            cache_stats = cache.get_stats()
            cached_data = cache.get(metric, timeframe)
            cache_status = "✅ В кэше" if cached_data else "❌ Не в кэше"
            cache_age = "N/A"
            if cached_data:
                # Вычисляем возраст кэша (примерно)
                cache_age = f"~{cache_stats.get('ttl_seconds', 45)}s"
            
            # Детектор "подозрительно дёшево"
            # Проверяем, не слишком ли низкая цена по сравнению с историческими данными
            closes = [r[4] for r in rows]
            if len(closes) >= 20:
                recent_avg = sum(closes[-20:]) / 20
                historical_avg = sum(closes) / len(closes)
                current_price = c
                
                # Проверяем отклонения
                deviation_from_recent = ((current_price - recent_avg) / recent_avg) * 100
                deviation_from_historical = ((current_price - historical_avg) / historical_avg) * 100
                
                suspicious = False
                suspicious_reason = ""
                
                if deviation_from_recent < -10:  # Более чем на 10% ниже недавнего среднего
                    suspicious = True
                    suspicious_reason = f"Цена на {abs(deviation_from_recent):.2f}% ниже недавнего среднего (20 баров)"
                elif deviation_from_historical < -15:  # Более чем на 15% ниже исторического среднего
                    suspicious = True
                    suspicious_reason = f"Цена на {abs(deviation_from_historical):.2f}% ниже исторического среднего ({len(closes)} баров)"
                
                # Проверяем на аномально низкий объем
                if v is not None and len(rows) >= 20:
                    volumes = [r[5] for r in rows if r[5] is not None]
                    if volumes:
                        avg_volume = sum(volumes) / len(volumes)
                        if v < avg_volume * 0.1:  # Менее 10% от среднего объема
                            suspicious = True
                            if suspicious_reason:
                                suspicious_reason += " + "
                            suspicious_reason += f"Аномально низкий объем ({v/avg_volume*100:.1f}% от среднего)"
            else:
                deviation_from_recent = 0.0
                deviation_from_historical = 0.0
                suspicious = False
                suspicious_reason = "Недостаточно данных для анализа"
            
            # Формируем сообщение
            message = f"<b>Диагностика OHLCV: {metric} {timeframe}</b>\n\n"
            message += f"<b>Последний бар:</b>\n"
            message += f"• Timestamp: {last_dt.strftime('%Y-%m-%d %H:%M:%S UTC')}\n"
            message += f"• Возраст: {age_seconds:.1f}s ({age_seconds/60:.1f} мин)\n"
            message += f"• OHLC: {o:.2f} / {h:.2f} / {l:.2f} / {c:.2f}\n"
            volume_str = f"{v:.2f}" if v is not None else "N/A"
            message += f"• Volume: {volume_str}\n\n"
            
            message += f"<b>Кэш:</b>\n"
            message += f"• Статус: {cache_status}\n"
            message += f"• Возраст кэша: {cache_age}\n"
            message += f"• Всего записей: {cache_stats.get('total_entries', 0)}\n"
            message += f"• Активных: {cache_stats.get('active_entries', 0)}\n"
            message += f"• Истекших: {cache_stats.get('expired_entries', 0)}\n\n"
            
            message += f"<b>Детектор подозрительно дёшево:</b>\n"
            if suspicious:
                message += f"⚠️ <b>ПОДОЗРИТЕЛЬНО!</b>\n"
                message += f"• {suspicious_reason}\n"
            else:
                message += f"✅ Цена в нормальном диапазоне\n"
            message += f"• Отклонение от недавнего среднего (20 баров): {deviation_from_recent:+.2f}%\n"
            message += f"• Отклонение от исторического среднего ({len(closes)} баров): {deviation_from_historical:+.2f}%\n"
            
            # Статистика по данным
            if len(rows) > 0:
                message += f"\n<b>Статистика ({len(rows)} баров):</b>\n"
                all_closes = [r[4] for r in rows]
                all_highs = [r[2] for r in rows]
                all_lows = [r[3] for r in rows]
                message += f"• Минимум: {min(all_lows):.2f}\n"
                message += f"• Максимум: {max(all_highs):.2f}\n"
                message += f"• Среднее: {sum(all_closes)/len(all_closes):.2f}\n"
                message += f"• Текущая цена: {c:.2f}\n"
            
            await update.effective_message.reply_text(
                message,
                parse_mode=ParseMode.HTML
            )
            
        except Exception:
            logger.exception("handle_diag failed")
            await update.effective_message.reply_text(
                "Ошибка при выполнении диагностики. Проверьте параметры команды: /diag [metric] [timeframe]"
            )

