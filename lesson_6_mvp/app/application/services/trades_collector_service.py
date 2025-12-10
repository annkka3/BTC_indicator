# app/application/services/trades_collector_service.py
"""
Сервис для сбора и кэширования сделок с бирж.
Собирает данные каждый час и хранит их в БД для быстрого доступа.
"""

from typing import List, Dict
from datetime import datetime
import logging

from ...domain.twap_detector.exchange_client import get_exchange_clients

logger = logging.getLogger("alt_forecast.services.trades_collector")


class TradesCollectorService:
    """Сервис для сбора сделок с бирж и сохранения в БД."""
    
    def __init__(self, db):
        """
        Args:
            db: Экземпляр DB для работы с базой данных
        """
        self.db = db
        self.exchange_clients = get_exchange_clients()
        self.symbols = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT"]
    
    def collect_trades_for_symbol(self, symbol: str, window_minutes: int = 60) -> int:
        """
        Собрать сделки для символа за последние N минут.
        
        Args:
            symbol: Символ торговли (например, "BTCUSDT")
            window_minutes: Окно сбора данных в минутах (по умолчанию 60)
        
        Returns:
            Количество собранных сделок
        """
        now_ms = int(datetime.now().timestamp() * 1000)
        since_ms = now_ms - (window_minutes * 60 * 1000)
        collected_at = now_ms
        
        all_trades = []
        
        for client in self.exchange_clients:
            try:
                # Получаем сделки с пагинацией (для Binance) или максимальным лимитом
                trades = client.get_all_trades(symbol, since_ms, until_ms=now_ms)
                
                if not trades:
                    logger.debug(f"No trades from {client.name} for {symbol}")
                    continue
                
                # Преобразуем в формат для БД
                for trade in trades:
                    all_trades.append({
                        "symbol": symbol,
                        "exchange": client.name,
                        "time": trade["time"],
                        "price": trade["price"],
                        "qty": trade["qty"],
                        "is_buyer": trade["is_buyer"],
                        "collected_at": collected_at,
                    })
                
                logger.info(
                    f"Collected {len(trades)} trades from {client.name} for {symbol}"
                )
                
            except Exception as e:
                logger.exception(f"Error collecting trades from {client.name} for {symbol}: {e}")
                continue
        
        # Сохраняем в БД
        if all_trades:
            self.db.upsert_many_trades(all_trades)
            logger.info(f"Saved {len(all_trades)} trades to DB for {symbol}")
        
        return len(all_trades)
    
    def collect_all_symbols(self, window_minutes: int = 60) -> Dict[str, int]:
        """
        Собрать сделки для всех символов.
        
        Args:
            window_minutes: Окно сбора данных в минутах (по умолчанию 60)
        
        Returns:
            Словарь {symbol: количество_собранных_сделок}
        """
        results = {}
        
        for symbol in self.symbols:
            try:
                count = self.collect_trades_for_symbol(symbol, window_minutes)
                results[symbol] = count
            except Exception as e:
                logger.exception(f"Error collecting trades for {symbol}: {e}")
                results[symbol] = 0
        
        return results
    
    def cleanup_old_trades(self, max_age_hours: int = 24) -> int:
        """
        Удалить старые сделки из БД.
        
        Args:
            max_age_hours: Максимальный возраст данных в часах (по умолчанию 24)
        
        Returns:
            Количество удаленных записей
        """
        deleted = self.db.cleanup_old_trades(max_age_hours)
        logger.info(f"Cleaned up {deleted} old trades (older than {max_age_hours} hours)")
        return deleted


