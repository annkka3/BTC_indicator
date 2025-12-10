# app/domain/market_diagnostics/personalization.py
"""
Personalization Mode - адаптация под риск-профиль и стиль пользователя.
"""

from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from enum import Enum


class RiskProfile(Enum):
    """Риск-профиль пользователя."""
    CONSERVATIVE = "conservative"
    MODERATE = "moderate"
    AGGRESSIVE = "aggressive"


class TradingStyle(Enum):
    """Стиль торговли."""
    SCALP = "scalp"
    SWING = "swing"
    POSITION = "position"


@dataclass
class UserProfile:
    """Профиль пользователя."""
    risk_profile: RiskProfile
    trading_style: TradingStyle
    preferred_r: float  # Желаемый R (0.5, 1.0, 2.0, etc.)
    preferred_setups: List[str]  # ["continuation", "reversal", "breakout"]
    user_id: Optional[int] = None


@dataclass
class PersonalizedRecommendation:
    """Персонализированная рекомендация."""
    optimal_entry_zone: Tuple[float, float]
    recommended_r: float
    setup_suitability: Dict[str, float]  # {setup_type: suitability_score}
    personalized_text: str


class PersonalizationEngine:
    """Движок персонализации."""
    
    def __init__(self):
        """Инициализация."""
        pass
    
    def adjust_entry_zone_for_risk(
        self,
        base_zone: Tuple[float, float],
        risk_profile: RiskProfile
    ) -> Tuple[float, float]:
        """
        Скорректировать зону входа под риск-профиль.
        
        Returns:
            Скорректированная зона
        """
        zone_start, zone_end = base_zone
        zone_size = zone_end - zone_start
        
        if risk_profile == RiskProfile.CONSERVATIVE:
            # Консервативные: более узкая зона, ближе к поддержке
            adjusted_start = zone_start + zone_size * 0.1
            adjusted_end = zone_start + zone_size * 0.6
        elif risk_profile == RiskProfile.AGGRESSIVE:
            # Агрессивные: более широкая зона
            adjusted_start = zone_start - zone_size * 0.1
            adjusted_end = zone_end + zone_size * 0.1
        else:  # MODERATE
            adjusted_start = zone_start
            adjusted_end = zone_end
        
        return (adjusted_start, adjusted_end)
    
    def calculate_recommended_r(
        self,
        base_r: float,
        risk_profile: RiskProfile,
        trading_style: TradingStyle,
        setup_confidence: float
    ) -> float:
        """
        Рассчитать рекомендуемый R для пользователя.
        
        Returns:
            Рекомендуемый R
        """
        # Базовый R
        recommended = base_r
        
        # Корректировка по риск-профилю
        if risk_profile == RiskProfile.CONSERVATIVE:
            recommended *= 0.5
        elif risk_profile == RiskProfile.AGGRESSIVE:
            recommended *= 1.5
        else:  # MODERATE
            recommended *= 1.0
        
        # Корректировка по стилю
        if trading_style == TradingStyle.SCALP:
            recommended *= 0.5  # Скальперы используют меньший R
        elif trading_style == TradingStyle.POSITION:
            recommended *= 1.5  # Позиционщики могут использовать больший R
        
        # Корректировка по уверенности
        recommended *= setup_confidence
        
        # Ограничиваем
        recommended = max(0.25, min(recommended, 2.0))
        
        return round(recommended, 2)
    
    def calculate_setup_suitability(
        self,
        available_setups: List[str],
        preferred_setups: List[str],
        setup_scores: Dict[str, float]  # {setup_type: score}
    ) -> Dict[str, float]:
        """
        Рассчитать пригодность сетапов для пользователя.
        
        Returns:
            {setup_type: suitability_score}
        """
        suitability = {}
        
        for setup in available_setups:
            base_score = setup_scores.get(setup, 0.5)
            
            # Бонус за предпочтения
            if setup in preferred_setups:
                base_score *= 1.3
            
            suitability[setup] = min(1.0, base_score)
        
        return suitability
    
    def generate_personalized_text(
        self,
        user_profile: UserProfile,
        optimal_zone: Tuple[float, float],
        recommended_r: float,
        setup_suitability: Dict[str, float]
    ) -> str:
        """Сгенерировать персонализированный текст."""
        risk_text = {
            RiskProfile.CONSERVATIVE: "консервативный",
            RiskProfile.MODERATE: "средний",
            RiskProfile.AGGRESSIVE: "агрессивный"
        }
        
        style_text = {
            TradingStyle.SCALP: "скальпинг",
            TradingStyle.SWING: "свинг",
            TradingStyle.POSITION: "позиционная торговля"
        }
        
        zone_start, zone_end = optimal_zone
        
        lines = [
            f"Для твоего профиля ({risk_text.get(user_profile.risk_profile, 'средний')} риск, {style_text.get(user_profile.trading_style, 'свинг')})",
            f"оптимальный вход начинается от {zone_start:.0f}–{zone_end:.0f}.",
            f"Рекомендуемый размер позиции: {recommended_r:.2f}R"
        ]
        
        # Добавляем лучшие сетапы
        if setup_suitability:
            best_setup = max(setup_suitability.items(), key=lambda x: x[1])
            if best_setup[1] > 0.6:
                lines.append(f"Наиболее подходящий сетап: {best_setup[0]} (пригодность {best_setup[1]*100:.0f}%)")
        
        return " ".join(lines)
    
    def personalize_recommendation(
        self,
        user_profile: UserProfile,
        base_entry_zone: Tuple[float, float],
        base_r: float,
        setup_confidence: float,
        available_setups: List[str],
        setup_scores: Dict[str, float]
    ) -> PersonalizedRecommendation:
        """
        Персонализировать рекомендацию для пользователя.
        
        Returns:
            PersonalizedRecommendation
        """
        # Скорректированная зона
        optimal_zone = self.adjust_entry_zone_for_risk(base_entry_zone, user_profile.risk_profile)
        
        # Рекомендуемый R
        recommended_r = self.calculate_recommended_r(
            base_r, user_profile.risk_profile, user_profile.trading_style, setup_confidence
        )
        
        # Пригодность сетапов
        setup_suitability = self.calculate_setup_suitability(
            available_setups, user_profile.preferred_setups, setup_scores
        )
        
        # Персонализированный текст
        personalized_text = self.generate_personalized_text(
            user_profile, optimal_zone, recommended_r, setup_suitability
        )
        
        return PersonalizedRecommendation(
            optimal_entry_zone=optimal_zone,
            recommended_r=recommended_r,
            setup_suitability=setup_suitability,
            personalized_text=personalized_text
        )












