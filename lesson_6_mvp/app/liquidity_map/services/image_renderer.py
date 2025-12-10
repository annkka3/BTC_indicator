# app/liquidity_map/services/image_renderer.py
"""
Рендерер изображения Liquidity Heat Map v2 - график свечей с зонами + pressure bars.
"""
import io
from typing import List, Dict
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle
from matplotlib.dates import date2num
from datetime import datetime, timezone, timedelta
import pandas as pd

from ..domain.models import TimeframeSnapshot, HeatZone
from ..domain.enums import ZoneType, ZoneRole, MarketRegime
from .data_loader import load_ohlcv_as_dataframe
from ...infrastructure.db import DB


# Константы layout
CANVAS_WIDTH = 1600
CANVAS_HEIGHT = 1800
DPI = 200
BG_COLOR = "#070B1A"

# Размеры колонок
MAIN_CHART_WIDTH_RATIO = 4
PRESSURE_BAR_WIDTH_RATIO = 1
HEADER_HEIGHT = 120

# Якорный таймфрейм для свечей
ANCHOR_TF = "1h"  # Можно изменить на "15m"

# Веса TF для визуального веса
TF_WEIGHTS = {
    "5m": 0.6,
    "15m": 0.8,
    "1h": 1.0,  # Якорный TF - максимальный вес
    "4h": 1.1,
    "1d": 1.2
}


def distance_factor(dist_atr: float) -> float:
    """
    Вычислить коэффициент прозрачности на основе расстояния до цены в ATR.
    
    Args:
        dist_atr: Расстояние до зоны в единицах ATR
    
    Returns:
        Коэффициент от 0.05 до 1.0
    """
    if dist_atr <= 0.5:
        return 1.0
    elif dist_atr <= 1.0:
        # 1.0 → 0.8
        return 1.0 - 0.2 * (dist_atr - 0.5) / 0.5
    elif dist_atr <= 2.0:
        # 0.8 → 0.4
        return 0.8 - 0.4 * (dist_atr - 1.0) / 1.0
    elif dist_atr <= 4.0:
        # 0.4 → 0.1
        return 0.4 - 0.3 * (dist_atr - 2.0) / 2.0
    else:
        return 0.05


def calculate_atr(df: pd.DataFrame, period: int = 14) -> float:
    """
    Вычислить ATR (Average True Range) для DataFrame.
    
    Args:
        df: DataFrame с колонками high, low, close
        period: Период для расчета ATR
    
    Returns:
        Последнее значение ATR
    """
    if df.empty or len(df) < period:
        # Fallback: используем 1% от текущей цены
        if not df.empty:
            return df['close'].iloc[-1] * 0.01
        return 100.0
    
    # Вычисляем True Range
    high = df['high']
    low = df['low']
    close = df['close']
    prev_close = close.shift(1)
    
    tr1 = high - low
    tr2 = abs(high - prev_close)
    tr3 = abs(low - prev_close)
    
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    
    # SMA за period
    atr = tr.rolling(window=period).mean()
    
    # Возвращаем последнее значение
    atr_value = atr.iloc[-1]
    if pd.isna(atr_value):
        # Fallback
        return df['close'].iloc[-1] * 0.01
    
    return float(atr_value)


