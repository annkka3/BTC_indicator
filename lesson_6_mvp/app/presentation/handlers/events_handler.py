# app/presentation/handlers/events_handler.py
"""
Handler for events commands.
"""

from telegram import Update
from telegram.ext import ContextTypes
from telegram.constants import ParseMode
from .base_handler import BaseHandler
from ...infrastructure.ui_keyboards import build_kb
import logging
import re
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

logger = logging.getLogger("alt_forecast.handlers.events")


class EventsHandler(BaseHandler):
    """Обработчик команд событий."""
    
    def _parse_date_to_ms(self, date_str: str, tz) -> int:
        """
        Преобразует 'YYYY-MM-DD' (или 'YYYY-MM-DD HH:MM') в unix ms локальной TZ.
        Если время не указано — берём полночь.
        """
        date_str = date_str.strip()
        fmt = "%Y-%m-%d %H:%M" if " " in date_str else "%Y-%m-%d"
        dt = datetime.strptime(date_str, fmt)
        if fmt == "%Y-%m-%d":
            dt = dt.replace(hour=0, minute=0, second=0, microsecond=0)
        if tz:
            dt = dt.replace(tzinfo=tz)
        return int(dt.timestamp() * 1000)
    
    async def handle_events_add(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработать команду /events_add."""
        try:
            from ...infrastructure.events import add_event
            from ...config import settings
            
            text = (update.effective_message.text or "").strip()
            
            # Разрешим оба формата: с временем и без
            m = re.match(r"^/events_add\s+(\d{4}-\d{2}-\d{2}(?:\s+\d{2}:\d{2})?)\s+(.+)$", text)
            if not m:
                await update.effective_message.reply_text(
                    "Формат: /events_add YYYY-MM-DD [HH:MM] Текст события\n"
                    "Пример: /events_add 2025-10-05 19:00 FOMC"
                )
                return
            
            date_str, title = m.group(1), m.group(2)
            
            try:
                tz = getattr(settings, "tz", None)
            except Exception:
                tz = None
            
            try:
                ts_ms = self._parse_date_to_ms(date_str, tz)
            except Exception as e:
                await update.effective_message.reply_text(f"Ошибка в дате: {e}")
                return
            
            eid = add_event(ts_ms, title, author_chat_id=(update.effective_user.id if update.effective_user else None))
            await update.effective_message.reply_text(f"✅ Событие добавлено (id={eid}). Видно всем.")
        except Exception:
            logger.exception("handle_events_add failed")
    
    async def handle_events_list(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработать команду /events_list."""
        try:
            from ...infrastructure.events import list_all_events, purge_past_events
            from ...config import settings
            
            try:
                purge_past_events()  # мягкая гигиена
            except Exception:
                logger.exception("purge_past_events failed silently")
            
            rows = list_all_events()
            if not rows:
                await update.effective_message.reply_text("Сейчас нет предстоящих событий.")
                return
            
            try:
                tz = getattr(settings, "tz", None)
            except Exception:
                tz = None
            
            lines = ["<b>Предстоящие события</b>"]
            for eid, ts, title in rows[:100]:
                dt = datetime.fromtimestamp(ts / 1000.0, tz=tz or timezone.utc)
                lines.append(f"• <b>{dt.strftime('%Y-%m-%d')}</b> — {title}")
            
            await update.effective_message.reply_text(
                "\n".join(lines),
                parse_mode=ParseMode.HTML
            )
        except Exception:
            logger.exception("handle_events_list failed")
    
    async def handle_events_del(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработать команду /events_del."""
        try:
            from ...infrastructure.events import del_event
            
            parts = update.effective_message.text.split()
            if len(parts) < 2 or not parts[1].isdigit():
                await update.effective_message.reply_text("Формат: /events_del 12")
                return
            
            del_event(update.effective_chat.id, int(parts[1]))
            await update.effective_message.reply_text("Удалено.")
        except Exception:
            logger.exception("handle_events_del failed")

