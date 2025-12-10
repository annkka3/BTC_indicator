# app/domain/market_diagnostics/scoring_engine.py
"""
Система скоринга индикаторов для Market Doctor.

Группирует индикаторы по функциональным классам и выдаёт единый числовой score.
"""

from typing import Dict, Optional, List
from dataclasses import dataclass
from enum import Enum
from datetime import datetime, timedelta
import numpy as np

from .analyzer import MarketDiagnostics, MarketPhase
from .features import TrendState, VolatilityState, LiquidityState
from .momentum_intelligence import MomentumIntelligence, MomentumInsight


class IndicatorGroup(str, Enum):
    """Группы индикаторов."""
    TREND = "trend"
    MOMENTUM = "momentum"
    VOLUME = "volume"
    VOLATILITY = "volatility"
    STRUCTURE = "structure"
    DERIVATIVES = "derivatives"


@dataclass
class GroupScore:
    """Score для группы индикаторов."""
    group: IndicatorGroup
    raw_score: float  # [-2, 2]
    signals: Dict[str, float]  # Детализация по индикаторам
    summary: str  # Текстовое описание


@dataclass
class TimeframeScore:
    """Score для одного таймфрейма."""
    timeframe: str
    weight: float
    regime: str
    trend: str
    group_scores: Dict[IndicatorGroup, GroupScore]
    net_score: float  # [-2, 2] взвешенная сумма
    normalized_long: float  # [0, 10]
    normalized_short: float  # [0, 10]


@dataclass
class MultiTFScore:
    """Агрегированный score по всем таймфреймам."""
    target_tf: str
    per_tf: Dict[str, TimeframeScore]
    aggregated_long: float  # [0, 10]
    aggregated_short: float  # [0, 10]
    confidence: float  # [0, 1]
    direction: str  # "LONG" or "SHORT"
    momentum_grade: Optional[str] = None  # "STRONG_BULLISH", "WEAK_BULLISH", "NEUTRAL", "WEAK_BEARISH", "STRONG_BEARISH"
    momentum_comment: Optional[str] = None  # "сильный бычий continuation", "слабый, высокий риск разворота"


# Веса групп индикаторов
GROUP_WEIGHTS = {
    IndicatorGroup.TREND: 0.25,
    IndicatorGroup.MOMENTUM: 0.25,
    IndicatorGroup.VOLUME: 0.15,
    IndicatorGroup.VOLATILITY: 0.10,
    IndicatorGroup.STRUCTURE: 0.20,
    IndicatorGroup.DERIVATIVES: 0.05
}

# Веса таймфреймов для разных target_tf
TF_WEIGHTS_FOR_TARGET = {
    "1h": {"1h": 0.50, "4h": 0.30, "1d": 0.15, "1w": 0.05},
    "4h": {"1h": 0.20, "4h": 0.40, "1d": 0.30, "1w": 0.10},
    "1d": {"1h": 0.10, "4h": 0.25, "1d": 0.40, "1w": 0.25},
    "1w": {"1h": 0.05, "4h": 0.15, "1d": 0.30, "1w": 0.50}
}


