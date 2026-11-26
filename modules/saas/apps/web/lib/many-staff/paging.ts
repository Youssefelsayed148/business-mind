/** Client-side paging for Many lists that answer everything at once. Pure. */

export const PAGE_SIZE = 50;

export interface Paged<T> {
  rows: T[];
  page: number;
  pageCount: number;
  total: number;
  /** 1-based position of the first and last row shown (0 when empty). */
  from: number;
  to: number;
}

/** The slice for `page` (1-based); an out-of-range page is clamped. */
export function paginate<T>(
  items: T[],
  page: number,
  size: number = PAGE_SIZE,
): Paged<T> {
  const total = items.length;
  const pageCount = Math.max(1, Math.ceil(total / size));
  const safe = Math.min(Math.max(1, Math.floor(page) || 1), pageCount);
  const start = (safe - 1) * size;
  const rows = items.slice(start, start + size);
  return {
    rows,
    page: safe,
    pageCount,
    total,
    from: rows.length ? start + 1 : 0,
    to: start + rows.length,
  };
}
