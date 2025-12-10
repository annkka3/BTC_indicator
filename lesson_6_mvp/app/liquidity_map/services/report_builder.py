# app/liquidity_map/services/report_builder.py
"""
Построитель текстового отчета с эталонной иерархией:
1. Régime (режим рынка)
2. Context (где цена находится)
3. Pressure (кто сильнее)
4. Reaction (что цена показала)
5. Decision (что делать / не делать)
"""
from typing import List
from datetime import datetime
from ..domain.models import TimeframeSnapshot
from ..domain.enums import ZoneType, ZoneRole, MarketRegime
from .regime_classifier import classify_regime, get_regime_description
from .zone_classifier import get_execution_zones, get_invalidation_zones
from .confidence_calculator import calculate_confidence_score


def build_text_report(snapshots: List[TimeframeSnapshot], symbol: str) -> str:
    """
    Построить текстовый отчет с эталонной иерархией.
    
    Args:
        snapshots: Список снимков (от меньшего к большему ТФ)
        symbol: Символ
    
    Returns:
        Текстовый отчет в формате HTML для Telegram
    """
    if not snapshots:
        return "<b>Liquidity Heat Intelligence Report</b>\n\nНет данных."
    
    # Берем цену из первого непустого snapshot
    current_price = 0.0
    for snapshot in snapshots:
        if snapshot.current_price > 0:
            current_price = snapshot.current_price
            break
    
    current_time = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    
    # Заголовок
    report = f"""<b>Liquidity Heat Intelligence Report</b>

<b>{symbol} / USDT</b>
Price: ${current_price:,.2f}
Date: {current_time}

"""
    
    # 1. RÉGIME (режим рынка) - ВСЕГДА ПЕРВЫМ
    regime = classify_regime(snapshots)
    regime_desc = get_regime_description(regime, symbol)
    report += f"<b>📊 MARKET REGIME</b>\n{regime_desc}\n\n"
    
    # 2. CONTEXT (где цена находится)
    context = _generate_context(snapshots, current_price)
    report += f"<b>📍 Context</b>\n{context}\n\n"
    
    # 3. PRESSURE (вербальные состояния, не проценты)
    pressure = _generate_pressure_states(snapshots)
    report += f"<b>⚖️ Pressure</b>\n{pressure}\n\n"
    
    # 4. REACTION (что цена показала)
    reaction = _generate_reaction(snapshots)
    if reaction:
        report += f"<b>🔄 Reaction</b>\n{reaction}\n\n"
    
    # 5. DECISION LAYER (Allowed/Forbidden/Risk Notes)
    decision_layer = _generate_decision_layer(snapshots, current_price, regime)
    report += f"<b>🎯 DECISION LAYER</b>\n{decision_layer}\n\n"
    
    # Confidence Score
    confidence_score, confidence_interp = calculate_confidence_score(snapshots, regime, current_price)
    report += f"<b>📈 Confidence Score: {confidence_score} / 100</b>\n{confidence_interp}\n"
    
    return report


