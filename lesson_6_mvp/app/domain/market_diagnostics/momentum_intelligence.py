# app/domain/market_diagnostics/momentum_intelligence.py
"""
Momentum Intelligence Layer for Market Doctor.

Не меняет числовые scores напрямую.
Берёт уже посчитанные индикаторы (RSI, StochRSI, MACD, WT, STC)
и возвращает компактное описание состояния импульса:

- continuation vs exhaustion vs reversal-risk
- bullish / bearish / neutral bias
- относительную силу 0..1

Сделано максимально консервативно, чтобы ничего не сломать.
"""

from dataclasses import dataclass
from typing import Dict, Optional

from .analyzer import MarketDiagnostics
from .features import TrendState, VolatilityState, LiquidityState


@dataclass
class MomentumInsight:
    """Высокоуровневое описание импульса на ТФ."""
    bias: str                 # "LONG" / "SHORT" / "NEUTRAL"
    regime: str               # "CONTINUATION" / "EXHAUSTION" / "REVERSAL_RISK" / "NEUTRAL"
    strength: float           # 0..1
    confidence: float         # 0..1 - уверенность в анализе
    comment: str              # Короткий текст (RU)
    details: Dict[str, float] # Вклад отдельных индикаторов


class MomentumIntelligence:
    """
    Rule-based движок поверх уже существующих осцилляторов.

    Цель v1 — быть осторожным: помечать только довольно очевидные
    ситуации и НЕ вмешиваться в текущую числовую систему скоринга.
    """

    def analyse(
        self, 
        diag: MarketDiagnostics, 
        indicators: Dict[str, object],
        features: Optional[Dict] = None,
        derivatives: Optional[Dict[str, float]] = None
    ) -> Optional[MomentumInsight]:
        """
        Построить описание импульса.

        Args:
            diag: диагностика MarketDiagnostics для ТФ
            indicators: словарь индикаторов (как из Indicators.calculate_all)
            features: словарь признаков (опционально, для учета дивергенций)
            derivatives: словарь деривативов (опционально, funding_rate, oi_change_pct, cvd)

        Returns:
            MomentumInsight или None, если данных мало
        """
        def last(name: str) -> Optional[float]:
            series = indicators.get(name)
            try:
                if hasattr(series, "iloc") and len(series) > 0:
                    return float(series.iloc[-1])
            except Exception:
                return None
            return None
        
        def get_series(name: str) -> Optional[object]:
            """Получить серию индикатора для анализа скорости изменения."""
            series = indicators.get(name)
            try:
                if hasattr(series, "iloc") and len(series) > 0:
                    return series
            except Exception:
                return None
            return None
        
        def change(name: str, periods: int = 3) -> Optional[float]:
            """Получить изменение индикатора за последние N периодов."""
            series = get_series(name)
            if series is not None and len(series) >= periods + 1:
                try:
                    return float(series.iloc[-1] - series.iloc[-(periods + 1)])
                except Exception:
                    return None
            return None

        rsi = last("rsi")
        rsi_series = get_series("rsi")
        stoch_k = last("stoch_rsi_k")
        stoch_d = last("stoch_rsi_d")
        macd = last("macd")
        macd_signal = last("macd_signal")
        macd_hist = last("macd_hist")
        macd_hist_series = get_series("macd_hist")
        wt1 = last("wt1")
        wt2 = last("wt2")
        stc = last("stc")
        
        # ADX и DI для анализа силы тренда
        adx = last("adx")
        plus_di = last("+di")
        minus_di = last("-di")
        
        # ATR для калибровки порогов на основе волатильности
        atr = last("atr")
        atr_series = get_series("atr")
        
        # EMA для анализа угла тренда
        ema_20 = get_series("ema_20")
        ema_50 = get_series("ema_50")
        
        # Текущая цена для расчета ATR%
        # Пытаемся получить из close в indicators (если передан DataFrame)
        current_price = None
        close_series = get_series("close")
        if close_series is not None and len(close_series) > 0:
            try:
                current_price = float(close_series.iloc[-1])
            except Exception:
                pass
        
        # Если не получилось, пытаемся из diag (может быть в extra_metrics)
        if current_price is None:
            extra = getattr(diag, "extra_metrics", {}) or {}
            current_price = extra.get("current_price")

        available = [v for v in [rsi, stoch_k, macd, wt1, stc] if v is not None]
        if len(available) < 2:
            return None

        bullish = 0.0
        bearish = 0.0
        exhaustion_up = 0.0
        exhaustion_down = 0.0
        details: Dict[str, float] = {}
        
        # Калибровка порогов на основе волатильности (ATR%)
        rsi_overbought = 70
        rsi_oversold = 30
        stoch_overbought = 80
        stoch_oversold = 20
        stc_overbought = 75
        stc_oversold = 25
        
        if atr is not None and current_price is not None and current_price > 0:
            atr_pct = (atr / current_price) * 100
            if atr_pct > 3:  # Высокая волатильность (>3%)
                rsi_overbought = 75  # Повышаем порог
                rsi_oversold = 25
                stoch_overbought = 85
                stoch_oversold = 15
                stc_overbought = 80
                stc_oversold = 20
                details["volatility_adjustment"] = "high"
            elif atr_pct < 1:  # Низкая волатильность (<1%)
                rsi_overbought = 65  # Снижаем порог
                rsi_oversold = 35
                stoch_overbought = 75
                stoch_oversold = 25
                stc_overbought = 70
                stc_oversold = 30
                details["volatility_adjustment"] = "low"
            else:
                details["volatility_adjustment"] = "normal"

        # --- RSI ---
        if rsi is not None:
            rsi_change = change("rsi", 3)  # Изменение за 3 бара
            
            if rsi > rsi_overbought:
                exhaustion_up += 1.0
                bearish += 0.3
                details["rsi"] = -0.7
                # Если RSI падает из перекупленности - признак ослабления
                if rsi_change is not None and rsi_change < -2:
                    exhaustion_up += 0.3
                    details["rsi_slowing"] = -0.3
            elif rsi < rsi_oversold:
                exhaustion_down += 1.0
                bullish += 0.3
                details["rsi"] = 0.7
                # Если RSI растет из перепроданности - признак ослабления
                if rsi_change is not None and rsi_change > 2:
                    exhaustion_down += 0.3
                    details["rsi_slowing"] = 0.3
            elif rsi > 55:
                bullish += 0.6
                details["rsi"] = 0.6
                # Ускорение RSI = усиление импульса
                if rsi_change is not None and rsi_change > 1:
                    bullish += 0.2
                    details["rsi_accelerating"] = 0.2
            elif rsi < 45:
                bearish += 0.6
                details["rsi"] = -0.6
                # Ускорение падения RSI = усиление медвежьего импульса
                if rsi_change is not None and rsi_change < -1:
                    bearish += 0.2
                    details["rsi_accelerating"] = -0.2
            else:
                details["rsi"] = 0.0

        # --- Stoch RSI ---
        if stoch_k is not None and stoch_d is not None:
            if stoch_k > stoch_overbought and stoch_d > stoch_overbought:
                exhaustion_up += 0.5
                bearish += 0.2
                details["stoch_rsi"] = -0.6
            elif stoch_k < stoch_oversold and stoch_d < stoch_oversold:
                exhaustion_down += 0.5
                bullish += 0.2
                details["stoch_rsi"] = 0.6
            elif stoch_k > stoch_d and stoch_k > 50:
                bullish += 0.4
                details["stoch_rsi"] = 0.4
            elif stoch_k < stoch_d and stoch_k < 50:
                bearish += 0.4
                details["stoch_rsi"] = -0.4

        # --- MACD ---
        if macd is not None and macd_signal is not None:
            if macd > macd_signal and macd > 0:
                bullish += 0.7
                details["macd"] = 0.7
            elif macd < macd_signal and macd < 0:
                bearish += 0.7
                details["macd"] = -0.7
            elif macd > 0:
                bullish += 0.3
                details["macd"] = 0.3
            elif macd < 0:
                bearish += 0.3
                details["macd"] = -0.3
        
        # --- MACD Histogram (скорость изменения импульса) ---
        if macd_hist is not None and macd_hist_series is not None:
            macd_hist_change = change("macd_hist", 2)  # Изменение за 2 бара
            
            if macd_hist > 0:
                # Бычий MACD histogram
                if macd_hist_change is not None:
                    if macd_hist_change < 0:
                        # MACD histogram уменьшается = ослабление бычьего импульса
                        bullish -= 0.2
                        details["macd_hist_slowing"] = -0.2
                    elif macd_hist_change > 0:
                        # MACD histogram увеличивается = усиление импульса
                        bullish += 0.2
                        details["macd_hist_accelerating"] = 0.2
            elif macd_hist < 0:
                # Медвежий MACD histogram
                if macd_hist_change is not None:
                    if macd_hist_change > 0:
                        # MACD histogram увеличивается = ослабление медвежьего импульса
                        bearish -= 0.2
                        details["macd_hist_slowing"] = 0.2
                    elif macd_hist_change < 0:
                        # MACD histogram уменьшается = усиление медвежьего импульса
                        bearish += 0.2
                        details["macd_hist_accelerating"] = -0.2

        # --- WaveTrend ---
        if wt1 is not None and wt2 is not None:
            if wt1 > wt2:
                bullish += 0.5
                details["wt"] = 0.5
            elif wt1 < wt2:
                bearish += 0.5
                details["wt"] = -0.5

        # --- Schaff Trend Cycle ---
        if stc is not None:
            if stc > stc_overbought:
                exhaustion_up += 0.5
                bearish += 0.2
                details["stc"] = -0.6
            elif stc < stc_oversold:
                exhaustion_down += 0.5
                bullish += 0.2
                details["stc"] = 0.6
            elif stc > 50:
                bullish += 0.3
                details["stc"] = 0.3
            else:
                bearish += 0.1
                details["stc"] = -0.1

        # Учет дивергенций (если доступны)
        divergence_bullish_impact = 0.0
        divergence_bearish_impact = 0.0
        if features:
            divergences = features.get('divergences', [])
            if divergences:
                for div in divergences:
                    side = div.get('side', '')
                    strength_str = div.get('strength', 'medium')
                    # Определяем вес дивергенции по силе
                    if strength_str == 'strong':
                        weight = 0.8
                    elif strength_str == 'medium':
                        weight = 0.5
                    else:  # weak
                        weight = 0.3
                    
                    # Бычья дивергенция = ослабление медвежьего импульса (усиление бычьего)
                    # Медвежья дивергенция = ослабление бычьего импульса (усиление медвежьего)
                    if side == 'bullish':
                        divergence_bullish_impact += weight
                        bullish += weight * 0.5  # Дивергенция - сигнал разворота, но не прямой импульс
                    elif side == 'bearish':
                        divergence_bearish_impact += weight
                        bearish += weight * 0.5
                
                details['divergences'] = {
                    'bullish_impact': divergence_bullish_impact,
                    'bearish_impact': divergence_bearish_impact,
                    'count': len(divergences)
                }

        total_trend = bullish - bearish
        total_exhaustion = exhaustion_up + exhaustion_down

        # Bias (определяем после учета дивергенций)
        if total_trend > 0.6:
            bias = "LONG"
        elif total_trend < -0.6:
            bias = "SHORT"
        else:
            bias = "NEUTRAL"
        
        # Теперь учитываем дивергенции для определения ослабления импульса
        if features:
            divergences = features.get('divergences', [])
            if divergences:
                for div in divergences:
                    side = div.get('side', '')
                    strength_str = div.get('strength', 'medium')
                    if strength_str == 'strong':
                        weight = 0.8
                    elif strength_str == 'medium':
                        weight = 0.5
                    else:
                        weight = 0.3
                    
                    # Дивергенции указывают на возможное ослабление текущего импульса
                    if side == 'bullish' and bias == "SHORT":
                        # Бычья дивергенция при медвежьем импульсе = признак ослабления
                        exhaustion_down += weight * 0.3
                    elif side == 'bearish' and bias == "LONG":
                        # Медвежья дивергенция при бычьем импульсе = признак ослабления
                        exhaustion_up += weight * 0.3
                
                # Пересчитываем total_exhaustion после учета дивергенций
                total_exhaustion = exhaustion_up + exhaustion_down
        
        # Анализ конвергенции индикаторов к экстремальным значениям
        extreme_overbought_count = 0
        extreme_oversold_count = 0
        
        if rsi is not None and rsi > rsi_overbought:
            extreme_overbought_count += 1
        if stoch_k is not None and stoch_k > stoch_overbought:
            extreme_overbought_count += 1
        if stc is not None and stc > stc_overbought:
            extreme_overbought_count += 1
        
        if rsi is not None and rsi < rsi_oversold:
            extreme_oversold_count += 1
        if stoch_k is not None and stoch_k < stoch_oversold:
            extreme_oversold_count += 1
        if stc is not None and stc < stc_oversold:
            extreme_oversold_count += 1
        
        # Конвергенция к перекупленности = сильный сигнал EXHAUSTION
        if extreme_overbought_count >= 2:
            exhaustion_up += 0.5
            details["convergence_overbought"] = extreme_overbought_count
        # Конвергенция к перепроданности = сильный сигнал EXHAUSTION
        if extreme_oversold_count >= 2:
            exhaustion_down += 0.5
            details["convergence_oversold"] = extreme_oversold_count
        
        # Пересчитываем total_exhaustion после учета конвергенции
        total_exhaustion = exhaustion_up + exhaustion_down
        
        # Учет угла тренда (EMA slope)
        ema_slope_20 = None
        ema_slope_50 = None
        
        if ema_20 is not None and len(ema_20) >= 5:
            try:
                ema_slope_20 = (ema_20.iloc[-1] - ema_20.iloc[-5]) / ema_20.iloc[-5]
                details["ema_20_slope"] = ema_slope_20
            except Exception:
                pass
        
        if ema_50 is not None and len(ema_50) >= 5:
            try:
                ema_slope_50 = (ema_50.iloc[-1] - ema_50.iloc[-5]) / ema_50.iloc[-5]
                details["ema_50_slope"] = ema_slope_50
            except Exception:
                pass
        
        # Используем более короткую EMA для анализа угла (более чувствительна)
        ema_slope = ema_slope_20 if ema_slope_20 is not None else ema_slope_50

        trend_state = getattr(diag, "trend", None)
        trend_str = (
            trend_state.value if isinstance(trend_state, TrendState)
            else str(trend_state)
        )

        # Определяем базовый regime (будет скорректирован позже на основе деривативов и SMC)
        regime = "NEUTRAL"
        comment = "Импульс нейтрален"
        strength = min(1.0, abs(total_trend))

        if bias == "LONG" and "BEAR" in str(trend_str).upper():
            regime = "REVERSAL_RISK"
            comment = "Локальный бычий импульс против медвежьего тренда — повышенный риск разворота."
        elif bias == "SHORT" and "BULL" in str(trend_str).upper():
            regime = "REVERSAL_RISK"
            comment = "Локальный медвежий импульс против бычьего тренда — возможен разворот."
        else:
            if total_exhaustion >= 1.0:
                regime = "EXHAUSTION"
                if bias == "LONG":
                    comment = "Импульс бычий, но есть признаки перегретости — риск коррекции."
                elif bias == "SHORT":
                    comment = "Импульс медвежий, но есть признаки усталости — возможен отскок."
                else:
                    comment = "Импульс ослабляет тренд, возможна консолидация."
                
                # Учет угла тренда для EXHAUSTION
                if ema_slope is not None:
                    if abs(ema_slope) > 0.05:  # Очень крутой тренд (>5% за 5 баров)
                        # Очень крутой тренд + перекупленность = сильный сигнал
                        strength += 0.1
                        details["steep_trend_exhaustion"] = abs(ema_slope)
            elif abs(total_trend) >= 0.8:
                regime = "CONTINUATION"
                if bias == "LONG":
                    comment = "Сильный бычий импульс по тренду."
                elif bias == "SHORT":
                    comment = "Сильный медвежий импульс по тренду."
                
                # Учет угла тренда для CONTINUATION
                if ema_slope is not None:
                    if abs(ema_slope) > 0.05:  # Крутой тренд
                        # Крутой тренд подтверждает CONTINUATION
                        strength += 0.1
                        details["steep_trend_continuation"] = abs(ema_slope)
            else:
                regime = "NEUTRAL"
                comment = "Импульс умеренный, без ярко выраженного преимущества."
        
        # Финальный пересчет total_exhaustion после всех изменений (деривативы, SMC)
        # Это нужно для правильного расчета strength
        total_exhaustion = exhaustion_up + exhaustion_down

        strength = float(round(min(1.0, strength + total_exhaustion * 0.2), 2))
        
        # Вычисляем confidence на основе:
        # 1. Количества доступных индикаторов
        # 2. Согласованности сигналов
        # 3. Волатильности (в высокой волатильности confidence ниже)
        # 4. Объема (подтверждение объемом повышает confidence)
        
        # Базовый confidence от количества индикаторов
        available_count = len([v for v in [rsi, stoch_k, macd, wt1, stc] if v is not None])
        base_confidence = min(1.0, available_count / 5.0)  # Максимум при 5 индикаторах
        
        # Согласованность сигналов (чем больше индикаторов в одном направлении, тем выше confidence)
        total_signals = abs(bullish) + abs(bearish)
        if total_signals > 0:
            consensus = max(abs(bullish), abs(bearish)) / total_signals
            base_confidence = base_confidence * (0.5 + consensus * 0.5)  # 0.5-1.0
        
        # Учет волатильности
        volatility_state = getattr(diag, "volatility", None)
        if isinstance(volatility_state, VolatilityState):
            if volatility_state == VolatilityState.HIGH:
                base_confidence = base_confidence * 0.75  # Снижаем на 25% в высокой волатильности
            elif volatility_state == VolatilityState.LOW:
                base_confidence = base_confidence * 1.1  # Повышаем на 10% в низкой волатильности
                base_confidence = min(1.0, base_confidence)
        
        # Учет объема (подтверждение направлением денежного потока)
        volume_confirmation = 1.0
        extra = getattr(diag, "extra_metrics", {}) or {}
        money_flow_state = extra.get('money_flow_state', '')
        if money_flow_state:
            if bias == "LONG" and ('↑' in money_flow_state or 'Рост' in money_flow_state):
                volume_confirmation = 1.15  # Объем подтверждает бычий импульс
            elif bias == "SHORT" and ('↓' in money_flow_state or 'Падение' in money_flow_state):
                volume_confirmation = 1.15  # Объем подтверждает медвежий импульс
            elif bias == "LONG" and ('↓' in money_flow_state or 'Падение' in money_flow_state):
                volume_confirmation = 0.85  # Объем не подтверждает бычий импульс
            elif bias == "SHORT" and ('↑' in money_flow_state or 'Рост' in money_flow_state):
                volume_confirmation = 0.85  # Объем не подтверждает медвежий импульс
        
        confidence = float(round(min(1.0, base_confidence * volume_confirmation), 2))
        
        # Если есть дивергенции, слегка повышаем confidence (это дополнительный сигнал)
        if features and features.get('divergences'):
            confidence = min(1.0, confidence * 1.05)
        
        # Учет конвергенции индикаторов для confidence
        if extreme_overbought_count >= 2 or extreme_oversold_count >= 2:
            # Множественная конвергенция = более надежный сигнал EXHAUSTION
            if regime == "EXHAUSTION":
                confidence = min(1.0, confidence * 1.1)
                details["convergence_confidence_boost"] = 0.1
        
        # Учет угла тренда для confidence
        if ema_slope is not None:
            if abs(ema_slope) > 0.05:  # Очень крутой тренд
                if regime == "EXHAUSTION":
                    # Очень крутой тренд + перекупленность = сильный сигнал
                    confidence = min(1.0, confidence * 1.15)
                    details["steep_trend_confidence"] = 0.15
                elif regime == "CONTINUATION":
                    # Крутой тренд подтверждает CONTINUATION
                    confidence = min(1.0, confidence * 1.05)
                    details["steep_trend_confidence"] = 0.05
            elif abs(ema_slope) < 0.01:  # Плоский тренд
                if regime == "REVERSAL_RISK":
                    # Плоский тренд снижает критичность REVERSAL_RISK
                    confidence = confidence * 0.9
                    details["flat_trend_confidence"] = -0.1
        
        # Учет силы тренда (ADX)
        if adx is not None:
            if adx > 40:
                # Очень сильный тренд - возможна перекупленность тренда
                if regime == "CONTINUATION":
                    # Слегка снижаем confidence (тренд может быть перекуплен)
                    confidence = confidence * 0.9
                    details["adx_extreme"] = -0.1
                elif regime == "EXHAUSTION":
                    # Очень сильный тренд + перекупленность = сильный сигнал EXHAUSTION
                    confidence = min(1.0, confidence * 1.15)
                    details["adx_extreme"] = 0.15
            elif adx > 25:
                # Сильный тренд - повышаем confidence для CONTINUATION
                if regime == "CONTINUATION":
                    confidence = min(1.0, confidence * 1.1)
                    details["adx_strong"] = 0.1
            elif adx < 20:
                # Слабый тренд - REVERSAL_RISK менее критичен
                if regime == "REVERSAL_RISK":
                    confidence = confidence * 0.9
                    details["adx_weak"] = -0.1
            
            # Используем +DI/-DI для подтверждения bias
            if plus_di is not None and minus_di is not None:
                if bias == "LONG" and plus_di > minus_di:
                    # Подтверждение бычьего импульса
                    confidence = min(1.0, confidence * 1.05)
                    details["di_confirmation"] = 0.05
                elif bias == "SHORT" and minus_di > plus_di:
                    # Подтверждение медвежьего импульса
                    confidence = min(1.0, confidence * 1.05)
                    details["di_confirmation"] = 0.05
                elif bias == "LONG" and minus_di > plus_di:
                    # Конфликт - снижаем confidence
                    confidence = confidence * 0.95
                    details["di_conflict"] = -0.05
                elif bias == "SHORT" and plus_di > minus_di:
                    # Конфликт - снижаем confidence
                    confidence = confidence * 0.95
                    details["di_conflict"] = -0.05
        
        # Учет деривативов (funding rate, OI)
        if derivatives:
            funding = derivatives.get('funding_rate', 0.0)
            oi_change = derivatives.get('oi_change_pct', 0.0)
            
            if funding is not None:
                # Экстремальный funding = риск ликвидаций = возможная EXHAUSTION
                if abs(funding) > 0.01:  # > 1% - экстремальный
                    if bias == "LONG" and funding > 0.01:
                        # Бычий импульс + высокий funding = риск ликвидаций лонгов
                        exhaustion_up += 0.3
                        confidence = confidence * 0.9
                        details["funding_extreme_long"] = funding
                    elif bias == "SHORT" and funding < -0.01:
                        # Медвежий импульс + низкий funding = риск ликвидаций шортов
                        exhaustion_down += 0.3
                        confidence = confidence * 0.9
                        details["funding_extreme_short"] = funding
                    # Пересчитываем total_exhaustion
                    total_exhaustion = exhaustion_up + exhaustion_down
                elif abs(funding) > 0.001:  # > 0.1% - высокий
                    if bias == "LONG" and funding > 0.001:
                        # Бычий импульс + высокий funding = легкий риск
                        exhaustion_up += 0.15
                        details["funding_high"] = funding
                    elif bias == "SHORT" and funding < -0.001:
                        # Медвежий импульс + низкий funding = легкий риск
                        exhaustion_down += 0.15
                        details["funding_low"] = funding
                    total_exhaustion = exhaustion_up + exhaustion_down
            
            if oi_change is not None:
                # Резкое изменение OI = подтверждение силы движения
                if abs(oi_change) > 10:  # > 10% - резкое изменение
                    if bias == "LONG" and oi_change > 0:
                        # Бычий импульс + рост OI = подтверждение
                        confidence = min(1.0, confidence * 1.1)
                        details["oi_surge_bullish"] = oi_change
                    elif bias == "SHORT" and oi_change < 0:
                        # Медвежий импульс + падение OI = подтверждение
                        confidence = min(1.0, confidence * 1.1)
                        details["oi_surge_bearish"] = oi_change
                    elif bias == "LONG" and oi_change < -10:
                        # Бычий импульс + резкое падение OI = конфликт
                        confidence = confidence * 0.9
                        details["oi_conflict"] = oi_change
                    elif bias == "SHORT" and oi_change > 10:
                        # Медвежий импульс + резкий рост OI = конфликт
                        confidence = confidence * 0.9
                        details["oi_conflict"] = oi_change
                elif abs(oi_change) > 5:  # > 5% - значительное изменение
                    if bias == "LONG" and oi_change > 0:
                        confidence = min(1.0, confidence * 1.05)
                        details["oi_increase_bullish"] = oi_change
                    elif bias == "SHORT" and oi_change < 0:
                        confidence = min(1.0, confidence * 1.05)
                        details["oi_decrease_bearish"] = oi_change
        
        # Учет структуры рынка (SMC) для контекста
        smc_context = getattr(diag, "smc_context", None)
        if smc_context and current_price:
            # Проверяем расстояние до уровней поддержки/сопротивления
            key_levels = getattr(diag, "key_levels", None)
            if key_levels:
                # Находим ближайшие уровни
                supports = [lvl for lvl in key_levels if lvl.price < current_price]
                resistances = [lvl for lvl in key_levels if lvl.price > current_price]
                
                if supports:
                    nearest_support = max(supports, key=lambda x: x.price)
                    distance_to_support = (current_price - nearest_support.price) / current_price
                    
                    if bias == "SHORT" and distance_to_support < 0.02:  # Близко к поддержке (<2%)
                        # Медвежий импульс + близость к поддержке = возможная EXHAUSTION
                        exhaustion_down += 0.2
                        details["near_support_exhaustion"] = distance_to_support
                        total_exhaustion = exhaustion_up + exhaustion_down
                
                if resistances:
                    nearest_resistance = min(resistances, key=lambda x: x.price)
                    distance_to_resistance = (nearest_resistance.price - current_price) / current_price
                    
                    if bias == "LONG" and distance_to_resistance < 0.02:  # Близко к сопротивлению (<2%)
                        # Бычий импульс + близость к сопротивлению = возможная EXHAUSTION
                        exhaustion_up += 0.2
                        details["near_resistance_exhaustion"] = distance_to_resistance
                        total_exhaustion = exhaustion_up + exhaustion_down
                    
                    if bias == "LONG" and distance_to_resistance < 0.01:  # Очень близко к сопротивлению (<1%)
                        # Очень близко к сопротивлению = сильный сигнал EXHAUSTION
                        if regime == "CONTINUATION":
                            regime = "EXHAUSTION"
                            comment = "Импульс бычий, но цена близко к сильному сопротивлению — высокий риск коррекции."
                        confidence = min(1.0, confidence * 1.1)
                        details["very_near_resistance"] = distance_to_resistance
        
        # Улучшенная обработка конфликтов между индикаторами
        # Детектируем конфликты: когда индикаторы дают противоречивые сигналы
        conflict_score = 0.0
        bullish_indicators = 0
        bearish_indicators = 0
        
        # Подсчитываем согласованность сигналов
        if rsi is not None:
            if rsi > 55:
                bullish_indicators += 1
            elif rsi < 45:
                bearish_indicators += 1
        
        if macd is not None and macd_signal is not None:
            if macd > macd_signal:
                bullish_indicators += 1
            elif macd < macd_signal:
                bearish_indicators += 1
        
        if wt1 is not None and wt2 is not None:
            if wt1 > wt2:
                bullish_indicators += 1
            elif wt1 < wt2:
                bearish_indicators += 1
        
        if stc is not None:
            if stc > 50:
                bullish_indicators += 1
            elif stc < 50:
                bearish_indicators += 1
        
        total_indicators = bullish_indicators + bearish_indicators
        if total_indicators > 0:
            # Если есть и бычьи, и медвежьи сигналы - это конфликт
            if bullish_indicators > 0 and bearish_indicators > 0:
                conflict_ratio = min(bullish_indicators, bearish_indicators) / total_indicators
                conflict_score = conflict_ratio
                # Снижаем confidence при конфликтах
                if conflict_score > 0.3:  # Значительный конфликт (>30%)
                    confidence = confidence * (1.0 - conflict_score * 0.3)  # Снижаем до 30%
                    details["indicator_conflict"] = conflict_score
                    # Обновляем comment при значительном конфликте
                    if conflict_score > 0.4:
                        comment = f"{comment} ⚠️ Противоречивые сигналы индикаторов."
        
        # Обработка edge cases
        # Edge case 1: Все индикаторы в нейтральной зоне
        if total_indicators == 0 and rsi is not None and 45 <= rsi <= 55:
            if stoch_k is not None and 40 <= stoch_k <= 60:
                if stc is not None and 40 <= stc <= 60:
                    # Все индикаторы нейтральны - снижаем confidence
                    confidence = confidence * 0.8
                    details["all_neutral"] = True
        
        # Edge case 2: Экстремальные значения всех индикаторов одновременно
        extreme_count = 0
        if rsi is not None and (rsi > 80 or rsi < 20):
            extreme_count += 1
        if stoch_k is not None and (stoch_k > 90 or stoch_k < 10):
            extreme_count += 1
        if stc is not None and (stc > 90 or stc < 10):
            extreme_count += 1
        
        if extreme_count >= 3:
            # Все индикаторы в экстремальных зонах - возможна ошибка данных или очень редкая ситуация
            confidence = confidence * 0.7
            details["all_extreme"] = True
            comment = f"{comment} ⚠️ Все индикаторы в экстремальных зонах - требуется дополнительная проверка."

        return MomentumInsight(
            bias=bias,
            regime=regime,
            strength=strength,
            confidence=confidence,
            comment=comment,
            details=details,
        )

