# app/domain/chart_settings.py
"""
Настройки графика для настраиваемого рендеринга.
"""

from typing import List, Optional, Dict, Any
from dataclasses import dataclass, field
from enum import Enum


class PriceMode(str, Enum):
    """Режимы отображения цены."""
    LINE = "line"  # Линия с заливкой
    CANDLE = "candle"  # Классические свечи
    CANDLE_HEIKIN = "candle+heikin"  # Свечи + Heikin-Ashi


class LegendPosition(str, Enum):
    """Позиция легенды."""
    TOP = "top"
    BOTTOM = "bottom"
    OFF = "off"


class SeparatorType(str, Enum):
    """Тип разделителей."""
    DAY = "day"
    WEEK = "week"


@dataclass
class ChartSettings:
    """Настройки графика."""
    
    # Режим отображения цены
    mode: PriceMode = PriceMode.CANDLE
    
    # Оверлеи (MA, EMA, BB, Ichimoku)
    sma_periods: List[int] = field(default_factory=list)  # ma=20,50,200 - пустой список по умолчанию (без дефолтных значений)
    ema_periods: List[int] = field(default_factory=list)  # ind=ema12,ema50,ema200
    bb_period: Optional[int] = None  # ind=bb20,2
    bb_std: float = 2.0  # стандартное отклонение для BB
    ichimoku_enabled: bool = False  # ind=ichimoku или ichimoku=9,26,52,26
    ichimoku_tenkan: int = 9  # период Tenkan-sen
    ichimoku_kijun: int = 26  # период Kijun-sen
    ichimoku_senkou_b: int = 52  # период Senkou Span B
    ichimoku_chikou: int = 26  # период Chikou Span (обычно равен Kijun)
    
    # Подложки и подсветки
    ribbon: bool = False  # ann=ribbon - лента тренда выше/ниже EMA200
    separator: Optional[SeparatorType] = None  # ann=sep=day|week
    pivots: bool = False  # ann=pivots - маркеры локальных high/low
    lastline: bool = False  # ann=lastline - пунктир на последней цене
    last_badge: bool = False  # ann=last - бейдж с текущей ценой и % изменения в правом верхнем углу
    last_ind: bool = True  # ann=last_ind - подписи последних значений индикаторов справа (по умолчанию включено)
    
    # Дивергенции
    show_divergences: bool = False  # ann=div - показывать дивергенции на графике
    divergence_indicators: Dict[str, bool] = field(default_factory=lambda: {
        "RSI": True,
        "MACD": True,
        "STOCH": False,
        "CCI": False,
        "MFI": False,
        "OBV": False,
        "VOLUME": False,
    })  # Какие индикаторы использовать для поиска дивергенций
    
    # Нижние панели
    show_volume: bool = False  # ind=vol
    show_rsi: bool = False  # ind=rsi14
    rsi_period: int = 14
    show_macd: bool = False  # ind=macd12,26,9
    macd_fast: int = 12
    macd_slow: int = 26
    macd_signal: int = 9
    show_atr: bool = False  # ind=atr14
    atr_period: int = 14
    
    # Прочее
    legend: LegendPosition = LegendPosition.TOP  # legend=top|bottom|off
    currency: str = "usd"  # vs=usd|usdt|eur|...
    timeframe: str = "1h"  # TF alias (240, 60m, day, 1w, 1mo и пр.)
    
    def __post_init__(self):
        """Валидация и нормализация настроек."""
        # Нормализуем timeframe
        self.timeframe = self._normalize_timeframe(self.timeframe)
        
        # Ограничиваем количество SMA периодов до 6 (но не добавляем дефолтные, если список пустой)
        if len(self.sma_periods) > 6:
            self.sma_periods = self.sma_periods[:6]
        
        # Валидация периодов
        if self.bb_period is not None and self.bb_period <= 0:
            self.bb_period = None
        if self.rsi_period <= 0:
            self.rsi_period = 14
        if self.atr_period <= 0:
            self.atr_period = 14
        if self.macd_fast <= 0 or self.macd_slow <= 0 or self.macd_signal <= 0:
            self.macd_fast, self.macd_slow, self.macd_signal = 12, 26, 9
        # Валидация Ichimoku периодов
        if self.ichimoku_tenkan <= 0:
            self.ichimoku_tenkan = 9
        if self.ichimoku_kijun <= 0:
            self.ichimoku_kijun = 26
        if self.ichimoku_senkou_b <= 0:
            self.ichimoku_senkou_b = 52
        if self.ichimoku_chikou <= 0:
            self.ichimoku_chikou = 26
    
    @staticmethod
    def _normalize_timeframe(tf: str) -> str:
        """Нормализация TF-алиасов."""
        tf_lower = tf.lower().strip()
        
        # Маппинг алиасов
        tf_map = {
            "240": "4h",
            "60m": "1h",
            "60": "1h",
            "1h": "1h",
            "15m": "15m",
            "15": "15m",
            "day": "1d",
            "1d": "1d",
            "24h": "1d",
            "1w": "1w",
            "week": "1w",
            "1mo": "1mo",
            "month": "1mo",
            "4h": "4h",
        }
        
        return tf_map.get(tf_lower, tf_lower)
    
    @classmethod
    def from_params(cls, params: Dict[str, Any]) -> "ChartSettings":
        """Создать настройки из словаря параметров."""
        settings = cls()
        
        # Режим отображения цены
        if "mode" in params:
            try:
                settings.mode = PriceMode(params["mode"].lower())
            except ValueError:
                pass
        
        # SMA периоды - сначала проверяем sma_periods из БД, потом ma из команды
        if "sma_periods" in params:
            # Если это список, используем его (может быть пустым)
            if isinstance(params["sma_periods"], list):
                settings.sma_periods = [p for p in params["sma_periods"] if p > 0][:6]
        elif "ma" in params:
            try:
                periods = [int(p.strip()) for p in str(params["ma"]).split(",") if p.strip()]
                settings.sma_periods = [p for p in periods if p > 0][:6]  # Ограничиваем до 6 периодов
            except (ValueError, AttributeError):
                pass
        
        # EMA периоды - сначала проверяем ema_periods из БД, потом ema из команды
        if "ema_periods" in params:
            # Если это список, используем его
            if isinstance(params["ema_periods"], list):
                settings.ema_periods = [p for p in params["ema_periods"] if p > 0]
        elif "ema" in params:
            try:
                periods = [int(p.strip().replace("ema", "")) for p in str(params["ema"]).split(",") if p.strip()]
                settings.ema_periods = [p for p in periods if p > 0]
            except (ValueError, AttributeError):
                pass
        
        # Bollinger Bands - сначала проверяем bb_period из БД, потом bb из команды
        if "bb_period" in params:
            try:
                settings.bb_period = int(params["bb_period"]) if params["bb_period"] is not None else None
                if "bb_std" in params:
                    settings.bb_std = float(params["bb_std"])
            except (ValueError, TypeError):
                pass
        elif "bb" in params:
            try:
                bb_str = str(params["bb"]).lower()
                if "," in bb_str:
                    period, std = bb_str.split(",", 1)
                    settings.bb_period = int(period.strip())
                    settings.bb_std = float(std.strip())
                else:
                    settings.bb_period = int(bb_str)
            except (ValueError, AttributeError):
                pass
        
        # Ichimoku - сначала проверяем ichimoku_enabled из БД, потом ichimoku из команды
        if "ichimoku_enabled" in params:
            settings.ichimoku_enabled = bool(params["ichimoku_enabled"])
            if settings.ichimoku_enabled:
                if "ichimoku_tenkan" in params:
                    settings.ichimoku_tenkan = int(params["ichimoku_tenkan"])
                if "ichimoku_kijun" in params:
                    settings.ichimoku_kijun = int(params["ichimoku_kijun"])
                if "ichimoku_senkou_b" in params:
                    settings.ichimoku_senkou_b = int(params["ichimoku_senkou_b"])
                if "ichimoku_chikou" in params:
                    settings.ichimoku_chikou = int(params["ichimoku_chikou"])
        elif "ichimoku" in params:
            settings.ichimoku_enabled = True
            try:
                ichi_str = str(params["ichimoku"]).strip()
                if ichi_str and ichi_str.lower() not in ("true", "1", "yes"):
                    # Парсим параметры: ichimoku=9,26,52,26
                    periods = [int(p.strip()) for p in ichi_str.split(",") if p.strip()]
                    if len(periods) >= 1:
                        settings.ichimoku_tenkan = periods[0]
                    if len(periods) >= 2:
                        settings.ichimoku_kijun = periods[1]
                    if len(periods) >= 3:
                        settings.ichimoku_senkou_b = periods[2]
                    if len(periods) >= 4:
                        settings.ichimoku_chikou = periods[3]
            except (ValueError, AttributeError):
                pass
        
        # Подложки - проверяем все варианты (из БД и из команды)
        if "ribbon" in params:
            settings.ribbon = bool(params["ribbon"])
        if "separator" in params:
            try:
                if params["separator"] is not None:
                    settings.separator = SeparatorType(params["separator"].lower())
                else:
                    settings.separator = None
            except (ValueError, AttributeError):
                pass
        elif "sep" in params:
            try:
                settings.separator = SeparatorType(params["sep"].lower())
            except ValueError:
                pass
        if "pivots" in params:
            settings.pivots = bool(params["pivots"])
        if "lastline" in params:
            settings.lastline = bool(params["lastline"])
        if "last_badge" in params:
            settings.last_badge = bool(params["last_badge"])
        elif "last" in params:
            settings.last_badge = bool(params["last"])
        if "last_ind" in params:
            # last_ind может быть явно выключен
            settings.last_ind = bool(params["last_ind"])
        # Если last_ind не указан, используем значение по умолчанию (True)
        
        # Дивергенции
        if "div" in params and params["div"]:
            settings.show_divergences = True
        if params.get("show_divergences", False):
            settings.show_divergences = True
        if "divergence_indicators" in params:
            # Обновляем словарь индикаторов
            div_indicators = params.get("divergence_indicators", {})
            if isinstance(div_indicators, dict):
                # Полностью заменяем словарь, а не обновляем
                settings.divergence_indicators = div_indicators.copy()
            elif isinstance(div_indicators, str):
                # Если это строка (JSON), пытаемся распарсить
                try:
                    import json
                    settings.divergence_indicators = json.loads(div_indicators)
                except Exception:
                    pass
        
        # Нижние панели
        # Поддерживаем оба формата: "vol" (из команды) и "show_volume" (из меню настроек)
        if ("vol" in params and params["vol"]) or params.get("show_volume", False):
            settings.show_volume = True
        if "rsi" in params or params.get("show_rsi", False):
            try:
                if "rsi" in params:
                    rsi_str = str(params["rsi"]).lower().replace("rsi", "")
                    settings.rsi_period = int(rsi_str) if rsi_str else 14
                elif "rsi_period" in params:
                    settings.rsi_period = int(params["rsi_period"])
                settings.show_rsi = True
            except (ValueError, AttributeError):
                settings.show_rsi = True
        if "macd" in params or params.get("show_macd", False):
            try:
                if "macd" in params:
                    macd_str = str(params["macd"]).lower().replace("macd", "")
                    # Парсим числа из строки (могут быть разделены запятыми)
                    import re
                    numbers = [int(n) for n in re.findall(r"\d+", macd_str)]
                    if len(numbers) >= 2:
                        settings.macd_fast = numbers[0]
                        settings.macd_slow = numbers[1]
                        settings.macd_signal = numbers[2] if len(numbers) >= 3 else 9
                else:
                    # Из меню настроек
                    if "macd_fast" in params:
                        settings.macd_fast = int(params["macd_fast"])
                    if "macd_slow" in params:
                        settings.macd_slow = int(params["macd_slow"])
                    if "macd_signal" in params:
                        settings.macd_signal = int(params["macd_signal"])
                settings.show_macd = True
            except (ValueError, AttributeError, Exception):
                settings.show_macd = True
        if "atr" in params or params.get("show_atr", False):
            try:
                if "atr" in params:
                    atr_str = str(params["atr"]).lower().replace("atr", "")
                    settings.atr_period = int(atr_str) if atr_str else 14
                elif "atr_period" in params:
                    settings.atr_period = int(params["atr_period"])
                settings.show_atr = True
            except (ValueError, AttributeError):
                settings.show_atr = True
        
        # Легенда
        if "legend" in params:
            try:
                settings.legend = LegendPosition(params["legend"].lower())
            except ValueError:
                pass
        
        # Валюта
        if "vs" in params or "currency" in params:
            currency = params.get("vs") or params.get("currency", "usd")
            settings.currency = str(currency).lower()
        
        # Timeframe
        if "tf" in params or "timeframe" in params:
            tf = params.get("tf") or params.get("timeframe", "1h")
            settings.timeframe = cls._normalize_timeframe(str(tf))
        
        return settings
    
    @classmethod
    def parse_command_string(cls, command: str) -> "ChartSettings":
        """Парсить строку команды с параметрами.
        
        Примеры:
        - /chart mode=candle ma=20,50 ind=bb20,2 ann=ribbon,lastline
        - /chart mode=line ind=rsi14,vol legend=bottom
        """
        params = {}
        
        # Разбиваем команду на части
        parts = command.split()
        
        for part in parts:
            if "=" in part:
                key, value = part.split("=", 1)
                key = key.lower().strip()
                value = value.strip()
                
                # Обработка специальных случаев
                if key == "ind":
                    # ind может содержать несколько индикаторов через запятую
                    indicators = [i.strip() for i in value.split(",")]
                    for ind in indicators:
                        ind_lower = ind.lower()
                        if ind_lower.startswith("ema"):
                            if "ema" not in params:
                                params["ema"] = []
                            period = int(ind_lower.replace("ema", ""))
                            params["ema"].append(period)
                        elif ind_lower.startswith("bb"):
                            # bb20,2 или bb20
                            params["bb"] = ind_lower.replace("bb", "")
                        elif ind_lower.startswith("ichimoku"):
                            # ichimoku или ichimoku=9,26,52,26
                            if "=" in ind_lower:
                                ichi_params = ind_lower.split("=", 1)[1]
                                params["ichimoku"] = ichi_params
                            else:
                                params["ichimoku"] = True
                        elif ind_lower == "vol":
                            params["vol"] = True
                        elif ind_lower.startswith("rsi"):
                            params["rsi"] = ind_lower
                        elif ind_lower.startswith("macd"):
                            params["macd"] = ind_lower
                        elif ind_lower.startswith("atr"):
                            params["atr"] = ind_lower
                elif key == "ann":
                    # ann может содержать несколько аннотаций через запятую
                    annotations = [a.strip() for a in value.split(",")]
                    for ann in annotations:
                        ann_lower = ann.lower()
                        if ann_lower == "ribbon":
                            params["ribbon"] = True
                        elif ann_lower.startswith("sep="):
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
                elif key == "ma":
                    params["ma"] = value
                elif key == "mode":
                    params["mode"] = value
                elif key == "legend":
                    params["legend"] = value
                elif key in ("vs", "currency"):
                    params["vs"] = value
                elif key in ("tf", "timeframe"):
                    params["tf"] = value
                elif key == "ichimoku":
                    params["ichimoku"] = value if value else True
        
        # Обработка списка EMA
        if "ema" in params and isinstance(params["ema"], list):
            params["ema"] = ",".join(str(p) for p in params["ema"])
        
        return cls.from_params(params)
    
    def to_dict(self) -> Dict[str, Any]:
        """Преобразовать настройки в словарь."""
        return {
            "mode": self.mode.value,
            "sma_periods": self.sma_periods,
            "ema_periods": self.ema_periods,
            "bb_period": self.bb_period,
            "bb_std": self.bb_std,
            "ichimoku_enabled": self.ichimoku_enabled,
            "ichimoku_tenkan": self.ichimoku_tenkan,
            "ichimoku_kijun": self.ichimoku_kijun,
            "ichimoku_senkou_b": self.ichimoku_senkou_b,
            "ichimoku_chikou": self.ichimoku_chikou,
            "ribbon": self.ribbon,
            "separator": self.separator.value if self.separator else None,
            "pivots": self.pivots,
            "lastline": self.lastline,
            "last_badge": self.last_badge,
            "last_ind": self.last_ind,
            "show_divergences": self.show_divergences,
            "divergence_indicators": self.divergence_indicators,
            "show_volume": self.show_volume,
            "show_rsi": self.show_rsi,
            "rsi_period": self.rsi_period,
            "show_macd": self.show_macd,
            "macd_fast": self.macd_fast,
            "macd_slow": self.macd_slow,
            "macd_signal": self.macd_signal,
            "show_atr": self.show_atr,
            "atr_period": self.atr_period,
            "legend": self.legend.value,
            "currency": self.currency,
            "timeframe": self.timeframe,
        }

