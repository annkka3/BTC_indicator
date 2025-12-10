# app/application/services/market_data_service.py
"""
Service for market data from external APIs (CoinGecko, Binance, etc.).
"""

from typing import List, Dict, Tuple, Optional
import logging

logger = logging.getLogger("alt_forecast.services.market_data")


class MarketDataService:
    """Сервис для получения рыночных данных."""
    
    def __init__(self):
        """Инициализация сервиса."""
        pass
    
    def get_top_movers(self, vs: str = "usd", tf: str = "24h", limit_each: int = 5, top: int = 500) -> Tuple[List[Dict], List[Dict], List[Dict], str]:
        """
        Получить топ движущихся монет.
        
        Args:
            vs: Валюта (usd, eur, etc.)
            tf: Таймфрейм (1h, 24h, 7d)
            limit_each: Количество топ/флоп для возврата
            top: Ограничение по топу (100, 200, 300, 400, 500)
        
        Returns:
            Tuple: (coins, gainers, losers, tf)
        """
        from ...infrastructure.coingecko import top_movers
        return top_movers(vs=vs, tf=tf, limit_each=limit_each, top=top)
    
    def get_global_stats(self) -> Dict:
        """Получить глобальную статистику рынка."""
        from ...infrastructure.coingecko import global_stats
        return global_stats()
    
    def get_trending(self) -> List[Dict]:
        """Получить трендовые монеты."""
        from ...infrastructure.coingecko import trending
        return trending()
    
    def get_categories(self) -> List[Dict]:
        """Получить категории криптовалют."""
        from ...infrastructure.coingecko import categories
        return categories()
    
    def get_markets_by_category(self, category: str, vs: str = "usd") -> List[Dict]:
        """Получить монеты по категории."""
        from ...infrastructure.coingecko import markets_by_category
        return markets_by_category(category, vs=vs)

