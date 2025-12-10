# app/domain/market_diagnostics/setup_type.py
"""
Типизация торговых сетапов на основе прогноза ML-модели.
"""

from enum import Enum
from typing import Dict, Optional, TYPE_CHECKING
from dataclasses import dataclass

if TYPE_CHECKING:
    from .analyzer import MarketDiagnostics
    from .scoring_engine import MultiTFScore
    from .trade_planner import TradePlan


class SetupType(str, Enum):
    """Типы торговых сетапов."""
    SOFT = "soft"  # Мягкий: |ret_pred| маленький, p_up около 0.55-0.6, широкий CI
    IMPULSE = "impulse"  # Импульсный: большой |ret_pred|, p_up высокое, CI относительно узкий
    NEEDS_CONFIRMATION = "needs_confirmation"  # Требует подтверждения: против глобального режима, импульс слабый
    NEUTRAL = "neutral"  # Нейтральный: неопределенный сетап


@dataclass
class SetupClassification:
    """Классификация торгового сетапа."""
    setup_type: SetupType
    grade: str  # "A", "B", "C", "D"
    confidence: float  # [0, 1]
    comment: str  # Текстовое описание
    factors: Dict[str, float]  # Факторы, влияющие на классификацию


def classify_setup(
    predicted_return: float,
    probability_up: float,
    confidence_interval_68: Optional[tuple] = None,
    confidence_interval_95: Optional[tuple] = None,
    global_regime: Optional[str] = None,
    momentum_grade: Optional[str] = None,
    momentum_strength: Optional[float] = None
) -> SetupClassification:
    """
    Классифицировать торговый сетап на основе прогноза.
        
        Args:
        predicted_return: Предсказанный return (в долях)
        probability_up: Вероятность роста
        confidence_interval_68: 68% доверительный интервал (lower, upper)
        confidence_interval_95: 95% доверительный интервал (lower, upper)
        global_regime: Глобальный режим рынка ("BULL", "BEAR", "NEUTRAL")
        momentum_grade: Momentum grade ("STRONG_BULLISH", "WEAK_BULLISH", etc.)
        momentum_strength: Сила импульса [0, 1]
        
        Returns:
        SetupClassification
    """
    factors = {}
    
    # Вычисляем ширину CI (если доступен)
    ci_width = None
    if confidence_interval_68:
        ci_lower, ci_upper = confidence_interval_68
        ci_width = abs(ci_upper - ci_lower)
    elif confidence_interval_95:
        ci_lower, ci_upper = confidence_interval_95
        ci_width = abs(ci_upper - ci_lower)
    
    # Определяем тип сетапа
    abs_ret = abs(predicted_return)
    
    # Мягкий сетап: маленький |ret_pred|, p_up около 0.55-0.6, широкий CI
    is_soft = (
        abs_ret < 0.01 and  # Маленький return
        0.55 <= probability_up <= 0.65 and  # Умеренная вероятность
        (ci_width is None or ci_width > 0.02)  # Широкий CI
    )
    
    # Импульсный сетап: большой |ret_pred|, p_up высокое, CI относительно узкий
    is_impulse = (
        abs_ret > 0.02 and  # Большой return
        probability_up > 0.7 and  # Высокая вероятность
        (ci_width is None or ci_width < 0.03)  # Узкий CI
    )
    
    # Требует подтверждения: против глобального режима или слабый импульс
    is_needs_confirmation = False
    if global_regime:
        # Проверяем противоречие с глобальным режимом
        if global_regime in ["BULL", "RISK_ON"] and predicted_return < -0.01:
            is_needs_confirmation = True
        elif global_regime in ["BEAR", "RISK_OFF", "PANIC"] and predicted_return > 0.01:
            is_needs_confirmation = True
    
    # Также требует подтверждения при слабом импульсе
    if momentum_strength is not None and momentum_strength < 0.4:
        is_needs_confirmation = True
    
    # Определяем тип
    if is_soft:
        setup_type = SetupType.SOFT
    elif is_impulse:
        setup_type = SetupType.IMPULSE
    elif is_needs_confirmation:
        setup_type = SetupType.NEEDS_CONFIRMATION
    else:
        setup_type = SetupType.NEUTRAL
    
    # Вычисляем Grade (A/B/C/D)
    grade = _calculate_grade(
        predicted_return, probability_up, ci_width, momentum_grade, momentum_strength
    )
    
    # Вычисляем confidence
    confidence = _calculate_confidence(
        probability_up, ci_width, momentum_strength, setup_type
    )
    
    # Формируем комментарий
    comment = _generate_comment(
        setup_type, grade, predicted_return, probability_up, momentum_grade
    )
    
    # Сохраняем факторы
    factors = {
        "abs_return": abs_ret,
        "probability_up": probability_up,
        "ci_width": ci_width if ci_width else 0.0,
        "momentum_strength": momentum_strength if momentum_strength else 0.5,
    }
    
    return SetupClassification(
        setup_type=setup_type,
        grade=grade,
        confidence=confidence,
        comment=comment,
        factors=factors
    )


