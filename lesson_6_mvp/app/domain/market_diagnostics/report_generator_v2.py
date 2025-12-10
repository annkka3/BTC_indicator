"""
Новая архитектура генератора отчётов Market Doctor v2.

Решает проблемы:
- Убирает дубликаты информации
- Унифицирует bias (убирает конфликты)
- Сокращает количество уровней до ключевых
- Автоматически решает, что показывать/скрывать
- Генерирует более структурированный "институциональный" отчёт
"""

from dataclasses import dataclass
from enum import Enum
from typing import Optional, List, Tuple


class Phase(str, Enum):
    ACCUMULATION = "accumulation"
    EXP_UP = "exp_up"
    EXP_DOWN = "exp_down"
    RANGE = "range"
    DISTRIBUTION = "distribution"


class SetupType(str, Enum):
    RANGE = "range"
    CONTINUATION = "continuation"
    REVERSAL = "reversal"
    MEAN_REVERSION = "mean_reversion"


class MicroRegime(str, Enum):
    TREND = "trend"
    EXHAUSTION = "exhaustion"
    LIQUIDITY_HUNT = "liquidity_hunt"
    CHOP = "chop"


@dataclass
class Bias:
    tactical: str          # "bullish" / "bearish" / "neutral"
    strategic: str         # "bullish" / "bearish" / "neutral"
    structural: Optional[str] = None   # текст типа "выше дневного EQH (93493)..."
    liquidity: Optional[str] = None    # текст "накопление ликвидности над локальными хайями"


@dataclass
class DirectionalScores:
    long_score: float      # 0–10
    short_score: float     # 0–10
    confidence: float      # 0–1 (0.53 == 53%)


@dataclass
class FlowSnapshot:
    cvd_change_pct: Optional[float] = None  # +15.7
    funding: Optional[float] = None         # 0.006
    oi_change_pct: Optional[float] = None   # +2.1
    comment: Optional[str] = None           # свободный текст, если хочешь


@dataclass
class Zone:
    name: str                  # "Основная зона спроса", "Зона предложения"
    role: str                  # "demand" / "supply" / "wait"
    lower: float
    upper: float
    comment: Optional[str] = None


@dataclass
class FVGZone:
    lower: float
    upper: float
    position: str              # "above" / "below" / "around"


@dataclass
class FibLevels:
    lvl_382: Optional[float] = None
    lvl_50: Optional[float] = None
    lvl_618: Optional[float] = None


@dataclass
class Scenario:
    name: str                  # "Range + Pullback", "Bullish Breakout"
    probability: float         # 0–1
    description: str           # короткий текст
    long_targets: List[Tuple[float, float]]  # [(from, to), ...]
    short_targets: List[Tuple[float, float]] # можно пустой список
    risk_comment: Optional[str] = None


@dataclass
class RiskBoard:
    overbought: str            # "low" / "medium" / "high"
    liquidity: str             # "low" / "medium" / "high"
    flush_risk: str            # "low" / "medium" / "high"
    stop_hunt_risk: str        # "low" / "medium" / "high"
    funding_oi_comment: Optional[str] = None


@dataclass
class RAsymmetry:
    long_r: float              # -0.09
    short_r: float             # -0.12


@dataclass
class LongStrengthChecklist:
    volumes_back: bool
    liquidity_above_cleared: bool
    funding_ok: bool
    structure_fixed: bool
    momentum_confirmed: bool


@dataclass
class MarketSnapshot:
    symbol: str
    timeframe: str             # "1h"
    price: float
    phase: Phase
    setup_type: SetupType
    micro_regime: MicroRegime
    bias: Bias
    dir_scores: DirectionalScores
    pump_score: float          # 0–1
    risk_score: float          # 0–1
    liquidity_level: str       # "low" / "medium" / "high"
    volatility_level: str      # "low" / "medium" / "high"
    narrative: Optional[str]
    flow: FlowSnapshot
    demand_zone: Zone
    supply_zone: Zone
    wait_zone: Optional[Zone]
    fvgs: List[FVGZone]
    fib: Optional[FibLevels]
    scenarios: List[Scenario]
    risk_board: RiskBoard
    r_asym: RAsymmetry
    long_checklist: LongStrengthChecklist
    breakout_trigger: Optional[float] = None  # уровень пробоя


