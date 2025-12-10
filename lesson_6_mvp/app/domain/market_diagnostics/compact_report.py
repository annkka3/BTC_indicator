# app/domain/market_diagnostics/compact_report.py
"""
Компактная структура отчёта Market Doctor в новом формате.
"""

from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, asdict, field
from datetime import datetime

from .scoring_engine import MultiTFScore, TimeframeScore
from .analyzer import MarketDiagnostics
from .setup_type import SetupType, SetupClassification
# Импорт NLG модулей перенесен в метод _render_ru_nlg для избежания циклических зависимостей


@dataclass
class SMCLevel:
    """Уровень SMC."""
    price_low: float
    price_high: float
    strength: float
    tf: str


@dataclass
class TradeTrigger:
    """Триггер для входа."""
    type: str  # "break", "break_and_hold", "rejection"
    level: float
    side: str  # "long" or "short"


@dataclass
class CompactReport:
    """Компактный отчёт Market Doctor."""
    symbol: str
    target_tf: str
    timestamp: str
    
    # Overall
    regime: str
    direction: str  # "LONG" or "SHORT"
    score_long: float
    score_short: float
    confidence: float
    tl_dr: str
    
    # Optional fields (with defaults)
    setup_type: Optional[str] = None  # Тип сетапа (TREND_CONTINUATION, REVERSAL, etc.)
    setup_description: Optional[str] = None  # Описание сетапа на русском
    
    # Per timeframe scores
    per_tf: Dict[str, Dict] = field(default_factory=dict)  # {timeframe: {weight, regime, trend, raw_scores, net_score, normalized_long, normalized_short}}
    
    # SMC levels
    smc: Dict = field(default_factory=dict)  # {levels: {support: [], resistance: []}, liquidity_pools: {}, imbalances: [], bos: [], fvgs: []}
    
    # Trade map
    trade_map: Dict = field(default_factory=dict)  # {bias, risk_mode, position_r, bullish_trigger, bearish_trigger, invalidations}
    
    # Default values (must be last)
    score_scale: int = 10
    brief_mode: bool = False  # Если True, используется краткий формат отчёта
    
    def to_dict(self) -> dict:
        """Конвертировать в словарь для JSON."""
        return asdict(self)


