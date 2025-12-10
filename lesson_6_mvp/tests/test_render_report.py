#!/usr/bin/env python3
"""
Тестовый скрипт для проверки рендеринга отчёта через CompactReportRenderer.
"""

import logging
import sys
import os

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

from app.infrastructure.db import DB
from app.domain.market_diagnostics.analyzer import MarketAnalyzer
from app.domain.market_diagnostics.report_builder import ReportBuilder
from app.domain.market_diagnostics.compact_report import CompactReportRenderer
from app.domain.market_diagnostics.features import FeatureExtractor
from app.domain.market_diagnostics.indicators import IndicatorCalculator
from app.domain.market_diagnostics.config import DEFAULT_CONFIG

def test_render_report():
    """Тестируем рендеринг отчёта через CompactReportRenderer."""
    logger = logging.getLogger(__name__)
    logger.info("=" * 80)
    logger.info("Тестирование рендеринга отчёта через CompactReportRenderer")
    logger.info("=" * 80)
    
    try:
        # Инициализация
        import os
        db_path = os.path.join(os.path.dirname(__file__), "data", "data.db")
        db = DB(path=db_path)
        symbol = "BTC"
        timeframe = "1h"
        
        logger.info(f"Символ: {symbol}, Таймфрейм: {timeframe}")
        
        # Получаем данные
        logger.info("Получение данных из БД...")
        rows = db.last_n(symbol, timeframe, 500)
        if not rows:
            logger.error(f"Нет данных для {symbol} {timeframe}")
            return
        
        import pandas as pd
        # Преобразуем rows в DataFrame
        data = {
            'timestamp': [r[0] for r in rows],
            'open': [r[1] for r in rows],
            'high': [r[2] for r in rows],
            'low': [r[3] for r in rows],
            'close': [r[4] for r in rows],
            'volume': [r[5] if r[5] is not None else 0.0 for r in rows]
        }
        df = pd.DataFrame(data)
        # ts в миллисекундах, конвертируем в секунды для pd.to_datetime
        df['timestamp'] = pd.to_datetime(df['timestamp'] // 1000, unit='s')
        df.set_index('timestamp', inplace=True)
        
        logger.info(f"Получено {len(df)} баров")
        
        # Вычисляем индикаторы и признаки
        logger.info("Вычисление индикаторов...")
        indicator_calc = IndicatorCalculator(DEFAULT_CONFIG)
        indicators = indicator_calc.calculate_all(df)
        
        logger.info("Извлечение признаков...")
        feature_extractor = FeatureExtractor(DEFAULT_CONFIG)
        features = feature_extractor.extract_features(df, indicators, derivatives={})
        
        # Анализ
        logger.info("Анализ рынка...")
        analyzer = MarketAnalyzer(DEFAULT_CONFIG)
        diagnostics = analyzer.analyze(symbol, timeframe, df, indicators, features)
        
        # Строим отчёт
        logger.info("Построение CompactReport...")
        report_builder = ReportBuilder()
        compact_report = report_builder.build_compact_report(
            symbol=symbol,
            target_tf=timeframe,
            diagnostics={timeframe: diagnostics},
            indicators={timeframe: indicators},
            features={timeframe: features},
            derivatives={timeframe: {}},
            current_price=df['close'].iloc[-1]
        )
        
        logger.info(f"CompactReport создан: per_tf keys={list(compact_report.per_tf.keys())}, per_tf count={len(compact_report.per_tf)}")
        
        # Рендерим отчёт
        logger.info("=" * 80)
        logger.info("Рендеринг отчёта через CompactReportRenderer...")
        logger.info("=" * 80)
        
        renderer = CompactReportRenderer()
        report_text = renderer.render(compact_report, use_nlg=True)
        
        logger.info(f"Отчёт сгенерирован, длина: {len(report_text)} символов")
        
        # Проверяем формат
        logger.info("=" * 80)
        logger.info("ПРОВЕРКА ФОРМАТА ОТЧЁТА:")
        logger.info("=" * 80)
        
        if "📐 Фибоначчи" in report_text:
            logger.info("✓ Блок Фибоначчи найден (новый формат)")
        else:
            logger.warning("✗ Блок Фибоначчи НЕ найден")
        
        if "🌊 Эллиотт" in report_text:
            logger.info("✓ Блок Эллиотта найден (новый формат)")
        else:
            logger.warning("✗ Блок Эллиотта НЕ найден")
        
        if "Импульс:" in report_text and "[" in report_text and "█" in report_text:
            logger.warning("⚠️ Обнаружены бары в отчёте (старый формат?)")
        else:
            logger.info("✓ Бары не обнаружены (новый формат)")
        
        if "Тренд: +" in report_text and "Импульс: +" in report_text and "Объём: +" in report_text:
            logger.info("✓ Полный консенсус индикаторов найден (новый формат)")
        elif "📈 Объём:" in report_text and "Консенсус:" in report_text:
            logger.warning("⚠️ Неполный консенсус индикаторов (старый формат?)")
        
        logger.info("=" * 80)
        logger.info("Первые 1000 символов отчёта:")
        logger.info("-" * 80)
        logger.info(report_text[:1000])
        logger.info("-" * 80)
        
    except Exception as e:
        logger.exception(f"Ошибка при тестировании: {e}")
        raise

if __name__ == "__main__":
    test_render_report()