def _generate_context(snapshots: List[TimeframeSnapshot], current_price: float) -> str:
    """Генерировать Context (где цена находится)."""
    if not snapshots or current_price == 0:
        return "Недостаточно данных."
    
    # Находим якорный snapshot (1h)
    anchor_snapshot = next((s for s in snapshots if s.tf == "1h"), None)
    if not anchor_snapshot:
        anchor_snapshot = snapshots[0]
    
    # Ищем EXECUTION зоны
    execution_zones = get_execution_zones(snapshots)
    
    context_parts = []
    
    # Проверяем, находится ли цена в EXECUTION зоне
    price_in_execution = False
    for zone in execution_zones:
        if zone.price_low <= current_price <= zone.price_high:
            price_in_execution = True
            zone_type_text = "buy" if zone.zone_type == ZoneType.BUY else "sell"
            if zone.price_low >= 1000:
                price_str = f"${round(zone.price_low/1000, 1):.1f}k–${round(zone.price_high/1000, 1):.1f}k"
            else:
                price_str = f"${zone.price_low:,.0f}–${zone.price_high:,.0f}"
            context_parts.append(f"Цена находится внутри {zone.tf} {zone_type_text}-зоны ({price_str})")
            break
    
    if not price_in_execution:
        # Ищем ближайшую зону
        all_zones = []
        for snapshot in snapshots:
            all_zones.extend(snapshot.active_zones)
        
        if all_zones:
            nearest_zone = min(all_zones, key=lambda z: abs(z.center_price - current_price))
            distance_pct = abs(current_price - nearest_zone.center_price) / current_price * 100
            zone_type_text = "buy" if nearest_zone.zone_type == ZoneType.BUY else "sell"
            context_parts.append(f"Цена вне зон, ближайшая {nearest_zone.tf} {zone_type_text}-зона на расстоянии {distance_pct:.1f}%")
        else:
            context_parts.append("Активных зон нет, цена вне структуры")
    
    return " ".join(context_parts) if context_parts else "Недостаточно данных для определения контекста."


def _generate_pressure_states(snapshots: List[TimeframeSnapshot]) -> str:
    """Генерировать вербальные состояния давления."""
    if not snapshots:
        return "Нет данных."
    
    pressure_parts = []
    
    # Показываем только ключевые ТФ
    key_tfs = ["15m", "1h", "4h", "1d"]
    for snapshot in snapshots:
        if snapshot.tf in key_tfs:
            pressure_stat = snapshot.pressure_stat
            state = pressure_stat.state
            pressure_parts.append(f"{snapshot.tf}: {state}")
    
    return "\n".join(pressure_parts) if pressure_parts else "Нет данных."


def _generate_reaction(snapshots: List[TimeframeSnapshot]) -> str:
    """Генерировать Reaction (что цена показала)."""
    if not snapshots:
        return ""
    
    # Находим якорный snapshot
    anchor_snapshot = next((s for s in snapshots if s.tf == "1h"), None)
    if not anchor_snapshot:
        return ""
    
    execution_zones = get_execution_zones(snapshots)
    if not execution_zones:
        return ""
    
    reaction_parts = []
    
    for zone in execution_zones[:2]:  # Максимум 2 зоны
        if zone.reactions >= 5:
            zone_type_text = "buy" if zone.zone_type == ZoneType.BUY else "sell"
            reaction_parts.append(f"{zone.tf} {zone_type_text}-зона: {zone.reactions} реакций (подтверждена)")
        elif zone.reactions > 0:
            zone_type_text = "buy" if zone.zone_type == ZoneType.BUY else "sell"
            reaction_parts.append(f"{zone.tf} {zone_type_text}-зона: {zone.reactions} реакций (слабо протестирована)")
    
    return "\n".join(reaction_parts) if reaction_parts else ""