def _calculate_grade(
    predicted_return: float,
    probability_up: float,
    ci_width: Optional[float],
    momentum_grade: Optional[str],
    momentum_strength: Optional[float]
) -> str:
    """Вычислить Grade сетапа (A/B/C/D)."""
    score = 0.0
    
    # Return (максимум 30 баллов)
    abs_ret = abs(predicted_return)
    if abs_ret > 0.03:
        score += 30
    elif abs_ret > 0.02:
        score += 20
    elif abs_ret > 0.01:
        score += 10
    
    # Probability (максимум 30 баллов)
    if probability_up > 0.8:
        score += 30
    elif probability_up > 0.7:
        score += 20
    elif probability_up > 0.6:
        score += 10
    
    # CI width (максимум 20 баллов) - узкий CI лучше
    if ci_width is not None:
        if ci_width < 0.02:
            score += 20
        elif ci_width < 0.03:
            score += 15
        elif ci_width < 0.04:
            score += 10
    
    # Momentum (максимум 20 баллов)
    if momentum_grade:
        if momentum_grade in ["STRONG_BULLISH", "STRONG_BEARISH"]:
            score += 20
        elif momentum_grade in ["WEAK_BULLISH", "WEAK_BEARISH"]:
            score += 10
    
    if momentum_strength is not None:
        score += momentum_strength * 10
    
    # Определяем Grade
    if score >= 70:
        return "A"
    elif score >= 50:
        return "B"
    elif score >= 30:
        return "C"
    else:
        return "D"


def _calculate_confidence(
    probability_up: float,
    ci_width: Optional[float],
    momentum_strength: Optional[float],
    setup_type: SetupType
) -> float:
    """Вычислить confidence сетапа [0, 1]."""
    confidence = 0.5
    
    # Базовая confidence на основе probability_up
    if probability_up > 0.8 or probability_up < 0.2:
        confidence = 0.8
    elif probability_up > 0.7 or probability_up < 0.3:
        confidence = 0.7
    elif probability_up > 0.6 or probability_up < 0.4:
        confidence = 0.6
    
    # Корректировка на основе CI width
    if ci_width is not None:
        if ci_width < 0.02:
            confidence += 0.1
        elif ci_width > 0.04:
            confidence -= 0.1
    
    # Корректировка на основе momentum
    if momentum_strength is not None:
        confidence += (momentum_strength - 0.5) * 0.2
    
    # Корректировка на основе типа сетапа
    if setup_type == SetupType.IMPULSE:
        confidence += 0.1
    elif setup_type == SetupType.NEEDS_CONFIRMATION:
        confidence -= 0.2
    elif setup_type == SetupType.SOFT:
        confidence -= 0.1
    
    return max(0.0, min(1.0, confidence))


def _generate_comment(
    setup_type: SetupType,
    grade: str,
    predicted_return: float,
    probability_up: float,
    momentum_grade: Optional[str]
) -> str:
    """Сгенерировать текстовый комментарий к сетапу."""
    ret_pct = predicted_return * 100
    p_up_pct = probability_up * 100
    
    if setup_type == SetupType.SOFT:
        comment = f"Мягкий сетап (Grade {grade}): прогноз {ret_pct:+.2f}%, вероятность {p_up_pct:.1f}%"
    elif setup_type == SetupType.IMPULSE:
        comment = f"Импульсный сетап (Grade {grade}): прогноз {ret_pct:+.2f}%, вероятность {p_up_pct:.1f}%"
    elif setup_type == SetupType.NEEDS_CONFIRMATION:
        comment = f"Требует подтверждения (Grade {grade}): прогноз {ret_pct:+.2f}%, вероятность {p_up_pct:.1f}%"
    else:
        comment = f"Нейтральный сетап (Grade {grade}): прогноз {ret_pct:+.2f}%, вероятность {p_up_pct:.1f}%"
    
    if momentum_grade:
        comment += f", импульс: {momentum_grade}"
    
    return comment


class SetupTypeDetector:
    """Детектор типа сетапа для Market Doctor."""
    
    def detect_setup_type(
        self,
        multi_tf_score: 'MultiTFScore',
        diagnostics: 'MarketDiagnostics',
        all_diagnostics: Optional[Dict[str, 'MarketDiagnostics']] = None,
        current_price: Optional[float] = None
    ) -> Optional[str]:
        """
        Определить тип сетапа на основе диагностики.
        
        Args:
            diagnostics: Результаты диагностики рынка
            multi_tf_score: Агрегированный score по таймфреймам
            trade_plan: План торговых действий (опционально)
        
        Returns:
            Тип сетапа (строка) или None
        """
        # Используем старую логику определения типа сетапа для Market Doctor
        # Это отличается от ML-прогноза, здесь мы анализируем структуру рынка
        
        if diagnostics.phase.value == "ACCUMULATION":
            return "RANGE_PLAY"
        elif diagnostics.phase.value == "EXPANSION_UP":
            return "TREND_CONTINUATION"
        elif diagnostics.phase.value == "DISTRIBUTION":
            return "REVERSAL"
        elif diagnostics.phase.value == "EXPANSION_DOWN":
            return "TREND_CONTINUATION"
        elif diagnostics.phase.value == "SHAKEOUT":
            return "BREAKOUT"
        else:
            return "UNKNOWN"


def translate_setup_type(setup_type: str) -> str:
    """
    Перевести тип сетапа на русский язык.
    
    Args:
        setup_type: Тип сетапа (строка)
    
    Returns:
        Перевод на русский
    """
    translations = {
        "TREND_CONTINUATION": "Продолжение тренда",
        "REVERSAL": "Разворот",
        "RANGE_PLAY": "Игра в диапазоне",
        "BREAKOUT": "Пробой",
        "MEAN_REVERSION": "Возврат к среднему",
        "UNKNOWN": "Неизвестно",
        # Новые типы из ML
        "soft": "Мягкий",
        "impulse": "Импульсный",
        "needs_confirmation": "Требует подтверждения",
        "neutral": "Нейтральный",
    }
    return translations.get(setup_type, setup_type)
