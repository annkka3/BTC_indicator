# app/domain/twap_detector/aggregator.py
"""
Агрегатор данных по биржам и формирование отчёта.
"""

from typing import List, Dict, Optional
from dataclasses import dataclass
from datetime import datetime
import logging

from .exchange_client import ExchangeClient, get_exchange_clients
from .pattern_analyzer import TWAPPatternAnalyzer, ExchangeAnalysis

logger = logging.getLogger("alt_forecast.twap_detector")


@dataclass
class TWAPReport:
    """Отчёт по TWAP-алгоритмам."""
    symbol: str
    timestamp: datetime
    window_minutes: int
    exchanges: List[ExchangeAnalysis]
    
    # Агрегированные метрики
    total_algo_volume_usd: float
    total_net_flow_usd: float
    dominant_direction: str  # "BUY", "SELL", "NEUTRAL"
    buy_exchanges: List[str]  # Биржи с доминированием покупок
    sell_exchanges: List[str]  # Биржи с доминированием продаж
    avg_algo_score: float
    
    # Синхронность паттернов
    synchronization_score: float  # 0.0 - 1.0 (насколько синхронны паттерны между биржами)


class TWAPDetector:
    """Детектор TWAP-алгоритмов на нескольких биржах."""
    
    def __init__(self, db=None):
        """
        Инициализация детектора.
        
        Args:
            db: Экземпляр DB для использования кэшированных данных (опционально)
        """
        self.exchange_clients = get_exchange_clients()
        self.pattern_analyzer = TWAPPatternAnalyzer()
        self.db = db
    
    def detect_patterns(
        self,
        symbol: str,
        window_minutes: int = 15,
        current_price: Optional[float] = None
    ) -> TWAPReport:
        """
        Детектировать TWAP-паттерны на всех биржах.
        
        Args:
            symbol: Символ торговли (например, BTCUSDT)
            window_minutes: Окно анализа в минутах
            current_price: Текущая цена (опционально, будет получена из последней сделки)
        
        Returns:
            TWAPReport с результатами анализа
        """
        # Рассчитываем временную метку начала окна
        now_ms = int(datetime.now().timestamp() * 1000)
        since_ms = now_ms - (window_minutes * 60 * 1000)
        until_ms = now_ms
        
        # Получаем сделки со всех бирж
        exchange_analyses = []
        
        # Если есть БД, сначала пытаемся получить данные из кэша
        if self.db:
            try:
                # Получаем все сделки из БД за период
                all_trades = self.db.get_trades_by_period(symbol, since_ms, until_ms)
                
                if all_trades:
                    # Группируем сделки по биржам
                    trades_by_exchange = {}
                    for trade in all_trades:
                        exchange = trade["exchange"]
                        if exchange not in trades_by_exchange:
                            trades_by_exchange[exchange] = []
                        trades_by_exchange[exchange].append(trade)
                    
                    # Анализируем сделки по каждой бирже
                    for exchange, trades in trades_by_exchange.items():
                        try:
                            if not trades:
                                continue
                            
                            # Определяем текущую цену из последней сделки, если не указана
                            if current_price is None:
                                current_price = trades[-1]["price"]
                            
                            # Анализируем паттерны
                            analysis = self.pattern_analyzer.analyze_trades(trades, current_price)
                            analysis.exchange = exchange
                            exchange_analyses.append(analysis)
                            
                        except Exception as e:
                            logger.exception(f"Error analyzing {exchange} for {symbol} from DB: {e}")
                            continue
                    
                    # Если получили данные из БД, используем их
                    if exchange_analyses:
                        logger.debug(f"Using cached trades from DB for {symbol}: {len(exchange_analyses)} exchanges")
                        return self._build_report(symbol, window_minutes, exchange_analyses, current_price)
            except Exception as e:
                logger.warning(f"Error getting trades from DB for {symbol}, falling back to API: {e}")
        
        # Fallback: получаем сделки напрямую с бирж через API
        for client in self.exchange_clients:
            try:
                # Получаем ВСЕ сделки за период с пагинацией
                trades = client.get_all_trades(symbol, since_ms, until_ms)
                
                if not trades:
                    logger.debug(f"No trades from {client.name} for {symbol}")
                    continue
                
                # Определяем текущую цену из последней сделки, если не указана
                if current_price is None:
                    current_price = trades[-1]["price"]
                
                # Анализируем паттерны
                analysis = self.pattern_analyzer.analyze_trades(trades, current_price)
                analysis.exchange = client.name  # Убеждаемся, что имя биржи установлено
                exchange_analyses.append(analysis)
                
            except Exception as e:
                logger.exception(f"Error analyzing {client.name} for {symbol}: {e}")
                continue
        
        # Формируем отчёт
        return self._build_report(symbol, window_minutes, exchange_analyses, current_price)
    
    def _build_report(
        self,
        symbol: str,
        window_minutes: int,
        exchange_analyses: List[ExchangeAnalysis],
        current_price: float
    ) -> TWAPReport:
        """Построить отчёт из анализов бирж."""
        if not exchange_analyses:
            return TWAPReport(
                symbol=symbol,
                timestamp=datetime.now(),
                window_minutes=window_minutes,
                exchanges=[],
                total_algo_volume_usd=0.0,
                total_net_flow_usd=0.0,
                dominant_direction="NEUTRAL",
                buy_exchanges=[],
                sell_exchanges=[],
                avg_algo_score=0.0,
                synchronization_score=0.0,
            )
        
        # Агрегируем метрики
        total_algo_volume_usd = sum(a.algo_volume_usd for a in exchange_analyses)
        total_net_flow_usd = sum(a.net_flow_usd for a in exchange_analyses)
        avg_algo_score = sum(a.algo_score for a in exchange_analyses) / len(exchange_analyses)
        
        # Определяем биржи с покупками и продажами
        buy_exchanges = [a.exchange for a in exchange_analyses if a.direction == "BUY"]
        sell_exchanges = [a.exchange for a in exchange_analyses if a.direction == "SELL"]
        
        # Определяем доминирующее направление
        buy_count = len(buy_exchanges)
        sell_count = len(sell_exchanges)
        
        if buy_count > sell_count:
            dominant_direction = "BUY"
        elif sell_count > buy_count:
            dominant_direction = "SELL"
        else:
            dominant_direction = "NEUTRAL"
        
        # Рассчитываем синхронность паттернов
        synchronization_score = self._calculate_synchronization(exchange_analyses)
        
        return TWAPReport(
            symbol=symbol,
            timestamp=datetime.now(),
            window_minutes=window_minutes,
            exchanges=exchange_analyses,
            total_algo_volume_usd=total_algo_volume_usd,
            total_net_flow_usd=total_net_flow_usd,
            dominant_direction=dominant_direction,
            buy_exchanges=buy_exchanges,
            sell_exchanges=sell_exchanges,
            avg_algo_score=avg_algo_score,
            synchronization_score=synchronization_score,
        )
    
    def _calculate_synchronization(self, analyses: List[ExchangeAnalysis]) -> float:
        """
        Рассчитать синхронность паттернов между биржами.
        
        Высокая синхронность = все биржи показывают одинаковое направление.
        """
        if len(analyses) < 2:
            return 1.0 if len(analyses) == 1 else 0.0
        
        # Группируем по направлению
        directions = [a.direction for a in analyses]
        
        # Если все направления одинаковые, синхронность = 1.0
        if len(set(directions)) == 1:
            return 1.0
        
        # Если есть конфликт, синхронность снижается
        buy_count = directions.count("BUY")
        sell_count = directions.count("SELL")
        neutral_count = directions.count("NEUTRAL")
        
        # Максимальная группа определяет синхронность
        max_group = max(buy_count, sell_count, neutral_count)
        synchronization_score = max_group / len(analyses)
        
        return synchronization_score


