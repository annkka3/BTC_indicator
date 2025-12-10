# app/infrastructure/indices_service.py
# -*- coding: utf-8 -*-
import asyncio
import time
import json
import re
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List

# aiohttp — опционально
try:
    import aiohttp  # type: ignore
except ImportError:
    aiohttp = None  # type: ignore

# bs4 — опционально (для altseason); при отсутствии используем regex
try:
    from bs4 import BeautifulSoup  # type: ignore
except ImportError:
    BeautifulSoup = None  # type: ignore

from urllib.request import urlopen, Request

_FNG_URL         = "https://api.alternative.me/fng/"
_FNG_WIDGET_PNG  = "https://alternative.me/crypto/fear-and-greed-index.png"
_GLOBAL_URL      = "https://api.alternative.me/v2/global/"
_TICKER_URL      = "https://api.alternative.me/v2/ticker/"
_LISTINGS_URL    = "https://api.alternative.me/v2/listings/"
_ALTSEASON_PAGE  = "https://www.blockchaincenter.net/en/altcoin-season-index/"

# ---------- helpers ----------

def _to_ts(value) -> Optional[int]:
    """Безопасно переводит 'timestamp' из API в unix-TS (секунды)."""
    if value is None:
        return None
    try:
        return int(value)
    except Exception:
        pass
    s = str(value).strip()
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%Y/%m/%d", "%d/%m/%Y"):
        try:
            dt = datetime.strptime(s, fmt).replace(tzinfo=timezone.utc)
            return int(dt.timestamp())
        except Exception:
            continue
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return int(dt.timestamp())
    except Exception:
        return None


