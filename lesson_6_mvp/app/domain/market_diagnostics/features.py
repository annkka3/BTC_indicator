# app/domain/market_diagnostics/features.py
"""
Свертка индикаторов в признаки для анализа рынка.

Преобразует технические индикаторы в состояния:
- Тренд (BULLISH / BEARISH / NEUTRAL)
- Волатильность (LOW / MEDIUM / HIGH)
- Ликвидность (LOW / MEDIUM / HIGH)
- Режим деривативов (LONG_SQUEEZE / SHORT_SQUEEZE / NEUTRAL)
"""

from typing import Dict, Optional, List
from enum import Enum
import pandas as pd
import numpy as np
import logging

from .config import MarketDoctorConfig, DEFAULT_CONFIG

logger = logging.getLogger(__name__)


class TrendState(Enum):
    """Состояние тренда."""
    BULLISH = "BULLISH"
    BEARISH = "BEARISH"
    NEUTRAL = "NEUTRAL"


class VolatilityState(Enum):
    """Состояние волатильности."""
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class LiquidityState(Enum):
    """Состояние ликвидности."""
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class FeatureExtractor:
    """Извлечение признаков из индикаторов."""
    
    def __init__(self, config: MarketDoctorConfig = None):
        """
        Инициализация FeatureExtractor.
        
        Args:
            config: Конфигурация Market Doctor. Если None, используется DEFAULT_CONFIG
        """
        self.config = config or DEFAULT_CONFIG
    
    def extract_features(self, df: pd.DataFrame, indicators: Dict[str, any], 
                        derivatives: Optional[Dict[str, float]] = None) -> Dict[str, any]:
        """
        Извлечь признаки из индикаторов.
        
        Args:
            df: DataFrame с OHLCV данными
            indicators: Словарь с рассчитанными индикаторами
            derivatives: Опциональные данные деривативов (funding, oi, cvd)
        
        Returns:
            Словарь с признаками
        """
        if len(df) == 0:
            return self._default_features()
        
        # Берем последние значения
        current_price = df['close'].iloc[-1]
        
        features = {}
        
        # Тренд
        features['trend'] = self._extract_trend(df, indicators, current_price)
        
        # Волатильность
        features['volatility'] = self._extract_volatility(df, indicators)
        
        # Ликвидность
        features['liquidity'] = self._extract_liquidity(df, indicators)
        
        # Структурные признаки
        features['structure'] = self._extract_structure(df)
        
        # Деривативы (если доступны)
        if derivatives:
            features['derivatives'] = self._extract_derivatives_features(derivatives)
        else:
            features['derivatives'] = None
        
        # Дивергенции индикаторов
        features['divergences'] = self._detect_divergences(df, indicators)
        
        return features
    
    def _default_features(self) -> Dict[str, any]:
        """Возвратить признаки по умолчанию при отсутствии данных."""
        return {
            'trend': TrendState.NEUTRAL,
            'volatility': VolatilityState.MEDIUM,
            'liquidity': LiquidityState.MEDIUM,
            'structure': 'RANGE',
            'derivatives': None,
            'divergences': []
        }
    
    def _extract_trend(self, df: pd.DataFrame, indicators: Dict[str, any], 
                      current_price: float) -> TrendState:
        """Извлечь состояние тренда."""
        scores = []
        
        # EMA тренд
        if 'ema_20' in indicators and 'ema_50' in indicators:
            ema20 = indicators['ema_20'].iloc[-1] if hasattr(indicators['ema_20'], 'iloc') else indicators['ema_20']
            ema50 = indicators['ema_50'].iloc[-1] if hasattr(indicators['ema_50'], 'iloc') else indicators['ema_50']
            if not (pd.isna(ema20) or pd.isna(ema50)):
                if current_price > ema20 > ema50:
                    scores.append(1)
                elif current_price < ema20 < ema50:
                    scores.append(-1)
        
        if 'ema_50' in indicators and 'ema_200' in indicators:
            ema50 = indicators['ema_50'].iloc[-1] if hasattr(indicators['ema_50'], 'iloc') else indicators['ema_50']
            ema200 = indicators['ema_200'].iloc[-1] if hasattr(indicators['ema_200'], 'iloc') else indicators['ema_200']
            if not (pd.isna(ema50) or pd.isna(ema200)):
                if ema50 > ema200:
                    scores.append(1)
                elif ema50 < ema200:
                    scores.append(-1)
        
        # RSI тренд (используем пороги из конфига)
        if 'rsi' in indicators:
            rsi = indicators['rsi'].iloc[-1] if hasattr(indicators['rsi'], 'iloc') else indicators['rsi']
            if not pd.isna(rsi):
                # Используем пороги из конфига, но с небольшим запасом для определения тренда
                rsi_bullish = (self.config.rsi_overbought + self.config.rsi_oversold) / 2 + 10  # ~60
                rsi_bearish = (self.config.rsi_overbought + self.config.rsi_oversold) / 2 - 10  # ~40
                if rsi > rsi_bullish:
                    scores.append(1)
                elif rsi < rsi_bearish:
                    scores.append(-1)
        
        # MACD тренд
        if 'macd_hist' in indicators:
            macd_hist = indicators['macd_hist'].iloc[-1] if hasattr(indicators['macd_hist'], 'iloc') else indicators['macd_hist']
            if not pd.isna(macd_hist):
                if macd_hist > 0:
                    scores.append(1)
                elif macd_hist < 0:
                    scores.append(-1)
        
        # Определяем итоговый тренд
        if not scores:
            return TrendState.NEUTRAL
        
        avg_score = sum(scores) / len(scores)
        if avg_score > 0.3:
            return TrendState.BULLISH
        elif avg_score < -0.3:
            return TrendState.BEARISH
        else:
            return TrendState.NEUTRAL
    
    def _extract_volatility(self, df: pd.DataFrame, indicators: Dict[str, any]) -> VolatilityState:
        """Извлечь состояние волатильности."""
        if 'atr' not in indicators:
            return VolatilityState.MEDIUM
        
        atr = indicators['atr']
        current_atr = atr.iloc[-1] if hasattr(atr, 'iloc') else atr
        
        if pd.isna(current_atr):
            return VolatilityState.MEDIUM
        
        # Сравниваем с историческим средним ATR
        if hasattr(atr, 'iloc'):
            atr_mean = atr.dropna().mean()
            if pd.isna(atr_mean) or atr_mean == 0:
                return VolatilityState.MEDIUM
            
            ratio = current_atr / atr_mean
            if ratio > self.config.bb_high_threshold:
                return VolatilityState.HIGH
            elif ratio < self.config.bb_low_threshold:
                return VolatilityState.LOW
            else:
                return VolatilityState.MEDIUM
        
        return VolatilityState.MEDIUM
    
    def _extract_liquidity(self, df: pd.DataFrame, indicators: Dict[str, any]) -> LiquidityState:
        """Извлечь состояние ликвидности."""
        if 'volume' not in df.columns:
            return LiquidityState.MEDIUM
        
        volume = df['volume'].fillna(0)
        if volume.sum() == 0:
            return LiquidityState.LOW
        
        # Проверяем объем относительно среднего
        volume_ma = volume.rolling(window=20).mean()
        current_volume = volume.iloc[-1]
        avg_volume = volume_ma.iloc[-1] if not volume_ma.empty else current_volume
        
        if pd.isna(avg_volume) or avg_volume == 0:
            return LiquidityState.MEDIUM
        
        ratio = current_volume / avg_volume
        
        if ratio > self.config.vol_high_ratio:
            return LiquidityState.HIGH
        elif ratio < self.config.vol_low_ratio:
            return LiquidityState.LOW
        else:
            return LiquidityState.MEDIUM
    
    def _extract_structure(self, df: pd.DataFrame) -> str:
        """Извлечь структурные признаки (HIGHER_HIGH / LOWER_LOW / RANGE)."""
        if len(df) < 20:
            return 'RANGE'
        
        # Ищем локальные максимумы и минимумы
        highs = df['high'].values
        lows = df['low'].values
        
        # Упрощенный поиск свингов
        lookback = min(10, len(df) // 4)
        
        recent_highs = highs[-lookback:]
        recent_lows = lows[-lookback:]
        prev_highs = highs[-lookback*2:-lookback] if len(highs) >= lookback*2 else []
        prev_lows = lows[-lookback*2:-lookback] if len(lows) >= lookback*2 else []
        
        if len(prev_highs) > 0 and len(recent_highs) > 0:
            max_recent_high = np.max(recent_highs)
            max_prev_high = np.max(prev_highs)
            
            if max_recent_high > max_prev_high:
                return 'HIGHER_HIGH'
        
        if len(prev_lows) > 0 and len(recent_lows) > 0:
            min_recent_low = np.min(recent_lows)
            min_prev_low = np.min(prev_lows)
            
            if min_recent_low < min_prev_low:
                return 'LOWER_LOW'
        
        return 'RANGE'
    
    def _extract_derivatives_features(self, derivatives: Dict[str, float]) -> Dict[str, any]:
        """Извлечь признаки из данных деривативов."""
        features = {}
        
        # Funding rate
        funding = derivatives.get('funding_rate', 0.0)
        if funding > 0.01:  # > 1% - очень высокий
            features['funding_state'] = 'EXTREME_LONG'
        elif funding > 0.001:  # > 0.1% - высокий
            features['funding_state'] = 'LONG'
        elif funding < -0.01:  # < -1% - очень низкий
            features['funding_state'] = 'EXTREME_SHORT'
        elif funding < -0.001:  # < -0.1% - низкий
            features['funding_state'] = 'SHORT'
        else:
            features['funding_state'] = 'NEUTRAL'
        
        # Open Interest (если доступен)
        oi_change = derivatives.get('oi_change_pct', 0.0)
        if oi_change > 10:
            features['oi_state'] = 'RAPID_INCREASE'
        elif oi_change > 5:
            features['oi_state'] = 'INCREASE'
        elif oi_change < -10:
            features['oi_state'] = 'RAPID_DECREASE'
        elif oi_change < -5:
            features['oi_state'] = 'DECREASE'
        else:
            features['oi_state'] = 'STABLE'
        
        # CVD (если доступен)
        cvd = derivatives.get('cvd', 0.0)
        if cvd > 0:
            features['cvd_state'] = 'BUYING_PRESSURE'
        elif cvd < 0:
            features['cvd_state'] = 'SELLING_PRESSURE'
        else:
            features['cvd_state'] = 'NEUTRAL'
        
        return features
    
    def _detect_divergences(self, df: pd.DataFrame, indicators: Dict[str, any]) -> List[Dict[str, any]]:
        """
        Обнаружить дивергенции индикаторов.
        
        Args:
            df: DataFrame с OHLCV данными
            indicators: Словарь с рассчитанными индикаторами
        
        Returns:
            Список словарей с информацией о дивергенциях
        """
        if len(df) < 50:
            return []
        
        try:
            # Импортируем детектор дивергенций
            from ...domain.divergence_detector import detect_divergences, DivergenceSignal
            
            # Конвертируем DataFrame в списки для детектора
            closes = df['close'].tolist()
            highs = df['high'].tolist()
            lows = df['low'].tolist()
            volumes = df['volume'].fillna(0).tolist() if 'volume' in df.columns else [0.0] * len(df)
            
            # Используем только основные индикаторы для дивергенций
            enabled_indicators = {
                "RSI": True,
                "MACD": True,
                "STOCH": True,
                "OBV": True,
                "VOLUME": False,  # Отключаем VOLUME, так как он менее надежен
                "CCI": False,     # Отключаем CCI и MFI для упрощения
                "MFI": False,
            }
            
            # Для детектора нужны Metric и Timeframe, но мы можем использовать "BTC" как дефолт
            # и "1h" как дефолт таймфрейм (это не критично для детекции дивергенций)
            from ...domain.models import Metric, Timeframe
            
            # Пробуем определить метрику из символа (если возможно)
            metric: Metric = "BTC"  # Дефолт
            timeframe: Timeframe = "1h"  # Дефолт
            
            # Вызываем детектор
            divergence_signals = detect_divergences(
                metric=metric,
                timeframe=timeframe,
                closes=closes,
                highs=highs,
                lows=lows,
                volumes=volumes,
                enabled_indicators=enabled_indicators
            )
            
            # Конвертируем DivergenceSignal в простые словари для features
            divergences = []
            for signal in divergence_signals:
                divergences.append({
                    'indicator': signal.indicator,
                    'side': signal.side,  # "bullish" или "bearish"
                    'strength': signal.strength,  # "strong", "medium", "weak"
                    'text': signal.text,
                    'price_val_left': signal.price_val_left,
                    'price_val_right': signal.price_val_right,
                })
            
            if divergences:
                logger.debug(f"Detected {len(divergences)} divergences: {[d['indicator'] + ' ' + d['side'] for d in divergences]}")
            
            return divergences
            
        except Exception as e:
            logger.debug(f"Failed to detect divergences: {e}")
            return []

