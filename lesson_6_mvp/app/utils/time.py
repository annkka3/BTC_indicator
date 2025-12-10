# app/utils/time.py
from __future__ import annotations
import pathlib

def ensure_path(sqlite_path: str) -> None:
    """
    Гарантирует существование каталога для SQLite-файла.
    Ничего не делает для ':memory:' и URI в стиле 'file:...'.

    Примеры входа:
      '/data/data.db'   -> создаст '/data'
      'db.sqlite3'      -> создаст текущий каталог (обычно уже есть)
      ':memory:'        -> пропуск
      'file:db?mode=memory&cache=shared' -> пропуск
      '~/bot/data.db'   -> корректно развернёт ~
    """
    if not sqlite_path:
        return

    s = sqlite_path.strip()
    if s == ":memory:" or s.startswith("file:"):
        return

    p = pathlib.Path(s).expanduser()
    # Всегда создаём именно каталог-родитель, даже если расширение нестандартное:
    dir_path = p.parent
    if dir_path and not dir_path.exists():
        dir_path.mkdir(parents=True, exist_ok=True)
