from __future__ import annotations

import sqlite3
import time
import datetime as _dt
from typing import List, Tuple, Optional

from zoneinfo import ZoneInfo  # используется в purge_past_events
from ..config import settings


# =========================================================
#  Вспомогательные утилиты
# =========================================================

def _init_connection_pragmas(conn: sqlite3.Connection) -> None:
    """Безопасные PRAGMA для снижения 'database is locked' и ускорения записи."""
    try:
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        conn.execute("PRAGMA busy_timeout=3000;")  # 3s ожидания при блокировке
    except Exception:
        pass


def _col_info(conn: sqlite3.Connection, table: str) -> dict[str, tuple[int, Optional[str], int]]:
    """
    Возвращает сведения о колонках: {name: (cid, dflt_value, notnull)}
    """
    info: dict[str, tuple[int, Optional[str], int]] = {}
    cur = conn.execute(f"PRAGMA table_info({table})")
    for cid, name, _type, notnull, dflt_value, _pk in cur.fetchall():
        info[name] = (cid, dflt_value, notnull)
    return info


def _has_col(conn: sqlite3.Connection, table: str, col: str) -> bool:
    cur = conn.execute(f"PRAGMA table_info({table})")
    return any(row[1] == col for row in cur.fetchall())


def _ensure_columns(conn: sqlite3.Connection) -> None:
    """
    Мягкая миграция: создаёт базовую таблицу и добавляет недостающие колонки.
    """
    with conn:
        # базовая таблица/индекс (минимальный набор колонок, чтобы не конфликтовать со старой схемой)
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts INTEGER NOT NULL,
                title TEXT NOT NULL
            );
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_events_ts ON events(ts)")

        cols = _col_info(conn, "events")

        # возможная старая колонка chat_id (иногда NOT NULL) — если её нет, можно добавить NULL
        if "chat_id" not in cols:
            try:
                conn.execute("ALTER TABLE events ADD COLUMN chat_id INTEGER;")
            except Exception:
                pass

        # автор, created_at и флаги уведомлений — все опциональные
        if "author_chat_id" not in cols:
            try:
                conn.execute("ALTER TABLE events ADD COLUMN author_chat_id INTEGER;")
            except Exception:
                pass

        if "created_at" not in cols:
            try:
                conn.execute("ALTER TABLE events ADD COLUMN created_at INTEGER;")
            except Exception:
                pass

        cols = _col_info(conn, "events")  # обновим после ALTER

        if "notified_24h_at" not in cols:
            try:
                conn.execute("ALTER TABLE events ADD COLUMN notified_24h_at INTEGER;")
            except Exception:
                pass

        if "notified_1h_at" not in cols:
            try:
                conn.execute("ALTER TABLE events ADD COLUMN notified_1h_at INTEGER;")
            except Exception:
                pass


def _conn() -> sqlite3.Connection:
    """Возвращает соединение и гарантирует схему/колонки/индексы."""
    path = settings.database_path
    conn = sqlite3.connect(path, check_same_thread=False)
    _init_connection_pragmas(conn)
    _ensure_columns(conn)
    return conn


# =========================================================
#  Публичный API (добавление/списки/очистка)
# =========================================================

def add_event(date_ts_ms: int, title: str, author_chat_id: int | None = None) -> int:
    """
    Добавляет событие, видимое всем.
    :return: id вставленной записи
    """
    title = (title or "").strip()
    if not title:
        raise ValueError("empty title")

    conn = _conn()
    cols = _col_info(conn, "events")
    has_chat = "chat_id" in cols
    has_author = "author_chat_id" in cols
    has_created = "created_at" in cols

    # значение для chat_id, если колонка есть (некоторые схемы требуют NOT NULL)
    chat_value = (author_chat_id if author_chat_id is not None else 0) if has_chat else None

    with conn:  # автокоммит
        if has_chat and has_author and has_created:
            cur = conn.execute(
                "INSERT INTO events(ts, title, chat_id, author_chat_id, created_at) VALUES(?, ?, ?, ?, ?)",
                (int(date_ts_ms), title, chat_value, author_chat_id, int(time.time() * 1000)),
            )
        elif has_chat and has_author and not has_created:
            cur = conn.execute(
                "INSERT INTO events(ts, title, chat_id, author_chat_id) VALUES(?, ?, ?, ?)",
                (int(date_ts_ms), title, chat_value, author_chat_id),
            )
        elif has_chat and not has_author and has_created:
            cur = conn.execute(
                "INSERT INTO events(ts, title, chat_id, created_at) VALUES(?, ?, ?, ?)",
                (int(date_ts_ms), title, chat_value, int(time.time() * 1000)),
            )
        elif has_chat and not has_author and not has_created:
            cur = conn.execute(
                "INSERT INTO events(ts, title, chat_id) VALUES(?, ?, ?)",
                (int(date_ts_ms), title, chat_value),
            )
        elif not has_chat and has_author and has_created:
            cur = conn.execute(
                "INSERT INTO events(ts, title, author_chat_id, created_at) VALUES(?, ?, ?, ?)",
                (int(date_ts_ms), title, author_chat_id, int(time.time() * 1000)),
            )
        elif not has_chat and has_author and not has_created:
            cur = conn.execute(
                "INSERT INTO events(ts, title, author_chat_id) VALUES(?, ? , ?)",
                (int(date_ts_ms), title, author_chat_id),
            )
        elif not has_chat and not has_author and has_created:
            cur = conn.execute(
                "INSERT INTO events(ts, title, created_at) VALUES(?, ? , ?)",
                (int(date_ts_ms), title, int(time.time() * 1000)),
            )
        else:
            # самая старая схема: только ts,title
            cur = conn.execute(
                "INSERT INTO events(ts, title) VALUES(?, ?)",
                (int(date_ts_ms), title),
            )

        return int(cur.lastrowid)


