from __future__ import annotations
import pandas as pd
import numpy as np
from pathlib import Path

# Путь к отобранным признакам (если доступен)
# Пробуем несколько возможных путей
def _get_selected_features_path():
    base_path = Path(__file__).parent.parent.parent
    possible_paths = [
        base_path / "lesson_05_model_improvement" / "selected_features (1).csv",
        base_path / "lesson_05_model_improvement" / "selected_features.csv",
    ]
    for path in possible_paths:
        if path.exists():
            return path
    return None

def advanced_preprocessing(df: pd.DataFrame) -> pd.DataFrame:
    """
    Расширенная предобработка данных:
    - Обработка пропусков
    - Обработка выбросов
    - Проверка логической целостности
    """
    df_clean = df.copy()
    df_clean = df_clean.sort_values('ts').reset_index(drop=True)
    df_clean.set_index('ts', inplace=True)
    
    # 1. Обработка пропусков - forward fill для OHLCV
    ohlcv_cols = ['open', 'high', 'low', 'close', 'volume']
    for col in ohlcv_cols:
        if col in df_clean.columns:
            df_clean[col] = df_clean[col].fillna(method='ffill').fillna(method='bfill')
    
    # 2. Обработка выбросов (IQR метод для цен) - мягкое ограничение
    for col in ['open', 'high', 'low', 'close']:
        if col in df_clean.columns:
            Q1 = df_clean[col].quantile(0.01)
            Q3 = df_clean[col].quantile(0.99)
            IQR = Q3 - Q1
            lower_bound = Q1 - 3 * IQR
            upper_bound = Q3 + 3 * IQR
            df_clean[col] = df_clean[col].clip(lower=lower_bound, upper=upper_bound)
    
    # 3. Проверка логической целостности
    if all(col in df_clean.columns for col in ['high', 'low', 'close', 'open']):
        df_clean['high'] = df_clean[['high', 'open', 'close']].max(axis=1)
        df_clean['low'] = df_clean[['low', 'open', 'close']].min(axis=1)
    
    # 4. Обработка нулевых/отрицательных объемов
    if 'volume' in df_clean.columns:
        df_clean['volume'] = df_clean['volume'].replace(0, np.nan)
        df_clean['volume'] = df_clean['volume'].fillna(method='ffill').fillna(method='bfill')
        df_clean['volume'] = df_clean['volume'].clip(lower=0.1)
    
    return df_clean

