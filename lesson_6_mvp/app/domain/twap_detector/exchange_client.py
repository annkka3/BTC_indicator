# app/domain/twap_detector/exchange_client.py
"""
Клиенты для работы с API бирж для получения сделок (trades).
"""

from typing import List, Dict, Optional
from datetime import datetime, timedelta
import logging
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = logging.getLogger("alt_forecast.twap_detector")


class ExchangeClient:
    """Базовый класс для клиентов бирж."""
    
    def __init__(self, name: str, base_url: str):
        self.name = name
        self.base_url = base_url
        self.session = requests.Session()
        retry_strategy = Retry(
            total=3,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)
    
    def get_trades(
        self,
        symbol: str,
        since_ms: int,
        limit: int = 1000
    ) -> List[Dict]:
        """
        Получить сделки с биржи.
        
        Args:
            symbol: Пара торговли (например, BTCUSDT)
            since_ms: Временная метка начала (в миллисекундах)
            limit: Максимальное количество сделок
        
        Returns:
            Список сделок в формате [{"time": ms, "price": float, "qty": float, "is_buyer": bool}, ...]
        """
        raise NotImplementedError
    
    def get_all_trades(
        self,
        symbol: str,
        since_ms: int,
        until_ms: Optional[int] = None
    ) -> List[Dict]:
        """
        Получить ВСЕ сделки за период с пагинацией.
        
        Args:
            symbol: Пара торговли (например, BTCUSDT)
            since_ms: Временная метка начала (в миллисекундах)
            until_ms: Временная метка конца (в миллисекундах), если None - до текущего момента
        
        Returns:
            Список всех сделок за период в формате [{"time": ms, "price": float, "qty": float, "is_buyer": bool}, ...]
        """
        raise NotImplementedError


