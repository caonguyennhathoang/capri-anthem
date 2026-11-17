"""Rank milestones and avatar frames drawn for Capri Anthem."""

from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageOps


@dataclass(frozen=True)
class RankTitle:
    key: str
    level: int
    name: str
    color: str


TITLES = (
    RankTitle("signal", 1, "Bắt Sóng", "#B7D3CB"),
    RankTitle("streetkid", 10, "Streetkid", "#FF71A6"),
    RankTitle("roman", 20, "Ống Kính Roman", "#B4D9FF"),
    RankTitle("talia", 40, "Chrome của Talia", "#FF796F"),
    RankTitle("netrunner", 50, "Netrunner", "#C6A6FF"),
    RankTitle("snake-nation", 60, "D · Snake Nation", "#80F6B1"),
    RankTitle("edgerunner", 70, "Edgerunner", "#FAEA6C"),
    RankTitle("king", 80, "Vương Miện King", "#FFCF70"),
    RankTitle("capri", 90, "Capri · Chiếm Sóng", "#FF71AA"),
    RankTitle("legend", 100, "Huyền Thoại Night City", "#FFE4A0"),
)


def equipped_title(level, selection=None):
    unlocked = [title for title in TITLES if title.level <= level]
    return next((title for title in unlocked if title.key == selection),
                unlocked[-1] if unlocked else None)


ART_DIR = Path(__file__).with_name("rank_art")
PANEL_COLORS = {
    "signal": "#243A3B", "streetkid": "#532240", "roman": "#253645",
    "talia": "#482434", "netrunner": "#382858", "snake-nation": "#233955",
    "edgerunner": "#464524", "king": "#40392F", "capri": "#571B39",
    "legend": "#493927",
}


def draw_portrait_panel(image, portrait, title):
    draw = ImageDraw.Draw(image)
    key = title.key if title else ""
    accent = title.color if title else "#B4A4B8"
    backdrop = PANEL_COLORS.get(key, "#302639")
    draw.polygon(((25, 46), (51, 20), (308, 20), (308, 418),
                  (281, 445), (25, 445)), fill=backdrop)

    # Angle and weight change with the title; dots read as printed texture at Discord scale.
    draw.polygon(((25, 225), (308, 104), (308, 192), (25, 331)), fill="#181521")
    draw.polygon(((25, 405), (308, 316), (308, 418), (281, 445), (25, 445)), fill="#100E17")
    for y in range(52, 185, 8):
        for x in range(43, 131, 8):
            if (x - 43) * 2 + y < 211:
                draw.point((x, y), fill=accent)
    draw.line(((26, 89), (26, 47), (51, 22), (134, 22)), fill=accent, width=3)
    draw.line(((307, 380), (307, 417), (280, 444), (232, 444)), fill=accent, width=3)

    asset = ART_DIR / f"{key}.webp"
    if key and asset.is_file():
        art_width = 146 if key in {"talia", "snake-nation"} else 169
        with Image.open(asset) as source:
            character = ImageOps.contain(source.convert("RGBA"), (art_width, 317),
                                         Image.Resampling.LANCZOS)
        image.alpha_composite(character, (306 - character.width, 414 - character.height))
        character.close()
    else:
        draw_panel_motif(draw, key, accent)

    # A broad, dark keyline keeps a bright avatar legible over the art.
    draw.polygon(((32, 136), (45, 123), (188, 123), (188, 271),
                  (174, 285), (32, 285)), fill="#110F18")
    if key == "roman":
        mask = Image.new("L", portrait.size)
        ImageDraw.Draw(mask).ellipse((0, 0, 129, 129), fill=255)
        image.paste(portrait.convert("RGBA"), (45, 137), mask)
    else:
        image.paste(portrait.convert("RGBA"), (45, 137))
    if key in {"roman", "talia", "snake-nation", "king", "capri"}:
        draw_character_frame(draw, key)
        if key == "roman":
            image.paste(portrait.convert("RGBA"), (45, 137), mask)
            draw.ellipse((44, 136, 176, 268), outline="#142B3B", width=2)
    elif title:
        frame = Image.new("RGBA", (95, 103))
        draw_title_frame(ImageDraw.Draw(frame), (4, 11), title)
        frame = frame.resize((166, 180), Image.Resampling.LANCZOS)
        image.alpha_composite(frame, (27, 105))
        frame.close()


