# app/infrastructure/repositories/subscription_repository.py
"""
Repository for user subscriptions.
"""

from typing import List
from .base_repository import BaseRepository


class SubscriptionRepository(BaseRepository):
    """Репозиторий для работы с подписками пользователей."""
    
    def add_subscription(self, chat_id: int):
        """Добавить подписку."""
        self.db.add_sub(chat_id)
    
    def remove_subscription(self, chat_id: int):
        """Удалить подписку."""
        self.db.remove_sub(chat_id)
    
    def list_subscriptions(self) -> List[int]:
        """Получить список всех подписок."""
        return self.db.list_subs()
    
    def list_daily_subscriptions(self, hour: int) -> List[int]:
        """Получить список подписок на ежедневный дайджест для указанного часа."""
        return self.db.list_daily_users(hour)

