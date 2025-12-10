# app/presentation/formatters/message_formatter.py
"""
Formatters for Telegram messages.
"""

from typing import Dict, List, Optional
from telegram.constants import ParseMode


class MessageFormatter:
    """Форматтер для сообщений Telegram."""
    
    @staticmethod
    def format_report(status_data: Dict, full: bool = False) -> str:
        """Форматировать отчет."""
        lines = []
        
        if full:
            lines.append("<b>📊 Полный отчет</b>\n")
        else:
            lines.append("<b>📊 Краткий отчет</b>\n")
        
        # Добавляем данные из status_data
        if "btc_price" in status_data:
            lines.append(f"BTC: <b>${status_data['btc_price']:,.2f}</b>")
        
        if "dominance" in status_data:
            lines.append(f"Доминирование BTC: <b>{status_data['dominance']:.2f}%</b>")
        
        if "market_cap" in status_data:
            lines.append(f"Капитализация: <b>${status_data['market_cap']:,.0f}</b>")
        
        if full and "top_gainers" in status_data:
            lines.append("\n<b>Топ-5 роста:</b>")
            for coin in status_data["top_gainers"][:5]:
                lines.append(f"• {coin['symbol']}: <b>+{coin['change']:.2f}%</b>")
        
        if full and "top_losers" in status_data:
            lines.append("\n<b>Топ-5 падения:</b>")
            for coin in status_data["top_losers"][:5]:
                lines.append(f"• {coin['symbol']}: <b>{coin['change']:.2f}%</b>")
        
        return "\n".join(lines)
    
    @staticmethod
    def format_top_flop(coins: List[Dict], title: str, limit: int = 10) -> str:
        """Форматировать топ/флоп."""
        lines = [f"<b>{title}</b>\n"]
        
        for i, coin in enumerate(coins[:limit], 1):
            symbol = coin.get("symbol", "?")
            change = coin.get("change_24h", 0.0)
            price = coin.get("price", 0.0)
            emoji = "🟢" if change > 0 else "🔴"
            lines.append(
                f"{i}. {emoji} <b>{symbol}</b>: "
                f"${price:,.4f} ({change:+.2f}%)"
            )
        
        return "\n".join(lines)
    
    @staticmethod
    def format_help(short: bool = True) -> str:
        """Форматировать справку."""
        if short:
            return (
                "<b>ℹ️ Краткая справка</b>\n\n"
                "Основные команды:\n"
                "• /start — главное меню\n"
                "• /status — краткий отчет\n"
                "• /full — полный отчет\n"
                "• /bubbles — пузырьки рынка\n"
                "• /chart — график BTC\n"
                "• /help_full — полная справка"
            )
        else:
            return (
                "<b>ℹ️ Полная справка</b>\n\n"
                "📊 <b>Отчеты:</b>\n"
                "• /status — краткий отчет\n"
                "• /full — полный отчет\n\n"
                "🫧 <b>Визуализация:</b>\n"
                "• /bubbles [15m|1h|1d] — пузырьки рынка\n"
                "• /chart [15m|1h|4h|1d] — график BTC\n"
                "• /chart_album [tf] — альбом графиков\n\n"
                "🏆 <b>Топ/Флоп:</b>\n"
                "• /top_24h — топ роста за 24ч\n"
                "• /flop_24h — топ падения за 24ч\n\n"
                "📈 <b>Аналитика:</b>\n"
                "• /corr [tf] — корреляции\n"
                "• /beta [tf] — бета ETH/BTC\n"
                "• /vol [tf] — волатильность\n\n"
                "🧭 <b>Индексы:</b>\n"
                "• /fng — Fear & Greed Index\n"
                "• /altseason — Altseason Index\n\n"
                "🧠 <b>Прогнозы:</b>\n"
                "• /forecast [tf] — прогноз BTC\n"
                "• /forecast_alts — прогнозы альтов\n\n"
                "Используйте кнопки меню для быстрого доступа!"
            )
    
    @staticmethod
    def format_welcome(user_name: str) -> str:
        """Форматировать приветственное сообщение."""
        return (
            f"👋 Привет, <b>{user_name}</b>!\n\n"
            "Добро пожаловать в <b>ALT Forecast Bot</b> — "
            "ваш помощник для анализа криптовалютного рынка.\n\n"
            "📊 <b>Что умеет бот:</b>\n"
            "• Анализ рынка и отчеты\n"
            "• Визуализация данных (графики, пузырьки)\n"
            "• Прогнозы на основе ML\n"
            "• Индексы и метрики\n"
            "• Аналитика и корреляции\n\n"
            "Используйте кнопки меню для навигации или команду /help для справки."
        )
    
    @staticmethod
    def format_twap(twap_data: Dict) -> str:
        """Форматировать данные TWAP."""
        symbol = twap_data.get("symbol", "BTC")
        twap = twap_data.get("twap", 0.0)
        current = twap_data.get("current_price", 0.0)
        diff = current - twap
        diff_pct = (diff / twap * 100) if twap > 0 else 0.0
        
        emoji = "🟢" if diff > 0 else "🔴" if diff < 0 else "⚪"
        
        return (
            f"<b>📊 TWAP {symbol}</b>\n\n"
            f"Текущая цена: <b>${current:,.2f}</b>\n"
            f"TWAP: <b>${twap:,.2f}</b>\n"
            f"Отклонение: {emoji} <b>{diff:+.2f}</b> ({diff_pct:+.2f}%)"
        )
    
    @staticmethod
    def format_traditional_markets(data: Dict) -> str:
        """Форматировать данные традиционных рынков."""
        lines = ["<b>🌍 Традиционные рынки</b>\n"]
        
        if "sp500" in data:
            sp500 = data["sp500"]
            change = sp500.get("change", 0.0)
            emoji = "🟢" if change > 0 else "🔴"
            lines.append(f"{emoji} S&P500: <b>{sp500.get('value', 0):,.2f}</b> ({change:+.2f}%)")
        
        if "gold" in data:
            gold = data["gold"]
            change = gold.get("change", 0.0)
            emoji = "🟢" if change > 0 else "🔴"
            lines.append(f"{emoji} Золото: <b>${gold.get('value', 0):,.2f}</b> ({change:+.2f}%)")
        
        if "oil" in data:
            oil = data["oil"]
            change = oil.get("change", 0.0)
            emoji = "🟢" if change > 0 else "🔴"
            lines.append(f"{emoji} Нефть: <b>${oil.get('value', 0):,.2f}</b> ({change:+.2f}%)")
        
        return "\n".join(lines)

