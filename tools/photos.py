"""Image helpers for uploaded photos: validation, the garment's main color, and a small copy for the model."""

import base64
import io
from collections import Counter

from PIL import Image, ImageOps, UnidentifiedImageError

MODEL_MAX_SIDE = 1024  # plenty for reading a care label, and keeps model calls fast


class PhotoError(Exception):
    """A photo we can't use, with a message the user or model can act on."""


def open_image(data: bytes) -> Image.Image:
    try:
        img = Image.open(io.BytesIO(data))
        img.load()
    except (UnidentifiedImageError, OSError):
        raise PhotoError("That file isn't a photo we can read. Use a JPG or PNG "
                         "(on iPhone: Settings > Camera > Formats > Most Compatible).")
    return ImageOps.exif_transpose(img).convert("RGB")


def main_color(data: bytes) -> str:
    """Most common color of the garment as hex, ignoring the background.

    The background is guessed from the photo's border; pixels close to it are skipped.
    """
    img = open_image(data)
    img.thumbnail((96, 96))
    w, h = img.size
    px = img.load()
    border = [px[x, y] for x in range(w) for y in (0, h - 1)] + [px[x, y] for y in range(h) for x in (0, w - 1)]
    bg = tuple(sorted(c[i] for c in border)[len(border) // 2] for i in range(3))

    def far_from_bg(c):
        return sum((a - b) ** 2 for a, b in zip(c, bg)) > 40 ** 2

    garment = [px[x, y] for x in range(w) for y in range(h) if far_from_bg(px[x, y])]
    if len(garment) < w * h * 0.05:  # garment fills the frame, or matches the background
        garment = [px[x, y] for x in range(w) for y in range(h)]
    # Round to a coarse grid so similar shades count together, then average the winning bucket.
    buckets = Counter((r // 24, g // 24, b // 24) for r, g, b in garment)
    top = buckets.most_common(1)[0][0]
    members = [c for c in garment if (c[0] // 24, c[1] // 24, c[2] // 24) == top]
    avg = [round(sum(c[i] for c in members) / len(members)) for i in range(3)]
    return "#{:02x}{:02x}{:02x}".format(*avg)


def as_data_uri(data: bytes) -> str:
    """Downscaled JPEG data URI to send to the vision model."""
    img = open_image(data)
    img.thumbnail((MODEL_MAX_SIDE, MODEL_MAX_SIDE))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()
