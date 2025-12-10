#!/usr/bin/env python3
"""
Тестовый скрипт для проверки нового генератора v2 на реальных данных.
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
from app.domain.market_diagnostics.report_adapter import ReportAdapter
from app.domain.market_diagnostics.report_generator_v2 import MarketDoctorReportGenerator
from app.domain.market_diagnostics.features import FeatureExtractor
from app.domain.market_diagnostics.indicators import IndicatorCalculator
from app.domain.market_diagnostics.config import DEFAULT_CONFIG

def test_v2_generator():
    """Тестируем новый генератор v2 на реальных данных."""
    logger = logging.getLogger(__name__)
    logger.info("=" * 80)
    logger.info("Тестирование нового генератора v2 на реальных данных")
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
        
        logger.info(f"CompactReport создан: per_tf keys={list(compact_report.per_tf.keys())}")
        
        # Тестируем адаптер
        logger.info("=" * 80)
        logger.info("Тестирование адаптера CompactReport -> MarketSnapshot...")
        logger.info("=" * 80)
        
        adapter = ReportAdapter()
        snapshot = adapter.adapt(compact_report)
        
        logger.info(f"MarketSnapshot создан:")
        logger.info(f"  - Symbol: {snapshot.symbol}")
        logger.info(f"  - Timeframe: {snapshot.timeframe}")
        logger.info(f"  - Price: {snapshot.price:,.0f}")
        logger.info(f"  - Phase: {snapshot.phase}")
        logger.info(f"  - SetupType: {snapshot.setup_type}")
        logger.info(f"  - MicroRegime: {snapshot.micro_regime}")
        logger.info(f"  - Bias: tactical={snapshot.bias.tactical}, strategic={snapshot.bias.strategic}")
        logger.info(f"  - DirectionalScores: long={snapshot.dir_scores.long_score:.1f}, short={snapshot.dir_scores.short_score:.1f}, confidence={snapshot.dir_scores.confidence:.0%}")
        logger.info(f"  - Demand Zone: {snapshot.demand_zone.lower:,.0f}–{snapshot.demand_zone.upper:,.0f}")
        logger.info(f"  - Supply Zone: {snapshot.supply_zone.lower:,.0f}–{snapshot.supply_zone.upper:,.0f}")
        logger.info(f"  - Flow: CVD={snapshot.flow.cvd_change_pct:+.1f}%" if snapshot.flow.cvd_change_pct else "  - Flow: данные недоступны")
        logger.info(f"  - R-Asymmetry: long={snapshot.r_asym.long_r:+.2f}R, short={snapshot.r_asym.short_r:+.2f}R")
        logger.info(f"  - Scenarios: {len(snapshot.scenarios)}")
        
        # Тестируем генератор v2
        logger.info("=" * 80)
        logger.info("Тестирование генератора v2...")
        logger.info("=" * 80)
        
        generator = MarketDoctorReportGenerator()
        
        # Полный отчёт
        logger.info("Генерация полного отчёта...")
        full_report = generator.generate(snapshot, mode="full")
        logger.info(f"Полный отчёт сгенерирован, длина: {len(full_report)} символов")
        
        # Краткий отчёт
        logger.info("Генерация краткого отчёта...")
        short_report = generator.generate(snapshot, mode="short")
        logger.info(f"Краткий отчёт сгенерирован, длина: {len(short_report)} символов")
        
        # Проверяем, что отчёты не содержат дубликатов
        logger.info("=" * 80)
        logger.info("Проверка на дубликаты...")
        logger.info("=" * 80)
        
        # Проверяем, что зоны не упоминаются слишком часто
        demand_zone_text = f"{snapshot.demand_zone.lower:,.0f}–{snapshot.demand_zone.upper:,.0f}"
        supply_zone_text = f"{snapshot.supply_zone.lower:,.0f}–{snapshot.supply_zone.upper:,.0f}"
        
        demand_count = full_report.count(demand_zone_text)
        supply_count = full_report.count(supply_zone_text)
        
        logger.info(f"Зона спроса упоминается {demand_count} раз(а)")
        logger.info(f"Зона предложения упоминается {supply_count} раз(а)")
        
        if demand_count <= 3 and supply_count <= 3:
            logger.info("✓ Дубликаты зон в пределах нормы (≤3 упоминаний)")
        else:
            logger.warning(f"⚠️ Возможны дубликаты: зоны упоминаются {demand_count}/{supply_count} раз")
        
        # Выводим первые 1000 символов полного отчёта
        logger.info("=" * 80)
        logger.info("Первые 1000 символов полного отчёта:")
        logger.info("-" * 80)
        logger.info(full_report[:1000])
        logger.info("-" * 80)
        
        logger.info("=" * 80)
        logger.info("Тест завершён успешно!")
        logger.info("=" * 80)
        
    except Exception as e:
        logger.exception(f"Ошибка при тестировании: {e}")
        raise

if __name__ == "__main__":
    test_v2_generator()











