# app/visual/digest.py (visual v4.2: robust denoise fallback, white bg, safer width)
from __future__ import annotations
import io
from typing import Tuple, List, Any, Dict
from datetime import datetime, timezone

import numpy as np
# Ленивая загрузка matplotlib для ускорения старта приложения
# matplotlib будет загружен только при вызове функций генерации графиков

from ..infrastructure.db import DB
from ..domain.models import Metric, Timeframe
from ..domain.services import key_levels, trend_arrow

# --- попытка взять внешний денойз; иначе используем локальный ---
try:
    from ..lib.filters import denoise_mad as _ext_denoise  # optional
except Exception:
    _ext_denoise = None  # type: ignore


def _apply_denoise(vals: List[float]) -> List[float]:
    if _ext_denoise is not None:
        try:
            return _ext_denoise(vals)
        except Exception:
            pass
    return _denoise(vals)


METRICS: Tuple[Metric, ...] = ("BTC", "ETHBTC", "USDT.D", "BTC.D", "TOTAL2", "TOTAL3")

TITLE_MAP = {
    "BTC": "BTCUSDT",
    "ETHBTC": "ETH/BTC",
    "USDT.D": "USDT Dominance",
    "BTC.D": "BTC Dominance",
    "TOTAL2": "TOTAL2 (Alt mcap ex-BTC)",
    "TOTAL3": "TOTAL3 (Alt mcap ex-BTC/ETH)",
}

def _tf_key(tf: Any) -> str:
    if hasattr(tf, "value"):
        return str(getattr(tf, "value"))
    if hasattr(tf, "name"):
        n = str(getattr(tf, "name"))
        return {"M15":"15m","H1":"1h","H4":"4h","D1":"1d"}.get(n, n)
    return str(tf)

def _last_n(db: DB, metric: Metric, tf: Timeframe, n: int):
    rows = db.last_n(metric, tf, n)
    rows = sorted(rows, key=lambda r: r[0])
    return rows[-n:]