def draw_character_frame(draw, key):
    """Character-specific hardware surrounding the 130px avatar aperture."""
    import math

    def poly(points, color):
        draw.polygon(points, fill=color)

    def line(points, color, width=2):
        draw.line(points, fill=color, width=width, joint="curve")

    def screw(x, y, color="#AAB8C7"):
        draw.ellipse((x-3, y-3, x+3, y+3), fill=color)
        line(((x-2, y), (x+2, y)), "#26303D", 1)

    if key == "roman":
        # Camera body is built outside the lens, never over the user's face.
        poly(((29,147),(37,131),(65,131),(74,114),(133,114),(144,131),
              (183,131),(198,146),(198,257),(185,277),(36,277),(26,262)), "#111923")
        line(((29,155),(29,145),(39,134),(65,134),(75,117),(131,117),
              (143,134),(182,134),(195,147),(195,255),(183,274),(37,274)), "#8198B0", 3)
        draw.rounded_rectangle((176,151,195,248), radius=5, fill="#344457")
        for y in range(160,245,7):
            line(((180,y),(191,y)), "#172430", 2)
        draw.rectangle((81,119,126,130), fill="#526E83")
        draw.rectangle((87,121,120,127), fill="#C9E8F1")
        draw.rounded_rectangle((154,122,177,131), radius=3, fill="#B8CFDC")
        draw.ellipse((36,140,44,148), fill="#FF4A57")
        for bounds, color, width in [((37,129,183,275),"#536B85",7),
                                     ((41,133,179,271),"#C2E7F5",2),
                                     ((44,136,176,268),"#142B3B",3)]:
            draw.ellipse(bounds, outline=color, width=width)
        for degree in range(0,360,12):
            a = math.radians(degree)
            line(tuple((110+int(r*math.cos(a)),202+int(r*math.sin(a))) for r in (70,73)), "#D6E9F3", 1)
        draw.arc((40,132,180,272), 208, 258, fill="#FFFFFF", width=3)
        screw(39,263)
        screw(185,263)
    elif key == "talia":
        plates = [([(28,147),(48,122),(102,122),(91,134),(46,140),(38,182)],"#DEE9ED"),
                  ([(113,122),(173,122),(192,143),(192,183),(179,172),(176,140),(126,135)],"#9DAFBD"),
                  ([(28,221),(41,231),(45,264),(91,273),(101,287),(46,282),(28,262)],"#718394"),
                  ([(181,221),(194,209),(194,265),(173,286),(112,286),(125,272),(175,263)],"#C1D2DA")]
        for vertices,color in plates:
            poly(vertices,color)
        line(((34,153),(34,178)),"#FFFFFF",3)
        line(((184,234),(184,263),(172,275),(136,278)),"#F2FBFF",3)
        for x in (32,188):
            draw.rounded_rectangle((x-6,185,x+6,220),radius=4,fill="#384551")
            for y in (190,201,212):
                line(((x-4,y),(x+4,y)),"#FF796F",3)
        for x,y in ((48,130),(174,133),(43,272),(177,275)):
            screw(x,y)
        for x in (98,110,122):
            poly(((x,275),(x+4,281),(x,287),(x-4,281)),"#FF4C65")
    elif key == "snake-nation":
        # A die-struck viper badge on a gunmetal portrait mount.
        ink, steel, jade, glint = "#101C25", "#4A656D", "#34786F", "#A5D1BC"
        line(((78,129),(175,129),(184,138),(184,257),(165,278),(49,278)), steel, 3)
        line(((179,201),(179,255),(163,271),(117,271)), "#76969A", 2)
        # Tapered neck folds around the left edge and sweeps under the portrait.
        poly(((87,116),(67,120),(53,136),(41,165),(43,195),(49,216),
              (48,242),(40,257),(41,266),(58,275),(102,278),(138,272),
              (108,285),(55,286),(32,276),(26,259),(34,237),(36,221),
              (26,193),(24,169),(31,145),(49,122),(71,106)), ink)
        poly(((78,114),(57,128),(40,150),(34,169),(35,190),(42,213),
              (41,233),(31,258),(36,271),(57,281),(97,282),(120,277),
              (99,286),(54,285),(31,275),(26,259),(33,238),(36,221),
              (27,194),(24,170),(31,145),(49,122),(71,106)), jade)
        for x,y in ((47,130),(39,141),(32,153),(29,166),(30,180),(33,194),
                    (36,207),(36,223),(32,240),(29,254)):
            poly(((x,y),(x+8,y-3),(x+5,y+4),(x+1,y+7)),steel)
        # Low brow, angular cheek and a single fang read at Discord scale.
        poly(((49,130),(62,105),(84,88),(107,84),(124,92),(159,97),
              (154,105),(133,112),(118,113),(130,119),(147,117),
              (134,128),(111,131),(94,121),(75,122)),ink)
        poly(((52,126),(65,106),(86,90),(106,87),(122,95),(151,99),
              (134,104),(109,103),(93,112),(72,116)),jade)
        poly(((64,109),(84,91),(105,87),(115,92),(92,95)),glint)
        poly(((96,103),(117,97),(113,104),(101,107)),"#F5C36D")
        line(((109,100),(108,105)),ink,2)
        poly(((79,117),(94,110),(112,115),(126,123),(141,120),
              (133,126),(113,128),(95,118)),steel)
        poly(((132,107),(141,105),(134,117)), "#DEE5CA")
        line(((154,101),(149,102)),ink,2)
    elif key == "king":
        line(((35,154),(35,271),(51,282),(170,282),(187,265),(187,154)),"#372C24",12)
        line(((35,154),(35,271),(51,282),(170,282),(187,265),(187,154)),"#D3AA59",5)
        poly(((40,134),(31,102),(68,117),(85,91),(110,114),(140,89),(155,116),(189,101),(179,135)),"#FFD27A")
        poly(((45,130),(40,116),(69,126),(85,108),(109,126),(140,105),(153,127),(178,116),(175,130)),"#8A5A36")
        draw.rectangle((43,134,178,143),fill="#F4C568")
        for x,y in ((34,103),(85,93),(140,91),(186,103)):
            draw.ellipse((x-3,y-3,x+3,y+3),fill="#FFF1BC")
        poly(((110,132),(116,138),(110,145),(104,138)),"#EE716B")
        for x in (35,187):
            for y in (179,213,247):
                poly(((x,y-5),(x+4,y),(x,y+5),(x-4,y)),"#FFF0BF")
        poly(((96,276),(110,267),(124,276),(110,289)),"#F4C568")
    elif key == "capri":
        poly(((25,156),(30,116),(50,125),(40,88),(75,116),(91,80),(99,116),(137,100),
              (118,125),(179,113),(170,138),(181,152),(177,143),(45,143),(45,166)),"#080B13")
        poly(((32,118),(73,125),(58,143),(36,140)),"#54FF77")
        poly(((81,124),(117,115),(107,138),(76,144)),"#54FF77")
        for x,y in ((53,133),(94,130)):
            draw.ellipse((x-7,y-7,x+7,y+7),fill="#10223C",outline="#36C7FF",width=2)
            draw.ellipse((x-2,y-3,x+2,y+3),fill="#7FFFFF")
        poly(((180,143),(199,132),(188,188),(180,177),(183,218),(174,226)),"#FF2868")
        poly(((30,174),(43,184),(37,227),(44,255),(35,271),(25,226)),"#080B13")
        poly(((39,267),(69,279),(164,265),(197,237),(185,278),(139,294),(74,285)),"#FF2868")
        poly(((58,276),(159,271),(180,257),(170,275),(112,285)),"#080B13")
        line(((180,222),(193,212),(184,240)),"#58FF85",4)


