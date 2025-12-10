"""
Модуль для использования обученной CatBoost модели из ноутбука.
Адаптирован для работы с ботом.
"""
from __future__ import annotations
import pickle
import os
import numpy as np
import pandas as pd
from pathlib import Path
from typing import Optional, Dict, Tuple
import logging
from functools import lru_cache

logger = logging.getLogger("alt_forecast.ml.catboost")

try:
    import catboost as cb
    HAS_CATBOOST = True
except ImportError:
    HAS_CATBOOST = False
    logger.warning("CatBoost not installed")

# Путь к сохраненным моделям
# Используем локальный путь, если /app не доступен (для локального запуска)
if Path("/app").exists() and os.access("/app", os.W_OK):
    MODELS_DIR = Path("/app/data/models")
else:
    # Локальный путь для разработки
    MODELS_DIR = Path(__file__).parent.parent.parent / "data" / "models"
MODELS_DIR.mkdir(parents=True, exist_ok=True)

# Горизонты прогноза (в барах для 5-минутных данных)
# Для 1h: 12 баров = 1 час, для 4h: 48 баров = 4 часа, для 24h: 288 баров = 24 часа
HORIZON_MAP = {
    "1h": 12,   # 12 * 5min = 60min = 1h
    "4h": 48,   # 48 * 5min = 240min = 4h
    "24h": 288, # 288 * 5min = 1440min = 24h
    "1d": 288,  # alias для 24h (1 день = 24 часа)
}

# Обратный маппинг: из горизонта в таймфрейм
HORIZON_TO_TF = {
    12: "1h",
    48: "4h",
    288: "24h",
}


def build_ma(price: pd.Series, L: int = 48) -> pd.Series:
    """EMA строго до t (без утечек): adjust=False, min_periods=L"""
    return price.ewm(span=L, adjust=False, min_periods=L).mean()


def make_targets(price: pd.Series, ma: pd.Series, H: int) -> Tuple[pd.Series, pd.Series]:
    """y_H(t) = log P_{t+H} - log MA(t)"""
    y = np.log(price.shift(-H)) - np.log(ma)
    d = (y > 0).astype(int)
    return y, d


