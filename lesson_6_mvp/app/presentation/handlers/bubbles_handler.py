# app/presentation/handlers/bubbles_handler.py
"""
Handler for bubbles commands and callbacks.
"""

from telegram import Update, InputFile
from telegram.ext import ContextTypes
from .base_handler import BaseHandler
from ...application.services.bubbles_service import BubblesService
from ...infrastructure.repositories.user_repository import UserRepository
from ...application.dto.bubbles_dto import BubblesSettingsDTO
import logging

logger = logging.getLogger("alt_forecast.handlers.bubbles")


class BubblesHandler(BaseHandler):
    """Обработчик команд и callback'ов для пузырьков."""
    
    def __init__(self, db, services: dict):
        super().__init__(db, services)
        self.user_repo = UserRepository(db)
        self.bubbles_service: BubblesService = services.get("bubbles_service")
        self.market_data_service = services.get("market_data_service")
    
    async def handle_bubbles_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE, tf: str = "1d"):
        """Обработать команду /bubbles."""
        chat_id = update.effective_chat.id
        
        # Получаем настройки пользователя
        settings_dict = self.user_repo.get_bubbles_settings(chat_id)
        settings = BubblesSettingsDTO(**settings_dict)
        
        # Используем переданный TF или из настроек
        if tf:
            settings.tf = tf
        
        # Получаем данные рынка
        coins, gainers, losers, _ = self.market_data_service.get_top_movers(
            vs="usd",
            tf=settings.tf,
            limit_each=5,
            top=settings.top
        )
        
        # Фильтруем стейблы если нужно
        if settings.hide_stables:
            coins = self._filter_stables(coins)
            gainers = self._filter_stables(gainers)
            losers = self._filter_stables(losers)
        
        # Гарантируем включение топ 5 растущих и топ 5 падающих монет
        # Создаем словарь для быстрого поиска по символу
        coins_by_sym = {str(c.get("symbol", "")).upper(): c for c in coins}
        
        # Добавляем топ 5 растущих, если их еще нет в списке
        for gainer in gainers[:5]:
            sym = str(gainer.get("symbol", "")).upper()
            if sym and sym not in coins_by_sym:
                coins_by_sym[sym] = gainer
                coins.append(gainer)
                logger.info(f"Added top gainer to bubbles: {sym}")
        
        # Добавляем топ 5 падающих, если их еще нет в списке
        for loser in losers[:5]:
            sym = str(loser.get("symbol", "")).upper()
            if sym and sym not in coins_by_sym:
                coins_by_sym[sym] = loser
                coins.append(loser)
                logger.info(f"Added top loser to bubbles: {sym}")
        
        # Вычисляем общий объем для режимов volume_share и volume_24h
        total_volume_24h = sum(float(c.get("total_volume", 0) or 0) for c in coins)
        
        # Подготавливаем данные
        coins_for_render = self.bubbles_service.prepare_bubbles_data(
            coins[:settings.count],
            settings.size_mode,
            total_volume_24h
        )
        
        # Генерируем пузырьки
        png = self.bubbles_service.generate_bubbles(
            coins=coins_for_render,
            tf=settings.tf,
            count=settings.count,
            hide_stables=settings.hide_stables,
            seed=settings.seed,
            size_mode=settings.size_mode,
        )
        
        # Формируем caption
        size_mode_label = {
            "percent": "%", "cap": "Капа",
            "volume_share": "Доля объёма", "volume_24h": "Объём 24ч"
        }.get(settings.size_mode, "%")
        
        caption = f"Crypto bubbles — {settings.tf} · n={settings.count} · top{settings.top}"
        
        # Отправляем
        photo = InputFile(png, filename=f"bubbles_{settings.tf}.png")
        await context.bot.send_photo(
            chat_id=chat_id,
            photo=photo,
            caption=caption,
            parse_mode=None
        )
        
        # Формируем текстовое сообщение
        def _fmt_plain(c, vs_currency, tf_):
            sym = str(c.get("symbol", "")).upper()
            px = float(c.get("current_price") or 0.0)
            ch = (c.get("price_change_percentage_1h_in_currency") if tf_ == "1h"
                  else c.get("price_change_percentage_24h_in_currency")) \
                 or c.get("price_change_percentage_1h") \
                 or c.get("price_change_percentage_24h") \
                 or 0.0
            return f"{sym}: {px:.6f} {vs_currency.upper()}  {float(ch):+.2f}%"
        
        gainers_text = "\n".join(_fmt_plain(x, "usd", settings.tf) for x in gainers) or "—"
        losers_text = "\n".join(_fmt_plain(x, "usd", settings.tf) for x in losers) or "—"
        
        size_desc_map = {
            "percent": "размер ~ |%|",
            "cap": "размер ~ капа",
            "volume_share": "размер ~ доля объёма",
            "volume_24h": "размер ~ объём 24ч"
        }
        size_desc = size_desc_map.get(settings.size_mode, "размер ~ |%|")
        
        text = (
            f"<b>Crypto movers ({settings.tf})</b>\n\n"
            f"Пузыри: {size_desc}, цвет — изменение (динамическая яркость).\n\n"
            f"(n={settings.count}, universe={len(coins)}, stables={'off' if settings.hide_stables else 'on'})\n\n"
            f"<b>Топ-5 растущих</b>\n\n{gainers_text}\n\n"
            f"<b>Топ-5 падающих</b>\n\n{losers_text}"
        )
        
        await context.bot.send_message(
            chat_id=chat_id,
            text=text,
            parse_mode="HTML"
        )
    
    def _filter_stables(self, coins: list) -> list:
        """Фильтровать стейблы из списка монет."""
        def _is_stable(sym: str) -> bool:
            s = (sym or "").upper()
            stables = {
                "USDT", "USDC", "DAI", "TUSD", "USDD", "FDUSD", "USDE", "USDS", "USDJ", "BUSD", "PYUSD",
                "GUSD", "LUSD", "SUSD", "EURS", "BSC-USD", "USD0", "WBTC", "WETH", "STETH", "WSTETH"
            }
            if s in stables:
                return True
            return s.endswith("USD") or s.startswith("USD") or s in {"USDT.E", "USDC.E", "USDT0"}
        
        return [c for c in coins if not _is_stable(c.get("symbol", ""))]
    
    async def handle_bubbles_debug(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработать команду /bubbles_debug (отладочная команда)."""
        try:
            chat_id = update.effective_chat.id
            await update.message.reply_text("[dbg] backend=Agg, coins=?")
            await self.handle_bubbles_command(update, context, tf="24h")
            await update.message.reply_text("[dbg] photo OK v=rank")
        except Exception:
            logger.exception("handle_bubbles_debug failed")

