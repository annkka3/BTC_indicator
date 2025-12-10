# app/domain/services.py
from __future__ import annotations
from typing import Tuple, Optional, Dict, List
import math
import statistics as stats

from .models import Metric, Timeframe, Divergence

ARROW_UP = "⬆"
ARROW_DOWN = "⬇"
ARROW_FLAT = "→"

TIMEFRAMES: tuple[Timeframe, ...] = ("15m", "1h", "4h", "1d")

WINDOW_BARS = {"15m": 50, "1h": 60, "4h": 60, "1d": 90}

PAIR_REL: list[tuple[Metric, Metric, str]] = [
    ("TOTAL3", "USDT.D", "inverse"),
    ("TOTAL3", "BTC.D",  "inverse"),
    ("TOTAL3", "BTC",    "direct"),
    ("TOTAL3", "TOTAL2", "direct"),
    ("ETHBTC", "BTC.D",  "inverse"),
]

# ---------------- utils / indicators ----------------

def arrow_from_delta(delta: float | None, eps: float = 0.0) -> str:
    if delta is None or (isinstance(delta, float) and math.isnan(delta)):
        return ARROW_FLAT
    if delta > eps:
        return ARROW_UP
    if delta < -eps:
        return ARROW_DOWN
    return ARROW_FLAT

def ema(values: list[float], period: int) -> list[Optional[float]]:
    if period <= 0 or not values:
        return []
    n = len(values)
    out: list[Optional[float]] = [None] * n
    if n < period:
        return out
    k = 2 / (period + 1)
    sma = sum(values[:period]) / period
    out[period - 1] = sma
    prev = sma
    for i in range(period, n):
        prev = (values[i] - prev) * k + prev
        out[i] = prev
    return out

def rsi(values: list[float], period: int = 14) -> list[Optional[float]]:
    n = len(values)
    if n < period + 1:
        return [None] * n
    rsis: list[Optional[float]] = [None] * n
    gains: List[float] = []
    losses: List[float] = []
    for i in range(1, period + 1):
        ch = values[i] - values[i - 1]
        gains.append(max(ch, 0.0))
        losses.append(-min(ch, 0.0))
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    rs = (avg_gain / avg_loss) if avg_loss != 0 else float("inf")
    rsis[period] = 100 - (100 / (1 + rs))
    for i in range(period + 1, n):
        ch = values[i] - values[i - 1]
        gain = max(ch, 0.0)
        loss = -min(ch, 0.0)
        avg_gain = (avg_gain * (period - 1) + gain) / period
        avg_loss = (avg_loss * (period - 1) + loss) / period
        rs = (avg_gain / avg_loss) if avg_loss != 0 else float("inf")
        rsis[i] = 100 - (100 / (1 + rs))
    return rsis

def macd(values: list[float], fast: int = 12, slow: int = 26, signal: int = 9) -> tuple[list[Optional[float]], list[Optional[float]], list[Optional[float]]]:
    ema_fast = ema(values, fast)
    ema_slow = ema(values, slow)
    macd_line: list[Optional[float]] = [None] * len(values)
    for i in range(len(values)):
        if ema_fast[i] is not None and ema_slow[i] is not None:
            macd_line[i] = ema_fast[i] - ema_slow[i]
    macd_vals = [x if x is not None else 0.0 for x in macd_line]
    sig = ema(macd_vals, signal)
    hist: list[Optional[float]] = [None if (m is None or s is None) else (m - s) for m, s in zip(macd_line, sig)]
    return macd_line, sig, hist

def true_range(h: float, l: float, prev_c: float | None) -> float:
    if prev_c is None:
        return h - l
    return max(h - l, abs(h - prev_c), abs(l - prev_c))

def atr(highs: list[float], lows: list[float], closes: list[float], period: int = 14) -> list[Optional[float]]:
    n = len(closes)
    if n == 0:
        return []
    trs: list[float] = []
    prev_c: float | None = None
    for i in range(n):
        trs.append(true_range(highs[i], lows[i], prev_c))
        prev_c = closes[i]
    return ema(trs, period)

def _last_two_indices(flags: list[bool]) -> list[int]:
    # последние два True-индекса
    idx = [i for i, b in enumerate(flags) if b]
    return idx[-2:]

