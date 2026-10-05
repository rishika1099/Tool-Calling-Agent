# Layer Lab: Design Notes

## Direction
A live sky behind frosted-glass panels. The weather is the backdrop: clear and blue on warm days,
paler when it's cold, heavy slate clouds with rain or snow falling when the forecast says so, and a
starry night sky (with the whole page in its night colors) once the sun has set in New York. On top: editorial type (Fraunces, variable weight) and a warm orange accent
that stands out against the blue.

## Tokens (in `static/style.css`)
| Token | Day | Night (`data-theme="dark"`, set from real sunrise/sunset) | Use |
|---|---|---|---|
| `--ink` | `#0e1a2b` | `#eef2f8` | text |
| `--glass` / `--glass-strong` | white 70% / 88% | navy 60% / 80% | panels, inputs |
| `--accent` | `#e0572f` | `#ff8a5c` | send button, focus, numbering |
| `--cold` / `--cool` / `--warm` / `--hot` | blue to orange | lighter versions | thermal scale for warmth |

Fonts: **Fraunces** (display, variable `wght`/`opsz`/`SOFT`), **Inter** (text), **Geist Mono** (numbers, tool names).

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

## Motion and effects
anime.js v4 (cdnjs) drives everything except the sky. Effects are plain-JS versions of components from
[reactbits.dev](https://reactbits.dev) and [originkit.dev](https://www.originkit.dev), which are React
libraries; we have no build step, so we rebuild instead of installing.

| Effect | Where | Based on |
|---|---|---|
| Intro: a bedroom window onto the live sky, curtains that part, zoom through the window | `#portal` | motionsites.ai **Gateway Portal** (reimagined as a bedroom window) |
| Live cloud sky, weather-driven, pointer wind and parallax | `static/sky.js` | Originkit **Cloud Sky** (its WebGL shader, ported unchanged) |
| Rain and snow particles | `static/sky.js` | our own, on a 2D canvas over the clouds |
| Heading letters get heavier near the pointer | hero | reactbits **Variable Proximity** |
| Rotating phrase ("walk to class", "first snow"...) | hero | reactbits **Rotating Text** |
| Blur-in answer text, word by word | chat | reactbits **Blur Text** |
| Outfit suggestions that expand on focus | "Your layers" | reactbits **FlexCarousel** (`liquid`, `rise`, `focusOnClick`, `captions`) |
| Spotlight and 3D tilt on cards | panels, prompts, closet | reactbits **Spotlight Card**, **Tilted Card** |
| Sparks on send | composer | reactbits **Click Spark** |
| Sliding thumb with a spring | cold-sensitivity control | |
| Layers stacking inside out, thermometers filling, numbers counting up | "Your layers" | |
| Day ribbon drawing left to right | "Your day" | |

Everything respects `prefers-reduced-motion` (the sky draws one still frame). The sky falls back to a
gradient without WebGL and renders at 60% resolution to stay light.

## Diagrams
`docs/architecture.svg` follows [diagram-design](https://github.com/cathrynlavery/diagram-design)'s architecture type,
skinned with the tokens above: one accent (the agent loop), right-angle connectors, labels on masks, legend strip at the bottom.
Regenerate it with `python3 docs/make_architecture.py` after changing that script.

## Rules
- Works at phone width: one column, 16px side padding, no sideways scrolling.
- Tool calls stay visible above each answer (course requirement), collapsed by default.
- Every color comes from a token; check both themes after any change.
- Animations stay subtle and respect `prefers-reduced-motion`.
