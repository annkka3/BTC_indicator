# app/domain/market_diagnostics/conditions_shift.py
"""
Conditions for shift - что должно случиться для смены bias.
"""

from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from enum import Enum


class ShiftCondition(Enum):
    """Условие для смены bias."""
    OI_GROWTH = "oi_growth"
    VOLUME_RETURN = "volume_return"
    LIQUIDITY_REMOVAL = "liquidity_removal"
    FUNDING_NEUTRAL = "funding_neutral"
    STRUCTURE_BREAK = "structure_break"
    MOMENTUM_CONFIRMATION = "momentum_confirmation"


@dataclass
class ShiftConditions:
    """Условия для смены bias."""
    current_bias: str  # "LONG", "SHORT", "NEUTRAL"
    target_bias: str  # "LONG", "SHORT"
    conditions: List[Dict]  # [{condition, description, current_state, required_state}]
    summary: str  # Краткое резюме


class ConditionsShift:
    """Анализатор условий для смены bias."""
    
    def __init__(self):
        """Инициализация."""
        pass
    
    def analyze_conditions_for_shift(
        self,
        current_bias: str,
        target_bias: str,
        current_oi_delta: Optional[float] = None,
        required_oi_delta: float = 0.03,
        current_volume: Optional[float] = None,
        avg_volume: Optional[float] = None,
        liquidity_above: Optional[List[float]] = None,
        current_funding: Optional[float] = None,
        neutral_funding_range: Tuple[float, float] = (-0.005, 0.005),
        structure_level: Optional[float] = None,
        break_level: Optional[float] = None,
        current_momentum: Optional[float] = None,
        required_momentum: float = 0.5
    ) -> ShiftConditions:
        """
        Определить условия для смены bias.
        
        Returns:
            ShiftConditions
        """
        conditions = []
        
        # Условие 1: OI должен расти вместе с ценой
        if current_oi_delta is not None:
            oi_ok = current_oi_delta >= required_oi_delta
            conditions.append({
                "condition": ShiftCondition.OI_GROWTH,
                "description": "ОИ начнёт расти вместе с ценой",
                "current_state": f"OI delta: {current_oi_delta*100:+.2f}%",
                "required_state": f"OI delta >= {required_oi_delta*100:.1f}%",
                "met": oi_ok
            })
        
        # Условие 2: Объёмы должны вернуться
        if current_volume is not None and avg_volume is not None:
            volume_ratio = current_volume / avg_volume if avg_volume > 0 else 1.0
            volume_ok = volume_ratio >= 1.0
            conditions.append({
                "condition": ShiftCondition.VOLUME_RETURN,
                "description": "Объёмы вернутся",
                "current_state": f"Объём: {volume_ratio:.2f}x среднего",
                "required_state": "Объём >= среднего",
                "met": volume_ok
            })
        
        # Условие 3: Ликвидность выше должна быть снята
        if liquidity_above:
            liq_sum = sum(liquidity_above)
            liq_ok = liq_sum == 0
            conditions.append({
                "condition": ShiftCondition.LIQUIDITY_REMOVAL,
                "description": "Ликвидность выше будет снята",
                "current_state": f"Ликвидность выше: {liq_sum:.0f}",
                "required_state": "Ликвидность выше = 0",
                "met": liq_ok
            })
        
        # Условие 4: Funding должен остаться нейтральным
        if current_funding is not None:
            funding_ok = neutral_funding_range[0] <= current_funding <= neutral_funding_range[1]
            conditions.append({
                "condition": ShiftCondition.FUNDING_NEUTRAL,
                "description": "Funding останется нейтральным",
                "current_state": f"Funding: {current_funding*100:+.3f}%",
                "required_state": f"Funding в диапазоне {neutral_funding_range[0]*100:.3f}% - {neutral_funding_range[1]*100:.3f}%",
                "met": funding_ok
            })
        
        # Условие 5: Пробой структуры
        if structure_level is not None and break_level is not None:
            break_ok = break_level > structure_level if target_bias == "LONG" else break_level < structure_level
            conditions.append({
                "condition": ShiftCondition.STRUCTURE_BREAK,
                "description": f"Пробой уровня {structure_level:.0f}",
                "current_state": f"Текущая цена: {break_level:.0f}",
                "required_state": f"Цена {'>' if target_bias == 'LONG' else '<'} {structure_level:.0f}",
                "met": break_ok
            })
        
        # Условие 6: Подтверждение импульса
        if current_momentum is not None:
            momentum_ok = current_momentum >= required_momentum if target_bias == "LONG" else current_momentum <= -required_momentum
            conditions.append({
                "condition": ShiftCondition.MOMENTUM_CONFIRMATION,
                "description": "Подтверждение импульса",
                "current_state": f"Momentum: {current_momentum:+.2f}",
                "required_state": f"Momentum {'>=' if target_bias == 'LONG' else '<='} {required_momentum if target_bias == 'LONG' else -required_momentum:.2f}",
                "met": momentum_ok
            })
        
        # Формируем резюме
        met_count = sum(1 for c in conditions if c.get("met", False))
        total_count = len(conditions)
        
        if met_count == total_count:
            summary = f"Все условия выполнены ({met_count}/{total_count}) — {target_bias} стал high-conviction"
        elif met_count >= total_count * 0.7:
            summary = f"Большинство условий выполнено ({met_count}/{total_count}) — {target_bias} близок к high-conviction"
        else:
            summary = f"Условия частично выполнены ({met_count}/{total_count}) — {target_bias} требует дополнительных подтверждений"
        
        return ShiftConditions(
            current_bias=current_bias,
            target_bias=target_bias,
            conditions=conditions,
            summary=summary
        )
    
    def format_conditions_text(
        self,
        conditions: ShiftConditions
    ) -> str:
        """Форматировать условия в текст."""
        # Преобразуем target_bias в читаемый формат
        target_bias_text = conditions.target_bias
        if target_bias_text == "LONG":
            target_bias_text = "Лонговый"
        elif target_bias_text == "SHORT":
            target_bias_text = "Медвежий"
        
        lines = []
        
        for cond in conditions.conditions:
            status = "✔" if cond.get("met", False) else "✗"
            lines.append(f"{status} {cond['description']}")
        
        if conditions.summary:
            lines.append("")
            lines.append(conditions.summary)
        
        return "\n".join(lines)

