# Layer Lab: Design Notes

## Direction
Editorial and calm, like a well-made wool coat: warm neutrals, one rust accent, lots of space,
a serif for headings. The data (clo bars, timeline) should feel like part of the design, not a dashboard.

## Tokens (in `static/style.css`)
| Token | Light | Dark | Use |
|---|---|---|---|
| `--bg` | `#f4f0e8` oat | `#151412` | page |
| `--surface` | `#fffdf9` | `#1e1c1a` | cards |
| `--ink` | `#1e1c19` | `#ede8e0` | text |
| `--accent` | `#b5543a` rust | `#d9774f` | send button, tool names, selection |
| `--cold` / `--warm` | `#3f6c8c` / `#c98b2b` | `#7fa7c6` / `#e0a94f` | warmth bars, weather |

Fonts: **Fraunces** (headings) + **Inter** (text), from Google Fonts.
Dark mode follows the system setting and can be forced with `data-theme="dark"` on `<html>`.

## Inspiration and what to take from each
| Source | Use it for |
|---|---|
| [godly.website](https://godly.website), [awwwards.com](https://www.awwwards.com) | Motion ideas: gentle hover lifts, the day timeline revealing segment by segment |
| [minimal.gallery](https://minimal.gallery), [land-book.com](https://land-book.com), [onepagelove.com](https://onepagelove.com) | Whitespace, the intro/empty state, card layout |
| [dark.design](https://www.dark.design), [darkmodedesign.com](https://www.darkmodedesign.com) | Checking the dark palette: contrast, no pure black, softer accents |
| [fontpair.co](https://www.fontpair.co) | Font pairing (currently Fraunces + Inter) |
| [uigradients.com](https://uigradients.com) | A header gradient that changes with the weather: cold, rain, sun |
| [lottiefiles.com](https://lottiefiles.com) | Small weather animations (rain, snow, wind) in the day panel. Load `lottie-web` from cdnjs, save the JSON files in `static/`, check each animation's license |
| [mockupworld.co](https://mockupworld.co) | Device mockups for README screenshots |
| [latent-spaces/brag](https://github.com/latent-spaces/brag) | A short launch video of the finished app for the README (Claude Code skill; needs Node 22+ and FFmpeg) |

## Motion (anime.js)
anime.js v4 is loaded from cdnjs in `index.html`. The helpers in `static/app.js` are `enter()`
(fade and rise with a stagger), `growBars()` (warmth bars grow from the left) and `countUp()` (clo numbers).
They run only when content changes, and not at all with reduced motion or if the CDN fails.
Currently animated: chat messages and tool calls, the day timeline, the outfit pieces and clo values, the closet on first load.

## Component references (ideas, not code)
[reactbits.dev](https://reactbits.dev) and [originkit.dev](https://www.originkit.dev) are React/Framer component
libraries. Our app is plain HTML served by Python with no build step, so we don't install them; we pick an
effect we like and rebuild it with anime.js and CSS. Good candidates:
- a split-text reveal for the intro heading
- a soft animated gradient behind the header that follows the weather (cold / rain / mild)
- a subtle spotlight or tilt on closet cards on hover

## Diagrams
`docs/architecture.svg` follows [diagram-design](https://github.com/cathrynlavery/diagram-design)'s architecture type,
skinned with the tokens above: one accent (the agent loop), right-angle connectors, labels on masks, legend strip at the bottom.
Regenerate it with `python3 docs/make_architecture.py` after changing that script.

## Rules
- Works at phone width: one column, 16px side padding, no sideways scrolling.
- Tool calls stay visible above each answer (course requirement), collapsed by default.
- Every color comes from a token; check both themes after any change.
- Animations stay subtle and respect `prefers-reduced-motion`.
