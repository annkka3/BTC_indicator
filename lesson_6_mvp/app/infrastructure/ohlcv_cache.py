# app/infrastructure/ohlcv_cache.py
"""
Кэш OHLCV данных с TTL.
"""

import time
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from threading import Lock
from ..domain.models import Metric, Timeframe

# TTL для кэша OHLCV (45 секунд по умолчанию)
OHLCV_TTL = float(__import__("os").getenv("OHLCV_TTL", "45"))


@dataclass
class CachedOHLCV:
    """Кэшированные OHLCV данные."""
    data: List[Tuple[int, float, float, float, float, Optional[float]]]  # [(ts, o, h, l, c, v), ...]
    timestamp: float = field(default_factory=time.time)
    metric: str = ""
    timeframe: str = ""
    
    def is_expired(self, ttl: float = OHLCV_TTL) -> bool:
        """Проверить, истек ли кэш."""
        return time.time() - self.timestamp > ttl


class OHLCVCache:
    """Кэш OHLCV данных с TTL."""
    
    def __init__(self, ttl: float = OHLCV_TTL):
        self._cache: Dict[Tuple[str, str], CachedOHLCV] = {}
        self._lock = Lock()
        self._ttl = ttl
    
    def get(self, metric: Metric, timeframe: Timeframe) -> Optional[List[Tuple[int, float, float, float, float, Optional[float]]]]:
        """Получить данные из кэша."""
        key = (str(metric), str(timeframe))
        
        with self._lock:
            cached = self._cache.get(key)
            if cached is None:
                return None
            
            if cached.is_expired(self._ttl):
                # Удаляем истекший кэш
                del self._cache[key]
                return None
            
            return cached.data
    
    def set(self, metric: Metric, timeframe: Timeframe, data: List[Tuple[int, float, float, float, float, Optional[float]]]):
        """Сохранить данные в кэш."""
        key = (str(metric), str(timeframe))
        
        with self._lock:
            self._cache[key] = CachedOHLCV(
                data=data,
                timestamp=time.time(),
                metric=str(metric),
                timeframe=str(timeframe)
            )
    
    def clear(self, metric: Optional[Metric] = None, timeframe: Optional[Timeframe] = None):
        """Очистить кэш."""
        with self._lock:
            if metric is None and timeframe is None:
                # Очистить весь кэш
                self._cache.clear()
            elif metric is not None and timeframe is not None:
                # Очистить конкретный ключ
                key = (str(metric), str(timeframe))
                self._cache.pop(key, None)
            else:
                # Очистить по частичному ключу
                keys_to_remove = []
                for key in self._cache.keys():
                    if metric is not None and key[0] != str(metric):
                        continue
                    if timeframe is not None and key[1] != str(timeframe):
                        continue
                    keys_to_remove.append(key)
                
                for key in keys_to_remove:
                    self._cache.pop(key, None)
    
    def cleanup_expired(self):
        """Очистить истекшие записи из кэша."""
        with self._lock:
            keys_to_remove = []
            for key, cached in self._cache.items():
                if cached.is_expired(self._ttl):
                    keys_to_remove.append(key)
            
            for key in keys_to_remove:
                self._cache.pop(key, None)
    
    def get_stats(self) -> Dict[str, any]:
        """Получить статистику кэша."""
        with self._lock:
            total = len(self._cache)
            expired = sum(1 for c in self._cache.values() if c.is_expired(self._ttl))
            
            return {
                "total_entries": total,
                "expired_entries": expired,
                "active_entries": total - expired,
                "ttl_seconds": self._ttl,
            }


# Глобальный экземпляр кэша
_global_cache: Optional[OHLCVCache] = None


def get_ohlcv_cache(ttl: Optional[float] = None) -> OHLCVCache:
    """Получить глобальный экземпляр кэша."""
    global _global_cache
    if _global_cache is None:
        _global_cache = OHLCVCache(ttl=ttl or OHLCV_TTL)
    return _global_cache















