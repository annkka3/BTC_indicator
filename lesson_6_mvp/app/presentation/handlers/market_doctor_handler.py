# app/presentation/handlers/market_doctor_handler.py
"""
Handler for Market Doctor command - комплексный анализ рынка криптовалют.
"""

from telegram import Update
from telegram.ext import ContextTypes
from telegram.constants import ParseMode
from .base_handler import BaseHandler
import pandas as pd
import logging
import time
from datetime import datetime
from typing import Optional, Dict, List

from ...domain.market_diagnostics import (
    IndicatorCalculator,
    FeatureExtractor,
    MarketAnalyzer,
    ReportRenderer,
    TradePlanner,
    MarketDoctorConfig,
    DEFAULT_CONFIG,
    MultiTFDiagnostics,
    CalibrationService,
    TradabilityAnalyzer,
    generate_pattern_id,
    ReportBuilder,
    CompactReportRenderer
)
from ...domain.market_diagnostics.profile_provider import ProfileProvider
from ...infrastructure.market_data_service import MarketDataService, DerivativesSnapshot
from ...infrastructure.repositories.diagnostics_repository import DiagnosticsRepository
from ...domain.market_diagnostics.anomaly_detector import AnomalyDetector
from ...domain.market_regime import GlobalRegimeAnalyzer
from ...domain.portfolio import PortfolioAnalyzer
from ...domain.sentiment import SentimentAnalyzer
from ...domain.market_diagnostics.backtest_analyzer import BacktestAnalyzer
from ...domain.market_diagnostics.calibration_analyzer import CalibrationAnalyzer
from ...domain.market_diagnostics.weights_storage import WeightsStorage
from ...domain.market_diagnostics.scoring_engine import IndicatorGroup

logger = logging.getLogger("alt_forecast.handlers.market_doctor")


