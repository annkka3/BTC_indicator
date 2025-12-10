# app/domain/market_diagnostics/report_nlg.py
"""
Natural Language Generation для отчетов Market Doctor.
Единый шаблон с плейсхолдерами и правила генерации текста.
"""

from typing import Dict, List, Optional, Tuple, TYPE_CHECKING
from dataclasses import dataclass
from enum import Enum

# Импорты для работы во время выполнения
from .scoring_engine import MultiTFScore
from .bias_engine_v2 import BiasEngineV2, BiasAnalysis
from .narrative_engine import NarrativeEngine, NarrativeSummary
from .regime_detector import RegimeDetector, RegimeAnalysis
from .flow_engine import FlowEngine, FlowAnalysis
from .smart_money_v2 import SmartMoneyV2, SmartMoneyAnalysis
from .r_asymmetry import RAsymmetryCalculator, RAsymmetry
from .conditions_shift import ConditionsShift, ShiftConditions
from .micro_patterns import MicroPatternEngine, PatternDetection
from .confidence_v2 import ConfidenceV2, ConfidenceAnalysis
from .personalization import PersonalizationEngine, UserProfile, RiskProfile, TradingStyle

if TYPE_CHECKING:
    from .compact_report import CompactReport
else:
    # Для избежания циклического импорта
    CompactReport = None


class Decision(Enum):
    """Решение для торговли."""
    WAIT = "WAIT"
    LONG = "LONG"
    SHORT = "SHORT"
    AVOID = "AVOID"


class PricePosition(Enum):
    """Позиция цены в диапазоне."""
    DISCOUNT = "discount"
    MIDDLE = "middle"
    PREMIUM = "premium"


@dataclass
class ReportContext:
    """Контекст для генерации отчета."""
    report: any  # CompactReport (используем any для избежания циклического импорта)
    multi_tf_score: MultiTFScore
    zones: Dict[str, Dict]  # Зоны цен
    price_position: PricePosition
    momentum_grade: str  # STRONG_BULLISH, WEAK_BULLISH, etc.
    data_ok: bool = True
    include_fibonacci: bool = True
    include_elliott: bool = True
    include_history: bool = True


