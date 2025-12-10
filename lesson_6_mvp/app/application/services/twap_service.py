# app/application/services/twap_service.py
"""
Service for TWAP (Time-Weighted Average Price) calculations.
"""

from typing import Dict, List, Optional
from datetime import datetime, timedelta
import logging

logger = logging.getLogger("alt_forecast.services.twap")


class TWAPService:
    """Сервис для расчета TWAP (Time-Weighted Average Price)."""
    
    def __init__(self, db):
        """
        Args:
            db: Database instance for accessing OHLC data
        """
        self.db = db
    
    def calculate_twap(
        self,
        symbol: str,
        timeframe: str = "1h",
        period_hours: int = 24,
    ) -> Optional[Dict]:
        """
        Рассчитать TWAP (Time-Weighted Average Price) для символа.
        
        ВАЖНО: Это именно TWAP (взвешенная по времени), а НЕ VWAP (взвешенная по объему).
        TWAP учитывает только время, в течение которого цена держалась на определенном уровне,
        и не зависит от объемов торговли.
        
        Формула: TWAP = Σ(Price_i * Δt_i) / Σ(Δt_i)
        где:
        - Price_i - типичная цена бара (HLC/3)
        - Δt_i - длительность интервала между барами (или номинальный таймфрейм)
        
        Args:
            symbol: Символ (BTC, ETH, etc.)
            timeframe: Таймфрейм (5m, 15m, 1h, 4h, 1d)
            period_hours: Период в часах для расчета
        
        Returns:
            Dict с TWAP данными или None
        """
        try:
            # Определяем количество баров для периода
            # Добавлены все используемые таймфреймы для избежания дефолта
            tf_to_hours = {
                "5m": 5.0 / 60.0,      # 0.0833 часа
                "15m": 0.25,           # 0.25 часа
                "1h": 1.0,
                "4h": 4.0,
                "1d": 24.0,
            }
            tf_hours = tf_to_hours.get(timeframe, 1.0)
            # Добавляем +1 для гарантии покрытия всего периода (может быть чуть больше period_hours)
            n_bars = int(period_hours / tf_hours) + 1
            
            # Получаем бары из БД (в порядке oldest → newest)
            rows = self.db.last_n(symbol, timeframe, n_bars)
            if not rows or len(rows) < 2:
                logger.warning("Not enough bars for TWAP calculation: %s %s", symbol, timeframe)
                return None
            
            # Рассчитываем TWAP по формуле: Σ(Price_i * Δt_i) / Σ(Δt_i)
            # Используем типичную цену (HLC/3) для каждого бара
            total_weighted_price = 0.0
            total_time = 0.0
            
            for i, (ts, o, h, l, c, v) in enumerate(rows):
                # Типичная цена бара
                typical_price = (float(h) + float(l) + float(c)) / 3.0
                
                # Время бара в часах (по умолчанию номинальный таймфрейм)
                time_weight = tf_hours
                
                # Если это не последний бар, используем реальный интервал между барами
                # Это позволяет корректно учитывать пропуски/дыры в данных
                if i < len(rows) - 1:
                    next_ts = rows[i + 1][0]
                    # ИСПРАВЛЕНО: rows идут oldest → newest, значит next_ts > ts
                    # Правильная формула: next_ts - ts (разница положительная)
                    time_diff_hours = (int(next_ts) - int(ts)) / (1000.0 * 3600.0)  # ms to hours
                    if time_diff_hours > 0:
                        time_weight = time_diff_hours
                    # При ровном потоке баров time_weight ≈ tf_hours
                    # При пропусках время между барами будет учитываться честно
                
                total_weighted_price += typical_price * time_weight
                total_time += time_weight
            
            if total_time == 0:
                return None
            
            twap = total_weighted_price / total_time
            current_price = float(rows[-1][4])  # последний close
            deviation = ((current_price - twap) / twap) * 100.0 if twap > 0 else 0.0
            
            return {
                "symbol": symbol,
                "timeframe": timeframe,
                "period_hours": period_hours,
                "twap": round(twap, 2),
                "current_price": round(current_price, 2),
                "deviation": round(deviation, 2),
                "bars_count": len(rows),
            }
        except Exception as e:
            logger.exception("Failed to calculate TWAP for %s: %s", symbol, e)
            return None
    
    def get_twap_for_symbols(
        self,
        symbols: List[str],
        timeframe: str = "1h",
        period_hours: int = 24,
    ) -> List[Dict]:
        """
        Получить TWAP для списка символов.
        
        Args:
            symbols: Список символов
            timeframe: Таймфрейм
            period_hours: Период в часах
        
        Returns:
            List[Dict]: Список TWAP данных
        """
        results = []
        for symbol in symbols:
            twap_data = self.calculate_twap(symbol, timeframe, period_hours)
            if twap_data:
                results.append(twap_data)
        return results
    
    def analyze_trading_patterns(
        self,
        symbol: str,
        period_hours: int = 1,
    ) -> Optional[Dict]:
        """
        Анализировать паттерны автоматических ордеров (TWAP-алгоритмов).
        
        Анализирует торговые паттерны на основе:
        - Отклонения цены от TWAP (рассчитанного через calculate_twap)
        - Объемов торговли
        - Направления движения цены
        
        Методология:
        1. Рассчитывает TWAP для периода через calculate_twap
        2. Для каждого бара определяет, выше или ниже типичная цена уровня TWAP
        3. Относит объем к buy (если цена выше TWAP) или sell (если ниже)
        
        Args:
            symbol: Символ (BTC, ETH, etc.)
            period_hours: Период анализа в часах (1 для последнего часа, 24 для суток)
        
        Returns:
            Dict с данными о паттернах торговли или None
        """
        try:
            # Используем 15m таймфрейм для более детального анализа
            timeframe = "15m"
            n_bars = int(period_hours * 4) + 1  # 15m = 4 бара в час
            
            # Получаем бары из БД
            rows = self.db.last_n(symbol, timeframe, n_bars)
            if not rows or len(rows) < 2:
                logger.warning("Not enough bars for pattern analysis: %s %s", symbol, timeframe)
                return None
            
            # Рассчитываем TWAP для периода (после исправления бага будет более точным)
            twap_data = self.calculate_twap(symbol, timeframe, period_hours)
            if not twap_data:
                return None
            
            twap = twap_data["twap"]
            current_price = twap_data["current_price"]
            
            # Анализируем паттерны покупки/продажи
            buy_volume = 0.0
            sell_volume = 0.0
            total_volume = 0.0
            
            # Анализируем каждый бар
            for ts, o, h, l, c, v in rows:
                volume = float(v) if v is not None else 0.0
                if volume == 0:
                    continue
                
                # Типичная цена бара (та же формула, что и в calculate_twap)
                typical_price = (float(h) + float(l) + float(c)) / 3.0
                
                # Если цена выше TWAP - больше покупок, ниже - продажи
                if typical_price > twap:
                    # Покупки (цена выше TWAP)
                    buy_volume += volume
                elif typical_price < twap:
                    # Продажи (цена ниже TWAP)
                    sell_volume += volume
                
                total_volume += volume
            
            # Определяем направление (покупка или продажа доминирует)
            if buy_volume > sell_volume:
                direction = "buy"
                dominant_volume = buy_volume
            elif sell_volume > buy_volume:
                direction = "sell"
                dominant_volume = sell_volume
            else:
                direction = "neutral"
                dominant_volume = total_volume / 2
            
            # Рассчитываем объем в час
            # ПРИМЕЧАНИЕ: Используется period_hours (номинальный период), а не фактическое
            # покрытое время. При наличии дыр в данных метрика может быть немного завышена
            # (один бар растягивается на весь период). Для более точного расчета можно было бы
            # использовать фактическое покрытое время из calculate_twap, но это усложнит код.
            volume_per_hour = dominant_volume / period_hours if period_hours > 0 else 0
            
            # Определяем силу сигнала на основе отклонения от TWAP
            deviation = twap_data["deviation"]
            if abs(deviation) > 1.0:
                signal_strength = "strong"
            elif abs(deviation) > 0.5:
                signal_strength = "moderate"
            else:
                signal_strength = "weak"
            
            # Время обнаружения (время последнего бара)
            last_bar_ts = rows[-1][0]
            minutes_ago = (int(datetime.now().timestamp() * 1000) - last_bar_ts) / (1000 * 60)
            
            return {
                "symbol": symbol,
                "period_hours": period_hours,
                "twap": twap,
                "current_price": current_price,
                "deviation": deviation,
                "direction": direction,
                "buy_volume": buy_volume,
                "sell_volume": sell_volume,
                "total_volume": total_volume,
                "volume_per_hour": volume_per_hour,
                "signal_strength": signal_strength,
                "minutes_ago": round(minutes_ago, 1),
                "bars_count": len(rows),
            }
        except Exception as e:
            logger.exception("Failed to analyze trading patterns for %s: %s", symbol, e)
            return None