def _mad(vals: List[float]) -> float:
    if not vals:
        return 0.0
    s = sorted(vals)
    m = s[len(s)//2]
    dev = sorted(abs(v-m) for v in vals)
    return dev[len(dev)//2] or 1e-12

def _denoise(vals: List[float]) -> List[float]:
    if len(vals) < 5:
        return vals[:]
    s = sorted(vals)
    m = s[len(s)//2]
    mad = _mad(vals)
    k = 3.5
    lo, hi = m - k*mad, m + k*mad
    return [min(max(v, lo), hi) for v in vals]

def _dedup_levels(levels: List[float], tol_rel: float = 0.002) -> List[float]:
    if not levels:
        return []
    lv = sorted(levels)
    out = [lv[0]]
    for v in lv[1:]:
        if abs(v - out[-1]) > tol_rel * max(1.0, abs(out[-1])):
            out.append(v)
    return out

def _dedup_bars(rows: List[tuple]) -> List[tuple]:
    """Склеиваем бары с одинаковым timestamp (в мс).
       Берём последний по времени бар, high/low агрегируем экстремумами, open/close из последнего.
    """
    if not rows:
        return []
    acc: Dict[int, list] = {}
    for ts, o, h, l, c, v in rows:
        cur = acc.get(ts)
        if cur is None:
            acc[ts] = [o, h, l, c, v]
        else:
            o0, h0, l0, _c0, _v0 = cur
            acc[ts] = [o0, max(h0, h), min(l0, l), c, v]
    out = [(ts, *vals) for ts, vals in acc.items()]
    out.sort(key=lambda r: r[0])
    return out

def _panel(ax, rows, metric: Metric, tf: Timeframe):
    # Ленивая загрузка matplotlib
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.dates as mdates
    from mplfinance.original_flavor import candlestick_ohlc
    
    ax.cla()  # reset от предыдущего состояния
    ax.set_facecolor("white")
    if not rows:
        ax.set_title(f"{TITLE_MAP.get(metric, metric)} • {_tf_key(tf)} • нет данных", fontsize=9)
        ax.axis("off")
        return None

    rows = _dedup_bars(rows)

    ohlc = []
    highs, lows, closes = [], [], []
    xs = []
    for ts, o, h, l, c, _ in rows:
        dt = datetime.fromtimestamp(ts / 1000.0, tz=timezone.utc)
        md = mdates.date2num(dt)
        xs.append(md)
        ohlc.append((md, o, h, l, c))
        highs.append(h); lows.append(l); closes.append(c)

    # Ширина свечи: 60% от медианного шага по X (устойчиво к выбросам/дубликатам)
    if len(xs) >= 3:
        steps = np.diff(xs)
        steps = steps[steps > 0]
        step = float(np.median(steps)) if steps.size else 0.0
        width = step * 0.6 if step > 0 else 0.4
    else:
        width = 0.4

    # Совместимость со старым mplfinance: без аргумента linewidth
    candlestick_ohlc(ax, ohlc, width=width, colorup="green", colordown="red", alpha=0.9)

    # robust ylim
    arr_all = np.array(highs + lows, dtype=float)
    q_low  = float(np.nanquantile(arr_all, 0.005))
    q_high = float(np.nanquantile(arr_all, 0.995))
    if not np.isfinite(q_low) or not np.isfinite(q_high) or q_high <= q_low:
        q_low, q_high = (min(lows), max(highs)) if lows and highs else (0.0, 1.0)
    pad = (q_high - q_low) * 0.08 or (abs(q_high) * 0.01 + 1e-9)
    ax.set_ylim(q_low - pad, q_high + pad)

    # S/R уровни (+ dedup)
    sup, res = key_levels(closes, highs, lows, 3)
    sup = _dedup_levels(sup)
    res = _dedup_levels(res)

    def fmt(v: float) -> str:
        if metric in ("TOTAL2", "TOTAL3"):
            return f"{v/1e9:.1f}B"
        if metric.endswith("D"):
            return f"{v:.2f}%"
        if metric == "ETHBTC":
            return f"{v:.6f}"
        return f"{v:.2f}"

    for lv in sup:
        ax.axhline(lv, linestyle="--", linewidth=0.6, alpha=0.6)
    for lv in res:
        ax.axhline(lv, linestyle="--", linewidth=0.6, alpha=0.6)

    arr = trend_arrow(_apply_denoise(closes), tf, eps_rel=0.0005)
    arr_map = {"⬆":"⬆️","⬇":"⬇️","→":"➡️"}
    ax.set_title(f"{TITLE_MAP.get(metric, metric)} • {_tf_key(tf)} {arr_map.get(arr, '➡️')}", fontsize=10)

    # Ленивая загрузка matplotlib
    import matplotlib.dates as mdates
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%b\n%d"))
    ax.grid(True, which="major", alpha=0.15)
    ax.tick_params(axis="x", labelsize=8)
    ax.tick_params(axis="y", labelsize=8)

    txt = f"S: {', '.join(fmt(x) for x in sup) if sup else '—'}   |   R: {', '.join(fmt(x) for x in res) if res else '—'}"
    ax.text(0.01, -0.18, txt, transform=ax.transAxes, fontsize=8)

    return rows[-1][0]

def render_digest(db: DB, tf: Timeframe, *, n_bars: int = 120) -> bytes:
    """
    Рендерит digest график с кэшированием и мониторингом производительности.
    Кэшируется на 60 секунд для ускорения повторных запросов.
    Использует ленивую загрузку matplotlib для ускорения старта приложения.
    """
    from ...utils.performance import PerformanceMonitor
    from ...infrastructure.cache import get_cache, set_cache
    
    with PerformanceMonitor("render_digest"):
        # Проверяем кэш
        cache_key = f"digest_{tf}_{n_bars}"
        cached_result = get_cache("render_digest", cache_key, ttl=60)
        if cached_result is not None:
            return cached_result
        
        # Ленивая загрузка matplotlib
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        
        fig, axes = plt.subplots(3, 2, figsize=(12, 9), dpi=140, facecolor="white")
        axes = axes.flatten()

        last_ts_any = None
        for i, metric in enumerate(METRICS):
            rows = _last_n(db, metric, tf, n_bars)
            last_ts_any = _panel(axes[i], rows, metric, tf) or last_ts_any

        for j in range(len(METRICS), 6):
            axes[j].axis("off")

        if last_ts_any:
            dt = datetime.fromtimestamp(last_ts_any / 1000.0, tz=timezone.utc)
            fig.text(0.98, 0.02, dt.strftime("%Y-%b-%d %H:%M UTC"), ha="right", va="bottom", fontsize=9, alpha=0.8)

        bio = io.BytesIO()
        fig.tight_layout()
        fig.savefig(bio, format="png", bbox_inches="tight")
        plt.close(fig)
        bio.seek(0)
        result = bio.read()
        
        # Сохраняем в кэш
        set_cache("render_digest", cache_key, result)
        return result

def render_digest_panels(db: DB, tf: Timeframe, *, n_bars: int = 120) -> List[Tuple[str, bytes]]:
    # Ленивая загрузка matplotlib
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    
    out: List[Tuple[str, bytes]] = []
    for metric in METRICS:
        rows = _last_n(db, metric, tf, n_bars)
        fig, ax = plt.subplots(figsize=(7, 3.4), dpi=140, facecolor="white")
        _panel(ax, rows, metric, tf)
        plt.tight_layout()
        bio = io.BytesIO()
        fig.savefig(bio, format="png", bbox_inches="tight")
        plt.close(fig)
        bio.seek(0)
        out.append((metric, bio.read()))
    return out
