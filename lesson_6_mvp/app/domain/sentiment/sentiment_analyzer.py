# app/domain/sentiment/sentiment_analyzer.py
"""
Анализатор новостей и сентимента для Market Doctor.
"""

from dataclasses import dataclass
from typing import List, Optional
from enum import Enum
from datetime import datetime, timedelta
import logging

logger = logging.getLogger("alt_forecast.sentiment")


class NewsType(str, Enum):
    """Тип новости."""
    PROTOCOL_UPDATE = "protocol_update"      # Обновление протокола
    LISTING = "listing"                       # Листинг на бирже
    DELISTING = "delisting"                  # Делистинг
    HACK = "hack"                            # Взлом/эксплойт
    REGULATION = "regulation"                 # Регуляторные новости
    PARTNERSHIP = "partnership"               # Партнерство
    FUNDING = "funding"                       # Фандрайзинг
    OTHER = "other"                           # Прочее


class NewsSentiment(str, Enum):
    """Сентимент новости."""
    POSITIVE = "positive"     # Позитивная новость
    NEGATIVE = "negative"     # Негативная новость
    NEUTRAL = "neutral"       # Нейтральная новость


@dataclass
class NewsEvent:
    """Событие новости."""
    symbol: str
    news_type: NewsType
    sentiment: NewsSentiment
    title: str
    source: Optional[str] = None
    timestamp: Optional[datetime] = None
    impact_score: float = 0.5  # 0.0 - 1.0, влияние на рынок


@dataclass
class SentimentSnapshot:
    """Снимок сентимента и новостей."""
    symbol: str
    recent_news: List[NewsEvent]
    has_significant_news: bool
    overall_sentiment: NewsSentiment
    risk_flags: List[str]
    
    def get_description(self) -> str:
        """Получить текстовое описание сентимента."""
        if not self.recent_news:
            return "📰 Последние события: за последние 12 часов значимых новостей не обнаружено."
        
        positive_count = sum(1 for n in self.recent_news if n.sentiment == NewsSentiment.POSITIVE)
        negative_count = sum(1 for n in self.recent_news if n.sentiment == NewsSentiment.NEGATIVE)
        
        if self.has_significant_news:
            if negative_count > positive_count:
                return (
                    f"🧨 Обнаружены негативные новости ({negative_count} событий) — "
                    f"даже при хорошем тех.сетапе рекомендуется снижать риск."
                )
            elif positive_count > negative_count:
                return (
                    f"📰 Последние события: за 12 часов найдено {len(self.recent_news)} значимых новостей "
                    f"({positive_count} позитивных). Риски новостного гэпа снижены."
                )
            else:
                return (
                    f"📰 Последние события: за 12 часов найдено {len(self.recent_news)} значимых новостей. "
                    f"Риски новостного гэпа требуют внимания."
                )
        else:
            return f"📰 Последние события: за 12 часов найдено {len(self.recent_news)} новостей (незначимых)."


