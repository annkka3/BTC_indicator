# app/application/dto/bubbles_dto.py
"""
DTOs for bubbles functionality.
"""

from dataclasses import dataclass
from typing import List, Dict, Optional


@dataclass
class BubblesSettingsDTO:
    """DTO для настроек пузырьков."""
    count: int = 50
    hide_stables: bool = True
    seed: int = 42
    size_mode: str = "percent"  # percent, cap, volume_share, volume_24h
    top: int = 500  # 100, 200, 300, 400, 500
    tf: str = "1d"  # 15m, 1h, 1d


@dataclass
class BubblesRequestDTO:
    """DTO для запроса генерации пузырьков."""
    tf: str
    settings: BubblesSettingsDTO
    coins: Optional[List[Dict]] = None
    vs_currency: str = "usd"

