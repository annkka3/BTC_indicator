# app/domain/market_diagnostics/trade_planner.py
"""
Планировщик торговых действий на основе диагностики рынка.

Генерирует конкретные подсказки:
- Можно ли брать небольшую позицию сейчас
- Где зона лимитных ордеров
- Уровень пробоя для добавления позиции
- Уровень выше которого не усреднять
"""

from dataclasses import dataclass
from typing import Optional, Tuple
import pandas as pd
import numpy as np

from .analyzer import MarketDiagnostics, MarketPhase
from .features import TrendState, VolatilityState, LiquidityState
from .config import MarketDoctorConfig, DEFAULT_CONFIG
from .momentum_intelligence import MomentumIntelligence, MomentumInsight
from ..market_regime import GlobalRegime


@dataclass
class TradePlan:
    """План торговых действий на основе диагностики рынка."""
    mode: str  # "neutral", "accumulation_play", "trend_follow", "distribution_wait"
    small_position_allowed: bool  # Можно ли брать небольшую позицию сейчас
    small_position_comment: str  # Комментарий к небольшой позиции
    
    limit_buy_zone: Optional[Tuple[float, float]] = None  # (low, high) - зона лимитных ордеров
    limit_buy_comment: Optional[str] = None  # Комментарий к лимитной зоне
    
    add_on_breakout_level: Optional[float] = None  # Уровень пробоя для добавления позиции
    add_on_breakout_comment: Optional[str] = None  # Комментарий к пробою
    
    dont_dca_above: Optional[float] = None  # Уровень выше которого не усреднять
    dont_dca_comment: Optional[str] = None  # Комментарий к уровню DCA
    
    # Новые поля
    skip_trading: bool = False  # Не торговать этот актив вообще
    skip_trading_comment: Optional[str] = None  # Комментарий почему не торговать
    position_size_factor: Optional[float] = None  # Коэффициент размера позиции (0.5-1.5)
    position_size_comment: Optional[str] = None  # Комментарий к размеру позиции
    scenario_playbook: Optional[str] = None  # Сценарный плейбук
    reliability_score: Optional[float] = None  # Надёжность паттерна (0.0-1.0)
    reliability_samples: Optional[int] = None  # Количество образцов для reliability
    regime_info: Optional[str] = None  # Информация о режиме рынка
    tradability_info: Optional[str] = None  # Информация о ликвидности
    sentiment_info: Optional[str] = None  # Информация о сентименте и новостях
    effective_threshold: Optional[float] = None  # Адаптивный порог pump_score
    threshold_samples: Optional[int] = None  # Количество образцов для threshold
    backtest_stats: Optional[dict] = None  # Статистика бэктеста для паттерна


