# app/infrastructure/market_data_service.py
"""
Сервис для получения рыночных данных.

Централизует работу с данными:
- OHLCV данные (из БД, файлов, внешних API)
- Данные деривативов (Binance, CoinGlass)
- Кэширование и retry логика
"""

import logging
from typing import Optional, Dict
import pandas as pd
from datetime import datetime, timedelta
from functools import lru_cache
import time

logger = logging.getLogger("alt_forecast.market_data")


class DerivativesSnapshot:
    """Снимок данных деривативов."""
    
    def __init__(
        self,
        funding: Optional[float] = None,
        oi: Optional[float] = None,
        oi_change_pct: Optional[float] = None,
        cvd_spot_slope: Optional[float] = None,
        cvd_fut_slope: Optional[float] = None,
        quality: str = "none"
    ):
        self.funding = funding
        self.oi = oi
        self.oi_change_pct = oi_change_pct
        self.cvd_spot_slope = cvd_spot_slope
        self.cvd_fut_slope = cvd_fut_slope
        self.quality = quality  # "full", "partial", "none"
    
    def to_dict(self) -> Dict[str, float]:
        """Преобразовать в словарь для использования в анализаторе."""
        result = {}
        if self.funding is not None:
            result['funding_rate'] = self.funding
        if self.oi_change_pct is not None:
            result['oi_change_pct'] = self.oi_change_pct
        if self.cvd_spot_slope is not None:
            result['cvd'] = self.cvd_spot_slope
        elif self.cvd_fut_slope is not None:
            result['cvd'] = self.cvd_fut_slope
        return result


