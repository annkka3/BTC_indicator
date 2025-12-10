# app/domain/market_regime/global_regime_analyzer.py
"""
Анализатор глобального режима рынка криптовалют.

Анализирует:
- BTC (1h/4h/1d)
- TOTAL2/TOTAL3 (альткоины)
- USDT.D / USDC.D (доминирование стейблкоинов)
- Funding/OI по рынку
- Волатильность BTC (crypto VIX)
"""

from enum import Enum
from dataclasses import dataclass
from typing import Dict, Optional, List, TYPE_CHECKING
from datetime import datetime, timedelta
import logging
import numpy as np

if TYPE_CHECKING:
    from ...domain.interfaces.idb import IDatabase
    from ...domain.interfaces.imarket_data_service import IMarketDataService
else:
    IDatabase = object
    IMarketDataService = object

logger = logging.getLogger("alt_forecast.market_regime")


class GlobalRegime(str, Enum):
    """Глобальный режим рынка."""
    RISK_ON = "risk_on"              # Рост, аппетит к риску высокий
    RISK_OFF = "risk_off"             # Падение, бегство в безопасность
    BTC_DOMINANCE = "btc_dominance"   # Доминирование BTC, альты слабеют
    ALT_SEASON = "alt_season"         # Сезон альткоинов, альты растут быстрее BTC
    CHOPPY = "choppy"                 # Боковик, высокая волатильность без направления
    PANIC = "panic"                   # Паника, экстремальная волатильность и падение


@dataclass
class RegimeSnapshot:
    """Снимок режима рынка."""
    regime: GlobalRegime
    confidence: float  # 0.0 - 1.0, уверенность в определении режима
    
    # Метрики
    btc_change_1h: float
    btc_change_4h: float
    btc_change_24h: float
    btc_volatility: float  # Волатильность BTC (crypto VIX)
    
    total2_change_24h: Optional[float] = None
    total3_change_24h: Optional[float] = None
    usdt_dominance: Optional[float] = None
    
    avg_funding: Optional[float] = None  # Средний funding rate по рынку
    oi_change: Optional[float] = None    # Изменение OI
    
    # Дополнительные сигналы
    btc_trend: str = "NEUTRAL"  # BULLISH, BEARISH, NEUTRAL
    alt_performance_vs_btc: float = 0.0  # Насколько альты опережают/отстают от BTC
    
    description: str = ""  # Текстовое описание режима


