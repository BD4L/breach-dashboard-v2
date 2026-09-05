import { brand } from "../lib/theme";

// Build-time endpoint: the browser icon follows the shared brand palette.
export function GET() {
  return new Response(
    `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 40 40"><rect width="40" height="40" rx="12" fill="${brand.ink}"/><path d="M13 9h10l5 5v17H13V9Zm10 0v6h5M17 21h7M17 26h7" fill="none" stroke="${brand.paper}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>`,
    { headers: { "Content-Type": "image/svg+xml" } },
  );
}
