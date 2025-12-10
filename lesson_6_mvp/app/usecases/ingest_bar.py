from __future__ import annotations
from ..infrastructure.db import DB

def ingest_bar(db: DB, metric: str, timeframe: str, ts: int, o: float, h: float, l: float, c: float, v: float | None = None):
    db.upsert_bar(metric, timeframe, ts, o, h, l, c, v)