class CompactReportRenderer:
    """Рендерер компактного отчёта."""
    
    def __init__(self, language: str = "ru"):
        """
        Инициализация.
        
        Args:
            language: Язык отчёта ("ru" или "en")
        """
        self.language = language
    
    def render(self, report: CompactReport, use_nlg: bool = True, use_v2: bool = False) -> str:
        """
        Рендерить компактный отчёт.
        
        Args:
            report: CompactReport
            use_nlg: Использовать NLG для single-TF отчетов (новый формат)
            use_v2: Использовать новый генератор v2 (без дубликатов, унифицированный bias)
        
        Returns:
            Текстовый отчёт
        """
        if self.language == "ru":
            import logging
            logger = logging.getLogger(__name__)
            logger.info(f"render() called: use_v2={use_v2}, use_nlg={use_nlg}, per_tf_count={len(report.per_tf)}, per_tf_keys={list(report.per_tf.keys())}")
            
            # Для single-TF отчетов используем новый генератор v2, если включен
            if use_v2 and len(report.per_tf) == 1:
                try:
                    logger.info(f"Attempting V2 generator for single-TF report, symbol={report.symbol}, tf={report.target_tf}")
                    result = self._render_ru_v2(report)
                    logger.info(f"V2 rendering successful, result length: {len(result)}, first_100_chars: {result[:100]}")
                    # Проверяем, что это действительно v2 формат
                    if "🏥 Market Doctor" in result and "🎯 Решение:" in result:
                        logger.info("✓ V2 format confirmed - using V2 generator result")
                        return result
                    else:
                        logger.warning(f"⚠ V2 format check failed! Report starts with: {result[:200]}")
                        logger.warning("V2 generator returned unexpected format, but using it anyway")
                        return result
                except Exception as e:
                    logger.error(f"V2 rendering failed: {e}", exc_info=True)
                    logger.warning("Falling back to NLG format due to V2 error")
                    # Fallback на NLG формат
                    use_v2 = False
            elif use_v2 and len(report.per_tf) != 1:
                logger.warning(f"V2 generator skipped: per_tf_count={len(report.per_tf)} (not single-TF)")
            elif not use_v2:
                logger.info(f"V2 generator disabled: use_v2={use_v2}")
            
            # Для single-TF отчетов ВСЕГДА используем новый NLG формат
            if len(report.per_tf) == 1:
                try:
                    import logging
                    logger = logging.getLogger(__name__)
                    logger.info(f"Using NLG format for single-TF report, per_tf keys: {list(report.per_tf.keys())}, per_tf_count={len(report.per_tf)}")
                    result = self._render_ru_nlg(report)
                    logger.info(f"NLG rendering successful, result length: {len(result)}")
                    return result
                except Exception as e:
                    import logging
                    logger = logging.getLogger(__name__)
                    logger.error(f"NLG rendering failed: {e}", exc_info=True)
                    logger.error(f"Report structure: symbol={report.symbol}, target_tf={report.target_tf}, per_tf_keys={list(report.per_tf.keys())}")
                    # Fallback на старый формат только в случае ошибки
                    logger.warning("Falling back to old format due to NLG error")
                    # НЕ используем старый _render_ru, так как он устарел
                    # Вместо этого пробуем v2 генератор ещё раз или возвращаем ошибку
                    logger.error("CRITICAL: All report generators failed! This should not happen.")
                    raise RuntimeError(f"Failed to generate report: NLG failed, V2 already tried. Original error: {e}")
            else:
                # Multi-TF отчёты пока используем старый формат
                import logging
                logger = logging.getLogger(__name__)
                logger.debug(f"Using old format for multi-TF report, per_tf_count={len(report.per_tf)}")
                return self._render_ru(report)
        else:
            return self._render_en(report)
    
    def _render_ru_nlg(self, report: CompactReport) -> str:
        """
        Рендерить отчёт используя NLG (новый формат).
        
        Args:
            report: CompactReport для рендеринга
        
        Returns:
            Отформатированная строка отчёта
        """
        # Импортируем logging в начале метода
        import logging
        logger = logging.getLogger(__name__)
        
        try:
            # Импортируем здесь, чтобы избежать циклических зависимостей
            from .report_nlg import ReportNLG, ReportContext, PricePosition
        except ImportError as e:
            logger.error(f"Failed to import NLG modules: {e}")
            raise
        
        # Определяем price_position
        try:
            price_position = self._determine_price_position(report)
        except Exception as e:
            logger.warning(f"Failed to determine price_position: {e}")
            price_position = PricePosition.MIDDLE
        
        # Определяем momentum_grade
        try:
            momentum_grade = self._determine_momentum_grade(report)
        except Exception as e:
            logger.warning(f"Failed to determine momentum_grade: {e}")
            momentum_grade = "NEUTRAL"
        
        # Строим зоны
        try:
            zones = self._build_price_zones(report)
            if not zones:
                logger.warning("_build_price_zones returned empty dict, creating default zones")
                # Создаём дефолтные зоны из smc данных
                current_price = report.smc.get('current_price', 0)
                premium_discount = report.smc.get('premium_discount', {})
                discount_end = premium_discount.get('discount_end', current_price * 0.99) if premium_discount else current_price * 0.99
                premium_start = premium_discount.get('premium_start', current_price * 1.01) if premium_discount else current_price * 1.01
                zones = {
                    "long_zone": {"start": discount_end * 0.99, "end": discount_end * 1.01},
                    "short_zone": {"start": premium_start * 0.99, "end": premium_start * 1.01},
                    "breakout_trigger": premium_start * 1.02
                }
        except Exception as e:
            logger.error(f"Failed to build price zones: {e}", exc_info=True)
            # Создаём дефолтные зоны
            current_price = report.smc.get('current_price', 0)
            zones = {
                "long_zone": {"start": current_price * 0.99, "end": current_price * 0.995},
                "short_zone": {"start": current_price * 1.005, "end": current_price * 1.01},
                "breakout_trigger": current_price * 1.02
            }
        
        # Создаем MultiTFScore из report (упрощенная версия)
        # Для NLG нам не нужен полный MultiTFScore, создаем минимальный объект
        # Используем существующий multi_tf_score если он есть, иначе создаем упрощенный
        from .scoring_engine import TimeframeScore, IndicatorGroup, GroupScore, MultiTFScore
        
        try:
            # Создаем упрощенный TimeframeScore для каждого TF
            per_tf_dict = {}
            for tf, tf_data in report.per_tf.items():
                # Создаем минимальный GroupScore для raw_scores
                group_scores = {}
                raw_scores = tf_data.get('raw_scores', {})
                for group_name, score in raw_scores.items():
                    try:
                        group = IndicatorGroup(group_name)
                        group_scores[group] = GroupScore(
                            group=group,
                            raw_score=score,
                            signals={},
                            summary=""
                        )
                    except ValueError:
                        # Пропускаем неизвестные группы
                        continue
                
                per_tf_dict[tf] = TimeframeScore(
                    timeframe=tf,
                    weight=1.0,  # Дефолтный вес
                    regime=report.regime,
                    trend=tf_data.get('trend', 'NEUTRAL'),
                    group_scores=group_scores,
                    net_score=(tf_data.get('normalized_long', 0) - tf_data.get('normalized_short', 0)) / 2.0,  # Примерный net_score
                    normalized_long=tf_data.get('normalized_long', 0),
                    normalized_short=tf_data.get('normalized_short', 0)
                )
            
            multi_tf_score = MultiTFScore(
                direction=report.direction,
                aggregated_long=report.score_long,
                aggregated_short=report.score_short,
                confidence=report.confidence,
                per_tf=per_tf_dict,
                target_tf=report.target_tf
            )
        except Exception as e:
            logger.error(f"Failed to create MultiTFScore: {e}", exc_info=True)
            raise
        
        # Создаем контекст
        # Проверяем наличие fibonacci и elliott в smc
        fibonacci_analysis = report.smc.get('fibonacci')
        elliott_waves = report.smc.get('elliott_waves')
        
        # Логирование для отладки
        logger.debug(f"_render_ru_nlg: fibonacci={bool(fibonacci_analysis)}, elliott={bool(elliott_waves)}, zones={list(zones.keys())}")
        
        context = ReportContext(
            report=report,
            multi_tf_score=multi_tf_score,
            zones=zones,
            price_position=price_position,
            momentum_grade=momentum_grade,
            data_ok=True,
            include_fibonacci=bool(fibonacci_analysis),
            include_elliott=bool(elliott_waves),
            include_history=False  # Пока отключено
        )
        
        # Генерируем отчет
        nlg = ReportNLG()
        brief = getattr(report, 'brief_mode', False)
        return nlg.build_report(context, brief=brief)
    
    def _determine_price_position(self, report: CompactReport):
        """Определить позицию цены в диапазоне."""
        from .report_nlg import PricePosition
        
        current_price = report.smc.get('current_price')
        if not current_price:
            return PricePosition.MIDDLE
        
        premium_discount = report.smc.get('premium_discount', {})
        if premium_discount:
            current_pos = premium_discount.get('current_position', 'neutral')
            if current_pos == "premium":
                return PricePosition.PREMIUM
            elif current_pos == "discount":
                return PricePosition.DISCOUNT
        
        # Определяем по зонам
        zones = self._build_price_zones(report)
        long_zone = zones.get("long_zone")
        short_zone = zones.get("short_zone")
        
        if long_zone and short_zone:
            if long_zone["start"] <= current_price <= long_zone["end"]:
                return PricePosition.DISCOUNT
            elif short_zone["start"] <= current_price <= short_zone["end"]:
                return PricePosition.PREMIUM
        
        return PricePosition.MIDDLE
    
    def _render_ru_v2(self, report: CompactReport) -> str:
        """
        Рендерить отчёт используя новый генератор v2 (без дубликатов, унифицированный bias).
        
        Args:
            report: CompactReport для рендеринга
        
        Returns:
            Отформатированная строка отчёта
        """
        import logging
        logger = logging.getLogger(__name__)
        
        try:
            from .report_adapter import ReportAdapter
            from .report_generator_v2 import MarketDoctorReportGenerator
            
            # Адаптируем CompactReport в MarketSnapshot
            adapter = ReportAdapter()
            snapshot = adapter.adapt(report)
            
            # Генерируем отчёт
            generator = MarketDoctorReportGenerator()
            brief_mode = getattr(report, 'brief_mode', False)
            mode = "short" if brief_mode else "auto"
            
            result = generator.generate(snapshot, mode=mode)
            return result
            
        except Exception as e:
            logger.error(f"V2 generator failed: {e}", exc_info=True)
            logger.error(f"Report structure: symbol={report.symbol}, target_tf={report.target_tf}, per_tf_keys={list(report.per_tf.keys())}")
            raise
    
    def _determine_momentum_grade(self, report: CompactReport) -> str:
        """Определить grade импульса."""
        target_tf_data = report.per_tf.get(report.target_tf, {})
        raw_scores = target_tf_data.get('raw_scores', {})
        momentum_score = raw_scores.get('momentum', 0)
        
        if momentum_score > 0.7:
            return "STRONG_BULLISH"
        elif momentum_score > 0.3:
            return "WEAK_BULLISH"
        elif momentum_score < -0.7:
            return "STRONG_BEARISH"
        elif momentum_score < -0.3:
            return "WEAK_BEARISH"
        else:
            return "NEUTRAL"
    
    def _render_ru(self, report: CompactReport) -> str:
        """Рендеринг на русском языке."""
        lines = []
        
        # Заголовок
        if len(report.per_tf) > 1:
            # Multi-TF отчёт - используем формат как в старом рендерере
            lines.append(f"🏥 <b>Market Doctor Multi-TF</b>")
            lines.append(f"Монета: <b>{report.symbol}</b>")
            lines.append("")
            lines.append("━━━━━━━━━━━━━━━━━━━━")
            
            # Консенсус, Pump, Risk, Confidence (как в старом формате)
            # Получаем средние значения pump и risk из per_tf
            avg_pump = 0.0
            avg_risk = 0.0
            pump_count = 0
            risk_count = 0
            
            for tf_data in report.per_tf.values():
                if 'pump_score' in tf_data and tf_data['pump_score'] is not None:
                    avg_pump += tf_data['pump_score']
                    pump_count += 1
                if 'risk_score' in tf_data and tf_data['risk_score'] is not None:
                    avg_risk += tf_data['risk_score']
                    risk_count += 1
            
            if pump_count > 0:
                avg_pump /= pump_count
            if risk_count > 0:
                avg_risk /= risk_count
            
            # Консенсус (используем режим из основного отчета)
            regime_text = self._translate_regime_ru(report.regime)
            lines.append(f"📊 <b>Консенсус:</b> {regime_text}")
            
            # Pump и Risk
            pump_emoji = "🔥" if avg_pump > 0.7 else "📈" if avg_pump > 0.5 else "📊"
            risk_emoji = "🔴" if avg_risk > 0.7 else "🟡" if avg_risk > 0.5 else "🟢"
            confidence_emoji = "🟢" if report.confidence > 0.7 else "🟡" if report.confidence > 0.5 else "🔴"
            
            lines.append(f"{pump_emoji} <b>Pump:</b> {avg_pump:.2f}")
            lines.append(f"{risk_emoji} <b>Risk:</b> {avg_risk:.2f}")
            lines.append(f"{confidence_emoji} <b>Confidence:</b> {report.confidence:.2f}")
            lines.append("")
            
            # Confidence explanation
            if report.confidence < 0.5:
                lines.append(f"🤔 Уверенность низкая ({report.confidence:.2f}): конфликт ТФ или недостаточно данных.")
            elif report.confidence > 0.7:
                lines.append(f"🔍 Уверенность высокая ({report.confidence:.2f}): согласованность по всем ТФ.")
            
            lines.append("━━━━━━━━━━━━━━━━━━━━")
        else:
            # Single-TF отчёт
            lines.append(f"🏥 <b>Market Doctor</b> — {report.symbol} | {report.target_tf}")
            lines.append("━━━━━━━━━━━━━━━━━━")
            
            # УЛУЧШЕННЫЙ ФОРМАТ: Вердикт одним предложением
            lines.extend(self._format_verdict_single_tf(report))
            lines.append("")
            lines.append("━━━━━━━━━━━━━━━━━━")
            lines.append("")
            
            # Режим рынка (улучшенный формат)
            lines.append("🧠 <b>Режим рынка</b>")
            regime_emoji = self._get_regime_emoji(report.regime)
            regime_text = self._translate_regime_ru(report.regime)
            lines.append(f"Фаза: {regime_text} {regime_emoji}")
            
            # Тип сетапа (если определён)
            if report.setup_type and report.setup_type != "UNKNOWN":
                setup_emoji = self._get_setup_emoji(report.setup_type)
                setup_text = report.setup_description or report.setup_type
                setup_names = {
                    "TREND_CONTINUATION": "Игра в диапазоне",
                    "REVERSAL": "Разворот",
                    "RANGE_PLAY": "Игра в диапазоне",
                    "BREAKOUT": "Пробой",
                    "MEAN_REVERSION": "Возврат к среднему"
                }
                setup_display = setup_names.get(report.setup_type, setup_text)
                lines.append(f"Тип сетапа: {setup_display} {setup_emoji}")
            
            # Стратегический и тактический bias
            score_value = report.score_long if report.direction == "LONG" else report.score_short
            opposite_score = report.score_short if report.direction == "LONG" else report.score_long
            edge = abs(score_value - opposite_score)
            confidence = report.confidence
            
            strategic_bias = report.direction
            strategic_text = "Лонговый" if strategic_bias == "LONG" else "Медвежий"
            
            # Тактический bias
            if confidence >= 0.5 and edge > 1.5:
                tactical_bias = strategic_bias
                tactical_text = "Лонговый" if tactical_bias == "LONG" else "Медвежий"
            else:
                tactical_bias = "NEUTRAL"
                tactical_text = "Нейтральный"
            
            lines.append(f"Тактический bias: {tactical_text}")
            lines.append(f"Стратегический bias: {strategic_text}")
            
            # Уверенность с категорией
            confidence_category = self._get_confidence_category(report.confidence)
            lines.append(f"Уверенность модели: {int(report.confidence * 100)}% ({confidence_category})")
        
        # Score с категорией силы
        if report.direction == "LONG":
            score_value = report.score_long
            direction_text = "ЛОНГ"
            opposite_score = report.score_short
        else:
            score_value = report.score_short
            direction_text = "ШОРТ"
            opposite_score = report.score_long
        
        # Определяем категорию силы и режим торговли
        score_category = self._get_score_category(score_value)
        trade_mode = self._get_trade_mode(score_value, report.confidence, report.direction, opposite_score)
        
        # Визуализация основного score
        main_bar = self._get_score_bar_normalized(score_value, report.score_scale)
        
        # Если режим NO_TRADE
        if trade_mode == "NO_TRADE":
            lines.append(f"📛 <b>Режим: Сетап не торговый</b>")
            lines.append(f"Score: {score_value:.1f}/10 — нет чёткого bias, рынок в балансе")
        else:
            # Multi-TF: разделяем глобальный и локальный bias
            if len(report.per_tf) > 1:
                target_tf_data = report.per_tf.get(report.target_tf, {})
                local_long = target_tf_data.get('normalized_long', 0)
                local_short = target_tf_data.get('normalized_short', 0)
                local_direction = "ЛОНГ" if local_long > local_short else "ШОРТ"
                local_score = local_long if local_direction == "ЛОНГ" else local_short
                
                lines.append(f"Глобальный bias (multi-TF): {direction_text} {score_value:.1f}/10 — {score_category}")
                lines.append(f"Локальный ({report.target_tf}): {local_direction} {local_score:.1f}/10")
            else:
                # УЛУЧШЕННЫЙ ФОРМАТ для Single-TF: оценка направлений
                lines.append("")
                lines.append("🎯 <b>Оценка направлений</b>")
                
                # Показываем оба score
                edge = report.score_long - report.score_short
                edge_text = f"+{edge:.1f}" if edge > 0 else f"{edge:.1f}"
                
                # Edge категория
                if abs(edge) > 3:
                    edge_category = "сильный"
                elif abs(edge) > 1.5:
                    edge_category = "умеренный"
                elif abs(edge) > 0.5:
                    edge_category = "слабый"
                else:
                    edge_category = "минимальный"
                
                lines.append(f"ЛОНГ: {report.score_long:.1f}/10   ШОРТ: {report.score_short:.1f}/10   Edge: {edge_text} ({edge_category})")
                lines.append("")
                
                # Объяснение edge
                if abs(edge) < 1.5:
                    lines.append("<i>Смысл: рынок в середине диапазона. Входить здесь нерентабельно ни в одну сторону.</i>")
                    if edge > 0:
                        zones = self._build_price_zones(report)
                        long_zone = zones.get("long_zone")
                        if long_zone:
                            lines.append(f"<i>Edge появляется только у лонга — но только от нижней границы диапазона ({self._format_price(long_zone['start'])}–{self._format_price(long_zone['end'])}).</i>")
                else:
                    lines.append(f"<i>Смысл: {edge_category} edge для {direction_text.lower()}а. Вход требует подтверждения.</i>")
        
        
        # Multi-TF анализ (если есть несколько таймфреймов)
        if len(report.per_tf) > 1:
            lines.append("")
            lines.append("━━━━━━━━━━━━━━━━━━━━")
            lines.append("")
            lines.append("⏱ <b>Сравнение таймфреймов</b>")
            lines.append("")
            
            # Сортируем таймфреймы по порядку
            tf_order = ["1h", "4h", "1d", "1w"]
            sorted_tfs = sorted(report.per_tf.keys(), key=lambda x: tf_order.index(x) if x in tf_order else 999)
            
            # Сокращенные названия для компактности
            phase_short = {
                "ACCUMULATION": "ACCUM",
                "DISTRIBUTION": "DISTR",
                "EXPANSION_UP": "EXP_UP",
                "EXPANSION_DOWN": "EXP_DN",
                "SHAKEOUT": "SHAKE"
            }
            
            trend_short = {
                "BULLISH": "BULL",
                "BEARISH": "BEAR",
                "NEUTRAL": "NEUT"
            }
            
            # Заголовок таблицы
            header_parts = [f"<b>{tf:>10}</b>" for tf in sorted_tfs]
            lines.append("      " + " │ ".join(header_parts))
            lines.append("      " + "─" * (len(" │ ".join(header_parts)) - 6))
            
            # Фазы
            phase_parts = []
            for tf in sorted_tfs:
                tf_data = report.per_tf[tf]
                phase_val = tf_data.get('regime', 'N/A')
                phase_text = phase_short.get(phase_val, phase_val[:8] if isinstance(phase_val, str) else "N/A")
                phase_emoji = self._get_regime_emoji(phase_val) if hasattr(self, '_get_regime_emoji') else "📦"
                phase_parts.append(f"{phase_emoji} {phase_text:>9}")
            lines.append("Фаза  " + " │ ".join(phase_parts))
            
            # Тренд
            trend_parts = []
            for tf in sorted_tfs:
                tf_data = report.per_tf[tf]
                trend_val = tf_data.get('trend', 'N/A')
                trend_text = trend_short.get(trend_val, trend_val[:4] if isinstance(trend_val, str) else "N/A")
                trend_emoji = "🟢" if trend_val == "BULLISH" else "🔴" if trend_val == "BEARISH" else "🟡"
                trend_parts.append(f"{trend_emoji} {trend_text:>9}")
            lines.append("Тренд " + " │ ".join(trend_parts))
            
            # Pump score
            pump_parts = []
            for tf in sorted_tfs:
                tf_data = report.per_tf[tf]
                pump_score = tf_data.get('pump_score', 0.0)
                pump_emoji_tf = "🔥" if pump_score > 0.7 else "📈" if pump_score > 0.5 else "📊"
                pump_parts.append(f"{pump_emoji_tf} {pump_score:.2f}")
            lines.append("Pump  " + " │ ".join([f"{p:>10}" for p in pump_parts]))
            
            # Risk score
            risk_parts = []
            for tf in sorted_tfs:
                tf_data = report.per_tf[tf]
                risk_score = tf_data.get('risk_score', 0.0)
                risk_emoji_tf = "🔴" if risk_score > 0.7 else "🟡" if risk_score > 0.5 else "🟢"
                risk_parts.append(f"{risk_emoji_tf} {risk_score:.2f}")
            lines.append("Risk  " + " │ ".join([f"{r:>10}" for r in risk_parts]))
            
            lines.append("")
            lines.append("━━━━━━━━━━━━━━━━━━━━")
            lines.append("")
            
            # УЛУЧШЕННЫЙ ФОРМАТ: Market State Snapshot
            lines.extend(self._format_market_state_snapshot(report))
            lines.append("")
            lines.append("━━━━━━━━━━━━━━━━━━━━")
            lines.append("")
        
        # Контекст (только для Single-TF, для Multi-TF пропускаем детальный блок)
        if len(report.per_tf) == 1:
            # УЛУЧШЕННЫЙ БЛОК: Детальный контекст для монотаймфрейма
            lines.append("")
            lines.append("━━━━━━━━━━━━━━━━━━")
            lines.append("")
            lines.append("📊 <b>Детальный контекст</b> ({})".format(report.target_tf))
            target_tf_data = report.per_tf.get(report.target_tf, {})
            
            # Тренд с визуализацией
            trend_val = target_tf_data.get('trend', 'N/A')
            trend_display = self._translate_trend_ru(trend_val)
            trend_emoji = "🟢" if trend_val == "BULLISH" else "🔴" if trend_val == "BEARISH" else "🟡"
            lines.append(f"{trend_emoji} <b>Тренд:</b> {trend_display}")
            
            # Импульс с детализацией
            momentum_summary = self._get_momentum_summary_ru(target_tf_data)
            raw_scores = target_tf_data.get('raw_scores', {})
            momentum_score = raw_scores.get('momentum', 0)
            momentum_bar = self._get_score_bar_directional(momentum_score)
            lines.append(f"⚡ <b>Импульс:</b> {momentum_summary} {momentum_bar}")
            
            # Pump и Risk с визуализацией
            pump_score = target_tf_data.get('pump_score', 0.5)
            risk_score = target_tf_data.get('risk_score', 0.5)
            pump_emoji = "🔥" if pump_score > 0.7 else "📈" if pump_score > 0.5 else "📊"
            risk_emoji = "🔴" if risk_score > 0.7 else "🟡" if risk_score > 0.5 else "🟢"
            pump_pct = int(pump_score * 100)
            risk_pct = int(risk_score * 100)
            pump_bar = self._get_percentage_bar(pump_pct, 10)
            risk_bar = self._get_percentage_bar(risk_pct, 10)
            lines.append(f"{pump_emoji} <b>Pump Score:</b> {pump_score:.2f} {pump_bar}")
            lines.append(f"{risk_emoji} <b>Risk Score:</b> {risk_score:.2f} {risk_bar}")
            
            # Ликвидность
            liquidity_summary = self._get_liquidity_summary_ru(report)
            liquidity_emoji = "🟢" if risk_score < 0.4 else "🟡" if risk_score < 0.6 else "🔴"
            lines.append(f"{liquidity_emoji} <b>Ликвидность:</b> {liquidity_summary}")
            
            # Волатильность
            vol_summary = self._get_volatility_summary_ru(target_tf_data)
            vol_score = raw_scores.get('volatility', 0)
            vol_emoji = "📊" if abs(vol_score) < 0.3 else "📈" if abs(vol_score) < 0.6 else "⚡"
            vol_bar = self._get_score_bar_directional(abs(vol_score))
            lines.append(f"{vol_emoji} <b>Волатильность:</b> {vol_summary} {vol_bar}")
            
            lines.append("")
            lines.append("━━━━━━━━━━━━━━━━━━")
            lines.append("")
            
            # Консенсус индикаторов (компактный формат)
            lines.append("📈 <b>Консенсус индикаторов</b> ({})".format(report.target_tf))
            
            # Компактный формат: только самые сильные сигналы
            significant_signals = []
            for group, score in raw_scores.items():
                if abs(score) > 0.5:  # Только значимые сигналы
                    group_name = self._format_group_name_ru(group)
                    emoji = "📈" if score > 0 else "📉"
                    significant_signals.append(f"{emoji} {group_name}: {score:+.2f}")
            
            if significant_signals:
                # Группируем в строки по 2-3 индикатора
                for i in range(0, len(significant_signals), 2):
                    chunk = significant_signals[i:i+2]
                    lines.append(" | ".join(chunk))
            else:
                lines.append("Нейтральные сигналы")
            
            # Общий консенсус
            net_score = target_tf_data.get('net_score', 0)
            consensus_emoji = "🟢" if net_score > 0.5 else "🔴" if net_score < -0.5 else "🟡"
            consensus_text = "бычий" if net_score > 0.5 else "медвежий" if net_score < -0.5 else "нейтральный"
            lines.append(f"{consensus_emoji} Консенсус: {consensus_text} ({net_score:+.2f})")
            lines.append("━━━━━━━━━━━━━━━━━━")
        
        # Структура рынка (SMC) - для обоих типов отчётов (улучшенный формат с зонами)
        lines.append("📌 <b>Структура рынка (SMC)</b>")
        
        # Текущая цена (если доступна)
        current_price = report.smc.get('current_price')
        if current_price:
            lines.append(f"💎 Текущая цена: {self._format_price(current_price)}")
        
        # Группируем уровни в зоны (только для Single-TF)
        if len(report.per_tf) == 1:
            zones = self._build_price_zones(report)
            
            # Определяем расположение цены
            if current_price:
                location_parts = []
                long_zone = zones.get("long_zone")
                wait_zone = zones.get("wait_zone")
                short_zone = zones.get("short_zone")
                
                if long_zone and long_zone["start"] <= current_price <= long_zone["end"]:
                    location_parts.append("в зоне спроса")
                elif wait_zone and wait_zone["start"] <= current_price <= wait_zone["end"]:
                    location_parts.append("в середине диапазона")
                elif short_zone and short_zone["start"] <= current_price <= short_zone["end"]:
                    location_parts.append("в зоне предложения")
                
                # Premium/Discount
                premium_discount = report.smc.get('premium_discount', {})
                if premium_discount:
                    current_pos = premium_discount.get('current_position', 'neutral')
                    if current_pos == "premium":
                        location_parts.append("в премиум-зоне")
                    elif current_pos == "discount":
                        location_parts.append("в discount-зоне")
                
                if location_parts:
                    lines.append(f"Расположение: {', '.join(location_parts)}.")
            
            # Лонг-зона
            long_zone = zones.get("long_zone")
            if long_zone:
                components = long_zone.get("components", [])
                components_text = ", ".join(set(components)) if components else ""
                lines.append("")
                lines.append(f"🟢 <b>Основная зона спроса (лучший лонг):</b>")
                lines.append(f"{self._format_price(long_zone['start'])} – {self._format_price(long_zone['end'])}")
                if components_text:
                    lines.append(f"({components_text})")
            
            # Шорт-зона
            short_zone = zones.get("short_zone")
            if short_zone:
                components = short_zone.get("components", [])
                components_text = ", ".join(set(components)) if components else ""
                lines.append("")
                lines.append(f"🔴 <b>Основная зона предложения:</b>")
                lines.append(f"{self._format_price(short_zone['start'])} – {self._format_price(short_zone['end'])}")
                if components_text:
                    lines.append(f"({components_text})")
                breakout_trigger = zones.get("breakout_trigger")
                if breakout_trigger:
                    lines.append(f"Breakout trigger: закрепление > {self._format_price(breakout_trigger)}")
            
            # Premium/Discount зоны
            premium_discount = report.smc.get('premium_discount')
            if premium_discount:
                premium_start = premium_discount.get('premium_start')
                discount_end = premium_discount.get('discount_end')
                current_pos = premium_discount.get('current_position', 'neutral')
                if premium_start and discount_end:
                    lines.append("")
                    lines.append("💰 <b>Premium / Discount</b>")
                    pos_text = "Премиум" if current_pos == "premium" else "Дисконт" if current_pos == "discount" else "Нейтрально"
                    lines.append(f"Текущая цена глубоко в {pos_text.lower()}")
                    if current_pos == "premium" and long_zone:
                        lines.append(f"Все лучшие лонги ниже {self._format_price(long_zone['end'])}")
        else:
            # Для Multi-TF оставляем старый формат
            levels = report.smc.get('levels', {})
            support_levels = levels.get('support', [])
            resistance_levels = levels.get('resistance', [])
            
            if support_levels:
                sup = support_levels[0]
                lines.append(f"Поддержка: {self._format_price(sup['price_low'])}–{self._format_price(sup['price_high'])}")
            
            if resistance_levels:
                res = resistance_levels[0]
                lines.append(f"Сопротивление: {self._format_price(res['price_low'])}–{self._format_price(res['price_high'])}")
        
        # Multi-TF карта SMC (компактно)
        multi_tf_levels = report.smc.get('multi_tf_levels', {})
        if multi_tf_levels and len(multi_tf_levels) > 1:
            lines.append("")
            lines.append("🗺 <b>Multi-TF карта SMC:</b>")
            tf_order = ["1h", "4h", "1d", "1w"]
            sorted_tfs = sorted(multi_tf_levels.keys(), key=lambda x: tf_order.index(x) if x in tf_order else 999)
            
            for tf in sorted_tfs:
                tf_data = multi_tf_levels[tf]
                tf_lines = []
                
                # Поддержка
                if tf_data.get('support'):
                    for sup in tf_data['support'][:1]:  # Только первый
                        rating = sup.get('rating', {})
                        rating_str = ""
                        if rating:
                            strength = rating.get('strength_text', '')
                            if strength == "сильная":
                                rating_str = " (HTF зона)"
                        tf_lines.append(f"поддержка {self._format_price(sup['price_low'])}–{self._format_price(sup['price_high'])}{rating_str}")
                
                # Сопротивление
                if tf_data.get('resistance'):
                    for res in tf_data['resistance'][:1]:  # Только первый
                        rating = res.get('rating', {})
                        rating_str = ""
                        if rating:
                            strength = rating.get('strength_text', '')
                            if strength == "сильная":
                                rating_str = " (HTF зона)"
                        tf_lines.append(f"сопротивление {self._format_price(res['price_low'])}–{self._format_price(res['price_high'])}{rating_str}")
                
                # Имбалансы
                if tf_data.get('imbalances'):
                    for imb in tf_data['imbalances']:
                        tf_lines.append(f"незакрытый дисбаланс {self._format_price(imb['price_low'])}–{self._format_price(imb['price_high'])} (магнит {'выше' if current_price and (imb['price_low'] + imb['price_high']) / 2 > current_price else 'ниже'})")
                
                if tf_lines:
                    lines.append(f"• {tf}: {'; '.join(tf_lines)}")
        
        # Расположение цены в диапазоне
        price_location = report.smc.get('price_location')
        levels = report.smc.get('levels', {})
        support_levels = levels.get('support', [])
        resistance_levels = levels.get('resistance', [])
        position_in_range = self._get_position_in_range(current_price, support_levels, resistance_levels)
        if position_in_range:
            lines.append(f"Позиция в диапазоне: {position_in_range}")
        
        if price_location:
            price_loc_ru = "Зона дисконта" if "Discount" in price_location else "Премиум-зона"
            lines.append(f"Расположение цены: {price_loc_ru}")
        
        # Premium/Discount зоны
        premium_discount = report.smc.get('premium_discount')
        if premium_discount:
            premium_start = premium_discount.get('premium_start')
            discount_end = premium_discount.get('discount_end')
            current_pos = premium_discount.get('current_position', 'neutral')
            tf = premium_discount.get('tf', 'N/A')
            
            if premium_start and discount_end:
                pos_emoji = "🔴" if current_pos == "premium" else "🟢" if current_pos == "discount" else "🟡"
                pos_text = "Премиум" if current_pos == "premium" else "Дисконт" if current_pos == "discount" else "Нейтрально"
                lines.append("")
                lines.append(f"💰 <b>Premium/Discount зоны ({tf}):</b>")
                lines.append(f"{pos_emoji} Текущая позиция: {pos_text}")
                lines.append(f"Премиум зона: от {self._format_price(premium_start)}")
                lines.append(f"Дисконт зона: до {self._format_price(discount_end)}")
        
        # Имбалансы с пометкой ТФ
        imbalances = report.smc.get('imbalances', [])
        if imbalances:
            lines.append("")
            lines.append("📎 <b>Зоны имбалансов:</b>")
            for imb in imbalances:
                filled = "Заполнен" if imb.get('filled', False) else "Не заполнен"
                tf = imb.get('tf', 'N/A')
                lines.append(f"{filled} имбаланс ({tf}): {self._format_price(imb['price_low'])}–{self._format_price(imb['price_high'])}")
        
        # Уровни Фибоначчи (только для Single-TF, компактно)
        if len(report.per_tf) == 1:
            fibonacci_data = report.smc.get('fibonacci')
            if fibonacci_data:
                lines.append("")
                lines.append("━━━━━━━━━━━━━━━━━━")
                lines.append("")
                lines.append("📐 <b>Фибоначчи</b>")
                
                # Ближайший уровень (самое важное)
                nearest = fibonacci_data.get('nearest_level')
                if nearest:
                    nearest_type = "корр." if nearest.get('type') == 'retracement' else "расш."
                    lines.append(f"Ближайший: {nearest.get('name')} ({nearest_type}) — {self._format_price(nearest.get('level'))}")
                
                # Только 3 ключевых уровня коррекции (самые важные: 38.2%, 50%, 61.8%)
                retracement_levels = fibonacci_data.get('retracement_levels', [])
                if retracement_levels and current_price:
                    important_ratios = [0.382, 0.5, 0.618]
                    fib_levels = []
                    for level in retracement_levels:
                        if level.get('ratio') in important_ratios:
                            level_price = level.get('level')
                            distance_pct = abs(level_price - current_price) / current_price * 100
                            fib_levels.append(f"{level.get('name')}: {self._format_price(level_price)} ({distance_pct:.1f}%)")
                    if fib_levels:
                        lines.append(f"Ключевые: {', '.join(fib_levels)}")
        
        # Волны Эллиотта (только для Single-TF, компактно)
        if len(report.per_tf) == 1:
            elliott_data = report.smc.get('elliott_waves')
            if elliott_data:
                lines.append("")
                lines.append("━━━━━━━━━━━━━━━━━━")
                lines.append("")
                lines.append("🌊 <b>Эллиотт</b>")
                
                pattern_type = elliott_data.get('pattern_type', 'unknown')
                pattern_short = {
                    'impulse_5': 'Импульс 1-5',
                    'corrective_abc': 'Коррекция A-C',
                    'unknown': 'Не определен'
                }
                pattern_name = pattern_short.get(pattern_type, pattern_type)
                
                current_wave = elliott_data.get('current_wave')
                trend_direction = elliott_data.get('trend_direction', 'unknown')
                trend_emoji = "📈" if trend_direction == "up" else "📉" if trend_direction == "down" else ""
                
                # Компактная строка с основной информацией
                info_parts = [f"Паттерн: {pattern_name}"]
                if current_wave:
                    info_parts.append(f"Волна: {current_wave}")
                if trend_direction != 'unknown':
                    info_parts.append(f"Тренд: {trend_emoji}")
                lines.append(" | ".join(info_parts))
                
                # Только целевые уровни (самое важное)
                target_levels = elliott_data.get('target_levels', [])
                if target_levels and current_price:
                    targets_str = []
                    for target in target_levels[:2]:  # Только первые 2
                        distance_pct = abs(target - current_price) / current_price * 100
                        direction = "↑" if target > current_price else "↓"
                        targets_str.append(f"{self._format_price(target)} ({distance_pct:.1f}% {direction})")
                    if targets_str:
                        lines.append(f"Цели: {', '.join(targets_str)}")
        
        lines.append("━━━━━━━━━━━━━━━━━━")
        
        # УЛУЧШЕННЫЙ ФОРМАТ: Вероятностные сценарии (для Multi-TF) или для Single-TF
        lines.extend(self._format_probabilistic_scenarios(report))
        lines.append("")
        lines.append("━━━━━━━━━━━━━━━━━━")
        lines.append("")
        
        # УЛУЧШЕННЫЙ ФОРМАТ: Decision Triggers (для Multi-TF) или Action Triggers (для Single-TF)
        lines.extend(self._format_decision_triggers(report))
        lines.append("")
        lines.append("━━━━━━━━━━━━━━━━━━")
        lines.append("")
        
        # УЛУЧШЕННЫЙ ФОРМАТ: Risk Board
        lines.extend(self._format_risk_board(report))
        lines.append("")
        lines.append("━━━━━━━━━━━━━━━━━━")
        lines.append("")
        
        # УЛУЧШЕННЫЙ ФОРМАТ: Playbook (только для Multi-TF)
        if len(report.per_tf) > 1:
            lines.extend(self._format_playbook(report))
            lines.append("")
            lines.append("━━━━━━━━━━━━━━━━━━")
            lines.append("")
        
        # УЛУЧШЕННЫЙ ФОРМАТ: Практические рекомендации (только для Single-TF, компактно)
        if len(report.per_tf) == 1:
            lines.extend(self._format_practical_recommendations_single_tf(report))
            lines.append("")
            lines.append("━━━━━━━━━━━━━━━━━━")
            lines.append("")
        
        # Торговые триггеры (старый формат - оставляем для совместимости)
        lines.append("🎯 <b>Триггеры</b> (не финсовет)")
        trade_map = report.trade_map
        
        # Определяем основной и контр-трендовый сценарии
        main_direction = report.direction
        bullish_trigger = trade_map.get('bullish_trigger')
        bearish_trigger = trade_map.get('bearish_trigger')
        
        # Имбалансы младших ТФ для execution
        execution_imbalances = trade_map.get('execution_imbalances', [])
        
        # Основной сценарий (по bias)
        if main_direction == "SHORT":
            lines.append(f"<b>Медвежий сценарий:</b>")
            if bearish_trigger:
                level = bearish_trigger.get('level', 0)
                trigger_text = f"• Краткосрочно в шорт при откате к {self._format_price(level)} с реакцией продавца."
                
                # Добавляем информацию об имбалансах младших ТФ
                if execution_imbalances:
                    for imb in execution_imbalances[:1]:  # Берём первый
                        tf = imb.get('tf', '')
                        mid_price = (imb.get('price_low', 0) + imb.get('price_high', 0)) / 2
                        trigger_text += f" Подтверждение — закрытие {tf}-имбаланса {self._format_price(mid_price)}."
                
                lines.append(trigger_text)
            else:
                # Используем сопротивление как зону для шорта
                if resistance_levels:
                    res = resistance_levels[0]
                    trigger_text = f"• Краткосрочно в шорт при откате к {self._format_price(res['price_low'])}–{self._format_price(res['price_high'])} с реакцией продавца."
                    
                    # Добавляем информацию об имбалансах младших ТФ
                    if execution_imbalances:
                        for imb in execution_imbalances[:1]:
                            tf = imb.get('tf', '')
                            mid_price = int((imb.get('price_low', 0) + imb.get('price_high', 0)) / 2)
                            trigger_text += f" Подтверждение — закрытие {tf}-имбаланса {mid_price:,}."
                    
                    lines.append(trigger_text)
            
            # Инвалидация шорта
            invalidations = trade_map.get('invalidations', [])
            invalidation_level = None
            for inv in invalidations:
                if inv.get('side') == 'long' or inv.get('side') == 'general':
                    invalidation_level = inv.get('level')
                    break
            if invalidation_level:
                lines.append(f"• Инвалидация шорта: закрепление выше {self._format_price(invalidation_level)}.")
            elif bullish_trigger:
                lines.append(f"• Инвалидация шорта: закрепление выше {self._format_price(bullish_trigger.get('level', 0))}.")
        else:
            lines.append(f"<b>Бычий сценарий:</b>")
            if bullish_trigger:
                level = bullish_trigger.get('level', 0)
                trigger_type = "пробой и удержание" if bullish_trigger.get('type') == 'break_and_hold' else "пробой"
                trigger_text = f"• Бычий триггер: {trigger_type} выше {self._format_price(level)}."
                
                # Добавляем информацию об имбалансах младших ТФ
                if execution_imbalances:
                    for imb in execution_imbalances[:1]:  # Берём первый
                        tf = imb.get('tf', '')
                        mid_price = (imb.get('price_low', 0) + imb.get('price_high', 0)) / 2
                        trigger_text += f" Подтверждение — закрытие {tf}-имбаланса {self._format_price(mid_price)}."
                
                lines.append(trigger_text)
            else:
                # Используем поддержку как зону для лонга
                if support_levels:
                    sup = support_levels[0]
                    trigger_text = f"• Лонг от поддержки {self._format_price(sup['price_low'])}–{self._format_price(sup['price_high'])} по сигналам разворота."
                    
                    # Добавляем информацию об имбалансах младших ТФ
                    if execution_imbalances:
                        for imb in execution_imbalances[:1]:
                            tf = imb.get('tf', '')
                            mid_price = int((imb.get('price_low', 0) + imb.get('price_high', 0)) / 2)
                            trigger_text += f" Подтверждение — закрытие {tf}-имбаланса {mid_price:,}."
                    
                    lines.append(trigger_text)
            
            # Инвалидация лонга
            invalidations = trade_map.get('invalidations', [])
            invalidation_level = None
            for inv in invalidations:
                if inv.get('side') == 'short' or inv.get('side') == 'general':
                    invalidation_level = inv.get('level')
                    break
            if invalidation_level:
                lines.append(f"• Инвалидация лонга: закрепление ниже {self._format_price(invalidation_level)}.")
            elif bearish_trigger:
                lines.append(f"• Инвалидация лонга: закрепление ниже {self._format_price(bearish_trigger.get('level', 0))}.")
        
        # Контр-трендовый сценарий
        lines.append(f"<b>{'Бычий' if main_direction == 'SHORT' else 'Медвежий'} сценарий (контртренд):</b>")
        if main_direction == "SHORT":
            if bullish_trigger:
                level = bullish_trigger.get('level', 0)
                trigger_type = "пробой и удержание" if bullish_trigger.get('type') == 'break_and_hold' else "пробой"
                lines.append(f"• Бычий триггер: {trigger_type} выше {self._format_price(level)}.")
            if support_levels:
                sup = support_levels[0]
                lines.append(f"• До подтверждения — лонг только от поддержки {self._format_price(sup['price_low'])}–{self._format_price(sup['price_high'])} по сигналам разворота.")
        else:
            if bearish_trigger:
                level = bearish_trigger.get('level', 0)
                lines.append(f"• Медвежий триггер: пробой ниже {self._format_price(level)}.")
            if resistance_levels:
                res = resistance_levels[0]
                lines.append(f"• До подтверждения — шорт только от сопротивления {self._format_price(res['price_low'])}–{self._format_price(res['price_high'])} по сигналам разворота.")
        
        # Режим размера позиции (округлённый)
        risk_mode = trade_map.get('risk_mode', 'NEUTRAL')
        position_r = trade_map.get('position_r', 0.5)
        risk_mode_ru = self._translate_risk_mode_ru(risk_mode)
        position_r_rounded = round(position_r, 1)
        lines.append(f"Режим размера позиции: {risk_mode_ru} (~{position_r_rounded}R)")
        lines.append("━━━━━━━━━━━━━━━━━━")
        
        # TL;DR с форматированием
        tldr_formatted = self._format_tldr(report.tl_dr, report.confidence, len(report.per_tf) > 1)
        lines.append(f"<b>TL;DR:</b>")
        for line in tldr_formatted:
            lines.append(line)
        
        # Добавляем переход к тактическому плану для Multi-TF
        if len(report.per_tf) > 1:
            lines.append("")
            lines.append("━━━━━━━━━━━━━━━━━━")
            lines.append("")
            lines.append("➡️ <b>Тактический план по 1h:</b> вызови команду /md_btc_1h")
        
        return "\n".join(lines)
    
    def _format_price(self, price: float) -> str:
        """Форматирует цену в зависимости от ее величины."""
        if price is None:
            return "N/A"
        if price < 0.01:
            return f"{price:,.6f}"
        elif price < 1:
            return f"{price:,.4f}"
        elif price < 100:
            return f"{price:,.3f}"
        elif price < 1000:
            return f"{price:,.2f}"
        elif price < 10000:
            return f"{price:,.1f}"
        else:
            return f"{int(price):,}"
    
    def _render_en(self, report: CompactReport) -> str:
        """Рендеринг на английском языке (сохранено на будущее)."""
        lines = []
        
        # Header
        lines.append(f"🏥 <b>Market Doctor</b> — {report.symbol} | {report.target_tf}")
        lines.append("━━━━━━━━━━━━━━━━━━")
        
        # Regime & Confidence
        regime_emoji = self._get_regime_emoji(report.regime)
        direction_emoji = "📈" if report.direction == "LONG" else "📉"
        lines.append(f"Regime: {report.regime} {regime_emoji}")
        lines.append(f"Confidence: {int(report.confidence * 100)}%")
        if report.direction == "LONG":
            score_value = report.score_long
        else:
            score_value = report.score_short
        lines.append(f"Score: {report.direction} {score_value:.1f}/{report.score_scale}")
        lines.append("━━━━━━━━━━━━━━━━━━")
        
        # Context
        lines.append("📊 <b>Context</b>")
        target_tf_data = report.per_tf.get(report.target_tf, {})
        trend_val = target_tf_data.get('trend', 'N/A')
        trend_display = trend_val.replace('_', ' ').title() if trend_val else 'N/A'
        lines.append(f"Trend: {trend_display}")
        lines.append(f"Momentum: {self._get_momentum_summary(target_tf_data)}")
        lines.append(f"Liquidity: {self._get_liquidity_summary(report)}")
        lines.append(f"Volatility: {self._get_volatility_summary(target_tf_data)}")
        lines.append("")
        
        # Indicator Consensus
        lines.append("📈 <b>Indicator Consensus</b>")
        raw_scores = target_tf_data.get('raw_scores', {})
        for group, score in raw_scores.items():
            emoji = "📈" if score > 0 else "📉" if score < 0 else "➡️"
            group_name = self._format_group_name(group)
            lines.append(f"{emoji} {group_name} → {self._get_score_description(score)}")
        lines.append("━━━━━━━━━━━━━━━━━━")
        
        # Market Structure (SMC)
        lines.append("📌 <b>Market Structure (SMC)</b>")
        
        levels = report.smc.get('levels', {})
        support_levels = levels.get('support', [])
        resistance_levels = levels.get('resistance', [])
        
        if support_levels:
            sup = support_levels[0]
            lines.append(f"Support: {self._format_price(sup['price_low'])}–{self._format_price(sup['price_high'])}")
        
        if resistance_levels:
            res = resistance_levels[0]
            lines.append(f"Resistance: {self._format_price(res['price_low'])}–{self._format_price(res['price_high'])}")
        
        price_location = report.smc.get('price_location')
        if price_location:
            lines.append(f"Price location: {price_location}")
        
        imbalances = report.smc.get('imbalances', [])
        if imbalances:
            lines.append("")
            lines.append("📎 <b>Imbalance Zones:</b>")
            for imb in imbalances[:2]:
                filled = "Filled" if imb.get('filled', False) else "Unfilled"
                lines.append(f"{filled} imbalance: {self._format_price(imb['price_low'])}–{self._format_price(imb['price_high'])}")
        
        lines.append("━━━━━━━━━━━━━━━━━━")
        
        # Trade triggers
        lines.append("🎯 <b>Trade triggers</b> (not financial advice)")
        trade_map = report.trade_map
        
        bullish_trigger = trade_map.get('bullish_trigger')
        if bullish_trigger:
            level = bullish_trigger.get('level', 0)
            lines.append(f"Bullish trigger: {bullish_trigger.get('type', 'break')} & hold above {self._format_price(level)}")
        
        bearish_trigger = trade_map.get('bearish_trigger')
        if bearish_trigger:
            level = bearish_trigger.get('level', 0)
            lines.append(f"Bearish trigger: {bearish_trigger.get('type', 'break')} under {self._format_price(level)}")
        
        risk_mode = trade_map.get('risk_mode', 'NEUTRAL')
        position_r = trade_map.get('position_r', 0.5)
        lines.append(f"Position size mode: {risk_mode} ({position_r}R)")
        lines.append("━━━━━━━━━━━━━━━━━━")
        
        # TL;DR
        lines.append(f"<b>TL;DR:</b> {report.tl_dr}")
        
        return "\n".join(lines)
    
    def _get_regime_emoji(self, regime: str) -> str:
        """Получить эмодзи для режима."""
        emoji_map = {
            "ACCUMULATION": "📦",
            "DISTRIBUTION": "📤",
            "EXPANSION_UP": "🚀",
            "EXPANSION_DOWN": "📉",
            "SHAKEOUT": "⚡"
        }
        return emoji_map.get(regime, "📊")
    
    def _get_momentum_summary(self, tf_data: dict) -> str:
        """Получить краткое описание импульса."""
        raw_scores = tf_data.get('raw_scores', {})
        momentum_score = raw_scores.get('momentum', 0)
        
        if momentum_score > 0.5:
            return "Strong"
        elif momentum_score > 0:
            return "Weak"
        elif momentum_score < -0.5:
            return "Weak (bearish)"
        else:
            return "Neutral"
    
    def _get_liquidity_summary(self, report: CompactReport) -> str:
        """Получить краткое описание ликвидности."""
        # Можно извлечь из SMC или из per_tf
        return "Neutral"  # Упрощённо
    
    def _get_volatility_summary(self, tf_data: dict) -> str:
        """Получить краткое описание волатильности."""
        raw_scores = tf_data.get('raw_scores', {})
        vol_score = raw_scores.get('volatility', 0)
        
        if abs(vol_score) > 0.5:
            return "High"
        elif abs(vol_score) > 0.2:
            return "Medium"
        else:
            return "Low"
    
    def _format_group_name(self, group: str) -> str:
        """Форматировать название группы."""
        names = {
            "trend": "Trend model",
            "momentum": "Momentum/Cycle",
            "volume": "Volume model",
            "volatility": "Volatility model",
            "structure": "Market structure",
            "derivatives": "Derivatives"
        }
        return names.get(group, group.title())
    
    def _get_score_description(self, score: float) -> str:
        """Получить описание score."""
        if score > 1.0:
            return "Strong bullish"
        elif score > 0.3:
            return "Weak bullish"
        elif score < -1.0:
            return "Strong bearish"
        elif score < -0.3:
            return "Weak bearish"
        else:
            return "Neutral"
    
    def _translate_regime_ru(self, regime: str) -> str:
        """Перевести режим на русский."""
        regime_map = {
            "ACCUMULATION": "Накопление",
            "DISTRIBUTION": "Распределение",
            "EXPANSION_UP": "Расширение вверх",
            "EXPANSION_DOWN": "Расширение вниз",
            "SHAKEOUT": "Встряска"
        }
        return regime_map.get(regime, regime)
    
    def _translate_trend_ru(self, trend: str) -> str:
        """Перевести тренд на русский."""
        trend_map = {
            "BULLISH": "Бычий",
            "BEARISH": "Медвежий",
            "NEUTRAL": "Нейтральный"
        }
        return trend_map.get(trend.upper(), trend)
    
    def _translate_risk_mode_ru(self, risk_mode: str) -> str:
        """Перевести режим риска на русский."""
        risk_map = {
            "CONSERVATIVE": "Консервативный",
            "BALANCED": "Сбалансированный",
            "AGGRESSIVE": "Агрессивный",
            "NEUTRAL": "Нейтральный"
        }
        return risk_map.get(risk_mode, risk_mode)
    
    def _format_group_name_ru(self, group: str) -> str:
        """Форматировать название группы на русском."""
        names = {
            "trend": "Тренд",
            "momentum": "Импульс",
            "volume": "Объём",
            "volatility": "Волатильность",
            "structure": "Структура",
            "derivatives": "Деривативы"
        }
        return names.get(group, group.title())
    
    def _get_score_description_ru(self, score: float) -> str:
        """Получить описание score на русском."""
        if score > 1.0:
            return "Сильный бычий"
        elif score > 0.3:
            return "Слабый бычий"
        elif score < -1.0:
            return "Сильный медвежий"
        elif score < -0.3:
            return "Слабый медвежий"
        else:
            return "Нейтрально"
    
    def _get_momentum_summary_ru(self, tf_data: dict) -> str:
        """Получить краткое описание импульса на русском.

        Сначала пробуем использовать MomentumIntelligence (momentum_insight),
        при его отсутствии — старый скоринг по raw_scores['momentum'].
        """
        mi = tf_data.get("momentum_insight")
        if mi:
            regime = mi.get("regime")
            bias = mi.get("bias")
            strength = mi.get("strength", 0.0)

            # Небольшое человекочитаемое маппирование
            if regime == "CONTINUATION":
                if bias == "LONG":
                    return "Сильный бычий импульс по тренду" if strength > 0.6 else "Бычий импульс по тренду"
                elif bias == "SHORT":
                    return "Сильный медвежий импульс по тренду" if strength > 0.6 else "Медвежий импульс по тренду"
                else:
                    return "Импульс по тренду"
            elif regime == "EXHAUSTION":
                if bias == "LONG":
                    return "Бычий импульс с признаками перегретости"
                elif bias == "SHORT":
                    return "Медвежий импульс с признаками усталости"
                else:
                    return "Импульс выдыхается"
            elif regime == "REVERSAL_RISK":
                if bias == "LONG":
                    return "Локальный бычий импульс против тренда (риск разворота)"
                elif bias == "SHORT":
                    return "Локальный медвежий импульс против тренда (риск разворота)"
                else:
                    return "Локальный импульс против тренда"
            else:
                return "Импульс нейтрален"

        # Fallback — старая логика
        raw_scores = tf_data.get('raw_scores', {})
        momentum_score = raw_scores.get('momentum', 0)

        if momentum_score > 0.5:
            return "Сильный"
        elif momentum_score > 0:
            return "Слабый"
        elif momentum_score < -0.5:
            return "Слабый (медвежий)"
        else:
            return "Нейтральный"
    
    def _get_liquidity_summary_ru(self, report: CompactReport) -> str:
        """Получить краткое описание ликвидности на русском (унифицированное)."""
        target_tf_data = report.per_tf.get(report.target_tf, {})
        risk_score = target_tf_data.get('risk_score', 0.5)
        
        # Унифицированная оценка ликвидности на основе risk_score
        if risk_score > 0.6:
            return "Ниже среднего"  # BELOW AVERAGE
        elif risk_score > 0.4:
            return "Средняя"
        else:
            return "Выше среднего"
    
    def _get_overbought_assessment(self, report: CompactReport) -> tuple[str, str]:
        """
        Получить унифицированную оценку перекупленности.
        
        Returns:
            Tuple[str, str]: (уровень на русском, уровень на английском)
            Уровни: "HIGH" / "MEDIUM" / "LOW"
        """
        target_tf_data = report.per_tf.get(report.target_tf, {})
        raw_scores = target_tf_data.get('raw_scores', {})
        momentum_score = raw_scores.get('momentum', 0)
        risk_score = target_tf_data.get('risk_score', 0.5)
        
        # Объединённая оценка: учитываем и momentum, и risk_score
        # Если RSI в экстремуме (high momentum) ИЛИ высокий риск -> HIGH
        if (momentum_score > 0.7 or risk_score > 0.65):
            return ("HIGH", "HIGH")
        elif (momentum_score > 0.5 or risk_score > 0.5):
            return ("MEDIUM", "MEDIUM")
        else:
            return ("LOW", "LOW")
    
    def _get_liquidity_assessment(self, report: CompactReport) -> tuple[str, str]:
        """
        Получить унифицированную оценку ликвидности.
        
        Returns:
            Tuple[str, str]: (уровень на русском, уровень на английском)
            Уровни: "BELOW AVERAGE" / "AVERAGE" / "ABOVE AVERAGE"
        """
        target_tf_data = report.per_tf.get(report.target_tf, {})
        risk_score = target_tf_data.get('risk_score', 0.5)
        
        if risk_score > 0.6:
            return ("Ниже среднего", "BELOW AVERAGE")
        elif risk_score > 0.4:
            return ("Средняя", "AVERAGE")
        else:
            return ("Выше среднего", "ABOVE AVERAGE")
    
    def _get_discount_zone(self, report: CompactReport) -> Optional[tuple[float, float]]:
        """
        Получить унифицированную discount zone (один расчёт для всех мест).
        
        Returns:
            Tuple[float, float] или None: (start_price, end_price)
        """
        levels = report.smc.get('levels', {})
        support_levels = levels.get('support', [])
        
        if not support_levels:
            return None
        
        sup = support_levels[0]
        sup_level = sup.get('price_low', 0)
        if not sup_level or sup_level <= 0:
            return None
        
        # Единый расчёт: 1% ниже и 1% выше от поддержки
        discount_start = sup_level * 0.99
        discount_end = sup_level * 1.01
        
        return (discount_start, discount_end)
    
    def _get_volatility_summary_ru(self, tf_data: dict) -> str:
        """Получить краткое описание волатильности на русском."""
        raw_scores = tf_data.get('raw_scores', {})
        vol_score = raw_scores.get('volatility', 0)
        
        if abs(vol_score) > 0.5:
            return "Высокая"
        elif abs(vol_score) > 0.2:
            return "Средняя"
        else:
            return "Низкая"
    
    def _get_score_bar(self, score: float) -> str:
        """Получить визуализацию score в виде прогресс-бара."""
        # Нормализуем score [-2, 2] в [0, 10]
        normalized = (score + 2) / 4 * 10
        normalized = max(0, min(10, normalized))
        
        # Создаём прогресс-бар из 10 символов
        filled = int(normalized)
        bar = "█" * filled + "░" * (10 - filled)
        
        return f"[{bar}]"
    
    def _get_score_bar_normalized(self, score: float, scale: int = 10) -> str:
        """Получить визуализацию нормализованного score."""
        # score уже в [0, scale]
        filled = int(score)
        bar = "█" * filled + "░" * (scale - filled)
        return f"[{bar}]"
    
    def _get_score_bar_directional(self, score: float) -> str:
        """Получить визуализацию score с направлением (↑ для бычьего, ↓ для медвежьего)."""
        # Нормализуем score [-2, 2] в [0, 10]
        normalized = (score + 2) / 4 * 10
        normalized = max(0, min(10, normalized))
        
        # Создаём прогресс-бар с направлением
        filled = int(normalized)
        if score > 0:
            # Бычий - используем ↑
            bar = "↑" * filled + "░" * (10 - filled)
        elif score < 0:
            # Медвежий - используем ↓
            bar = "↓" * filled + "░" * (10 - filled)
        else:
            # Нейтральный
            bar = "─" * filled + "░" * (10 - filled)
        
        return f"[{bar}]"
    
    def _get_score_category(self, score: float) -> str:
        """Получить категорию силы сигнала."""
        if score >= 8:
            return "экстремальный"
        elif score >= 6:
            return "сильный"
        elif score >= 3:
            return "умеренный"
        else:
            return "слабый / нет сетапа"
    
    def _get_trade_mode(self, score: float, confidence: float, direction: str, opposite_score: float) -> str:
        """Определить режим торговли."""
        # Режим NO_TRADE для слабых и неуверенных сетапов
        if confidence < 0.45 and abs(score - 5) < 1:
            return "NO_TRADE"
        return "TRADE"
    
    def _get_confidence_category(self, confidence: float) -> str:
        """Получить категорию уверенности."""
        if confidence >= 0.7:
            return "высокая"
        elif confidence >= 0.4:
            return "средняя"
        else:
            return "низкая"
    
    def _analyze_tf_conflict(self, per_tf: dict, target_tf: str) -> Optional[str]:
        """Анализ конфликта между таймфреймами."""
        if len(per_tf) < 2:
            return None
        
        target_data = per_tf.get(target_tf, {})
        target_long = target_data.get('normalized_long', 0)
        target_short = target_data.get('normalized_short', 0)
        target_direction = "Лонг" if target_long > target_short else "Шорт"
        
        # Проверяем старшие ТФ
        higher_tfs = []
        tf_order = ["1h", "4h", "1d", "1w"]
        target_idx = tf_order.index(target_tf) if target_tf in tf_order else 0
        
        for tf in per_tf.keys():
            if tf in tf_order:
                tf_idx = tf_order.index(tf)
                if tf_idx > target_idx:
                    higher_tfs.append(tf)
        
        if not higher_tfs:
            return None
        
        # Проверяем конфликт
        conflicts = []
        for tf in higher_tfs:
            tf_data = per_tf.get(tf, {})
            tf_long = tf_data.get('normalized_long', 0)
            tf_short = tf_data.get('normalized_short', 0)
            tf_direction = "Лонг" if tf_long > tf_short else "Шорт"
            
            if tf_direction != target_direction:
                conflicts.append(tf)
        
        if conflicts:
            conflicts_str = "/".join(conflicts)
            return f"Конфликт ТФ: локальный {target_tf} ({target_direction.lower()}) против тренда {conflicts_str} — confidence понижен."
        
        return None
    
    def _get_level_role(self, level_type: str, global_direction: str, current_price: Optional[float], level_price: float) -> str:
        """Получить роль уровня (цель, зона входа, фиксация)."""
        if not current_price:
            return ""
        
        if level_type == "support":
            if global_direction == "SHORT":
                return "(цель для шорта, агрессивные лонги только при признаках разворота)"
            else:
                return "(зона потенциальных лонгов / фиксации шорта)"
        else:  # resistance
            if global_direction == "SHORT":
                return "(зона для поиска шортов / фиксации лонгов)"
            else:
                return "(цель для лонга, агрессивные шорты только при признаках разворота)"
    
    def _get_position_in_range(self, current_price: Optional[float], support_levels: list, resistance_levels: list) -> Optional[str]:
        """Получить позицию цены в диапазоне."""
        if not current_price or not support_levels or not resistance_levels:
            return None
        
        sup_price = support_levels[0]['price_low']
        res_price = resistance_levels[0]['price_low']
        
        range_size = res_price - sup_price
        distance_to_sup = current_price - sup_price
        distance_to_res = res_price - current_price
        
        if distance_to_sup < range_size * 0.3:
            return "ближе к поддержке"
        elif distance_to_res < range_size * 0.3:
            return "ближе к сопротивлению"
        else:
            return "в середине диапазона"
    
    def _format_tldr(self, tldr: str, confidence: float, is_multi_tf: bool) -> List[str]:
        """Форматировать TL;DR в список строк с маркерами."""
        # Разбиваем на предложения
        sentences = [s.strip() for s in tldr.replace('.', '.').split('.') if s.strip()]
        
        formatted = []
        for sentence in sentences:
            if sentence:
                formatted.append(f"• {sentence}")
        
        # Добавляем объяснение низкой уверенности, если нужно
        if confidence < 0.5 and is_multi_tf:
            formatted.insert(1, "• Уверенность низкая из-за конфликта ТФ — требуется дополнительный анализ.")
        
        return formatted
    
    def _get_price_location(self, report: CompactReport) -> Optional[str]:
        """Получить расположение цены (premium/discount)."""
        # Извлекаем из SMC данных
        smc = report.smc
        # Можно добавить поле current_position в SMC данные при построении отчёта
        # Пока возвращаем None, если нет данных
        return None
    
    def _get_setup_emoji(self, setup_type: str) -> str:
        """Получить эмодзи для типа сетапа."""
        emoji_map = {
            "TREND_CONTINUATION": "➡️",
            "REVERSAL": "🔄",
            "RANGE_PLAY": "↔️",
            "BREAKOUT": "🚀",
            "MEAN_REVERSION": "↩️",
            "UNKNOWN": "❓"
        }
        return emoji_map.get(setup_type, "📊")
    
    def _get_percentage_bar(self, percentage: float, length: int = 10) -> str:
        """Получить визуальный бар для процентного значения (0-100%)."""
        percentage = max(0, min(100, percentage))
        filled = int(percentage / 100 * length)
        bar = "█" * filled + "░" * (length - filled)
        return f"{bar} ({percentage:.0f}%)"
    
    def _get_percentage_from_score(self, score: float, scale: int = 10) -> float:
        """Преобразовать score в проценты (0-100%)."""
        normalized = max(0, min(scale, score))
        return (normalized / scale) * 100
    
    def _format_market_state_snapshot(self, report: CompactReport) -> List[str]:
        """Форматировать Market State Snapshot с визуальными шкалами."""
        lines = []
        lines.append("📍 <b>Market State Snapshot</b>")
        
        # Получаем данные из отчета
        target_tf_data = report.per_tf.get(report.target_tf, {})
        raw_scores = target_tf_data.get('raw_scores', {})
        
        # Trend strength (из score)
        trend_score = abs(report.score_long if report.direction == "LONG" else report.score_short)
        trend_pct = self._get_percentage_from_score(trend_score, report.score_scale)
        trend_bar = self._get_percentage_bar(trend_pct, 10)
        lines.append(f"Trend: {trend_bar}")
        
        # Volatility (из raw_scores)
        vol_score = raw_scores.get('volatility', 0)
        vol_pct = abs(vol_score) * 25 if abs(vol_score) <= 2 else 50  # Приблизительная нормализация
        vol_bar = self._get_percentage_bar(vol_pct, 10)
        lines.append(f"Volatility: {vol_bar}")
        
        # Liquidity (упрощенная оценка)
        risk_score = target_tf_data.get('risk_score', 0.5)
        liquidity_pct = (1 - risk_score) * 100  # Инвертируем risk для ликвидности
        liquidity_bar = self._get_percentage_bar(liquidity_pct, 10)
        liquidity_warning = " ⚠️ тонкий рынок → выше риск ложных движений" if liquidity_pct < 30 else ""
        lines.append(f"Liquidity: {liquidity_bar}{liquidity_warning}")
        
        # Market regime description
        regime_text = self._translate_regime_ru(report.regime)
        trend_text = self._translate_trend_ru(target_tf_data.get('trend', 'NEUTRAL'))
        lines.append("")
        lines.append(f"{regime_text} → {trend_text} (но локальная перегретость)" if risk_score > 0.6 else f"{regime_text} → {trend_text}")
        
        return lines
    
    def _format_probabilistic_scenarios(self, report: CompactReport) -> List[str]:
        """Форматировать вероятностные сценарии с качественными оценками (без процентов)."""
        lines = []
        # Для Multi-TF - более общий заголовок, для Single-TF - с временным горизонтом
        if len(report.per_tf) > 1:
            lines.append("📈 <b>Сценарии</b>")
        else:
            lines.append("📈 <b>Сценарии (24–48ч)</b>")
        
        target_tf_data = report.per_tf.get(report.target_tf, {})
        current_price = report.smc.get('current_price')
        levels = report.smc.get('levels', {})
        support_levels = levels.get('support', [])
        resistance_levels = levels.get('resistance', [])
        
        # Получаем pump и risk для расчета относительных весов
        pump_score = target_tf_data.get('pump_score', 0.5)
        risk_score = target_tf_data.get('risk_score', 0.5)
        
        # Рассчитываем относительные веса сценариев
        direction = report.direction
        confidence = report.confidence
        
        scenarios = []
        
        # Используем зоны для Single-TF
        zones = self._build_price_zones(report) if len(report.per_tf) == 1 else {}
        long_zone = zones.get("long_zone")
        short_zone = zones.get("short_zone")
        breakout_trigger = zones.get("breakout_trigger")
        
        # Bullish Breakout scenario
        if direction == "LONG" or pump_score > 0.6:
            weight_bull = pump_score * 0.7 + confidence * 0.3
            if breakout_trigger:
                target1 = breakout_trigger * 1.025
                target2 = breakout_trigger * 1.10
                
                liquidity_ru, liquidity_en = self._get_liquidity_assessment(report)
                risk_desc = 'стандартный риск' if liquidity_en != "BELOW AVERAGE" else 'низкая ликвидность → возможен ложный пробой'
                
                scenarios.append({
                    'name': 'Bullish Breakout',
                    'weight': weight_bull,
                    'priority': 'основной' if weight_bull > 0.5 else 'альтернативный',
                    'condition': f'Требуется пробой {self._format_price(breakout_trigger)} и закрепление.',
                    'condition_detail': '',
                    'targets': f'{self._format_price(target1)} → {self._format_price(target2)}',
                    'risk': risk_desc
                })
            elif resistance_levels:
                res = resistance_levels[0]
                res_level = res.get('price_low', current_price * 1.02 if current_price else 0)
                target1 = res_level * 1.025 if res_level else 0
                target2 = res_level * 1.10 if res_level else 0
                
                liquidity_ru, liquidity_en = self._get_liquidity_assessment(report)
                risk_desc = 'стандартный риск' if liquidity_en != "BELOW AVERAGE" else 'низкая ликвидность → возможен ложный пробой'
                
                scenarios.append({
                    'name': 'Bullish Breakout',
                    'weight': weight_bull,
                    'priority': 'основной' if weight_bull > 0.5 else 'альтернативный',
                    'condition': f'Требуется пробой {self._format_price(res_level)} и закрепление.',
                    'condition_detail': '',
                    'targets': f'{self._format_price(target1)} → {self._format_price(target2)}',
                    'risk': risk_desc
                })
        
        # Range/Pullback scenario (наиболее вероятный при текущих условиях)
        weight_range = 1 - abs(pump_score - 0.5) * 2
        if long_zone and short_zone:
            scenarios.append({
                'name': 'Range + Pullback',
                'weight': weight_range,
                'priority': 'основной' if weight_range > 0.5 else 'альтернативный',
                'condition': f'Цена продолжает торговаться внутри диапазона {self._format_price(long_zone["start"])}–{self._format_price(short_zone["end"])}, без выхода за границы спроса и предложения',
                'condition_detail': '',
                'targets': f'Лучший вход: {self._format_price(long_zone["start"])}–{self._format_price(long_zone["end"])}. Цели: {self._format_price(short_zone["start"])}–{self._format_price(short_zone["end"])}',
                'risk': 'средний риск в диапазоне'
            })
        elif support_levels and resistance_levels:
            sup = support_levels[0]
            res = resistance_levels[0]
            sup_level = sup.get('price_low', 0)
            res_level = res.get('price_low', 0)
            
            # Унифицированный discount zone
            discount_zone = self._get_discount_zone(report)
            if discount_zone:
                discount_start, discount_end = discount_zone
                discount_zone_str = f"{self._format_price(discount_start)}–{self._format_price(discount_end)}"
            else:
                discount_zone_str = f"{self._format_price(sup_level * 0.99)}–{self._format_price(sup_level * 1.01)}"
            
            scenarios.append({
                'name': 'Range + Pullback',
                'weight': weight_range,
                'priority': 'основной' if weight_range > 0.5 else 'альтернативный',
                'condition': f'Цена остаётся между {self._format_price(sup_level)} и {self._format_price(res_level)}.',
                'condition_detail': '',
                'targets': f'Лучший вход: {discount_zone_str}',
                'risk': 'средний риск в диапазоне'
            })
        
        # Bearish Rejection scenario
        if direction == "SHORT" or risk_score > 0.6:
            weight_bear = risk_score * 0.6 + (1 - confidence) * 0.4
            if support_levels:
                sup = support_levels[0]
                sup_level = sup.get('price_low', current_price * 0.98 if current_price else 0)
                res_level = resistance_levels[0].get('price_low', current_price * 1.02 if current_price else 0) if resistance_levels else (current_price * 1.02 if current_price else 0)
                
                scenarios.append({
                    'name': 'Bearish Rejection',
                    'weight': weight_bear,
                    'priority': 'основной' if weight_bear > 0.5 else 'альтернативный',
                    'condition': f'Откат из зоны {self._format_price(res_level)}–{self._format_price(res_level * 1.02)} с уходом к поддержкам {self._format_price(sup_level)}.',
                    'condition_detail': '',
                    'targets': f'Цель: {self._format_price(sup_level * 0.98)}',
                    'risk': 'высокий риск выноса стопов перед реальным разворотом'
                })
        
        # Сортируем по весу (убывание)
        scenarios.sort(key=lambda x: x['weight'], reverse=True)
        
        # Убеждаемся, что только один сценарий помечен как "основной"
        if scenarios:
            # Первый (с наибольшим весом) - основной, остальные - альтернативные
            for i in range(1, len(scenarios)):
                if scenarios[i]['priority'] == 'основной' and scenarios[0]['priority'] == 'основной':
                    scenarios[i]['priority'] = 'альтернативный'
        
        # Выводим сценарии с качественными оценками
        for i, scenario in enumerate(scenarios, 1):
            priority_emoji = "1️⃣" if scenario['priority'] == 'основной' else "2️⃣"
            lines.append("")
            lines.append(f"{i}) <b>{scenario['name']}</b> — {scenario['priority']} сценарий:")
            lines.append(f"   • {scenario['condition']}")
            if scenario['condition_detail']:
                lines.append(f"   • {scenario['condition_detail']}")
            lines.append(f"   • Цели: {scenario['targets']}")
            lines.append(f"   • Риск: {scenario['risk']}")
        
        return lines
    
    def _format_decision_triggers(self, report: CompactReport) -> List[str]:
        """Форматировать Decision Triggers (условия для действий) с использованием зон."""
        lines = []
        lines.append("⚙️ <b>Decision Triggers</b>")
        
        current_price = report.smc.get('current_price')
        zones = self._build_price_zones(report) if len(report.per_tf) == 1 else {}
        long_zone = zones.get("long_zone")
        short_zone = zones.get("short_zone")
        wait_zone = zones.get("wait_zone")
        breakout_trigger = zones.get("breakout_trigger")
        
        # LONG trigger
        lines.append("")
        lines.append("🟩 <b>Условие для LONG:</b>")
        if long_zone:
            lines.append(f"Цена возвращается в {self._format_price(long_zone['start'])}–{self._format_price(long_zone['end'])}")
        if breakout_trigger:
            lines.append(f"или закрепляется выше {self._format_price(breakout_trigger)} с объёмом")
        
        # SHORT trigger
        lines.append("")
        lines.append("🟥 <b>Условие для SHORT:</b>")
        if short_zone:
            lines.append(f"Реакция продавца в зоне {self._format_price(short_zone['start'])}–{self._format_price(short_zone['end'])}")
        
        # WAIT condition
        if wait_zone:
            lines.append("")
            lines.append("🔵 <b>Условие для \"WAIT\":</b>")
            lines.append(f"{self._format_price(wait_zone['start'])}–{self._format_price(wait_zone['end'])} = зона без edge")
        
        return lines
    
    def _format_risk_board(self, report: CompactReport) -> List[str]:
        """Форматировать Risk Board (таблица рисков) с унифицированными оценками."""
        lines = []
        lines.append("⚠️ <b>Risk Board</b>")
        
        target_tf_data = report.per_tf.get(report.target_tf, {})
        raw_scores = target_tf_data.get('raw_scores', {})
        risk_score = target_tf_data.get('risk_score', 0.5)
        pump_score = target_tf_data.get('pump_score', 0.5)
        
        # Overbought assessment (унифицированная оценка)
        overbought_ru, overbought_en = self._get_overbought_assessment(report)
        rsi_comment = "в зоне перекупленности" if overbought_ru == "HIGH" else ("в средней зоне" if overbought_ru == "MEDIUM" else "не в зоне перекупленности")
        lines.append(f"• Overbought: {overbought_en} (RSI/Stoch RSI {rsi_comment})")
        
        # Liquidity assessment (унифицированная оценка)
        liquidity_ru, liquidity_en = self._get_liquidity_assessment(report)
        liquidity_comment = "(тонкий рынок → выше риск выносов)" if liquidity_en == "BELOW AVERAGE" else "(стандартная ликвидность)"
        lines.append(f"• Liquidity: {liquidity_en} {liquidity_comment}")
        
        # Funding/OI assessment (упрощённо)
        funding_level = "нейтрально"
        funding_comment = ""
        if pump_score > 0.7 and risk_score < 0.4:
            funding_level = "подтверждает импульс"
        elif pump_score < 0.4:
            funding_level = "не подтверждает импульс"
            funding_comment = " (импульс не подтверждён деривативами)"
        lines.append(f"• Funding/OI: {funding_level}{funding_comment}")
        
        # Probability of flush (вербально, без точных процентов)
        if risk_score > 0.65:
            flush_desc = "повышенная"
        elif risk_score > 0.45:
            flush_desc = "средняя"
        else:
            flush_desc = "низкая"
        lines.append(f"• Probability of flush (локального сброса): {flush_desc}")
        
        return lines
    
    def _format_playbook(self, report: CompactReport) -> List[str]:
        """Форматировать Playbook (чек-лист вместо текста) с унифицированными уровнями."""
        lines = []
        lines.append("🎯 <b>Playbook</b>")
        
        levels = report.smc.get('levels', {})
        support_levels = levels.get('support', [])
        resistance_levels = levels.get('resistance', [])
        
        # Good entry zone (унифицированный расчёт)
        discount_zone = self._get_discount_zone(report)
        if discount_zone:
            discount_start, discount_end = discount_zone
            lines.append("")
            lines.append(f"✔️ <b>Хороший вход:</b> {self._format_price(discount_start)}–{self._format_price(discount_end)}")
            lines.append("   (discount zone + объёмные уровни)")
        
        # Caution zone
        if resistance_levels:
            res = resistance_levels[0]
            res_level = res.get('price_low', 0)
            caution_start = res_level * 0.98
            caution_end = res_level * 1.02
            
            lines.append("")
            lines.append(f"⚠️ <b>Осторожно:</b> {self._format_price(caution_start)}–{self._format_price(caution_end)}")
            lines.append("   (зона повышения риска, потенциальный разворот)")
        
        # Forbidden zone
        if resistance_levels:
            res = resistance_levels[0]
            forbidden_level = res.get('price_low', 0) * 1.05
            
            lines.append("")
            lines.append(f"❌ <b>Запрещено:</b> покупка выше {self._format_price(forbidden_level)}")
            lines.append("   без обновления структуры и подтверждений по объёму")
        
        return lines
    
    def _build_price_zones(self, report: CompactReport) -> Dict[str, Dict]:
        """
        Группировать уровни в зоны: лонг-зона, WAIT-зона, шорт-зона.
        
        Returns:
            {
                "long_zone": {"start": float, "end": float, "components": [...]},
                "wait_zone": {"start": float, "end": float},
                "short_zone": {"start": float, "end": float, "components": [...]},
                "breakout_trigger": float
            }
        """
        current_price = report.smc.get('current_price')
        if not current_price:
            return {}
        
        levels = report.smc.get('levels', {})
        support_levels = levels.get('support', [])
        resistance_levels = levels.get('resistance', [])
        
        # Собираем все уровни и компоненты
        long_components = []
        short_components = []
        
        # Поддержки -> лонг-зона
        if support_levels:
            sup = support_levels[0]
            sup_low = sup.get('price_low', 0)
            sup_high = sup.get('price_high', 0)
            long_components.append(("поддержка", sup_low, sup_high))
        
        # Premium/Discount
        premium_discount = report.smc.get('premium_discount', {})
        if premium_discount:
            discount_end = premium_discount.get('discount_end')
            premium_start = premium_discount.get('premium_start')
            if discount_end:
                long_components.append(("discount", discount_end * 0.99, discount_end * 1.01))
            if premium_start:
                short_components.append(("premium", premium_start * 0.99, premium_start * 1.01))
        
        # FVG (Fair Value Gaps) - добавляем в соответствующие зоны
        imbalances = report.smc.get('imbalances', [])
        for imb in imbalances:
            if imb.get('filled', False):
                continue
            imb_low = imb.get('price_low', 0)
            imb_high = imb.get('price_high', 0)
            if imb_low < current_price:
                long_components.append(("FVG", imb_low, imb_high))
            else:
                short_components.append(("FVG", imb_low, imb_high))
        
        # Группируем в зоны
        zones = {}
        
        # Лонг-зона: объединяем все компоненты поддержки (нижняя часть диапазона)
        if long_components:
            all_longs = []
            for comp in long_components:
                all_longs.extend([comp[1], comp[2]])
            if all_longs:
                long_start = min(all_longs)
                long_end = max(all_longs)
                # Не расширяем слишком сильно - берем реальные уровни
                # Лонг-зона должна быть четко внизу
                zones["long_zone"] = {
                    "start": long_start * 0.998,  # Небольшой запас снизу
                    "end": long_end * 1.002,  # Небольшой запас сверху
                    "components": [comp[0] for comp in long_components]
                }
        
        # Шорт-зона: сопротивление и premium (верхняя часть диапазона)
        if resistance_levels:
            res = resistance_levels[0]
            res_low = res.get('price_low', 0)
            res_high = res.get('price_high', 0)
            short_components.append(("сопротивление", res_low, res_high))
        
        if short_components:
            all_shorts = []
            for comp in short_components:
                all_shorts.extend([comp[1], comp[2]])
            if all_shorts:
                short_start = min(all_shorts)
                short_end = max(all_shorts)
                # Шорт-зона должна быть четко вверху
                zones["short_zone"] = {
                    "start": short_start * 0.998,  # Небольшой запас снизу
                    "end": short_end * 1.002,  # Небольшой запас сверху
                    "components": [comp[0] for comp in short_components]
                }
                zones["breakout_trigger"] = short_end * 1.01
        
        # WAIT-зона: между лонг и шорт зонами (середина диапазона)
        # Важно: зоны не должны пересекаться!
        if zones.get("long_zone") and zones.get("short_zone"):
            long_end = zones["long_zone"]["end"]
            short_start = zones["short_zone"]["start"]
            
            # Если зоны пересекаются - корректируем
            if long_end >= short_start:
                # Зоны пересекаются - разделяем по середине
                mid_point = (long_end + short_start) / 2
                zones["long_zone"]["end"] = mid_point * 0.999
                zones["short_zone"]["start"] = mid_point * 1.001
            
            # WAIT-зона между ними
            zones["wait_zone"] = {
                "start": zones["long_zone"]["end"],
                "end": zones["short_zone"]["start"]
            }
        elif zones.get("long_zone"):
            # Если нет шорт-зоны, WAIT начинается после лонг-зоны
            zones["wait_zone"] = {
                "start": zones["long_zone"]["end"],
                "end": current_price * 1.05  # Примерно 5% выше
            }
        elif zones.get("short_zone"):
            # Если нет лонг-зоны, WAIT до шорт-зоны
            zones["wait_zone"] = {
                "start": current_price * 0.95,  # Примерно 5% ниже
                "end": zones["short_zone"]["start"]
            }
        
        return zones
    
    def _format_verdict_single_tf(self, report: CompactReport) -> List[str]:
        """Форматировать вердикт для Single-TF отчета с разделением стратегического и тактического bias."""
        lines = []
        
        target_tf_data = report.per_tf.get(report.target_tf, {})
        risk_score = target_tf_data.get('risk_score', 0.5)
        liquidity_ru, liquidity_en = self._get_liquidity_assessment(report)
        overbought_ru, overbought_en = self._get_overbought_assessment(report)
        current_price = report.smc.get('current_price')
        
        # Определяем стратегический и тактический bias
        confidence = report.confidence
        score_value = report.score_long if report.direction == "LONG" else report.score_short
        opposite_score = report.score_short if report.direction == "LONG" else report.score_long
        edge = abs(score_value - opposite_score)
        
        # Стратегический bias (глобальное направление)
        strategic_bias = report.direction  # LONG или SHORT
        strategic_text = "Лонговый" if strategic_bias == "LONG" else "Медвежий"
        
        # Тактический bias (можно ли входить сейчас)
        tactical_bias = "NEUTRAL"
        verdict = "WAIT / OBSERVE"
        
        # Определяем, есть ли edge для входа
        has_tactical_edge = False
        if confidence >= 0.5 and edge > 1.5:
            has_tactical_edge = True
            tactical_bias = strategic_bias
            verdict = "LONG" if strategic_bias == "LONG" else "SHORT"
            if risk_score > 0.5:
                verdict += " (осторожно)"
        else:
            # Нет тактического edge
            tactical_bias = "NEUTRAL"
            verdict = "WAIT / OBSERVE"
        
        # Причина для WAIT
        reason_parts = []
        if verdict == "WAIT / OBSERVE":
            # Проверяем позицию цены
            zones = self._build_price_zones(report)
            wait_zone = zones.get("wait_zone")
            long_zone = zones.get("long_zone")
            
            if wait_zone and current_price:
                if wait_zone["start"] <= current_price <= wait_zone["end"]:
                    reason_parts.append("цена торгуется в середине диапазона")
            
            # Проверяем импульс
            momentum_insight = target_tf_data.get('momentum_insight', {})
            if momentum_insight:
                regime = momentum_insight.get('regime', '')
                if regime == "EXHAUSTION":
                    reason_parts.append("импульс ослаб")
            
            # Проверяем premium/discount
            premium_discount = report.smc.get('premium_discount', {})
            if premium_discount:
                current_pos = premium_discount.get('current_position', 'neutral')
                if current_pos == "premium":
                    reason_parts.append("цена в премиум-зоне")
            
            if not reason_parts:
                reason_parts.append("edge для входа отсутствует")
            
            reason = ", ".join(reason_parts) + "."
        else:
            reason = "умеренный edge, вход требует подтверждения"
        
        # Лучшее действие
        zones = self._build_price_zones(report)
        long_zone = zones.get("long_zone")
        breakout_trigger = zones.get("breakout_trigger")
        
        best_action = "ждем подтверждения"
        if verdict == "WAIT / OBSERVE":
            if long_zone and strategic_bias == "LONG":
                best_action = f"ждать отката в {self._format_price(long_zone['start'])}–{self._format_price(long_zone['end'])} — там находится реальная зона спроса"
            elif breakout_trigger and strategic_bias == "LONG":
                best_action = f"ждать пробоя {self._format_price(breakout_trigger)} с подтверждением"
        elif verdict.startswith("LONG") and long_zone:
            best_action = f"вход от {self._format_price(long_zone['start'])}–{self._format_price(long_zone['end'])}"
        elif verdict.startswith("SHORT"):
            short_zone = zones.get("short_zone")
            if short_zone:
                best_action = f"вход от {self._format_price(short_zone['start'])}–{self._format_price(short_zone['end'])}"
        
        lines.append("🎯 <b>Решение:</b> " + verdict)
        lines.append(f"<i>Причина:</i> {reason}")
        lines.append(f"<i>Лучшее действие:</i> {best_action}")
        
        return lines
    
    def _format_metaphor(self, report: CompactReport) -> str:
        """Генерировать метафору состояния рынка."""
        target_tf_data = report.per_tf.get(report.target_tf, {})
        risk_score = target_tf_data.get('risk_score', 0.5)
        pump_score = target_tf_data.get('pump_score', 0.5)
        raw_scores = target_tf_data.get('raw_scores', {})
        momentum_score = raw_scores.get('momentum', 0)
        
        # Генерируем метафору на основе состояния
        if pump_score > 0.7 and risk_score > 0.6:
            return "разогнанный автомобиль на мокрой дороге — движение вверх есть, но сцепление слабое: легко сорвать"
        elif risk_score > 0.7:
            return "рынок перегрет без топлива — движется вверх, но сцепление слабое"
        elif momentum_score > 0.6 and risk_score < 0.4:
            return "сильный импульс по тренду — движение уверенное, но требует подтверждения"
        elif momentum_score < -0.6:
            return "против тренда на локальном уровне — движение рискованное, возможен разворот"
        else:
            return "баланс сил — движение неопределённое, требуется подтверждение"
    
    def _format_practical_recommendations_single_tf(self, report: CompactReport) -> List[str]:
        """Форматировать практические рекомендации для Single-TF отчета с использованием зон."""
        lines = []
        lines.append("💡 <b>Рекомендации</b> (не финсовет)")
        
        target_tf_data = report.per_tf.get(report.target_tf, {})
        score_value = report.score_long if report.direction == "LONG" else report.score_short
        confidence = report.confidence
        risk_score = target_tf_data.get('risk_score', 0.5)
        zones = self._build_price_zones(report)
        long_zone = zones.get("long_zone")
        short_zone = zones.get("short_zone")
        breakout_trigger = zones.get("breakout_trigger")
        
        # Рекомендации для лонга
        if report.direction == "LONG":
            lines.append("")
            lines.append("<b>Для лонга:</b>")
            
            if long_zone:
                lines.append(f"Вход: только от {self._format_price(long_zone['start'])}–{self._format_price(long_zone['end'])}")
                # Стоп-лосс
                stop_level = long_zone['start'] * 0.995
                if report.smc.get('current_price'):
                    stop_pct = ((report.smc.get('current_price') - stop_level) / report.smc.get('current_price')) * 100
                    lines.append(f"Риск: ставить стоп под {self._format_price(stop_level)} (~{stop_pct:.1f}%)")
            
            if short_zone:
                lines.append(f"Цели: {self._format_price(short_zone['start'])}–{self._format_price(short_zone['end'])}")
            
            # Размер позиции
            if confidence < 0.5 or abs(score_value - 5) < 1:
                size_text = "консервативный (0.25–0.5R)"
            elif score_value >= 7 and confidence >= 0.7:
                size_text = "1R" if risk_score < 0.4 else "0.75R"
            else:
                size_text = "0.5–0.75R"
            lines.append(f"Размер: {size_text}")
            
            # Для шорта (контртренд)
            if short_zone:
                lines.append("")
                lines.append("<b>Для шорта (контртренд):</b>")
                lines.append(f"Только при явном отклонении от {self._format_price(short_zone['start'])}–{self._format_price(short_zone['end'])}")
                if breakout_trigger:
                    lines.append(f"Инвалидация: выше {self._format_price(breakout_trigger)}")
        
        # Рекомендации для шорта
        elif report.direction == "SHORT":
            lines.append("")
            lines.append("<b>Для шорта:</b>")
            
            if short_zone:
                lines.append(f"Вход: только от {self._format_price(short_zone['start'])}–{self._format_price(short_zone['end'])}")
                # Стоп-лосс
                stop_level = short_zone['end'] * 1.005
                if report.smc.get('current_price'):
                    stop_pct = ((stop_level - report.smc.get('current_price')) / report.smc.get('current_price')) * 100
                    lines.append(f"Риск: ставить стоп выше {self._format_price(stop_level)} (~{stop_pct:.1f}%)")
            
            if long_zone:
                lines.append(f"Цели: {self._format_price(long_zone['start'])}–{self._format_price(long_zone['end'])}")
            
            # Размер позиции
            if confidence < 0.5 or abs(score_value - 5) < 1:
                size_text = "консервативный (0.25–0.5R)"
            elif score_value >= 7 and confidence >= 0.7:
                size_text = "1R" if risk_score < 0.4 else "0.75R"
            else:
                size_text = "0.5–0.75R"
            lines.append(f"Размер: {size_text}")
        
        return lines
    
    def _format_historical_pattern(self, report: CompactReport) -> List[str]:
        """Форматировать исторические паттерны похожих сетапов."""
        lines = []
        lines.append("📚 <b>История таких сетапов:</b>")
        
        # Получаем статистику из metadata если есть (может не быть в CompactReport)
        metadata = getattr(report, 'metadata', None) or {}
        
        # Упрощённая логика на основе setup_type и grade
        setup_type = report.setup_type
        grade = getattr(report, 'grade', None)
        
        if grade == 'C' or grade == 'D':
            lines.append("• Преимущество неустойчивое")
            lines.append("• Чаще дают \"ложный импульс\" перед коррекцией")
            lines.append("• Хорошие входы появлялись только после отката — не по текущим уровням")
        elif grade == 'B':
            lines.append("• Умеренное преимущество")
            lines.append("• Требуют подтверждения объёмом")
            lines.append("• Лучшие входы — на откатах к поддержкам")
        else:
            lines.append("• Хорошее преимущество")
            lines.append("• Входы по текущим уровням могут быть эффективны")
            lines.append("• Требуется контроль риска")
        
        # Если есть статистика hit-rate в metadata
        hit_rate = metadata.get('hit_rate') if isinstance(metadata, dict) else None
        avg_r = metadata.get('avg_r') if isinstance(metadata, dict) else None
        if hit_rate is not None or avg_r is not None:
            lines.append("")
            hit_str = f"Hit-rate: {hit_rate:.0%}" if hit_rate is not None else ""
            r_str = f"Средний R: ≈{avg_r:.2f}" if avg_r is not None else ""
            if hit_str or r_str:
                lines.append(f"• {hit_str} | {r_str}")
        
        return lines