class IndicesService:
    """
    HTTP-запросы через aiohttp (если установлен) или stdlib (urllib).
    Кэш:
      - общий TTL (self._ttl) = 30 мин
      - тикер — 5 мин
      - listings — 24 ч
    """
    def __init__(self, session: Optional["aiohttp.ClientSession"] = None):
        self._session = session if aiohttp else None
        # key -> {"ts": int, "data": Any, "ttl": int|None}
        self._cache: Dict[str, Dict[str, Any]] = {}
        self._ttl = 60 * 30  # 30 минут

    # ---------- cache ----------
    def _cache_get(self, key: str, default_ttl: Optional[int] = None):
        item = self._cache.get(key)
        if not item:
            return None
        ttl = item.get("ttl") or default_ttl or self._ttl
        if time.time() - item["ts"] < ttl:
            return item["data"]
        return None

    def _cache_put(self, key: str, data: Any, ttl: Optional[int] = None):
        self._cache[key] = {"ts": time.time(), "data": data, "ttl": ttl}

    # ---------- HTTP ----------
    async def _get_text(self, url: str) -> str:
        if aiohttp:
            if self._session is not None:
                async with self._session.get(url, timeout=15) as r:
                    r.raise_for_status()
                    return await r.text()
            async with aiohttp.ClientSession() as s:
                async with s.get(url, timeout=15) as r:
                    r.raise_for_status()
                    return await r.text()
        # fallback stdlib (в отдельном потоке)
        def _sync_get() -> str:
            req = Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urlopen(req, timeout=15) as resp:
                return resp.read().decode("utf-8", errors="ignore")
        return await asyncio.to_thread(_sync_get)

    async def _get_json(self, url: str) -> Any:
        txt = await self._get_text(url)
        return json.loads(txt)

    # ---------- Fear & Greed ----------
    async def get_fng_history(self, limit: int = 7, date_format: str = "world") -> Dict[str, Any]:
        limit = max(1, min(int(limit), 1000))
        cache_key = f"fng:{limit}:{date_format}"
        cached = self._cache_get(cache_key)
        if cached:
            return cached

        url = f"{_FNG_URL}?limit={limit}&format=json&date_format={date_format}"
        j = await self._get_json(url)

        values = []
        for d in (j.get("data") or []):
            values.append({
                "value": int(d.get("value") or 0),
                "classification": d.get("value_classification", "") or "",
                "timestamp": _to_ts(d.get("timestamp")),
            })
        try:
            ttu = int((j.get("metadata") or {}).get("time_until_update") or 0)
        except Exception:
            ttu = 0

        values = sorted(values, key=lambda x: x.get("timestamp") or 0, reverse=True)
        data = {"values": values, "time_until_update": ttu}
        self._cache_put(cache_key, data)  # TTL по умолчанию (30 мин)
        return data

    def get_fng_widget_url(self, cache_bust: Optional[int] = None) -> str:
        """
        Возвращает URL PNG-виджета Fear & Greed с cache-buster параметром,
        чтобы Telegram не отдавал устаревшую картинку из CDN.
        По умолчанию обновляем адрес раз в час.
        """
        if cache_bust is None:
            # меняется раз в час: достаточно часового тика
            cache_bust = int(time.time() // 3600)
        return f"{_FNG_WIDGET_PNG}?v={cache_bust}"

    # ---------- Altseason ----------
    async def get_altseason(self) -> Dict[str, Any]:
        """Получает значение (0..100) и лейбл "Altcoin Season"/"Bitcoin Season".
        
        Сначала пытается использовать CoinGecko API для расчета на основе BTC доминирования.
        Если не получается, парсит со страницы Blockchaincenter.
        """
        import logging
        logger = logging.getLogger("alt_forecast.indices")
        
        cache_key = "altseason"
        cached = self._cache_get(cache_key, default_ttl=60 * 10)  # 10 минут
        if cached:
            return cached

        value: Optional[int] = None
        label: str = ""
        
        # Стратегия 1: Используем CoinGecko API для расчета на основе BTC доминирования
        try:
            # Используем тот же способ импорта, что и в market_data_service.py
            # Когда indices_service импортируется из handlers через ...infrastructure.indices_service,
            # относительный импорт .coingecko может не работать, поэтому используем абсолютный
            from app.infrastructure.coingecko import global_stats
            
            # Вызываем синхронную функцию в отдельном потоке
            global_data = await asyncio.to_thread(global_stats)
            
            if global_data and "data" in global_data:
                market_cap_percentage = global_data["data"].get("market_cap_percentage", {})
                btc_dominance = market_cap_percentage.get("btc", None)
                
                if btc_dominance is not None:
                    # Формула расчета Altcoin Season Index на основе BTC доминирования
                    # Согласно blockchaincenter.net:
                    # - Индекс = 100 означает полный Altcoin Season (BTC доминирование низкое)
                    # - Индекс = 0 означает полный Bitcoin Season (BTC доминирование высокое)
                    # - Порог 75% для Altcoin Season
                    # 
                    # Формула: чем ниже BTC доминирование, тем выше индекс
                    # Обычно BTC доминирование колеблется от ~35% до ~70%
                    # Используем более широкий диапазон для более точного расчета
                    
                    # Нормализуем BTC доминирование: если оно в диапазоне 30-70%
                    # 30% BTC -> 100 индекс (Altcoin Season)
                    # 70% BTC -> 0 индекс (Bitcoin Season)
                    # Линейная интерполяция
                    
                    if btc_dominance <= 30:
                        # Очень низкое доминирование BTC - сильный Altcoin Season
                        value = 100
                    elif btc_dominance >= 70:
                        # Очень высокое доминирование BTC - сильный Bitcoin Season
                        value = 0
                    else:
                        # Линейная интерполяция: 30% BTC -> 100 индекс, 70% BTC -> 0 индекс
                        # Формула: index = 100 * (70 - btc_dom) / (70 - 30)
                        value = 100 * (70 - btc_dominance) / 40
                        value = max(0, min(100, value))  # Ограничиваем 0-100
                        value = int(round(value))  # Округляем до целого
                    
                    if value >= 75:
                        label = "Altcoin Season"
                    else:
                        label = "Bitcoin Season"
                    
                    logger.info(f"Altseason: Calculated from CoinGecko - BTC dominance: {btc_dominance:.2f}%, Index: {value} (no %), Label: {label}")
        except Exception as e:
            logger.warning(f"Altseason: Failed to calculate from CoinGecko: {e}", exc_info=True)
        
        # Стратегия 2: Парсинг со страницы Blockchaincenter (fallback)
        if value is None:
            try:
                html = await self._get_text(_ALTSEASON_PAGE)
                
                # Улучшенный парсинг с несколькими стратегиями
                if BeautifulSoup:
                    soup = BeautifulSoup(html, "html.parser")
                    
                    # Стратегия 1: Ищем SVG или canvas элемент с gauge (часто используется на сайте)
                    # Ищем элементы с классом или id, связанными с gauge/chart
                    gauge_elem = soup.find(class_=re.compile(r'gauge|chart|index|value', re.I))
                    if gauge_elem:
                        # Ищем число в тексте или атрибутах
                        gauge_text = gauge_elem.get_text()
                        gauge_match = re.search(r'(\d{1,3})\s*%?', gauge_text)
                        if gauge_match:
                            try:
                                candidate = int(gauge_match.group(1))
                                if 0 <= candidate <= 100:
                                    value = candidate
                                    logger.info(f"Altseason: Found value {value} from gauge element")
                            except Exception:
                                pass
                    
                    # Стратегия 2: Ищем процент рядом с текстом "Altcoin Season Index" или в заголовке
                    if value is None:
                        # Ищем паттерн типа "Altcoin Season Index" и затем число рядом (более точный поиск)
                        # Ищем в пределах 100 символов после "Altcoin Season Index"
                        index_pattern = re.search(
                            r'Altcoin Season Index[^0-9]{0,100}(\d{1,3})\s*%',
                            html, re.I | re.S
                        )
                        if index_pattern:
                            try:
                                candidate = int(index_pattern.group(1))
                                if 0 <= candidate <= 100:
                                    value = candidate
                                    logger.info(f"Altseason: Found value {value} from index pattern (near 'Altcoin Season Index')")
                            except Exception:
                                pass
                        
                        # Если не нашли, ищем в заголовках или крупных элементах
                        if value is None:
                            # Ищем в заголовках h1-h4
                            for tag_name in ["h1", "h2", "h3", "h4"]:
                                headers = soup.find_all(tag_name)
                                for header in headers:
                                    header_text = header.get_text()
                                    if "Altcoin Season" in header_text or "altcoin season" in header_text.lower():
                                        # Ищем число с % в этом заголовке
                                        num_in_header = re.search(r'(\d{1,3})\s*%', header_text)
                                        if num_in_header:
                                            try:
                                                candidate = int(num_in_header.group(1))
                                                if 0 <= candidate <= 100:
                                                    value = candidate
                                                    logger.info(f"Altseason: Found value {value} from {tag_name} header: {header_text[:50]}")
                                                    break
                                            except Exception:
                                                pass
                                        # Или в следующем элементе (span, div, p, strong)
                                        next_elem = header.find_next(["span", "div", "p", "strong", "h1", "h2", "h3"])
                                        if next_elem:
                                            next_text = next_elem.get_text(strip=True)
                                            # Ищем число с % в следующем элементе
                                            num_in_next = re.search(r'(\d{1,3})\s*%', next_text)
                                            if num_in_next:
                                                try:
                                                    candidate = int(num_in_next.group(1))
                                                    if 0 <= candidate <= 100:
                                                        value = candidate
                                                        logger.info(f"Altseason: Found value {value} from element after {tag_name}: {next_text[:50]}")
                                                        break
                                                except Exception:
                                                    pass
                                if value is not None:
                                    break
                        
                        # Если все еще не нашли, ищем в элементах с большими числами (обычно это основной индикатор)
                        if value is None:
                            # Ищем элементы с классом или id, содержащими "value", "index", "percent"
                            for elem in soup.find_all(attrs={"class": re.compile(r'value|index|percent|gauge', re.I)}):
                                elem_text = elem.get_text()
                                num_match = re.search(r'(\d{1,3})\s*%', elem_text)
                                if num_match:
                                    try:
                                        candidate = int(num_match.group(1))
                                        if 0 <= candidate <= 100:
                                            value = candidate
                                            logger.info(f"Altseason: Found value {value} from element with value/index class")
                                            break
                                    except Exception:
                                        pass
                                if value is not None:
                                    break
                    
                    # Стратегия 3: Ищем заголовок и следующее число
                    if value is None:
                        header = soup.find(lambda tag: tag.name in ("h1", "h2", "h3", "h4") and "Altcoin Season" in tag.get_text())
                        if header:
                            # Ищем число в следующих элементах
                            for elem in header.find_all_next(["span", "div", "p", "strong", "b", "h1", "h2", "h3"], limit=30):
                                txt = elem.get_text(strip=True)
                                # Ищем число с % или без, но больше 0
                                num_match = re.search(r'(\d{1,3})', txt)
                                if num_match:
                                    try:
                                        candidate = int(num_match.group(1))
                                        if 0 <= candidate <= 100:
                                            value = candidate
                                            logger.info(f"Altseason: Found value {value} from header context: {txt[:50]}")
                                            break
                                    except Exception:
                                        continue
                    
                    # Стратегия 4: Ищем в метаданных или data-атрибутах
                    if value is None:
                        for attr in ["data-value", "data-index", "data-percent", "value", "index"]:
                            meta_value = soup.find(attrs={attr: True})
                            if meta_value:
                                try:
                                    val_str = meta_value.get(attr)
                                    if val_str:
                                        num_match = re.search(r'(\d+)', str(val_str))
                                        if num_match:
                                            candidate = int(num_match.group(1))
                                            if 0 <= candidate <= 100:
                                                value = candidate
                                                logger.info(f"Altseason: Found value {value} from {attr} attribute")
                                                break
                                except Exception:
                                    continue
                    
                    # Определяем label на основе value
                    if value is not None:
                        if value >= 75:
                            label = "Altcoin Season"
                        else:
                            label = "Bitcoin Season"
                        logger.info(f"Altseason: Set label '{label}' based on value {value}")
                    else:
                        # Пытаемся найти label в тексте
                        lab_match = re.search(r'(Altcoin Season|Bitcoin Season)', html, re.I)
                        if lab_match:
                            label = lab_match.group(0).strip()
                            logger.info(f"Altseason: Found label '{label}' from text")
                else:
                    # Fallback на regex
                    # Ищем процент
                    percent_match = re.search(r'(\d{1,3})\s*%', html, re.I)
                    if percent_match:
                        try:
                            value = int(percent_match.group(1))
                            if not (0 <= value <= 100):
                                value = None
                        except Exception:
                            value = None
                    
                    # Ищем label
                    lab_match = re.search(r'(Altcoin Season|Bitcoin Season)', html, re.I)
                    if lab_match:
                        label = lab_match.group(0).strip()
                    
                    # Если нашли label, но не value, определяем по label
                    if value is None and label:
                        if "Altcoin" in label:
                            value = 75  # По умолчанию для Altcoin Season
                        else:
                            value = 50  # По умолчанию для Bitcoin Season
                
                if value is None:
                    logger.warning("Altseason: Could not parse value from HTML")
            except Exception as e:
                logger.warning(f"Altseason: Failed to parse from blockchaincenter: {e}")
        
        if value is None:
            logger.error("Altseason: Could not get value from any source")
            # Возвращаем None, чтобы handler мог обработать ошибку
            return {"value": None, "label": ""}
        
        data = {"value": value, "label": label}
        self._cache_put(cache_key, data, ttl=60 * 10)  # Кэш на 10 минут для более частых обновлений
        return data

    # ---------- Global metrics ----------
    async def get_global(self, convert: str = "USD") -> Dict[str, Any]:
        convert = (convert or "USD").upper()
        cache_key = f"global:{convert}"
        cached = self._cache_get(cache_key)
        if cached:
            return cached

        j = await self._get_json(f"{_GLOBAL_URL}?convert={convert}")
        data = j.get("data", {}) if isinstance(j, dict) else {}
        quotes = data.get("quotes", {}) or {}
        quote = quotes.get(convert, quotes.get("USD", {})) or {}

        res = {
            "convert": convert,
            "total_market_cap": float(quote.get("total_market_cap") or 0),
            "total_volume_24h": float(quote.get("total_volume_24h") or 0),
            "btc_dominance": float(data.get("bitcoin_percentage_of_market_cap") or 0),
            "active_cryptocurrencies": data.get("active_cryptocurrencies"),
            "active_markets": data.get("active_markets"),
        }
        self._cache_put(cache_key, res)  # TTL по умолчанию (30 мин)
        return res

    # ---------- Ticker / сортировки ----------
    async def get_ticker(
        self,
        limit: int = 50,
        sort: Optional[str] = None,
        convert: str = "USD",
        structure: str = "array",
    ) -> List[Dict[str, Any]]:
        """
        Возвращает список монет с ценой/объёмом/изменениями.
        sort: rank | percent_change_1h | percent_change_24h | percent_change_7d | volume_24h | market_cap
        structure: "array" | "dictionary"
        """
        limit = max(1, min(int(limit), 200))
        convert = (convert or "USD").upper()
        sort = sort or ""
        structure = structure or "array"

        cache_key = f"ticker:{convert}:{sort}:{structure}:{limit}"
        cached = self._cache_get(cache_key, default_ttl=300)  # 5 минут
        if cached:
            return cached

        params = [f"limit={limit}", f"convert={convert}", f"structure={structure}"]
        if sort:
            params.append(f"sort={sort}")
        url = f"{_TICKER_URL}?{'&'.join(params)}"

        j = await self._get_json(url)
        data = j.get("data", [])
        if isinstance(data, dict):
            data = list(data.values())

        out: List[Dict[str, Any]] = []
        for d in data:
            quotes = d.get("quotes", {}) or {}
            q = quotes.get(convert, quotes.get("USD", {})) or {}

            def _f(x):
                try:
                    return float(x or 0)
                except Exception:
                    return 0.0

            out.append({
                "id": d.get("id"),
                "name": d.get("name"),
                "symbol": d.get("symbol"),
                "rank": d.get("rank"),
                "price": _f(q.get("price")),
                "market_cap": _f(q.get("market_cap")),
                "volume_24h": _f(q.get("volume_24h")),
                "percent_change_1h": _f(q.get("percentage_change_1h") or q.get("percent_change_1h")),
                "percent_change_24h": _f(q.get("percentage_change_24h") or q.get("percent_change_24h")),
                "percent_change_7d": _f(q.get("percentage_change_7d") or q.get("percent_change_7d")),
            })

        self._cache_put(cache_key, out, ttl=300)
        return out

    # ---------- Listings ----------
    async def get_listings(self) -> List[Dict[str, Any]]:
        """
        Возвращает справочник монет (id, name, symbol, website_slug).
        Кэшируем на 24 часа.
        """
        cache_key = "listings"
        cached = self._cache_get(cache_key, default_ttl=86400)  # сутки
        if cached:
            return cached

        j = await self._get_json(_LISTINGS_URL)
        data = j.get("data", []) if isinstance(j, dict) else []
        # нормализуем имена/символы
        out: List[Dict[str, Any]] = []
        for d in data:
            out.append({
                "id": d.get("id"),
                "name": d.get("name"),
                "symbol": d.get("symbol"),
                "slug": d.get("website_slug") or d.get("name", "").lower().replace(" ", "-"),
            })
        self._cache_put(cache_key, out, ttl=86400)
        return out

    # ---------- Single coin by id/slug ----------
    async def get_coin(self, id_or_slug: str, convert: str = "USD") -> Optional[Dict[str, Any]]:
        """
        Возвращает тикер по конкретной монете.
        Принимает numeric id (строка/число) или slug/имя (например, "bitcoin", "Bitcoin").
        """
        convert = (convert or "USD").upper()
        key = f"coin:{id_or_slug}:{convert}"
        cached = self._cache_get(key, default_ttl=300)
        if cached:
            return cached

        # 1) Если передали число — можно сразу дернуть /v2/ticker/<id>/
        is_numeric = False
        try:
            _ = int(str(id_or_slug).strip())
            is_numeric = True
        except Exception:
            is_numeric = False

        if is_numeric:
            url = f"{_TICKER_URL}{id_or_slug}/?convert={convert}"
            j = await self._get_json(url)
            d = (j.get("data") or {}).get(str(id_or_slug))
            if not d:
                return None
        else:
            # 2) Иначе пробуем найти slug через listings
            listings = await self.get_listings()
            query = str(id_or_slug).strip().lower()
            cand = None
            # сначала точное совпадение по slug
            for x in listings:
                if (x.get("slug") or "").lower() == query:
                    cand = x
                    break
            # затем по name
            if cand is None:
                for x in listings:
                    if (x.get("name") or "").lower() == query:
                        cand = x
                        break
            # затем по symbol (строгое совпадение)
            if cand is None:
                for x in listings:
                    if (x.get("symbol") or "").lower() == query:
                        cand = x
                        break
            if cand is None:
                return None
            cid = cand.get("id")
            url = f"{_TICKER_URL}{cid}/?convert={convert}"
            j = await self._get_json(url)
            d = (j.get("data") or {}).get(str(cid))
            if not d:
                return None

        quotes = d.get("quotes", {}) or {}
        q = quotes.get(convert, quotes.get("USD", {})) or {}

        def _f(x):
            try:
                return float(x or 0)
            except Exception:
                return 0.0

        res = {
            "id": d.get("id"),
            "name": d.get("name"),
            "symbol": d.get("symbol"),
            "rank": d.get("rank"),
            "price": _f(q.get("price")),
            "market_cap": _f(q.get("market_cap")),
            "volume_24h": _f(q.get("volume_24h")),
            "percent_change_1h": _f(q.get("percentage_change_1h") or q.get("percent_change_1h")),
            "percent_change_24h": _f(q.get("percentage_change_24h") or q.get("percent_change_24h")),
            "percent_change_7d": _f(q.get("percentage_change_7d") or q.get("percent_change_7d")),
        }
        self._cache_put(key, res, ttl=300)
        return res