class MarketDataService:
    """Сервис для получения рыночных данных."""
    
    def __init__(self, db=None):
        """
        Инициализация сервиса.
        
        Args:
            db: Экземпляр базы данных для получения OHLCV данных
        """
        self.db = db
        self._cache_ohlcv = {}  # Простой in-memory кэш
        self._cache_derivatives = {}
        self._cache_ttl = 60  # TTL кэша в секундах
    
    async def get_ohlcv(
        self,
        symbol: str,
        timeframe: str,
        limit: int = 500
    ) -> Optional[pd.DataFrame]:
        """
        Получить OHLCV данные.
        
        Args:
            symbol: Символ монеты
            timeframe: Таймфрейм (1h, 4h, 1d)
            limit: Количество баров
        
        Returns:
            DataFrame с OHLCV данными или None
        """
        # Проверяем кэш
        cache_key = f"{symbol}:{timeframe}:{limit}"
        if cache_key in self._cache_ohlcv:
            cached_data, cached_time = self._cache_ohlcv[cache_key]
            if time.time() - cached_time < self._cache_ttl:
                logger.debug(f"Using cached OHLCV data for {cache_key}")
                return cached_data
        
        # Получаем данные из БД
        if self.db:
            try:
                # Нормализуем символ
                symbol_variants = self._normalize_symbol(symbol)
                
                for sym_variant in symbol_variants:
                    try:
                        # Пробуем получить данные из БД
                        rows = self.db.last_n(sym_variant, timeframe, limit)
                        if rows and len(rows) > 0:
                            df = self._rows_to_dataframe(rows)
                            if df is not None and not df.empty:
                                # Кэшируем результат
                                self._cache_ohlcv[cache_key] = (df, time.time())
                                logger.debug(f"Loaded OHLCV from DB: {sym_variant} {timeframe} ({len(df)} bars)")
                                return df
                    except AttributeError:
                        # Если у db нет метода last_n, пропускаем
                        logger.debug(f"DB does not have last_n method")
                        break
                    except Exception as e:
                        logger.debug(f"Failed to load {sym_variant} {timeframe} from DB: {e}")
                        continue
            except Exception as e:
                logger.debug(f"Error getting OHLCV from DB: {e}")
        
        # Fallback на data_adapter
        try:
            from ...ml.data_adapter import load_bars_from_project
            symbol_variants = self._normalize_symbol(symbol)
            
            for sym_variant in symbol_variants:
                try:
                    # Пробуем загрузить через data_adapter
                    df = load_bars_from_project(sym_variant, timeframe, limit=limit)
                    if df is not None and not df.empty:
                        df = self._normalize_dataframe(df)
                        if df is not None and not df.empty:
                            # Кэшируем результат
                            self._cache_ohlcv[cache_key] = (df, time.time())
                            logger.debug(f"Loaded OHLCV from data_adapter: {sym_variant} {timeframe} ({len(df)} bars)")
                            return df
                except FileNotFoundError:
                    # Файл не найден - пробуем следующий вариант
                    continue
                except ImportError:
                    # Модуль data_adapter не найден
                    logger.debug("data_adapter module not found")
                    break
                except Exception as e:
                    logger.debug(f"Failed to load {sym_variant} {timeframe} via data_adapter: {e}")
                    continue
        except ImportError:
            logger.debug("data_adapter module not available")
        except Exception as e:
            logger.debug(f"Error getting OHLCV from data_adapter: {e}")
        
        logger.warning(f"Could not get OHLCV data for {symbol} {timeframe}")
        return None
    
    async def get_derivatives(
        self,
        symbol: str,
        timeframe: str = "1h"
    ) -> DerivativesSnapshot:
        """
        Получить данные деривативов.
        
        Args:
            symbol: Символ монеты
            timeframe: Таймфрейм (для контекста, не используется напрямую)
        
        Returns:
            DerivativesSnapshot с данными деривативов
        """
        # Проверяем кэш
        cache_key = f"{symbol}:derivatives"
        if cache_key in self._cache_derivatives:
            cached_data, cached_time = self._cache_derivatives[cache_key]
            if time.time() - cached_time < self._cache_ttl:
                logger.debug(f"Using cached derivatives data for {cache_key}")
                return cached_data
        
        snapshot = DerivativesSnapshot(quality="none")
        
        # Получаем funding rate из Binance
        try:
            from .market_data import binance_funding_and_mark
            binance_symbol = symbol.upper()
            if not binance_symbol.endswith('USDT'):
                binance_symbol = f"{binance_symbol}USDT"
            
            funding_data = binance_funding_and_mark(binance_symbol)
            snapshot.funding = funding_data.get('fundingRate', 0.0)
            snapshot.quality = "partial"
        except Exception as e:
            logger.debug(f"Could not get funding rate for {symbol}: {e}")
        
        # Получаем OI и CVD из CoinGlass
        try:
            from .derivatives_client import get_oi_and_cvd
            oi_cvd_data = get_oi_and_cvd(symbol)
            
            if oi_cvd_data.get('oi_change_pct') is not None:
                snapshot.oi_change_pct = oi_cvd_data.get('oi_change_pct', 0.0)
            
            if oi_cvd_data.get('cvd') is not None:
                snapshot.cvd_spot_slope = oi_cvd_data.get('cvd', 0.0)
            
            if snapshot.funding is not None and snapshot.oi_change_pct is not None:
                snapshot.quality = "full"
            elif snapshot.funding is not None or snapshot.oi_change_pct is not None:
                snapshot.quality = "partial"
        except Exception as e:
            logger.debug(f"Could not get OI/CVD from CoinGlass for {symbol}: {e}")
        
        # Кэшируем результат
        self._cache_derivatives[cache_key] = (snapshot, time.time())
        
        return snapshot
    
    def _normalize_symbol(self, symbol: str) -> list[str]:
        """Нормализовать символ и вернуть список вариантов."""
        symbol = symbol.upper().strip().replace("/", "").replace("-", "")
        variants = []
        
        if ":" in symbol:
            variants.append(symbol)
            return variants
        
        variants.append(symbol)
        
        if len(symbol) <= 5 and not symbol.endswith("USDT"):
            variants.append(f"{symbol}USDT")
        
        if symbol.endswith("USDT"):
            base = symbol[:-4]
            if len(base) <= 5:
                variants.insert(0, base)
        
        for v in variants[:]:
            if ":" not in v:
                variants.append(f"BINANCE:{v}")
        
        seen = set()
        unique_variants = []
        for v in variants:
            if v not in seen:
                seen.add(v)
                unique_variants.append(v)
        
        return unique_variants
    
    def _rows_to_dataframe(self, rows) -> pd.DataFrame:
        """Преобразовать строки из БД в DataFrame."""
        if not rows:
            return pd.DataFrame()
        
        data = []
        for row in rows:
            # БД возвращает кортежи вида (ts, o, h, l, c, v)
            if isinstance(row, (list, tuple)) and len(row) >= 5:
                try:
                    ts = int(row[0])
                    o = float(row[1])
                    h = float(row[2])
                    l = float(row[3])
                    c = float(row[4])
                    v = float(row[5]) if len(row) > 5 and row[5] is not None else 0.0
                    
                    # Проверяем на валидность данных
                    if not (pd.isna(o) or pd.isna(h) or pd.isna(l) or pd.isna(c)):
                        data.append({
                            'ts': ts,
                            'open': o,
                            'high': h,
                            'low': l,
                            'close': c,
                            'volume': v
                        })
                except (ValueError, TypeError, IndexError) as e:
                    logger.debug(f"Error parsing row: {e}, row: {row}")
                    continue
        
        if not data:
            return pd.DataFrame()
        
        df = pd.DataFrame(data)
        
        # Сортируем по времени
        df = df.sort_values('ts')
        
        # Преобразуем ts в datetime и устанавливаем как индекс
        df['ts'] = pd.to_datetime(df['ts'], unit='ms', errors='coerce')
        df = df.set_index('ts')
        
        # Убираем строки с NaN в критических колонках
        df = df.dropna(subset=['open', 'high', 'low', 'close'])
        
        return df
    
    def _normalize_dataframe(self, df: pd.DataFrame) -> pd.DataFrame:
        """Нормализовать DataFrame (колонки, типы, сортировка)."""
        if df is None or df.empty:
            return pd.DataFrame()
        
        required_cols = ['open', 'high', 'low', 'close', 'volume']
        
        # Нормализуем названия колонок
        col_mapping = {
            'o': 'open', 'h': 'high', 'l': 'low', 'c': 'close', 'v': 'volume',
            'Open': 'open', 'High': 'high', 'Low': 'low', 'Close': 'close', 'Volume': 'volume'
        }
        
        for old_col, new_col in col_mapping.items():
            if old_col in df.columns and new_col not in df.columns:
                df[new_col] = df[old_col]
        
        # Проверяем наличие всех колонок
        if not all(col in df.columns for col in required_cols):
            return pd.DataFrame()
        
        # Убираем строки с NaN в критических колонках
        df = df.dropna(subset=['open', 'high', 'low', 'close'])
        
        # Сортируем по индексу (если это DatetimeIndex)
        if isinstance(df.index, pd.DatetimeIndex):
            df = df.sort_index()
        elif 'timestamp' in df.columns:
            df = df.sort_values('timestamp')
        
        return df[required_cols]

