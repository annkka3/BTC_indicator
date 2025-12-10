# app/domain/portfolio/portfolio_state.py
"""
Состояние портфеля пользователя.
"""

from dataclasses import dataclass, field
from typing import List, Optional, Dict
from enum import Enum
from datetime import datetime


class Sector(str, Enum):
    """Секторы криптовалют."""
    AI = "ai"                    # AI-альты (AGIX, FET, RNDR и т.д.)
    L1 = "l1"                    # Layer 1 (ETH, SOL, AVAX, ADA и т.д.)
    L2 = "l2"                    # Layer 2 (ARB, OP, MATIC и т.д.)
    DEFI = "defi"                # DeFi (UNI, AAVE, COMP и т.д.)
    MEME = "meme"                # Мемкоины (DOGE, SHIB, PEPE и т.д.)
    GAMING = "gaming"            # GameFi (AXS, SAND, MANA и т.д.)
    NFT = "nft"                  # NFT (FLOW, ENJ и т.д.)
    STABLECOIN = "stablecoin"    # Стейблкоины
    EXCHANGE = "exchange"         # Токены бирж (BNB, FTT и т.д.)
    OTHER = "other"              # Прочее


@dataclass
class Position:
    """Открытая позиция пользователя."""
    symbol: str                  # Символ монеты (BTC, ETH и т.д.)
    side: str                    # "long" или "short"
    size: float                  # Размер позиции в USDT
    entry_price: float           # Цена входа
    current_price: Optional[float] = None  # Текущая цена (для расчета PnL)
    sector: Optional[Sector] = None  # Сектор (опционально)
    leverage: float = 1.0        # Плечо (1.0 = спот)
    risk_r: Optional[float] = None  # Риск в R (если известен)
    opened_at: Optional[datetime] = None  # Время открытия


@dataclass
class PortfolioState:
    """Состояние портфеля пользователя."""
    user_id: int
    positions: List[Position] = field(default_factory=list)
    total_equity: float = 0.0    # Общий капитал в USDT
    cash_available: float = 0.0  # Доступный кэш в USDT
    
    # Концентрация по секторам
    sector_exposure: Dict[Sector, float] = field(default_factory=dict)
    
    # Риск-метрики
    total_risk_r: float = 0.0    # Суммарный риск в R
    max_sector_exposure: float = 0.0  # Максимальная экспозиция к одному сектору (%)
    
    # Дополнительные метрики
    long_exposure: float = 0.0   # Общая экспозиция лонгов в USDT
    short_exposure: float = 0.0  # Общая экспозиция шортов в USDT
    net_exposure: float = 0.0    # Чистая экспозиция (long - short)
    
    def get_sector_for_symbol(self, symbol: str) -> Optional[Sector]:
        """
        Определить сектор для символа.
        
        TODO: Можно расширить словарь или использовать внешний источник.
        """
        symbol_upper = symbol.upper()
        
        # AI сектор
        ai_symbols = ["AGIX", "FET", "RNDR", "OCEAN", "AI", "TAO", "ARKM"]
        if symbol_upper in ai_symbols:
            return Sector.AI
        
        # L1
        l1_symbols = ["ETH", "SOL", "AVAX", "ADA", "DOT", "ATOM", "NEAR", "APT", "SUI"]
        if symbol_upper in l1_symbols:
            return Sector.L1
        
        # L2
        l2_symbols = ["ARB", "OP", "MATIC", "IMX", "METIS"]
        if symbol_upper in l2_symbols:
            return Sector.L2
        
        # DeFi
        defi_symbols = ["UNI", "AAVE", "COMP", "MKR", "CRV", "SNX", "SUSHI"]
        if symbol_upper in defi_symbols:
            return Sector.DEFI
        
        # Meme
        meme_symbols = ["DOGE", "SHIB", "PEPE", "FLOKI", "BONK", "WIF"]
        if symbol_upper in meme_symbols:
            return Sector.MEME
        
        # Gaming
        gaming_symbols = ["AXS", "SAND", "MANA", "GALA", "ENJ"]
        if symbol_upper in gaming_symbols:
            return Sector.GAMING
        
        # Exchange
        exchange_symbols = ["BNB", "FTT", "HT", "OKB"]
        if symbol_upper in exchange_symbols:
            return Sector.EXCHANGE
        
        return Sector.OTHER
    
    def calculate_metrics(self):
        """Пересчитать метрики портфеля."""
        # Сбрасываем метрики
        self.sector_exposure = {}
        self.total_risk_r = 0.0
        self.long_exposure = 0.0
        self.short_exposure = 0.0
        
        # Считаем по позициям
        for pos in self.positions:
            # Экспозиция
            exposure = pos.size * pos.leverage
            if pos.side == "long":
                self.long_exposure += exposure
            else:
                self.short_exposure += exposure
            
            # Риск в R
            if pos.risk_r:
                self.total_risk_r += pos.risk_r
            
            # Секторная концентрация
            sector = pos.sector or self.get_sector_for_symbol(pos.symbol)
            if sector:
                if sector not in self.sector_exposure:
                    self.sector_exposure[sector] = 0.0
                self.sector_exposure[sector] += exposure
        
        # Чистая экспозиция
        self.net_exposure = self.long_exposure - self.short_exposure
        
        # Максимальная экспозиция к сектору (%)
        if self.total_equity > 0:
            for sector, exposure in self.sector_exposure.items():
                pct = (exposure / self.total_equity) * 100
                if pct > self.max_sector_exposure:
                    self.max_sector_exposure = pct
        else:
            self.max_sector_exposure = 0.0






