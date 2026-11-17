"""Render the listening chart for Discord."""

from io import BytesIO

from PIL import Image, ImageDraw

from rank_card import clipped, font, listening_time


def render_leaderboard(server, rows):
    background, ink, muted = "#16121D", "#F6F1F7", "#C6B9CC"
    pink, green, rule = "#FF2868", "#58FF85", "#513D54"
    first_row, row_height = 158, 104
    image = Image.new("RGB", (800, first_row + row_height * len(rows) + 24), background)
    draw = ImageDraw.Draw(image)
    title_font = font(44, bold=True)
    name_font = font(31, bold=True)
    value_font = font(30, bold=True)
    detail_font = font(26)
    title_line_font = font(21, bold=True)
    draw.polygon(((598, 0), (800, 0), (800, 120), (686, 81), (754, 22), (608, 69)), fill=pink)
    draw.polygon(((718, 78), (800, 47), (800, 56), (704, 100)), fill=green)
    title = clipped(draw, "Bảng xếp hạng nghe nhạc", title_font, 555)
    draw.text((32, 22), title, font=title_font, fill=ink)
    draw.text((34, 82), clipped(draw, server, detail_font, 640), font=detail_font, fill=muted)
    for x, label in ((36, "Hạng"), (126, "Người nghe"), (543, "XP"), (764, "Thời gian nghe")):
        draw.text((x, 140), label, font=detail_font, fill=muted, anchor="rs" if x >= 543 else "ls")

    for rank, (name, milliseconds, xp, level, rank_title) in enumerate(rows, 1):
        top = first_row + (rank - 1) * row_height
        primary, secondary = ink, muted
        if rank == 1:
            draw.polygon(((16, top), (784, top), (784, top + row_height - 23),
                          (760, top + row_height - 1), (16, top + row_height - 1)), fill="#3C1832")
            draw.polygon(((16, top), (103, top), (88, top + row_height - 1),
                          (16, top + row_height - 1)), fill=green)
            secondary = "#E6BBCF"
        elif rank > 2:
            draw.line((34, top, 766, top), fill=rule)

        draw.text((37, top + 62), f"#{rank}", font=value_font,
                  fill=background if rank == 1 else primary, anchor="ls")
        draw.text((126, top + 34), clipped(draw, name, name_font, 273),
                  font=name_font, fill=primary, anchor="ls")
        if rank_title:
            draw.text((126, top + 61), clipped(draw, rank_title.name, title_line_font, 273),
                      font=title_line_font, fill=rank_title.color, anchor="ls")
        draw.text((126, top + (88 if rank_title else 67)), f"Cấp {level}", font=title_line_font,
                  fill=secondary, anchor="ls")
        xp_text = f"{xp:,}".replace(",", ".")
        draw.text((543, top + 62), clipped(draw, xp_text, value_font, 130),
                  font=value_font, fill=primary, anchor="rs")
        duration = clipped(draw, listening_time(milliseconds), detail_font, 206)
        draw.text((764, top + 62), duration, font=detail_font, fill=primary, anchor="rs")

    output = BytesIO()
    image.save(output, format="PNG")
    result = output.getvalue()
    output.close()
    image.close()
    return result
