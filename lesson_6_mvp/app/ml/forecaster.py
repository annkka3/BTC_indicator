from __future__ import annotations
import pandas as pd
import numpy as np
from .features import build_features
from .model import train_models, load_model, infer

def train_symbol(loader_fn, symbol: str, tf: str, horizon: int = 24):
    """
    loader_fn(symbol, tf) -> DataFrame[ts, open, high, low, close, volume]
    """
    df = loader_fn(symbol, tf)
    feats = build_features(df)
    path, meta = train_models(symbol, tf, feats, horizon=horizon)
    return path, meta

def forecast_symbol(loader_fn, symbol: str, tf: str, horizon: int = 24):
    df = loader_fn(symbol, tf)
    feats = build_features(df)
    model = load_model(symbol, tf, horizon=horizon)
    if model is None:
        # обучаем «на лету», если ещё нет
        from .model import train_models
        _, _ = train_models(symbol, tf, feats, horizon=horizon)
        model = load_model(symbol, tf, horizon=horizon)

    X = feats.drop(columns=['open','high','low','close','volume'], errors='ignore')
    x_row = X.iloc[-1].values
    y_hat, p_up = infer(model, x_row)
    
    # Конвертация log-отклонения от EMA в доходность
    # y_hat = log(P_{t+H}) - log(MA(t))
    # Для получения доходности относительно текущей цены:
    # P_{t+H} = MA(t) * exp(y_hat)
    # ret_pred = (P_{t+H} - P_t) / P_t
    current_price = feats['close'].iloc[-1]
    # EMA48 для текущего момента
    ma = feats['close'].ewm(span=48, adjust=False, min_periods=48).mean().iloc[-1]
    # Предсказанная цена через horizon
    predicted_price = ma * np.exp(y_hat)
    # Доходность
    ret_pred = (predicted_price - current_price) / current_price
    
    # Альтернативный упрощенный вариант (если MA ≈ current_price):
    # ret_pred = np.exp(y_hat) - 1
    
    return {
        "symbol": symbol.upper(),
        "tf": tf,
        "horizon": horizon,
        "ret_pred": float(ret_pred),  # ожидаемый доход (%), в долях
        "p_up": p_up,                 # вероятность роста
        "meta": model["meta"],
    }