class ScoringEngine:
    """Движок для скоринга индикаторов."""
    
    def __init__(self, custom_weights: Optional[Dict[IndicatorGroup, float]] = None):
        """
        Инициализация скоринга.
        
        Args:
            custom_weights: Кастомные веса групп (если None, используются GROUP_WEIGHTS)
        """
        # Кэш для scores (TTL 60 секунд)
        self._cache: Dict[str, tuple] = {}  # {cache_key: (score, timestamp)}
        self._cache_ttl = 60  # секунд
        
        # Используем кастомные веса или дефолтные
        self.weights = custom_weights if custom_weights else GROUP_WEIGHTS.copy()
        
        # Momentum Intelligence Layer для улучшения анализа импульса
        self.momentum_intel = MomentumIntelligence()
    
    def score_trend_group(self, diag: MarketDiagnostics, indicators: dict, features: dict) -> GroupScore:
        """
        Оценить группу трендовых индикаторов.
        
        Включает: EMA20/50/200, Supertrend, структура (HH/HL/LH/LL)
        """
        signals = {}
        bullish_count = 0
        bearish_count = 0
        
        # EMA направление
        if 'ema20' in indicators and 'ema50' in indicators and 'ema200' in indicators:
            ema20 = indicators['ema20']
            ema50 = indicators['ema50']
            ema200 = indicators['ema200']
            
            try:
                if hasattr(ema20, 'iloc') and len(ema20) >= 2:
                    ema20_dir = "up" if ema20.iloc[-1] > ema20.iloc[-2] else "down"
                else:
                    ema20_dir = "neutral"
                
                if hasattr(ema50, 'iloc') and len(ema50) >= 2:
                    ema50_dir = "up" if ema50.iloc[-1] > ema50.iloc[-2] else "down"
                else:
                    ema50_dir = "neutral"
                
                if hasattr(ema200, 'iloc') and len(ema200) >= 2:
                    ema200_dir = "up" if ema200.iloc[-1] > ema200.iloc[-2] else "down"
                else:
                    ema200_dir = "neutral"
            except Exception:
                ema20_dir = "neutral"
                ema50_dir = "neutral"
                ema200_dir = "neutral"
            
            if ema20_dir == "up" and ema50_dir == "up" and ema200_dir == "up":
                bullish_count += 3
                signals['ema'] = 1.5
            elif ema20_dir == "down" and ema50_dir == "down" and ema200_dir == "down":
                bearish_count += 3
                signals['ema'] = -1.5
            else:
                signals['ema'] = 0.0
        
        # ADX (сила тренда)
        if 'adx' in indicators and '+di' in indicators and '-di' in indicators:
            try:
                adx = indicators['adx']
                plus_di = indicators['+di']
                minus_di = indicators['-di']
                if hasattr(adx, 'iloc') and len(adx) > 0:
                    adx_val = adx.iloc[-1]
                    plus_di_val = plus_di.iloc[-1] if hasattr(plus_di, 'iloc') else 0
                    minus_di_val = minus_di.iloc[-1] if hasattr(minus_di, 'iloc') else 0
                    
                    # ADX > 25 означает сильный тренд
                    if adx_val > 25:
                        if plus_di_val > minus_di_val:
                            bullish_count += 1
                            signals['adx'] = 0.5
                        elif minus_di_val > plus_di_val:
                            bearish_count += 1
                            signals['adx'] = -0.5
                        else:
                            signals['adx'] = 0.0
                    else:
                        signals['adx'] = 0.0  # Слабый тренд
                else:
                    signals['adx'] = 0.0
            except Exception:
                signals['adx'] = 0.0
        
        # Ichimoku Cloud
        if 'ichimoku_tenkan' in indicators and 'ichimoku_kijun' in indicators:
            try:
                tenkan = indicators['ichimoku_tenkan']
                kijun = indicators['ichimoku_kijun']
                close = features.get('close') if 'close' in features else None
                
                if hasattr(tenkan, 'iloc') and len(tenkan) > 0 and len(kijun) > 0:
                    tenkan_val = tenkan.iloc[-1]
                    kijun_val = kijun.iloc[-1]
                    
                    # Цена выше Tenkan и Kijun = бычий сигнал
                    if close is not None and hasattr(close, 'iloc'):
                        close_val = close.iloc[-1]
                        if close_val > tenkan_val and close_val > kijun_val:
                            bullish_count += 1
                            signals['ichimoku'] = 0.5
                        elif close_val < tenkan_val and close_val < kijun_val:
                            bearish_count += 1
                            signals['ichimoku'] = -0.5
                        else:
                            signals['ichimoku'] = 0.0
                    # Или пересечение Tenkan/Kijun
                    elif tenkan_val > kijun_val:
                        bullish_count += 0.5
                        signals['ichimoku'] = 0.25
                    else:
                        bearish_count += 0.5
                        signals['ichimoku'] = -0.25
                else:
                    signals['ichimoku'] = 0.0
            except Exception:
                signals['ichimoku'] = 0.0
        
        # Структура рынка
        structure = features.get('structure', 'RANGE')
        if hasattr(structure, 'value'):
            structure = structure.value
        
        if structure in ['UPTREND', 'HIGHER_HIGHS']:
            bullish_count += 2
            signals['structure'] = 1.0
        elif structure in ['DOWNTREND', 'LOWER_LOWS']:
            bearish_count += 2
            signals['structure'] = -1.0
        else:
            signals['structure'] = 0.0
        
        # Тренд из диагностики
        trend_val = diag.trend.value if hasattr(diag.trend, 'value') else str(diag.trend)
        if trend_val in ['BULLISH', 'bullish']:
            bullish_count += 1
            signals['trend_state'] = 0.5
        elif trend_val in ['BEARISH', 'bearish']:
            bearish_count += 1
            signals['trend_state'] = -0.5
        else:
            signals['trend_state'] = 0.0
        
        # Нормализуем в [-2, 2]
        raw_score = max(-2.0, min(2.0, (bullish_count - bearish_count) / 3.0))
        
        # Формируем описание
        if raw_score > 1.0:
            summary = "Сильный бычий тренд"
        elif raw_score > 0.3:
            summary = "Слабый бычий тренд"
        elif raw_score < -1.0:
            summary = "Сильный медвежий тренд"
        elif raw_score < -0.3:
            summary = "Слабый медвежий тренд"
        else:
            summary = "Нейтральный тренд"
        
        return GroupScore(
            group=IndicatorGroup.TREND,
            raw_score=raw_score,
            signals=signals,
            summary=summary
        )
    
    def score_momentum_group(self, diag: MarketDiagnostics, indicators: dict, features: dict) -> GroupScore:
        """
        Оценить группу импульсных индикаторов.
        
        Включает: RSI, StochRSI, MACD, WT, STC
        """
        signals = {}
        bullish_count = 0
        bearish_count = 0
        
        # RSI
        if 'rsi' in indicators:
            try:
                rsi = indicators['rsi']
                if hasattr(rsi, 'iloc') and len(rsi) > 0:
                    rsi_val = rsi.iloc[-1]
                    if rsi_val > 70:
                        bearish_count += 1  # Перекупленность
                        signals['rsi'] = -0.5
                    elif rsi_val < 30:
                        bullish_count += 1  # Перепроданность
                        signals['rsi'] = 0.5
                    elif rsi_val > 50:
                        signals['rsi'] = 0.2
                    else:
                        signals['rsi'] = -0.2
                else:
                    signals['rsi'] = 0.0
            except Exception:
                signals['rsi'] = 0.0
        
        # MACD
        if 'macd' in indicators and 'macd_signal' in indicators:
            try:
                macd = indicators['macd']
                macd_signal = indicators['macd_signal']
                if hasattr(macd, 'iloc') and len(macd) > 0 and len(macd_signal) > 0:
                    macd_val = macd.iloc[-1]
                    signal_val = macd_signal.iloc[-1]
                    if macd_val > signal_val:
                        bullish_count += 1
                        signals['macd'] = 0.5
                    else:
                        bearish_count += 1
                        signals['macd'] = -0.5
                else:
                    signals['macd'] = 0.0
            except Exception:
                signals['macd'] = 0.0
        
        # StochRSI
        if 'stoch_rsi_k' in indicators and 'stoch_rsi_d' in indicators:
            try:
                stoch_k = indicators['stoch_rsi_k']
                stoch_d = indicators['stoch_rsi_d']
                if hasattr(stoch_k, 'iloc') and len(stoch_k) > 0 and len(stoch_d) > 0:
                    k_val = stoch_k.iloc[-1]
                    d_val = stoch_d.iloc[-1]
                    if k_val > 80 and d_val > 80:
                        bearish_count += 1
                        signals['stoch_rsi'] = -0.5
                    elif k_val < 20 and d_val < 20:
                        bullish_count += 1
                        signals['stoch_rsi'] = 0.5
                    else:
                        signals['stoch_rsi'] = 0.0
                else:
                    signals['stoch_rsi'] = 0.0
            except Exception:
                signals['stoch_rsi'] = 0.0
        
        # WaveTrend (WT)
        if 'wt1' in indicators and 'wt2' in indicators:
            try:
                wt1 = indicators['wt1']
                wt2 = indicators['wt2']
                if hasattr(wt1, 'iloc') and len(wt1) > 0 and len(wt2) > 0:
                    wt1_val = wt1.iloc[-1]
                    wt2_val = wt2.iloc[-1]
                    # Пересечение WT1 выше WT2 = бычий сигнал
                    if wt1_val > wt2_val:
                        bullish_count += 1
                        signals['wt'] = 0.5
                    else:
                        bearish_count += 1
                        signals['wt'] = -0.5
                else:
                    signals['wt'] = 0.0
            except Exception:
                signals['wt'] = 0.0
        
        # Schaff Trend Cycle (STC)
        if 'stc' in indicators:
            try:
                stc = indicators['stc']
                if hasattr(stc, 'iloc') and len(stc) > 0:
                    stc_val = stc.iloc[-1]
                    if stc_val > 75:
                        bearish_count += 1  # Перекупленность
                        signals['stc'] = -0.5
                    elif stc_val < 25:
                        bullish_count += 1  # Перепроданность
                        signals['stc'] = 0.5
                    else:
                        signals['stc'] = 0.0
                else:
                    signals['stc'] = 0.0
            except Exception:
                signals['stc'] = 0.0
        
        # Дивергенции индикаторов (важный сигнал для импульса)
        divergences = features.get('divergences', [])
        if divergences:
            divergence_bullish_count = 0
            divergence_bearish_count = 0
            divergence_strength_sum = 0.0
            
            for div in divergences:
                side = div.get('side', '')
                strength_str = div.get('strength', 'medium')
                indicator = div.get('indicator', '')
                
                # Определяем вес дивергенции по силе
                if strength_str == 'strong':
                    weight = 1.5
                elif strength_str == 'medium':
                    weight = 1.0
                else:  # weak
                    weight = 0.5
                
                if side == 'bullish':
                    divergence_bullish_count += weight
                    divergence_strength_sum += weight
                    signals[f'divergence_{indicator.lower()}'] = weight * 0.8  # Сильный бычий сигнал
                elif side == 'bearish':
                    divergence_bearish_count += weight
                    divergence_strength_sum += weight
                    signals[f'divergence_{indicator.lower()}'] = -weight * 0.8  # Сильный медвежий сигнал
            
            # Дивергенции - это важный сигнал ослабления тренда или разворота
            # Бычья дивергенция увеличивает bullish_count, медвежья - bearish_count
            if divergence_bullish_count > 0:
                bullish_count += divergence_bullish_count
            if divergence_bearish_count > 0:
                bearish_count += divergence_bearish_count
            
            # Если есть дивергенции, добавляем информацию в signals
            if divergence_strength_sum > 0:
                signals['divergences'] = {
                    'bullish': divergence_bullish_count,
                    'bearish': divergence_bearish_count,
                    'total': len(divergences)
                }
        
        # Нормализуем в [-2, 2]
        raw_score = max(-2.0, min(2.0, (bullish_count - bearish_count) / 3.0))
        
        # Используем MomentumIntelligence для улучшения анализа
        momentum_insight = None
        try:
            # Получаем derivatives из features, если доступны
            derivatives_data = features.get('derivatives') if features else None
            momentum_insight = self.momentum_intel.analyse(diag, indicators, features, derivatives_data)
        except Exception:
            # Если MomentumIntelligence не работает, продолжаем без него
            momentum_insight = None
        
        # Корректируем raw_score на основе режима импульса
        # Это позволяет динамически адаптировать силу сигнала на основе контекста
        if momentum_insight:
            regime = momentum_insight.regime
            bias = momentum_insight.bias
            strength = momentum_insight.strength
            
            # Сохраняем исходный score для логирования
            original_score = raw_score
            
            # Корректируем raw_score в зависимости от режима импульса
            if regime == "EXHAUSTION":
                # При перегретости снижаем силу сигнала (риск коррекции)
                # Если bias совпадает с направлением raw_score - снижаем (риск разворота)
                if (bias == "LONG" and raw_score > 0) or (bias == "SHORT" and raw_score < 0):
                    # Снижаем на 30-50% в зависимости от strength перегретости
                    # Чем выше strength, тем больше снижение
                    exhaustion_factor = max(0.5, 1.0 - (strength * 0.5))  # Минимум 50% от исходного
                    raw_score = raw_score * exhaustion_factor
                    signals['momentum_intel'] = {
                        'regime': regime,
                        'adjustment': f'exhaustion_factor={exhaustion_factor:.2f}',
                        'original_score': original_score
                    }
            elif regime == "REVERSAL_RISK":
                # При риске разворота усиливаем сигнал (локальный импульс против тренда)
                # Это важный сигнал - локальное движение против общего тренда
                if (bias == "LONG" and raw_score > 0) or (bias == "SHORT" and raw_score < 0):
                    # Усиливаем на 20-40% в зависимости от strength
                    # Чем сильнее локальный импульс, тем больше усиление
                    reversal_factor = 1.0 + (strength * 0.4)
                    raw_score = raw_score * reversal_factor
                    # Ограничиваем, чтобы не выйти за [-2, 2]
                    raw_score = max(-2.0, min(2.0, raw_score))
                    signals['momentum_intel'] = {
                        'regime': regime,
                        'adjustment': f'reversal_factor={reversal_factor:.2f}',
                        'original_score': original_score
                    }
            elif regime == "CONTINUATION":
                # При продолжении тренда слегка усиливаем сигнал
                # Подтверждаем, что импульс поддерживает тренд
                if abs(raw_score) > 0.3:  # Только если есть значимый сигнал
                    continuation_factor = 1.0 + (strength * 0.15)  # Максимум +15%
                    raw_score = raw_score * continuation_factor
                    raw_score = max(-2.0, min(2.0, raw_score))
                    signals['momentum_intel'] = {
                        'regime': regime,
                        'adjustment': f'continuation_factor={continuation_factor:.2f}',
                        'original_score': original_score
                    }
            else:  # NEUTRAL
                # При нейтральном режиме слегка снижаем силу сигнала
                # Нет явного преимущества, поэтому снижаем уверенность
                if abs(raw_score) > 0.5:
                    neutral_factor = 0.9  # Снижаем на 10%
                    raw_score = raw_score * neutral_factor
                    signals['momentum_intel'] = {
                        'regime': regime,
                        'adjustment': f'neutral_factor={neutral_factor:.2f}',
                        'original_score': original_score
                    }
        
        # Описание с учетом дивергенций и MomentumIntelligence
        divergence_info = ""
        if divergences:
            bullish_divs = sum(1 for d in divergences if d.get('side') == 'bullish')
            bearish_divs = sum(1 for d in divergences if d.get('side') == 'bearish')
            if bullish_divs > 0 or bearish_divs > 0:
                div_texts = []
                if bullish_divs > 0:
                    div_texts.append(f"{bullish_divs} бычья")
                if bearish_divs > 0:
                    div_texts.append(f"{bearish_divs} медвежья")
                divergence_info = f" ({', '.join(div_texts)} дивергенция)"
        
        # Добавляем информацию о режиме импульса в summary
        momentum_regime_info = ""
        if momentum_insight:
            regime = momentum_insight.regime
            if regime == "EXHAUSTION":
                momentum_regime_info = " (признаки перегретости)"
            elif regime == "REVERSAL_RISK":
                momentum_regime_info = " (риск разворота)"
            elif regime == "CONTINUATION":
                momentum_regime_info = " (продолжение тренда)"
        
        if raw_score > 0.5:
            summary = f"Импульс растёт{divergence_info}{momentum_regime_info}"
        elif raw_score < -0.5:
            summary = f"Импульс падает{divergence_info}{momentum_regime_info}"
        else:
            summary = f"Импульс нейтрален{divergence_info}{momentum_regime_info}"
        
        return GroupScore(
            group=IndicatorGroup.MOMENTUM,
            raw_score=raw_score,
            signals=signals,
            summary=summary
        )
    
    def score_volume_group(self, diag: MarketDiagnostics, indicators: dict, features: dict) -> GroupScore:
        """
        Оценить группу объёмных индикаторов.
        
        Включает: OBV, CMF, Volume MA
        """
        signals = {}
        bullish_count = 0
        bearish_count = 0
        
        # OBV направление
        extra = diag.extra_metrics or {}
        money_flow_state = extra.get('money_flow_state', '')
        
        if '↓' in money_flow_state or 'Падение' in money_flow_state:
            bearish_count += 1
            signals['obv'] = -0.8
        elif '↑' in money_flow_state or 'Рост' in money_flow_state:
            bullish_count += 1
            signals['obv'] = 0.8
        else:
            signals['obv'] = 0.0
        
        # CMF
        import re
        cmf_match = re.search(r'CMF:\s*([-+]?\d+\.?\d*)', money_flow_state)
        if cmf_match:
            cmf_value = float(cmf_match.group(1))
            if cmf_value > 0.05:
                bullish_count += 1
                signals['cmf'] = 0.5
            elif cmf_value < -0.05:
                bearish_count += 1
                signals['cmf'] = -0.5
            else:
                signals['cmf'] = 0.0
        else:
            signals['cmf'] = 0.0
        
        # Нормализуем
        raw_score = max(-2.0, min(2.0, (bullish_count - bearish_count) / 1.5))
        
        # Описание
        if raw_score > 0.5:
            summary = "Объём подтверждает рост"
        elif raw_score < -0.5:
            summary = "Объём подтверждает падение"
        else:
            summary = "Объём нейтрален"
        
        return GroupScore(
            group=IndicatorGroup.VOLUME,
            raw_score=raw_score,
            signals=signals,
            summary=summary
        )
    
    def score_volatility_group(self, diag: MarketDiagnostics, indicators: dict, features: dict) -> GroupScore:
        """
        Оценить группу волатильности.
        
        Включает: Bollinger Bands, ATR
        """
        signals = {}
        bullish_count = 0
        bearish_count = 0
        
        # Bollinger Bands
        extra = diag.extra_metrics or {}
        bb_state = extra.get('bb_state', '')
        
        if 'выше верхней' in bb_state or 'above upper' in bb_state.lower():
            bearish_count += 1  # Перекупленность
            signals['bb'] = -0.5
        elif 'ниже нижней' in bb_state or 'below lower' in bb_state.lower():
            bullish_count += 1  # Перепроданность
            signals['bb'] = 0.5
        else:
            signals['bb'] = 0.0
        
        # Волатильность из диагностики
        if hasattr(diag.volatility, 'value'):
            vol_val = diag.volatility.value
        else:
            vol_val = str(diag.volatility)
        
        if vol_val == 'HIGH':
            # Высокая волатильность может быть как бычьей, так и медвежьей
            # Зависит от направления тренда
            trend_val = diag.trend.value if hasattr(diag.trend, 'value') else str(diag.trend)
            if trend_val in ['BULLISH', 'bullish']:
                signals['volatility'] = 0.3
            elif trend_val in ['BEARISH', 'bearish']:
                signals['volatility'] = -0.3
            else:
                signals['volatility'] = 0.0
        else:
            signals['volatility'] = 0.0
        
        raw_score = max(-2.0, min(2.0, (bullish_count - bearish_count) / 1.5))
        
        if raw_score > 0.3:
            summary = "Волатильность поддерживает рост"
        elif raw_score < -0.3:
            summary = "Волатильность поддерживает падение"
        else:
            summary = "Волатильность нейтральна"
        
        return GroupScore(
            group=IndicatorGroup.VOLATILITY,
            raw_score=raw_score,
            signals=signals,
            summary=summary
        )
    
    def score_structure_group(self, diag: MarketDiagnostics, indicators: dict, features: dict) -> GroupScore:
        """
        Оценить группу структуры рынка (SMC).
        
        Включает: BOS, Premium/Discount, FVG, Liquidity pools
        """
        signals = {}
        bullish_count = 0
        bearish_count = 0
        
        # BOS
        if diag.smc_context and diag.smc_context.last_bos:
            bos = diag.smc_context.last_bos
            if bos.direction == "up":
                bullish_count += 1
                signals['bos'] = 0.8
            else:
                bearish_count += 1
                signals['bos'] = -0.8
        else:
            signals['bos'] = 0.0
        
        # Premium/Discount
        if diag.smc_context:
            smc = diag.smc_context
            if smc.current_position == "discount":
                bullish_count += 1
                signals['premium_discount'] = 0.5
            elif smc.current_position == "premium":
                bearish_count += 1
                signals['premium_discount'] = -0.5
            else:
                signals['premium_discount'] = 0.0
        
        # Фаза рынка
        phase_val = diag.phase.value if hasattr(diag.phase, 'value') else str(diag.phase)
        if phase_val in ['ACCUMULATION', 'EXPANSION_UP']:
            bullish_count += 1
            signals['phase'] = 0.5
        elif phase_val in ['DISTRIBUTION', 'EXPANSION_DOWN']:
            bearish_count += 1
            signals['phase'] = -0.5
        else:
            signals['phase'] = 0.0
        
        raw_score = max(-2.0, min(2.0, (bullish_count - bearish_count) / 2.0))
        
        if raw_score > 0.5:
            summary = "Структура поддерживает рост"
        elif raw_score < -0.5:
            summary = "Структура поддерживает падение"
        else:
            summary = "Структура нейтральна"
        
        return GroupScore(
            group=IndicatorGroup.STRUCTURE,
            raw_score=raw_score,
            signals=signals,
            summary=summary
        )
    
    def score_derivatives_group(self, diag: MarketDiagnostics, indicators: dict, features: dict, derivatives: dict) -> GroupScore:
        """
        Оценить группу деривативов.
        
        Включает: Funding, OI, CVD
        """
        signals = {}
        bullish_count = 0
        bearish_count = 0
        
        # Funding
        funding = derivatives.get('funding_rate', 0.0)
        if funding > 0.01:  # Высокий funding → медвежий сигнал
            bearish_count += 1
            signals['funding'] = -0.5
        elif funding < -0.01:  # Отрицательный funding → бычий
            bullish_count += 1
            signals['funding'] = 0.5
        else:
            signals['funding'] = 0.0
        
        # OI change
        oi_change = derivatives.get('oi_change_24h', 0.0)
        trend_val = diag.trend.value if hasattr(diag.trend, 'value') else str(diag.trend)
        if oi_change > 0.05:  # Рост OI при падении → медвежий
            if trend_val in ['BEARISH', 'bearish']:
                bearish_count += 1
                signals['oi'] = -0.5
        elif oi_change < -0.05:  # Падение OI при росте → бычий
            if trend_val in ['BULLISH', 'bullish']:
                bullish_count += 1
                signals['oi'] = 0.5
        else:
            signals['oi'] = 0.0
        
        raw_score = max(-2.0, min(2.0, (bullish_count - bearish_count) / 1.5))
        
        if raw_score > 0.3:
            summary = "Деривативы поддерживают рост"
        elif raw_score < -0.3:
            summary = "Деривативы поддерживают падение"
        else:
            summary = "Деривативы нейтральны"
        
        return GroupScore(
            group=IndicatorGroup.DERIVATIVES,
            raw_score=raw_score,
            signals=signals,
            summary=summary
        )
    
    def score_timeframe(
        self,
        diag: MarketDiagnostics,
        indicators: dict,
        features: dict,
        derivatives: dict,
        timeframe: str,
        target_tf: Optional[str] = None
    ) -> TimeframeScore:
        """
        Посчитать score для одного таймфрейма.
        
        Args:
            diag: MarketDiagnostics для таймфрейма
            indicators: Словарь индикаторов
            features: Словарь признаков
            derivatives: Словарь деривативов
            timeframe: Таймфрейм
        
        Returns:
            TimeframeScore
        """
        # Проверяем кэш
        cache_key = f"{diag.symbol}_{timeframe}_{diag.timestamp if hasattr(diag, 'timestamp') else 'none'}"
        if cache_key in self._cache:
            cached_score, cached_ts = self._cache[cache_key]
            if (datetime.now() - cached_ts).total_seconds() < self._cache_ttl:
                return cached_score
        
        # Считаем score для каждой группы
        group_scores = {}
        
        group_scores[IndicatorGroup.TREND] = self.score_trend_group(diag, indicators, features)
        group_scores[IndicatorGroup.MOMENTUM] = self.score_momentum_group(diag, indicators, features)
        group_scores[IndicatorGroup.VOLUME] = self.score_volume_group(diag, indicators, features)
        group_scores[IndicatorGroup.VOLATILITY] = self.score_volatility_group(diag, indicators, features)
        group_scores[IndicatorGroup.STRUCTURE] = self.score_structure_group(diag, indicators, features)
        group_scores[IndicatorGroup.DERIVATIVES] = self.score_derivatives_group(diag, indicators, features, derivatives)
        
        # Взвешенная сумма
        net_score = sum(
            group_scores[group].raw_score * self.weights[group]
            for group in IndicatorGroup
        )
        
        # Нормализуем в [0, 10]
        normalized_long = (net_score + 2) / 4 * 10
        normalized_short = 10 - normalized_long
        
        # Вес таймфрейма (будет использован при агрегации)
        # Используем target_tf для правильного расчёта весов, если передан
        if target_tf is None:
            target_tf = "1h"  # По умолчанию
        weight = TF_WEIGHTS_FOR_TARGET.get(target_tf, {}).get(timeframe, 0.0)
        
        # Безопасное извлечение значений
        regime_val = diag.phase.value if hasattr(diag.phase, 'value') else str(diag.phase)
        trend_val = diag.trend.value if hasattr(diag.trend, 'value') else str(diag.trend)
        
        result = TimeframeScore(
            timeframe=timeframe,
            weight=weight,
            regime=regime_val,
            trend=trend_val,
            group_scores=group_scores,
            net_score=net_score,
            normalized_long=max(0, min(10, normalized_long)),
            normalized_short=max(0, min(10, normalized_short))
        )
        
        # Сохраняем в кэш
        self._cache[cache_key] = (result, datetime.now())
        
        # Очищаем старый кэш
        self._clean_cache()
        
        return result
    
    def _clean_cache(self):
        """Очистить устаревший кэш."""
        now = datetime.now()
        keys_to_remove = [
            key for key, (_, ts) in self._cache.items()
            if (now - ts).total_seconds() > self._cache_ttl
        ]
        for key in keys_to_remove:
            del self._cache[key]
    
    def aggregate_multi_tf(
        self,
        per_tf_scores: Dict[str, TimeframeScore],
        target_tf: str = "1h"
    ) -> MultiTFScore:
        """
        Агрегировать scores по всем таймфреймам.
        
        Args:
            per_tf_scores: Словарь {timeframe: TimeframeScore}
            target_tf: Целевой таймфрейм для сигнала
        
        Returns:
            MultiTFScore
        """
        weights = TF_WEIGHTS_FOR_TARGET.get(target_tf, {})
        
        # Взвешенная сумма net_score
        aggregated_net = sum(
            score.net_score * weights.get(tf, 0.0)
            for tf, score in per_tf_scores.items()
        )
        
        # Нормализуем в [0, 10]
        aggregated_long = (aggregated_net + 2) / 4 * 10
        aggregated_short = 10 - aggregated_long
        
        # Confidence на основе согласованности
        confidence = self._compute_confidence(per_tf_scores, target_tf)
        
        # Направление
        direction = "LONG" if aggregated_long > aggregated_short else "SHORT"
        
        # Вычисляем Momentum Grade и Comment на основе momentum группы
        momentum_grade, momentum_comment = self._compute_momentum_grade_and_comment(
            per_tf_scores, target_tf
        )
        
        return MultiTFScore(
            target_tf=target_tf,
            per_tf=per_tf_scores,
            aggregated_long=max(0, min(10, aggregated_long)),
            aggregated_short=max(0, min(10, aggregated_short)),
            confidence=confidence,
            direction=direction,
            momentum_grade=momentum_grade,
            momentum_comment=momentum_comment
        )
    
    def _compute_momentum_grade_and_comment(
        self,
        per_tf_scores: Dict[str, TimeframeScore],
        target_tf: str
    ) -> tuple[Optional[str], Optional[str]]:
        """
        Вычислить Momentum Grade и Comment на основе momentum группы scores.
        
        Args:
            per_tf_scores: Словарь scores по ТФ
            target_tf: Целевой таймфрейм
        
        Returns:
            Tuple (momentum_grade, momentum_comment)
        """
        # Получаем momentum group score для целевого таймфрейма
        if target_tf not in per_tf_scores:
            return None, None
        
        target_score = per_tf_scores[target_tf]
        momentum_group = target_score.group_scores.get(IndicatorGroup.MOMENTUM)
        
        if not momentum_group:
            return None, None
        
        # Получаем momentum_intel из signals, если есть
        momentum_intel = momentum_group.signals.get('momentum_intel')
        
        # Определяем bias и strength на основе momentum score
        momentum_score = momentum_group.raw_score
        momentum_strength = abs(momentum_score)
        
        # Определяем grade на основе score и strength
        if momentum_score > 1.0:
            grade = "STRONG_BULLISH"
            if momentum_intel and momentum_intel.get('regime') == 'EXHAUSTION':
                comment = "сильный бычий импульс, признаки перегретости"
            elif momentum_intel and momentum_intel.get('regime') == 'REVERSAL_RISK':
                comment = "сильный бычий импульс, риск разворота"
            elif momentum_intel and momentum_intel.get('regime') == 'CONTINUATION':
                comment = "сильный бычий continuation"
            else:
                comment = "сильный бычий импульс"
        elif momentum_score > 0.3:
            grade = "WEAK_BULLISH"
            if momentum_intel and momentum_intel.get('regime') == 'EXHAUSTION':
                comment = "слабый бычий импульс, признаки перегретости"
            elif momentum_intel and momentum_intel.get('regime') == 'REVERSAL_RISK':
                comment = "слабый бычий импульс, высокий риск разворота"
            else:
                comment = "слабый бычий импульс"
        elif momentum_score < -1.0:
            grade = "STRONG_BEARISH"
            if momentum_intel and momentum_intel.get('regime') == 'EXHAUSTION':
                comment = "сильный медвежий импульс, признаки перепроданности"
            elif momentum_intel and momentum_intel.get('regime') == 'REVERSAL_RISK':
                comment = "сильный медвежий импульс, риск разворота"
            elif momentum_intel and momentum_intel.get('regime') == 'CONTINUATION':
                comment = "сильный медвежий continuation"
            else:
                comment = "сильный медвежий импульс"
        elif momentum_score < -0.3:
            grade = "WEAK_BEARISH"
            if momentum_intel and momentum_intel.get('regime') == 'EXHAUSTION':
                comment = "слабый медвежий импульс, признаки перепроданности"
            elif momentum_intel and momentum_intel.get('regime') == 'REVERSAL_RISK':
                comment = "слабый медвежий импульс, высокий риск разворота"
            else:
                comment = "слабый медвежий импульс"
        else:
            grade = "NEUTRAL"
            comment = "импульс нейтрален"
        
        return grade, comment
    
    def _compute_confidence(
        self,
        per_tf_scores: Dict[str, TimeframeScore],
        target_tf: str
    ) -> float:
        """
        Вычислить confidence на основе согласованности таймфреймов.
        
        Args:
            per_tf_scores: Словарь scores по ТФ
            target_tf: Целевой таймфрейм
        
        Returns:
            Confidence [0, 1]
        """
        if target_tf not in per_tf_scores:
            return 0.5
        
        weights = TF_WEIGHTS_FOR_TARGET.get(target_tf, {})
        target_score = per_tf_scores[target_tf]
        target_sign = 1 if target_score.net_score > 0.2 else (-1 if target_score.net_score < -0.2 else 0)
        
        if target_sign == 0:
            return 0.4
        
        aligned = 0.0
        total = 0.0
        
        for tf, score in per_tf_scores.items():
            w = weights.get(tf, 0.0)
            if w <= 0:
                continue
            
            total += w
            sign = 1 if score.net_score > 0.2 else (-1 if score.net_score < -0.2 else 0)
            
            if sign == target_sign:
                aligned += w
            elif sign == 0:
                aligned += w * 0.3
            # else: против - не добавляем
        
        ratio = aligned / (total or 1.0)
        confidence = 0.3 + 0.7 * ratio
        return round(confidence, 2)