def draw_layout(snapshots: List[TimeframeSnapshot], symbol: str, db: DB) -> bytes:
    """
    Нарисовать новый layout: график свечей с зонами слева, pressure bars справа.
    
    Args:
        snapshots: Список снимков (должно быть 5: 5m, 15m, 1h, 4h, 1d)
        symbol: Символ
        db: База данных для загрузки свечей
    
    Returns:
        PNG bytes
    """
    # Создаем фигуру с двумя колонками
    fig = plt.figure(figsize=(CANVAS_WIDTH/DPI, CANVAS_HEIGHT/DPI), dpi=DPI, facecolor=BG_COLOR)
    gs = fig.add_gridspec(2, 2, height_ratios=[HEADER_HEIGHT, CANVAS_HEIGHT-HEADER_HEIGHT], 
                          width_ratios=[MAIN_CHART_WIDTH_RATIO, PRESSURE_BAR_WIDTH_RATIO],
                          hspace=0, wspace=0.02)
    
    # Header (на всю ширину)
    ax_header = fig.add_subplot(gs[0, :])
    ax_header.set_facecolor(BG_COLOR)
    ax_header.axis('off')
    
    # Основной график (слева)
    ax_main = fig.add_subplot(gs[1, 0])
    ax_main.set_facecolor(BG_COLOR)
    
    # Pressure bars (справа)
    ax_pressure = fig.add_subplot(gs[1, 1])
    ax_pressure.set_facecolor(BG_COLOR)
    ax_pressure.axis('off')
    
    # Берем цену из первого непустого snapshot
    current_price = 0.0
    for snapshot in snapshots:
        if snapshot.current_price > 0:
            current_price = snapshot.current_price
            break
    
    # Рисуем header
    _draw_header(ax_header, symbol, current_price)
    
    # Определяем режим для предупреждения
    from .regime_classifier import classify_regime
    regime = classify_regime(snapshots)
    
    # Рисуем основной график со свечами и зонами
    _draw_main_chart(ax_main, snapshots, symbol, db, ANCHOR_TF, regime)
    
    # Рисуем pressure bars справа
    _draw_pressure_panel(ax_pressure, snapshots)
    
    # Рисуем легенду внизу основного графика
    _draw_legend(ax_main, snapshots)
    
    # Сохраняем в bytes
    buf = io.BytesIO()
    fig.savefig(buf, format='png', facecolor=BG_COLOR, bbox_inches='tight', pad_inches=0)
    plt.close(fig)
    buf.seek(0)
    return buf.read()


def _draw_header(ax, symbol: str, current_price: float):
    """Нарисовать заголовок."""
    header_text = f"Liquidity Heat Intelligence - {symbol}/USDT"
    price_text = f"Price: ${current_price:,.2f}"
    time_text = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    
    # Заголовок (y ~ 0.95)
    ax.text(
        0.5, 0.95,
        header_text,
        ha='center', va='top',
        fontsize=18, fontweight='bold',
        color='white', family='monospace',
        transform=ax.transAxes
    )
    
    # Цена и время (y ~ 0.91)
    ax.text(
        0.5, 0.91,
        f"{price_text} | {time_text}",
        ha='center', va='top',
        fontsize=12,
        color='#888888', family='monospace',
        transform=ax.transAxes
    )


