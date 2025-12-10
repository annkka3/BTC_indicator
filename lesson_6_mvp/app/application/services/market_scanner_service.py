# app/application/services/market_scanner_service.py
"""
Сервис для сканирования рынка и поиска топ-сетапов Market Doctor.
"""

from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass
import asyncio
import logging

from ...domain.market_diagnostics import (
    IndicatorCalculator,
    FeatureExtractor,
    MarketAnalyzer,
    ReportRenderer,
    MarketDoctorConfig,
    DEFAULT_CONFIG,
    MultiTFDiagnostics,
    TradabilityAnalyzer,
    TradabilityState,
    CalibrationService,
    generate_pattern_id
)
from ...domain.market_regime import GlobalRegimeAnalyzer
from ...infrastructure.market_data_service import MarketDataService
from ...infrastructure.repositories.watchlist_repository import WatchlistRepository

logger = logging.getLogger("alt_forecast.services.market_scanner")


@dataclass
class SetupCandidate:
    """Кандидат в топ-сетапы."""
    symbol: str
    avg_pump_score: float
    avg_risk_score: float
    consensus_phase: str
    timeframes: Dict[str, Dict]  # {"1h": {phase, trend, ...}, "4h": {...}, "1d": {...}}
    current_price: float
    multi_diag: Optional[MultiTFDiagnostics] = None
    tradability_state: Optional[str] = None  # ILLIQUID, NORMAL, HIGH_LIQUIDITY
    spread_bps: Optional[float] = None
    size_at_10bps: Optional[float] = None
    regime: Optional[str] = None  # Глобальный режим рынка
    reliability_score: Optional[float] = None  # Надёжность паттерна
    effective_threshold: Optional[float] = None  # Адаптивный порог pump_score


