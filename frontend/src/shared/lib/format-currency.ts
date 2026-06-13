/**
 * Formats a micro-cent / cent integer as a USD string with thousands separators and two
 * decimals (e.g. 123456 -> "$1,234.56"). One canonical money formatter for the app —
 * replaces the per-file copies that variously used toFixed(2) or toLocaleString().
 */
export function formatCents(value: number | null | undefined) {
  return `$${((value ?? 0) / 100).toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
}
