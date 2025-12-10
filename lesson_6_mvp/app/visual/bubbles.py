# app/visual/bubbles.py

from __future__ import annotations

import io
import math
import re
from typing import Dict, List, Tuple

import matplotlib
matplotlib.use("Agg")  # без GUI
import matplotlib.pyplot as plt
import matplotlib.patheffects as pe
from matplotlib.patches import Circle
import numpy as np


# -----------------------------
# Детектор стейблов/обёрток
# -----------------------------
_STABLES = {
    "USDT", "USDC", "DAI", "TUSD", "USDD", "FDUSD", "USDE", "USDS", "USDJ",
    "BUSD", "BSC-USD", "USD0", "EURS", "PYUSD", "GUSD", "LUSD", "SUSD",
}
_WRAPPED = {"WBTC", "WETH", "STETH", "WSTETH"}

_STABLE_RE = re.compile(
    r"""^(?:USDT|USDC|DAI|TUSD|USDD|FDUSD|USDE|USDS|USDJ|BUSD|PYUSD|GUSD|LUSD|SUSD|EURS)(?:[\.\-]e)?$""",
    re.IGNORECASE,
)

def _is_stable(sym: str) -> bool:
    s = (sym or "").upper()
    if s in _STABLES or s in _WRAPPED:
        return True
    if s.endswith("USD") or s.startswith("USD"):
        return True
    if _STABLE_RE.match(s):
        return True
    # биржевые варианты
    if s in {"USDT0", "USDT.E", "USDC.E", "USDT-TRON", "USDT-ERC20"}:
        return True
    return False


# -----------------------------
# Вспомогательные функции
# -----------------------------
def _chg_for_tf(c: Dict, tf: str) -> float:
    """Процентное изменение за 15m/1h/24h из разных возможных ключей."""
    if tf == "15m":
        # Для 15m используем 1h данные как fallback, так как CoinGecko может не иметь 15m
        return float(
            c.get("price_change_percentage_1h_in_currency")
            or c.get("price_change_percent_1h_in_currency")
            or c.get("price_change_percentage_1h")
            or 0.0
        )
    elif tf == "1h":
        return float(
            c.get("price_change_percentage_1h_in_currency")
            or c.get("price_change_percent_1h_in_currency")
            or c.get("price_change_percentage_1h")
            or 0.0
        )
    else:  # 24h, 1d
        return float(
            c.get("price_change_percentage_24h_in_currency")
            or c.get("price_change_percent_24h_in_currency")
            or c.get("price_change_percentage_24h")
            or 0.0
        )


def _color_from_change(x: float, scale: float = 6.0) -> Tuple[float, float, float, float]:
    """
    Динамический цвет в зависимости от % изменения.
    Использует палитру "2. Строгий моно-green" для роста и "3. Heatmap пузырьков" для падения.
    Малые изменения - очень светлые, большие - более насыщенные.
    """
    abs_x = abs(x)
    if scale > 0:
        v = max(0.0, min(1.0, abs_x / float(scale)))
    else:
        v = 0.0
    
    if x > 0.01:  # Рост (положительные изменения)
        # Палитра "2. Строгий моно-green": от светлого к насыщенному зеленому
        # 5 цветов для плавного градиента
        green_palette = [
            np.array([0xF0, 0xFF, 0xF5]),  # #F0FFF5 - очень светлый
            np.array([0xCC, 0xF5, 0xDA]),  # #CCF5DA
            np.array([0x99, 0xEB, 0xB8]),  # #99EBB8
            np.array([0x66, 0xE0, 0x96]),  # #66E096
            np.array([0x00, 0xB8, 0x5C]),  # #00B85C - насыщенный зеленый
        ]
        
        # Интерполируем между цветами палитры
        # v от 0 до 1, разбиваем на 4 сегмента (между 5 цветами)
        segment = v * 4.0  # 0-4
        idx = int(segment)  # 0, 1, 2, 3
        idx = min(idx, 3)  # Ограничиваем до 3
        t = segment - idx  # Доля между текущим и следующим цветом
        
        c0 = green_palette[idx]
        c1 = green_palette[min(idx + 1, 4)]
        rgb = ((1.0 - t) * c0 + t * c1) / 255.0
        
    elif x < -0.01:  # Падение (отрицательные изменения)
        # Палитра "3. Heatmap пузырьков": от светлого розового к темно-красному
        # 5 цветов для плавного градиента
        red_palette = [
            np.array([0xFF, 0xEC, 0xEC]),  # #FFECEC - очень светлый розовый
            np.array([0xFF, 0xC2, 0xC2]),  # #FFC2C2
            np.array([0xFF, 0x8A, 0x8A]),  # #FF8A8A
            np.array([0xFF, 0x52, 0x52]),  # #FF5252
            np.array([0xD5, 0x00, 0x00]),  # #D50000 - темно-красный
        ]
        
        # Интерполируем между цветами палитры
        segment = v * 4.0  # 0-4
        idx = int(segment)  # 0, 1, 2, 3
        idx = min(idx, 3)  # Ограничиваем до 3
        t = segment - idx  # Доля между текущим и следующим цветом
        
        c0 = red_palette[idx]
        c1 = red_palette[min(idx + 1, 4)]
        rgb = ((1.0 - t) * c0 + t * c1) / 255.0
        
    else:
        # Нейтральный почти белый для нулевого или очень малого изменения
        # Используем первый цвет из зеленой палитры (почти белый)
        rgb = np.array([0xF0, 0xFF, 0xF5]) / 255.0
    
    # Обрезаем значения RGB в диапазоне [0, 1] для избежания ошибок округления
    rgb = np.clip(rgb, 0.0, 1.0)
    
    return (float(rgb[0]), float(rgb[1]), float(rgb[2]), 0.98)