def build_features(df: pd.DataFrame, use_selected_features: bool = True) -> pd.DataFrame:
    """
    Расширенный Feature Engineering на основе улучшений из lesson_05:
    - Базовые технические индикаторы
    - Взаимодействия признаков
    - Полиномиальные признаки
    - Rolling статистики
    - Лаги важных признаков
    - Календарные признаки
    
    df: columns = ['ts','open','high','low','close','volume'] (ts in UTC)
    returns df with engineered features. index = ts
    """
    # Предобработка данных
    df_feat = advanced_preprocessing(df)
    
    # === 1. БАЗОВЫЕ ТЕХНИЧЕСКИЕ ПРИЗНАКИ ===
    
    # Returns
    df_feat['ret_1'] = df_feat['close'].pct_change(1).fillna(0.0)
    df_feat['ret_4'] = df_feat['close'].pct_change(4).fillna(0.0)
    df_feat['ret_16'] = df_feat['close'].pct_change(16).fillna(0.0)
    df_feat['ret_96'] = df_feat['close'].pct_change(96).fillna(0.0)
    
    # Волатильности (БЕЗ УТЕЧКИ: shift(1))
    df_feat['vol_20'] = df_feat['ret_1'].rolling(20, min_periods=1).std().shift(1).fillna(0.0)
    df_feat['vol_96'] = df_feat['ret_1'].rolling(96, min_periods=1).std().shift(1).fillna(0.0)
    
    # RSI(14)
    delta = df_feat['close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(14, min_periods=1).mean().shift(1)
    loss = (-delta.where(delta < 0, 0)).rolling(14, min_periods=1).mean().shift(1)
    rs = gain / (loss + 1e-9)
    df_feat['rsi_14'] = 100 - (100 / (1 + rs)).fillna(50.0)
    
    # MACD(12,26) и сигнал(9)
    ema12 = df_feat['close'].ewm(span=12, adjust=False).mean().shift(1)
    ema26 = df_feat['close'].ewm(span=26, adjust=False).mean().shift(1)
    df_feat['macd'] = (ema12 - ema26).fillna(0.0)
    df_feat['macd_sig'] = df_feat['macd'].ewm(span=9, adjust=False).mean().shift(1).fillna(0.0)
    df_feat['macd_hist'] = df_feat['macd'] - df_feat['macd_sig']
    
    # Bollinger Bands
    ma20 = df_feat['close'].rolling(20).mean().shift(1)
    std20 = df_feat['close'].rolling(20).std().shift(1)
    df_feat['bb_width'] = (2 * std20 / (ma20 + 1e-9)).fillna(0.0)
    df_feat['bb_position'] = ((df_feat['close'] - ma20) / (2 * std20 + 1e-9)).fillna(0.0)
    
    # ATR%
    high_low = df_feat['high'] - df_feat['low']
    high_close = np.abs(df_feat['high'] - df_feat['close'].shift(1))
    low_close = np.abs(df_feat['low'] - df_feat['close'].shift(1))
    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    atr = tr.rolling(14).mean().shift(1)
    df_feat['atr_pct'] = (atr / (df_feat['close'] + 1e-9)).fillna(0.0)
    
    # Z-score к EMA48
    ema48 = df_feat['close'].ewm(span=48, adjust=False).mean().shift(1)
    residual = df_feat['close'] - ema48
    residual_std = residual.rolling(48, min_periods=1).std().shift(1)
    df_feat['z_to_ema'] = (residual / (residual_std + 1e-9)).fillna(0.0)
    
    # Объемные признаки
    df_feat['vol_rel_24'] = df_feat['volume'] / (df_feat['volume'].rolling(24, min_periods=1).mean().shift(1) + 1e-9)
    df_feat['vol_rel_96'] = df_feat['volume'] / (df_feat['volume'].rolling(96, min_periods=1).mean().shift(1) + 1e-9)
    
    # === 2. ВЗАИМОДЕЙСТВИЯ ПРИЗНАКОВ ===
    df_feat['z_macd_interaction'] = df_feat['z_to_ema'] * df_feat['macd']
    df_feat['rsi_vol_interaction'] = df_feat['rsi_14'] * df_feat['vol_20']
    df_feat['macd_atr_interaction'] = df_feat['macd'] / (df_feat['atr_pct'] + 1e-9)
    df_feat['z_atr_interaction'] = df_feat['z_to_ema'] * df_feat['atr_pct']
    df_feat['bb_ret_interaction'] = df_feat['bb_width'] * df_feat['ret_4']
    
    # === 3. ПОЛИНОМИАЛЬНЫЕ ПРИЗНАКИ ===
    important_features = ['z_to_ema', 'macd', 'atr_pct', 'rsi_14', 'bb_width']
    for feat in important_features:
        if feat in df_feat.columns:
            df_feat[f'{feat}_squared'] = (df_feat[feat] ** 2).fillna(0.0)
            df_feat[f'{feat}_cubed'] = (df_feat[feat] ** 3).fillna(0.0)
    
    # === 4. ROLLING СТАТИСТИКИ ===
    for window in [6, 12, 24]:
        if 'z_to_ema' in df_feat.columns:
            df_feat[f'z_to_ema_rolling_mean_{window}'] = df_feat['z_to_ema'].rolling(window, min_periods=1).mean().shift(1).fillna(0.0)
            df_feat[f'z_to_ema_rolling_std_{window}'] = df_feat['z_to_ema'].rolling(window, min_periods=1).std().shift(1).fillna(0.0)
        if 'macd' in df_feat.columns:
            df_feat[f'macd_rolling_mean_{window}'] = df_feat['macd'].rolling(window, min_periods=1).mean().shift(1).fillna(0.0)
    
    # === 5. ЛАГИ ВАЖНЫХ ПРИЗНАКОВ ===
    for lag in [1, 2, 3, 6, 12]:
        if 'z_to_ema' in df_feat.columns:
            df_feat[f'z_to_ema_lag{lag}'] = df_feat['z_to_ema'].shift(lag).fillna(0.0)
        if 'rsi_14' in df_feat.columns:
            df_feat[f'rsi_14_lag{lag}'] = df_feat['rsi_14'].shift(lag).fillna(50.0)
        if 'macd' in df_feat.columns:
            df_feat[f'macd_lag{lag}'] = df_feat['macd'].shift(lag).fillna(0.0)
    
    # === 6. КАЛЕНДАРНЫЕ ПРИЗНАКИ ===
    if df_feat.index.tz is None:
        # Если нет timezone, предполагаем UTC
        df_feat.index = pd.to_datetime(df_feat.index).tz_localize('UTC')
    
    df_feat['hour'] = df_feat.index.hour
    df_feat['dow'] = df_feat.index.dayofweek
    df_feat['sin_dow'] = np.sin(2 * np.pi * df_feat['dow'] / 7)
    df_feat['cos_dow'] = np.cos(2 * np.pi * df_feat['dow'] / 7)
    
    # === 7. РЕЖИМЫ РЫНКА ===
    # ADX lookalike
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
    
    # Импульс
    df_feat['impulse'] = df_feat['ret_1'] / (df_feat['vol_20'] + 1e-9)
    
    # Финальная очистка
    feature_cols = [c for c in df_feat.columns 
                    if c not in ['open', 'high', 'low', 'close', 'volume', 'hour', 'dow'] 
                    and pd.api.types.is_numeric_dtype(df_feat[c])]
    
    df_feat[feature_cols] = df_feat[feature_cols].replace([np.inf, -np.inf], np.nan)
    df_feat[feature_cols] = df_feat[feature_cols].fillna(0.0)
    
    # Feature Selection: используем отобранные признаки если доступны
    if use_selected_features:
        selected_features_path = _get_selected_features_path()
        if selected_features_path and selected_features_path.exists():
            try:
                selected_df = pd.read_csv(selected_features_path)
                selected_features = selected_df['feature'].tolist()
                # Оставляем только те признаки, которые есть в данных
                available_selected = [f for f in selected_features if f in df_feat.columns]
                if available_selected:
                    # Добавляем базовые колонки обратно для таргета
                    keep_cols = ['open', 'high', 'low', 'close', 'volume'] + available_selected
                    keep_cols = [c for c in keep_cols if c in df_feat.columns]
                    df_feat = df_feat[keep_cols]
    except Exception:
                # Если не удалось загрузить, используем все признаки
                pass
    
    return df_feat
