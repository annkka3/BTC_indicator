# app/domain/twap_detector/pattern_analyzer.py
"""
Анализатор паттернов TWAP-алгоритмов в потоке сделок.
"""

from typing import List, Dict, Optional
from dataclasses import dataclass
import logging

# numpy опционален - используем fallback если не установлен
try:
    import numpy as np
except ImportError:
    np = None

logger = logging.getLogger("alt_forecast.twap_detector")


@dataclass
class ExchangeAnalysis:
    """Результат анализа одной биржи."""
    exchange: str
    direction: str  # "BUY" или "SELL"
    algo_score: float  # 0.0 - 1.0
    algo_volume_usd: float  # Объём алго-ордеров в USD
    net_flow_usd: float  # Чистый поток (покупки - продажи) в USD
    buy_volume_usd: float
    sell_volume_usd: float
    imbalance: float  # -1.0 до 1.0 (отрицательное = продажи доминируют)
    total_trades: int
    algo_trades_count: int


class TWAPPatternAnalyzer:
    """Анализатор TWAP-паттернов в потоке сделок."""
    
    def __init__(self):
        """Инициализация анализатора."""
        pass
    
    def analyze_trades(
        self,
        trades: List[Dict],
        current_price: float
    ) -> ExchangeAnalysis:
        """
        Проанализировать поток сделок и определить TWAP-паттерны.
        
        Args:
            trades: Список сделок [{"time": ms, "price": float, "qty": float, "is_buyer": bool}, ...]
            current_price: Текущая цена актива
        
        Returns:
            ExchangeAnalysis с результатами анализа
        """
        if not trades:
            return ExchangeAnalysis(
                exchange=trades[0].get("exchange", "Unknown") if trades else "Unknown",
                direction="NEUTRAL",
                algo_score=0.0,
                algo_volume_usd=0.0,
                net_flow_usd=0.0,
                buy_volume_usd=0.0,
                sell_volume_usd=0.0,
                imbalance=0.0,
                total_trades=0,
                algo_trades_count=0,
            )
        
        exchange = trades[0].get("exchange", "Unknown")
        
        # Сортируем сделки по времени
        sorted_trades = sorted(trades, key=lambda x: x["time"])
        
        # Рассчитываем базовые метрики
        buy_volume_usd = 0.0
        sell_volume_usd = 0.0
        
        for trade in sorted_trades:
            volume_usd = trade["price"] * trade["qty"]
            if trade["is_buyer"]:
                buy_volume_usd += volume_usd
            else:
                sell_volume_usd += volume_usd
        
        net_flow_usd = buy_volume_usd - sell_volume_usd
        total_volume = buy_volume_usd + sell_volume_usd
        
        # Рассчитываем imbalance (-1.0 до 1.0)
        if total_volume > 0:
            imbalance = (buy_volume_usd - sell_volume_usd) / total_volume
        else:
            imbalance = 0.0
        
        # Определяем направление
        if imbalance > 0.1:
            direction = "BUY"
        elif imbalance < -0.1:
            direction = "SELL"
        else:
            direction = "NEUTRAL"
        
        # Анализируем алгоподобность
        algo_score, algo_trades = self._detect_algo_pattern(sorted_trades, current_price)
        
        # Рассчитываем объём алго-ордеров
        algo_volume_usd = 0.0
        for trade in algo_trades:
            volume_usd = trade["price"] * trade["qty"]
            algo_volume_usd += volume_usd
        
        return ExchangeAnalysis(
            exchange=exchange,
            direction=direction,
            algo_score=algo_score,
            algo_volume_usd=algo_volume_usd,
            net_flow_usd=net_flow_usd,
            buy_volume_usd=buy_volume_usd,
            sell_volume_usd=sell_volume_usd,
            imbalance=imbalance,
            total_trades=len(sorted_trades),
            algo_trades_count=len(algo_trades),
        )
    
    def _detect_algo_pattern(
        self,
        trades: List[Dict],
        current_price: float
    ) -> tuple[float, List[Dict]]:
        """
        Детектировать TWAP-паттерн в потоке сделок.
        
        Признаки TWAP-алгоритма:
        1. Много мелких однонаправленных сделок
        2. Похожий объём сделок
        3. Равные интервалы между сделками
        4. Однонаправленность (все покупки или все продажи)
        
        Returns:
            (algo_score, algo_trades) где algo_score от 0.0 до 1.0
        """
        if len(trades) < 5:
            return 0.0, []
        
        # Группируем сделки по направлению
        buy_trades = [t for t in trades if t["is_buyer"]]
        sell_trades = [t for t in trades if not t["is_buyer"]]
        
        # Выбираем группу с большим количеством сделок
        if len(buy_trades) >= len(sell_trades) and len(buy_trades) >= 5:
            candidate_trades = buy_trades
        elif len(sell_trades) >= 5:
            candidate_trades = sell_trades
        else:
            return 0.0, []
        
        # Проверяем признаки TWAP-паттерна
        scores = []
        
        # 1. Однонаправленность (все сделки в одну сторону)
        same_direction_score = 1.0 if len(candidate_trades) >= len(trades) * 0.7 else 0.0
        scores.append(same_direction_score)
        
        # 2. Похожий объём сделок (низкая вариативность)
        volumes = [t["qty"] for t in candidate_trades]
        if len(volumes) > 1:
            try:
                import numpy as np
                cv = np.std(volumes) / np.mean(volumes) if np.mean(volumes) > 0 else 1.0
            except ImportError:
                # Fallback без numpy
                mean_vol = sum(volumes) / len(volumes)
                variance = sum((x - mean_vol) ** 2 for x in volumes) / len(volumes)
                std_vol = variance ** 0.5
                cv = std_vol / mean_vol if mean_vol > 0 else 1.0
            # Коэффициент вариации < 0.5 считается признаком алгоритма
            volume_consistency_score = max(0.0, 1.0 - cv)
            scores.append(volume_consistency_score)
        else:
            scores.append(0.0)
        
        # 3. Равные интервалы между сделками
        if len(candidate_trades) > 1:
            intervals = []
            for i in range(1, len(candidate_trades)):
                interval = candidate_trades[i]["time"] - candidate_trades[i-1]["time"]
                intervals.append(interval)
            
            if len(intervals) > 1:
                try:
                    import numpy as np
                    cv_intervals = np.std(intervals) / np.mean(intervals) if np.mean(intervals) > 0 else 1.0
                except ImportError:
                    # Fallback без numpy
                    mean_int = sum(intervals) / len(intervals)
                    variance = sum((x - mean_int) ** 2 for x in intervals) / len(intervals)
                    std_int = variance ** 0.5
                    cv_intervals = std_int / mean_int if mean_int > 0 else 1.0
                # Коэффициент вариации интервалов < 0.7 считается признаком алгоритма
                interval_consistency_score = max(0.0, 1.0 - cv_intervals)
                scores.append(interval_consistency_score)
            else:
                scores.append(0.0)
        else:
            scores.append(0.0)
        
        # 4. Много мелких сделок (относительно среднего объёма)
        try:
            import numpy as np
            avg_volume = np.mean(volumes) if volumes else 0.0
        except ImportError:
            avg_volume = sum(volumes) / len(volumes) if volumes else 0.0
        total_volume = sum(volumes)
        # Если средний объём меньше 10% от общего, это признак алгоритма
        if total_volume > 0:
            small_trades_ratio = avg_volume / total_volume if total_volume > 0 else 0.0
            small_trades_score = min(1.0, small_trades_ratio * 10)  # Нормализуем
            scores.append(small_trades_score)
        else:
            scores.append(0.0)
        
        # 5. Количество сделок (больше сделок = больше вероятность алгоритма)
        trades_count_score = min(1.0, len(candidate_trades) / 50.0)  # 50+ сделок = максимальный score
        scores.append(trades_count_score)
        
        # Итоговый score - среднее взвешенное
        weights = [0.2, 0.25, 0.25, 0.15, 0.15]  # Веса для каждого признака
        algo_score = sum(s * w for s, w in zip(scores, weights))
        
        # Если score достаточно высокий, считаем эти сделки алго-ордерами
        if algo_score >= 0.5:
            return algo_score, candidate_trades
        else:
            return algo_score, []

