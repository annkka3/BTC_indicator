# app/presentation/handlers/chart_handler.py
"""
Handler for chart commands.
"""

from typing import Tuple
from telegram import Update, InputMediaPhoto, InputFile
from telegram.ext import ContextTypes
from telegram.constants import ParseMode
from .base_handler import BaseHandler
from ...infrastructure.ui_keyboards import DEFAULT_TF
from ...usecases.generate_report import METRICS
from ...lib.series import get_closes
from ...domain.services import trend_arrow_metric, indicator_divergences, pair_divergences, risk_score
from ...infrastructure.chart_parser import parse_chart_command_simple
from ...domain.chart_settings import ChartSettings
import logging

logger = logging.getLogger("alt_forecast.handlers.charts")


class ChartHandler(BaseHandler):
    """Обработчик команд графиков."""
    
    def _resolve_tf(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> str:
        """Определить таймфрейм из контекста."""
        args = context.args or []
        if args and args[0] in ("15m", "1h", "4h", "1d", "24h"):
            return args[0] if args[0] != "24h" else "1d"
        return context.user_data.get('tf', DEFAULT_TF)
    
    def _parse_chart_settings(self, update: Update, context: ContextTypes.DEFAULT_TYPE, default_metric: str = "BTC") -> Tuple[ChartSettings, str]:
        """Парсить настройки графика из команды."""
        message_text = update.effective_message.text or ""
        
        # Пытаемся распарсить настройки из команды
        settings = parse_chart_command_simple(message_text)
        if settings is None:
            # Используем настройки по умолчанию
            settings = ChartSettings()
            settings.timeframe = self._resolve_tf(update, context)
        else:
            # Если TF не указан в команде, используем из контекста
            if not settings.timeframe or settings.timeframe == "1h":
                settings.timeframe = self._resolve_tf(update, context)
        
        # Извлекаем символ из команды (если указан)
        parts = message_text.split()
        metric = default_metric
        for part in parts:
            if part.upper() in ["BTC", "ETH", "USDT.D", "BTC.D", "TOTAL2", "TOTAL3", "ETHBTC"]:
                metric = part.upper()
                break
        
        return settings, metric
    
    async def handle_chart(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработать команду /chart с поддержкой параметров."""
        try:
            settings, metric = self._parse_chart_settings(update, context)
            chat_id = update.effective_chat.id
            
            # Проверяем, используется ли новый формат с параметрами
            message_text = update.effective_message.text or ""
            has_custom_params = any(param in message_text for param in ["mode=", "ma=", "ind=", "ann=", "legend=", "vs="])
            
            if has_custom_params:
                # Используем новый рендерер с настройками
                from ...visual.chart_renderer import render_chart
                try:
                    png = render_chart(self.db, metric, settings, n_bars=500)
                    
                    # Формируем подпись
                    caption_parts = [f"<b>{metric}</b> • {settings.timeframe}"]
                    if settings.currency:
                        caption_parts.append(f"{settings.currency.upper()}")
                    caption = " • ".join(caption_parts)
                    caption += f"\n<i>Mode: {settings.mode.value}</i>"
                    if settings.sma_periods:
                        caption += f" • MA: {','.join(map(str, settings.sma_periods))}"
                    if settings.ema_periods:
                        caption += f" • EMA: {','.join(map(str, settings.ema_periods))}"
                    
                    photo = InputFile(png, filename=f"chart_{metric}_{settings.timeframe}.png")
                    await context.bot.send_photo(
                        chat_id=chat_id,
                        photo=photo,
                        caption=caption,
                        parse_mode=ParseMode.HTML
                    )
                    return
                except Exception:
                    logger.exception("render_chart failed")
                    await update.effective_message.reply_text("Не удалось построить график с указанными параметрами, попробуйте позже.")
                    return
            
            # Старый формат - используем существующий рендерер
            tf = self._resolve_tf(update, context)
            
            from ...visual.digest import render_digest
            try:
                png = render_digest(self.db, tf)
            except Exception:
                logger.exception("render_digest failed")
                await update.effective_message.reply_text("Не удалось построить график, попробуйте позже.")
                return

            arrows = {}
            for m in METRICS:
                closes = get_closes(self.db, m, tf, 80)
                arrows[m] = trend_arrow_metric(m, tf, closes)

            all_divs = []
            for m in METRICS:
                rows = self.db.last_n(m, tf, 320)
                if not rows:
                    continue
                highs = [r[2] for r in rows]
                lows = [r[3] for r in rows]
                closes = [r[4] for r in rows]
                vols = [r[5] for r in rows] if len(rows[0]) > 5 else None
                divs = indicator_divergences(m, tf, closes, vols)
                all_divs.extend(divs)

            series = self._pair_series_sec(tf, 320)
            if series:
                all_divs.extend(pair_divergences(tf, series))

            score, label = risk_score(tf, arrows, all_divs)
            caption = f"<b>{tf}</b>: {label} (счёт {score})\n<i>/chart 15m|1h|4h|1d</i>"

            photo = InputFile(png, filename=f"chart_{tf}.png")
            await context.bot.send_photo(
                chat_id=chat_id,
                photo=photo,
                caption=caption,
                parse_mode=ParseMode.HTML
            )
            
        except Exception:
            logger.exception("handle_chart failed")
    
    async def handle_chart_album(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработать команду /chart_album."""
        try:
            tf = self._resolve_tf(update, context)
            chat_id = update.effective_chat.id
            
            from ...visual.digest import render_digest_panels
            panels = render_digest_panels(self.db, tf)

            arrows = {}
            for m in METRICS:
                closes = get_closes(self.db, m, tf, 80)
                arrows[m] = trend_arrow_metric(m, tf, closes)

            all_divs = []
            for m in METRICS:
                rows = self.db.last_n(m, tf, 320)
                if not rows:
                    continue
                highs = [r[2] for r in rows]
                lows = [r[3] for r in rows]
                closes = [r[4] for r in rows]
                vols = [r[5] for r in rows] if len(rows[0]) > 5 else None
                divs = indicator_divergences(m, tf, closes, vols)
                all_divs.extend(divs)

            series = self._pair_series_sec(tf, 320)
            if series:
                all_divs.extend(pair_divergences(tf, series))

            media = [InputMediaPhoto(InputFile(p, filename=f"panel_{i}.png")) for i, p in enumerate(panels)]
            await context.bot.send_media_group(chat_id=chat_id, media=media)
            
        except Exception:
            logger.exception("handle_chart_album failed")
    
    def _pair_series_sec(self, tf: str, n: int = 320):
        """Вспомогательный метод для получения серий."""
        from ...usecases.generate_report import METRICS
        series = {}
        for m in METRICS:
            rows = self.db.last_n_closes(m, tf, n)
            series[m] = [(_ts_sec(ts), c) for ts, c in rows]
        return series


def _ts_sec(ts: int) -> int:
    """Преобразовать timestamp в секунды."""
    if ts > 1e10:  # миллисекунды
        return ts // 1000
    return ts

