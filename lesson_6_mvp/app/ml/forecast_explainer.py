# app/ml/forecast_explainer.py
"""
Объяснение прогнозов: топ факторов, влияющих на прогноз.
"""

import logging
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass

logger = logging.getLogger("alt_forecast.ml.explainer")


@dataclass
class ForecastFactor:
    """Фактор, влияющий на прогноз."""
    name: str
    impact: float  # Влияние на прогноз (-1..1, где 1 = сильно бычий, -1 = сильно медвежий)
    strength: float  # Сила фактора (0..1)
    description: str  # Текстовое описание


def explain_forecast(
    predicted_return: float,
    probability_up: float,
    momentum_grade: Optional[str] = None,
    momentum_strength: Optional[float] = None,
    global_regime: Optional[str] = None,
    pump_score: Optional[float] = None,
    risk_score: Optional[float] = None,
    setup_type: Optional[str] = None,
    grade: Optional[str] = None,
    confidence_interval_68: Optional[Tuple[float, float]] = None,
    liquidity_state: Optional[str] = None
) -> List[ForecastFactor]:
    """
    Объяснить прогноз, выделив топ факторов.
    
    Args:
        predicted_return: Предсказанный return
        probability_up: Вероятность роста
        momentum_grade: Momentum grade (STRONG_BULLISH, etc.)
        momentum_strength: Сила импульса (0..1)
        global_regime: Глобальный режим рынка
        pump_score: Pump score (0..1)
        risk_score: Risk score (0..1)
        setup_type: Тип сетапа
        grade: Grade сетапа (A/B/C/D)
        confidence_interval_68: 68% доверительный интервал
        liquidity_state: Состояние ликвидности
    
    Returns:
        Список факторов, отсортированный по силе влияния
    """
    factors = []
    
    # Фактор 1: Momentum
    if momentum_grade:
        momentum_impact = 0.0
        if momentum_grade in ["STRONG_BULLISH", "WEAK_BULLISH"]:
            momentum_impact = 0.6 if "STRONG" in momentum_grade else 0.3
        elif momentum_grade in ["STRONG_BEARISH", "WEAK_BEARISH"]:
            momentum_impact = -0.6 if "STRONG" in momentum_grade else -0.3
        
        momentum_strength_val = momentum_strength if momentum_strength else 0.5
        factors.append(ForecastFactor(
            name="Momentum",
            impact=momentum_impact,
            strength=momentum_strength_val,
            description=f"Импульс: {momentum_grade.lower().replace('_', ' ')}"
        ))
    
    # Фактор 2: Глобальный режим
    if global_regime:
        regime_impact = 0.0
        regime_desc = ""
        if global_regime in ["RISK_ON", "ALT_SEASON"]:
            regime_impact = 0.4
            regime_desc = "бычий режим рынка"
        elif global_regime in ["RISK_OFF", "PANIC"]:
            regime_impact = -0.4
            regime_desc = "медвежий режим рынка"
        elif global_regime == "CHOPPY":
            regime_impact = 0.0
            regime_desc = "боковик"
        
        if regime_impact != 0:
            factors.append(ForecastFactor(
                name="Глобальный режим",
                impact=regime_impact,
                strength=0.6,
                description=regime_desc
            ))
    
    # Фактор 3: Pump Score
    if pump_score is not None:
        pump_impact = (pump_score - 0.5) * 0.8  # Нормализуем к -0.4..0.4
        factors.append(ForecastFactor(
            name="Потенциал роста",
            impact=pump_impact,
            strength=abs(pump_score - 0.5) * 2,  # Сила = отклонение от нейтрального
            description=f"Pump score: {pump_score:.2f}"
        ))
    
    # Фактор 4: Risk Score
    if risk_score is not None:
        risk_impact = -(risk_score - 0.5) * 0.6  # Высокий риск = негативное влияние
        factors.append(ForecastFactor(
            name="Риск",
            impact=risk_impact,
            strength=abs(risk_score - 0.5) * 2,
            description=f"Risk score: {risk_score:.2f}"
        ))
    
    # Фактор 5: Вероятность (p_up)
    p_up_impact = (probability_up - 0.5) * 0.5
    factors.append(ForecastFactor(
        name="Вероятность направления",
        impact=p_up_impact,
        strength=abs(probability_up - 0.5) * 2,
        description=f"Вероятность роста: {probability_up:.1%}"
    ))
    
    # Фактор 6: Тип сетапа
    if setup_type:
        setup_impact = 0.0
        if setup_type == "IMPULSE":
            setup_impact = 0.3 if predicted_return > 0 else -0.3
        elif setup_type == "SOFT":
            setup_impact = 0.1 if predicted_return > 0 else -0.1
        elif setup_type == "NEEDS_CONFIRMATION":
            setup_impact = -0.2  # Требует подтверждения = снижает уверенность
        
        factors.append(ForecastFactor(
            name="Тип сетапа",
            impact=setup_impact,
            strength=0.4,
            description=f"Сетап: {setup_type}"
        ))
    
    # Фактор 7: Grade
    if grade:
        grade_impact = 0.0
        if grade == "A":
            grade_impact = 0.2
        elif grade == "B":
            grade_impact = 0.1
        elif grade == "C":
            grade_impact = -0.1
        elif grade == "D":
            grade_impact = -0.2
        
        factors.append(ForecastFactor(
            name="Качество сетапа",
            impact=grade_impact,
            strength=0.3,
            description=f"Grade: {grade}"
        ))
    
    # Фактор 8: Ликвидность
    if liquidity_state:
        liquidity_impact = 0.0
        if liquidity_state == "HIGH":
            liquidity_impact = 0.1
        elif liquidity_state == "LOW":
            liquidity_impact = -0.15
        
        factors.append(ForecastFactor(
            name="Ликвидность",
            impact=liquidity_impact,
            strength=0.2,
            description=f"Ликвидность: {liquidity_state}"
        ))
    
    # Фактор 9: Ширина доверительного интервала
    if confidence_interval_68:
        ci_lower, ci_upper = confidence_interval_68
        ci_width = abs(ci_upper - ci_lower)
        # Узкий CI = высокая уверенность
        ci_impact = -ci_width * 2  # Широкий CI снижает уверенность
        factors.append(ForecastFactor(
            name="Неопределенность",
            impact=ci_impact,
            strength=min(ci_width * 10, 1.0),
            description=f"Ширина ДИ: {ci_width*100:.2f}%"
        ))
    
    # Сортируем по силе влияния (impact * strength)
    factors.sort(key=lambda f: abs(f.impact * f.strength), reverse=True)
    
    return factors[:5]  # Возвращаем топ-5 факторов


def format_explanation(factors: List[ForecastFactor], predicted_return: float) -> str:
    """
    Форматировать объяснение для отображения.
    
    Args:
        factors: Список факторов
        predicted_return: Предсказанный return
    
    Returns:
        Текстовое объяснение
    """
    if not factors:
        return "Недостаточно данных для объяснения"
    
    direction = "бычий" if predicted_return > 0 else "медвежий"
    
    lines = [f"📊 <b>Объяснение прогноза ({direction}):</b>\n"]
    
    for i, factor in enumerate(factors, 1):
        arrow = "📈" if factor.impact > 0 else "📉" if factor.impact < 0 else "➡️"
        impact_str = f"{factor.impact:+.2f}"
        lines.append(
            f"{i}. {arrow} <b>{factor.name}</b>: {impact_str}\n"
            f"   {factor.description}"
        )
    
    return "\n".join(lines)


















