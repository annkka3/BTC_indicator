# app/domain/market_diagnostics/reporter.py
"""
Генератор текстовых отчетов для Market Doctor.
"""

from typing import Optional, Dict
import re
from .analyzer import MarketDiagnostics
from .trade_planner import TradePlan
from .multi_tf import MultiTFDiagnostics


class ReportRenderer:
    """Рендерер отчетов Market Doctor."""
    
    def render_report(self, diag: MarketDiagnostics, plan: Optional[TradePlan] = None, timeframe: Optional[str] = None) -> str:
        """
        Сформировать текстовый отчет.
        
        Args:
            diag: Результаты диагностики рынка
            plan: Опциональный торговый план
            timeframe: Таймфрейм для проверки конфликтов со старшими ТФ
            
        Returns:
            Текстовый отчет в формате для Telegram
        """
        lines = []
        
        # Заголовок
        lines.append(f"🏥 <b>Market Doctor</b>")
        lines.append(f"Монета: <b>{diag.symbol}</b> | ТФ: <b>{diag.timeframe}</b>")
        
        # Краткий саммари в одну строку
        phase_emoji = self._get_phase_emoji(diag.phase)
        trend_emoji = self._get_trend_emoji(diag.trend)
        vol_emoji = self._get_volatility_emoji(diag.volatility)
        liq_emoji = self._get_liquidity_emoji(diag.liquidity)
        
        # Эмодзи для score
        pump_emoji = "🔥" if diag.pump_score > 0.7 else "📈" if diag.pump_score > 0.5 else "📊"
        risk_emoji = "🔴" if diag.risk_score > 0.7 else "🟡" if diag.risk_score > 0.5 else "🟢"
        
        # Confidence emoji
        confidence_emoji = "🟢" if diag.confidence > 0.7 else "🟡" if diag.confidence > 0.5 else "🔴"
        
        # Улучшенная шапка - более читаемая с группировкой
        lines.append("━━━━━━━━━━━━━━━━━━━━")
        lines.append(f"{phase_emoji} <b>Фаза:</b> {diag.phase.value}")
        lines.append(f"{trend_emoji} <b>Тренд:</b> {diag.trend.value}")
        lines.append(f"{vol_emoji} <b>Волатильность:</b> {diag.volatility.value}")
        lines.append(f"{liq_emoji} <b>Ликвидность:</b> {diag.liquidity.value}")
        lines.append("")
        lines.append(f"{pump_emoji} <b>Pump:</b> {diag.pump_score:.2f}")
        lines.append(f"{risk_emoji} <b>Risk:</b> {diag.risk_score:.2f}")
        lines.append(f"{confidence_emoji} <b>Confidence:</b> {diag.confidence:.2f}")
        lines.append("━━━━━━━━━━━━━━━━━━━━")
        lines.append("")
        
        # TL;DR краткое резюме
        tldr = self._generate_tldr(diag, plan)
        if tldr:
            lines.append(f"💡 <b>TL;DR:</b> {tldr}")
            lines.append("")
        
        # Reliability score
        if plan and plan.reliability_score is not None:
            reliability_emoji = "🟢" if plan.reliability_score > 0.7 else "🟡" if plan.reliability_score > 0.5 else "🔴"
            samples_text = f" по {plan.reliability_samples} похожим кейсам" if plan.reliability_samples else ""
            lines.append(f"🧪 <b>Надёжность паттерна:</b> {reliability_emoji} {plan.reliability_score:.2f}{samples_text}")
            lines.append("")
        
        # Grade сетапа (с учётом reliability, tradability, user_profile)
        effective_threshold = plan.effective_threshold if plan else None
        tradability_state = diag.liquidity.value if hasattr(diag, 'liquidity') else None
        user_profile = None  # Можно передавать из handler
        grade, grade_desc = self._calculate_grade(
            diag.pump_score, 
            diag.risk_score, 
            diag.confidence,
            effective_threshold,
            plan.reliability_score if plan else None,
            tradability_state,
            user_profile
        )
        grade_emoji = "🟢" if grade == "A" else "🟡" if grade == "B" else "🔴"
        lines.append(f"{grade_emoji} <b>Grade:</b> {grade} ({grade_desc})")
        
        # Проверка Pump vs адаптивный порог
        if plan and plan.effective_threshold:
            if diag.pump_score < plan.effective_threshold:
                lines.append("")
                regime_text = plan.regime_info or 'текущем'
                # Убираем детали режима из warning, они будут внизу
                if "Режим:" in regime_text:
                    regime_text = regime_text.split("Режим:")[-1].strip()
                lines.append(f"⚠️ <b>Внимание:</b> Текущий Pump ({diag.pump_score:.2f}) ниже адаптивного порога "
                           f"для сильных сетапов ({plan.effective_threshold:.2f}) в режиме {regime_text}. "
                           f"Сценарий скорее спекулятивный/наблюдательный, а не high-conviction вход.")
        
        lines.append("")
        
        # Бэктест статистика (если есть pattern_id и backtest_analyzer)
        if plan and plan.backtest_stats:
            stats = plan.backtest_stats
            lines.append("")
            lines.append("📈 <b>История похожих сетапов (24ч вперёд):</b>")
            avg_return = stats.get('avg_return', 0)
            win_rate = stats.get('win_rate', 0)
            count = stats.get('count', 0)
            if count > 0:
                avg_return_r = avg_return / 100.0  # Конвертируем % в R (упрощённо)
                lines.append(f"• Средний результат: {avg_return_r:+.2f}R")
                lines.append(f"• Hit-rate (R > 0): {win_rate:.0f}% по {count} кейсам")
            lines.append("")
        
        # Confidence explanation
        if diag.confidence < 0.5:
            lines.append(f"🤔 <b>Уверенность низкая ({diag.confidence:.2f}):</b> "
                        f"конфликт ТФ, мало данных или частичный доступ к деривативам. "
                        f"Сетап требует дополнительного внимания.")
        elif diag.confidence > 0.7:
            lines.append(f"🔍 <b>Уверенность высокая ({diag.confidence:.2f}):</b> "
                        f"конфлюэнс по таймфреймам, качественные деривативы, стабильный исторический паттерн.")
        lines.append("")
        
        # Проверка "лонг против старшего тренда" для single-TF
        if plan and timeframe == "1h":
            # Проверяем старшие ТФ (4h/1d) если они доступны
            # Это можно сделать через дополнительный анализ или через multi-TF
            # Пока добавляем предупреждение если фаза ACCUM/EXP_UP на 1h, но pump низкий
            if (diag.phase.value in ['ACCUMULATION', 'EXPANSION_UP'] and 
                diag.pump_score < 0.5):
                lines.append("🚫 <b>Лонг против старшего тренда</b> — повышенный риск, сценарий только для агрессивного профиля.")
                lines.append("")
        
        # Фаза рынка и состояния уже выведены в шапке, пропускаем дублирование
        # lines.append(f"{phase_emoji} <b>Фаза рынка:</b> {diag.phase.value}")
        # lines.append(f"{trend_emoji} <b>Тренд:</b> {diag.trend.value}")
        # lines.append(f"{vol_emoji} <b>Волатильность:</b> {diag.volatility.value}")
        # lines.append(f"{liq_emoji} <b>Ликвидность:</b> {diag.liquidity.value}")
        # lines.append("")
        
        # Индикаторы
        lines.append("📊 <b>Индикаторы</b>")
        extra = diag.extra_metrics
        
        indicator_items = []
        if 'trend_summary' in extra:
            indicator_items.append(f"• Цена vs EMA: {extra['trend_summary']}")
        
        if 'rsi' in extra:
            indicator_items.append(f"• RSI: {extra['rsi']}")
        
        if 'stoch_rsi_state' in extra:
            indicator_items.append(f"• Stoch RSI: {extra['stoch_rsi_state']}")
        
        if 'macd_state' in extra:
            indicator_items.append(f"• MACD: {extra['macd_state']}")
        
        if 'bb_state' in extra:
            indicator_items.append(f"• Bollinger: {extra['bb_state']}")
        
        if 'money_flow_state' in extra:
            money_flow_text = extra['money_flow_state']
            indicator_items.append(f"• OBV/CMF: {money_flow_text}")
            
            # Добавляем смысловой вывод для OBV/CMF
            money_flow_hint = self._get_money_flow_hint(extra, diag)
            if money_flow_hint:
                indicator_items.append(f"  {money_flow_hint}")
        
        if indicator_items:
            lines.extend(indicator_items)
        
        lines.append("")
        
        # Деривативы
        lines.append("🧨 <b>Деривативы</b>")
        derivative_items = []
        if 'funding' in extra:
            derivative_items.append(f"• Funding: {extra['funding']}")
        
        if 'oi_state' in extra:
            derivative_items.append(f"• OI: {extra['oi_state']}")
        
        if 'cvd_comment' in extra:
            derivative_items.append(f"• {extra['cvd_comment']}")
        
        if derivative_items:
            lines.extend(derivative_items)
        
        lines.append("")
        
        # Сильные уровни и SMC контекст
        if diag.key_levels or diag.smc_context or diag.legs_summary:
            lines.append("━━━━━━━━━━━━━━━━━━━━")
            lines.append("📌 <b>Сильные уровни и зоны Smart Money</b>")
            lines.append("")
            
            # Ключевые уровни
            if diag.key_levels:
                # Показываем топ-5 по силе
                top_levels = sorted(diag.key_levels, key=lambda l: l.strength, reverse=True)[:5]
                for lvl in top_levels:
                    kind_emoji = "🟢" if lvl.kind.value in ['support', 'orderblock_demand'] else "🔴"
                    rounded_price = self._round_price(lvl.price)
                    kind_name = "поддержка" if lvl.kind.value == "support" else "сопротивление" if lvl.kind.value == "resistance" else lvl.kind.value
                    lines.append(
                        f"  {kind_emoji} {kind_name} ~{rounded_price} "
                        f"(сила {lvl.strength:.2f}, касаний {lvl.touched_times})"
                    )
                lines.append("")
            
            # SMC контекст
            if diag.smc_context:
                smc = diag.smc_context
                
                if smc.last_bos:
                    bos = smc.last_bos
                    bos_emoji = "🟢" if bos.direction == "up" else "🔴"
                    bos_price_rounded = self._round_price(bos.price)
                    lines.append(f"  {bos_emoji} Последний BOS: {bos.direction} около ~{bos_price_rounded}")
                
                if smc.main_liquidity_above:
                    liq_above_rounded = self._round_price(smc.main_liquidity_above)
                    lines.append(f"  💧 Ликвидность сверху (equal highs): ~{liq_above_rounded}")
                    lines.append(f"     Потенциальная зона забора стопов шортистов перед разворотом или защитой продавца.")
                
                if smc.main_liquidity_below:
                    liq_below_rounded = self._round_price(smc.main_liquidity_below)
                    lines.append(f"  💧 Ликвидность снизу (equal lows): ~{liq_below_rounded}")
                    lines.append(f"     Стопы лонгов, возможен вынос вниз перед набором позиции.")
                
                if smc.order_blocks_demand:
                    ob = smc.order_blocks_demand[0]  # Берем первый
                    ob_low_rounded = self._round_price(ob.price_low)
                    ob_high_rounded = self._round_price(ob.price_high)
                    lines.append(f"  🟦 Demand Order Block: ~{ob_low_rounded}–{ob_high_rounded}")
                
                if smc.premium_zone_start and smc.discount_zone_end:
                    position_emoji = "🔴" if smc.current_position == "premium" else "🟢" if smc.current_position == "discount" else "🟡"
                    # Более человеческий текст
                    discount_price = self._round_price(smc.discount_zone_end)
                    premium_price = self._round_price(smc.premium_zone_start)
                    
                    if smc.current_position == "premium":
                        lines.append(
                            f"  {position_emoji} <b>Диапазон:</b> discount-зона до {discount_price}, premium выше неё. "
                            f"Сейчас цена в premium — новые покупки хуже по соотношению риск/потенциал."
                        )
                    elif smc.current_position == "discount":
                        lines.append(
                            f"  {position_emoji} <b>Диапазон:</b> discount-зона до {discount_price}, premium от {premium_price}. "
                            f"Сейчас цена в discount — более выгодная зона для покупок."
                        )
                    else:
                        lines.append(
                            f"  {position_emoji} <b>Диапазон:</b> discount-зона до {discount_price}, premium от {premium_price}."
                        )
                lines.append("")
            
            # Волновой анализ (legs summary)
            if diag.legs_summary:
                lines.append(f"  📊 Структура движений: {diag.legs_summary}")
                lines.append("")
            
            lines.append("━━━━━━━━━━━━━━━━━━━━")
            lines.append("")
        
        # Аналитический вывод
        lines.append("🧠 <b>Аналитический вывод</b>")
        lines.append(diag.risk_comment)
        lines.append("")
        lines.append(diag.pump_prob_comment)
        lines.append("")
        
        # Проверка на пропуск торговли
        if plan and plan.skip_trading:
            lines.append("━━━━━━━━━━━━━━━━━━━━")
            lines.append(f"🔴 <b>ВНИМАНИЕ:</b> {plan.skip_trading_comment}")
            lines.append("━━━━━━━━━━━━━━━━━━━━")
            lines.append("")
            return "\n".join(lines)
        
        # Торговые подсказки
        if plan:
            lines.append("━━━━━━━━━━━━━━━━━━━━")
            lines.append("🎯 <b>Торговые подсказки</b>")
            lines.append("<i>для анализа, не финсовет</i>")
            lines.append("")
            
            # Сценарный плейбук (если есть)
            if plan.scenario_playbook:
                lines.append("")
                lines.append(plan.scenario_playbook)
                lines.append("")
            
            if plan.small_position_allowed:
                lines.append(f"🟢 {plan.small_position_comment}")
            else:
                # Показываем комментарий даже если позиция не рекомендуется
                lines.append(f"🔴 {plan.small_position_comment}")
            
            # Position sizing hint
            if plan.position_size_factor and plan.position_size_comment:
                lines.append(f"💰 {plan.position_size_comment}")
            
            if plan.limit_buy_zone:
                low, high = plan.limit_buy_zone
                low_rounded = self._round_price(low)
                high_rounded = self._round_price(high)
                comment = plan.limit_buy_comment or ""
                if comment:
                    comment = re.sub(rf"{low:.4f}", low_rounded, comment)
                    comment = re.sub(rf"{high:.4f}", high_rounded, comment)
                    comment = re.sub(rf"{low:.2f}", low_rounded, comment)
                    comment = re.sub(rf"{high:.2f}", high_rounded, comment)
                    lines.append(f"🟦 Лимитная зона: <b>{low_rounded}–{high_rounded}</b>. {comment}")
                else:
                    lines.append(f"🟦 Лимитная зона: <b>{low_rounded}–{high_rounded}</b>")
            
            if plan.add_on_breakout_level:
                breakout_rounded = self._round_price(plan.add_on_breakout_level)
                comment = plan.add_on_breakout_comment or ""
                if comment:
                    comment = re.sub(rf"{plan.add_on_breakout_level:.4f}", breakout_rounded, comment)
                    comment = re.sub(rf"{plan.add_on_breakout_level:.2f}", breakout_rounded, comment)
                    lines.append(f"🟩 Добавление позиции после пробоя <b>{breakout_rounded}</b>. {comment}")
                else:
                    lines.append(f"🟩 Добавление позиции после пробоя: <b>{breakout_rounded}</b>")
            
            if plan.dont_dca_above:
                dca_rounded = self._round_price(plan.dont_dca_above)
                comment = plan.dont_dca_comment or ""
                if comment:
                    comment = re.sub(rf"{plan.dont_dca_above:.4f}", dca_rounded, comment)
                    comment = re.sub(rf"{plan.dont_dca_above:.2f}", dca_rounded, comment)
                    lines.append(f"❌ Не усреднять выше <b>{dca_rounded}</b>. {comment}")
                else:
                    lines.append(f"❌ Не усреднять выше: <b>{dca_rounded}</b>")
            
            # Добавляем дисклеймер
            lines.append("")
            lines.append("━━━━━━━━━━━━━━━━━━━━")
            lines.append("<i>⚠️ Данные подсказки носят информационный характер и не являются финансовой рекомендацией.</i>")
        
        # Режим рынка и сентимент (компактно, без дублирования)
        if plan:
            regime_sentiment_lines = []
            if plan.regime_info:
                # Упрощаем режим - только краткое описание без деталей
                regime_text = plan.regime_info
                # Убираем префикс "Режим:" если есть
                if "Режим:" in regime_text:
                    regime_text = regime_text.split("Режим:")[-1].strip()
                # Убираем детали типа "BTC -13.4%" из TL;DR, оставляем только внизу
                if "BTC" in regime_text and "%" in regime_text:
                    # Извлекаем только режим без цифр для компактности
                    regime_parts = regime_text.split(",")
                    regime_name = regime_parts[0].strip() if regime_parts else regime_text
                    regime_sentiment_lines.append(f"🌍 <b>Режим:</b> {regime_name}")
                else:
                    regime_sentiment_lines.append(f"🌍 <b>Режим:</b> {regime_text}")
            
            if plan.sentiment_info:
                regime_sentiment_lines.append(plan.sentiment_info)
            
            if regime_sentiment_lines:
                lines.append("")
                lines.extend(regime_sentiment_lines)
        
        return "\n".join(lines)
    
    def render_brief(self, diag: MarketDiagnostics, plan: Optional[TradePlan] = None) -> str:
        """
        Сформировать краткий отчет (TL;DR версия).
        
        Args:
            diag: Результаты диагностики рынка
            plan: Опциональный торговый план
        
        Returns:
            Краткий отчет (3-5 строк)
        """
        lines = []
        
        # Краткая строка с основными метриками
        phase_emoji = self._get_phase_emoji(diag.phase)
        trend_emoji = self._get_trend_emoji(diag.trend)
        vol_emoji = self._get_volatility_emoji(diag.volatility)
        
        pump_emoji = "🔥" if diag.pump_score > 0.7 else "📈" if diag.pump_score > 0.5 else "📊"
        risk_emoji = "🔴" if diag.risk_score > 0.7 else "🟡" if diag.risk_score > 0.5 else "🟢"
        
        lines.append(
            f"<b>{diag.symbol}</b> {diag.timeframe}: {phase_emoji} {diag.phase.value} | "
            f"{trend_emoji} {diag.trend.value} | {vol_emoji} {diag.volatility.value} | "
            f"{pump_emoji} pump {diag.pump_score:.2f} | {risk_emoji} risk {diag.risk_score:.2f}"
        )
        
        # Торговые подсказки (только ключевые)
        if plan:
            if plan.small_position_allowed:
                lines.append(f"🟢 {plan.small_position_comment}")
            
            if plan.limit_buy_zone:
                low, high = plan.limit_buy_zone
                lines.append(f"🟦 Лимитка: {low:.4f}–{high:.4f}")
            
            if plan.add_on_breakout_level:
                lines.append(f"🟩 Добавлять выше {plan.add_on_breakout_level:.4f}")
            
            if plan.dont_dca_above:
                lines.append(f"❌ Не усреднять выше {plan.dont_dca_above:.4f}")
        
        return "\n".join(lines)
    
    def render_trade_only(self, diag: MarketDiagnostics, plan: Optional[TradePlan] = None) -> str:
        """
        Сформировать отчет только с торговым планом (без индикаторов).
        
        Args:
            diag: Результаты диагностики рынка
            plan: Опциональный торговый план
        
        Returns:
            Отчет только с торговыми подсказками
        """
        lines = []
        
        # Минимальный заголовок
        lines.append(f"🏥 <b>Market Doctor</b> - Торговый план")
        lines.append(f"Монета: <b>{diag.symbol}</b> | ТФ: <b>{diag.timeframe}</b>")
        lines.append("")
        lines.append("━━━━━━━━━━━━━━━━━━━━")
        
        # Краткая сводка
        phase_emoji = self._get_phase_emoji(diag.phase)
        pump_emoji = "🔥" if diag.pump_score > 0.7 else "📈" if diag.pump_score > 0.5 else "📊"
        risk_emoji = "🔴" if diag.risk_score > 0.7 else "🟡" if diag.risk_score > 0.5 else "🟢"
        
        lines.append(f"{phase_emoji} <b>Фаза:</b> {diag.phase.value}")
        lines.append(f"{pump_emoji} <b>Pump:</b> {diag.pump_score:.2f}")
        lines.append(f"{risk_emoji} <b>Risk:</b> {diag.risk_score:.2f}")
        lines.append("━━━━━━━━━━━━━━━━━━━━")
        lines.append("")
        
        # Проверка на пропуск торговли
        if plan and plan.skip_trading:
            lines.append(f"🔴 <b>ВНИМАНИЕ:</b> {plan.skip_trading_comment}")
            lines.append("━━━━━━━━━━━━━━━━━━━━")
            lines.append("")
            return "\n".join(lines)
        
        # Торговые подсказки
        if plan:
            lines.append("━━━━━━━━━━━━━━━━━━━━")
            lines.append("🎯 <b>Торговые подсказки</b>")
            lines.append("")
            
            # Сценарный плейбук
            if plan.scenario_playbook:
                lines.append("")
                lines.append(plan.scenario_playbook)
                lines.append("")
            
            if plan.small_position_allowed:
                lines.append(f"🟢 {plan.small_position_comment}")
            else:
                lines.append(f"🔴 {plan.small_position_comment}")
            
            # Position sizing
            if plan.position_size_factor and plan.position_size_comment:
                lines.append(f"💰 {plan.position_size_comment}")
            
            if plan.limit_buy_zone:
                low, high = plan.limit_buy_zone
                low_rounded = self._round_price(low)
                high_rounded = self._round_price(high)
                if plan.limit_buy_comment:
                    comment = plan.limit_buy_comment
                    # Заменяем точные цены в комментарии на округлённые
                    comment = re.sub(rf"{low:.4f}", low_rounded, comment)
                    comment = re.sub(rf"{high:.4f}", high_rounded, comment)
                    # Также заменяем форматы типа "X.XXXX" на округлённые
                    comment = re.sub(rf"{low:.2f}", low_rounded, comment)
                    comment = re.sub(rf"{high:.2f}", high_rounded, comment)
                    lines.append(f"🟦 Лимитная зона: <b>{low_rounded}–{high_rounded}</b>. {comment}")
                else:
                    lines.append(f"🟦 Лимитная зона: <b>{low_rounded}–{high_rounded}</b>")
            
            if plan.add_on_breakout_level:
                breakout_rounded = self._round_price(plan.add_on_breakout_level)
                if plan.add_on_breakout_comment:
                    comment = plan.add_on_breakout_comment
                    # Заменяем точные цены в комментарии на округлённые
                    comment = re.sub(rf"{plan.add_on_breakout_level:.4f}", breakout_rounded, comment)
                    comment = re.sub(rf"{plan.add_on_breakout_level:.2f}", breakout_rounded, comment)
                    lines.append(f"🟩 Добавление позиции после пробоя <b>{breakout_rounded}</b>. {comment}")
                else:
                    lines.append(f"🟩 Добавление позиции после пробоя: <b>{breakout_rounded}</b>")
            
            if plan.dont_dca_above:
                dca_rounded = self._round_price(plan.dont_dca_above)
                if plan.dont_dca_comment:
                    comment = plan.dont_dca_comment
                    # Заменяем точные цены в комментарии на округлённые
                    comment = re.sub(rf"{plan.dont_dca_above:.4f}", dca_rounded, comment)
                    comment = re.sub(rf"{plan.dont_dca_above:.2f}", dca_rounded, comment)
                    lines.append(f"❌ Не усреднять выше <b>{dca_rounded}</b>. {comment}")
                else:
                    lines.append(f"❌ Не усреднять выше: <b>{dca_rounded}</b>")
            
            lines.append("")
            lines.append("━━━━━━━━━━━━━━━━━━━━")
            lines.append("<i>⚠️ Данные подсказки носят информационный характер и не являются финансовой рекомендацией.</i>")
        
        return "\n".join(lines)
    
    def render_multi_tf(self, multi_diag: MultiTFDiagnostics, trade_plans: Optional[Dict[str, "TradePlan"]] = None) -> str:
        """
        Сформировать отчет для multi-TF анализа.
        
        Args:
            multi_diag: Результаты multi-TF диагностики
            trade_plans: Опциональный словарь торговых планов по ТФ {"1h": plan, ...}
        
        Returns:
            Отчет по всем таймфреймам
        """
        lines = []
        
        lines.append(f"🏥 <b>Market Doctor Multi-TF</b>")
        lines.append(f"Монета: <b>{multi_diag.symbol}</b>")
        lines.append("")
        lines.append("━━━━━━━━━━━━━━━━━━━━")
        
        # Консенсусная информация с учётом старшинства ТФ
        consensus_phase = multi_diag.get_consensus_phase()
        higher_tf_consensus = multi_diag.get_higher_tf_consensus()
        local_consensus = multi_diag.get_local_consensus()
        
        avg_pump = multi_diag.get_avg_pump_score()
        avg_risk = multi_diag.get_avg_risk_score()
        
        pump_emoji = "🔥" if avg_pump > 0.7 else "📈" if avg_pump > 0.5 else "📊"
        risk_emoji = "🔴" if avg_risk > 0.7 else "🟡" if avg_risk > 0.5 else "🟢"
        
        avg_confidence = multi_diag.get_avg_confidence()
        confidence_emoji = "🟢" if avg_confidence > 0.7 else "🟡" if avg_confidence > 0.5 else "🔴"
        
        # Показываем консенсус с учётом старшинства ТФ
        if higher_tf_consensus and local_consensus and higher_tf_consensus != local_consensus:
            lines.append(f"📊 <b>Консенсус по старшим ТФ:</b> {higher_tf_consensus}")
            higher_desc = "нисходящего" if higher_tf_consensus in ['DISTRIBUTION', 'EXPANSION_DOWN'] else "восходящего"
            lines.append(f"📊 <b>Локальный контекст (1h):</b> {local_consensus}-откат внутри {higher_desc} режима")
        else:
            lines.append(f"📊 <b>Консенсус:</b> {consensus_phase}")
        
        lines.append(f"{pump_emoji} <b>Pump:</b> {avg_pump:.2f}")
        lines.append(f"{risk_emoji} <b>Risk:</b> {avg_risk:.2f}")
        lines.append(f"{confidence_emoji} <b>Confidence:</b> {avg_confidence:.2f}")
        lines.append("")
        
        # Confidence explanation for multi-TF
        has_conflict = multi_diag.get_timeframe_conflict()
        if has_conflict:
            lines.append("⚠️ <b>Конфликт между таймфреймами</b> - разные фазы на разных ТФ")
        
        if avg_confidence < 0.5:
            lines.append(f"🤔 Уверенность низкая ({avg_confidence:.2f}): конфликт ТФ или недостаточно данных.")
        elif avg_confidence > 0.7:
            if has_conflict:
                lines.append(f"🔍 Уверенность высокая ({avg_confidence:.2f}), но фазы конфликтуют между ТФ — оценка опирается на историю паттернов, а не на идеальное выравнивание таймфреймов.")
            else:
                lines.append(f"🔍 Уверенность высокая ({avg_confidence:.2f}): согласованность по всем ТФ.")
        
        lines.append("━━━━━━━━━━━━━━━━━━━━")
        lines.append("")
        
        # Таблица по таймфреймам
        timeframes = ["1h", "4h", "1d"]
        available_tfs = [tf for tf in timeframes if tf in multi_diag.snapshots]
        
        if available_tfs:
            # Сокращенные названия для компактности
            phase_short = {
                "ACCUMULATION": "ACCUM",
                "DISTRIBUTION": "DISTR",
                "EXPANSION_UP": "EXP_UP",
                "EXPANSION_DOWN": "EXP_DN",
                "SHAKEOUT": "SHAKE"
            }
            
            trend_short = {
                "BULLISH": "BULL",
                "BEARISH": "BEAR",
                "NEUTRAL": "NEUT"
            }
            
            vol_short = {
                "LOW": "LOW",
                "MEDIUM": "MED",
                "HIGH": "HIGH"
            }
            
            # Улучшенная таблица с выравниванием и разделителями
            lines.append("⏱ <b>Сравнение таймфреймов</b>")
            lines.append("")
            
            # Заголовок
            header_parts = [f"<b>{tf:>10}</b>" for tf in available_tfs]
            lines.append("      " + " │ ".join(header_parts))
            lines.append("      " + "─" * (len(" │ ".join(header_parts)) - 6))
            
            # Фазы
            phase_parts = []
            for tf in available_tfs:
                diag = multi_diag.snapshots[tf]
                phase_emoji = self._get_phase_emoji(diag.phase)
                phase_text = phase_short.get(diag.phase.value, diag.phase.value[:8])
                phase_parts.append(f"{phase_emoji} {phase_text:>9}")
            lines.append("Фаза  " + " │ ".join(phase_parts))
            
            # Тренд
            trend_parts = []
            for tf in available_tfs:
                diag = multi_diag.snapshots[tf]
                trend_emoji = self._get_trend_emoji(diag.trend)
                trend_text = trend_short.get(diag.trend.value, diag.trend.value[:4])
                trend_parts.append(f"{trend_emoji} {trend_text:>9}")
            lines.append("Тренд " + " │ ".join(trend_parts))
            
            # Pump score
            pump_parts = []
            for tf in available_tfs:
                diag = multi_diag.snapshots[tf]
                pump_emoji_tf = "🔥" if diag.pump_score > 0.7 else "📈" if diag.pump_score > 0.5 else "📊"
                pump_parts.append(f"{pump_emoji_tf} {diag.pump_score:.2f}")
            lines.append("Pump  " + " │ ".join([f"{p:>10}" for p in pump_parts]))
            
            # Risk score
            risk_parts = []
            for tf in available_tfs:
                diag = multi_diag.snapshots[tf]
                risk_emoji_tf = "🔴" if diag.risk_score > 0.7 else "🟡" if diag.risk_score > 0.5 else "🟢"
                risk_parts.append(f"{risk_emoji_tf} {diag.risk_score:.2f}")
            lines.append("Risk  " + " │ ".join([f"{r:>10}" for r in risk_parts]))
            
            lines.append("")
            lines.append("━━━━━━━━━━━━━━━━━━━━")
            lines.append("")
        
        lines.append("")
        
        # Уровни и SMC контекст по таймфреймам
        has_levels_or_smc = any(
            (diag.key_levels or diag.smc_context or diag.legs_summary)
            for diag in multi_diag.snapshots.values()
        )
        
        if has_levels_or_smc:
            lines.append("━━━━━━━━━━━━━━━━━━━━")
            lines.append("📌 <b>Сильные уровни и зоны Smart Money</b>")
            lines.append("")
            
            # Используем все доступные таймфреймы из snapshots
            for tf in sorted(multi_diag.snapshots.keys()):
                diag = multi_diag.snapshots[tf]
                
                if not (diag.key_levels or diag.smc_context or diag.legs_summary):
                    continue
                
                lines.append(f"<b>{tf}:</b>")
                
                # Ключевые уровни
                if diag.key_levels:
                    top_levels = sorted(diag.key_levels, key=lambda l: l.strength, reverse=True)[:3]
                    for lvl in top_levels:
                        kind_emoji = "🟢" if lvl.kind.value in ['support', 'orderblock_demand'] else "🔴"
                        rounded_price = self._round_price(lvl.price)
                        kind_name = "поддержка" if lvl.kind.value == "support" else "сопротивление" if lvl.kind.value == "resistance" else lvl.kind.value
                        lines.append(
                            f"  {kind_emoji} {kind_name} ~{rounded_price} "
                            f"(сила {lvl.strength:.2f})"
                        )
                
                # SMC контекст
                if diag.smc_context:
                    smc = diag.smc_context
                    
                    if smc.last_bos:
                        bos_emoji = "🟢" if smc.last_bos.direction == "up" else "🔴"
                        lines.append(f"  {bos_emoji} BOS: {smc.last_bos.direction} ~{smc.last_bos.price:.4f}")
                    
                    if smc.main_liquidity_above:
                        lines.append(f"  💧 Ликвидность выше: <b>{smc.main_liquidity_above:.4f}</b>")
                    
                    if smc.main_liquidity_below:
                        lines.append(f"  💧 Ликвидность ниже: <b>{smc.main_liquidity_below:.4f}</b>")
                    
                    if smc.order_blocks_demand:
                        ob = smc.order_blocks_demand[0]
                        lines.append(f"  🟦 Demand OB: <b>{ob.price_low:.4f}–{ob.price_high:.4f}</b>")
                    
                    if smc.premium_zone_start and smc.discount_zone_end:
                        position_emoji = "🔴" if smc.current_position == "premium" else "🟢" if smc.current_position == "discount" else "🟡"
                        discount_price = self._round_price(smc.discount_zone_end)
                        premium_price = self._round_price(smc.premium_zone_start)
                        
                        if smc.current_position == "premium":
                            lines.append(
                                f"  {position_emoji} <b>Диапазон:</b> discount-зона до {discount_price}, premium выше неё. "
                                f"Сейчас цена в premium — новые покупки хуже по соотношению риск/потенциал."
                            )
                        elif smc.current_position == "discount":
                            lines.append(
                                f"  {position_emoji} <b>Диапазон:</b> discount-зона до {discount_price}, premium от {premium_price}. "
                                f"Сейчас цена в discount — более выгодная зона для покупок."
                            )
                        else:
                            lines.append(
                                f"  {position_emoji} <b>Диапазон:</b> discount-зона до {discount_price}, premium от {premium_price}."
                            )
                
                # Волновой анализ
                if diag.legs_summary:
                    lines.append(f"  📊 {diag.legs_summary}")
                
                lines.append("")
            
            lines.append("━━━━━━━━━━━━━━━━━━━━")
            lines.append("")
        
        # Усредненные торговые подсказки
        if trade_plans:
            # Усредняем торговые планы
            avg_plan = self._average_trade_plans(trade_plans)
            if avg_plan:
                lines.append("━━━━━━━━━━━━━━━━━━━━")
                lines.append("🎯 <b>Торговые подсказки</b>")
                lines.append("<i>для анализа, не финсовет</i>")
                lines.append("")
                
                if avg_plan.small_position_allowed:
                    lines.append(f"🟢 {avg_plan.small_position_comment}")
                else:
                    lines.append(f"🔴 {avg_plan.small_position_comment}")
                
                if avg_plan.limit_buy_zone:
                    low, high = avg_plan.limit_buy_zone
                    low_rounded = self._round_price(low)
                    high_rounded = self._round_price(high)
                    comment = avg_plan.limit_buy_comment or ""
                    if comment:
                        # Заменяем точные цены в комментарии на округлённые
                        comment = re.sub(rf"{low:.4f}", low_rounded, comment)
                        comment = re.sub(rf"{high:.4f}", high_rounded, comment)
                        comment = re.sub(rf"{low:.2f}", low_rounded, comment)
                        comment = re.sub(rf"{high:.2f}", high_rounded, comment)
                        lines.append(f"🟦 Лимитная зона: <b>{low_rounded}–{high_rounded}</b>. {comment}")
                    else:
                        lines.append(f"🟦 Лимитная зона: <b>{low_rounded}–{high_rounded}</b>")
                
                if avg_plan.add_on_breakout_level:
                    breakout_rounded = self._round_price(avg_plan.add_on_breakout_level)
                    comment = avg_plan.add_on_breakout_comment or ""
                    if comment:
                        # Заменяем точные цены в комментарии на округлённые
                        comment = re.sub(rf"{avg_plan.add_on_breakout_level:.4f}", breakout_rounded, comment)
                        comment = re.sub(rf"{avg_plan.add_on_breakout_level:.2f}", breakout_rounded, comment)
                        lines.append(f"🟩 Добавление позиции после пробоя <b>{breakout_rounded}</b>. {comment}")
                    else:
                        lines.append(f"🟩 Добавление позиции после пробоя: <b>{breakout_rounded}</b>")
                
                if avg_plan.dont_dca_above:
                    dca_rounded = self._round_price(avg_plan.dont_dca_above)
                    comment = avg_plan.dont_dca_comment or ""
                    if comment:
                        # Заменяем точные цены в комментарии на округлённые
                        comment = re.sub(rf"{avg_plan.dont_dca_above:.4f}", dca_rounded, comment)
                        comment = re.sub(rf"{avg_plan.dont_dca_above:.2f}", dca_rounded, comment)
                        lines.append(f"❌ Не усреднять выше <b>{dca_rounded}</b>. {comment}")
                    else:
                        lines.append(f"❌ Не усреднять выше: <b>{dca_rounded}</b>")
                
                # Добавляем итоговый блок с главным смыслом для multi-TF
                if has_conflict:
                    # Анализируем фазы для итогового вывода
                    phases_by_tf = {tf: multi_diag.snapshots[tf].phase.value for tf in available_tfs}
                    senior_tfs = [tf for tf in available_tfs if tf in ['4h', '1d']]
                    junior_tfs = [tf for tf in available_tfs if tf == '1h']
                    
                    if senior_tfs and junior_tfs:
                        senior_phases = [phases_by_tf[tf] for tf in senior_tfs]
                        junior_phases = [phases_by_tf[tf] for tf in junior_tfs]
                        
                        # Определяем основной режим старших ТФ
                        from collections import Counter
                        senior_mode = Counter(senior_phases).most_common(1)[0][0]
                        junior_mode = Counter(junior_phases).most_common(1)[0][0] if junior_phases else None
                        
                        if senior_mode in ['DISTRIBUTION', 'EXPANSION_DOWN']:
                            if junior_mode == 'ACCUMULATION':
                                lines.append("")
                                lines.append("💡 <b>Итог:</b> Старшие ТФ в распределении (4h/1d), локальный 1h-откат. "
                                           "Любые лонги — против старшего режима, лучше искать продажи от сопротивлений или ждать новой базы.")
                        elif senior_mode in ['ACCUMULATION', 'EXPANSION_UP']:
                            if junior_mode in ['DISTRIBUTION', 'EXPANSION_DOWN']:
                                lines.append("")
                                lines.append("💡 <b>Итог:</b> Старшие ТФ в накоплении/росте (4h/1d), локальный 1h-коррекция. "
                                           "Коррекция может быть возможностью для входа, но нужно подтверждение на старших ТФ.")
                
                lines.append("")
                lines.append("━━━━━━━━━━━━━━━━━━━━")
                lines.append("<i>⚠️ Данные подсказки носят информационный характер и не являются финансовой рекомендацией.</i>")
        
        return "\n".join(lines)
    
    def _average_trade_plans(self, trade_plans: Dict[str, "TradePlan"]) -> Optional["TradePlan"]:
        """
        Усреднить торговые планы по нескольким таймфреймам.
        
        Args:
            trade_plans: Словарь торговых планов {"1h": plan, "4h": plan, "1d": plan}
        
        Returns:
            Усредненный торговый план или None
        """
        if not trade_plans:
            return None
        
        from .trade_planner import TradePlan
        
        # Собираем все лимитные зоны
        limit_zones = []
        breakout_levels = []
        dont_dca_levels = []
        small_allowed_count = 0
        total_count = len(trade_plans)
        
        # Определяем общий режим (берем наиболее частый)
        modes = [plan.mode for plan in trade_plans.values()]
        from collections import Counter
        most_common_mode = Counter(modes).most_common(1)[0][0] if modes else "neutral"
        
        # Собираем комментарии
        small_comments = []
        
        for plan in trade_plans.values():
            if plan.small_position_allowed:
                small_allowed_count += 1
            if plan.small_position_comment:
                small_comments.append(plan.small_position_comment)
            
            if plan.limit_buy_zone:
                limit_zones.append(plan.limit_buy_zone)
            
            if plan.add_on_breakout_level:
                breakout_levels.append(plan.add_on_breakout_level)
            
            if plan.dont_dca_above:
                dont_dca_levels.append(plan.dont_dca_above)
        
        # Усредняем small_position_allowed (большинство должно разрешать)
        small_allowed = small_allowed_count > total_count / 2
        
        # Формируем усредненный комментарий
        if small_comments:
            # Берем наиболее частый комментарий или первый, если все разные
            comment_counter = Counter(small_comments)
            most_common_comment = comment_counter.most_common(1)[0][0]
            small_comment = most_common_comment
        else:
            small_comment = "Условия нейтральные" if small_allowed else "Сейчас идёт направленный дамп, пробная позиция повышенного риска."
        
        # Усредняем лимитные зоны (берем среднее от всех зон)
        limit_zone = None
        limit_comment = None
        if limit_zones:
            all_lows = [zone[0] for zone in limit_zones]
            all_highs = [zone[1] for zone in limit_zones]
            avg_low = sum(all_lows) / len(all_lows)
            avg_high = sum(all_highs) / len(all_highs)
            limit_zone = (avg_low, avg_high)
            # Убираем цены из комментария - они будут выведены отдельно с округлением
            limit_comment = "Сильная поддержка и кластеры объёмов ниже текущей цены."
        
        # Усредняем уровни пробоя (берем среднее)
        breakout_level = None
        breakout_comment = None
        if breakout_levels:
            breakout_level = sum(breakout_levels) / len(breakout_levels)
            # Убираем цены из комментария - они будут выведены отдельно с округлением
            breakout_comment = "Имеет смысл увеличивать позицию только после закрепления выше этого уровня — это пробой кластера сопротивлений (EMA/Bollinger/локальные хайи)."
        
        # Усредняем уровни DCA (берем среднее)
        dont_dca_level = None
        dont_dca_comment = None
        if dont_dca_levels:
            dont_dca_level = sum(dont_dca_levels) / len(dont_dca_levels)
            # Убираем цены из комментария - они будут выведены отдельно с округлением
            dont_dca_comment = "Выше этого уровня начинается зона сильных сопротивлений — здесь уже логичнее фиксировать прибыль, чем усреднять убыток."
        
        return TradePlan(
            mode=most_common_mode,
            small_position_allowed=small_allowed,
            small_position_comment=small_comment,
            limit_buy_zone=limit_zone,
            limit_buy_comment=limit_comment,
            add_on_breakout_level=breakout_level,
            add_on_breakout_comment=breakout_comment,
            dont_dca_above=dont_dca_level,
            dont_dca_comment=dont_dca_comment
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
    
    def _get_liquidity_emoji(self, liquidity) -> str:
        """Получить эмодзи для ликвидности."""
        emoji_map = {
            "LOW": "🔴",
            "MEDIUM": "🟡",
            "HIGH": "🟢"
        }
        return emoji_map.get(liquidity.value, "⚪")
    
    def _get_money_flow_hint(self, extra: dict, diag) -> Optional[str]:
        """Получить смысловой вывод для OBV/CMF."""
        try:
            money_flow_state = extra.get('money_flow_state', '')
            
            # Проверяем OBV направление
            obv_down = '↓' in money_flow_state or 'Падение' in money_flow_state
            
            # Пытаемся получить CMF значение
            cmf_value = None
            if 'CMF:' in money_flow_state:
                import re
                cmf_match = re.search(r'CMF:\s*([-+]?\d+\.?\d*)', money_flow_state)
                if cmf_match:
                    cmf_value = float(cmf_match.group(1))
            
            # Определяем тренд цены (упрощённо через pump_score или phase)
            price_rising = diag.pump_score > 0.5 or diag.phase.value in ['ACCUMULATION', 'EXPANSION_UP']
            
            hints = []
            
            # OBV не подтверждает рост
            if obv_down and price_rising:
                hints.append("⚠️ рост без подтверждения объёмом — возможен ложный импульс")
            
            # CMF отрицательный (исправляем противоречие: |CMF| < 0.05 → нейтрально)
            if cmf_value is not None:
                if abs(cmf_value) < 0.05:
                    # Не добавляем hint для нейтрального CMF
                    pass
                elif cmf_value < -0.05:
                    hints.append("преобладает отток капитала")
                elif cmf_value > 0.05:
                    hints.append("приток капитала подтверждает движение")
            
            # OBV падает при росте цены
            if obv_down and price_rising:
                hints.append("объём скорее не подтверждает рост, покупатели пассивны")
            
            if hints:
                return " • ".join(hints)
            
            return None
        except Exception:
            return None
    
    def _generate_tldr(self, diag: MarketDiagnostics, plan: Optional[TradePlan] = None) -> Optional[str]:
        """Сгенерировать краткое TL;DR резюме."""
        try:
            parts = []
            
            # Направление
            if diag.pump_score > 0.6:
                direction = "лонг-сетап"
            elif diag.pump_score < 0.4:
                direction = "медвежий сетап"
            else:
                direction = "нейтральный сетап"
            
            # Сила
            if diag.pump_score >= 0.75:
                strength = "сильный"
            elif diag.pump_score >= 0.6:
                strength = "умеренный"
            else:
                strength = "слабый"
            
            parts.append(f"{strength} {direction}")
            
            # Фаза
            phase_map = {
                "ACCUMULATION": "внутри накопления",
                "DISTRIBUTION": "в распределении",
                "EXPANSION_UP": "в росте",
                "EXPANSION_DOWN": "в падении"
            }
            phase_desc = phase_map.get(diag.phase.value, "")
            if phase_desc:
                parts.append(phase_desc)
            
            # Режим
            if plan and plan.regime_info:
                regime_text = plan.regime_info.lower().replace("режим:", "").strip()
                if regime_text:
                    parts.append(f"в режиме {regime_text}")
            
            # Рекомендация
            if plan:
                if plan.limit_buy_zone:
                    low, high = plan.limit_buy_zone
                    low_rounded = self._round_price(low)
                    high_rounded = self._round_price(high)
                    parts.append(f"лучше ждать скидку до {low_rounded}–{high_rounded}")
                elif plan.add_on_breakout_level:
                    breakout_rounded = self._round_price(plan.add_on_breakout_level)
                    parts.append(f"лучше ждать пробой {breakout_rounded}")
                elif not plan.small_position_allowed:
                    parts.append("лучше не входить")
            
            if parts:
                return ", ".join(parts) + "."
            
            return None
        except Exception:
            return None
    
    def _calculate_grade(
        self, 
        pump_score: float, 
        risk_score: float, 
        confidence: float, 
        effective_threshold: Optional[float] = None,
        reliability_score: Optional[float] = None,
        tradability_state: Optional[str] = None,
        user_profile: Optional[str] = None
    ) -> tuple[str, str]:
        """
        Рассчитать Grade сетапа (A/B/C) с учётом всех факторов.
        
        Args:
            pump_score: Pump score
            risk_score: Risk score
            confidence: Confidence score
            effective_threshold: Адаптивный порог pump_score
            reliability_score: Надёжность паттерна (0.0-1.0)
            tradability_state: Состояние ликвидности (LOW/MEDIUM/HIGH)
            user_profile: Профиль пользователя (Conservative/Balanced/Aggressive)
        
        Returns:
            (grade, description) - например ("B", "средний сетап")
        """
        # Проверяем относительно адаптивного порога, если есть
        threshold = effective_threshold if effective_threshold is not None else 0.7
        
        # Понижаем Grade если reliability низкая
        reliability_penalty = False
        if reliability_score is not None and reliability_score < 0.5:
            reliability_penalty = True
        
        # Понижаем Grade если ликвидность низкая
        liquidity_penalty = False
        if tradability_state == "LOW":
            liquidity_penalty = True
        
        # Для консервативных профилей требуем более высокий pump
        conservative_threshold = threshold
        if user_profile == "Conservative":
            conservative_threshold = max(threshold, 0.75)
        
        # Grade A: pump ≥ threshold, risk ≤ 0.5, confidence ≥ 0.7, reliability ≥ 0.7, не LOW ликвидность
        if (pump_score >= conservative_threshold and 
            risk_score <= 0.5 and 
            confidence >= 0.7 and
            (reliability_score is None or reliability_score >= 0.7) and
            not liquidity_penalty):
            return ("A", "сильный исторически устойчивый сетап")
        
        # Grade B: pump ≥ 0.6, risk ≤ 0.6, нет серьёзных штрафов
        if (pump_score >= 0.6 and 
            risk_score <= 0.6 and
            not reliability_penalty and
            not liquidity_penalty):
            return ("B", "средний сетап с приемлемым соотношением риск/потенциал")
        
        # Grade C: всё остальное
        reasons = []
        if pump_score < threshold:
            reasons.append(f"Pump ниже порога ({threshold:.2f})")
        if reliability_penalty:
            reasons.append("низкая надёжность паттерна")
        if liquidity_penalty:
            reasons.append("низкая ликвидность")
        if risk_score > 0.6:
            reasons.append("повышенный риск")
        
        if reasons:
            desc = ", ".join(reasons)
            if liquidity_penalty and user_profile != "Aggressive":
                desc += " — сетап только для агрессивных профилей или наблюдения"
            return ("C", desc)
        else:
            return ("C", "слабый сетап, требует дополнительного подтверждения")
    
    def _round_price(self, price: float) -> str:
        """
        Округлить цену до разумного значения для отображения.
        
        Для BTC/ETH (>1000): округляем до 10-50
        Для средних (>10): округляем до 1-5
        Для малых: округляем до 0.1-0.5
        """
        if price >= 1000:
            # Округляем до 10 или 50
            rounded = round(price / 10) * 10
            if rounded % 50 == 0:
                return f"{int(rounded):,}"
            return f"{int(rounded):,}"
        elif price >= 10:
            # Округляем до 1 или 5
            rounded = round(price)
            return f"{rounded:.0f}"
        elif price >= 1:
            # Округляем до 0.1 или 0.5
            rounded = round(price * 2) / 2
            return f"{rounded:.1f}"
        else:
            # Округляем до 0.01 или 0.05
            rounded = round(price * 20) / 20
            return f"{rounded:.2f}"