class MarketScannerService:
    """Сервис для сканирования рынка и поиска топ-сетапов."""
    
    # Топ монеты по умолчанию (можно расширить)
    DEFAULT_TOP_COINS = [
        "BTC", "ETH", "BNB", "SOL", "XRP", "ADA", "DOGE", "DOT", "MATIC", "AVAX",
        "LINK", "UNI", "LTC", "ATOM", "ETC", "XLM", "ALGO", "VET", "ICP", "FIL",
        "TRX", "EOS", "AAVE", "GRT", "THETA", "AXS", "SAND", "MANA", "ENJ", "CHZ",
        "HBAR", "NEAR", "FLOW", "EGLD", "XTZ", "ZEC", "DASH", "BCH", "XMR", "ZIL",
        "ENA", "WIF", "OP", "TIA", "ARB", "SUI", "APT", "INJ", "SEI", "JUP"
    ]
    
    def __init__(self, db, config: MarketDoctorConfig = None):
        """
        Args:
            db: Database instance
            config: Конфигурация Market Doctor
        """
        self.db = db
        self.config = config or DEFAULT_CONFIG
        self.data_service = MarketDataService(db)
        self.watchlist_repo = WatchlistRepository(db)
        
        # Инициализируем компоненты Market Doctor
        self.indicator_calculator = IndicatorCalculator(self.config)
        self.feature_extractor = FeatureExtractor(self.config)
        self.market_analyzer = MarketAnalyzer(self.config)
        # ReportRenderer используется только для fallback, создаем лениво
        self._report_renderer = None
        self.tradability_analyzer = TradabilityAnalyzer(db)
        self.calibration_service = CalibrationService(db)
        self.regime_analyzer = GlobalRegimeAnalyzer(db)
    
    @property
    def report_renderer(self):
        """Ленивая инициализация ReportRenderer."""
        if self._report_renderer is None:
            self._report_renderer = ReportRenderer()
        return self._report_renderer
    
    async def scan_universe(
        self,
        symbols: Optional[List[str]] = None,
        timeframes: List[str] = None,
        min_pump_score: float = 0.7,
        max_risk_score: float = 0.7,
        limit: int = 10,
        filter_illiquid: bool = True,
        user_profile: Optional[str] = None  # "Conservative", "Balanced", "Aggressive"
    ) -> List[SetupCandidate]:
        """
        Сканировать список символов и найти топ-сетапы.
        
        Args:
            symbols: Список символов для сканирования (None = использовать DEFAULT_TOP_COINS)
            timeframes: Список таймфреймов для анализа (по умолчанию ["4h", "1d"])
            min_pump_score: Минимальный pump_score для фильтрации
            max_risk_score: Максимальный risk_score для фильтрации
            limit: Максимальное количество результатов
        
        Returns:
            Список кандидатов в топ-сетапы, отсортированный по pump_score
        """
        if symbols is None:
            symbols = self.DEFAULT_TOP_COINS
        
        if timeframes is None:
            timeframes = ["4h", "1d"]
        
        # Получаем текущий режим рынка (один раз для всех символов)
        regime_snapshot = self.regime_analyzer.analyze_current_regime()
        current_regime = regime_snapshot.regime
        
        candidates = []
        
        # Сканируем каждый символ с параллелизмом
        sem = asyncio.Semaphore(5)  # Максимум 5 параллельных запросов
        
        async def _wrapped_analyze(symbol: str):
            async with sem:
                return await self._analyze_symbol(symbol, timeframes, current_regime)
        
        # Создаём задачи для всех символов
        tasks = [asyncio.create_task(_wrapped_analyze(s)) for s in symbols]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Обрабатываем результаты
        for symbol, result in zip(symbols, results):
            if isinstance(result, Exception):
                logger.debug(f"Failed to analyze {symbol}: {result}")
                continue
            
            candidate = result
            if not candidate:
                continue
            
            # Используем адаптивный порог вместо статического
            effective_threshold = self.calibration_service.get_effective_pump_threshold(
                symbol, current_regime
            )
            candidate.effective_threshold = effective_threshold
            
            # Фильтруем по адаптивному pump_score и risk_score
            if (candidate.avg_pump_score >= effective_threshold and 
                candidate.avg_risk_score <= max_risk_score):
                # Фильтруем по ликвидности
                if filter_illiquid:
                    # Для консервативных пользователей пропускаем неликвидные инструменты
                    if user_profile == "Conservative" and candidate.tradability_state == TradabilityState.ILLIQUID.value:
                        continue
                    # Для всех остальных тоже можно пропускать экстремально неликвидные
                    elif candidate.tradability_state == TradabilityState.ILLIQUID.value and candidate.spread_bps and candidate.spread_bps > 50:
                        continue
                
                candidates.append(candidate)
        
        # Сортируем по pump_score (по убыванию)
        candidates.sort(key=lambda x: x.avg_pump_score, reverse=True)
        
        # Возвращаем топ N
        return candidates[:limit]
    
    async def _analyze_symbol(
        self,
        symbol: str,
        timeframes: List[str],
        current_regime = None
    ) -> Optional[SetupCandidate]:
        """
        Проанализировать символ на нескольких таймфреймах.
        
        Args:
            symbol: Символ для анализа
            timeframes: Список таймфреймов
        
        Returns:
            SetupCandidate или None если не удалось получить данные
        """
        timeframes_data = {}
        
        # Получаем данные деривативов один раз
        try:
            derivatives_snapshot = await self.data_service.get_derivatives(symbol, "1h")
            derivatives = derivatives_snapshot.to_dict()
        except Exception:
            derivatives = {}
        
        # Собираем данные по всем таймфреймам
        for tf in timeframes:
            try:
                df = await self.data_service.get_ohlcv(symbol, tf, limit=500)
                if df is None or df.empty:
                    continue
                
                # Рассчитываем индикаторы
                indicators = self.indicator_calculator.calculate_all(df)
                
                # Извлекаем признаки
                features = self.feature_extractor.extract_features(df, indicators, derivatives)
                
                # Сохраняем данные
                timeframes_data[tf] = {
                    "df": df,
                    "indicators": indicators,
                    "features": features
                }
            except Exception as e:
                logger.debug(f"Failed to get data for {symbol} {tf}: {e}")
                continue
        
        if not timeframes_data:
            return None
        
        # Анализируем multi-TF
        try:
            multi_diag = self.market_analyzer.analyze_multi(symbol, timeframes_data, derivatives)
            
            # Получаем текущую цену
            last_tf = list(timeframes_data.keys())[0]
            current_price = float(timeframes_data[last_tf]["df"]['close'].iloc[-1])
            
            # Анализируем ликвидность
            volume_24h = None
            try:
                # Пробуем получить объем из данных
                if last_tf in timeframes_data:
                    df = timeframes_data[last_tf]["df"]
                    if 'volume' in df.columns:
                        volume_24h = df['volume'].tail(24).sum() * current_price  # Примерная оценка
            except:
                pass
            
            tradability = self.tradability_analyzer.analyze_tradability(
                symbol, current_price, volume_24h
            )
            
            # Рассчитываем reliability_score и pattern_id
            reliability_score = None
            if current_regime:
                # Берем первый доступный таймфрейм для pattern_id
                first_tf = list(multi_diag.snapshots.keys())[0] if multi_diag.snapshots else None
                if first_tf:
                    diag = multi_diag.snapshots[first_tf]
                    # Получаем structure из features
                    structure_str = "RANGE"
                    if first_tf in timeframes_data:
                        features = timeframes_data[first_tf].get("features", {})
                        structure_str = features.get('structure', 'RANGE')
                        if hasattr(structure_str, 'value'):
                            structure_str = structure_str.value
                        else:
                            structure_str = str(structure_str)
                    
                    pattern_id = generate_pattern_id(
                        diag.phase,
                        diag.trend,
                        structure_str,
                        current_regime
                    )
                    
                    try:
                        reliability_score = self.calibration_service.get_reliability_score(pattern_id)
                    except Exception as e:
                        logger.debug(f"Failed to get reliability score for {symbol}: {e}")
            
            # Формируем данные по таймфреймам
            tf_info = {}
            for tf in timeframes:
                if tf in multi_diag.snapshots:
                    diag = multi_diag.snapshots[tf]
                    tf_info[tf] = {
                        "phase": diag.phase.value,
                        "trend": diag.trend.value,
                        "volatility": diag.volatility.value,
                        "pump_score": diag.pump_score,
                        "risk_score": diag.risk_score
                    }
            
            consensus_phase = multi_diag.get_consensus_phase()
            # Если это строка, используем как есть, если объект - берём value
            if hasattr(consensus_phase, 'value'):
                consensus_phase = consensus_phase.value
            else:
                consensus_phase = str(consensus_phase)
            
            return SetupCandidate(
                symbol=symbol,
                avg_pump_score=multi_diag.get_avg_pump_score(),
                avg_risk_score=multi_diag.get_avg_risk_score(),
                consensus_phase=consensus_phase,
                timeframes=tf_info,
                current_price=current_price,
                multi_diag=multi_diag,
                tradability_state=tradability.state.value,
                spread_bps=tradability.spread_bps,
                size_at_10bps=tradability.size_at_10bps,
                regime=current_regime.value if current_regime else None,
                reliability_score=reliability_score
            )
        except Exception as e:
            logger.debug(f"Failed to analyze {symbol}: {e}")
            return None
    
    def format_top_setups_report(
        self,
        candidates: List[SetupCandidate],
        timeframes: List[str]
    ) -> str:
        """
        Сформировать отчет о топ-сетапах.
        
        Args:
            candidates: Список кандидатов
            timeframes: Список таймфреймов
        
        Returns:
            Текстовый отчет
        """
        if not candidates:
            return "❌ Топ-сетапы не найдены.\n\nПопробуйте изменить фильтры (pump_score, risk_score)."
        
        lines = []
        lines.append(f"🔥 <b>Топ-{len(candidates)} сетапов</b> ({'/'.join(timeframes)}):")
        lines.append("")
        
        # Добавляем информацию о режиме рынка в заголовок
        if candidates and candidates[0].regime:
            regime_emoji = {
                "risk_on": "🟢",
                "risk_off": "🔴",
                "alt_season": "🚀",
                "btc_dominance": "₿",
                "choppy": "🟡",
                "panic": "⚠️"
            }.get(candidates[0].regime, "🌍")
            lines.append(f"{regime_emoji} <b>Режим рынка:</b> {candidates[0].regime.upper()}")
            lines.append("")
        
        for i, candidate in enumerate(candidates, 1):
            pump_emoji = "🔥" if candidate.avg_pump_score > 0.8 else "📈" if candidate.avg_pump_score > 0.7 else "📊"
            risk_emoji = "🔴" if candidate.avg_risk_score > 0.7 else "🟡" if candidate.avg_risk_score > 0.5 else "🟢"
            
            # Информация о ликвидности
            liquidity_info = ""
            if candidate.tradability_state:
                if candidate.tradability_state == TradabilityState.ILLIQUID.value:
                    liquidity_info = " 💧 ILLIQUID"
                elif candidate.tradability_state == TradabilityState.HIGH_LIQUIDITY.value:
                    liquidity_info = " 💧 HIGH_LIQUIDITY"
            
            # Информация о reliability
            reliability_info = ""
            if candidate.reliability_score is not None:
                rel_emoji = "🟢" if candidate.reliability_score > 0.7 else "🟡" if candidate.reliability_score > 0.5 else "🔴"
                reliability_info = f" • {rel_emoji} reliability {candidate.reliability_score:.2f}"
            
            # Информация об адаптивном пороге
            threshold_info = ""
            if candidate.effective_threshold is not None:
                threshold_info = f" • threshold {candidate.effective_threshold:.2f}"
            
            # Формируем строку с фазой
            phase_info = f" • {candidate.consensus_phase}"
            
            # Grade сетапа
            grade, grade_desc = self._calculate_grade(
                candidate.avg_pump_score,
                candidate.avg_risk_score,
                0.7,  # Упрощённо, можно добавить confidence в SetupCandidate
                candidate.effective_threshold
            )
            grade_emoji = "🟢" if grade == "A" else "🟡" if grade == "B" else "🔴"
            grade_info = f" • {grade_emoji} Grade {grade}"
            
            # Режим
            regime_info = ""
            if candidate.regime:
                regime_emoji = {
                    "risk_on": "🟢",
                    "risk_off": "🔴",
                    "alt_season": "🚀",
                    "btc_dominance": "₿",
                    "choppy": "🟡",
                    "panic": "⚠️"
                }.get(candidate.regime, "🌍")
                regime_info = f" • {regime_emoji} {candidate.regime.upper()}"
            
            lines.append(
                f"{i}) <b>{candidate.symbol}</b>{phase_info}{regime_info}{grade_info} • "
                f"{pump_emoji} Pump {candidate.avg_pump_score:.2f}"
                f"{f' (порог {candidate.effective_threshold:.2f})' if candidate.effective_threshold else ''} / "
                f"{risk_emoji} Risk {candidate.avg_risk_score:.2f}"
                f"{reliability_info}{liquidity_info}"
            )
            
            # Дополнительная информация о ликвидности
            if candidate.spread_bps and candidate.size_at_10bps:
                lines.append(
                    f"   💧 Спред: {candidate.spread_bps:.1f} bps, "
                    f"доступный объем: ~{candidate.size_at_10bps:.0f} USDT"
                )
            
            # Информация по таймфреймам
            for tf in timeframes:
                if tf in candidate.timeframes:
                    tf_data = candidate.timeframes[tf]
                    phase_emoji = self._get_phase_emoji(tf_data["phase"])
                    trend_emoji = self._get_trend_emoji(tf_data["trend"])
                    vol_emoji = self._get_volatility_emoji(tf_data["volatility"])
                    
                    lines.append(
                        f"   {tf}: {phase_emoji} {tf_data['phase']}, "
                        f"{trend_emoji} {tf_data['trend']}, "
                        f"{vol_emoji} {tf_data['volatility']}"
                    )
            
            lines.append("")
        
        # Показываем адаптивные пороги если есть
        if candidates and candidates[0].effective_threshold:
            lines.append(f"⚙ <b>Фильтр:</b> pump_score ≥ адаптивный порог (по режиму и истории актива), risk_score ≤ 0.7")
        else:
            lines.append(f"⚙ <b>Фильтр:</b> pump_score ≥ 0.7, risk_score ≤ 0.7")
        
        return "\n".join(lines)
    
    def _calculate_grade(self, pump_score: float, risk_score: float, confidence: float, effective_threshold: Optional[float] = None) -> tuple[str, str]:
        """Рассчитать Grade сетапа (A/B/C)."""
        threshold = effective_threshold if effective_threshold is not None else 0.7
        
        if pump_score >= threshold and risk_score <= 0.5 and confidence >= 0.7:
            return ("A", "сильный исторически устойчивый сетап")
        if pump_score >= 0.6 and risk_score <= 0.6:
            return ("B", "средний сетап")
        if pump_score < threshold:
            return ("C", f"Pump ниже порога ({threshold:.2f})")
        elif risk_score > 0.6:
            return ("C", "повышенный риск")
        else:
            return ("C", "слабый сетап")
    
    def _get_phase_emoji(self, phase: str) -> str:
        """Получить эмодзи для фазы."""
        emoji_map = {
            "ACCUMULATION": "📦",
            "DISTRIBUTION": "📤",
            "EXPANSION_UP": "🚀",
            "EXPANSION_DOWN": "📉",
            "SHAKEOUT": "⚡"
        }
        return emoji_map.get(phase, "📊")
    
    def _get_trend_emoji(self, trend: str) -> str:
        """Получить эмодзи для тренда."""
        emoji_map = {
            "BULLISH": "🟢",
            "BEARISH": "🔴",
            "NEUTRAL": "🟡"
        }
        return emoji_map.get(trend, "⚪")
    
    def _get_volatility_emoji(self, volatility: str) -> str:
        """Получить эмодзи для волатильности."""
        emoji_map = {
            "LOW": "🔵",
            "MEDIUM": "🟡",
            "HIGH": "🔴"
        }
        return emoji_map.get(volatility, "⚪")
    
    async def scan_user_watchlist(
        self,
        user_id: int,
        timeframes: List[str] = None
    ) -> List[SetupCandidate]:
        """
        Сканировать watchlist пользователя.
        
        Args:
            user_id: ID пользователя
            timeframes: Список таймфреймов
        
        Returns:
            Список кандидатов из watchlist пользователя
        """
        if timeframes is None:
            timeframes = ["4h", "1d"]
        
        # Получаем символы из watchlist
        symbols = self.watchlist_repo.get_user_watchlist(user_id)
        
        if not symbols:
            return []
        
        candidates = []
        
        # Анализируем каждый символ
        for symbol in symbols:
            try:
                candidate = await self._analyze_symbol(symbol, timeframes)
                if candidate:
                    candidates.append(candidate)
            except Exception as e:
                logger.debug(f"Failed to analyze {symbol} from watchlist: {e}")
                continue
        
        # Сортируем по pump_score
        candidates.sort(key=lambda x: x.avg_pump_score, reverse=True)
        
        return candidates

