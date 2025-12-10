# app/infrastructure/derivatives_client.py
"""
Клиент для получения данных деривативов (OI, CVD) из CoinGlass.
"""

import os
import logging
from typing import Dict, Optional
import requests

logger = logging.getLogger("alt_forecast.derivatives")


def get_oi_and_cvd(symbol: str, timeframe: str = "1h") -> Dict[str, float]:
    """
    Получить данные Open Interest и CVD из CoinGlass.
    
    Args:
        symbol: Символ монеты (например, BTC, ETH)
        timeframe: Таймфрейм (1h, 4h, 1d)
    
    Returns:
        Словарь с данными:
        - oi_change_pct: Изменение OI в процентах
        - cvd: CVD (Cumulative Volume Delta) значение
    """
    result = {
        'oi_change_pct': 0.0,
        'cvd': 0.0
    }
    
    # Проверяем наличие API ключа
    api_key = os.getenv("COINGLASS_API_KEY") or os.getenv("COINGLASS_SECRET")
    if not api_key:
        logger.debug("CoinGlass API key not found, skipping OI/CVD fetch")
        return result
    
    try:
        # Нормализуем символ (убираем USDT если есть)
        symbol_clean = symbol.upper().replace("USDT", "").replace(".P", "")
        
        # CoinGlass API endpoint для OI
        # Примечание: точный endpoint зависит от версии API CoinGlass
        # Здесь используется примерный формат
        api_base = os.getenv("COINGLASS_API_BASE", "https://open-api.coinglass.com/api/pro/v1")
        
        headers = {
            "coinglassSecret": api_key,
            "accept": "application/json",
        }
        
        # Пробуем получить OI данные
        # Примечание: CoinGlass API может иметь разные endpoints
        # Здесь используется примерный формат, который нужно адаптировать под реальный API
        try:
            oi_url = f"{api_base}/futures/openInterest"
            params = {"symbol": symbol_clean}
            
            response = requests.get(oi_url, headers=headers, params=params, timeout=10)
            if response.status_code == 200:
                data = response.json()
                # Парсим данные OI (формат зависит от CoinGlass API)
                # Примерная логика:
                if isinstance(data, dict) and 'data' in data:
                    oi_data = data['data']
                    if isinstance(oi_data, list) and len(oi_data) > 0:
                        # Берем последнее значение и сравниваем с предыдущим
                        current_oi = float(oi_data[-1].get('openInterest', 0))
                        if len(oi_data) > 1:
                            prev_oi = float(oi_data[-2].get('openInterest', 0))
                            if prev_oi > 0:
                                result['oi_change_pct'] = ((current_oi - prev_oi) / prev_oi) * 100
        except Exception as e:
            logger.debug(f"Failed to fetch OI from CoinGlass: {e}")
        
        # Пробуем получить CVD данные
        # Примечание: CVD может быть доступен через другой endpoint
        try:
            cvd_url = f"{api_base}/futures/cvd"
            params = {"symbol": symbol_clean}
            
            response = requests.get(cvd_url, headers=headers, params=params, timeout=10)
            if response.status_code == 200:
                data = response.json()
                # Парсим CVD данные
                if isinstance(data, dict) and 'data' in data:
                    cvd_data = data['data']
                    if isinstance(cvd_data, dict):
                        result['cvd'] = float(cvd_data.get('cvd', 0.0))
                    elif isinstance(cvd_data, (int, float)):
                        result['cvd'] = float(cvd_data)
        except Exception as e:
            logger.debug(f"Failed to fetch CVD from CoinGlass: {e}")
        
    except Exception as e:
        logger.exception(f"Error fetching derivatives data from CoinGlass: {e}")
    
    return result