def _generate_decision_layer(snapshots: List[TimeframeSnapshot], current_price: float, 
                             regime: MarketRegime) -> str:
    """Генерировать Decision Layer (Allowed/Forbidden/Risk Notes)."""
    if not snapshots or current_price == 0:
        return "Недостаточно данных для принятия решений."
    
    decision_parts = []
    
    # Allowed
    execution_zones = get_execution_zones(snapshots)
    allowed_parts = []
    
    for zone in execution_zones[:2]:  # Максимум 2 зоны
        zone_type_text = "Buy" if zone.zone_type == ZoneType.BUY else "Sell"
        if zone.price_low >= 1000:
            price_str = f"${round(zone.price_low/1000, 1):.1f}k–${round(zone.price_high/1000, 1):.1f}k"
        else:
            price_str = f"${zone.price_low:,.0f}–${zone.price_high:,.0f}"
        
        if zone_type_text == "Buy":
            allowed_parts.append(f"— Long from {zone.tf} {zone_type_text}-Zone {price_str}")
        else:
            allowed_parts.append(f"— Short from {zone.tf} {zone_type_text}-Zone {price_str}")
    
    if not allowed_parts:
        allowed_parts.append("— No execution zones available")
    
    decision_parts.append("✅ <b>Allowed:</b>")
    decision_parts.extend(allowed_parts)
    decision_parts.append("")
    
    # Forbidden
    forbidden_parts = []
    
    # Проверяем INVALIDATION зоны
    invalidation_zones = get_invalidation_zones(snapshots, current_price)
    for zone in invalidation_zones:
        zone_type_text = "sell" if zone.zone_type == ZoneType.SELL else "buy"
        forbidden_parts.append(f"— {zone_type_text.capitalize()}s inside {zone.tf} {zone_type_text}-zones")
    
    # Общие правила
    anchor_snapshot = next((s for s in snapshots if s.tf == "1h"), None)
    if anchor_snapshot:
        anchor_bias = anchor_snapshot.bias
        if anchor_bias == "LONG":
            forbidden_parts.append("— Shorts inside 1h buy-zones")
        elif anchor_bias == "SHORT":
            forbidden_parts.append("— Longs inside 1h sell-zones")
    
    # Если нет execution zones
    if not execution_zones:
        forbidden_parts.append("— Longs outside zones (no edge)")
        forbidden_parts.append("— Shorts outside zones (no edge)")
    
    if not forbidden_parts:
        forbidden_parts.append("— No specific restrictions")
    
    decision_parts.append("❌ <b>Forbidden:</b>")
    decision_parts.extend(forbidden_parts)
    decision_parts.append("")
    
    # Risk Notes
    risk_parts = []
    
    # Контртренд
    if regime == MarketRegime.COUNTER_TREND_BOUNCE:
        ltf_snapshot = next((s for s in snapshots if s.tf in ["15m", "1h"]), None)
        if ltf_snapshot:
            risk_parts.append(f"— Counter-trend pressure on {ltf_snapshot.tf}")
    
    # Конфликты ТФ
    htf_snapshots = [s for s in snapshots if s.tf in ["4h", "1d"]]
    ltf_snapshots = [s for s in snapshots if s.tf in ["15m", "1h"]]
    
    if htf_snapshots and ltf_snapshots:
        htf_bias = htf_snapshots[0].bias
        ltf_bias = ltf_snapshots[0].bias
        if htf_bias != ltf_bias and htf_bias != "NEUTRAL" and ltf_bias != "NEUTRAL":
            risk_parts.append(f"— Conflict between HTF ({htf_bias}) and LTF ({ltf_bias})")
    
    # Близкие invalidation зоны
    for zone in invalidation_zones:
        if zone.price_low >= 1000:
            price_str = f"${round(zone.price_low/1000, 1):.1f}k"
        else:
            price_str = f"${zone.price_low:,.0f}"
        risk_parts.append(f"— Expect false breaks near {price_str}")
    
    if not risk_parts:
        risk_parts.append("— No specific risk notes")
    
    decision_parts.append("⚠️ <b>Risk Notes:</b>")
    decision_parts.extend(risk_parts)
    
    return "\n".join(decision_parts)