class BinanceClient(ExchangeClient):
    """Клиент для Binance API."""
    
    def __init__(self):
        super().__init__("Binance", "https://api.binance.com")
    
    def get_trades(self, symbol: str, since_ms: int, limit: int = 1000) -> List[Dict]:
        """Получить сделки с Binance."""
        try:
            # Используем aggTrades для агрегированных сделок
            url = f"{self.base_url}/api/v3/aggTrades"
            params = {
                "symbol": symbol.upper(),
                "startTime": since_ms,
                "limit": min(limit, 1000),  # Binance ограничивает до 1000
            }
            
            logger.debug(f"{self.name}: Requesting trades for {symbol}, since_ms={since_ms}, limit={params['limit']}")
            response = self.session.get(url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()
            
            logger.debug(f"{self.name}: Received {len(data)} trades from API")
            
            trades = []
            for trade in data:
                trades.append({
                    "time": trade["T"],  # Время закрытия агрегированной сделки
                    "price": float(trade["p"]),  # Цена
                    "qty": float(trade["q"]),  # Количество
                    "is_buyer": trade["m"] == False,  # m=False означает покупку (buyer)
                    "exchange": self.name,
                })
            
            logger.info(f"{self.name}: Returning {len(trades)} trades for {symbol}")
            return trades
        except Exception as e:
            logger.error(f"Error fetching trades from {self.name} for {symbol}: {e}", exc_info=True)
            return []
    
    def get_all_trades(self, symbol: str, since_ms: int, until_ms: Optional[int] = None) -> List[Dict]:
        """Получить ВСЕ сделки с Binance за период с пагинацией."""
        all_trades = []
        max_limit = 1000
        current_since = since_ms
        
        try:
            while True:
                url = f"{self.base_url}/api/v3/aggTrades"
                params = {
                    "symbol": symbol.upper(),
                    "startTime": current_since,
                    "limit": max_limit,
                }
                
                if until_ms:
                    params["endTime"] = until_ms
                
                response = self.session.get(url, params=params, timeout=10)
                response.raise_for_status()
                data = response.json()
                
                if not data:
                    break
                
                batch_trades = []
                last_time = current_since
                for trade in data:
                    trade_time = trade["T"]
                    # Проверяем, что сделка в нужном диапазоне
                    if trade_time < since_ms:
                        continue
                    if until_ms and trade_time > until_ms:
                        break
                    
                    batch_trades.append({
                        "time": trade_time,
                        "price": float(trade["p"]),
                        "qty": float(trade["q"]),
                        "is_buyer": trade["m"] == False,
                        "exchange": self.name,
                    })
                    last_time = max(last_time, trade_time)
                
                if not batch_trades:
                    break
                
                all_trades.extend(batch_trades)
                
                # Если получили меньше лимита, значит это последняя страница
                if len(data) < max_limit:
                    break
                
                # Для следующей итерации начинаем с последней сделки + 1мс
                current_since = last_time + 1
                
                # Защита от бесконечного цикла
                if len(all_trades) > 100000:  # Максимум 100k сделок
                    logger.warning(f"Reached max trades limit for {symbol} on {self.name}")
                    break
            
            return all_trades
        except Exception as e:
            logger.error(f"Error fetching all trades from {self.name}: {e}")
            return all_trades if all_trades else []


class BybitClient(ExchangeClient):
    """Клиент для Bybit API."""
    
    def __init__(self):
        super().__init__("Bybit", "https://api.bybit.com")
    
    def get_trades(self, symbol: str, since_ms: int, limit: int = 1000) -> List[Dict]:
        """Получить сделки с Bybit."""
        try:
            # Bybit использует формат BTCUSDT для spot
            url = f"{self.base_url}/v5/market/recent-trade"
            params = {
                "category": "spot",
                "symbol": symbol.upper(),
                "limit": min(limit, 1000),
            }
            
            logger.debug(f"{self.name}: Requesting trades for {symbol}, since_ms={since_ms}, limit={params['limit']}")
            response = self.session.get(url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()
            
            if data.get("retCode") != 0:
                logger.warning(f"{self.name} API error for {symbol}: retCode={data.get('retCode')}, retMsg={data.get('retMsg')}")
                return []
            
            trades = []
            result = data.get("result", {})
            trade_list = result.get("list", [])
            
            logger.debug(f"{self.name}: Received {len(trade_list)} trades from API for {symbol}")
            
            for trade in trade_list:
                trade_time = int(trade["time"])
                # Фильтруем только сделки после since_ms
                if trade_time >= since_ms:
                    trades.append({
                        "time": trade_time,
                        "price": float(trade["price"]),
                        "qty": float(trade["size"]),
                        "is_buyer": trade["side"] == "Buy",
                        "exchange": self.name,
                    })
            
            logger.info(f"{self.name}: Returning {len(trades)} trades (filtered from {len(trade_list)}) for {symbol}")
            return trades
        except Exception as e:
            logger.error(f"Error fetching trades from {self.name} for {symbol}: {e}", exc_info=True)
            return []
    
    def get_all_trades(self, symbol: str, since_ms: int, until_ms: Optional[int] = None) -> List[Dict]:
        """
        Получить сделки с Bybit за период.
        
        Примечание: Bybit API для recent-trade не поддерживает пагинацию через cursor
        и не позволяет запрашивать исторические данные за период. Используем максимальный лимит (1000 сделок).
        Для более длительных периодов данные могут быть неполными.
        """
        # Bybit не поддерживает пагинацию для исторических данных через публичный API
        # Используем обычный метод с максимальным лимитом
        return self.get_trades(symbol, since_ms, limit=1000)


class OKXClient(ExchangeClient):
    """Клиент для OKX API."""
    
    def __init__(self):
        super().__init__("OKX", "https://www.okx.com")
    
    def get_trades(self, symbol: str, since_ms: int, limit: int = 1000) -> List[Dict]:
        """Получить сделки с OKX."""
        try:
            # OKX использует формат BTC-USDT для spot
            okx_symbol = symbol.replace("USDT", "-USDT")
            url = f"{self.base_url}/api/v5/market/trades"
            params = {
                "instId": okx_symbol,
                "limit": min(limit, 500),  # OKX ограничивает до 500
            }
            
            logger.debug(f"{self.name}: Requesting trades for {symbol} (OKX format: {okx_symbol}), since_ms={since_ms}, limit={params['limit']}")
            response = self.session.get(url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()
            
            if data.get("code") != "0":
                logger.warning(f"{self.name} API error for {symbol}: code={data.get('code')}, msg={data.get('msg')}")
                return []
            
            trades = []
            trade_list = data.get("data", [])
            
            logger.debug(f"{self.name}: Received {len(trade_list)} trades from API for {symbol}")
            
            for trade in trade_list:
                trade_time = int(trade["ts"])
                # Фильтруем только сделки после since_ms
                if trade_time >= since_ms:
                    trades.append({
                        "time": trade_time,
                        "price": float(trade["px"]),
                        "qty": float(trade["sz"]),
                        "is_buyer": trade["side"] == "buy",
                        "exchange": self.name,
                    })
            
            logger.info(f"{self.name}: Returning {len(trades)} trades (filtered from {len(trade_list)}) for {symbol}")
            return trades
        except Exception as e:
            logger.error(f"Error fetching trades from {self.name} for {symbol}: {e}", exc_info=True)
            return []
    
    def get_all_trades(self, symbol: str, since_ms: int, until_ms: Optional[int] = None) -> List[Dict]:
        """
        Получить сделки с OKX за период.
        
        Примечание: OKX API не поддерживает получение исторических данных за период
        через публичный эндпоинт trades. Используем максимальный лимит (500 сделок).
        Для более длительных периодов данные могут быть неполными.
        """
        # OKX не поддерживает пагинацию для исторических данных через публичный API
        # Используем обычный метод с максимальным лимитом
        return self.get_trades(symbol, since_ms, limit=500)


class GateClient(ExchangeClient):
    """Клиент для Gate.io API."""
    
    def __init__(self):
        super().__init__("Gate", "https://api.gateio.ws")
    
    def get_trades(self, symbol: str, since_ms: int, limit: int = 1000) -> List[Dict]:
        """Получить сделки с Gate.io."""
        try:
            # Gate.io использует формат BTC_USDT для spot
            gate_symbol = symbol.replace("USDT", "_USDT")
            url = f"{self.base_url}/api/v4/spot/trades"
            params = {
                "currency_pair": gate_symbol,
                "limit": min(limit, 1000),
            }
            
            logger.debug(f"{self.name}: Requesting trades for {symbol} (Gate format: {gate_symbol}), since_ms={since_ms}, limit={params['limit']}")
            response = self.session.get(url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()
            
            logger.debug(f"{self.name}: Received {len(data)} trades from API for {symbol}")
            
            trades = []
            for trade in data:
                # Gate.io может возвращать время как float или строку
                trade_time_raw = trade.get("create_time_ms")
                if isinstance(trade_time_raw, str):
                    trade_time = int(float(trade_time_raw))
                else:
                    trade_time = int(trade_time_raw)
                # Фильтруем только сделки после since_ms
                if trade_time >= since_ms:
                    trades.append({
                        "time": trade_time,
                        "price": float(trade["price"]),
                        "qty": float(trade["amount"]),
                        "is_buyer": trade["side"] == "buy",
                        "exchange": self.name,
                    })
            
            logger.info(f"{self.name}: Returning {len(trades)} trades (filtered from {len(data)}) for {symbol}")
            return trades
        except Exception as e:
            logger.error(f"Error fetching trades from {self.name} for {symbol}: {e}", exc_info=True)
            return []
    
    def get_all_trades(self, symbol: str, since_ms: int, until_ms: Optional[int] = None) -> List[Dict]:
        """
        Получить сделки с Gate.io за период.
        
        Примечание: Gate.io API не поддерживает получение исторических данных за период
        через публичный эндпоинт trades. Используем максимальный лимит (1000 сделок).
        Для более длительных периодов данные могут быть неполными.
        """
        # Gate.io не поддерживает пагинацию для исторических данных через публичный API
        # Используем обычный метод с максимальным лимитом
        return self.get_trades(symbol, since_ms, limit=1000)


def get_exchange_clients() -> List[ExchangeClient]:
    """Получить список всех доступных клиентов бирж."""
    return [
        BinanceClient(),
        BybitClient(),
        OKXClient(),
        GateClient(),
    ]

