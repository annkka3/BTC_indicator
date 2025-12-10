# app/ml/meta_forecaster.py
"""
Meta-модель над диагностическими фичами.

Учится, когда верить первому мозгу (ML-модели) и когда лучше резать сигнал.
"""

import logging
from typing import Dict, Optional, List
from dataclasses import dataclass
import pandas as pd
import numpy as np

logger = logging.getLogger("alt_forecast.ml.meta_forecaster")

try:
    import catboost as cb
    HAS_CATBOOST = True
except ImportError:
    HAS_CATBOOST = False
    logger.warning("CatBoost not available for meta-forecaster")


@dataclass
class MetaForecast:
    """Результат meta-прогноза."""
    adjusted_e_r: float  # Скорректированный E[R]
    trade_flag: bool  # True = можно торговать, False = только наблюдать
    confidence: float  # Уверенность в корректировке (0..1)
    factors: Dict[str, float]  # Вклад каждого фактора


class MetaForecaster:
    """Meta-модель для корректировки прогнозов."""
    
    def __init__(self, db):
        """
        Args:
            db: Database instance для доступа к forecast_history и outcomes
        """
        self.db = db
        self.model = None
        self.feature_names = []
        self._load_model()
    
    def _load_model(self):
        """Загрузить обученную meta-модель."""
        # TODO: Реализовать загрузку модели из файла
        # Пока модель не обучена, используем rule-based логику
        pass
    
    def _build_features(
        self,
        predicted_return: float,
        probability_up: float,
        momentum_grade: Optional[str] = None,
        momentum_strength: Optional[float] = None,
        global_regime: Optional[str] = None,
        pump_score: Optional[float] = None,
        risk_score: Optional[float] = None,
        setup_type: Optional[str] = None,
        grade: Optional[str] = None,
        confidence_interval_68: Optional[tuple] = None,
        reliability_score: Optional[float] = None
    ) -> Dict[str, float]:
        """
        Построить фичи для meta-модели.
        
        Args:
            predicted_return: Предсказанный return
            probability_up: Вероятность роста
            momentum_grade: Momentum grade
            momentum_strength: Сила импульса
            global_regime: Глобальный режим
            pump_score: Pump score
            risk_score: Risk score
            setup_type: Тип сетапа
            grade: Grade
            confidence_interval_68: Доверительный интервал
            reliability_score: Reliability score
        
        Returns:
            Dict с фичами
        """
        features = {}
        
        # Базовые фичи из ML-прогноза
        features['predicted_return'] = predicted_return
        features['probability_up'] = probability_up
        features['abs_predicted_return'] = abs(predicted_return)
        
        # Momentum фичи
        if momentum_grade:
            features['momentum_bullish'] = 1.0 if "BULLISH" in momentum_grade else 0.0
            features['momentum_bearish'] = 1.0 if "BEARISH" in momentum_grade else 0.0
            features['momentum_strong'] = 1.0 if "STRONG" in momentum_grade else 0.0
        else:
            features['momentum_bullish'] = 0.0
            features['momentum_bearish'] = 0.0
            features['momentum_strong'] = 0.0
        
        features['momentum_strength'] = momentum_strength if momentum_strength else 0.5
        
        # Режим фичи
        if global_regime:
            features['regime_risk_on'] = 1.0 if global_regime in ["RISK_ON", "ALT_SEASON"] else 0.0
            features['regime_risk_off'] = 1.0 if global_regime in ["RISK_OFF", "PANIC"] else 0.0
            features['regime_choppy'] = 1.0 if global_regime == "CHOPPY" else 0.0
        else:
            features['regime_risk_on'] = 0.0
            features['regime_risk_off'] = 0.0
            features['regime_choppy'] = 0.0
        
        # Pump и Risk
        features['pump_score'] = pump_score if pump_score is not None else 0.5
        features['risk_score'] = risk_score if risk_score is not None else 0.5
        features['pump_risk_ratio'] = features['pump_score'] / (features['risk_score'] + 0.01)
        
        # Setup type фичи
        if setup_type:
            features['setup_impulse'] = 1.0 if setup_type == "IMPULSE" else 0.0
            features['setup_soft'] = 1.0 if setup_type == "SOFT" else 0.0
            features['setup_needs_confirmation'] = 1.0 if setup_type == "NEEDS_CONFIRMATION" else 0.0
        else:
            features['setup_impulse'] = 0.0
            features['setup_soft'] = 0.0
            features['setup_needs_confirmation'] = 0.0
        
        # Grade фичи
        if grade:
            grade_map = {"A": 4, "B": 3, "C": 2, "D": 1}
            features['grade_numeric'] = grade_map.get(grade, 2.5)
        else:
            features['grade_numeric'] = 2.5
        
        # CI ширина
        if confidence_interval_68:
            ci_lower, ci_upper = confidence_interval_68
            features['ci_width'] = abs(ci_upper - ci_lower)
        else:
            features['ci_width'] = 0.1  # Дефолт
        
        # Reliability
        features['reliability_score'] = reliability_score if reliability_score is not None else 0.5
        
        # Взаимодействия
        features['p_up_x_grade'] = probability_up * features['grade_numeric']
        features['return_x_pump'] = predicted_return * features['pump_score']
        features['return_x_risk'] = predicted_return * features['risk_score']
        
        return features
    
    def forecast(
        self,
        predicted_return: float,
        probability_up: float,
        momentum_grade: Optional[str] = None,
        momentum_strength: Optional[float] = None,
        global_regime: Optional[str] = None,
        pump_score: Optional[float] = None,
        risk_score: Optional[float] = None,
        setup_type: Optional[str] = None,
        grade: Optional[str] = None,
        confidence_interval_68: Optional[tuple] = None,
        reliability_score: Optional[float] = None
    ) -> MetaForecast:
        """
        Сделать meta-прогноз.
        
        Args:
            predicted_return: Предсказанный return из основной модели
            probability_up: Вероятность роста
            ... (остальные параметры как в _build_features)
        
        Returns:
            MetaForecast с корректировкой
        """
        # Строим фичи
        features = self._build_features(
            predicted_return, probability_up,
            momentum_grade, momentum_strength,
            global_regime, pump_score, risk_score,
            setup_type, grade, confidence_interval_68, reliability_score
        )
        
        # Если модель обучена, используем её
        if self.model is not None:
            # TODO: Использовать обученную модель
            pass
        
        # Пока используем rule-based логику
        return self._rule_based_forecast(features, predicted_return)
    
    def _rule_based_forecast(self, features: Dict[str, float], predicted_return: float) -> MetaForecast:
        """
        Rule-based корректировка (пока модель не обучена).
        
        Args:
            features: Фичи
            predicted_return: Исходный прогноз
        
        Returns:
            MetaForecast
        """
        adjusted_e_r = predicted_return
        trade_flag = True
        confidence = 0.7
        factors = {}
        
        # Корректировка 1: Grade
        if features['grade_numeric'] < 2.5:  # Grade C или D
            adjusted_e_r *= 0.7
            factors['grade_adjustment'] = -0.3
            if features['grade_numeric'] < 2.0:  # Grade D
                trade_flag = False
                factors['grade_block'] = -1.0
        
        # Корректировка 2: Risk vs Pump
        if features['pump_risk_ratio'] < 0.8:  # Риск выше потенциала
            adjusted_e_r *= 0.8
            factors['risk_adjustment'] = -0.2
        
        # Корректировка 3: Setup type
        if features['setup_needs_confirmation'] > 0.5:
            adjusted_e_r *= 0.6
            factors['setup_adjustment'] = -0.4
            trade_flag = False
        
        # Корректировка 4: Режим против прогноза
        if features['regime_risk_off'] > 0.5 and predicted_return > 0:
            adjusted_e_r *= 0.7
            factors['regime_conflict'] = -0.3
        
        # Корректировка 5: Широкий CI = низкая уверенность
        if features['ci_width'] > 0.05:
            adjusted_e_r *= 0.9
            confidence *= 0.8
            factors['ci_adjustment'] = -0.1
        
        # Корректировка 6: Reliability
        if features['reliability_score'] < 0.5:
            adjusted_e_r *= 0.85
            factors['reliability_adjustment'] = -0.15
        
        return MetaForecast(
            adjusted_e_r=adjusted_e_r,
            trade_flag=trade_flag,
            confidence=confidence,
            factors=factors
        )
    
    def train(self, min_samples: int = 100) -> bool:
        """
        Обучить meta-модель на исторических данных.
        
        Args:
            min_samples: Минимальное количество образцов
        
        Returns:
            True если обучение успешно
        """
        if not HAS_CATBOOST:
            logger.error("CatBoost not available for training")
            return False
        
        try:
            # Получаем исторические данные из forecast_history и outcomes
            cur = self.db.conn.cursor()
            
            # TODO: Реализовать получение данных с outcomes
            # Пока возвращаем False - модель не обучена
            logger.warning("Meta-forecaster training not yet implemented")
            return False
        except Exception as e:
            logger.exception(f"Failed to train meta-forecaster: {e}")
            return False


