def _draw_main_chart(ax, snapshots: List[TimeframeSnapshot], symbol: str, db: DB, anchor_tf: str, regime=None):
    """Нарисовать основной график со свечами и зонами."""
    # Находим якорный snapshot
    anchor_snapshot = None
    for snapshot in snapshots:
        if snapshot.tf == anchor_tf:
            anchor_snapshot = snapshot
            break
    
    if not anchor_snapshot:
        # Fallback на первый доступный
        anchor_snapshot = next((s for s in snapshots if s.current_price > 0), None)
        if not anchor_snapshot:
            ax.text(0.5, 0.5, "No data", ha='center', va='center', color='white', transform=ax.transAxes)
            return
    
    # Загружаем свечи для якорного TF
    df = load_ohlcv_as_dataframe(symbol, anchor_tf, db, n_bars=100)
    if df.empty:
        ax.text(0.5, 0.5, f"No data for {symbol} {anchor_tf}", ha='center', va='center', 
                color='white', transform=ax.transAxes)
        return
    
    # Конвертируем timestamp в datetime
    df['datetime'] = pd.to_datetime(df['timestamp'], unit='ms', utc=True)
    df.set_index('datetime', inplace=True)
    
    # Определяем диапазон цен
    price_min = df['low'].min()
    price_max = df['high'].max()
    price_range = price_max - price_min
    padding = price_range * 0.05
    price_min -= padding
    price_max += padding
    
    # Вычисляем ATR для distance_factor
    atr_value = calculate_atr(df, period=14)
    current_price = float(df['close'].iloc[-1])
    
    # Рисуем зоны всех TF слоями (сначала старшие TF как фон)
    tf_order = ["1d", "4h", "1h", "15m", "5m"]  # От старших к младшим
    for tf in tf_order:
        snapshot = next((s for s in snapshots if s.tf == tf), None)
        if snapshot:
            _draw_zones_for_tf(ax, snapshot, df.index[0], df.index[-1], price_min, price_max, 
                              tf, current_price, atr_value)
    
    # Рисуем свечи
    _draw_candles(ax, df, price_min, price_max)
    
    # Рисуем яркую линию текущей цены поверх всего
    _draw_current_price_line(ax, current_price, df.index[0], df.index[-1], price_min, price_max)
    
    # Настройка осей
    ax.set_ylabel('Price (USDT)', color='white', fontsize=10)
    ax.set_xlabel('Time', color='white', fontsize=10)
    ax.set_title(f"Liquidity Heat Map — {symbol} ({anchor_tf})", color='white', fontsize=12, pad=10)
    ax.set_facecolor(BG_COLOR)
    ax.tick_params(colors='white', labelsize=8)
    ax.grid(True, alpha=0.2, color='gray', linestyle='--')
    ax.spines['bottom'].set_color('white')
    ax.spines['top'].set_color('white')
    ax.spines['right'].set_color('white')
    ax.spines['left'].set_color('white')
    
    # Форматирование дат на оси X
    import matplotlib.dates as mdates
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%m-%d %H:%M'))
    plt.setp(ax.xaxis.get_majorticklabels(), rotation=45, ha='right', color='white')
    
    # Предупреждение о контртренде
    if regime == MarketRegime.COUNTER_TREND_BOUNCE:
        ax.text(
            0.5, -0.08,
            "⚠️ Counter-trend environment",
            ha='center', va='top',
            fontsize=10, fontweight='bold',
            color='#ff6b6b',
            family='monospace',
            transform=ax.transAxes,
            bbox=dict(boxstyle='round,pad=0.5', facecolor='#2d1b1b', edgecolor='#ff6b6b', alpha=0.9)
        )