class MarketDoctorHandler(BaseHandler):
    """Обработчик команды Market Doctor."""
    
    def __init__(self, db, services: dict = None, config: MarketDoctorConfig = None):
        """
        Инициализация handler.
        
        Args:
            db: Экземпляр базы данных
            services: Словарь сервисов
            config: Конфигурация Market Doctor (по умолчанию DEFAULT_CONFIG)
        """
        super().__init__(db, services)
        self.config = config or DEFAULT_CONFIG
        self.profile_provider = ProfileProvider(db)
        self.indicator_calculator = IndicatorCalculator(self.config)
        self.feature_extractor = FeatureExtractor(self.config)
        self.market_analyzer = MarketAnalyzer(self.config)
        self.report_renderer = ReportRenderer()
        self.trade_planner = TradePlanner(self.config)
        self.data_service = MarketDataService(db)
        self.diagnostics_repo = DiagnosticsRepository(db)
        self.anomaly_detector = AnomalyDetector(self.diagnostics_repo)
        self.calibration_service = CalibrationService(db)
        self.regime_analyzer = GlobalRegimeAnalyzer(db)
        self.tradability_analyzer = TradabilityAnalyzer(db)
        self.portfolio_analyzer = PortfolioAnalyzer()
        self.sentiment_analyzer = SentimentAnalyzer(db)
        self.backtest_analyzer = BacktestAnalyzer(db)
        self.weights_storage = WeightsStorage(db)
        # Загружаем активные веса и передаём их в ReportBuilder
        active_weights = self.weights_storage.get_active_weights()
        self.report_builder = ReportBuilder(active_weights)
        self.compact_renderer = CompactReportRenderer()
        self.calibration_analyzer = CalibrationAnalyzer(db)
    
    def _get_user_config(self, user_id: int) -> MarketDoctorConfig:
        """Получить конфигурацию для пользователя на основе его профиля риска."""
        return self.profile_provider.get_config_for_user(user_id)
    
    async def handle_market_doctor(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработать команду /md или /market_doctor."""
        logger.info(f"handle_market_doctor called, user_id={update.effective_user.id if update.effective_user else 'N/A'}, args={context.args}")
        await self._handle_market_doctor_common(update, context, brief=False, trade_only=False)
    
    async def handle_market_doctor_brief(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработать команду /mdh - краткий отчет multi-TF."""
        await self._handle_market_doctor_common(update, context, brief=True, trade_only=False)
    
    async def handle_market_doctor_trade_only(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработать команду /mdt - только торговый план без индикаторов."""
        await self._handle_market_doctor_common(update, context, brief=False, trade_only=True)
    
    async def _handle_market_doctor_common(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        brief: bool = False,
        trade_only: bool = False
    ):
        logger.info(f"_handle_market_doctor_common called: brief={brief}, trade_only={trade_only}, args={context.args}")
        """
        Обработать команду /market_doctor или /md.
        
        Формат: /md <symbol> [timeframe]
        Пример: /md BTC 1h
        """
        try:
            # Получаем аргументы из context.args или из текста сообщения
            args = context.args or []
            
            # Если args пустой, пробуем извлечь из текста сообщения
            if not args and update.effective_message and update.effective_message.text:
                text = update.effective_message.text.strip()
                parts = text.split()
                if len(parts) > 1:
                    # Пропускаем команду (первая часть)
                    args = parts[1:]
                    logger.debug(f"Extracted args from message text: {args}")
            
            # Если все еще нет аргументов, показываем инструкцию
            if not args:
                logger.warning("No arguments provided for /md command")
                await self._safe_reply_text(
                    update,
                    "Использование: /md <символ> [таймфрейм]\n"
                    "Пример: /md BTC 1h\n"
                    "Пример: /md ETHUSDT 4h\n"
                    "Таймфреймы: 1h, 4h, 1d (по умолчанию 1h)",
                    parse_mode=ParseMode.HTML
                )
                return
            
            logger.debug(f"Processing /md command with args: {args}")
            
            symbol = args[0].upper().strip()
            timeframe = args[1] if len(args) > 1 else ("multi" if brief else "1h")
            
            # Для brief режима всегда используем multi-TF
            if brief:
                timeframes = ["1h", "4h", "1d"]
                await self._handle_multi_tf_analysis(update, symbol, timeframes, brief=True)
            else:
                # Проверяем, нужен ли multi-TF анализ
                multi_tf = timeframe.lower() == "multi" or timeframe.lower() == "all"
                
                if multi_tf:
                    # Multi-TF анализ
                    timeframes = ["1h", "4h", "1d"]
                    await self._handle_multi_tf_analysis(update, symbol, timeframes, brief=False)
                else:
                    # Одиночный ТФ анализ
                    valid_timeframes = ["1h", "4h", "1d", "15m"]
                    if timeframe not in valid_timeframes:
                        timeframe = "1h"
                    
                    # Проверяем, нужен ли краткий формат
                    ud = context.user_data
                    brief_mode = ud.get("md_brief", False)
                    
                    await self._handle_single_tf_analysis(update, context, symbol, timeframe, trade_only=trade_only, brief=brief_mode)
        
        except Exception as e:
            logger.exception("handle_market_doctor failed")
            await self._safe_reply_text(
                update,
                f"❌ Ошибка при анализе: {str(e)}\n"
                "Проверьте правильность параметров команды.",
                parse_mode=ParseMode.HTML
            )
    
    async def handle_market_doctor_calibrate(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработать команду /md_calibrate - отчёт о калибровке скоринга."""
        try:
            await update.message.reply_text("📊 Анализирую накопленные данные...", parse_mode=ParseMode.MARKDOWN)
            
            # Парсим аргументы (опционально: символ, таймфрейм)
            args = context.args or []
            symbol = args[0].upper() if len(args) > 0 else None
            timeframe = args[1] if len(args) > 1 else None
            
            # Генерируем отчёт о калибровке
            report = self.calibration_analyzer.generate_calibration_report(
                symbol=symbol,
                timeframe=timeframe,
                horizon_bars=4,
                horizon_hours=24.0
            )
            
            # Форматируем отчёт
            lines = []
            lines.append("📊 <b>Отчёт о калибровке Market Doctor</b>")
            lines.append("━━━━━━━━━━━━━━━━━━")
            
            # Пороги scores
            lines.append("\n🎯 <b>Рекомендуемые пороги scores:</b>")
            if report.score_thresholds:
                for direction, thresholds in report.score_thresholds.items():
                    if thresholds:
                        lines.append(f"\n{direction}:")
                        for level, threshold in thresholds.items():
                            lines.append(f"  • {level}: {threshold:.1f}/10")
            else:
                lines.append("Недостаточно данных для определения порогов")
            
            # Рекомендации по весам групп
            if report.recommendations:
                lines.append("\n⚖️ <b>Рекомендации по весам групп:</b>")
                for rec in report.recommendations:
                    change = "↑" if rec.recommended_weight > rec.current_weight else "↓"
                    lines.append(
                        f"\n{rec.group}: {rec.current_weight:.2f} → {rec.recommended_weight:.2f} {change}"
                    )
                    lines.append(f"  Корреляция: {rec.correlation_with_success:.2f}")
                    lines.append(f"  {rec.reasoning}")
            else:
                lines.append("\n⚖️ <b>Рекомендации по весам:</b>")
                lines.append("Недостаточно данных для рекомендаций")
            
            # Статистика по режимам
            if report.stats_by_regime:
                lines.append("\n📈 <b>Статистика по режимам:</b>")
                for regime, stats in report.stats_by_regime.items():
                    avg_r = stats.get('avg_r', 0)
                    win_rate = stats.get('win_rate', 0)
                    count = stats.get('count', 0)
                    lines.append(
                        f"\n{regime}:"
                        f"\n  • Средний R: {avg_r:.2f}"
                        f"\n  • Win rate: {win_rate:.1%}"
                        f"\n  • Сэмплов: {count}"
                    )
            
            # Статистика по таймфреймам
            if report.stats_by_timeframe:
                lines.append("\n⏰ <b>Статистика по таймфреймам:</b>")
                for tf, stats in report.stats_by_timeframe.items():
                    avg_r = stats.get('avg_r', 0)
                    win_rate = stats.get('win_rate', 0)
                    count = stats.get('count', 0)
                    lines.append(
                        f"\n{tf}:"
                        f"\n  • Средний R: {avg_r:.2f}"
                        f"\n  • Win rate: {win_rate:.1%}"
                        f"\n  • Сэмплов: {count}"
                    )
            
            # Информация о данных
            lines.append("\n━━━━━━━━━━━━━━━━━━")
            lines.append("💡 <i>Отчёт основан на накопленных данных диагностик.</i>")
            if report.recommendations:
                lines.append("\n📌 <b>Применить рекомендуемые веса:</b>")
                lines.append("<code>/md_apply_weights</code>")
            
            message = "\n".join(lines)
            
            # Разбиваем на части, если сообщение слишком длинное
            max_length = 4000
            if len(message) > max_length:
                parts = []
                current_part = []
                current_length = 0
                
                for line in lines:
                    line_length = len(line) + 1  # +1 for newline
                    if current_length + line_length > max_length and current_part:
                        parts.append("\n".join(current_part))
                        current_part = [line]
                        current_length = line_length
                    else:
                        current_part.append(line)
                        current_length += line_length
                
                if current_part:
                    parts.append("\n".join(current_part))
                
                for part in parts:
                    await update.message.reply_text(part, parse_mode=ParseMode.HTML)
            else:
                await update.message.reply_text(message, parse_mode=ParseMode.HTML)
        
        except Exception as e:
            logger.exception(f"Error in handle_market_doctor_calibrate: {e}")
            await update.message.reply_text(
                f"❌ Ошибка при генерации отчёта о калибровке: {str(e)}",
                parse_mode=ParseMode.MARKDOWN
            )
    
    async def handle_market_doctor_apply_weights(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработать команду /md_apply_weights - применить рекомендуемые веса."""
        try:
            await update.message.reply_text("⚖️ Применяю рекомендуемые веса...", parse_mode=ParseMode.MARKDOWN)
            
            # Генерируем отчёт о калибровке
            report = self.calibration_analyzer.generate_calibration_report(
                symbol=None,
                timeframe=None,
                horizon_bars=4,
                horizon_hours=24.0
            )
            
            if not report.recommendations:
                await update.message.reply_text(
                    "❌ Нет рекомендаций для применения.\n"
                    "Сначала запустите /md_calibrate для анализа данных.",
                    parse_mode=ParseMode.MARKDOWN
                )
                return
            
            # Формируем словарь весов из рекомендаций
            new_weights = {}
            current_weights = self.weights_storage.get_active_weights()
            
            # Начинаем с текущих весов
            for group in IndicatorGroup:
                new_weights[group] = current_weights.get(group, 0.1)
            
            # Применяем рекомендации
            applied_count = 0
            changes = []
            
            for rec in report.recommendations:
                try:
                    group = IndicatorGroup(rec.group)
                    old_weight = current_weights.get(group, 0.1)
                    new_weight = rec.recommended_weight
                    
                    # Нормализуем веса, чтобы сумма была равна 1.0
                    new_weights[group] = new_weight
                    applied_count += 1
                    
                    change_pct = ((new_weight - old_weight) / old_weight * 100) if old_weight > 0 else 0
                    changes.append(
                        f"  • {rec.group}: {old_weight:.3f} → {new_weight:.3f} "
                        f"({change_pct:+.1f}%)"
                    )
                except ValueError:
                    # Неизвестная группа, пропускаем
                    continue
            
            # Нормализуем веса
            total = sum(new_weights.values())
            if total > 0:
                for group in new_weights:
                    new_weights[group] = new_weights[group] / total
            
            # Сохраняем как новую конфигурацию
            import time
            config_name = f"calibrated_{int(time.time())}"
            self.weights_storage.save_weights(
                name=config_name,
                weights=new_weights,
                description="Автоматически откалиброванные веса на основе статистики",
                set_active=True
            )
            
            # Обновляем ReportBuilder с новыми весами
            self.report_builder = ReportBuilder(new_weights)
            
            # Формируем ответ
            lines = []
            lines.append("✅ <b>Веса успешно применены!</b>")
            lines.append("\n📊 <b>Изменения:</b>")
            for change in changes:
                lines.append(change)
            
            lines.append(f"\n💾 Конфигурация сохранена как: <code>{config_name}</code>")
            lines.append("\n💡 <i>Новые веса будут использоваться для всех последующих анализов.</i>")
            lines.append("<i>Для возврата к дефолтным весам используйте:</i>")
            lines.append("<code>/md_weights_reset</code>")
            
            await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)
        
        except Exception as e:
            logger.exception(f"Error in handle_market_doctor_apply_weights: {e}")
            await update.message.reply_text(
                f"❌ Ошибка при применении весов: {str(e)}",
                parse_mode=ParseMode.MARKDOWN
            )
    
    async def handle_market_doctor_weights_list(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработать команду /md_weights_list - список конфигураций весов."""
        try:
            configs = self.weights_storage.list_configurations()
            
            if not configs:
                await update.message.reply_text(
                    "📋 Нет сохранённых конфигураций весов.",
                    parse_mode=ParseMode.MARKDOWN
                )
                return
            
            lines = []
            lines.append("📋 <b>Конфигурации весов:</b>")
            lines.append("━━━━━━━━━━━━━━━━━━")
            
            # datetime уже импортирован наверху
            for config in configs:
                active_marker = "✅" if config['is_active'] else ""
                lines.append(
                    f"\n{active_marker} <b>{config['name']}</b>"
                )
                if config['description']:
                    lines.append(f"   {config['description']}")
                lines.append(f"   Создана: {datetime.fromtimestamp(config['created_at_ms'] / 1000).strftime('%Y-%m-%d %H:%M')}")
            
            lines.append("\n━━━━━━━━━━━━━━━━━━")
            lines.append("💡 <i>Для активации конфигурации используйте:</i>")
            lines.append("<code>/md_weights_set &lt;name&gt;</code>")
            
            await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)
        
        except Exception as e:
            logger.exception(f"Error in handle_market_doctor_weights_list: {e}")
            await update.message.reply_text(
                f"❌ Ошибка при получении списка конфигураций: {str(e)}",
                parse_mode=ParseMode.MARKDOWN
            )
    
    async def handle_market_doctor_weights_reset(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработать команду /md_weights_reset - сброс к дефолтным весам."""
        try:
            from ...domain.market_diagnostics.scoring_engine import GROUP_WEIGHTS
            
            # Сохраняем дефолтные веса как активные
            self.weights_storage.save_weights(
                name="default",
                weights=GROUP_WEIGHTS,
                description="Дефолтные веса групп индикаторов",
                set_active=True
            )
            
            # Обновляем ReportBuilder
            self.report_builder = ReportBuilder(GROUP_WEIGHTS)
            
            await update.message.reply_text(
                "✅ Веса сброшены к дефолтным значениям.",
                parse_mode=ParseMode.MARKDOWN
            )
        
        except Exception as e:
            logger.exception(f"Error in handle_market_doctor_weights_reset: {e}")
            await update.message.reply_text(
                f"❌ Ошибка при сбросе весов: {str(e)}",
                parse_mode=ParseMode.MARKDOWN
            )
    
    async def handle_market_doctor_top(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработать команду /mdtop - топ сетапы."""
        try:
            from ...application.services.market_scanner_service import MarketScannerService
            
            # Парсим аргументы: /mdtop [limit] [min_pump] [max_risk]
            args = context.args or []
            limit = int(args[0]) if len(args) > 0 and args[0].isdigit() else 10
            min_pump = float(args[1]) if len(args) > 1 else 0.7
            max_risk = float(args[2]) if len(args) > 2 else 0.7
            
            # Отправляем сообщение о начале сканирования
            processing_msg = await update.effective_message.reply_text(
                f"🔍 Сканирую рынок для поиска топ-{limit} сетапов...",
                parse_mode=ParseMode.HTML
            )
            
            # Создаем сервис сканера
            scanner = MarketScannerService(self.db, self.config)
            
            # Получаем профиль пользователя для фильтрации по ликвидности
            user_id = update.effective_user.id if update.effective_user else None
            user_profile = None
            if user_id:
                profile = self.profile_provider.get_profile(user_id)
                user_profile = profile.value if profile else None
            
            # Сканируем рынок
            timeframes = ["4h", "1d"]
            candidates = await scanner.scan_universe(
                symbols=None,  # Используем DEFAULT_TOP_COINS
                timeframes=timeframes,
                min_pump_score=min_pump,
                max_risk_score=max_risk,
                limit=limit,
                filter_illiquid=True,
                user_profile=user_profile
            )
            
            # Формируем отчет
            report = scanner.format_top_setups_report(candidates, timeframes)
            
            # Отправляем отчет
            await processing_msg.edit_text(
                report,
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True
            )
        except Exception as e:
            logger.exception("handle_market_doctor_top failed")
            await self._safe_reply_text(
                update,
                f"❌ Ошибка при сканировании рынка: {str(e)}\n\n"
                "Использование: /mdtop [limit] [min_pump] [max_risk]\n"
                "Пример: /mdtop 10 0.7 0.7",
                parse_mode=ParseMode.HTML
            )
    
    async def _handle_single_tf_analysis(self, update: Update, context: ContextTypes.DEFAULT_TYPE, symbol: str, timeframe: str, trade_only: bool = False, brief: bool = False):
        """Обработать анализ для одного таймфрейма."""
        # Получаем конфигурацию для пользователя
        user_id = update.effective_user.id if update.effective_user else None
        user_config = self._get_user_config(user_id) if user_id else self.config
        
        # Кэшируем компоненты по user_id для избежания пересоздания
        cache_key = f"user_config_{user_id}" if user_id else "default"
        if not hasattr(self, '_component_cache'):
            self._component_cache = {}
        
        if cache_key not in self._component_cache or user_config != self.config:
            self._component_cache[cache_key] = {
                'indicator_calculator': IndicatorCalculator(user_config),
                'feature_extractor': FeatureExtractor(user_config),
                'market_analyzer': MarketAnalyzer(user_config),
                'trade_planner': TradePlanner(user_config),
            }
            self.config = user_config
        
        # Используем кэшированные компоненты
        cached = self._component_cache.get(cache_key, {})
        indicator_calculator = cached.get('indicator_calculator', self.indicator_calculator)
        feature_extractor = cached.get('feature_extractor', self.feature_extractor)
        market_analyzer = cached.get('market_analyzer', self.market_analyzer)
        trade_planner = cached.get('trade_planner', self.trade_planner)
        
        # Отправляем сообщение о начале анализа
        processing_msg = await update.effective_message.reply_text(
            f"🔍 Анализирую {symbol} на таймфрейме {timeframe}...",
            parse_mode=ParseMode.HTML
        )
        
        # Получаем OHLCV данные через сервис
        df = await self.data_service.get_ohlcv(symbol, timeframe, limit=500)
        
        # Fallback на старый метод если сервис не вернул данные
        if df is None or df.empty:
            logger.debug(f"MarketDataService did not return data, trying fallback method")
            df = self._get_ohlcv_data(symbol, timeframe)
        
        if df is None or df.empty:
            # Пробуем предложить альтернативные варианты символа
            variants = self.data_service._normalize_symbol(symbol) if hasattr(self.data_service, '_normalize_symbol') else self._normalize_symbol(symbol)
            variants_text = ", ".join(variants[:5])  # Показываем первые 5 вариантов
            
            # Формируем более информативное сообщение
            message = (
                f"❌ Не удалось получить данные для <b>{symbol}</b> на таймфрейме <b>{timeframe}</b>\n\n"
                f"Проверенные варианты: {variants_text}\n\n"
                "Возможные причины:\n"
                "• Символ не найден в базе данных и на TradingView\n"
                "• Недостаточно данных для выбранного таймфрейма\n"
                "• Символ может быть недоступен на Binance\n\n"
                "💡 Попробуйте:\n"
                "• Использовать полный тикер (например, AIAUSDT вместо AIA)\n"
                "• Проверить правильность написания символа\n"
                "• Использовать другой таймфрейм (например, 1h вместо 1d)"
            )
            
            await processing_msg.edit_text(
                message,
                parse_mode=ParseMode.HTML
            )
            return
        
        # Рассчитываем индикаторы
        indicators = indicator_calculator.calculate_all(df)
        
        # Получаем данные деривативов через сервис
        derivatives_snapshot = await self.data_service.get_derivatives(symbol, timeframe)
        derivatives = derivatives_snapshot.to_dict()
        
        # Извлекаем признаки
        features = feature_extractor.extract_features(df, indicators, derivatives)
        
        # Анализируем рынок
        diagnostics = market_analyzer.analyze(
            symbol=symbol,
            timeframe=timeframe,
            df=df,
            indicators=indicators,
            features=features,
            derivatives=derivatives
        )
        
        # Анализируем глобальный режим рынка
        regime_snapshot = self.regime_analyzer.analyze_current_regime()
        current_regime = regime_snapshot.regime
        
        # Получаем адаптивный порог pump_score для символа и режима
        effective_threshold = self.calibration_service.get_effective_pump_threshold(
            symbol, current_regime
        )
        
        # Анализируем ликвидность
        # Получаем актуальную текущую цену с биржи, а не из последней свечи
        try:
            from ...infrastructure.market_data import binance_spot_price
            symbol_usdt = f"{symbol}USDT" if not symbol.endswith("USDT") else symbol
            current_price = binance_spot_price(symbol_usdt)
        except Exception as e:
            logger.debug(f"Failed to get current price from Binance API: {e}, falling back to last candle close")
            # Fallback на последнюю цену закрытия из DataFrame
            current_price = float(df['close'].iloc[-1])
        volume_24h = None
        try:
            # Пробуем получить объем из extra_metrics или из БД
            if 'volume_24h' in diagnostics.extra_metrics:
                volume_24h = diagnostics.extra_metrics.get('volume_24h')
        except:
            pass
        
        tradability = self.tradability_analyzer.analyze_tradability(
            symbol, current_price, volume_24h
        )
        
        # Анализируем сентимент и новости
        sentiment_snapshot = None
        try:
            sentiment_snapshot = self.sentiment_analyzer.analyze_sentiment(symbol, hours_back=12)
        except Exception as e:
            logger.debug(f"Failed to analyze sentiment: {e}")
        
        # Определяем режим стратегии на основе профиля пользователя
        strategy_mode = "auto"
        position_base_factor = 1.0
        if user_id:
            default_mode = self.profile_provider.get_strategy_mode_for_user(user_id)
            if default_mode != "auto":
                strategy_mode = default_mode
            
            # Получаем базовый коэффициент размера позиции для профиля
            from ...domain.market_diagnostics.profile_provider import RiskProfile
            profile = self.profile_provider.get_profile(user_id)
            position_base_factor = RiskProfile.get_position_size_factor(
                profile, diagnostics.pump_score, diagnostics.risk_score
            )
        
        # Генерируем pattern_id и reliability_score (нужно до использования в _calculate_position_size)
        # Получаем structure из features (он не сохраняется в MarketDiagnostics)
        structure_str = features.get('structure', 'RANGE')
        if hasattr(structure_str, 'value'):
            structure_str = structure_str.value
        else:
            structure_str = str(structure_str)
        
        pattern_id = generate_pattern_id(
            diagnostics.phase,
            diagnostics.trend,
            structure_str,
            current_regime
        )
        
        reliability_score = None
        reliability_samples = None
        try:
            reliability_score, reliability_samples = self.calibration_service.get_reliability_score_with_samples(pattern_id)
        except Exception as e:
            logger.debug(f"Failed to get reliability score: {e}")
            try:
                # Fallback на старый метод
                reliability_score = self.calibration_service.get_reliability_score(pattern_id)
            except:
                pass
        
        # Строим торговый план с учетом режима рынка
        trade_plan = self.trade_planner.build_plan(
            diagnostics, df, indicators, mode=strategy_mode, regime=current_regime
        )
        
        # Обновляем position_size_factor с учетом профиля пользователя, режима, reliability и ликвидности
        if user_id:
            # Пересчитываем с учетом профиля, режима, reliability и ликвидности
            factor, comment = trade_planner._calculate_position_size(
                diagnostics, strategy_mode, position_base_factor,
                regime=current_regime,
                reliability_score=reliability_score,
                tradability_state=tradability.state.value if tradability else None,
                size_at_10bps=tradability.size_at_10bps if tradability else None
            )
            trade_plan.position_size_factor = factor
            trade_plan.position_size_comment = comment
        
        # Сохраняем снимок диагностики для валидации
        try:
            from ...infrastructure.repositories.diagnostics_repository import DiagnosticsSnapshot
            import time
            
            # Подготавливаем метрики по уровням и SMC для backtest анализа
            levels_metrics = {}
            smc_metrics = {}
            
            if diagnostics.key_levels:
                # Расстояние до ближайших уровней
                support_levels = [lvl for lvl in diagnostics.key_levels if lvl.kind.value in ['support', 'orderblock_demand'] and lvl.price < current_price]
                resistance_levels = [lvl for lvl in diagnostics.key_levels if lvl.kind.value in ['resistance', 'liquidity_high', 'orderblock_supply'] and lvl.price > current_price]
                
                if support_levels:
                    nearest_support = max(support_levels, key=lambda l: l.price)
                    levels_metrics['distance_to_support_pct'] = ((current_price - nearest_support.price) / current_price) * 100
                    levels_metrics['nearest_support_price'] = nearest_support.price
                    levels_metrics['nearest_support_strength'] = nearest_support.strength
                
                if resistance_levels:
                    nearest_resistance = min(resistance_levels, key=lambda l: l.price)
                    levels_metrics['distance_to_resistance_pct'] = ((nearest_resistance.price - current_price) / current_price) * 100
                    levels_metrics['nearest_resistance_price'] = nearest_resistance.price
                    levels_metrics['nearest_resistance_strength'] = nearest_resistance.strength
            
            if diagnostics.smc_context:
                smc = diagnostics.smc_context
                
                # Order blocks метрики
                if smc.order_blocks_demand:
                    demand_below = [ob for ob in smc.order_blocks_demand if ob.price_high < current_price]
                    if demand_below:
                        nearest_demand = max(demand_below, key=lambda ob: ob.price_high)
                        smc_metrics['has_demand_ob_below'] = True
                        smc_metrics['distance_to_demand_ob_pct'] = ((current_price - nearest_demand.price_high) / current_price) * 100
                        smc_metrics['demand_ob_strength'] = nearest_demand.strength
                    else:
                        smc_metrics['has_demand_ob_below'] = False
                else:
                    smc_metrics['has_demand_ob_below'] = False
                
                # Premium/Discount метрики
                if smc.premium_zone_start and smc.discount_zone_end:
                    smc_metrics['premium_zone_start'] = smc.premium_zone_start
                    smc_metrics['discount_zone_end'] = smc.discount_zone_end
                    smc_metrics['current_position'] = smc.current_position
                    
                    # Вычисляем позицию внутри диапазона (0-1, где 0 = discount, 1 = premium)
                    range_size = smc.premium_zone_start - smc.discount_zone_end
                    if range_size > 0:
                        position_in_range = (current_price - smc.discount_zone_end) / range_size
                        smc_metrics['position_in_range'] = max(0.0, min(1.0, position_in_range))
                
                # Liquidity pools метрики
                if smc.main_liquidity_above:
                    smc_metrics['distance_to_liquidity_above_pct'] = ((smc.main_liquidity_above - current_price) / current_price) * 100
                    smc_metrics['liquidity_above_price'] = smc.main_liquidity_above
                
                if smc.main_liquidity_below:
                    smc_metrics['distance_to_liquidity_below_pct'] = ((current_price - smc.main_liquidity_below) / current_price) * 100
                    smc_metrics['liquidity_below_price'] = smc.main_liquidity_below
                
                # BOS метрики
                if smc.last_bos:
                    smc_metrics['has_bos'] = True
                    smc_metrics['bos_direction'] = smc.last_bos.direction
                    smc_metrics['bos_strength'] = smc.last_bos.strength
                else:
                    smc_metrics['has_bos'] = False
            
            snapshot = DiagnosticsSnapshot(
                timestamp=int(time.time() * 1000),
                symbol=symbol,
                timeframe=timeframe,
                phase=diagnostics.phase.value,
                trend=diagnostics.trend.value,
                volatility=diagnostics.volatility.value,
                liquidity=diagnostics.liquidity.value,
                structure=structure_str,
                pump_score=diagnostics.pump_score,
                risk_score=diagnostics.risk_score,
                close_price=current_price,
                strategy_mode=trade_plan.mode,
                extra_metrics={
                    "indicators": {k: float(v.iloc[-1]) if hasattr(v, 'iloc') else float(v) for k, v in indicators.items() if v is not None},
                    "features": {k: float(v) if isinstance(v, (int, float)) else str(v) for k, v in features.items()},
                    "regime": current_regime.value,
                    "effective_threshold": effective_threshold,
                    "tradability": {
                        "spread_bps": tradability.spread_bps,
                        "size_at_10bps": tradability.size_at_10bps,
                        "state": tradability.state.value
                    },
                    "levels": levels_metrics,
                    "smc": smc_metrics
                },
                pattern_id=pattern_id,
                reliability_score=reliability_score
            )
            self.diagnostics_repo.save_snapshot(snapshot)
        except Exception as e:
            logger.warning(f"Failed to save diagnostics snapshot: {e}", exc_info=True)
        
        # Проверяем аномалии
        anomalies = []
        try:
            # Используем уже полученную актуальную цену с биржи (current_price определена выше)
            anomalies = self.anomaly_detector.detect_all_anomalies(
                symbol, timeframe, diagnostics, derivatives, current_price
            )
        except Exception as e:
            logger.debug(f"Failed to detect anomalies: {e}")
        
        # Добавляем информацию о режиме рынка, ликвидности и сентименте в trade_plan
        trade_plan.regime_info = regime_snapshot.description
        trade_plan.tradability_info = tradability.get_description()
        trade_plan.effective_threshold = effective_threshold
        trade_plan.reliability_score = reliability_score
        trade_plan.reliability_samples = reliability_samples
        if sentiment_snapshot:
            trade_plan.sentiment_info = sentiment_snapshot.get_description()
        
        # Получаем бэктест статистику для паттерна
        try:
            phase_trend_key = f"{diagnostics.phase.value}_{diagnostics.trend.value}"
            backtest_stats = self.backtest_analyzer.analyze_phase_trend_distribution(
                symbol=symbol,
                timeframe=timeframe,
                hours=24
            )
            if phase_trend_key in backtest_stats:
                trade_plan.backtest_stats = backtest_stats[phase_trend_key]
        except Exception as e:
            logger.debug(f"Failed to get backtest stats: {e}")
        
        # Адаптируем risk_score на основе негативных новостей
        if sentiment_snapshot and sentiment_snapshot.has_significant_news:
            if sentiment_snapshot.overall_sentiment.value == "negative":
                # Увеличиваем risk_score при негативных новостях
                diagnostics.risk_score = min(1.0, diagnostics.risk_score + 0.15)
                logger.debug(f"Increased risk_score due to negative news: {diagnostics.risk_score}")
        
        # Генерируем отчет в зависимости от режима
        # ВСЕГДА используем новый компактный формат с генератором v2
        use_compact_format = True  # Всегда используем компактный формат
        
        if use_compact_format and not trade_only:
            # Новый компактный формат
            try:
                logger.info(f"Building compact report: symbol={symbol}, tf={timeframe}, brief={brief}")
                compact_report = self.report_builder.build_compact_report(
                    symbol=symbol,
                    target_tf=timeframe,
                    diagnostics={timeframe: diagnostics},
                    indicators={timeframe: indicators},
                    features={timeframe: features},
                    derivatives={timeframe: derivatives},
                    trade_plan=trade_plan,
                    current_price=current_price
                )
                logger.info(f"Compact report built: per_tf_count={len(compact_report.per_tf)}, per_tf_keys={list(compact_report.per_tf.keys())}")
                
                # Устанавливаем brief_mode в compact_report
                compact_report.brief_mode = brief
                
                # Используем NLG для single-TF отчетов
                # Используем новый генератор v2 (без дубликатов, унифицированный bias) по умолчанию
                use_v2 = context.user_data.get('md_use_v2', True)  # По умолчанию True (включен)
                logger.info(f"Rendering report: symbol={symbol}, tf={timeframe}, use_v2={use_v2}, use_nlg=True, brief={brief}, per_tf_count={len(compact_report.per_tf)}")
                
                report = self.compact_renderer.render(compact_report, use_nlg=True, use_v2=use_v2)
                
                # Проверяем, что отчёт действительно от v2 генератора
                if "🏥 Market Doctor" in report and "🎯 Решение:" in report and "🧠 Режим рынка" in report:
                    logger.info(f"✓ V2 generator confirmed! Report length: {len(report)}, starts with: {report[:150]}")
                elif "📦 Фаза:" in report or "Монета:" in report:
                    logger.error(f"✗ OLD FORMAT DETECTED! Report starts with: {report[:200]}")
                    logger.error("This means V2 generator failed and fell back to old format")
                    logger.error("Check logs above for V2 generator errors")
                else:
                    logger.warning(f"⚠ Unknown format! Report starts with: {report[:200]}")
            except Exception as e:
                logger.error(f"Failed to generate compact report: {e}", exc_info=True)
                logger.error(f"Exception type: {type(e).__name__}, args: {e.args}")
                logger.error(f"Stack trace:")
                import traceback
                logger.error(traceback.format_exc())
                # НЕ используем старый формат - это критическая ошибка
                # Вместо этого пробуем ещё раз с минимальными настройками
                try:
                    logger.warning("Retrying with minimal settings...")
                    compact_report.brief_mode = False
                    report = self.compact_renderer.render(compact_report, use_nlg=True, use_v2=False)
                    if "🏥 Market Doctor" in report:
                        logger.info("Retry successful with NLG format")
                    else:
                        raise RuntimeError("Retry also failed")
                except Exception as retry_error:
                    logger.error(f"Retry also failed: {retry_error}")
                    # Только в крайнем случае используем старый формат
                    logger.error("CRITICAL: All report generation methods failed, using old format as last resort")
                    report = self.report_renderer.render_report(diagnostics, trade_plan, timeframe=timeframe)
        elif trade_only:
            report = self.report_renderer.render_trade_only(diagnostics, trade_plan)
        else:
            report = self.report_renderer.render_report(diagnostics, trade_plan, timeframe=timeframe)
        
        # Добавляем аномалии в отчет, если есть
        if anomalies:
            anomaly_messages = [alert.message for alert in anomalies if alert.severity in ["medium", "high"]]
            if anomaly_messages:
                report += "\n\n" + "\n".join(anomaly_messages)
        
        # Отправляем отчет (с разбиением на части, если слишком длинный)
        await self._send_long_message(
            update,
            message_to_edit=processing_msg,
            text=report,
            max_length=4000,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True
        )
    
    async def _handle_multi_tf_analysis(self, update: Update, symbol: str, timeframes: list[str], brief: bool = False):
        """Обработать анализ для нескольких таймфреймов."""
        # Отправляем сообщение о начале анализа
        processing_msg = await update.effective_message.reply_text(
            f"🔍 Анализирую {symbol} на таймфреймах: {', '.join(timeframes)}...",
            parse_mode=ParseMode.HTML
        )
        
        # Используем новый Multi-TF анализатор
        timeframes_data = {}
        trade_plans = {}
        
        # Получаем данные деривативов один раз для всех ТФ
        derivatives_snapshot = await self.data_service.get_derivatives(symbol, "1h")
        derivatives = derivatives_snapshot.to_dict()
        
        # Собираем данные по всем таймфреймам
        for tf in timeframes:
            df = await self.data_service.get_ohlcv(symbol, tf, limit=500)
            
            if df is None or df.empty:
                continue
            
            # Рассчитываем индикаторы
            indicators = self.indicator_calculator.calculate_all(df)
            
            # Извлекаем признаки
            features = self.feature_extractor.extract_features(df, indicators, derivatives)
            
            # Сохраняем данные для multi-TF анализа
            timeframes_data[tf] = {
                "df": df,
                "indicators": indicators,
                "features": features
            }
        
        if not timeframes_data:
            await processing_msg.edit_text(
                f"❌ Не удалось получить данные для {symbol} ни на одном из таймфреймов.",
                parse_mode=ParseMode.HTML
            )
            return
        
        # Анализируем multi-TF
        multi_diag = self.market_analyzer.analyze_multi(symbol, timeframes_data, derivatives)
        
        # Строим торговые планы для каждого ТФ
        for tf in timeframes:
            if tf not in timeframes_data:
                continue
            
            df = timeframes_data[tf]["df"]
            indicators = timeframes_data[tf]["indicators"]
            diag = multi_diag.snapshots[tf]
            
            # Строим торговый план для этого ТФ
            trade_plan = self.trade_planner.build_plan(diag, df, indicators, mode="auto")
            trade_plans[tf] = trade_plan
        
        # Анализируем сентимент для multi-TF (один раз для символа)
        sentiment_snapshot = None
        try:
            sentiment_snapshot = self.sentiment_analyzer.analyze_sentiment(symbol, hours_back=12)
        except Exception as e:
            logger.debug(f"Failed to analyze sentiment: {e}")
        
        # Генерируем отчет в зависимости от режима
        if brief:
            # Краткий отчет - используем render_brief для каждого ТФ
            brief_reports = []
            for tf in timeframes:
                if tf in multi_diag.snapshots:
                    diag = multi_diag.snapshots[tf]
                    plan = trade_plans.get(tf)
                    brief_reports.append(self.report_renderer.render_brief(diag, plan))
            report = "\n\n".join(brief_reports)
        else:
            # Полный отчет - используем новый компактный формат для multi-TF
            try:
                # Собираем данные для компактного отчёта
                diagnostics_dict = {tf: multi_diag.snapshots[tf] for tf in timeframes if tf in multi_diag.snapshots}
                indicators_dict = {tf: timeframes_data[tf]["indicators"] for tf in timeframes if tf in timeframes_data}
                features_dict = {tf: timeframes_data[tf]["features"] for tf in timeframes if tf in timeframes_data}
                derivatives_dict = {tf: derivatives for tf in timeframes}  # Одинаковые для всех ТФ
                
                # Используем первый таймфрейм как target
                target_tf = timeframes[0] if timeframes else "1h"
                # Получаем актуальную текущую цену с биржи
                try:
                    from ...infrastructure.market_data import binance_spot_price
                    symbol_usdt = f"{symbol}USDT" if not symbol.endswith("USDT") else symbol
                    current_price = binance_spot_price(symbol_usdt)
                except Exception as e:
                    logger.debug(f"Failed to get current price from Binance API in multi-TF: {e}, falling back to last candle close")
                    # Fallback на последнюю цену закрытия из DataFrame
                    current_price = timeframes_data[target_tf]["df"]["close"].iloc[-1] if target_tf in timeframes_data else None
                
                # Строим компактный отчёт
                compact_report = self.report_builder.build_compact_report(
                    symbol=symbol,
                    target_tf=target_tf,
                    diagnostics=diagnostics_dict,
                    indicators=indicators_dict,
                    features=features_dict,
                    derivatives=derivatives_dict,
                    trade_plan=trade_plans.get(target_tf),
                    current_price=current_price
                )
                # Используем NLG для single-TF отчетов
                # Используем новый генератор v2 (без дубликатов, унифицированный bias) по умолчанию
                use_v2 = context.user_data.get('md_use_v2', True)  # По умолчанию True (включен)
                logger.info(f"Rendering multi-TF report: symbol={symbol}, use_v2={use_v2}, brief={brief}")
                report = self.compact_renderer.render(compact_report, use_nlg=True, use_v2=use_v2)
            except Exception as e:
                logger.warning(f"Failed to generate compact multi-TF report, falling back to standard format: {e}", exc_info=True)
                # Fallback на старый формат
                report = self.report_renderer.render_multi_tf(multi_diag, trade_plans)
        
        # Добавляем информацию о сентименте в multi-TF отчет
        if sentiment_snapshot:
            report += f"\n\n{sentiment_snapshot.get_description()}"
        
        # Отправляем отчет (с разбиением на части, если слишком длинный)
        await self._send_long_message(
            update,
            message_to_edit=processing_msg,
            text=report,
            max_length=4000,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True
        )
    
    def _get_phase_emoji(self, phase) -> str:
        """Получить эмодзи для фазы."""
        emoji_map = {
            "ACCUMULATION": "📦",
            "DISTRIBUTION": "📤",
            "EXPANSION_UP": "🚀",
            "EXPANSION_DOWN": "📉",
            "SHAKEOUT": "⚡"
        }
        return emoji_map.get(phase.value, "📊")
    
    def _get_trend_emoji(self, trend) -> str:
        """Получить эмодзи для тренда."""
        emoji_map = {
            "BULLISH": "🟢",
            "BEARISH": "🔴",
            "NEUTRAL": "🟡"
        }
        return emoji_map.get(trend.value, "⚪")
    
    def _get_volatility_emoji(self, volatility) -> str:
        """Получить эмодзи для волатильности."""
        emoji_map = {
            "LOW": "🔵",
            "MEDIUM": "🟡",
            "HIGH": "🔴"
        }
        return emoji_map.get(volatility.value, "⚪")
    
    def _normalize_symbol(self, symbol: str) -> list[str]:
        """
        Нормализовать символ и вернуть список возможных вариантов для поиска.
        
        Args:
            symbol: Символ монеты (например, TIA, BTC, ETHUSDT, AIA)
        
        Returns:
            Список вариантов символа для поиска
        """
        symbol = symbol.upper().strip().replace("/", "").replace("-", "")
        variants = []
        
        # Если уже есть формат EXCHANGE:SYMBOL, используем как есть
        if ":" in symbol:
            variants.append(symbol)
            return variants
        
        # Добавляем оригинальный символ
        variants.append(symbol)
        
        # Если символ короткий (до 5 символов), пробуем добавить USDT
        if len(symbol) <= 5 and not symbol.endswith("USDT"):
            variants.append(f"{symbol}USDT")
            # Для Binance perpetual контракты имеют суффикс .P
            variants.append(f"{symbol}USDT.P")
        
        # Если символ заканчивается на USDT, пробуем без USDT
        if symbol.endswith("USDT"):
            base = symbol[:-4]
            if len(base) <= 5:
                variants.insert(0, base)  # Добавляем в начало
            # Если это не perpetual (.P), пробуем добавить .P
            if not symbol.endswith(".P"):
                variants.append(f"{symbol}.P")
        
        # Если символ заканчивается на .P, пробуем без .P
        if symbol.endswith(".P"):
            base = symbol[:-2]
            if base not in variants:
                variants.insert(0, base)  # Добавляем вариант без .P в начало
        
        # Для TradingView пробуем разные форматы бирж
        # Сначала пробуем Binance (наиболее популярная)
        for v in variants[:]:  # Копируем список для итерации
            if ":" not in v:  # Не добавляем если уже есть биржа
                variants.append(f"BINANCE:{v}")
                # Для Binance также пробуем perpetual формат
                if not v.endswith(".P") and not v.endswith("USDT"):
                    variants.append(f"BINANCE:{v}USDT.P")
        
        # Убираем дубликаты, сохраняя порядок
        seen = set()
        unique_variants = []
        for v in variants:
            if v not in seen:
                seen.add(v)
                unique_variants.append(v)
        
        return unique_variants
    
    def _get_ohlcv_data(self, symbol: str, timeframe: str) -> pd.DataFrame:
        """
        Получить OHLCV данные для символа.
        
        Args:
            symbol: Символ монеты (например, BTC, ETHUSDT, TIA)
            timeframe: Таймфрейм (1h, 4h, 1d)
        
        Returns:
            DataFrame с колонками ['open', 'high', 'low', 'close', 'volume']
        """
        # Получаем варианты символа для поиска
        symbol_variants = self._normalize_symbol(symbol)
        
        # Сначала пробуем получить из БД с разными вариантами символа
        for sym_variant in symbol_variants:
            try:
                rows = self.db.last_n(sym_variant, timeframe, 500)
                if rows:
                    # Преобразуем в DataFrame
                    data = []
                    for ts, o, h, l, c, v in rows:
                        data.append({
                            'ts': ts,
                            'open': float(o),
                            'high': float(h),
                            'low': float(l),
                            'close': float(c),
                            'volume': float(v) if v is not None else None
                        })
                    
                    df = pd.DataFrame(data)
                    
                    # Сортируем по времени
                    df = df.sort_values('ts')
                    
                    # Устанавливаем индекс времени
                    df['ts'] = pd.to_datetime(df['ts'], unit='ms')
                    df = df.set_index('ts')
                    
                    return df[['open', 'high', 'low', 'close', 'volume']]
            except Exception:
                continue
        
        # Если данных нет в БД, пробуем через data_adapter (с fallback на TradingView)
        for sym_variant in symbol_variants:
            try:
                from ...ml.data_adapter import load_bars_from_project
                df = load_bars_from_project(sym_variant, timeframe, limit=500)
                if df is not None and not df.empty:
                    # data_adapter возвращает DataFrame с колонкой 'ts' или индексом времени
                    # Нормализуем формат DataFrame
                    if 'ts' in df.columns:
                        # Преобразуем ts в datetime если нужно
                        if not pd.api.types.is_datetime64_any_dtype(df['ts']):
                            df['ts'] = pd.to_datetime(df['ts'], unit='ms', errors='coerce')
                        df = df.set_index('ts')
                    elif isinstance(df.index, pd.DatetimeIndex):
                        pass  # Уже правильный индекс
                    elif df.index.name == 'ts':
                        # Индекс уже называется ts, но может быть не datetime
                        if not pd.api.types.is_datetime64_any_dtype(df.index):
                            df.index = pd.to_datetime(df.index, unit='ms', errors='coerce')
                    else:
                        # Пытаемся найти колонку времени
                        for col in ['datetime', 'time', 'timestamp', 'ts']:
                            if col in df.columns:
                                df[col] = pd.to_datetime(df[col], unit='ms', errors='coerce')
                                df = df.set_index(col)
                                break
                    
                    # Убеждаемся, что есть нужные колонки
                    required_cols = ['open', 'high', 'low', 'close', 'volume']
                    if all(col in df.columns for col in required_cols):
                        # Удаляем строки с NaN в критических колонках
                        df = df.dropna(subset=['open', 'high', 'low', 'close'])
                        if not df.empty:
                            logger.info(f"Successfully loaded {sym_variant} {timeframe} via data_adapter ({len(df)} bars)")
                            return df[required_cols]
            except FileNotFoundError:
                # Это нормально - символ не найден, пробуем следующий вариант
                logger.debug(f"Symbol {sym_variant} not found via data_adapter")
                continue
            except Exception as e:
                logger.debug(f"Failed to load {sym_variant} {timeframe} via data_adapter: {e}")
                continue
        
        # Если ничего не получилось
        logger.warning(f"Could not get OHLCV data for any variant of {symbol} {timeframe}. Tried: {symbol_variants}")
        return pd.DataFrame()
    
    def _get_derivatives_data(self, symbol: str) -> dict:
        """
        Получить данные деривативов для символа.
        
        Args:
            symbol: Символ монеты
        
        Returns:
            Словарь с данными деривативов (funding_rate, oi_change_pct, cvd)
        """
        derivatives = {}
        
        try:
            # Нормализуем символ для Binance (добавляем USDT если нужно)
            binance_symbol = symbol.upper()
            if not binance_symbol.endswith('USDT'):
                # Пробуем добавить USDT
                binance_symbol = f"{binance_symbol}USDT"
            
            # Получаем funding rate из Binance
            try:
                from ...infrastructure.market_data import binance_funding_and_mark
                funding_data = binance_funding_and_mark(binance_symbol)
                derivatives['funding_rate'] = funding_data.get('fundingRate', 0.0)
            except Exception as e:
                logger.debug(f"Could not get funding rate for {binance_symbol}: {e}")
                derivatives['funding_rate'] = 0.0
            
            # Получаем OI и CVD из CoinGlass
            try:
                # Ленивый импорт для внешних API вызовов
                from ...infrastructure.derivatives_client import get_oi_and_cvd
                oi_cvd_data = get_oi_and_cvd(symbol)
                derivatives['oi_change_pct'] = oi_cvd_data.get('oi_change_pct', 0.0)
                derivatives['cvd'] = oi_cvd_data.get('cvd', 0.0)
            except Exception as e:
                logger.debug(f"Could not get OI/CVD from CoinGlass for {symbol}: {e}")
                derivatives['oi_change_pct'] = 0.0
                derivatives['cvd'] = 0.0
            
        except Exception as e:
            logger.debug(f"Error getting derivatives data for {symbol}: {e}")
        
        return derivatives

