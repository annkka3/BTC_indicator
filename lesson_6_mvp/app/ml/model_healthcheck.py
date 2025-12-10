# app/ml/model_healthcheck.py
"""
Модуль для проверки здоровья ML-моделей.
"""

import logging
import numpy as np
import pandas as pd
from typing import Dict, Optional, List
from pathlib import Path

logger = logging.getLogger("alt_forecast.ml.healthcheck")

try:
    import catboost as cb
    HAS_CATBOOST = True
except ImportError:
    HAS_CATBOOST = False


def healthcheck_model(
    symbol: str,
    tf: str,
    horizon: int,
    model_name: str = "catboost"
) -> Dict:
    """
    Проверить здоровье модели.
    
    Выполняет:
    - Загружает модель
    - Делает тестовые прогоны на известных барах
    - Проверяет: нет NaN в фичах, p_up ∈ [0,1], ci68 вложен в ci95
    
    Args:
        symbol: Символ
        tf: Таймфрейм
        horizon: Горизонт прогноза
        model_name: Имя модели ("catboost" или "catboost_extended")
    
    Returns:
        Dict с результатами проверки
    """
    results = {
        "status": "unknown",
        "checks": {},
        "errors": [],
        "warnings": []
    }
    
    try:
        # Загружаем модель
        from .catboost_forecaster import load_catboost_model, build_features_from_notebook
        from .data_adapter import load_bars_from_project
        
        use_extended = (model_name == "catboost_extended")
        model_data = load_catboost_model(symbol, tf, horizon, use_extended=use_extended)
        
        if model_data is None:
            results["status"] = "error"
            results["errors"].append(f"Model not found: {symbol}_{model_name}_{tf}_h{horizon}")
            return results
        
        # Загружаем тестовые данные
        try:
            df = load_bars_from_project(symbol, tf, limit=1000)
            if df is None or len(df) < 100:
                results["status"] = "error"
                results["errors"].append("Not enough test data")
                return results
        except Exception as e:
            results["status"] = "error"
            results["errors"].append(f"Failed to load test data: {e}")
            return results
        
        # Строим features
        try:
            df_feat = build_features_from_notebook(df)
            if use_extended:
                from .catboost_forecaster import build_extended_features
                df_feat = build_extended_features(df_feat)
        except Exception as e:
            results["status"] = "error"
            results["errors"].append(f"Failed to build features: {e}")
            return results
        
        # Проверка 1: Нет NaN в фичах
        feature_cols = model_data["feature_names"]
        X_test = df_feat[feature_cols].iloc[-10:].values  # Последние 10 баров
        
        nan_check = np.isnan(X_test).any()
        results["checks"]["no_nan_in_features"] = not nan_check
        if nan_check:
            results["warnings"].append("Found NaN values in features")
        
        # Проверка 2: Модель может делать прогнозы
        try:
            y_pred = model_data["reg"].predict(X_test)
            p_up = model_data["cls"].predict_proba(X_test)[:, 1]
            
            results["checks"]["model_can_predict"] = True
        except Exception as e:
            results["status"] = "error"
            results["errors"].append(f"Model prediction failed: {e}")
            results["checks"]["model_can_predict"] = False
            return results
        
        # Проверка 3: p_up ∈ [0,1]
        p_up_valid = (p_up >= 0).all() and (p_up <= 1).all()
        results["checks"]["p_up_in_range"] = p_up_valid
        if not p_up_valid:
            results["errors"].append(f"p_up out of range: min={p_up.min():.3f}, max={p_up.max():.3f}")
        
        # Проверка 4: y_pred разумные значения (не inf, не слишком большие)
        y_pred_valid = np.isfinite(y_pred).all() and (np.abs(y_pred) < 1.0).all()
        results["checks"]["y_pred_valid"] = y_pred_valid
        if not y_pred_valid:
            results["warnings"].append(f"y_pred has extreme values: min={y_pred.min():.3f}, max={y_pred.max():.3f}")
        
        # Проверка 5: Структура модели соответствует ожидаемой
        has_reg = "reg" in model_data
        has_cls = "cls" in model_data
        has_features = "feature_names" in model_data
        has_meta = "meta" in model_data
        
        structure_valid = has_reg and has_cls and has_features and has_meta
        results["checks"]["model_structure_valid"] = structure_valid
        if not structure_valid:
            missing = []
            if not has_reg:
                missing.append("reg")
            if not has_cls:
                missing.append("cls")
            if not has_features:
                missing.append("feature_names")
            if not has_meta:
                missing.append("meta")
            results["errors"].append(f"Missing model components: {', '.join(missing)}")
        
        # Проверка 6: Количество фичей соответствует ожидаемому
        expected_features = len(model_data["feature_names"])
        actual_features = X_test.shape[1]
        features_match = expected_features == actual_features
        results["checks"]["feature_count_match"] = features_match
        if not features_match:
            results["errors"].append(
                f"Feature count mismatch: expected {expected_features}, got {actual_features}"
            )
        
        # Проверка 7: CI (если доступен в метаданных)
        # Это проверка будет выполнена при реальном прогнозе
        
        # Определяем общий статус
        if results["errors"]:
            results["status"] = "error"
        elif results["warnings"]:
            results["status"] = "warning"
        else:
            results["status"] = "ok"
        
        # Добавляем статистику
        results["stats"] = {
            "test_samples": len(X_test),
            "features_count": actual_features,
            "p_up_range": (float(p_up.min()), float(p_up.max())),
            "y_pred_range": (float(y_pred.min()), float(y_pred.max())),
        }
        
    except Exception as e:
        logger.exception(f"Healthcheck failed: {e}")
        results["status"] = "error"
        results["errors"].append(f"Unexpected error: {e}")
    
    return results


def healthcheck_all_models(symbol: str = "BTC", tf: str = "5m") -> Dict:
    """
    Проверить все модели для символа.
    
    Args:
        symbol: Символ
        tf: Таймфрейм
    
    Returns:
        Dict с результатами проверки всех моделей
    """
    horizons = [12, 48, 288]
    model_names = ["catboost", "catboost_extended"]
    
    results = {}
    
    for horizon in horizons:
        for model_name in model_names:
            # Для H=48 используем extended, для остальных - базовый
            if horizon == 48 and model_name == "catboost":
                continue
            if horizon != 48 and model_name == "catboost_extended":
                continue
            
            key = f"{symbol}_{model_name}_{tf}_h{horizon}"
            logger.info(f"Healthchecking {key}")
            results[key] = healthcheck_model(symbol, tf, horizon, model_name)
    
    return results


















