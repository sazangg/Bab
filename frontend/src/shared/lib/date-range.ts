export type DateRange = { startAt?: string; endAt?: string; error?: string };

/** Converts a `yyyy-mm-dd` date string + a time-of-day into an ISO boundary, or undefined. */
export function toDateBoundary(value: string, time: string) {
  if (!value) return undefined;
  const date = new Date(`${value}T${time}`);
  return Number.isNaN(date.getTime()) ? undefined : date.toISOString();
}

/**
 * Builds an inclusive ISO date range (start at 00:00:00, end at 23:59:59) from two date
 * inputs, validating each boundary and the ordering. Returns `{ error }` on invalid input.
 */
export function buildDateRange(startDate: string, endDate: string): DateRange {
  const startAt = toDateBoundary(startDate, "00:00:00");
  const endAt = toDateBoundary(endDate, "23:59:59");
  if (startDate && !startAt) return { error: "The start date is invalid." };
  if (endDate && !endAt) return { error: "The end date is invalid." };
  if (startAt && endAt && startAt > endAt) {
    return { error: "The start date must be before the end date." };
  }
  return { startAt, endAt };
}
