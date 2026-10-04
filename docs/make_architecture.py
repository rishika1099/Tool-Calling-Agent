"""Generates docs/architecture.svg. Run: python3 docs/make_architecture.py"""

from pathlib import Path

# Layer Lab architecture diagram, following diagram-design's architecture type:
# left-to-right flow, <=9 nodes, <=12 arrows, accent on the one focal node, orthogonal
# connectors, arrows before boxes, masked labels 6px off their stroke, 4px grid.
PAPER, PAPER2, SURFACE = "#f4f0e8", "#ebe4d6", "#fffdf9"
INK, MUTED, SOFT = "#1e1c19", "#6f6a62", "#8c857b"
ACCENT, ACCENT_TINT, LINK = "#b5543a", "#f6e7e0", "#3f6c8c"
SANS = "Inter, 'Helvetica Neue', Arial, sans-serif"
MONO = "ui-monospace, 'SF Mono', Menlo, Consolas, monospace"

def mono_w(text, size, track=0.06):
    return len(text) * size * (0.62 + track)

out = []
w = out.append
w(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 108 960 440" width="960" height="440" role="img" aria-labelledby="ll-arch-title ll-arch-desc">')
w('<title id="ll-arch-title">Layer Lab architecture</title>')
w('<desc id="ll-arch-desc">The browser page posts chat messages to FastAPI endpoints on Cloud Run. The run_agent loop sends the conversation and tool schemas to Gemini on Vertex AI, which returns tool calls. The loop runs tools, which read and write session state, read clothing warmth tables, and call Open-Meteo and the National Weather Service.</desc>')
w('<defs>')
for mid, color in (("ll-arrow", MUTED), ("ll-arrow-link", LINK)):
    w(f'<marker id="{mid}" viewBox="0 0 8 8" refX="8" refY="4" markerWidth="8" markerHeight="8" markerUnits="userSpaceOnUse" orient="auto"><path d="M0,0 L8,4 L0,8 Z" fill="{color}"/></marker>')
w('</defs>')
w(f'<rect y="108" width="960" height="440" rx="10" fill="{PAPER}"/>')

# Zone: everything that runs in the Cloud Run container.
w(f'<rect x="196" y="132" width="536" height="344" rx="8" fill="rgba(30,28,25,0.025)" stroke="rgba(30,28,25,0.16)" stroke-width="0.8" stroke-dasharray="4,3"/>')
zl = "CLOUD RUN · APP.PY"
w(f'<rect x="208" y="136" width="{mono_w(zl,7,0.14)+8:.0f}" height="12" rx="2" fill="{PAPER}"/>')
w(f'<text x="212" y="145" fill="{SOFT}" font-size="7" font-family="{MONO}" letter-spacing="0.14em">{zl}</text>')

def line(x1, y1, x2, y2, color=MUTED, dashed=False, marker="ll-arrow"):
    dash = ' stroke-dasharray="4,3"' if dashed else ""
    sw = "1" if dashed else "1.2"
    w(f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{color}" stroke-width="{sw}"{dash} marker-end="url(#{marker})"/>')

def label(text, cx=None, x=None, y=0, color=MUTED):
    width = round(mono_w(text, 8) + 8)
    width += (4 - width % 4) % 4
    left = x if x is not None else cx - width / 2
    w(f'<rect x="{left:.0f}" y="{y}" width="{width}" height="12" rx="2" fill="{PAPER}"/>')
    w(f'<text x="{left + width/2:.0f}" y="{y+9}" fill="{color}" font-size="8" font-family="{MONO}" letter-spacing="0.06em" text-anchor="middle">{text}</text>')

# Arrows first, so boxes sit on top.
line(160, 196, 228, 196);                    label("POST /CHAT", cx=194, y=178)
line(368, 196, 424, 196)
line(564, 185, 772, 185);                    label("PROMPT + TOOLS", cx=668, y=167)
line(772, 207, 564, 207, dashed=True);       label("TOOL CALLS", cx=668, y=213)
line(494, 228, 494, 292);                    label("RUN TOOL", x=504, y=254)
line(298, 228, 298, 292, dashed=True);       label("PANELS", x=308, y=254)
line(424, 324, 368, 324)
line(564, 324, 772, 324, color=LINK, marker="ll-arrow-link"); label("HTTPS, NO KEY", cx=668, y=306, color=LINK)
line(494, 356, 494, 404);                    label("CLO VALUES", x=504, y=374)

def node(x, y, wd, ht, tag, name, sub, fill=SURFACE, stroke=INK, tag_color=None):
    tag_color = tag_color or stroke
    w(f'<rect x="{x}" y="{y}" width="{wd}" height="{ht}" rx="6" fill="{fill}" stroke="{stroke}" stroke-width="1"/>')
    tw = round(mono_w(tag, 7, 0.14) + 8)
    w(f'<rect x="{x+12}" y="{y+10}" width="{tw}" height="12" rx="2" fill="none" stroke="{tag_color}" stroke-width="0.8"/>')
    w(f'<text x="{x+16}" y="{y+19}" fill="{tag_color}" font-size="7" font-family="{MONO}" letter-spacing="0.14em">{tag}</text>')
    ny = y + (38 if ht >= 64 else 36)
    w(f'<text x="{x+12}" y="{ny}" fill="{INK}" font-size="12" font-weight="600" font-family="{SANS}">{name}</text>')
    w(f'<text x="{x+12}" y="{ny+14}" fill="{MUTED}" font-size="9" font-family="{MONO}">{sub}</text>')

node(24, 164, 136, 64, "BROWSER", "Layer Lab page", "static/ · anime.js", stroke=MUTED)
node(228, 164, 140, 64, "FASTAPI", "Endpoints", "/chat · /upload")
node(424, 164, 140, 64, "HARNESS", "Agent loop", "run_agent()", fill=ACCENT_TINT, stroke=ACCENT)
node(228, 292, 140, 64, "STATE", "Session", "closet, plan, photos", fill=PAPER2, stroke=MUTED)
node(424, 292, 140, 64, "TOOLS · 11", "Warmth + outfit", "tools/*.py")
node(424, 404, 140, 56, "DATA", "Clo tables", "data/*.csv", fill=PAPER2, stroke=MUTED)
node(772, 164, 164, 64, "VERTEX AI", "Gemini", "gemini-3.5-flash-lite", stroke=LINK)
node(772, 292, 164, 64, "HTTP API", "Open-Meteo + NWS", "forecast · alerts", stroke=LINK)

# Legend strip along the bottom.
w(f'<line x1="24" y1="500" x2="936" y2="500" stroke="rgba(30,28,25,0.12)" stroke-width="0.8"/>')
x = 24
for kind, fill, stroke, text in (("box", ACCENT_TINT, ACCENT, "FOCAL: THE AGENT LOOP"), ("box", SURFACE, INK, "SERVICE"),
                                 ("box", PAPER2, MUTED, "STATE + DATA"), ("box", SURFACE, LINK, "EXTERNAL SERVICE"),
                                 ("dash", None, MUTED, "RETURN / READ-ONLY")):
    if kind == "box":
        w(f'<rect x="{x}" y="516" width="16" height="10" rx="2" fill="{fill}" stroke="{stroke}" stroke-width="1"/>')
    else:
        w(f'<line x1="{x}" y1="521" x2="{x+16}" y2="521" stroke="{stroke}" stroke-width="1" stroke-dasharray="4,3"/>')
    w(f'<text x="{x+24}" y="524" fill="{MUTED}" font-size="8" font-family="{MONO}" letter-spacing="0.08em">{text}</text>')
    x += 24 + mono_w(text, 8, 0.08) + 28
w('</svg>')
open(Path(__file__).parent / "architecture.svg", "w").write("\n".join(out))
print("wrote docs/architecture.svg")
