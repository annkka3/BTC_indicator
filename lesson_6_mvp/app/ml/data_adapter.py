# app/ml/data_adapter.py
from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import Iterable, Optional, Tuple, Callable

import numpy as np
import pandas as pd

__all__ = [
    "load_bars_from_project",
    "make_loader",
]

# =========================
# Helpers
# =========================

def _tf_to_str(tf: str) -> str:
    """
    Normalize timeframe string to one of: "1h", "4h", "24h".
    """
    tf = (tf or "").lower().strip()
    if tf in {"1h", "60", "60m", "60min", "h1"}:
        return "1h"
    if tf in {"4h", "240", "240m", "h4", "4hour", "4hr"}:
        return "4h"
    if tf in {"24h", "1d", "d", "day", "d1"}:
        return "24h"
    return tf or "1h"


def _tf_aliases(tf: str) -> list[str]:
    """
    Return common synonyms used in DB/files for a given tf.
    Used in SQL WHERE and filename patterns.
    """
    tf = _tf_to_str(tf)
    if tf == "1h":
        return ["1h", "60", "60m", "60min", "H1", "h1"]
    if tf == "4h":
        return ["4h", "240", "240m", "H4", "h4", "4hour", "4hr"]
    # 24h
    return ["24h", "1d", "D", "day", "1D", "d1"]


def _tf_file_aliases(tf: str) -> list[str]:
    """
    Aliases that commonly appear in filenames.
    """
    tf = _tf_to_str(tf)
    if tf == "1h":
        return ["1h", "60", "60m", "H1"]
    if tf == "4h":
        return ["4h", "240", "H4"]
    return ["24h", "1d", "D", "1D"]


def _symbol_norm(sym: str) -> str:
    """
    Normalize symbol to exchange-like format: e.g. BTC -> BTCUSDT.
    If a known standalone base is passed, append USDT.
    """
    s = (sym or "").upper().replace("/", "").replace("-", "").strip()
    if not s:
        return "BTCUSDT"
    if ":" in s:  # already EXCHANGE:PAIR
        return s
    if s in {"BTC", "ETH", "SOL", "BNB", "XRP", "ADA", "DOGE", "TON", "TRX", "DOT", "LINK"}:
        return s + "USDT"
    return s


def _maybe_parse_ts(s: pd.Series) -> pd.Series:
    """
    Convert a 'ts' series to UTC datetime (supports seconds / milliseconds / strings).
    """
    if np.issubdtype(s.dtype, np.number):
        # detect ms vs s by magnitude (> 1e12 -> ms)
        is_ms = (s > 1e12)
        ts = pd.to_datetime(np.where(is_ms, s / 1000.0, s), unit="s", utc=True)
    else:
        ts = pd.to_datetime(s, utc=True)
    return ts


def _normalize_df(df: pd.DataFrame, limit: int) -> pd.DataFrame:
    """
    Ensure the DF has columns: ['ts','open','high','low','close','volume'] and sane types/order.
    """
    if df is None or df.empty:
        raise ValueError("DataAdapter: empty dataframe")

    # map columns case-insensitively
    cols = {c.lower(): c for c in df.columns}
    ren: dict[str, str] = {}

    for want in ["ts", "open", "high", "low", "close", "volume"]:
        for have_lower, have_orig in cols.items():
            if have_lower == want:
                ren[have_orig] = want
        if want == "ts":
            for alt in ("time", "timestamp", "datetime", "date"):
                if alt in cols:
                    ren[cols[alt]] = "ts"
        if want == "volume":
            for alt in ("vol", "base_volume", "quote_volume"):
                if alt in cols:
                    ren[cols[alt]] = "volume"

    df = df.rename(columns=ren)

    missing = [c for c in ["ts", "open", "high", "low", "close", "volume"] if c not in df.columns]
    if missing:
        raise ValueError(f"DataAdapter: not enough columns in source: missing={missing}, got={list(df.columns)}")

    df = df[["ts", "open", "high", "low", "close", "volume"]].copy()

    # MultiIndex from some loaders (e.g., TradingView) -> reset
    if isinstance(df.index, pd.MultiIndex):
        df = df.reset_index(drop=True)

    # timestamps
    df["ts"] = _maybe_parse_ts(df["ts"])

    # clean & order
    df = df.sort_values("ts").drop_duplicates(subset=["ts"], keep="last")
    if limit and limit > 0:
        df = df.tail(int(limit))

    df = df.replace([np.inf, -np.inf], np.nan).dropna()
    for c in ("open", "high", "low", "close", "volume"):
        df[c] = df[c].astype(float)

    # sanity
    df = df[df["high"] >= df["low"]]
    df = df[df["open"] > 0]
    df = df[df["close"] > 0]
    return df


