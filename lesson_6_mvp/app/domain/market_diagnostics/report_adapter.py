"""
Адаптер для преобразования CompactReport в MarketSnapshot для нового генератора отчётов.
"""

from typing import Optional, List, Tuple
from .compact_report import CompactReport
from .report_generator_v2 import (
    MarketSnapshot, Phase, SetupType, MicroRegime, Bias, DirectionalScores,
    FlowSnapshot, Zone, FVGZone, FibLevels, Scenario, RiskBoard, RAsymmetry,
    LongStrengthChecklist
)
from .flow_engine import FlowEngine
from .r_asymmetry import RAsymmetryCalculator
from .conditions_shift import ConditionsShift


class ReportAdapter:
    """Адаптер для преобразования CompactReport в MarketSnapshot."""
    
    def __init__(self):
        self.flow_engine = FlowEngine()
        self.r_asymmetry_calc = RAsymmetryCalculator()
        self.conditions_shift = ConditionsShift()
    
    def adapt(self, report: CompactReport) -> MarketSnapshot:
        """Преобразовать CompactReport в MarketSnapshot."""
        
        # Phase - получаем из regime (в CompactReport phase хранится в report.regime)
        phase_str = report.regime if report.regime else 'RANGE'
        phase = self._map_phase(phase_str)
        
        # SetupType
        setup_type = self._map_setup_type(report.setup_type)
        
        # MicroRegime
        micro_regime = self._map_micro_regime(report.regime)
        
        # Bias
        bias = self._extract_bias(report)
        
        # DirectionalScores
        dir_scores = DirectionalScores(
            long_score=report.score_long,
            short_score=report.score_short,
            confidence=report.confidence
        )
        
        # FlowSnapshot
        flow = self._extract_flow(report)
        
        # Zones
        demand_zone, supply_zone, wait_zone = self._extract_zones(report)
        
        # FVG
        fvgs = self._extract_fvgs(report)
        
        # FibLevels
        fib = self._extract_fib(report)
        
        # Scenarios
        scenarios = self._extract_scenarios(report)
        
        # RiskBoard
        risk_board = self._extract_risk_board(report)
        
        # RAsymmetry
        r_asym = self._extract_r_asymmetry(report)
        
        # LongStrengthChecklist
        long_checklist = self._extract_long_checklist(report)
        
        # Breakout trigger
        breakout_trigger = self._extract_breakout_trigger(report)
        
        # Target TF data
        target_tf_data = report.per_tf.get(report.target_tf, {})
        pump_score = target_tf_data.get('pump_score', 0.5)
        risk_score = target_tf_data.get('risk_score', 0.5)
        
        # Liquidity and volatility
        liquidity_level = self._extract_liquidity_level(report, target_tf_data)
        volatility_level = self._extract_volatility_level(report, target_tf_data)
        
        # Narrative
        narrative = self._extract_narrative(report, target_tf_data)
        
        return MarketSnapshot(
            symbol=report.symbol,
            timeframe=report.target_tf,
            price=report.smc.get('current_price', 0),
            phase=phase,
            setup_type=setup_type,
            micro_regime=micro_regime,
            bias=bias,
            dir_scores=dir_scores,
            pump_score=pump_score,
            risk_score=risk_score,
            liquidity_level=liquidity_level,
            volatility_level=volatility_level,
            narrative=narrative,
            flow=flow,
            demand_zone=demand_zone,
            supply_zone=supply_zone,
            wait_zone=wait_zone,
            fvgs=fvgs,
            fib=fib,
            scenarios=scenarios,
            risk_board=risk_board,
            r_asym=r_asym,
            long_checklist=long_checklist,
            breakout_trigger=breakout_trigger
        )
    
    def _map_phase(self, phase: str) -> Phase:
        """Преобразовать фазу из CompactReport в Phase enum."""
        if not phase:
            return Phase.RANGE
        
        phase_map = {
            "ACCUMULATION": Phase.ACCUMULATION,
            "EXPANSION_UP": Phase.EXP_UP,
            "EXPANSION_DOWN": Phase.EXP_DOWN,
            "RANGE": Phase.RANGE,
            "DISTRIBUTION": Phase.DISTRIBUTION,
            # Альтернативные названия
            "EXP_UP": Phase.EXP_UP,
            "EXP_DOWN": Phase.EXP_DOWN,
        }
        return phase_map.get(phase.upper(), Phase.RANGE)
    
    def _map_setup_type(self, setup_type: Optional[str]) -> SetupType:
        """Преобразовать тип сетапа."""
        if not setup_type:
            return SetupType.RANGE
        
        setup_map = {
            "RANGE": SetupType.RANGE,
            "CONTINUATION": SetupType.CONTINUATION,
            "REVERSAL": SetupType.REVERSAL,
            "MEAN_REVERSION": SetupType.MEAN_REVERSION,
        }
        return setup_map.get(setup_type.upper(), SetupType.RANGE)
    
    def _map_micro_regime(self, regime: str) -> MicroRegime:
        """Преобразовать режим в MicroRegime."""
        regime_map = {
            "TREND": MicroRegime.TREND,
            "EXHAUSTION": MicroRegime.EXHAUSTION,
            "LIQUIDITY_HUNT": MicroRegime.LIQUIDITY_HUNT,
            "CHOP": MicroRegime.CHOP,
        }
        return regime_map.get(regime.upper(), MicroRegime.CHOP)
    
    def _extract_bias(self, report: CompactReport) -> Bias:
        """Извлечь bias из отчёта."""
        target_tf_data = report.per_tf.get(report.target_tf, {})
        raw_scores = target_tf_data.get('raw_scores', {})
        
        # Тактический bias
        tactical_score = raw_scores.get('trend', 0) + raw_scores.get('momentum', 0)
        if tactical_score > 0.3:
            tactical = "bullish"
        elif tactical_score < -0.3:
            tactical = "bearish"
        else:
            tactical = "neutral"
        
        # Стратегический bias
        strategic_score = report.score_long - report.score_short
        if strategic_score > 0.5:
            strategic = "bullish"
        elif strategic_score < -0.5:
            strategic = "bearish"
        else:
            strategic = "neutral"
        
        # Structural bias - из SMC данных
        structural_text = None
        smc = report.smc
        multi_tf_levels = smc.get('multi_tf_levels', {})
        current_price = smc.get('current_price', 0)
        
        # Проверяем дневной EQH/EQL
        if '1d' in multi_tf_levels:
            daily_levels = multi_tf_levels['1d']
            resistance = daily_levels.get('resistance', [])
            support = daily_levels.get('support', [])
            
            if resistance and current_price > 0:
                eqh = resistance[0].get('price_low', 0) if resistance else 0
                if eqh > 0 and current_price > eqh:
                    structural_text = f"Выше дневного EQH ({eqh:.0f}), риск выноса стопов"
            elif support and current_price > 0:
                eql = support[0].get('price_low', 0) if support else 0
                if eql > 0 and current_price < eql:
                    structural_text = f"Ниже дневного EQL ({eql:.0f}), поддержка"
        
        # Liquidity bias
        liquidity_text = None
        liquidity_pools = smc.get('liquidity_pools', {})
        liquidity_above = liquidity_pools.get('above', [])
        if liquidity_above:
            liquidity_text = "Накопление ликвидности над локальными хайями"
        else:
            liquidity_text = "Нейтральный"
        
        return Bias(
            tactical=tactical,
            strategic=strategic,
            structural=structural_text,
            liquidity=liquidity_text
        )
    
    def _extract_flow(self, report: CompactReport) -> FlowSnapshot:
        """Извлечь данные о потоках капитала."""
        # TODO: интегрировать реальные данные из Flow Engine
        return FlowSnapshot(
            cvd_change_pct=None,
            funding=None,
            oi_change_pct=None,
            comment=None
        )
    
    def _extract_zones(self, report: CompactReport) -> Tuple[Zone, Zone, Optional[Zone]]:
        """Извлечь зоны спроса, предложения и ожидания."""
        smc = report.smc
        levels = smc.get('levels', {})
        current_price = smc.get('current_price', 0)
        
        # Пытаемся использовать данные из zones, если они есть в smc
        zones_data = smc.get('zones', {})
        if zones_data:
            long_zone_data = zones_data.get('long_zone', {})
            short_zone_data = zones_data.get('short_zone', {})
            
            if long_zone_data and short_zone_data:
                demand_lower = long_zone_data.get('start', current_price * 0.99)
                demand_upper = long_zone_data.get('end', demand_lower * 1.01)
                supply_lower = short_zone_data.get('start', current_price * 1.01)
                supply_upper = short_zone_data.get('end', supply_lower * 1.01)
            else:
                # Fallback на levels
                support_levels = levels.get('support', [])
                demand_lower = support_levels[0].get('price_low', current_price * 0.99) if support_levels else current_price * 0.99
                demand_upper = support_levels[0].get('price_high', demand_lower * 1.01) if support_levels else demand_lower * 1.01
                
                resistance_levels = levels.get('resistance', [])
                supply_lower = resistance_levels[0].get('price_low', current_price * 1.01) if resistance_levels else current_price * 1.01
                supply_upper = resistance_levels[0].get('price_high', supply_lower * 1.01) if resistance_levels else supply_lower * 1.01
        else:
            # Используем levels напрямую
            support_levels = levels.get('support', [])
            demand_lower = support_levels[0].get('price_low', current_price * 0.99) if support_levels else current_price * 0.99
            demand_upper = support_levels[0].get('price_high', demand_lower * 1.01) if support_levels else demand_lower * 1.01
            
            resistance_levels = levels.get('resistance', [])
            supply_lower = resistance_levels[0].get('price_low', current_price * 1.01) if resistance_levels else current_price * 1.01
            supply_upper = resistance_levels[0].get('price_high', supply_lower * 1.01) if resistance_levels else supply_lower * 1.01
        
        demand_zone = Zone(
            name="Основная зона спроса",
            role="demand",
            lower=demand_lower,
            upper=demand_upper,
            comment="Discount-зона + FVG + многократные касания."
        )
        
        supply_zone = Zone(
            name="Зона предложения",
            role="supply",
            lower=supply_lower,
            upper=supply_upper,
            comment="Премиум + локальные EQH, шорт только по реакции."
        )
        
        # Зона ожидания (между спросом и предложением)
        wait_zone = None
        if demand_upper < supply_lower:
            wait_zone = Zone(
                name="Зона ожидания",
                role="wait",
                lower=demand_upper,
                upper=supply_lower,
                comment="Зона без edge"
            )
        
        return demand_zone, supply_zone, wait_zone
    
    def _extract_fvgs(self, report: CompactReport) -> List[FVGZone]:
        """Извлечь FVG зоны."""
        smc = report.smc
        imbalances = smc.get('imbalances', [])
        current_price = smc.get('current_price', 0)
        
        fvgs = []
        for imb in imbalances[:3]:  # Только первые 3
            price_low = imb.get('price_low', 0)
            price_high = imb.get('price_high', 0)
            
            if price_low > 0 and price_high > 0:
                if current_price < price_low:
                    position = "above"
                elif current_price > price_high:
                    position = "below"
                else:
                    position = "around"
                
                fvgs.append(FVGZone(
                    lower=price_low,
                    upper=price_high,
                    position=position
                ))
        
        return fvgs
    
    def _extract_fib(self, report: CompactReport) -> Optional[FibLevels]:
        """Извлечь уровни Фибоначчи."""
        smc = report.smc
        fib_data = smc.get('fibonacci')
        
        if not fib_data:
            return None
        
        retracement_levels = fib_data.get('retracement_levels', [])
        
        lvl_382 = None
        lvl_50 = None
        lvl_618 = None
        
        for level in retracement_levels:
            ratio = level.get('ratio', 0)
            price = level.get('level', 0)
            
            if abs(ratio - 0.382) < 0.01:
                lvl_382 = price
            elif abs(ratio - 0.5) < 0.01:
                lvl_50 = price
            elif abs(ratio - 0.618) < 0.01:
                lvl_618 = price
        
        if lvl_382 or lvl_50 or lvl_618:
            return FibLevels(
                lvl_382=lvl_382,
                lvl_50=lvl_50,
                lvl_618=lvl_618
            )
        
        return None
    
    def _extract_scenarios(self, report: CompactReport) -> List[Scenario]:
        """Извлечь сценарии."""
        scenarios = []
        
        # Проверяем наличие сценариев в разных местах
        # 1. В атрибуте scenarios (если есть)
        if hasattr(report, 'scenarios') and report.scenarios:
            for i, sc in enumerate(report.scenarios[:2]):  # Максимум 2 сценария
                if isinstance(sc, dict):
                    name = sc.get('name', f'Сценарий {i+1}')
                    probability = sc.get('probability', sc.get('weight', 0.5))
                    description = sc.get('description', sc.get('idea', ''))
                    
                    # Цели
                    long_targets = []
                    short_targets = []
                    
                    targets = sc.get('targets', {})
                    if targets:
                        long_tgt = targets.get('long', [])
                        short_tgt = targets.get('short', [])
                        
                        for tgt in long_tgt:
                            if isinstance(tgt, (list, tuple)) and len(tgt) >= 2:
                                long_targets.append((float(tgt[0]), float(tgt[1])))
                        
                        for tgt in short_tgt:
                            if isinstance(tgt, (list, tuple)) and len(tgt) >= 2:
                                short_targets.append((float(tgt[0]), float(tgt[1])))
                    
                    risk_comment = sc.get('risk', sc.get('risk_label', 'Средний риск'))
                    
                    scenarios.append(Scenario(
                        name=name,
                        probability=probability,
                        description=description,
                        long_targets=long_targets,
                        short_targets=short_targets,
                        risk_comment=risk_comment
                    ))
        
        # 2. Если сценариев нет, создаём дефолтный на основе зон
        if not scenarios:
            demand_zone, supply_zone, _ = self._extract_zones(report)
            
            # Основной сценарий: Range + Pullback
            scenarios.append(Scenario(
                name="Range + Pullback",
                probability=0.65,
                description=f"Диапазон {demand_zone.lower:,.0f}–{supply_zone.upper:,.0f}, игра от границ.",
                long_targets=[(demand_zone.lower, supply_zone.upper)],
                short_targets=[],
                risk_comment="Средний риск в диапазоне."
            ))
        
        return scenarios
    
    def _extract_risk_board(self, report: CompactReport) -> RiskBoard:
        """Извлечь данные Risk Board."""
        target_tf_data = report.per_tf.get(report.target_tf, {})
        raw_scores = target_tf_data.get('raw_scores', {})
        
        # Overbought
        rsi = raw_scores.get('rsi', 50)
        if rsi > 70:
            overbought = "high"
        elif rsi < 30:
            overbought = "low"
        else:
            overbought = "medium"
        
        # Liquidity
        liquidity_level = self._extract_liquidity_level(report, target_tf_data)
        liquidity = liquidity_level
        
        # Flush risk
        flush_risk = "low"  # TODO: вычислить из данных
        
        # Stop hunt risk
        stop_hunt_risk = "medium" if report.regime == "EXHAUSTION" else "low"
        
        # Funding/OI comment
        funding_oi_comment = "Funding/OI нейтральны — импульс не подтверждён деривативами."
        
        return RiskBoard(
            overbought=overbought,
            liquidity=liquidity,
            flush_risk=flush_risk,
            stop_hunt_risk=stop_hunt_risk,
            funding_oi_comment=funding_oi_comment
        )
    
    def _extract_r_asymmetry(self, report: CompactReport) -> RAsymmetry:
        """Извлечь R-асимметрию."""
        try:
            smc = report.smc
            current_price = smc.get('current_price', 0)
            levels = smc.get('levels', {})
            
            # Получаем зоны
            support_levels = levels.get('support', [])
            resistance_levels = levels.get('resistance', [])
            
            if support_levels and resistance_levels:
                # Рассчитываем стопы и цели
                long_stop = support_levels[0].get('price_low', 0) * 0.995
                long_target = resistance_levels[0].get('price_low', 0)
                short_stop = resistance_levels[0].get('price_high', 0) * 1.005
                short_target = support_levels[0].get('price_high', 0)
                
                # ATR из volatility (приблизительно)
                target_tf_data = report.per_tf.get(report.target_tf, {})
                raw_scores = target_tf_data.get('raw_scores', {})
                volatility = abs(raw_scores.get('volatility', 0))
                atr = current_price * volatility * 0.01 if volatility > 0 else current_price * 0.02
                
                # Вычисляем R-асимметрию
                r_asymmetry = self.r_asymmetry_calc.calculate_full_r_asymmetry(
                    current_price=current_price,
                    long_stop=long_stop,
                    long_target=long_target,
                    short_stop=short_stop,
                    short_target=short_target,
                    atr=atr,
                    long_win_prob=0.6 if report.direction == "LONG" else 0.4,
                    short_win_prob=0.6 if report.direction == "SHORT" else 0.4
                )
                
                if r_asymmetry:
                    return RAsymmetry(
                        long_r=getattr(r_asymmetry, 'long_r', 0) or 0,
                        short_r=getattr(r_asymmetry, 'short_r', 0) or 0
                    )
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.warning(f"Failed to extract R-asymmetry: {e}")
        
        return RAsymmetry(
            long_r=-0.09,
            short_r=-0.12
        )
    
    def _extract_long_checklist(self, report: CompactReport) -> LongStrengthChecklist:
        """Извлечь чеклист для усиления лонга."""
        try:
            target_tf_data = report.per_tf.get(report.target_tf, {})
            raw_scores = target_tf_data.get('raw_scores', {})
            
            # Проверяем ликвидность
            smc = report.smc
            liquidity_pools = smc.get('liquidity_pools', {})
            liquidity_above = liquidity_pools.get('above', [])
            liquidity_above_cleared = len(liquidity_above) == 0
            
            # Проверяем структуру
            structure_score = raw_scores.get('structure', 0)
            structure_fixed = structure_score > 0.3
            
            # Проверяем импульс - учитываем micro_regime
            # Если режим CHOP (пила), то импульс не подтверждён
            momentum_score = raw_scores.get('momentum', 0)
            micro_regime = self._map_micro_regime(report.regime)
            # Если режим CHOP, импульс не подтверждён независимо от momentum_score
            if micro_regime == MicroRegime.CHOP:
                momentum_confirmed = False
            else:
                momentum_confirmed = momentum_score > 0.3
            
            # Для объёмов и funding используем упрощённую логику
            # (полные данные будут вычисляться в report_nlg.py)
            volumes_back = False  # Будет вычислено в report_nlg.py
            funding_ok = True  # Будет вычислено в report_nlg.py
            
            return LongStrengthChecklist(
                volumes_back=volumes_back,
                liquidity_above_cleared=liquidity_above_cleared,
                funding_ok=funding_ok,
                structure_fixed=structure_fixed,
                momentum_confirmed=momentum_confirmed
            )
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.warning(f"Failed to extract long checklist: {e}")
        
        return LongStrengthChecklist(
            volumes_back=False,
            liquidity_above_cleared=False,
            funding_ok=True,
            structure_fixed=False,
            momentum_confirmed=False
        )
    
    def _extract_breakout_trigger(self, report: CompactReport) -> Optional[float]:
        """Извлечь уровень пробоя."""
        smc = report.smc
        levels = smc.get('levels', {})
        resistance_levels = levels.get('resistance', [])
        
        if resistance_levels:
            # Берём самый верхний уровень сопротивления
            highest = max(resistance_levels, key=lambda x: x.get('price_high', 0))
            return highest.get('price_high', None)
        
        return None
    
    def _extract_liquidity_level(self, report: CompactReport, target_tf_data: dict) -> str:
        """Извлечь уровень ликвидности."""
        risk_score = target_tf_data.get('risk_score', 0.5)
        
        # Инвертируем risk_score для ликвидности
        liquidity_score = 1 - risk_score
        
        if liquidity_score > 0.7:
            return "high"
        elif liquidity_score < 0.3:
            return "low"
        else:
            return "medium"
    
    def _extract_volatility_level(self, report: CompactReport, target_tf_data: dict) -> str:
        """Извлечь уровень волатильности."""
        raw_scores = target_tf_data.get('raw_scores', {})
        volatility = abs(raw_scores.get('volatility', 0))
        
        if volatility > 0.7:
            return "high"
        elif volatility < 0.3:
            return "low"
        else:
            return "medium"
    
    def _extract_narrative(self, report: CompactReport, target_tf_data: dict) -> Optional[str]:
        """Извлечь narrative."""
        # TODO: интегрировать реальные данные из NarrativeEngine
        return "Рынок в нейтральном состоянии."
    
    def _get_ohlcv_data(self, report: CompactReport) -> Tuple[Optional[List], Optional[List]]:
        """Получить OHLCV данные для расчёта индикаторов."""
        try:
            # Пробуем получить данные из контекста, если он доступен
            # Если нет - возвращаем None (данные будут вычисляться в report_nlg.py)
            return None, None
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.warning(f"Failed to get OHLCV data: {e}")
        
        return None, None
    
    def _get_funding_data(self, report: CompactReport) -> Optional[float]:
        """Получить funding rate."""
        try:
            # Пробуем получить funding из контекста, если он доступен
            # Если нет - возвращаем None (данные будут вычисляться в report_nlg.py)
            return None
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.warning(f"Failed to get funding data: {e}")
        
        return None