def draw_panel_motif(draw, key, accent):
    if key in {"streetkid", "legend"}:
        skyline = ((124, 395), (124, 363), (143, 363), (143, 341), (165, 341), (165, 370),
                   (183, 370), (183, 315), (208, 315), (208, 335), (226, 335), (226, 285),
                   (249, 285), (249, 326), (276, 326), (276, 302), (300, 302), (300, 395))
        draw.polygon(skyline, fill="#100E17")
        draw.line(skyline, fill=accent, width=2)
        for x, y in ((150, 350), (191, 325), (201, 334), (233, 296), (243, 306), (284, 313)):
            draw.rectangle((x, y, x + 3, y + 5), fill=accent)
    elif key == "netrunner":
        for x, y in ((214, 93), (250, 166), (222, 268), (269, 300)):
            draw.line(((x - 55, y + 42), (x, y + 42), (x, y), (298, y)),
                      fill=accent, width=2)
            draw.ellipse((x - 4, y - 4, x + 4, y + 4), fill=accent)
    elif key == "edgerunner":
        draw.polygon(((284, 72), (211, 219), (257, 204), (188, 373),
                      (292, 169), (244, 181)), fill=accent)
        draw.line(((278, 107), (226, 201), (266, 189), (211, 307)), fill="#58FF85", width=2)
    else:
        heights = (12, 17, 30, 55, 39, 66, 42, 20, 33, 13)
        for index, height in enumerate(heights):
            x = 132 + index * 15
            draw.line((x, 357 - height, x, 357 + height), fill=accent, width=4)


