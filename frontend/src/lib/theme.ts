// Public Anthropic site colors observed September 5, 2026.
// Shared by the static HTML, CSS custom properties, and generated favicon.
export const brand = {
  paper: "#faf9f5",
  canvas: "#f0eee6",
  ink: "#141413",
} as const;

export const brandVariables = Object.entries(brand)
  .map(([name, value]) => `--brand-${name}:${value}`)
  .join(";");
