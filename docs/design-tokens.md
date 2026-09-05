# UI token pack

The dashboard uses **Open Props 1.7.23**, pinned in `frontend/package.json` and bundled by Astro from npm. The official package supplies color palettes, typography scales, spacing, border widths, radii, shadows, easing, duration, and stacking layers. No browser request to a token CDN is required. [Open Props documentation](https://open-props.style/)

`frontend/src/styles/tokens.css` selects the pack values and gives them application roles. `dashboard.css` consumes those roles. Change theme decisions in `tokens.css`, rather than assigning new colors or sizes in individual components.

| Role | Pack mapping |
| --- | --- |
| Page / surface | Gray 1 / Gray 0 |
| Primary / secondary text | Gray 9 / Gray 7 |
| Selected row | Teal 0 |
| Action / hover | Teal 10 / Teal 11 |
| Success | Teal 10 text on Teal 0 |
| Warning | Orange 10 text on Orange 0 |
| Failure | Red 9 text on Red 0 |
| Metadata / working text / body | 12 / 14 / 16 px at the default root size |
| Borders / focus | Pack 1 px / 2 px |
| Control / panel radius | Pack radius 2 (5 px) |
| Interaction timing | Pack quick 2 (120 ms), moderate 1 (180 ms), ease-out 3 |

The 14 px working-text size is a documented midpoint of the pack's 12 px and 16 px steps. The spacing aliases use pack steps, with 12 px and 40 px composed from adjacent steps. Font families remain the locally bundled DM Sans and Newsreader from the approved interface, with pack fallbacks. Root-relative sizes support browser text scaling.

The existing layout, column behaviors, source reports, and evidence navigation remain intact. Structural geometry such as column proportions, responsive breakpoints, and logo paths is not a color/typography token. Do not shrink metadata below the 12 px role to fit a layout; change wrapping or responsive placement instead. Mobile form text uses 16 px and touch controls use 44 px.

The favicon and browser theme color use the same package values during the static build. They introduce no backend process.

## Contrast verification

Calculated from the installed pack's sRGB values: primary text **14.63:1**, secondary text **7.76:1**, accent button text **6.63:1**, success **6.53:1**, warning **4.89:1**, and failure **5.10:1**. Control boundaries are **3.15:1** and the focus ring on the page is **4.50:1**. These are the explicit token pairs, not a claim of a complete accessibility audit; inspect actual component combinations when adding variants.
