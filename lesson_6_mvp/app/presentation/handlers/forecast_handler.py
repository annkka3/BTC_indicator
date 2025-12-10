# app/presentation/handlers/forecast_handler.py
"""
Handler for forecast commands.
"""

from telegram import Update
from telegram.ext import ContextTypes
from telegram.constants import ParseMode
from .base_handler import BaseHandler
from ...infrastructure.ui_keyboards import DEFAULT_TF
import logging

logger = logging.getLogger("alt_forecast.handlers.forecast")


class ForecastHandler(BaseHandler):
    """Обработчик команд прогнозов."""
    
    def __init__(self, db, services: dict):
        super().__init__(db, services)
        self.forecast_service = services.get("forecast_service")
    
    def _resolve_tf(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> str:
        """Определить таймфрейм из контекста."""
        args = context.args or []
        if args and args[0] in ("15m", "1h", "4h", "1d", "24h"):
            tf = args[0]
            # Нормализуем 24h -> 1d для совместимости
            if tf == "24h":
                tf = "1d"
            return tf
        
        tf = context.user_data.get('tf', DEFAULT_TF)
        # Нормализуем 24h -> 1d для совместимости
        if tf == "24h":
            tf = "1d"
        return tf
    
    async def handle_forecast(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработать команду /forecast (краткий прогноз BTC)."""
        try:
            from ...infrastructure.ui_keyboards import build_kb
            
            tf = self._resolve_tf(update, context)
            horizon = 24
            
            # Показываем сообщение о загрузке
            loading_msg = await update.effective_message.reply_text(
                "⏳ Генерирую прогноз...",
                parse_mode=ParseMode.HTML
            )
            
            forecast = self.forecast_service.forecast_btc(tf, horizon)
            
            if not forecast:
                await loading_msg.edit_text(
                    "❌ Не удалось сгенерировать прогноз. Попробуйте позже.",
                    parse_mode=ParseMode.HTML
                )
                return
            
            # Получаем текущую цену из прогноза (она уже сохранена из 5m бара)
            current_price = forecast.get("current_price")
            if not current_price:
                # Fallback: получаем цену из БД если её нет в прогнозе
                try:
                    rows_5m = self.db.last_n("BTC", "5m", 1)
                    if rows_5m:
                        current_price = float(rows_5m[0][4])  # close из последнего 5m бара
                    else:
                        rows = self.db.last_n("BTC", tf, 1)
                        current_price = float(rows[0][4]) if rows else 0.0
                except Exception:
                    current_price = 0.0
            
            # Классифицируем сетап
            from ...domain.market_diagnostics.setup_type import classify_setup
            
            # Получаем глобальный режим (если доступен)
            global_regime = None
            try:
                from ...domain.market_regime.global_regime_analyzer import GlobalRegimeAnalyzer
                regime_analyzer = GlobalRegimeAnalyzer(self.db)
                regime_snapshot = regime_analyzer.analyze_current_regime()
                if regime_snapshot:
                    global_regime = regime_snapshot.regime.value if hasattr(regime_snapshot.regime, 'value') else str(regime_snapshot.regime)
            except Exception:
                pass
            
            setup_class = classify_setup(
                predicted_return=forecast["predicted_return"],
                probability_up=forecast["probability_up"],
                confidence_interval_68=forecast.get("confidence_interval_68"),
                confidence_interval_95=forecast.get("confidence_interval_95"),
                global_regime=global_regime,
                momentum_grade=None,  # Можно получить из multi_tf_score если доступен
                momentum_strength=None
            )
            
            # Для прогнозов показываем все Grade (фильтрация только для Market Doctor)
            # Прогнозы - это информационные сообщения, а не торговые сигналы
            # Фильтрация по Grade применяется только в Market Doctor для торговых рекомендаций
            
            # Формируем сообщение
            ret_pct = forecast["predicted_return"] * 100
            p_up = forecast["probability_up"]
            
            regime = (
                "🟢 бычий" if (p_up >= 0.6 and forecast["predicted_return"] > 0)
                else "🔴 медвежий" if (p_up <= 0.4 and forecast["predicted_return"] < 0)
                else "⚪ нейтральный"
            )
            
            # Определяем режим детализации
            detail_mode = context.user_data.get("detail_mode", "standard")  # tldr, standard, deep
            
            # Добавляем информацию о сетапе
            setup_info = f"Grade {setup_class.grade} • {setup_class.setup_type.value}"
            
            # Индикатор модели
            model_type = forecast.get("model_type", "Unknown")
            if model_type == "CatBoost":
                model_indicator = "🤖 <i>ML</i>"
                model_badge = "✨"
            elif model_type == "Legacy":
                model_indicator = "📊 <i>Legacy</i>"
                model_badge = ""
            else:
                model_indicator = f"<i>{model_type}</i>"
                model_badge = ""
            
            # Формируем текст в зависимости от режима детализации
            if detail_mode == "tldr":
                # TL;DR: одна фраза + стрелка + Grade
                arrow = "📈" if forecast["predicted_return"] > 0 else "📉" if forecast["predicted_return"] < 0 else "➡️"
                text = (
                    f"{arrow} <b>Прогноз BTC ({tf})</b>\n"
                    f"{ret_pct:+.2f}% | P(up) {p_up:.0%} | Grade {setup_class.grade}\n"
                    f"Цена: ${forecast['target_price']:,.0f}"
                )
            elif detail_mode == "deep":
                # Deep Dive: подробный расклад с объяснением
                from ...ml.forecast_explainer import explain_forecast, format_explanation
                from ...domain.market_diagnostics.calibration_service import CalibrationService
                
                # Получаем дополнительные данные для объяснения
                global_regime_val = None
                try:
                    from ...domain.market_regime.global_regime_analyzer import GlobalRegimeAnalyzer
                    regime_analyzer = GlobalRegimeAnalyzer(self.db)
                    regime_snapshot = regime_analyzer.analyze_current_regime()
                    if regime_snapshot:
                        global_regime_val = regime_snapshot.regime.value if hasattr(regime_snapshot.regime, 'value') else str(regime_snapshot.regime)
                except Exception as e:
                    logger.debug(f"Failed to get global regime: {e}")
                    global_regime_val = None
                
                # Объясняем прогноз
                factors = explain_forecast(
                    predicted_return=forecast["predicted_return"],
                    probability_up=p_up,
                    momentum_grade=None,  # Можно получить из multi_tf_score
                    momentum_strength=None,
                    global_regime=global_regime_val,
                    pump_score=None,  # Можно получить из diagnostics
                    risk_score=None,
                    setup_type=setup_class.setup_type.value,
                    grade=setup_class.grade,
                    confidence_interval_68=forecast.get("confidence_interval_68"),
                    liquidity_state=None
                )
                
                explanation = format_explanation(factors, forecast["predicted_return"])
                
                # Получаем статистику по типу сетапа
                setup_stats = None
                try:
                    calibration_service = CalibrationService(self.db)
                    setup_stats = calibration_service.get_setup_type_stats(
                        "BTC", tf, horizon,
                        setup_type=setup_class.setup_type.value,
                        grade=setup_class.grade
                    )
                except Exception as e:
                    logger.debug(f"Failed to get setup stats: {e}")
                
                stats_text = ""
                if setup_stats:
                    stats_text = (
                        f"\n\n📊 <b>Историческая статистика:</b>\n"
                        f"E[R]: {setup_stats['avg_return']*100:+.2f}% | "
                        f"Hit-rate: {setup_stats['hit_rate']:.1%}\n"
                        f"ES: {setup_stats['expected_shortfall']*100:+.2f}% | "
                        f"VaR(5%): {setup_stats['var_5']*100:+.2f}%"
                    )
                
                text = (
                    f"<b>📊 Прогноз BTC ({tf}, +{horizon} бар)</b> {model_badge}\n"
                    f"{model_indicator}\n\n"
                    f"Текущая цена: <b>${current_price:,.2f}</b>\n"
                    f"Ожидаемое изменение: <b>{ret_pct:+.2f}%</b>\n"
                    f"Вероятность роста: <b>{p_up:.1%}</b>\n"
                    f"Целевая цена: <b>${forecast['target_price']:,.2f}</b>\n"
                    f"Режим: <b>{regime}</b>\n"
                    f"Сетап: <b>{setup_info}</b>\n"
                    f"<i>{setup_class.comment}</i>\n\n"
                    f"{explanation}"
                    f"{stats_text}"
                )
            else:
                # Standard: текущий вид
                text = (
                    f"<b>📊 Прогноз BTC ({tf}, +{horizon} бар)</b> {model_badge}\n"
                    f"{model_indicator}\n\n"
                    f"Текущая цена: <b>${current_price:,.2f}</b>\n"
                    f"Ожидаемое изменение: <b>{ret_pct:+.2f}%</b>\n"
                    f"Вероятность роста: <b>{p_up:.1%}</b>\n"
                    f"Целевая цена: <b>${forecast['target_price']:,.2f}</b>\n"
                    f"Режим: <b>{regime}</b>\n"
                    f"Сетап: <b>{setup_info}</b>\n"
                    f"<i>{setup_class.comment}</i>"
                )
            
            await loading_msg.edit_text(
                text,
                parse_mode=ParseMode.HTML,
                reply_markup=build_kb("main")
            )
        except Exception as e:
            logger.exception(f"handle_forecast failed: {e}")
            try:
                from ...infrastructure.ui_keyboards import build_kb
                await update.effective_message.reply_text(
                    f"❌ Ошибка при генерации прогноза: {str(e)[:100]}",
                    reply_markup=build_kb("main")
                )
            except Exception:
                pass
    
    async def handle_forecast_full(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработать команду /forecast_full (полный прогноз BTC)."""
        try:
            from ...infrastructure.ui_keyboards import build_kb
            
            tf = self._resolve_tf(update, context)
            horizon = 24
            
            # Показываем сообщение о загрузке
            try:
                loading_msg = await update.effective_message.reply_text(
                    "⏳ Генерирую полный прогноз...",
                    parse_mode=ParseMode.HTML
                )
            except Exception:
                loading_msg = None
            
            forecast = self.forecast_service.forecast_btc(tf, horizon)
            if not forecast:
                error_text = "Не удалось сгенерировать прогноз. Попробуйте позже."
                if loading_msg:
                    try:
                        await loading_msg.edit_text(error_text, parse_mode=ParseMode.HTML)
                    except Exception:
                        await update.effective_message.reply_text(error_text, parse_mode=ParseMode.HTML)
                else:
                    await update.effective_message.reply_text(error_text, parse_mode=ParseMode.HTML)
                return
            
            # Получаем текущую цену из прогноза (она уже сохранена из 5m бара)
            current_price = forecast.get("current_price")
            if not current_price:
                # Fallback: получаем цену из БД если её нет в прогнозе
                try:
                    rows_5m = self.db.last_n("BTC", "5m", 1)
                    if rows_5m:
                        current_price = float(rows_5m[0][4])  # close из последнего 5m бара
                    else:
                        rows = self.db.last_n("BTC", tf, 1)
                        current_price = float(rows[0][4]) if rows else 0.0
                except Exception:
                    current_price = 0.0
            
            # Формируем полное сообщение
            regime = (
                "🟢 бычий" if (forecast["probability_up"] >= 0.6 and forecast["predicted_return"] > 0)
                else "🔴 медвежий" if (forecast["probability_up"] <= 0.4 and forecast["predicted_return"] < 0)
                else "⚪ нейтральный"
            )
            
            ci68 = forecast.get("confidence_interval_68", (0.0, 0.0))
            ci95 = forecast.get("confidence_interval_95", (0.0, 0.0))
            meta = forecast.get("metadata", {})
            
            # Индикатор модели
            model_type = forecast.get("model_type", "Unknown")
            if model_type == "CatBoost":
                model_indicator = "🤖 ML"
                model_badge = "✨"
            elif model_type == "Legacy":
                model_indicator = "📊 Legacy"
                model_badge = ""
            else:
                model_indicator = model_type
                model_badge = ""
            
            # Форматируем метрики (если их нет, показываем "—")
            mae_walk = meta.get('MAE_walk')
            auc_walk = meta.get('AUC_walk')
            n_train = meta.get('n_train') or meta.get('n_samples')
            
            mae_str = f"{mae_walk:.4f}" if mae_walk is not None and not (isinstance(mae_walk, float) and (mae_walk != mae_walk or mae_walk == float('inf'))) else "—"
            auc_str = f"{auc_walk:.3f}" if auc_walk is not None and not (isinstance(auc_walk, float) and (auc_walk != auc_walk or auc_walk == float('inf'))) else "—"
            n_train_str = str(n_train) if n_train is not None else "—"
            
            # Определяем режим детализации
            detail_mode = context.user_data.get("detail_mode", "standard")
            
            # Базовый текст
            base_text = (
                f"<b>Полный прогноз BTC ({tf}, +{horizon} бар)</b> {model_badge}\n"
                f"<i>{model_indicator}</i>\n"
                f"Текущая цена: <b>${current_price:,.2f}</b>\n"
                f"Ожидание: <b>{forecast['predicted_return'] * 100:+.2f}%</b>   "
                f"P(up): <b>{forecast['probability_up']:.2f}</b>   Режим: <b>{regime}</b>\n"
                f"Целевой уровень: <b>{forecast['target_price']:.2f}</b>\n"
                f"ДИ 68%: <b>{ci68[0] * 100:+.2f}% … {ci68[1] * 100:+.2f}%</b>\n"
                f"ДИ 95%: <b>{ci95[0] * 100:+.2f}% … {ci95[1] * 100:+.2f}%</b>\n"
                f"<i>MAE(walk): {mae_str}, AUC(walk): {auc_str}, N(train): {n_train_str}</i>"
            )
            
            # Добавляем объяснение для deep режима
            if detail_mode == "deep":
                from ...ml.forecast_explainer import explain_forecast, format_explanation
                from ...domain.market_diagnostics.calibration_service import CalibrationService
                from ...domain.market_diagnostics.setup_type import classify_setup
                
                # Получаем setup_class для объяснения
                setup_class = classify_setup(
                    predicted_return=forecast["predicted_return"],
                    probability_up=forecast["probability_up"],
                    confidence_interval_68=ci68,
                    confidence_interval_95=ci95,
                    global_regime=None,
                    momentum_grade=None,
                    momentum_strength=None
                )
                
                # Получаем глобальный режим
                global_regime_val = None
                try:
                    from ...domain.market_regime.global_regime_analyzer import GlobalRegimeAnalyzer
                    regime_analyzer = GlobalRegimeAnalyzer(self.db)
                    regime_snapshot = regime_analyzer.analyze_current_regime()
                    if regime_snapshot:
                        global_regime_val = regime_snapshot.regime.value if hasattr(regime_snapshot.regime, 'value') else str(regime_snapshot.regime)
                except Exception as e:
                    logger.debug(f"Failed to get global regime: {e}")
                    global_regime_val = None
                
                # Объясняем прогноз
                factors = explain_forecast(
                    predicted_return=forecast["predicted_return"],
                    probability_up=forecast["probability_up"],
                    momentum_grade=None,
                    momentum_strength=None,
                    global_regime=global_regime_val,
                    pump_score=None,
                    risk_score=None,
                    setup_type=setup_class.setup_type.value,
                    grade=setup_class.grade,
                    confidence_interval_68=ci68,
                    liquidity_state=None
                )
                
                explanation = format_explanation(factors, forecast["predicted_return"])
                
                # Получаем статистику
                setup_stats = None
                try:
                    calibration_service = CalibrationService(self.db)
                    setup_stats = calibration_service.get_setup_type_stats(
                        "BTC", tf, horizon,
                        setup_type=setup_class.setup_type.value,
                        grade=setup_class.grade
                    )
                except Exception as e:
                    logger.debug(f"Failed to get setup stats: {e}")
                
                stats_text = ""
                if setup_stats:
                    stats_text = (
                        f"\n\n📊 <b>Историческая статистика:</b>\n"
                        f"E[R]: {setup_stats['avg_return']*100:+.2f}% | "
                        f"Hit-rate: {setup_stats['hit_rate']:.1%}\n"
                        f"ES: {setup_stats['expected_shortfall']*100:+.2f}% | "
                        f"VaR(5%): {setup_stats['var_5']*100:+.2f}%"
                    )
                
                text = base_text + "\n\n" + explanation + stats_text
            else:
                text = base_text
            
            # Отправляем сообщение
            try:
                if loading_msg:
                    try:
                        await loading_msg.edit_text(text, parse_mode=ParseMode.HTML)
                    except Exception:
                        await update.effective_message.reply_text(text, parse_mode=ParseMode.HTML)
                else:
                    await update.effective_message.reply_text(text, parse_mode=ParseMode.HTML)
            except Exception as send_error:
                logger.exception(f"Failed to send forecast_full message: {send_error}")
                try:
                    await update.effective_message.reply_text(
                        f"❌ Ошибка при отправке прогноза: {str(send_error)[:100]}",
                        parse_mode=ParseMode.HTML
                    )
                except Exception:
                    pass
        except Exception as e:
            logger.exception(f"handle_forecast_full failed: {e}")
            try:
                await update.effective_message.reply_text(
                    f"❌ Ошибка при генерации полного прогноза: {str(e)[:100]}",
                    parse_mode=ParseMode.HTML
                )
            except Exception:
                pass
    
    async def handle_forecast_alts(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработать команду /forecast_alts (прогнозы для альткоинов)."""
        try:
            from ...infrastructure.coingecko import top_movers
            from ...ml.data_adapter import make_loader, _symbol_norm
            
            loader = make_loader()
            vs = "usd"
            
            try:
                coins, gainers, losers, _ = top_movers(vs=vs, tf="24h", limit_each=24)
            except Exception as e:
                await update.effective_message.reply_text(f"Не удалось получить список альтов: {e}")
                return
            
            def _is_ok(sym):
                s = (sym or "").upper()
                return s not in {"BTC", "WBTC", "USDT", "USDC", "DAI", "BUSD", "TUSD", "FDUSD", "PYUSD", "EURS",
                                 "SUSD", "LUSD", "USDD", "USDJ", "USDE", "USDS", "GUSD", "USD0", "BSC-USD",
                                 "STETH", "WSTETH", "WETH"}
            
            top10 = [c for c in sorted(coins, key=lambda x: float(x.get("market_cap") or 0), reverse=True) if
                     _is_ok(c.get("symbol"))][:10]
            movers24 = [c for c in (gainers[:12] + losers[:12]) if _is_ok(c.get("symbol"))]
            
            async def _do_batch(title, arr, tf_for_model="1h", horizon=24):
                lines = [f"<b>{title}</b>  ({tf_for_model}, +{horizon} бар)"]
                for c in arr:
                    sym = _symbol_norm(c.get("symbol") or "")
                    try:
                        from ...ml.forecaster import forecast_symbol
                        res = forecast_symbol(sym, tf_for_model, horizon, loader)
                        if res:
                            ret_pct = res.get("ret_pred", 0.0) * 100
                            p_up = res.get("p_up", 0.5)
                            lines.append(f"• {sym}: {ret_pct:+.2f}% (P(up)={p_up:.2f})")
                    except Exception:
                        continue
                if len(lines) > 1:
                    await update.effective_message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)
            
            await _do_batch("Топ-10 по капе", top10)
            await _do_batch("Движущиеся 24h", movers24)
            
        except Exception:
            logger.exception("handle_forecast_alts failed")
    
    async def handle_forecast_stats(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработать команду /forecast_stats (статистика качества прогнозов)."""
        try:
            from ...infrastructure.ui_keyboards import build_kb
            from ...application.services.forecast_evaluation_service import ForecastEvaluationService
            
            args = context.args or []
            
            # Определяем фильтры из аргументов
            symbol = "BTC"  # По умолчанию BTC
            timeframe = None  # По умолчанию все таймфреймы
            
            if len(args) >= 1:
                symbol = args[0].upper()
            if len(args) >= 2:
                timeframe = args[1].lower()
            
            # Показываем сообщение о загрузке
            loading_msg = await update.effective_message.reply_text(
                "⏳ Загружаю статистику...",
                parse_mode=ParseMode.HTML
            )
            
            # Создаем сервис оценки
            evaluation_service = ForecastEvaluationService(self.db)
            
            # Обновляем схему БД если нужно
            evaluation_service.update_forecast_history_schema()
            
            # Получаем метрики качества
            metrics = evaluation_service.get_forecast_quality_metrics(
                symbol=symbol,
                timeframe=timeframe,
                min_samples=5  # Минимум 5 образцов для статистики
            )
            
            if not metrics:
                await loading_msg.edit_text(
                    f"❌ Недостаточно данных для статистики.\n\n"
                    f"Попробуйте:\n"
                    f"• Подождите, пока накопится больше прогнозов\n"
                    f"• Используйте другую комбинацию символа/таймфрейма\n\n"
                    f"Пример: <code>/forecast_stats BTC 1h</code>",
                    parse_mode=ParseMode.HTML,
                    reply_markup=build_kb("main")
                )
                return
            
            # Формируем красивое сообщение со статистикой
            text_parts = []
            
            # Заголовок
            title = f"📊 <b>Статистика прогнозов</b>"
            if symbol:
                title += f" {symbol}"
            if timeframe:
                title += f" ({timeframe})"
            text_parts.append(title)
            text_parts.append("")
            
            # Основные метрики
            text_parts.append("<b>📈 Основные метрики:</b>")
            text_parts.append(f"• Образцов: <b>{metrics['n_samples']}</b>")
            text_parts.append(f"• Hit Rate: <b>{metrics['hit_rate']:.1%}</b>")
            
            # Форматируем MAE и RMSE
            mae_pct = metrics['mae'] * 100
            rmse_pct = metrics['rmse'] * 100
            text_parts.append(f"• MAE: <b>{mae_pct:.2f}%</b>")
            text_parts.append(f"• RMSE: <b>{rmse_pct:.2f}%</b>")
            
            # Bias с эмодзи
            bias_pct = metrics['bias'] * 100
            bias_emoji = "📈" if bias_pct > 0.1 else "📉" if bias_pct < -0.1 else "➡️"
            bias_text = "завышение" if bias_pct > 0.1 else "занижение" if bias_pct < -0.1 else "нейтрально"
            text_parts.append(f"• Bias: {bias_emoji} <b>{bias_pct:+.2f}%</b> ({bias_text})")
            
            # Корреляция
            correlation = metrics.get('correlation', 0.0)
            text_parts.append(f"• Корреляция: <b>{correlation:.3f}</b>")
            text_parts.append("")
            
            # Калибровка вероятностей
            if metrics.get('calibration_curve') and len(metrics['calibration_curve']) > 0:
                text_parts.append("<b>🎯 Калибровка вероятностей:</b>")
                
                calibration = metrics['calibration_curve']
                # Показываем первые 5 бинов
                for bin_data in calibration[:5]:
                    pred_prob = bin_data['predicted_prob']
                    actual_rate = bin_data['actual_up_rate']
                    count = bin_data['count']
                    
                    # Вычисляем разницу (calibration error)
                    error = abs(pred_prob - actual_rate)
                    error_emoji = "✅" if error < 0.1 else "⚠️" if error < 0.2 else "❌"
                    
                    text_parts.append(
                        f"• P={pred_prob:.0%}: {error_emoji} "
                        f"Реальная {actual_rate:.0%} (n={count})"
                    )
                
                if len(calibration) > 5:
                    text_parts.append(f"  <i>... и еще {len(calibration) - 5} бинов</i>")
                text_parts.append("")
            
            # Hit rate для разных вероятностей
            text_parts.append("<b>📊 Детальная статистика:</b>")
            
            # Получаем детальную статистику по бинам
            try:
                cur = self.db.conn.cursor()
                query = """
                    SELECT 
                        CASE 
                            WHEN probability_up < 0.4 THEN 'Низкая (P<40%)'
                            WHEN probability_up >= 0.4 AND probability_up < 0.6 THEN 'Средняя (40-60%)'
                            WHEN probability_up >= 0.6 THEN 'Высокая (P≥60%)'
                            ELSE 'Другая'
                        END as prob_category,
                        COUNT(*) as total,
                        SUM(hit) as hits,
                        AVG(prediction_error) as avg_error,
                        AVG(actual_return) as avg_actual_return
                    FROM forecast_history
                    WHERE evaluation_status = 'evaluated'
                      AND actual_return IS NOT NULL
                """
                params = []
                
                if symbol:
                    query += " AND symbol = ?"
                    params.append(symbol)
                
                if timeframe:
                    query += " AND timeframe = ?"
                    params.append(timeframe)
                
                query += " GROUP BY prob_category ORDER BY prob_category"
                
                cur.execute(query, params)
                rows = cur.fetchall()
                
                for row in rows:
                    category = row["prob_category"]
                    total = row["total"]
                    hits = row["hits"] or 0
                    hit_rate_cat = (hits / total) if total > 0 else 0.0
                    avg_error_pct = (row["avg_error"] or 0.0) * 100
                    
                    hit_emoji = "✅" if hit_rate_cat > 0.5 else "⚠️" if hit_rate_cat > 0.4 else "❌"
                    text_parts.append(
                        f"• {category}: {hit_emoji} "
                        f"Hit {hit_rate_cat:.0%} "
                        f"(n={total}, err={avg_error_pct:+.1f}%)"
                    )
                
            except Exception as e:
                logger.debug(f"Failed to get detailed stats: {e}")
            
            text_parts.append("")
            text_parts.append("<i>Использование: /forecast_stats [SYMBOL] [TIMEFRAME]</i>")
            text_parts.append("<i>Примеры: /forecast_stats BTC 1h</i>")
            
            text = "\n".join(text_parts)
            
            await loading_msg.edit_text(
                text,
                parse_mode=ParseMode.HTML,
                reply_markup=build_kb("main")
            )
            
        except Exception as e:
            logger.exception(f"handle_forecast_stats failed: {e}")
            try:
                from ...infrastructure.ui_keyboards import build_kb
                await update.effective_message.reply_text(
                    f"❌ Ошибка при получении статистики: {str(e)[:100]}",
                    reply_markup=build_kb("main")
                )
            except Exception:
                pass

