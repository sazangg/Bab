export function resolveAssetUrl(url: string): string | null {
  // Defense in depth alongside the backend logo-url validator: only ever hand an
  // http(s) (or app-relative) URL to <img src>, never javascript:/data: schemes.
  if (/^https?:\/\//i.test(url)) return url;
  if (url.startsWith("//")) return null;
  if (!url.startsWith("/")) return null;

  const apiBaseUrl = import.meta.env.VITE_BAB_API_URL as string | undefined;
  return apiBaseUrl?.trim() ? new URL(url, apiBaseUrl).toString() : url;
}