class MarketDoctorReportGenerator:
    """
    Автогенератор текста отчёта по MarketSnapshot.
    
    Умеет:
    - решать, какое решение: LONG / SHORT / WAIT
    - какой уровень детализации: short / full
    - какие секции показывать, а какие скрывать
    - убирать дубликаты информации
    - унифицировать bias
    """

    def __init__(
        self,
        edge_min_strong: float = 2.0,
        edge_min_normal: float = 1.0,
        confidence_high: float = 0.65,
        confidence_low: float = 0.55,
    ):
        self.edge_min_strong = edge_min_strong
        self.edge_min_normal = edge_min_normal
        self.confidence_high = confidence_high
        self.confidence_low = confidence_low

    # ---------------- core public ----------------

    def generate(self, snap: MarketSnapshot, mode: str = "auto") -> str:
        """
        mode:
          - "auto"  → сам решает full / short
          - "full"  → всегда полная версия
          - "short" → только краткая версия
        """
        edge = snap.dir_scores.long_score - snap.dir_scores.short_score
        abs_edge = abs(edge)

        # определяем level детализации
        if mode == "short":
            detail = "short"
        elif mode == "full":
            detail = "full"
        else:
            # auto: если edge маленький и confidence средний → коротко
            if abs_edge < self.edge_min_normal and snap.dir_scores.confidence < self.confidence_high:
                detail = "short"
            else:
                detail = "full"

        decision = self._decide_action(snap, edge)
        blocks = []

        blocks.append(self._block_header(snap, decision, edge))

        if detail == "full":
            blocks.append(self._block_regime(snap))
            blocks.append(self._block_directional_scores(snap, edge))
            blocks.append(self._block_context(snap))
            blocks.append(self._block_consensus(snap))
            if snap.flow.cvd_change_pct is not None:
                blocks.append(self._block_flow(snap))
            blocks.append(self._block_smc(snap))
            if snap.fib is not None:
                blocks.append(self._block_fib(snap))
            if snap.scenarios:
                blocks.append(self._block_scenarios(snap))
            blocks.append(self._block_triggers(snap))
            blocks.append(self._block_risk_board(snap))
            blocks.append(self._block_practical_recs(snap, decision, edge))
            blocks.append(self._block_r_asym(snap))
            blocks.append(self._block_long_conditions(snap))
        else:
            # короткая версия
            blocks.append(self._block_short_core(snap, decision, edge))
            blocks.append(self._block_triggers_short(snap))
            blocks.append(self._block_tldr(snap, decision))

        # финальный TL;DR для full тоже не повредит
        if detail == "full":
            blocks.append(self._block_tldr(snap, decision))

        return "\n\n".join([b for b in blocks if b.strip()])

    # ---------------- decision logic ----------------

    def _decide_action(self, snap: MarketSnapshot, edge: float) -> str:
        """
        Возвращает одно из: "LONG", "SHORT", "WAIT"
        Логика:
        - если edge < порога и R отрицательный → WAIT
        - если edge > 0 и достаточно велик → LONG
        - если edge < 0 и достаточно велик по модулю → SHORT
        """
        abs_edge = abs(edge)
        conf = snap.dir_scores.confidence
        long_r = snap.r_asym.long_r
        short_r = snap.r_asym.short_r

        # если оба R отрицательные и edge слабый → WAIT
        if long_r <= 0 and short_r <= 0 and abs_edge < self.edge_min_normal:
            return "WAIT"

        # сильный LONG
        if edge >= self.edge_min_strong and long_r > 0 and conf >= self.confidence_high:
            return "LONG"

        # слабый LONG
        if edge >= self.edge_min_normal and long_r >= short_r:
            return "LONG"

        # сильный SHORT
        if edge <= -self.edge_min_strong and short_r > 0 and conf >= self.confidence_high:
            return "SHORT"

        # слабый SHORT
        if edge <= -self.edge_min_normal and short_r >= long_r:
            return "SHORT"

        return "WAIT"

    # ---------------- blocks ----------------

    def _block_header(self, snap: MarketSnapshot, decision: str, edge: float) -> str:
        edge_word = "отсутствует"
        if abs(edge) >= self.edge_min_strong:
            edge_word = "сильный"
        elif abs(edge) >= self.edge_min_normal:
            edge_word = "умеренный"

        # Определяем причину решения (без дубликатов)
        if decision == "WAIT":
            # Проверяем позицию цены
            in_premium = snap.price >= snap.supply_zone.lower if snap.supply_zone else False
            if in_premium:
                reason = "цена в верхней части диапазона, премиум-зоне → вход не даёт edge"
            else:
                reason = "явного преимущества ни у лонга, ни у шорта нет, цена в середине диапазона"
            action = "наблюдать за реакцией на ключевые уровни, не открывая новые позиции по текущей цене"
        elif decision == "LONG":
            reason = f"edge {edge_word} в пользу лонга, цена близка к зоне спроса"
            action = f"ждать возврата в {snap.demand_zone.lower:,.0f}–{snap.demand_zone.upper:,.0f} — там находится реальная зона спроса"
        else:  # SHORT
            reason = f"edge {edge_word} в пользу шорта, цена близка к зоне предложения"
            action = f"ждать реакции продавца в {snap.supply_zone.lower:,.0f}–{snap.supply_zone.upper:,.0f}"

        return (
            f"🏥 Market Doctor — {snap.symbol} | {snap.timeframe}\n"
            f"━━━━━━━━━━━━━━━━━━\n\n"
            f"🎯 Решение: {decision} / OBSERVE\n\n"
            f"Причина: {reason}.\n\n"
            f"Лучшее действие: {action}."
        )

    def _block_regime(self, snap: MarketSnapshot) -> str:
        phase_map = {
            Phase.ACCUMULATION: "Накопление 📦",
            Phase.EXP_UP: "Расширение вверх 🚀",
            Phase.EXP_DOWN: "Расширение вниз 🔻",
            Phase.RANGE: "Диапазон ↔️",
            Phase.DISTRIBUTION: "Распределение 📤",
        }
        micro_map = {
            MicroRegime.TREND: "Трендовый режим",
            MicroRegime.EXHAUSTION: "Режим истощения импульса",
            MicroRegime.LIQUIDITY_HUNT: "Охота за ликвидностью",
            MicroRegime.CHOP: "Флэт / пиление",
        }

        phase_txt = phase_map.get(snap.phase, "—")
        micro_txt = micro_map.get(snap.micro_regime, "—")

        # Унифицируем bias - убираем конфликты
        tactical_bias = self._map_bias(snap.bias.tactical)
        strategic_bias = self._map_bias(snap.bias.strategic)
        
        # Проверяем на конфликты и объясняем
        bias_conflict = self._check_bias_conflict(snap)
        bias_note = ""
        if bias_conflict:
            bias_note = f"\n\n⚠️ Примечание: {bias_conflict}"

        # Правильная оценка уверенности
        conf_pct = int(snap.dir_scores.confidence * 100)
        if conf_pct >= 65:
            conf_label = "высокая"
        elif conf_pct >= 55:
            conf_label = "умеренная"
        else:
            conf_label = "низкая"

        parts = [
            "🧠 Режим рынка",
            "",
            f"Фаза: {phase_txt}",
            f"Тип сетапа: {self._map_setup_type(snap.setup_type)}",
            f"Подрежим: {micro_txt}",
            f"Тактический bias: {tactical_bias}",
            f"Стратегический bias: {strategic_bias}",
        ]
        if snap.bias.structural:
            parts.append(f"Structural Bias: {snap.bias.structural}")
        if snap.bias.liquidity:
            parts.append(f"Liquidity Bias: {snap.bias.liquidity}")

        parts.append(f"Уверенность модели: {conf_pct}% ({conf_label}){bias_note}")

        return "\n".join(parts)

    def _check_bias_conflict(self, snap: MarketSnapshot) -> Optional[str]:
        """Проверяет конфликты в bias и возвращает объяснение или None."""
        # Exhaustion + выше EQH → обычно медвежий, но стратегический может быть лонговый
        if (snap.micro_regime == MicroRegime.EXHAUSTION and 
            snap.bias.structural and "выше" in snap.bias.structural.lower() and
            snap.bias.strategic == "bullish"):
            return "Exhaustion + выше EQH обычно указывает на медвежий риск, но стратегический bias лонговый — это указывает на возможный разворот после коррекции."
        return None

    def _map_setup_type(self, st: SetupType) -> str:
        if st == SetupType.RANGE:
            return "Игра в диапазоне ↔️"
        if st == SetupType.CONTINUATION:
            return "Продолжение тренда ➡️"
        if st == SetupType.REVERSAL:
            return "Разворот ⚠️"
        if st == SetupType.MEAN_REVERSION:
            return "Возврат к среднему ↩️"
        return "—"

    def _map_bias(self, b: str) -> str:
        mapping = {
            "bullish": "Бычий",
            "bearish": "Медвежий",
            "neutral": "Нейтральный",
        }
        return mapping.get(b, b)

    def _block_directional_scores(self, snap: MarketSnapshot, edge: float) -> str:
        # Обновлённая логика: слабый до 0.7, умеренный 0.7-2, сильный >2
        abs_edge = abs(edge)
        if abs_edge < 0.7:
            edge_category = "слабый"
        elif abs_edge < 2.0:
            edge_category = "умеренный"
        else:
            edge_category = "сильный"
        
        explanation = ""
        if abs(edge) < 1.0:
            explanation = "\n\nСмысл: рынок в середине диапазона. Входить здесь нерентабельно ни в одну сторону."
        elif edge > 0:
            explanation = f"\n\nСмысл: edge появляется только у лонга — но только от нижней границы диапазона ({snap.demand_zone.lower:,.0f}–{snap.demand_zone.upper:,.0f})."
        else:
            explanation = f"\n\nСмысл: edge появляется только у шорта — но только от верхней границы диапазона ({snap.supply_zone.lower:,.0f}–{snap.supply_zone.upper:,.0f})."

        return (
            "🎯 Оценка направлений\n\n"
            f"ЛОНГ: {snap.dir_scores.long_score:.1f}/10   "
            f"ШОРТ: {snap.dir_scores.short_score:.1f}/10   "
            f"Edge: {edge:+.1f} ({edge_category})"
            f"{explanation}"
        )

    def _block_context(self, snap: MarketSnapshot) -> str:
        parts = [
            "📊 Детальный контекст",
            "",
            f"Тренд: {self._context_trend_text(snap)}",
            f"Импульс: {self._context_momentum_text(snap)}",
            f"Pump Score: {snap.pump_score:.2f}",
            f"Risk Score: {snap.risk_score:.2f} → стандартный риск" if 0.3 <= snap.risk_score <= 0.7 else f"Risk Score: {snap.risk_score:.2f}",
            f"Ликвидность: {snap.liquidity_level.capitalize()}",
            f"Волатильность: {snap.volatility_level.capitalize()}",
        ]
        # Narrative только если добавляет новую информацию
        if snap.narrative and snap.narrative not in ["Рынок в нейтральном состоянии.", "Рынок показывает усталость покупателей."]:
            parts.append(f"Narrative: {snap.narrative}")
        return "\n".join(parts)

    def _context_trend_text(self, snap: MarketSnapshot) -> str:
        if snap.bias.tactical == "bullish":
            return "Бычий"
        if snap.bias.tactical == "bearish":
            return "Медвежий"
        return "Нейтральный"

    def _context_momentum_text(self, snap: MarketSnapshot) -> str:
        if snap.micro_regime == MicroRegime.EXHAUSTION:
            return "Импульс ослабевает"
        if snap.micro_regime == MicroRegime.TREND:
            return "Сильный импульс по тренду"
        if snap.micro_regime == MicroRegime.LIQUIDITY_HUNT:
            return "Импульс на сбор ликвидности"
        if snap.micro_regime == MicroRegime.CHOP:
            return "Импульс размытый, режим пилы"
        return "Импульс нейтрален"

    def _block_consensus(self, snap: MarketSnapshot) -> str:
        # Упрощённая версия без дубликатов
        return (
            "📈 Консенсус индикаторов\n\n"
            "Суммарно: сигнал ближе к нейтральному с лёгким уклоном в лонг.\n"
            "Структура рынка остаётся уязвимой для выноса стопов над локальными максимумами."
        )

    def _block_flow(self, snap: MarketSnapshot) -> str:
        cvd = snap.flow.cvd_change_pct
        comment = "CVD растёт → есть спрос, но без агрессивного импульса." if cvd and cvd > 0 else "CVD снижается → давление продавцов."
        return (
            "💰 Потоки капитала (Flow Engine)\n\n"
            f"CVD: {cvd:+.1f}%\n"
            f"{comment}"
        )

    def _block_smc(self, snap: MarketSnapshot) -> str:
        dz = snap.demand_zone
        sz = snap.supply_zone

        parts = [
            "📌 Smart Money Map (SMC)",
            "",
            f"Текущая цена: {snap.price:,.0f}",
            "Позиция: верхняя часть диапазона, ближе к зоне предложения → участок повышенного риска.",
            "",
            f"🟢 Зона спроса (лонг): {dz.lower:,.0f}–{dz.upper:,.0f}",
        ]
        if dz.comment:
            parts.append(f"{dz.comment}")
        parts.append("")
        parts.append(f"🔴 Зона предложения (шорт): {sz.lower:,.0f}–{sz.upper:,.0f}")
        if sz.comment:
            parts.append(f"{sz.comment}")

        # FVG - только ключевые (первые 2-3)
        if snap.fvgs:
            parts.append("")
            parts.append("📎 Незакрытые FVG (магниты):")
            for fvg in snap.fvgs[:3]:  # Только первые 3
                pos_txt = "ниже" if fvg.position == "below" else "выше" if fvg.position == "above" else "рядом"
                parts.append(f"• {fvg.lower:,.0f}–{fvg.upper:,.0f} ({pos_txt} текущей цены)")
        
        return "\n".join(parts)

    def _block_fib(self, snap: MarketSnapshot) -> str:
        f = snap.fib
        return (
            "📐 Фибоначчи\n\n"
            f"38.2%: {f.lvl_382:,.0f} | 50.0%: {f.lvl_50:,.0f} | 61.8%: {f.lvl_618:,.0f}\n"
            "Фибо-уровни усиливают значимость нижней части диапазона как зоны интереса покупателей."
        )

    def _block_scenarios(self, snap: MarketSnapshot) -> str:
        lines = ["📈 Сценарии (4–24ч)", ""]

        for sc in snap.scenarios:
            prob_pct = int(sc.probability * 100)
            lines.append(f"{sc.name} — {prob_pct}%")
            lines.append(f"  {sc.description}")
            if sc.long_targets:
                tgt = ", ".join([f"{lo:,.0f}→{hi:,.0f}" for lo, hi in sc.long_targets])
                lines.append(f"  Цели лонга: {tgt}")
            if sc.short_targets:
                tgt = ", ".join([f"{lo:,.0f}→{hi:,.0f}" for lo, hi in sc.short_targets])
                lines.append(f"  Цели шорта: {tgt}")
            if sc.risk_comment:
                lines.append(f"  Риск: {sc.risk_comment}")
            lines.append("")

        return "\n".join(lines).rstrip()

    def _block_triggers(self, snap: MarketSnapshot) -> str:
        dz = snap.demand_zone
        sz = snap.supply_zone
        wait_zone_text = ""
        if snap.wait_zone:
            wait_zone_text = f"\n\n🔵 WAIT:\n{snap.wait_zone.lower:,.0f}–{snap.wait_zone.upper:,.0f} = зона без edge"

        return (
            "⚙️ Decision Triggers\n\n"
            f"🟩 LONG:\n"
            f"• Возврат цены в {dz.lower:,.0f}–{dz.upper:,.0f} и признаки разворота"
            f"{f' или закрепление выше {snap.breakout_trigger:,.0f}' if snap.breakout_trigger else ''}.\n\n"
            f"🟥 SHORT:\n"
            f"• Реакция продавца в {sz.lower:,.0f}–{sz.upper:,.0f} (SFP, поглощение, падение объёмов)."
            f"{wait_zone_text}"
        )

    def _block_risk_board(self, snap: MarketSnapshot) -> str:
        rb = snap.risk_board
        return (
            "⚠️ Risk Board\n\n"
            f"Перекупленность: {rb.overbought.upper()}\n"
            f"Ликвидность: {rb.liquidity.upper()}\n"
            f"Flush-risk (резкий сброс): {rb.flush_risk.upper()}\n"
            f"Stop-hunt risk: {rb.stop_hunt_risk.upper()}\n"
            f"{rb.funding_oi_comment or ''}".strip()
        )

    def _block_practical_recs(self, snap: MarketSnapshot, decision: str, edge: float) -> str:
        dz = snap.demand_zone
        sz = snap.supply_zone
        long_size = "0.25R"
        short_size = "0.25R"

        return (
            "💡 Практические рекомендации (не финсовет)\n\n"
            f"Для лонга:\n"
            f"• Интересен только от {dz.lower:,.0f}–{dz.upper:,.0f} при подтверждении сетапа.\n"
            f"• Размер позиции: {long_size} (консервативный режим).\n\n"
            f"Для шорта:\n"
            f"• Только по реакции в {sz.lower:,.0f}–{sz.upper:,.0f}, контртренд.\n"
            f"• Размер позиции: {short_size}.\n\n"
            f"Горизонт удержания: 4–24 часа."
        )

    def _block_r_asym(self, snap: MarketSnapshot) -> str:
        ra = snap.r_asym
        # Проверяем, оба ли R близки к нулю
        both_neutral = abs(ra.long_r) < 0.2 and abs(ra.short_r) < 0.2
        if both_neutral:
            comment = "По цене прямо сейчас статистики за активный вход нет — нормальные лонги только от нижней зоны."
        else:
            comment = "По текущей цене асимметрия слабая — рынок статистически нейтрален для новых входов."
        return (
            "⚖️ R-Асимметрия\n\n"
            f"Long: {ra.long_r:+.2f}R | Short: {ra.short_r:+.2f}R\n"
            f"{comment}"
        )

    def _block_long_conditions(self, snap: MarketSnapshot) -> str:
        ch = snap.long_checklist
        items = [
            ("Объёмы вернулись", ch.volumes_back),
            ("Ликвидность сверху снята", ch.liquidity_above_cleared),
            ("Funding/OI в норме", ch.funding_ok),
            ("Структура улучшилась", ch.structure_fixed),
            ("Импульс подтвердился", ch.momentum_confirmed),
        ]
        done = sum(1 for _, v in items if v)
        total = len(items)
        lines = ["🔍 Что должно случиться, чтобы лонг стал сильным", ""]
        for name, ok in items:
            mark = "✔" if ok else "✗"
            lines.append(f"{mark} {name}")
        lines.append("")
        lines.append(f"Выполнено условий: {done}/{total} — лонг ещё требует подтверждений.")
        return "\n".join(lines)

    # ----- short mode blocks -----

    def _block_short_core(self, snap: MarketSnapshot, decision: str, edge: float) -> str:
        dz = snap.demand_zone
        sz = snap.supply_zone
        return (
            "📌 Краткое резюме\n\n"
            f"Режим: диапазон / истощение импульса.\n"
            f"Edge: {edge:+.1f} в пользу {'лонга' if edge > 0 else 'шорта' if edge < 0 else 'никого'}.\n"
            f"По текущей цене вход невыгоден.\n"
            f"Лучшие уровни: лонг {dz.lower:,.0f}–{dz.upper:,.0f}, шорт {sz.lower:,.0f}–{sz.upper:,.0f}."
        )

    def _block_triggers_short(self, snap: MarketSnapshot) -> str:
        dz = snap.demand_zone
        sz = snap.supply_zone
        return (
            "⚙️ Триггеры (коротко)\n\n"
            f"ЛОНГ: только {dz.lower:,.0f}–{dz.upper:,.0f} или выше ключевого пробоя.\n"
            f"ШОРТ: только по реакции в {sz.lower:,.0f}–{sz.upper:,.0f}.\n"
            f"Внутри диапазона между зонами — режим наблюдения."
        )

    def _block_tldr(self, snap: MarketSnapshot, decision: str) -> str:
        dz = snap.demand_zone
        sz = snap.supply_zone
        return (
            "━━━━━━━━━━━━━━━━━━\n"
            "TL;DR:\n\n"
            f"• Рынок в диапазоне, импульс выдыхается.\n"
            f"• По текущим ценам {decision}: новых позиций не открывать.\n"
            f"• Рабочие зоны: лонг {dz.lower:,.0f}–{dz.upper:,.0f}, шорт {sz.lower:,.0f}–{sz.upper:,.0f}."
        )

