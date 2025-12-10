# app/application/services/traditional_markets_service.py
"""
Service for traditional markets data (S&P500, Gold, Oil).
"""

from typing import Dict, Optional
import logging
import requests
import os

logger = logging.getLogger("alt_forecast.services.traditional_markets")


class TraditionalMarketsService:
    """Сервис для получения данных о традиционных рынках."""
    
    def __init__(self):
        """Инициализация сервиса."""
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (compatible; ALT-Forecast-Bot/1.0)"
        })
    
    def get_sp500_price(self) -> Optional[Dict]:
        """
        Получить текущую цену S&P500.
        
        Использует Yahoo Finance через yfinance или альтернативные источники.
        
        Returns:
            Dict с данными о S&P500 или None
        """
        try:
            # Пробуем использовать yfinance если доступен
            try:
                import yfinance as yf
                # Пробуем разные тикеры для S&P500
                tickers = ["^GSPC", "SPY", "^SPX"]
                for ticker in tickers:
                    try:
                        spx = yf.Ticker(ticker)
                        info = spx.history(period="5d")  # Увеличиваем период для надежности
                        if info.empty:
                            logger.debug("Ticker %s returned empty data", ticker)
                            continue
                        if len(info) < 2:
                            logger.debug("Ticker %s returned only %d rows, need at least 2", ticker, len(info))
                            continue
                        
                        current = float(info["Close"].iloc[-1])
                        prev = float(info["Close"].iloc[-2])
                        change = current - prev
                        change_pct = (change / prev * 100.0) if prev > 0 else 0.0
                        
                        logger.info("Successfully fetched S&P500 data from ticker %s: price=%.2f, change=%.2f%%", 
                                   ticker, current, change_pct)
                        
                        return {
                            "symbol": "SPX",
                            "name": "S&P 500",
                            "price": round(current, 2),
                            "change_24h": round(change, 2),
                            "change_percent_24h": round(change_pct, 2),
                        }
                    except Exception as e:
                        logger.warning("Ticker %s failed: %s", ticker, e, exc_info=True)
                        continue
            except ImportError:
                logger.warning("yfinance not available, trying alternative")
            except Exception as e:
                logger.warning("yfinance failed: %s", e, exc_info=True)
            
            # Альтернатива: используем Alpha Vantage если доступен API ключ
            api_key = os.getenv("ALPHA_VANTAGE_API_KEY")
            if api_key:
                # Пробуем разные символы
                symbols = ["SPY", "^GSPC", "SPX"]
                for symbol in symbols:
                    try:
                        url = f"https://www.alphavantage.co/query"
                        params = {
                            "function": "GLOBAL_QUOTE",
                            "symbol": symbol,
                            "apikey": api_key
                        }
                        response = self.session.get(url, params=params, timeout=10)
                        if response.status_code == 200:
                            data = response.json()
                            quote = data.get("Global Quote", {})
                            if quote and quote.get("05. price"):
                                price = float(quote.get("05. price", 0))
                                change = float(quote.get("09. change", 0))
                                change_pct_str = quote.get("10. change percent", "0%")
                                change_pct = float(change_pct_str.replace("%", "").replace("+", ""))
                                
                                return {
                                    "symbol": "SPX",
                                    "name": "S&P 500",
                                    "price": round(price, 2),
                                    "change_24h": round(change, 2),
                                    "change_percent_24h": round(change_pct, 2),
                                }
                    except Exception as e:
                        logger.debug("Alpha Vantage symbol %s failed: %s", symbol, e)
                        continue
            
            # Fallback: пробуем простой публичный API
            try:
                # Используем finnhub или другой бесплатный API
                url = "https://query1.finance.yahoo.com/v8/finance/chart/^GSPC?interval=1d&range=5d"
                response = self.session.get(url, timeout=10)
                if response.status_code == 200:
                    data = response.json()
                    result = data.get("chart", {}).get("result", [])
                    if result:
                        quotes = result[0].get("indicators", {}).get("quote", [])
                        if quotes and len(quotes) > 0:
                            closes = quotes[0].get("close", [])
                            if len(closes) >= 2:
                                current = float([c for c in closes if c is not None][-1])
                                prev = float([c for c in closes if c is not None][-2])
                                change = current - prev
                                change_pct = (change / prev * 100.0) if prev > 0 else 0.0
                                
                                logger.info("Successfully fetched S&P500 from Yahoo Finance API: price=%.2f", current)
                                
                                return {
                                    "symbol": "SPX",
                                    "name": "S&P 500",
                                    "price": round(current, 2),
                                    "change_24h": round(change, 2),
                                    "change_percent_24h": round(change_pct, 2),
                                }
            except Exception as e:
                logger.debug("Yahoo Finance API fallback failed: %s", e)
            
            # Fallback: возвращаем None если не удалось получить данные
            logger.warning("Could not fetch S&P500 price from any source. Install yfinance: pip install yfinance")
            return None
        except Exception as e:
            logger.exception("Failed to get S&P500 price: %s", e)
            return None
    
    def get_gold_price(self) -> Optional[Dict]:
        """
        Получить текущую цену золота.
        
        Returns:
            Dict с данными о золоте или None
        """
        try:
            # Пробуем использовать yfinance
            try:
                import yfinance as yf
                gold = yf.Ticker("GC=F")  # Gold Futures
                info = gold.history(period="2d")
                if not info.empty:
                    current = float(info["Close"].iloc[-1])
                    prev = float(info["Close"].iloc[-2]) if len(info) > 1 else current
                    change = current - prev
                    change_pct = (change / prev * 100.0) if prev > 0 else 0.0
                    
                    return {
                        "symbol": "XAU",
                        "name": "Gold",
                        "price_usd": round(current, 2),
                        "price_oz": round(current, 2),  # цена за унцию
                        "change_24h": round(change, 2),
                        "change_percent_24h": round(change_pct, 2),
                    }
            except ImportError:
                logger.debug("yfinance not available for gold")
            except Exception as e:
                logger.warning("yfinance gold failed: %s", e)
            
            # Альтернатива: metals-api.com если доступен API ключ
            api_key = os.getenv("METALS_API_KEY")
            if api_key:
                try:
                    url = "https://api.metals.live/v1/spot/gold"
                    headers = {"x-api-key": api_key}
                    response = self.session.get(url, headers=headers, timeout=10)
                    if response.status_code == 200:
                        data = response.json()
                        price = float(data.get("price", 0))
                        change = float(data.get("change", 0))
                        change_pct = float(data.get("changePercent", 0))
                        
                        return {
                            "symbol": "XAU",
                            "name": "Gold",
                            "price_usd": round(price, 2),
                            "price_oz": round(price, 2),
                            "change_24h": round(change, 2),
                            "change_percent_24h": round(change_pct, 2),
                        }
                except Exception as e:
                    logger.warning("metals-api failed: %s", e)
            
            # Fallback: CoinGecko для золота (если доступен)
            try:
                url = "https://api.coingecko.com/api/v3/simple/price"
                params = {"ids": "pax-gold", "vs_currencies": "usd", "include_24hr_change": "true"}
                response = self.session.get(url, params=params, timeout=10)
                if response.status_code == 200:
                    data = response.json()
                    paxg = data.get("pax-gold", {})
                    if paxg:
                        price = float(paxg.get("usd", 0))
                        change_pct = float(paxg.get("usd_24h_change", 0))
                        change = price * (change_pct / 100.0)
                        
                        return {
                            "symbol": "XAU",
                            "name": "Gold",
                            "price_usd": round(price, 2),
                            "price_oz": round(price, 2),
                            "change_24h": round(change, 2),
                            "change_percent_24h": round(change_pct, 2),
                        }
            except Exception as e:
                logger.warning("CoinGecko gold failed: %s", e)
            
            logger.warning("Could not fetch gold price from any source")
            return None
        except Exception as e:
            logger.exception("Failed to get gold price: %s", e)
            return None
    
    def get_oil_price(self) -> Optional[Dict]:
        """
        Получить текущую цену нефти (WTI Crude Oil).
        
        Returns:
            Dict с данными о нефти или None
        """
        try:
            # Пробуем использовать yfinance
            try:
                import yfinance as yf
                # Пробуем разные тикеры для нефти
                tickers = ["CL=F", "USO", "OIL"]  # WTI Futures, Oil ETF, Oil ETF альтернативный
                for ticker in tickers:
                    try:
                        oil = yf.Ticker(ticker)
                        info = oil.history(period="5d")  # Увеличиваем период для надежности
                        if info.empty:
                            logger.debug("Oil ticker %s returned empty data", ticker)
                            continue
                        if len(info) < 2:
                            logger.debug("Oil ticker %s returned only %d rows, need at least 2", ticker, len(info))
                            continue
                        
                        current = float(info["Close"].iloc[-1])
                        prev = float(info["Close"].iloc[-2])
                        change = current - prev
                        change_pct = (change / prev * 100.0) if prev > 0 else 0.0
                        
                        logger.info("Successfully fetched Oil data from ticker %s: price=%.2f, change=%.2f%%", 
                                   ticker, current, change_pct)
                        
                        # Если это ETF (USO, OIL), цена будет отличаться от фьючерса
                        # USO обычно около $70-80, что примерно соответствует $70-80 за баррель
                        # Но лучше использовать фьючерс если доступен
                        if ticker == "CL=F":
                            # Это фьючерс, используем напрямую
                            return {
                                "symbol": "WTI",
                                "name": "WTI Crude Oil",
                                "price_usd": round(current, 2),
                                "change_24h": round(change, 2),
                                "change_percent_24h": round(change_pct, 2),
                            }
                        elif ticker in ["USO", "OIL"]:
                            # ETF, используем как fallback
                            return {
                                "symbol": "WTI",
                                "name": "WTI Crude Oil",
                                "price_usd": round(current, 2),
                                "change_24h": round(change, 2),
                                "change_percent_24h": round(change_pct, 2),
                            }
                    except Exception as e:
                        logger.warning("Oil ticker %s failed: %s", ticker, e, exc_info=True)
                        continue
            except ImportError:
                logger.warning("yfinance not available for oil")
            except Exception as e:
                logger.warning("yfinance oil failed: %s", e, exc_info=True)
            
            # Альтернатива: Alpha Vantage если доступен
            api_key = os.getenv("ALPHA_VANTAGE_API_KEY")
            if api_key:
                # Пробуем разные символы для нефти
                symbols = ["USO", "OIL", "CL=F"]
                for symbol in symbols:
                    try:
                        url = f"https://www.alphavantage.co/query"
                        params = {
                            "function": "GLOBAL_QUOTE",
                            "symbol": symbol,
                            "apikey": api_key
                        }
                        response = self.session.get(url, params=params, timeout=10)
                        if response.status_code == 200:
                            data = response.json()
                            quote = data.get("Global Quote", {})
                            if quote and quote.get("05. price"):
                                price = float(quote.get("05. price", 0))
                                change = float(quote.get("09. change", 0))
                                change_pct_str = quote.get("10. change percent", "0%")
                                change_pct = float(change_pct_str.replace("%", "").replace("+", ""))
                                
                                return {
                                    "symbol": "WTI",
                                    "name": "WTI Crude Oil",
                                    "price_usd": round(price, 2),
                                    "change_24h": round(change, 2),
                                    "change_percent_24h": round(change_pct, 2),
                                }
                    except Exception as e:
                        logger.debug("Alpha Vantage oil symbol %s failed: %s", symbol, e)
                        continue
            
            # Fallback: пробуем простой публичный API
            try:
                # Используем Yahoo Finance API напрямую
                url = "https://query1.finance.yahoo.com/v8/finance/chart/CL=F?interval=1d&range=5d"
                response = self.session.get(url, timeout=10)
                if response.status_code == 200:
                    data = response.json()
                    result = data.get("chart", {}).get("result", [])
                    if result:
                        quotes = result[0].get("indicators", {}).get("quote", [])
                        if quotes and len(quotes) > 0:
                            closes = quotes[0].get("close", [])
                            if len(closes) >= 2:
                                current = float([c for c in closes if c is not None][-1])
                                prev = float([c for c in closes if c is not None][-2])
                                change = current - prev
                                change_pct = (change / prev * 100.0) if prev > 0 else 0.0
                                
                                logger.info("Successfully fetched Oil from Yahoo Finance API: price=%.2f", current)
                                
                                return {
                                    "symbol": "WTI",
                                    "name": "WTI Crude Oil",
                                    "price_usd": round(current, 2),
                                    "change_24h": round(change, 2),
                                    "change_percent_24h": round(change_pct, 2),
                                }
            except Exception as e:
                logger.debug("Yahoo Finance API fallback for oil failed: %s", e)
            
            logger.warning("Could not fetch oil price from any source")
            return None
        except Exception as e:
            logger.exception("Failed to get oil price: %s", e)
            return None
    
    def get_all_traditional_markets(self) -> Dict:
        """
        Получить данные обо всех традиционных рынках.
        
        Returns:
            Dict с данными о S&P500, золоте и нефти
        """
        return {
            "sp500": self.get_sp500_price(),
            "gold": self.get_gold_price(),
            "oil": self.get_oil_price(),
        }

