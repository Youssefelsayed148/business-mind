"use client";

import { Button } from "@/lib/ui";

import type { Paged } from "./paging";

/** Previous / next for a client-side paged list. Renders nothing when one page is enough. */
export function Pager({
  paged,
  onPage,
  noun,
}: {
  paged: Paged<unknown>;
  onPage: (page: number) => void;
  noun: string;
}) {
  if (paged.pageCount <= 1) return null;
  return (
    <nav className="staff-many-pager" aria-label={`${noun} pages`}>
      <Button
        variant="quiet"
        disabled={paged.page <= 1}
        onClick={() => onPage(paged.page - 1)}
        data-testid="pager-prev"
      >
        Previous
      </Button>
      <span data-testid="pager-status" aria-live="polite">
        {paged.from} to {paged.to} of {paged.total} (page {paged.page} of{" "}
        {paged.pageCount})
      </span>
      <Button
        variant="quiet"
        disabled={paged.page >= paged.pageCount}
        onClick={() => onPage(paged.page + 1)}
        data-testid="pager-next"
      >
        Next
      </Button>
    </nav>
  );
}
