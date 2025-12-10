# app/ml/regime_aware_forecaster.py
"""
Режим-зависимые модели для прогнозирования.

Держит отдельные модели для разных режимов рынка:
- BULL: бычий рынок
- BEAR: медвежий рынок  
- SIDEWAYS: боковик
- PANIC: паника/краш
"""

import logging
from typing import Dict, Optional
from pathlib import Path

from .catboost_forecaster import (
    forecast_with_catboost,
    load_catboost_model,
    train_catboost_model,
    build_features_from_notebook,
    build_extended_features,
    MODELS_DIR
)
from ..domain.market_regime.global_regime_analyzer import GlobalRegime, GlobalRegimeAnalyzer

logger = logging.getLogger("alt_forecast.ml.regime_aware")


def _regime_to_model_suffix(regime: GlobalRegime) -> str:
    """
    Преобразовать режим рынка в суффикс для имени модели.
    
    Args:
        regime: Глобальный режим рынка
    
    Returns:
        Суффикс для имени модели
    """
    # Группируем режимы в категории моделей
    if regime in [GlobalRegime.RISK_ON, GlobalRegime.ALT_SEASON]:
        return "bull"
    elif regime in [GlobalRegime.RISK_OFF, GlobalRegime.PANIC]:
        return "bear"
    elif regime == GlobalRegime.CHOPPY:
        return "sideways"
    else:
        # BTC_DOMINANCE и другие - используем общую модель
        return "default"


def load_regime_model(
    symbol: str,
    tf: str,
    horizon: int,
    regime: GlobalRegime,
    use_extended: bool = False
) -> Optional[Dict]:
    """
    Загрузить модель для конкретного режима.
    
    Args:
        symbol: Символ
        tf: Таймфрейм
        horizon: Горизонт прогноза
        regime: Глобальный режим рынка
        use_extended: Использовать расширенные фичи
    
    Returns:
        Данные модели или None
    """
    regime_suffix = _regime_to_model_suffix(regime)
    model_name = f"catboost_{regime_suffix}"
    if use_extended:
        model_name = f"catboost_extended_{regime_suffix}"
    
    # Пробуем загрузить режим-специфичную модель
    model_data = load_catboost_model(symbol, tf, horizon, use_extended=False, model_name=model_name)
    
    if model_data is None:
        # Если режим-специфичной модели нет, используем общую
        logger.debug(f"Regime-specific model not found for {regime.value}, using default")
        model_name_default = "catboost_extended" if use_extended else "catboost"
        model_data = load_catboost_model(symbol, tf, horizon, use_extended=use_extended, model_name=model_name_default)
    
    return model_data


def forecast_with_regime_awareness(
    df,
    symbol: str = "BTC",
    tf: str = "1h",
    horizon: int = 12,
    regime: Optional[GlobalRegime] = None,
    regime_analyzer: Optional[GlobalRegimeAnalyzer] = None,
    cached_model_data: Optional[Dict] = None
) -> Optional[Dict]:
    """
    Сделать прогноз с учетом режима рынка.
    
    Args:
        df: DataFrame с OHLCV данными
        symbol: Символ
        tf: Таймфрейм
        horizon: Горизонт прогноза
        regime: Глобальный режим рынка (если None, определяется автоматически)
        regime_analyzer: Анализатор режима (если None, создается новый)
        cached_model_data: Кэшированные данные модели
    
    Returns:
        Dict с прогнозом или None
    """
    # Определяем режим, если не передан
    if regime is None:
        if regime_analyzer is None:
            from ...infrastructure.db import DB
            db = DB()
            regime_analyzer = GlobalRegimeAnalyzer(db)
        
        regime_snapshot = regime_analyzer.analyze_current_regime()
        regime = regime_snapshot.regime if regime_snapshot else GlobalRegime.CHOPPY
    
    # Определяем, использовать ли расширенные фичи
    use_extended = (horizon == 48)
    
    # Загружаем режим-специфичную модель
    if cached_model_data is None:
        model_data = load_regime_model(symbol, tf, horizon, regime, use_extended)
    else:
        model_data = cached_model_data
    
    if model_data is None:
        # Если модели нет, используем обычный forecast_with_catboost
        logger.warning(f"Regime model not found, falling back to default forecast")
        return forecast_with_catboost(df, symbol, tf, horizon, cached_model_data)
    
    # Используем логику из forecast_with_catboost для прогноза
    # (копируем основную логику, но с режим-специфичной моделью)
    try:
        # Строим features
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
        
        # Преобразуем residual в return
        predicted_return = y_pred
        
        # Вычисляем доверительные интервалы
        target_stats = model_data["meta"].get("target_stats", {})
        target_std = target_stats.get("std", 0.0)
        
        if target_std <= 0:
            if len(df_feat) >= 96:
                recent_returns = df_feat['ret_1'].iloc[-96:].dropna()
                if len(recent_returns) > 0:
                    target_std = float(recent_returns.std())
        
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
            "regime_used": regime.value,  # Сохраняем, какой режим использовался
        }
        
        if cached_model_data is None:
            result["model_data"] = model_data
        
        return result
    except Exception as e:
        logger.exception(f"Failed to forecast with regime awareness: {e}")
        # Fallback на обычный прогноз
        return forecast_with_catboost(df, symbol, tf, horizon, cached_model_data)


















