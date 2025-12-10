# app/domain/market_diagnostics/anomaly_detector.py
"""
Детектор аномалий для Market Doctor.

Обнаруживает необычные ситуации на рынке:
- Резкие изменения funding/OI/CVD
- Аномалии деривативов
- Резкие изменения фаз рынка
"""

from dataclasses import dataclass
from typing import Optional, List, Dict, Any, TYPE_CHECKING
from datetime import datetime, timedelta
import time

if TYPE_CHECKING:
    from ...domain.interfaces.idiagnostics_repository import IDiagnosticsRepository
else:
    IDiagnosticsRepository = object

from .analyzer import MarketDiagnostics, MarketPhase


@dataclass
class AnomalyAlert:
    """Алерт об аномалии."""
    symbol: str
    timeframe: str
    anomaly_type: str  # "funding_spike", "oi_anomaly", "cvd_divergence", "phase_change", "doctor_concerned"
    severity: str  # "low", "medium", "high"
    message: str
    timestamp: int
    metadata: Optional[Dict[str, Any]] = None


class AnomalyDetector:
    """Детектор аномалий для Market Doctor."""
    
    def __init__(self, diagnostics_repo: IDiagnosticsRepository):
        """
        Args:
            diagnostics_repo: Репозиторий диагностик для проверки истории (реализует IDiagnosticsRepository интерфейс)
        """
        self.diagnostics_repo = diagnostics_repo
    
    def detect_derivatives_anomalies(
        self,
        symbol: str,
        timeframe: str,
        derivatives: Dict[str, float],
        current_price: float
    ) -> List[AnomalyAlert]:
        """
        Обнаружить аномалии в деривативах.
        
        Args:
            symbol: Символ
            timeframe: Таймфрейм
            derivatives: Данные деривативов
            current_price: Текущая цена
        
        Returns:
            Список алертов об аномалиях
        """
        alerts = []
        
        funding = derivatives.get('funding_rate', 0.0)
        oi_change = derivatives.get('oi_change_pct', 0.0)
        cvd = derivatives.get('cvd', 0.0)
        
        # Аномалия: funding резко улетел, а цена стоит
        if abs(funding) > 0.01 and abs(oi_change) < 2.0:
            alerts.append(AnomalyAlert(
                symbol=symbol,
                timeframe=timeframe,
                anomaly_type="funding_spike",
                severity="medium",
                message=(
                    f"⚡ {symbol}: деривативная аномалия — "
                    f"экстремальный funding ({funding*100:.2f}%) при стабильной цене. "
                    f"Возможен крупный импульс."
                ),
                timestamp=int(time.time() * 1000),
                metadata={"funding": funding, "oi_change": oi_change}
            ))
        
        # Аномалия: OI резко вырос, а vol низкая
        if oi_change > 10.0:
            alerts.append(AnomalyAlert(
                symbol=symbol,
                timeframe=timeframe,
                anomaly_type="oi_anomaly",
                severity="high",
                message=(
                    f"⚡ {symbol}: резкий рост OI (+{oi_change:.1f}%) при низкой волатильности. "
                    f"Возможна подготовка к крупному движению."
                ),
                timestamp=int(time.time() * 1000),
                metadata={"oi_change": oi_change}
            ))
        
        # Аномалия: CVD сильно в одну сторону против цены
        if cvd != 0.0:
            # Если CVD сильно отрицательный, а цена растет - дивергенция
            if cvd < -0.3:
                alerts.append(AnomalyAlert(
                    symbol=symbol,
                    timeframe=timeframe,
                    anomaly_type="cvd_divergence",
                    severity="medium",
                    message=(
                        f"⚡ {symbol}: дивергенция CVD — сильный отток ликвидности "
                        f"при росте цены. Возможна коррекция."
                    ),
                    timestamp=int(time.time() * 1000),
                    metadata={"cvd": cvd}
                ))
        
        return alerts
    
    def detect_phase_change(
        self,
        symbol: str,
        timeframe: str,
        current_phase: MarketPhase,
        hours_back: int = 24
    ) -> Optional[AnomalyAlert]:
        """
        Обнаружить резкое изменение фазы рынка.
        
        Args:
            symbol: Символ
            timeframe: Таймфрейм
            current_phase: Текущая фаза
            hours_back: Сколько часов назад проверять
        
        Returns:
            Алерт об изменении фазы или None
        """
        # Получаем предыдущие диагностики
        snapshots = self.diagnostics_repo.get_snapshots(
            symbol=symbol,
            timeframe=timeframe,
            limit=10
        )
        
        if len(snapshots) < 2:
            return None
        
        # Берем последнюю диагностику (текущую) и предпоследнюю
        current_snapshot = snapshots[0]
        previous_snapshot = snapshots[1]
        
        current_phase_str = current_snapshot.get('phase')
        previous_phase_str = previous_snapshot.get('phase')
        
        if current_phase_str != previous_phase_str:
            # Проверяем, было ли это резкое изменение
            phase_changes = {
                ("ACCUMULATION", "EXPANSION_DOWN"): "high",
                ("EXPANSION_UP", "EXPANSION_DOWN"): "high",
                ("ACCUMULATION", "DISTRIBUTION"): "medium",
                ("EXPANSION_UP", "DISTRIBUTION"): "medium",
            }
            
            change_key = (previous_phase_str, current_phase_str)
            severity = phase_changes.get(change_key, "low")
            
            return AnomalyAlert(
                symbol=symbol,
                timeframe=timeframe,
                anomaly_type="phase_change",
                severity=severity,
                message=(
                    f"⚡ {symbol}: резкое изменение фазы — "
                    f"{previous_phase_str} → {current_phase_str}. "
                    f"Рынок перешел в другую структуру."
                ),
                timestamp=int(time.time() * 1000),
                metadata={
                    "previous_phase": previous_phase_str,
                    "current_phase": current_phase_str
                }
            )
        
        return None
    
    def detect_risk_spike(
        self,
        symbol: str,
        timeframe: str,
        current_risk_score: float,
        hours_back: int = 6
    ) -> Optional[AnomalyAlert]:
        """
        Обнаружить резкий рост risk_score.
        
        Args:
            symbol: Символ
            timeframe: Таймфрейм
            current_risk_score: Текущий risk_score
            hours_back: Сколько часов назад проверять
        
        Returns:
            Алерт о росте риска или None
        """
        # Получаем предыдущие диагностики
        snapshots = self.diagnostics_repo.get_snapshots(
            symbol=symbol,
            timeframe=timeframe,
            limit=10
        )
        
        if len(snapshots) < 2:
            return None
        
        # Берем последнюю диагностику (текущую) и предпоследнюю
        current_snapshot = snapshots[0]
        previous_snapshot = snapshots[1]
        
        previous_risk = previous_snapshot.get('risk_score', 0.0)
        
        # Если risk_score подскочил на 0.2 или больше
        if current_risk_score - previous_risk >= 0.2:
            return AnomalyAlert(
                symbol=symbol,
                timeframe=timeframe,
                anomaly_type="doctor_concerned",
                severity="high" if current_risk_score > 0.7 else "medium",
                message=(
                    f"⚡ {symbol}: резкий рост риска — "
                    f"risk_score подскочил с {previous_risk:.2f} до {current_risk_score:.2f}. "
                    f"Рынок стал более нестабильным."
                ),
                timestamp=int(time.time() * 1000),
                metadata={
                    "previous_risk": previous_risk,
                    "current_risk": current_risk_score
                }
            )
        
        return None
    
    def detect_all_anomalies(
        self,
        symbol: str,
        timeframe: str,
        diagnostics: MarketDiagnostics,
        derivatives: Dict[str, float],
        current_price: float
    ) -> List[AnomalyAlert]:
        """
        Обнаружить все аномалии для символа.
        
        Args:
            symbol: Символ
            timeframe: Таймфрейм
            diagnostics: Текущая диагностика
            derivatives: Данные деривативов
            current_price: Текущая цена
        
        Returns:
            Список всех обнаруженных аномалий
        """
        alerts = []
        
        # Деривативные аномалии
        alerts.extend(self.detect_derivatives_anomalies(
            symbol, timeframe, derivatives, current_price
        ))
        
        # Изменение фазы
        phase_alert = self.detect_phase_change(symbol, timeframe, diagnostics.phase)
        if phase_alert:
            alerts.append(phase_alert)
        
        # Рост риска
        risk_alert = self.detect_risk_spike(
            symbol, timeframe, diagnostics.risk_score
        )
        if risk_alert:
            alerts.append(risk_alert)
        
        return alerts