def draw_title_frame(draw, origin, title):
    """Draw only around the portrait, leaving the center unobstructed."""
    x, y = origin
    color = title.color
    dark = "#231A2A"

    def points(vertices):
        return [(x + left, y + top) for left, top in vertices]

    def trace(vertices, fill=color, width=3):
        draw.line(points(vertices), fill=fill, width=width)

    def shape(vertices, fill=color):
        draw.polygon(points(vertices), fill=fill)

    def box(left, top, right, bottom, fill):
        draw.rectangle((x + left, y + top, x + right, y + bottom), fill=fill)

    def dot(left, top, radius, fill):
        draw.ellipse((x + left - radius, y + top - radius, x + left + radius, y + top + radius),
                     fill=fill)

    key = title.key
    if key == "signal":
        trace([(0, 86), (0, 0), (86, 0), (86, 86), (0, 86)], "#72848A", 2)
        dot(82, 3, 4, "#58FF85")
    elif key == "streetkid":
        trace([(3, 83), (3, 14), (15, 2), (84, 2), (84, 70), (71, 83), (3, 83)],
              "#96476F", 2)
        shape([(0, 2), (21, 2), (0, 20)])
        shape([(86, 65), (86, 86), (66, 86)])
    elif key == "roman":
        for left, top, dx, dy in ((2, 2, 1, 1), (84, 2, -1, 1),
                                  (2, 84, 1, -1), (84, 84, -1, -1)):
            trace([(left, top + 13 * dy), (left, top), (left + 13 * dx, top)])
        dot(74, 3, 4, "#FF554F")
        for left in range(24, 66, 8):
            box(left, 82, left + 3, 85, "#A5CAF4")
    elif key == "talia":
        shape([(0, 0), (40, 0), (35, 6), (7, 6), (7, 29), (0, 35)], "#BBC7D1")
        shape([(86, 0), (86, 40), (80, 33), (80, 7), (55, 7), (49, 0)], "#DEF0F1")
        shape([(0, 49), (7, 55), (7, 79), (33, 79), (40, 86), (0, 86)], "#637484")
        shape([(86, 51), (86, 86), (51, 86), (58, 79), (79, 79), (79, 58)], "#A5B5C0")
        for left in (34, 43, 52):
            dot(left, 84, 3, "#FF433F")
    elif key == "netrunner":
        trace([(2, 68), (2, 19), (18, 2), (65, 2)], "#8F63DF", 2)
        trace([(84, 19), (84, 68), (66, 84), (19, 84)], "#8F63DF", 2)
        trace([(0, 43), (0, 10), (10, 0), (30, 0)])
        trace([(86, 43), (86, 76), (76, 86), (56, 86)])
        dot(30, 0, 3, color)
        dot(56, 86, 3, color)
    elif key == "snake-nation":
        trace([(1, 56), (1, 1), (54, 1)], "#288465", 2)
        trace([(85, 30), (85, 85), (32, 85)], "#288465", 2)
        shape([(0, 0), (32, 0), (16, 7), (8, 26), (8, 7)])
        shape([(86, 86), (54, 86), (70, 79), (78, 60), (78, 79)])
        trace([(62, 0), (85, 0), (85, 25)], "#ED5469", 2)
        trace([(1, 61), (1, 85), (25, 85)], "#487AEC", 2)
    elif key == "edgerunner":
        trace([(0, 62), (0, 18), (17, 1), (83, 1), (83, 49)], color, 4)
        trace([(3, 70), (3, 84), (68, 84), (86, 66), (86, 53)], color, 4)
        trace([(69, 80), (85, 64)], "#69F7AE", 2)
    elif key == "king":
        trace([(2, 14), (2, 84), (84, 84), (84, 14)], "#A18E76", 3)
        shape([(23, 7), (20, -3), (34, 0), (43, -9), (52, 0), (66, -3), (63, 7)])
        trace([(6, 78), (16, 78)], "#C6C0B4", 2)
        trace([(70, 78), (80, 78)], "#C6C0B4", 2)
    elif key == "capri":
        shape([(0, 8), (10, 0), (45, 0), (34, 7), (8, 7), (8, 32), (0, 24)], dark)
        shape([(86, 52), (86, 86), (46, 86), (60, 80), (79, 80), (79, 62)], dark)
        shape([(27, 82), (84, 70), (75, 79), (47, 86)], "#FF2868")
        for left in (13, 29):
            shape([(left - 6, 5), (left + 5, 0), (left + 3, 8), (left - 4, 9)], "#58FF85")
            dot(left, 5, 2, "#45B7FA")
    elif key == "legend":
        trace([(0, 84), (0, 0), (86, 0), (86, 84), (0, 84)], "#AA8657", 2)
        shape([(0, 88), (0, 80), (9, 80), (9, 75), (17, 75), (17, 82), (27, 82),
               (27, 71), (35, 71), (35, 78), (43, 78), (43, 76), (51, 76), (51, 81),
               (61, 81), (61, 73), (69, 73), (69, 79), (79, 79), (79, 76), (86, 76), (86, 88)], dark)
        trace([(0, 87), (86, 87)], color, 2)
        trace([(1, 11), (1, 1), (14, 1)], color)
        trace([(72, 1), (85, 1), (85, 11)], color)
