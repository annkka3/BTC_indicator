# app/domain/market_diagnostics/config.py
"""
Конфигурация для Market Doctor.

Содержит все пороги, веса и параметры для анализа рынка.
Позволяет легко настраивать поведение системы под разные рынки и стратегии.
"""

from dataclasses import dataclass, field
from typing import Dict


@dataclass
class MarketDoctorConfig:
    """Конфигурация Market Doctor."""
    
    # Пороги для волатильности (ATR ratio)
    bb_low_threshold: float = 0.7
    bb_high_threshold: float = 1.5
    
    # Пороги для ликвидности (volume ratio)
    vol_low_ratio: float = 0.5
    vol_high_ratio: float = 1.5
    
    # Пороги для RSI
    rsi_oversold: int = 30
    rsi_overbought: int = 70
    
    # Пороги для Stoch RSI
    stoch_rsi_oversold: int = 20
    stoch_rsi_overbought: int = 80
    
    # Пороги для MACD
    macd_bullish_threshold: float = 0.0
    macd_bearish_threshold: float = 0.0
    
    # Пороги для деривативов
    funding_extreme_long: float = 0.01  # > 1%
    funding_extreme_short: float = -0.01  # < -1%
    funding_high: float = 0.001  # > 0.1%
    funding_low: float = -0.001  # < -0.1%
    
    oi_rapid_increase: float = 10.0  # > 10%
    oi_rapid_decrease: float = -10.0  # < -10%
    oi_increase: float = 5.0  # > 5%
    oi_decrease: float = -5.0  # < -5%
    
    # Веса для pump_score
    pump_score_weights: Dict[str, float] = field(default_factory=lambda: {
        "phase": 0.3,
        "trend": 0.2,
        "volatility": 0.1,
        "structure": 0.15,
        "derivatives": 0.25,
    })
    
    # Веса для risk_score
    risk_score_weights: Dict[str, float] = field(default_factory=lambda: {
        "volatility": 0.3,
        "liquidity": 0.25,
        "phase": 0.2,
        "derivatives": 0.15,
        "trend": 0.1,
    })
    
    # Пороги для pump_score компонентов
    pump_phase_weights: Dict[str, float] = field(default_factory=lambda: {
        "ACCUMULATION": 0.3,
        "SHAKEOUT": 0.25,
        "EXPANSION_UP": 0.2,
        "DISTRIBUTION": 0.0,
        "EXPANSION_DOWN": 0.0,
    })
    
    # Пороги для risk_score компонентов
    risk_phase_weights: Dict[str, float] = field(default_factory=lambda: {
        "SHAKEOUT": 0.2,
        "EXPANSION_DOWN": 0.15,
        "DISTRIBUTION": 0.1,
        "EXPANSION_UP": 0.05,
        "ACCUMULATION": 0.0,
    })
    
    # Пороги для отклонения от VWAP/EMA200 (для pump_score)
    vwap_deviation_threshold: float = 0.02  # 2% отклонение
    ema200_deviation_threshold: float = 0.05  # 5% отклонение
    
    # Минимальное количество баров для полного анализа
    min_full_bars: int = 150
    
    def validate(self) -> None:
        """Проверить корректность конфигурации."""
        # Проверяем, что веса pump_score суммируются примерно в 1.0
        pump_sum = sum(self.pump_score_weights.values())
        if abs(pump_sum - 1.0) > 0.01:
            raise ValueError(f"pump_score_weights must sum to 1.0, got {pump_sum}")
        
        # Проверяем, что веса risk_score суммируются примерно в 1.0
        risk_sum = sum(self.risk_score_weights.values())
        if abs(risk_sum - 1.0) > 0.01:
            raise ValueError(f"risk_score_weights must sum to 1.0, got {risk_sum}")


# Пресеты конфигураций
SAFE_CONFIG = MarketDoctorConfig(
    bb_low_threshold=0.6,
    bb_high_threshold=1.3,
    vol_low_ratio=0.6,
    vol_high_ratio=1.3,
    pump_score_weights={
        "phase": 0.25,
        "trend": 0.25,
        "volatility": 0.15,
        "structure": 0.15,
        "derivatives": 0.2,
    },
    risk_score_weights={
        "volatility": 0.35,
        "liquidity": 0.3,
        "phase": 0.15,
        "derivatives": 0.1,
        "trend": 0.1,
    },
)

AGGRESSIVE_CONFIG = MarketDoctorConfig(
    bb_low_threshold=0.8,
    bb_high_threshold=1.7,
    vol_low_ratio=0.4,
    vol_high_ratio=1.7,
    pump_score_weights={
        "phase": 0.35,
        "trend": 0.15,
        "volatility": 0.1,
        "structure": 0.2,
        "derivatives": 0.2,
    },
    risk_score_weights={
        "volatility": 0.25,
        "liquidity": 0.2,
        "phase": 0.25,
        "derivatives": 0.2,
        "trend": 0.1,
    },
)

# Конфигурация по умолчанию
DEFAULT_CONFIG = MarketDoctorConfig()


