# app/domain/market_diagnostics/analyzer.py
"""
Анализатор рынка - классификация фазы рынка на основе признаков.

Фазы рынка:
- ACCUMULATION - накопление
- DISTRIBUTION - распределение
- EXPANSION_UP - расширение вверх
- EXPANSION_DOWN - расширение вниз
- SHAKEOUT - встряска
"""

from typing import Dict, Optional, List
from enum import Enum
from dataclasses import dataclass, field
import pandas as pd
import numpy as np

from .features import TrendState, VolatilityState, LiquidityState
from .config import MarketDoctorConfig, DEFAULT_CONFIG
from .structure_levels import Level, build_support_resistance_levels
from .smc import SMCContext, analyze_smc_context
from .waves import analyze_legs, generate_legs_summary
from .fibonacci import FibonacciAnalysis, analyze_fibonacci
from .elliott_waves import ElliottWavePattern, analyze_elliott_waves


class MarketPhase(Enum):
    """Фаза рынка."""
    ACCUMULATION = "ACCUMULATION"
    DISTRIBUTION = "DISTRIBUTION"
    EXPANSION_UP = "EXPANSION_UP"
    EXPANSION_DOWN = "EXPANSION_DOWN"
    SHAKEOUT = "SHAKEOUT"


@dataclass
class MarketDiagnostics:
    """Результаты диагностики рынка."""
    symbol: str
    timeframe: str
    phase: MarketPhase
    trend: TrendState
    volatility: VolatilityState
    liquidity: LiquidityState
    risk_score: float  # 0-1, где 1 = максимальный риск
    pump_score: float  # 0-1, где 1 = максимальная вероятность пампов
    confidence: float = 0.5  # 0-1, уверенность модели в оценке
    risk_comment: str = ""
    pump_prob_comment: str = ""
    extra_metrics: Dict[str, any] = field(default_factory=dict)
    key_levels: Optional[List[Level]] = None  # Сильные уровни поддержки/сопротивления
    smc_context: Optional[SMCContext] = None  # Smart Money Concepts контекст
    legs_summary: Optional[str] = None  # Описание структуры движений (волновой анализ)
    fibonacci_analysis: Optional[FibonacciAnalysis] = None  # Анализ уровней Фибоначчи
    elliott_waves: Optional[ElliottWavePattern] = None  # Паттерн волн Эллиотта


