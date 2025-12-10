#!/usr/bin/env python3
"""
Прямой тест генерации отчёта - вызывает методы генерации напрямую, минуя Telegram API.
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

def test_direct_report_generation():
    """Прямой тест генерации отчёта."""
    logger = logging.getLogger(__name__)
    logger.info("=" * 80)
    logger.info("Прямой тест генерации отчёта (минуя Telegram API)")
    logger.info("=" * 80)
    
    try:
        from app.infrastructure.db import DB
        from app.domain.market_diagnostics.analyzer import MarketAnalyzer
        from app.domain.market_diagnostics.report_builder import ReportBuilder
        from app.domain.market_diagnostics.compact_report import CompactReportRenderer
        from app.domain.market_diagnostics.features import FeatureExtractor
        from app.domain.market_diagnostics.indicators import IndicatorCalculator
        from app.domain.market_diagnostics.config import DEFAULT_CONFIG
        from app.domain.market_diagnostics.trade_planner import TradePlanner
        
        symbol = "BTC"
        timeframe = "1h"
        
        logger.info(f"Параметры: symbol={symbol}, tf={timeframe}")
        
        # Инициализация
        db_path = os.path.join(os.path.dirname(__file__), "data", "data.db")
        if not os.path.exists(db_path):
            db_path = "./data/data.db"
        
        db = DB(path=db_path)
        
        # Получаем данные
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
        
        logger.info("✓ Диагностика выполнена")
        
        # Строим торговый план
        trade_planner = TradePlanner(DEFAULT_CONFIG)
        trade_plan = trade_planner.build_plan(diagnostics, df, indicators)
        
        logger.info("✓ Торговый план построен")
        
        # Получаем текущую цену
        current_price = float(df['close'].iloc[-1])
        
        # Строим compact_report
        report_builder = ReportBuilder()
        compact_report = report_builder.build_compact_report(
            symbol=symbol,
            target_tf=timeframe,
            diagnostics={timeframe: diagnostics},
            indicators={timeframe: indicators},
            features={timeframe: features},
            derivatives={timeframe: {}},
            trade_plan=trade_plan,
            current_price=current_price
        )
        
        logger.info(f"✓ CompactReport создан: per_tf_count={len(compact_report.per_tf)}, per_tf_keys={list(compact_report.per_tf.keys())}")
        
        # Рендерим отчёт с use_v2=True
        logger.info("=" * 80)
        logger.info("Генерация отчёта с use_v2=True")
        logger.info("=" * 80)
        
        renderer = CompactReportRenderer()
        use_v2 = True  # Включаем v2 генератор
        
        report = renderer.render(compact_report, use_nlg=True, use_v2=use_v2)
        
        logger.info("=" * 80)
        logger.info("ОТЧЁТ СГЕНЕРИРОВАН")
        logger.info("=" * 80)
        logger.info(f"Длина отчёта: {len(report)} символов")
        logger.info("=" * 80)
        logger.info("ПЕРВЫЕ 800 СИМВОЛОВ:")
        logger.info("-" * 80)
        logger.info(report[:800])
        logger.info("-" * 80)
        
        # Проверяем формат
        if "🏥 Market Doctor" in report and "🎯 Решение:" in report and "🧠 Режим рынка" in report:
            logger.info("✓ V2 ФОРМАТ ПОДТВЕРЖДЁН!")
            logger.info("Генератор v2 работает корректно!")
        elif "📦 Фаза:" in report or "Монета:" in report:
            logger.error("✗ СТАРЫЙ ФОРМАТ! V2 генератор не использовался")
            logger.error("Проверьте логи выше для диагностики")
        else:
            logger.warning("⚠ Неизвестный формат")
            logger.info(f"Первые 500 символов для анализа:\n{report[:500]}")
        
        logger.info("=" * 80)
        logger.info("ПОЛНЫЙ ОТЧЁТ:")
        logger.info("=" * 80)
        logger.info(report)
        logger.info("=" * 80)
        
    except Exception as e:
        logger.exception(f"Ошибка при тестировании: {e}")
        raise

if __name__ == "__main__":
    test_direct_report_generation()











