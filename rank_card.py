"""Render a compact Discord rank card on demand."""

from io import BytesIO
from pathlib import Path
import ctypes

from PIL import Image, ImageDraw, ImageFont, ImageOps

from rank_titles import draw_portrait_panel

FONT = Path("/usr/share/fonts/truetype/nunito-sans/NunitoSans-VariableFont_YTLC,opsz,wdth,wght.ttf")


def render_and_release(renderer, *args, **kwargs):
    """Return unused native image/font buffers to Linux after rendering."""
    try:
        return renderer(*args, **kwargs)
    finally:
        try:
            trim = ctypes.CDLL(None).malloc_trim
        except AttributeError:
            pass
        else:
            trim.argtypes = [ctypes.c_size_t]
            trim.restype = ctypes.c_int
            trim(0)


def font(size, *, bold=False):
    if FONT.is_file():
        result = ImageFont.truetype(str(FONT), size)
        result.set_variation_by_name("Bold" if bold else "Regular")
        return result
    return ImageFont.truetype("DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf", size)


def listening_time(milliseconds):
    seconds = max(0, milliseconds) // 1000
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours} giờ {minutes:02d} phút"
    return f"{minutes} phút {seconds:02d} giây"


def clipped(draw, text, face, width):
    text = " ".join(str(text).split())[:100]
    if draw.textlength(text, font=face) <= width:
        return text
    while text and draw.textlength(text + "…", font=face) > width:
        text = text[:-1]
    return text + "…"


def render_rank_card(*, name, server, avatar, milliseconds, position, xp, level, base_xp,
                     next_xp, earning, orders=0, title=None):
    width, height = 860, 466
    background, ink, muted = "#16121D", "#F6F1F7", "#C6B9CC"
    green, rule = "#58FF85", "#4D3D51"
    accent = title.color if title else "#FF71AA"
    image = Image.new("RGBA", (width, height), background)
    draw = ImageDraw.Draw(image)

    portrait = None
    if avatar:
        try:
            with Image.open(BytesIO(avatar)) as original:
                portrait = ImageOps.fit(original.convert("RGB"), (130, 130),
                                        method=Image.Resampling.LANCZOS)
        except OSError:
            pass
    if portrait is None:
        portrait = Image.new("RGB", (130, 130), "#302436")
        ImageDraw.Draw(portrait).text((65, 63), str(name).strip()[:1].upper() or "?",
                                     font=font(64, bold=True), fill=ink, anchor="mm")
    draw_portrait_panel(image, portrait, title)

    name_font = font(58, bold=True)
    meta_font = font(23)
    title_font = font(34, bold=True)
    draw.text((335, 78), clipped(draw, name, name_font, 487), font=name_font, fill=ink, anchor="ls")
    if title:
        draw.text((337, 124), clipped(draw, title.name, title_font, 485), font=title_font,
                  fill=accent, anchor="ls")
    draw.text((337, 158 if title else 119), clipped(draw, server, meta_font, 485),
              font=meta_font, fill=muted, anchor="ls")
    draw.line((335, 179, 825, 179), fill=rule, width=2)

    stat_font = font(29, bold=True)
    stat_label_font = font(20)
    xp_text = f"{xp:,}".replace(",", ".") + " XP"
    order_text = f"{orders:,}".replace(",", ".")
    for left, width, value, label in (
        (335, 139, xp_text, "Tổng XP"),
        (489, 182, listening_time(milliseconds), "Thời gian nghe"),
        (690, 135, order_text, "Bài đã order"),
    ):
        value_font = stat_font
        if draw.textlength(value, font=value_font) > width:
            value_font = font(23, bold=True)
        draw.text((left, 230), clipped(draw, value, value_font, width),
                  font=value_font, fill=ink, anchor="ls")
        draw.text((left, 263), label, font=stat_label_font, fill=muted, anchor="ls")

    draw.line((335, 284, 825, 284), fill=rule, width=2)
    level_font = font(36, bold=True)
    draw.text((335, 337), clipped(draw, f"Cấp {level}", level_font, 233),
              font=level_font, fill=ink, anchor="ls")
    place = f"#{position:,}".replace(",", ".") if position is not None else "Chưa có"
    draw.text((825, 334), clipped(draw, f"Xếp hạng {place}", meta_font, 245),
              font=meta_font, fill=muted, anchor="rs")
    needed = next_xp - base_xp
    fraction = max(0, min(1, (xp - base_xp) / needed))
    draw.text((335, 374), clipped(draw, f"Tiến độ cấp {level + 1}", meta_font, 250),
              font=meta_font, fill=ink, anchor="ls")
    remaining = f"Còn {next_xp - xp:,} XP".replace(",", ".")
    draw.text((825, 374), clipped(draw, remaining, meta_font, 221),
              font=meta_font, fill=muted, anchor="rs")
    segment_count, segment_width, gap = 10, 44, 5
    # Measure progress over painted segments so gaps do not consume XP.
    filled_pixels = round(segment_count * segment_width * fraction)
    for index in range(segment_count):
        left = 335 + index * (segment_width + gap)
        right = left + segment_width - 1
        draw.rectangle((left, 391, right, 408), fill=rule)
        fill_width = min(segment_width, filled_pixels - index * segment_width)
        if fill_width > 0:
            draw.rectangle((left, 391, left + fill_width - 1, 408), fill=accent)

    status = "Đang tích XP" if earning else "Tạm ngừng tích XP"
    status_color = green if earning else muted
    draw.ellipse((336, 432, 344, 440), fill=status_color)
    draw.text((355, 443), status, font=stat_label_font, fill=status_color, anchor="ls")

    output = BytesIO()
    image.save(output, format="PNG")
    result = output.getvalue()
    output.close()
    portrait.close()
    image.close()
    return result