def pivots_high(values: list[float], left: int = 2, right: int = 2) -> list[bool]:
    n = len(values)
    res = [False] * n
    for i in range(left, n - right):
        v = values[i]
        if all(v > values[i - j] for j in range(1, left + 1)) and all(v > values[i + j] for j in range(1, right + 1)):
            res[i] = True
    return res

def pivots_low(values: list[float], left: int = 2, right: int = 2) -> list[bool]:
    n = len(values)
    res = [False] * n
    for i in range(left, n - right):
        v = values[i]
        if all(v < values[i - j] for j in range(1, left + 1)) and all(v < values[i + j] for j in range(1, right + 1)):
            res[i] = True
    return res

# ---------------- levels (ATR-based clustering) ----------------

def key_levels(closes: list[float], highs: list[float], lows: list[float], k: int = 3) -> tuple[list[float], list[float]]:
    """Возвращает (supports, resistances) — по 0..k ближайших уровней, кластеризованных по ATR."""
    if not closes:
        return [], []
    last = closes[-1]
    ph = pivots_high(highs, 2, 2)
    pl = pivots_low(lows, 2, 2)
    res_levels = [highs[i] for i, b in enumerate(ph) if b]
    sup_levels = [lows[i] for i, b in enumerate(pl) if b]

    # радиус кластера = max(0.25*ATR, 0.2% цены)
    atr14 = atr(highs, lows, closes, 14)
    atr_last = atr14[-1] if atr14 and atr14[-1] is not None else (last * 0.003 if last else 1.0)
    cluster_r = max(0.25 * float(atr_last), (abs(last) * 0.002))

    def cluster(levels: list[float], radius: float) -> list[float]:
        if not levels:
            return []
        levels = sorted(levels)
        clusters: list[list[float]] = [[levels[0]]]
        for lv in levels[1:]:
            if abs(lv - clusters[-1][-1]) <= radius:
                clusters[-1].append(lv)
            else:
                clusters.append([lv])
        # берём медиану кластера
        return [sorted(grp)[len(grp) // 2] for grp in clusters]

    res_levels = cluster(res_levels, cluster_r)
    sup_levels = cluster(sup_levels, cluster_r)

    res_sorted = sorted([lv for lv in res_levels if lv >= last], key=lambda x: x - last)[:k]
    sup_sorted = sorted([lv for lv in sup_levels if lv <= last], key=lambda x: last - x)[:k]
    return sup_sorted, res_sorted

# ---------------- swings & divergences ----------------

def last_two_swings(values: list[float]) -> tuple[Optional[tuple[int, float]], Optional[tuple[int, float]]]:
    hi_flags = pivots_high(values, 2, 2)
    lo_flags = pivots_low(values, 2, 2)
    last_hi_idx = next((i for i in range(len(values) - 1, -1, -1) if hi_flags[i]), None)
    last_lo_idx = next((i for i in range(len(values) - 1, -1, -1) if lo_flags[i]), None)
    return ((last_hi_idx, values[last_hi_idx]) if last_hi_idx is not None else None,
            (last_lo_idx, values[last_lo_idx]) if last_lo_idx is not None else None)

def _strength_tag(diff: float, series: list[Optional[float]]) -> str:
    vals = [x for x in series if x is not None]
    if len(vals) < 20:
        return "(слабая)"
    try:
        sd = stats.pstdev(vals)
    except Exception:
        sd = 0.0
    if sd <= 1e-9:
        return "(слабая)"
    z = abs(diff) / sd
    if z >= 1.2:
        return "(сильная)"
    if z >= 0.7:
        return "(средняя)"
    return "(слабая)"

def _alts_implication(metric: Metric, bullish_for_metric: bool) -> str:
    """
    Приводим сигналы к «альто-логике»:
      • для USDT.D и BTC.D рост = плохо для альт (bullish -> bearish_alts)
      • для остальных (BTC, TOTAL2/3, ETHBTC) рост = хорошо для альт
    """
    if metric in ("USDT.D", "BTC.D"):
        return "bearish_alts" if bullish_for_metric else "bullish_alts"
    return "bullish_alts" if bullish_for_metric else "bearish_alts"

def indicator_divergences(metric: Metric, tf: Timeframe, closes: list[float], vols: list[Optional[float]]) -> list[Divergence]:
    out: list[Divergence] = []
    n = len(closes)
    if n < 50:
        return out

    r = rsi(closes, 14)
    m_line, sig, _ = macd(closes, 12, 26, 9)

    hi_flags = pivots_high(closes, 2, 2)
    lo_flags = pivots_low(closes, 2, 2)
    hi_idx = _last_two_indices(hi_flags)
    lo_idx = _last_two_indices(lo_flags)

    # RSI
    if len(hi_idx) == 2 and r[hi_idx[0]] is not None and r[hi_idx[1]] is not None:
        if closes[hi_idx[1]] > closes[hi_idx[0]] and r[hi_idx[1]] < r[hi_idx[0]]:
            diff = (r[hi_idx[1]] - r[hi_idx[0]])
            out.append(Divergence(
                tf, metric, "RSI",
                f"Bearish дивергенция (RSI) { _strength_tag(diff, r) }: цена HH, RSI ниже",
                _alts_implication(metric, bullish_for_metric=False)
            ))
    if len(lo_idx) == 2 and r[lo_idx[0]] is not None and r[lo_idx[1]] is not None:
        if closes[lo_idx[1]] < closes[lo_idx[0]] and r[lo_idx[1]] > r[lo_idx[0]]:
            diff = (r[lo_idx[1]] - r[lo_idx[0]])
            out.append(Divergence(
                tf, metric, "RSI",
                f"Bullish дивергенция (RSI) { _strength_tag(diff, r) }: цена LL, RSI выше",
                _alts_implication(metric, bullish_for_metric=True)
            ))

    # MACD
    if len(hi_idx) == 2 and m_line[hi_idx[0]] is not None and m_line[hi_idx[1]] is not None:
        if closes[hi_idx[1]] > closes[hi_idx[0]] and m_line[hi_idx[1]] < m_line[hi_idx[0]]:
            diff = (m_line[hi_idx[1]] - m_line[hi_idx[0]])
            out.append(Divergence(
                tf, metric, "MACD",
                f"Bearish дивергенция (MACD) { _strength_tag(diff, [x for x in m_line if x is not None]) }: цена HH, MACD ниже",
                _alts_implication(metric, bullish_for_metric=False)
            ))
    if len(lo_idx) == 2 and m_line[lo_idx[0]] is not None and m_line[lo_idx[1]] is not None:
        if closes[lo_idx[1]] < closes[lo_idx[0]] and m_line[lo_idx[1]] > m_line[lo_idx[0]]:
            diff = (m_line[lo_idx[1]] - m_line[lo_idx[0]])
            out.append(Divergence(
                tf, metric, "MACD",
                f"Bullish дивергенция (MACD) { _strength_tag(diff, [x for x in m_line if x is not None]) }: цена LL, MACD выше",
                _alts_implication(metric, bullish_for_metric=True)
            ))

    # Volume
    if vols and any(v is not None for v in vols):
        vols_pure = vols
        if len(hi_idx) == 2 and vols_pure[hi_idx[0]] is not None and vols_pure[hi_idx[1]] is not None:
            if closes[hi_idx[1]] > closes[hi_idx[0]] and vols_pure[hi_idx[1]] < vols_pure[hi_idx[0]]:
                out.append(Divergence(
                    tf, metric, "VOLUME",
                    "Bearish дивергенция (Volume): HH на меньшем объёме",
                    _alts_implication(metric, bullish_for_metric=False)
                ))
        if len(lo_idx) == 2 and vols_pure[lo_idx[0]] is not None and vols_pure[lo_idx[1]] is not None:
            if closes[lo_idx[1]] < closes[lo_idx[0]] and vols_pure[lo_idx[1]] < vols_pure[lo_idx[0]]:
                out.append(Divergence(
                    tf, metric, "VOLUME",
                    "Bullish дивергенция (Volume): LL на меньшем объёме",
                    _alts_implication(metric, bullish_for_metric=True)
                ))

    return out

# ---------------- pair / cross divergences ----------------

def pair_divergences(tf: Timeframe, series: dict[Metric, list[Tuple[int, float]]]) -> list[Divergence]:
    """
    Смотрим на HH/LL TOTAL3/TOTAL2/BTC/ETHBTC и подтверждение/опровержение от USDT.D/BTC.D.
    Допуск ~0.15% на «почти экстремумы».
    """
    out: list[Divergence] = []
    win = WINDOW_BARS.get(tf, 60)

    def new_extreme(vals: list[float], tol_rel: float = 0.0015) -> tuple[bool, bool]:
        """Возвращает (is_near_HH, is_near_LL) — «почти экстремум» + направление к last-1."""
        if len(vals) < 3:
            return (False, False)
        last = vals[-1]
        prev_last = vals[-2]
        mx = max(vals[:-1])
        mn = min(vals[:-1])
        up = (last >= mx * (1 - tol_rel)) and (last > prev_last)
        dn = (last <= mn * (1 + tol_rel)) and (last < prev_last)
        return up, dn

    for A, B, rel in PAIR_REL:
        sa = series.get(A, [])
        sb = series.get(B, [])
        if len(sa) < win or len(sb) < win:
            continue
        a_vals = [c for _, c in sa[-win:]]
        b_vals = [c for _, c in sb[-win:]]
        a_hi, a_lo = new_extreme(a_vals)
        b_hi, b_lo = new_extreme(b_vals)

        if rel == "direct":
            if a_hi and not b_hi:
                out.append(Divergence(tf, None, "PAIR", f"Direct дивергенция: {A} HH без подтверждения {B}", "bearish_alts" if A in ("TOTAL3","TOTAL2","BTC") else "neutral"))
            if a_lo and not b_lo:
                out.append(Divergence(tf, None, "PAIR", f"Direct дивергенция: {A} LL без подтверждения {B}", "bullish_alts" if A in ("TOTAL3","TOTAL2","BTC") else "neutral"))
        else:  # inverse
            if a_hi and not b_lo:
                out.append(Divergence(tf, None, "PAIR", f"Inverse дивергенция: {A} HH, {B} не делает LL", "bearish_alts" if A in ("TOTAL3","ETHBTC") else "neutral"))
            if a_lo and not b_hi:
                out.append(Divergence(tf, None, "PAIR", f"Inverse дивергенция: {A} LL, {B} не делает HH", "bullish_alts" if A in ("TOTAL3","ETHBTC") else "neutral"))

    return out

# ---------------- arrows ----------------

def slope_arrow(closes: list[float], ema_period: int = 3, eps_rel: float = 0.0005) -> str:
    """(legacy) Стрелка по уклону EMA(period) последних двух значений."""
    if len(closes) < ema_period + 2:
        return ARROW_FLAT
    e = ema(closes, ema_period)
    tail = [x for x in e if x is not None]
    if len(tail) < 2:
        return ARROW_FLAT
    delta = tail[-1] - tail[-2]
    eps = abs(closes[-1]) * eps_rel
    return arrow_from_delta(delta, eps=eps)

def lastbar_arrow(closes: list[float], eps_rel: float = 0.0005) -> str:
    if len(closes) < 2:
        return ARROW_FLAT
    delta = closes[-1] - closes[-2]
    eps = abs(closes[-1]) * eps_rel
    return arrow_from_delta(delta, eps=eps)

def trend_arrow(closes: list[float], tf: Timeframe, eps_rel: float = 0.0005) -> str:
    """
    Унифицированная стрелка:
    — знак наклона OLS-регрессии на последних N барах (N зависит от TF),
    — относительный порог по цене последнего бара.
    """
    if len(closes) < 3:
        return ARROW_FLAT
    win_by_tf = {"15m": 12, "1h": 10, "4h": 12, "1d": 10}
    n = win_by_tf.get(tf, 10)
    y = closes[-n:] if len(closes) >= n else closes[:]
    if len(y) < 3:
        return lastbar_arrow(closes, eps_rel=eps_rel)
    x = list(range(len(y)))
    sx = sum(x); sy = sum(y)
    sxx = sum(i * i for i in x); sxy = sum(i * j for i, j in zip(x, y))
    denom = len(y) * sxx - sx * sx
    if denom == 0:
        return lastbar_arrow(closes, eps_rel=eps_rel)
    slope = (len(y) * sxy - sx * sy) / denom
    base = abs(y[-1]) or 1.0
    eps = base * eps_rel
    return arrow_from_delta(slope, eps=eps)

# ---------------- risk score ----------------
def risk_score(tf, arrows, divs, grade_weights: dict[tuple[str, str, str], float] | None = None):
    """
    grade_weights: словарь {(metric, indicator, side) -> вес}, где side ∈ {"bullish","bearish"}.
    Весы задают ДОПОЛНИТЕЛЬНОЕ влияние подтверждённых дивергенций (без знака):
      soft = +0.5, hard = +1.0
    Знак (±) применяется здесь по стороне сигнала (bullish = +, bearish = −).
    """
    score = 0
    score += 2 if arrows.get("TOTAL3") == ARROW_UP else (-2 if arrows.get("TOTAL3") == ARROW_DOWN else 0)
    score += 1 if arrows.get("TOTAL2") == ARROW_UP else (-1 if arrows.get("TOTAL2") == ARROW_DOWN else 0)
    score += 1 if arrows.get("BTC")    == ARROW_UP else (-1 if arrows.get("BTC")    == ARROW_DOWN else 0)
    score += 2 if arrows.get("USDT.D") == ARROW_DOWN else (-2 if arrows.get("USDT.D") == ARROW_UP else 0)
    score += 2 if arrows.get("BTC.D")  == ARROW_DOWN else (-2 if arrows.get("BTC.D")  == ARROW_UP else 0)
    score += 1 if arrows.get("ETHBTC") == ARROW_UP else (-1 if arrows.get("ETHBTC") == ARROW_DOWN else 0)

    # --- вклад дивергенций ---
    div_adj = 0.0

    for d in divs:  # <— раньше было all_divs; исправлено
        # базовый вклад по импликации
        impl = (getattr(d, "implication", "") or "").lower()
        if "bullish" in impl:
            div_adj += 1.0
        elif "bearish" in impl:
            div_adj -= 1.0

        # дополнительный бонус за подтверждение (soft/hard)
        if grade_weights:
            # пытаемся вытащить metric и indicator из объекта дивергенции
            metric = getattr(d, "metric", None) or getattr(d, "name", None)
            indicator = getattr(d, "indicator", None)
            side = "bullish" if "bullish" in impl else ("bearish" if "bearish" in impl else None)

            if metric and indicator and side:
                w = float(grade_weights.get((str(metric), str(indicator), side), 0.0))
                # применяем знак по стороне
                div_adj += (+w if side == "bullish" else -w)

    # кэп по вкладу дивергенций (оставляем твой прежний диапазон)
    div_adj = max(-2.0, min(2.0, div_adj))
    score += div_adj
    # --- /вклад дивергенций ---

    def label_for(x: int | float) -> str:
        if x >= 5:  return "Сильный Risk-ON"
        if x >= 2:  return "Risk-ON"
        if x <= -5: return "Сильный Risk-OFF"
        if x <= -2: return "Risk-OFF"
        return "Нейтрально"

    label = label_for(score)

    # Если выше по коду у тебя действительно есть prev_label — оставляю логику как была.
    # (Если переменной нет, этот блок просто убери.)
    try:
        prev = prev_label  # noqa: F821  # внешняя переменная, если определена
    except NameError:
        prev = None

    if prev:
        if prev in ("Сильный Risk-ON", "Risk-ON") and score >= 1:
            label = "Risk-ON" if score >= 2 else "Нейтрально"
        if prev in ("Сильный Risk-OFF", "Risk-OFF") and score <= -1:
            label = "Risk-OFF" if score <= -2 else "Нейтрально"

    return score, label

# --- backward-compat wrapper for legacy callers (expects metric, tf, closes) ---
def trend_arrow_metric(metric: Metric, tf: Timeframe, closes: list[float], eps_rel: float = 0.0005) -> str:
    # metric не используется в расчёте; сохраняем сигнатуру ради совместимости
    return trend_arrow(closes, tf, eps_rel=eps_rel)
