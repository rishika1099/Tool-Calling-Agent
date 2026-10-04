"""Generates the sample garment + care-label photos in this folder, so graders can exercise
scan_garment (tools/wardrobe.py) without taking their own photos. Run: python3 data/demo_photos/make_demo_photos.py

These are synthetic (drawn with Pillow), not real photos of clothes: a flat silhouette on a
plain background, same as the "lay it on a bed or floor" framing the onboarding flow asks for,
plus a printed care label Gemini vision can read for the fiber mix. Good enough to prove the
pipeline (is_clothing, garment_type, fit, formality, materials_source="label", main_color);
not meant to replace scanning real clothes.
"""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

OUT = Path(__file__).parent
FABRIC_BG = (238, 234, 225)  # a plain sheet/floor, roughly
LABEL_BG = (250, 249, 246)

FONT_CANDIDATES = [
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
]


def font(size: int, bold: bool = False):
    names = [f for f in FONT_CANDIDATES if ("Bold" in f) == bold]
    for path in names:
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def garment_canvas(size=(900, 1100)):
    img = Image.new("RGB", size, FABRIC_BG)
    draw = ImageDraw.Draw(img)
    # A faint vignette so the garment reads as "on a surface", not a flat color swatch.
    for i in range(0, 40):
        shade = tuple(max(0, c - i // 3) for c in FABRIC_BG)
        draw.rectangle((i, i, size[0] - i, size[1] - i), outline=shade, width=1)
    return img, draw


def save(img: Image.Image, name: str):
    path = OUT / name
    img.convert("RGB").save(path, format="JPEG", quality=90)
    print(f"wrote {path}")


def draw_tshirt(draw: ImageDraw.ImageDraw, color, cx=450, top=260, w=440, h=560):
    body_l, body_r = cx - w / 2, cx + w / 2
    collar = w * 0.18
    sleeve = w * 0.28
    points = [
        (cx - collar, top), (cx + collar, top),  # collar
        (body_r - sleeve * 0.3, top + sleeve * 0.15), (body_r + sleeve, top + sleeve * 1.1),  # right shoulder/sleeve
        (body_r - sleeve * 0.2, top + sleeve * 2.0),  # right armpit
        (body_r, top + h), (body_l, top + h),  # hem
        (body_l + sleeve * 0.2, top + sleeve * 2.0),  # left armpit
        (body_l - sleeve, top + sleeve * 1.1), (body_l + sleeve * 0.3, top + sleeve * 0.15),  # left sleeve/shoulder
    ]
    draw.polygon(points, fill=color, outline=tuple(max(0, c - 40) for c in color))
    draw.ellipse((cx - collar * 0.8, top - 6, cx + collar * 0.8, top + 28), outline=tuple(max(0, c - 60) for c in color), width=4)


def draw_sweater(draw: ImageDraw.ImageDraw, color, cx=450, top=270, w=400, h=540):
    """A long-sleeved roll-neck knit: long sleeves, ribbed neck, cuffs and hem, cable lines."""
    shade = tuple(max(0, c - 35) for c in color)
    dark = tuple(max(0, c - 60) for c in color)
    body_l, body_r = cx - w / 2, cx + w / 2
    hem = top + h
    # Long sleeves angled down and out, ending level with the hem.
    for side in (-1, 1):
        edge = body_r if side == 1 else body_l
        sleeve = [(edge - side * 40, top + 10), (edge + side * 185, hem - 90),
                  (edge + side * 110, hem - 40), (edge - side * 5, top + 200)]
        draw.polygon(sleeve, fill=color, outline=dark)
        # Ribbed cuff across the end of the sleeve.
        for k in range(4):
            t = 0.90 + k * 0.03
            x1 = sleeve[0][0] + (sleeve[1][0] - sleeve[0][0]) * t
            y1 = sleeve[0][1] + (sleeve[1][1] - sleeve[0][1]) * t
            x2 = sleeve[3][0] + (sleeve[2][0] - sleeve[3][0]) * t
            y2 = sleeve[3][1] + (sleeve[2][1] - sleeve[3][1]) * t
            draw.line((x1, y1, x2, y2), fill=dark, width=3)
    # Body.
    draw.polygon([(body_l + 30, top), (body_r - 30, top), (body_r, top + 60), (body_r, hem), (body_l, hem), (body_l, top + 60)],
                 fill=color, outline=dark)
    # Roll neck with vertical ribs.
    draw.rounded_rectangle((cx - 85, top - 60, cx + 85, top + 14), radius=14, fill=color, outline=dark, width=3)
    for x in range(int(cx - 70), int(cx + 71), 14):
        draw.line((x, top - 52, x, top + 6), fill=shade, width=3)
    # Cable-knit columns down the body.
    for x in range(int(body_l + 50), int(body_r - 30), 50):
        for y in range(int(top + 40), int(hem - 70), 28):
            draw.line((x, y, x + 12, y + 14), fill=shade, width=3)
            draw.line((x + 12, y + 14, x, y + 28), fill=shade, width=3)
    # Ribbed hem band.
    draw.line((body_l, hem - 48, body_r, hem - 48), fill=dark, width=3)
    for x in range(int(body_l + 10), int(body_r), 12):
        draw.line((x, hem - 44, x, hem - 4), fill=shade, width=3)


def draw_jeans(draw: ImageDraw.ImageDraw, color, cx=450, top=200, w=380, h=720):
    """Five-pocket denim jeans seen from the front: belt loops, fly, curved pockets, rivets, orange topstitching."""
    waist_l, waist_r = cx - w / 2, cx + w / 2
    hip_y = top + h * 0.26
    ankle_y = top + h
    shade = tuple(max(0, c - 40) for c in color)
    light = tuple(min(255, c + 22) for c in color)
    stitch = (214, 150, 66)  # the orange thread jeans are known for

    # Tapered legs joined at the crotch.
    draw.polygon([(waist_l, top), (waist_r, top), (waist_r + 14, hip_y), (cx + w * 0.42, ankle_y),
                  (cx + w * 0.10, ankle_y), (cx, hip_y + 60), (cx - w * 0.10, ankle_y),
                  (cx - w * 0.42, ankle_y), (waist_l - 14, hip_y)], fill=color, outline=shade)
    # Faded denim wash down the thighs.
    for side in (-1, 1):
        x = cx + side * w * 0.24
        draw.ellipse((x - 34, hip_y + 40, x + 34, hip_y + 330), fill=light)
    # Waistband, belt loops and button.
    draw.rectangle((waist_l, top, waist_r, top + 34), outline=shade, width=3)
    draw.line((waist_l, top + 30, waist_r, top + 30), fill=stitch, width=2)
    for x in (waist_l + 40, cx - 70, cx + 70, waist_r - 40):
        draw.rectangle((x - 7, top - 6, x + 7, top + 40), fill=color, outline=shade, width=2)
    draw.ellipse((cx - 11, top + 6, cx + 11, top + 28), fill=(170, 150, 110), outline=(110, 95, 70), width=2)
    # Fly and the two curved front pockets with rivets.
    draw.line((cx, top + 34, cx, hip_y + 60), fill=shade, width=3)
    draw.arc((cx - 2, top + 34, cx + 70, hip_y + 50), 20, 100, fill=stitch, width=3)
    for side in (-1, 1):
        x_out = waist_l if side == -1 else waist_r
        box = (min(x_out, x_out - side * 150), top - 50, max(x_out, x_out - side * 150), top + 150)
        draw.arc(box, 0 if side == -1 else 90, 90 if side == -1 else 180, fill=stitch, width=4)
        draw.ellipse((x_out - side * 22 - 6, top + 44, x_out - side * 22 + 6, top + 56), fill=(184, 115, 51))
    # Orange topstitching down the outer seams and at the hems.
    for side in (-1, 1):
        draw.line((cx + side * (w / 2 + 8), hip_y, cx + side * w * 0.40, ankle_y - 4), fill=stitch, width=2)
        draw.line((cx + side * w * 0.11, ankle_y - 14, cx + side * w * 0.41, ankle_y - 14), fill=stitch, width=2)


def label_card(lines: list[tuple[str, int, bool]], size=(700, 500)) -> Image.Image:
    """A plain care-label card: a list of (text, size, bold) lines, top to bottom."""
    img = Image.new("RGB", size, LABEL_BG)
    draw = ImageDraw.Draw(img)
    draw.rectangle((0, 0, size[0] - 1, size[1] - 1), outline=(190, 185, 175), width=6)
    y = 50
    for text, fsize, bold in lines:
        f = font(fsize, bold)
        draw.text((50, y), text, fill=(35, 32, 28), font=f)
        y += int(fsize * 1.6)
    # A couple of generic care-symbol glyphs (wash tub, no-bleach triangle) so it reads as a tag.
    draw.rounded_rectangle((500, 360, 580, 410), radius=8, outline=(80, 80, 80), width=4)
    draw.line((500, 410, 580, 360), fill=(80, 80, 80), width=4)  # dryer: circle in square, simplified
    draw.polygon([(500, 440), (580, 440), (540, 370)], outline=(80, 80, 80), width=4)  # no-bleach triangle
    return img


GARMENTS = [
    {
        "slug": "sweater",
        "draw": draw_sweater,
        "color": (124, 38, 38),  # red wool sweater
        "label": [
            ("KNIT SWEATER", 30, True),
            ("70% WOOL", 34, False),
            ("30% POLYAMIDE", 34, False),
            ("", 20, False),
            ("Machine wash cold", 26, False),
            ("Do not bleach", 26, False),
            ("Dry flat", 26, False),
        ],
    },
    {
        "slug": "tshirt",
        "draw": draw_tshirt,
        "color": (64, 102, 74),  # forest green cotton tee (distinct from the fabric background)
        "label": [
            ("CARE INSTRUCTIONS", 30, True),
            ("100% COTTON", 34, False),
            ("", 20, False),
            ("Machine wash warm", 26, False),
            ("Tumble dry low", 26, False),
            ("Iron medium heat", 26, False),
        ],
    },
    {
        "slug": "jeans",
        "draw": draw_jeans,
        "color": (54, 71, 106),  # indigo jeans
        "label": [
            ("STRETCH DENIM JEANS", 30, True),
            ("98% COTTON", 34, False),
            ("2% ELASTANE", 34, False),
            ("", 20, False),
            ("Machine wash cold", 26, False),
            ("inside out", 26, False),
            ("Do not bleach", 26, False),
        ],
    },
]


def main():
    for g in GARMENTS:
        img, draw = garment_canvas()
        g["draw"](draw, g["color"])
        save(img, f"{g['slug']}.jpg")
        save(label_card(g["label"]), f"{g['slug']}_label.jpg")


if __name__ == "__main__":
    main()
