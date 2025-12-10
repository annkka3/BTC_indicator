# app/infrastructure/chart_parser.py
"""
Парсер параметров команд для графиков.
"""

import re
from typing import Dict, Any, Optional
from ..domain.chart_settings import ChartSettings


def parse_chart_command(command: str) -> ChartSettings:
    """Парсить команду с параметрами графика.
    
    Примеры:
    - /chart mode=candle ma=20,50 ind=bb20,2 ann=ribbon,lastline
    - /chart mode=line ind=rsi14,vol legend=bottom
    - /chart BTC mode=candle ma=20,50,200 ind=ema12,ema50,ema200 ind=bb20,2 ann=ribbon,sep=day,pivots,lastline ind=vol,rsi14,macd12,26,9,atr14 legend=top vs=usd tf=1h
    """
    # Убираем команду /chart и символ (если есть)
    parts = command.strip().split()
    
    # Убираем /chart и символ (первые 1-2 части)
    if parts and parts[0].startswith("/chart"):
        parts = parts[1:]
    
    # Если первый элемент - символ (BTC, ETH и т.д.), убираем его
    if parts and len(parts[0]) <= 10 and not "=" in parts[0]:
        parts = parts[1:]
    
    # Собираем все параметры
    params = {}
    
    for part in parts:
        if "=" not in part:
            continue
        
        key, value = part.split("=", 1)
        key = key.lower().strip()
        value = value.strip()
        
        # Обработка специальных случаев
        if key == "ind":
            # ind может содержать несколько индикаторов через запятую
            # Пример: ind=rsi14,vol,macd12,26,9,atr14
            if "ind" not in params:
                params["ind"] = []
            params["ind"].extend([i.strip() for i in value.split(",")])
        elif key == "ann":
            # ann может содержать несколько аннотаций через запятую
            # Пример: ann=ribbon,sep=day,pivots,lastline
            if "ann" not in params:
                params["ann"] = []
            params["ann"].extend([a.strip() for a in value.split(",")])
        else:
            params[key] = value
    
    # Обработка индикаторов
    if "ind" in params:
        indicators = params["ind"]
        for ind in indicators:
            ind_lower = ind.lower().strip()
            
            if ind_lower.startswith("ema"):
                # ema12, ema50, ema200
                period = int(re.sub(r"[^0-9]", "", ind_lower))
                if "ema" not in params:
                    params["ema"] = []
                params["ema"].append(period)
            elif ind_lower.startswith("bb"):
                # bb20,2 или bb20
                bb_match = re.match(r"bb(\d+)(?:[,\s]+([\d.]+))?", ind_lower)
                if bb_match:
                    period = int(bb_match.group(1))
                    std = float(bb_match.group(2)) if bb_match.group(2) else 2.0
                    params["bb"] = f"{period},{std}"
            elif ind_lower.startswith("ichimoku"):
                # ichimoku или ichimoku=9,26,52,26
                if "=" in ind_lower:
                    # Есть параметры
                    ichi_params = ind_lower.split("=", 1)[1]
                    params["ichimoku"] = ichi_params
                else:
                    # Без параметров - используем дефолты
                    params["ichimoku"] = True
            elif ind_lower == "vol":
                params["vol"] = True
            elif ind_lower.startswith("rsi"):
                # rsi14
                period = int(re.sub(r"[^0-9]", "", ind_lower)) or 14
                params["rsi"] = f"rsi{period}"
            elif ind_lower.startswith("macd"):
                # macd12,26,9 или macd12,26,9 (может быть разделено запятыми или пробелами)
                # Убираем "macd" и парсим числа
                macd_str = ind_lower.replace("macd", "")
                # Парсим числа: могут быть разделены запятыми или пробелами
                numbers = re.findall(r"\d+", macd_str)
                if len(numbers) >= 2:
                    fast = int(numbers[0])
                    slow = int(numbers[1])
                    signal = int(numbers[2]) if len(numbers) >= 3 else 9
                    params["macd"] = f"macd{fast},{slow},{signal}"
                else:
                    # Если не удалось распарсить, используем значения по умолчанию
                    params["macd"] = "macd12,26,9"
            elif ind_lower.startswith("atr"):
                # atr14
                period = int(re.sub(r"[^0-9]", "", ind_lower)) or 14
                params["atr"] = f"atr{period}"
        
        del params["ind"]
    
    # Обработка аннотаций
    if "ann" in params:
        annotations = params["ann"]
        for ann in annotations:
            ann_lower = ann.lower().strip()
            
            if ann_lower == "ribbon":
                params["ribbon"] = True
            elif ann_lower.startswith("sep="):
                # sep=day или sep=week
                sep_type = ann_lower.split("=", 1)[1]
                params["sep"] = sep_type
            elif ann_lower == "pivots":
                params["pivots"] = True
            elif ann_lower == "lastline":
                params["lastline"] = True
            elif ann_lower == "last":
                params["last"] = True
            elif ann_lower == "last_ind":
                params["last_ind"] = True
            elif ann_lower == "no_last_ind" or ann_lower == "!last_ind":
                params["last_ind"] = False
        
        del params["ann"]
    
    # Обработка списка EMA
    if "ema" in params and isinstance(params["ema"], list):
        params["ema"] = ",".join(str(p) for p in sorted(set(params["ema"])))
    
    return ChartSettings.from_params(params)


def parse_chart_command_simple(text: str) -> Optional[ChartSettings]:
    """Упрощенный парсинг команды из текста сообщения.
    
    Парсит команды вида:
    - /chart mode=candle ma=20,50
    - /chart BTC mode=line ind=rsi14
    """
    if not text or not text.strip().startswith("/chart"):
        return None
    
    return parse_chart_command(text)