def _draw_zones_for_tf(ax, snapshot: TimeframeSnapshot, start_time: pd.Timestamp, 
                       end_time: pd.Timestamp, price_min: float, price_max: float, 
                       tf: str, current_price: float, atr_value: float):
    """Нарисовать зоны для конкретного TF с соответствующим стилем и auto-opacity."""
    active_zones = snapshot.active_zones
    if not active_zones:
        return
    
    # Стили для разных TF (RGB в диапазоне 0-1)
    # Якорный TF (1h) - максимальная яркость и четкость
    tf_styles = {
        "5m": {
            "buy": {"base_color": (0, 200/255, 100/255), "edge": None, "linewidth": 0},
            "sell": {"base_color": (255/255, 100/255, 100/255), "edge": None, "linewidth": 0},
            "label": False,
            "base_alpha": 0.15
        },
        "15m": {
            "buy": {"base_color": (0, 220/255, 120/255), "edge": None, "linewidth": 0},
            "sell": {"base_color": (255/255, 120/255, 80/255), "edge": None, "linewidth": 0},
            "label": True,
            "base_alpha": 0.25
        },
        "1h": {
            "buy": {"base_color": (0, 255/255, 150/255), "edge": (0, 255/255, 150/255), "linewidth": 2},
            "sell": {"base_color": (255/255, 140/255, 100/255), "edge": (255/255, 140/255, 100/255), "linewidth": 2},
            "label": True,
            "base_alpha": 0.5  # Якорный TF - ярче
        },
        "4h": {
            "buy": {"base_color": (0, 200/255, 255/255), "edge": (0, 200/255, 255/255), "linewidth": 1.5},
            "sell": {"base_color": (255/255, 160/255, 0), "edge": (255/255, 160/255, 0), "linewidth": 1.5},
            "label": True,
            "base_alpha": 0.3
        },
        "1d": {
            "buy": {"base_color": (0, 150/255, 255/255), "edge": (0, 150/255, 255/255), "linewidth": 2},
            "sell": {"base_color": (255/255, 100/255, 0), "edge": (255/255, 100/255, 0), "linewidth": 2},
            "label": True,
            "base_alpha": 0.2
        }
    }
    
    style = tf_styles.get(tf, tf_styles["1h"])
    tf_weight = TF_WEIGHTS.get(tf, 1.0)
    
    # Конвертируем время в числовой формат для matplotlib
    start_num = date2num(start_time.to_pydatetime())
    end_num = date2num(end_time.to_pydatetime())
    width = end_num - start_num
    
    for zone in active_zones:
        if zone.price_high < price_min or zone.price_low > price_max:
            continue
        
        # Вычисляем расстояние до зоны в ATR
        zone_mid = (zone.price_low + zone.price_high) / 2.0
        dist_atr = abs(current_price - zone_mid) / atr_value if atr_value > 0 else 10.0
        
        # Получаем distance_factor
        dist_factor = distance_factor(dist_atr)
        
        # Определяем базовый цвет в зависимости от типа зоны
        if zone.zone_type == ZoneType.BUY:
            base_color = style["buy"]["base_color"]
            edge_color_base = style["buy"].get("edge")
            linewidth = style["buy"].get("linewidth", 0)
        else:
            base_color = style["sell"]["base_color"]
            edge_color_base = style["sell"].get("edge")
            linewidth = style["sell"].get("linewidth", 0)
        
        # Вычисляем visual_strength
        visual_strength = zone.strength * dist_factor * tf_weight
        visual_strength = max(0.0, min(visual_strength, 1.0))
        
        # Определяем роль зоны
        is_execution_zone = (zone.role == ZoneRole.EXECUTION)
        is_invalidation_zone = (zone.role == ZoneRole.INVALIDATION)
        
        # Проверяем, находится ли цена внутри зоны (decision zone)
        price_in_zone = (zone.price_low <= current_price <= zone.price_high)
        if price_in_zone and is_execution_zone:
            # EXECUTION зона, где находится цена - максимально яркая
            visual_strength = min(1.0, visual_strength * 1.5)  # Усиливаем на 50%
        
        # Для CONTEXT зон снижаем видимость
        if zone.role == ZoneRole.CONTEXT:
            visual_strength *= 0.3  # Сильно приглушаем
        
        # CONTEXT зоны с очень низким visual_strength рисуем только как тонкие линии
        if zone.role == ZoneRole.CONTEXT and visual_strength < 0.15:
            # Рисуем только тонкую линию на границе
            if zone.price_low >= price_min:
                ax.plot(
                    [start_num, end_num],
                    [zone.price_low, zone.price_low],
                    color=base_color,
                    linewidth=0.5,
                    alpha=0.2
                )
            if zone.price_high <= price_max:
                ax.plot(
                    [start_num, end_num],
                    [zone.price_high, zone.price_high],
                    color=base_color,
                    linewidth=0.5,
                    alpha=0.2
                )
            continue
        
        # Вычисляем финальный alpha на основе роли зоны
        base_alpha = style.get("base_alpha", 0.3)
        alpha_min = 0.1
        
        # EXECUTION зоны - максимально яркие
        if is_execution_zone:
            if price_in_zone:
                alpha_max = 0.9  # Очень яркая для decision zone
            else:
                alpha_max = 0.7  # Яркая для execution zones
        elif is_invalidation_zone:
            alpha_max = 0.5  # Средняя яркость для invalidation
        else:  # CONTEXT
            alpha_max = 0.2  # Очень приглушенная для context zones
        
        final_alpha = alpha_min + (alpha_max - alpha_min) * visual_strength
        # Для decision zone гарантируем минимум яркости
        if price_in_zone:
            final_alpha = max(final_alpha, 0.6)  # Минимум 0.6 для зоны с ценой
        final_alpha = min(final_alpha, base_alpha * visual_strength * (1.5 if price_in_zone else 1.0))
        
        # Применяем age_factor
        age_days = (datetime.utcnow() - zone.created_at).days
        age_factor = max(0.3, 1.0 - age_days / 7.0)
        final_alpha *= age_factor
        
        color = (base_color[0], base_color[1], base_color[2], final_alpha)
        
        # Edge color (ярче для decision zone)
        if edge_color_base is not None:
            if price_in_zone:
                edge_alpha = min(1.0, final_alpha * 2.0) * age_factor  # Максимально яркая обводка
                linewidth = max(linewidth, 2.5)  # Толще обводка для decision zone
            else:
                edge_alpha = min(0.8, final_alpha * 1.5) * age_factor
            edge_color = (edge_color_base[0], edge_color_base[1], edge_color_base[2], edge_alpha)
        else:
            edge_color = None
            # Для decision zone добавляем обводку, даже если её не было
            if price_in_zone and tf == ANCHOR_TF:
                edge_color = (base_color[0], base_color[1], base_color[2], min(1.0, final_alpha * 1.8))
                linewidth = 2.5
        
        # Рисуем прямоугольник зоны
        rect = Rectangle(
            (start_num, zone.price_low),
            width,
            zone.price_high - zone.price_low,
            facecolor=color,
            edgecolor=edge_color,
            linewidth=linewidth
        )
        ax.add_patch(rect)
        
        # Подпись зоны с ценами (для EXECUTION, INVALIDATION и сильных зон близко к цене)
        should_label = (is_execution_zone or is_invalidation_zone) or \
                      (zone.strength >= 0.7 and dist_atr <= 2.0 and zone.reactions >= 3)
        if should_label and style["label"] and dist_atr <= 3.0:
            center_price = (zone.price_low + zone.price_high) / 2
            
            # Форматируем цены (исправляем баг с форматированием)
            if zone.price_low >= 1000:
                price_low_k = zone.price_low / 1000.0
                price_high_k = zone.price_high / 1000.0
                if abs(price_low_k - price_high_k) < 0.1:
                    price_label = f"{price_low_k:.1f}k"
                else:
                    price_label = f"{price_low_k:.1f}k-{price_high_k:.1f}k"
            else:
                if abs(zone.price_low - zone.price_high) < 1.0:
                    price_label = f"${zone.price_low:,.0f}"
                else:
                    price_label = f"${zone.price_low:,.0f}-${zone.price_high:,.0f}"
            
            # Подпись с TF и ценами
            label_text = f"{tf} {zone.zone_type.value}\n{price_label}"
            if is_execution_zone:
                label_text = f"🎯 {label_text}"
            
            ax.text(
                start_num + width * 0.02,
                center_price,
                label_text,
                ha='left', va='center',
                fontsize=9 if tf == ANCHOR_TF else 8,
                color='white',
                alpha=0.95 if is_execution_zone else 0.7,
                fontweight='bold' if is_execution_zone else 'normal',
                family='monospace',
                bbox=dict(boxstyle='round,pad=0.3', facecolor='black', edgecolor='white', alpha=0.7) if is_execution_zone else None
            )
            
            # Горизонтальные линии для границ зоны (только для EXECUTION) - усиленные
            if is_execution_zone:
                # Верхняя граница - особенно яркая, если цена близко к ней
                price_near_top = abs(current_price - zone.price_high) / atr_value < 0.5 if atr_value > 0 else False
                top_linewidth = 2.5 if price_near_top else 2.0
                top_alpha = 0.9 if price_near_top else 0.7
                
                # Нижняя граница
                price_near_bottom = abs(current_price - zone.price_low) / atr_value < 0.5 if atr_value > 0 else False
                bottom_linewidth = 2.5 if price_near_bottom else 2.0
                bottom_alpha = 0.9 if price_near_bottom else 0.7
                
                ax.axhline(zone.price_low, color=base_color, linewidth=bottom_linewidth, alpha=bottom_alpha, 
                          linestyle='--', zorder=50)
                ax.axhline(zone.price_high, color=base_color, linewidth=top_linewidth, alpha=top_alpha, 
                          linestyle='--', zorder=50)


