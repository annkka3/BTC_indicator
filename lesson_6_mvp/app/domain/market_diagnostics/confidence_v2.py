# app/domain/market_diagnostics/confidence_v2.py
"""
Auto-Calibrated Confidence - умный регулятор уверенности с объяснениями.
"""

from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass


@dataclass
class ConfidenceAnalysis:
    """Анализ уверенности."""
    confidence: float  # 0-1
    factors: List[Dict]  # [{factor, contribution, status}]
    explanation: str  # Объяснение уверенности


class ConfidenceV2:
    """Умный регулятор уверенности."""
    
    def __init__(self):
        """Инициализация."""
        pass
    
    def calculate_tf_confluence(
        self,
        tf_scores: Dict[str, Dict]  # {timeframe: {direction, score}}
    ) -> Tuple[float, str]:
        """
        Рассчитать конфлюэнс по таймфреймам.
        
        Returns:
            Tuple[score, description]
        """
        if not tf_scores:
            return 0.5, "нет данных"
        
        directions = [data.get('direction', 'NEUTRAL') for data in tf_scores.values()]
        scores = [data.get('score', 5.0) for data in tf_scores.values()]
        
        # Проверяем согласованность направлений
        long_count = sum(1 for d in directions if d == "LONG")
        short_count = sum(1 for d in directions if d == "SHORT")
        total = len(directions)
        
        if total == 0:
            return 0.5, "нет данных"
        
        # Конфлюэнс = доля согласованных ТФ
        max_agreement = max(long_count, short_count)
        confluence_ratio = max_agreement / total
        
        # Учитываем силу сигналов
        avg_score = sum(scores) / len(scores) if scores else 5.0
        score_factor = min(1.0, (avg_score - 4.0) / 4.0) if avg_score > 4.0 else 0.0
        
        final_score = confluence_ratio * 0.7 + score_factor * 0.3
        
        if final_score > 0.8:
            desc = "высокий score TF-конфлюэнса"
        elif final_score > 0.6:
            desc = "умеренный score TF-конфлюэнса"
        else:
            desc = "слабый score TF-конфлюэнса"
        
        return final_score, desc
    
    def calculate_indicator_alignment(
        self,
        indicator_scores: Dict[str, float]  # {indicator: score}
    ) -> Tuple[float, str]:
        """
        Рассчитать согласованность индикаторов.
        
        Returns:
            Tuple[score, description]
        """
        if not indicator_scores:
            return 0.5, "нет данных"
        
        scores = list(indicator_scores.values())
        if not scores:
            return 0.5, "нет данных"
        
        # Проверяем, в одном ли направлении индикаторы
        positive = sum(1 for s in scores if s > 0)
        negative = sum(1 for s in scores if s < 0)
        total = len(scores)
        
        alignment_ratio = max(positive, negative) / total if total > 0 else 0.5
        
        # Учитываем силу сигналов
        avg_abs_score = sum(abs(s) for s in scores) / len(scores)
        strength_factor = min(1.0, avg_abs_score / 2.0)
        
        final_score = alignment_ratio * 0.6 + strength_factor * 0.4
        
        if final_score > 0.7:
            desc = "высокая согласованность индикаторов"
        elif final_score > 0.5:
            desc = "умеренная согласованность индикаторов"
        else:
            desc = "слабая согласованность индикаторов"
        
        return final_score, desc
    
    def calculate_volume_confirmation(
        self,
        recent_volume: float,
        avg_volume: float,
        price_direction: str  # "up", "down", "neutral"
    ) -> Tuple[float, str]:
        """
        Рассчитать подтверждение объёмом.
        
        Returns:
            Tuple[score, description]
        """
        if avg_volume == 0:
            return 0.5, "нет данных"
        
        volume_ratio = recent_volume / avg_volume
        
        # Объём должен быть выше среднего для подтверждения
        if volume_ratio >= 1.2:
            return 0.8, "сильная поддержка объёмом"
        elif volume_ratio >= 1.0:
            return 0.6, "умеренная поддержка объёмом"
        elif volume_ratio >= 0.8:
            return 0.4, "слабая поддержка объёмом"
        else:
            return 0.2, "нет подтверждения объёмом"
    
    def calculate_oi_confirmation(
        self,
        oi_delta: Optional[float] = None,
        price_direction: str = "neutral"
    ) -> Tuple[float, str]:
        """
        Рассчитать подтверждение OI.
        
        Returns:
            Tuple[score, description]
        """
        if oi_delta is None:
            return 0.5, "нет данных OI"
        
        # OI должен расти вместе с ценой для подтверждения
        if price_direction == "up" and oi_delta > 0.02:
            return 0.8, "подтверждение OI"
        elif price_direction == "down" and oi_delta < -0.02:
            return 0.8, "подтверждение OI"
        elif abs(oi_delta) < 0.01:
            return 0.5, "нейтральный OI"
        else:
            return 0.3, "нет подтверждения OI"
    
    def calculate_volatility_factor(
        self,
        volatility: float,
        avg_volatility: float
    ) -> Tuple[float, str]:
        """
        Рассчитать фактор волатильности.
        
        Returns:
            Tuple[score, description]
        """
        if avg_volatility == 0:
            return 0.5, "нет данных"
        
        vol_ratio = volatility / avg_volatility
        
        # Умеренная волатильность лучше для уверенности
        if 0.8 <= vol_ratio <= 1.2:
            return 0.7, "нормальная волатильность"
        elif vol_ratio > 1.5:
            return 0.4, "высокая волатильность снижает уверенность"
        elif vol_ratio < 0.5:
            return 0.6, "низкая волатильность — рынок спокоен"
        else:
            return 0.5, "умеренная волатильность"
    
    def calculate_regime_factor(
        self,
        regime: str  # "trend", "exhaustion", "chop", "liquidity_hunt"
    ) -> Tuple[float, str]:
        """
        Рассчитать фактор режима.
        
        Returns:
            Tuple[score, description]
        """
        regime_scores = {
            "trend": 0.8,
            "exhaustion": 0.4,
            "chop": 0.3,
            "liquidity_hunt": 0.5
        }
        
        score = regime_scores.get(regime, 0.5)
        desc = f"режим {regime}"
        
        return score, desc
    
    def calculate_data_quality(
        self,
        data_completeness: float,  # 0-1
        data_freshness: float  # 0-1 (как давно обновлялись данные)
    ) -> Tuple[float, str]:
        """
        Рассчитать качество данных.
        
        Returns:
            Tuple[score, description]
        """
        quality_score = (data_completeness * 0.6 + data_freshness * 0.4)
        
        if quality_score > 0.9:
            desc = "отличное качество данных"
        elif quality_score > 0.7:
            desc = "хорошее качество данных"
        elif quality_score > 0.5:
            desc = "удовлетворительное качество данных"
        else:
            desc = "низкое качество данных"
        
        return quality_score, desc
    
    def calculate_full_confidence(
        self,
        base_confidence: float,
        tf_scores: Optional[Dict[str, Dict]] = None,
        indicator_scores: Optional[Dict[str, float]] = None,
        recent_volume: Optional[float] = None,
        avg_volume: Optional[float] = None,
        price_direction: str = "neutral",
        oi_delta: Optional[float] = None,
        volatility: Optional[float] = None,
        avg_volatility: Optional[float] = None,
        regime: Optional[str] = None,
        data_completeness: float = 1.0,
        data_freshness: float = 1.0
    ) -> ConfidenceAnalysis:
        """
        Полный расчет уверенности с объяснениями.
        
        Returns:
            ConfidenceAnalysis
        """
        factors = []
        weights = []
        
        # TF конфлюэнс
        if tf_scores:
            score, desc = self.calculate_tf_confluence(tf_scores)
            factors.append({"factor": "TF-конфлюэнс", "contribution": score, "status": desc})
            weights.append(0.25)
        
        # Согласованность индикаторов
        if indicator_scores:
            score, desc = self.calculate_indicator_alignment(indicator_scores)
            factors.append({"factor": "Согласованность индикаторов", "contribution": score, "status": desc})
            weights.append(0.20)
        
        # Подтверждение объёмом
        if recent_volume is not None and avg_volume is not None:
            score, desc = self.calculate_volume_confirmation(recent_volume, avg_volume, price_direction)
            factors.append({"factor": "Подтверждение объёмом", "contribution": score, "status": desc})
            weights.append(0.15)
        
        # Подтверждение OI
        if oi_delta is not None:
            score, desc = self.calculate_oi_confirmation(oi_delta, price_direction)
            factors.append({"factor": "Подтверждение OI", "contribution": score, "status": desc})
            weights.append(0.15)
        
        # Волатильность
        if volatility is not None and avg_volatility is not None:
            score, desc = self.calculate_volatility_factor(volatility, avg_volatility)
            factors.append({"factor": "Волатильность", "contribution": score, "status": desc})
            weights.append(0.10)
        
        # Режим
        if regime:
            score, desc = self.calculate_regime_factor(regime)
            factors.append({"factor": "Режим рынка", "contribution": score, "status": desc})
            weights.append(0.10)
        
        # Качество данных
        score, desc = self.calculate_data_quality(data_completeness, data_freshness)
        factors.append({"factor": "Качество данных", "contribution": score, "status": desc})
        weights.append(0.05)
        
        # Взвешенное среднее
        if factors and weights:
            total_weight = sum(weights)
            if total_weight > 0:
                adjusted_weights = [w / total_weight for w in weights]
                final_confidence = sum(f['contribution'] * w for f, w in zip(factors, adjusted_weights))
            else:
                final_confidence = base_confidence
        else:
            final_confidence = base_confidence
        
        # Ограничиваем
        final_confidence = max(0.0, min(1.0, final_confidence))
        
        # Формируем объяснение
        explanation_parts = []
        for factor in factors:
            if factor['contribution'] > 0.7:
                explanation_parts.append(f"— {factor['status']}")
            elif factor['contribution'] < 0.4:
                explanation_parts.append(f"— {factor['status']}")
        
        explanation = "\n".join(explanation_parts) if explanation_parts else "Стандартная уверенность"
        
        return ConfidenceAnalysis(
            confidence=final_confidence,
            factors=factors,
            explanation=explanation
        )












