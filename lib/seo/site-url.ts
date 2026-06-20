// Absolute site origin for surfaces that can't ride layout.tsx's metadataBase.
// Metadata objects resolve relative URLs against metadataBase automatically;
// JSON-LD string payloads and sitemap entries need the absolute form spelled
// out. Mirror of the metadataBase literal in app/layout.tsx — keep in sync (a
// single shared const across layout/sitemap/json-ld is a later cleanup; CTK-078
// owns layout.tsx, so this slice doesn't refactor it).
export const SITE_URL = 'https://coralticker.com';