def _generate_tldr(snapshots: List[TimeframeSnapshot]) -> str:
    """Генерировать краткое резюме на основе конфликтов ТФ."""
    if len(snapshots) < 2:
        return "Недостаточно данных для анализа."
    
    # Разделяем на младшие (5m, 15m, 1h) и старшие (4h, 1d) ТФ
    short_tfs = ["5m", "15m", "1h"]
    long_tfs = ["4h", "1d"]
    
    long_bias_tfs = []
    short_bias_tfs = []
    
    for snapshot in snapshots:
        if snapshot.tf in short_tfs:
            if snapshot.buy_pressure > 60:
                long_bias_tfs.append(snapshot.tf)
            elif snapshot.sell_pressure > 60:
                short_bias_tfs.append(snapshot.tf)
        elif snapshot.tf in long_tfs:
            if snapshot.buy_pressure > 60:
                long_bias_tfs.append(snapshot.tf)
            elif snapshot.sell_pressure > 60:
                short_bias_tfs.append(snapshot.tf)
    
    # Анализируем конфликты
    short_tf_long = [s for s in snapshots if s.tf in short_tfs and s.buy_pressure > 60]
    short_tf_short = [s for s in snapshots if s.tf in short_tfs and s.sell_pressure > 60]
    long_tf_long = [s for s in snapshots if s.tf in long_tfs and s.buy_pressure > 60]
    long_tf_short = [s for s in snapshots if s.tf in long_tfs and s.sell_pressure > 60]
    
    # Конфликт между младшими и старшими ТФ
    if (len(short_tf_long) > 0 or len(short_tf_short) > 0) and (len(long_tf_long) > 0 or len(long_tf_short) > 0):
        if len(short_tf_long) > 0 and len(long_tf_short) > 0:
            # Проверяем силу конфликта для предупреждения
            long_tf_sell_snapshot = next((s for s in snapshots if s.tf in long_tfs and s.sell_pressure > 70), None)
            if long_tf_sell_snapshot:
                return "Локальное восстановление на младших ТФ внутри нисходящей структуры старших ТФ. ⚠️ Движение остаётся контртрендовым относительно дневной структуры. Агрессивные лонги без реакции от зон повышенного риска."
            else:
                return "Локальное восстановление на младших ТФ внутри нисходящей структуры старших ТФ."
        elif len(short_tf_short) > 0 and len(long_tf_long) > 0:
            return "Коррекция на младших ТФ внутри восходящей структуры старших ТФ."
        else:
            return "Смешанные сигналы между младшими и старшими ТФ. Требуется осторожность."
    
    # Согласованность
    if len(long_bias_tfs) > len(short_bias_tfs):
        if len(long_bias_tfs) >= 3:
            return "Большинство ТФ поддерживают сценарий роста."
        else:
            return "Преимущественно восходящее давление, но не на всех ТФ."
    elif len(short_bias_tfs) > len(long_bias_tfs):
        if len(short_bias_tfs) >= 3:
            return "Большинство ТФ поддерживают сценарий снижения."
        else:
            return "Преимущественно нисходящее давление, но не на всех ТФ."
    else:
        return "Баланс сил смешанный, явного преимущества нет."


def _format_tf_block(snapshot: TimeframeSnapshot) -> str:
    """Форматировать блок для одного таймфрейма."""
    block = f"""<b>⏱ {snapshot.tf}</b>

Buy pressure: {snapshot.buy_pressure:.1f}%
Sell pressure: {snapshot.sell_pressure:.1f}%

"""
    
    # Активные зоны
    active_zones = snapshot.active_zones
    if active_zones:
        block += "<b>Active zones:</b>\n"
        for zone in active_zones[:5]:  # Показываем до 5 зон
            zone_type_emoji = "🟢" if zone.zone_type == ZoneType.BUY else "🔴"
            block += f"- {zone_type_emoji} {zone.zone_type.value} zone ${zone.price_low:,.2f}–${zone.price_high:,.2f} (strength {zone.strength:.2f}, reactions {zone.reactions})\n"
    else:
        block += "Активных зон нет, баланс условно нейтрален — на этом ТФ нет edge.\n"
    
    block += "\n"
    
    # Интерпретация (пропускаем, если нет зон)
    if active_zones:
        interpretation = _generate_interpretation(snapshot)
        block += f"<i>Interpretation:</i>\n{interpretation}\n"
    
    return block