class GlobalRegimeAnalyzer:
    """Анализатор глобального режима рынка."""
    
    def __init__(
        self,
        db: IDatabase,
        market_data_service: IMarketDataService,
        cache_ttl_seconds: int = 60
    ):
        """
        Args:
            db: Database instance (реализует IDatabase интерфейс)
            market_data_service: Сервис рыночных данных (реализует IMarketDataService интерфейс)
            cache_ttl_seconds: TTL кэша в секундах (по умолчанию 60)
        """
        self.db = db
        self.data_service = market_data_service
        self._cache: Optional[RegimeSnapshot] = None
        self._cache_ts: Optional[datetime] = None
        self._cache_ttl = timedelta(seconds=cache_ttl_seconds)
    
    def analyze_current_regime(self) -> RegimeSnapshot:
        """
        Проанализировать текущий режим рынка.
        
        Использует кэширование для оптимизации производительности.
        
        Returns:
            RegimeSnapshot с текущим режимом и метриками
        """
        # Проверяем кэш
        now = datetime.utcnow()
        if self._cache and self._cache_ts and (now - self._cache_ts) < self._cache_ttl:
            logger.debug(f"Using cached regime: {self._cache.regime.value}")
            return self._cache
        
        # Вычисляем режим
        try:
            # Получаем данные BTC
            btc_data = self._get_btc_data()
            if not btc_data:
                logger.warning("Failed to get BTC data for regime analysis")
                return self._default_regime()
            
            # Получаем данные альткоинов
            alt_data = self._get_alt_data()
            
            # Получаем данные деривативов
            derivatives_data = self._get_derivatives_data()
            
            # Определяем режим
            regime, confidence = self._determine_regime(
                btc_data, alt_data, derivatives_data
            )
            
            # Формируем описание
            description = self._generate_description(regime, btc_data, alt_data)
            
            snapshot = RegimeSnapshot(
                regime=regime,
                confidence=confidence,
                btc_change_1h=btc_data.get('change_1h', 0.0),
                btc_change_4h=btc_data.get('change_4h', 0.0),
                btc_change_24h=btc_data.get('change_24h', 0.0),
                btc_volatility=btc_data.get('volatility', 0.0),
                total2_change_24h=alt_data.get('total2_change'),
                total3_change_24h=alt_data.get('total3_change'),
                usdt_dominance=alt_data.get('usdt_dominance'),
                avg_funding=derivatives_data.get('avg_funding'),
                oi_change=derivatives_data.get('oi_change'),
                btc_trend=btc_data.get('trend', 'NEUTRAL'),
                alt_performance_vs_btc=alt_data.get('performance_vs_btc', 0.0),
                description=description
            )
            
            # Сохраняем в кэш
            self._cache = snapshot
            self._cache_ts = now
            
            return snapshot
        except Exception as e:
            logger.exception(f"Error analyzing regime: {e}")
            return self._default_regime()
    
    def _get_btc_data(self) -> Optional[Dict]:
        """Получить данные BTC."""
        try:
            # Получаем бары BTC для разных таймфреймов
            bars_1h = self.db.last_n("BTC", "1h", 24)
            bars_4h = self.db.last_n("BTC", "4h", 24)
            bars_1d = self.db.last_n("BTC", "1d", 30)
            
            if not bars_1h or not bars_4h or not bars_1d:
                return None
            
            # Вычисляем изменения
            current_price_1h = bars_1h[-1][4]  # close
            price_1h_ago = bars_1h[0][4] if len(bars_1h) >= 24 else current_price_1h
            
            current_price_4h = bars_4h[-1][4]
            price_4h_ago = bars_4h[0][4] if len(bars_4h) >= 6 else current_price_4h
            
            current_price_1d = bars_1d[-1][4]
            price_1d_ago = bars_1d[0][4] if len(bars_1d) >= 2 else current_price_1d
            
            change_1h = ((current_price_1h - price_1h_ago) / price_1h_ago) * 100 if price_1h_ago > 0 else 0.0
            change_4h = ((current_price_4h - price_4h_ago) / price_4h_ago) * 100 if price_4h_ago > 0 else 0.0
            change_24h = ((current_price_1d - price_1d_ago) / price_1d_ago) * 100 if price_1d_ago > 0 else 0.0
            
            # Вычисляем волатильность (ATR за последние 24 часа)
            volatility = self._calculate_volatility(bars_1h[-24:])
            
            # Определяем тренд
            trend = self._determine_trend(change_1h, change_4h, change_24h)
            
            return {
                'change_1h': change_1h,
                'change_4h': change_4h,
                'change_24h': change_24h,
                'volatility': volatility,
                'trend': trend,
                'current_price': current_price_1d
            }
        except Exception as e:
            logger.exception(f"Error getting BTC data: {e}")
            return None
    
    def _get_alt_data(self) -> Dict:
        """Получить данные альткоинов."""
        try:
            # Пробуем получить TOTAL2 и TOTAL3
            total2_bars = self.db.last_n("TOTAL2", "1d", 7)
            total3_bars = self.db.last_n("TOTAL3", "1d", 7)
            
            total2_change = None
            total3_change = None
            
            if total2_bars and len(total2_bars) >= 2:
                current = total2_bars[-1][4]
                previous = total2_bars[0][4]
                total2_change = ((current - previous) / previous) * 100 if previous > 0 else 0.0
            
            if total3_bars and len(total3_bars) >= 2:
                current = total3_bars[-1][4]
                previous = total3_bars[0][4]
                total3_change = ((current - previous) / previous) * 100 if previous > 0 else 0.0
            
            # Получаем BTC для сравнения
            btc_bars = self.db.last_n("BTC", "1d", 7)
            btc_change = None
            if btc_bars and len(btc_bars) >= 2:
                current = btc_bars[-1][4]
                previous = btc_bars[0][4]
                btc_change = ((current - previous) / previous) * 100 if previous > 0 else 0.0
            
            # Вычисляем performance альтов vs BTC
            performance_vs_btc = 0.0
            if total2_change is not None and btc_change is not None:
                performance_vs_btc = total2_change - btc_change
            
            # Пробуем получить USDT.D
            usdt_d_bars = self.db.last_n("USDT.D", "1d", 7)
            usdt_dominance = None
            if usdt_d_bars and len(usdt_d_bars) >= 1:
                usdt_dominance = usdt_d_bars[-1][4]
            
            return {
                'total2_change': total2_change,
                'total3_change': total3_change,
                'usdt_dominance': usdt_dominance,
                'performance_vs_btc': performance_vs_btc
            }
        except Exception as e:
            logger.debug(f"Error getting alt data: {e}")
            return {}
    
    def _get_derivatives_data(self) -> Dict:
        """Получить данные деривативов."""
        # TODO: Интегрировать с реальными данными funding/OI
        # Пока возвращаем пустой словарь
        return {}
    
    def _calculate_volatility(self, bars: List) -> float:
        """Вычислить волатильность (ATR)."""
        if len(bars) < 2:
            return 0.0
        
        try:
            trs = []
            for i in range(1, len(bars)):
                high = bars[i][2]
                low = bars[i][3]
                prev_close = bars[i-1][4]
                
                tr = max(
                    high - low,
                    abs(high - prev_close),
                    abs(low - prev_close)
                )
                trs.append(tr)
            
            if not trs:
                return 0.0
            
            atr = np.mean(trs)
            current_price = bars[-1][4]
            return (atr / current_price) * 100 if current_price > 0 else 0.0
        except Exception:
            return 0.0
    
    def _determine_trend(self, change_1h: float, change_4h: float, change_24h: float) -> str:
        """Определить тренд BTC."""
        # Взвешенное среднее (больше вес у более долгосрочных изменений)
        weighted_change = (change_1h * 0.2) + (change_4h * 0.3) + (change_24h * 0.5)
        
        if weighted_change > 2.0:
            return "BULLISH"
        elif weighted_change < -2.0:
            return "BEARISH"
        else:
            return "NEUTRAL"
    
    def _determine_regime(
        self,
        btc_data: Dict,
        alt_data: Dict,
        derivatives_data: Dict
    ) -> tuple[GlobalRegime, float]:
        """
        Определить режим рынка на основе данных.
        
        Returns:
            (regime, confidence)
        """
        change_24h = btc_data.get('change_24h', 0.0)
        volatility = btc_data.get('volatility', 0.0)
        trend = btc_data.get('trend', 'NEUTRAL')
        alt_performance = alt_data.get('performance_vs_btc', 0.0)
        usdt_dominance = alt_data.get('usdt_dominance')
        
        # PANIC: экстремальная волатильность + сильное падение
        if volatility > 10.0 and change_24h < -10.0:
            return GlobalRegime.PANIC, 0.9
        
        # RISK_OFF: падение + высокая волатильность
        if change_24h < -5.0 and volatility > 5.0:
            return GlobalRegime.RISK_OFF, 0.85
        
        # RISK_ON: рост + умеренная волатильность
        if change_24h > 3.0 and volatility < 4.0:
            return GlobalRegime.RISK_ON, 0.8
        
        # ALT_SEASON: альты опережают BTC значительно
        if alt_performance > 5.0 and change_24h > 0:
            return GlobalRegime.ALT_SEASON, 0.75
        
        # BTC_DOMINANCE: BTC растет, альты отстают или падают
        if change_24h > 2.0 and alt_performance < -2.0:
            return GlobalRegime.BTC_DOMINANCE, 0.75
        
        # CHOPPY: высокая волатильность без четкого направления
        if volatility > 5.0 and abs(change_24h) < 3.0:
            return GlobalRegime.CHOPPY, 0.7
        
        # По умолчанию - нейтральный режим
        if change_24h > 0:
            return GlobalRegime.RISK_ON, 0.6
        else:
            return GlobalRegime.RISK_OFF, 0.6
    
    def _generate_description(
        self,
        regime: GlobalRegime,
        btc_data: Dict,
        alt_data: Dict
    ) -> str:
        """Сгенерировать текстовое описание режима."""
        change_24h = btc_data.get('change_24h', 0.0)
        volatility = btc_data.get('volatility', 0.0)
        alt_performance = alt_data.get('performance_vs_btc', 0.0)
        
        descriptions = {
            GlobalRegime.RISK_ON: f"Рост рынка, BTC +{change_24h:.1f}%, волатильность {volatility:.1f}%",
            GlobalRegime.RISK_OFF: f"Падение рынка, BTC {change_24h:.1f}%, волатильность {volatility:.1f}%",
            GlobalRegime.BTC_DOMINANCE: f"Доминирование BTC, альты отстают на {abs(alt_performance):.1f}%",
            GlobalRegime.ALT_SEASON: f"Сезон альткоинов, альты опережают BTC на {alt_performance:.1f}%",
            GlobalRegime.CHOPPY: f"Боковик, высокая волатильность {volatility:.1f}% без четкого направления",
            GlobalRegime.PANIC: f"Паника на рынке, экстремальная волатильность {volatility:.1f}%"
        }
        
        return descriptions.get(regime, "Неопределенный режим")
    
    def _default_regime(self) -> RegimeSnapshot:
        """Вернуть режим по умолчанию при ошибке."""
        return RegimeSnapshot(
            regime=GlobalRegime.CHOPPY,
            confidence=0.5,
            btc_change_1h=0.0,
            btc_change_4h=0.0,
            btc_change_24h=0.0,
            btc_volatility=0.0,
            description="Недостаточно данных для анализа режима"
        )


