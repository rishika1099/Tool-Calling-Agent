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

## Rules
- Works at phone width: one column, 16px side padding, no sideways scrolling.
- Tool calls stay visible above each answer (course requirement), collapsed by default.
- Every color comes from a token; check both themes after any change.
- Animations stay subtle and respect `prefers-reduced-motion`.