class SentimentAnalyzer:
    """Анализатор новостей и сентимента."""
    
    def __init__(self, db=None):
        """
        Args:
            db: Database instance (опционально, для хранения новостей)
        """
        self.db = db
    
    def analyze_sentiment(
        self,
        symbol: str,
        hours_back: int = 12
    ) -> SentimentSnapshot:
        """
        Проанализировать новости и сентимент для символа.
        
        Args:
            symbol: Символ монеты
            hours_back: Сколько часов назад искать новости
        
        Returns:
            SentimentSnapshot с результатами анализа
        """
        # TODO: Интегрировать с реальным новостным API/RSS
        # Пока возвращаем пустой результат
        
        # В реальной реализации здесь будет:
        # 1. Запрос к новостному API (CoinGecko, CryptoCompare, CryptoPanic и т.д.)
        # 2. Парсинг RSS фидов
        # 3. Анализ сентимента (можно использовать простой keyword-based подход)
        # 4. Фильтрация по типу новостей (листинги, хак, регуляция и т.д.)
        
        recent_news = self._fetch_recent_news(symbol, hours_back)
        
        # Определяем значимость новостей
        significant_news = [
            n for n in recent_news
            if n.impact_score > 0.6 or n.news_type in [NewsType.HACK, NewsType.DELISTING, NewsType.REGULATION]
        ]
        has_significant_news = len(significant_news) > 0
        
        # Определяем общий сентимент
        if not recent_news:
            overall_sentiment = NewsSentiment.NEUTRAL
        else:
            positive = sum(1 for n in recent_news if n.sentiment == NewsSentiment.POSITIVE)
            negative = sum(1 for n in recent_news if n.sentiment == NewsSentiment.NEGATIVE)
            if positive > negative:
                overall_sentiment = NewsSentiment.POSITIVE
            elif negative > positive:
                overall_sentiment = NewsSentiment.NEGATIVE
            else:
                overall_sentiment = NewsSentiment.NEUTRAL
        
        # Формируем флаги риска
        risk_flags = []
        if any(n.news_type == NewsType.HACK for n in recent_news):
            risk_flags.append("Взлом/эксплойт")
        if any(n.news_type == NewsType.DELISTING for n in recent_news):
            risk_flags.append("Делистинг")
        if any(n.news_type == NewsType.REGULATION for n in recent_news):
            risk_flags.append("Регуляторный риск")
        
        return SentimentSnapshot(
            symbol=symbol,
            recent_news=recent_news,
            has_significant_news=has_significant_news,
            overall_sentiment=overall_sentiment,
            risk_flags=risk_flags
        )
    
    def _fetch_recent_news(self, symbol: str, hours_back: int) -> List[NewsEvent]:
        """
        Получить последние новости для символа.
        
        TODO: Интегрировать с реальным источником новостей.
        """
        # Пока возвращаем пустой список
        # В реальной реализации здесь будет запрос к API
        
        # Пример структуры:
        # news_items = news_api.get_news(symbol, hours_back=hours_back)
        # events = []
        # for item in news_items:
        #     event = NewsEvent(
        #         symbol=symbol,
        #         news_type=self._classify_news_type(item),
        #         sentiment=self._analyze_sentiment(item),
        #         title=item.title,
        #         source=item.source,
        #         timestamp=item.timestamp,
        #         impact_score=self._calculate_impact(item)
        #     )
        #     events.append(event)
        # return events
        
        return []
    
    def _classify_news_type(self, news_item) -> NewsType:
        """Классифицировать тип новости (TODO: реализовать)."""
        # Простой keyword-based классификатор
        title_lower = news_item.get('title', '').lower()
        
        if any(word in title_lower for word in ['hack', 'exploit', 'breach', 'stolen']):
            return NewsType.HACK
        elif any(word in title_lower for word in ['listing', 'listed']):
            return NewsType.LISTING
        elif any(word in title_lower for word in ['delisting', 'delisted']):
            return NewsType.DELISTING
        elif any(word in title_lower for word in ['regulation', 'sec', 'regulatory']):
            return NewsType.REGULATION
        elif any(word in title_lower for word in ['update', 'upgrade', 'hard fork']):
            return NewsType.PROTOCOL_UPDATE
        elif any(word in title_lower for word in ['partnership', 'partners']):
            return NewsType.PARTNERSHIP
        elif any(word in title_lower for word in ['funding', 'raise', 'investment']):
            return NewsType.FUNDING
        else:
            return NewsType.OTHER
    
    def _analyze_sentiment(self, news_item) -> NewsSentiment:
        """Проанализировать сентимент новости (TODO: реализовать)."""
        # Простой keyword-based анализ
        title_lower = news_item.get('title', '').lower()
        
        positive_words = ['bullish', 'surge', 'rally', 'partnership', 'listing', 'upgrade']
        negative_words = ['crash', 'hack', 'exploit', 'delisting', 'regulation', 'ban']
        
        positive_count = sum(1 for word in positive_words if word in title_lower)
        negative_count = sum(1 for word in negative_words if word in title_lower)
        
        if positive_count > negative_count:
            return NewsSentiment.POSITIVE
        elif negative_count > positive_count:
            return NewsSentiment.NEGATIVE
        else:
            return NewsSentiment.NEUTRAL
    
    def _calculate_impact(self, news_item) -> float:
        """Рассчитать влияние новости на рынок (TODO: реализовать)."""
        # Простая эвристика: хак, делистинг, регуляция = высокое влияние
        news_type = self._classify_news_type(news_item)
        
        high_impact_types = [NewsType.HACK, NewsType.DELISTING, NewsType.REGULATION]
        if news_type in high_impact_types:
            return 0.9
        
        medium_impact_types = [NewsType.LISTING, NewsType.PROTOCOL_UPDATE]
        if news_type in medium_impact_types:
            return 0.6
        
        return 0.3






