# app/infrastructure/db.py
from __future__ import annotations
import os
import sqlite3
from typing import Tuple, Iterable, Dict, Iterator, Optional, List, Any
from contextlib import contextmanager
from datetime import datetime
from functools import lru_cache

from ..utils.time import ensure_path
from ..config import settings
from .cache import get_cache, set_cache
from ..utils.performance import measure_time
import time

RowBars = Tuple[int, float, float, float, float, float | None]  # ts,o,h,l,c,v
RowClose = Tuple[int, float]                                    # ts,c

class DB:
    def __init__(self, path: str | None = None):
        self.path = path or settings.database_path
        ensure_path(self.path)
        # isolation_level=None => явный контроль транзакций (BEGIN/COMMIT),
        # check_same_thread=False — допускаем вызовы из разных потоков
        self.conn = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None)
        self.conn.row_factory = sqlite3.Row
        self._setup()
        self._init()

    def _setup(self):
        # устойчивые настройки для write-heavy небольшой БД
        cur = self.conn.cursor()
        # journal_mode настраиваем через переменную окружения (WAL по умолчанию)
        mode = os.getenv("SQLITE_JOURNAL_MODE", "WAL")
        cur.execute(f"PRAGMA journal_mode={mode};")
        cur.execute("PRAGMA synchronous=NORMAL;")
        cur.execute("PRAGMA busy_timeout=5000;")        # подождём до 5с при блокировке
        cur.execute("PRAGMA temp_store=MEMORY;")
        cur.execute("PRAGMA foreign_keys=ON;")
        cur.execute("PRAGMA wal_autocheckpoint=1000;")  # чекпойнт каждые ~1000 страниц
        self.conn.commit()

    def _init(self):
        cur = self.conn.cursor()
        cur.executescript(
            """
            CREATE TABLE IF NOT EXISTS bars (
                metric TEXT NOT NULL,
                timeframe TEXT NOT NULL,
                ts INTEGER NOT NULL, -- unix ms close time
                o REAL NOT NULL,
                h REAL NOT NULL,
                l REAL NOT NULL,
                c REAL NOT NULL,
                v REAL,
                PRIMARY KEY (metric, timeframe, ts)
            );

            -- подписки на часовые/периодические отчёты (как было)
            CREATE TABLE IF NOT EXISTS subs (
                chat_id INTEGER PRIMARY KEY
            );

            -- индивидуальные настройки пользователя/чата
            CREATE TABLE IF NOT EXISTS user_settings(
                user_id INTEGER PRIMARY KEY,
                vs_currency TEXT DEFAULT 'usd',
                bubbles_count INTEGER DEFAULT 50,
                bubbles_hide_stables INTEGER DEFAULT 1,
                bubbles_seed INTEGER DEFAULT 42,
                bubbles_size_mode TEXT DEFAULT 'percent',  -- 'percent', 'cap', 'volume_share', 'volume_24h'
                bubbles_top INTEGER DEFAULT 500,           -- 100, 200, 300, 400, 500
                bubbles_tf TEXT DEFAULT '1d',              -- '15m', '1h', '1d'
                daily_digest INTEGER DEFAULT 0,   -- 0/1
                daily_hour INTEGER DEFAULT 9      -- локальный час рассылки
            );
            
            -- активные/исторические дивергенции
            CREATE TABLE IF NOT EXISTS divs (
                id INTEGER PRIMARY KEY,
                metric TEXT NOT NULL,              -- BTC / TOTAL3 / ...
                timeframe TEXT NOT NULL,           -- 15m / 1h / 4h / 1d
                indicator TEXT NOT NULL,           -- RSI / MACD / VOLUME / PAIR
                side TEXT NOT NULL,                -- bullish / bearish
                implication TEXT NOT NULL,         -- bullish_alts / bearish_alts / neutral
                pivot_l_ts INTEGER,                -- ts левого свинга (ms)
                pivot_l_val REAL,
                pivot_r_ts INTEGER,                -- ts правого свинга (ms)
                pivot_r_val REAL,
                detected_ts INTEGER NOT NULL,      -- когда нашли (ms)
                status TEXT NOT NULL DEFAULT 'active',  -- active / confirmed / invalid
                confirm_ts INTEGER,                -- когда подтвердили (ms)
                confirm_grade TEXT CHECK(confirm_grade IN ('soft','hard')),
                invalid_ts INTEGER,                -- когда отменили (ms)
                score REAL DEFAULT 0.0,            -- качество (опц.)
                uniq TEXT UNIQUE                   -- idempotency ключ
            );
            
            -- сделки с бирж для TWAP анализа
            CREATE TABLE IF NOT EXISTS trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,              -- BTCUSDT, ETHUSDT и т.д.
                exchange TEXT NOT NULL,            -- Binance, Bybit, OKX, Gate
                time INTEGER NOT NULL,            -- timestamp сделки (ms)
                price REAL NOT NULL,
                qty REAL NOT NULL,
                is_buyer INTEGER NOT NULL,        -- 0 = продажа, 1 = покупка
                collected_at INTEGER NOT NULL,      -- когда собрали данные (ms)
                UNIQUE(symbol, exchange, time, price, qty)  -- дедупликация
            );
            """
        )
        cur.execute("PRAGMA table_info('divs')")
        _cols = [r[1] for r in cur.fetchall()]
        if 'confirm_grade' not in _cols:
            cur.execute("ALTER TABLE divs ADD COLUMN confirm_grade TEXT CHECK(confirm_grade IN ('soft','hard'))")

        # Миграция для user_settings - добавление новых колонок для настроек пузырьков
        cur.execute("PRAGMA table_info('user_settings')")
        _user_cols = [r[1] for r in cur.fetchall()]
        if 'bubbles_size_mode' not in _user_cols:
            cur.execute("ALTER TABLE user_settings ADD COLUMN bubbles_size_mode TEXT DEFAULT 'percent'")
        if 'bubbles_top' not in _user_cols:
            cur.execute("ALTER TABLE user_settings ADD COLUMN bubbles_top INTEGER DEFAULT 500")
        if 'bubbles_tf' not in _user_cols:
            cur.execute("ALTER TABLE user_settings ADD COLUMN bubbles_tf TEXT DEFAULT '1d'")
        # Добавляем колонку для настроек графиков (храним как JSON)
        if 'chart_settings' not in _user_cols:
            cur.execute("ALTER TABLE user_settings ADD COLUMN chart_settings TEXT")

        # Индекс под WHERE metric=? AND timeframe=? ORDER BY ts DESC
        cur.execute("CREATE INDEX IF NOT EXISTS idx_bars_mtf_ts ON bars(metric, timeframe, ts DESC)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_divs_active ON divs(status, timeframe, metric)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_divs_detected ON divs(detected_ts DESC)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_divs_status ON divs(status, confirm_grade)")
        
        # Индексы для trades
        cur.execute("CREATE INDEX IF NOT EXISTS idx_trades_symbol_time ON trades(symbol, time DESC)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_trades_exchange_time ON trades(exchange, time DESC)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_trades_collected_at ON trades(collected_at DESC)")

        self.conn.commit()

    # ---------- housekeeping ----------

    def close(self):
        try:
            self.conn.close()
        except Exception:
            pass

    @contextmanager
    def atomic(self):
        """BEGIN IMMEDIATE … COMMIT для групповых операций (блокирует на запись)."""
        cur = self.conn.cursor()
        try:
            cur.execute("BEGIN IMMEDIATE;")
            yield
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise

    def purge_old_bars(self, retention_by_tf: Dict[str, int]):
        """
        Удаляет старые бары по таймфреймам.
        retention_by_tf: {'15m': cutoff_ts_ms, '1h': cutoff_ts_ms, ...}
        """
        with self.atomic():
            for tf, cutoff in (retention_by_tf or {}).items():
                self.conn.execute(
                    "DELETE FROM bars WHERE timeframe=? AND ts<?",
                    (tf, int(cutoff))
                )

    # -------- subscriptions (как было) --------

    def add_sub(self, chat_id: int):
        self.conn.execute(
            "INSERT OR IGNORE INTO subs(chat_id) VALUES(?)",
            (chat_id,)
        )
        if not self.conn.in_transaction:
            self.conn.commit()

    def remove_sub(self, chat_id: int):
        self.conn.execute(
            "DELETE FROM subs WHERE chat_id=?",
            (chat_id,)
        )
        if not self.conn.in_transaction:
            self.conn.commit()

    def list_subs(self) -> list[int]:
        cur = self.conn.cursor()
        cur.execute("SELECT chat_id FROM subs")
        return [int(r[0]) for r in cur.fetchall()]

    # -------- user settings (новое) --------

    def _ensure_user_row(self, user_id: int):
        self.conn.execute("INSERT OR IGNORE INTO user_settings(user_id) VALUES(?)", (user_id,))
        if not self.conn.in_transaction:
            self.conn.commit()

    def get_user_settings(self, user_id: int) -> Tuple[str, int, int, int, int, int, str, int, str]:
        """
        Возвращает (vs_currency, bubbles_count, bubbles_hide_stables, bubbles_seed, daily_digest, daily_hour,
                    bubbles_size_mode, bubbles_top, bubbles_tf)
        """
        self._ensure_user_row(user_id)
        cur = self.conn.cursor()
        cur.execute(
            "SELECT vs_currency,bubbles_count,bubbles_hide_stables,bubbles_seed,daily_digest,daily_hour,"
            "bubbles_size_mode,bubbles_top,bubbles_tf "
            "FROM user_settings WHERE user_id=?",
            (user_id,)
        )
        row = cur.fetchone()
        if not row:
            # дефолты, если что-то пошло не так
            return ("usd", 50, 1, 42, 0, 9, "percent", 500, "1d")
        # Для новых колонок используем проверку на None (могут быть NULL для старых записей)
        size_mode = row["bubbles_size_mode"] if row["bubbles_size_mode"] is not None else "percent"
        top = row["bubbles_top"] if row["bubbles_top"] is not None else 500
        tf_setting = row["bubbles_tf"] if row["bubbles_tf"] is not None else "1d"
        return (
            str(row["vs_currency"]),
            int(row["bubbles_count"]),
            int(row["bubbles_hide_stables"]),
            int(row["bubbles_seed"]),
            int(row["daily_digest"]),
            int(row["daily_hour"]),
            str(size_mode),
            int(top),
            str(tf_setting),
        )

    def set_user_settings(self, user_id: int, **kwargs):
        """
        Обновляет произвольный набор колонок user_settings.
        Допустимые ключи: vs_currency, bubbles_count, bubbles_hide_stables, bubbles_seed, daily_digest, daily_hour,
                          bubbles_size_mode, bubbles_top, bubbles_tf
        """
        if not kwargs:
            return
        allowed = {
            "vs_currency", "bubbles_count", "bubbles_hide_stables", "bubbles_seed", 
            "daily_digest", "daily_hour", "bubbles_size_mode", "bubbles_top", "bubbles_tf"
        }
        upd = {k: v for k, v in kwargs.items() if k in allowed}
        if not upd:
            return
        self._ensure_user_row(user_id)
        keys = ",".join([f"{k}=?" for k in upd.keys()])
        vals = list(upd.values()) + [user_id]
        self.conn.execute(f"UPDATE user_settings SET {keys} WHERE user_id=?", vals)
        if not self.conn.in_transaction:
            self.conn.commit()

    def list_daily_users(self, hour: int) -> List[int]:
        """
        Список user_id, подписанных на ежедневный дайджест в указанный час.
        """
        cur = self.conn.cursor()
        cur.execute(
            "SELECT user_id FROM user_settings WHERE daily_digest=1 AND daily_hour=?",
            (int(hour),)
        )
        return [int(r[0]) for r in cur.fetchall()]
    
    def get_chart_settings(self, user_id: int) -> Optional[Dict]:
        """
        Получить настройки графиков для пользователя.
        Возвращает словарь с настройками или None, если настройки не сохранены.
        """
        self._ensure_user_row(user_id)
        cur = self.conn.cursor()
        cur.execute(
            "SELECT chart_settings FROM user_settings WHERE user_id=?",
            (user_id,)
        )
        row = cur.fetchone()
        if row and row[0]:
            try:
                import json
                return json.loads(row[0])
            except (json.JSONDecodeError, TypeError):
                return None
        return None
    
    def save_chart_settings(self, user_id: int, settings: Dict) -> None:
        """
        Сохранить настройки графиков для пользователя.
        settings - словарь с настройками графика.
        """
        self._ensure_user_row(user_id)
        import json
        try:
            settings_json = json.dumps(settings)
            cur = self.conn.cursor()
            cur.execute(
                "UPDATE user_settings SET chart_settings=? WHERE user_id=?",
                (settings_json, user_id)
            )
            if not self.conn.in_transaction:
                self.conn.commit()
        except Exception as e:
            import logging
            logger = logging.getLogger("alt_forecast.db")
            logger.exception("Error saving chart settings: %s", e)

    # -------- bars I/O --------

    def upsert_bar(
        self, metric: str, timeframe: str, ts_ms: int,
        o: float, h: float, l: float, c: float, v: float | None = None
    ):
        self.conn.execute(
            "INSERT OR REPLACE INTO bars(metric,timeframe,ts,o,h,l,c,v) VALUES(?,?,?,?,?,?,?,?)",
            (metric, timeframe, int(ts_ms), float(o), float(h), float(l), float(c),
             (None if v is None else float(v)))
        )
        # Коммитим только если не в транзакции (иначе преждевременный commit ломает батч)
        if not self.conn.in_transaction:
            self.conn.commit()

    def upsert_many_bars(self, rows: Iterable[Tuple[str, str, int, float, float, float, float, Optional[float]]]):
        """
        Быстрый батч-апсерт. rows: iterable of (metric, timeframe, ts_ms, o, h, l, c, v)
        Используй внутри self.atomic() при больших пачках для максимальной скорости.
        """
        self.conn.executemany(
            "INSERT OR REPLACE INTO bars(metric,timeframe,ts,o,h,l,c,v) VALUES(?,?,?,?,?,?,?,?)",
            (
                (m, tf, int(ts), float(o), float(h), float(l), float(c),
                 (None if v is None else float(v)))
                for m, tf, ts, o, h, l, c, v in rows
            )
        )
        if not self.conn.in_transaction:
            self.conn.commit()

    # ---- helpers to convert rows ----

    @staticmethod
    def _row_to_bars_tuple(r: sqlite3.Row) -> RowBars:
        return (
            int(r["ts"]),
            float(r["o"]),
            float(r["h"]),
            float(r["l"]),
            float(r["c"]),
            (None if r["v"] is None else float(r["v"]))
        )

    @staticmethod
    def _row_to_close_tuple(r: sqlite3.Row) -> RowClose:
        return (int(r["ts"]), float(r["c"]))

    # ---- single-metric readers (ASC order) ----

    @measure_time
    def last_n(self, metric: str, timeframe: str, n: int) -> List[RowBars]:
        """
        Возвращает последние n баров в порядке oldest→newest.
        Кэшируется на 30 секунд для часто используемых запросов.
        """
        # Используем кэш с ключом на основе параметров
        cache_key = f"{metric}_{timeframe}_{n}"
        cached_result = get_cache("DB.last_n", cache_key, ttl=30)
        if cached_result is not None:
            return cached_result
        
        cur = self.conn.cursor()
        cur.execute(
            "SELECT ts,o,h,l,c,v FROM bars WHERE metric=? AND timeframe=? ORDER BY ts DESC LIMIT ?",
            (metric, timeframe, int(n))
        )
        rows = cur.fetchall()
        rows.reverse()  # ASC по времени
        result = [self._row_to_bars_tuple(r) for r in rows]
        
        # Сохраняем в кэш
        set_cache("DB.last_n", cache_key, result)
        return result

    def last_n_closes(self, metric: str, timeframe: str, n: int) -> List[RowClose]:
        """
        Возвращает последние n (ts, close) в порядке oldest→newest.
        Кэшируется на 30 секунд для часто используемых запросов.
        """
        # Используем кэш с ключом на основе параметров
        cache_key = f"{metric}_{timeframe}_{n}"
        cached_result = get_cache("DB.last_n_closes", cache_key, ttl=30)
        if cached_result is not None:
            return cached_result
        
        cur = self.conn.cursor()
        cur.execute(
            "SELECT ts, c FROM bars WHERE metric=? AND timeframe=? ORDER BY ts DESC LIMIT ?",
            (metric, timeframe, int(n))
        )
        rows = cur.fetchall()
        rows.reverse()
        result = [self._row_to_close_tuple(r) for r in rows]
        
        # Сохраняем в кэш
        set_cache("DB.last_n_closes", cache_key, result)
        return result

    def iter_bars_between(
        self, metric: str, timeframe: str, start_ts_ms: int, end_ts_ms: int
    ) -> Iterator[RowBars]:
        """
        Генератор баров по диапазону времени [start, end], ORDER BY ts ASC.
        Удобно для бэктестов/агрегаций.
        """
        cur = self.conn.cursor()
        cur.execute(
            "SELECT ts,o,h,l,c,v FROM bars WHERE metric=? AND timeframe=? AND ts BETWEEN ? AND ? ORDER BY ts ASC",
            (metric, timeframe, int(start_ts_ms), int(end_ts_ms))
        )
        for r in cur:
            yield self._row_to_bars_tuple(r)

    def get_last_ts(self, metric: str, timeframe: str) -> int | None:
        cur = self.conn.cursor()
        cur.execute(
            "SELECT ts FROM bars WHERE metric=? AND timeframe=? ORDER BY ts DESC LIMIT 1",
            (metric, timeframe)
        )
        row = cur.fetchone()
        return int(row["ts"]) if row else None

    # ---- batch readers (для pair_divergences и отчётов) ----

    @measure_time
    def last_n_many_closes(
        self,
        metrics: Iterable[str],
        timeframe: str,
        n: int
    ) -> Dict[str, List[RowClose]]:
        """
        Возвращает словарь metric -> список (ts, close) для всех метрик.
        Все списки в порядке oldest→newest.
        Оптимизировано: использует один запрос с IN для всех метрик.
        """
        metrics_list = list(metrics)
        if not metrics_list:
            return {}
        
        # Оптимизация: один запрос для всех метрик
        placeholders = ','.join('?' * len(metrics_list))
        cur = self.conn.cursor()
        cur.execute(
            f"""
            SELECT metric, ts, c 
            FROM bars 
            WHERE metric IN ({placeholders}) AND timeframe=?
            ORDER BY metric, ts DESC
            """,
            (*metrics_list, timeframe)
        )
        
        # Группируем результаты по метрикам
        out: Dict[str, List[RowClose]] = {m: [] for m in metrics_list}
        rows_by_metric: Dict[str, List] = {m: [] for m in metrics_list}
        
        for row in cur.fetchall():
            metric = row["metric"]
            ts = int(row["ts"])
            c = float(row["c"])
            rows_by_metric[metric].append((ts, c))
        
        # Берем последние n для каждой метрики и реверсируем
        for m in metrics_list:
            rows = rows_by_metric[m][:n]
            rows.reverse()
            out[m] = rows
        
        return out

    @measure_time
    def last_n_many_bars(
        self,
        metrics: Iterable[str],
        timeframe: str,
        n: int
    ) -> Dict[str, List[RowBars]]:
        """
        То же, что last_n_many_closes, но с полными барами (ts,o,h,l,c,v).
        Оптимизировано: использует один запрос с IN для всех метрик.
        """
        metrics_list = list(metrics)
        if not metrics_list:
            return {}
        
        # Оптимизация: один запрос для всех метрик
        placeholders = ','.join('?' * len(metrics_list))
        cur = self.conn.cursor()
        cur.execute(
            f"""
            SELECT metric, ts, o, h, l, c, v 
            FROM bars 
            WHERE metric IN ({placeholders}) AND timeframe=?
            ORDER BY metric, ts DESC
            """,
            (*metrics_list, timeframe)
        )
        
        # Группируем результаты по метрикам
        out: Dict[str, List[RowBars]] = {m: [] for m in metrics_list}
        rows_by_metric: Dict[str, List] = {m: [] for m in metrics_list}
        
        for row in cur.fetchall():
            metric = row["metric"]
            # Создаем кортеж в формате RowBars: (ts, o, h, l, c, v)
            bar_tuple = (
                int(row["ts"]),
                float(row["o"]),
                float(row["h"]),
                float(row["l"]),
                float(row["c"]),
                None if row["v"] is None else float(row["v"])
            )
            rows_by_metric[metric].append(bar_tuple)
        
        # Берем последние n для каждой метрики и реверсируем
        for m in metrics_list:
            rows = rows_by_metric[m][:n]
            rows.reverse()
            out[m] = rows
        
        return out

    # ---------- divergences persistence ----------

    def upsert_div(self, *, metric: str, timeframe: str, indicator: str, side: str,
                   implication: str, pivot_l_ts: int | None, pivot_l_val: float | None,
                   pivot_r_ts: int | None, pivot_r_val: float | None,
                   detected_ts: int, score: float = 0.0) -> None:
        uniq = f"{metric}|{timeframe}|{indicator}|{side}|{pivot_l_ts}|{pivot_r_ts}"
        cur = self.conn.cursor()
        cur.execute(
            """INSERT OR IGNORE INTO divs(metric,timeframe,indicator,side,implication,
                                          pivot_l_ts,pivot_l_val,pivot_r_ts,pivot_r_val,
                                          detected_ts,status,score,uniq)
               VALUES(?,?,?,?,?,?,?,?,?,?, 'active', ?, ?)""",
            (metric, timeframe, indicator, side, implication,
             pivot_l_ts, pivot_l_val, pivot_r_ts, pivot_r_val,
             detected_ts, score, uniq)
        )
        self.conn.commit()

    def list_open_divs(self, metric: str, timeframe: str) -> list[tuple]:
        """
        Возвращает активные и подтверждённые (active + confirmed) дивергенции
        с их статусом и степенью подтверждения (confirm_grade).
        Поля: (id, indicator, side, implication, pivot_r_ts, pivot_r_val, status, confirm_grade)
        """
        cur = self.conn.cursor()
        cur.execute(
            """SELECT id, indicator, side, implication,
                      pivot_r_ts, pivot_r_val, status, confirm_grade
               FROM divs
               WHERE metric=? AND timeframe=? AND status IN ('active','confirmed')
               ORDER BY detected_ts DESC""",
            (metric, timeframe)
        )
        return cur.fetchall()

    def list_active_divs(self, metric: str, timeframe: str) -> list[tuple]:
        return self.list_open_divs(metric, timeframe)

    def confirm_div_by_id(self, div_id: int, ts_ms: int) -> None:
        cur = self.conn.cursor()
        cur.execute("UPDATE divs SET status='confirmed', confirm_ts=? WHERE id=? AND status='active'",
                    (ts_ms, div_id))
        self.conn.commit()

    def invalidate_div_by_id(self, div_id: int, ts_ms: int) -> None:
        cur = self.conn.cursor()
        cur.execute("UPDATE divs SET status='invalid', invalid_ts=? WHERE id=? AND status IN ('active','confirmed')",
                    (ts_ms, div_id))
        self.conn.commit()

    def confirm_soft_by_id(self, div_id: int, ts_ms: int) -> None:
        """
        Подтверждение soft: если уже hard — не понижаем.
        Если статус ещё не confirmed — делаем confirmed+soft.
        """
        cur = self.conn.cursor()
        cur.execute("SELECT status, confirm_grade FROM divs WHERE id=?", (div_id,))
        row = cur.fetchone()
        if not row:
            return
        status, grade = row["status"], row["confirm_grade"]
        if grade == "hard":
            return
        if status != "confirmed":
            cur.execute(
                "UPDATE divs SET status='confirmed', confirm_ts=?, confirm_grade='soft' WHERE id=?",
                (ts_ms, div_id)
            )
        else:
            cur.execute(
                "UPDATE divs SET confirm_grade='soft' WHERE id=? AND (confirm_grade IS NULL OR confirm_grade<>'hard')",
                (div_id,)
            )
        self.conn.commit()

    def confirm_hard_by_id(self, div_id: int, ts_ms: int) -> None:
        """
        Подтверждение hard: апгрейдит soft→hard, либо подтверждает с нуля.
        """
        cur = self.conn.cursor()
        cur.execute("SELECT status, confirm_grade FROM divs WHERE id=?", (div_id,))
        row = cur.fetchone()
        if not row:
            return
        status, grade = row["status"], row["confirm_grade"]
        if status != "confirmed":
            cur.execute(
                "UPDATE divs SET status='confirmed', confirm_ts=?, confirm_grade='hard' WHERE id=?",
                (ts_ms, div_id)
            )
        else:
            if grade != "hard":
                cur.execute("UPDATE divs SET confirm_grade='hard' WHERE id=?", (div_id,))
        self.conn.commit()

    # совместимость со старым кодом: трактуем "confirm_div_by_id" как hard
    def confirm_div_by_id(self, div_id: int, ts_ms: int) -> None:
        self.confirm_hard_by_id(div_id, ts_ms)

    def invalidate_div_by_id(self, div_id: int, ts_ms: int) -> None:
        cur = self.conn.cursor()
        cur.execute(
            "UPDATE divs SET status='invalid', invalid_ts=?, confirm_grade=NULL WHERE id=? AND status IN ('active','confirmed')",
            (ts_ms, div_id)
        )
        self.conn.commit()

    # ---------- trades persistence (для TWAP анализа) ----------

    def upsert_many_trades(self, trades: List[Dict]) -> None:
        """
        Батч-вставка сделок с дедупликацией.
        
        Args:
            trades: Список словарей с ключами:
                - symbol: str (например, "BTCUSDT")
                - exchange: str (например, "Binance")
                - time: int (timestamp в миллисекундах)
                - price: float
                - qty: float
                - is_buyer: bool (True = покупка, False = продажа)
                - collected_at: int (timestamp когда собрали данные, в миллисекундах)
        """
        if not trades:
            return
        
        cur = self.conn.cursor()
        with self.atomic():
            for trade in trades:
                cur.execute(
                    """INSERT OR IGNORE INTO trades(symbol, exchange, time, price, qty, is_buyer, collected_at)
                       VALUES(?, ?, ?, ?, ?, ?, ?)""",
                    (
                        trade["symbol"],
                        trade["exchange"],
                        trade["time"],
                        trade["price"],
                        trade["qty"],
                        1 if trade["is_buyer"] else 0,
                        trade["collected_at"],
                    )
                )
        self.conn.commit()

    def get_trades_by_period(
        self,
        symbol: str,
        since_ms: int,
        until_ms: Optional[int] = None,
        exchange: Optional[str] = None
    ) -> List[Dict]:
        """
        Получить сделки за период из БД.
        
        Args:
            symbol: Символ торговли (например, "BTCUSDT")
            since_ms: Начало периода (timestamp в миллисекундах)
            until_ms: Конец периода (timestamp в миллисекундах), если None - до текущего момента
            exchange: Фильтр по бирже (опционально)
        
        Returns:
            Список сделок в формате [{"time": ms, "price": float, "qty": float, "is_buyer": bool, "exchange": str}, ...]
        """
        cur = self.conn.cursor()
        
        if until_ms is None:
            until_ms = int(datetime.now().timestamp() * 1000)
        
        if exchange:
            cur.execute(
                """SELECT time, price, qty, is_buyer, exchange
                   FROM trades
                   WHERE symbol=? AND exchange=? AND time >= ? AND time <= ?
                   ORDER BY time ASC""",
                (symbol, exchange, since_ms, until_ms)
            )
        else:
            cur.execute(
                """SELECT time, price, qty, is_buyer, exchange
                   FROM trades
                   WHERE symbol=? AND time >= ? AND time <= ?
                   ORDER BY time ASC""",
                (symbol, since_ms, until_ms)
            )
        
        rows = cur.fetchall()
        return [
            {
                "time": row["time"],
                "price": float(row["price"]),
                "qty": float(row["qty"]),
                "is_buyer": bool(row["is_buyer"]),
                "exchange": row["exchange"],
            }
            for row in rows
        ]

    def cleanup_old_trades(self, max_age_hours: int = 24) -> int:
        """
        Удалить старые сделки (старше указанного количества часов).
        
        Args:
            max_age_hours: Максимальный возраст данных в часах (по умолчанию 24)
        
        Returns:
            Количество удаленных записей
        """
        cur = self.conn.cursor()
        cutoff_ms = int(datetime.now().timestamp() * 1000) - (max_age_hours * 60 * 60 * 1000)
        
        cur.execute("DELETE FROM trades WHERE collected_at < ?", (cutoff_ms,))
        deleted = cur.rowcount
        self.conn.commit()
        
        return deleted


