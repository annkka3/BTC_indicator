# app/infrastructure/cache.py
import time, threading
from functools import wraps
from typing import Any, Dict, Tuple

_locks: Dict[Tuple, threading.Lock] = {}
_cache: Dict[Tuple, Tuple[float, Any]] = {}

def cached(ttl: int, key_fn=None, stale_ok: bool = True):
    """
    Декоратор кэширования с TTL и stale-while-revalidate.
    Один и тот же ключ не выполняет конкурентно несколько внешних запросов.
    """
    def deco(fn):
        @wraps(fn)
        def w(*args, **kwargs):
            key = (fn.__name__, key_fn(*args, **kwargs) if key_fn else (args, tuple(sorted(kwargs.items()))))
            now = time.time()
            ts, val = _cache.get(key, (0.0, None))

            # свежий кэш
            if val is not None and (now - ts) < ttl:
                return val

            # отдаём устаревший кэш и рефрешим в фоне
            if stale_ok and val is not None:
                threading.Thread(target=_refresh, args=(fn, key, args, kwargs), daemon=True).start()
                return val

            # дедупликация одновременных запросов
            lock = _locks.setdefault(key, threading.Lock())
            with lock:
                ts2, val2 = _cache.get(key, (0.0, None))
                if val2 is not None and (time.time() - ts2) < ttl:
                    return val2
                try:
                    out = fn(*args, **kwargs)
                    _cache[key] = (time.time(), out)
                    return out
                except Exception:
                    # Если функция упала, но есть stale данные, вернём их
                    if stale_ok and val is not None:
                        return val
                    # Иначе пробрасываем исключение
                    raise
        return w
    return deco

def _refresh(fn, key, args, kwargs):
    try:
        out = fn(*args, **kwargs)
        _cache[key] = (time.time(), out)
    except Exception:
        # при фейле просто оставляем старый кэш
        pass

def get_stale_cache(fn_name: str, cache_key: str):
    """
    Получить устаревшие данные из кэша (даже если TTL истёк).
    
    Args:
        fn_name: Имя функции
        cache_key: Ключ кэша
    
    Returns:
        Значение из кэша или None
    """
    key = (fn_name, cache_key)
    ts, val = _cache.get(key, (0.0, None))
    if val is not None:
        return val
    return None


def get_cache(fn_name: str, cache_key: str, ttl: int = 60):
    """
    Получить данные из кэша с проверкой TTL.
    
    Args:
        fn_name: Имя функции
        cache_key: Ключ кэша
        ttl: TTL в секундах
    
    Returns:
        Значение из кэша или None
    """
    key = (fn_name, cache_key)
    now = time.time()
    ts, val = _cache.get(key, (0.0, None))
    if val is not None and (now - ts) < ttl:
        return val
    return None


def set_cache(fn_name: str, cache_key: str, value: Any):
    """
    Сохранить значение в кэш.
    
    Args:
        fn_name: Имя функции
        cache_key: Ключ кэша
        value: Значение для кэширования
    """
    key = (fn_name, cache_key)
    _cache[key] = (time.time(), value)
