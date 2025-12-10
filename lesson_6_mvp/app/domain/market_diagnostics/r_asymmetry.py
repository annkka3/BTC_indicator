# app/domain/market_diagnostics/r_asymmetry.py
"""
R-asymmetry calculator - расчет асимметрии риска.
"""

from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass


@dataclass
class RAsymmetry:
    """Асимметрия риска."""
    long_r: float  # Матожидание для лонга в R
    short_r: float  # Матожидание для шорта в R
    asymmetry: float  # Разница (long_r - short_r)
    interpretation: str  # Интерпретация


class RAsymmetryCalculator:
    """Калькулятор асимметрии риска."""
    
    def __init__(self):
        """Инициализация."""
        pass
    
    def calculate_atr_based_r(
        self,
        atr: float,
        current_price: float,
        stop_distance_pct: float,
        target_distance_pct: float,
        win_probability: float
    ) -> float:
        """
        Рассчитать матожидание в R на основе ATR.
        
        Args:
            atr: Average True Range
            current_price: Текущая цена
            stop_distance_pct: Расстояние до стопа в процентах
            target_distance_pct: Расстояние до цели в процентах
            win_probability: Вероятность выигрыша (0-1)
        
        Returns:
            Матожидание в R
        """
        # R = расстояние до стопа в ATR
        stop_in_atr = (current_price * stop_distance_pct / 100) / atr if atr > 0 else 1.0
        target_in_atr = (current_price * target_distance_pct / 100) / atr if atr > 0 else 1.0
        
        # R-ratio = target / stop
        r_ratio = target_in_atr / stop_in_atr if stop_in_atr > 0 else 1.0
        
        # Матожидание = win_prob * R_ratio - (1 - win_prob) * 1
        expected_r = (win_probability * r_ratio) - ((1 - win_probability) * 1.0)
        
        return expected_r
    
    def calculate_scenario_based_r(
        self,
        scenarios: List[Dict],  # [{probability, target_r, stop_r}]
        direction: str  # "long" or "short"
    ) -> float:
        """
        Рассчитать матожидание на основе вероятностей сценариев.
        
        Returns:
            Матожидание в R
        """
        if not scenarios:
            return 0.0
        
        total_r = 0.0
        total_prob = 0.0
        
        for scenario in scenarios:
            prob = scenario.get('probability', 0.0)
            target_r = scenario.get('target_r', 0.0)
            stop_r = scenario.get('stop_r', 0.0)
            
            # Матожидание для сценария
            scenario_r = (prob * target_r) - ((1 - prob) * stop_r)
            total_r += scenario_r * prob
            total_prob += prob
        
        if total_prob == 0:
            return 0.0
        
        return total_r / total_prob
    
    def calculate_historical_pattern_r(
        self,
        historical_results: List[Dict],  # [{outcome_r, count}]
        current_setup_similarity: float  # Схожесть текущего сетапа (0-1)
    ) -> float:
        """
        Рассчитать матожидание на основе исторических результатов паттернов.
        
        Returns:
            Матожидание в R
        """
        if not historical_results:
            return 0.0
        
        total_r = 0.0
        total_count = 0.0
        
        for result in historical_results:
            outcome_r = result.get('outcome_r', 0.0)
            count = result.get('count', 1)
            similarity = result.get('similarity', 1.0) * current_setup_similarity
            
            total_r += outcome_r * count * similarity
            total_count += count * similarity
        
        if total_count == 0:
            return 0.0
        
        return total_r / total_count
    
    def calculate_full_r_asymmetry(
        self,
        current_price: float,
        long_stop: float,
        long_target: float,
        short_stop: float,
        short_target: float,
        atr: float,
        long_win_prob: float,
        short_win_prob: float,
        long_scenarios: Optional[List[Dict]] = None,
        short_scenarios: Optional[List[Dict]] = None,
        historical_long: Optional[List[Dict]] = None,
        historical_short: Optional[List[Dict]] = None,
        setup_similarity: float = 1.0
    ) -> RAsymmetry:
        """
        Полный расчет асимметрии риска.
        
        Returns:
            RAsymmetry
        """
        # Расстояния в процентах
        long_stop_pct = abs((current_price - long_stop) / current_price * 100) if long_stop > 0 else 2.0
        long_target_pct = abs((long_target - current_price) / current_price * 100) if long_target > 0 else 4.0
        short_stop_pct = abs((short_stop - current_price) / current_price * 100) if short_stop > 0 else 2.0
        short_target_pct = abs((current_price - short_target) / current_price * 100) if short_target > 0 else 4.0
        
        # Базовое матожидание на основе ATR
        long_r_atr = self.calculate_atr_based_r(atr, current_price, long_stop_pct, long_target_pct, long_win_prob)
        short_r_atr = self.calculate_atr_based_r(atr, current_price, short_stop_pct, short_target_pct, short_win_prob)
        
        # Корректировка на основе сценариев
        long_r_scenario = 0.0
        short_r_scenario = 0.0
        
        if long_scenarios:
            long_r_scenario = self.calculate_scenario_based_r(long_scenarios, "long")
        if short_scenarios:
            short_r_scenario = self.calculate_scenario_based_r(short_scenarios, "short")
        
        # Корректировка на основе истории
        long_r_hist = 0.0
        short_r_hist = 0.0
        
        if historical_long:
            long_r_hist = self.calculate_historical_pattern_r(historical_long, setup_similarity)
        if historical_short:
            short_r_hist = self.calculate_historical_pattern_r(historical_short, setup_similarity)
        
        # Взвешенное среднее
        long_r = (long_r_atr * 0.4) + (long_r_scenario * 0.3) + (long_r_hist * 0.3)
        short_r = (short_r_atr * 0.4) + (short_r_scenario * 0.3) + (short_r_hist * 0.3)
        
        # Асимметрия
        asymmetry = long_r - short_r
        
        # Интерпретация
        if asymmetry > 0.3:
            interpretation = f"Рынок сильно в пользу лонгов (+{asymmetry:.2f}R)"
        elif asymmetry > 0.1:
            interpretation = f"Рынок слегка в пользу лонгов (+{asymmetry:.2f}R)"
        elif asymmetry < -0.3:
            interpretation = f"Рынок сильно в пользу шортов ({asymmetry:.2f}R)"
        elif asymmetry < -0.1:
            interpretation = f"Рынок слегка в пользу шортов ({asymmetry:.2f}R)"
        else:
            interpretation = "Рынок нейтрален по асимметрии"
        
        return RAsymmetry(
            long_r=long_r,
            short_r=short_r,
            asymmetry=asymmetry,
            interpretation=interpretation
        )