def _draw_candles(ax, df: pd.DataFrame, price_min: float, price_max: float):
    """Нарисовать свечи."""
    dates = df.index
    dates_num = [date2num(d.to_pydatetime()) for d in dates]
    
    # Ширина свечи
    candle_width = (dates_num[-1] - dates_num[0]) / len(dates) * 0.6
    
    for i, (date, row) in enumerate(df.iterrows()):
        date_num = dates_num[i]
        open_price = row['open']
        high_price = row['high']
        low_price = row['low']
        close_price = row['close']
        
        # Цвет свечи (более контрастные)
        is_green = close_price >= open_price
        body_color = '#00ff88' if is_green else '#ff4444'  # Более яркие цвета
        wick_color = '#ffffff' if is_green else '#ffffff'
        
        # Тени (wick) - более заметные
        ax.plot(
            [date_num, date_num],
            [low_price, high_price],
            color=wick_color,
            linewidth=1.0,
            alpha=0.8,
            zorder=10
        )
        
        # Тело свечи - более контрастное
        body_bottom = min(open_price, close_price)
        body_top = max(open_price, close_price)
        body_height = body_top - body_bottom
        if body_height == 0:
            body_height = (price_max - price_min) * 0.001
        
        rect = Rectangle(
            (date_num - candle_width/2, body_bottom),
            candle_width,
            body_height,
            facecolor=body_color,
            edgecolor='white',
            linewidth=0.5,
            alpha=0.9,
            zorder=11
        )
        ax.add_patch(rect)
    
    # Устанавливаем пределы осей
    ax.set_xlim(dates_num[0] - candle_width, dates_num[-1] + candle_width)
    ax.set_ylim(price_min, price_max)