def build_extended_features(df_feat: pd.DataFrame) -> pd.DataFrame:
    """
    Добавить расширенные признаки (как в ноутбуке, ячейка 11).
    
    Включает:
    - Взаимодействия между важными признаками
    - Rolling статистики (mean, std, max, min)
    - Разности и относительные изменения
    - Полиномиальные признаки (квадраты и кубы)
    
    Args:
        df_feat: DataFrame с базовыми признаками
    
    Returns:
        DataFrame с расширенными признаками
    """
    df_feat_extended = df_feat.copy()
    available_features = df_feat_extended.columns.tolist()
    
    # === 1. ВЗАИМОДЕЙСТВИЯ МЕЖДУ ПРИЗНАКАМИ ===
    interactions_added = 0
    
    if 'z_to_ema' in available_features and 'macd' in available_features:
        df_feat_extended['z_macd_interaction'] = df_feat_extended['z_to_ema'] * df_feat_extended['macd']
        interactions_added += 1
    
    if 'macd' in available_features and 'atr_pct' in available_features:
        df_feat_extended['macd_atr_interaction'] = df_feat_extended['macd'] / (df_feat_extended['atr_pct'] + 1e-9)
        interactions_added += 1
    
    if 'rsi_14' in available_features and 'vol_20' in available_features:
        df_feat_extended['rsi_vol_interaction'] = df_feat_extended['rsi_14'] * df_feat_extended['vol_20']
        interactions_added += 1
    
    if 'z_to_ema' in available_features and 'atr_pct' in available_features:
        df_feat_extended['z_atr_interaction'] = df_feat_extended['z_to_ema'] * df_feat_extended['atr_pct']
        interactions_added += 1
    
    if 'adx_lookalike' in available_features and 'liq_regime' in available_features:
        df_feat_extended['adx_liq_interaction'] = df_feat_extended['adx_lookalike'] * df_feat_extended['liq_regime']
        interactions_added += 1
    
    if 'bb_width' in available_features and 'ret_4' in available_features:
        df_feat_extended['bb_ret_interaction'] = df_feat_extended['bb_width'] * df_feat_extended['ret_4']
        interactions_added += 1
    
    # === 2. ROLLING СТАТИСТИКИ ===
    rolling_added = 0
    
    if 'z_to_ema' in available_features:
        for window in [6, 12, 24]:
            df_feat_extended[f'z_to_ema_rolling_mean_{window}'] = df_feat_extended['z_to_ema'].rolling(window, min_periods=1).mean().shift(1).fillna(0.0)
            df_feat_extended[f'z_to_ema_rolling_std_{window}'] = df_feat_extended['z_to_ema'].rolling(window, min_periods=1).std().shift(1).fillna(0.0)
            df_feat_extended[f'z_to_ema_rolling_max_{window}'] = df_feat_extended['z_to_ema'].rolling(window, min_periods=1).max().shift(1).fillna(0.0)
            df_feat_extended[f'z_to_ema_rolling_min_{window}'] = df_feat_extended['z_to_ema'].rolling(window, min_periods=1).min().shift(1).fillna(0.0)
            rolling_added += 4
    
    if 'macd' in available_features:
        for window in [6, 12]:
            df_feat_extended[f'macd_rolling_mean_{window}'] = df_feat_extended['macd'].rolling(window, min_periods=1).mean().shift(1).fillna(0.0)
            df_feat_extended[f'macd_rolling_std_{window}'] = df_feat_extended['macd'].rolling(window, min_periods=1).std().shift(1).fillna(0.0)
            rolling_added += 2
    
    if 'atr_pct' in available_features:
        for window in [6, 12]:
            df_feat_extended[f'atr_rolling_mean_{window}'] = df_feat_extended['atr_pct'].rolling(window, min_periods=1).mean().shift(1).fillna(0.0)
            df_feat_extended[f'atr_rolling_ratio_{window}'] = df_feat_extended['atr_pct'] / (df_feat_extended[f'atr_rolling_mean_{window}'] + 1e-9)
            rolling_added += 2
    
    if 'ret_96' in available_features:
        for window in [6, 12]:
            df_feat_extended[f'ret_96_rolling_mean_{window}'] = df_feat_extended['ret_96'].rolling(window, min_periods=1).mean().shift(1).fillna(0.0)
            df_feat_extended[f'ret_96_rolling_std_{window}'] = df_feat_extended['ret_96'].rolling(window, min_periods=1).std().shift(1).fillna(0.0)
            rolling_added += 2
    
    # === 3. РАЗНОСТИ И ИЗМЕНЕНИЯ ===
    diff_added = 0
    
    if 'z_to_ema' in available_features:
        df_feat_extended['z_diff_1'] = df_feat_extended['z_to_ema'].diff(1).fillna(0.0)
        df_feat_extended['z_diff_3'] = df_feat_extended['z_to_ema'].diff(3).fillna(0.0)
        diff_added += 2
    
    if 'macd' in available_features:
        df_feat_extended['macd_diff_1'] = df_feat_extended['macd'].diff(1).fillna(0.0)
        df_feat_extended['macd_diff_3'] = df_feat_extended['macd'].diff(3).fillna(0.0)
        diff_added += 2
    
    if 'atr_pct' in available_features:
        df_feat_extended['atr_diff_1'] = df_feat_extended['atr_pct'].diff(1).fillna(0.0)
        df_feat_extended['atr_pct_change'] = df_feat_extended['atr_pct'].pct_change(1).fillna(0.0)
        diff_added += 2
    
    if 'ret_96' in available_features:
        df_feat_extended['ret_96_diff_1'] = df_feat_extended['ret_96'].diff(1).fillna(0.0)
        diff_added += 1
    
    if 'ret_4' in available_features:
        df_feat_extended['ret_4_diff_1'] = df_feat_extended['ret_4'].diff(1).fillna(0.0)
        diff_added += 1
    
    if 'macd' in available_features:
        df_feat_extended['macd_pct_change'] = df_feat_extended['macd'].pct_change(1).fillna(0.0)
        diff_added += 1
    
    # === 4. ПОЛИНОМИАЛЬНЫЕ ПРИЗНАКИ ===
    polynomial_added = 0
    important_features_poly = ['z_to_ema', 'macd', 'atr_pct', 'adx_lookalike', 'bb_width']
    
    for feat in important_features_poly:
        if feat in available_features:
            df_feat_extended[f'{feat}_squared'] = (df_feat_extended[feat] ** 2).fillna(0.0)
            df_feat_extended[f'{feat}_cubed'] = (df_feat_extended[feat] ** 3).fillna(0.0)
            polynomial_added += 2
    
    # Финальная очистка
    feature_cols_extended = [c for c in df_feat_extended.columns 
                            if c not in ['open', 'high', 'low', 'close', 'volume'] 
                            and pd.api.types.is_numeric_dtype(df_feat_extended[c])]
    
    df_feat_extended[feature_cols_extended] = df_feat_extended[feature_cols_extended].replace([np.inf, -np.inf], np.nan)
    df_feat_extended[feature_cols_extended] = df_feat_extended[feature_cols_extended].fillna(0.0)
    
    logger.info(f"Extended features added: interactions={interactions_added}, rolling={rolling_added}, diff={diff_added}, polynomial={polynomial_added}")
    
    return df_feat_extended


