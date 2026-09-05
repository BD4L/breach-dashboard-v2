# UI token pack

The dashboard uses **Open Props 1.7.23**, pinned in `frontend/package.json` and bundled by Astro from npm. The official package supplies status palettes, typography scales, spacing, border widths, radii, shadows, easing, duration, and stacking layers. No browser request to a token CDN is required. [Open Props documentation](https://open-props.style/)

The user selected an **Anthropic-inspired** visual direction on September 5, 2026. The public site's observed colors are warm paper `#faf9f5`, cream canvas `#f0eee6`, and charcoal ink `#141413`. These three primitives live in `frontend/src/lib/theme.ts`; static HTML, CSS custom properties, the browser theme color, and the generated favicon share them. The design uses analogous locally bundled fonts, DM Sans and Newsreader. [Anthropic reference](https://www.anthropic.com/)

`frontend/src/styles/tokens.css` maps the pack and brand primitives to application roles. `dashboard.css` consumes those roles. Change theme decisions in these two theme sources, rather than assigning individual component colors or sizes.

| Role | Mapping |
| --- | --- |
| Page / surface | Brand canvas / paper |
| Primary / secondary text | Brand ink / 68% ink mixed with paper |
| Selected row | 6% ink mixed with paper |
| Action / hover | Ink / 85% ink mixed with paper |
| Success | Open Props Teal 10 on Teal 0 |
| Warning | Open Props Orange 10 on Orange 0 |
| Failure | Open Props Red 9 on Red 0 |
| Metadata / working text / body | 12 / 14 / 16 px at the default root size |
| Borders / focus | Pack 1 px / 2 px |
| Small / control / panel radius | 8 / 12 / 16 px from pack steps |
| Interaction timing | Pack quick 2 (120 ms), moderate 1 (180 ms), ease-out 3 |

The 14 px working-text size is the midpoint of the pack's 12 px and 16 px steps. Spacing aliases use pack steps, with 12 px and 40 px composed from adjacent steps. The 12 px control radius is pack radius 3 minus size 1. Root-relative sizes support browser text scaling.

The page title uses bold DM Sans; evidence and supporting section headings use Newsreader. Navigation and controls use charcoal. Status colors are reserved for source health and warnings. Decorative dots and timeline points are removed. Saved, Sources, and bookmark controls use line icons with accessible names and native hover titles. Primary views retain visible text; their repeated counts are omitted visually on mobile. Source-health icons retain visible status labels.

The existing review layout, report data, and evidence navigation remain intact. Structural geometry such as column proportions and responsive breakpoints is not a color/typography token. Do not shrink metadata below 12 px to fit a layout; change wrapping or responsive placement instead. Mobile form text uses 16 px and icon touch controls use 44 px. The static theme and icon generation introduce no backend process.

## Contrast verification

Calculated from the brand primitives, sRGB mixes, and installed status palettes: primary text on paper **17.50:1**, secondary text **6.23:1** on paper and **5.65:1** on canvas, success **6.53:1**, warning **4.89:1**, and failure **5.10:1** on their respective status backgrounds. Control boundaries are **3.44:1** against paper and **3.12:1** against canvas. The charcoal focus ring is **15.87:1** against the page. These are explicit token pairs, not a complete accessibility audit; inspect actual component combinations when adding variants.
