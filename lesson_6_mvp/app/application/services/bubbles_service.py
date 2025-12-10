# app/application/services/bubbles_service.py
"""
Service for bubbles visualization.
"""

from typing import Dict, List
import io
import logging

logger = logging.getLogger("alt_forecast.services.bubbles")


class BubblesService:
    """Сервис для генерации пузырьковых диаграмм."""
    
    def __init__(self, market_data_service):
        """
        Args:
            market_data_service: MarketDataService instance
        """
        self.market_data = market_data_service
    
    def generate_bubbles(
        self,
        coins: List[Dict],
        tf: str,
        count: int = 50,
        hide_stables: bool = True,
        seed: int = 42,
        size_mode: str = "percent",
    ) -> io.BytesIO:
        """
        Сгенерировать пузырьковую диаграмму.
        
        Args:
            coins: Список монет с данными
            tf: Таймфрейм (15m, 1h, 1d)
            count: Количество пузырьков
            hide_stables: Скрыть стейблы
            seed: Seed для генерации позиций
            size_mode: Режим размера (percent, cap, volume_share, volume_24h)
        
        Returns:
            BytesIO: PNG изображение
        """
        from ...visual.bubbles import render_bubbles
        
        # Маппинг режима размера
        size_mode_map = {
            "percent": "percent",
            "cap": "rank",
            "volume_share": "volume_share",
            "volume_24h": "volume_24h"
        }
        render_size_mode = size_mode_map.get(size_mode, "percent")
        
        return render_bubbles(
            coins=coins,
            tf=tf,
            count=count,
            hide_stables=hide_stables,
            seed=seed,
            color_mode="quantile",
            size_mode=render_size_mode,
        )
    
    def prepare_bubbles_data(
        self,
        coins: List[Dict],
        size_mode: str,
        total_volume_24h: float = 0.0,
    ) -> List[Dict]:
        """
        Подготовить данные для рендеринга пузырьков.
        
        Args:
            coins: Список монет
            size_mode: Режим размера
            total_volume_24h: Общий объем 24ч (для volume_share)
        
        Returns:
            List[Dict]: Подготовленные данные
        """
        coins_for_render = coins.copy()
        
        if size_mode in ("volume_share", "volume_24h"):
            # Добавляем volume_share для режимов объема
            for c in coins_for_render:
                vol = float(c.get("total_volume", 0) or 0)
                if total_volume_24h > 0:
                    c["volume_share"] = vol / total_volume_24h
                else:
                    c["volume_share"] = 0.0
        
        return coins_for_render