def _generate_interpretation(snapshot: TimeframeSnapshot) -> str:
    """Генерировать интерпретацию для таймфрейма на основе давления."""
    active_zones = snapshot.active_zones
    bp = snapshot.buy_pressure
    sp = snapshot.sell_pressure
    
    if not active_zones:
        return ""
    
    interpretations = []
    
    # Определяем доминирующую сторону на основе давления
    dominant = "buy" if bp > sp else "sell"
    dominance = max(bp, sp)
    
    # Правило 1: текст от давления (разные формулировки для разных уровней)
    if dominance > 85:
        if dominant == "buy":
            interpretations.append("Режим почти односторонний, контртрендовые сделки имеют низкий edge.")
        else:
            interpretations.append("Режим почти односторонний, контртрендовые сделки имеют низкий edge.")
    elif 70 < dominance <= 85:
        if dominant == "buy":
            interpretations.append("Преимущество на стороне покупателей, но рынок ещё не в экстремальной фазе.")
        else:
            interpretations.append("Преимущество на стороне продавцов, но рынок ещё не в экстремальной фазе.")
    elif 55 < dominance <= 70:
        if dominant == "buy":
            interpretations.append("Buy-зоны преобладают, но баланс ещё не экстремальный.")
        else:
            interpretations.append("Sell-зоны преобладают, но баланс ещё не экстремальный.")
    else:
        interpretations.append("Баланс между buy- и sell-зонами близок к нейтральному.")
    
    # Явный bias
    if dominance > 70:
        if dominant == "buy":
            interpretations.append("Bias: лонг, работать от спроса.")
        else:
            interpretations.append("Bias: шорт, работать от предложения.")
    else:
        interpretations.append("Bias: нейтральный, работаем только от реакций на зоны.")
    
    # Блок про реакции (один раз, с разными формулировками)
    if active_zones:
        avg_reactions = sum(z.reactions for z in active_zones) / len(active_zones)
        if avg_reactions >= 30:
            interpretations.append("Зоны многократно подтверждены историей цены.")
        elif avg_reactions >= 5:
            interpretations.append("Зоны уже несколько раз протестированы, но без экстремальных реакций.")
        else:
            interpretations.append("Большая часть зон пока слабо проверена реальной торговлей.")
    
    # Анализ силы зон (только если не упомянуто выше)
    if active_zones and dominance <= 70:
        avg_strength = sum(z.strength for z in active_zones) / len(active_zones)
        if avg_strength > 0.7:
            interpretations.append("Высокая концентрация ликвидности в зонах.")
        elif avg_strength < 0.3:
            interpretations.append("Слабая концентрация ликвидности.")
    
    if not interpretations:
        return "Нейтральная картина ликвидности."
    
    return " ".join(interpretations)


def _format_summary_table(snapshots: List[TimeframeSnapshot]) -> str:
    """Форматировать сводную таблицу."""
    table = "<b>📊 Сводная таблица</b>\n\n"
    table += "<code>TF    Buy    Sell    Bias</code>\n"
    
    for snapshot in snapshots:
        bias_emoji = {
            "LONG": "🟢",
            "SHORT": "🔴",
            "NEUTRAL": "🟡"
        }.get(snapshot.bias, "⚪")
        
        table += f"<code>{snapshot.tf:4s}  {snapshot.buy_pressure:5.1f}%  {snapshot.sell_pressure:5.1f}%  {bias_emoji}</code>\n"
    
    return table


def _generate_decision(snapshots: List[TimeframeSnapshot]) -> str:
    """Генерировать решение на основе всех таймфреймов."""
    if not snapshots:
        return "WAIT / OBSERVE"
    
    # Подсчитываем bias
    biases = [s.bias for s in snapshots]
    long_count = biases.count("LONG")
    short_count = biases.count("SHORT")
    neutral_count = biases.count("NEUTRAL")
    
    # Проверяем конфликты
    has_conflict = (long_count > 0 and short_count > 0)
    
    if neutral_count == len(snapshots):
        return "WAIT / OBSERVE"
    elif has_conflict:
        return "TRADE ONLY FROM ZONES"
    elif long_count > short_count:
        return "CONSIDER LONG (with zone confirmation)"
    elif short_count > long_count:
        return "CONSIDER SHORT (with zone confirmation)"
    else:
        return "WAIT / OBSERVE"


