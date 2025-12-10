# app/domain/market_diagnostics/report_builder.py
"""
Билдер для создания CompactReport из существующих данных Market Doctor.
"""

from typing import Dict, List, Optional, Any
from datetime import datetime, timezone
from dataclasses import asdict

from .compact_report import CompactReport, SMCLevel, TradeTrigger
from .scoring_engine import ScoringEngine, MultiTFScore, TimeframeScore, GROUP_WEIGHTS
from .analyzer import MarketDiagnostics
from .trade_planner import TradePlan
from .setup_type import SetupTypeDetector, translate_setup_type
from .momentum_intelligence import MomentumIntelligence

# Конфиг релевантности имбалансов по таймфреймам
IMBALANCE_RELEVANCE = {
    "1h": {
        "main_tfs": ["1h", "4h", "1d"],
        "show_in_report": ["1h", "4h", "1d"],
        "execution_tfs": ["15m"]
    },
    "4h": {
        "main_tfs": ["4h", "1d", "1w"],
        "show_in_report": ["4h", "1d", "1w"],
        "execution_tfs": ["1h"]
    },
    "1d": {
        "main_tfs": ["1d", "1w"],
        "show_in_report": ["1d", "1w"],
        "execution_tfs": ["4h"]
    },
    "15m": {
        "main_tfs": ["15m", "1h", "4h"],
        "show_in_report": ["15m", "1h", "4h"],
        "execution_tfs": ["5m"]
    },
    "5m": {
        "main_tfs": ["5m", "15m", "1h"],
        "show_in_report": ["5m", "15m", "1h"],
        "execution_tfs": []
    }
}


