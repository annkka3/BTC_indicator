# app/domain/market_diagnostics/multi_tf.py
"""
Multi-Timeframe диагностика рынка.

Позволяет анализировать рынок на нескольких таймфреймах одновременно
и видеть конфлюэнс между ними.
"""

from dataclasses import dataclass
from typing import Dict

# Не импортируем MarketDiagnostics здесь, чтобы избежать циклического импорта
# Используем строковую аннотацию типа "MarketDiagnostics"


@dataclass
class MultiTFDiagnostics:
    """Диагностика рынка на нескольких таймфреймах."""
    symbol: str
    snapshots: Dict[str, "MarketDiagnostics"]  # {"1h": ..., "4h": ..., "1d": ...}
    
    def get_consensus_phase(self) -> str:
        """Получить консенсусную фазу по всем таймфреймам с учётом весов."""
        if not self.snapshots:
            return "UNKNOWN"
        
        # Веса таймфреймов (старшие ТФ важнее)
        tf_weights = {
            "1d": 3,
            "4h": 2,
            "1h": 1,
            "15m": 0.5,
            "1m": 0.25
        }
        
        # Собираем фазы с весами
        from collections import defaultdict
        weighted_phases = defaultdict(float)
        
        for tf, snapshot in self.snapshots.items():
            weight = tf_weights.get(tf, 1.0)
            phase = snapshot.phase.value
            weighted_phases[phase] += weight
        
        if not weighted_phases:
            return "UNKNOWN"
        
        # Возвращаем фазу с наибольшим весом
        return max(weighted_phases.items(), key=lambda x: x[1])[0]
    
    def get_higher_tf_consensus(self) -> str:
        """Получить консенсус по старшим таймфреймам (4h/1d)."""
        higher_tfs = {tf: snapshot for tf, snapshot in self.snapshots.items() if tf in ["4h", "1d"]}
        if not higher_tfs:
            return None
        
        # Веса для старших ТФ
        tf_weights = {"1d": 3, "4h": 2}
        
        from collections import defaultdict
        weighted_phases = defaultdict(float)
        
        for tf, snapshot in higher_tfs.items():
            weight = tf_weights.get(tf, 2.0)
            phase = snapshot.phase.value
            weighted_phases[phase] += weight
        
        if not weighted_phases:
            return None
        
        return max(weighted_phases.items(), key=lambda x: x[1])[0]
    
    def get_local_consensus(self) -> str:
        """Получить консенсус по локальным таймфреймам (1h)."""
        local_tfs = {tf: snapshot for tf, snapshot in self.snapshots.items() if tf == "1h"}
        if not local_tfs:
            return None
        
        # Берем фазу с 1h
        return list(local_tfs.values())[0].phase.value
    
    def get_avg_pump_score(self) -> float:
        """Получить средний pump_score по всем таймфреймам."""
        scores = [snapshot.pump_score for snapshot in self.snapshots.values()]
        if not scores:
            return 0.0
        return sum(scores) / len(scores)
    
    def get_avg_risk_score(self) -> float:
        """Получить средний risk_score по всем таймфреймам."""
        scores = [snapshot.risk_score for snapshot in self.snapshots.values()]
        if not scores:
            return 0.0
        return sum(scores) / len(scores)
    
    def get_timeframe_conflict(self) -> bool:
        """Проверить, есть ли конфликт между таймфреймами."""
        if len(self.snapshots) < 2:
            return False
        
        phases = [snapshot.phase.value for snapshot in self.snapshots.values()]
        
        # Конфликт: если есть и бычьи и медвежьи фазы
        bullish_phases = {"ACCUMULATION", "EXPANSION_UP"}
        bearish_phases = {"DISTRIBUTION", "EXPANSION_DOWN"}
        
        has_bullish = any(p in bullish_phases for p in phases)
        has_bearish = any(p in bearish_phases for p in phases)
        
        return has_bullish and has_bearish
    
    def get_avg_confidence(self) -> float:
        """Получить средний confidence по всем таймфреймам."""
        confidences = [snapshot.confidence for snapshot in self.snapshots.values()]
        if not confidences:
            return 0.5
        base_confidence = sum(confidences) / len(confidences)
        
        # Увеличиваем confidence при согласованности таймфреймов
        if not self.get_timeframe_conflict():
            # Если нет конфликта, увеличиваем confidence
            base_confidence += 0.1
        
        # Ограничиваем диапазоном [0.0, 1.0]
        return max(0.0, min(1.0, base_confidence))