def build_short_caption(snapshots: List[TimeframeSnapshot], symbol: str) -> str:
    """
    Построить короткий caption для изображения (максимум 1024 символа).
    
    Args:
        snapshots: Список снимков
        symbol: Символ
    
    Returns:
        Короткий caption
    """
    if not snapshots:
        return f"<b>Liquidity Heat Intelligence - {symbol}/USDT</b>"
    
    # Берем цену из первого непустого snapshot
    current_price = 0.0
    for snapshot in snapshots:
        if snapshot.current_price > 0:
            current_price = snapshot.current_price
            break
    
    current_time = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    
    # Régime
    from .regime_classifier import classify_regime, get_regime_description
    regime = classify_regime(snapshots)
    regime_desc = get_regime_description(regime, symbol)
    
    # Confidence Score
    from .confidence_calculator import calculate_confidence_score
    confidence_score, confidence_interp = calculate_confidence_score(snapshots, regime, current_price)
    
    caption = f"""📊 <b>Liquidity Heat Intelligence — {symbol}/USDT</b>

<b>📊 Régime:</b> {regime_desc}
<b>📈 Confidence:</b> {confidence_score}/100

Полный отчёт ниже 👇"""
    
    # Обрезаем до 1024 символов, если нужно
    if len(caption) > 1024:
        caption = caption[:1020] + "..."
    
    return caption


def build_compact_report(snapshots: List[TimeframeSnapshot], symbol: str) -> str:
    """
    Построить компактный отчет (1-2 экрана) для Telegram.
    
    Args:
        snapshots: Список снимков
        symbol: Символ
    
    Returns:
        Компактный отчет
    """
    if not snapshots:
        return f"📊 <b>Liquidity Heat Intelligence — {symbol}/USDT</b>\n\nНет данных."
    
    # Берем цену из первого непустого snapshot
    current_price = 0.0
    for snapshot in snapshots:
        if snapshot.current_price > 0:
            current_price = snapshot.current_price
            break
    
    current_time = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    
    # Заголовок
    report = f"""📊 <b>Liquidity Heat Intelligence — {symbol}/USDT</b>

Цена: ${current_price:,.2f} | {current_time}

"""
    
    # 1. Régime (первым)
    from .regime_classifier import classify_regime, get_regime_description
    regime = classify_regime(snapshots)
    regime_desc = get_regime_description(regime, symbol)
    report += f"<b>📊 MARKET REGIME</b>\n{regime_desc}\n\n"
    
    # 2. Pressure (вербальные состояния)
    pressure = _generate_pressure_states(snapshots)
    report += f"<b>⚖️ Pressure</b>\n{pressure}\n\n"
    
    # 3. Confidence Score
    from .confidence_calculator import calculate_confidence_score
    confidence_score, confidence_interp = calculate_confidence_score(snapshots, regime, current_price)
    report += f"<b>📈 Confidence: {confidence_score}/100</b>\n{confidence_interp}\n\n"
    
    # Таблица по ТФ
    report += "<code>TF  | Buy / Sell | Bias</code>\n"
    for snapshot in snapshots:
        bp = snapshot.buy_pressure
        sp = snapshot.sell_pressure
        bias_emoji = {
            "LONG": "🟢",
            "SHORT": "🔴",
            "NEUTRAL": "🟡"
        }.get(snapshot.bias, "⚪")
        
        # Формулировка bias
        if bp > 70:
            bias_text = "Сильный спрос (лонг-режим)"
        elif sp > 70:
            bias_text = "Локальное давление продавца"
        elif bp > sp and bp > 55:
            bias_text = "Наклон в лонг, но не экстремальный"
        elif sp > bp and sp > 55:
            bias_text = "Наклон в шорт, но не экстремальный"
        else:
            bias_text = "Флэт, без edge"
        
        report += f"<code>{snapshot.tf:4s} | {bp:3.0f} / {sp:3.0f} | {bias_emoji} {bias_text}</code>\n"
    
    report += "\n"
    
    # Ключевые зоны (EXECUTION зоны, или сильные активные зоны)
    from .zone_classifier import get_execution_zones
    execution_zones = get_execution_zones(snapshots)
    
    if execution_zones:
        report += "<b>🎯 Execution Zones:</b>\n"
        for zone in execution_zones[:2]:  # Максимум 2
            zone_type_emoji = "🟢" if zone.zone_type == ZoneType.BUY else "🔴"
            zone_type_text = "buy" if zone.zone_type == ZoneType.BUY else "sell"
            # Нормализуем цены
            if zone.price_low >= 1000:
                price_low_k = round(zone.price_low / 1000, 1)
                price_high_k = round(zone.price_high / 1000, 1)
                price_str = f"${price_low_k:.1f}k–${price_high_k:.1f}k"
            else:
                price_str = f"${zone.price_low:,.0f}–${zone.price_high:,.0f}"
            report += f"{zone.tf}: {zone_type_emoji} {price_str} ({zone_type_text})\n"
    else:
        # Если нет EXECUTION зон, показываем сильные активные зоны
        all_active_zones = []
        for snapshot in snapshots:
            for zone in snapshot.active_zones:
                if zone.strength >= 0.6 and zone.reactions >= 2:
                    all_active_zones.append(zone)
        
        if all_active_zones:
            # Сортируем по приоритету
            all_active_zones.sort(key=lambda z: (z.strength, z.reactions), reverse=True)
            report += "<b>📍 Key Zones (Context):</b>\n"
            for zone in all_active_zones[:2]:  # Максимум 2
                zone_type_emoji = "🟢" if zone.zone_type == ZoneType.BUY else "🔴"
                zone_type_text = "buy" if zone.zone_type == ZoneType.BUY else "sell"
                # Нормализуем цены
                if zone.price_low >= 1000:
                    price_low_k = round(zone.price_low / 1000, 1)
                    price_high_k = round(zone.price_high / 1000, 1)
                    price_str = f"${price_low_k:.1f}k–${price_high_k:.1f}k"
                else:
                    price_str = f"${zone.price_low:,.0f}–${zone.price_high:,.0f}"
                report += f"{zone.tf}: {zone_type_emoji} {price_str} ({zone_type_text})\n"
        else:
            report += "<b>⚠️ No Key Zones</b>\nNo edge available.\n"
    
    return report


