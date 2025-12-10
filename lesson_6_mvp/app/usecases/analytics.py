# app/usecases/analytics.py
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Dict, List, Tuple, Iterable

import numpy as np
import pandas as pd


# ===== базовые утилы ==========================================================

def _closes_df(db, metrics: Iterable[str], timeframe: str, n: int = 1000) -> pd.DataFrame:
    """
    Собирает wide-DataFrame клоузов с индексом времени.
    Гарантии: сортировка по времени, дедуп по ts, forward-fill, удаление строк с NaN.
    """
    frames: List[pd.Series] = []
    for m in metrics:
        rows = db.last_n_closes(m, timeframe, n)  # [(ts, c)]
        if not rows:
            continue
        # Дедуп по ts: берём последнее значение
        # (dict перезатрёт дубликаты; потом восстановим порядок сортировкой)
        ser_map = {pd.to_datetime(int(ts), unit="ms"): float(c) for ts, c in rows if _is_finite(c)}
        if not ser_map:
            continue
        s = pd.Series(ser_map, name=m).sort_index()
        frames.append(s)

    if not frames:
        return pd.DataFrame()

    df = pd.concat(frames, axis=1).sort_index()
    # Приведём типы, уберём полностью пустые столбцы, ffill для непрерывности
    df = df.apply(pd.to_numeric, errors="coerce")
    df = df.dropna(how="all").ffill().dropna(how="any")
    return df


def _ohlcv_df(db, metric: str, timeframe: str, n: int = 1200) -> pd.DataFrame:
    """
    Возвращает OHLCV DataFrame с индексом времени (UTC).
    Гарантии: сортировка по времени, дедуп по ts, очистка не-конечных значений.
    """
    rows = db.last_n(metric, timeframe, n)  # [(ts,o,h,l,c,v)]
    if not rows:
        return pd.DataFrame()

    # Дедуп по ts с выбором последнего бара
    dedup: Dict[int, Tuple[int, float, float, float, float, float | None]] = {}
    for ts, o, h, l, c, v in rows:
        if not (_is_finite(o) and _is_finite(h) and _is_finite(l) and _is_finite(c)):
            continue
        vv = float(v) if v is not None and _is_finite(v) else np.nan
        dedup[int(ts)] = (int(ts), float(o), float(h), float(l), float(c), vv)

    if not dedup:
        return pd.DataFrame()

    df = pd.DataFrame(
        [dedup[k] for k in sorted(dedup.keys())],
        columns=["ts", "o", "h", "l", "c", "v"],
    )
    df["ts"] = pd.to_datetime(df["ts"], unit="ms")
    df = df.set_index("ts")
    return df


def _is_finite(x) -> bool:
    try:
        xf = float(x)
    except Exception:
        return False
    return math.isfinite(xf)


# ===== 1) корреляции и бета ===================================================

def corr_matrix_and_beta(db, metrics: List[str], base: str, timeframe: str, n: int = 600):
    """
    Возвращает (corr_df, betas_dict), где бета = Cov(asset, base) / Var(base).
    Безопасно обрабатывает нулевую дисперсию бенчмарка.
    """
    df = _closes_df(db, metrics, timeframe, n)
    if df.empty or base not in df.columns:
        return pd.DataFrame(), {}
    rets = df.pct_change().dropna(how="any")
    if rets.empty or rets[base].var() <= 0 or not np.isfinite(rets[base].var()):
        # корр матрицу вернуть можем, а беты бессмысленны
        return rets.corr(), {m: np.nan for m in df.columns}

    corr = rets.corr()
    base_var = float(rets[base].var())
    betas: Dict[str, float] = {}
    for col in rets.columns:
        cov = float(rets[[col, base]].cov().iloc[0, 1])
        betas[col] = cov / base_var if base_var > 0 else np.nan
    return corr, betas


# ===== 2) волатильность и режимы =============================================

@dataclass
class VolStats:
    rv_7: float
    rv_30: float
    atr_14: float
    regime: str
    pctl: float


