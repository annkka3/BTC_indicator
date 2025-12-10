# app/application/services/twap_detector_service.py
"""
Сервис для детекции TWAP-алгоритмов с кэшированием результатов.
"""

from typing import Dict, Optional
from datetime import datetime, timedelta
from dataclasses import asdict
import logging

from ...domain.twap_detector import TWAPDetector, TWAPReport

logger = logging.getLogger("alt_forecast.services.twap_detector")


class TWAPDetectorService:
    """Сервис для детекции TWAP-алгоритмов с кэшированием."""
    
    def __init__(self, db=None):
        """
        Инициализация сервиса.
        
        Args:
            db: Экземпляр DB для использования кэшированных данных (опционально)
        """
        self.detector = TWAPDetector(db=db)
        self._cache: Dict[str, Dict] = {}
        self._cache_ttl = timedelta(minutes=5)  # Кэш на 5 минут
    
    def get_twap_report(
        self,
        symbol: str,
        window_minutes: int = 15,
        force_refresh: bool = False
    ) -> Optional[TWAPReport]:
        """
        Получить отчёт по TWAP-алгоритмам для символа.
        
        Args:
            symbol: Символ торговли (например, BTCUSDT)
            window_minutes: Окно анализа в минутах
            force_refresh: Принудительно обновить кэш
        
        Returns:
            TWAPReport или None при ошибке
        """
        cache_key = f"{symbol}:{window_minutes}"
        
        # Проверяем кэш
        if not force_refresh and cache_key in self._cache:
            cached = self._cache[cache_key]
            cache_time = cached.get("timestamp")
            if cache_time and (datetime.now() - cache_time) < self._cache_ttl:
                logger.debug(f"Using cached TWAP report for {symbol}")
                return cached.get("report")
        
        # Получаем свежий отчёт
        try:
            report = self.detector.detect_patterns(symbol, window_minutes)
            
            # Сохраняем в кэш
            self._cache[cache_key] = {
                "report": report,
                "timestamp": datetime.now(),
            }
            
            return report
        except Exception as e:
            logger.exception(f"Error detecting TWAP patterns for {symbol}: {e}")
            return None
    
    def get_multiple_reports(
        self,
        symbols: list[str],
        window_minutes: int = 15
    ) -> Dict[str, Optional[TWAPReport]]:
        """
        Получить отчёты для нескольких символов.
        
        Args:
            symbols: Список символов
            window_minutes: Окно анализа в минутах
        
        Returns:
            Словарь {symbol: TWAPReport или None}
        """
        results = {}
        for symbol in symbols:
            results[symbol] = self.get_twap_report(symbol, window_minutes)
        return results
    
    def clear_cache(self):
        """Очистить кэш."""
        self._cache.clear()
        logger.info("TWAP detector cache cleared")


