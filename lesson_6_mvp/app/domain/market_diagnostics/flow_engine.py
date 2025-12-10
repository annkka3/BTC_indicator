# app/domain/market_diagnostics/flow_engine.py
"""
Flow Engine - анализ потоков капитала (institutional level).
"""

from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
import statistics


@dataclass
class FlowAnalysis:
    """Анализ потоков капитала."""
    cvd_rate_of_change: float  # CVD rate-of-change
    oi_delta_clusters: Dict[str, float]  # {timeframe: delta}
    funding_z_score: float  # Отклонение funding от среднего
    aggressive_orders_imbalance: float  # Дисбаланс агрессивных ордеров
    interpretation: str  # Человеческое объяснение


class FlowEngine:
    """Движок анализа потоков капитала."""
    
    def __init__(self):
        """Инициализация."""
        pass
    
    def calculate_cvd_rate_of_change(
        self,
        cvd_values: List[float],
        period: int = 20
    ) -> float:
        """
        Рассчитать rate-of-change для CVD (Cumulative Volume Delta).
        
        Args:
            cvd_values: Последние значения CVD
            period: Период для расчета
        
        Returns:
            Rate of change в процентах
        """
        if len(cvd_values) < period + 1:
            return 0.0
        
        current = cvd_values[-1]
        previous = cvd_values[-period - 1]
        
        if previous == 0:
            return 0.0
        
        return ((current - previous) / abs(previous)) * 100
    
    def analyze_oi_delta_clusters(
        self,
        oi_data: Dict[str, List[float]]  # {timeframe: [oi_values]}
    ) -> Dict[str, float]:
        """
        Анализ кластеров изменения Open Interest по таймфреймам.
        
        Returns:
            {timeframe: delta_percentage}
        """
        clusters = {}
        
        for tf, oi_values in oi_data.items():
            if len(oi_values) < 2:
                continue
            
            current = oi_values[-1]
            previous = oi_values[-2] if len(oi_values) >= 2 else oi_values[0]
            
            if previous == 0:
                clusters[tf] = 0.0
            else:
                delta_pct = ((current - previous) / previous) * 100
                clusters[tf] = delta_pct
        
        return clusters
    
    def calculate_funding_z_score(
        self,
        current_funding: float,
        historical_funding: List[float],
        window: int = 100
    ) -> float:
        """
        Рассчитать z-score funding rate относительно исторического среднего.
        
        Returns:
            Z-score (стандартные отклонения от среднего)
        """
        if len(historical_funding) < 10:
            return 0.0
        
        recent = historical_funding[-window:] if len(historical_funding) > window else historical_funding
        
        if not recent:
            return 0.0
        
        mean_funding = statistics.mean(recent)
        std_funding = statistics.stdev(recent) if len(recent) > 1 else 0.001
        
        if std_funding == 0:
            return 0.0
        
        z_score = (current_funding - mean_funding) / std_funding
        return z_score
    
    def calculate_aggressive_orders_imbalance(
        self,
        buy_orders: List[float],  # Объемы агрессивных покупок
        sell_orders: List[float],  # Объемы агрессивных продаж
        lookback: int = 20
    ) -> float:
        """
        Рассчитать дисбаланс агрессивных ордеров.
        
        Returns:
            Имбаланс от -1 до +1 (положительный = больше покупок)
        """
        if len(buy_orders) < lookback or len(sell_orders) < lookback:
            lookback = min(len(buy_orders), len(sell_orders))
        
        recent_buys = sum(buy_orders[-lookback:])
        recent_sells = sum(sell_orders[-lookback:])
        
        total = recent_buys + recent_sells
        if total == 0:
            return 0.0
        
        imbalance = (recent_buys - recent_sells) / total
        return imbalance
    
    def generate_flow_interpretation(
        self,
        cvd_roc: float,
        oi_deltas: Dict[str, float],
        funding_z: float,
        aggressive_imbalance: float
    ) -> str:
        """Сгенерировать человеческое объяснение потоков."""
        interpretations = []
        
        # CVD анализ
        if abs(cvd_roc) > 5:
            direction = "растёт" if cvd_roc > 0 else "падает"
            interpretations.append(f"CVD {direction} ({cvd_roc:+.1f}%)")
        
        # OI анализ
        if oi_deltas:
            avg_oi_delta = sum(oi_deltas.values()) / len(oi_deltas)
            if abs(avg_oi_delta) > 2:
                if avg_oi_delta > 0:
                    interpretations.append(f"OI растёт +{avg_oi_delta:.1f}%, но цена стоит — сигнал на поглощение лимитами (limit absorption)")
                else:
                    interpretations.append(f"OI падает {avg_oi_delta:.1f}% — возможна разгрузка позиций")
        
        # Funding анализ
        if abs(funding_z) > 2:
            funding_pct = funding_z * 0.01  # Примерное преобразование
            if funding_z > 0:
                interpretations.append(f"Funding +{funding_pct*100:.3f}% — слишком горячо, вероятна контрреакция маркет-мейкера")
            else:
                interpretations.append(f"Funding {funding_pct*100:.3f}% — слишком холодно, возможен отскок")
        
        # Агрессивные ордера
        if abs(aggressive_imbalance) > 0.3:
            side = "покупателей" if aggressive_imbalance > 0 else "продавцов"
            interpretations.append(f"Дисбаланс агрессивных ордеров в пользу {side} ({aggressive_imbalance*100:+.0f}%)")
        
        return ". ".join(interpretations) if interpretations else "Потоки капитала нейтральны"
    
    def analyze_flows(
        self,
        cvd_values: Optional[List[float]] = None,
        oi_data: Optional[Dict[str, List[float]]] = None,
        current_funding: Optional[float] = None,
        historical_funding: Optional[List[float]] = None,
        buy_orders: Optional[List[float]] = None,
        sell_orders: Optional[List[float]] = None
    ) -> FlowAnalysis:
        """
        Полный анализ потоков капитала.
        
        Returns:
            FlowAnalysis
        """
        # CVD
        cvd_roc = 0.0
        if cvd_values:
            cvd_roc = self.calculate_cvd_rate_of_change(cvd_values)
        
        # OI delta
        oi_deltas = {}
        if oi_data:
            oi_deltas = self.analyze_oi_delta_clusters(oi_data)
        
        # Funding z-score
        funding_z = 0.0
        if current_funding is not None and historical_funding:
            funding_z = self.calculate_funding_z_score(current_funding, historical_funding)
        
        # Aggressive orders
        aggressive_imbalance = 0.0
        if buy_orders and sell_orders:
            aggressive_imbalance = self.calculate_aggressive_orders_imbalance(buy_orders, sell_orders)
        
        # Интерпретация
        interpretation = self.generate_flow_interpretation(
            cvd_roc, oi_deltas, funding_z, aggressive_imbalance
        )
        
        return FlowAnalysis(
            cvd_rate_of_change=cvd_roc,
            oi_delta_clusters=oi_deltas,
            funding_z_score=funding_z,
            aggressive_orders_imbalance=aggressive_imbalance,
            interpretation=interpretation
        )