class ReportNLG:
    """Natural Language Generation для отчетов Market Doctor."""
    
    def __init__(self):
        """Инициализация генератора."""
        self.bias_engine_v2 = BiasEngineV2()
        self.narrative_engine = NarrativeEngine()
        self.regime_detector = RegimeDetector()
        self.flow_engine = FlowEngine()
        self.smart_money_v2 = SmartMoneyV2()
        self.r_asymmetry_calc = RAsymmetryCalculator()
        self.conditions_shift = ConditionsShift()
        self.micro_patterns = MicroPatternEngine()
        self.confidence_v2 = ConfidenceV2()
        self.personalization = PersonalizationEngine()
    
    def build_report(self, context: ReportContext, brief: bool = False) -> str:
        """
        Построить отчет по шаблону.
        
        Args:
            context: Контекст с данными для отчета
            brief: Если True, генерирует краткий отчёт (V4 Short & Smart)
        
        Returns:
            Текстовый отчет
        """
        # Определяем решение
        decision, decision_reason = self._choose_decision(context)
        best_action = self._best_action_text(decision, context)
        
        # Собираем все значения для плейсхолдеров
        placeholders = self._build_placeholders(context, decision, decision_reason, best_action)
        
        # Генерируем отчет по шаблону
        if brief:
            template = self._get_brief_template(context)
        else:
            template = self._get_template(context)
        report_text = template.format(**placeholders)
        
        return report_text
    
    def _choose_decision(
        self,
        context: ReportContext
    ) -> Tuple[Decision, str]:
        """
        Выбрать решение на основе метрик.
        
        Returns:
            Tuple[Decision, str]: (решение, причина)
        """
        report = context.report
        long_score = report.score_long
        short_score = report.score_short
        edge_diff = long_score - short_score
        max_score = max(long_score, short_score)
        confidence = report.confidence
        
        # Проверка данных
        if not context.data_ok:
            return Decision.AVOID, "Проблемы с данными/моделью — лучше пропустить любые решения."
        
        # 1) Если вообще нет edge - всегда WAIT
        if max_score < 4.5 or abs(edge_diff) < 1.0:
            return Decision.WAIT, "явного преимущества ни у лонга, ни у шорта нет, цена в середине диапазона."
        
        # 2) Если явный лонговый edge
        if edge_diff >= 1.0 and long_score >= 5.5:
            if context.price_position == PricePosition.DISCOUNT:
                return Decision.LONG, "бычий bias + цена в дисконт-зоне — есть смысл искать вход в лонг."
            elif context.price_position == PricePosition.MIDDLE:
                return Decision.WAIT, "бычий bias, но по текущим ценам вход неэффективен — лучше ждать отката."
            else:  # premium
                return Decision.WAIT, "бычий bias, но цена в премиуме — лучше ждать отката к поддержке."
        
        # 3) Если явный шортовый edge
        if edge_diff <= -1.0 and short_score >= 5.5:
            if context.price_position == PricePosition.PREMIUM:
                return Decision.SHORT, "шортовый bias + цена в премиум-зоне — сценарий для продажи от сопротивления."
            elif context.price_position == PricePosition.MIDDLE:
                return Decision.WAIT, "шортовый bias, но в середине диапазона edge слабый — лучше ждать теста сопротивления."
            else:  # discount
                return Decision.WAIT, "шортовый bias, но цена уже в зоне дисконта — вход вниз поздний, лучше ждать отката."
        
        # 4) Остальное — консервативный WAIT
        return Decision.WAIT, "сетап неоднозначный — лучше наблюдать и ждать реакции на ключевых уровнях."
    
    def _best_action_text(self, decision: Decision, context: ReportContext) -> str:
        """Сгенерировать текст лучшего действия."""
        zones = context.zones
        long_zone = zones.get("long_zone")
        short_zone = zones.get("short_zone")
        price_position = context.price_position
        report = context.report
        current_price = report.smc.get('current_price', 0)
        
        if decision == Decision.WAIT:
            # Для WAIT не даем конкретных активных рекомендаций
            edge_diff = report.score_long - report.score_short
            if abs(edge_diff) < 1.0:
                # Минимальный edge - просто наблюдение
                return "наблюдать за реакцией на ключевые уровни, не открывая новые позиции по текущей цене."
            else:
                # Есть небольшой edge, но недостаточно для входа
                if price_position == PricePosition.MIDDLE:
                    return "наблюдать за реакцией на границах диапазона, не входить из середины."
                elif price_position == PricePosition.PREMIUM and long_zone:
                    return f"ждать отката к нижней части диапазона ({long_zone['start']:.0f}–{long_zone['end']:.0f}) для более выгодного входа."
                elif price_position == PricePosition.DISCOUNT and short_zone:
                    return f"ждать отката к верхней части диапазона ({short_zone['start']:.0f}–{short_zone['end']:.0f}) для более выгодного входа."
                return "наблюдать за реакцией на ключевых уровнях."
        
        if decision == Decision.LONG:
            if long_zone:
                return f"искать подтверждённый вход в лонг от поддержки {long_zone['start']:.0f}–{long_zone['end']:.0f}."
        
        if decision == Decision.SHORT:
            if short_zone:
                return f"искать шорт от зоны предложения {short_zone['start']:.0f}–{short_zone['end']:.0f} по сигналам разворота."
        
        return "наблюдать за ценой у ключевых уровней."
    
    def _confidence_label(self, conf: float) -> str:
        """Вербальный ярлык для уверенности."""
        if conf < 0.4:
            return "низкая"
        if conf < 0.7:
            return "средняя"
        return "высокая"
    
    def _score_strength(self, score: float) -> str:
        """Вербальный ярлык для силы score."""
        if score < 4:
            return "слабый"
        if score < 6:
            return "умеренный"
        if score < 7.5:
            return "хороший"
        return "сильный"
    
    def _edge_label(self, edge_diff: float) -> str:
        """Вербальный ярлык для edge."""
        ad = abs(edge_diff)
        if ad < 1.0:
            return "edge почти отсутствует"
        if ad < 2.0:
            return "слабый edge"
        if ad < 3.0:
            return "умеренный edge"
        return "сильный edge"
    
    def _consensus_label_from_value(self, v: float) -> str:
        """Вербальный ярлык для консенсуса индикатора."""
        if v <= -0.7:
            return "сильный медвежий"
        if v <= -0.3:
            return "умеренно медвежий"
        if v < 0.3:
            return "нейтральный"
        if v < 0.7:
            return "умеренно бычий"
        return "сильный бычий"
    
    def _scenario_weight_label(self, prob: float) -> str:
        """Вербальный ярлык для веса сценария."""
        if prob >= 0.7:
            return "наиболее вероятный"
        if prob >= 0.5:
            return "возможный"
        return "редкий, но важный"
    
    def _overbought_label(self, rsi: Optional[float], stoch_k: Optional[float], stoch_d: Optional[float]) -> str:
        """Вербальный ярлык для перекупленности."""
        if rsi and (rsi > 70 or (stoch_k and stoch_d and stoch_k > 80 and stoch_d > 80)):
            return "высокая (зона перекупленности)"
        if rsi and (rsi < 30 or (stoch_k and stoch_d and stoch_k < 20 and stoch_d < 20)):
            return "низкая (зона перепроданности)"
        return "умеренная"
    
    def _liquidity_label_detailed(self, liq_value: float) -> str:
        """Вербальный ярлык для ликвидности."""
        if liq_value < 0.3:
            return "низкая (тонкий рынок, возможны проскальзывания)"
        if liq_value < 0.7:
            return "средняя"
        return "высокая (рыночные ордера исполняются комфортно)"
    
    def _position_size_r(self, edge_diff: float, confidence: float) -> float:
        """Рассчитать размер позиции в R."""
        base = 0.25
        if abs(edge_diff) > 2.0:
            base += 0.25
        if confidence > 0.7:
            base += 0.25
        return round(min(base, 1.0), 2)
    
    def _size_mode_label(self, size_r: float) -> str:
        """Вербальный ярлык для режима размера позиции."""
        if size_r <= 0.25:
            return "минимальный"
        if size_r <= 0.5:
            return "консервативный"
        if size_r <= 0.75:
            return "умеренный"
        return "агрессивный"
    
    def _get_ohlcv_data(self, symbol: str, timeframe: str, n_bars: int = 100) -> tuple:
        """
        Получить OHLCV данные для анализа.
        
        Returns:
            (candles_list, volumes_list, price_changes_list)
        """
        try:
            # Пытаемся получить db из контекста или глобально
            from app.infrastructure.db import DB
            from app.config import settings
            import os
            
            db_path = getattr(settings, 'database_path', os.getenv('DATABASE_PATH', '/data/data.db'))
            db = DB(db_path)
            
            # Получаем бары
            rows = db.last_n(symbol, timeframe, n_bars)
            if not rows:
                return [], [], []
            
            candles = []
            volumes = []
            price_changes = []
            prev_close = None
            
            for ts, o, h, l, c, v in rows:
                candles.append({
                    'open': float(o),
                    'high': float(h),
                    'low': float(l),
                    'close': float(c),
                    'volume': float(v) if v is not None else 0.0
                })
                volumes.append(float(v) if v is not None else 0.0)
                
                if prev_close is not None:
                    price_changes.append((float(c) - prev_close) / prev_close)
                prev_close = float(c)
            
            return candles, volumes, price_changes
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.warning(f"Failed to get OHLCV data: {e}")
            return [], [], []
    
    def _get_funding_data(self, symbol: str = "BTCUSDT") -> tuple:
        """
        Получить funding rate данные.
        
        Returns:
            (current_funding, historical_funding_list)
        """
        try:
            from app.infrastructure.market_data import binance_funding_and_mark
            
            # Получаем текущий funding
            data = binance_funding_and_mark(symbol)
            current_funding = data.get('fundingRate', 0.0)
            
            # Для исторического funding пока возвращаем пустой список
            # TODO: можно сохранять историю funding в БД
            historical_funding = [current_funding] * 100  # Заглушка
            
            return current_funding, historical_funding
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.warning(f"Failed to get funding data: {e}")
            return None, []
    
    def _build_placeholders(
        self,
        context: ReportContext,
        decision: Decision,
        decision_reason: str,
        best_action: str
    ) -> Dict[str, any]:
        """Построить словарь плейсхолдеров для шаблона."""
        report = context.report
        zones = context.zones
        target_tf_data = report.per_tf.get(report.target_tf, {})
        raw_scores = target_tf_data.get('raw_scores', {})
        
        # Получаем OHLCV данные
        candles, volumes, price_changes = self._get_ohlcv_data(report.symbol, report.target_tf, 100)
        
        # Рассчитываем индикаторы для отображения конкретных значений
        indicator_values = {}
        try:
            if candles and len(candles) > 0:
                import pandas as pd
                from .indicators import IndicatorCalculator
                from .config import DEFAULT_CONFIG
                
                # Создаём DataFrame из candles
                df = pd.DataFrame({
                    'open': [c[1] for c in candles],
                    'high': [c[2] for c in candles],
                    'low': [c[3] for c in candles],
                    'close': [c[4] for c in candles],
                    'volume': volumes if volumes else [0.0] * len(candles)
                })
                
                # Рассчитываем индикаторы
                indicator_calc = IndicatorCalculator(DEFAULT_CONFIG)
                indicators = indicator_calc.calculate_all(df)
                
                # Извлекаем последние значения
                if len(df) > 0:
                    indicator_values = {
                        'rsi': indicators.get('rsi', pd.Series([50.0]))[-1] if 'rsi' in indicators and len(indicators['rsi']) > 0 else None,
                        'macd': indicators.get('macd', pd.Series([0.0]))[-1] if 'macd' in indicators and len(indicators['macd']) > 0 else None,
                        'macd_signal': indicators.get('macd_signal', pd.Series([0.0]))[-1] if 'macd_signal' in indicators and len(indicators['macd_signal']) > 0 else None,
                        'macd_hist': indicators.get('macd_hist', pd.Series([0.0]))[-1] if 'macd_hist' in indicators and len(indicators['macd_hist']) > 0 else None,
                        'bb_upper': indicators.get('bb_upper', pd.Series([current_price]))[-1] if 'bb_upper' in indicators and len(indicators['bb_upper']) > 0 else None,
                        'bb_middle': indicators.get('bb_middle', pd.Series([current_price]))[-1] if 'bb_middle' in indicators and len(indicators['bb_middle']) > 0 else None,
                        'bb_lower': indicators.get('bb_lower', pd.Series([current_price]))[-1] if 'bb_lower' in indicators and len(indicators['bb_lower']) > 0 else None,
                        'stoch_rsi_k': indicators.get('stoch_rsi_k', pd.Series([50.0]))[-1] if 'stoch_rsi_k' in indicators and len(indicators['stoch_rsi_k']) > 0 else None,
                        'stoch_rsi_d': indicators.get('stoch_rsi_d', pd.Series([50.0]))[-1] if 'stoch_rsi_d' in indicators and len(indicators['stoch_rsi_d']) > 0 else None,
                        'atr': indicators.get('atr', pd.Series([0.0]))[-1] if 'atr' in indicators and len(indicators['atr']) > 0 else None,
                        'adx': indicators.get('adx', pd.Series([0.0]))[-1] if 'adx' in indicators and len(indicators['adx']) > 0 else None,
                        'ema_20': indicators.get('ema_20', pd.Series([current_price]))[-1] if 'ema_20' in indicators and len(indicators['ema_20']) > 0 else None,
                        'ema_50': indicators.get('ema_50', pd.Series([current_price]))[-1] if 'ema_50' in indicators and len(indicators['ema_50']) > 0 else None,
                        'ema_200': indicators.get('ema_200', pd.Series([current_price]))[-1] if 'ema_200' in indicators and len(indicators['ema_200']) > 0 else None,
                    }
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.warning(f"Failed to calculate indicator values: {e}")
            indicator_values = {}
        
        # Получаем funding данные
        current_funding, historical_funding = self._get_funding_data(f"{report.symbol}USDT" if report.symbol == "BTC" else report.symbol)
        
        # Decision
        decision_labels = {
            Decision.WAIT: "WAIT / OBSERVE",
            Decision.LONG: "LONG SETUP",
            Decision.SHORT: "SHORT SETUP",
            Decision.AVOID: "AVOID / SKIP"
        }
        decision_label = decision_labels.get(decision, "WAIT / OBSERVE")
        
        # Режим
        regime_emoji = self._get_regime_emoji(report.regime)
        regime_name = self._translate_regime(report.regime)
        
        # Setup type
        setup_type_emoji = self._get_setup_emoji(report.setup_type) if report.setup_type else "📊"
        setup_type_name = report.setup_description or report.setup_type or "Не определен"
        
        # Confidence
        confidence_pct = int(report.confidence * 100)
        confidence_label = self._confidence_label(report.confidence)
        
        # Score
        main_direction = "ЛОНГ" if report.direction == "LONG" else "ШОРТ"
        main_score = report.score_long if report.direction == "LONG" else report.score_short
        score_strength = self._score_strength(main_score)
        score_bar = self._get_score_bar_normalized(main_score, 10)
        
        edge_diff = report.score_long - report.score_short
        edge_label = self._edge_label(edge_diff)
        
        # Категория edge
        edge_category_text = "сильный" if abs(edge_diff) > 3 else ("умеренный" if abs(edge_diff) > 1.5 else ("слабый" if abs(edge_diff) > 0.5 else "минимальный"))
        
        # Объяснение edge
        long_zone = zones.get("long_zone")
        if abs(edge_diff) < 1.5:
            edge_explanation_text = "Смысл: рынок в середине диапазона. Входить здесь нерентабельно ни в одну сторону."
            if edge_diff > 0 and long_zone:
                edge_explanation_text += f" Edge появляется только у лонга — но только от нижней границы диапазона ({long_zone.get('start', 0):.0f}–{long_zone.get('end', 0):.0f})."
        else:
            edge_explanation_text = f"Смысл: {edge_category_text} edge для {main_direction.lower()}а. Вход требует подтверждения."
        
        # Тактический и стратегический bias
        tactical_bias_text = "Нейтральный" if decision == Decision.WAIT else ("Лонговый" if decision == Decision.LONG else "Медвежий")
        strategic_bias_text = "Лонговый" if report.direction == "LONG" else "Медвежий"
        
        # Согласованность сигналов
        signals_alignment_label = "высокая" if report.confidence >= 0.7 else ("средняя" if report.confidence >= 0.4 else "низкая")
        
        # Контекст
        trend_label = self._translate_trend(target_tf_data.get('trend', 'NEUTRAL'))
        momentum_label = self._get_momentum_summary_ru(target_tf_data)
        momentum_bar = self._get_score_bar_directional(raw_scores.get('momentum', 0))
        
        pump_score = target_tf_data.get('pump_score', 0.5)
        risk_score = target_tf_data.get('risk_score', 0.5)
        pump_bar = self._get_percentage_bar(int(pump_score * 100), 10)
        risk_bar = self._get_percentage_bar(int(risk_score * 100), 10)
        
        liquidity_label = self._get_liquidity_summary_ru(report)
        volatility_label = self._get_volatility_summary_ru(target_tf_data)
        volatility_bar = self._get_score_bar_directional(abs(raw_scores.get('volatility', 0)))
        
        # Форматируем описания для risk_score и volatility
        risk_score_label = "стандартный риск" if risk_score < 0.5 else "повышенный риск"
        volatility_description = "осторожный режим → повышает шанс резких одно-свечных движений (stop sweep)" if volatility_label == "Низкая" else "стандартная"
        
        # Консенсус индикаторов
        trend_score = raw_scores.get('trend', 0)
        momentum_score = raw_scores.get('momentum', 0)
        volume_score = raw_scores.get('volume', 0)
        structure_score = raw_scores.get('structure', 0)
        deriv_score = raw_scores.get('derivatives', 0)
        
        # Общий консенсус (взвешенная сумма)
        consensus_value = 0.4 * trend_score + 0.3 * volume_score + 0.3 * structure_score
        consensus_label = self._consensus_label_from_value(consensus_value)
        
        # Структура рынка
        current_price = report.smc.get('current_price', 0)
        long_zone = zones.get("long_zone", {})
        short_zone = zones.get("short_zone", {})
        
        demand_zone_low = long_zone.get("start", 0) if long_zone else 0
        demand_zone_high = long_zone.get("end", 0) if long_zone else 0
        supply_zone_low = short_zone.get("start", 0) if short_zone else 0
        supply_zone_high = short_zone.get("end", 0) if short_zone else 0
        
        # Позиция в диапазоне
        range_position_label = self._get_range_position_label(context.price_position, current_price, long_zone, short_zone)
        
        # Premium/Discount
        premium_discount = report.smc.get('premium_discount', {})
        premium_position_label = self._get_premium_position_label(premium_discount)
        premium_position_label_lower = premium_position_label.lower() if premium_position_label else "нейтрально"
        premium_threshold = premium_discount.get('premium_start', 0) if premium_discount else 0
        discount_threshold = premium_discount.get('discount_end', 0) if premium_discount else 0
        
        # Проверяем, находится ли цена рядом с премиум-зоной (но не внутри)
        premium_position_text = premium_position_label_lower
        if current_price and premium_threshold:
            distance_pct = abs(current_price - premium_threshold) / premium_threshold if premium_threshold > 0 else 1.0
            if current_price < premium_threshold and distance_pct < 0.005 and premium_position_label == "Нейтрально":
                premium_position_text = "верхней части диапазона, рядом с премиум-зоной"
            elif premium_position_label == "Премиум":
                # Если цена в премиум-зоне, добавляем про зону предложения
                if short_zone:
                    premium_position_text = f"премиум-зоне, неподалёку от зоны предложения ({short_zone.get('start', 0):.0f}–{short_zone.get('end', 0):.0f}), где вероятность контрдействия продавца повышается"
                else:
                    premium_position_text = "премиум-зоне, неподалёку от зоны предложения, где вероятность контрдействия продавца повышается"
        
        # Имбалансы
        imbalances_lines = self._format_imbalances(report.smc.get('imbalances', []), current_price)
        
        # Фибоначчи
        # Данные могут быть в report.fibonacci_analysis или в report.smc['fibonacci']
        fibonacci_analysis = getattr(report, 'fibonacci_analysis', None) or report.smc.get('fibonacci')
        fibonacci_data = fibonacci_analysis if context.include_fibonacci and fibonacci_analysis else None
        
        # Логирование для отладки
        import logging
        logger = logging.getLogger(__name__)
        if context.include_fibonacci:
            logger.debug(f"Fibonacci check: include_fibonacci={context.include_fibonacci}, has_data={bool(fibonacci_analysis)}, smc_keys={list(report.smc.keys()) if hasattr(report, 'smc') else 'no smc'}")
        fib_near_level_name = ""
        fib_near_price = 0
        fib_382 = 0
        fib_500 = 0
        fib_618 = 0
        
        if fibonacci_data:
            nearest = fibonacci_data.get('nearest_level')
            if nearest:
                # Поддерживаем оба формата: старый (с percentage) и новый (с level)
                if 'percentage' in nearest:
                    fib_near_level_name = nearest.get('type', '') + ' ' + str(nearest.get('percentage', 0)) + '%'
                    fib_near_price = nearest.get('price', 0)
                else:
                    fib_near_level_name = nearest.get('name', nearest.get('type', ''))
                    fib_near_price = nearest.get('level', 0)
            
            retracement_levels = fibonacci_data.get('retracement_levels', [])
            for level in retracement_levels:
                # Поддерживаем оба формата: старый (с percentage) и новый (с ratio)
                if 'percentage' in level:
                    percentage = level.get('percentage', 0)
                    price = level.get('price', 0)
                else:
                    # Новый формат: ratio (0.382, 0.5, 0.618)
                    ratio = level.get('ratio', 0)
                    percentage = ratio * 100
                    price = level.get('level', 0)
                
                if abs(percentage - 38.2) < 1:
                    fib_382 = price
                elif abs(percentage - 50.0) < 1:
                    fib_500 = price
                elif abs(percentage - 61.8) < 1:
                    fib_618 = price
        
        # Эллиотт
        # Данные могут быть в report.elliott_waves или в report.smc['elliott_waves']
        elliott_waves = getattr(report, 'elliott_waves', None) or report.smc.get('elliott_waves')
        elliott_data = elliott_waves if context.include_elliott and elliott_waves else None
        
        # Логирование для отладки
        if context.include_elliott:
            logger.debug(f"Elliott check: include_elliott={context.include_elliott}, has_data={bool(elliott_waves)}, smc_keys={list(report.smc.keys()) if hasattr(report, 'smc') else 'no smc'}")
        elliott_pattern = "Не определен"
        elliott_wave = ""
        elliott_trend = ""
        
        if elliott_data:
            pattern_type = elliott_data.get('pattern_type', 'unknown')
            pattern_short = {
                'impulse_5': 'Импульс 1-5',
                'corrective_abc': 'Коррекция A-C',
                'unknown': 'Не определен'
            }
            elliott_pattern = pattern_short.get(pattern_type, pattern_type)
            
            current_wave = elliott_data.get('current_wave')
            if current_wave:
                elliott_wave = str(current_wave)
            
            trend_direction = elliott_data.get('trend_direction', 'unknown')
            if trend_direction == "up":
                elliott_trend = "📈"
            elif trend_direction == "down":
                elliott_trend = "📉"
            else:
                elliott_trend = ""
        
        # Сценарии
        scenarios = self._get_scenarios(context)
        scenario1 = scenarios[0] if scenarios else {}
        scenario2 = scenarios[1] if len(scenarios) > 1 else {}
        scenario3 = scenarios[2] if len(scenarios) > 2 else {}
        
        # Вычисляем проценты для сценариев (до использования в словаре)
        scenario1_weight_pct = "60–70%" if scenario1.get('weight', 0) > 0.6 else "25–35%"
        scenario2_weight_pct = "60–70%" if scenario2.get('weight', 0) > 0.6 else "25–35%"
        
        # Форматируем второй сценарий (скрываем если пустой)
        scenario2_block = ""
        if scenario2 and scenario2.get('name'):
            scenario2_block = f"\n2) {scenario2.get('name', '')} — {scenario2.get('weight_label', '')} ({scenario2_weight_pct})\n\nУсловие: {scenario2.get('condition', '')}\n🎯 Цели: {scenario2.get('targets', '')}\n🎯 Риск: {scenario2.get('risk_label', '')}\n"
        
        # Временной горизонт
        horizon_map = {
            "15m": (1, 4),
            "1h": (4, 24),
            "4h": (24, 72),
            "1d": (72, 168)
        }
        horizon_hours_min, horizon_hours_max = horizon_map.get(report.target_tf, (4, 24))
        
        # Decision Triggers
        long_trigger_text, short_trigger_text, wait_trigger_text = self._format_decision_triggers(context)
        
        # Risk Board
        overbought_label = self._overbought_label(
            raw_scores.get('rsi'),
            raw_scores.get('stoch_k'),
            raw_scores.get('stoch_d')
        )
        liquidity_label_detailed = self._liquidity_label_detailed(1 - risk_score)  # Инвертируем risk для ликвидности
        derivatives_risk_label = self._get_derivatives_risk_label(pump_score, risk_score)
        flush_risk_label = self._get_flush_risk_label(context)
        
        # Практические рекомендации
        position_size_r = self._position_size_r(edge_diff, report.confidence)
        size_mode_label = self._size_mode_label(position_size_r)
        position_size_r_label = f"{position_size_r:.2f}"
        
        entry_strategy_text, stop_loss_text, targets_text = self._get_entry_strategy(decision, context)
        risk_mgmt_text = self._get_risk_mgmt_text(risk_score)
        
        # Форматируем блоки для стопов и целей (скрываем N/A)
        stop_loss_block = f"Стоп ниже {stop_loss_text}\n" if stop_loss_text != "N/A" else ""
        targets_block = f"Цели: {targets_text}\n" if targets_text != "N/A" else ""
        
        # Если оба блока пустые, убираем лишний перенос строки
        if not stop_loss_block and not targets_block:
            # Ничего не делаем, блоки остаются пустыми
            pass
        
        # Формируем рекомендации в зависимости от решения
        recommendations_text = self._format_recommendations(decision, context, entry_strategy_text, stop_loss_text, targets_text, size_mode_label, position_size_r_label, risk_mgmt_text)
        
        # История
        hist_avg_r, hist_hit_rate, hist_n_cases, hist_comment = self._get_history_data(context)
        
        # TL;DR
        tldr_lines = self._generate_tldr_lines(context, decision, decision_reason)
        
        # ========== НОВЫЕ МОДУЛИ V2 ==========
        
        # 1. Bias Engine v2 - Structural & Liquidity Bias
        smc_data = report.smc
        liquidity_above = smc_data.get('liquidity_pools', {}).get('above', [])
        liquidity_below = smc_data.get('liquidity_pools', {}).get('below', [])
        imbalances = smc_data.get('imbalances', [])
        
        bias_analysis = None
        try:
            # Получаем HTF уровни из multi_tf_levels если есть
            htf_levels = {}
            multi_tf_levels = smc_data.get('multi_tf_levels', {})
            for tf, levels_data in multi_tf_levels.items():
                if tf in ['4h', '1d', '1w']:
                    support = levels_data.get('support', [])
                    resistance = levels_data.get('resistance', [])
                    htf_levels[tf] = [s.get('price_low', 0) for s in support] + [r.get('price_low', 0) for r in resistance]
            
            # EQH/EQL из key_levels
            key_levels = smc_data.get('levels', {})
            resistance_levels = key_levels.get('resistance', [])
            support_levels = key_levels.get('support', [])
            eqh_levels = [r.get('price_low', 0) for r in resistance_levels[:3]]
            eql_levels = [s.get('price_low', 0) for s in support_levels[:3]]
            
            bias_analysis = self.bias_engine_v2.get_full_bias_analysis(
                tactical_bias=tactical_bias_text,
                strategic_bias=strategic_bias_text,
                current_price=current_price,
                htf_levels=htf_levels if htf_levels else None,
                imbalances=imbalances,
                eqh_levels=eqh_levels if eqh_levels else None,
                eql_levels=eql_levels if eql_levels else None,
                liquidity_above=liquidity_above,
                liquidity_below=liquidity_below,
                recent_volume=sum(volumes[-5:]) / 5 if volumes and len(volumes) >= 5 else (volumes[-1] if volumes else None),
                avg_volume=sum(volumes) / len(volumes) if volumes else None,
                oi_delta=None,  # TODO: получить из Binance API
                funding_rate=current_funding
            )
        except Exception:
            bias_analysis = None
        
        # 2. Narrative Engine
        narrative_summary = None
        try:
            if candles and volumes:
                narrative_summary = self.narrative_engine.generate_narrative(
                    candles=candles,
                    volumes=volumes,
                    momentum_score=momentum_score,
                    volume_score=volume_score,
                    trend_direction=trend_label
                )
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.warning(f"Narrative engine failed: {e}")
            narrative_summary = None
        
        # 3. Regime Detector
        regime_analysis = None
        try:
            volatility_val = abs(raw_scores.get('volatility', 0))
            
            # Вычисляем размеры фитилей из свечей
            recent_wicks = []
            if candles:
                for candle in candles[-20:]:  # Последние 20 свечей
                    wick_size = (candle['high'] - max(candle['open'], candle['close'])) + \
                               (min(candle['open'], candle['close']) - candle['low'])
                    recent_wicks.append(wick_size / candle['close'] if candle['close'] > 0 else 0)
            
            if price_changes and volumes:
                regime_analysis = self.regime_detector.detect_regime(
                    price_changes=price_changes,
                    volumes=volumes,
                    volatility=volatility_val,
                    momentum_score=momentum_score,
                    liquidity_above=liquidity_above if isinstance(liquidity_above, list) else [],
                    liquidity_below=liquidity_below if isinstance(liquidity_below, list) else [],
                    recent_wicks=recent_wicks
                )
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.warning(f"Regime detector failed: {e}")
            regime_analysis = None
        
        # 4. Flow Engine
        flow_analysis = None
        try:
            # Вычисляем CVD (Cumulative Volume Delta) из свечей
            cvd_values = []
            if candles and volumes:
                cvd = 0.0
                for i, candle in enumerate(candles):
                    if candle['close'] > candle['open']:
                        cvd += volumes[i] if i < len(volumes) else 0
                    elif candle['close'] < candle['open']:
                        cvd -= volumes[i] if i < len(volumes) else 0
                    cvd_values.append(cvd)
            
            # Для OI пока используем заглушку (можно получить из Binance API)
            oi_data = None
            
            # Для агрессивных ордеров используем объёмы как приближение
            buy_orders = volumes if candles and all(c['close'] > c['open'] for c in candles[-10:]) else None
            sell_orders = volumes if candles and all(c['close'] < c['open'] for c in candles[-10:]) else None
            
            flow_analysis = self.flow_engine.analyze_flows(
                cvd_values=cvd_values if cvd_values else None,
                oi_data=oi_data,
                current_funding=current_funding,
                historical_funding=historical_funding if historical_funding else None,
                buy_orders=buy_orders,
                sell_orders=sell_orders
            )
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.warning(f"Flow engine failed: {e}")
            flow_analysis = None
        
        # 5. Smart Money v2
        smart_money_analysis = None
        try:
            # Вычисляем volume absorption (поглощение объёма)
            volume_absorption = 0.5
            if candles and volumes and len(candles) >= 10:
                recent_candles = candles[-10:]
                recent_volumes = volumes[-10:] if len(volumes) >= 10 else volumes
                # Если большой объём, но цена не двигается - поглощение
                avg_vol = sum(recent_volumes) / len(recent_volumes) if recent_volumes else 0
                max_vol = max(recent_volumes) if recent_volumes else 0
                price_range = max(c['high'] for c in recent_candles) - min(c['low'] for c in recent_candles)
                if max_vol > avg_vol * 1.5 and price_range < current_price * 0.01:
                    volume_absorption = 0.8
                elif max_vol > avg_vol * 1.2:
                    volume_absorption = 0.6
            
            # Вычисляем recent_wicks
            recent_wicks_sm = []
            if candles:
                for candle in candles[-20:]:
                    wick_size = (candle['high'] - max(candle['open'], candle['close'])) + \
                               (min(candle['open'], candle['close']) - candle['low'])
                    recent_wicks_sm.append(wick_size)
            
            smart_money_analysis = self.smart_money_v2.analyze_smart_money(
                current_price=current_price,
                weekly_ob=None,  # TODO: получить из данных
                weekly_os=None,  # TODO: получить из данных
                daily_fvg=imbalances[0] if imbalances else None,
                volume_profile=None,  # TODO: построить из данных
                limit_orders=None,  # TODO: получить из данных
                liquidity_above=liquidity_above if isinstance(liquidity_above, list) else [],
                liquidity_below=liquidity_below if isinstance(liquidity_below, list) else [],
                recent_wicks=recent_wicks_sm,
                volume_absorption=volume_absorption,
                oi_delta=None,  # TODO: получить из Binance API
                key_levels=eqh_levels + eql_levels
            )
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.warning(f"Smart Money v2 failed: {e}")
            smart_money_analysis = None
        
        # 6. R-asymmetry
        r_asymmetry = None
        try:
            if long_zone and short_zone:
                # Рассчитываем стопы и цели
                long_stop = long_zone.get('start', 0) * 0.995
                long_target = short_zone.get('start', 0)
                short_stop = short_zone.get('end', 0) * 1.005
                short_target = long_zone.get('end', 0)
                
                # ATR из volatility (приблизительно)
                atr = current_price * volatility_val * 0.01 if volatility_val > 0 else current_price * 0.02
                
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
        except Exception:
            r_asymmetry = None
        
        # 7. Conditions for shift
        shift_conditions = None
        try:
            current_volume = volumes[-1] if volumes else None
            avg_volume = sum(volumes) / len(volumes) if volumes else None
            
            # Преобразуем текстовые bias в формат для анализа
            current_bias_enum = "NEUTRAL"
            if "Лонговый" in tactical_bias_text or "LONG" in tactical_bias_text.upper():
                current_bias_enum = "LONG"
            elif "Медвежий" in tactical_bias_text or "SHORT" in tactical_bias_text.upper():
                current_bias_enum = "SHORT"
            
            target_bias_enum = "LONG"
            if "Медвежий" in strategic_bias_text or "SHORT" in strategic_bias_text.upper():
                target_bias_enum = "SHORT"
            elif "Лонговый" in strategic_bias_text or "LONG" in strategic_bias_text.upper():
                target_bias_enum = "LONG"
            
            shift_conditions = self.conditions_shift.analyze_conditions_for_shift(
                current_bias=current_bias_enum,
                target_bias=target_bias_enum,
                current_oi_delta=None,  # TODO: получить из Binance API
                current_volume=current_volume,
                avg_volume=avg_volume,
                liquidity_above=liquidity_above if isinstance(liquidity_above, list) else [],
                current_funding=current_funding,
                structure_level=short_zone.get('start', 0) if short_zone else None,
                break_level=current_price,
                current_momentum=momentum_score
            )
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.warning(f"Conditions shift failed: {e}")
            shift_conditions = None
        
        # 8. Micro-Pattern Engine
        micro_patterns = []
        try:
            if candles and volumes:
                # Вычисляем buy_volume и sell_volume
                buy_volume = []
                sell_volume = []
                price_changes_patterns = []
                
                for i, candle in enumerate(candles):
                    vol = volumes[i] if i < len(volumes) else 0
                    if candle['close'] > candle['open']:
                        buy_volume.append(vol)
                        sell_volume.append(0)
                    else:
                        buy_volume.append(0)
                        sell_volume.append(vol)
                    
                    if i > 0:
                        price_changes_patterns.append((candle['close'] - candles[i-1]['close']) / candles[i-1]['close'])
                
                micro_patterns = self.micro_patterns.detect_all_patterns(
                    candles=candles,
                    volumes=volumes,
                    buy_volume=buy_volume if buy_volume else None,
                    sell_volume=sell_volume if sell_volume else None,
                    price_changes=price_changes_patterns if price_changes_patterns else None,
                    key_levels=eqh_levels + eql_levels,
                    imbalances=imbalances,
                    current_price=current_price
                )
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.warning(f"Micro-patterns failed: {e}")
            micro_patterns = []
        
        # 9. Auto-Calibrated Confidence
        confidence_analysis = None
        try:
            # Формируем tf_scores для конфлюэнса
            tf_scores = {}
            for tf, tf_data in report.per_tf.items():
                tf_scores[tf] = {
                    'direction': report.direction,
                    'score': tf_data.get('normalized_long', 5.0) if report.direction == "LONG" else tf_data.get('normalized_short', 5.0)
                }
            
            confidence_analysis = self.confidence_v2.calculate_full_confidence(
                base_confidence=report.confidence,
                tf_scores=tf_scores,
                indicator_scores={
                    'trend': trend_score,
                    'momentum': momentum_score,
                    'volume': volume_score,
                    'structure': structure_score
                },
                recent_volume=volumes[-1] if volumes else None,
                avg_volume=sum(volumes) / len(volumes) if volumes else None,
                price_direction="up" if momentum_score > 0 else ("down" if momentum_score < 0 else "neutral"),
                oi_delta=None,  # TODO: получить из данных
                volatility=volatility_val,
                avg_volatility=volatility_val,  # TODO: получить среднюю
                regime=regime_analysis.primary_regime.value if regime_analysis else None
            )
        except Exception:
            confidence_analysis = None
        
        # 10. Personalization (пока без пользовательского профиля)
        personalized_recommendation = None
        # TODO: получить user_profile из контекста или БД
        
        # Форматируем новые данные для шаблона
        structural_bias_text = ""
        liquidity_bias_text = ""
        if bias_analysis:
            if hasattr(bias_analysis, 'structural_description') and bias_analysis.structural_description:
                structural_bias_text = bias_analysis.structural_description
            if hasattr(bias_analysis, 'liquidity_description') and bias_analysis.liquidity_description:
                liquidity_bias_text = bias_analysis.liquidity_description
        
        narrative_text = ""
        market_profile_text = ""
        if narrative_summary:
            narrative_text = getattr(narrative_summary, 'narrative_text', '') or ""
            market_profile_text = getattr(narrative_summary, 'behavior_profile', '') or ""
        
        regime_detected = "trend"
        regime_description = ""
        if regime_analysis:
            regime_detected = getattr(regime_analysis.primary_regime, 'value', 'trend') if hasattr(regime_analysis, 'primary_regime') else "trend"
            regime_description = getattr(regime_analysis, 'description', '') or ""
        
        flow_interpretation = ""
        if flow_analysis:
            flow_interpretation = getattr(flow_analysis, 'interpretation', '') or ""
        
        smart_money_narrative = ""
        sfp_prob_1h = 0
        sfp_prob_4h = 0
        if smart_money_analysis:
            smart_money_narrative = getattr(smart_money_analysis, 'narrative_interpretation', '') or ""
            if hasattr(smart_money_analysis, 'sfp_probability') and smart_money_analysis.sfp_probability:
                sfp_prob_1h = getattr(smart_money_analysis.sfp_probability, 'probability_1h', 0) * 100
                sfp_prob_4h = getattr(smart_money_analysis.sfp_probability, 'probability_4h', 0) * 100
        
        r_asymmetry_text = ""
        r_long = 0
        r_short = 0
        r_long_label = "слабый"
        r_short_label = "слабый"
        if r_asymmetry:
            r_asymmetry_text = getattr(r_asymmetry, 'interpretation', '') or ""
            r_long = getattr(r_asymmetry, 'long_r', 0) or 0
            r_short = getattr(r_asymmetry, 'short_r', 0) or 0
            r_long_label = "умеренно" if abs(r_long) > 0.3 else "слабый"
            r_short_label = "умеренно" if abs(r_short) > 0.3 else "слабый"
        
        shift_conditions_text = ""
        if shift_conditions:
            try:
                shift_conditions_text = self.conditions_shift.format_conditions_text(shift_conditions)
            except Exception:
                shift_conditions_text = ""
        
        micro_patterns_text = ""
        if micro_patterns:
            try:
                micro_patterns_text = "\n".join([f"• {getattr(p, 'description', '')}" for p in micro_patterns[:2] if hasattr(p, 'description')])
            except Exception:
                micro_patterns_text = ""
        
        # Форматируем блоки для условного отображения
        shift_conditions_block = ""
        if shift_conditions_text:
            shift_conditions_block = f"\n━━━━━━━━━━━━━━━━━━\n\n🔍 Что должно случиться, чтобы {strategic_bias_text} стал сильным\n\n{shift_conditions_text}\n"
        
        micro_patterns_block = ""
        if micro_patterns_text:
            micro_patterns_block = f"\n━━━━━━━━━━━━━━━━━━\n\n🧩 Micro-Patterns\n\n{micro_patterns_text}\n\n━━━━━━━━━━━━━━━━━━"
        
        confidence_explanation = ""
        confidence_final = report.confidence
        if confidence_analysis:
            confidence_explanation = getattr(confidence_analysis, 'explanation', '') or ""
            confidence_final = getattr(confidence_analysis, 'confidence', report.confidence) or report.confidence
        
        # Breakout trigger из zones
        breakout_trigger = zones.get("breakout_trigger", 0)
        
        # Форматируем блоки для Structural и Liquidity Bias
        structural_bias_block = ""
        if structural_bias_text:
            structural_bias_block = f"Structural Bias: {structural_bias_text}"
        
        liquidity_bias_block = ""
        if liquidity_bias_text:
            liquidity_bias_block = f"Liquidity Bias: {liquidity_bias_text}"
        
        if not narrative_text:
            narrative_text = ""
        
        if not market_profile_text:
            market_profile_text = "рынок в нейтральном состоянии"
        
        if not flow_interpretation:
            flow_interpretation = "Потоки капитала нейтральны"
        
        if not smart_money_narrative:
            smart_money_narrative = "Smart Money в режиме ожидания"
        
        if not shift_conditions_text:
            shift_conditions_text = ""
        
        if not micro_patterns_text:
            micro_patterns_text = ""
        
        if not confidence_explanation:
            confidence_explanation = "Стандартная уверенность"
        
        if not r_asymmetry_text:
            r_asymmetry_text = "Рынок нейтрален по асимметрии"
        
        return {
            "symbol": report.symbol,
            "tf": report.target_tf,
            "decision_label": decision_label,
            "decision_reason": decision_reason,
            "best_action": best_action,
            "regime_icon": regime_emoji,
            "regime_name": regime_name,
            "setup_type_icon": setup_type_emoji,
            "setup_type_name": setup_type_name,
            "confidence_pct": int(confidence_final * 100) if 'confidence_final' in locals() else confidence_pct,
            "confidence_label": confidence_label,
            "main_direction": main_direction,
            "main_score": main_score,
            "score_strength": score_strength,
            "score_bar": score_bar,
            "long_score": report.score_long,
            "short_score": report.score_short,
            "edge_label": edge_label,
            "edge_diff": edge_diff,
            "edge_category_text": edge_category_text,
            "edge_explanation_text": edge_explanation_text,
            "tactical_bias_text": tactical_bias_text,
            "strategic_bias_text": strategic_bias_text,
            "signals_alignment_label": signals_alignment_label,
            "trend_label": trend_label,
            "momentum_label": momentum_label,
            "momentum_bar": momentum_bar,
            "pump_score": pump_score,
            "pump_bar": pump_bar,
            "risk_score": risk_score,
            "risk_bar": risk_bar,
            "liquidity_label": liquidity_label,
            "volatility_label": volatility_label,
            "volatility_bar": volatility_bar,
            "trend_score": trend_score,
            "momentum_score": momentum_score,
            "volume_score": volume_score,
            "structure_score": structure_score,
            "deriv_score": deriv_score,
            "consensus_label": consensus_label,
            "consensus_value": consensus_value,
            "price": current_price,
            "indicators_block": self._format_indicators_block(indicator_values, current_price),
            "demand_zone_low": demand_zone_low,
            "demand_zone_high": demand_zone_high,
            "supply_zone_low": supply_zone_low,
            "supply_zone_high": supply_zone_high,
            "range_position_label": range_position_label,
            "premium_position_label": premium_position_label,
            "premium_position_label_lower": premium_position_label_lower,
            "premium_position_text": premium_position_text,
            "premium_threshold": premium_threshold,
            "discount_threshold": discount_threshold,
            "imbalances_lines": imbalances_lines,
            "fib_near_level_name": fib_near_level_name,
            "fib_near_price": fib_near_price,
            "fib_382": fib_382,
            "fib_500": fib_500,
            "fib_618": fib_618,
            "elliott_pattern": elliott_pattern,
            "elliott_wave": elliott_wave,
            "elliott_trend": elliott_trend,
            "scenario1_name": scenario1.get('name', ''),
            "scenario1_weight_label": scenario1.get('weight_label', ''),
            "scenario1_range_text": scenario1.get('range_text', ''),
            "scenario1_idea": scenario1.get('idea', ''),
            "scenario1_risk_label": scenario1.get('risk_label', ''),
            "scenario1_weight_pct": scenario1_weight_pct,
            "scenario2_name": scenario2.get('name', ''),
            "scenario2_weight_label": scenario2.get('weight_label', ''),
            "scenario2_weight_pct": scenario2_weight_pct,
            "scenario2_condition": scenario2.get('condition', ''),
            "scenario2_targets": scenario2.get('targets', ''),
            "scenario2_risk_label": scenario2.get('risk_label', ''),
            "scenario2_block": scenario2_block,
            "maybe_scenario3_block": self._format_scenario3(scenario3) if scenario3 else "",
            "horizon_hours_min": horizon_hours_min,
            "horizon_hours_max": horizon_hours_max,
            "long_trigger_text": long_trigger_text,
            "short_trigger_text": short_trigger_text,
            "wait_trigger_text": wait_trigger_text,
            "overbought_label": overbought_label,
            "liquidity_label_detailed": liquidity_label_detailed,
            "derivatives_risk_label": derivatives_risk_label,
            "flush_risk_label": flush_risk_label,
            "size_mode_label": size_mode_label,
            "position_size_r_label": position_size_r_label,
            "entry_strategy_text": entry_strategy_text,
            "stop_loss_text": stop_loss_text,
            "targets_text": targets_text,
            "stop_loss_block": stop_loss_block,
            "targets_block": targets_block,
            "risk_mgmt_text": risk_mgmt_text,
            "recommendations_text": recommendations_text,
            "hist_avg_r": hist_avg_r,
            "hist_hit_rate": hist_hit_rate,
            "hist_n_cases": hist_n_cases,
            "hist_comment": hist_comment,
            "tldr_line1": tldr_lines[0] if len(tldr_lines) > 0 else "",
            "tldr_line2": tldr_lines[1] if len(tldr_lines) > 1 else "",
            "tldr_line3": tldr_lines[2] if len(tldr_lines) > 2 else "",
            # Новые поля V2
            "structural_bias_text": structural_bias_text,
            "liquidity_bias_text": liquidity_bias_text,
            "structural_bias_block": structural_bias_block,
            "liquidity_bias_block": liquidity_bias_block,
            "narrative_text": narrative_text,
            "market_profile_text": market_profile_text,
            "regime_detected": regime_detected,
            "regime_description": regime_description,
            "flow_interpretation": flow_interpretation,
            "smart_money_narrative": smart_money_narrative,
            "sfp_prob_1h": sfp_prob_1h,
            "sfp_prob_4h": sfp_prob_4h,
            "r_asymmetry_text": r_asymmetry_text,
            "r_long": r_long,
            "r_short": r_short,
            "r_long_label": r_long_label,
            "r_short_label": r_short_label,
            "risk_score_label": risk_score_label,
            "volatility_description": volatility_description,
            "shift_conditions_text": shift_conditions_text,
            "shift_conditions_block": shift_conditions_block,
            "micro_patterns_text": micro_patterns_text,
            "micro_patterns_block": micro_patterns_block,
            "confidence_explanation": confidence_explanation,
            "confidence_final": confidence_final,
            "breakout_trigger": breakout_trigger
        }
    
    def _get_template(self, context: ReportContext) -> str:
        """Получить шаблон отчета."""
        template = """🏥 Market Doctor — {symbol} | {tf}

━━━━━━━━━━━━━━━━━━

🎯 Решение: {decision_label}

Причина: {decision_reason}

Лучшее действие: {best_action}

━━━━━━━━━━━━━━━━━━

🧠 Режим рынка

Фаза: {regime_name} {regime_icon}

Тип сетапа: {setup_type_name} {setup_type_icon}

Регим: {regime_detected} → {regime_description}
Market Profile: {market_profile_text}
Тактический bias: {tactical_bias_text}
Стратегический bias: {strategic_bias_text}
{structural_bias_block}
{liquidity_bias_block}
Уверенность модели: {confidence_final:.0%} ({confidence_label})
Причины: {confidence_explanation}

━━━━━━━━━━━━━━━━━━

🎯 Оценка направлений

ЛОНГ: {long_score:.1f}/10   ШОРТ: {short_score:.1f}/10   Edge: {edge_diff:+.1f} ({edge_category_text})

{edge_explanation_text}

━━━━━━━━━━━━━━━━━━

📊 Детальный контекст ({tf})

Тренд: {trend_label}
Импульс: {momentum_label}
Micro-regime: {regime_detected}
Pump Score: {pump_score:.2f}
Risk Score: {risk_score:.2f} → {risk_score_label}
Ликвидность: {liquidity_label}, но качество слабое (нет агрессии покупателей)
Волатильность: {volatility_label} → {volatility_description}
Narrative: {narrative_text}

━━━━━━━━━━━━━━━━━━

📈 Консенсус индикаторов ({tf})

Тренд: {trend_score:+.2f} | Импульс: {momentum_score:+.2f} | Объём: {volume_score:+.2f}
Структура: {structure_score:+.2f} | Деривативы: {deriv_score:+.2f}
Консенсус: {consensus_label} ({consensus_value:+.2f})
Дисбаланс между структурой и объёмом → edge нестабилен

━━━━━━━━━━━━━━━━━━

📊 Технические индикаторы ({tf})

{indicators_block}

━━━━━━━━━━━━━━━━━━

💰 Потоки капитала (Flow Engine)

{flow_interpretation}

━━━━━━━━━━━━━━━━━━

📌 Smart Money Map (SMC)

🔹 Текущая цена: {price:.0f}

Позиция: {range_position_label} → рискованный участок.

🟢 ЗОНА СПРОСА (лучший лонг): {demand_zone_low:.0f}–{demand_zone_high:.0f}

Состав: FVG (imbalance), многократные касания, discount зона ниже EQ, подтверждение объёмом (агрессия покупателей)
→ Единственная зона, где лонг даёт математическое преимущество

🔴 ЗОНА ПРЕДЛОЖЕНИЯ (шорт): {supply_zone_low:.0f}–{supply_zone_high:.0f}

Состав: премиум зона, локальные EQH → риск выноса, слабые объёмы, поверхностное давление продавца
→ Шорт только по реакции, не заранее

Smart Money: {smart_money_narrative}
SFP Probability: 1h {sfp_prob_1h:.0f}% | 4h {sfp_prob_4h:.0f}%

💰 PREMIUM / DISCOUNT

Текущая цена: {premium_position_text}
Лучшая цена для лонга: ниже {demand_zone_high:.0f}

📎 ИМБАЛАНСЫ (магниты)

{imbalances_lines}

Цена любит закрывать их в ближайшие 3–12 баров

━━━━━━━━━━━━━━━━━━"""
        
        # Фибоначчи (опционально)
        fibonacci_analysis = getattr(context.report, 'fibonacci_analysis', None) or context.report.smc.get('fibonacci')
        import logging
        logger = logging.getLogger(__name__)
        logger.debug(f"Template Fibonacci check: include_fibonacci={context.include_fibonacci}, has_data={bool(fibonacci_analysis)}, type={type(fibonacci_analysis)}")
        if context.include_fibonacci and fibonacci_analysis:
            template += """
📐 Фибоначчи

Ближайший: {fib_near_level_name} — {fib_near_price:.0f}
Ключевые: 38.2%: {fib_382:.0f} | 50.0%: {fib_500:.0f} | 61.8%: {fib_618:.0f}

━━━━━━━━━━━━━━━━━━"""
        
        # Эллиотт (опционально)
        elliott_waves = getattr(context.report, 'elliott_waves', None) or context.report.smc.get('elliott_waves')
        logger.debug(f"Template Elliott check: include_elliott={context.include_elliott}, has_data={bool(elliott_waves)}, type={type(elliott_waves)}")
        if context.include_elliott and elliott_waves:
            template += """
🌊 Эллиотт

Паттерн: {elliott_pattern} | Волна: {elliott_wave} | Тренд: {elliott_trend}

━━━━━━━━━━━━━━━━━━"""
        
        template += """
📈 Сценарии ({horizon_hours_min}–{horizon_hours_max}ч)

1) {scenario1_name} — {scenario1_weight_label} ({scenario1_weight_pct})

{scenario1_range_text}
Идея: {scenario1_idea}
Цели: long {supply_zone_low:.0f} → {supply_zone_high:.0f} | short {demand_zone_low:.0f}–{demand_zone_high:.0f} (только по реакции)
Риск: {scenario1_risk_label}
{scenario2_block}
{maybe_scenario3_block}

━━━━━━━━━━━━━━━━━━

⚙️ Decision Triggers

🟩 LONG TRIGGER

{long_trigger_text}

🟥 SHORT TRIGGER

Реакция продавца в зоне {supply_zone_low:.0f}–{supply_zone_high:.0f}: поглощение, SFP, потеря объёма, расхождение имбаланса

🔵 WAIT ZONE

{wait_trigger_text} = зона без edge

━━━━━━━━━━━━━━━━━━

⚠️ Risk Board

Перекупленность: {overbought_label} | Ликвидность: {liquidity_label_detailed}
Funding/OI: {derivatives_risk_label} | Риск flush: {flush_risk_label}

━━━━━━━━━━━━━━━━━━

💡 Практические рекомендации (не финсовет)

🎯 Про лонги

{entry_strategy_text}
{stop_loss_block}{targets_block}
Размер: {position_size_r_label}R ({size_mode_label})

🎯 Про шорты

Только при подтверждении реакции в {supply_zone_low:.0f}–{supply_zone_high:.0f}
Инвалидация: выше {breakout_trigger:.0f}
Размер: {position_size_r_label}R ({size_mode_label})

⏰ Горизонт

{horizon_hours_min}–{horizon_hours_max} часа

━━━━━━━━━━━━━━━━━━

⚖️ R-Асимметрия текущего входа

Long: {r_long:+.2f}R ({r_long_label}) | Short: {r_short:+.2f}R ({r_short_label})
→ {r_asymmetry_text}
{shift_conditions_block}
{micro_patterns_block}

━━━━━━━━━━━━━━━━━━"""
        
        # История (опционально)
        if context.include_history and context.report.smc.get('history'):
            template += """
📚 История похожих сетапов:

   • Средний результат: {hist_avg_r:+.2f}R

   • Hit-rate (R > 0): {hist_hit_rate:.0f}% по {hist_n_cases} кейсам

   • Краткий вывод: {hist_comment}

━━━━━━━━━━━━━━━━━━"""
        
        template += """
TL;DR:

{tldr_line1}

{tldr_line2}

{tldr_line3}"""
        
        return template
    
    def _get_brief_template(self, context: ReportContext) -> str:
        """Получить краткий шаблон отчета (V4 Short & Smart)."""
        template = """🏥 Market Doctor — {symbol} | {tf}

РЕШЕНИЕ: {decision_label}

{decision_reason}

🧠 Market Regime

Режим: {regime_name}
Микрорежим: {regime_detected} ({momentum_label})
Bias: Тактический — {tactical_bias_text} │ Стратегический — {strategic_bias_text}
Уверенность модели: {confidence_final:.0%} ({confidence_label})

Главное: {narrative_text}

🎯 Направления

ЛОНГ: {long_score:.1f} / 10
ШОРТ: {short_score:.1f} / 10
Edge: {edge_diff:+.1f} → {edge_category_text}

📍 Smart Money Map ({tf})

Цена: {price:.0f}
Локация: {range_position_label}

🟢 Лонг-зона (единственная зона с edge)
{demand_zone_low:.0f}–{demand_zone_high:.0f}
(Discount + FVG + подтверждения объёмом)

🔴 Шорт-зона (по реакции)
{supply_zone_low:.0f}–{supply_zone_high:.0f}
(Premium + EQH стопы сверху)

🧲 FVG (магниты)
{imbalances_lines}

📈 Сценарии ({horizon_hours_min}–{horizon_hours_max}ч)

{scenario1_name} (≈{scenario1_weight_pct})
{scenario1_range_text}
{scenario1_idea}

{scenario2_block}

⚙️ Decision Triggers

🟩 LONG
• {long_trigger_text}

🟥 SHORT
• Реакция продавца в зоне {supply_zone_low:.0f}–{supply_zone_high:.0f} (SFP / поглощение / падение объёмов)

🔵 WAIT
{wait_trigger_text} → зона без edge

⚠️ Risk Board

Перекупленность: {overbought_label}
Ликвидность: {liquidity_label_detailed}
Funding/OI: {derivatives_risk_label}
Flush-risk: {flush_risk_label}

🎯 Рекомендации (не финсовет)

ЛОНГ
{entry_strategy_text}
{stop_loss_block}
Размер: {position_size_r_label}R

ШОРТ (контртренд)
Только по реакции {supply_zone_low:.0f}–{supply_zone_high:.0f}
Инвалидация: > {breakout_trigger:.0f}
Размер: {position_size_r_label}R

TL;DR

{decision_reason}

Лучшие зоны:
Лонг: {demand_zone_low:.0f}–{demand_zone_high:.0f}
Шорт: {supply_zone_low:.0f}–{supply_zone_high:.0f}

Пока: {decision_label}"""
        
        return template
    
    # Вспомогательные методы для форматирования
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
    
    def _translate_regime(self, regime: str) -> str:
        """Перевести режим на русский."""
        regime_map = {
            "ACCUMULATION": "Накопление",
            "DISTRIBUTION": "Распределение",
            "EXPANSION_UP": "Расширение вверх",
            "EXPANSION_DOWN": "Расширение вниз",
            "SHAKEOUT": "Встряска"
        }
        return regime_map.get(regime, regime)
    
    def _get_setup_emoji(self, setup_type: Optional[str]) -> str:
        """Получить эмодзи для типа сетапа."""
        if not setup_type:
            return "📊"
        emoji_map = {
            "TREND_CONTINUATION": "➡️",
            "REVERSAL": "🔄",
            "RANGE_PLAY": "↔️",
            "BREAKOUT": "🚀",
            "MEAN_REVERSION": "↩️"
        }
        return emoji_map.get(setup_type, "📊")
    
    def _translate_trend(self, trend: str) -> str:
        """Перевести тренд на русский."""
        trend_map = {
            "BULLISH": "Бычий",
            "BEARISH": "Медвежий",
            "NEUTRAL": "Нейтральный"
        }
        return trend_map.get(trend.upper(), trend)
    
    def _get_momentum_summary_ru(self, tf_data: dict) -> str:
        """Получить краткое описание импульса на русском."""
        raw_scores = tf_data.get('raw_scores', {})
        momentum_score = raw_scores.get('momentum', 0)
        
        mi = tf_data.get("momentum_insight")
        if mi:
            regime = mi.get("regime")
            bias = mi.get("bias")
            strength = mi.get("strength", 0.0)
            
            # Если momentum_score отрицательный, приоритет на ослабление
            if momentum_score < -0.2:
                if regime == "EXHAUSTION":
                    return "Импульс выдыхается"
                else:
                    return "Импульс ослабевает"
            elif regime == "EXHAUSTION":
                return "Импульс выдыхается"
            elif regime == "CONTINUATION":
                return f"Сильный импульс по тренду" if strength > 0.6 else "Импульс по тренду"
            elif regime == "REVERSAL_RISK":
                return "Локальный импульс против тренда"
        
        # Проверяем численное значение импульса
        if momentum_score < -0.3:
            return "Импульс ослабевает"
        elif momentum_score < -0.1:
            return "Слабый импульс, рынок тормозит"
        elif momentum_score > 0.5:
            return "Сильный"
        elif momentum_score > 0:
            return "Слабый"
        else:
            return "Нейтральный"
    
    def _get_liquidity_summary_ru(self, report: CompactReport) -> str:
        """Получить краткое описание ликвидности."""
        target_tf_data = report.per_tf.get(report.target_tf, {})
        risk_score = target_tf_data.get('risk_score', 0.5)
        
        if risk_score > 0.6:
            return "Ниже среднего"
        elif risk_score > 0.4:
            return "Средняя"
        else:
            return "Выше среднего"
    
    def _get_volatility_summary_ru(self, tf_data: dict) -> str:
        """Получить краткое описание волатильности."""
        raw_scores = tf_data.get('raw_scores', {})
        vol_score = raw_scores.get('volatility', 0)
        
        if abs(vol_score) > 0.5:
            return "Высокая"
        elif abs(vol_score) > 0.2:
            return "Средняя"
        else:
            return "Низкая"
    
    def _get_score_bar_normalized(self, score: float, scale: int = 10) -> str:
        """Визуализация score."""
        filled = int(score)
        bar = "█" * filled + "░" * (scale - filled)
        return f"[{bar}]"
    
    def _get_score_bar_directional(self, score: float) -> str:
        """Визуализация score с направлением."""
        normalized = (score + 2) / 4 * 10
        normalized = max(0, min(10, normalized))
        filled = int(normalized)
        if score > 0:
            bar = "↑" * filled + "░" * (10 - filled)
        elif score < 0:
            bar = "↓" * filled + "░" * (10 - filled)
        else:
            bar = "─" * filled + "░" * (10 - filled)
        return f"[{bar}]"
    
    def _get_percentage_bar(self, percentage: float, length: int = 10) -> str:
        """Визуализация процентов."""
        percentage = max(0, min(100, percentage))
        filled = int(percentage / 100 * length)
        bar = "█" * filled + "░" * (length - filled)
        return f"[{bar}]"
    
    def _get_range_position_label(self, price_position: PricePosition, current_price: float, long_zone: dict, short_zone: dict) -> str:
        """Получить описание позиции в диапазоне."""
        # Проверяем реальное расположение относительно зон
        in_long_zone = long_zone and long_zone.get("start", 0) <= current_price <= long_zone.get("end", 0)
        in_short_zone = short_zone and short_zone.get("start", 0) <= current_price <= short_zone.get("end", 0)
        
        if in_long_zone:
            return "в нижней части диапазона, ближе к зоне спроса"
        elif in_short_zone:
            return "в верхней части диапазона, ближе к зоне предложения"
        elif price_position == PricePosition.DISCOUNT:
            return "ближе к нижней части диапазона"
        elif price_position == PricePosition.PREMIUM:
            return "ближе к верхней части диапазона"
        else:
            return "в середине диапазона"
    
    def _get_premium_position_label(self, premium_discount: dict) -> str:
        """Получить описание позиции premium/discount с проверкой реальных значений."""
        if not premium_discount:
            return "Нейтрально"
        
        # Проверяем реальные значения цены относительно порогов
        current_price = premium_discount.get('current_price')
        premium_start = premium_discount.get('premium_start')
        discount_end = premium_discount.get('discount_end')
        
        if current_price and premium_start and current_price >= premium_start:
            return "Премиум"
        elif current_price and discount_end and current_price <= discount_end:
            return "Дисконт"
        
        # Если цена близка к премиум-порогу (в пределах 0.5%), считаем "рядом с премиум-зоной"
        if current_price and premium_start:
            distance_pct = abs(current_price - premium_start) / premium_start if premium_start > 0 else 1.0
            if current_price < premium_start and distance_pct < 0.005:  # В пределах 0.5%
                return "Нейтрально"  # Будем использовать "рядом с премиум-зоной" в тексте
        
        # Fallback на текстовое значение (если нет числовых данных)
        current_pos = premium_discount.get('current_position', 'neutral')
        if current_pos == "premium":
            return "Премиум"
        elif current_pos == "discount":
            return "Дисконт"
        return "Нейтрально"
    
    def _format_imbalances(self, imbalances: List[dict], current_price: float) -> str:
        """Форматировать имбалансы (FVG)."""
        if not imbalances:
            return ""
        
        lines = []
        lines.append("📎 Незакрытые зоны дисбаланса (FVG):")
        for imb in imbalances[:3]:  # Максимум 3
            if imb.get('filled', False):
                continue
            imb_low = imb.get('price_low', 0)
            imb_high = imb.get('price_high', 0)
            direction = "над текущей ценой" if (imb_low + imb_high) / 2 > current_price else "под текущей ценой"
            lines.append(f"• {imb_low:.0f}–{imb_high:.0f} ({direction})")
        
        return "\n".join(lines) if lines else ""
    
    def _get_scenarios(self, context: ReportContext) -> List[dict]:
        """Получить сценарии."""
        # Используем существующую логику из _format_probabilistic_scenarios
        # Упрощенная версия для шаблона
        report = context.report
        target_tf_data = report.per_tf.get(report.target_tf, {})
        pump_score = target_tf_data.get('pump_score', 0.5)
        risk_score = target_tf_data.get('risk_score', 0.5)
        confidence = report.confidence
        zones = context.zones
        
        scenarios = []
        
        # Range scenario
        long_zone = zones.get("long_zone")
        short_zone = zones.get("short_zone")
        current_price = report.smc.get('current_price', 0)
        if long_zone and short_zone:
            weight_range = 1 - abs(pump_score - 0.5) * 2
            range_text = f'Цена продолжает торговаться внутри диапазона {long_zone["start"]:.0f}–{short_zone["end"]:.0f}, без выхода за границы спроса и предложения'
            
            # Добавляем фразу про верхнюю треть диапазона, если цена там
            if current_price:
                range_size = short_zone["end"] - long_zone["start"]
                price_position_in_range = (current_price - long_zone["start"]) / range_size if range_size > 0 else 0.5
                if price_position_in_range > 0.67:  # Верхняя треть
                    range_text += f'. Цена сейчас находится в верхней трети диапазона — зона, где edge минимальный'
            
            scenarios.append({
                'name': 'Range + Pullback',
                'weight': weight_range,
                'weight_label': self._scenario_weight_label(weight_range),
                'range_text': range_text,
                'idea': f'Лучший вход: {long_zone["start"]:.0f}–{long_zone["end"]:.0f}. Цели: {short_zone["start"]:.0f}–{short_zone["end"]:.0f}',
                'risk_label': 'средний риск в диапазоне'
            })
        
        # Breakout scenario
        if report.direction == "LONG" or pump_score > 0.6:
            weight_bull = pump_score * 0.7 + confidence * 0.3
            breakout_trigger = zones.get("breakout_trigger")
            if breakout_trigger:
                target1 = breakout_trigger * 1.025
                target2 = breakout_trigger * 1.10
                scenarios.append({
                    'name': 'Bullish Breakout',
                    'weight': weight_bull,
                    'weight_label': self._scenario_weight_label(weight_bull),
                    'condition': f'Требуется пробой {breakout_trigger:.0f} и закрепление',
                    'targets': f'{target1:.0f} → {target2:.0f}',
                    'risk_label': 'стандартный риск' if (1 - risk_score) >= 0.6 else 'низкая ликвидность → возможен ложный пробой'
                })
        
        # Сортируем по весу
        scenarios.sort(key=lambda x: x['weight'], reverse=True)
        
        # Убеждаемся, что только один сценарий помечен как "основной"
        if scenarios:
            # Первый (с наибольшим весом) - основной, остальные - альтернативные
            scenarios[0]['weight_label'] = self._scenario_weight_label(scenarios[0]['weight'])
            for i in range(1, len(scenarios)):
                # Если вес близок к первому, оставляем как есть, иначе помечаем как альтернативный
                if scenarios[i]['weight'] >= 0.5 and scenarios[i]['weight'] >= scenarios[0]['weight'] * 0.8:
                    scenarios[i]['weight_label'] = self._scenario_weight_label(scenarios[i]['weight'])
                else:
                    scenarios[i]['weight_label'] = "альтернативный"
        
        return scenarios
    
    def _format_scenario3(self, scenario3: dict) -> str:
        """Форматировать третий сценарий (если есть)."""
        if not scenario3:
            return ""
        return f"""3) {scenario3.get('name', '')} — {scenario3.get('weight_label', '')} сценарий:

   • {scenario3.get('condition', '')}

   • Цели: {scenario3.get('targets', '')}

   • Риск: {scenario3.get('risk_label', '')}

━━━━━━━━━━━━━━━━━━"""
    
    def _format_decision_triggers(self, context: ReportContext) -> Tuple[str, str, str]:
        """Форматировать Decision Triggers."""
        zones = context.zones
        long_zone = zones.get("long_zone")
        short_zone = zones.get("short_zone")
        wait_zone = zones.get("wait_zone")
        breakout_trigger = zones.get("breakout_trigger")
        
        # LONG trigger
        long_parts = []
        if long_zone:
            long_parts.append(f"Цена возвращается в {long_zone['start']:.0f}–{long_zone['end']:.0f}")
        if breakout_trigger:
            long_parts.append(f"или закрепляется выше {breakout_trigger:.0f} с объёмом")
        long_trigger_text = "\n".join(long_parts) if long_parts else "Нет четких условий для лонга"
        
        # SHORT trigger
        short_parts = []
        if short_zone:
            short_parts.append(f"Реакция продавца в зоне {short_zone['start']:.0f}–{short_zone['end']:.0f}")
        short_trigger_text = "\n".join(short_parts) if short_parts else "Нет четких условий для шорта"
        
        # WAIT trigger
        if wait_zone:
            wait_trigger_text = f"{wait_zone['start']:.0f}–{wait_zone['end']:.0f}"
        else:
            wait_trigger_text = "Середина диапазона"
        
        return long_trigger_text, short_trigger_text, wait_trigger_text
    
    def _get_derivatives_risk_label(self, pump_score: float, risk_score: float) -> str:
        """Вербальный ярлык для деривативов."""
        if pump_score > 0.7 and risk_score < 0.4:
            return "подтверждает импульс"
        elif pump_score < 0.4:
            return "не подтверждает импульс (импульс не подтверждён деривативами)"
        return "нейтральные"
    
    def _get_flush_risk_label(self, context: ReportContext) -> str:
        """Вербальный ярлык для риска flush."""
        target_tf_data = context.report.per_tf.get(context.report.target_tf, {})
        risk_score = target_tf_data.get('risk_score', 0.5)
        premium_discount = context.report.smc.get('premium_discount', {})
        current_pos = premium_discount.get('current_position', 'neutral') if premium_discount else 'neutral'
        
        # Премиум + высокий риск + выдыхающийся импульс -> повышенная
        momentum_insight = target_tf_data.get('momentum_insight', {})
        is_exhaustion = momentum_insight.get('regime') == "EXHAUSTION" if momentum_insight else False
        
        if risk_score > 0.65 or (current_pos == "premium" and is_exhaustion):
            return "повышенная"
        elif risk_score > 0.45:
            return "средняя"
        else:
            return "низкая"
    
    def _get_entry_strategy(self, decision: Decision, context: ReportContext) -> Tuple[str, str, str]:
        """Получить стратегию входа, стоп-лосс и цели."""
        zones = context.zones
        long_zone = zones.get("long_zone")
        short_zone = zones.get("short_zone")
        current_price = context.report.smc.get('current_price', 0)
        report = context.report
        edge_diff = report.score_long - report.score_short
        
        # Для WAIT с минимальным edge - не даем активных рекомендаций
        if decision == Decision.WAIT and abs(edge_diff) < 1.0:
            return "Наблюдение за реакцией на границах диапазона", "N/A", "N/A"
        
        if decision == Decision.LONG and long_zone:
            entry = f"Вход от {long_zone['start']:.0f}–{long_zone['end']:.0f} по сигналам разворота"
            stop = f"ниже {long_zone['start'] * 0.995:.0f} (~{((current_price - long_zone['start'] * 0.995) / current_price * 100) if current_price > 0 else 0:.1f}%)"
            if short_zone:
                targets = f"{short_zone['start']:.0f}–{short_zone['end']:.0f}"
            else:
                targets = "по структуре"
            return entry, stop, targets
        
        elif decision == Decision.SHORT and short_zone:
            entry = f"Вход от {short_zone['start']:.0f}–{short_zone['end']:.0f} по сигналам разворота"
            stop = f"выше {short_zone['end'] * 1.005:.0f} (~{((short_zone['end'] * 1.005 - current_price) / current_price * 100) if current_price > 0 else 0:.1f}%)"
            if long_zone:
                targets = f"{long_zone['start']:.0f}–{long_zone['end']:.0f}"
            else:
                targets = "по структуре"
            return entry, stop, targets
        
        return "Наблюдение", "N/A", "N/A"
    
    def _get_risk_mgmt_text(self, risk_score: float) -> str:
        """Получить текст управления риском."""
        if risk_score > 0.7:
            return "Высокий риск — использовать более узкие стопы, уменьшить размер позиции на 25-30%"
        elif risk_score > 0.5:
            return "Умеренный риск — стандартные стопы, следить за подтверждением объёмом"
        else:
            return "Низкий риск — можно использовать стандартные стопы, хорошая ликвидность"
    
    def _get_history_data(self, context: ReportContext) -> Tuple[float, float, int, str]:
        """Получить исторические данные (заглушка, можно расширить)."""
        # Пока возвращаем дефолтные значения
        # В будущем можно интегрировать с CalibrationService
        return 0.0, 0.0, 0, "Недостаточно данных для статистики"
    
    def _format_recommendations(
        self,
        decision: Decision,
        context: ReportContext,
        entry_strategy_text: str,
        stop_loss_text: str,
        targets_text: str,
        size_mode_label: str,
        position_size_r_label: str,
        risk_mgmt_text: str
    ) -> str:
        """Форматировать рекомендации в зависимости от решения."""
        report = context.report
        zones = context.zones
        long_zone = zones.get("long_zone")
        short_zone = zones.get("short_zone")
        edge_diff = report.score_long - report.score_short
        strategic_bias = report.direction
        
        lines = []
        
        if decision == Decision.WAIT:
            # Для WAIT с минимальным edge - не даем активных рекомендаций
            if abs(edge_diff) < 1.0:
                lines.append("Режим: наблюдение")
                lines.append("")
                lines.append("По текущим ценам входы не оправданы — лучше наблюдать и ждать реакции на границах диапазона.")
                if long_zone and short_zone:
                    lines.append("")
                    lines.append("Рабочие зоны для будущих входов:")
                    lines.append(f"• Лонг: от {long_zone['start']:.0f}–{long_zone['end']:.0f} (только при подтверждении разворота)")
                    lines.append(f"• Шорт: от {short_zone['start']:.0f}–{short_zone['end']:.0f} (только при подтверждении разворота)")
            else:
                # Есть небольшой edge
                lines.append(f"Размер позиции: {size_mode_label} ({position_size_r_label}R)")
                lines.append("")
                lines.append(f"Стратегия входа: {entry_strategy_text}")
                if stop_loss_text != "N/A":
                    lines.append(f"Стоп-лосс: {stop_loss_text}")
                if targets_text != "N/A":
                    lines.append(f"Цели: {targets_text}")
                lines.append("")
                lines.append(f"Управление риском: {risk_mgmt_text}")
        elif decision == Decision.LONG:
            lines.append(f"Размер позиции: {size_mode_label} ({position_size_r_label}R)")
            lines.append("")
            lines.append(f"Стратегия входа: {entry_strategy_text}")
            if stop_loss_text != "N/A":
                lines.append(f"Стоп-лосс: {stop_loss_text}")
            if targets_text != "N/A":
                lines.append(f"Цели: {targets_text}")
            lines.append("")
            lines.append(f"Управление риском: {risk_mgmt_text}")
            
            # Для шорта (контртренд) если стратегический bias медвежий
            if strategic_bias == "SHORT" and short_zone:
                lines.append("")
                lines.append("Для шорта (контртренд):")
                lines.append(f"Только при явном отклонении от {short_zone['start']:.0f}–{short_zone['end']:.0f}")
                breakout_trigger = zones.get("breakout_trigger")
                if breakout_trigger:
                    lines.append(f"Инвалидация: выше {breakout_trigger:.0f}")
        elif decision == Decision.SHORT:
            lines.append(f"Размер позиции: {size_mode_label} ({position_size_r_label}R)")
            lines.append("")
            lines.append(f"Стратегия входа: {entry_strategy_text}")
            if stop_loss_text != "N/A":
                lines.append(f"Стоп-лосс: {stop_loss_text}")
            if targets_text != "N/A":
                lines.append(f"Цели: {targets_text}")
            lines.append("")
            lines.append(f"Управление риском: {risk_mgmt_text}")
        
        return "\n".join(lines)
    
    def _generate_tldr_lines(self, context: ReportContext, decision: Decision, decision_reason: str) -> List[str]:
        """Сгенерировать строки TL;DR - компактный и ударный вариант."""
        report = context.report
        zones = context.zones
        long_zone = zones.get("long_zone")
        short_zone = zones.get("short_zone")
        breakout_trigger = zones.get("breakout_trigger")
        current_price = report.smc.get('current_price', 0)
        
        lines = []
        
        # Определяем позицию цены
        premium_discount = report.smc.get('premium_discount', {})
        premium_start = premium_discount.get('premium_start', 0) if premium_discount else 0
        in_premium = current_price >= premium_start if premium_start > 0 and current_price > 0 else False
        
        # Строка 1: Позиция + решение
        if decision == Decision.WAIT:
            if in_premium:
                lines.append("Цена в премиум-зоне, середина диапазона → входов здесь нет.")
            else:
                lines.append("Рынок в середине диапазона → входов здесь нет.")
        elif decision == Decision.LONG:
            lines.append(f"Лонг-сетап: вход от {long_zone['start']:.0f}–{long_zone['end']:.0f}." if long_zone else "Лонг-сетап.")
        elif decision == Decision.SHORT:
            lines.append(f"Шорт-сетап: вход от {short_zone['start']:.0f}–{short_zone['end']:.0f}." if short_zone else "Шорт-сетап.")
        
        # Строка 2: Рабочие зоны
        if long_zone and short_zone:
            lines.append(f"Рабочие зоны: лонг {long_zone['start']:.0f}–{long_zone['end']:.0f}, шорт {short_zone['start']:.0f}–{short_zone['end']:.0f}.")
        elif long_zone:
            lines.append(f"Рабочая зона: лонг {long_zone['start']:.0f}–{long_zone['end']:.0f}.")
        elif short_zone:
            lines.append(f"Рабочая зона: шорт {short_zone['start']:.0f}–{short_zone['end']:.0f}.")
        
        # Строка 3: Breakout или ожидание зоны
        if decision == Decision.WAIT:
            if long_zone:
                # Показываем зону спроса для ожидания
                lines.append(f"Ждать цену {long_zone['start']:.0f}–{long_zone['end']:.0f}")
            elif breakout_trigger:
                lines.append(f"Breakout: только выше {breakout_trigger:.0f}. Пока: наблюдение.")
            else:
                lines.append("Пока: наблюдение.")
        elif breakout_trigger:
            lines.append(f"Breakout: только выше {breakout_trigger:.0f}. Пока: наблюдение.")
        else:
            if long_zone or short_zone:
                lines.append("Ждать подтверждения сигнала.")
            else:
                lines.append("Пока: наблюдение.")
        
        return lines[:3]  # Максимум 3 строки
    
    def _format_indicators_block(self, indicator_values: dict, current_price: float) -> str:
        """Форматировать блок с конкретными значениями индикаторов."""
        lines = []
        
        # RSI
        rsi = indicator_values.get('rsi')
        if rsi is not None:
            rsi_status = "🟢" if rsi < 30 else "🔴" if rsi > 70 else "🟡"
            lines.append(f"RSI (14): {rsi:.1f} {rsi_status}")
        
        # MACD
        macd = indicator_values.get('macd')
        macd_signal = indicator_values.get('macd_signal')
        macd_hist = indicator_values.get('macd_hist')
        if macd is not None and macd_signal is not None:
            macd_status = "🟢" if macd_hist and macd_hist > 0 else "🔴" if macd_hist and macd_hist < 0 else "🟡"
            hist_val = macd_hist if macd_hist is not None else 0.0
            lines.append(f"MACD: {macd:.2f} | Signal: {macd_signal:.2f} | Hist: {hist_val:.2f} {macd_status}")
        
        # Bollinger Bands
        bb_upper = indicator_values.get('bb_upper')
        bb_middle = indicator_values.get('bb_middle')
        bb_lower = indicator_values.get('bb_lower')
        if bb_upper is not None and bb_lower is not None:
            bb_position = ""
            if current_price > 0:
                if current_price >= bb_upper:
                    bb_position = " (цена выше верхней полосы)"
                elif current_price <= bb_lower:
                    bb_position = " (цена ниже нижней полосы)"
                else:
                    bb_position = " (цена внутри полос)"
            lines.append(f"Bollinger Bands: {bb_upper:.0f} / {bb_middle:.0f} / {bb_lower:.0f}{bb_position}")
        
        # Stochastic RSI
        stoch_k = indicator_values.get('stoch_rsi_k')
        stoch_d = indicator_values.get('stoch_rsi_d')
        if stoch_k is not None and stoch_d is not None:
            stoch_status = "🟢" if stoch_k < 20 and stoch_d < 20 else "🔴" if stoch_k > 80 and stoch_d > 80 else "🟡"
            lines.append(f"Stoch RSI: K={stoch_k:.1f} D={stoch_d:.1f} {stoch_status}")
        
        # ATR
        atr = indicator_values.get('atr')
        if atr is not None and current_price > 0:
            atr_pct = (atr / current_price) * 100
            lines.append(f"ATR (14): {atr:.0f} ({atr_pct:.2f}%)")
        
        # ADX
        adx = indicator_values.get('adx')
        if adx is not None:
            adx_strength = "сильный" if adx > 25 else "слабый" if adx < 20 else "умеренный"
            lines.append(f"ADX (14): {adx:.1f} ({adx_strength} тренд)")
        
        # EMA
        ema_20 = indicator_values.get('ema_20')
        ema_50 = indicator_values.get('ema_50')
        ema_200 = indicator_values.get('ema_200')
        if ema_20 is not None or ema_50 is not None or ema_200 is not None:
            ema_parts = []
            if ema_20 is not None:
                ema_parts.append(f"EMA20: {ema_20:.0f}")
            if ema_50 is not None:
                ema_parts.append(f"EMA50: {ema_50:.0f}")
            if ema_200 is not None:
                ema_parts.append(f"EMA200: {ema_200:.0f}")
            if ema_parts:
                lines.append(" | ".join(ema_parts))
        
        if not lines:
            return "Индикаторы: данные недоступны"
        
        return "\n".join(lines)

