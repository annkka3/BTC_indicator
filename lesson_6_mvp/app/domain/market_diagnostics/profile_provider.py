# app/domain/market_diagnostics/profile_provider.py
"""
Провайдер профилей риска для Market Doctor.
"""

from typing import Optional
from .config import MarketDoctorConfig, DEFAULT_CONFIG, SAFE_CONFIG, AGGRESSIVE_CONFIG


class RiskProfile:
    """Профиль риска пользователя."""
    
    CONSERVATIVE = "conservative"  # 🛡 Консервативный
    BALANCED = "balanced"  # ⚖️ Сбалансированный
    AGGRESSIVE = "aggressive"  # 🔥 Агрессивный
    
    @staticmethod
    def get_config(profile: str) -> MarketDoctorConfig:
        """
        Получить конфигурацию Market Doctor для профиля риска.
        
        Args:
            profile: Профиль риска (conservative, balanced, aggressive)
        
        Returns:
            MarketDoctorConfig для профиля
        """
        if profile == RiskProfile.CONSERVATIVE:
            return SAFE_CONFIG
        elif profile == RiskProfile.AGGRESSIVE:
            return AGGRESSIVE_CONFIG
        else:
            return DEFAULT_CONFIG
    
    @staticmethod
    def get_default_strategy_mode(profile: str) -> str:
        """
        Получить режим стратегии по умолчанию для профиля.
        
        Args:
            profile: Профиль риска
        
        Returns:
            Режим стратегии (accumulation_play, trend_follow, mean_reversion, neutral)
        """
        if profile == RiskProfile.CONSERVATIVE:
            return "accumulation_play"
        elif profile == RiskProfile.AGGRESSIVE:
            return "trend_follow"
        else:
            return "auto"
    
    @staticmethod
    def get_position_size_factor(profile: str, pump_score: float, risk_score: float) -> float:
        """
        Получить коэффициент размера позиции для профиля.
        
        Args:
            profile: Профиль риска
            pump_score: Pump score (0-1)
            risk_score: Risk score (0-1)
        
        Returns:
            Коэффициент размера позиции (0.5-1.5)
        """
        base_factor = {
            RiskProfile.CONSERVATIVE: 0.5,
            RiskProfile.BALANCED: 1.0,
            RiskProfile.AGGRESSIVE: 1.5
        }.get(profile, 1.0)
        
        # Корректировка на основе pump_score и risk_score
        if pump_score > 0.8 and risk_score < 0.5:
            # Высокий потенциал, низкий риск - можно увеличить
            multiplier = 1.1
        elif risk_score > 0.7:
            # Высокий риск - уменьшаем
            multiplier = 0.8
        else:
            multiplier = 1.0
        
        return base_factor * multiplier


class ProfileProvider:
    """Провайдер профилей риска для пользователей."""
    
    def __init__(self, db):
        """
        Args:
            db: Экземпляр базы данных
        """
        self.db = db
        self._ensure_profile_column()
    
    def _ensure_profile_column(self):
        """Создать колонку для профиля риска в user_settings, если её нет."""
        cur = self.db.conn.cursor()
        cur.execute("PRAGMA table_info('user_settings')")
        cols = [r[1] for r in cur.fetchall()]
        
        if 'md_risk_profile' not in cols:
            cur.execute("ALTER TABLE user_settings ADD COLUMN md_risk_profile TEXT DEFAULT 'balanced'")
            self.db.conn.commit()
    
    def get_profile(self, user_id: int) -> str:
        """
        Получить профиль риска пользователя.
        
        Args:
            user_id: ID пользователя
        
        Returns:
            Профиль риска (conservative, balanced, aggressive)
        """
        self.db._ensure_user_row(user_id)
        cur = self.db.conn.cursor()
        cur.execute(
            "SELECT md_risk_profile FROM user_settings WHERE user_id=?",
            (user_id,)
        )
        row = cur.fetchone()
        if row and row[0]:
            return row[0]
        return RiskProfile.BALANCED  # По умолчанию сбалансированный
    
    def set_profile(self, user_id: int, profile: str):
        """
        Установить профиль риска пользователя.
        
        Args:
            user_id: ID пользователя
            profile: Профиль риска (conservative, balanced, aggressive)
        """
        if profile not in [RiskProfile.CONSERVATIVE, RiskProfile.BALANCED, RiskProfile.AGGRESSIVE]:
            raise ValueError(f"Invalid profile: {profile}")
        
        self.db._ensure_user_row(user_id)
        cur = self.db.conn.cursor()
        cur.execute(
            "UPDATE user_settings SET md_risk_profile=? WHERE user_id=?",
            (profile, user_id)
        )
        self.db.conn.commit()
    
    def get_config_for_user(self, user_id: int) -> MarketDoctorConfig:
        """
        Получить конфигурацию Market Doctor для пользователя.
        
        Args:
            user_id: ID пользователя
        
        Returns:
            MarketDoctorConfig для профиля пользователя
        """
        profile = self.get_profile(user_id)
        return RiskProfile.get_config(profile)
    
    def get_strategy_mode_for_user(self, user_id: int) -> str:
        """
        Получить режим стратегии по умолчанию для пользователя.
        
        Args:
            user_id: ID пользователя
        
        Returns:
            Режим стратегии
        """
        profile = self.get_profile(user_id)
        return RiskProfile.get_default_strategy_mode(profile)


