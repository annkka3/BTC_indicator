# app/domain/sentiment/__init__.py
"""
Модуль для анализа новостей и сентимента рынка.
"""

from .sentiment_analyzer import SentimentAnalyzer, SentimentSnapshot, NewsEvent

__all__ = [
    "SentimentAnalyzer",
    "SentimentSnapshot",
    "NewsEvent",
]