class ReportBuilder:
    """Билдер для создания компактного отчёта."""
    
    def __init__(self, custom_weights: Optional[Dict[Any, float]] = None):
        """
        Инициализация.
        
        Args:
            custom_weights: Кастомные веса групп индикаторов (если None, используются дефолтные)
        """
        self.scoring_engine = ScoringEngine(custom_weights)
        self.setup_detector = SetupTypeDetector()
        self.momentum_intel = MomentumIntelligence()
    
    def build_compact_report(
        self,
        symbol: str,
        target_tf: str,
        diagnostics: Dict[str, MarketDiagnostics],  # {timeframe: MarketDiagnostics}
        indicators: Dict[str, dict],  # {timeframe: indicators_dict}
        features: Dict[str, dict],  # {timeframe: features_dict}
        derivatives: Dict[str, dict],  # {timeframe: derivatives_dict}
        trade_plan: Optional[TradePlan] = None,
        current_price: Optional[float] = None
    ) -> CompactReport:
        """
        Построить компактный отчёт из существующих данных.
        
        Args:
            symbol: Символ
            target_tf: Целевой таймфрейм
            diagnostics: Словарь диагностик по ТФ
            indicators: Словарь индикаторов по ТФ
            features: Словарь признаков по ТФ
            derivatives: Словарь деривативов по ТФ
            trade_plan: Торговый план
            current_price: Текущая цена
        
        Returns:
            CompactReport
        """
        # Считаем scores по каждому ТФ
        per_tf_scores = {}
        for tf, diag in diagnostics.items():
            tf_indicators = indicators.get(tf, {})
            tf_features = features.get(tf, {})
            tf_derivatives = derivatives.get(tf, {})
            
            try:
                # Передаём target_tf для правильного расчёта весов
                tf_score = self.scoring_engine.score_timeframe(
                    diag, tf_indicators, tf_features, tf_derivatives, tf, target_tf=target_tf
                )
                per_tf_scores[tf] = tf_score
            except Exception as e:
                import logging
                logger = logging.getLogger(__name__)
                logger.warning(f"Failed to score timeframe {tf}: {e}")
                # Пропускаем этот ТФ
                continue
        
        # Агрегируем multi-TF (если есть несколько ТФ)
        from .scoring_engine import MultiTFScore
        
        if len(per_tf_scores) > 1:
            multi_tf_score = self.scoring_engine.aggregate_multi_tf(per_tf_scores, target_tf)
        elif len(per_tf_scores) == 1:
            # Если только один ТФ, используем его score напрямую
            single_score = list(per_tf_scores.values())[0]
            multi_tf_score = MultiTFScore(
                target_tf=target_tf,
                per_tf=per_tf_scores,
                aggregated_long=single_score.normalized_long,
                aggregated_short=single_score.normalized_short,
                confidence=0.7,  # Базовая уверенность для одного ТФ
                direction="LONG" if single_score.normalized_long > single_score.normalized_short else "SHORT"
            )
        else:
            # Если нет scores вообще, создаём дефолтный
            multi_tf_score = MultiTFScore(
                target_tf=target_tf,
                per_tf={},
                aggregated_long=5.0,
                aggregated_short=5.0,
                confidence=0.5,
                direction="NEUTRAL"
            )
        
        # Формируем per_tf словарь для отчёта
        per_tf_dict = {}
        for tf, score in per_tf_scores.items():
            raw_scores = {
                group.value: group_score.raw_score
                for group, group_score in score.group_scores.items()
            }
            
            # Пытаемся построить MomentumInsight для этого ТФ
            momentum_insight = None
            diag_for_tf = diagnostics.get(tf)
            tf_indicators = indicators.get(tf, {})
            tf_features = features.get(tf, {})
            tf_derivatives = derivatives.get(tf, {})
            if diag_for_tf is not None:
                try:
                    momentum_insight = self.momentum_intel.analyse(
                        diag_for_tf, tf_indicators, tf_features, tf_derivatives
                    )
                except Exception:
                    momentum_insight = None  # не ломаем отчёт из-за ошибок в новом модуле
            
            # Получаем pump_score и risk_score из diagnostics
            pump_score = None
            risk_score = None
            if diag_for_tf:
                pump_score = getattr(diag_for_tf, 'pump_score', None)
                risk_score = getattr(diag_for_tf, 'risk_score', None)
            
            tf_entry = {
                "weight": score.weight,
                "regime": score.regime,
                "trend": score.trend,
                "raw_scores": raw_scores,
                "net_score": score.net_score,
                "normalized_long": score.normalized_long,
                "normalized_short": score.normalized_short,
            }
            
            # Добавляем pump_score и risk_score если доступны
            if pump_score is not None:
                tf_entry["pump_score"] = pump_score
            if risk_score is not None:
                tf_entry["risk_score"] = risk_score
            
            if momentum_insight is not None:
                tf_entry["momentum_insight"] = asdict(momentum_insight)
            
            per_tf_dict[tf] = tf_entry
        
        # Получаем target_diag для дальнейшего использования
        target_diag = diagnostics.get(target_tf)
        
        # Убеждаемся что per_tf_dict не пустой (fallback на дефолтные значения)
        if not per_tf_dict and target_diag:
            phase_val = target_diag.phase.value if hasattr(target_diag.phase, 'value') else str(target_diag.phase)
            trend_val = target_diag.trend.value if hasattr(target_diag.trend, 'value') else str(target_diag.trend)
            per_tf_dict[target_tf] = {
                "weight": 1.0,
                "regime": phase_val,
                "trend": trend_val,
                "raw_scores": {},
                "net_score": 0.0,
                "normalized_long": 5.0,
                "normalized_short": 5.0
            }
        
        # SMC levels (собираем из всех ТФ для multi-TF анализа имбалансов)
        smc_data = self._extract_smc_data_multi_tf(diagnostics, target_tf, current_price)
        
        # Добавляем current_price в smc_data для рендерера
        if current_price:
            smc_data['current_price'] = current_price
        
        # Trade map
        trade_map = self._build_trade_map(trade_plan, target_diag, current_price, diagnostics, target_tf)
        
        # Определяем тип сетапа
        setup_result = self.setup_detector.detect_setup_type(
            multi_tf_score, target_diag, diagnostics, current_price
        )
        
        # TL;DR
        tl_dr = self._generate_tldr(multi_tf_score, target_diag, trade_plan, setup_result, current_price)
        
        return CompactReport(
            symbol=symbol,
            target_tf=target_tf,
            timestamp=datetime.now(timezone.utc).isoformat(),
            regime=target_diag.phase.value if target_diag and hasattr(target_diag.phase, 'value') else (str(target_diag.phase) if target_diag else "UNKNOWN"),
            direction=multi_tf_score.direction,
            score_long=multi_tf_score.aggregated_long,
            score_short=multi_tf_score.aggregated_short,
            score_scale=10,
            confidence=multi_tf_score.confidence,
            setup_type=setup_result if isinstance(setup_result, str) else (setup_result.setup_type.value if hasattr(setup_result, 'setup_type') else "UNKNOWN") if setup_result else "UNKNOWN",
            setup_description=(translate_setup_type(setup_result) if isinstance(setup_result, str) else (setup_result.description if hasattr(setup_result, 'description') else "")) if setup_result else "",
            tl_dr=tl_dr,
            per_tf=per_tf_dict,
            smc=smc_data,
            trade_map=trade_map
        )
    
    def _extract_smc_data(
        self,
        diag: Optional[MarketDiagnostics],
        current_price: Optional[float]
    ) -> dict:
        """Извлечь SMC данные из одного диагностика (legacy метод)."""
        if not diag or not diag.smc_context:
            return {
                "levels": {"support": [], "resistance": []},
                "liquidity_pools": {"above": [], "below": []},
                "imbalances": [],
                "bos": [],
                "fvgs": []
            }
        
        smc = diag.smc_context
        
        # Support/Resistance levels
        support_levels = []
        resistance_levels = []
        
        if diag.key_levels:
            for level in diag.key_levels:
                if current_price and level.price < current_price:
                    # Support
                    support_levels.append({
                        "price_low": level.price * 0.999,
                        "price_high": level.price * 1.001,
                        "strength": level.strength,
                        "tf": diag.timeframe
                    })
                elif current_price and level.price > current_price:
                    # Resistance
                    resistance_levels.append({
                        "price_low": level.price * 0.999,
                        "price_high": level.price * 1.001,
                        "strength": level.strength,
                        "tf": diag.timeframe
                    })
        
        # Сортируем по близости к цене (ближайшие первыми)
        if current_price:
            support_levels.sort(key=lambda x: abs(current_price - x["price_low"]))
            resistance_levels.sort(key=lambda x: abs(x["price_low"] - current_price))
        
        # Liquidity pools
        liquidity_above = smc.liquidity_above or []
        liquidity_below = smc.liquidity_below or []
        
        # Imbalances (FVG)
        imbalances = []
        if smc.fvgs:
            for fvg in smc.fvgs[:2]:  # Максимум 2
                imbalances.append({
                    "price_low": fvg.price_low,
                    "price_high": fvg.price_high,
                    "filled": False,  # Упрощённо
                    "tf": diag.timeframe
                })
        
        # BOS
        bos_list = []
        if smc.last_bos:
            bos_list.append({
                "direction": smc.last_bos.direction,
                "price": smc.last_bos.price,
                "tf": diag.timeframe
            })
        
        return {
            "levels": {
                "support": support_levels[:3],  # Топ 3
                "resistance": resistance_levels[:3]
            },
            "liquidity_pools": {
                "above": liquidity_above[:3],
                "below": liquidity_below[:3]
            },
            "imbalances": imbalances,
            "bos": bos_list,
            "fvgs": []
        }
    
    def _extract_smc_data_multi_tf(
        self,
        diagnostics: Dict[str, MarketDiagnostics],
        target_tf: str,
        current_price: Optional[float]
    ) -> dict:
        """Извлечь SMC данные из всех таймфреймов с учётом иерархии для имбалансов."""
        # Получаем конфиг релевантности для target_tf
        relevance_config = IMBALANCE_RELEVANCE.get(target_tf, IMBALANCE_RELEVANCE["1h"])
        show_tfs = relevance_config["show_in_report"]
        
        # Собираем данные из целевого ТФ для levels и liquidity
        target_diag = diagnostics.get(target_tf)
        if not target_diag or not target_diag.smc_context:
            return {
                "levels": {"support": [], "resistance": []},
                "liquidity_pools": {"above": [], "below": []},
                "imbalances": [],
                "bos": [],
                "fvgs": []
            }
        
        smc = target_diag.smc_context
        
        # Support/Resistance levels (только из target_tf)
        support_levels = []
        resistance_levels = []
        
        if target_diag.key_levels:
            for level in target_diag.key_levels:
                # Вычисляем рейтинг уровня
                level_rating = self._calculate_level_rating(level, target_diag, current_price)
                
                if current_price and level.price < current_price:
                    support_levels.append({
                        "price_low": level.price * 0.999,
                        "price_high": level.price * 1.001,
                        "strength": level.strength,
                        "tf": target_diag.timeframe,
                        "rating": level_rating
                    })
                elif current_price and level.price > current_price:
                    resistance_levels.append({
                        "price_low": level.price * 0.999,
                        "price_high": level.price * 1.001,
                        "strength": level.strength,
                        "tf": target_diag.timeframe,
                        "rating": level_rating
                    })
        
        # Сортируем по близости к цене
        if current_price:
            support_levels.sort(key=lambda x: abs(current_price - x["price_low"]))
            resistance_levels.sort(key=lambda x: abs(x["price_low"] - current_price))
        
        # Liquidity pools (только из target_tf)
        liquidity_above = smc.liquidity_above or []
        liquidity_below = smc.liquidity_below or []
        
        # Имбалансы: собираем из релевантных ТФ и фильтруем
        all_imbalances = []
        
        for tf in show_tfs:
            diag = diagnostics.get(tf)
            if not diag or not diag.smc_context or not diag.smc_context.fvgs:
                continue
            
            for fvg in diag.smc_context.fvgs:
                # Проверяем, что имбаланс незаполнен (упрощённо)
                # В реальности нужно проверять, пересекается ли текущая цена с FVG
                filled = False
                if current_price:
                    # Если цена внутри FVG, считаем заполненным
                    if fvg.price_low <= current_price <= fvg.price_high:
                        filled = True
                    # Если цена прошла через FVG, тоже заполнен
                    # (упрощённая логика, можно улучшить)
                
                # Фильтруем по расстоянию от цены (максимум 3-5%)
                if current_price:
                    mid_price = (fvg.price_low + fvg.price_high) / 2
                    distance_pct = abs(mid_price - current_price) / current_price
                    # Для старших ТФ (4h, 1d) разрешаем больший диапазон
                    if tf in ["4h", "1d", "1w"]:
                        max_distance = 0.05  # 5%
                    else:
                        max_distance = 0.03  # 3%
                    
                    if distance_pct > max_distance:
                        continue
                
                all_imbalances.append({
                    "price_low": fvg.price_low,
                    "price_high": fvg.price_high,
                    "filled": filled,
                    "tf": tf
                })
        
        # Сортируем имбалансы по близости к цене и берём только незаполненные
        if current_price:
            # Сначала фильтруем незаполненные
            unfilled_imbalances = [imb for imb in all_imbalances if not imb["filled"]]
            # Сортируем по расстоянию до середины имбаланса
            unfilled_imbalances.sort(
                key=lambda x: abs(current_price - (x["price_low"] + x["price_high"]) / 2)
            )
            # Берём 1-2 ближайших
            imbalances = unfilled_imbalances[:2]
        else:
            imbalances = all_imbalances[:2]
        
        # BOS (только из target_tf)
        bos_list = []
        if smc.last_bos:
            bos_list.append({
                "direction": smc.last_bos.direction,
                "price": smc.last_bos.price,
                "tf": target_diag.timeframe
            })
        
        # Premium/Discount зоны (из target_tf)
        premium_discount_info = None
        if smc.premium_zone_start is not None and smc.discount_zone_end is not None:
            premium_discount_info = {
                "premium_start": smc.premium_zone_start,
                "discount_end": smc.discount_zone_end,
                "current_position": smc.current_position or "neutral",
                "tf": target_diag.timeframe
            }
        
        # Фибоначчи и Эллиотт (из target_tf)
        fibonacci_data = None
        elliott_data = None
        
        if target_diag:
            # Фибоначчи
            import logging
            logger = logging.getLogger(__name__)
            logger.debug(f"Checking fibonacci_analysis: has_attr={hasattr(target_diag, 'fibonacci_analysis')}, value={getattr(target_diag, 'fibonacci_analysis', None)}")
            
            if target_diag.fibonacci_analysis:
                fib = target_diag.fibonacci_analysis
                fibonacci_data = {
                    "swing_high": fib.swing_high,
                    "swing_low": fib.swing_low,
                    "retracement_levels": [
                        {
                            "level": level.level,
                            "ratio": level.ratio,
                            "name": level.name
                        }
                        for level in fib.retracement_levels
                    ],
                    "extension_levels": [
                        {
                            "level": level.level,
                            "ratio": level.ratio,
                            "name": level.name
                        }
                        for level in fib.extension_levels[:3]  # Только первые 3
                    ],
                    "nearest_level": {
                        "level": fib.nearest_level.level,
                        "name": fib.nearest_level.name,
                        "type": fib.nearest_level.type
                    } if fib.nearest_level else None
                }
            
            # Эллиотт
            logger.debug(f"Checking elliott_waves: has_attr={hasattr(target_diag, 'elliott_waves')}, value={getattr(target_diag, 'elliott_waves', None)}")
            
            if target_diag.elliott_waves:
                ew = target_diag.elliott_waves
                elliott_data = {
                    "pattern_type": ew.pattern_type,
                    "current_wave": ew.current_wave,
                    "trend_direction": ew.trend_direction,
                    "confidence": ew.confidence,
                    "waves": [
                        {
                            "number": wave.wave_number,
                            "type": wave.wave_type.value,
                            "start_price": wave.start_price,
                            "end_price": wave.end_price,
                            "length_pct": wave.length_pct
                        }
                        for wave in ew.waves[-5:]  # Последние 5 волн
                    ],
                    "target_levels": ew.target_levels or []
                }
        
        result = {
            "levels": {
                "support": support_levels[:1],  # Только ближайший
                "resistance": resistance_levels[:1]  # Только ближайший
            },
            "liquidity_pools": {
                "above": liquidity_above[:3],
                "below": liquidity_below[:3]
            },
            "imbalances": imbalances,
            "bos": bos_list,
            "fvgs": [],
            "premium_discount": premium_discount_info,
            "multi_tf_levels": self._build_multi_tf_smc_map(diagnostics, target_tf, current_price),
            "fibonacci": fibonacci_data,
            "elliott_waves": elliott_data
        }
        
        # Логирование для отладки
        logger.debug(f"SMC data result: fibonacci={bool(fibonacci_data)}, elliott={bool(elliott_data)}")
        
        return result
    
    def _calculate_level_rating(
        self,
        level: any,
        diag: MarketDiagnostics,
        current_price: Optional[float]
    ) -> Dict[str, any]:
        """
        Вычислить рейтинг уровня на основе различных факторов.
        
        Returns:
            Словарь с рейтингом: {"strength_text": "сильная", "factors": ["1h", "объём", "FVG"]}
        """
        factors = []
        strength_score = level.strength if hasattr(level, 'strength') else 0.5
        
        # Фактор: таймфрейм
        tf = diag.timeframe
        if tf in ["4h", "1d", "1w"]:
            factors.append(f"{tf} (HTF)")
            strength_score += 0.2
        else:
            factors.append(tf)
        
        # Фактор: количество касаний
        touched = level.touched_times if hasattr(level, 'touched_times') else 0
        if touched >= 3:
            factors.append("множественные касания")
            strength_score += 0.15
        elif touched >= 2:
            factors.append("2+ касания")
            strength_score += 0.1
        
        # Фактор: пересечение с FVG/ликвидностью
        if diag.smc_context:
            # Проверяем пересечение с FVG
            if diag.smc_context.fvgs:
                for fvg in diag.smc_context.fvgs:
                    if abs(level.price - (fvg.price_low + fvg.price_high) / 2) < level.price * 0.01:
                        factors.append("FVG")
                        strength_score += 0.1
                        break
            
            # Проверяем пересечение с ликвидностью
            if level.price in (diag.smc_context.liquidity_above or []):
                factors.append("ликвидность")
                strength_score += 0.1
            if level.price in (diag.smc_context.liquidity_below or []):
                factors.append("ликвидность")
                strength_score += 0.1
        
        # Определяем текстовую категорию силы
        strength_score = min(1.0, strength_score)
        if strength_score >= 0.7:
            strength_text = "сильная"
        elif strength_score >= 0.5:
            strength_text = "средняя"
        else:
            strength_text = "слабая"
        
        return {
            "strength_text": strength_text,
            "factors": factors,
            "score": strength_score
        }
    
    def _build_multi_tf_smc_map(
        self,
        diagnostics: Dict[str, MarketDiagnostics],
        target_tf: str,
        current_price: Optional[float]
    ) -> Dict[str, Dict]:
        """
        Построить компактную multi-TF карту SMC.
        
        Returns:
            {tf: {"support": [...], "resistance": [...], "imbalances": [...]}}
        """
        relevance_config = IMBALANCE_RELEVANCE.get(target_tf, IMBALANCE_RELEVANCE["1h"])
        show_tfs = relevance_config["show_in_report"]
        
        multi_tf_map = {}
        
        for tf in show_tfs:
            diag = diagnostics.get(tf)
            if not diag or not diag.smc_context:
                continue
            
            tf_levels = {
                "support": [],
                "resistance": [],
                "imbalances": []
            }
            
            # Уровни поддержки/сопротивления
            if diag.key_levels and current_price:
                for level in diag.key_levels[:2]:  # Максимум 2 на ТФ
                    level_rating = self._calculate_level_rating(level, diag, current_price)
                    level_data = {
                        "price_low": level.price * 0.999,
                        "price_high": level.price * 1.001,
                        "strength": level.strength,
                        "rating": level_rating
                    }
                    
                    if level.price < current_price:
                        tf_levels["support"].append(level_data)
                    elif level.price > current_price:
                        tf_levels["resistance"].append(level_data)
            
            # Имбалансы (только незаполненные, ближайшие)
            if diag.smc_context.fvgs and current_price:
                imbalances = []
                for fvg in diag.smc_context.fvgs[:2]:  # Максимум 2
                    if fvg.price_low <= current_price <= fvg.price_high:
                        continue  # Заполнен
                    
                    mid_price = (fvg.price_low + fvg.price_high) / 2
                    distance_pct = abs(mid_price - current_price) / current_price
                    if distance_pct > 0.05:  # Слишком далеко
                        continue
                    
                    imbalances.append({
                        "price_low": fvg.price_low,
                        "price_high": fvg.price_high,
                        "filled": False
                    })
                
                tf_levels["imbalances"] = imbalances[:1]  # Только ближайший
            
            if tf_levels["support"] or tf_levels["resistance"] or tf_levels["imbalances"]:
                multi_tf_map[tf] = tf_levels
        
        return multi_tf_map
    
    def _build_trade_map(
        self,
        trade_plan: Optional[TradePlan],
        diag: Optional[MarketDiagnostics],
        current_price: Optional[float],
        diagnostics: Optional[Dict[str, MarketDiagnostics]] = None,
        target_tf: Optional[str] = None
    ) -> dict:
        """Построить торговую карту."""
        if not trade_plan:
            return {
                "bias": "NEUTRAL",
                "risk_mode": "NEUTRAL",
                "position_r": 0.5,
                "bullish_trigger": None,
                "bearish_trigger": None,
                "invalidations": [],
                "execution_imbalances": []
            }
        
        # Определяем bias
        bias = "LONG" if trade_plan.small_position_allowed and diag and diag.pump_score > 0.5 else "SHORT"
        
        # Risk mode
        if trade_plan.position_size_factor:
            if trade_plan.position_size_factor < 0.5:
                risk_mode = "CONSERVATIVE"
            elif trade_plan.position_size_factor > 1.0:
                risk_mode = "AGGRESSIVE"
            else:
                risk_mode = "BALANCED"
        else:
            risk_mode = "NEUTRAL"
        
        position_r = trade_plan.position_size_factor or 0.5
        
        # Triggers
        bullish_trigger = None
        if hasattr(trade_plan, 'add_on_breakout_level') and trade_plan.add_on_breakout_level:
            bullish_trigger = {
                "type": "break_and_hold",
                "level": trade_plan.add_on_breakout_level
            }
        
        bearish_trigger = None
        if hasattr(trade_plan, 'limit_buy_zone') and trade_plan.limit_buy_zone and current_price:
            # Если цена выше лимитной зоны, это может быть медвежий триггер
            low, high = trade_plan.limit_buy_zone
            if current_price < low:
                bearish_trigger = {
                    "type": "break",
                    "level": low
                }
        
        # Invalidations
        invalidations = []
        if hasattr(trade_plan, 'dont_dca_above') and trade_plan.dont_dca_above:
            invalidations.append({
                "side": "long",
                "level": trade_plan.dont_dca_above
            })
        if hasattr(trade_plan, 'dont_dca_below') and trade_plan.dont_dca_below:
            invalidations.append({
                "side": "short",
                "level": trade_plan.dont_dca_below
            })
        if hasattr(trade_plan, 'stop_loss') and trade_plan.stop_loss:
            invalidations.append({
                "side": "general",
                "level": trade_plan.stop_loss
            })
        
        # Имбалансы младших ТФ для execution (используем execution_tfs из конфига)
        execution_imbalances = []
        if diagnostics and target_tf:
            relevance_config = IMBALANCE_RELEVANCE.get(target_tf, IMBALANCE_RELEVANCE["1h"])
            execution_tfs = relevance_config.get("execution_tfs", [])
            
            for tf in execution_tfs:
                exec_diag = diagnostics.get(tf)
                if not exec_diag or not exec_diag.smc_context or not exec_diag.smc_context.fvgs:
                    continue
                
                # Берём ближайший незаполненный имбаланс
                for fvg in exec_diag.smc_context.fvgs:
                    if current_price:
                        # Проверяем, что имбаланс незаполнен
                        if fvg.price_low <= current_price <= fvg.price_high:
                            continue  # Заполнен
                        
                        # Фильтруем по расстоянию (до 2% для младших ТФ)
                        mid_price = (fvg.price_low + fvg.price_high) / 2
                        distance_pct = abs(mid_price - current_price) / current_price
                        if distance_pct > 0.02:  # 2%
                            continue
                    
                    # Добавляем ближайший имбаланс
                    execution_imbalances.append({
                        "tf": tf,
                        "price_low": fvg.price_low,
                        "price_high": fvg.price_high,
                        "direction": fvg.direction
                    })
                    break  # Берём только первый для каждого ТФ
        
        return {
            "bias": bias,
            "risk_mode": risk_mode,
            "position_r": position_r,
            "bullish_trigger": bullish_trigger,
            "bearish_trigger": bearish_trigger,
            "invalidations": invalidations,
            "execution_imbalances": execution_imbalances
        }
    
    def _generate_tldr(
        self,
        multi_tf_score: MultiTFScore,
        diag: Optional[MarketDiagnostics],
        trade_plan: Optional[TradePlan],
        setup_result: Optional[any] = None,
        current_price: Optional[float] = None
    ) -> str:
        """Сгенерировать улучшенный TL;DR на русском с учётом конфликтов ТФ и зон."""
        parts = []
        
        # Проверяем режим NO_TRADE / WAIT
        score_value = multi_tf_score.aggregated_long if multi_tf_score.direction == "LONG" else multi_tf_score.aggregated_short
        opposite_score = multi_tf_score.aggregated_short if multi_tf_score.direction == "LONG" else multi_tf_score.aggregated_long
        edge = abs(score_value - opposite_score)
        
        # Стратегический bias
        strategic_bias = multi_tf_score.direction
        strategic_text = "бычий" if strategic_bias == "LONG" else "медвежий"
        
        # Тактический edge
        has_tactical_edge = multi_tf_score.confidence >= 0.5 and edge > 1.5
        
        if not has_tactical_edge:
            # Режим WAIT - нет тактического edge
            parts.append("Рынок — середина диапазона.")
            parts.append("Входы здесь неэффективны.")
            
            # Ключевые уровни для ожидания
            if trade_plan:
                if trade_plan.limit_buy_zone:
                    low, high = trade_plan.limit_buy_zone
                    parts.append(f"Ждать цену {low:,.0f}–{high:,.0f}")
                elif trade_plan.add_on_breakout_level:
                    parts.append(f"или пробой выше {trade_plan.add_on_breakout_level:,.0f}")
            elif diag and diag.key_levels:
                # Используем уровни из диагностики
                support_levels = [lvl for lvl in diag.key_levels if lvl.price < (current_price or 0)]
                if support_levels:
                    sup = max(support_levels, key=lambda l: l.price)
                    parts.append(f"Ждать откат к {sup.price:,.0f}")
            
            return " ".join(parts)
        
        # Обычный режим - разделяем стратегический и тактический bias
        edge = abs(score_value - opposite_score)
        has_tactical_edge = multi_tf_score.confidence >= 0.5 and edge > 1.5
        
        # Стратегический bias
        strategic_bias = multi_tf_score.direction
        strategic_text = "бычий" if strategic_bias == "LONG" else "медвежий"
        
        # Тактический edge
        if not has_tactical_edge:
            # Нет тактического edge - режим WAIT
            parts.append(f"Стратегический bias остаётся {strategic_text},")
            parts.append("тактически вход неэффективен — нужна цена ниже.")
            
            # Ключевые уровни для ожидания
            if trade_plan:
                if trade_plan.limit_buy_zone:
                    low, high = trade_plan.limit_buy_zone
                    parts.append(f"Ждать откат в {low:,.0f}–{high:,.0f}")
                elif trade_plan.add_on_breakout_level:
                    parts.append(f"или пробой выше {trade_plan.add_on_breakout_level:,.0f}")
            elif diag and diag.key_levels:
                support_levels = [lvl for lvl in diag.key_levels if lvl.price < (current_price or 0)]
                if support_levels:
                    sup = max(support_levels, key=lambda l: l.price)
                    parts.append(f"Ждать откат к {sup.price:,.0f}")
            
            return " ".join(parts) + "."
        
        # Есть тактический edge
        # Тип сетапа (если определён)
        if setup_result:
            if isinstance(setup_result, str):
                if setup_result != "UNKNOWN":
                    setup_desc = translate_setup_type(setup_result)
                    parts.append(f"Сетап: {setup_desc}.")
            elif hasattr(setup_result, 'setup_type'):
                if setup_result.setup_type.value != "UNKNOWN":
                    parts.append(f"Сетап: {setup_result.description}.")
        
        # Направление с силой
        direction_strength = ""
        if multi_tf_score.direction == "LONG":
            if multi_tf_score.aggregated_long >= 8:
                direction_strength = "сильный"
            elif multi_tf_score.aggregated_long >= 6:
                direction_strength = "умеренный"
            else:
                direction_strength = "слабый"
            parts.append(f"{direction_strength} бычий глобальный bias")
        else:
            if multi_tf_score.aggregated_short >= 8:
                direction_strength = "сильный"
            elif multi_tf_score.aggregated_short >= 6:
                direction_strength = "умеренный"
            else:
                direction_strength = "слабый"
            parts.append(f"{direction_strength} медвежий глобальный bias")
        
        # Режим с контекстом
        if diag:
            regime_map = {
                "ACCUMULATION": "накопление",
                "DISTRIBUTION": "распределение",
                "EXPANSION_UP": "расширение вверх",
                "EXPANSION_DOWN": "расширение вниз",
                "SHAKEOUT": "встряска"
            }
            phase_val = diag.phase.value if hasattr(diag.phase, 'value') else str(diag.phase)
            regime_text = regime_map.get(phase_val, phase_val.lower())
            parts.append(f"рынок в фазе {regime_text}")
        
        # Ключевой уровень
        if trade_plan:
            if trade_plan.limit_buy_zone:
                low, high = trade_plan.limit_buy_zone
                parts.append(f"зона накопления: {low:,.0f}–{high:,.0f}")
            elif trade_plan.add_on_breakout_level:
                parts.append(f"ключевой уровень пробоя: {trade_plan.add_on_breakout_level:,.0f}")
        
        # Рекомендация
        if multi_tf_score.direction == "LONG" and multi_tf_score.aggregated_long >= 7:
            parts.append("рекомендуется рассмотреть лонг-позицию")
        elif multi_tf_score.direction == "SHORT" and multi_tf_score.aggregated_short >= 7:
            parts.append("рекомендуется рассмотреть шорт-позицию")
        else:
            parts.append("режим: наблюдение")
        
        return " ".join(parts) + "."

