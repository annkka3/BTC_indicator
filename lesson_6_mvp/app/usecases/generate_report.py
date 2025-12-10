# app/usecases/generate_report.py (visual text v2.2: fix TZ attr, avg divisor, indentation)
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Tuple, Any

from ..infrastructure.db import DB
from ..domain.models import Metric, Timeframe
from ..domain.services import (
    key_levels,
    indicator_divergences,
    pair_divergences,
    risk_score,
    trend_arrow,
    ARROW_UP, ARROW_DOWN, ARROW_FLAT,
)
from ..domain.divergence_detector import detect_divergences as detect_divergences_new, DivergenceSignal
from ..lib.series import get_closes


# --- кнопка «Все события» + общий хелпер для reply_markup ---
def events_keyboard() -> dict:
    """
    Inline-клавиатура Telegram со ссылкой на список событий.
    callback_data адаптируйте под ваш роутинг при необходимости.
    """
    return {
        "inline_keyboard": [[
            {"text": "🗓 Все события", "callback_data": "events:list_all"}
        ]]
    }
# --- /кнопка ---


def _now_hhmm() -> str:
    """Текущее время в HH:MM с учетом settings.tz (ZoneInfo) или переменной окружения TZ, иначе UTC."""
    try:
        from datetime import datetime
        from zoneinfo import ZoneInfo
        try:
            from ..config import settings  # optional
            tzobj = getattr(settings, "tz", None)  # в config это ZoneInfo
        except Exception:
            tzobj = None
        if tzobj is None:
            import os
            tzname = os.getenv("TZ")
            tzobj = ZoneInfo(tzname) if tzname else None
        now = datetime.now(tzobj) if tzobj else datetime.utcnow()
        return now.strftime("%H:%M")
    except Exception:
        return "--:--"


METRICS: Tuple[Metric, ...] = ("BTC", "ETHBTC", "USDT.D", "BTC.D", "TOTAL2", "TOTAL3")

# --------------- TF normalize ---------------
def _tf_key(tf: Any) -> str:
    if hasattr(tf, "value"):
        return str(getattr(tf, "value"))
    if hasattr(tf, "name"):
        n = str(getattr(tf, "name"))
        return {"M15": "15m", "H1": "1h", "H4": "4h", "D1": "1d"}.get(n, n)
    return str(tf)

