# app/infrastructure/repositories/user_repository.py
"""
Repository for user settings and preferences.
"""

from typing import Tuple
from .base_repository import BaseRepository


class UserRepository(BaseRepository):
    """Репозиторий для работы с настройками пользователей."""
    
    def get_settings(self, user_id: int) -> Tuple[str, int, int, int, int, int, str, int, str]:
        """
        Получить настройки пользователя.
        
        Returns:
            Tuple: (vs_currency, bubbles_count, bubbles_hide_stables, bubbles_seed, 
                   daily_digest, daily_hour, bubbles_size_mode, bubbles_top, bubbles_tf)
        """
        return self.db.get_user_settings(user_id)
    
    def update_settings(self, user_id: int, **kwargs):
        """Обновить настройки пользователя."""
        self.db.set_user_settings(user_id, **kwargs)
    
    def get_bubbles_settings(self, user_id: int) -> dict:
        """Получить настройки пузырьков для пользователя."""
        vs, count, hide, seed, daily, hour, size_mode, top, tf = self.get_settings(user_id)
        return {
            "count": count,
            "hide_stables": bool(hide),
            "seed": seed,
            "size_mode": size_mode,
            "top": top,
            "tf": tf,
        }
    
    def update_bubbles_settings(self, user_id: int, **kwargs):
        """Обновить настройки пузырьков."""
        allowed_keys = {
            "bubbles_count", "bubbles_hide_stables", "bubbles_seed",
            "bubbles_size_mode", "bubbles_top", "bubbles_tf"
        }
        filtered_kwargs = {k: v for k, v in kwargs.items() if k in allowed_keys}
        if filtered_kwargs:
            self.update_settings(user_id, **filtered_kwargs)

