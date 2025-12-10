# app/infrastructure/quota.py
import os, time, threading
from functools import wraps
from typing import Optional

MONTH_LIMIT = int(os.getenv("COINGECKO_MONTH_LIMIT", "10000"))
_state = {"month": None, "used": 0}
_lock = threading.Lock()
_db: Optional[object] = None  # БД для персистентности квоты


def init_quota_db(db):
    """Инициализировать БД для сохранения квоты."""
    global _db
    _db = db
    if _db:
        _init_quota_table(_db)


def _init_quota_table(db):
    """Инициализировать таблицу для хранения квоты."""
    cur = db.conn.cursor()
    cur.executescript("""
        CREATE TABLE IF NOT EXISTS coingecko_quota (
            month_id TEXT PRIMARY KEY,
            used INTEGER NOT NULL DEFAULT 0,
            updated_at_ms INTEGER NOT NULL
        );
    """)
    db.conn.commit()


def _load_quota_from_db():
    """Загрузить квоту из БД."""
    global _state
    if not _db:
        return
    
    try:
        cur = _db.conn.cursor()
        mid = _month_id()
        cur.execute(
            "SELECT used FROM coingecko_quota WHERE month_id = ?",
            (mid,)
        )
        row = cur.fetchone()
        if row:
            _state["month"] = mid
            _state["used"] = row[0]
    except Exception:
        pass  # Если БД недоступна, используем in-memory состояние


def _save_quota_to_db():
    """Сохранить квоту в БД."""
    if not _db:
        return
    
    try:
        cur = _db.conn.cursor()
        mid = _month_id()
        import time as time_module
        cur.execute("""
            INSERT OR REPLACE INTO coingecko_quota (month_id, used, updated_at_ms)
            VALUES (?, ?, ?)
        """, (mid, _state["used"], int(time_module.time() * 1000)))
        _db.conn.commit()
    except Exception:
        pass  # Если БД недоступна, продолжаем работу


def _month_id():
    t = time.gmtime()
    return f"{t.tm_year:04d}-{t.tm_mon:02d}"


def budget_guard(units: int = 1):
    """
    Месячный счётчик внешних запросов к CoinGecko.
    
    Если лимит превышен — бросает RuntimeError.
    Использовать ТОЛЬКО когда реально делается запрос к API (не при использовании кэша).
    
    Args:
        units: Количество единиц квоты для этого запроса (по умолчанию 1)
    """
    def deco(fn):
        @wraps(fn)
        def w(*a, **k):
            with _lock:
                mid = _month_id()
                
                # Загружаем состояние из БД при первом использовании или смене месяца
                if _state["month"] is None or _state["month"] != mid:
                    _load_quota_from_db()
                    if _state["month"] != mid:
                        _state["month"], _state["used"] = mid, 0
                
                # Проверяем лимит
                if _state["used"] + units > MONTH_LIMIT:
                    raise RuntimeError(
                        f"COINGECKO_BUDGET_EXCEEDED: использовано {_state['used']}/{MONTH_LIMIT} запросов в этом месяце"
                    )
                
                # Увеличиваем счётчик
                _state["used"] += units
                _save_quota_to_db()
            
            return fn(*a, **k)
        return w
    return deco


def get_budget():
    """
    Получить текущее состояние квоты.
    
    Returns:
        Tuple[dict, int]: (текущее состояние, лимит)
    """
    with _lock:
        mid = _month_id()
        if _state["month"] is None or _state["month"] != mid:
            _load_quota_from_db()
            if _state["month"] != mid:
                _state["month"], _state["used"] = mid, 0
        
        return {
            "month": _state["month"],
            "used": _state["used"],
            "limit": MONTH_LIMIT,
            "remaining": MONTH_LIMIT - _state["used"],
            "percentage": (_state["used"] / MONTH_LIMIT * 100) if MONTH_LIMIT > 0 else 0
        }, MONTH_LIMIT
