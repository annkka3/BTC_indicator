#!/usr/bin/env python3
"""
Тестовый скрипт для симуляции генерации отчёта через бота.
Имитирует вызов handler.handle_market_doctor().
"""

import logging
import sys
import os
from unittest.mock import Mock

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)

# Добавляем путь к проекту
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def test_bot_report_generation():
    """Симулируем генерацию отчёта через бота."""
    logger = logging.getLogger(__name__)
    logger.info("=" * 80)
    logger.info("Симуляция генерации отчёта через бота")
    logger.info("=" * 80)
    
    try:
        from app.infrastructure.db import DB
        from app.presentation.handlers.market_doctor_handler import MarketDoctorHandler
        
        symbol = "BTC"
        timeframe = "1h"
        brief = False
        trade_only = False
        
        logger.info(f"Параметры: symbol={symbol}, tf={timeframe}, brief={brief}, trade_only={trade_only}")
        
        # Инициализация
        db_path = os.path.join(os.path.dirname(__file__), "data", "data.db")
        if not os.path.exists(db_path):
            db_path = "./data/data.db"
        
        db = DB(path=db_path)
        handler = MarketDoctorHandler(db)
        
        logger.info("✓ MarketDoctorHandler инициализирован")
        
        # Создаём mock context с user_data
        mock_context = Mock()
        mock_context.user_data = {'md_use_v2': True}  # Включаем v2 генератор
        mock_context.args = [symbol, timeframe]
        
        # Создаём mock update
        mock_update = Mock()
        mock_update.effective_user = Mock()
        mock_update.effective_user.id = 12345
        mock_update.effective_message = Mock()
        mock_update.effective_message.text = f"/md {symbol} {timeframe}"
        mock_update.effective_message.reply_text = Mock()
        
        logger.info("✓ Mock объекты созданы")
        
        # Вызываем метод напрямую (без async)
        logger.info("=" * 80)
        logger.info("Генерация отчёта...")
        logger.info("=" * 80)
        
        # Импортируем asyncio для запуска async функции
        import asyncio
        
        async def generate_report():
            try:
                # Вызываем основной метод обработки команды
                # Это вызовет _handle_market_doctor_common, который в свою очередь вызовет генерацию отчёта
                await handler.handle_market_doctor(mock_update, mock_context)
                
                # Получаем результат из reply_text
                if mock_update.effective_message.reply_text.called:
                    call_args = mock_update.effective_message.reply_text.call_args
                    if call_args:
                        report = call_args[0][0] if call_args[0] else call_args[1].get('text', '')
                        logger.info("=" * 80)
                        logger.info("ОТЧЁТ СГЕНЕРИРОВАН")
                        logger.info("=" * 80)
                        logger.info(f"Длина отчёта: {len(report)} символов")
                        logger.info("=" * 80)
                        logger.info("ПЕРВЫЕ 500 СИМВОЛОВ:")
                        logger.info("-" * 80)
                        logger.info(report[:500])
                        logger.info("-" * 80)
                        
                        # Проверяем формат
                        if "🏥 Market Doctor" in report and "🎯 Решение:" in report and "🧠 Режим рынка" in report:
                            logger.info("✓ V2 ФОРМАТ ПОДТВЕРЖДЁН!")
                        elif "📦 Фаза:" in report or "Монета:" in report:
                            logger.error("✗ СТАРЫЙ ФОРМАТ! V2 генератор не использовался")
                            logger.error("Проверьте логи выше для диагностики")
                        else:
                            logger.warning("⚠ Неизвестный формат")
                        
                        logger.info("=" * 80)
                        logger.info("ПОЛНЫЙ ОТЧЁТ:")
                        logger.info("=" * 80)
                        logger.info(report)
                        logger.info("=" * 80)
                    else:
                        logger.warning("reply_text был вызван, но аргументы не найдены")
                else:
                    logger.warning("reply_text не был вызван - возможно, произошла ошибка")
            except Exception as e:
                logger.exception(f"Ошибка при генерации отчёта: {e}")
                raise
        
        # Запускаем async функцию
        asyncio.run(generate_report())
        
    except Exception as e:
        logger.exception(f"Ошибка при тестировании: {e}")
        raise

if __name__ == "__main__":
    test_bot_report_generation()