def _draw_current_price_line(ax, current_price: float, start_time: pd.Timestamp, 
                             end_time: pd.Timestamp, price_min: float, price_max: float):
    """Нарисовать яркую линию текущей цены поверх всех зон."""
    if current_price < price_min or current_price > price_max:
        return
    
    start_num = date2num(start_time.to_pydatetime())
    end_num = date2num(end_time.to_pydatetime())
    
    # Толстая яркая линия
    ax.plot(
        [start_num, end_num],
        [current_price, current_price],
        color='white',
        linewidth=3,
        alpha=0.9,
        zorder=100  # Поверх всего
    )
    
    # Подпись справа
    ax.text(
        end_num,
        current_price,
        f"PRICE ${current_price:,.0f}",
        ha='left',
        va='center',
        fontsize=10,
        fontweight='bold',
        color='white',
        bbox=dict(boxstyle='round,pad=0.5', facecolor='black', edgecolor='white', alpha=0.8),
        family='monospace',
        zorder=101
    )


def _draw_pressure_panel(ax, snapshots: List[TimeframeSnapshot]):
    """Нарисовать панель pressure bars справа."""
    # Порядок TF (сверху вниз)
    tf_order = ["5m", "15m", "1h", "4h", "1d"]
    
    # Высота каждого сегмента
    total_height = 1.0
    segment_height = total_height / len(tf_order)
    
    for i, tf in enumerate(tf_order):
        snapshot = next((s for s in snapshots if s.tf == tf), None)
        if not snapshot:
            continue
        
        # Позиция сегмента (сверху вниз)
        y_bottom = 1.0 - (i + 1) * segment_height
        y_top = 1.0 - i * segment_height
        y_mid = (y_bottom + y_top) / 2
        
        # Вычисляем высоты баров
        buy_height = segment_height * (snapshot.buy_pressure / 100.0)
        sell_height = segment_height * (snapshot.sell_pressure / 100.0)
        
        # Рисуем фон (верхняя половина = SELL, нижняя = BUY) - более контрастный
        sell_bg_rect = Rectangle(
            (0, y_mid),
            1,
            segment_height / 2,
            facecolor=(255/255, 80/255, 0, 0.15),
            edgecolor='#888888',
            linewidth=1,
            transform=ax.transAxes
        )
        ax.add_patch(sell_bg_rect)
        
        buy_bg_rect = Rectangle(
            (0, y_bottom),
            1,
            segment_height / 2,
            facecolor=(0, 180/255, 255/255, 0.15),
            edgecolor='#888888',
            linewidth=1,
            transform=ax.transAxes
        )
        ax.add_patch(buy_bg_rect)
        
        # Рисуем заполнение SELL (сверху вниз) - более яркое
        if sell_height > 0:
            sell_fill_rect = Rectangle(
                (0, y_top - sell_height),
                1,
                sell_height,
                facecolor=(255/255, 80/255, 0, 0.85),
                edgecolor='white',
                linewidth=1.5,
                transform=ax.transAxes
            )
            ax.add_patch(sell_fill_rect)
        
        # Рисуем заполнение BUY (снизу вверх) - более яркое
        if buy_height > 0:
            buy_fill_rect = Rectangle(
                (0, y_bottom),
                1,
                buy_height,
                facecolor=(0, 180/255, 255/255, 0.85),
                edgecolor='white',
                linewidth=1.5,
                transform=ax.transAxes
            )
            ax.add_patch(buy_fill_rect)
        
        # Подписи - всегда видимые, с лучшим контрастом
        if buy_height > segment_height * 0.1:
            ax.text(
                0.5, y_bottom + buy_height / 2,
                f"BUY {snapshot.buy_pressure:.0f}%",
                ha='center', va='center',
                fontsize=10, fontweight='bold',
                color='white',
                family='monospace',
                bbox=dict(boxstyle='round,pad=0.2', facecolor='black', edgecolor='white', alpha=0.8),
                transform=ax.transAxes
            )
        
        if sell_height > segment_height * 0.1:
            ax.text(
                0.5, y_top - sell_height / 2,
                f"SELL {snapshot.sell_pressure:.0f}%",
                ha='center', va='center',
                fontsize=10, fontweight='bold',
                color='white',
                family='monospace',
                bbox=dict(boxstyle='round,pad=0.2', facecolor='black', edgecolor='white', alpha=0.8),
                transform=ax.transAxes
            )
        
        # Метка TF - более заметная
        ax.text(
            0.5, y_mid,
            f"• {tf} •",
            ha='center', va='center',
            fontsize=11, fontweight='bold',
            color='white',
            family='monospace',
            bbox=dict(boxstyle='round,pad=0.3', facecolor='#333333', edgecolor='white', alpha=0.9),
            transform=ax.transAxes
        )


