# app/domain/portfolio/portfolio_analyzer.py
"""
Анализатор портфеля пользователя для адаптации рекомендаций Market Doctor.
"""

from typing import Optional, Dict
from dataclasses import dataclass
import logging

from .portfolio_state import PortfolioState, Sector

logger = logging.getLogger("alt_forecast.portfolio")


@dataclass
class PortfolioImpact:
    """Влияние портфеля на рекомендацию."""
    position_size_factor_adjustment: float  # Множитель для position_size_factor (0.0 - 1.0)
    comment: str  # Комментарий о влиянии портфеля
    warnings: list[str] = None  # Предупреждения о концентрации риска
    
    def __post_init__(self):
        if self.warnings is None:
            self.warnings = []


class PortfolioAnalyzer:
    """Анализатор портфеля для адаптации рекомендаций."""
    
    def __init__(self):
        """Инициализация анализатора."""
        pass
    
    def analyze_impact(
        self,
        portfolio: Optional[PortfolioState],
        symbol: str,
        proposed_size: float,
        sector: Optional[Sector] = None
    ) -> PortfolioImpact:
        """
        Проанализировать влияние текущего портфеля на предложенную позицию.
        
        Args:
            portfolio: Состояние портфеля пользователя
            symbol: Символ монеты для новой позиции
            proposed_size: Предложенный размер позиции в USDT
            sector: Сектор монеты (если известен)
        
        Returns:
            PortfolioImpact с рекомендациями по адаптации размера позиции
        """
        if not portfolio:
            # Нет данных о портфеле - не ограничиваем
            return PortfolioImpact(
                position_size_factor_adjustment=1.0,
                comment="Портфель не отслеживается"
            )
        
        # Пересчитываем метрики портфеля
        portfolio.calculate_metrics()
        
        warnings = []
        adjustment = 1.0
        
        # Проверка концентрации по сектору
        if sector:
            sector_exposure = portfolio.sector_exposure.get(sector, 0.0)
            if portfolio.total_equity > 0:
                current_sector_pct = (sector_exposure / portfolio.total_equity) * 100
                new_exposure = proposed_size
                new_sector_pct = ((sector_exposure + new_exposure) / portfolio.total_equity) * 100
                
                # Если уже высокая концентрация в секторе
                if current_sector_pct > 30:
                    # Сильно режем размер
                    reduction = max(0.3, 1.0 - (current_sector_pct / 50.0))
                    adjustment *= reduction
                    warnings.append(
                        f"Высокая концентрация в секторе {sector.value}: {current_sector_pct:.1f}%"
                    )
                elif current_sector_pct > 20:
                    # Умеренное снижение
                    adjustment *= 0.7
                    warnings.append(
                        f"Умеренная концентрация в секторе {sector.value}: {current_sector_pct:.1f}%"
                    )
        
        # Проверка общего риска в R
        if portfolio.total_risk_r > 5.0:
            # Высокий суммарный риск - режем размер
            risk_reduction = max(0.4, 1.0 - (portfolio.total_risk_r / 10.0))
            adjustment *= risk_reduction
            warnings.append(f"Высокий суммарный риск: {portfolio.total_risk_r:.1f}R")
        elif portfolio.total_risk_r > 3.0:
            # Умеренный риск
            adjustment *= 0.8
            warnings.append(f"Умеренный риск: {portfolio.total_risk_r:.1f}R")
        
        # Проверка доступного кэша
        if portfolio.cash_available < proposed_size:
            # Недостаточно кэша
            if portfolio.cash_available > 0:
                adjustment *= min(1.0, portfolio.cash_available / proposed_size)
                warnings.append(
                    f"Недостаточно кэша: доступно {portfolio.cash_available:.0f} USDT, "
                    f"требуется {proposed_size:.0f} USDT"
                )
            else:
                adjustment = 0.0
                warnings.append("Нет доступного кэша")
        
        # Проверка максимальной экспозиции к сектору
        if portfolio.max_sector_exposure > 40:
            adjustment *= 0.6
            warnings.append(
                f"Критическая концентрация: максимальная экспозиция к сектору {portfolio.max_sector_exposure:.1f}%"
            )
        
        # Формируем комментарий
        if warnings:
            comment = (
                f"⚠️ Концентрация: {', '.join(warnings[:2])}. "
                f"Market Doctor уменьшает рекомендованный размер позиции на {int((1 - adjustment) * 100)}% "
                f"для снижения кластерного риска."
            )
        else:
            comment = "✅ Портфель диверсифицирован, ограничений нет."
        
        return PortfolioImpact(
            position_size_factor_adjustment=max(0.0, min(1.0, adjustment)),
            comment=comment,
            warnings=warnings
        )






