# app/presentation/handlers/base_handler.py
"""
Base handler class for Telegram bot handlers.

Этот модуль содержит базовый класс для всех обработчиков команд и callback'ов.
Использует паттерн Template Method для обеспечения общей функциональности.

Архитектура:
- Presentation Layer - обработка пользовательского ввода
- Использует Dependency Injection для получения services и db
- Предоставляет безопасные методы для работы с Telegram API

Пример использования:
    class MyHandler(BaseHandler):
        async def handle_my_command(self, update, context):
            # Использование services
            service = self.services.get("my_service")
            result = await service.do_something()
            
            # Безопасная отправка ответа
            await self._safe_reply_text(update, f"Result: {result}")
"""

from abc import ABC
from typing import Optional
from telegram import Update
from telegram.ext import ContextTypes
import logging

logger = logging.getLogger("alt_forecast.handlers")


class BaseHandler(ABC):
    """
    Базовый класс для всех обработчиков команд и callback'ов.
    
    Этот класс реализует паттерн Template Method и предоставляет:
    - Общую функциональность для всех handlers
    - Безопасные методы для работы с Telegram API
    - Доступ к базе данных и services через dependency injection
    
    Все handlers должны наследоваться от этого класса и реализовывать
    свои методы обработки команд.
    
    Атрибуты:
        db: Экземпляр базы данных для работы с данными
        services: Словарь с application services (market_data_service, etc.)
    """
    
    def __init__(self, db, services: Optional[dict] = None):
        """
        Инициализация базового handler.
        
        Args:
            db: Database instance - экземпляр базы данных
            services: Dictionary of application services - словарь сервисов приложения
                     Содержит ссылки на все application services (market_data_service,
                     bubbles_service, forecast_service, и т.д.)
        
        Пример:
            handler = MyHandler(db, services={
                "market_data_service": MarketDataService(),
                "bubbles_service": BubblesService(...)
            })
        """
        self.db = db
        self.services = services or {}
    
    async def handle(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        Основной метод обработки. Должен быть переопределен в подклассах.
        
        Args:
            update: Telegram Update объект - содержит информацию о сообщении
            context: ContextTypes.DEFAULT_TYPE - контекст выполнения команды
        
        Raises:
            NotImplementedError: Если метод не переопределен в подклассе
        
        Примечание:
            Этот метод является частью паттерна Template Method.
            Дочерние классы могут переопределить его, но обычно используют
            более специфичные методы типа handle_<command_name>.
        """
        raise NotImplementedError("Subclasses must implement handle method")
    
    async def _safe_reply_text(self, update: Update, text: str, **kwargs):
        """
        Безопасная отправка текстового сообщения с обработкой ошибок.
        
        Этот метод оборачивает вызов reply_text в try-except блок,
        чтобы предотвратить краш бота при ошибках отправки сообщений.
        
        Args:
            update: Telegram Update объект
            text: Текст сообщения для отправки
            **kwargs: Дополнительные параметры для reply_text
                     (parse_mode, reply_markup, и т.д.)
        
        Пример:
            await self._safe_reply_text(
                update,
                "Hello, world!",
                parse_mode=ParseMode.HTML,
                reply_markup=keyboard
            )
        """
        try:
            await update.effective_message.reply_text(text, **kwargs)
        except Exception as e:
            logger.exception("Failed to send text message: %s", e)
    
    async def _safe_edit_text(self, query, text: str, **kwargs):
        """
        Безопасное редактирование сообщения с обработкой ошибок.
        
        Используется для редактирования сообщений при обработке callback'ов.
        Оборачивает вызов edit_message_text в try-except блок.
        
        Args:
            query: CallbackQuery объект от Telegram
            text: Новый текст сообщения
            **kwargs: Дополнительные параметры для edit_message_text
        
        Пример:
            await self._safe_edit_text(
                query,
                "Updated message",
                parse_mode=ParseMode.HTML
            )
        """
        try:
            await query.edit_message_text(text, **kwargs)
        except Exception as e:
            logger.exception("Failed to edit message: %s", e)
    
    async def _safe_send_photo(self, chat_id: int, context: ContextTypes.DEFAULT_TYPE, photo, caption: str = None, **kwargs):
        """
        Безопасная отправка фото с обработкой ошибок.
        
        Автоматически конвертирует bytes/BytesIO в InputFile для отправки.
        Оборачивает вызов send_photo в try-except блок.
        
        Args:
            chat_id: ID чата для отправки фото
            context: ContextTypes.DEFAULT_TYPE - контекст выполнения
            photo: Фото для отправки (может быть URL, bytes, BytesIO, InputFile)
            caption: Подпись к фото (опционально)
            **kwargs: Дополнительные параметры для send_photo
                     (reply_markup, parse_mode, и т.д.)
        
        Пример:
            # Отправка изображения из bytes
            image_bytes = generate_image()
            await self._safe_send_photo(
                chat_id=update.effective_chat.id,
                context=context,
                photo=image_bytes,
                caption="Generated image"
            )
        """
        try:
            from telegram import InputFile
            from io import BytesIO
            # Автоматическая конвертация bytes/BytesIO в InputFile
            if isinstance(photo, (bytes, BytesIO)):
                photo = InputFile(photo, filename="image.png")
            await context.bot.send_photo(chat_id=chat_id, photo=photo, caption=caption, **kwargs)
        except Exception as e:
            logger.exception("Failed to send photo: %s", e)
    
    async def _send_long_message(self, update: Update, message_to_edit=None, text: str = None, max_length: int = 4000, **kwargs):
        """
        Отправка длинного сообщения с автоматическим разбиением на части.
        
        Если сообщение превышает max_length, оно разбивается на части.
        Если передан message_to_edit, первая часть редактирует это сообщение,
        остальные отправляются как новые.
        
        Args:
            update: Telegram Update объект
            message_to_edit: Сообщение для редактирования (опционально)
            text: Текст для отправки
            max_length: Максимальная длина одного сообщения (по умолчанию 4000)
            **kwargs: Дополнительные параметры (parse_mode, и т.д.)
        """
        if not text:
            return
        
        # Если сообщение короткое, отправляем как обычно
        if len(text) <= max_length:
            try:
                if message_to_edit:
                    await message_to_edit.edit_text(text, **kwargs)
                else:
                    await update.effective_message.reply_text(text, **kwargs)
            except Exception as e:
                logger.exception("Failed to send message: %s", e)
            return
        
        # Разбиваем на части
        lines = text.split('\n')
        parts = []
        current_part = []
        current_length = 0
        
        for line in lines:
            line_length = len(line) + 1  # +1 for newline
            
            # Если добавление этой строки превысит лимит, сохраняем текущую часть
            if current_length + line_length > max_length and current_part:
                parts.append('\n'.join(current_part))
                current_part = [line]
                current_length = line_length
            else:
                current_part.append(line)
                current_length += line_length
        
        # Добавляем последнюю часть
        if current_part:
            parts.append('\n'.join(current_part))
        
        # Отправляем части
        for i, part in enumerate(parts):
            try:
                if i == 0 and message_to_edit:
                    # Первая часть редактирует существующее сообщение
                    await message_to_edit.edit_text(part, **kwargs)
                else:
                    # Остальные части отправляются как новые сообщения
                    await update.effective_message.reply_text(
                        part,
                        **kwargs
                    )
            except Exception as e:
                logger.exception(f"Failed to send message part {i+1}/{len(parts)}: %s", e)