class TradePlanner:
    """Планировщик торговых действий."""
    
    def __init__(self, config: MarketDoctorConfig = None):
        """
        Инициализация планировщика.
        
        Args:
            config: Конфигурация Market Doctor. Если None, используется DEFAULT_CONFIG
        """
        self.config = config or DEFAULT_CONFIG
        self.momentum_intel = MomentumIntelligence()
    
    @staticmethod
    def _extract_regime(regime) -> Optional[GlobalRegime]:
        """
        Извлечь GlobalRegime из regime, независимо от того, является ли он
        RegimeSnapshot или GlobalRegime напрямую.
        
        Args:
            regime: RegimeSnapshot или GlobalRegime или None
        
        Returns:
            GlobalRegime или None
        """
        if regime is None:
            return None
        
        # Если это RegimeSnapshot, извлекаем вложенный GlobalRegime
        if hasattr(regime, 'regime'):
            return regime.regime
        
        # Если это уже GlobalRegime, возвращаем как есть
        if isinstance(regime, GlobalRegime):
            return regime
        
        return None
    
    def build_plan(
        self,
        diag: MarketDiagnostics,
        df: pd.DataFrame,
        indicators: dict,
        mode: str = "auto",
        regime: Optional[GlobalRegime] = None,
        features: Optional[dict] = None,
        momentum_insight: Optional[MomentumInsight] = None,
        derivatives: Optional[dict] = None,
    ) -> TradePlan:
        """
        Построить план торговых действий на основе диагностики.
        
        Args:
            diag: Результаты диагностики рынка
            df: DataFrame с OHLCV данными
            indicators: Словарь с рассчитанными индикаторами
            mode: Режим стратегии ("auto", "accumulation_play", "trend_follow", "mean_reversion")
            regime: Глобальный режим рынка
            features: Словарь признаков (опционально, для MomentumIntelligence)
            momentum_insight: MomentumInsight (опционально, если не передан - вычисляется внутри)
        
        Returns:
            TradePlan с торговыми подсказками
        """
        close = df['close']
        current_price = close.iloc[-1]
        
        # Вычисляем MomentumInsight, если не передан
        if momentum_insight is None:
            try:
                # Получаем derivatives из features, если доступны
                derivatives_data = None
                if derivatives:
                    derivatives_data = derivatives
                elif features:
                    derivatives_data = features.get('derivatives')
                momentum_insight = self.momentum_intel.analyse(diag, indicators, features, derivatives_data)
            except Exception:
                momentum_insight = None
        
        # Определяем режим торговли (если auto - выбираем автоматически)
        if mode == "auto":
            mode = self._determine_mode(diag)
        
        # Можно ли брать небольшую позицию сейчас (с учетом MomentumInsight)
        small_allowed, small_comment = self._small_position_allowed(diag, mode, momentum_insight)
        
        # В зависимости от режима стратегии строим разные планы
        if mode == "trend_follow":
            # Тренд-фолловинг: игнорируем лимитки ниже, работаем с пробоями
            limit_zone = None
            limit_comment = None
            breakout_level = self._find_breakout_level(df, indicators, current_price, diag)
            breakout_comment = None
            if breakout_level:
                breakout_comment = (
                    f"Тренд-фолловинг: добавлять позицию после закрепления выше {breakout_level:.4f} "
                    f"(пробой сопротивлений). Перезаходы на откатах к поддержкам."
                )
            dont_dca_level = self._find_dont_dca_level(df, indicators, current_price, diag)
            dont_dca_comment = None
            if dont_dca_level:
                dont_dca_comment = (
                    f"Выше {dont_dca_level:.4f} — зона распределения. "
                    f"Фиксировать прибыль, не усреднять."
                )
        elif mode == "mean_reversion":
            # Mean reversion: строим уровни вокруг VWAP/Bollinger basis
            limit_zone = self._find_mean_reversion_zone(df, indicators, current_price)
            limit_comment = None
            if limit_zone:
                low, high = limit_zone
                limit_comment = (
                    f"Mean reversion: зона возврата к среднему {low:.4f}–{high:.4f} "
                    f"(около VWAP/Bollinger basis)."
                )
            breakout_level = None
            breakout_comment = None
            dont_dca_level = self._find_mean_reversion_resistance(df, indicators, current_price)
            dont_dca_comment = None
            if dont_dca_level:
                dont_dca_comment = (
                    f"Выше {dont_dca_level:.4f} — отклонение от среднего. "
                    f"Фиксировать прибыль при возврате к среднему."
                )
        else:
            # accumulation_play или по умолчанию
            limit_zone = self._find_limit_buy_zone(df, indicators, current_price, diag)
            limit_comment = None
            if limit_zone:
                low, high = limit_zone
                # Улучшаем комментарий с учетом SMC контекста
                if diag and diag.smc_context and diag.smc_context.order_blocks_demand:
                    demand_blocks = [ob for ob in diag.smc_context.order_blocks_demand 
                                   if ob.price_low <= high and ob.price_high >= low]
                    if demand_blocks:
                        limit_comment = (
                            f"Лимитка привязана к demand order block после BOS — "
                            f"зона {low:.4f}–{high:.4f}, где смарт-мани уже проявляли интерес."
                        )
                    else:
                        limit_comment = (
                            f"Сильная поддержка и кластеры объёмов ниже текущей цены → "
                            f"лимитная зона {low:.4f}–{high:.4f}."
                        )
                else:
                    limit_comment = (
                        f"Сильная поддержка и кластеры объёмов ниже текущей цены → "
                        f"лимитная зона {low:.4f}–{high:.4f}."
                    )
            
            breakout_level = self._find_breakout_level(df, indicators, current_price, diag)
            breakout_comment = None
            if breakout_level:
                # Улучшаем комментарий с учетом SMC контекста
                if diag and diag.smc_context and diag.smc_context.main_liquidity_above:
                    liquidity_level = diag.smc_context.main_liquidity_above
                    if abs(breakout_level - liquidity_level) / liquidity_level < 0.01:  # В пределах 1%
                        breakout_comment = (
                            f"Добавление позиции логично после забора ликвидности над кластером equal highs "
                            f"в районе {breakout_level:.4f}."
                        )
                    else:
                        breakout_comment = (
                            f"Имеет смысл увеличивать позицию только после закрепления выше {breakout_level:.4f} — "
                            f"это пробой кластера сопротивлений (EMA/Bollinger/локальные хайи)."
                        )
                else:
                    breakout_comment = (
                        f"Имеет смысл увеличивать позицию только после закрепления выше {breakout_level:.4f} — "
                        f"это пробой кластера сопротивлений (EMA/Bollinger/локальные хайи)."
                    )
            
            dont_dca_level = self._find_dont_dca_level(df, indicators, current_price, diag)
            dont_dca_comment = None
            if dont_dca_level:
                # Улучшаем комментарий с учетом SMC контекста
                if diag and diag.smc_context and diag.smc_context.premium_zone_start:
                    premium_start = diag.smc_context.premium_zone_start
                    if abs(dont_dca_level - premium_start) / premium_start < 0.01:  # В пределах 1%
                        dont_dca_comment = (
                            f"Выше {dont_dca_level:.4f} актив входит в премиум-зону текущего диапазона — "
                            f"усреднение тут ухудшает среднюю цену и увеличивает риск."
                        )
                    else:
                        dont_dca_comment = (
                            f"Выше {dont_dca_level:.4f} начинается зона сильных сопротивлений — "
                            f"здесь уже логичнее фиксировать прибыль, чем усреднять убыток."
                        )
                else:
                    dont_dca_comment = (
                        f"Выше {dont_dca_level:.4f} начинается зона сильных сопротивлений — "
                        f"здесь уже логичнее фиксировать прибыль, чем усреднять убыток."
                    )
        
        # Проверяем, нужно ли пропустить торговлю (с учетом режима и MomentumInsight)
        skip_trading, skip_comment = self._should_skip_trading(diag, regime, momentum_insight)
        
        # Рассчитываем коэффициент размера позиции (с учетом режима и MomentumInsight)
        position_factor, position_comment = self._calculate_position_size(
            diag, mode, regime=regime, momentum_insight=momentum_insight
        )
        
        # Генерируем сценарный плейбук
        scenario_playbook = self._generate_scenario_playbook(diag, mode, small_allowed)
        
        return TradePlan(
            mode=mode,
            small_position_allowed=small_allowed,
            small_position_comment=small_comment,
            limit_buy_zone=limit_zone,
            limit_buy_comment=limit_comment,
            add_on_breakout_level=breakout_level,
            add_on_breakout_comment=breakout_comment,
            dont_dca_above=dont_dca_level,
            dont_dca_comment=dont_dca_comment,
            skip_trading=skip_trading,
            skip_trading_comment=skip_comment,
            position_size_factor=position_factor,
            position_size_comment=position_comment,
            scenario_playbook=scenario_playbook
        )
    
    def _determine_mode(self, diag: MarketDiagnostics) -> str:
        """Определить режим торговли."""
        if diag.phase == MarketPhase.ACCUMULATION:
            return "accumulation_play"
        elif diag.phase == MarketPhase.EXPANSION_UP:
            return "trend_follow"
        elif diag.phase == MarketPhase.DISTRIBUTION:
            return "distribution_wait"
        elif diag.phase == MarketPhase.SHAKEOUT:
            return "neutral"  # Встряска - лучше подождать
        else:
            return "neutral"
    
    def _small_position_allowed(
        self, 
        diag: MarketDiagnostics, 
        mode: str = "auto",
        momentum_insight: Optional[MomentumInsight] = None
    ) -> Tuple[bool, str]:
        """
        Определить, можно ли брать небольшую позицию сейчас.
        
        Args:
            diag: Результаты диагностики рынка
            mode: Режим стратегии ("auto", "accumulation_play", "trend_follow", "mean_reversion")
            momentum_insight: MomentumInsight для учета режима импульса
        
        Returns:
            (allowed: bool, comment: str)
        """
        # Учет MomentumInsight для фильтрации сетапов
        if momentum_insight:
            # При EXHAUSTION - снижаем вероятность входа
            if momentum_insight.regime == "EXHAUSTION":
                if momentum_insight.confidence > 0.7:
                    # Высокая уверенность в перегретости - не рекомендуется
                    return False, f"Импульс перегрет ({momentum_insight.comment}) - риск коррекции высокий."
                # Средняя уверенность - можно, но с осторожностью
                base_allowed, base_comment = self._small_position_allowed_base(diag, mode)
                if base_allowed:
                    return True, f"{base_comment} ⚠️ Но учтите: {momentum_insight.comment}"
            
            # При REVERSAL_RISK - осторожность, но может быть возможность
            elif momentum_insight.regime == "REVERSAL_RISK":
                if momentum_insight.confidence > 0.6:
                    # Высокая уверенность в риске разворота - лучше подождать
                    return False, f"Риск разворота ({momentum_insight.comment}) - лучше дождаться подтверждения."
        
        # Базовая логика (без учета MomentumInsight)
        return self._small_position_allowed_base(diag, mode)
    
    def _small_position_allowed_base(self, diag: MarketDiagnostics, mode: str = "auto") -> Tuple[bool, str]:
        """
        Базовая логика определения возможности небольшой позиции (без MomentumInsight).
        
        Args:
            diag: Результаты диагностики рынка
            mode: Режим стратегии
        
        Returns:
            (allowed: bool, comment: str)
        """
        # Рынок в балансе/накоплении - допустима небольшая пробная позиция
        if diag.phase == MarketPhase.ACCUMULATION:
            if diag.volatility == VolatilityState.LOW:
                return True, "Рынок в балансе/накоплении, допустима небольшая пробная позиция."
            elif diag.volatility == VolatilityState.MEDIUM:
                return True, "Рынок в накоплении со средней волатильностью, небольшая позиция допустима с осторожностью."
        
        # Расширение вверх - можно, но с осторожностью
        if diag.phase == MarketPhase.EXPANSION_UP:
            if mode == "trend_follow":
                return True, "Тренд-фолловинг: расширение вверх - хорошая возможность для входа по тренду."
            elif diag.trend == TrendState.BULLISH:
                return True, "Рынок в расширении вверх, небольшая позиция допустима, но следите за пробоями."
            else:
                return False, "Расширение вверх без четкого бычьего тренда - повышенный риск."
        
        # Расширение вниз - не рекомендуется
        if diag.phase == MarketPhase.EXPANSION_DOWN:
            return False, "Сейчас идёт направленный дамп, пробная позиция повышенного риска."
        
        # Распределение - лучше ждать
        if diag.phase == MarketPhase.DISTRIBUTION:
            return False, "Фаза распределения, лучше ждать отката или новой базы."
        
        # Встряска - не рекомендуется
        if diag.phase == MarketPhase.SHAKEOUT:
            return False, "Рынок в встряске - высокая волатильность при низкой ликвидности, лучше подождать."
        
        # По умолчанию - неясная структура
        return False, "Структура неясная, лучше без новых позиций."
    
    def _should_skip_trading(
        self,
        diag: MarketDiagnostics,
        regime: Optional[GlobalRegime] = None,
        momentum_insight: Optional[MomentumInsight] = None
    ) -> Tuple[bool, Optional[str]]:
        """
        Определить, нужно ли пропустить торговлю этим активом.
        
        Args:
            diag: Результаты диагностики
            regime: Глобальный режим рынка
            momentum_insight: MomentumInsight для учета режима импульса
        
        Returns:
            (skip: bool, comment: str)
        """
        # Учет MomentumInsight: при EXHAUSTION с высокой уверенностью - пропускаем
        if momentum_insight:
            if momentum_insight.regime == "EXHAUSTION" and momentum_insight.confidence > 0.8:
                return True, (
                    f"🔴 РЫНОК ДЛЯ ПРОПУСКА: импульс перегрет с высокой уверенностью "
                    f"({momentum_insight.comment}). Риск коррекции слишком высок."
                )
        
        # Адаптируем пороги в зависимости от режима
        risk_threshold = 0.7
        pump_threshold = 0.3
        
        regime_enum = self._extract_regime(regime)
        if regime_enum == GlobalRegime.RISK_OFF:
            # В RISK_OFF повышаем требования
            risk_threshold = 0.6
            pump_threshold = 0.4
        elif regime_enum == GlobalRegime.PANIC:
            # В панике еще выше требования
            risk_threshold = 0.5
            pump_threshold = 0.5
        elif regime_enum == GlobalRegime.RISK_ON:
            # В RISK_ON можно немного снизить требования
            risk_threshold = 0.75
            pump_threshold = 0.25
        
        # Высокий риск при низком потенциале - пропускаем
        if diag.risk_score > risk_threshold and diag.pump_score < pump_threshold:
            regime_text = f" ({regime_enum.value})" if regime_enum else ""
            return True, (
                f"🔴 РЫНОК ДЛЯ ПРОПУСКА{regime_text}: текущая структура даёт высокий риск при низком апсайде. "
                "Лучше искать другие сетапы."
            )
        
        # Экстремально высокий риск
        extreme_threshold = 0.85 if regime_enum != GlobalRegime.PANIC else 0.75
        if diag.risk_score > extreme_threshold:
            return True, (
                "🔴 РЫНОК ДЛЯ ПРОПУСКА: экстремально высокий риск. "
                "Рынок в нестабильном состоянии, лучше подождать улучшения структуры."
            )
        
        # Очень низкий потенциал при среднем/высоком риске
        if diag.pump_score < 0.2 and diag.risk_score > 0.5:
            return True, (
                "🔴 РЫНОК ДЛЯ ПРОПУСКА: очень низкий потенциал роста при повышенном риске. "
                "Неблагоприятное соотношение риск/награда."
            )
        
        return False, None
    
    def _calculate_position_size(
        self,
        diag: MarketDiagnostics,
        mode: str,
        base_factor: float = 1.0,
        regime: Optional[GlobalRegime] = None,
        reliability_score: Optional[float] = None,
        tradability_state: Optional[str] = None,
        size_at_10bps: Optional[float] = None,
        momentum_insight: Optional[MomentumInsight] = None
    ) -> Tuple[Optional[float], Optional[str]]:
        """
        Рассчитать коэффициент размера позиции.
        
        Args:
            diag: Результаты диагностики
            mode: Режим стратегии
            base_factor: Базовый коэффициент (зависит от профиля пользователя)
            regime: Глобальный режим рынка
            reliability_score: Надёжность паттерна (0.0-1.0)
            tradability_state: Состояние ликвидности (ILLIQUID, NORMAL, HIGH_LIQUIDITY)
            size_at_10bps: Доступный объем при проскальзывании 10 bps (в USDT)
        
        Returns:
            (factor: float, comment: str)
        """
        # Базовый коэффициент зависит от pump_score и risk_score
        factor = base_factor
        
        # Адаптация под режим рынка
        regime_enum = self._extract_regime(regime)
        if regime_enum == GlobalRegime.RISK_OFF:
            # В RISK_OFF режем position_size_factor в 2 раза
            factor *= 0.5
        elif regime_enum == GlobalRegime.PANIC:
            # В панике еще больше режем
            factor *= 0.3
        elif regime_enum == GlobalRegime.RISK_ON:
            # В RISK_ON можно немного увеличить
            factor *= 1.1
        elif regime_enum == GlobalRegime.ALT_SEASON:
            # В сезон альтов можно увеличить для альтов
            factor *= 1.15
        
        # Корректировка на основе pump_score
        if diag.pump_score > 0.8:
            factor *= 1.2  # Высокий потенциал - можно увеличить
        elif diag.pump_score > 0.6:
            factor *= 1.1
        elif diag.pump_score < 0.3:
            factor *= 0.7  # Низкий потенциал - уменьшаем
        
        # Корректировка на основе risk_score
        if diag.risk_score > 0.7:
            factor *= 0.7  # Высокий риск - уменьшаем
        elif diag.risk_score > 0.5:
            factor *= 0.85
        elif diag.risk_score < 0.3:
            factor *= 1.1  # Низкий риск - можно немного увеличить
        
        # Корректировка на основе reliability_score
        if reliability_score is not None:
            if reliability_score > 0.7:
                factor *= 1.1  # Высокая надёжность - можно увеличить
            elif reliability_score < 0.5:
                factor *= 0.8  # Низкая надёжность - уменьшаем
        
        # Корректировка на основе ликвидности
        if tradability_state:
            from .tradability import TradabilityState
            if tradability_state == TradabilityState.ILLIQUID.value:
                factor *= 0.6  # Низкая ликвидность - значительно уменьшаем
            elif tradability_state == TradabilityState.HIGH_LIQUIDITY.value:
                factor *= 1.05  # Высокая ликвидность - можно немного увеличить
        
        # Ограничение размера позиции на основе доступного объема
        if size_at_10bps is not None and size_at_10bps > 0:
            # Предполагаем базовый размер позиции (например, 10k USDT)
            # Если доступный объем меньше базового размера, уменьшаем factor
            base_position_size = 10000  # USDT
            if size_at_10bps < base_position_size:
                volume_factor = size_at_10bps / base_position_size
                factor *= volume_factor
        
        # Корректировка на основе MomentumInsight
        momentum_adjustment = 1.0
        momentum_comment = ""
        if momentum_insight:
            if momentum_insight.regime == "EXHAUSTION":
                # При перегретости снижаем размер позиции
                momentum_adjustment = 0.6 - (momentum_insight.strength * 0.2)  # 0.4-0.6
                momentum_comment = f" (импульс перегрет: {momentum_insight.comment})"
            elif momentum_insight.regime == "REVERSAL_RISK":
                # При риске разворота снижаем размер позиции
                momentum_adjustment = 0.7 - (momentum_insight.confidence * 0.2)  # 0.5-0.7
                momentum_comment = f" (риск разворота: {momentum_insight.comment})"
            elif momentum_insight.regime == "CONTINUATION":
                # При продолжении тренда можно слегка увеличить (если confidence высокий)
                if momentum_insight.confidence > 0.7:
                    momentum_adjustment = 1.0 + (momentum_insight.strength * 0.1)  # 1.0-1.1
                    momentum_comment = f" (импульс поддерживает тренд)"
            # NEUTRAL - без изменений
        
        factor = factor * momentum_adjustment
        
        # Ограничиваем диапазон
        factor = max(0.3, min(1.5, factor))
        
        # Формируем комментарий
        # Обрабатываем случай, когда regime может быть RegimeSnapshot или GlobalRegime
        regime_value = None
        if regime:
            # Проверяем, является ли regime объектом RegimeSnapshot (имеет атрибут .regime)
            if hasattr(regime, 'regime'):
                # Это RegimeSnapshot, берем значение из вложенного GlobalRegime
                regime_value = regime.regime.value if hasattr(regime.regime, 'value') else str(regime.regime)
            elif hasattr(regime, 'value'):
                # Это GlobalRegime напрямую
                regime_value = regime.value
            else:
                # Fallback: пытаемся преобразовать в строку
                regime_value = str(regime)
        
        regime_text = f" (режим: {regime_value})" if regime_value else ""
        reliability_text = f", надёжность: {reliability_score:.2f}" if reliability_score is not None else ""
        momentum_text = momentum_comment if momentum_insight else ""
        
        if factor < 0.7:
            comment = f"💰 Рекомендуемый размер позиции: <b>{factor:.2f}R</b>{regime_text}{reliability_text}{momentum_text}. Снижен из-за повышенного риска или неблагоприятного режима."
        elif factor > 1.2:
            comment = f"💰 Рекомендуемый размер позиции: <b>{factor:.2f}R</b>{regime_text}{reliability_text}. Можно увеличить из-за высокого потенциала и благоприятных условий."
        else:
            comment = f"💰 Рекомендуемый размер позиции: <b>{factor:.2f}R</b>{regime_text}{reliability_text}."
        
        return factor, comment
    
    def _generate_scenario_playbook(
        self,
        diag: MarketDiagnostics,
        mode: str,
        small_allowed: bool
    ) -> Optional[str]:
        """
        Сгенерировать сценарный плейбук на основе диагностики и режима.
        
        Returns:
            Текстовый плейбук или None
        """
        if mode == "accumulation_play":
            if diag.pump_score > 0.7:
                return (
                    "📋 <b>Сценарий: набор в базе с лимитками ниже и агрессивным добавлением на пробое.</b>\n\n"
                    "• Рынок в фазе накопления с высоким потенциалом роста\n"
                    "• Стратегия: лимитные ордера в зоне поддержки, добавление на пробое сопротивлений\n"
                    "• Ожидание: выход из компрессии с потенциалом импульса\n"
                    "• Управление риском: стопы ниже зоны накопления, фиксация части прибыли на пробоях"
                )
            else:
                return (
                    "📋 <b>Сценарий: осторожный набор в базе.</b>\n\n"
                    "• Рынок в фазе накопления, но потенциал роста умеренный\n"
                    "• Стратегия: небольшие лимитные ордера, ожидание подтверждения\n"
                    "• Управление риском: строгие стопы, готовность к выходу при ухудшении структуры"
                )
        
        elif mode == "trend_follow":
            if diag.phase == MarketPhase.EXPANSION_UP:
                return (
                    "📋 <b>Сценарий: трендовое сопровождение — докупка на откатах к EMA20/50, частичная фиксация на новых экстремумах.</b>\n\n"
                    "• Рынок в расширении вверх с четким трендом\n"
                    "• Стратегия: входы на откатах к ключевым поддержкам (EMA20/50), добавление на пробоях\n"
                    "• Управление позицией: фиксация 30-50% на новых максимумах, перезаходы на коррекциях\n"
                    "• Стопы: ниже последнего значимого минимума"
                )
            else:
                return (
                    "📋 <b>Сценарий: тренд-фолловинг с осторожностью.</b>\n\n"
                    "• Тренд присутствует, но фаза не идеальна для агрессивного следования\n"
                    "• Стратегия: небольшие позиции на пробоях, готовность к выходу\n"
                    "• Управление риском: быстрая фиксация при первых признаках разворота"
                )
        
        elif mode == "mean_reversion":
            return (
                "📋 <b>Сценарий: возврат к среднему.</b>\n\n"
                "• Рынок отклоняется от средних значений (VWAP/Bollinger)\n"
                "• Стратегия: входы в зоне перепродажи/перекупленности, выход при возврате к среднему\n"
                "• Управление: быстрая фиксация прибыли, стопы за пределами зоны возврата"
            )
        
        elif diag.phase == MarketPhase.DISTRIBUTION:
            return (
                "📋 <b>Сценарий: ожидание отката или новой базы.</b>\n\n"
                "• Рынок в фазе распределения\n"
                "• Стратегия: избегать новых позиций, фиксировать существующие\n"
                "• Ожидание: формирование новой базы накопления или значимый откат"
            )
        
        return None
    
    def _find_limit_buy_zone(
        self,
        df: pd.DataFrame,
        indicators: dict,
        current_price: float,
        diag: Optional[MarketDiagnostics] = None
    ) -> Optional[Tuple[float, float]]:
        """
        Найти зону лимитных ордеров ниже текущей цены.
        
        Приоритет:
        1. Demand Order Block (если есть SMC контекст)
        2. Сильные уровни поддержки
        3. Локальные минимумы и EMA/VWAP
        
        Returns:
            (low, high) или None
        """
        # Приоритет 1: Demand Order Block из SMC контекста
        if diag and diag.smc_context and diag.smc_context.order_blocks_demand:
            demand_blocks = [ob for ob in diag.smc_context.order_blocks_demand 
                           if ob.price_high < current_price]
            if demand_blocks:
                # Берем ближайший к цене demand OB
                best_demand = max(demand_blocks, key=lambda ob: ob.price_high)
                # Добавляем небольшой отступ вниз
                if 'atr' in indicators:
                    atr = self._get_last_value(indicators['atr'])
                    pad = float(atr) * 0.2 if atr else best_demand.price_low * 0.005
                else:
                    pad = best_demand.price_low * 0.005
                
                support_low = max(best_demand.price_low - pad, best_demand.price_low * 0.995)
                support_high = min(best_demand.price_high * 1.005, current_price * 0.99)
                
                if support_high < current_price:
                    return (round(support_low, 4), round(support_high, 4))
        
        # Приоритет 2: Сильные уровни поддержки
        if diag and diag.key_levels:
            support_levels = [lvl for lvl in diag.key_levels 
                            if lvl.kind.value in ['support', 'orderblock_demand'] 
                            and lvl.price < current_price]
            if support_levels:
                # Берем ближайший сильный уровень
                best_support = max(support_levels, key=lambda l: (l.strength, l.price))
                if 'atr' in indicators:
                    atr = self._get_last_value(indicators['atr'])
                    pad = float(atr) * 0.3 if atr else best_support.price * 0.01
                else:
                    pad = best_support.price * 0.01
                
                support_low = best_support.price * 0.995
                support_high = min(best_support.price * 1.005, current_price * 0.99)
                
                if support_high < current_price:
                    return (round(support_low, 4), round(support_high, 4))
        
        # Приоритет 3: Discount зона из SMC
        if diag and diag.smc_context and diag.smc_context.discount_zone_end:
            discount_end = diag.smc_context.discount_zone_end
            if discount_end < current_price:
                if 'atr' in indicators:
                    atr = self._get_last_value(indicators['atr'])
                    pad = float(atr) * 0.2 if atr else discount_end * 0.01
                else:
                    pad = discount_end * 0.01
                
                support_low = discount_end * 0.99
                support_high = min(discount_end * 1.01, current_price * 0.99)
                
                if support_high < current_price:
                    return (round(support_low, 4), round(support_high, 4))
        
        # Fallback: классический метод (локальные минимумы, EMA, VWAP)
        close = df['close']
        low = df['low']
        
        lookback = min(50, len(df))
        recent_lows = low.tail(lookback)
        
        n_lows = min(3, len(recent_lows))
        if n_lows == 0:
            return None
        
        lowest_points = recent_lows.nsmallest(n_lows)
        if len(lowest_points) == 0:
            return None
        
        support_low = float(lowest_points.min())
        support_high = float(lowest_points.mean())
        
        if 'ema_20' in indicators:
            ema20 = self._get_last_value(indicators['ema_20'])
            if ema20 and ema20 < current_price:
                support_high = max(support_high, ema20 * 0.98)
        
        if 'ema_50' in indicators:
            ema50 = self._get_last_value(indicators['ema_50'])
            if ema50 and ema50 < current_price:
                support_low = min(support_low, ema50 * 0.97)
        
        if 'vwap' in indicators:
            vwap = self._get_last_value(indicators['vwap'])
            if vwap and vwap < current_price:
                support_high = max(support_high, vwap * 0.99)
        
        if 'atr' in indicators:
            atr = self._get_last_value(indicators['atr'])
            if atr and atr > 0:
                pad = float(atr) * 0.3
                support_low = max(support_low - pad, support_low * 0.95)
        
        if support_high >= current_price:
            return None
        
        price_range = support_high - support_low
        if price_range > current_price * 0.1:
            support_high = support_low + (current_price * 0.05)
        
        return (round(support_low, 4), round(support_high, 4))
    
    def _find_breakout_level(
        self,
        df: pd.DataFrame,
        indicators: dict,
        current_price: float,
        diag: Optional[MarketDiagnostics] = None
    ) -> Optional[float]:
        """
        Найти уровень пробоя для добавления позиции.
        
        Приоритет:
        1. Liquidity pool (equal highs) из SMC
        2. Сильные уровни сопротивления
        3. EMA/Bollinger/локальные максимумы
        
        Returns:
            Уровень пробоя или None
        """
        resistance_levels = []
        
        # Приоритет 1: Liquidity pool (equal highs) из SMC
        if diag and diag.smc_context and diag.smc_context.main_liquidity_above:
            liquidity_level = diag.smc_context.main_liquidity_above
            if liquidity_level > current_price:
                # Добавляем небольшой буфер для пробоя
                resistance_levels.append(liquidity_level * 1.002)
        
        # Приоритет 2: Сильные уровни сопротивления
        if diag and diag.key_levels:
            resistance_key_levels = [lvl for lvl in diag.key_levels 
                                    if lvl.kind.value in ['resistance', 'liquidity_high', 'orderblock_supply']
                                    and lvl.price > current_price]
            if resistance_key_levels:
                # Берем ближайший сильный уровень
                best_resistance = min(resistance_key_levels, key=lambda l: l.price)
                resistance_levels.append(best_resistance.price)
        
        # Приоритет 3: Классические методы (EMA, Bollinger, локальные максимумы)
        high = df['high']
        
        if 'ema_20' in indicators:
            ema20 = self._get_last_value(indicators['ema_20'])
            if ema20 and ema20 > current_price:
                resistance_levels.append(ema20)
        
        if 'ema_50' in indicators:
            ema50 = self._get_last_value(indicators['ema_50'])
            if ema50 and ema50 > current_price:
                resistance_levels.append(ema50)
        
        if 'ema_200' in indicators:
            ema200 = self._get_last_value(indicators['ema_200'])
            if ema200 and ema200 > current_price:
                resistance_levels.append(ema200)
        
        if 'bb_middle' in indicators:
            bb_mid = self._get_last_value(indicators['bb_middle'])
            if bb_mid and bb_mid > current_price:
                resistance_levels.append(bb_mid)
        elif 'bb_mid' in indicators:
            bb_mid = self._get_last_value(indicators['bb_mid'])
            if bb_mid and bb_mid > current_price:
                resistance_levels.append(bb_mid)
        
        if 'bb_upper' in indicators:
            bb_upper = self._get_last_value(indicators['bb_upper'])
            if bb_upper and bb_upper > current_price:
                resistance_levels.append(bb_upper)
        
        lookback = min(30, len(df))
        recent_highs = high.tail(lookback)
        if len(recent_highs) > 0:
            max_high = float(recent_highs.max())
            if max_high > current_price:
                resistance_levels.append(max_high * 0.98)
        
        if not resistance_levels:
            return None
        
        breakout_level = min(resistance_levels)
        
        if breakout_level > current_price * 1.2:
            return None
        
        return round(breakout_level, 4)
    
    def _find_dont_dca_level(
        self,
        df: pd.DataFrame,
        indicators: dict,
        current_price: float,
        diag: Optional[MarketDiagnostics] = None
    ) -> Optional[float]:
        """
        Найти уровень выше которого не усреднять (DCA).
        
        Приоритет:
        1. Premium зона из SMC (начало premium зоны)
        2. Сильные уровни сопротивления
        3. EMA200/Bollinger/локальные максимумы
        
        Returns:
            Уровень или None
        """
        resistance_levels = []
        
        # Приоритет 1: Premium зона из SMC
        if diag and diag.smc_context and diag.smc_context.premium_zone_start:
            premium_start = diag.smc_context.premium_zone_start
            if premium_start > current_price:
                resistance_levels.append(premium_start)
            elif premium_start <= current_price:
                # Если уже в premium - берем ближайшее сильное сопротивление выше
                pass
        
        # Приоритет 2: Сильные уровни сопротивления
        if diag and diag.key_levels:
            resistance_key_levels = [lvl for lvl in diag.key_levels 
                                    if lvl.kind.value in ['resistance', 'liquidity_high', 'orderblock_supply']
                                    and lvl.strength > 0.5]  # Только сильные уровни
            if resistance_key_levels:
                # Берем ближайший к цене сильный уровень
                closest_resistance = min([lvl for lvl in resistance_key_levels if lvl.price >= current_price],
                                        key=lambda l: l.price, default=None)
                if closest_resistance:
                    resistance_levels.append(closest_resistance.price)
                # Если все сопротивления ниже цены, берем максимальное
                elif resistance_key_levels:
                    max_resistance = max(resistance_key_levels, key=lambda l: l.price)
                    if max_resistance.price > current_price * 0.95:  # Не слишком далеко
                        resistance_levels.append(max_resistance.price)
        
        # Приоритет 3: Классические методы
        # EMA200 как сильное сопротивление
        if 'ema_200' in indicators:
            ema200 = self._get_last_value(indicators['ema_200'])
            if ema200:
                resistance_levels.append(ema200)
        
        # Верхняя Bollinger Band
        if 'bb_upper' in indicators:
            bb_upper = self._get_last_value(indicators['bb_upper'])
            if bb_upper:
                resistance_levels.append(bb_upper)
        
        # EMA50 как сопротивление
        if 'ema_50' in indicators:
            ema50 = self._get_last_value(indicators['ema_50'])
            if ema50 and ema50 > current_price:
                resistance_levels.append(ema50)
        
        # Локальные максимумы (зоны распределения)
        lookback = min(50, len(df))
        recent_highs = df['high'].tail(lookback)
        if len(recent_highs) > 0:
            # Берем средний максимум за период
            avg_high = float(recent_highs.mean())
            if avg_high > current_price:
                resistance_levels.append(avg_high)
        
        if not resistance_levels:
            return None
        
        # Берем минимальный уровень (ближайший к цене)
        dont_dca_level = min(resistance_levels)
        
        # Если уровень уже ниже текущей цены - возвращаем текущую цену
        if dont_dca_level <= current_price:
            return round(current_price * 1.02, 4)  # На 2% выше текущей
        
        return round(dont_dca_level, 4)
    
    def _find_mean_reversion_zone(
        self,
        df: pd.DataFrame,
        indicators: dict,
        current_price: float
    ) -> Optional[Tuple[float, float]]:
        """
        Найти зону mean reversion вокруг VWAP/Bollinger basis.
        
        Returns:
            (low, high) или None
        """
        # Берем VWAP как основу
        vwap = self._get_last_value(indicators.get('vwap'))
        bb_middle = self._get_last_value(indicators.get('bb_middle'))
        
        if not vwap and not bb_middle:
            return None
        
        # Используем VWAP если есть, иначе BB middle
        basis = vwap if vwap else bb_middle
        
        if not basis or basis <= 0:
            return None
        
        # Зона mean reversion: ±2-3% от basis
        deviation = basis * 0.025  # 2.5%
        
        support_low = basis - deviation
        support_high = basis + deviation
        
        # Проверяем, что зона ниже текущей цены (для покупки)
        if support_high >= current_price:
            return None
        
        return (round(support_low, 4), round(support_high, 4))
    
    def _find_mean_reversion_resistance(
        self,
        df: pd.DataFrame,
        indicators: dict,
        current_price: float
    ) -> Optional[float]:
        """
        Найти уровень сопротивления для mean reversion (верхняя граница отклонения).
        
        Returns:
            Уровень или None
        """
        vwap = self._get_last_value(indicators.get('vwap'))
        bb_upper = self._get_last_value(indicators.get('bb_upper'))
        
        if not vwap and not bb_upper:
            return None
        
        # Используем верхнюю Bollinger или VWAP + отклонение
        if bb_upper:
            resistance = bb_upper
        else:
            resistance = vwap * 1.05  # 5% выше VWAP
        
        if not resistance or resistance <= current_price:
            return None
        
        return round(resistance, 4)
    
    def _get_last_value(self, series_or_value) -> Optional[float]:
        """Получить последнее значение из Series или вернуть само значение."""
        if isinstance(series_or_value, pd.Series):
            if len(series_or_value) == 0:
                return None
            value = series_or_value.iloc[-1]
            if pd.isna(value):
                return None
            return float(value)
        elif isinstance(series_or_value, (int, float)):
            return float(series_or_value)
        else:
            return None