def _calculate_global_liquidity_skew(snapshots: List[TimeframeSnapshot]) -> str:
    """
    Вычислить Global Liquidity Skew (интегральная оценка).
    
    Returns:
        Строка с описанием глобального bias
    """
    if not snapshots:
        return ""
    
    # Веса для каждого ТФ
    weights = {"5m": 1.0, "15m": 1.5, "1h": 2.0, "4h": 2.5, "1d": 3.0}
    
    score = 0.0
    total_weight = 0.0
    
    for snapshot in snapshots:
        weight = weights.get(snapshot.tf, 1.0)
        # Skew от -1 до +1
        skew = (snapshot.buy_pressure - snapshot.sell_pressure) / 100.0
        score += skew * weight
        total_weight += weight
    
    # Нормализуем
    if total_weight > 0:
        normalized_score = score / total_weight * 10  # Масштабируем для читаемости
    else:
        return ""
    
    # Определяем режим
    if normalized_score > 2.0:
        bias_text = f"Global Liquidity Bias: +{normalized_score:.1f} (лонг-режим)"
    elif normalized_score < -2.0:
        bias_text = f"Global Liquidity Bias: {normalized_score:.1f} (шорт-режим)"
    else:
        bias_text = f"Global Liquidity Bias: {normalized_score:+.1f} (нейтральный)"
    
    return bias_text