def realized_vol(x: pd.Series, window: int) -> float:
    """
    Простая realized-vol на окне: std(returns) * sqrt(N) для сопоставимости разных длин.
    Если точек мало — возвращаем std без annualize-масштаба.
    """
    r = x.pct_change().dropna()
    if r.empty:
        return float("nan")
    std = float(r.std())
    return float(std * np.sqrt(len(r))) if len(r) >= window else std


def atr(series: pd.DataFrame, period: int = 14) -> float:
    """
    Классический TR и скользящее среднее (SMA) за period. Возвращает последний ATR.
    """
    if series.empty:
        return float("nan")
    h, l, c = series["h"], series["l"], series["c"]
    prev_c = c.shift(1)
    tr = pd.concat([(h - l).abs(), (h - prev_c).abs(), (l - prev_c).abs()], axis=1).max(axis=1)
    a = tr.rolling(period).mean()
    return float(a.iloc[-1]) if len(a) and pd.notna(a.iloc[-1]) else float("nan")


def vol_regime(db, metric: str, timeframe: str, n: int = 1200) -> VolStats:
    """
    rv7/rv30, ATR14 и грубая классификация режима по перцентилю текущей волы (RV30) на истории.
    """
    df = _ohlcv_df(db, metric, timeframe, n)
    if df.empty or len(df) < 60:
        return VolStats(float("nan"), float("nan"), float("nan"), "n/a", float("nan"))

    rv7 = realized_vol(df["c"], 7)
    rv30 = realized_vol(df["c"], 30)

    rv_hist = df["c"].pct_change().rolling(30).std().dropna()
    if rv_hist.empty or not np.isfinite(rv_hist.iloc[-1]):
        pctl = float("nan")
        regime = "unknown"
    else:
        cur = float(rv_hist.iloc[-1])
        pctl = float((rv_hist <= cur).mean() * 100.0)
        regime = "low" if pctl < 33 else ("high" if pctl > 66 else "normal")

    a14 = atr(df, 14)
    return VolStats(rv7, rv30, a14, regime, pctl)


# ===== 6) уровни S/R и пробои =================================================

def pivot_points(df: pd.DataFrame, k: int = 3) -> Tuple[List[Tuple[pd.Timestamp, float]], List[Tuple[pd.Timestamp, float]]]:
    """
    Возвращает списки локальных максимумов/минимумов (ts, значение) с плечами ±k баров.
    """
    if df is None or df.empty or len(df) < 2 * k + 1:
        return [], []
    H: List[Tuple[pd.Timestamp, float]] = []
    L: List[Tuple[pd.Timestamp, float]] = []
    for i in range(k, len(df) - k):
        window = df.iloc[i - k:i + k + 1]
        # строгое равенство на пике/дне допускает плато — это ок для кластеризации уровней
        if df["h"].iloc[i] == window["h"].max():
            H.append((df.index[i], float(df["h"].iloc[i])))
        if df["l"].iloc[i] == window["l"].min():
            L.append((df.index[i], float(df["l"].iloc[i])))
    return H, L


def nearest_sr(df: pd.DataFrame, k: int = 3):
    """
    Возвращает (last_close, [resist_above], [support_below]).
    """
    if df is None or df.empty:
        return None
    H, L = pivot_points(df, k=k)
    last_close = float(df["c"].iloc[-1])
    above = sorted([p for _, p in H if p >= last_close])[:3]
    below = sorted([p for _, p in L if p <= last_close], reverse=True)[:3]
    return last_close, above, below


