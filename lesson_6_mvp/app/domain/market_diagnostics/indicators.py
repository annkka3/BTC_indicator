# app/domain/market_diagnostics/indicators.py
"""
Расчет технических индикаторов для анализа рынка.

Поддерживаемые индикаторы:
- EMA (9, 20, 50, 200)
- SMA (50, 200)
- VWAP (интрадей + anchored)
- Bollinger Bands (20, 2σ)
- RSI (14)
- Stochastic RSI (14, 14, 3, 3)
- MACD (12, 26, 9)
- ATR (волатильность)
- OBV
- CMF
"""

from typing import Dict, List, Optional, Tuple
import pandas as pd
import numpy as np
try:
    import ta
except ImportError:
    ta = None

from .config import MarketDoctorConfig, DEFAULT_CONFIG


class IndicatorCalculator:
    """Калькулятор технических индикаторов."""
    
    def __init__(self, config: MarketDoctorConfig = None):
        """
        Инициализация калькулятора.
        
        Args:
            config: Конфигурация Market Doctor. Если None, используется DEFAULT_CONFIG
        """
        self.config = config or DEFAULT_CONFIG
        self.min_full_bars = self.config.min_full_bars
    
    def calculate_all(self, df: pd.DataFrame) -> Dict[str, any]:
        """
        Рассчитать все индикаторы для DataFrame с OHLCV данными.
        
        Args:
            df: DataFrame с колонками ['open', 'high', 'low', 'close', 'volume']
                или ['o', 'h', 'l', 'c', 'v']
        
        Returns:
            Словарь с рассчитанными индикаторами
        """
        # Нормализуем названия колонок
        df = self._normalize_columns(df.copy())
        
        if len(df) < self.min_full_bars:
            # Если данных недостаточно, возвращаем что можем
            return self._calculate_minimal(df)
        
        results = {}
        
        # EMA
        results['ema_9'] = self._ema(df['close'], 9)
        results['ema_20'] = self._ema(df['close'], 20)
        results['ema_50'] = self._ema(df['close'], 50)
        results['ema_200'] = self._ema(df['close'], 200)
        
        # SMA
        results['sma_50'] = self._sma(df['close'], 50)
        results['sma_200'] = self._sma(df['close'], 200)
        
        # VWAP (интрадей - упрощенная версия)
        results['vwap'] = self._vwap(df)
        
        # Bollinger Bands (вычисляем один раз)
        bb = self._bollinger_bands(df['close'], 20, 2)
        results['bb_upper'] = bb['upper']
        results['bb_middle'] = bb['middle']
        results['bb_lower'] = bb['lower']
        
        # RSI
        results['rsi'] = self._rsi(df['close'], 14)
        
        # Stochastic RSI (возвращаем и K, и D)
        stoch_rsi = self._stoch_rsi(df['close'], 14, 14, 3, 3)
        results['stoch_rsi_k'] = stoch_rsi['k']
        results['stoch_rsi_d'] = stoch_rsi['d']
        
        # MACD (вычисляем один раз)
        macd = self._macd(df['close'], 12, 26, 9)
        results['macd'] = macd['macd']
        results['macd_signal'] = macd['signal']
        results['macd_hist'] = macd['histogram']
        
        # ATR
        results['atr'] = self._atr(df, 14)
        
        # OBV
        results['obv'] = self._obv(df)
        
        # CMF
        results['cmf'] = self._cmf(df, 20)
        
        # Volume spike (относительный рост к скользящему среднему)
        results['volume_spike'] = self._volume_spike(df['volume'], 20)
        
        # WaveTrend (WT)
        if len(df) >= 10:
            wt = self._wave_trend(df)
            results['wt1'] = wt['wt1']
            results['wt2'] = wt['wt2']
        
        # Schaff Trend Cycle (STC)
        if len(df) >= 50:
            results['stc'] = self._stc(df['close'])
        
        # ADX (Average Directional Index)
        if len(df) >= 14:
            adx_result = self._adx(df, 14)
            results['adx'] = adx_result['adx']
            results['+di'] = adx_result['+di']
            results['-di'] = adx_result['-di']
        
        # Ichimoku Cloud
        if len(df) >= 52:
            ichimoku = self._ichimoku(df)
            results['ichimoku_tenkan'] = ichimoku['tenkan']
            results['ichimoku_kijun'] = ichimoku['kijun']
            results['ichimoku_senkou_a'] = ichimoku['senkou_a']
            results['ichimoku_senkou_b'] = ichimoku['senkou_b']
            results['ichimoku_chikou'] = ichimoku['chikou']
        
        return results
    
    def _normalize_columns(self, df: pd.DataFrame) -> pd.DataFrame:
        """Нормализовать названия колонок."""
        mapping = {
            'o': 'open', 'h': 'high', 'l': 'low', 'c': 'close', 'v': 'volume'
        }
        for old, new in mapping.items():
            if old in df.columns and new not in df.columns:
                df[new] = df[old]
        return df
    
    def _calculate_minimal(self, df: pd.DataFrame) -> Dict[str, any]:
        """Рассчитать минимальный набор индикаторов при недостатке данных."""
        df = self._normalize_columns(df.copy())
        results = {}
        
        n = len(df)
        if n >= 9:
            results['ema_9'] = self._ema(df['close'], 9)
        if n >= 20:
            results['ema_20'] = self._ema(df['close'], 20)
            # Bollinger Bands вычисляем один раз
            bb = self._bollinger_bands(df['close'], min(20, n), 2)
            results['bb_upper'] = bb['upper']
            results['bb_middle'] = bb['middle']
            results['bb_lower'] = bb['lower']
            results['cmf'] = self._cmf(df, min(20, n))
        if n >= 14:
            results['rsi'] = self._rsi(df['close'], 14)
            results['atr'] = self._atr(df, 14)
        if n >= 26:
            # MACD вычисляем один раз
            macd_all = self._macd(df['close'], 12, 26, 9)
            results['macd'] = macd_all['macd']
            results['macd_signal'] = macd_all['signal']
            results['macd_hist'] = macd_all['histogram']
        
        results['obv'] = self._obv(df)
        results['vwap'] = self._vwap(df)
        
        return results
    
    def _ema(self, series: pd.Series, period: int) -> pd.Series:
        """Exponential Moving Average."""
        return series.ewm(span=period, adjust=False).mean()
    
    def _sma(self, series: pd.Series, period: int) -> pd.Series:
        """Simple Moving Average."""
        return series.rolling(window=period).mean()
    
    def _vwap(self, df: pd.DataFrame, anchor_index: int = 0) -> pd.Series:
        """
        Volume Weighted Average Price.
        
        Args:
            df: DataFrame с OHLCV данными
            anchor_index: Индекс начала расчета (для anchored VWAP)
        
        Returns:
            Series с VWAP значениями
        """
        if 'volume' not in df.columns or df['volume'].isna().all():
            # Если объема нет, возвращаем SMA
            return self._sma(df['close'], 20)
        
        # Anchored VWAP от указанного индекса
        price = df['close'].iloc[anchor_index:]
        volume = df['volume'].iloc[anchor_index:].fillna(0)
        
        typical_price = (df['high'].iloc[anchor_index:] + 
                        df['low'].iloc[anchor_index:] + 
                        price) / 3
        
        cum_vol = volume.cumsum()
        cum_pv = (typical_price * volume).cumsum()
        vwap = cum_pv / cum_vol.replace(0, np.nan)
        
        # Создаем полный Series с NaN до anchor_index
        full = pd.Series(index=df.index, data=np.nan, dtype=float)
        full.iloc[anchor_index:] = vwap
        
        return full
    
    def _bollinger_bands(self, series: pd.Series, period: int = 20, std_dev: float = 2.0) -> Dict[str, pd.Series]:
        """Bollinger Bands."""
        sma = self._sma(series, period)
        std = series.rolling(window=period).std()
        
        return {
            'upper': sma + (std * std_dev),
            'middle': sma,
            'lower': sma - (std * std_dev)
        }
    
    def _rsi(self, series: pd.Series, period: int = 14) -> pd.Series:
        """Relative Strength Index."""
        if ta:
            try:
                return ta.momentum.RSIIndicator(close=series, window=period).rsi()
            except Exception:
                pass
        
        # Ручной расчет RSI
        delta = series.diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
        
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))
        return rsi
    
    def _stoch_rsi(self, series: pd.Series, rsi_period: int = 14, stoch_period: int = 14, 
                   k_period: int = 3, d_period: int = 3) -> Dict[str, pd.Series]:
        """
        Stochastic RSI.
        
        Returns:
            Словарь с ключами 'k' и 'd'
        """
        rsi = self._rsi(series, rsi_period)
        
        # Min и Max RSI за период
        rsi_min = rsi.rolling(window=stoch_period).min()
        rsi_max = rsi.rolling(window=stoch_period).max()
        
        # Stoch RSI
        stoch_rsi = ((rsi - rsi_min) / (rsi_max - rsi_min)) * 100
        
        # Сглаживание K и D
        k = stoch_rsi.rolling(window=k_period).mean()
        d = k.rolling(window=d_period).mean()
        
        return {
            'k': k,
            'd': d
        }
    
    def _macd(self, series: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> Dict[str, pd.Series]:
        """MACD (Moving Average Convergence Divergence)."""
        ema_fast = self._ema(series, fast)
        ema_slow = self._ema(series, slow)
        macd_line = ema_fast - ema_slow
        signal_line = self._ema(macd_line, signal)
        histogram = macd_line - signal_line
        
        return {
            'macd': macd_line,
            'signal': signal_line,
            'histogram': histogram
        }
    
    def _atr(self, df: pd.DataFrame, period: int = 14) -> pd.Series:
        """Average True Range."""
        high = df['high']
        low = df['low']
        close = df['close']
        
        tr1 = high - low
        tr2 = abs(high - close.shift())
        tr3 = abs(low - close.shift())
        
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        atr = tr.rolling(window=period).mean()
        
        return atr
    
    def _obv(self, df: pd.DataFrame) -> pd.Series:
        """On-Balance Volume."""
        if 'volume' not in df.columns or df['volume'].isna().all():
            return pd.Series(index=df.index, data=0.0)
        
        close = df['close']
        volume = df['volume'].fillna(0)
        
        obv = (np.sign(close.diff()) * volume).fillna(0).cumsum()
        return obv
    
    def _cmf(self, df: pd.DataFrame, period: int = 20) -> pd.Series:
        """Chaikin Money Flow."""
        if 'volume' not in df.columns or df['volume'].isna().all():
            return pd.Series(index=df.index, data=0.0)
        
        high = df['high']
        low = df['low']
        close = df['close']
        volume = df['volume'].fillna(0)
        
        mfv = ((close - low) - (high - close)) / (high - low) * volume
        cmf = mfv.rolling(window=period).sum() / volume.rolling(window=period).sum()
        
        return cmf.fillna(0)
    
    def _volume_spike(self, volume: pd.Series, period: int = 20) -> pd.Series:
        """Относительный рост объема к скользящему среднему."""
        if volume.isna().all():
            return pd.Series(index=volume.index, data=1.0)
        
        volume_ma = volume.rolling(window=period).mean()
        spike = volume / volume_ma
        return spike.fillna(1.0)
    
    def _wave_trend(self, df: pd.DataFrame, channel_length: int = 10, average_length: int = 21) -> Dict[str, pd.Series]:
        """
        WaveTrend индикатор.
        
        Returns:
            Словарь с 'wt1' и 'wt2'
        """
        high = df['high']
        low = df['low']
        close = df['close']
        
        # AP (Average Price)
        ap = (high + low + close) / 3
        
        # ESA (Exponential Smoothing of AP)
        esa = ap.ewm(span=channel_length, adjust=False).mean()
        
        # D (Difference)
        d = (ap - esa).abs().ewm(span=channel_length, adjust=False).mean()
        
        # CI (Chande Index)
        ci = (ap - esa) / (0.015 * d)
        
        # WT1 и WT2
        wt1 = ci.ewm(span=average_length, adjust=False).mean()
        wt2 = wt1.ewm(span=4, adjust=False).mean()
        
        return {
            'wt1': wt1,
            'wt2': wt2
        }
    
    def _stc(self, close: pd.Series, fast_period: int = 23, slow_period: int = 50, cycle_period: int = 10) -> pd.Series:
        """
        Schaff Trend Cycle (STC).
        
        Returns:
            STC значения от 0 до 100
        """
        # MACD Line
        macd_line = close.ewm(span=fast_period, adjust=False).mean() - close.ewm(span=slow_period, adjust=False).mean()
        
        # Stochastic of MACD
        macd_min = macd_line.rolling(window=cycle_period).min()
        macd_max = macd_line.rolling(window=cycle_period).max()
        
        stoch_macd = 100 * ((macd_line - macd_min) / (macd_max - macd_min))
        stoch_macd = stoch_macd.fillna(50)
        
        # Smooth STC
        stc = stoch_macd.ewm(span=cycle_period, adjust=False).mean()
        
        return stc.fillna(50)
    
    def _adx(self, df: pd.DataFrame, period: int = 14) -> Dict[str, pd.Series]:
        """
        Average Directional Index (ADX).
        
        Returns:
            Словарь с 'adx', '+di', '-di'
        """
        high = df['high']
        low = df['low']
        close = df['close']
        
        # True Range
        tr1 = high - low
        tr2 = abs(high - close.shift())
        tr3 = abs(low - close.shift())
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        
        # Directional Movement
        plus_dm = high.diff()
        minus_dm = -low.diff()
        
        plus_dm[plus_dm < 0] = 0
        minus_dm[minus_dm < 0] = 0
        
        # Smooth TR, +DM, -DM
        atr = tr.rolling(window=period).mean()
        plus_di = 100 * (plus_dm.rolling(window=period).mean() / atr)
        minus_di = 100 * (minus_dm.rolling(window=period).mean() / atr)
        
        # DX
        dx = 100 * abs(plus_di - minus_di) / (plus_di + minus_di)
        dx = dx.fillna(0)
        
        # ADX
        adx = dx.rolling(window=period).mean()
        
        return {
            'adx': adx.fillna(0),
            '+di': plus_di.fillna(0),
            '-di': minus_di.fillna(0)
        }
    
    def _ichimoku(self, df: pd.DataFrame, tenkan: int = 9, kijun: int = 26, senkou_b: int = 52, chikou: int = 26) -> Dict[str, pd.Series]:
        """
        Ichimoku Cloud компоненты.
        
        Returns:
            Словарь с компонентами Ichimoku
        """
        high = df['high']
        low = df['low']
        close = df['close']
        
        # Tenkan-sen (Conversion Line)
        tenkan_high = high.rolling(window=tenkan).max()
        tenkan_low = low.rolling(window=tenkan).min()
        tenkan_sen = (tenkan_high + tenkan_low) / 2
        
        # Kijun-sen (Base Line)
        kijun_high = high.rolling(window=kijun).max()
        kijun_low = low.rolling(window=kijun).min()
        kijun_sen = (kijun_high + kijun_low) / 2
        
        # Senkou Span A (Leading Span A)
        senkou_span_a = ((tenkan_sen + kijun_sen) / 2).shift(kijun)
        
        # Senkou Span B (Leading Span B)
        senkou_b_high = high.rolling(window=senkou_b).max()
        senkou_b_low = low.rolling(window=senkou_b).min()
        senkou_span_b = ((senkou_b_high + senkou_b_low) / 2).shift(kijun)
        
        # Chikou Span (Lagging Span)
        chikou_span = close.shift(-chikou)
        
        return {
            'tenkan': tenkan_sen,
            'kijun': kijun_sen,
            'senkou_a': senkou_span_a,
            'senkou_b': senkou_span_b,
            'chikou': chikou_span
        }