def list_all_events(limit: int = 200) -> List[Tuple[int, int, str]]:
    """
    Возвращает список ближайших событий, включая сегодняшние и будущие.
    Формат: (id, ts_ms, title). Включаем «вчерашние» (24h назад).
    """
    now_ms = int(time.time() * 1000)
    conn = _conn()
    cur = conn.cursor()
    try:
        cur.execute(
            "SELECT id, ts, title FROM events WHERE ts >= ? ORDER BY ts ASC LIMIT ?",
            (now_ms - 24 * 3600 * 1000, int(limit)),
        )
        return [(int(r[0]), int(r[1]), str(r[2])) for r in cur.fetchall()]
    finally:
        cur.close()


def purge_past_events() -> int:
    """
    Удаляет все события, которые уже прошли (ts < сегодня 00:00 лок. времени).
    Возвращает количество удалённых записей.
    """
    # пытаемся взять TZ из settings.tz или переменной окружения TZ
    try:
        tz = getattr(settings, "tz", None)
    except Exception:
        tz = None
    if tz is None:
        import os
        tzname = os.getenv("TZ")
        tz = ZoneInfo(tzname) if tzname else None

    now = _dt.datetime.now(tz) if tz else _dt.datetime.utcnow()
    start_today = _dt.datetime(now.year, now.month, now.day, tzinfo=tz)
    cutoff_ms = int(start_today.timestamp() * 1000)

    conn = _conn()
    with conn:
        cur = conn.execute("DELETE FROM events WHERE ts < ?", (cutoff_ms,))
        return cur.rowcount


# Совместимость со старым API (если где-то вызывалось)
def list_events(_chat_id: int) -> List[Tuple[int, int, str]]:
    """Deprecated: оставлено ради совместимости. Возвращает общий список."""
    return list_all_events()


# =========================================================
#  Напоминания: выборка «созревших» и отметка отправки
# =========================================================

def _now_ms() -> int:
    return int(time.time() * 1000)


def due_events(now_ms: int) -> List[Tuple[int, Optional[int], int, str, str]]:
    """
    Возвращает напоминания, которые «созрели» к отправке.
    Формат: (event_id, target_chat_id, ts_ms, title, kind), kind ∈ {"24h","1h"}.
    По умолчанию получатель — author_chat_id (если колонка есть).
    """
    conn = _conn()
    cur = conn.cursor()
    try:
        HOUR = 60 * 60 * 1000
        DAY = 24 * HOUR
        LEEWAY = 5 * 60 * 1000  # ±5 минут

        cols = _col_info(conn, "events")
        author_sel = "author_chat_id" if "author_chat_id" in cols else "NULL as author_chat_id"

        # 24 часа до события
        cur.execute(
            f"""
            SELECT id, {author_sel}, ts, title
            FROM events
            WHERE ts > ?
              AND ts - ? <= ?
              AND (notified_24h_at IS NULL)
            ORDER BY ts ASC
            """,
            (now_ms, now_ms, DAY + LEEWAY),
        )
        rows_24 = [
            (int(eid), (int(chat) if chat is not None else None), int(ts), str(title), "24h")
            for (eid, chat, ts, title) in cur.fetchall()
        ]

        # 1 час до события
        cur.execute(
            f"""
            SELECT id, {author_sel}, ts, title
            FROM events
            WHERE ts > ?
              AND ts - ? <= ?
              AND (notified_1h_at IS NULL)
            ORDER BY ts ASC
            """,
            (now_ms, now_ms, HOUR + LEEWAY),
        )
        rows_1 = [
            (int(eid), (int(chat) if chat is not None else None), int(ts), str(title), "1h")
            for (eid, chat, ts, title) in cur.fetchall()
        ]

        return rows_24 + rows_1
    finally:
        cur.close()


def mark_notified(event_id: int, kind: str) -> None:
    """Помечает событие как уведомлённое для окна (24h или 1h)."""
    col = "notified_24h_at" if kind == "24h" else "notified_1h_at"
    conn = _conn()
    with conn:
        conn.execute(f"UPDATE events SET {col}=? WHERE id=?", (_now_ms(), int(event_id)))


def del_event(_chat_id: int, event_id: int) -> int:
    conn = _conn()
    with conn:
        cur = conn.execute("DELETE FROM events WHERE id=?", (int(event_id),))
        return cur.rowcount