def _draw_legend(ax, snapshots: List[TimeframeSnapshot]):
    """Нарисовать легенду с информацией о зонах."""
    # Собираем все EXECUTION зоны
    execution_zones = []
    for snapshot in snapshots:
        for zone in snapshot.active_zones:
            if zone.role == ZoneRole.EXECUTION:
                execution_zones.append((snapshot.tf, zone))
    
    if not execution_zones:
        return
    
    # Ограничиваем до 3 самых важных зон
    execution_zones = sorted(execution_zones, key=lambda x: x[1].strength * x[1].reactions, reverse=True)[:3]
    
    # Формируем текст легенды
    legend_text = "🎯 Key Zones: "
    zone_texts = []
    for tf, zone in execution_zones:
        zone_type_emoji = "🟢" if zone.zone_type == ZoneType.BUY else "🔴"
        if zone.price_low >= 1000:
            price_str = f"{zone.price_low/1000:.1f}k-{zone.price_high/1000:.1f}k"
        else:
            price_str = f"${zone.price_low:,.0f}-${zone.price_high:,.0f}"
        zone_texts.append(f"{zone_type_emoji} {tf}: {price_str}")
    
    legend_text += " | ".join(zone_texts)
    
    # Рисуем легенду внизу графика
    ax.text(
        0.5, -0.12,
        legend_text,
        ha='center', va='top',
        fontsize=9,
        color='white',
        family='monospace',
        transform=ax.transAxes,
        bbox=dict(boxstyle='round,pad=0.5', facecolor='#1a1a2e', edgecolor='white', alpha=0.9)
    )
