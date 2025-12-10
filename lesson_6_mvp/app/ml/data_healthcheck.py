# app/ml/data_healthcheck.py
"""
Проверка качества входных данных для ML-моделей.

Проверяет:
- Аномально низкий volume
- Дыры в OHLCV данных
- Резкие спайки (биржевые глюки)
- Некорректные значения (NaN, inf, отрицательные цены)
"""

import logging
import pandas as pd
import numpy as np
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass

logger = logging.getLogger("alt_forecast.ml.data_healthcheck")


@dataclass
class DataQualityReport:
    """Отчет о качестве данных."""
    is_valid: bool
    issues: List[str]
    warnings: List[str]
    metrics: Dict[str, float]
    invalid_indices: List[int]  # Индексы строк с проблемами


def check_data_quality(df: pd.DataFrame, min_samples: int = 100) -> DataQualityReport:
    """
    Проверить качество входных данных.
    
    Args:
        df: DataFrame с OHLCV данными (columns: ts, open, high, low, close, volume)
        min_samples: Минимальное количество валидных образцов
    
    Returns:
        DataQualityReport с результатами проверки
    """
    issues = []
    warnings = []
    invalid_indices = []
    metrics = {}
    
    if df is None or df.empty:
        return DataQualityReport(
            is_valid=False,
            issues=["DataFrame is None or empty"],
            warnings=[],
            metrics={},
            invalid_indices=[]
        )
    
    # Проверка 1: Наличие обязательных колонок
    required_cols = ['open', 'high', 'low', 'close']
    missing_cols = [col for col in required_cols if col not in df.columns]
    if missing_cols:
        issues.append(f"Missing required columns: {missing_cols}")
        return DataQualityReport(
            is_valid=False,
            issues=issues,
            warnings=warnings,
            metrics={},
            invalid_indices=[]
        )
    
    # Проверка 2: NaN и inf значения
    for col in ['open', 'high', 'low', 'close']:
        nan_count = df[col].isna().sum()
        inf_count = np.isinf(df[col]).sum() if col in df.columns else 0
        
        if nan_count > 0:
            nan_indices = df[df[col].isna()].index.tolist()
            invalid_indices.extend(nan_indices)
            issues.append(f"Column {col}: {nan_count} NaN values")
        
        if inf_count > 0:
            inf_indices = df[np.isinf(df[col])].index.tolist()
            invalid_indices.extend(inf_indices)
            issues.append(f"Column {col}: {inf_count} inf values")
    
    # Проверка 3: Некорректные значения (отрицательные или нулевые цены)
    for col in ['open', 'high', 'low', 'close']:
        invalid = df[(df[col] <= 0) | (df[col] > 1e10)].index.tolist()
        if invalid:
            invalid_indices.extend(invalid)
            issues.append(f"Column {col}: {len(invalid)} invalid values (<= 0 or > 1e10)")
    
    # Проверка 4: Логическая корректность OHLC
    # high >= max(open, close) и low <= min(open, close)
    invalid_ohlc = df[
        (df['high'] < df[['open', 'close']].max(axis=1)) |
        (df['low'] > df[['open', 'close']].min(axis=1))
    ].index.tolist()
    
    if invalid_ohlc:
        invalid_indices.extend(invalid_ohlc)
        issues.append(f"Invalid OHLC logic: {len(invalid_ohlc)} rows")
    
    # Проверка 5: Аномально низкий volume (если есть)
    if 'volume' in df.columns:
        volume_median = df['volume'].median()
        if volume_median > 0:
            # Volume меньше 1% от медианы считается аномально низким
            low_volume_threshold = volume_median * 0.01
            low_volume = df[df['volume'] < low_volume_threshold].index.tolist()
            if len(low_volume) > len(df) * 0.1:  # Если больше 10% данных
                warnings.append(f"Many low volume bars: {len(low_volume)} ({len(low_volume)/len(df)*100:.1f}%)")
    
    # Проверка 6: Резкие спайки (изменение цены > 50% за один бар)
    if len(df) > 1:
        price_changes = df['close'].pct_change().abs()
        spikes = df[price_changes > 0.5].index.tolist()
        if spikes:
            invalid_indices.extend(spikes)
            issues.append(f"Price spikes (>50% change): {len(spikes)} bars")
    
    # Проверка 7: Дыры в данных (большие пропуски во времени)
    if 'ts' in df.columns or isinstance(df.index, pd.DatetimeIndex):
        ts_col = df['ts'] if 'ts' in df.columns else df.index
        if pd.api.types.is_datetime64_any_dtype(ts_col):
            ts_sorted = pd.Series(ts_col).sort_values()
            if len(ts_sorted) > 1:
                time_diffs = ts_sorted.diff().dropna()
                if len(time_diffs) > 0:
                    median_diff = time_diffs.median()
                    # Пропуски больше 10x от медианного интервала
                    large_gaps = time_diffs[time_diffs > median_diff * 10]
                    if len(large_gaps) > 0:
                        warnings.append(f"Large time gaps detected: {len(large_gaps)} gaps")
                        metrics['max_gap_hours'] = float(large_gaps.max().total_seconds() / 3600)
    
    # Проверка 8: Достаточно ли валидных данных
    valid_indices = set(df.index) - set(invalid_indices)
    valid_count = len(valid_indices)
    
    if valid_count < min_samples:
        issues.append(f"Insufficient valid data: {valid_count} < {min_samples} required")
    
    # Метрики
    metrics['total_rows'] = len(df)
    metrics['valid_rows'] = valid_count
    metrics['invalid_rows'] = len(set(invalid_indices))
    metrics['valid_ratio'] = valid_count / len(df) if len(df) > 0 else 0.0
    
    # Определяем, валидны ли данные
    is_valid = len(issues) == 0 and valid_count >= min_samples
    
    return DataQualityReport(
        is_valid=is_valid,
        issues=issues,
        warnings=warnings,
        metrics=metrics,
        invalid_indices=list(set(invalid_indices))
    )


def filter_invalid_data(df: pd.DataFrame, report: DataQualityReport) -> pd.DataFrame:
    """
    Отфильтровать невалидные данные из DataFrame.
    
    Args:
        df: Исходный DataFrame
        report: Отчет о качестве данных
    
    Returns:
        Отфильтрованный DataFrame
    """
    if report.is_valid:
        return df
    
    if not report.invalid_indices:
        return df
    
    # Удаляем строки с проблемами
    valid_df = df.drop(index=report.invalid_indices)
    
    logger.info(f"Filtered {len(report.invalid_indices)} invalid rows, {len(valid_df)} rows remaining")
    
    return valid_df


