def recent_breakouts(df: pd.DataFrame, lookback: int = 50):
    """
    True, если текущая свеча закрылась выше max(high, lookback) или ниже min(low, lookback).
    Безопасно обрабатывает короткие серии.
    """
    if df is None or df.empty or len(df) < max(lookback, 2):
        return False, False
    highs = df["h"].rolling(lookback).max()
    lows = df["l"].rolling(lookback).min()
    # Используем -1 против max/min по предыдущим барам (исключая текущий)
    prev_high = float(highs.iloc[-2]) if len(highs) >= 2 and pd.notna(highs.iloc[-2]) else float("inf")
    prev_low = float(lows.iloc[-2]) if len(lows) >= 2 and pd.notna(lows.iloc[-2]) else float("-inf")
    last_c = float(df["c"].iloc[-1])
    bo_up = last_c > prev_high
    bo_dn = last_c < prev_low
    return bool(bo_up), bool(bo_dn)


# ===== 10) market breadth =====================================================

def breadth(db, metrics: List[str], timeframe: str, ma_short: int = 50, ma_long: int = 200, n: int = 1500):
    """
    Возвращает словарь с количеством/долей метрик выше MA50/MA200.
    Устойчив к пустым сериям; деление на ноль исключено.
    """
    df = _closes_df(db, metrics, timeframe, n)
    if df.empty:
        return {"above_ma50": 0, "above_ma200": 0, "total": 0, "pct_ma50": 0.0, "pct_ma200": 0.0}

    ma50 = df.rolling(ma_short).mean().iloc[-1]
    ma200 = df.rolling(ma_long).mean().iloc[-1]
    last = df.iloc[-1]

    # Сравнение корректно работает и с NaN (NaN -> False)
    above50 = int((last > ma50).fillna(False).sum())
    above200 = int((last > ma200).fillna(False).sum())
    total = int(df.shape[1]) if df.shape[1] > 0 else 1

    return {
        "above_ma50": above50,
        "above_ma200": above200,
        "total": total,
        "pct_ma50": round(100.0 * above50 / total, 1),
        "pct_ma200": round(100.0 * above200 / total, 1),
    }


# ===== 9) простой бэктест RSI =================================================

@dataclass
class BTResult:
    trades: int
    winrate: float
    total_ret: float  # в %
    sharpe: float


def backtest_rsi(
    db,
    metric: str,
    timeframe: str,
    rsi_period: int = 14,
    lower: int = 30,
    upper: int = 70,
    n: int = 3000,
) -> BTResult:
    """
    Простой long-только тест: вход при выходе RSI из перепроданности, выход при достижении зоны перекупленности.
    Возвращает число сделок, winrate, суммарную доходность (%) и грубый шарп.
    """
    df = _ohlcv_df(db, metric, timeframe, n)
    if df.empty or len(df) < rsi_period + 5:
        return BTResult(0, float("nan"), float("nan"), float("nan"))

    # RSI (SMA-вариант через rolling mean; достаточно для быстрой прикидки)
    delta = df["c"].diff()
    up = delta.clip(lower=0).rolling(rsi_period).mean()
    dn = (-delta.clip(upper=0)).rolling(rsi_period).mean()
    rs = up / dn.replace(0, np.nan)
    rsi = (100 - (100 / (1 + rs))).bfill()

    pos = 0
    entry = 0.0
    pnl: List[float] = []
    wins = 0
    trades = 0

    for i in range(1, len(df)):
        # вход: пересечение снизу уровня lower
        if pos == 0 and rsi.iloc[i - 1] < lower <= rsi.iloc[i]:
            pos = 1
            entry = float(df["c"].iloc[i])
            trades += 1
        # выход: пересечение снизу уровня upper
        elif pos == 1 and rsi.iloc[i - 1] < upper <= rsi.iloc[i]:
            ret = float(df["c"].iloc[i]) / entry - 1.0
            wins += int(ret > 0)
            pnl.append(ret)
            pos = 0

    total = float(np.sum(pnl)) if pnl else 0.0
    winrate = (wins / trades * 100.0) if trades > 0 else float("nan")

    rets = pd.Series(pnl, dtype=float)
    vol = float(rets.std()) if len(rets) > 1 else float("nan")
    sharpe = float(np.sqrt(252) * rets.mean() / vol) if vol and np.isfinite(vol) and vol > 0 else float("nan")

    return BTResult(trades, winrate, total * 100.0, sharpe)
