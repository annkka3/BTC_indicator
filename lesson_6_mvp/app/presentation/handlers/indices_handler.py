# app/presentation/handlers/indices_handler.py
"""
Handler for indices commands (fng, altseason).
"""

from telegram import Update, InputFile, InputMediaPhoto
from telegram.ext import ContextTypes
from telegram.constants import ParseMode
from .base_handler import BaseHandler
from ...infrastructure.ui_keyboards import build_kb
import logging

logger = logging.getLogger("alt_forecast.handlers.indices")


class IndicesHandler(BaseHandler):
    """Обработчик команд индексов."""
    
    def __init__(self, db, services: dict):
        super().__init__(db, services)
        self.indices_service = services.get("indices_service")
    
    async def handle_fng(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработать команду /fng (Fear & Greed Index)."""
        try:
            # Обрабатываем callback query если есть
            q = update.callback_query
            if q:
                await q.answer()
            
            # Используем старый IndicesService
            from ...infrastructure.indices_service import IndicesService
            indices = IndicesService(None)
            
            # Получаем текущее значение
            d = await indices.get_fng_history(limit=1)
            cur = d["values"][0] if d.get("values") else {"value": None, "classification": ""}
            val = cur.get("value")
            cls = cur.get("classification", "")
            
            try:
                ttu = int(d.get("time_until_update") or 0)
            except Exception:
                ttu = 0
            
            # Формируем caption как в старой версии
            def _ago_or_in(seconds):
                if seconds <= 0:
                    return "Обновлено только что"
                if seconds < 60:
                    return f"Обновлено {seconds} сек назад"
                mins = seconds // 60
                if mins < 60:
                    return f"Обновлено {mins} мин назад"
                hours = mins // 60
                return f"Обновлено {hours} ч назад"
            
            caption = (
                f"<b>Fear & Greed</b>\n"
                f"Значение: <b>{val if val is not None else '—'}</b> — {cls or ''}\n"
                f"{_ago_or_in(ttu)}"
            )
            
            # Используем URL изображения от Alternative.me (как в старой версии)
            png_url = indices.get_fng_widget_url()
            
            chat_id = update.effective_chat.id
            
            # Отправляем фото с URL
            await context.bot.send_photo(
                chat_id=chat_id,
                photo=png_url,
                caption=caption,
                parse_mode=ParseMode.HTML,
                reply_markup=build_kb("more")
            )
        except Exception:
            logger.exception("handle_fng failed")
    
    async def handle_fng_history(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработать команду /fng_history."""
        try:
            parts = (getattr(update.effective_message, "text", "") or "").split()
            limit = int(parts[1]) if len(parts) > 1 else 7
            limit = max(3, min(limit, 60))
            
            from ...infrastructure.indices_service import IndicesService
            indices = IndicesService(None)
            
            d = await indices.get_fng_history(limit=limit)
            values = d.get("values", [])
            
            if not values:
                await update.effective_message.reply_text(
                    "Не удалось получить историю F&G.",
                    reply_markup=build_kb("main")
                )
                return
            
            # Формируем сообщение с историей
            lines = [f"<b>🧮 F&G история (последние {len(values)})</b>\n"]
            for v in values[:limit]:
                val = v.get("value", 0)
                cls = v.get("classification", "")
                date = v.get("timestamp", "")
                lines.append(f"• {val}/100 — {cls} ({date})")
            
            text = "\n".join(lines)
            await update.effective_message.reply_text(
                text,
                parse_mode=ParseMode.HTML,
                reply_markup=build_kb("main")
            )
        except Exception:
            logger.exception("handle_fng_history failed")
    
    async def handle_altseason(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработать команду /altseason."""
        try:
            from ...infrastructure.indices_service import IndicesService
            indices = IndicesService(None)
            
            # Обрабатываем callback query если есть
            q = update.callback_query
            if q:
                await q.answer()
            
            d = await indices.get_altseason()
            val = d.get("value")
            label = d.get("label") or ""
            
            # Логируем полученные данные для отладки
            logger.info(f"Altseason data: value={val}, label={label}")
            
            if val is None:
                await update.effective_message.reply_text(
                    "Не удалось получить индекс Altseason. Попробуйте позже.",
                    reply_markup=build_kb("main")
                )
                return
            
            # Подготавливаем исторические данные (пока пустые, можно добавить позже)
            historical = []
            
            # Генерируем красивый gauge-график
            from ...visual.altseason_gauge import render_altseason_gauge
            png_bytes = render_altseason_gauge(float(val), label, historical)
            
            photo = InputFile(png_bytes, filename="altseason_gauge.png")
            
            chat_id = update.effective_chat.id
            
            # Всегда удаляем старое сообщение и отправляем новое, чтобы избежать проблем с парсингом
            if q:
                message = q.message
                # Удаляем старое сообщение, если это возможно
                try:
                    if message:
                        await message.delete()
                except Exception:
                    # Если не удалось удалить, просто отправляем новое
                    pass
            
            # Отправляем новое фото БЕЗ caption - вся информация уже на изображении
            await context.bot.send_photo(
                chat_id=chat_id,
                photo=photo,
                reply_markup=build_kb("main")
            )
        except Exception:
            logger.exception("handle_altseason failed")