# =========================
# SQLite sources
# =========================

_SQLITE_CANDIDATES = [
    "/app/data/ohlcv.db",
    "/app/data/ohlcv.sqlite",
    "/app/data/market.db",
    "/app/data/bars.db",
    "/app/data/tv.db",
]

def _sqlite_paths() -> Iterable[Path]:
    # ENV overrides first
    for k in ("OHLCV_DB", "OHLCV_SQLITE", "SQLITE_PATH"):
        p = os.getenv(k)
        if p and Path(p).exists():
            yield Path(p)
    for p in _SQLITE_CANDIDATES:
        pp = Path(p)
        if pp.exists():
            yield pp


def _sqlite_guess_table(conn: sqlite3.Connection) -> Tuple[str, pd.DataFrame] | None:
    cur = conn.cursor()
    tables = [r[0] for r in cur.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
    for t in tables:
        info = cur.execute(f"PRAGMA table_info({t})").fetchall()
        cols = [r[1].lower() for r in info]
        if {"open", "high", "low", "close"}.issubset(cols) and ("ts" in cols or "time" in cols):
            return t, pd.DataFrame({"col": cols})
    return None


def _load_from_sqlite(db_path: Path, symbol: str, tf: str, limit: int) -> Optional[pd.DataFrame]:
    con = sqlite3.connect(str(db_path))
    try:
        guessed = _sqlite_guess_table(con)
        if not guessed:
            return None
        table, _ = guessed

        cur = con.cursor()
        cols = [r[1].lower() for r in cur.execute(f"PRAGMA table_info({table})").fetchall()]

        base_cols = ["ts", "open", "high", "low", "close", "volume"]
        sel_cols = [c for c in base_cols if c in cols] \
                 + [c for c in ("symbol", "ticker", "pair") if c in cols] \
                 + [c for c in ("tf", "interval", "timeframe") if c in cols]
        if not sel_cols:
            return None

        sym_cols = [c for c in ("symbol", "ticker", "pair") if c in cols]
        tf_cols  = [c for c in ("tf", "interval", "timeframe") if c in cols]

        where, args = [], []
        if sym_cols:
            where.append("(" + " OR ".join([c + "=?"] * len(sym_cols)) + ")")
            args += [symbol] * len(sym_cols)
        if tf_cols:
            aliases = _tf_aliases(tf)
            # (tf IN (?, ?, ?)) OR (interval IN (?, ?, ?)) ...
            tf_blocks = []
            for c in tf_cols:
                tf_blocks.append(f"{c} IN ({','.join(['?']*len(aliases))})")
                args += aliases
            where.append("(" + " OR ".join(tf_blocks) + ")")

        sql = f"SELECT {', '.join(sel_cols)} FROM {table}"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY ts DESC LIMIT ?"
        args.append(int(limit if limit else 5000))

        df = pd.read_sql_query(sql, con, params=args)
        if df.empty:
            # try without filters (last resort)
            df = pd.read_sql_query(
                f"SELECT {', '.join(sel_cols)} FROM {table} ORDER BY ts DESC LIMIT ?",
                con, params=[int(limit if limit else 5000)]
            )
        if df.empty:
            return None

        return _normalize_df(df, limit)
    finally:
        con.close()


# =========================
# Files (Parquet/CSV)
# =========================

_DATA_DIRS = [
    "/app/data/ohlcv",
    "/app/data/tv",
    "/app/data/bars",
    "/app/data/csv",
    "/app/data/parquet",
]

def _iter_data_dirs() -> Iterable[Path]:
    for k in ("OHLCV_DIR", "DATA_DIR"):
        p = os.getenv(k)
        if p and Path(p).exists():
            yield Path(p)
    for p in _DATA_DIRS:
        pp = Path(p)
        if pp.exists():
            yield pp


def _load_from_files(symbol: str, tf: str, limit: int) -> Optional[pd.DataFrame]:
    sym = symbol
    tf_alias = _tf_file_aliases(tf)

    patterns = []
    for alias in tf_alias:
        patterns.extend([
            f"{sym}_{alias}.parquet",
            f"*{sym}*_{alias}.parquet",
            f"{sym}_{alias}.csv",
            f"*{sym}*_{alias}.csv",
            f"{sym}-{alias}.csv",
            f"{sym}{alias}.csv",
        ])

    for d in _iter_data_dirs():
        for pat in patterns:
            for path in d.glob(pat):
                try:
                    if path.suffix.lower() == ".parquet":
                        df = pd.read_parquet(path)
                    else:
                        df = pd.read_csv(path)
                    if df is not None and not df.empty:
                        return _normalize_df(df, limit)
                except Exception:
                    continue
    return None


# =========================
# TradingView fallback
# =========================

def _tv_interval(Interval, tf: str):
    """
    Resolve Interval enum/attr for different libraries and TFs.
    Covers tvDatafeed and tradingview_datafeed variants.
    """
    tf = _tf_to_str(tf)

    candidates = {
        "1h":  ["in_1_hour", "H1", "h1"],
        "4h":  ["in_4_hour", "H4", "h4", "in_240_minute", "IN_240_MINUTE", "M240"],
        "24h": [
            "in_daily",         # tvDatafeed частый вариант
            "in_1_day",         # иногда встречается
            "D", "1D", "d1",    # tradingview_datafeed enum'ы
            "DAY", "daily",     # на всякий случай
            "in_1440_minute", "IN_1440_MINUTE", "M1440"
        ],
    }[tf]

    for name in candidates:
        if hasattr(Interval, name):
            return getattr(Interval, name)
    return None


def _load_from_tv(symbol: str, tf: str, limit: int) -> Optional[pd.DataFrame]:
    """
    Optional fallback if no SQLite/files found.
    Controlled by env DISABLE_TV_FALLBACK=1 to turn off.
    """
    if os.getenv("DISABLE_TV_FALLBACK", "").strip() == "1":
        return None

    tv_mod = None
    try:
        # preferred lib
        from tvDatafeed import TvDatafeed, Interval
        tv_mod = ("tvdatafeed", TvDatafeed, Interval)
    except Exception:
        try:
            # alt lib
            from tradingview_datafeed import TvDatafeed, Interval
            tv_mod = ("tradingview_datafeed", TvDatafeed, Interval)
        except Exception:
            return None

    _, TvDatafeed, Interval = tv_mod
    interval = _tv_interval(Interval, tf)
    if interval is None:
        return None

    tv_symbol = symbol if ":" in symbol else f"BINANCE:{symbol}"
    try:
        tv = TvDatafeed()
        df = tv.get_hist(tv_symbol, interval=interval, n_bars=int(limit or 5000))
        if df is None or df.empty:
            return None
        df = df.reset_index().rename(columns={"datetime": "ts", "time": "ts"})
        return _normalize_df(df, limit)
    except Exception:
        return None


# =========================
# Public API
# =========================

def load_bars_from_project(symbol: str, tf: str, limit: int = 5000) -> pd.DataFrame:
    """
    Try in order:
      1) SQLite in /app/data/*.db (or env OHLCV_DB/SQLITE_PATH)
      2) Files in /app/data/... (csv/parquet)
      3) TradingView fallback (can be disabled by DISABLE_TV_FALLBACK=1)

    Returns a DataFrame ['ts','open','high','low','close','volume'] in UTC, ascending by ts.
    """
    sym = _symbol_norm(symbol)
    tf = _tf_to_str(tf)

    # SQLite
    for p in _sqlite_paths():
        try:
            df = _load_from_sqlite(p, sym, tf, limit)
            if df is not None and not df.empty:
                return df
        except Exception:
            continue

    # Files
    try:
        df = _load_from_files(sym, tf, limit)
        if df is not None and not df.empty:
            return df
    except Exception:
        pass

    # TV fallback
    df = _load_from_tv(sym, tf, limit)
    if df is not None and not df.empty:
        return df

    raise FileNotFoundError(
        f"DataAdapter: не удалось найти бары для {sym} {tf}. "
        f"Проверь SQLite (/app/data/*.db) или файлы в /app/data/…"
    )


def make_loader(db: object | None = None) -> Callable[[str, str, int], pd.DataFrame]:
    """
    Factory that returns a loader(signature: (symbol, tf, limit) -> DataFrame).
    You can later replace the internals to use your self.db if needed.
    """
    def _loader(symbol: str, tf: str, limit: int = 5000) -> pd.DataFrame:
        return load_bars_from_project(symbol, tf, limit=limit)
    return _loader
