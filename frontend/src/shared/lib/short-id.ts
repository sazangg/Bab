/** Truncates an id to its first `length` characters (default 8) for compact display. */
export function shortId(value: string | null | undefined, length = 8) {
  return value ? value.slice(0, length) : "-";
}