def _generate_execution_guidance(snapshots: List[TimeframeSnapshot]) -> str:
    """Генерировать Execution Guidance на основе зон и bias."""
    if not snapshots:
        return ""
    
    # Находим якорный TF (1h)
    anchor_snapshot = next((s for s in snapshots if s.tf == "1h"), None)
    if not anchor_snapshot:
        anchor_snapshot = snapshots[0]
    
    guidance_parts = []
    
    # Рабочий TF
    if anchor_snapshot.buy_pressure > 60 or anchor_snapshot.sell_pressure > 60:
        guidance_parts.append(f"— Рабочий TF: 15m → 1h")
    else:
        guidance_parts.append(f"— Рабочий TF: 5m → 15m (низкий edge на старших TF)")
    
    # Предпочтение направления
    anchor_bias = anchor_snapshot.bias
    if anchor_bias == "LONG":
        # Ищем ближайшую buy-зону
        buy_zones = [z for z in anchor_snapshot.active_zones if z.zone_type == ZoneType.BUY and z.strength > 0.6]
        if buy_zones:
            nearest_zone = min(buy_zones, key=lambda z: abs(z.center_price - anchor_snapshot.current_price))
            # Нормализуем цены
            if nearest_zone.price_low >= 1000:
                price_low_k = round(nearest_zone.price_low / 1000, 1)
                price_high_k = round(nearest_zone.price_high / 1000, 1)
                price_str = f"${price_low_k:.1f}k–${price_high_k:.1f}k"
            else:
                price_str = f"${nearest_zone.price_low:,.0f}–${nearest_zone.price_high:,.0f}"
            guidance_parts.append(f"— Предпочтение: лонг от 1h buy-зон ({price_str})")
        else:
            guidance_parts.append(f"— Предпочтение: лонг от 1h buy-зон")
    elif anchor_bias == "SHORT":
        # Ищем ближайшую sell-зону
        sell_zones = [z for z in anchor_snapshot.active_zones if z.zone_type == ZoneType.SELL and z.strength > 0.6]
        if sell_zones:
            nearest_zone = min(sell_zones, key=lambda z: abs(z.center_price - anchor_snapshot.current_price))
            # Нормализуем цены
            if nearest_zone.price_low >= 1000:
                price_low_k = round(nearest_zone.price_low / 1000, 1)
                price_high_k = round(nearest_zone.price_high / 1000, 1)
                price_str = f"${price_low_k:.1f}k–${price_high_k:.1f}k"
            else:
                price_str = f"${nearest_zone.price_low:,.0f}–${nearest_zone.price_high:,.0f}"
            guidance_parts.append(f"— Предпочтение: шорт от 1h sell-зон ({price_str})")
        else:
            guidance_parts.append(f"— Предпочтение: шорт от 1h sell-зон")
    else:
        guidance_parts.append(f"— Предпочтение: нейтральный, работаем только от реакций на зоны")
    
    # Шорты (если есть конфликт)
    higher_tf_snapshot = next((s for s in snapshots if s.tf in ["4h", "1d"]), None)
    if higher_tf_snapshot and higher_tf_snapshot.bias == "SHORT":
        sell_zones = [z for z in higher_tf_snapshot.active_zones if z.zone_type == ZoneType.SELL and z.strength > 0.7]
        if sell_zones:
            nearest_sell = min(sell_zones, key=lambda z: abs(z.center_price - anchor_snapshot.current_price))
            # Нормализуем цены
            if nearest_sell.price_low >= 1000:
                price_low_k = round(nearest_sell.price_low / 1000, 1)
                price_high_k = round(nearest_sell.price_high / 1000, 1)
                price_str = f"${price_low_k:.1f}k–${price_high_k:.1f}k"
            else:
                price_str = f"${nearest_sell.price_low:,.0f}–${nearest_sell.price_high:,.0f}"
            guidance_parts.append(f"— Шорты: только при реакции от {higher_tf_snapshot.tf} sell ({price_str})")
    
    # Вне зон
    if not anchor_snapshot.active_zones:
        guidance_parts.append(f"— Вне зон: edge отсутствует")
    else:
        # Проверяем, находится ли цена в зоне
        current_price = anchor_snapshot.current_price
        in_zone = any(z.price_low <= current_price <= z.price_high for z in anchor_snapshot.active_zones)
        if not in_zone:
            guidance_parts.append(f"— Вне зон: edge отсутствует, ждать входа в зону")
    
    return "\n".join(guidance_parts)

