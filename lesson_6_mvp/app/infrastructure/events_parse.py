from __future__ import annotations
from typing import Tuple
import re, time, datetime as dt
from zoneinfo import ZoneInfo

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")  # YYYY-MM-DD

def parse_date_to_ms(date_str: str, tz: ZoneInfo | None) -> int:
    """Парсит YYYY-MM-DD в unix ms (локальная полночь выбранной TZ, если задана)."""
    s = date_str.strip()
    if not _DATE_RE.match(s):
        raise ValueError("Ожидаю дату в формате YYYY-MM-DD")
    y, m, d = (int(s[0:4]), int(s[5:7]), int(s[8:10]))
    if tz:
        dt_obj = dt.datetime(y, m, d, 0, 0, 0, tzinfo=tz)
        return int(dt_obj.timestamp() * 1000)
    # UTC по умолчанию
    return int(dt.datetime(y, m, d, 0, 0, 0, tzinfo=dt.timezone.utc).timestamp() * 1000)