def build_features_from_notebook(df: pd.DataFrame) -> pd.DataFrame:
    """
    Строит features как в ноутбуке (упрощенная версия).
    
    Args:
        df: DataFrame с колонками ['ts', 'open', 'high', 'low', 'close', 'volume']
    
    Returns:
        DataFrame с features, индекс = ts
    """
    df_feat = df.copy()
    df_feat = df_feat.sort_values('ts').reset_index(drop=True)
    df_feat.set_index('ts', inplace=True)
    
    # === 1. БАЗОВЫЕ ПРИЗНАКИ ===
    # Returns
    df_feat['ret_1'] = df_feat['close'].pct_change(1).fillna(0.0)
    df_feat['ret_4'] = df_feat['close'].pct_change(4).fillna(0.0)
    df_feat['ret_16'] = df_feat['close'].pct_change(16).fillna(0.0)
    df_feat['ret_96'] = df_feat['close'].pct_change(96).fillna(0.0)
    
    # Волатильности (БЕЗ УТЕЧКИ: shift(1))
    df_feat['vol_20'] = df_feat['ret_1'].rolling(20, min_periods=1).std().shift(1).fillna(0.0)
    df_feat['vol_96'] = df_feat['ret_1'].rolling(96, min_periods=1).std().shift(1).fillna(0.0)
    
    # RSI (14) (БЕЗ УТЕЧКИ: shift(1))
    delta = df_feat['close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(14, min_periods=1).mean().shift(1)
    loss = (-delta.where(delta < 0, 0)).rolling(14, min_periods=1).mean().shift(1)
    rs = gain / (loss + 1e-9)
    df_feat['rsi_14'] = 100 - (100 / (1 + rs)).fillna(50.0)
    
    # MACD(12,26) и сигнал(9) (БЕЗ УТЕЧКИ: shift(1))
    ema12 = df_feat['close'].ewm(span=12, adjust=False).mean().shift(1)
    ema26 = df_feat['close'].ewm(span=26, adjust=False).mean().shift(1)
    df_feat['macd'] = (ema12 - ema26).fillna(0.0)
    df_feat['macd_sig'] = df_feat['macd'].ewm(span=9, adjust=False).mean().shift(1).fillna(0.0)
    
    # Bollinger Bands width (БЕЗ УТЕЧКИ: shift(1))
    ma20 = df_feat['close'].rolling(20).mean().shift(1)
    std20 = df_feat['close'].rolling(20).std().shift(1)
    df_feat['bb_width'] = (2 * std20 / (ma20 + 1e-9)).fillna(0.0)
    
    # ATR% (14) (БЕЗ УТЕЧКИ: shift(1))
    high_low = df_feat['high'] - df_feat['low']
    high_close = np.abs(df_feat['high'] - df_feat['close'].shift(1))
    low_close = np.abs(df_feat['low'] - df_feat['close'].shift(1))
    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    atr = tr.rolling(14).mean().shift(1)
    df_feat['atr_pct'] = (atr / (df_feat['close'] + 1e-9)).fillna(0.0)
    
    # Z-score отклонения к EMA48 (БЕЗ УТЕЧКИ: shift(1))
    ema48 = df_feat['close'].ewm(span=48, adjust=False).mean().shift(1)
    residual = df_feat['close'] - ema48
    residual_std = residual.rolling(48, min_periods=1).std().shift(1)
    df_feat['z_to_ema'] = (residual / (residual_std + 1e-9)).fillna(0.0)
    
    # === 2. СВЕЧНОЙ ПРОФИЛЬ ===
    high_low_range = df_feat['high'] - df_feat['low']
    body = np.abs(df_feat['close'] - df_feat['open'])
    df_feat['body_to_range'] = np.where(high_low_range > 0, body / high_low_range, 0.0)
    
    upper_wick = df_feat['high'] - np.maximum(df_feat['open'], df_feat['close'])
    df_feat['upper_wick'] = np.where(high_low_range > 0, upper_wick / high_low_range, 0.0)
    
    lower_wick = np.minimum(df_feat['open'], df_feat['close']) - df_feat['low']
    df_feat['lower_wick'] = np.where(high_low_range > 0, lower_wick / high_low_range, 0.0)
    
    # === 3. КАЛЕНДАРНЫЕ/ЦИКЛИЧЕСКИЕ ===
    df_feat['hour'] = df_feat.index.hour
    df_feat['dow'] = df_feat.index.dayofweek
    df_feat['dom'] = df_feat.index.day
    df_feat['month'] = df_feat.index.month
    
    df_feat['sin_hour'] = np.sin(2 * np.pi * df_feat['hour'] / 24)
    df_feat['cos_hour'] = np.cos(2 * np.pi * df_feat['hour'] / 24)
    df_feat['sin_dow'] = np.sin(2 * np.pi * df_feat['dow'] / 7)
    df_feat['cos_dow'] = np.cos(2 * np.pi * df_feat['dow'] / 7)
    
    df_feat['sess_asia'] = ((df_feat['hour'] >= 0) & (df_feat['hour'] < 8)).astype(int)
    df_feat['sess_europe'] = ((df_feat['hour'] >= 7) & (df_feat['hour'] < 15)).astype(int)
    df_feat['sess_us'] = ((df_feat['hour'] >= 13) & (df_feat['hour'] < 21)).astype(int)
    
    # === 4. РЕЖИМЫ РЫНКА ===
    df_feat['trend_slope'] = ema48.diff().fillna(0.0)
    
    ema_short = df_feat['close'].ewm(span=8, adjust=False).mean().shift(1)
    ema_long = df_feat['close'].ewm(span=21, adjust=False).mean().shift(1)
    df_feat['adx_lookalike'] = (np.abs(ema_short - ema_long) / (atr + 1e-9)).fillna(0.0)
    
    # Волатильностный режим
    vol_96_clean = df_feat['vol_96'].fillna(df_feat['vol_96'].median() if df_feat['vol_96'].notna().any() else 0.0)
    if vol_96_clean.notna().any() and vol_96_clean.std() > 0:
        vol_96_quantiles = vol_96_clean.quantile([0.2, 0.8])
        df_feat['vol_regime'] = pd.cut(
            vol_96_clean,
            bins=[-np.inf, vol_96_quantiles[0.2], vol_96_quantiles[0.8], np.inf],
            labels=[0, 1, 2]
        ).astype(float).fillna(1.0)
    else:
        df_feat['vol_regime'] = 1.0
    
    # Ликвидность (прокси)
    vol_mean_96 = df_feat['volume'].rolling(96, min_periods=1).mean().shift(1)
    vol_mean_288 = df_feat['volume'].rolling(288, min_periods=1).mean().shift(1)
    liq_ratio = vol_mean_96 / (vol_mean_288 + 1e-9)
    liq_ratio_clean = liq_ratio.fillna(1.0)
    if liq_ratio_clean.notna().any() and liq_ratio_clean.std() > 0:
        liq_quantiles = liq_ratio_clean.quantile([0.2, 0.8])
        df_feat['liq_regime'] = pd.cut(
            liq_ratio_clean,
            bins=[-np.inf, liq_quantiles[0.2], liq_quantiles[0.8], np.inf],
            labels=[0, 1, 2]
        ).astype(float).fillna(1.0)
    else:
        df_feat['liq_regime'] = 1.0
    
    # Импульс
    df_feat['impulse'] = df_feat['ret_1'] / (df_feat['vol_20'] + 1e-9)
    
    def rank_pct_rolling(x):
        """Безопасный расчет rank percentile"""
        if len(x) == 0:
            return 0.5
        x_series = pd.Series(x)
        ranks = x_series.rank(pct=True)
        return ranks.iloc[-1] if len(ranks) > 0 else 0.5
    
    df_feat['impulse_p'] = df_feat['impulse'].rolling(288, min_periods=1).apply(rank_pct_rolling, raw=True).shift(1).fillna(0.5)
    
    # === 5. ЛАГИ ВАЖНЫХ ПРИЗНАКОВ ===
    for lag in [1, 2, 3, 6, 9, 12]:
        df_feat[f'z_to_ema_lag{lag}'] = df_feat['z_to_ema'].shift(lag).fillna(0.0)
    
    for lag in [1, 2, 3, 4, 5, 6]:
        df_feat[f'rsi_14_lag{lag}'] = df_feat['rsi_14'].shift(lag).fillna(50.0)
        df_feat[f'macd_lag{lag}'] = df_feat['macd'].shift(lag).fillna(0.0)
    
    for lag in [1, 2, 3, 6]:
        df_feat[f'vol_20_lag{lag}'] = df_feat['vol_20'].shift(lag).fillna(0.0)
    
    for lag in [1, 2, 3, 4]:
        df_feat[f'ret_1_lag{lag}'] = df_feat['ret_1'].shift(lag).fillna(0.0)
    
    # === 6. МАКРО-ФИЧИ (опционально) ===
    try:
        from .macro_features import add_macro_features
        df_feat = add_macro_features(df_feat, macro_df=None)
        logger.debug("Macro features added")
    except Exception as e:
        logger.warning(f"Failed to add macro features: {e}")
    
    # === 7. MOMENTUM INTELLIGENCE ФИЧИ (опционально) ===
    try:
        from .momentum_features import add_momentum_features
        # Строим indicators dict из df_feat для momentum
        indicators = {}
        if "rsi_14" in df_feat.columns:
            indicators["rsi"] = df_feat["rsi_14"]
        if "macd" in df_feat.columns:
            indicators["macd"] = df_feat["macd"]
            if "macd_sig" in df_feat.columns:
                indicators["macd_signal"] = df_feat["macd_sig"]
                indicators["macd_hist"] = df_feat["macd"] - df_feat["macd_sig"]
        
        df_feat = add_momentum_features(df_feat, indicators=indicators if indicators else None)
        logger.debug("Momentum features added")
    except Exception as e:
        logger.warning(f"Failed to add momentum features: {e}")
    
    # === ФИНАЛЬНАЯ ОЧИСТКА ===
    feature_cols = [c for c in df_feat.columns 
                    if c not in ['open', 'high', 'low', 'close', 'volume'] 
                    and pd.api.types.is_numeric_dtype(df_feat[c])]
    
    df_feat[feature_cols] = df_feat[feature_cols].replace([np.inf, -np.inf], np.nan)
    df_feat[feature_cols] = df_feat[feature_cols].fillna(0.0)
    
    return df_feat


def load_catboost_model(symbol: str, tf: str, horizon: int, use_extended: bool = False) -> Optional[Dict]:
    """
    Загрузить обученную CatBoost модель.
    
    Args:
        symbol: Символ (например, "BTC")
        tf: Таймфрейм (1h, 4h, 24h)
        horizon: Горизонт прогноза в барах
        use_extended: Использовать CatBoost_Extended (для H=48 согласно отчету)
    
    Returns:
        Dict с моделью и метаданными или None
    """
    # Определяем имя модели
    model_name = "catboost_extended" if use_extended else "catboost"
    model_path = MODELS_DIR / f"{symbol.upper()}_{model_name}_{tf}_h{horizon}.pkl"
    
    if not model_path.exists():
        return None
    
    try:
        with open(model_path, "rb") as f:
            model_data = pickle.load(f)
        return model_data
    except Exception as e:
        logger.error(f"Failed to load CatBoost model from {model_path}: {e}")
        return None


def save_catboost_model(symbol: str, tf: str, horizon: int, model_reg, model_cls, feature_names: list, metadata: dict, model_name: str = "catboost"):
    """
    Сохранить обученную CatBoost модель.
    
    Args:
        symbol: Символ
        tf: Таймфрейм
        horizon: Горизонт прогноза
        model_reg: CatBoost регрессор
        model_cls: CatBoost классификатор
        feature_names: Список имен признаков
        metadata: Метаданные модели
        model_name: Имя модели ("catboost" или "catboost_extended")
    """
    model_path = MODELS_DIR / f"{symbol.upper()}_{model_name}_{tf}_h{horizon}.pkl"
    
    model_data = {
        "reg": model_reg,
        "cls": model_cls,
        "feature_names": feature_names,
        "meta": metadata,
    }
    
    try:
        with open(model_path, "wb") as f:
            pickle.dump(model_data, f)
        logger.info(f"CatBoost model saved to {model_path}")
    except Exception as e:
        logger.error(f"Failed to save CatBoost model to {model_path}: {e}")
        raise


def train_catboost_model(
    df: pd.DataFrame,
    symbol: str = "BTC",
    tf: str = "1h",
    horizon: int = 12,
    use_selected_features: bool = True,
    use_extended: bool = False
) -> Optional[Dict]:
    """
    Обучить CatBoost модель на данных.
    
    Args:
        df: DataFrame с OHLCV данными
        symbol: Символ
        tf: Таймфрейм
        horizon: Горизонт прогноза в барах
        use_selected_features: Использовать отобранные признаки из ноутбука
        use_extended: Использовать расширенные признаки (CatBoost_Extended)
    
    Returns:
        Dict с моделью и метаданными или None
    """
    if not HAS_CATBOOST:
        logger.error("CatBoost not installed")
        return None
    
    try:
        # Строим базовые features
        df_feat = build_features_from_notebook(df)
        
        # Если use_extended=True, добавляем расширенные признаки
        if use_extended:
            df_feat = build_extended_features(df_feat)
            logger.info(f"Using extended features for CatBoost_Extended")
        
        # Строим targets
        price = df_feat['close'].copy()
        ma = build_ma(price, L=48)
        y_reg, y_cls = make_targets(price, ma, horizon)
        
        # Выбираем features
        feature_cols = [c for c in df_feat.columns 
                       if c not in ['open', 'high', 'low', 'close', 'volume'] 
                       and pd.api.types.is_numeric_dtype(df_feat[c])]
        
        # Используем отобранные признаки если доступны
        if use_selected_features:
            try:
                selected_path = Path("lesson_04_simple_model/results/selected_features-2.csv")
                if selected_path.exists():
                    selected_df = pd.read_csv(selected_path)
                    selected_features = selected_df['feature'].tolist()
                    # Оставляем только те признаки, которые есть в df_feat
                    feature_cols = [f for f in feature_cols if f in selected_features]
                    logger.info(f"Using {len(feature_cols)} selected features")
            except Exception as e:
                logger.warning(f"Failed to load selected features: {e}")
        
        # Подготавливаем данные
        X = df_feat[feature_cols].copy()
        valid = ~(y_reg.isna() | y_cls.isna())
        valid.iloc[-horizon:] = False  # Убираем последние H баров
        
        X_data = X[valid].values
        y_reg_data = y_reg[valid].values
        y_cls_data = y_cls[valid].values
        
        if len(X_data) < 100:
            logger.warning(f"Not enough data for training: {len(X_data)} samples")
            return None
        
        # Вычисляем статистику таргета для метаданных
        y_reg_valid = y_reg[valid]
        target_stats = {
            "mean": float(y_reg_valid.mean()),
            "std": float(y_reg_valid.std()),
            "min": float(y_reg_valid.min()),
            "max": float(y_reg_valid.max()),
            "percentiles": {
                "p5": float(y_reg_valid.quantile(0.05)),
                "p25": float(y_reg_valid.quantile(0.25)),
                "p50": float(y_reg_valid.quantile(0.50)),
                "p75": float(y_reg_valid.quantile(0.75)),
                "p95": float(y_reg_valid.quantile(0.95)),
            }
        }
        
        # Обучаем CatBoost регрессор
        cat_reg = cb.CatBoostRegressor(
            iterations=300,
            depth=6,
            learning_rate=0.05,
            loss_function='MAE',
            verbose=False,
            random_state=42
        )
        cat_reg.fit(X_data, y_reg_data)
        
        # Обучаем CatBoost классификатор
        cat_cls = cb.CatBoostClassifier(
            iterations=300,
            depth=6,
            learning_rate=0.05,
            verbose=False,
            random_state=42
        )
        cat_cls.fit(X_data, y_cls_data)
        
        # Метаданные
        model_type = "CatBoost_Extended" if use_extended else "CatBoost"
        metadata = {
            "symbol": symbol.upper(),
            "tf": tf,
            "horizon": horizon,
            "features": feature_cols,
            "n_samples": len(X_data),
            "model_type": model_type,
            "version": "1.0",
            "target_name": "log_residual_ma48",  # Определение таргета
            "target_stats": target_stats,  # Статистика таргета
        }
        
        # Сохраняем модель с правильным именем
        model_name = "catboost_extended" if use_extended else "catboost"
        save_catboost_model(symbol, tf, horizon, cat_reg, cat_cls, feature_cols, metadata, model_name=model_name)
        
        return {
            "reg": cat_reg,
            "cls": cat_cls,
            "feature_names": feature_cols,
            "meta": metadata,
        }
    except Exception as e:
        logger.exception(f"Failed to train CatBoost model: {e}")
        return None


def forecast_with_catboost(
    df: pd.DataFrame,
    symbol: str = "BTC",
    tf: str = "1h",
    horizon: int = 12,
    cached_model_data: Optional[Dict] = None
) -> Optional[Dict]:
    """
    Сделать прогноз с использованием CatBoost модели.
    
    Выбирает правильную модель согласно отчету:
    - H=12: CatBoost (базовая)
    - H=48: CatBoost_Extended
    - H=288: CatBoost (базовая)
    
    Args:
        df: DataFrame с OHLCV данными
        symbol: Символ
        tf: Таймфрейм
        horizon: Горизонт прогноза в барах
    
    Returns:
        Dict с прогнозом или None
    """
    if not HAS_CATBOOST:
        logger.error("CatBoost not installed")
        return None
    
    try:
        # Определяем, какую модель использовать согласно отчету
        # H=48 использует CatBoost_Extended (лучший результат: 9.68% vs 9.62%)
        use_extended = (horizon == 48)
        
        # Используем кэшированную модель, если предоставлена, иначе загружаем
        if cached_model_data is not None:
            model_data = cached_model_data
        else:
            model_data = load_catboost_model(symbol, tf, horizon, use_extended=use_extended)
        
        # Если модели нет, обучаем её
        if model_data is None:
            model_type = "CatBoost_Extended" if use_extended else "CatBoost"
            logger.info(f"Model not found, training new {model_type} model for {symbol} {tf} H={horizon}")
            model_data = train_catboost_model(df, symbol, tf, horizon, use_extended=use_extended)
            if model_data is None:
                return None
        
        # Строим features (базовые или расширенные в зависимости от модели)
        if use_extended:
            df_feat = build_features_from_notebook(df)
            df_feat = build_extended_features(df_feat)
        else:
            df_feat = build_features_from_notebook(df)
        
        # Получаем последнюю строку features
        feature_cols = model_data["feature_names"]
        X_last = df_feat[feature_cols].iloc[-1].values.reshape(1, -1)
        
        # Делаем прогноз
        y_pred = model_data["reg"].predict(X_last)[0]
        p_up = model_data["cls"].predict_proba(X_last)[0, 1]
        
        # Преобразуем residual обратно в return
        # residual = log(P_{t+H}) - log(MA(t))
        # Для прогноза: return ≈ residual (приближенно)
        # Но лучше использовать текущую цену и MA для более точного прогноза
        current_price = df_feat['close'].iloc[-1]
        ma_current = build_ma(df_feat['close'], L=48).iloc[-1]
        
        # residual предсказывает отклонение от MA
        # return = exp(log(MA) + residual) / MA - 1 ≈ residual (для малых значений)
        predicted_return = y_pred  # Используем residual как приближение return
        
        # Вычисляем доверительные интервалы на основе статистики таргета
        # Используем стандартное отклонение остатков как меру неопределенности
        target_stats = model_data["meta"].get("target_stats", {})
        target_std = target_stats.get("std", 0.0)
        
        # Если std не задан, используем историческую волатильность как fallback
        if target_std <= 0:
            # Используем волатильность последних 96 баров как приближение
            if len(df_feat) >= 96:
                recent_returns = df_feat['ret_1'].iloc[-96:].dropna()
                if len(recent_returns) > 0:
                    target_std = float(recent_returns.std())
        
        # CI 68%: ±1 std, CI 95%: ±2 std
        # Для остатков (residual) это приблизительно соответствует CI для return
        ci68_lower = predicted_return - target_std
        ci68_upper = predicted_return + target_std
        ci95_lower = predicted_return - 2 * target_std
        ci95_upper = predicted_return + 2 * target_std
        
        result = {
            "ret_pred": float(predicted_return),
            "p_up": float(p_up),
            "residual": float(y_pred),
            "confidence_interval_68": (float(ci68_lower), float(ci68_upper)),
            "confidence_interval_95": (float(ci95_lower), float(ci95_upper)),
            "meta": model_data["meta"],
        }
        
        # Если модель была загружена (не из кэша), возвращаем её для кэширования
        if cached_model_data is None:
            result["model_data"] = model_data
        
        return result
    except Exception as e:
        logger.exception(f"Failed to forecast with CatBoost: {e}")
        return None

