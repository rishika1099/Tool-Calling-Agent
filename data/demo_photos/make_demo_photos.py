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


def draw_sweater(draw: ImageDraw.ImageDraw, color, cx=450, top=240, w=480, h=600):
    draw_tshirt(draw, color, cx, top, w, h)
    # Ribbed hem and cuffs: a few darker horizontal lines near the bottom.
    shade = tuple(max(0, c - 35) for c in color)
    for y in range(top + h - 30, top + h, 6):
        draw.line((cx - w * 0.42, y, cx + w * 0.42, y), fill=shade, width=2)


def draw_jeans(draw: ImageDraw.ImageDraw, color, cx=450, top=220, w=380, h=680):
    waist_l, waist_r = cx - w / 2, cx + w / 2
    hip_y = top + h * 0.22
    ankle_y = top + h
    gap = w * 0.08  # inseam gap between the legs
    shade = tuple(max(0, c - 40) for c in color)

    # Waistband/hip block, full width.
    draw.polygon([(waist_l, top), (waist_r, top), (waist_r + 10, hip_y), (waist_l - 10, hip_y)],
                 fill=color, outline=shade)
    # Two straight leg panels hanging from the hip block down to the ankle hem.
    draw.rectangle((waist_l - 10, hip_y, cx - gap / 2, ankle_y), fill=color, outline=shade)
    draw.rectangle((cx + gap / 2, hip_y, waist_r + 10, ankle_y), fill=color, outline=shade)

    # Topstitching and a back pocket, in a lighter thread color.
    stitch = (235, 215, 120)
    draw.line((waist_l, top + 20, waist_r, top + 20), fill=stitch, width=3)
    draw.rectangle((cx + gap / 2 + 20, hip_y + 30, cx + gap / 2 + 100, hip_y + 110), outline=stitch, width=3)


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
            ("CARE INSTRUCTIONS", 30, True),
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
            ("CARE INSTRUCTIONS", 30, True),
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
