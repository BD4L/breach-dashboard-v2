import colors from "open-props/src/colors";

// Build-time endpoint: the browser icon follows the same pack as the CSS theme.
export function GET() {
  return new Response(
    `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 40 40"><rect width="40" height="40" rx="5" fill="${colors["--teal-10"]}"/><path d="M11 10h12a6 6 0 0 1 0 12H11m0-6h14a6 6 0 0 1 0 12H11V10" fill="none" stroke="${colors["--gray-0"]}" stroke-width="2"/></svg>`,
    { headers: { "Content-Type": "image/svg+xml" } },
  );
}
