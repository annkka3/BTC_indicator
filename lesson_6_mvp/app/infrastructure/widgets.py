# -*- coding: utf-8 -*-
from io import BytesIO
from typing import Optional, Tuple
from PIL import Image, ImageDraw, ImageFont

def _text_size(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont) -> tuple[int, int]:
    """
    Pillow 10+: textsize удалён. Используем textbbox, а при сбое — getsize.
    """
    try:
        left, top, right, bottom = draw.textbbox((0, 0), text, font=font)
        return right - left, bottom - top
    except Exception:
        # Pillow <10 — у шрифта часто есть getsize
        try:
            return font.getsize(text)  # type: ignore[attr-defined]
        except Exception:
            return (len(text) * 10, 16)



def _load_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    # Пытаемся взять системный DejaVu, иначе дефолтный PIL
    for path in (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSansCondensed.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
    ):
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            continue
    return ImageFont.load_default()

def _blend(c1: Tuple[int,int,int], c2: Tuple[int,int,int], t: float) -> Tuple[int,int,int]:
    t = max(0.0, min(float(t), 1.0))
    return (int(c1[0]+(c2[0]-c1[0])*t),
            int(c1[1]+(c2[1]-c1[1])*t),
            int(c1[2]+(c2[2]-c1[2])*t))

def gen_altseason_png(value: int | None, label: str) -> bytes:
    """
    Рисуем компактный PNG-виджет Altseason.
    """
    W, H = 800, 360
    bg = (29, 31, 36)
    fg = (240, 240, 240)
    green = (86, 201, 122)
    gray = (170, 170, 170)

    img = Image.new("RGB", (W, H), bg)
    draw = ImageDraw.Draw(img)

    # Шрифты с фоллбэком
    try:
        f_title = ImageFont.truetype("DejaVuSans-Bold.ttf", 38)
    except Exception:
        f_title = ImageFont.load_default()
    try:
        f_big = ImageFont.truetype("DejaVuSans-Bold.ttf", 120)
    except Exception:
        f_big = ImageFont.load_default()
    try:
        f_label = ImageFont.truetype("DejaVuSans.ttf", 32)
    except Exception:
        f_label = ImageFont.load_default()

    # Заголовок
    title = "Altcoin Season Index"
    tw, th = _text_size(draw, title, f_title)
    draw.text(((W - tw) // 2, 24), title, fill=fg, font=f_title)

    # Значение
    vtxt = "—" if value is None else str(value)
    vw, vh = _text_size(draw, vtxt, f_big)
    draw.text(((W - vw) // 2, 100), vtxt, fill=green if value is not None else gray, font=f_big)

    # Подпись ("Altcoin Season" / "Bitcoin Season")
    label = label or ""
    lw, lh = _text_size(draw, label, f_label)
    draw.text(((W - lw) // 2, 100 + vh + 20), label, fill=fg, font=f_label)

    # Экспорт в bytes
    import io
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()