class MarketAnalyzer:
    """Анализатор рынка для определения фазы."""
    
    def __init__(self, config: MarketDoctorConfig = None):
        """
        Инициализация анализатора.
        
        Args:
            config: Конфигурация Market Doctor. Если None, используется DEFAULT_CONFIG
        """
        self.config = config or DEFAULT_CONFIG
    
    def analyze(self, symbol: str, timeframe: str, df: pd.DataFrame, 
                indicators: Dict[str, any], features: Dict[str, any],
                derivatives: Optional[Dict[str, float]] = None) -> MarketDiagnostics:
        """
        Проанализировать рынок и определить фазу.
        
        Args:
            symbol: Символ монеты
            timeframe: Таймфрейм
            df: DataFrame с OHLCV данными
            indicators: Рассчитанные индикаторы
            features: Извлеченные признаки
            derivatives: Опциональные данные деривативов
        
        Returns:
            MarketDiagnostics с результатами анализа
        """
        trend = features.get('trend', TrendState.NEUTRAL)
        volatility = features.get('volatility', VolatilityState.MEDIUM)
        liquidity = features.get('liquidity', LiquidityState.MEDIUM)
        structure = features.get('structure', 'RANGE')
        
        # Определяем фазу рынка (с учетом деривативов)
        phase = self._classify_phase(trend, volatility, liquidity, structure, features, indicators, df, derivatives)
        
        # Рассчитываем числовые score (передаем дополнительные данные для улучшенного расчета)
        risk_score = self._calculate_risk_score(phase, trend, volatility, liquidity, derivatives, df, indicators)
        pump_score = self._calculate_pump_score(phase, trend, volatility, liquidity, structure, features, derivatives, df, indicators)
        confidence = self._calculate_confidence(df, indicators, derivatives, features)
        
        # Формируем комментарии
        risk_comment = self._generate_risk_comment(phase, trend, volatility, liquidity, derivatives)
        pump_prob_comment = self._generate_pump_prob_comment(phase, trend, volatility, liquidity, structure, derivatives)
        
        # Дополнительные метрики для отчета
        extra_metrics = self._prepare_extra_metrics(indicators, features, derivatives, df)
        
        # Анализ структуры и уровней
        key_levels = None
        smc_context = None
        legs_summary = None
        fibonacci_analysis = None
        elliott_waves = None
        
        try:
            current_price = df['close'].iloc[-1]
            
            # Строим уровни поддержки/сопротивления
            key_levels = build_support_resistance_levels(df, left=2, right=2, tolerance_bps=0.3, min_strength=0.2)
            
            # Анализ SMC контекста
            smc_context = analyze_smc_context(df, left=2, right=2, lookback=50)
            
            # Волновой анализ (legs)
            from .structure_levels import find_swings
            swing_highs, swing_lows = find_swings(df, left=2, right=2)
            if swing_highs and swing_lows:
                legs = analyze_legs(df, swing_highs, swing_lows, min_leg_pct=2.0)
                if legs:
                    legs_summary = generate_legs_summary(legs, current_price)
            
            # Анализ уровней Фибоначчи
            try:
                fibonacci_analysis = analyze_fibonacci(df, current_price=current_price)
            except Exception as e:
                import logging
                logger = logging.getLogger(__name__)
                logger.debug(f"Failed to analyze Fibonacci: {e}")
            
            # Анализ волн Эллиотта
            try:
                elliott_waves = analyze_elliott_waves(df, current_price=current_price)
            except Exception as e:
                import logging
                logger = logging.getLogger(__name__)
                logger.debug(f"Failed to analyze Elliott Waves: {e}")
        except Exception as e:
            # Логируем ошибку, но не прерываем анализ
            import logging
            logger = logging.getLogger(__name__)
            logger.debug(f"Failed to analyze structure/SMC: {e}")
        
        return MarketDiagnostics(
            symbol=symbol,
            timeframe=timeframe,
            phase=phase,
            trend=trend,
            volatility=volatility,
            liquidity=liquidity,
            risk_score=risk_score,
            pump_score=pump_score,
            confidence=confidence,
            risk_comment=risk_comment,
            pump_prob_comment=pump_prob_comment,
            extra_metrics=extra_metrics,
            key_levels=key_levels,
            smc_context=smc_context,
            legs_summary=legs_summary,
            fibonacci_analysis=fibonacci_analysis,
            elliott_waves=elliott_waves
        )
    
    def _classify_phase(self, trend: TrendState, volatility: VolatilityState,
                       liquidity: LiquidityState, structure: str,
                       features: Dict[str, any], indicators: Dict[str, any],
                       df: pd.DataFrame, derivatives: Optional[Dict[str, float]] = None) -> MarketPhase:
        """Классифицировать фазу рынка."""
        
        # SHAKEOUT - высокая волатильность + низкая ликвидность
        if volatility == VolatilityState.HIGH and liquidity == LiquidityState.LOW:
            phase = MarketPhase.SHAKEOUT
        # EXPANSION_UP - бычий тренд + средняя/высокая ликвидность
        elif trend == TrendState.BULLISH and liquidity in [LiquidityState.MEDIUM, LiquidityState.HIGH]:
            if structure == 'HIGHER_HIGH':
                phase = MarketPhase.EXPANSION_UP
            # Даже без структуры, но с сильным трендом
            elif volatility == VolatilityState.MEDIUM:
                phase = MarketPhase.EXPANSION_UP
            else:
                phase = MarketPhase.EXPANSION_UP
        # EXPANSION_DOWN - медвежий тренд + средняя/высокая ликвидность
        elif trend == TrendState.BEARISH and liquidity in [LiquidityState.MEDIUM, LiquidityState.HIGH]:
            if structure == 'LOWER_LOW':
                phase = MarketPhase.EXPANSION_DOWN
            elif volatility == VolatilityState.MEDIUM:
                phase = MarketPhase.EXPANSION_DOWN
            else:
                phase = MarketPhase.EXPANSION_DOWN
        # ACCUMULATION - нейтральный/бычий тренд + низкая волатильность + низкая ликвидность
        elif trend in [TrendState.NEUTRAL, TrendState.BULLISH]:
            if volatility == VolatilityState.LOW and liquidity == LiquidityState.LOW:
                phase = MarketPhase.ACCUMULATION
            # Также может быть накопление при нейтральном тренде и средних показателях
            elif trend == TrendState.NEUTRAL and volatility == VolatilityState.MEDIUM:
                phase = MarketPhase.ACCUMULATION
            else:
                phase = MarketPhase.ACCUMULATION
        # DISTRIBUTION - медвежий/нейтральный тренд + низкая волатильность + низкая ликвидность
        elif trend in [TrendState.NEUTRAL, TrendState.BEARISH]:
            if volatility == VolatilityState.LOW and liquidity == LiquidityState.LOW:
                phase = MarketPhase.DISTRIBUTION
            elif trend == TrendState.NEUTRAL and volatility == VolatilityState.MEDIUM:
                phase = MarketPhase.DISTRIBUTION
            else:
                phase = MarketPhase.DISTRIBUTION
        # По умолчанию - накопление/распределение в зависимости от тренда
        elif trend == TrendState.BULLISH:
            phase = MarketPhase.ACCUMULATION
        elif trend == TrendState.BEARISH:
            phase = MarketPhase.DISTRIBUTION
        else:
            phase = MarketPhase.ACCUMULATION
        
        # Учитываем деривативы для уточнения фазы
        if derivatives:
            funding = derivatives.get('funding_rate', 0.0)
            oi_change = derivatives.get('oi_change_pct', 0.0)
            
            # Признак шорт-сквиза в зародыше (ACCUMULATION + экстремальный funding)
            if phase == MarketPhase.ACCUMULATION and funding < self.config.funding_low and oi_change > self.config.oi_increase:
                return MarketPhase.SHAKEOUT  # Более агрессивная фаза перед сквизом
            
            # Признак выдавливания лонгов (EXPANSION_UP + высокий funding + падение OI)
            if phase == MarketPhase.EXPANSION_UP and funding > self.config.funding_extreme_long and oi_change < self.config.oi_decrease:
                return MarketPhase.DISTRIBUTION
        
        return phase
    
    def _calculate_risk_score(
        self, 
        phase: MarketPhase, 
        trend: TrendState,
        volatility: VolatilityState, 
        liquidity: LiquidityState,
        derivatives: Optional[Dict[str, float]],
        df: pd.DataFrame,
        indicators: Dict[str, any]
    ) -> float:
        """
        Рассчитать риск-скор (0-1, где 1 = максимальный риск).
        
        Использует взвешенную комбинацию признаков из конфига.
        """
        weights = self.config.risk_score_weights
        score = 0.0
        
        # Компонент волатильности
        vol_component = 0.0
        if volatility == VolatilityState.HIGH:
            vol_component = 1.0
        elif volatility == VolatilityState.MEDIUM:
            vol_component = 0.5
        score += weights.get("volatility", 0.3) * vol_component
        
        # Компонент ликвидности
        liq_component = 0.0
        if liquidity == LiquidityState.LOW:
            liq_component = 1.0
        elif liquidity == LiquidityState.MEDIUM:
            liq_component = 0.5
        score += weights.get("liquidity", 0.25) * liq_component
        
        # Компонент фазы
        phase_weight = self.config.risk_phase_weights.get(phase.value, 0.0)
        score += weights.get("phase", 0.2) * phase_weight
        
        # Компонент деривативов
        deriv_component = 0.0
        if derivatives:
            funding = abs(derivatives.get('funding_rate', 0.0))
            if funding > self.config.funding_extreme_long:
                deriv_component = 1.0
            elif funding > self.config.funding_high:
                deriv_component = 0.6
            elif funding > 0.0:
                deriv_component = 0.3
        score += weights.get("derivatives", 0.15) * deriv_component
        
        # Компонент тренда (медвежий тренд увеличивает риск)
        trend_component = 0.0
        if trend == TrendState.BEARISH:
            trend_component = 1.0
        elif trend == TrendState.NEUTRAL:
            trend_component = 0.5
        score += weights.get("trend", 0.1) * trend_component
        
        return min(score, 1.0)  # Ограничиваем максимумом 1.0
    
    def _calculate_pump_score(
        self, 
        phase: MarketPhase, 
        trend: TrendState,
        volatility: VolatilityState, 
        liquidity: LiquidityState,
        structure: str, 
        features: Dict[str, any],
        derivatives: Optional[Dict[str, float]],
        df: pd.DataFrame,
        indicators: Dict[str, any]
    ) -> float:
        """
        Рассчитать скор вероятности пампов (0-1, где 1 = максимальная вероятность).
        
        Использует взвешенную комбинацию признаков из конфига.
        """
        weights = self.config.pump_score_weights
        score = 0.0
        
        # Компонент фазы
        phase_weight = self.config.pump_phase_weights.get(phase.value, 0.0)
        score += weights.get("phase", 0.3) * phase_weight
        
        # Компонент тренда
        trend_component = 0.0
        if trend == TrendState.BULLISH:
            trend_component = 1.0
        elif trend == TrendState.NEUTRAL:
            trend_component = 0.5
        score += weights.get("trend", 0.2) * trend_component
        
        # Компонент структуры
        structure_component = 0.0
        if structure == 'HIGHER_HIGH':
            structure_component = 1.0
        elif structure == 'RANGE':
            structure_component = 0.5
        score += weights.get("structure", 0.15) * structure_component
        
        # Компонент волатильности (компрессия перед взрывом)
        vol_component = 0.0
        if volatility == VolatilityState.LOW:
            vol_component = 1.0  # Компрессия - хороший знак для пампов
        elif volatility == VolatilityState.MEDIUM:
            vol_component = 0.5
        score += weights.get("volatility", 0.1) * vol_component
        
        # Компонент деривативов
        deriv_component = 0.0
        if derivatives:
            funding = derivatives.get('funding_rate', 0.0)
            oi_change = derivatives.get('oi_change_pct', 0.0)
            cvd = derivatives.get('cvd', 0.0)
            
            # Позитивный CVD увеличивает вероятность
            if cvd > 0:
                deriv_component += 0.3
            
            # Повышающийся OI - хороший знак
            if oi_change > self.config.oi_increase:
                deriv_component += 0.3
            elif oi_change > 0:
                deriv_component += 0.15
            
            # Короткие перегреты (низкий funding) - хороший знак для пампов
            if funding < self.config.funding_low:
                deriv_component += 0.2
            elif funding < 0:
                deriv_component += 0.1
            
            deriv_component = min(deriv_component, 1.0)
        
        score += weights.get("derivatives", 0.25) * deriv_component
        
        # Дополнительный компонент: отклонение от VWAP/EMA200
        # Если цена ниже VWAP/EMA200 при накоплении - это хорошо для пампов
        try:
            current_price = float(df['close'].iloc[-1])
            
            # Отклонение от VWAP
            if 'vwap' in indicators:
                vwap = self._get_last_value(indicators['vwap'])
                if vwap and vwap > 0:
                    vwap_dev = (current_price - vwap) / vwap
                    if vwap_dev < -self.config.vwap_deviation_threshold:
                        score += 0.05  # Цена ниже VWAP - хороший знак
            
            # Отклонение от EMA200
            if 'ema_200' in indicators:
                ema200 = self._get_last_value(indicators['ema_200'])
                if ema200 and ema200 > 0:
                    ema200_dev = (current_price - ema200) / ema200
                    if ema200_dev < -self.config.ema200_deviation_threshold:
                        score += 0.05  # Цена ниже EMA200 - хороший знак
        except Exception:
            pass  # Игнорируем ошибки при расчете отклонений
        
        return min(score, 1.0)  # Ограничиваем максимумом 1.0
    
    def _calculate_confidence(
        self,
        df: pd.DataFrame,
        indicators: Dict[str, any],
        derivatives: Optional[Dict[str, float]],
        features: Dict[str, any]
    ) -> float:
        """
        Рассчитать уверенность модели в оценке.
        
        Компоненты confidence:
        1. Длина истории данных (больше данных = выше confidence)
        2. Качество деривативов (full > partial > none)
        3. Стабильность тренда (согласованность индикаторов)
        4. Наличие ключевых индикаторов
        
        Returns:
            Confidence score от 0.0 до 1.0
        """
        confidence = 0.5  # Базовая уверенность
        
        # 1. Длина истории данных
        data_length = len(df)
        if data_length >= 200:
            confidence += 0.2  # Достаточно данных
        elif data_length >= 100:
            confidence += 0.1  # Умеренное количество данных
        elif data_length < 50:
            confidence -= 0.2  # Мало данных
        
        # 2. Качество деривативов
        if derivatives:
            # Проверяем наличие ключевых полей
            has_funding = 'funding_rate' in derivatives and derivatives.get('funding_rate') is not None
            has_oi = 'open_interest' in derivatives and derivatives.get('open_interest') is not None
            
            if has_funding and has_oi:
                confidence += 0.15  # Full derivatives data
            elif has_funding or has_oi:
                confidence += 0.08  # Partial derivatives data
        else:
            confidence -= 0.1  # Нет данных деривативов
        
        # 3. Стабильность тренда (согласованность индикаторов)
        trend_consistency = 0.0
        
        # Проверяем согласованность EMA
        if 'ema_50' in indicators and 'ema_200' in indicators:
            ema50 = self._get_last_value(indicators['ema_50'])
            ema200 = self._get_last_value(indicators['ema_200'])
            if ema50 and ema200:
                # Если EMA50 > EMA200, это бычий тренд
                ema_bullish = ema50 > ema200
                
                # Проверяем RSI
                if 'rsi' in indicators:
                    rsi = self._get_last_value(indicators['rsi'])
                    if rsi:
                        rsi_bullish = rsi > 50
                        if ema_bullish == rsi_bullish:
                            trend_consistency += 0.1
                
                # Проверяем MACD
                if 'macd' in indicators and 'macd_signal' in indicators:
                    macd = self._get_last_value(indicators['macd'])
                    macd_signal = self._get_last_value(indicators['macd_signal'])
                    if macd and macd_signal:
                        macd_bullish = macd > macd_signal
                        if ema_bullish == macd_bullish:
                            trend_consistency += 0.1
        
        confidence += trend_consistency
        
        # 4. Наличие ключевых индикаторов
        key_indicators = ['rsi', 'macd', 'ema_50', 'ema_200', 'bb_upper', 'bb_lower']
        available_indicators = sum(1 for ind in key_indicators if ind in indicators and indicators[ind] is not None)
        indicator_score = (available_indicators / len(key_indicators)) * 0.1
        confidence += indicator_score
        
        # Ограничиваем диапазоном [0.0, 1.0]
        return max(0.0, min(1.0, confidence))
    
    def analyze_multi(
        self,
        symbol: str,
        timeframes_data: Dict[str, Dict],
        derivatives: Optional[Dict[str, float]] = None
    ):
        """
        Проанализировать рынок на нескольких таймфреймах.
        
        Args:
            symbol: Символ монеты
            timeframes_data: Словарь {timeframe: {"df": df, "indicators": indicators, "features": features}}
            derivatives: Опциональные данные деривативов (общие для всех ТФ)
        
        Returns:
            MultiTFDiagnostics с результатами анализа по всем ТФ
        """
        # Импортируем здесь, чтобы избежать циклического импорта
        from .multi_tf import MultiTFDiagnostics
        
        snapshots = {}
        
        for timeframe, data in timeframes_data.items():
            df = data["df"]
            indicators = data["indicators"]
            features = data["features"]
            
            # Анализируем каждый таймфрейм
            diag = self.analyze(
                symbol=symbol,
                timeframe=timeframe,
                df=df,
                indicators=indicators,
                features=features,
                derivatives=derivatives
            )
            
            snapshots[timeframe] = diag
        
        return MultiTFDiagnostics(symbol=symbol, snapshots=snapshots)
    
    def _get_last_value(self, series_or_value) -> Optional[float]:
        """Получить последнее значение из Series или вернуть само значение."""
        if isinstance(series_or_value, pd.Series):
            if len(series_or_value) == 0:
                return None
            value = series_or_value.iloc[-1]
            if pd.isna(value):
                return None
            return float(value)
        elif isinstance(series_or_value, (int, float)):
            return float(series_or_value)
        else:
            return None
    
    def _generate_risk_comment(self, phase: MarketPhase, trend: TrendState,
                              volatility: VolatilityState, liquidity: LiquidityState,
                              derivatives: Optional[Dict[str, float]]) -> str:
        """Сгенерировать комментарий о рисках."""
        comments = []
        
        # Риски по фазе
        if phase == MarketPhase.SHAKEOUT:
            comments.append("⚠️ Высокая волатильность при низкой ликвидности - риск резких движений")
        elif phase == MarketPhase.EXPANSION_DOWN:
            comments.append("⚠️ Фаза расширения вниз - повышенный риск снижения")
        elif phase == MarketPhase.EXPANSION_UP:
            comments.append("✅ Фаза расширения вверх - благоприятные условия для роста")
        elif phase == MarketPhase.DISTRIBUTION:
            comments.append("⚠️ Фаза распределения - возможна коррекция")
        
        # Риски по волатильности
        if volatility == VolatilityState.HIGH:
            comments.append("📊 Высокая волатильность - возможны резкие движения")
        elif volatility == VolatilityState.LOW:
            comments.append("📊 Низкая волатильность - стабильное движение")
        
        # Риски по ликвидности
        if liquidity == LiquidityState.LOW:
            comments.append("💧 Низкая ликвидность - возможны проскальзывания")
        
        # Риски по деривативам
        if derivatives:
            funding = derivatives.get('funding_rate', 0.0)
            if abs(funding) > 0.01:  # > 1%
                comments.append(f"🔥 Экстремальный funding ({funding*100:.3f}%) - риск ликвидаций")
        
        if not comments:
            comments.append("✅ Риски в пределах нормы")
        
        return " | ".join(comments)
    
    def _generate_pump_prob_comment(self, phase: MarketPhase, trend: TrendState,
                                   volatility: VolatilityState, liquidity: LiquidityState,
                                   structure: str, derivatives: Optional[Dict[str, float]]) -> str:
        """Сгенерировать комментарий о вероятности пампов."""
        comments = []
        
        # Вероятность пампов по фазе
        if phase == MarketPhase.ACCUMULATION:
            comments.append("📈 Накопление - возможен рост после пробоя")
        elif phase == MarketPhase.EXPANSION_UP:
            comments.append("🚀 Расширение вверх - активный рост")
        elif phase == MarketPhase.SHAKEOUT:
            comments.append("⚡ Встряска - возможен резкий отскок")
        
        # Вероятность по тренду
        if trend == TrendState.BULLISH:
            comments.append("📊 Бычий тренд - благоприятные условия")
        
        # Вероятность по структуре
        if structure == 'HIGHER_HIGH':
            comments.append("📈 Структура выше максимумов - сильный импульс")
        
        # Вероятность по деривативам
        if derivatives:
            funding = derivatives.get('funding_rate', 0.0)
            oi_change = derivatives.get('oi_change_pct', 0.0)
            
            if funding < -0.001 and oi_change > 5:
                comments.append("🔥 Короткие перегреты + рост OI - возможен шорт-сквиз")
            elif funding > 0.001 and oi_change < -5:
                comments.append("📉 Длинные перегреты + падение OI - возможна коррекция")
        
        if not comments:
            comments.append("📊 Условия нейтральные")
        
        return " | ".join(comments)
    
    def _prepare_extra_metrics(self, indicators: Dict[str, any], features: Dict[str, any],
                              derivatives: Optional[Dict[str, float]], df: pd.DataFrame) -> Dict[str, any]:
        """Подготовить дополнительные метрики для отчета."""
        metrics = {}
        
        # Тренд summary
        current_price = df['close'].iloc[-1]
        trend_summary_parts = []
        
        if 'ema_20' in indicators:
            ema20 = self._get_last_value(indicators['ema_20'])
            if not pd.isna(ema20):
                trend_summary_parts.append(f"EMA20: {'↑' if current_price > ema20 else '↓'}")
        
        if 'ema_50' in indicators:
            ema50 = self._get_last_value(indicators['ema_50'])
            if not pd.isna(ema50):
                trend_summary_parts.append(f"EMA50: {'↑' if current_price > ema50 else '↓'}")
        
        if 'ema_200' in indicators:
            ema200 = self._get_last_value(indicators['ema_200'])
            if not pd.isna(ema200):
                trend_summary_parts.append(f"EMA200: {'↑' if current_price > ema200 else '↓'}")
        
        metrics['trend_summary'] = " | ".join(trend_summary_parts) if trend_summary_parts else "N/A"
        
        # RSI
        if 'rsi' in indicators:
            rsi = self._get_last_value(indicators['rsi'])
            if not pd.isna(rsi):
                metrics['rsi'] = f"{rsi:.1f}"
            else:
                metrics['rsi'] = "N/A"
        else:
            metrics['rsi'] = "N/A"
        
        # Stoch RSI (используем K и D)
        if 'stoch_rsi_k' in indicators and 'stoch_rsi_d' in indicators:
            stoch_k = self._get_last_value(indicators['stoch_rsi_k'])
            stoch_d = self._get_last_value(indicators['stoch_rsi_d'])
            if not (pd.isna(stoch_k) or pd.isna(stoch_d)):
                state = ""
                if stoch_k > 80:
                    state = "перекупленность"
                elif stoch_k < 20:
                    state = "перепроданность"
                else:
                    state = "нейтрально"
                metrics['stoch_rsi_state'] = f"K: {stoch_k:.1f} | D: {stoch_d:.1f} ({state})"
            else:
                metrics['stoch_rsi_state'] = "N/A"
        elif 'stoch_rsi' in indicators:  # Fallback для старого формата
            stoch_rsi = self._get_last_value(indicators['stoch_rsi'])
            if not pd.isna(stoch_rsi):
                if stoch_rsi > 80:
                    metrics['stoch_rsi_state'] = f"{stoch_rsi:.1f} (перекупленность)"
                elif stoch_rsi < 20:
                    metrics['stoch_rsi_state'] = f"{stoch_rsi:.1f} (перепроданность)"
                else:
                    metrics['stoch_rsi_state'] = f"{stoch_rsi:.1f} (нейтрально)"
            else:
                metrics['stoch_rsi_state'] = "N/A"
        else:
            metrics['stoch_rsi_state'] = "N/A"
        
        # MACD
        if 'macd_hist' in indicators:
            macd_hist = self._get_last_value(indicators['macd_hist'])
            if not pd.isna(macd_hist):
                if macd_hist > 0:
                    metrics['macd_state'] = f"↑ {macd_hist:.4f} (бычий)"
                else:
                    metrics['macd_state'] = f"↓ {macd_hist:.4f} (медвежий)"
            else:
                metrics['macd_state'] = "N/A"
        else:
            metrics['macd_state'] = "N/A"
        
        # Bollinger Bands
        if 'bb_upper' in indicators and 'bb_lower' in indicators:
            bb_upper = self._get_last_value(indicators['bb_upper'])
            bb_lower = self._get_last_value(indicators['bb_lower'])
            if not (pd.isna(bb_upper) or pd.isna(bb_lower)):
                if current_price > bb_upper:
                    metrics['bb_state'] = "Выше верхней полосы (перекупленность)"
                elif current_price < bb_lower:
                    metrics['bb_state'] = "Ниже нижней полосы (перепроданность)"
                else:
                    metrics['bb_state'] = "В пределах полос"
            else:
                metrics['bb_state'] = "N/A"
        else:
            metrics['bb_state'] = "N/A"
        
        # Money Flow
        obv_trend = "N/A"
        cmf_state = "N/A"
        
        if 'obv' in indicators:
            obv = indicators['obv']
            if hasattr(obv, 'iloc') and len(obv) >= 2:
                obv_current = obv.iloc[-1]
                obv_prev = obv.iloc[-2]
                if not (pd.isna(obv_current) or pd.isna(obv_prev)):
                    if obv_current > obv_prev:
                        obv_trend = "↑ Рост"
                    elif obv_current < obv_prev:
                        obv_trend = "↓ Падение"
                    else:
                        obv_trend = "→ Без изменений"
        
        if 'cmf' in indicators:
            cmf = self._get_last_value(indicators['cmf'])
            if not pd.isna(cmf):
                if cmf > 0.1:
                    cmf_state = f"{cmf:.3f} (приток)"
                elif cmf < -0.1:
                    cmf_state = f"{cmf:.3f} (отток)"
                else:
                    cmf_state = f"{cmf:.3f} (нейтрально)"
        
        metrics['money_flow_state'] = f"OBV: {obv_trend} | CMF: {cmf_state}"
        
        # Деривативы
        if derivatives:
            funding = derivatives.get('funding_rate', 0.0)
            metrics['funding'] = f"{funding*100:.4f}%"
            
            oi_change = derivatives.get('oi_change_pct', 0.0)
            if oi_change > 5:
                metrics['oi_state'] = f"↑ +{oi_change:.1f}% (рост)"
            elif oi_change < -5:
                metrics['oi_state'] = f"↓ {oi_change:.1f}% (падение)"
            else:
                metrics['oi_state'] = f"→ {oi_change:.1f}% (стабильно)"
            
            cvd = derivatives.get('cvd', 0.0)
            if cvd > 0:
                metrics['cvd_comment'] = f"CVD: +{cvd:.0f} (покупки)"
            elif cvd < 0:
                metrics['cvd_comment'] = f"CVD: {cvd:.0f} (продажи)"
            else:
                metrics['cvd_comment'] = "CVD: нейтрально"
        else:
            metrics['funding'] = "N/A"
            metrics['oi_state'] = "N/A"
            metrics['cvd_comment'] = "N/A"
        
        return metrics
    
    def _get_last_value(self, series) -> float:
        """Получить последнее значение из Series или скаляр."""
        if hasattr(series, 'iloc'):
            return series.iloc[-1]
        elif hasattr(series, '__iter__') and not isinstance(series, str):
            return list(series)[-1]
        else:
            return float(series)