# --------------- Denoise (anti-spike) ---------------
def _mad(vals: List[float]) -> float:
    if not vals:
        return 0.0
    s = sorted(vals)
    m = s[len(s) // 2]
    dev = sorted(abs(v - m) for v in vals)
    return dev[len(dev) // 2] or 1e-12

def _winsorize(vals: List[float], p: float = 0.995) -> List[float]:
    if not vals:
        return vals
    s = sorted(vals)
    lo = s[max(0, int((1 - p) * len(s)) - 1)]
    hi = s[min(len(s) - 1, int(p * len(s)))]
    return [min(max(v, lo), hi) for v in vals]

# --- momentum helpers for confirmation ---

def _rsi14(closes: List[float]) -> float | None:
    n = len(closes)
    period = 14
    if n < period + 1:
        return None
    gains = []
    losses = []
    for i in range(1, n):
        ch = closes[i] - closes[i-1]
        gains.append(max(ch, 0.0))
        losses.append(max(-ch, 0.0))
    # первые 14
    ag = sum(gains[:period]) / period
    al = sum(losses[:period]) / period
    # Wilder smoothing
    for i in range(period, len(gains)):
        ag = (ag * (period - 1) + gains[i]) / period
        al = (al * (period - 1) + losses[i]) / period
    if al == 0:
        return 100.0
    rs = ag / al
    return 100.0 - (100.0 / (1.0 + rs))

def _macd_fast_slow_signal(closes: List[float]) -> tuple[float | None, float | None]:
    """Возвращает (macd_line, signal_line) по (12,26,9). Нужны >= 26+9 баров для стабильности."""
    n = len(closes)
    f, s, sig = 12, 26, 9
    if n < s + sig:
        return None, None
    kf = 2 / (f + 1)
    ks = 2 / (s + 1)
    # EMA fast/slow
    ema_f = closes[0]
    ema_s = closes[0]
    for i in range(1, n):
        ema_f = closes[i] * kf + ema_f * (1 - kf)
        ema_s = closes[i] * ks + ema_s * (1 - ks)
    macd_line = ema_f - ema_s
    # для сигнальной лучше посчитать по всей серии macd, но достаточно итеративно добить последних 9
    # упростим: пересчитаем серию macd разом
    ema_f = closes[0]; ema_s = closes[0]
    macd_series = []
    for i in range(1, n):
        ema_f = closes[i] * kf + ema_f * (1 - kf)
        ema_s = closes[i] * ks + ema_s * (1 - ks)
        macd_series.append(ema_f - ema_s)
    ks9 = 2 / (sig + 1)
    ema_sig = macd_series[0]
    for i in range(1, len(macd_series)):
        ema_sig = macd_series[i] * ks9 + ema_sig * (1 - ks9)
    return macd_series[-1], ema_sig

def _maybe_confirm(db: DB, metric: Metric, tf: Timeframe, rows: list[tuple]) -> None:
    if not rows:
        return
    closes = [r[4] for r in rows]
    rsi = _rsi14(closes)
    macd_line, macd_signal = _macd_fast_slow_signal(closes)
    if rsi is None or macd_line is None or macd_signal is None:
        return
    macd_hist = macd_line - macd_signal
    last_ts = rows[-1][0]

    try:
        open_divs = db.list_open_divs(metric, tf)
    except Exception:
        return

    for (div_id, _ind, side, _impl, _rts, _rval, _status, grade) in open_divs:
        if side == "bullish":
            soft_ok = (rsi > 52.0) or (macd_line > 0.0 and macd_hist >= 0.0)
            hard_ok = (rsi > 52.0) and (macd_line > 0.0 and macd_hist >= 0.0)
        else:
            soft_ok = (rsi < 48.0) or (macd_line < 0.0 and macd_hist <= 0.0)
            hard_ok = (rsi < 48.0) and (macd_line < 0.0 and macd_hist <= 0.0)

        if hard_ok:
            db.confirm_hard_by_id(div_id, last_ts)
        elif soft_ok:
            db.confirm_soft_by_id(div_id, last_ts)


# --- persistence helpers for divergences ---

def _last_two_indices(flags: list[bool]) -> list[int]:
    idx = [i for i, f in enumerate(flags) if f]
    return idx[-2:] if len(idx) >= 2 else []

def _pivots_for_side(closes: List[float], highs: List[float], lows: List[float], side: str):
    """
    Возвращает индексы последних двух пивотов для нужной стороны и цену закрытия правого пивота.
    Пивот-хай: high[i] >= max(high[i-2:i]) и high[i] >= max(high[i+1:i+3])
    Пивот-лоу: low[i]  <= min(low[i-2:i])  и low[i]  <= min(low[i+1:i+3])
    Используем окно left=2,right=2 как в исходной идее.
    """
    n = len(closes)
    if n < 5:
        return None, None, None

    def last_two_high_pivots() -> List[int]:
        idx = []
        for i in range(2, n - 2):
            if highs[i] >= max(highs[i-2:i]) and highs[i] >= max(highs[i+1:i+3]):
                idx.append(i)
        return idx[-2:]

    def last_two_low_pivots() -> List[int]:
        idx = []
        for i in range(2, n - 2):
            if lows[i] <= min(lows[i-2:i]) and lows[i] <= min(lows[i+1:i+3]):
                idx.append(i)
        return idx[-2:]

    if side == "bearish":
        piv = last_two_high_pivots()
        if len(piv) == 2:
            l_idx, r_idx = piv[0], piv[1]
            return l_idx, r_idx, closes[r_idx]
    elif side == "bullish":
        piv = last_two_low_pivots()
        if len(piv) == 2:
            l_idx, r_idx = piv[0], piv[1]
            return l_idx, r_idx, closes[r_idx]

    return None, None, None

def _persist_divergences_new(db: DB, metric: Metric, tf: Timeframe, rows: list[tuple], div_signals: List[DivergenceSignal]):
    """
    Сохраняет дивергенции из нового детектора в БД.
    rows: [(ts,o,h,l,c,v)] oldest→newest
    """
    if not div_signals or not rows:
        return
    ts_series = [r[0] for r in rows]
    now_ts = ts_series[-1]

    for ds in div_signals:
        # Определяем implication из side и метрики
        if ds.side == "bullish":
            implication = "bullish_alts" if metric not in ("USDT.D", "BTC.D") else "bearish_alts"
        else:
            implication = "bearish_alts" if metric not in ("USDT.D", "BTC.D") else "bullish_alts"
        
        # Используем координаты из DivergenceSignal
        pivot_l_ts = ts_series[ds.price_idx_left] if ds.price_idx_left < len(ts_series) else None
        pivot_r_ts = ts_series[ds.price_idx_right] if ds.price_idx_right < len(ts_series) else None
        
        # Вычисляем score на основе strength
        score = 0.0
        if "(сильная)" in ds.strength:
            score = 1.0
        elif "(средняя)" in ds.strength:
            score = 0.5
        
        db.upsert_div(
            metric=metric, timeframe=tf, indicator=ds.indicator, side=ds.side,
            implication=implication, pivot_l_ts=pivot_l_ts,
            pivot_l_val=ds.price_val_left,
            pivot_r_ts=pivot_r_ts, pivot_r_val=ds.price_val_right,
            detected_ts=now_ts, score=score
        )

def _persist_divergences(db: DB, metric: Metric, tf: Timeframe, rows: list[tuple], divs):
    """
    rows: [(ts,o,h,l,c,v)] oldest→newest
    """
    if not divs or not rows:
        return
    ts_series = [r[0] for r in rows]
    highs = [r[2] for r in rows]
    lows  = [r[3] for r in rows]
    closes= [r[4] for r in rows]
    now_ts = ts_series[-1]

    for d in divs:
        # side из импликации для альтов не подходит — определяем из текста
        txt = d.text.lower()
        side = "bearish" if ("bear" in txt or "hh" in txt and "цена" in txt and "ниже" in txt) else "bullish"
        l_idx, r_idx, r_price = _pivots_for_side(closes, highs, lows, side)
        pivot_l_ts = ts_series[l_idx] if l_idx is not None else None
        pivot_r_ts = ts_series[r_idx] if r_idx is not None else None
        db.upsert_div(
            metric=metric, timeframe=tf, indicator=d.indicator, side=side,
            implication=d.implication, pivot_l_ts=pivot_l_ts,
            pivot_l_val=closes[l_idx] if l_idx is not None else None,
            pivot_r_ts=pivot_r_ts, pivot_r_val=r_price,
            detected_ts=now_ts, score=0.0
        )

def _invalidate_by_price(db: DB, metric: Metric, tf: Timeframe, rows: list[tuple]):
    """
    Отмена по правилу цены:
      - bearish: новый HH выше pivot_r_val
      - bullish: новый LL ниже pivot_r_val
    """
    if not rows:
        return
    last_h = rows[-1][2]
    last_l = rows[-1][3]
    last_ts= rows[-1][0]
    for (div_id, indicator, side, _impl, _r_ts, r_val, _status, _grade) in db.list_open_divs(metric, tf):
        if side == "bearish" and r_val is not None and last_h > r_val:
            db.invalidate_div_by_id(div_id, last_ts)
        if side == "bullish" and r_val is not None and last_l < r_val:
            db.invalidate_div_by_id(div_id, last_ts)


def _denoise(vals: List[float]) -> List[float]:
    if len(vals) < 5:
        return vals[:]
    s = sorted(vals)
    m = s[len(s) // 2]
    mad = _mad(vals)
    k = 3.5
    lo, hi = m - k * mad, m + k * mad
    clipped = [min(max(v, lo), hi) for v in vals]
    return _winsorize(clipped, 0.995)

# --------------- Helpers ---------------
def _fmt_levels(metric: Metric, levels: List[float]) -> str:
    if not levels:
        return "—"
    if metric in ("TOTAL2", "TOTAL3"):
        return " / ".join(f"{lv / 1e9:.1f}B" for lv in levels)
    if metric.endswith("D"):
        return " / ".join(f"{lv:.2f}%" for lv in levels)
    if metric == "ETHBTC":
        return " / ".join(f"{lv:.6f}" for lv in levels)
    return " / ".join(f"{lv:.2f}" for lv in levels)

def _arrows_for_tf_shift(db: DB, tf: Timeframe, shift: int = 1) -> Dict[Metric, str]:
    """Как _arrows_for_tf, но считает «как если бы» последние `shift` баров не существовали."""
    arrows: Dict[Metric, str] = {}
    for m in METRICS:
        closes = get_closes(db, m, tf, 100 + shift)  # oldest→newest
        if len(closes) > shift:
            closes = closes[:-shift]
        closes = _denoise(closes)
        arrows[m] = trend_arrow(closes, tf, eps_rel=0.0005)
    return arrows

def _pair_series_shift(db: DB, tf: Timeframe, n: int = 320, shift: int = 1) -> Dict[Metric, List[Tuple[int, float]]]:
    res: Dict[Metric, List[Tuple[int, float]]] = {}
    for m in METRICS:
        rows = sorted(db.last_n(m, tf, n + shift), key=lambda r: r[0])
        if shift and len(rows) > shift:
            rows = rows[:-shift]
        res[m] = [(ts, c) for (ts, _o, _h, _l, c, _v) in rows]
    return res

def _grade_weights_for_tf(db: DB, tf: Timeframe) -> dict[tuple[str, str, str], float]:
    """
    Строит словарь {(metric, indicator, side)->weight} для открытых (active+confirmed) дивергенций.
    Учитываем только confirmed: soft=+0.5, hard=+1.0.
    side ∈ {'bullish','bearish'} — определяется по implication.
    """
    weights: dict[tuple[str, str, str], float] = {}
    for m in METRICS:
        try:
            rows = db.list_open_divs(m, tf)  # (id, indicator, side, implication, pivot_r_ts, pivot_r_val, status, confirm_grade)
        except Exception:
            continue
        for (_id, indicator, side, implication, _rts, _rval, status, grade) in rows:
            if status != "confirmed":
                continue
            # вес по градации
            base = 1.0 if grade == "hard" else 0.5
            s = "bullish" if "bullish" in (implication or "").lower() else ("bearish" if "bearish" in (implication or "").lower() else None)
            if not s:
                continue
            key = (str(m), str(indicator), s)
            # на случай нескольких подтверждений одного типа — берём максимальный вес
            weights[key] = max(weights.get(key, 0.0), base)
    return weights


@dataclass
class TfCalc:
    score: float   # было: int
    label: str
    arrows: Dict[Metric, str]
    counts: Dict[Metric, Tuple[int, int]]
    details: List[str]

def _calc_for_tf_shift(db: DB, tf: Timeframe, shift: int = 1) -> TfCalc:
    arrows = _arrows_for_tf_shift(db, tf, shift=shift)
    details: List[str] = []
    counts: Dict[Metric, Tuple[int, int]] = {m: (0, 0) for m in METRICS}

    all_divs = []
    for m in METRICS:
        rows = sorted(db.last_n(m, tf, 320 + shift), key=lambda r: r[0])
        if shift and len(rows) > shift:
            rows = rows[:-shift]
        if not rows:
            continue
        highs = [r[2] for r in rows]
        lows = [r[3] for r in rows]
        closes = _denoise([r[4] for r in rows])
        vols = [r[5] for r in rows]
        
        # Используем новый детектор дивергенций
        div_signals = detect_divergences_new(m, tf, closes, highs, lows, vols, enabled_indicators=None)
        
        # Преобразуем DivergenceSignal в старый формат Divergence для совместимости
        from ..domain.models import Divergence
        divs = []
        for ds in div_signals:
            # Определяем implication из side
            if ds.side == "bullish":
                implication = "bullish_alts" if m not in ("USDT.D", "BTC.D") else "bearish_alts"
            else:
                implication = "bearish_alts" if m not in ("USDT.D", "BTC.D") else "bullish_alts"
            divs.append(Divergence(tf, m, ds.indicator, ds.text, implication))
        
        # Также используем старый детектор для обратной совместимости
        divs_old = indicator_divergences(m, tf, closes, vols)
        divs.extend(divs_old)
        
        _invalidate_by_price(db, m, tf, rows)
        _persist_divergences_new(db, m, tf, rows, div_signals)
        _persist_divergences(db, m, tf, rows, divs_old)  # Сохраняем старые для совместимости
        _maybe_confirm(db, m, tf, rows)

        try:
            for (_id, ind, side, _impl, _rts, _rval, status, grade) in db.list_open_divs(m, tf)[:3]:
                tag = "🟢 bull" if side == "bullish" else "🔴 bear"
                if status == 'confirmed':
                    gtxt = 'hard' if grade == 'hard' else 'soft'
                    details.append(f"{m}: {tag} ({ind}) — подтв. {gtxt} (до отмены)")
                else:
                    details.append(f"{m}: {tag} ({ind}) — активна (до отмены)")
        except Exception:
            pass

        all_divs.extend(divs)
        bull = sum(1 for d in divs if "bullish" in d.implication)
        bear = sum(1 for d in divs if "bearish" in d.implication)
        counts[m] = (bull, bear)

    pairs = pair_divergences(tf, _pair_series_shift(db, tf, 320, shift=shift))
    all_divs.extend(pairs)

    grade_weights = _grade_weights_for_tf(db, tf)
    score, label = risk_score(tf, arrows, all_divs, grade_weights=grade_weights)
    return TfCalc(score=score, label=label, arrows=arrows, counts=counts, details=details)

def _arrows_for_tf(db: DB, tf: Timeframe) -> Dict[Metric, str]:
    arrows: Dict[Metric, str] = {}
    for m in METRICS:
        closes = get_closes(db, m, tf, 100)  # oldest→newest
        closes = _denoise(closes)
        arrows[m] = trend_arrow(closes, tf, eps_rel=0.0005)
    return arrows

def _pair_series(db: DB, tf: Timeframe, n: int = 320) -> Dict[Metric, List[Tuple[int, float]]]:
    res: Dict[Metric, List[Tuple[int, float]]] = {}
    for m in METRICS:
        rows = db.last_n(m, tf, n)
        rows = sorted(rows, key=lambda r: r[0])
        res[m] = [(ts, c) for (ts, _o, _h, _l, c, _v) in rows]
    return res

# --------------- Core ---------------

def _overall_label_from_avg(avg: float) -> str:
    s = round(avg)
    return ("Сильный Risk-OFF" if s <= -3 else
            "Risk-OFF"         if s == -2 else
            "Слабый Risk-OFF"  if s == -1 else
            "Нейтрально"       if s == 0 else
            "Слабый Risk-ON"   if s == 1 else
            "Risk-ON"          if s == 2 else
            "Сильный Risk-ON")

def _table_lines(arrows_by_tf: Dict[str, Dict[Metric, str]]) -> List[str]:
    to_emoji = {ARROW_UP: "⬆️", ARROW_DOWN: "⬇️", ARROW_FLAT: "➡️"}
    lines = ["Metric    15m   1h   4h   1d"]
    for m in METRICS:
        a15 = arrows_by_tf.get("15m", {}).get(m, ARROW_FLAT)
        a1h = arrows_by_tf.get("1h", {}).get(m, ARROW_FLAT)
        a4h = arrows_by_tf.get("4h", {}).get(m, ARROW_FLAT)
        a1d = arrows_by_tf.get("1d", {}).get(m, ARROW_FLAT)
        lines.append(f"{m:<8}  {to_emoji[a15]:^3}  {to_emoji[a1h]:^3}  {to_emoji[a4h]:^3}  {to_emoji[a1d]:^3}")
    return lines

def _table_html(arrows_by_tf: Dict[str, Dict[Metric, str]]) -> str:
    return "<pre>" + "\n".join(_table_lines(arrows_by_tf)) + "</pre>"

def _label_emoji(label: str) -> str:
    s = label.lower()
    if "сильный" in s and "risk-off" in s: return "🔴🔴"
    if "risk-off" in s: return "🔴"
    if "нейтрал" in s: return "⚪️"
    if "сильный" in s and "risk-on" in s: return "🟢🟢"
    if "risk-on" in s: return "🟢"
    return "⚪️"

def _bucket_label(label: str) -> str:
    """Нормализует любые вариации лейбла режима в пять канонических корзин для группировки."""
    s = (label or "").lower()
    if "risk-on" in s:
        return "Сильный Risk-ON" if ("сильный" in s or "strong" in s or "++" in s) else "Risk-ON"
    if "risk-off" in s:
        return "Сильный Risk-OFF" if ("сильный" in s or "strong" in s or "++" in s) else "Risk-OFF"
    if "нейтрал" in s or "neutral" in s or s.strip() == "":
        return "Нейтрально"
    return "Нейтрально"

def _daily_sr_lines(db: DB) -> List[str]:
    tf = "1d"
    out = ["<b>Дневные уровни S/R (1d)</b>"]
    for m in METRICS:
        rows = sorted(db.last_n(m, tf, 800), key=lambda r: r[0])
        if not rows:
            continue
        highs = [r[2] for r in rows]
        lows  = [r[3] for r in rows]
        closes= [r[4] for r in rows]
        sup, res = key_levels(closes, highs, lows, 3)
        out.append(f"• <code>{m}</code> — S: {_fmt_levels(m, sup)} | R: {_fmt_levels(m, res)}")
    return out

def _tf_badge(name: str, label: str) -> str:
    return f"<code>{name}</code>: {label} {_label_emoji(label)}"

def _tips_block() -> str:
    return (
        "<i>Подсказка:</i> для широкой альта-сцены благоприятно: "
        "<code>TOTAL3</code>/<code>TOTAL2</code>/<code>BTC</code> ⬆ и <code>USDT.D</code>/<code>BTC.D</code> ⬇, "
        "подтверждённые bullish-дивергенциями и поддержками. Это не финсовет."
    )

def _shortcuts_block() -> str:
    return (
        "<b>Быстрые команды</b>\n"
        "• график: <code>/chart 15m|1h|4h|1d</code>\n"
        "• альбом: <code>/chart_album 15m|1h|4h|1d</code>\n"
        "• уровни: <code>/levels BTC 1h</code> • дивы: <code>/scan_divs 1h</code>\n"
        "• риск: <code>/risk_now</code> • корреляции: <code>/corr 1h</code>\n"
        "• опционы: <code>/options_btc</code> / <code>/options_eth</code>"
    )

# --------------- Public builders ---------------

def build_status_report(db: DB) -> str:
    order = ("15m", "1h", "4h", "1d")
    tfs = {k: _calc_for_tf(db, k) for k in order}
    denom = max(1, len(tfs))
    avg = sum(t.score for t in tfs.values()) / denom

    groups = {"Сильный Risk-ON": [], "Risk-ON": [], "Нейтрально": [], "Сильный Risk-OFF": [], "Risk-OFF": []}
    for k in order:
        b = _bucket_label(tfs[k].label)
        groups[b].append(k)

    parts: List[str] = []
    parts.append(f"<b>Альт-обзор ⏱ {_now_hhmm()}</b>")
    for key in ("Сильный Risk-ON", "Risk-ON", "Нейтрально", "Сильный Risk-OFF", "Risk-OFF"):
        tfl = groups.get(key) or []
        if not tfl:
            continue
        dot = _label_emoji(key)
        suffix = (f" • {', '.join(tfl)}" if tfl else "")
        parts.append(f"{key} {dot}{suffix}")
    parts.append(f"<b>Средний счёт: {avg:.1f}</b>")
    parts.append("")
    parts.append(_table_html({k: tfs[k].arrows for k in order}))
    parts.append("")
    parts.append(_tips_block())
    return "\n".join(parts)

def _calc_for_tf(db: DB, tf: Timeframe) -> TfCalc:
    arrows = _arrows_for_tf(db, tf)
    details: List[str] = []
    counts: Dict[Metric, Tuple[int, int]] = {m: (0, 0) for m in METRICS}

    all_divs = []
    for m in METRICS:
        rows = sorted(db.last_n(m, tf, 320), key=lambda r: r[0])
        if not rows:
            continue
        highs = [r[2] for r in rows]
        lows  = [r[3] for r in rows]
        closes= _denoise([r[4] for r in rows])
        vols  = [r[5] for r in rows]
        divs = indicator_divergences(m, tf, closes, vols)
        _invalidate_by_price(db, m, tf, rows)
        _persist_divergences(db, m, tf, rows, divs)
        _maybe_confirm(db, m, tf, rows)
        all_divs.extend(divs)
        bull = sum(1 for d in divs if "bullish" in d.implication)
        bear = sum(1 for d in divs if "bearish" in d.implication)
        counts[m] = (bull, bear)
        for d in divs[:3]:
            head = "🟢 Bullish" if "bullish" in d.implication else ("🔴 Bearish" if "bearish" in d.implication else "Div")
            details.append(f"{m}: {head} ({d.indicator}) — {d.text}")

        try:
            # открытые = active + confirmed, со статусом и confirm_grade
            if hasattr(db, "list_open_divs"):
                open_divs = db.list_open_divs(m, tf)
            else:
                # бэкап на случай старой версии: читаем active
                open_divs = db.list_active_divs(m, tf)

            # ожидаемые поля для новой версии:
            # (id, indicator, side, implication, pivot_r_ts, pivot_r_val, status, confirm_grade)
            for row in open_divs[:3]:
                # поддержим оба формата (старый и новый)
                if len(row) >= 8:
                    _id, ind, side, _impl, _rts, _rval, status, grade = row
                else:
                    _id, ind, side, _impl, _rts, _rval = row
                    status, grade = "active", None

                tag = "🟢 bull" if side == "bullish" else "🔴 bear"
                if status == "confirmed":
                    gtxt = "hard" if grade == "hard" else ("soft" if grade == "soft" else "")
                    suffix = f"подтв.{(' ' + gtxt) if gtxt else ''}"
                else:
                    suffix = "активна"
                details.append(f"{m}: {tag} ({ind}) — {suffix} (до отмены)")
        except Exception:
            # не роняем отчёт, если таблицы/метода ещё нет
            pass

    pairs = pair_divergences(tf, _pair_series(db, tf, 320))
    all_divs.extend(pairs)

    grade_weights = _grade_weights_for_tf(db, tf)
    score, label = risk_score(tf, arrows, all_divs, grade_weights=grade_weights)
    return TfCalc(score=score, label=label, arrows=arrows, counts=counts, details=details)

def build_full_report(db: DB) -> str:
    order = ("15m", "1h", "4h", "1d")
    tfs = {k: _calc_for_tf(db, k) for k in order}
    denom = max(1, len(tfs))
    avg = sum(t.score for t in tfs.values()) / denom

    groups = {"Сильный Risk-ON": [], "Risk-ON": [], "Нейтрально": [], "Сильный Risk-OFF": [], "Risk-OFF": []}
    for k in order:
        b = _bucket_label(tfs[k].label)
        groups[b].append(k)

    parts: List[str] = []
    parts.append(f"<b>Альт-обзор ⏱ {_now_hhmm()} (полный)</b>")
    for key in ("Сильный Risk-ON", "Risk-ON", "Нейтрально", "Сильный Risk-OFF", "Risk-OFF"):
        tfl = groups.get(key) or []
        if not tfl:
            continue
        dot = _label_emoji(key)
        suffix = (f" • {', '.join(tfl)}" if tfl else "")
        parts.append(f"{key} {dot}{suffix}")
    parts.append(f"<b>Средний счёт: {avg:.1f}</b>")
    parts.append("")
    parts.append(_table_html({k: tfs[k].arrows for k in order}))
    parts.append("")

    for k in order:
        if tfs[k].details:
            parts.append(f"<b>{k}</b>: {tfs[k].label} (счёт {tfs[k].score:+.1f})")
            parts.extend("• " + d for d in tfs[k].details[:6])

    parts.append("")
    parts.extend(_daily_sr_lines(db))
    parts.append("")
    parts.append(_tips_block())

    # Изменения за последний час (сравнение с «снимком» на 1 бар раньше)
    parts.append("")
    diffs: List[str] = []
    for k in order:
        prev = _calc_for_tf_shift(db, k, shift=1)
        cur = tfs[k]
        if prev.label != cur.label:
            diffs.append(f"• {k}: {prev.label} → {cur.label} (счёт {prev.score:+.1f} → {cur.score:+.1f})")
        elif prev.score != cur.score:
            diffs.append(f"• {k}: счёт {prev.score:+.1f} → {cur.score:+.1f}")
    if diffs:
        diffs.append(f"• {k}: {prev.label} → {cur.label} (счёт {prev.score:+.1f} → {cur.score:+.1f})")
        diffs.append(f"• {k}: счёт {prev.score:+.1f} → {cur.score:+.1f}")

    return "\n".join(parts)


# --- UI-обёртки: тот же текст + inline-кнопка «Все события» ---
def build_status_report_ui(db: DB) -> tuple[str, dict]:
    return build_status_report(db), events_keyboard()

def build_full_report_ui(db: DB) -> tuple[str, dict]:
    return build_full_report(db), events_keyboard()

