# app/lib/series.py
from __future__ import annotations
from typing import List, Tuple
import math

from ..infrastructure.db import DB

def get_closes(db: DB, metric: str, tf: str, n: int = 80) -> List[float]:
    """
    Последние n клоузов строго oldest→newest.

    Надёжность:
    - сортируем по ts (на случай разнородных источников);
    - убираем дубли по ts (берём последний встретившийся);
    - фильтруем None/NaN/нечисловые значения;
    - приводим к float.
    """
    rows: List[Tuple[int, float]] = db.last_n_closes(metric, tf, n)  # [(ts, c)]
    if not rows:
        return []

    # сортируем по ts
    rows.sort(key=lambda r: r[0])

    # дедуп по ts: если есть одинаковые ts, берём последний close
    dedup: dict[int, float] = {}
    for ts, c in rows:
        try:
            fc = float(c)
        except Exception:
            continue
        dedup[int(ts)] = fc

    if not dedup:
        return []

    # обратно в список и фильтруем не-конечные
    seq = [(ts, c) for ts, c in sorted(dedup.items(), key=lambda x: x[0]) if math.isfinite(c)]

    if not seq:
        return []

    # берём хвост из n элементов
    return [c for _, c in seq][-n:]


