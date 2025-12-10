#!/usr/bin/env python3
"""
Тестовый скрипт для проверки генерации отчёта Market Doctor
и проверки логов Фибоначчи и Эллиотта.
"""

import logging
import sys
import os

# Настройка логирования
logging.basicConfig(
    level=logging.DEBUG,
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
from app.domain.market_diagnostics.report_nlg import ReportNLG, ReportContext
from app.domain.market_diagnostics.features import FeatureExtractor
from app.domain.market_diagnostics.indicators import IndicatorCalculator
from app.domain.market_diagnostics.trade_planner import TradePlanner

def test_market_doctor_report():
    """Тестируем генерацию отчёта Market Doctor."""
    logger = logging.getLogger(__name__)
    logger.info("=" * 80)
    logger.info("Тестирование генерации отчёта Market Doctor")
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
        # rows это список кортежей (ts, o, h, l, c, v)
        # ts в миллисекундах
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
        from app.domain.market_diagnostics.config import DEFAULT_CONFIG
        indicator_calc = IndicatorCalculator(DEFAULT_CONFIG)
        indicators = indicator_calc.calculate_all(df)
        
        logger.info("Извлечение признаков...")
        feature_extractor = FeatureExtractor(DEFAULT_CONFIG)
        features = feature_extractor.extract_features(df, indicators, derivatives={})
        
        # Анализ
        logger.info("Анализ рынка...")
        analyzer = MarketAnalyzer()
        diagnostics = analyzer.analyze(symbol, timeframe, df, indicators, features)
        
        logger.info(f"Фаза: {diagnostics.phase}")
        logger.info(f"Тренд: {diagnostics.trend}")
        
        # Проверяем Фибоначчи и Эллиотта
        logger.info("=" * 80)
        logger.info("ПРОВЕРКА ДАННЫХ ФИБОНАЧЧИ И ЭЛЛИОТТА:")
        logger.info("=" * 80)
        
        if diagnostics.fibonacci_analysis:
            logger.info(f"✓ Fibonacci analysis найден: {type(diagnostics.fibonacci_analysis)}")
            logger.info(f"  - Swing high: {diagnostics.fibonacci_analysis.swing_high}")
            logger.info(f"  - Swing low: {diagnostics.fibonacci_analysis.swing_low}")
            logger.info(f"  - Nearest level: {diagnostics.fibonacci_analysis.nearest_level}")
        else:
            logger.warning("✗ Fibonacci analysis НЕ найден (None)")
        
        if diagnostics.elliott_waves:
            logger.info(f"✓ Elliott waves найден: {type(diagnostics.elliott_waves)}")
            logger.info(f"  - Pattern type: {diagnostics.elliott_waves.pattern_type}")
            logger.info(f"  - Current wave: {diagnostics.elliott_waves.current_wave}")
            logger.info(f"  - Trend direction: {diagnostics.elliott_waves.trend_direction}")
        else:
            logger.warning("✗ Elliott waves НЕ найден (None)")
        
        # Строим отчёт
        logger.info("=" * 80)
        logger.info("Построение CompactReport...")
        logger.info("=" * 80)
        
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
        
        # Проверяем данные в CompactReport
        logger.info("=" * 80)
        logger.info("ПРОВЕРКА ДАННЫХ В COMPACTREPORT:")
        logger.info("=" * 80)
        
        smc = compact_report.smc
        logger.info(f"SMC keys: {list(smc.keys())}")
        
        if 'fibonacci' in smc and smc['fibonacci']:
            logger.info(f"✓ Fibonacci в smc найден: {type(smc['fibonacci'])}")
            logger.info(f"  - Keys: {list(smc['fibonacci'].keys())}")
        else:
            logger.warning("✗ Fibonacci в smc НЕ найден")
        
        if 'elliott_waves' in smc and smc['elliott_waves']:
            logger.info(f"✓ Elliott waves в smc найден: {type(smc['elliott_waves'])}")
            logger.info(f"  - Keys: {list(smc['elliott_waves'].keys())}")
        else:
            logger.warning("✗ Elliott waves в smc НЕ найден")
        
        # Генерируем отчёт через NLG
        logger.info("=" * 80)
        logger.info("Генерация отчёта через NLG...")
        logger.info("=" * 80)
        
        nlg = ReportNLG()
        context = ReportContext(
            report=compact_report,
            include_fibonacci=True,
            include_elliott=True
        )
        
        report_text = nlg.build_report(context)
        
        # Проверяем наличие блоков в отчёте
        logger.info("=" * 80)
        logger.info("ПРОВЕРКА ОТЧЁТА:")
        logger.info("=" * 80)
        
        if "📐 Фибоначчи" in report_text:
            logger.info("✓ Блок Фибоначчи найден в отчёте")
        else:
            logger.warning("✗ Блок Фибоначчи НЕ найден в отчёте")
        
        if "🌊 Эллиотт" in report_text:
            logger.info("✓ Блок Эллиотта найден в отчёте")
        else:
            logger.warning("✗ Блок Эллиотта НЕ найден в отчёте")
        
        logger.info("=" * 80)
        logger.info("Тест завершён")
        logger.info("=" * 80)
        
        # Выводим первые 2000 символов отчёта для проверки
        logger.info("\nПервые 2000 символов отчёта:")
        logger.info("-" * 80)
        logger.info(report_text[:2000])
        logger.info("-" * 80)
        
    except Exception as e:
        logger.exception(f"Ошибка при тестировании: {e}")
        raise

if __name__ == "__main__":
    test_market_doctor_report()

