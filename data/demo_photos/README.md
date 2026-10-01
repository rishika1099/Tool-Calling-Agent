# Sample photos for `scan_garment`

Three garment + care-label pairs so graders can try `scan_garment` (`tools/wardrobe.py`)
without photographing their own clothes:

| Garment | Care label | Expected scan |
|---|---|---|
| `sweater.jpg` | `sweater_label.jpg` | sweater_thick, 70% wool / 30% polyamide (read from the label), red |
| `tshirt.jpg` | `tshirt_label.jpg` | t_shirt, 100% cotton, green |
| `jeans.jpg` | `jeans_label.jpg` | jeans, 98% cotton / 2% elastane, indigo |

These are drawn with Pillow (`make_demo_photos.py`), not real photos: a flat garment silhouette
on a plain background (the same "lay it on a bed or floor" framing the onboarding flow asks for)
and a printed care label, which is enough for Gemini vision to return `is_clothing`, a
`garment_type`, and a fiber mix read from the label (`materials_source: "label"`). The main color
is still measured from the pixels by `tools/photos.main_color`, same as a real photo.

**Try it:**
1. In the running app, use the composer's attach button to upload a garment photo, then its
   label photo, and ask "scan this sweater" — or:
2. `curl -F session_id=demo -F file=@data/demo_photos/sweater.jpg http://localhost:8000/upload`
   to get a `photo_id`, repeat for the label, then `POST /wardrobe/scan` with both ids.

Regenerate after changing the drawing code: `python3 data/demo_photos/make_demo_photos.py`.