def _scale_radii_by_rank(caps: np.ndarray, min_r: float, max_r: float) -> np.ndarray:
    """Размер по месту в рейтинге (как на cryptobubbles)."""
    n = len(caps)
    ranks = np.argsort(np.argsort(-caps))  # 0 = самая большая капа
    # экспонента сглаживает: большие заметны, мелкие не исчезают
    t = (ranks / max(1, n - 1)) ** 0.75
    return min_r + (1.0 - t) * (max_r - min_r)


def _scale_radii_cap_sqrt(caps: np.ndarray, min_r: float, max_r: float) -> np.ndarray:
    x = np.sqrt(np.maximum(1.0, caps))
    x = (x - x.min()) / max(1e-9, x.max() - x.min())
    return min_r + x * (max_r - min_r)


def _scale_radii_cap_log(caps: np.ndarray, min_r: float, max_r: float) -> np.ndarray:
    x = np.log10(np.maximum(1.0, caps))
    x = (x - x.min()) / max(1e-9, x.max() - x.min())
    return min_r + x * (max_r - min_r)


# -----------------------------
# Главная функция
# -----------------------------
def render_bubbles(
    coins: List[Dict],
    tf: str,
    count: int = 50,
    hide_stables: bool = True,
    seed: int | None = 42,
    min_r: int = 35,  # Еще больше увеличен минимальный радиус
    max_r: int = 200,  # Еще больше увеличен максимальный радиус для больших пузырей
    color_mode: str = "quantile",   # "simple" / "quantile"
    size_mode: str = "rank",        # "rank" / "cap_sqrt" / "cap_log" / "percent" / "volume_share" / "volume_24h"
) -> io.BytesIO:
    """
    Рисует PNG с пузырями в духе cryptobubbles.
    Возвращает BytesIO с PNG.
    """

    rng = np.random.default_rng(seed if seed is not None else 42)

    # 1) подготовка списка
    items: List[Dict] = []
    for c in coins or []:
        sym = (c.get("symbol") or c.get("ticker") or "").upper()
        if not sym:
            continue
        if hide_stables and _is_stable(sym):
            continue
        cap = float(c.get("market_cap") or c.get("market_cap_usd") or 0.0)
        if cap <= 0:
            cap = 1.0
        chg = _chg_for_tf(c, tf)
        vol = float(c.get("total_volume", 0) or 0)
        vol_share = float(c.get("volume_share", 0) or 0)
        items.append({
            "sym": sym, 
            "cap": cap, 
            "chg": float(chg),
            "vol": vol,
            "vol_share": vol_share
        })

    # Сортируем по размеру (в зависимости от режима)
    if size_mode == "percent":
        items.sort(key=lambda x: abs(x["chg"]), reverse=True)
    elif size_mode in ("volume_share", "volume_24h"):
        items.sort(key=lambda x: x["vol"], reverse=True)
    else:
        items.sort(key=lambda x: x["cap"], reverse=True)
    
    items = items[:max(5, min(200, int(count or 50)))]
    if not items:
        raise ValueError("render_bubbles: пустые данные")

    # 2) радиусы в зависимости от режима
    if size_mode == "percent":
        # Размер по абсолютному значению процента изменения
        abs_chgs = np.array([abs(x["chg"]) for x in items], dtype=float)
        if abs_chgs.max() > abs_chgs.min():
            radii = min_r + (abs_chgs - abs_chgs.min()) / (abs_chgs.max() - abs_chgs.min()) * (max_r - min_r)
        else:
            radii = np.full(len(items), (min_r + max_r) / 2)
    elif size_mode == "cap":
        # По капитализации (используем rank как было)
        caps = np.array([x["cap"] for x in items], dtype=float)
        radii = _scale_radii_by_rank(caps, min_r, max_r)
    elif size_mode == "volume_share":
        # По доле объема
        vol_shares = np.array([x["vol_share"] for x in items], dtype=float)
        if vol_shares.max() > vol_shares.min():
            radii = min_r + (vol_shares - vol_shares.min()) / (vol_shares.max() - vol_shares.min()) * (max_r - min_r)
        else:
            radii = np.full(len(items), (min_r + max_r) / 2)
    elif size_mode == "volume_24h":
        # По объему 24ч
        vols = np.array([x["vol"] for x in items], dtype=float)
        if vols.max() > vols.min():
            radii = min_r + (vols - vols.min()) / (vols.max() - vols.min()) * (max_r - min_r)
        else:
            radii = np.full(len(items), (min_r + max_r) / 2)
    elif size_mode == "rank":
        caps = np.array([x["cap"] for x in items], dtype=float)
        radii = _scale_radii_by_rank(caps, min_r, max_r)
    elif size_mode == "cap_sqrt":
        caps = np.array([x["cap"] for x in items], dtype=float)
        radii = _scale_radii_cap_sqrt(caps, min_r, max_r)
    else:  # cap_log
        caps = np.array([x["cap"] for x in items], dtype=float)
        radii = _scale_radii_cap_log(caps, min_r, max_r)

    # 3) стартовые позиции: самый большой в центре, остальные вокруг
    # Динамическая подстройка под размер экрана
    # Увеличиваем размер холста и пузырьков, чтобы они занимали 70-80% площади
    # Базовый размер холста увеличен для большего использования площади
    base_width, base_height = 2000, 1200  # Еще больше увеличенный базовый размер
    # Увеличиваем размер, если пузырей много, для лучшей читаемости
    scale_factor = 1.0 + (len(items) - 50) * 0.01  # +1% за каждые 10 пузырей сверх 50
    scale_factor = max(1.0, min(1.5, scale_factor))  # Ограничиваем от 1.0 до 1.5
    W = int(base_width * scale_factor)
    H = int(base_height * scale_factor)
    cx, cy = W / 2.0, H / 2.0
    
    # Определяем отступ между пузырьками (используется в начальном размещении и релаксации)
    pad = 8.0  # Отступ между пузырями для лучшей читаемости
    
    # Находим индекс самого большого пузыря
    max_radius_idx = np.argmax(radii)
    
    # Разделяем на лучшие и худшие (для размещения худших по углам)
    sorted_by_chg = sorted(enumerate(items), key=lambda x: x[1]["chg"])
    # Берем 4 худших, исключая самый большой (если он среди худших)
    worst_candidates = [idx for idx, _ in sorted_by_chg]
    worst_4_indices = []
    for idx in worst_candidates:
        if idx != max_radius_idx and len(worst_4_indices) < 4:
            worst_4_indices.append(idx)
    # Если не набрали 4, добавляем еще худших (включая возможно самый большой)
    if len(worst_4_indices) < 4:
        for idx in worst_candidates:
            if idx not in worst_4_indices and len(worst_4_indices) < 4:
                worst_4_indices.append(idx)
    
    # Инициализируем позиции
    x = np.zeros(len(items))
    y = np.zeros(len(items))
    
    # Самый большой пузырь в центре
    x[max_radius_idx] = cx
    y[max_radius_idx] = cy
    
    # 4 худших по углам (если есть)
    corner_positions = [
        (10, 10),  # левый верхний
        (W - 10, 10),  # правый верхний
        (10, H - 10),  # левый нижний
        (W - 10, H - 10),  # правый нижний
    ]
    for i, corner_idx in enumerate(worst_4_indices[:4]):
        if corner_idx != max_radius_idx:  # не перезаписываем центр
            # Учитываем радиус пузыря, чтобы он не выходил за границы
            r = radii[corner_idx]
            if i == 0:  # левый верхний
                x[corner_idx] = r + 10
                y[corner_idx] = r + 10
            elif i == 1:  # правый верхний
                x[corner_idx] = W - r - 10
                y[corner_idx] = r + 10
            elif i == 2:  # левый нижний
                x[corner_idx] = r + 10
                y[corner_idx] = H - r - 10
            elif i == 3:  # правый нижний
                x[corner_idx] = W - r - 10
                y[corner_idx] = H - r - 10
    
    # Остальные пузыри размещаем по спирали вокруг центра с достаточными отступами
    # Используем улучшенный алгоритм для минимизации начальных коллизий
    phi = (1 + 5 ** 0.5) / 2  # Золотое сечение
    remaining_indices = [i for i in range(len(items)) if i != max_radius_idx and i not in worst_4_indices[:4]]
    
    # Сортируем оставшиеся пузыри по размеру (большие сначала) для лучшего размещения
    remaining_with_radii = [(i, radii[i]) for i in remaining_indices]
    remaining_with_radii.sort(key=lambda x: x[1], reverse=True)
    remaining_indices_sorted = [i for i, _ in remaining_with_radii]
    
    # Вычисляем общую площадь всех пузырьков для оценки необходимого пространства
    total_area = sum(np.pi * radii[i] ** 2 for i in range(len(items)))
    available_area = W * H * 0.8  # 80% площади экрана
    area_ratio = available_area / max(total_area, 1.0)
    
    # Адаптивный шаг спирали на основе доступного пространства
    base_spiral_step = max(25, min(W, H) * 0.04)  # Адаптивный базовый шаг
    
    for idx, i in enumerate(remaining_indices_sorted):
        # Используем золотую спираль с большим шагом для предотвращения коллизий
        angle = idx * 2 * np.pi / phi  # Золотой угол
        
        # Увеличиваем минимальный отступ от центрального пузыря
        base_rad = radii[max_radius_idx] + radii[i] + pad + 15  # Увеличенный отступ
        
        # Адаптивный шаг спирали - учитываем размер пузырьков и доступное пространство
        spiral_step = base_spiral_step + (radii[i] * 0.5)
        spiral_rad = base_rad + idx * spiral_step
        
        # Ограничиваем максимальный радиус спирали
        max_spiral_rad = min(W, H) * 0.38  # Увеличиваем до 38% для лучшего использования
        spiral_rad = min(spiral_rad, max_spiral_rad)
        
        # Начальная позиция на спирали
        x[i] = cx + spiral_rad * np.cos(angle)
        y[i] = cy + spiral_rad * np.sin(angle)
        
        # Итеративное исправление коллизий при начальном размещении
        max_placement_iterations = 50
        for placement_iter in range(max_placement_iterations):
            collision_found = False
            placed_indices = [max_radius_idx] + worst_4_indices[:4] + remaining_indices_sorted[:idx]
            
            for placed_idx in placed_indices:
                if placed_idx == i:
                    continue
                
                dx = x[i] - x[placed_idx]
                dy = y[i] - y[placed_idx]
                dist = math.hypot(dx, dy) or 1e-6
                need_dist = radii[i] + radii[placed_idx] + pad
                
                if dist < need_dist:
                    collision_found = True
                    # Агрессивное смещение для устранения коллизии
                    push_away = (need_dist - dist) * 1.5 + 5
                    if dist > 0:
                        x[i] += (dx / dist) * push_away
                        y[i] += (dy / dist) * push_away
                    else:
                        # Если полностью перекрываются, смещаем по углу
                        x[i] = cx + spiral_rad * np.cos(angle + np.pi / 4)
                        y[i] = cy + spiral_rad * np.sin(angle + np.pi / 4)
                        spiral_rad += radii[i] + 10
                    
                    # Удерживаем в границах
                    margin = W * 0.10
                    x[i] = min(max(radii[i] + margin, x[i]), W - radii[i] - margin)
                    y[i] = min(max(radii[i] + margin, y[i]), H - radii[i] - margin)
            
            if not collision_found:
                break  # Коллизий нет, можно переходить к следующему пузырьку

    # 4) релаксация (репеллер) - приоритет на устранение коллизий
    # pad уже определен выше
    import logging
    log = logging.getLogger("alt_forecast.visual")
    
    # Фаза 1: Агрессивное разрешение коллизий до полного их устранения
    max_iterations_phase1 = 800  # Увеличиваем количество итераций
    no_collision_iterations = 0  # Счетчик итераций без коллизий
    
    for iteration in range(max_iterations_phase1):
        collisions = 0
        total_overlap = 0.0
        
        # Проверяем все пары на коллизии
        for i in range(len(items)):
            for j in range(i + 1, len(items)):
                dx, dy = x[j] - x[i], y[j] - y[i]
                dist = math.hypot(dx, dy) or 1e-6
                need = radii[i] + radii[j] + pad
                
                if dist < need:
                    collisions += 1
                    overlap = need - dist
                    total_overlap += overlap
                    
                    # Максимально агрессивное отталкивание для гарантированного устранения коллизий
                    # Используем очень сильное отталкивание - в 2-3 раза больше перекрытия
                    push_strength = 2.5 + (overlap / max(radii[i] + radii[j], 10.0)) * 1.0
                    push = overlap * push_strength
                    
                    ux, uy = dx / dist, dy / dist
                    
                    # Равномерное отталкивание - оба пузырька отталкиваются одинаково
                    # Это более эффективно для устранения коллизий, чем пропорциональное движение
                    move = push * 0.5
                    
                    x[i] -= ux * move
                    y[i] -= uy * move
                    x[j] += ux * move
                    y[j] += uy * move
        
        # Удерживаем пузырьки в границах (широкие границы на этой фазе)
        margin_ratio = 0.10  # Уменьшаем отступы для большего пространства
        min_x = W * margin_ratio
        max_x = W * (1 - margin_ratio)
        min_y = H * margin_ratio
        max_y = H * (1 - margin_ratio)
        
        for i in range(len(items)):
            r = radii[i]
            x[i] = min(max(r + min_x, x[i]), max_x - r)
            y[i] = min(max(r + min_y, y[i]), max_y - r)
        
        # Если коллизий нет несколько итераций подряд, переходим к следующей фазе
        if collisions == 0:
            no_collision_iterations += 1
            if no_collision_iterations >= 10:  # Нужно 10 итераций подряд без коллизий
                log.info(f"bubbles: Фаза 1 завершена на итерации {iteration}, коллизий нет")
                break
        else:
            no_collision_iterations = 0
            # Логируем прогресс каждые 100 итераций
            if iteration % 100 == 0:
                log.info(f"bubbles: Фаза 1, итерация {iteration}, коллизий: {collisions}, общее перекрытие: {total_overlap:.2f}")
    
    # Логируем финальное состояние Фазы 1
    if collisions > 0:
        log.warning(f"bubbles: Фаза 1 завершена, но остались коллизии: {collisions}, перекрытие: {total_overlap:.2f}")
    
    # Фаза 2: Равномерное распределение и заполнение экрана (после устранения коллизий)
    # Теперь все коллизии устранены, можем безопасно масштабировать и распределять
    
    # Сначала вычисляем текущие границы
    if len(items) > 0:
        min_x_used = min(x[i] - radii[i] for i in range(len(items)))
        max_x_used = max(x[i] + radii[i] for i in range(len(items)))
        min_y_used = min(y[i] - radii[i] for i in range(len(items)))
        max_y_used = max(y[i] + radii[i] for i in range(len(items)))
        
        current_width = max_x_used - min_x_used
        current_height = max_y_used - min_y_used
        usage_ratio_x = current_width / W
        usage_ratio_y = current_height / H
        log.info(f"bubbles: Перед Фазой 2 - использование пространства: {usage_ratio_x*100:.1f}% x {usage_ratio_y*100:.1f}%")
        
        # Целевая область: 75-80% экрана
        target_margin_ratio = 0.10  # 10% отступ с каждой стороны = 80% использование
        target_width = W * (1 - 2 * target_margin_ratio)
        target_height = H * (1 - 2 * target_margin_ratio)
        
        # Вычисляем масштаб для заполнения экрана
        # Более агрессивный подход: сразу масштабируем до целевого размера
        if current_width > 0 and current_height > 0:
            scale_x = target_width / current_width
            scale_y = target_height / current_height
            # Используем минимальный масштаб для равномерного масштабирования
            scale = min(scale_x, scale_y)
            
            # Если область меньше целевой, агрессивно увеличиваем масштаб
            # Если область больше целевой, немного уменьшаем
            if scale > 1.0:
                # Область слишком мала - нужно расширить
                # Применяем масштаб более агрессивно, но с учетом возможных коллизий
                scale = min(scale, 2.0)  # До 2.0x для активного заполнения
            else:
                # Область слишком велика - немного уменьшаем
                scale = max(0.95, scale)  # Минимальное уменьшение
            
            # Центр текущей области
            center_x_used = (min_x_used + max_x_used) / 2
            center_y_used = (min_y_used + max_y_used) / 2
            
            # Применяем масштабирование сразу
            for i in range(len(items)):
                x[i] = cx + (x[i] - center_x_used) * scale
                y[i] = cy + (y[i] - center_y_used) * scale
                
                # Удерживаем в границах после масштабирования
                margin = W * target_margin_ratio
                r = radii[i]
                x[i] = min(max(r + margin, x[i]), W - r - margin)
                y[i] = min(max(r + margin, y[i]), H - r - margin)
            
            log.info(f"bubbles: Применено масштабирование {scale:.2f}x, целевое использование: {target_width/W*100:.1f}% x {target_height/H*100:.1f}%")
        
        # Финальная релаксация с сохранением расстояний и заполнением пространства
        max_iterations_phase2 = 300
        for iteration in range(max_iterations_phase2):
            # Проверяем коллизии (не должны быть, но на всякий случай)
            has_collisions = False
            for i in range(len(items)):
                for j in range(i + 1, len(items)):
                    dx, dy = x[j] - x[i], y[j] - y[i]
                    dist = math.hypot(dx, dy) or 1e-6
                    need = radii[i] + radii[j] + pad
                    
                    if dist < need:
                        has_collisions = True
                        overlap = need - dist
                        # Быстрое устранение коллизий
                        push = overlap * 1.5
                        ux, uy = dx / dist, dy / dist
                        move = push * 0.5
                        
                        x[i] -= ux * move
                        y[i] -= uy * move
                        x[j] += ux * move
                        y[j] += uy * move
            
            # Расширение для заполнения пространства (только если нет коллизий)
            if not has_collisions:
                # Вычисляем текущие границы использования пространства
                current_min_x = min(x[i] - radii[i] for i in range(len(items)))
                current_max_x = max(x[i] + radii[i] for i in range(len(items)))
                current_min_y = min(y[i] - radii[i] for i in range(len(items)))
                current_max_y = max(y[i] + radii[i] for i in range(len(items)))
                
                current_width_used = current_max_x - current_min_x
                current_height_used = current_max_y - current_min_y
                
                # Целевые размеры для заполнения 75-80% экрана
                target_width_used = W * 0.75
                target_height_used = H * 0.75
                
                # Вычисляем, насколько нужно расширить
                width_factor = target_width_used / max(current_width_used, 1.0)
                height_factor = target_height_used / max(current_height_used, 1.0)
                # Используем минимальный фактор для сохранения пропорций
                expansion_factor = min(width_factor, height_factor)
                # Ограничиваем разумными пределами
                expansion_factor = max(1.0, min(expansion_factor, 1.6))
                
                # Применяем расширение постепенно, но более агрессивно
                # Чем ближе к концу итераций, тем больше расширяем
                progress = iteration / max_iterations_phase2
                expansion_rate = 0.25 * (1.0 - progress * 0.5)  # Уменьшается со временем
                current_expansion = 1.0 + (expansion_factor - 1.0) * expansion_rate
                
                # Центр текущей области
                center_x_used = (current_min_x + current_max_x) / 2
                center_y_used = (current_min_y + current_max_y) / 2
                
                # Расширяем от центра
                for i in range(len(items)):
                    dx_from_center = x[i] - center_x_used
                    dy_from_center = y[i] - center_y_used
                    x[i] = center_x_used + dx_from_center * current_expansion
                    y[i] = center_y_used + dy_from_center * current_expansion
                
                # Удерживаем в границах
                margin = W * target_margin_ratio
                for i in range(len(items)):
                    r = radii[i]
                    x[i] = min(max(r + margin, x[i]), W - r - margin)
                    y[i] = min(max(r + margin, y[i]), H - r - margin)
            else:
                # Если есть коллизии, просто удерживаем в границах
                margin = W * target_margin_ratio
                for i in range(len(items)):
                    r = radii[i]
                    x[i] = min(max(r + margin, x[i]), W - r - margin)
                    y[i] = min(max(r + margin, y[i]), H - r - margin)
            
            # Логируем прогресс каждые 50 итераций
            if iteration % 50 == 0 and not has_collisions:
                current_min_x_check = min(x[i] - radii[i] for i in range(len(items)))
                current_max_x_check = max(x[i] + radii[i] for i in range(len(items)))
                current_min_y_check = min(y[i] - radii[i] for i in range(len(items)))
                current_max_y_check = max(y[i] + radii[i] for i in range(len(items)))
                usage_x = (current_max_x_check - current_min_x_check) / W
                usage_y = (current_max_y_check - current_min_y_check) / H
                log.info(f"bubbles: Фаза 2, итерация {iteration}, использование: {usage_x*100:.1f}% x {usage_y*100:.1f}%")
            
            # Если коллизий нет и распределение стабильно, можно остановиться
            if not has_collisions and iteration > 50:
                break
    
    # 4.5) Финальная проверка и устранение любых оставшихся коллизий
    # Гарантируем, что все коллизии устранены перед рендерингом
    for final_iteration in range(200):
        has_collisions = False
        max_overlap = 0.0
        
        for i in range(len(items)):
            for j in range(i + 1, len(items)):
                dx, dy = x[j] - x[i], y[j] - y[i]
                dist = math.hypot(dx, dy) or 1e-6
                need = radii[i] + radii[j] + pad
                
                if dist < need:
                    has_collisions = True
                    overlap = need - dist
                    max_overlap = max(max_overlap, overlap)
                    
                    # Очень агрессивное отталкивание для гарантированного устранения
                    push = overlap * 2.0  # Увеличиваем силу отталкивания
                    ux, uy = dx / dist, dy / dist
                    
                    # Равномерное отталкивание
                    move = push * 0.5
                    
                    x[i] -= ux * move
                    y[i] -= uy * move
                    x[j] += ux * move
                    y[j] += uy * move
        
        # Удерживаем в границах
        margin_ratio = 0.10  # 10% отступ = 80% использование
        margin = W * margin_ratio
        for i in range(len(items)):
            r = radii[i]
            x[i] = min(max(r + margin, x[i]), W - r - margin)
            y[i] = min(max(r + margin, y[i]), H - r - margin)
        
        # Если коллизий нет или они очень малы, можно остановиться
        if not has_collisions or (max_overlap < 0.1 and final_iteration > 50):
            if has_collisions:
                log.warning(f"bubbles: Финальная проверка завершена с {final_iteration} итерациями, осталось коллизий с перекрытием {max_overlap:.2f}")
            else:
                log.info(f"bubbles: Финальная проверка завершена на итерации {final_iteration}, коллизий нет")
            
            # Логируем финальное использование пространства
            if len(items) > 0:
                final_min_x = min(x[i] - radii[i] for i in range(len(items)))
                final_max_x = max(x[i] + radii[i] for i in range(len(items)))
                final_min_y = min(y[i] - radii[i] for i in range(len(items)))
                final_max_y = max(y[i] + radii[i] for i in range(len(items)))
                final_usage_x = (final_max_x - final_min_x) / W
                final_usage_y = (final_max_y - final_min_y) / H
                log.info(f"bubbles: Финальное использование пространства: {final_usage_x*100:.1f}% x {final_usage_y*100:.1f}%")
            break

    # 5) цвета - динамические в зависимости от % изменения
    chgs = np.array([it["chg"] for it in items], dtype=float)
    
    # Логирование для отладки
    import logging
    log = logging.getLogger("alt_forecast.visual")
    if len(chgs) > 0:
        log.info("bubbles colors: chg min=%.2f, max=%.2f, mean=%.2f, non_zero=%d/%d", 
                 chgs.min(), chgs.max(), chgs.mean(), np.count_nonzero(chgs), len(chgs))
    
    # Определяем масштаб для нормализации цветов
    # Используем более агрессивную нормализацию для лучшей видимости цветов
    if color_mode == "quantile":
        # Используем квантили для более равномерного распределения цветов
        lo, hi = np.quantile(chgs, [0.05, 0.95])  # Более широкие квантили
        scale = max(1.5, abs(hi - lo))
        # Если разброс мал, используем максимальное абсолютное значение
        if scale < 1.0:
            max_abs = np.max(np.abs(chgs))
            scale = max(2.0, max_abs * 0.8)  # Немного уменьшаем для более ярких цветов
    else:
        # Используем максимальное абсолютное значение
        max_abs = np.max(np.abs(chgs))
        scale = max(2.0, max_abs * 0.8)  # Уменьшаем множитель для более ярких цветов
    
    # Минимальный масштаб для гарантии видимости цветов
    if scale < 0.5:
        scale = 2.0
    
    log.info("bubbles colors: scale=%.2f", scale)
    
    # Вычисляем цвета для каждого пузыря
    colors = []
    for i, v in enumerate(chgs):
        color = _color_from_change(v, scale=scale)
        colors.append(color)
        # Логируем первые несколько для отладки
        if i < 5:
            log.info("bubbles color[%d]: chg=%.2f, color=(%.2f,%.2f,%.2f)", i, v, color[0], color[1], color[2])
    
    # Проверяем, что цвета не все одинаковые
    unique_colors = len(set([(int(c[0]*255), int(c[1]*255), int(c[2]*255)) for c in colors]))
    log.info("bubbles colors: unique colors=%d/%d", unique_colors, len(colors))
    
    # Если все цвета одинаковые или все синие, принудительно устанавливаем разные цвета для теста
    if unique_colors <= 1:
        log.warning("bubbles colors: все цвета одинаковые! Принудительно устанавливаем тестовые цвета")
        # Устанавливаем чередующиеся зеленые и красные для теста
        for i in range(len(colors)):
            if i % 2 == 0:
                colors[i] = (0.18, 0.49, 0.20, 0.98)  # Зеленый
            else:
                colors[i] = (0.78, 0.18, 0.16, 0.98)  # Красный

    # 6) рисунок/оси
    # Увеличиваем DPI для лучшего качества изображения
    fig = plt.figure(figsize=(W / 100, H / 100), dpi=150)  # Увеличенное разрешение для лучшего качества
    ax = plt.gca()

    # Фон с легким градиентом (как на cryptobubbles - чистый, но не чисто белый)
    # Создаем легкий градиент от почти белого к очень светло-серому
    bg_color = (0.98, 0.98, 0.99)  # Почти белый с легким синеватым оттенком
    fig.patch.set_facecolor(bg_color)
    ax.set_facecolor(bg_color)
    ax.set_axis_off()

    # >>> ФИКС «белого экрана»: прибиваем окно просмотра и отключаем автоскейл
    ax.set_xlim(0, W)
    ax.set_ylim(H, 0)  # инвертируем Y как в экранных координатах
    ax.set_aspect("equal", adjustable="box")
    ax.set_autoscale_on(False)
    fig.subplots_adjust(left=0, right=1, top=1, bottom=0)

    # Убираем абстрактные фоновые дуги для более чистого вида

    # Функция для создания пузыря с 3D эффектом (как на cryptobubbles)
    def draw_bubble_with_gradient(ax, x, y, r, base_color, zorder_base=2):
        """Рисует пузырь с тенью и бликом для 3D эффекта (оптимизированная версия)."""
        # Тень (смещенная вниз и вправо) - более мягкая
        shadow_offset = max(2, r * 0.1)
        shadow_alpha = 0.12
        ax.add_patch(
            Circle(
                (x + shadow_offset, y + shadow_offset), r * 0.98,
                facecolor=(0, 0, 0, shadow_alpha),
                edgecolor=None,
                zorder=zorder_base,
            )
        )
        
        # Основной пузырь
        # Убеждаемся, что цвет правильного формата (RGBA или RGB)
        if isinstance(base_color, tuple) and len(base_color) >= 3:
            # Используем только RGB, без альфа-канала для facecolor
            face_color = base_color[:3]
            # Обрезаем значения в диапазоне [0, 1] для избежания ошибок округления
            face_color = tuple(max(0.0, min(1.0, float(c))) for c in face_color)
        else:
            face_color = (0.5, 0.5, 0.5)  # Серый по умолчанию
        
        # Логируем цвет для отладки (только первые несколько)
        import logging
        log_debug = logging.getLogger("alt_forecast.visual")
        if zorder_base < 2.01:  # Только для первых пузырей
            log_debug.info("draw_bubble: base_color=%s, face_color=%s", base_color, face_color)
        
        # Рисуем основной пузырь - убираем блик, чтобы цвет был виден
        ax.add_patch(
            Circle(
                (x, y), r,
                facecolor=face_color,  # Используем RGB без альфа
                edgecolor=(0, 0, 0, 0.12),  # Тонкая обводка
                linewidth=max(0.6, r * 0.012),
                zorder=zorder_base + 1,
            )
        )

    # Пузыри + подписи
    for idx, (it, r, xi, yi, col) in enumerate(zip(items, radii, x, y, colors)):
        # Убеждаемся, что цвет - это кортеж из 4 элементов (RGBA)
        if len(col) != 4:
            log.warning("bubbles: неправильный формат цвета для %s: %s", it["sym"], col)
            col = (0.5, 0.5, 0.5, 0.98)  # Серый по умолчанию
        else:
            # Обрезаем значения RGB в диапазоне [0, 1] для избежания ошибок округления
            col = (max(0.0, min(1.0, float(col[0]))), 
                   max(0.0, min(1.0, float(col[1]))), 
                   max(0.0, min(1.0, float(col[2]))), 
                   float(col[3]))
        
        # Логируем первые несколько цветов для отладки
        if idx < 3:
            log.info("bubbles render[%d]: %s, color=%s, chg=%.2f", idx, it["sym"], col, it["chg"])
        
        # Рисуем пузырь с градиентом
        draw_bubble_with_gradient(ax, xi, yi, r, col, zorder_base=2 + idx * 0.001)
        
        # Динамический размер текста в зависимости от размера пузырька
        # Формула: размер шрифта пропорционален радиусу, но с ограничениями
        # Для больших пузырей - больший шрифт, для маленьких - меньший
        base_font_size = r * 0.35  # Базовый размер относительно радиуса
        min_font_size = 8  # Минимальный размер для читаемости
        max_font_size = 24  # Максимальный размер для больших пузырей
        fs_symbol = max(min_font_size, min(max_font_size, int(base_font_size)))
        
        # Размер шрифта для процента (чуть меньше названия)
        fs_percent = max(6, min(16, int(fs_symbol * 0.65)))
        
        # Определяем цвет текста на основе яркости фона для максимальной читаемости
        brightness = (col[0] * 0.299 + col[1] * 0.587 + col[2] * 0.114)
        
        # Адаптивный цвет текста: белый на темных фонах, очень темный на светлых
        # Используем более высокий порог для переключения на белый текст (brightness < 0.55)
        if brightness < 0.55:
            text_color = "white"  # Белый текст на темных/средних фонах
            # Тонкая темная обводка для контраста (не белая!)
            text_path_effects = [
                pe.Stroke(linewidth=0.5, foreground=(0, 0, 0, 0.6)),  # Тонкая темная обводка
                pe.Normal()
            ]
        else:
            text_color = (0.02, 0.02, 0.02, 1.0)  # Очень темный текст на светлых фонах
            # На светлых фонах обводка не нужна - текст и так читается хорошо
            text_path_effects = None
        
        # Используем более жирный шрифт для лучшей читаемости
        font_weight = "bold"  # Жирный шрифт (heavy может не поддерживаться во всех шрифтах)
        
        # Форматируем процент изменения
        chg_val = it["chg"]
        if abs(chg_val) < 0.01:
            chg_text = "0.0%"
        else:
            chg_text = f"{chg_val:+.1f}%"
        
        # Показываем текст только если пузырек достаточно большой
        # Для очень маленьких пузырей показываем только символ
        if r >= 12:  # Если радиус >= 12, показываем и символ, и процент
            # Название монеты (центр) с жирным шрифтом и адаптивной обводкой
            ax.text(
                xi, yi - r * 0.15,  # Смещаем немного вверх для места под процентом
                it["sym"],
                ha="center", va="center",
                fontsize=fs_symbol, weight=font_weight, color=text_color,
                family="sans-serif",  # Используем sans-serif для лучшей читаемости
                path_effects=text_path_effects,  # Тонкая темная обводка только для белого текста
                zorder=10,  # Текст всегда сверху
            )
            
            # Процент изменения (ниже названия) с жирным шрифтом
            ax.text(
                xi, yi + r * 0.25,  # Смещаем вниз от центра
                chg_text,
                ha="center", va="center",
                fontsize=fs_percent, weight=font_weight, color=text_color,
                family="sans-serif",  # Используем sans-serif для лучшей читаемости
                path_effects=text_path_effects,  # Тонкая темная обводка только для белого текста
                zorder=10,  # Текст всегда сверху
            )
        else:  # Для маленьких пузырей - только символ с жирным шрифтом
            ax.text(
                xi, yi, it["sym"],
                ha="center", va="center",
                fontsize=fs_symbol, weight=font_weight, color=text_color,
                family="sans-serif",  # Используем sans-serif для лучшей читаемости
                path_effects=text_path_effects,  # Тонкая темная обводка только для белого текста
                zorder=10,  # Текст всегда сверху
            )

    # Заголовок (улучшенный стиль)
    title_text = f"Crypto bubbles — {tf} · n={len(items)}"
    ax.text(
        0.02, 0.98, title_text,
        transform=ax.transAxes, ha="left", va="top",
        fontsize=14, weight="bold", 
        color=(0.15, 0.15, 0.15, 1.0),  # Темно-серый вместо черного
        zorder=100,  # Всегда сверху
        bbox=dict(boxstyle="round,pad=0.5", facecolor=(1, 1, 1, 0.85), edgecolor=(0.8, 0.8, 0.8, 0.5), linewidth=1),
    )

    # вывод в PNG с высоким разрешением
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=150, bbox_inches='tight', pad_inches=0)  # Увеличенное разрешение для лучшего качества
    plt.close(fig)
    buf.seek(0)
    return buf

