#!/usr/bin/env python3
"""
Тестовый скрипт для проверки генерации отчёта с генератором v2.
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

def test_report_generation():
    """Тестируем генерацию отчёта с генератором v2."""
    logger = logging.getLogger(__name__)
    logger.info("=" * 80)
    logger.info("Тестирование генерации отчёта с генератором v2")
    logger.info("=" * 80)
    
    try:
        from app.infrastructure.db import DB
        from app.domain.market_diagnostics.analyzer import MarketAnalyzer
        from app.domain.market_diagnostics.report_builder import ReportBuilder
        from app.domain.market_diagnostics.compact_report import CompactReportRenderer
        from app.domain.market_diagnostics.features import FeatureExtractor
        from app.domain.market_diagnostics.indicators import IndicatorCalculator
        from app.domain.market_diagnostics.config import DEFAULT_CONFIG
        
        symbol = "BTC"
        timeframe = "1h"
        
        logger.info(f"Символ: {symbol}, Таймфрейм: {timeframe}")
        
        # Получаем данные
        db_path = os.path.join(os.path.dirname(__file__), "data", "data.db")
        db = DB(path=db_path)
        rows = db.last_n(symbol, timeframe, 500)
        if not rows:
            logger.error(f"Нет данных для {symbol} {timeframe}")
            return
        
        import pandas as pd
        data = {
            'timestamp': [r[0] for r in rows],
            'open': [r[1] for r in rows],
            'high': [r[2] for r in rows],
            'low': [r[3] for r in rows],
            'close': [r[4] for r in rows],
            'volume': [r[5] if r[5] is not None else 0.0 for r in rows]
        }
        df = pd.DataFrame(data)
        df['timestamp'] = pd.to_datetime(df['timestamp'] // 1000, unit='s')
        df.set_index('timestamp', inplace=True)
        
        logger.info(f"Получено {len(df)} баров")
        
        # Вычисляем индикаторы и признаки
        indicator_calc = IndicatorCalculator(DEFAULT_CONFIG)
        indicators = indicator_calc.calculate_all(df)
        
        feature_extractor = FeatureExtractor(DEFAULT_CONFIG)
        features = feature_extractor.extract_features(df, indicators, derivatives={})
        
        # Анализ
        analyzer = MarketAnalyzer(DEFAULT_CONFIG)
        diagnostics = analyzer.analyze(symbol, timeframe, df, indicators, features)
        
        # Строим отчёт
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
        
        logger.info(f"CompactReport создан: per_tf_count={len(compact_report.per_tf)}, per_tf_keys={list(compact_report.per_tf.keys())}")
        
        # Тестируем рендеринг с use_v2=True
        logger.info("=" * 80)
        logger.info("Тестирование рендеринга с use_v2=True")
        logger.info("=" * 80)
        
        renderer = CompactReportRenderer()
        
        # Тест 1: use_v2=True
        logger.info("Тест 1: use_v2=True, use_nlg=True")
        try:
            report_v2 = renderer.render(compact_report, use_nlg=True, use_v2=True)
            logger.info(f"✓ Отчёт сгенерирован, длина: {len(report_v2)}")
            logger.info(f"Первые 300 символов:\n{report_v2[:300]}")
            
            # Проверяем формат
            if "🏥 Market Doctor" in report_v2 and "🎯 Решение:" in report_v2 and "🧠 Режим рынка" in report_v2:
                logger.info("✓ V2 формат подтверждён!")
            elif "📦 Фаза:" in report_v2 or "Монета:" in report_v2:
                logger.error("✗ Старый формат! V2 генератор не использовался")
            else:
                logger.warning("⚠ Неизвестный формат")
        except Exception as e:
            logger.exception(f"Ошибка при генерации с use_v2=True: {e}")
        
        # Тест 2: use_v2=False (для сравнения)
        logger.info("\nТест 2: use_v2=False, use_nlg=True")
        try:
            report_nlg = renderer.render(compact_report, use_nlg=True, use_v2=False)
            logger.info(f"✓ Отчёт сгенерирован, длина: {len(report_nlg)}")
            logger.info(f"Первые 200 символов:\n{report_nlg[:200]}")
        except Exception as e:
            logger.exception(f"Ошибка при генерации с use_v2=False: {e}")
        
        logger.info("=" * 80)
        logger.info("Тест завершён")
        logger.info("=" * 80)
        
    except Exception as e:
        logger.exception(f"Ошибка при тестировании: {e}")
        raise

if __name__ == "__main__":
    test_report_generation()











