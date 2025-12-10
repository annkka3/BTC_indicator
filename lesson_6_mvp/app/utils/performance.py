# app/utils/performance.py
"""
Утилиты для мониторинга и оптимизации производительности.
"""

import time
import logging
from functools import wraps
from typing import Callable, Any
import cProfile
import pstats
from io import StringIO

logger = logging.getLogger("alt_forecast.performance")


def measure_time(func: Callable) -> Callable:
    """
    Декоратор для измерения времени выполнения функции.
    
    Пример:
        @measure_time
        def my_function():
            # ваш код
            pass
    """
    @wraps(func)
    def wrapper(*args, **kwargs):
        start = time.time()
        try:
            result = func(*args, **kwargs)
            elapsed = time.time() - start
            logger.debug(f"{func.__name__} took {elapsed:.4f}s")
            return result
        except Exception as e:
            elapsed = time.time() - start
            logger.warning(f"{func.__name__} failed after {elapsed:.4f}s: {e}")
            raise
    return wrapper


def measure_time_async(func: Callable) -> Callable:
    """
    Декоратор для измерения времени выполнения асинхронной функции.
    
    Пример:
        @measure_time_async
        async def my_async_function():
            # ваш код
            pass
    """
    @wraps(func)
    async def wrapper(*args, **kwargs):
        start = time.time()
        try:
            result = await func(*args, **kwargs)
            elapsed = time.time() - start
            logger.debug(f"{func.__name__} took {elapsed:.4f}s")
            return result
        except Exception as e:
            elapsed = time.time() - start
            logger.warning(f"{func.__name__} failed after {elapsed:.4f}s: {e}")
            raise
    return wrapper


def profile_function(func: Callable, sort_by: str = 'cumulative', lines: int = 20) -> Callable:
    """
    Декоратор для профилирования функции.
    
    Args:
        func: Функция для профилирования
        sort_by: Критерий сортировки ('cumulative', 'time', 'calls')
        lines: Количество строк для вывода
    
    Пример:
        @profile_function
        def my_function():
            # ваш код
            pass
    """
    @wraps(func)
    def wrapper(*args, **kwargs):
        profiler = cProfile.Profile()
        profiler.enable()
        try:
            result = func(*args, **kwargs)
        finally:
            profiler.disable()
            stats = pstats.Stats(profiler)
            stats.sort_stats(sort_by)
            output = StringIO()
            stats.print_stats(lines, file=output)
            logger.debug(f"Profile for {func.__name__}:\n{output.getvalue()}")
        return result
    return wrapper


class PerformanceMonitor:
    """
    Контекстный менеджер для мониторинга производительности блока кода.
    
    Пример:
        with PerformanceMonitor("my_operation"):
            # ваш код
            pass
    """
    
    def __init__(self, operation_name: str, log_level: int = logging.DEBUG):
        self.operation_name = operation_name
        self.log_level = log_level
        self.start_time = None
    
    def __enter__(self):
        self.start_time = time.time()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        elapsed = time.time() - self.start_time
        logger.log(
            self.log_level,
            f"{self.operation_name} took {elapsed:.4f}s"
        )
        return False

