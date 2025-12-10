from __future__ import annotations
import os, pickle
from pathlib import Path
import numpy as np
import pandas as pd

try:
    import catboost as cb
    _HAS_CATBOOST = True
except Exception:
    _HAS_CATBOOST = False

try:
    import lightgbm as lgb
    _HAS_LGBM = True
except Exception:
    _HAS_LGBM = False

from sklearn.ensemble import RandomForestRegressor, RandomForestClassifier
from sklearn.metrics import mean_absolute_error, roc_auc_score

MODELS_DIR = Path("/app/data/models")
MODELS_DIR.mkdir(parents=True, exist_ok=True)

def _make_regressor():
    """Создает регрессор с оптимизированными параметрами из lesson_05"""
    if _HAS_CATBOOST:
        # Параметры из оптимизации Optuna (примерные, можно настроить)
        return cb.CatBoostRegressor(
            iterations=500,
            depth=6,
            learning_rate=0.05,
            l2_leaf_reg=3,
            random_strength=1.0,
            bagging_temperature=0.5,
            random_state=42,
            verbose=False,
            loss_function='MAE'
        )
    elif _HAS_LGBM:
        return lgb.LGBMRegressor(
            n_estimators=600, learning_rate=0.03, max_depth=-1,
            subsample=0.9, colsample_bytree=0.9, random_state=42
        )
    return RandomForestRegressor(n_estimators=400, random_state=42, n_jobs=-1)

def _make_classifier():
    """Создает классификатор с оптимизированными параметрами из lesson_05"""
    if _HAS_CATBOOST:
        # Параметры из оптимизации Optuna (примерные, можно настроить)
        return cb.CatBoostClassifier(
            iterations=500,
            depth=6,
            learning_rate=0.05,
            l2_leaf_reg=3,
            random_strength=1.0,
            bagging_temperature=0.5,
            random_state=42,
            verbose=False,
            loss_function='Logloss'
        )
    elif _HAS_LGBM:
        return lgb.LGBMClassifier(
            n_estimators=600, learning_rate=0.03, max_depth=-1,
            subsample=0.9, colsample_bytree=0.9, random_state=42
        )
    return RandomForestClassifier(n_estimators=500, random_state=42, n_jobs=-1)

def _walk_forward_splits(n: int, train_size: int, step: int):
    i = train_size
    while i + step <= n:
        yield slice(0, i), slice(i, i+step)
        i += step

def prepare_targets(df_feat: pd.DataFrame, horizon: int):
    """
    Подготовка таргетов для регрессии и классификации
    Использует log-отклонение от EMA-тренда (как в lesson_05)
    
    Args:
        df_feat: DataFrame с признаками
        horizon: Горизонт прогноза в барах
    
    Returns:
        y_reg: Таргет для регрессии (log residual)
        y_cls: Таргет для классификации (направление)
    """
    price = df_feat['close'].copy()
    # EMA с периодом 48 (для 5m это ~4 часа)
    ma = price.ewm(span=48, adjust=False, min_periods=48).mean()
    
    # y_H(t) = log(P_{t+H}) - log(MA(t))
    y_reg = np.log(price.shift(-horizon)) - np.log(ma)
    y_cls = (y_reg > 0).astype(int)
    
    return y_reg, y_cls

def train_models(symbol: str, tf: str, df_feat: pd.DataFrame, horizon: int = 24):
    """
    Обучение моделей с улучшенным таргетом и архитектурой из lesson_05
    
    df_feat: выход build_features(); индекс = ts
    horizon: сколько баров вперёд предсказываем (для 5m → 48 = 4 часа)
    """
    X = df_feat.copy()
    
    # Используем новый таргет: log-отклонение от EMA-тренда
    y_reg, y_cls = prepare_targets(X, horizon)
    
    # Удаляем базовые колонки из признаков
    X = X.drop(columns=['open','high','low','close','volume'], errors='ignore')
    
    # Фильтруем валидные данные
    valid = ~(y_reg.isna() | y_cls.isna())
    valid.iloc[-horizon:] = False  # Удаляем последние horizon строк
    
    data = X[valid].values
    y_r = y_reg[valid].values
    y_c = y_cls[valid].values
    
    if len(data) == 0:
        raise ValueError(f"No valid data for training. horizon={horizon}, valid samples={valid.sum()}")
    
    # walk-forward оценка
    train_size = max(500, int(0.7 * len(data)))
    step = max(50, int(0.1 * len(data)))
    mae_list, auc_list = [], []

    for tr, te in _walk_forward_splits(len(data), train_size, step):
        reg = _make_regressor()
        cls = _make_classifier()
        
        try:
            reg.fit(data[tr], y_r[tr])
            cls.fit(data[tr], y_c[tr])
            pred = reg.predict(data[te])
            proba = getattr(cls, "predict_proba")(data[te])[:,1]
            mae_list.append(mean_absolute_error(y_r[te], pred))
            try:
                auc_list.append(roc_auc_score(y_c[te], proba))
            except ValueError:
                pass
        except Exception as e:
            # Пропускаем проблемные фолды
            continue

    # Финальные модели на всём массиве
    reg_f = _make_regressor()
    cls_f = _make_classifier()
    reg_f.fit(data, y_r)
    cls_f.fit(data, y_c)

    meta = {
        "symbol": symbol.upper(),
        "tf": tf,
        "horizon": horizon,
        "features": list(X.columns),
        "MAE_walk": float(np.nanmedian(mae_list) if mae_list else np.nan),
        "AUC_walk": float(np.nanmedian(auc_list) if auc_list else np.nan),
        "n_samples": int(len(data)),
        "target_type": "log_residual_from_ema",  # Новый тип таргета
        "model_type": "CatBoost" if _HAS_CATBOOST else ("LightGBM" if _HAS_LGBM else "RandomForest"),
    }

    # Сохраняем
    obj = {"reg": reg_f, "cls": cls_f, "meta": meta}
    path = MODELS_DIR / f"{symbol.upper()}_{tf}_h{horizon}.pkl"
    with open(path, "wb") as f:
        pickle.dump(obj, f)
    return path, meta

def load_model(symbol: str, tf: str, horizon: int = 24):
    path = MODELS_DIR / f"{symbol.upper()}_{tf}_h{horizon}.pkl"
    if not path.exists():
        return None
    with open(path, "rb") as f:
        return pickle.load(f)

def infer(model_obj, x_row: np.ndarray):
    """
    Предсказание модели
    
    Returns:
        y_hat: log-отклонение от EMA-тренда (для конвертации в доходность нужно exp(y_hat) - 1)
        p_up: вероятность роста
    """
    reg = model_obj["reg"]
    cls = model_obj["cls"]
    y_hat = float(reg.predict(x_row.reshape(1,-1))[0])
    p_up = float(getattr(cls, "predict_proba")(x_row.reshape(1,-1))[0,1])
    return y_hat, p_up
